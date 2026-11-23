"""saved: the built-in Saved source (platform "saved"), the pages the owner saves from any site.

Created by the first save (services/saved_service.py). Its posts come by hand, so it never fetches (never due, even
forced; never failing) and has no archive.
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
