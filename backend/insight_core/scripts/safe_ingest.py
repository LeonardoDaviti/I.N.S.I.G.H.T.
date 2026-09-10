# backend/insight_core/scripts/safe_ingest.py
"""
Safe ingestion script that only fetches from sources that need updating.

Filtering Logic:
- Sources in backoff after repeated failures → SKIP (unless triggered manually)
- Sources with 0 posts (newly added) → FETCH
- Sources with latest fetch older than SAFE_INGEST_SKIP_THRESHOLD_HOURS → FETCH
- Sources with recent fetches inside that window → SKIP

This prevents redundant fetching during development iterations.

Usage: python backend/insight_core/scripts/safe_ingest.py
"""
import sys
from pathlib import Path
import contextlib
import random
import time
import os
import urllib.parse
from datetime import datetime, timedelta, timezone

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import asyncio
import psycopg
from psycopg import Cursor
from insight_core.db.ensure_db import ensure_database
from insight_core.db.repo_posts import PostsRepository
from insight_core.services.entity_memory_service import EntityMemoryService
from insight_core.services.event_memory_service import EventMemoryService
from insight_core.services.sources_service import SourcesService
from insight_core.services.operations_service import OperationsService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.connectors import create_connector
from insight_core.utils.url_normalization import extract_url_host
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

DEBUG_MODE = False  # DEBUG here also puts the API at DEBUG level (bridge imports this module)
setup_logging(debug_mode=DEBUG_MODE)
logger = get_component_logger("safe_ingest")

# Configuration
SKIP_THRESHOLD_HOURS = int(os.getenv("SAFE_INGEST_SKIP_THRESHOLD_HOURS", "20"))

# yt-dlp is the single most expensive thing a cycle does, and the only one bounded by a
# remote party's patience rather than by us: each channel is a subprocess doing JS player
# extraction, the budget is 2-wide, and it is the floor the whole cycle sits on. Off, the
# 32 YouTube sources are skipped entirely and a cycle is pure HTTP.
YTDLP_ENABLED = str(os.getenv("INSIGHT_YTDLP_ENABLED", "1")).strip().lower() not in {
    "0", "false", "no", "off",
}

# YouTube runs on its own, much slower cadence. Channels publish on the order of ten videos
# a month, so re-scanning every 20 hours spends the most expensive budget in the system
# re-reading a list that has not changed. Weekly rather than monthly deliberately: a month
# of backlog does not fit in one fetch window (see YOUTUBE_MIN_POSTS_PER_FETCH), and a
# month-old "latest video" is not news.
YOUTUBE_SKIP_THRESHOLD_HOURS = float(os.getenv("SAFE_INGEST_YOUTUBE_SKIP_THRESHOLD_HOURS", "168"))

# The backlog guard from the adaptive-cadence spec, applied here because this is the first
# place a cadence outruns a fetch window. The YouTube platform default is 5 posts per fetch,
# sized for a 20-hour cycle. At 168 hours any channel publishing more than 5 videos a week
# would silently lose the overflow - the fetch would succeed and the posts would simply
# never exist. A floor of 15 covers ~2/day, comfortably above what these channels publish.
YOUTUBE_MIN_POSTS_PER_FETCH = int(os.getenv("SAFE_INGEST_YOUTUBE_MIN_POSTS", "15"))

# Platforms served by SourceFetchService. Everything else goes through a shared
# connector object (in practice: telegram) and MUST stay sequential - see FETCH below.
LIVE_FETCH_PLATFORMS = {"rss", "reddit", "youtube"}

# Conservative default. The ceiling that matters is not this number but the default
# asyncio executor (min(32, cpu_count + 4)): SourceFetchService does all of its network
# I/O through asyncio.to_thread, so anything above that queues invisibly and the
# semaphore stops meaning anything.
MAX_FETCH_CONCURRENCY = max(1, int(os.getenv("SAFE_INGEST_MAX_CONCURRENCY", "8")))

# yt-dlp needs its own, much smaller budget: YouTube's bot detection is per-IP, not
# per-channel, and 2026-07-23 we spent 7.5 minutes on a single video retrying against
# "Sign in to confirm you're not a bot". Firing 22 channels at once guarantees that state.
MAX_YTDLP_CONCURRENCY = max(1, int(os.getenv("SAFE_INGEST_YTDLP_CONCURRENCY", "2")))

# ...and a minimum gap between two yt-dlp starts on top of that budget. youtube.com is one
# host key, so yt-dlp sources deliberately skip the per-host limiter - which is also the only
# place fetch_delay_seconds is consulted. Without this the 22 configured channels went from
# "one at a time, spaced by fetch_delay" to "two at a time, back to back for the whole
# block", i.e. exactly the traffic shape that produced the 2026-07-23 bot-detection episode.
# Spacing STARTS rather than holding a lock, so the 2-slot budget stays usable.
YTDLP_MIN_START_INTERVAL_SECONDS = float(os.getenv("SAFE_INGEST_YTDLP_MIN_INTERVAL", "3"))

# Hosts that need more spacing than the source's own fetch_delay_seconds. Derived from the
# host sets and delays SourceFetchService already owns rather than retyped: the hardcoded
# pair {"nitter.net", "tg.i-c-a.su"} covered 2 of the 5 hosts in those sets, so telegram.local
# - which is every self-hosted Telegram source, 35 of them on the deployed instance - got a
# 0s floor. That bridge already answers "Too many requests" under a SEQUENTIAL cycle, so a
# 0s floor under a concurrent one is the one combination guaranteed to make it worse.
HOST_MIN_INTERVAL_OVERRIDES = {
    **{host: float(SourceFetchService.TELEGRAM_PAGE_DELAY_SECONDS)
       for host in SourceFetchService.TELEGRAM_HOSTS},
    **{host: float(SourceFetchService.NITTER_PAGE_DELAY_SECONDS)
       for host in SourceFetchService.NITTER_HOSTS},
}

# Dead-source backoff: 15m, 30m, 1h, 2h, 4h, 8h, 16h, 24h, 24h...
BACKOFF_BASE_MINUTES = int(os.getenv("SAFE_INGEST_BACKOFF_BASE_MINUTES", "15"))
BACKOFF_MAX_HOURS = int(os.getenv("SAFE_INGEST_BACKOFF_MAX_HOURS", "24"))

# Enrichment runs in chunks purely so it can report progress; the services themselves
# are happy with the whole batch.
ENRICH_CHUNK_SIZE = max(1, int(os.getenv("SAFE_INGEST_ENRICH_CHUNK_SIZE", "100")))

# Commit every N posts so a crash mid-save does not discard the whole cycle's writes.
# Deliberately small: repo_posts.upsert_post opens one writing SAVEPOINT per post (two on the
# rare external_id collision path - its lookup savepoint is read-only and so is never
# assigned an XID at all), and Postgres only caches 64 subtransaction ids per backend. Past
# that the backend's snapshot is marked suboverflowed and EVERY OTHER backend in the cluster
# - the API serving /api/posts, the briefing jobs - falls back to pg_subtrans lookups for as
# long as the transaction stays open, which here is the whole save phase. RELEASE SAVEPOINT
# does not hand the id back; only the top-level commit does, which is why this is a commit
# interval and not a savepoint-stack depth.
SAVE_COMMIT_BATCH = max(1, int(os.getenv("SAFE_INGEST_SAVE_COMMIT_BATCH", "20")))

# record_live_fetch re-inspects the source (for YouTube: a full unbounded yt-dlp channel
# dump per channel) right after we already fetched it. Kept on by default so archive
# metadata stays accurate, but an operator can switch it off when a cycle must be fast.
REFRESH_ARCHIVE_METADATA = os.getenv("SAFE_INGEST_REFRESH_ARCHIVE_METADATA", "1") != "0"


class _HostLimiter:
    """One in-flight request per host, spaced by the source's fetch_delay_seconds.

    The old loop did a global `await asyncio.sleep(fetch_delay)` between sources. Under
    asyncio.gather that sleep buys nothing - every task sleeps at the same time - while
    the real politeness need becomes acute, because sources cluster hard by host
    (12 of them are github.com, 10 reddit.com, 6 arxiv) and 38 hosts see a single
    request each. Spacing belongs per host, not per loop iteration.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_request_at: dict[str, float] = {}

    @staticmethod
    def host_key(source: dict) -> str:
        handle = source.get("handle_or_url") or ""
        # Only ask for a host when this is actually a URL. extract_url_host parses bare
        # handles as hosts - "@chan" -> "chan", "r/MachineLearning" -> "r" - which hands
        # nearly every handle source a private bucket and switches the limiter off for it.
        if "://" in handle:
            # extract_url_host, not a local urlparse: it applies HOST_ALIASES and strips
            # "www.", and it already computes posts.url_host for the rows this same script
            # writes. A private copy put www.reddit.com and old.reddit.com in different
            # buckets - splitting exactly the clusters this limiter exists to serialise.
            hostname = extract_url_host(handle)
            if hostname:
                return hostname
        # Bare handles (@channel, subreddit names) have no host; group them per platform
        # rather than letting them all share one bucket.
        return f"platform:{source.get('platform')}"

    @contextlib.asynccontextmanager
    async def slot(self, host: str, min_interval: float):
        min_interval = max(float(min_interval or 0), HOST_MIN_INTERVAL_OVERRIDES.get(host, 0.0))
        lock = self._locks.get(host)
        if lock is None:
            lock = self._locks[host] = asyncio.Lock()

        async with lock:
            last = self._last_request_at.get(host)
            if last is not None:
                wait = min_interval - (time.monotonic() - last)
                if wait > 0:
                    logger.debug("⏳ %s: waiting %.1fs for host spacing", host, wait)
                    await asyncio.sleep(wait)
            try:
                yield
            finally:
                self._last_request_at[host] = time.monotonic()


class _StartSpacer:
    """Minimum wall-clock gap between the *starts* of successive operations.

    Not a _HostLimiter: that holds its lock for the whole call, which would serialise the
    22 youtube.com channels into one at a time and undo MAX_YTDLP_CONCURRENCY. This only
    hands out start slots, so N calls may still overlap - they just cannot begin together.
    """

    def __init__(self, min_interval: float) -> None:
        self._min_interval = max(0.0, min_interval)
        self._lock = asyncio.Lock()
        self._next_start_at = 0.0

    async def wait(self) -> None:
        if not self._min_interval:
            return
        async with self._lock:
            now = time.monotonic()
            start_at = max(now, self._next_start_at)
            # Reserved before sleeping, so the next caller queues behind this slot rather
            # than racing for the same one once the lock is released.
            self._next_start_at = start_at + self._min_interval
        delay = start_at - time.monotonic()
        if delay > 0:
            logger.debug("⏳ yt-dlp: waiting %.1fs for start spacing", delay)
            await asyncio.sleep(delay)


def _interleave_by_host(sources: list[dict]) -> list[dict]:
    """Round-robin the fetch queue across hosts, keeping priority tiers in order.

    Ordering by (priority, handle_or_url) alone puts the ~32 youtube.com channels in one
    contiguous run and the ~12 github.com feeds in another, and asyncio.gather starts tasks
    in list order - so the first MAX_FETCH_CONCURRENCY tasks all want the same gate and the
    global budget stops meaning anything. Interleaving makes the tasks that start together
    mostly want *different* gates. Within a tier the input order is preserved per host, so
    priority still decides who goes first.
    """
    tiers: dict = {}
    for source in sources:
        tier = tiers.setdefault(source["settings"]["priority"], {})
        tier.setdefault(_HostLimiter.host_key(source), []).append(source)

    ordered: list[dict] = []
    for priority in sorted(tiers):
        buckets = tiers[priority]
        while buckets:
            for host in list(buckets):
                ordered.append(buckets[host].pop(0))
                if not buckets[host]:
                    del buckets[host]
    return ordered


def _failed_result(source: dict, error: str) -> dict:
    """A fetch result for a source that never produced one, so the cycle can still count it."""
    now = time.time()
    return {
        "source": source,
        "platform": source.get("platform"),
        "posts": [],
        "error": error,
        "started_at": now,
        "ended_at": now,
    }


# Detected once, here, rather than by catching AttributeError per call: backend/psycopg is a
# psql-shelling dev shim with no pq submodule (the image deletes it in favour of the real
# package) and insight_api_bridge imports this module at API startup, so the shim must not
# crash the import. Swallowing AttributeError at the call site instead would also swallow a
# genuine psycopg API move and silently disable the batch-rollback guard - the connection
# would report "not poisoned", the rollback would never run, and every later post in the run
# would fail 25P02 until the terminal commit raised and took the whole cycle's writes.
_PQ_INERROR = getattr(getattr(psycopg, "pq", None), "TransactionStatus", None)
_PQ_INERROR = getattr(_PQ_INERROR, "INERROR", None)
if _PQ_INERROR is None:
    logger.warning(
        "psycopg.pq.TransactionStatus.INERROR is unavailable - the aborted-transaction "
        "guard in the save loop is disabled (expected only under the backend/psycopg shim)"
    )


def _transaction_is_poisoned(conn) -> bool:
    """True when the connection sits in aborted-transaction state and accepts nothing."""
    if _PQ_INERROR is None:
        return False
    return conn.info.transaction_status == _PQ_INERROR


def get_source_post_stats(cur: Cursor, source_id: str) -> tuple[int, datetime | None]:
    """
    Get post count and latest fetch time for a source.

    Returns:
        (post_count, latest_fetched_at)
    """
    query = """
        SELECT
            COUNT(*) as post_count,
            MAX(fetched_at) as latest_fetched_at
        FROM posts
        WHERE source_id = %s
    """
    cur.execute(query, (source_id,))
    row = cur.fetchone()

    post_count = row[0] if row else 0
    latest_fetched_at = row[1] if row and row[1] else None

    return post_count, latest_fetched_at


def _backoff_state(source: dict) -> dict:
    """Read the backoff block written by _record_backoff.

    Deliberately a separate settings key from `ops`: OperationsService.record_source_status
    does a read-modify-write of `ops` across two connections, so a counter living there
    would be silently clobbered by concurrent status writes.
    """
    state = (source.get("settings") or {}).get("ingest_backoff")
    return state if isinstance(state, dict) else {}


def _next_retry_at(consecutive_failures: int, now: datetime) -> str:
    """Exponential backoff capped at BACKOFF_MAX_HOURS, jittered.

    Jitter matters: 73 sources are permanently failing, and without it they all wake up
    in the same second of every cycle.
    """
    # Jitter is applied to the CAPPED delay and only downward, so BACKOFF_MAX_HOURS is a
    # bound an operator can read as one. Jittering upward after the cap (0.85-1.15 of 24h)
    # parked a stuck source up to 27.6h; jittering before it leaves every source at the
    # ceiling landing on exactly 24h, which is the herd this exists to break up.
    delay_minutes = min(
        BACKOFF_BASE_MINUTES * (2 ** max(0, consecutive_failures - 1)),
        BACKOFF_MAX_HOURS * 60,
    ) * random.uniform(0.85, 1.0)
    return (now + timedelta(minutes=delay_minutes)).isoformat()


def should_fetch_source(cur: Cursor, source: dict, trigger: str = "manual") -> tuple[bool, str]:
    """
    Determine if a source should be fetched based on post history.

    Returns:
        (should_fetch: bool, reason: str)
    """
    source_id = source["id"]
    display_name = source["settings"].get("display_name") or source["handle_or_url"]
    is_youtube = source.get("platform") == "youtube"

    # Case -1: yt-dlp switched off. Not a failure and not backoff - the operator chose a
    # cycle without YouTube in it, so say so plainly rather than reporting these as skipped
    # for freshness.
    if is_youtube and not YTDLP_ENABLED:
        return False, "🚫 yt-dlp disabled (INSIGHT_YTDLP_ENABLED=0)"

    skip_threshold_hours = YOUTUBE_SKIP_THRESHOLD_HOURS if is_youtube else SKIP_THRESHOLD_HOURS

    # Case 0: dead source serving out a backoff window. 73 of 235 sources are in a
    # permanent error state and each one burns a full 30s timeout every single cycle.
    # A manual trigger always bypasses this - that is the operator's "try it now" button.
    if trigger != "manual":
        state = _backoff_state(source)
        next_retry_at = state.get("next_retry_at")
        if next_retry_at:
            try:
                retry_at = datetime.fromisoformat(next_retry_at)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                retry_at = None
            if retry_at and datetime.now(timezone.utc) < retry_at:
                failures = state.get("consecutive_failures") or 0
                return False, f"🚫 Backoff until {next_retry_at} ({failures} consecutive failures)"

    post_count, latest_fetched_at = get_source_post_stats(cur, source_id)

    # Case 1: No posts yet (newly added source)
    if post_count == 0:
        return True, "📦 New source (0 posts)"

    # Case 2: Has posts, check freshness
    if latest_fetched_at:
        now = datetime.now(timezone.utc)
        time_since_fetch = now - latest_fetched_at
        hours_since_fetch = time_since_fetch.total_seconds() / 3600

        if hours_since_fetch < skip_threshold_hours:
            return False, (
                f"⏭️  Recently fetched {hours_since_fetch:.1f}h ago ({post_count} posts, "
                f"{skip_threshold_hours:.0f}h cadence)"
            )
        else:
            return True, f"🔄 Stale data ({hours_since_fetch:.1f}h old, {post_count} posts)"

    # Case 3: Has posts but no fetched_at (shouldn't happen, but safe fallback)
    return True, f"⚠️  Unknown fetch time ({post_count} posts)"


async def _record_backoff(sources_service: SourcesService, source: dict, *, failed: bool) -> None:
    """Advance or clear the failure counter for one source.

    Only a fetch that *errored* advances the ladder. Every other outcome - including a fetch
    that answered with zero posts - clears it: an empty feed answered, it just had nothing
    new, and it burned no timeout.
    """
    state = _backoff_state(source)
    failures = int(state.get("consecutive_failures") or 0)
    now = datetime.now(timezone.utc)

    if failed:
        failures += 1
        payload = {
            "consecutive_failures": failures,
            "next_retry_at": _next_retry_at(failures, now),
            "last_error_at": now.isoformat(),
        }
    else:
        if not failures and not state.get("next_retry_at"):
            return  # Already clean - do not spend a connection saying so.
        payload = {
            "consecutive_failures": 0,
            "next_retry_at": None,
            "last_success_at": now.isoformat(),
        }

    try:
        await asyncio.to_thread(
            sources_service.merge_source_settings, source["id"], {"ingest_backoff": payload}
        )
        source.setdefault("settings", {})["ingest_backoff"] = {**state, **payload}
    except Exception as exc:
        logger.warning("Could not persist backoff state for %s: %s", source["handle_or_url"], exc)


async def _fetch_source(
    source: dict,
    *,
    fetch_service: SourceFetchService,
    operations_service: OperationsService,
    sources_service: SourcesService,
    trigger: str,
    semaphore: asyncio.Semaphore,
    ytdlp_semaphore: asyncio.Semaphore,
    ytdlp_spacer: _StartSpacer,
    host_limiter: _HostLimiter,
    connector=None,
) -> dict:
    """Fetch one source and record its status. Never raises.

    "Never raises" is a contract, not a courtesy: these coroutines run under asyncio.gather,
    so anything escaping one of them takes the whole cycle's fetch with it. That is why even
    reading source["settings"] happens inside the try.
    """
    settings = source.get("settings") or {}
    display_name = settings.get("display_name") or source.get("handle_or_url")
    priority = settings.get("priority")

    started_at = time.time()
    posts: list = []
    error: str | None = None

    try:
        max_posts = settings["max_posts_per_fetch"]
        # Gate order is load-bearing: the narrow gate (per-host lock, yt-dlp budget) is taken
        # BEFORE the global semaphore. Taken inside it - as this did originally - a run of
        # same-host sources parks all MAX_FETCH_CONCURRENCY slots on tasks that are merely
        # waiting for one host lock or for the 2-slot yt-dlp budget, nothing else can start,
        # and effective concurrency collapses to 1-2. Waiting for a narrow gate must never
        # cost a global slot. (_interleave_by_host attacks the same problem from the other
        # end; both are needed, since interleaving alone still stalls once enough same-host
        # tasks are in flight.)
        async with contextlib.AsyncExitStack() as gates:
            is_ytdlp = connector is None and fetch_service.classify_source(source) == "youtube_channel"
            if is_ytdlp:
                # Backlog guard for the weekly cadence. The stored default is 5, sized for a
                # 20-hour cycle; over 168 hours anything past the fifth video would be
                # dropped by a fetch that still reported success.
                max_posts = max(max_posts, YOUTUBE_MIN_POSTS_PER_FETCH)
                # No host lock on top of this: youtube.com is one host key, so the lock would
                # serialise all 32 channels instead of letting MAX_YTDLP_CONCURRENCY run.
                # The spacer supplies the politeness the host lock would have, without the
                # serialisation - see YTDLP_MIN_START_INTERVAL_SECONDS.
                await gates.enter_async_context(ytdlp_semaphore)
                await ytdlp_spacer.wait()
            elif connector is None:
                await gates.enter_async_context(
                    host_limiter.slot(_HostLimiter.host_key(source), settings["fetch_delay_seconds"])
                )
            await gates.enter_async_context(semaphore)

            logger.info(f"📥 [{priority}] Fetching up to {max_posts} posts from {display_name}")
            if connector is not None:
                posts = await connector.fetch_posts(source["handle_or_url"], limit=max_posts)
            elif is_ytdlp:
                # SourceFetchService.fetch_live_posts calls YouTubeService.fetch_live_posts
                # synchronously, and that shells out to yt-dlp - awaiting it would block the
                # whole event loop for minutes and silently serialise every other source.
                # Same call, moved off the loop and behind the yt-dlp budget.
                posts = await asyncio.to_thread(
                    fetch_service.youtube_service.fetch_live_posts,
                    source["handle_or_url"],
                    max_posts,
                )
            else:
                posts = await fetch_service.fetch_live_posts(source, limit=max_posts)
    except Exception as exc:
        error = str(exc)
        posts = []

    elapsed = time.time() - started_at

    if error is None:
        logger.info(f"✅ [{priority}] {display_name}: fetched {len(posts)} posts in {elapsed:.1f}s")
        status = "healthy" if posts else "empty"
        message = f"Fetched {len(posts)} posts"
    else:
        logger.error(f"❌ Failed to fetch from {source['handle_or_url']}: {error}")
        status = "error"
        message = error

    try:
        await asyncio.to_thread(
            operations_service.record_source_status,
            source["id"],
            # A fetch that raises nothing but returns nothing is not healthy - that is
            # exactly how a silently dead feed looks. Report it as such so the
            # Operations panel can surface it.
            status=status,
            message=message,
            trigger=trigger,
            fetched_posts=len(posts) if error is None else None,
        )
    except Exception as exc:
        logger.warning("Could not record status for %s: %s", source["handle_or_url"], exc)

    # An empty fetch is a successful answer and clears the ladder exactly like a non-empty
    # one. Skipping it here (the original `if status != "empty"`) left a recovered-but-quiet
    # feed parked at consecutive_failures=6 forever, so the next transient blip sent it
    # straight to a ~16h delay instead of restarting at 15 minutes.
    await _record_backoff(sources_service, source, failed=status == "error")

    return {
        "source": source,
        "platform": source["platform"],
        "posts": posts,
        "error": error,
        "started_at": started_at,
        "ended_at": started_at + elapsed,
    }


async def _record_connector_outage(
    operations_service: OperationsService,
    sources: list[dict],
    error: str,
    trigger: str,
) -> list[dict]:
    """Report the sources a connector-level failure never let us attempt.

    Their backoff ladder is deliberately NOT advanced: a shared connector fault (locked
    session, FloodWaitError) is no evidence that any individual channel is dead, and parking
    all of telegram for hours because one connect() failed would be its own outage.
    """
    results = []
    for source in sources:
        try:
            await asyncio.to_thread(
                operations_service.record_source_status,
                source["id"],
                status="error",
                message=f"Connector unavailable: {error}",
                trigger=trigger,
                fetched_posts=None,
            )
        except Exception as exc:
            logger.warning("Could not record status for %s: %s", source.get("handle_or_url"), exc)
        results.append(_failed_result(source, error))
    return results


async def safe_ingest_posts(trigger: str = "manual"):
    """Fetch and save posts only from sources that need updating."""

    # Start total timer
    total_start_time = time.time()
    platform_timings = {}

    # 0. Get database URL
    db_url = ensure_database()

    # 1. Get all sources with settings from database
    sources_service = SourcesService(db_url)
    operations_service = OperationsService(db_url)
    fetch_service = SourceFetchService(db_url)
    all_sources = sources_service.get_all_sources_with_settings()

    # Filter only enabled sources
    enabled_sources = [s for s in all_sources if s["enabled"]]

    if not enabled_sources:
        logger.warning("⚠️  No enabled sources found")
        return _empty_result()

    logger.info(f"📊 Found {len(enabled_sources)} enabled sources")

    # 2. Filter sources based on fetch history
    sources_to_fetch = []
    sources_to_skip = []
    backoff_skipped = 0

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for source in enabled_sources:
                should_fetch, reason = should_fetch_source(cur, source, trigger)
                display_name = source["settings"].get("display_name") or source["handle_or_url"]

                if should_fetch:
                    sources_to_fetch.append(source)
                    logger.info(f"✅ {display_name}: {reason}")
                else:
                    sources_to_skip.append(source)
                    if reason.startswith("🚫"):
                        backoff_skipped += 1
                    logger.info(f"⏭️  {display_name}: {reason}")

    # 3. Summary
    logger.info("=" * 60)
    logger.info(f"📥 Sources to fetch: {len(sources_to_fetch)}")
    logger.info(f"⏭️  Sources to skip:  {len(sources_to_skip)} ({backoff_skipped} in backoff)")
    logger.info("=" * 60)

    if not sources_to_fetch:
        logger.info("✨ All sources are up to date! Nothing to fetch.")
        return _empty_result(sources_backoff_skipped=backoff_skipped)

    # 4. Group by platform and sort by priority within each platform
    by_platform = {}
    for source in sources_to_fetch:
        platform = source["platform"]
        if platform not in by_platform:
            by_platform[platform] = []
        by_platform[platform].append(source)

    # Sort sources within each platform by priority (lower = first)
    for platform in by_platform:
        by_platform[platform].sort(key=lambda s: (
            s["settings"]["priority"],
            s["handle_or_url"]
        ))

    # Log priority order for each platform
    for platform, sources in by_platform.items():
        priority_info = [
            f"[{s['settings']['priority']}] {s['settings'].get('display_name') or s['handle_or_url']}"
            for s in sources
        ]
        logger.info(f"📋 {platform.upper()} priority order: {' → '.join(priority_info)}")

    # 5. Fetch. Live platforms run concurrently under a global semaphore plus a per-host
    #    limiter; connector platforms (telegram) stay strictly sequential because they
    #    share one Telethon client, one MTProto connection, one session file on disk, and
    #    a request_counter throttle whose read-modify-write has an `await` in the middle -
    #    parallelising them silently disables the throttle and earns a FloodWaitError on
    #    the account.
    all_posts = []
    failed_sources: list[dict] = []
    source_lookup = {source["id"]: source for source in sources_to_fetch}

    semaphore = asyncio.Semaphore(MAX_FETCH_CONCURRENCY)
    ytdlp_semaphore = asyncio.Semaphore(MAX_YTDLP_CONCURRENCY)
    ytdlp_spacer = _StartSpacer(YTDLP_MIN_START_INTERVAL_SECONDS)
    host_limiter = _HostLimiter()

    fetch_kwargs = {
        "fetch_service": fetch_service,
        "operations_service": operations_service,
        "sources_service": sources_service,
        "trigger": trigger,
        "semaphore": semaphore,
        "ytdlp_semaphore": ytdlp_semaphore,
        "ytdlp_spacer": ytdlp_spacer,
        "host_limiter": host_limiter,
    }

    live_sources = [
        source
        for platform, sources in by_platform.items()
        if platform in LIVE_FETCH_PLATFORMS
        for source in sources
    ]
    live_sources.sort(key=lambda s: (s["settings"]["priority"], s["handle_or_url"]))
    live_sources = _interleave_by_host(live_sources)

    connector_platforms = {
        platform: sources
        for platform, sources in by_platform.items()
        if platform not in LIVE_FETCH_PLATFORMS
    }

    async def run_live_sources() -> list[dict]:
        if not live_sources:
            return []
        logger.info(
            f"🚀 Fetching {len(live_sources)} live sources with concurrency "
            f"{MAX_FETCH_CONCURRENCY} (yt-dlp {MAX_YTDLP_CONCURRENCY})"
        )
        # _fetch_source is written never to raise, but "written never to" is not a guarantee
        # a whole cycle should rest on: without return_exceptions one unexpected error
        # discards every source fetched so far. Every returned exception is inspected below.
        results = await asyncio.gather(
            *(_fetch_source(s, **fetch_kwargs) for s in live_sources),
            return_exceptions=True,
        )
        collected: list[dict] = []
        for source, result in zip(live_sources, results):
            if isinstance(result, BaseException):
                logger.error(
                    "💥 Unhandled error fetching %s (cycle continues): %s",
                    source.get("handle_or_url"),
                    result,
                    exc_info=result,
                )
                collected.append(_failed_result(source, f"unhandled fetch error: {result}"))
            else:
                collected.append(result)
        return collected

    async def run_connector_platform(platform: str, sources: list[dict]) -> list[dict]:
        """Fetch one connector platform's sources sequentially. Never raises.

        create_connector / connect() / disconnect() all sat outside any try here, which put
        the whole cycle back on the exact failure this module exists to prevent: a locked or
        expired Telethon session raises about a second in, and every RSS/Reddit/YouTube post
        being fetched alongside it is thrown away. One platform's outage costs that platform.
        """
        results: list[dict] = []
        connector = None
        try:
            connector = create_connector(platform)
            if connector is None:
                # Returning [] here booked all 12 telegram sources as ingested - `succeeded =
                # attempted - len(failed_sources)` counts anything that never reaches
                # failed_sources - so a container missing TELEGRAM_API_ID reported
                # `success: True, sources_failed: 0` and contributed nothing, indistinguishable
                # from 12 healthy channels with no new posts. That is the exact pathology this
                # module's return value was rewritten to stop reporting.
                error = "connector unavailable or not configured"
                logger.warning(f"⚠️  Skipping platform {platform}: {error}")
                return await _record_connector_outage(
                    operations_service, sources, error, trigger
                )
            await connector.connect()
            logger.info(f"🔌 Connected to {platform} connector")
            for idx, source in enumerate(sources):
                results.append(await _fetch_source(source, connector=connector, **fetch_kwargs))
                if idx < len(sources) - 1:
                    delay = source["settings"]["fetch_delay_seconds"]
                    logger.info(f"⏳ Waiting {delay}s before next {platform} source...")
                    await asyncio.sleep(delay)
        except Exception as exc:
            logger.error(
                "💥 %s connector failed after %s/%s sources (the rest of the cycle is kept): %s",
                platform,
                len(results),
                len(sources),
                exc,
                exc_info=True,
            )
            # Sources we never reached are still reported, so the run's counts and the
            # Operations panel show the outage instead of the cycle silently shrinking.
            results.extend(
                await _record_connector_outage(
                    operations_service, sources[len(results):], str(exc), trigger
                )
            )
        finally:
            if connector is not None:
                try:
                    await connector.disconnect()
                    logger.info(f"🔌 Disconnected from {platform} connector")
                except Exception as exc:
                    logger.warning("Could not disconnect %s connector: %s", platform, exc)
        return results

    fetch_groups = [("live", live_sources, run_live_sources())]
    fetch_groups += [
        (platform, sources, run_connector_platform(platform, sources))
        for platform, sources in connector_platforms.items()
    ]

    # return_exceptions is what keeps a group failure local. Without it the first group to
    # raise aborts the gather, discards every post the others already fetched, and - because
    # gather does NOT cancel its siblings - leaves them running detached for the remaining
    # ~30 minutes, writing status rows for a run whose posts will never be saved, until
    # asyncio.run tears them down mid-flight by closing the loop.
    grouped_results = await asyncio.gather(
        *(coro for _, _, coro in fetch_groups), return_exceptions=True
    )

    for (label, group_sources, _), group in zip(fetch_groups, grouped_results):
        if isinstance(group, BaseException):
            # Both group runners are supposed to be exception-proof, so reaching this is a
            # bug worth a stack trace - but it costs one platform, never the cycle. Every
            # source in the group is booked as failed so the run's counts stay honest.
            logger.error(
                "💥 Fetch group '%s' failed entirely: %s", label, group, exc_info=group
            )
            failed_sources.extend(
                {"source": s.get("handle_or_url"), "error": f"fetch group '{label}' failed: {group}"}
                for s in group_sources
            )
            continue
        for result in group:
            platform = result["platform"]
            window = platform_timings.get(platform)
            if window is None:
                platform_timings[platform] = [result["started_at"], result["ended_at"]]
            else:
                window[0] = min(window[0], result["started_at"])
                window[1] = max(window[1], result["ended_at"])

            if result["error"]:
                failed_sources.append(
                    {"source": result["source"]["handle_or_url"], "error": result["error"]}
                )
                continue

            for post in result["posts"]:
                post["_source_id"] = result["source"]["id"]
            all_posts.extend(result["posts"])

    platform_timings = {p: window[1] - window[0] for p, window in platform_timings.items()}
    fetch_elapsed = time.time() - total_start_time
    # Counted once, here, so all_posts can be released after the save without breaking the
    # log lines and the result dict that used to read len(all_posts) at the very end.
    fetched_count = len(all_posts)
    logger.info(
        f"📦 Fetch phase done in {fetch_elapsed:.1f}s: {fetched_count} posts, "
        f"{len(failed_sources)} failed sources"
    )
    # grouped_results pins every fetched post a second time via result["posts"]. The
    # exception objects it may hold also carry __traceback__, whose frames keep that
    # source's locals alive; they have already been logged with exc_info above.
    del grouped_results

    # 6. Save to database. Every post is isolated by the SAVEPOINT repo_posts.upsert_post
    #    opens around its own write (and releases on both paths): a single row violating
    #    posts_source_external_unique used to abort the whole transaction and discard the
    #    entire ~30-minute fetch - it did exactly that twice on 2026-07-22. A poisoned post
    #    must cost one post, not one cycle. No second savepoint is wrapped around it here:
    #    the outer one bought nothing and doubled the subtransaction ids charged against
    #    Postgres's 64-per-backend cache (see SAVE_COMMIT_BATCH).
    db_start_time = time.time()
    repo = PostsRepository(db_url)
    event_service = EventMemoryService(db_url)
    per_source_fetch_counts = {}
    persisted_posts = []
    failed_posts: list[dict] = []
    created_count = 0
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            # Watermarks as of the last successful commit. If the transaction is ever left
            # in error state everything written since that commit dies with the rollback,
            # and persisted_posts must shrink with it - enrichment would otherwise be handed
            # post ids that no longer exist.
            committed_posts = 0
            committed_created = 0
            for index, post in enumerate(all_posts, start=1):
                post_copy = dict(post)
                source_id = post_copy.pop("_source_id")
                per_source_fetch_counts[source_id] = per_source_fetch_counts.get(source_id, 0) + 1

                try:
                    post_id, was_inserted = repo.upsert_post(cur, post_copy, source_id)
                except Exception as exc:
                    failed_posts.append(
                        {
                            "url": post_copy.get("url"),
                            "source_id": source_id,
                            "error": str(exc),
                        }
                    )
                    logger.error(
                        "❌ Failed to save post %s (source %s): %s",
                        post_copy.get("url"),
                        source_id,
                        exc,
                    )
                    # upsert_post normally leaves the transaction usable - its savepoint has
                    # already rolled the bad statement back. Its collision lookup is the one
                    # statement that runs outside that savepoint, so verify instead of
                    # assuming: an aborted transaction rejects every later statement with
                    # 25P02, which would turn one poisoned row back into a lost batch.
                    if _transaction_is_poisoned(conn):
                        conn.rollback()
                        discarded = persisted_posts[committed_posts:]
                        del persisted_posts[committed_posts:]
                        created_count = committed_created
                        failed_posts.extend(
                            {
                                "url": item.get("url"),
                                "source_id": item.get("_source_id"),
                                "error": "discarded: transaction rolled back after a failed post",
                            }
                            for item in discarded
                        )
                        logger.error(
                            "↩️  Transaction left in error state; rolled back %s uncommitted posts",
                            len(discarded),
                        )
                else:
                    if was_inserted:
                        created_count += 1
                    persisted_posts.append(
                        {
                            **post_copy,
                            "id": post_id,
                            "_source_id": source_id,
                        }
                    )
                    logger.info(f"Saved post: {post_copy['url']}")

                # Checkpoint on every iteration, failures included. Hung off the success path
                # (behind the `continue` this replaces), a post that failed exactly on a batch
                # boundary skipped its own commit and deferred it a whole extra batch - which
                # doubles both the posts a later rollback can destroy and the subtransaction
                # ids held open, the two numbers SAVE_COMMIT_BATCH exists to bound. A failed
                # post costs savepoints too, so `index` - every post attempted - is the right
                # denominator.
                if index % SAVE_COMMIT_BATCH == 0:
                    conn.commit()
                    committed_posts = len(persisted_posts)
                    committed_created = created_count
        conn.commit()

    save_elapsed = time.time() - db_start_time
    logger.info(
        f"💾 Saved {len(persisted_posts)}/{fetched_count} posts in {save_elapsed:.1f}s "
        f"({created_count} new, {len(failed_posts)} failed)"
    )
    # Everything below needs post ids, not post bodies. all_posts holds 3000-5000 dicts
    # carrying content, content_html and YouTube transcripts - on the order of 100-200MB -
    # and without this it stayed live through enrichment AND the archive refresh, holding
    # peak RSS for ~15 more minutes of yt-dlp work that needs none of it.
    all_posts.clear()

    # 7. Enrichment. Chunked only so it reports progress: this phase used to be 8+ minutes
    #    of complete silence, which is indistinguishable from a hang.
    if persisted_posts:
        _run_enrichment(
            "Entity memory",
            EntityMemoryService(db_url).process_posts,
            persisted_posts,
        )
        _run_enrichment(
            "Event memory",
            event_service.process_posts,
            persisted_posts,
        )
        # Same reasoning as all_posts: the archive refresh below is pure yt-dlp and HTTP,
        # and nothing after this point reads a post body.
        persisted_posts.clear()

    # 8. Archive metadata refresh. record_live_fetch re-inspects the source it just
    #    fetched (for YouTube that is a full unbounded yt-dlp channel dump), so log each
    #    one - this is a large, previously invisible slice of the cycle.
    #
    #    It runs under exactly the gates the fetch phase uses, and for the same reasons.
    #    Serially it was the dominant phase: ~32 YouTube channels at a realistic 30-60s each
    #    is 16-32 minutes of strictly sequential yt-dlp after a fetch phase this change set
    #    cut to ~15 minutes, and one channel that reaches the 900s scan ceiling costs 900s by
    #    itself. Parallelising it without the yt-dlp budget would instead fire every channel
    #    at YouTube's per-IP bot detector at once, which is the trade the fetch phase already
    #    settled - so reuse its gates rather than inventing a second policy.
    if REFRESH_ARCHIVE_METADATA:
        refresh_start = time.time()
        refreshable = [
            (source_id, count)
            for source_id, count in per_source_fetch_counts.items()
            if (source_lookup.get(source_id) or {}).get("platform") in LIVE_FETCH_PLATFORMS
        ]
        logger.info(f"🗂️  Refreshing archive metadata for {len(refreshable)} sources...")
        refreshed = 0

        async def refresh_one(source_id: str, fetched_posts: int) -> None:
            """Refresh one source's archive metadata. Never raises."""
            nonlocal refreshed
            source = source_lookup[source_id]
            settings = source.get("settings") or {}
            display_name = settings.get("display_name") or source["handle_or_url"]
            started = time.time()
            try:
                async with contextlib.AsyncExitStack() as gates:
                    if fetch_service.classify_source(source) == "youtube_channel":
                        await gates.enter_async_context(ytdlp_semaphore)
                        await ytdlp_spacer.wait()
                    else:
                        await gates.enter_async_context(
                            host_limiter.slot(
                                _HostLimiter.host_key(source), settings.get("fetch_delay_seconds") or 0
                            )
                        )
                    await gates.enter_async_context(semaphore)
                    await fetch_service.record_live_fetch(
                        source_id, source, fetched_posts=fetched_posts
                    )
            except Exception as exc:
                logger.warning("Archive metadata refresh failed for %s: %s", display_name, exc)
            refreshed += 1
            logger.info(
                f"🗂️  [{refreshed}/{len(refreshable)}] {display_name} refreshed in "
                f"{time.time() - started:.1f}s"
            )

        # return_exceptions for the same reason the fetch groups use it: a refresh is
        # best-effort metadata and must never cost the run its return value.
        outcomes = await asyncio.gather(
            *(refresh_one(source_id, count) for source_id, count in refreshable),
            return_exceptions=True,
        )
        for (source_id, _), outcome in zip(refreshable, outcomes):
            if isinstance(outcome, BaseException):
                logger.error(
                    "💥 Unhandled error refreshing archive metadata for %s: %s",
                    (source_lookup.get(source_id) or {}).get("handle_or_url"),
                    outcome,
                    exc_info=outcome,
                )
        logger.info(f"🗂️  Archive metadata refresh done in {time.time() - refresh_start:.1f}s")
    else:
        logger.info("🗂️  Archive metadata refresh disabled (SAFE_INGEST_REFRESH_ARCHIVE_METADATA=0)")

    db_elapsed = time.time() - db_start_time
    total_elapsed = time.time() - total_start_time

    logger.info(f"✅ Ingested {fetched_count} posts from {len(sources_to_fetch)} sources")
    logger.info(
        f"⏱️  Fetch {fetch_elapsed:.1f}s | save+enrich+refresh {db_elapsed:.1f}s | "
        f"total {total_elapsed:.1f}s"
    )

    # Log timing summary (only in debug mode)
    if DEBUG_MODE:
        logger.debug("=" * 60)
        logger.debug("⏱️  TIMING SUMMARY")
        logger.debug("=" * 60)

        # Per-platform timings are wall-clock windows now (first start -> last finish),
        # so they overlap: the live platforms run concurrently with each other.
        for platform, elapsed in platform_timings.items():
            source_count = len(by_platform[platform])
            logger.debug(f"  {platform.upper():12s} : {elapsed:6.2f}s ({source_count} sources)")

        logger.debug("-" * 60)
        logger.debug(f"  {'DATABASE':12s} : {db_elapsed:6.2f}s ({fetched_count} posts)")
        logger.debug("-" * 60)
        logger.debug(f"  {'TOTAL':12s} : {total_elapsed:6.2f}s")
        logger.debug("=" * 60)

    # "posts_ingested" used to be len(all_posts) - the FETCH count - so a run that fetched 349
    # and created 43 reported 349, and the number could never fall when a feed froze. It also
    # returned success unconditionally, which is why 83 ingest runs recorded zero failures even
    # when every source errored.
    attempted = len(sources_to_fetch)
    succeeded = attempted - len(failed_sources)
    error_parts = []
    if failed_sources:
        error_parts.append(
            f"{len(failed_sources)} of {attempted} sources failed: "
            + "; ".join(f["source"] for f in failed_sources[:5])
        )
    if failed_posts:
        error_parts.append(f"{len(failed_posts)} posts could not be saved")
    return {
        "success": not failed_sources and not failed_posts,
        "posts_ingested": created_count,
        "posts_fetched": fetched_count,
        "posts_duplicate": fetched_count - created_count - len(failed_posts),
        "posts_failed": len(failed_posts),
        "post_failures": failed_posts[:20],
        "sources_ingested": succeeded,
        "sources_attempted": attempted,
        "sources_failed": len(failed_sources),
        "sources_backoff_skipped": backoff_skipped,
        "failures": failed_sources[:20],
        "error": "; ".join(error_parts) if error_parts else None,
    }


def _empty_result(sources_backoff_skipped: int = 0) -> dict:
    """Nothing-to-do result carrying the full key set callers expect."""
    return {
        "success": True,
        "posts_ingested": 0,
        "posts_fetched": 0,
        "posts_duplicate": 0,
        "posts_failed": 0,
        "post_failures": [],
        "sources_ingested": 0,
        "sources_attempted": 0,
        "sources_failed": 0,
        "sources_backoff_skipped": sources_backoff_skipped,
        "failures": [],
        "error": None,
    }


def _run_enrichment(label: str, process_posts, posts: list[dict]) -> None:
    """Run one enrichment service over the batch in chunks, reporting progress.

    A failing chunk is logged and skipped rather than losing the whole batch, matching
    the previous "enrichment is best-effort" behaviour.
    """
    started = time.time()
    total = len(posts)
    logger.info(f"🧠 {label}: processing {total} posts...")
    for offset in range(0, total, ENRICH_CHUNK_SIZE):
        chunk = posts[offset : offset + ENRICH_CHUNK_SIZE]
        chunk_started = time.time()
        try:
            process_posts(chunk)
        except Exception as exc:
            logger.warning("%s enrichment skipped for chunk at %s: %s", label, offset, exc)
        logger.info(
            f"🧠 {label}: {min(offset + len(chunk), total)}/{total} posts "
            f"({time.time() - chunk_started:.1f}s this chunk)"
        )
    logger.info(f"🧠 {label}: done in {time.time() - started:.1f}s")


if __name__ == "__main__":
    asyncio.run(safe_ingest_posts())
