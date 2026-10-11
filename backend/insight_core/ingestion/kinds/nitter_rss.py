"""nitter_rss: X/Twitter accounts through a Nitter instance's /<user>/rss feed (cursor paging)."""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    PolitenessProfile,
    RateLimit,
    Source,
    resume_counts,
)

# gates.HOST_FLOORS gives each a 10s floor.
NITTER_HOSTS = frozenset({"nitter.local", "nitter.net"})
NITTER_BASE_URL = "https://nitter.local"

NITTER_PROFILE = PolitenessProfile(
    concurrency_pool="host-lock",
    page_delay_s=10,
    batch_size=10,
    batch_cooldown_s=30,
    live_pages_rate_limited=True,
)

STATUS_RE = re.compile(r"/status/(?P<post_id>\d+)")


def extract_nitter_tweet_count(profile_html: str) -> Optional[int]:
    match = re.search(
        r'<li class="posts">.*?<span class="profile-stat-num">([\d,]+)</span>',
        profile_html,
        re.DOTALL,
    )
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _status_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = STATUS_RE.search(value)
    return match.group("post_id") if match else None


def _username(source_url: str) -> str:
    segments = parsing.path_segments(source_url)
    if len(segments) < 2 or segments[1] != "rss":
        raise ValueError(f"Invalid Nitter RSS URL: {source_url}")
    return segments[0]


class NitterRssKind(BaseKind):
    name = "nitter_rss"
    available_basis = "estimate"   # the profile counter (replies and reposts included)
    profile = NITTER_PROFILE

    def __init__(self, http: KindHttp) -> None:
        self.http = http

    def matches(self, source: Source) -> bool:
        url = str(source.get("handle_or_url") or "")
        segments = parsing.path_segments(url)
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        return host in NITTER_HOSTS and len(segments) >= 2 and segments[1] == "rss"

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "nitter_cursor" and checkpoint.get(
            "cursor"
        ) is not None

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        posts: List[Dict[str, Any]] = []
        async for page in self._pages(str(source["handle_or_url"]), limit, None, 0, 0, self.profile.rate_limit()):
            posts.extend(page.posts)
        return posts[:limit]

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        collected, pages = resume_counts(checkpoint)
        cursor = (checkpoint or {}).get("cursor")
        async for page in self._pages(str(source["handle_or_url"]), target, cursor, collected, pages, rate):
            yield page

    async def inspect(self, source: Source) -> Inspection:
        source_url = str(source["handle_or_url"])
        username = _username(source_url)
        origin = parsing.origin_from_source(source_url, NITTER_BASE_URL)
        profile_html, _ = await self.http.get_text(f"{origin}/{username}")
        rss_text, _ = await self.http.get_text(source_url)
        page_size = max(1, len(parsing.parse_feed_posts(rss_text, source_url)))
        return Inspection(extract_nitter_tweet_count(profile_html), page_size, None)

    async def _pages(self, source_url: str, target: int, cursor: Optional[str], initial_collected: int,
                     initial_pages: int, rate: RateLimit):
        seen_urls: set[str] = set()
        collected = initial_collected
        pages_fetched = initial_pages
        current_cursor = cursor

        while collected < target:
            page_posts, next_cursor = await self._fetch_page(source_url, current_cursor)
            if not page_posts:
                break

            pages_fetched += 1
            unique: List[Dict[str, Any]] = []
            for post in page_posts:
                if post["url"] in seen_urls:
                    continue
                seen_urls.add(post["url"])
                unique.append(post)
                collected += 1
                if collected >= target:
                    break

            yield ArchivePage(unique, {
                "mode": "nitter_cursor",
                "cursor": next_cursor,
                "last_cursor": current_cursor,
                "pages_fetched": pages_fetched,
                "collected_posts": collected,
            })

            if collected >= target or not next_cursor or next_cursor == current_cursor:
                break
            current_cursor = next_cursor
            await self.http.sleep(rate.delay_after(pages_fetched))

    async def _fetch_page(self, source_url: str, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        origin = parsing.origin_from_source(source_url, NITTER_BASE_URL)
        username = _username(source_url)
        url = f"{origin}/{username}/rss"
        if cursor:
            url = f"{url}?cursor={urllib.parse.quote(cursor, safe='')}"

        body, headers = await self.http.get_text(url)
        posts = parsing.parse_feed_posts(body, f"{origin}/{username}/rss")
        for post in posts:
            external_id = _status_id(post["url"]) or _status_id(post.get("guid", ""))
            if external_id:
                post["external_id"] = external_id
        return posts, headers.get("min-id")
