"""ArchiveMetadataWriter: persists settings.archive for a source.

Every derived number (backlog, estimated pages and seconds, resumability) depends on the kind, an explicit argument.
Stores are taken by duck type so ingestion/ does not import services/.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Literal, Optional

from insight_core.ingestion.archive_ladder import coverage_status
from insight_core.ingestion.gates import HOST_FLOORS
from insight_core.ingestion.kinds.base import RateLimit, Source, SourceKind

Mode = Literal["plan", "archive", "archive_progress", "live"]
HISTORY_LIMIT = 40


def resumable(kind: SourceKind, checkpoint: Any) -> Optional[Dict[str, Any]]:
    """The checkpoint an archive can resume from, or None. A finished archive's checkpoint
    (completed_at) never resumes: the next archive continues below the stored posts instead."""
    if isinstance(checkpoint, dict) and not checkpoint.get("completed_at") and kind.checkpoint_resumable(checkpoint):
        return checkpoint
    return None


def archive_estimate(kind: SourceKind, source: Source, available_posts: Any, stored: int,
                     page_size: Optional[int], rate: RateLimit) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """(older posts, pages, seconds) for an archive of the posts older than the stored ones; all None when the
    source reports no size. Each wait between pages is max(host gap, the kind's pause), as the gate slot waits."""
    if isinstance(available_posts, bool) or not isinstance(available_posts, int) or available_posts < 0:
        return None, None, None
    older = max(0, available_posts - stored)
    pages = kind.estimate_pages(older, page_size)
    return older, pages, kind.profile.estimate_seconds(pages, rate, HOST_FLOORS.get(kind.host_key(source), 0.0))


def derive_archive_status(stored_posts: int, available_posts: Optional[int]) -> str:
    if stored_posts <= 0:
        return "not_archived"
    if available_posts and stored_posts >= available_posts:
        return "archived"
    return "partial"


class ArchiveMetadataWriter:
    def __init__(self, *, posts: Any, sources: Any, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.posts = posts
        self.sources = sources
        self.clock = clock

    def record(self, source_id: str, kind: SourceKind, data: Dict[str, Any], mode: Mode) -> None:
        """Merge one plan / archive / archive-progress / live-fetch observation into settings.archive."""
        # the count alone, kept or live (one per fetched source and per archive page: never the dates' aggregate)
        stored = int(self.posts.post_count(source_id))
        source = self.sources.get_source_by_id(source_id)
        merged_settings = self.sources.get_source_with_settings(source_id)["settings"] if source else {}
        current = (merged_settings or {}).get("archive", {})
        now = self.clock().isoformat()

        # what is left to archive, derived on every path so it falls as posts come in; None when the size is unknown
        available_posts = data.get("available_posts", current.get("available_posts"))
        backlog_posts, estimated_pages, estimated_seconds = archive_estimate(
            kind, source or {}, available_posts, stored, data.get("page_size", current.get("page_size")) or 1,
            kind.profile.rate_limit(data.get("rate_limit", current.get("rate_limit"))))

        smart = self._smart(kind, current, data, mode)
        status = current.get("status", "not_archived")
        if smart is not None:
            # a feed's coverage (archive_ladder.coverage_status); a plan that found more makes it partial at once
            status = coverage_status(stored, smart)
        elif mode in {"archive", "archive_progress"}:
            status = derive_archive_status(stored, data.get("available_posts"))
        elif mode == "live" and isinstance(available_posts, int):
            status = derive_archive_status(stored, available_posts)

        history = list(current.get("history") or [])
        if mode in {"plan", "archive", "live"}:
            history.append(self._history_event(mode, stored, data, now))
        checkpoint = self._prepare_checkpoint(current, data, mode, now)

        archive = {
            "status": status,
            "stored_posts": stored,
            "available_posts": data.get("available_posts", current.get("available_posts")),
            "first_post_date": data.get("first_post_date", current.get("first_post_date")),
            "last_archived_at": now if mode == "archive" else current.get("last_archived_at"),
            "last_live_fetch_at": now if mode == "live" else current.get("last_live_fetch_at"),
            # When the source was last measured: planning an archive is the only measurement.
            "last_inspected_at": now if mode == "plan" else current.get("last_inspected_at"),
            "source_type": kind.name,
            "page_size": data.get("page_size", current.get("page_size")),
            "estimated_pages": estimated_pages if estimated_pages is not None else current.get("estimated_pages"),
            "estimated_seconds": estimated_seconds if estimated_seconds is not None else current.get("estimated_seconds"),
            "last_pages_fetched": data.get("pages_fetched", current.get("last_pages_fetched")),
            "backlog_posts": backlog_posts,
            "rate_limit": data.get("rate_limit", current.get("rate_limit")),
            "checkpoint": checkpoint,
            "resume_ready": resumable(kind, checkpoint) is not None,
            # {host, until} while the archive waits out a host's limit; a page, a pause or the end clears it
            "waiting": (data.get("waiting") if mode in {"archive", "archive_progress"}
                        else current.get("waiting")),
            "history": history[-HISTORY_LIMIT:],
            # why the last archive added no more (its skipped counts), and the date it stopped at
            "unreached": data.get("unreached", current.get("unreached")) if mode == "archive" else current.get("unreached"),
            "until": (data.get("until_reached") if mode == "archive" else current.get("until")),
        }
        if smart is not None:
            archive["smart"] = smart
        # what a feed's plan measured besides (its sitemap posts): kept for archive_support
        for key in ("sitemap_posts", "sitemap_prefix"):
            if mode == "plan" and key in data:
                archive[key] = data[key]
            elif mode == "plan" and smart is not None:
                archive[key] = None
        self.sources.merge_source_settings(source_id, {"archive": archive})

    @staticmethod
    def _smart(kind: SourceKind, current: Dict[str, Any], data: Dict[str, Any], mode: Mode) -> Optional[Dict[str, Any]]:
        """The smart archiver's record: the plan's (data["smart"]), else the one kept; exhausted when an archive ended
        with no strategy left. None for a kind without one."""
        smart = data.get("smart") if isinstance(data.get("smart"), dict) else current.get("smart")
        if not isinstance(smart, dict):
            return None
        smart = dict(smart)
        if mode == "archive" and not data.get("until_reached") and not data.get("paused") and not data.get("waiting") \
                and data.get("success", True):
            checkpoint = data.get("checkpoint")
            smart["exhausted"] = not (isinstance(checkpoint, dict) and kind.checkpoint_resumable(checkpoint))
            ladder = checkpoint.get("ladder") if isinstance(checkpoint, dict) else None
            if isinstance(ladder, dict) and isinstance(ladder.get("worked"), dict):
                smart["worked"] = ladder["worked"]
        elif mode == "plan" and isinstance(data.get("smart"), dict):
            smart["exhausted"] = False
        return smart

    @staticmethod
    def _prepare_checkpoint(current: Dict[str, Any], data: Dict[str, Any], mode: Mode, now: str) -> Optional[Dict[str, Any]]:
        if mode == "archive_progress":
            checkpoint = data.get("checkpoint")
            return dict(checkpoint) if isinstance(checkpoint, dict) else current.get("checkpoint")
        if mode == "archive":
            checkpoint = data.get("checkpoint")
            if not isinstance(checkpoint, dict):
                return None
            if data.get("until_reached") and data.get("pages_fetched"):
                # stopped at its date, not at the source's end: a later archive goes on from here
                return dict(checkpoint)
            finished = dict(checkpoint)
            finished["completed_at"] = now
            if data.get("archive_status") == "archived":
                finished["completed"] = True
            return finished
        return current.get("checkpoint")

    @staticmethod
    def _history_event(mode: Mode, stored: int, data: Dict[str, Any], now: str) -> Dict[str, Any]:
        return {
            "at": now,
            "mode": mode,
            "status": data.get("archive_status") or data.get("status"),
            "stored_posts": stored,
            "available_posts": data.get("available_posts"),
            "pages_fetched": data.get("pages_fetched"),
            "source_type": data.get("source_type"),
        }
