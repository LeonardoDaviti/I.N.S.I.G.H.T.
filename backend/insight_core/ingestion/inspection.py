"""DbInspectionRefresher: the live-fetch archive-metadata record, plus what a fetch learned about its source.

After a run each fetched source records the cheap half of its archive metadata (ArchiveMetadataWriter.record mode
"live"); it never measures the source (only planning an archive does). Never raises.
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

    async def named(self, source: Mapping[str, Any], title: str) -> None:
        """What the feed calls itself (source_names.clean_name), as the name of a source that has none; a name the
        owner set is never written over. Never raises."""
        from insight_core.ingestion.source_names import clean_name

        if str((source.get("settings") or {}).get("display_name") or "").strip():
            return
        name = clean_name(title, str(source.get("handle_or_url") or ""))
        if not name:
            return
        try:
            await asyncio.to_thread(self.writer.sources.name_if_unnamed, str(source.get("id")), name)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not name %s: %s", source.get("handle_or_url"), exc)

    async def recognised(self, source: Mapping[str, Any], settings: Mapping[str, Any]) -> None:
        """What a fetch learned the source is ({"substack": True}), merged into its settings when they don't say so
        already. Never raises."""
        current = source.get("settings") or {}
        if all(current.get(key) == value for key, value in settings.items()):
            return
        try:
            await asyncio.to_thread(self.writer.sources.merge_source_settings, str(source.get("id")), dict(settings))
            logger.info("%s is %s: its settings say so now", source.get("handle_or_url"), dict(settings))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record what %s is: %s", source.get("handle_or_url"), exc)
