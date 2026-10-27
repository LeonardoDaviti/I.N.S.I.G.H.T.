"""
Archive planning and execution for DB-backed sources (Mark IX).

Fetching lives behind the source-kind seam (insight_core/ingestion/kinds), and every live
fetch goes through the ingestion runner (insight_core/ingestion). This service keeps:
- plan_archive / archive_source: one loop over kind.archive_pages, paced by
  kind.profile.rate_limit(persisted settings, request overrides) and by the same
  FetchGates.slot per page a fetch takes; every page is one save batch. A host that limits
  us (429) or times out is waited out and the page retried once from the last checkpoint;
  twice in a row pauses the archive with its checkpoint kept (issue 0016). An unavailable
  kind (yt-dlp off, no Telegram session) raises KindUnavailable before any planning (the API answers 409). Both run inside the
  kind's session (B8: telegram_mtproto connects and checks authorisation; every other kind
  has a no-op session), so a session that cannot open is the same 409.

settings["archive"] is written by ingestion.archive_metadata.ArchiveMetadataWriter.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, List, Optional

from insight_core.db import database as db

from insight_core.db.repo_posts import PostDraft, PostsRepository, SaveBatchResult
from insight_core.ingestion.archive_metadata import (
    ArchiveMetadataWriter,
    archive_estimate,
    derive_archive_status,
    resumable,
)
from insight_core.ingestion.gates import FetchGates
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import ArchivePage, KindUnavailable, RateLimit, SourceKind, resume_counts
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
        for source in self.sources_service.get_all_sources_with_settings():
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
        reads; an unmeasured feed stays archivable so a plan can measure it.
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
        }
        reason = unavailable_reason(kind.profile, availability)
        if reason is not None:
            return {**support, "archivable": False, "reason": reason, "unavailable": True}
        if kind.archive_refused:
            return {**support, "archivable": False, "reason": kind.archive_refused}
        if kind.available_basis == "feed_window":
            available = (settings.get("archive") or {}).get("available_posts")
            if isinstance(available, int) and not isinstance(available, bool) and available <= live_fetch_limit:
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
        async with self._kind_session(kind):
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
    ) -> Dict[str, Any]:
        """Archive a source's posts older than the stored ones, until the source ends."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise LookupError(f"Source {source_id} not found")

        kind = self.kinds.resolve(source)
        self._check_available(kind)
        async with self._kind_session(kind):
            plan = await self._plan(source_id, source, kind, resume=resume,
                                    rate_limit_overrides=rate_limit_overrides)
            return await self._archive(source_id, source, kind, plan, progress_callback)

    async def _archive(
        self,
        source_id: str,
        source: Dict[str, Any],
        kind: SourceKind,
        plan: Dict[str, Any],
        progress_callback: ProgressCallback,
    ) -> Dict[str, Any]:
        """One loop over kind.archive_pages from the plan's checkpoint (its measurement reused)."""
        rate = kind.profile.rate_limit(plan.get("rate_limit"))
        # An archive has no limit: a kind stops where the source ends. The target only caps
        # the count, at the source's size when it reports one.
        available = plan.get("available_posts")
        target_posts = available if isinstance(available, int) else UNBOUNDED_ARCHIVE
        older_posts = plan.get("older_posts")
        start_checkpoint = plan.get("checkpoint")
        resume_collected_posts, total_pages_fetched = resume_counts(start_checkpoint)
        total_posts_fetched = total_inserted = total_updated = 0
        await self._emit_progress(progress_callback, {
            "stage": "planning_complete",
            "source_type": kind.name,
            "older_posts": older_posts,
            "estimated_pages": plan.get("estimated_pages"),
            "estimated_seconds": plan.get("estimated_seconds"),
            "message": "Planning complete: " + (
                "size unknown" if older_posts is None else f"about {older_posts} older posts"),
            "progress": 0.0,
        })

        if older_posts == 0:
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
                "message": "The archive already reaches the source's oldest post",
            }
            await self._record_archive_metadata(source_id, result, mode="archive", kind=kind)
            return result

        gates = self.gates or FetchGates.shared()
        host = kind.host_key(source)
        delay = (source.get("settings") or {}).get("fetch_delay_seconds") or 0
        checkpoint = start_checkpoint
        retried = False
        paused_reason: Optional[str] = None
        while True:
            pages = kind.archive_pages(source, target_posts, checkpoint, rate)
            try:
                async for page in self._gated(pages, gates, kind, host, delay, rate, total_pages_fetched):
                    retried = False
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

                    await self._record_archive_metadata(source_id, {
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
                        "message": f"Fetched {kind.name} page {total_pages_fetched}",
                    })
                break
            except HttpError as exc:
                if not exc.limiting:
                    raise
                if retried:
                    # Twice in a row: pause. The last page's checkpoint is saved (no
                    # completed_at), so Resume continues from it.
                    paused_reason = f"{host} {'is not answering' if exc.timed_out else 'is limiting us'}"
                    break
                retried = True
                wait = gates.host_limiter.limited(host, exc.retry_after)
                slowed = {"host": host, "timed_out": exc.timed_out, "gap_s": gates.host_limiter.gap(host)}
                await self._emit_progress(progress_callback,
                                          {"stage": "slowed", "level": "warning", **slowed,
                                           "message": slowed_line(slowed)})
                await gates.sleep(wait)
                # The page is asked again from the last recorded checkpoint.

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
        if paused_reason is not None:
            # Not recorded as a finished archive: the checkpoint gets no completed_at.
            result.update(paused=True, paused_reason=paused_reason, message=f"Paused: {paused_reason}; resume later")
            await self._emit_progress(progress_callback, {
                "stage": "paused",
                "level": "warning",
                "source_type": kind.name,
                "pages_fetched": total_pages_fetched,
                "posts_fetched": total_posts_fetched,
                "message": result["message"],
            })
            return result
        result["archive_status"] = derive_archive_status(post_stats["post_count"], plan["available_posts"])

        await self._record_archive_metadata(source_id, result, mode="archive", kind=kind)
        await self._emit_progress(progress_callback, {
            "stage": "completed",
            "source_type": kind.name,
            "pages_fetched": total_pages_fetched,
            "posts_fetched": total_posts_fetched,
            "posts_inserted": total_inserted,
            "posts_updated": total_updated,
            "stored_posts": post_stats["post_count"],
            "message": f"Archive completed with {total_posts_fetched} posts",
            "progress": 100,
        })
        return result

    @staticmethod
    async def _gated(pages: AsyncIterator[ArchivePage], gates: FetchGates, kind: SourceKind, host: str,
                     delay: float, rate: RateLimit, pages_fetched: int) -> AsyncIterator[ArchivePage]:
        """The kind's pages, each asked for under the same gate slot a fetch takes, so a run and
        an archive on one host are spaced together.

        The kind's pause after the last page (its page delay, or a batch cooldown) is the slot's
        minimum interval, so the wait between two pages is max(host gap, pause), never the sum.
        """
        while True:
            pause = rate.delay_after(pages_fetched) if pages_fetched else 0.0
            async with gates.slot(kind.profile, host, per_source_delay_s=max(delay, pause)):
                try:
                    page = await pages.__anext__()
                except StopAsyncIteration:
                    return
            gates.host_limiter.succeeded(host)
            pages_fetched += 1
            yield page

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
