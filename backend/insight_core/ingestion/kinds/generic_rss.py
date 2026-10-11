"""generic_rss: any RSS/Atom feed (the fallback kind), with optional full-content expansion."""
from __future__ import annotations

import logging
import os
import urllib.parse
from typing import Any, Dict, List, Optional

from insight_core.ingestion.http import KindHttp
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

# An RSS body shorter than this is probably a teaser; expansion fetches the article page.
SHORT_BODY_CHARS = 1400


class GenericRssKind(SingleShotArchive, BaseKind):
    name = "generic_rss"
    available_basis = "feed_window"
    profile = GENERIC_RSS_PROFILE

    def __init__(self, http: KindHttp, *, full_content_hosts: Optional[set[str]] = None) -> None:
        self.http = http
        self.full_content_hosts = full_content_hosts if full_content_hosts is not None else {
            host.strip().lower()
            for host in os.getenv("RSS_FULL_CONTENT_HOSTS", "news.smol.ai").split(",")
            if host.strip()
        }

    def matches(self, source: Source) -> bool:
        return True  # the fallback

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        url = str(source["handle_or_url"])
        feed_text, _ = await self.http.get_text(url)
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
        if not posts:
            return posts
        settings = source.get("settings") or {}
        host = (urllib.parse.urlparse(str(source["handle_or_url"])).hostname or "").lower()
        if not (bool(settings.get("fetch_full_content")) or host in self.full_content_hosts):
            return posts
        return [await self._maybe_expand_article_body(post) for post in posts]

    async def _maybe_expand_article_body(self, post: Dict[str, Any]) -> Dict[str, Any]:
        url = post.get("url")
        if not isinstance(url, str) or not url.startswith("http"):
            return post

        current_content = parsing.strip_html(post.get("content_html") or post.get("content") or "")
        if len(current_content) >= SHORT_BODY_CHARS:
            return post

        try:
            article_html, _ = await self.http.get_text(url)
            extracted_html = parsing.extract_article_html(article_html)
            extracted_text = parsing.strip_html(extracted_html)
            if len(extracted_text) <= max(len(current_content) + 250, 700):
                return post

            next_post = dict(post)
            next_post["content_html"] = extracted_html
            next_post["content"] = extracted_text
            next_post["metadata"] = {**(post.get("metadata") or {}), "full_content_fetched": True}
            return next_post
        except Exception as exc:
            logger.debug("Full-content expansion skipped for %s: %s", url, exc)
            return post
