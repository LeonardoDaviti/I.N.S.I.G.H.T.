"""DbInspectionRefresher: the live-fetch archive-metadata record (spec §A.2 step 10).

After a run, every source that fetched records the cheap half of its archive metadata:
its kind (source_type), the posts this fetch read, the stored post count and the live
fetch time (ArchiveMetadataWriter.record mode "live"). It never measures the source: only
planning an archive does (issue 0015), so a run ends when its last source is saved.

Moved from SourceFetchService.record_live_fetch. Never raises.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Mapping

from insight_core.ingestion.kinds.base import SourceKind

logger = logging.getLogger("insight.ingestion.inspection")


class DbInspectionRefresher:
    """ArchiveMetadataWriter.record(mode="live") for one fetched source, off the loop."""

    def __init__(self, *, writer: Any) -> None:   # ArchiveMetadataWriter (record(source_id, kind, data, mode))
        self.writer = writer

    async def refresh(self, source: Mapping[str, Any], kind: SourceKind, fetched_posts: int) -> None:
        data = {"source_type": kind.name, "posts_fetched": fetched_posts}
        try:
            await asyncio.to_thread(self.writer.record, str(source.get("id")), kind, data, "live")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Archive metadata write failed for %s: %s", source.get("handle_or_url"), exc)

    async def recognised(self, source: Mapping[str, Any], settings: Mapping[str, Any]) -> None:
        """What a fetch learned the source is (issue 0167: {"substack": True}), merged into its settings when they
        don't say so already: its next fetch reads it by that kind. Never raises."""
        current = source.get("settings") or {}
        if all(current.get(key) == value for key, value in settings.items()):
            return
        try:
            await asyncio.to_thread(self.writer.sources.merge_source_settings, str(source.get("id")), dict(settings))
            logger.info("%s is %s: its settings say so now", source.get("handle_or_url"), dict(settings))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record what %s is: %s", source.get("handle_or_url"), exc)
