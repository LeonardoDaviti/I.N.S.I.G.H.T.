"""DbInspectionRefresher: the live-fetch archive-metadata refresh (spec §A.2 step 10).

Re-inspecting a source is a second full fetch of it (a feed re-download, or an unbounded
yt-dlp channel dump for YouTube), so it runs on one global cadence,
ARCHIVE_INSPECT_INTERVAL_HOURS, tracked by settings.archive.last_inspected_at - distinct
from last_live_fetch_at, which updates every run and so cannot gate anything. The cheap
half (stored post count, live-fetch time) is recorded on every call.

kind.inspect runs under the same FetchGates.slot as the fetch, for the same reasons: the
yt-dlp budget and the host floors apply to an inspection exactly as to a fetch.

Moved from SourceFetchService.record_live_fetch / _archive_inspection_due. Never raises.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from insight_core.ingestion.kinds.base import SourceKind
from insight_core.utils.env import env_float

logger = logging.getLogger("insight.ingestion.inspection")


# 0 restores the Mark VIII every-run behaviour.
ARCHIVE_INSPECT_INTERVAL_HOURS = env_float("INSIGHT_ARCHIVE_INSPECT_INTERVAL_HOURS", 168)


def _refresh_enabled() -> bool:
    # Renamed from SAFE_INGEST_REFRESH_ARCHIVE_METADATA (still read as a fallback).
    value = os.getenv("INSIGHT_REFRESH_ARCHIVE_METADATA", os.getenv("SAFE_INGEST_REFRESH_ARCHIVE_METADATA", "1"))
    return value.strip() != "0"


def inspection_due(source: Mapping[str, Any], now: datetime, interval_hours: float) -> bool:
    """Has it been long enough to re-measure this source's archive size?"""
    if interval_hours <= 0:
        return True
    last = ((source.get("settings") or {}).get("archive") or {}).get("last_inspected_at")
    if not last:
        return True
    try:
        at = datetime.fromisoformat(str(last))
    except (TypeError, ValueError):
        return True  # Unreadable timestamp: measure rather than skip forever.
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    return (now - at).total_seconds() / 3600 >= interval_hours


class DbInspectionRefresher:
    """Due check + kind.inspect under gates.slot + ArchiveMetadataWriter.record(mode="live")."""

    def __init__(
        self,
        *,
        writer: Any,                      # ArchiveMetadataWriter (record(source_id, kind, data, mode))
        gates: Any,                       # FetchGates
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        interval_hours: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.writer = writer
        self.gates = gates
        self.clock = clock
        self.interval_hours = ARCHIVE_INSPECT_INTERVAL_HOURS if interval_hours is None else interval_hours
        self.enabled = _refresh_enabled() if enabled is None else enabled

    async def refresh(self, source: Mapping[str, Any], kind: SourceKind, fetched_posts: int) -> None:
        if not self.enabled:
            return
        source_id = str(source.get("id"))
        settings = source.get("settings") or {}
        data: dict[str, Any] = {}
        if inspection_due(source, self.clock(), self.interval_hours):
            try:
                async with self.gates.slot(kind.profile, kind.host_key(source),
                                           per_source_delay_s=settings.get("fetch_delay_seconds") or 0):
                    inspection = await kind.inspect(source)
                data = {
                    **inspection.as_dict(),
                    "display_name": settings.get("display_name") or source.get("handle_or_url"),
                    "inspected": True,
                }
            except Exception as exc:  # noqa: BLE001
                # Record the cheap half anyway: skipping it froze the stored post count on
                # exactly the sources whose inspection fails.
                logger.warning("Archive inspection failed for %s: %s", source.get("handle_or_url"), exc)
                data = {}
        data["source_type"] = kind.name
        data["posts_fetched"] = fetched_posts
        try:
            await asyncio.to_thread(self.writer.record, source_id, kind, data, "live")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Archive metadata write failed for %s: %s", source.get("handle_or_url"), exc)
