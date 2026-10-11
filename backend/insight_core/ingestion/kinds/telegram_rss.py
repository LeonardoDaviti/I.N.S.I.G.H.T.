"""telegram_rss: Telegram channels through an RSS bridge (tg.i-c-a.su, the self-hosted one).

The bridge answers "Too many requests" (FLOOD_WAIT) when paged quickly, so live pages are
rate limited too (live_pages_rate_limited) and a live fetch reads only the pages it needs
for `limit`. The source URL's query (e.g. ?limit=50, the bridge's page size) is kept on
every page URL.
"""
from __future__ import annotations

import json
import math
import re
import urllib.parse
from typing import Any, Dict, List, Optional

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

# Hosts that serve the bridge's /rss/<channel> feeds. gates.HOST_FLOORS gives each a 5s floor.
TELEGRAM_RSS_HOSTS = frozenset({"telegram.local", "tg.i-c-a.su", "127.0.0.1"})

TELEGRAM_RSS_PROFILE = PolitenessProfile(
    concurrency_pool="host-lock",
    page_delay_s=5,
    batch_size=10,
    batch_cooldown_s=30,
    live_pages_rate_limited=True,
)

CANONICAL_RE = re.compile(r"^https://t\.me/(?P<username>[^/]+)/(?P<post_id>\d+)$")


class TelegramRssKind(BaseKind):
    name = "telegram_rss"
    available_basis = "upper_bound"   # the newest post number; deleted posts still count
    profile = TELEGRAM_RSS_PROFILE

    def __init__(self, http: KindHttp) -> None:
        self.http = http

    def matches(self, source: Source) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        segments = parsing.path_segments(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in TELEGRAM_RSS_HOSTS and len(segments) >= 2 and segments[0] == "rss"

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "telegram_page" and bool(
            checkpoint.get("next_page")
        )

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        rate = self.profile.rate_limit()
        async for page in self._pages(str(source["handle_or_url"]), limit, start_page=1,
                                      initial_collected=0, initial_pages=0, rate=rate):
            collected.extend(page.posts)
        return collected[:limit]

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        initial_collected, initial_pages = resume_counts(checkpoint)
        start_page = int((checkpoint or {}).get("next_page") or 1)
        async for page in self._pages(str(source["handle_or_url"]), target, start_page=start_page,
                                      initial_collected=initial_collected, initial_pages=initial_pages,
                                      rate=rate):
            yield page

    async def inspect(self, source: Source) -> Inspection:
        source_url = str(source["handle_or_url"])
        page_one = await self.fetch_page(source_url, 1)
        if not page_one:
            raise ValueError(f"No canonical Telegram posts found for {_username(source_url)}")

        highest_post_id = max(int(post["external_id"]) for post in page_one if post.get("external_id"))
        page_size = max(1, len(page_one))
        last_page_number = await self._find_last_page(source_url, highest_post_id, page_size)
        last_page = await self.fetch_page(source_url, last_page_number)
        oldest = last_page[-1]["date"] if last_page else None
        return Inspection(highest_post_id, page_size, parsing.isoformat(oldest))

    async def _pages(self, source_url: str, target: int, *, start_page: int, initial_collected: int,
                     initial_pages: int, rate: RateLimit):
        """Pages from start_page until target posts (counting initial_collected) are reached."""
        seen_urls: set[str] = set()
        collected = initial_collected
        pages_fetched = initial_pages
        page = max(1, start_page)

        while collected < target:
            page_posts = await self.fetch_page(source_url, page)
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
                "mode": "telegram_page",
                "next_page": page + 1,
                "last_page": page,
                "pages_fetched": pages_fetched,
                "collected_posts": collected,
            })
            page += 1
            if collected < target:
                await self.http.sleep(rate.delay_after(pages_fetched))

    async def fetch_page(self, source_url: str, page: int) -> List[Dict[str, Any]]:
        origin = parsing.origin_from_source(source_url, parsing.TELEGRAM_BASE_URL)
        username = _username(source_url)
        body, _ = await self.http.get_text(page_url(source_url, page))

        if body.lstrip().startswith("{"):
            payload = json.loads(body)
            raise ValueError(payload.get("errors", payload))

        canonical: List[Dict[str, Any]] = []
        for post in parsing.parse_feed_posts(body, f"{origin}/rss/{username}"):
            match = CANONICAL_RE.match(post["url"])
            if not match or post.get("title", "").startswith("[Sponsored]"):
                continue
            post["title"] = parsing.strip_telegram_media_tag(post.get("title", ""))
            post["external_id"] = match.group("post_id")
            post["url"] = f"https://t.me/{match.group('username')}/{match.group('post_id')}"
            post["content_html"] = parsing.normalize_telegram_resources(post.get("content_html", ""), origin)
            post["content"] = parsing.strip_html(post["content_html"])
            post["media_urls"] = [
                parsing.normalize_telegram_resources(media_url, origin) for media_url in post.get("media_urls", [])
            ]
            canonical.append(post)
        return canonical

    async def _find_last_page(self, source_url: str, highest_post_id: int, page_size: int) -> int:
        low = 1
        high = max(1, math.ceil(highest_post_id / max(page_size, 1)))

        while await self._page_has_posts(source_url, high):
            low = high
            high *= 2

        while low < high:
            mid = (low + high + 1) // 2
            if await self._page_has_posts(source_url, mid):
                low = mid
            else:
                high = mid - 1
        return low

    async def _page_has_posts(self, source_url: str, page: int) -> bool:
        return bool(await self.fetch_page(source_url, page))


def _username(source_url: str) -> str:
    segments = parsing.path_segments(source_url)
    if len(segments) < 2 or segments[0] != "rss":
        raise ValueError(f"Invalid Telegram RSS URL: {source_url}")
    return segments[1]


def page_url(source_url: str, page: int) -> str:
    """{origin}/rss/{channel}/{page}, keeping the source URL's query (?limit=N = page size)."""
    origin = parsing.origin_from_source(source_url, parsing.TELEGRAM_BASE_URL)
    query = urllib.parse.urlparse(source_url).query
    url = f"{origin}/rss/{_username(source_url)}/{page}"
    return f"{url}?{query}" if query else url
