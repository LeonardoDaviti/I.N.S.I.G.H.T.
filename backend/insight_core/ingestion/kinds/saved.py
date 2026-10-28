"""saved: the built-in Saved source, the pages the owner saves from any site (issue 0031).

One source, platform "saved", handle "Saved" (its name), created by the first save
(services/saved_service.py). Its posts come by hand, one page at a time, so the kind never
fetches: its profile says so and decide_fetch never finds it due, not even forced, so it is
never due and never failing. It has no archive.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from insight_core.ingestion.kinds.base import BaseKind, Inspection, PolitenessProfile, Source

PLATFORM = "saved"
HANDLE = "Saved"


class SavedKind(BaseKind):
    name = "saved"
    profile = PolitenessProfile(concurrency_pool="host-lock", fetches=False)
    available_basis = "unknown"
    archive_refused = "Saved pages come one at a time, from the bookmarklet or ⌘K: there is nothing to archive."

    def matches(self, source: Source) -> bool:
        return source.get("platform") == PLATFORM

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        return []

    async def inspect(self, source: Source) -> Inspection:
        return Inspection(None, None, None)

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: Any):
        return
        yield  # pragma: no cover - an empty async generator


__all__ = ["HANDLE", "PLATFORM", "SavedKind"]
