"""Base contract for source-specific archive adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple


class BaseSourceAdapter(ABC):
    """Shared contract for non-standard source acquisition paths."""

    adapter_type = "base"

    def __init__(self, service: Any):
        self.service = service

    @abstractmethod
    def matches(self, source: Dict[str, Any]) -> bool:
        """Return True when the adapter owns the source."""

    @abstractmethod
    async def inspect_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        """Inspect the source and report archive capabilities."""

    @abstractmethod
    async def fetch_live_posts(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        """Fetch the latest items for regular ingestion."""

    @abstractmethod
    async def archive_posts(
        self,
        source: Dict[str, Any],
        target_posts: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
        *,
        checkpoint: Optional[Dict[str, Any]] = None,
        initial_collected: int = 0,
        initial_pages_fetched: int = 0,
        page_callback: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]], Awaitable[None] | None]] = None,
        rate_limit: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
        """Archive posts using an adapter-specific strategy."""

    def default_rate_limit(self) -> Dict[str, Any]:
        return {"page_delay_seconds": 1}

    def checkpoint_is_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict)

    def estimate_seconds(self, estimated_pages: int, rate_limit: Optional[Dict[str, Any]] = None) -> int:
        if estimated_pages <= 0:
            return 0
        page_delay = int((rate_limit or {}).get("page_delay_seconds", self.default_rate_limit().get("page_delay_seconds", 1)))
        return estimated_pages + max(0, estimated_pages - 1) * page_delay
