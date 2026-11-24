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
    """Resolves a source to its kind: first match in priority order, cached by what kinds match on (platform,
    address, whether settings.page_watch is set), so a source switched to follow a page gets page_watch.
    """

    def __init__(self, kinds: Sequence["SourceKind"]) -> None:
        self.kinds = tuple(kinds)
        self._cache: dict[tuple[str, str, bool], "SourceKind"] = {}

    def resolve(self, source: "Source") -> "SourceKind":
        key = (str(source.get("platform") or ""), str(source.get("handle_or_url") or ""),
               isinstance((source.get("settings") or {}).get("page_watch"), dict))
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
    def default(http: "KindHttp", youtube: Any, *, db_url: Optional[str] = None) -> "KindRegistry":
        """The real kinds in resolution priority; generic_rss is the fallback. saved and page_watch come first (the
        Saved source is no feed; settings.page_watch is an explicit choice). With db_url, generic_rss and page_watch
        read the article page of new posts only; without it, of every teaser they fetch.
        """
        from insight_core.adapters import ADAPTER_CLASSES
        from insight_core.db.repo_posts import PostsRepository
        from insight_core.ingestion.kinds.bluesky import BlueskyKind
        from insight_core.ingestion.kinds.forum import ForumKind
        from insight_core.ingestion.kinds.generic_rss import GenericRssKind, LearnedLadder
        from insight_core.ingestion.kinds.nitter_rss import NitterRssKind
        from insight_core.ingestion.kinds.page_watch import PageWatchKind
        from insight_core.ingestion.kinds.reddit import RedditKind
        from insight_core.ingestion.kinds.saved import SavedKind
        from insight_core.ingestion.kinds.substack import SubstackKind
        from insight_core.ingestion.kinds.telegram_mtproto import TelegramKind
        from insight_core.ingestion.kinds.telegram_rss import TelegramRssKind
        from insight_core.ingestion.kinds.youtube import YouTubeKind

        posts = PostsRepository(db_url) if db_url else None
        stored_urls = posts.stored_urls if posts else None
        return KindRegistry([
            SavedKind(),
            PageWatchKind(http, stored_urls=stored_urls, kept_urls=posts.kept_urls if posts else None),
            *(adapter_class(http) for adapter_class in ADAPTER_CLASSES),
            ForumKind(http),   # a forum board's address (Discourse, Flarum, FluxBB listing shapes)
            SubstackKind(http, stored_urls=stored_urls),
            RedditKind(http),
            YouTubeKind(youtube),
            TelegramRssKind(http),
            NitterRssKind(http, stored_articles=posts.stored_x_articles if posts else None),
            BlueskyKind(http),   # matches nothing unless INSIGHT_BLUESKY is on
            TelegramKind(http=http),
            GenericRssKind(http, stored_urls=stored_urls, teasers_due=posts.teasers_to_read_again if posts else None,
                           learned=LearnedLadder(db_url) if db_url else None),
        ])


__all__ = ["KindRegistry"]
