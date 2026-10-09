# backend/insight_core/scripts/safe_ingest.py
"""
Safe ingestion script that only fetches from sources that need updating.

Filtering logic (Mark IX B1): one decision, ingestion.schedule.decide_fetch, fed by the
source's cadence columns and its row in source_fetch_state:
- kind unavailable (yt-dlp off) → SKIP, reported as unavailable, never as backoff
- in backoff after repeated failures → SKIP (a manual trigger ignores backoff only)
- new source (no successful fetch, 0 posts) → FETCH
- otherwise FETCH once the adaptive fetch interval has elapsed since the last
  *successful* fetch (empty fetches count), else SKIP

B4 replaces this module with a CLI shim over ingestion.run_ingestion.

Politeness (Mark IX B3): each source resolves to a SourceKind (ingestion/kinds) whose
PolitenessProfile drives both the decision (cadence floor, minimum posts, requirements)
and the gates: FetchGates.slot(kind.profile, kind.host_key(source)) for the fetch and for
the archive-metadata refresh alike.

Usage: python backend/insight_core/scripts/safe_ingest.py
"""
import sys
from pathlib import Path
import time
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterator

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import asyncio
import psycopg
from insight_core.db.ensure_db import ensure_database
from insight_core.db.repo_fetch_state import FetchStateRow
from insight_core.db.repo_posts import PostsRepository
from insight_core.ingestion.gates import FetchGates, interleave_by_host
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import KindUnavailable, PolitenessProfile, SourceKind
from insight_core.ingestion.kinds.generic_rss import GENERIC_RSS_PROFILE
from insight_core.ingestion.ports import DbFetchStateStore
from insight_core.ingestion.schedule import (
    Availability,
    DecisionKind,
    FetchDecision,
    availability_from_env,
    cadence_stats,
    decide_fetch,
)
from insight_core.ingestion.types import FetchOutcome, OutcomeStatus
from insight_core.services.entity_memory_service import EntityMemoryService
from insight_core.services.event_memory_service import EventMemoryService
from insight_core.services.sources_service import SourcesService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

DEBUG_MODE = False  # DEBUG here also puts the API at DEBUG level (bridge imports this module)
setup_logging(debug_mode=DEBUG_MODE)
logger = get_component_logger("safe_ingest")

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
# dump) on its own cadence. Kept on by default so archive metadata stays accurate, but an
# operator can switch it off when a cycle must be fast.
REFRESH_ARCHIVE_METADATA = os.getenv("SAFE_INGEST_REFRESH_ARCHIVE_METADATA", "1") != "0"


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


@dataclass(frozen=True)
class ShouldFetch:
    """should_fetch_source's answer. Unpacks as (fetch, reason); .kind/.decision for the rest."""

    fetch: bool
    reason: str
    decision: FetchDecision

    @property
    def kind(self) -> DecisionKind:
        return self.decision.kind

    def __iter__(self) -> Iterator:
        yield self.fetch
        yield self.reason


def should_fetch_source(
    source: dict,
    state: FetchStateRow | None,
    trigger: str = "manual",
    *,
    profile: PolitenessProfile = GENERIC_RSS_PROFILE,
    now: datetime | None = None,
    availability: Availability | None = None,
) -> ShouldFetch:
    """Adapter from the Mark VIII call shape to decide_fetch.

    A manual trigger keeps its Mark VIII meaning through ignore_backoff: it skips the
    backoff window (the operator's "try it now") but still respects freshness. B4 replaces
    this with FetchRequest.force.
    """
    decision = decide_fetch(
        cadence_stats(source, state),
        profile,
        now or datetime.now(timezone.utc),
        force=False,
        availability=availability or availability_from_env(),
        ignore_backoff=(trigger == "manual"),
    )
    return ShouldFetch(decision.fetch, decision.detail, decision)


async def _fetch_source(
    source: dict,
    *,
    kind: SourceKind,
    fetch_state: DbFetchStateStore,
    trigger: str,
    gates: FetchGates,
    post_limit: int | None = None,
) -> dict:
    """Fetch one source through its kind, under its gates, and record the outcome. Never raises.

    post_limit is the decision's limit (already floored by the profile); without one the
    source's own max_posts_per_fetch applies, raised to the profile's minimum.

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
    unavailable: str | None = None

    try:
        max_posts = post_limit if post_limit is not None else max(
            settings["max_posts_per_fetch"], kind.profile.min_posts_per_fetch
        )
        async with gates.slot(kind.profile, kind.host_key(source),
                              per_source_delay_s=settings.get("fetch_delay_seconds") or 0):
            logger.info(f"📥 [{priority}] Fetching up to {max_posts} posts from {display_name}")
            posts = await kind.fetch_latest(source, max_posts)
    except KindUnavailable as exc:
        unavailable = exc.reason
        posts = []
    except Exception as exc:
        error = str(exc)
        posts = []

    elapsed = time.time() - started_at

    if unavailable is not None:
        logger.warning(f"🚫 {display_name}: unavailable ({unavailable})")
    elif error is None:
        logger.info(f"✅ [{priority}] {display_name}: fetched {len(posts)} posts in {elapsed:.1f}s")
    else:
        logger.error(f"❌ Failed to fetch from {source.get('handle_or_url')}: {error}")

    # One outcome write per fetch. A fetch that raises nothing but returns nothing is
    # `empty`, not healthy - that is how a silently dead feed looks - but it is still a
    # success: it clears the failure ladder and advances last_success_at. A kind that turns
    # out to be unavailable is `unavailable`, which never advances backoff.
    if unavailable is not None:
        outcome = FetchOutcome(str(source.get("id")), OutcomeStatus.UNAVAILABLE, 0, unavailable, elapsed)
    else:
        outcome = FetchOutcome.from_fetch(str(source.get("id")), fetched=len(posts), error=error, duration_s=elapsed)
    try:
        await asyncio.to_thread(fetch_state.record_outcome, outcome, trigger=trigger)
    except Exception as exc:
        logger.warning("Could not record fetch outcome for %s: %s", source.get("handle_or_url"), exc)

    return {
        "source": source,
        "platform": source.get("platform"),
        "posts": posts,
        "error": error if unavailable is None else f"unavailable: {unavailable}",
        "started_at": started_at,
        "ended_at": started_at + elapsed,
    }


async def safe_ingest_posts(
    trigger: str = "manual",
    *,
    sources_service: SourcesService | None = None,
    fetch_service: SourceFetchService | None = None,
    fetch_state: DbFetchStateStore | None = None,
    kinds: KindRegistry | None = None,
    gates: FetchGates | None = None,
    availability: Callable[[], Availability] = availability_from_env,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
):
    """Fetch and save posts only from sources that are due.

    The keyword arguments are seams for tests; the defaults are the real adapters.
    """

    # Start total timer
    total_start_time = time.time()
    platform_timings = {}

    # 0. Get database URL
    db_url = ensure_database()

    # 1. Get all sources with settings from database
    sources_service = sources_service or SourcesService(db_url)
    fetch_service = fetch_service or SourceFetchService(db_url)
    fetch_state = fetch_state or DbFetchStateStore(db_url)
    kinds = kinds or fetch_service.kinds

    # Refresh cadence first, so new sources leave probation and gaps follow the posts
    # (B4 moves this to the daily work). Best-effort: stale tiers beat no cycle.
    try:
        refreshed = await asyncio.to_thread(fetch_state.refresh_cadence)
        logger.info(f"📈 Cadence refreshed for {refreshed} sources")
    except Exception as exc:
        logger.warning("Cadence refresh failed (continuing with stored tiers): %s", exc)

    all_sources = sources_service.get_all_sources_with_settings()

    # Filter only enabled sources
    enabled_sources = [s for s in all_sources if s["enabled"]]

    if not enabled_sources:
        logger.warning("⚠️  No enabled sources found")
        return _empty_result()

    logger.info(f"📊 Found {len(enabled_sources)} enabled sources")

    # 2. Decide, from the fetch state (one load) and the cadence columns.
    sources_to_fetch = []
    sources_to_skip = []
    post_limits: dict[str, int] = {}
    decisions: list[tuple[str, FetchDecision]] = []
    decision_counts: dict[str, int] = {}

    states = await asyncio.to_thread(fetch_state.load, [s["id"] for s in enabled_sources])
    available = availability()
    now = clock()
    for source in enabled_sources:
        answer = should_fetch_source(
            source,
            states.get(source["id"]),
            trigger,
            profile=kinds.resolve(source).profile,
            now=now,
            availability=available,
        )
        decisions.append((source["id"], answer.decision))
        decision_counts[answer.kind.value] = decision_counts.get(answer.kind.value, 0) + 1
        display_name = source["settings"].get("display_name") or source["handle_or_url"]

        if answer.fetch:
            sources_to_fetch.append(source)
            post_limits[source["id"]] = answer.decision.post_limit
            logger.info(f"✅ {display_name}: {answer.reason}")
        else:
            sources_to_skip.append(source)
            logger.info(f"⏭️  {display_name}: {answer.reason}")

    # Counted from the decision kind, never from the reason text: yt-dlp-off sources are
    # unavailable, not in backoff (the Mark VIII 🚫 prefix counted both as backoff).
    backoff_skipped = decision_counts.get(DecisionKind.SKIP_BACKOFF.value, 0)
    unavailable_skipped = decision_counts.get(DecisionKind.SKIP_UNAVAILABLE.value, 0)

    try:
        await asyncio.to_thread(fetch_state.record_decisions, decisions)
    except Exception as exc:
        logger.warning("Could not record fetch decisions: %s", exc)

    # 3. Summary
    logger.info("=" * 60)
    logger.info(f"📥 Sources to fetch: {len(sources_to_fetch)}")
    logger.info(
        f"⏭️  Sources to skip:  {len(sources_to_skip)} ({backoff_skipped} in backoff, "
        f"{unavailable_skipped} unavailable)"
    )
    logger.info("=" * 60)

    skip_counts = {
        "sources_backoff_skipped": backoff_skipped,
        "sources_unavailable_skipped": unavailable_skipped,
        "decisions": decision_counts,
    }

    if not sources_to_fetch:
        logger.info("✨ All sources are up to date! Nothing to fetch.")
        return _empty_result(**skip_counts)

    # 4. Order: priority first, then round-robin across hosts so the tasks gather starts
    #    together mostly want different gates.
    sources_to_fetch.sort(key=lambda s: (s["settings"]["priority"], s["handle_or_url"]))
    sources_to_fetch = interleave_by_host(sources_to_fetch)
    source_kinds = {source["id"]: kinds.resolve(source) for source in sources_to_fetch}
    by_platform: dict[str, list[dict]] = {}
    by_pool: dict[str, int] = {}
    for source in sources_to_fetch:
        by_platform.setdefault(source["platform"], []).append(source)
        pool = source_kinds[source["id"]].profile.concurrency_pool
        by_pool[pool] = by_pool.get(pool, 0) + 1
    for platform, sources in by_platform.items():
        priority_info = [
            f"[{s['settings']['priority']}] {s['settings'].get('display_name') or s['handle_or_url']}"
            for s in sources
        ]
        logger.info(f"📋 {platform.upper()} priority order: {' → '.join(priority_info)}")

    # 5. Fetch. Every source runs concurrently through its kind; FetchGates applies the
    #    politeness profile (host lock + host floor, or the yt-dlp pool and start spacer)
    #    under one global budget.
    all_posts = []
    failed_sources: list[dict] = []
    source_lookup = {source["id"]: source for source in sources_to_fetch}
    gates = gates or FetchGates.shared()

    logger.info(
        f"🚀 Fetching {len(sources_to_fetch)} sources with concurrency {gates.max_concurrency} "
        f"(yt-dlp {gates.ytdlp_concurrency}); pools: {by_pool}"
    )
    # _fetch_source is written never to raise, but "written never to" is not a guarantee a
    # whole cycle should rest on: without return_exceptions one unexpected error discards
    # every source fetched so far, and - because gather does NOT cancel its siblings - leaves
    # them running detached. Every returned exception is inspected below.
    gathered = await asyncio.gather(
        *(
            _fetch_source(s, kind=source_kinds[s["id"]], fetch_state=fetch_state, trigger=trigger,
                          gates=gates, post_limit=post_limits.get(s["id"]))
            for s in sources_to_fetch
        ),
        return_exceptions=True,
    )
    results: list[dict] = []
    for source, result in zip(sources_to_fetch, gathered):
        if isinstance(result, BaseException):
            logger.error(
                "💥 Unhandled error fetching %s (cycle continues): %s",
                source.get("handle_or_url"),
                result,
                exc_info=result,
            )
            results.append(_failed_result(source, f"unhandled fetch error: {result}"))
        else:
            results.append(result)
    del gathered

    for result in results:
        platform = result["platform"]
        window = platform_timings.get(platform)
        if window is None:
            platform_timings[platform] = [result["started_at"], result["ended_at"]]
        else:
            window[0] = min(window[0], result["started_at"])
            window[1] = max(window[1], result["ended_at"])

        if result["error"]:
            failed_sources.append({"source": result["source"]["handle_or_url"], "error": result["error"]})
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
    # results pins every fetched post a second time via result["posts"].
    del results

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
            if source_id in source_lookup
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
                kind = source_kinds[source_id]
                async with gates.slot(kind.profile, kind.host_key(source),
                                      per_source_delay_s=settings.get("fetch_delay_seconds") or 0):
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
        **skip_counts,
        "failures": failed_sources[:20],
        "error": "; ".join(error_parts) if error_parts else None,
    }


def _empty_result(
    sources_backoff_skipped: int = 0,
    sources_unavailable_skipped: int = 0,
    decisions: dict[str, int] | None = None,
) -> dict:
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
        "sources_unavailable_skipped": sources_unavailable_skipped,
        "decisions": dict(decisions or {}),
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
