"""generic_rss: any RSS/Atom feed (the fallback kind). A new post whose feed gave only a
summary is expanded from its article page (ingestion/full_text.py). A live fetch asks for the
feed conditionally (issue 0044): an unchanged feed answers 304 and is no posts."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Sequence

from insight_core.ingestion import full_text
from insight_core.ingestion.http import AddressMemory, KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import (
    BaseKind,
    Inspection,
    PolitenessProfile,
    SingleShotArchive,
    Source,
)
from insight_core.utils.json_safe import iso

logger = logging.getLogger("insight.ingestion.generic_rss")

GENERIC_RSS_PROFILE = PolitenessProfile(concurrency_pool="host-lock")

# Which of these urls are already stored (blocking; run in a thread).
StoredUrls = Callable[[Sequence[str]], set]


class GenericRssKind(SingleShotArchive, BaseKind):
    name = "generic_rss"
    available_basis = "feed_window"
    conditional = True
    profile = GENERIC_RSS_PROFILE

    def __init__(self, http: KindHttp, *, stored_urls: Optional[StoredUrls] = None) -> None:
        self.http = http
        self.stored_urls = stored_urls

    def matches(self, source: Source) -> bool:
        return True  # the fallback

    async def fetch_latest(self, source: Source, limit: int, *,
                           memory: Optional[AddressMemory] = None) -> List[Dict[str, Any]]:
        """With memory (the runner's), the feed is asked conditionally: unchanged (304) is no posts."""
        url = str(source["handle_or_url"])
        if memory is None:
            feed_text, _ = await self.http.get_text(url)
        else:
            answer = await memory.get(self.http, url)
            if answer.not_modified:
                return []
            feed_text = answer.text
        posts = parsing.parse_feed_posts(feed_text, url)[:limit]
        return await self._maybe_expand(source, posts)

    async def inspect(self, source: Source) -> Inspection:
        url = str(source["handle_or_url"])
        feed_text, _ = await self.http.get_text(url)
        posts = parsing.parse_feed_posts(feed_text, url)
        oldest = posts[-1]["date"] if posts else None
        return Inspection(
            available_posts=len(posts),
            page_size=max(1, len(posts)),
            first_post_date=iso(oldest),
        )

    async def _maybe_expand(self, source: Source, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Read the article page of each new teaser post, one page at a time.

        A stored post is never re-read here: it was expanded when it was new, or it is the
        repair script's job. When the lookup fails nothing is read, rather than every page.
        """
        if not full_text.full_page_enabled(source):
            return posts
        teasers = [post for post in posts if full_text.page_is_article(post.get("url")) and full_text.is_teaser(post)]
        if not teasers:
            return posts
        try:
            stored = (await asyncio.to_thread(self.stored_urls, [post["url"] for post in teasers])
                      if self.stored_urls else set())
        except Exception as exc:  # noqa: BLE001 - the feed's own bodies are still saved
            logger.warning("Full-text lookup failed for %s: %s", source.get("handle_or_url"), exc)
            return posts
        expanded: Dict[str, Dict[str, Any]] = {}
        for index, post in enumerate(post for post in teasers if post["url"] not in stored):
            if index:
                await self.http.sleep(full_text.PAGE_DELAY_S)
            try:
                article = await full_text.read_article(self.http, post["url"], full_text.body_text(post))
            except Exception as exc:  # noqa: BLE001 - the summary is kept
                logger.debug("Full-text expansion skipped for %s: %s", post["url"], exc)
                continue
            if article is not None:
                expanded[post["url"]] = full_text.with_full_text(post, *article)
        return [expanded.get(post.get("url"), post) for post in posts]
