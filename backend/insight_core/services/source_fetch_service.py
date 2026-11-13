"""
Archive planning and execution for DB-backed sources (Mark IX).

Fetching lives behind the source-kind seam (insight_core/ingestion/kinds), and every live
fetch goes through the ingestion runner (insight_core/ingestion). This service keeps:
- plan_archive / archive_source: one loop over kind.archive_pages, paced by
  kind.profile.rate_limit(persisted settings, request overrides) and by the same
  FetchGates.slot per page a fetch takes; every page is one save batch. A host that limits
  us (429) or times out is waited out and the page retried once from the last checkpoint
  (issue 0016); twice in a row, the archive waits for the host's window and the scheduler
  continues it (continue_archive), pausing only after MAX_WAITS waits with no page gained.
  Each host's budget is learned from those limits (ingestion/host_budgets.py), and once
  known an archive paces under it and keeps out of the way of the host's live fetches
  (issue 0107). An unavailable
  kind (yt-dlp off, no Telegram session) raises KindUnavailable before any planning (the API answers 409). Both run inside the
  kind's session (B8: telegram_mtproto connects and checks authorisation; every other kind
  has a no-op session), so a session that cannot open is the same 409.

settings["archive"] is written by ingestion.archive_metadata.ArchiveMetadataWriter.

Issue 0130: an archive "back to a date" (`until`) of a kind whose pages go newest first (kind.chronological:
Telegram, X, Substack) stops after the first page that passes the date, its checkpoint kept so a later archive
goes on from there; an archive whose pages added nothing says why (the kind's checkpoint "skipped": already
stored, no post, unreadable; and the posts that were stored already under another address), and a reader whose
every listed entry is a post (LISTS_ONLY_POSTS) that finds none fails, saying the site's layout changed; a feed
that answers 404/410 (or no feed) wakes the source doctor (issue 0036: the feed finder and page watching), whose
finding the source sheet offers.
"""
from __future__ import annotations

import asyncio
import time
import contextlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from insight_core.db import database as db
from insight_core.ingestion import archive_ladder

from insight_core.db.repo_linked import LinkedPage, linked_not_stored
from insight_core.db.repo_posts import BACKLOG_KEY, PostDraft, PostsRepository, SaveBatchResult
from insight_core.ingestion.archive_metadata import (
    ArchiveMetadataWriter,
    archive_estimate,
    derive_archive_status,
    resumable,
)
from insight_core.ingestion.gates import HOST_FLOORS, FetchGates
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import (
    SKIP_NO_POST,
    SKIP_STORED,
    SKIP_UNREADABLE,
    ArchivePage,
    KindUnavailable,
    RateLimit,
    SourceKind,
    layout_changed_line,
    resume_counts,
    skipped_counts,
)
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.ports import slowed_line
from insight_core.ingestion.schedule import (
    DEFAULT_MAX_POSTS_PER_FETCH,
    Availability,
    availability_from_env,
    unavailable_reason,
)
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.operations_service import backlog_posts
from insight_core.services.posts_service import PostsService
from insight_core.services.sources_service import SourcesService
from insight_core.services.youtube_service import YouTubeService
from insight_core.utils.json_safe import iso

ProgressCallback = Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]]

# The target of an archive whose source reports no size: it runs until the source ends.
UNBOUNDED_ARCHIVE = 1_000_000_000
ARCHIVE_STOP_KEY = "archive_stop:"
STOP_CHECK_S = 20.0   # v10.13.9: a running archive looks for a stop request at most this often (one small read)   # v10.13.9: system_settings key + source id: the owner asked its archive to stop

# Issue 0107. A host that refused twice in a row is waited out: FIRST_WAIT_S, doubling up to
# LAST_WAIT_S while no page comes; after MAX_WAITS such waits the archive pauses.
FIRST_WAIT_S = 5 * 60
LAST_WAIT_S = 60 * 60
MAX_WAITS = 6
# An archive looks for due live fetches of its host at most every LIVE_CHECK_S, and keeps out of
# their way in LIVE_YIELD_STEP_S steps, at most LIVE_YIELD_MAX_S (a run that never comes).
LIVE_CHECK_S = 60
LIVE_YIELD_STEP_S = 30
LIVE_YIELD_MAX_S = 15 * 60
# The checkpoint of a linked fetch (issue 0084 B): the list it reads, where it is, what was not stored.
LINKED_MODE = "linked"
LINKED_SHOWN = 5   # the pages the Archive section names
CANNOT_READ = "This source's pages can't be read one page at a time"
# A leg's own result keys: what is left of a waiting leg's result is the plan the next leg reuses.
_LEG_KEYS = frozenset({
    "success", "posts_fetched", "pages_fetched", "posts_inserted", "posts_updated", "stored_posts",
    "archive_status", "message", "paused", "paused_reason", "waiting", "waiting_until", "waiting_host",
    "waiting_reason", "waits", "events", "progress", "missing", "unreached", "until_reached", "layout_changed",
    "error",
})
# A reader whose every listed entry is a post (kind.LISTS_ONLY_POSTS) that reads this many and finds no post: its
# site's layout changed (issue 0130 B2).
LAYOUT_MIN_PAGES = 3


def until_datetime(value: Any) -> Optional[datetime]:
    """An archive's horizon (issue 0130 C): a date ("2025-11-01") or a time, as UTC; None when unset or unreadable."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        found = value
    else:
        found = parsing.parse_datetime_value(str(value) if "T" in str(value) else f"{value}T00:00:00+00:00")
    if found is None:
        return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def _post_time(post: Dict[str, Any]) -> Optional[datetime]:
    value = post.get("date")
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return until_datetime(value) if value else None


def why_line(skipped: Dict[str, int], updated: int, inserted: int, *, re_read: bool) -> Optional[str]:
    """Why an archive's pages added fewer posts than the source lists (issue 0130 B4), or None when nothing
    is to explain: "102 already stored (not read again) · 8 pages are no post (no article or no date) · ..."."""
    parts = []
    if skipped.get(SKIP_STORED):
        parts.append(f"{plural(skipped[SKIP_STORED], 'page')} already stored (not read again)")
    if updated:
        parts.append(f"{plural(updated, 'post')} " + ("read again, already stored" if re_read
                                                   else "already stored under another address"))
    if skipped.get(SKIP_NO_POST):
        parts.append(f"{plural(skipped[SKIP_NO_POST], 'page')} no post (no article, or no date)")
    if skipped.get(SKIP_UNREADABLE):
        parts.append(f"{plural(skipped[SKIP_UNREADABLE], 'page')} could not be read")
    if not parts:
        return None if inserted else "the source's listing ends here"
    return " · ".join(parts)


class SourceFetchService:
    """Archive service for DB-backed sources; fetches go through the source kinds."""

    def __init__(
        self,
        db_url: str,
        *,
        http: Optional[KindHttp] = None,
        kinds: Optional[KindRegistry] = None,
        availability: Callable[[], Availability] = availability_from_env,
        gates: Optional[FetchGates] = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        live_fetch_due: Optional[Callable[[str], bool]] = None,
        doctor: Optional[Any] = None,
    ):
        self.db_url = db_url
        self.sources_service = SourcesService(db_url)
        self.posts_service = PostsService(db_url)
        self.posts_repo = PostsRepository(db_url)
        self.youtube_service = YouTubeService(db_url)
        self.logger = get_component_logger("source_fetch_service")
        self.http = http or KindHttp()
        self.kinds = kinds or KindRegistry.default(self.http, self.youtube_service, db_url=db_url)
        self.archive_metadata = ArchiveMetadataWriter(posts=self.posts_service, sources=self.sources_service)
        self.availability = availability
        # None: the process's FetchGates.shared(), the runner's own (taken inside the loop).
        self.gates = gates
        self.clock = clock
        # Is a live fetch of this host due now (ports.DbLiveFetchDue)? None: never yield.
        self.live_fetch_due = live_fetch_due
        # The source doctor (ingestion/source_doctor.py), woken by a feed that answers 404 (issue 0130 B3); None: not.
        self.doctor = doctor

    # ------------------------------------------------------------------ kinds

    async def _inspect(self, kind: SourceKind, source: Dict[str, Any]) -> Dict[str, Any]:
        inspection = await kind.inspect(source)
        source_settings = source.get("settings") or {}
        return {
            **inspection.as_dict(),
            "available_basis": kind.available_basis,
            "source_type": kind.name,
            "display_name": source_settings.get("display_name") or source["handle_or_url"],
        }

    # ------------------------------------------------------------------ archive

    def archive_catalog(self) -> List[Dict[str, Any]]:
        """Every enabled source that can archive, with its persisted archive status; unfinished
        archives first. A source that cannot archive (see archive_support) is left out."""
        catalog = []
        availability = self.availability()
        # Issue 0195: the list's settings (one query; no archive history, no checkpoint resume lists), not each
        # source's settings read one by one with the lists the catalog never shows.
        for source in self.sources_service.list_sources():
            if not source.get("enabled"):
                continue
            settings = source.get("settings") or {}
            if not self._support(self.kinds.resolve(source), settings, availability)["archivable"]:
                continue
            archive = settings.get("archive", {})
            stored = int(archive.get("stored_posts") or source.get("post_count") or 0)
            catalog.append(
                {
                    "source_id": source["id"],
                    "display_name": settings.get("display_name") or source["handle_or_url"],
                    "platform": source["platform"],
                    "kind": self.kinds.resolve(source).name,
                    "enabled": bool(source.get("enabled")),
                    "stored_posts": stored,
                    "available_posts": archive.get("available_posts"),
                    # E1: the backlog is available - stored, or None when unknown.
                    "backlog_posts": backlog_posts(archive.get("available_posts"), stored),
                    "estimated_seconds": archive.get("estimated_seconds"),
                    # When planning last measured the source (None: never).
                    "last_inspected_at": archive.get("last_inspected_at"),
                    "archive_status": archive.get("status") or "not_archived",
                    "resume_ready": bool(archive.get("resume_ready")),
                    "source_type": archive.get("source_type"),
                    "last_archived_at": archive.get("last_archived_at"),
                    "last_live_fetch_at": archive.get("last_live_fetch_at"),
                    "checkpoint": archive.get("checkpoint"),
                    "rate_limit": archive.get("rate_limit") or {},
                    # {host, until} while it waits out a host's limit (issue 0107), else None.
                    "waiting": archive.get("waiting"),
                    # The smart archiver's coverage (issue 0143): "stored N of ~M", the platform, the reasons.
                    "coverage": coverage_of(archive, stored),
                }
            )
        catalog.sort(key=lambda item: (item["archive_status"] != "partial",
                                       item["archive_status"] != "not_archived",
                                       item["display_name"].lower()))
        return catalog

    def archive_support(self, source_id: str) -> Dict[str, Any]:
        """Can this source archive, and what does its available count mean? No network.

        A kind this process cannot fetch (yt-dlp off, no Telegram credentials) cannot
        archive. A feed (available_basis feed_window) has no history beyond what it lists
        now, so archiving only adds anything when the feed lists more than one live fetch
        reads, or the site's sitemap lists older posts of its section (issue 0108); an
        unmeasured feed stays archivable so a plan can measure it.
        """
        # Merged settings (the kind's defaults under the user's), as every fetch reads them.
        source = self.sources_service.get_source_with_settings(source_id)
        return self._support(self.kinds.resolve(source), source.get("settings") or {}, self.availability())

    @staticmethod
    def _support(kind: SourceKind, settings: Dict[str, Any], availability: Availability) -> Dict[str, Any]:
        """archive_support from a source's merged settings."""
        limit = int(settings.get("max_posts_per_fetch") or DEFAULT_MAX_POSTS_PER_FETCH)
        # The floor decide_fetch applies too: what one live fetch really reads.
        live_fetch_limit = max(limit, kind.profile.min_posts_per_fetch)
        support: Dict[str, Any] = {
            "kind": kind.name,
            "available_basis": kind.available_basis,
            "archivable": True,
            "reason": None,
            "unavailable": False,
            "live_fetch_limit": live_fetch_limit,
            # Its archive can stop at a date (issue 0130 C): its pages go newest first.
            "until": bool(getattr(kind, "chronological", False)),
        }
        reason = unavailable_reason(kind.profile, availability)
        if reason is not None:
            return {**support, "archivable": False, "reason": reason, "unavailable": True}
        if kind.archive_refused:
            return {**support, "archivable": False, "reason": kind.archive_refused}
        if kind.available_basis == "feed_window":
            archive = settings.get("archive") or {}
            available = archive.get("available_posts")
            # A sitemap listing older posts than the feed (issue 0108, inspect's raw.sitemap_posts) is read
            # post by post, however few: the feed's window is not all there is.
            sitemap = archive.get("sitemap_posts")
            from_sitemap = isinstance(sitemap, int) and not isinstance(sitemap, bool) and sitemap > 0
            # The smart archiver (issue 0143): a feed whose site holds more than the feed by any strategy of its
            # ladder (smart.found_more) archives, however short the feed. The deploy's re-run plans every feed
            # measured before the ladder (scripts/rerun_archives_0143.py).
            smart = archive.get("smart") if isinstance(archive.get("smart"), dict) else {}
            if (isinstance(available, int) and not isinstance(available, bool) and available <= live_fetch_limit
                    and not from_sitemap and not smart.get("found_more")):
                return {**support, "archivable": False, "reason": (
                    f"This feed only lists its latest {available} post{'' if available == 1 else 's'}, "
                    f"and every fetch already reads up to {live_fetch_limit}.")}
        return support

    async def plan_archive(
        self,
        source_id: str,
        *,
        resume: bool = True,
        rate_limit_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Measure a source and say where its archive continues from and how much is older."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise LookupError(f"Source {source_id} not found")

        kind = self.kinds.resolve(source)
        self._check_available(kind)
        async with self._kind_session(kind), self._feed_doctor(source, kind):
            return await self._plan(source_id, source, kind, resume=resume,
                                    rate_limit_overrides=rate_limit_overrides)

    def _check_available(self, kind: SourceKind) -> None:
        # E7: the archive honours the same availability switch as every live fetch.
        reason = unavailable_reason(kind.profile, self.availability())
        if reason is not None:
            raise KindUnavailable(reason)

    @contextlib.asynccontextmanager
    async def _kind_session(self, kind: SourceKind) -> AsyncIterator[None]:
        """The kind's session around one plan or archive run (KindUnavailable if it cannot open)."""
        session = kind.session()
        await session.open()
        try:
            yield
        finally:
            try:
                await session.close()
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Could not close the %s session: %s", kind.name, exc)

    async def _plan(
        self,
        source_id: str,
        source: Dict[str, Any],
        kind: SourceKind,
        *,
        resume: bool,
        rate_limit_overrides: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Measure the source once, then choose where the archive starts.

        A resumable checkpoint wins (when resume is asked); otherwise the kind's start
        checkpoint continues below the stored posts, or None starts at the newest post.
        older_posts (available - stored, or None when the source reports no size) is only
        for the estimate: an archive runs until the source ends.
        """
        inspection = await self._inspect(kind, source)
        source_with_settings = self.sources_service.get_source_with_settings(source_id)
        current_archive = (source_with_settings.get("settings") or {}).get("archive", {})
        # Profile defaults <- the persisted rate limit <- this request's overrides.
        rate = kind.profile.rate_limit(current_archive.get("rate_limit"), rate_limit_overrides)
        saved = resumable(kind, current_archive.get("checkpoint"))
        stats = self.posts_service.get_source_post_stats(source_id)
        stored = int(stats["post_count"])
        oldest = iso(stats.get("oldest_published_at"))
        start = None
        if not (resume and saved) and stored:
            start = await kind.start_checkpoint(source, stats)
        older_posts, estimated_pages, estimated_seconds = archive_estimate(
            kind, source, inspection["available_posts"], stored, inspection["page_size"], rate)

        inspection.update({
            "source_id": source_id,
            "current_stored_posts": stored,
            "oldest_published_at": oldest,
            "continues_from": oldest if start is not None else None,
            "older_posts": older_posts,
            "estimated_pages": estimated_pages,
            "estimated_seconds": estimated_seconds,
            "resume": bool(resume and saved),
            "resume_available": saved is not None,
            "checkpoint": saved if resume and saved else start,
            "rate_limit": rate.as_settings(),
        })

        await self._record_archive_metadata(source_id, inspection, mode="plan", kind=kind)
        return inspection

    async def archive_source(
        self,
        source_id: str,
        progress_callback: ProgressCallback = None,
        *,
        resume: bool = True,
        rate_limit_overrides: Optional[Dict[str, Any]] = None,
        until: Any = None,
    ) -> Dict[str, Any]:
        """Archive a source's posts older than the stored ones, until the source ends, or (`until`, a date, for a
        chronological kind) until its pages pass that date (issue 0130 C)."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise LookupError(f"Source {source_id} not found")

        kind = self.kinds.resolve(source)
        self._check_available(kind)
        async with self._kind_session(kind), self._feed_doctor(source, kind):
            plan = await self._plan(source_id, source, kind, resume=resume,
                                    rate_limit_overrides=rate_limit_overrides)
            horizon = until_datetime(until) if getattr(kind, "chronological", False) else None
            if horizon is not None:
                plan["until"] = horizon.isoformat()
            return await self._archive(source_id, source, kind, plan, progress_callback)

    @contextlib.asynccontextmanager
    async def _feed_doctor(self, source: Dict[str, Any], kind: SourceKind) -> AsyncIterator[None]:
        """A feed that answers 404/410, or no feed, while planning or archiving (issue 0130 B3): the source doctor
        looks for where it moved (the feed finder, then page watching, as every source add), and the error says
        what it found; the source sheet offers it (Switch). Anything else is raised as it was."""
        try:
            yield
        except Exception as exc:
            line = await self._doctor_line(source, kind, exc)
            if line is None:
                raise
            raise FeedMoved(f"{str(exc)[:200]}. {line}") from exc

    async def _doctor_line(self, source: Dict[str, Any], kind: SourceKind, exc: BaseException) -> Optional[str]:
        from insight_core.ingestion.source_doctor import DOCTOR_KINDS, failure_signal, short_address

        if self.doctor is None or kind.name not in DOCTOR_KINDS or failure_signal(exc) not in ("gone", "not_feed"):
            return None
        source_id = str(source["id"])
        try:
            state = await asyncio.to_thread(self._fetch_state, source_id)
            await self.doctor.after_failure(self.sources_service.get_source_with_settings(source_id) or source,
                                            kind, state, exc)
            after = await asyncio.to_thread(self._fetch_state, source_id)
            now = (self.sources_service.get_source_by_id(source_id) or {}).get("handle_or_url")
        except Exception:  # noqa: BLE001 - the archive's own error stands
            self.logger.exception("The source doctor could not look at %s", source.get("handle_or_url"))
            return None
        if now and now != source.get("handle_or_url"):
            return f"The feed moved: INSIGHT now follows {short_address(str(now))}; run the archive again"
        finding = after.doctor_finding or {}
        replacement = finding.get("replacement") if not finding.get("dismissed") else None
        if isinstance(replacement, dict) and replacement.get("url"):
            what = "a page to follow" if replacement.get("kind") == "page_watch" else "a feed"
            return (f"INSIGHT found {what} at {short_address(str(replacement['url']))}: switch to it on the source's "
                    "sheet, then run the archive again")
        if after.doctor_checked_at is not None and not finding.get("dismissed"):
            return "INSIGHT looked for where it moved and found nothing; check the address on the source's sheet"
        return None

    def _fetch_state(self, source_id: str) -> Any:
        """The source's fetch state (blocking), a blank one when it has none yet."""
        from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow

        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return FetchStateRepository().load(cur, [source_id]).get(source_id) or FetchStateRow(source_id=source_id)

    async def continue_archive(
        self,
        source_id: str,
        previous: Dict[str, Any],
        progress_callback: ProgressCallback = None,
    ) -> Dict[str, Any]:
        """Continue an archive that waited out a host's limit (issue 0107), from where its last
        leg stopped: `previous` is that leg's result (the waiting job's payload). The plan it
        carries is reused: no new measurement, which would be one more request to a host that
        was limiting us. The counts and the waits carry on."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise LookupError(f"Source {source_id} not found")
        kind = self.kinds.resolve(source)
        self._check_available(kind)
        plan = {key: value for key, value in previous.items() if key not in _LEG_KEYS}
        carried = {key: previous.get(key) for key in ("posts_fetched", "posts_inserted", "posts_updated", "waits")}
        await self._emit_progress(progress_callback, {
            "stage": "continuing",
            "source_type": kind.name,
            "host": previous.get("waiting_host"),
            "message": f"Continuing after {previous.get('waiting_host') or 'the host'}'s limit",
        })
        async with self._kind_session(kind):
            return await self._archive(source_id, source, kind, plan, progress_callback, carried=carried)

    # ---- v10.13.9: the owner stops a running archive ------------------------------------------------

    def request_stop(self, source_id: str) -> None:
        """Ask the running archive of the source to stop after its current page (whichever process runs it)."""
        from insight_core.db.repo_operations import SystemSettingsRepository
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            SystemSettingsRepository.upsert(cur, ARCHIVE_STOP_KEY + str(source_id),
                                            {"at": datetime.now(timezone.utc).isoformat()})
            conn.commit()

    def stop_requested(self, source_id: str) -> bool:
        """Whether the owner asked this source's archive to stop; a check that fails never stops an archive."""
        from insight_core.db.repo_operations import SystemSettingsRepository
        try:
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                return SystemSettingsRepository.get(cur, ARCHIVE_STOP_KEY + str(source_id)) is not None
        except Exception:  # noqa: BLE001 - the archive goes on
            self.logger.warning("Archive: could not read the stop request of %s", source_id)
            return False

    def clear_stop(self, source_id: str) -> None:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM system_settings WHERE key = %s", (ARCHIVE_STOP_KEY + str(source_id),))
            conn.commit()

    async def _archive(
        self,
        source_id: str,
        source: Dict[str, Any],
        kind: SourceKind,
        plan: Dict[str, Any],
        progress_callback: ProgressCallback,
        *,
        carried: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """One leg of the archive: a loop over kind.archive_pages from the plan's checkpoint (its
        measurement reused). It ends completed, paused, or waiting for a host's limit (issue
        0107: the scheduler continues it, carrying the counts)."""
        rate = kind.profile.rate_limit(plan.get("rate_limit"))
        linked = (plan.get("checkpoint") or {}).get("mode") == LINKED_MODE
        # A linked fetch (issue 0084 B) keeps its list and its result in its job: the source's archive
        # (its checkpoint, status and counts) is left as it was.
        record = _no_record if linked else self._record_archive_metadata
        # An archive has no limit: a kind stops where the source ends. The target only caps
        # the count, at the source's size when it reports one.
        available = plan.get("available_posts")
        target_posts = available if isinstance(available, int) else UNBOUNDED_ARCHIVE
        older_posts = plan.get("older_posts")
        start_checkpoint = plan.get("checkpoint")
        resume_collected_posts, total_pages_fetched = resume_counts(start_checkpoint)
        carried = carried or {}
        total_posts_fetched = int(carried.get("posts_fetched") or 0)
        total_inserted = int(carried.get("posts_inserted") or 0)
        total_updated = int(carried.get("posts_updated") or 0)
        # A continuation's checkpoint already counts this archive's earlier legs, as does the carry.
        resume_collected_posts = max(0, resume_collected_posts - total_posts_fetched)
        if not carried:
            await self._emit_progress(progress_callback, {
                "stage": "planning_complete",
                "source_type": kind.name,
                "older_posts": older_posts,
                "estimated_pages": plan.get("estimated_pages"),
                "estimated_seconds": plan.get("estimated_seconds"),
                "message": (f"Planning complete: {plural(older_posts or 0, 'linked page')} to read" if linked
                            else "Planning complete: " + (
                                "size unknown" if older_posts is None else f"about {older_posts} older posts")),
                "progress": 0.0,
            })

        horizon = until_datetime(plan.get("until"))
        continues_from = until_datetime(plan.get("continues_from"))
        if horizon is not None and not carried and continues_from is not None and continues_from <= horizon:
            # The archive continues below the stored posts, and they already reach the date.
            post_stats = self.posts_service.get_source_post_stats(source_id)
            result = {**plan, "success": True, "posts_fetched": 0, "pages_fetched": total_pages_fetched,
                      "posts_inserted": 0, "posts_updated": 0, "stored_posts": post_stats["post_count"],
                      "archive_status": derive_archive_status(post_stats["post_count"], plan["available_posts"]),
                      "until_reached": plan["until"],
                      "message": f"The archive already reaches {horizon:%-d %b %Y}"}
            await record(source_id, result, mode="archive", kind=kind)
            return result

        if older_posts == 0 and not carried:
            post_stats = self.posts_service.get_source_post_stats(source_id)
            result = {
                **plan,
                "success": True,
                "posts_fetched": 0,
                "pages_fetched": total_pages_fetched,
                "posts_inserted": 0,
                "posts_updated": 0,
                "stored_posts": post_stats["post_count"],
                "archive_status": derive_archive_status(post_stats["post_count"], plan["available_posts"]),
                "message": ("Every page your posts link is stored" if linked
                            else "The archive already reaches the source's oldest post"),
            }
            await record(source_id, result, mode="archive", kind=kind)
            return result

        gates = self.gates or FetchGates.shared()
        host = kind.host_key(source)
        delay = (source.get("settings") or {}).get("fetch_delay_seconds") or 0
        checkpoint = start_checkpoint
        retried = False
        pages_this_leg = 0
        stopped: Optional[HttpError] = None
        reached: Optional[datetime] = None   # the oldest post of the page that passed `until` (issue 0130 C)
        owner_stopped = False                # v10.13.9: POST /api/archive/{id}/stop
        stop_checked = time.monotonic()      # the first look after STOP_CHECK_S
        pace = _Pace(self, gates, host, progress_callback)
        await gates.budgets.archive_started(host)
        try:
            while True:
                pages = (self._linked_pages(kind, source, checkpoint) if linked
                         else kind.archive_pages(source, target_posts, checkpoint, rate))
                try:
                    gated = self._gated(pages, gates, kind, host, delay, rate, total_pages_fetched, pace)
                    async for page in gated:
                        retried = False
                        pages_this_leg += 1
                        if page.posts:
                            saved = await asyncio.to_thread(self._save_posts, source_id, page.posts)
                            total_posts_fetched += len(page.posts)
                            total_inserted += saved.inserted
                            total_updated += saved.updated
                        collected = resume_collected_posts + total_posts_fetched
                        if page.checkpoint is not None:
                            checkpoint = page.checkpoint
                            total_pages_fetched = int(page.checkpoint.get("pages_fetched") or total_pages_fetched + 1)
                        else:
                            # Single-shot kinds finish in one page; keep a checkpoint for the history.
                            total_pages_fetched += 1
                            checkpoint = {"mode": kind.name, "pages_fetched": total_pages_fetched,
                                          "collected_posts": collected}

                        await record(source_id, {
                            **plan,
                            "pages_fetched": total_pages_fetched,
                            "posts_fetched": total_posts_fetched,
                            "posts_inserted": total_inserted,
                            "posts_updated": total_updated,
                            "checkpoint": checkpoint,
                        }, mode="archive_progress", kind=kind)
                        await self._emit_progress(progress_callback, {
                            "stage": "page_fetched",
                            "source_type": kind.name,
                            "pages_fetched": total_pages_fetched,
                            "posts_collected": collected,
                            "progress": (min(100.0, total_posts_fetched / older_posts * 100.0)
                                         if older_posts else None),
                            "message": (f"Read linked page {total_pages_fetched} of {len(checkpoint.get('urls') or ())}"
                                        if linked else f"Fetched {kind.name} page {total_pages_fetched}"),
                        })
                        if (not linked and time.monotonic() - stop_checked >= STOP_CHECK_S
                                and await asyncio.to_thread(self.stop_requested, source_id)):
                            # v10.13.9: the owner stopped it (POST /api/archive/{id}/stop), between two pages:
                            # what is stored stays; the checkpoint says why and is never resumed by itself
                            checkpoint = {**(checkpoint or {}), "end": True, "stopped": archive_ladder.OWNER_STOP}
                            await record(source_id, {**plan, "pages_fetched": total_pages_fetched,
                                                     "posts_fetched": total_posts_fetched,
                                                     "posts_inserted": total_inserted, "posts_updated": total_updated,
                                                     "checkpoint": checkpoint}, mode="archive_progress", kind=kind)
                            await asyncio.to_thread(self.clear_stop, source_id)
                            owner_stopped = True
                            break
                        if horizon is not None and page.posts:
                            dates = [d for d in (_post_time(post) for post in page.posts) if d is not None]
                            if dates and min(dates) < horizon:
                                reached = min(dates)
                                break
                    if reached is not None or owner_stopped:
                        await gated.aclose()
                        with contextlib.suppress(Exception):
                            await pages.aclose()   # type: ignore[attr-defined]
                    break
                except HttpError as exc:
                    if not exc.limiting:
                        raise
                    if exc.status == 429:
                        await gates.budgets.limited(host)
                    if retried:
                        # Twice in a row: the window has not refilled. The last page's checkpoint
                        # is saved (no completed_at): the archive waits, or pauses.
                        stopped = exc
                        break
                    retried = True
                    wait = gates.host_limiter.limited(host, exc.retry_after)
                    slowed = {"host": host, "timed_out": exc.timed_out, "gap_s": gates.host_limiter.gap(host)}
                    await self._emit_progress(progress_callback,
                                              {"stage": "slowed", "level": "warning", **slowed,
                                               "message": slowed_line(slowed)})
                    await gates.sleep(wait)
                    # The page is asked again from the last recorded checkpoint.
        finally:
            gates.budgets.archive_stopped(host)

        post_stats = self.posts_service.get_source_post_stats(source_id)
        result = {
            **plan,
            "success": True,
            "posts_fetched": total_posts_fetched,
            "pages_fetched": total_pages_fetched,
            "posts_inserted": total_inserted,
            "posts_updated": total_updated,
            "stored_posts": post_stats["post_count"],
            "checkpoint": checkpoint,
        }
        if stopped is not None:
            # Once one window is measured, the wait aims at the refill of the one this limit hit (0107's follow-up).
            refill = gates.budgets.refill_wait(host) if stopped.status == 429 and not stopped.timed_out else None
            return await self._stopped(source_id, kind, plan, result, host, stopped,
                                       waits=0 if pages_this_leg else int(carried.get("waits") or 0),
                                       refill_s=refill, progress_callback=progress_callback, record=record)
        result["archive_status"] = derive_archive_status(post_stats["post_count"], plan["available_posts"])
        message = (f"Archive stopped by you after {total_pages_fetched} pages ({total_posts_fetched} posts kept)"
                   if owner_stopped else f"Archive completed with {total_posts_fetched} posts")
        skipped = skipped_counts(checkpoint)
        if not linked:
            # Why it added no more (issue 0130 B4): what its pages skipped, and what was stored already.
            result["unreached"] = {**skipped, "updated": total_updated}
            why = why_line(skipped, total_updated, total_inserted,
                           re_read=not getattr(kind, "skips_stored", False))
            if why and (total_inserted == 0 or any(skipped.values())):
                message += f"; {'nothing new' if not total_inserted else f'{total_inserted} new'}: {why}"
        if reached is not None:
            result["until_reached"] = plan["until"]
            message = (f"Archive reached {horizon:%-d %b %Y} with {total_posts_fetched} posts"
                       f" (its oldest page goes to {reached:%-d %b %Y})")
        elif (not linked and getattr(kind, "LISTS_ONLY_POSTS", False) and total_posts_fetched == 0
              and skipped[SKIP_NO_POST] >= LAYOUT_MIN_PAGES):
            # Every listed entry is a post, and none read as one: the site's layout changed (issue 0130 B2).
            message = layout_changed_line(skipped[SKIP_NO_POST])
            result.update(success=False, layout_changed=True, error=message)
        result["message"] = message
        if linked:
            result["missing"] = list((checkpoint or {}).get("missing") or [])
            listed = len((checkpoint or {}).get("urls") or ())
            message = result["message"] = (f"Fetched {total_posts_fetched} of {plural(listed, 'linked page')}"
                                           + (f"; {len(result['missing'])} not stored (listed)" if result["missing"] else ""))

        await record(source_id, result, mode="archive", kind=kind)
        await self._emit_progress(progress_callback, {
            "stage": "completed",
            "source_type": kind.name,
            "pages_fetched": total_pages_fetched,
            "posts_fetched": total_posts_fetched,
            "posts_inserted": total_inserted,
            "posts_updated": total_updated,
            "stored_posts": post_stats["post_count"],
            "message": message,
            "progress": 100,
        })
        return result

    async def _stopped(self, source_id: str, kind: SourceKind, plan: Dict[str, Any], result: Dict[str, Any],
                       host: str, exc: HttpError, *, waits: int, refill_s: Optional[float] = None,
                       progress_callback: ProgressCallback, record: Any = None) -> Dict[str, Any]:
        """A host refused twice in a row. The archive waits for its window (first 5 min, then
        doubling up to 60 min while no page comes; once one window of the host is measured, until
        the refill of the window this limit hit: `refill_s`, HostBudgets.refill_wait) and the
        scheduler continues it; after
        MAX_WAITS waits with no page gained it pauses, saying why. Its checkpoint is kept either
        way (no completed_at), so Resume continues from it."""
        record = record or self._record_archive_metadata
        progress = {"source_type": kind.name, "pages_fetched": result["pages_fetched"],
                    "posts_fetched": result["posts_fetched"], "level": "warning"}
        if waits >= MAX_WAITS:
            reason = f"{host} {'is still not answering' if exc.timed_out else 'is still limiting us'} after {MAX_WAITS} waits"
            result.update(paused=True, paused_reason=reason, message=f"Paused: {reason}; resume later")
            await record(source_id, {**result, "waiting": None}, mode="archive_progress", kind=kind)
            await self._emit_progress(progress_callback, {"stage": "paused", **progress, "message": result["message"]})
            return result
        ladder = refill_s is None
        wait_s = min(LAST_WAIT_S, FIRST_WAIT_S * 2 ** waits if ladder else refill_s)
        until = self.clock() + timedelta(seconds=wait_s)
        what = f"{host} to answer" if exc.timed_out else f"{host}'s limit"
        result.update(waiting=True, waiting_until=until.isoformat(), waiting_host=host,
                      waiting_reason="timeout" if exc.timed_out else "limit", waits=waits + 1,
                      message=f"Waiting for {what}")
        await record(source_id, {**result, "waiting": {"host": host, "until": until.isoformat(),
                                                       "reason": result["waiting_reason"]}},
                     mode="archive_progress", kind=kind)
        await self._emit_progress(progress_callback, {
            "stage": "waiting", **progress, "host": host, "waiting_until": until.isoformat(), "wait_s": wait_s,
            "timed_out": exc.timed_out, "refill": not ladder,
            "message": f"Waiting for {what}: continues at {until:%H:%M} UTC{'' if ladder else ', when its window refills'}"})
        return result

    async def _gated(self, pages: AsyncIterator[ArchivePage], gates: FetchGates, kind: SourceKind, host: str,
                     delay: float, rate: RateLimit, pages_fetched: int, pace: "_Pace") -> AsyncIterator[ArchivePage]:
        """The kind's pages, each asked for under the same gate slot a fetch takes, so a run and
        an archive on one host are spaced together.

        The kind's pause after the last page (its page delay, or a batch cooldown) is the slot's
        minimum interval, so the wait between two pages is max(host gap, pause, the learned
        budget's pace), never the sum. Before each page the archive keeps out of the way of a
        live fetch of the host that is due (issue 0107).
        """
        while True:
            await pace.yield_to_live()
            pause = rate.delay_after(pages_fetched) if pages_fetched else 0.0
            async with gates.slot(kind.profile, host, per_source_delay_s=max(delay, pause, await pace.gap())):
                try:
                    page = await pages.__anext__()
                except StopAsyncIteration:
                    return
            gates.host_limiter.succeeded(host)
            await pace.succeeded()
            pages_fetched += 1
            yield page

    # ------------------------------------------------------------------ linked, not stored (issue 0084 B)

    def linked_pages(self, source_id: str) -> List[LinkedPage]:
        """The source's own pages that stored posts link and no stored post is (repo_linked)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return linked_not_stored(cur, source_ids=[source_id]).get(str(source_id), [])

    def linked_summary(self, source_id: str) -> Dict[str, Any]:
        """What the Archive section says: how many pages are linked and not stored, whether one fetch
        can read them (the kind reads one page), how long that takes, and whether the source's archive
        pages back so it would hold them (offered first, until it has run). No network."""
        source = self.sources_service.get_source_with_settings(source_id)
        kind = self.kinds.resolve(source)
        pages = self.linked_pages(source_id)
        settings = source.get("settings") or {}
        archive = settings.get("archive") or {}
        support = self._support(kind, settings, self.availability())
        sitemap = archive.get("sitemap_posts")
        smart = archive.get("smart") if isinstance(archive.get("smart"), dict) else {}
        pages_back = support["archivable"] and (kind.available_basis != "feed_window" or bool(smart.get("found_more")) or (
            isinstance(sitemap, int) and not isinstance(sitemap, bool) and sitemap > 0))
        return {
            "count": len(pages),
            # A feed with nothing older to archive still reads its linked pages one by one.
            "readable": bool(getattr(kind, "reads_posts", False)) and not support["unavailable"],
            "estimated_seconds": self._linked_estimate(kind, source, len(pages)),
            "archive_holds": bool(pages_back),
            "archive_ran": bool(archive.get("last_archived_at")) and not archive.get("resume_ready"),
            "pages": [{"url": page.url, "posts": page.posts, "first_linked_at": iso(page.first_linked_at)}
                      for page in pages[:LINKED_SHOWN]],
        }

    def _linked_estimate(self, kind: SourceKind, source: Dict[str, Any], pages: int) -> int:
        """One second a page and every wait between pages, as an archive's estimate (no learned budget)."""
        rate = kind.profile.rate_limit(((source.get("settings") or {}).get("archive") or {}).get("rate_limit"))
        # The fixed floors, not the shared gates: linked_summary runs in a worker thread, with no event loop
        # for FetchGates.shared() (the 0084 B line answered 500 for every source, v10.0.2 review).
        floors = self.gates.host_limiter.host_floors if self.gates else HOST_FLOORS
        return kind.profile.estimate_seconds(pages, rate, float(floors.get(kind.host_key(source), 0.0)))

    async def plan_linked(self, source_id: str) -> Dict[str, Any]:
        """The list a linked fetch reads, as the plan an archive leg runs from: its checkpoint holds
        the pages (never more), so a wait and a continuation read the same list."""
        source = self.sources_service.get_source_with_settings(source_id)
        if not source:
            raise LookupError(f"Source {source_id} not found")
        kind = self.kinds.resolve(source)
        pages = await asyncio.to_thread(self.linked_pages, source_id)
        rate = kind.profile.rate_limit(((source.get("settings") or {}).get("archive") or {}).get("rate_limit"))
        return {
            "source_id": source_id,
            "source_type": kind.name,
            "linked": len(pages),
            "available_posts": None,
            "older_posts": len(pages),
            "estimated_pages": len(pages),
            "estimated_seconds": self._linked_estimate(kind, source, len(pages)),
            "rate_limit": rate.as_settings(),
            "checkpoint": {"mode": LINKED_MODE, "urls": [page.url for page in pages], "next_index": 0,
                           "missing": [], "pages_fetched": 0, "collected_posts": 0},
        }

    async def fetch_linked(self, source_id: str, progress_callback: ProgressCallback = None) -> Dict[str, Any]:
        """Read the source's linked, not stored pages, one each with its own reader (kind.read_post),
        as an archive leg: the same gate slot per page, 0107's budgets and waits. Each is saved as a
        post of the source through the normal save path, so the story job joins it. A kind that can't
        read one page raises KindUnavailable."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise LookupError(f"Source {source_id} not found")
        kind = self.kinds.resolve(source)
        self._check_available(kind)
        if not getattr(kind, "reads_posts", False):
            raise KindUnavailable(CANNOT_READ)
        async with self._kind_session(kind):
            plan = await self.plan_linked(source_id)
            return await self._archive(source_id, source, kind, plan, progress_callback)

    async def _linked_pages(self, kind: SourceKind, source: Dict[str, Any], checkpoint: Dict[str, Any]
                            ) -> AsyncIterator[ArchivePage]:
        """One page per listed address, from the checkpoint's next_index. A host limiting us (429, a
        timeout) raises (the loop waits and asks again from the last checkpoint); a page that fails
        otherwise, or holds no post, is listed in `missing` and never asked again."""
        urls = list(checkpoint.get("urls") or [])
        missing = list(checkpoint.get("missing") or [])
        collected, pages_fetched = resume_counts(checkpoint)
        index = int(checkpoint.get("next_index") or 0)
        while index < len(urls):
            url = urls[index]
            post: Optional[Dict[str, Any]] = None
            try:
                post = await kind.read_post(source, url)  # type: ignore[attr-defined]
                if post is None:
                    missing.append({"url": url, "reason": "no post on the page"})
            except KindUnavailable:
                raise
            except ValueError as exc:   # HttpError, and a request that failed another way
                if isinstance(exc, HttpError) and exc.limiting:
                    raise
                missing.append(_missing(url, exc))
            index += 1
            pages_fetched += 1
            if post is not None:
                post[BACKLOG_KEY] = True   # an older page: never new to you
                collected += 1
            yield ArchivePage([post] if post else [], {
                **checkpoint, "next_index": index, "missing": missing,
                "pages_fetched": pages_fetched, "collected_posts": collected})

    # ------------------------------------------------------------------ persistence

    def _save_posts(self, source_id: str, posts: List[Dict[str, Any]]) -> SaveBatchResult:
        """One save batch for one source's posts (blocking; run it in a thread)."""
        with db.connection(self.db_url) as conn:
            return self.posts_repo.save_batch(conn, [PostDraft(source_id, post) for post in posts])

    async def _record_archive_metadata(
        self, source_id: str, data: Dict[str, Any], mode: str, *, kind: Optional[SourceKind] = None
    ) -> None:
        """Off-loop: the writer is several blocking DB round trips and zero awaits."""
        if kind is None:
            source = self.sources_service.get_source_by_id(source_id) or {}
            kind = self.kinds.by_name(data.get("source_type")) or self.kinds.resolve(source)
        await asyncio.to_thread(self.archive_metadata.record, source_id, kind, data, mode)  # type: ignore[arg-type]

    async def _emit_progress(self, progress_callback: ProgressCallback, payload: Dict[str, Any]) -> None:
        if progress_callback is None:
            return
        result = progress_callback(payload)
        if asyncio.iscoroutine(result):
            await result


def coverage_of(archive: Dict[str, Any], stored: int) -> Optional[Dict[str, Any]]:
    """A feed's coverage line (issue 0143): {stored, estimate, platform, strategy, reasons, exhausted}, from the
    smart archiver's record in settings.archive; None before its ladder looked at the site."""
    from insight_core.ingestion.archive_ladder import reasons

    smart = archive.get("smart") if isinstance(archive.get("smart"), dict) else None
    if smart is None:
        return None
    return {
        "stored": stored,
        "estimate": smart.get("estimate"),
        "platform": smart.get("platform"),
        "strategy": smart.get("strategy"),
        "found_more": bool(smart.get("found_more")),
        "exhausted": bool(smart.get("exhausted")),
        "reasons": reasons(smart),
        "worked": smart.get("worked") or {},
        "web_archive": bool(archive.get("web_archive")),
    }


def archive_service(db_url: str) -> SourceFetchService:
    """The archive service with its real ports: an archive keeps out of the way of its host's due
    live fetches (issue 0107). The API's registry and the scheduler each build one."""
    from insight_core.ingestion.ports import DbLiveFetchDue

    from insight_core.ingestion.http import KindHttp as _Http
    from insight_core.ingestion.source_doctor import DbDoctorStore, SourceDoctor
    from insight_core.services.source_config_sync_service import SourceConfigSyncService

    service = SourceFetchService(db_url)
    service.live_fetch_due = DbLiveFetchDue(db_url, service.kinds)
    # A feed that answers 404 while archiving wakes the doctor, as a live fetch's does (issue 0130 B3); its look
    # uses the Add source dialog's short timeout, and a switch keeps sources.json in step (issue 0036).
    service.doctor = SourceDoctor(http=_Http(timeout=5), registry=service.kinds, clock=service.clock,
                                  store=DbDoctorStore(db_url, switch=SourceConfigSyncService(db_url).switch_source))
    return service


class FeedMoved(ValueError):
    """An archive's feed answered 404/410 (or no feed), and the source doctor looked (issue 0130 B3)."""


class _Pace:
    """One archive leg's pace against its host (issue 0107): the learned budget's gap between
    pages, the events that say so, and keeping out of the way of a due live fetch."""

    def __init__(self, service: SourceFetchService, gates: FetchGates, host: str, progress: ProgressCallback) -> None:
        self.service, self.gates, self.host, self.progress = service, gates, host, progress
        self.announced: Optional[int] = None    # the learned gap last said in an event
        self.last_live_check: Optional[float] = None

    async def gap(self) -> float:
        learned = self.gates.budgets.learned(self.host)
        if learned is None:
            return 0.0
        gap = learned.archive_gap_s()
        if round(gap) != self.announced:
            self.announced = round(gap)
            await self.service._emit_progress(self.progress, {
                "stage": "pacing", "host": self.host, "archive_gap_s": round(gap, 1), **_budget_fields(learned),
                "message": f"Pacing to 80% of {learned.line()}: one page every {round(gap)} s"})
        return gap

    async def succeeded(self) -> None:
        measured = await self.gates.budgets.succeeded(self.host)
        if measured is None:
            return
        learned = self.gates.budgets.learned(self.host)
        message = measured.line()
        if learned is not None:
            self.announced = round(learned.archive_gap_s())
            message += f"; pacing to 80%: one page every {self.announced} s"
        await self.service._emit_progress(self.progress, {
            "stage": "learned", "host": self.host, **_budget_fields(measured),
            "archive_gap_s": round(learned.archive_gap_s(), 1) if learned else None, "message": message})

    async def yield_to_live(self) -> None:
        due_now = self.service.live_fetch_due
        if due_now is None:
            return
        now = self.gates.clock()
        if self.last_live_check is not None and now - self.last_live_check < LIVE_CHECK_S:
            return
        self.last_live_check = now
        if not await asyncio.to_thread(due_now, self.host):
            return
        await self.service._emit_progress(self.progress, {
            "stage": "yielding", "host": self.host, "message": f"Making room for {self.host}'s live fetches"})
        waited = 0
        while waited < LIVE_YIELD_MAX_S:
            await self.gates.sleep(LIVE_YIELD_STEP_S)
            waited += LIVE_YIELD_STEP_S
            if not await asyncio.to_thread(due_now, self.host):
                break
        self.last_live_check = self.gates.clock()


async def _no_record(*_args: Any, **_kwargs: Any) -> None:
    """A linked fetch writes nothing into settings.archive (its job holds its list and its result)."""


def _missing(url: str, exc: Exception) -> Dict[str, Any]:
    """A page not stored, and why: its HTTP status when it has one (404, 410: gone)."""
    status = getattr(exc, "status", None)
    if status is None:
        found = re.match(r"HTTP (\d{3})", str(exc))
        status = int(found.group(1)) if found else None
    return ({"url": url, "reason": f"HTTP {status}", "status": status} if status
            else {"url": url, "reason": str(exc)[:120]})


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _budget_fields(budget: Any) -> Dict[str, Any]:
    return {"requests": budget.requests, "window_s": budget.window_s, "limits": budget.limits}
