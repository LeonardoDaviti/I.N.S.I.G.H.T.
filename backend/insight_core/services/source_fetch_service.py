"""
Archive planning and execution for DB-backed sources (Mark IX).

Fetching lives behind the source-kind seam (insight_core/ingestion/kinds), and every live
fetch goes through the ingestion runner (insight_core/ingestion). This service keeps:
- plan_archive / archive_source: one loop over kind.archive_pages, paced by
  kind.profile.rate_limit(persisted settings, request overrides); every page is a save
  batch followed by enrichment. An unavailable kind (yt-dlp off, no Telegram session)
  raises KindUnavailable before any planning (the API answers 409).
- fetch_reddit_comments_for_post for the post detail page

settings["archive"] is written by ingestion.archive_metadata.ArchiveMetadataWriter.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

import psycopg

from insight_core.db.repo_posts import PostDraft, PostsRepository, SaveBatchResult
from insight_core.ingestion.archive_metadata import ArchiveMetadataWriter, derive_archive_status
from insight_core.ingestion.enrichment import Enricher
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.base import KindUnavailable, SourceKind, resume_counts
from insight_core.ingestion.kinds.reddit import fetch_reddit_comments
from insight_core.ingestion.schedule import Availability, availability_from_env, unavailable_reason
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.entity_memory_service import EntityMemoryService
from insight_core.services.event_memory_service import EventMemoryService
from insight_core.services.posts_service import PostsService
from insight_core.services.sources_service import SourcesService
from insight_core.services.youtube_service import YouTubeService

ProgressCallback = Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]]


class SourceFetchService:
    """Archive service for DB-backed sources; fetches go through the source kinds."""

    def __init__(
        self,
        db_url: str,
        *,
        http: Optional[KindHttp] = None,
        kinds: Optional[KindRegistry] = None,
        availability: Callable[[], Availability] = availability_from_env,
    ):
        self.db_url = db_url
        self.sources_service = SourcesService(db_url)
        self.posts_service = PostsService(db_url)
        self.posts_repo = PostsRepository(db_url)
        self.memory_service = EntityMemoryService(db_url)
        self.event_service = EventMemoryService(db_url)
        self.youtube_service = YouTubeService(db_url)
        self.logger = get_component_logger("source_fetch_service")
        self.http = http or KindHttp()
        self.kinds = kinds or KindRegistry.default(self.http, self.youtube_service)
        self.archive_metadata = ArchiveMetadataWriter(posts=self.posts_service, sources=self.sources_service)
        self.enricher = Enricher(self.memory_service, self.event_service)
        self.availability = availability

    # ------------------------------------------------------------------ kinds

    async def _inspect(self, kind: SourceKind, source: Dict[str, Any]) -> Dict[str, Any]:
        inspection = await kind.inspect(source)
        source_settings = source.get("settings") or {}
        return {
            **inspection.as_dict(),
            "source_type": kind.name,
            "display_name": source_settings.get("display_name") or source["handle_or_url"],
        }

    # ------------------------------------------------------------------ archive

    async def plan_archive(
        self,
        source_id: str,
        desired_posts: Optional[int] = None,
        *,
        resume: bool = True,
        rate_limit_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Inspect a source and estimate archive effort."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        kind = self.kinds.resolve(source)
        # E7: the archive honours the same availability switch as every live fetch.
        reason = unavailable_reason(kind.profile, self.availability())
        if reason is not None:
            raise KindUnavailable(reason)
        inspection = await self._inspect(kind, source)
        source_with_settings = self.sources_service.get_source_with_settings(source_id)
        current_archive = (source_with_settings.get("settings") or {}).get("archive", {})
        # Profile defaults <- the persisted rate limit <- this request's overrides.
        rate = kind.profile.rate_limit(current_archive.get("rate_limit"), rate_limit_overrides)
        checkpoint = current_archive.get("checkpoint") if resume else None
        resume_available = kind.checkpoint_resumable(checkpoint)
        resume_collected_posts = resume_counts(checkpoint)[0] if resume_available else 0
        available = inspection["available_posts"]
        desired = desired_posts or available or (source.get("settings") or {}).get("max_posts_per_fetch", 50)
        desired = min(desired, available or desired)
        remaining_posts = max(0, desired - resume_collected_posts)
        estimated_pages = kind.estimate_pages(remaining_posts, inspection["page_size"])

        inspection.update({
            "desired_posts": desired,
            "remaining_posts": remaining_posts,
            "estimated_pages": estimated_pages,
            "estimated_seconds": kind.profile.estimate_seconds(estimated_pages, rate),
            "source_id": source_id,
            "current_stored_posts": self.posts_service.get_source_post_stats(source_id)["post_count"],
            "resume": bool(resume and resume_available),
            "resume_available": resume_available,
            "checkpoint": checkpoint if resume_available else None,
            "rate_limit": rate.as_settings(),
        })

        await self._record_archive_metadata(source_id, inspection, mode="plan", kind=kind)
        return inspection

    async def archive_source(
        self,
        source_id: str,
        desired_posts: Optional[int] = None,
        progress_callback: ProgressCallback = None,
        *,
        resume: bool = True,
        rate_limit_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Archive historical posts for a single source: one loop over kind.archive_pages."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        plan = await self.plan_archive(
            source_id,
            desired_posts,
            resume=resume,
            rate_limit_overrides=rate_limit_overrides,
        )
        kind = self.kinds.resolve(source)
        rate = kind.profile.rate_limit(plan.get("rate_limit"))
        target_posts = plan["desired_posts"]
        start_checkpoint = plan.get("checkpoint") if plan.get("resume") else None
        resume_collected_posts, total_pages_fetched = resume_counts(start_checkpoint)
        total_posts_fetched = total_inserted = total_updated = 0
        await self._emit_progress(progress_callback, {
            "stage": "planning_complete",
            "source_type": kind.name,
            "target_posts": target_posts,
            "remaining_posts": plan.get("remaining_posts", target_posts),
            "estimated_pages": plan.get("estimated_pages"),
            "estimated_seconds": plan.get("estimated_seconds"),
            "message": f"Planning complete for {target_posts} posts",
            "progress": min(100.0, (resume_collected_posts / max(target_posts, 1)) * 100.0),
        })

        if plan.get("remaining_posts", 0) <= 0:
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
                "message": "Archive already covers the requested range",
            }
            await self._record_archive_metadata(source_id, result, mode="archive", kind=kind)
            return result

        checkpoint = start_checkpoint
        async for page in kind.archive_pages(source, target_posts, start_checkpoint, rate):
            if page.posts:
                saved = await self._save_and_enrich(source_id, page.posts)
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
                checkpoint = {"mode": kind.name, "pages_fetched": total_pages_fetched, "collected_posts": collected}

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
                "target_posts": target_posts,
                "progress": min(100.0, (collected / max(target_posts, 1)) * 100.0),
                "message": f"Fetched {kind.name} page {total_pages_fetched}",
            })

        post_stats = self.posts_service.get_source_post_stats(source_id)
        result = {
            **plan,
            "success": True,
            "posts_fetched": total_posts_fetched,
            "pages_fetched": total_pages_fetched,
            "posts_inserted": total_inserted,
            "posts_updated": total_updated,
            "stored_posts": post_stats["post_count"],
            "archive_status": derive_archive_status(post_stats["post_count"], plan["available_posts"]),
            "checkpoint": checkpoint,
        }

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

    # ------------------------------------------------------------------ post detail

    async def fetch_reddit_comments_for_post(self, post_url: str, limit: int = 80) -> List[Dict[str, Any]]:
        """Fetch a Reddit post discussion thread on demand via the public JSON endpoint."""
        return await fetch_reddit_comments(self.http, post_url, limit)

    # ------------------------------------------------------------------ persistence

    def _save_posts(self, source_id: str, posts: List[Dict[str, Any]]) -> SaveBatchResult:
        """One save batch for one source's posts (blocking; run it in a thread)."""
        with psycopg.connect(self.db_url) as conn:
            return self.posts_repo.save_batch(conn, [PostDraft(source_id, post) for post in posts])

    async def _save_and_enrich(self, source_id: str, posts: List[Dict[str, Any]]) -> SaveBatchResult:
        """save_batch off the loop, then enrichment over the posts it inserted."""
        saved = await asyncio.to_thread(self._save_posts, source_id, posts)
        await self.enricher.run(saved.inserted_posts)
        return saved

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
