"""Source kinds: one adapter per fetch strategy, resolved once per source by KindRegistry.

Must stay import-light (see ingestion/__init__.py): adapters/*.py import kinds.base, so
KindRegistry.default imports the adapters and the concrete kinds inside the function.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Sequence

if TYPE_CHECKING:
    from insight_core.ingestion.http import KindHttp
    from insight_core.ingestion.kinds.base import Source, SourceKind


class KindRegistry:
    """Resolves a source to its kind: first match in priority order, cached per source."""

    def __init__(self, kinds: Sequence["SourceKind"]) -> None:
        self.kinds = tuple(kinds)
        self._cache: dict[tuple[str, str], "SourceKind"] = {}

    def resolve(self, source: "Source") -> "SourceKind":
        key = (str(source.get("platform") or ""), str(source.get("handle_or_url") or ""))
        kind = self._cache.get(key)
        if kind is None:
            kind = next((k for k in self.kinds if k.matches(source)), None)
            if kind is None:
                raise LookupError(f"No source kind matches {key}")
            self._cache[key] = kind
        return kind

    def by_name(self, name: Optional[str]) -> Optional["SourceKind"]:
        return next((k for k in self.kinds if k.name == name), None)

    @staticmethod
    def default(http: "KindHttp", youtube: Any) -> "KindRegistry":
        """The real kinds in resolution priority (spec §D.1); generic_rss is the fallback."""
        from insight_core.adapters import ADAPTER_CLASSES
        from insight_core.ingestion.kinds.generic_rss import GenericRssKind
        from insight_core.ingestion.kinds.nitter_rss import NitterRssKind
        from insight_core.ingestion.kinds.reddit import RedditKind
        from insight_core.ingestion.kinds.telegram_mtproto import TelegramKind
        from insight_core.ingestion.kinds.telegram_rss import TelegramRssKind
        from insight_core.ingestion.kinds.youtube import YouTubeKind

        return KindRegistry([
            *(adapter_class(http) for adapter_class in ADAPTER_CLASSES),
            RedditKind(http),
            YouTubeKind(youtube),
            TelegramRssKind(http),
            NitterRssKind(http),
            TelegramKind(http=http),
            GenericRssKind(http),
        ])


__all__ = ["KindRegistry"]
