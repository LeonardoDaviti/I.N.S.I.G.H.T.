"""
Source fetching and archive orchestration for DB-backed sources.

This service handles:
- Archive planning for Telegram RSS, Nitter RSS, Reddit, and generic RSS feeds
- Archive execution with per-source rate limiting
- Live fetching for RSS-backed sources used by ingest.py / safe_ingest.py
- Persistence of archive metadata inside sources.settings["archive"]
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional, Tuple
import psycopg

from insight_core.db.repo_posts import PostsRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.posts_service import PostsService
from insight_core.services.sources_service import SourcesService
from insight_core.services.youtube_service import YouTubeService


class SourceFetchService:
    """Central fetch/archive service for DB-backed sources."""

    TELEGRAM_BASE_URL = "https://telegram.local"
    NITTER_BASE_URL = "https://nitter.local"
    REDDIT_BASE_URL = "https://www.reddit.com"
    DEFAULT_TIMEOUT_SECONDS = 30
    DEFAULT_USER_AGENT = "INSIGHT Archive Fetcher/1.0"

    TELEGRAM_PAGE_DELAY_SECONDS = 5
    TELEGRAM_BATCH_SIZE = 10
    TELEGRAM_BATCH_COOLDOWN_SECONDS = 30
    NITTER_PAGE_DELAY_SECONDS = 10
    NITTER_BATCH_SIZE = 10
    NITTER_BATCH_COOLDOWN_SECONDS = 30
    REDDIT_PAGE_DELAY_SECONDS = 2
    YOUTUBE_PAGE_DELAY_SECONDS = 2

    TELEGRAM_HOSTS = {"telegram.local", "tg.i-c-a.su", "127.0.0.1"}
    NITTER_HOSTS = {"nitter.local", "nitter.net"}
    YOUTUBE_HOSTS = {"www.youtube.com", "youtube.com", "m.youtube.com"}
    REDDIT_HOSTS = {"www.reddit.com", "reddit.com", "old.reddit.com"}

    TELEGRAM_CANONICAL_RE = re.compile(r"^https://t\.me/(?P<username>[^/]+)/(?P<post_id>\d+)$")
    NITTER_STATUS_RE = re.compile(r"/status/(?P<post_id>\d+)")
    IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)
    REDDIT_POST_URL_RE = re.compile(r"^https?://(?:www\.)?reddit\.com")

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.sources_service = SourcesService(db_url)
        self.posts_service = PostsService(db_url)
        self.posts_repo = PostsRepository(db_url)
        self.youtube_service = YouTubeService(db_url)
        self.logger = get_component_logger("source_fetch_service")
        self.timeout = int(os.getenv("RSS_TIMEOUT_SECONDS", str(self.DEFAULT_TIMEOUT_SECONDS)))
        self.user_agent = os.getenv("RSS_USER_AGENT", self.DEFAULT_USER_AGENT)
        self.reddit_user_agent = os.getenv(
            "REDDIT_USER_AGENT",
            "INSIGHT Archive Fetcher/1.0",
        )

    async def plan_archive(self, source_id: str, desired_posts: Optional[int] = None) -> Dict[str, Any]:
        """Inspect a source and estimate archive effort."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        inspection = await self.inspect_source(source)
        desired = desired_posts or inspection["available_posts"] or source.get("settings", {}).get("max_posts_per_fetch", 50)
        desired = min(desired, inspection["available_posts"] or desired)
        estimated_pages = self._estimate_pages(inspection["source_type"], desired, inspection["page_size"])

        inspection.update({
            "desired_posts": desired,
            "estimated_pages": estimated_pages,
            "estimated_seconds": self._estimate_seconds(inspection["source_type"], estimated_pages),
            "source_id": source_id,
            "current_stored_posts": self.posts_service.get_source_post_stats(source_id)["post_count"],
        })

        await self._record_archive_metadata(source_id, inspection, mode="plan")
        return inspection

    async def archive_source(self, source_id: str, desired_posts: Optional[int] = None) -> Dict[str, Any]:
        """Archive historical posts for a single source."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        plan = await self.plan_archive(source_id, desired_posts)
        source_type = plan["source_type"]
        target_posts = plan["desired_posts"]

        if source_type == "telegram_rss":
            posts, pages_fetched = await self._collect_telegram_posts(source["handle_or_url"], target_posts)
        elif source_type == "nitter_rss":
            posts, pages_fetched = await self._collect_nitter_posts(source["handle_or_url"], target_posts)
        elif source_type == "youtube_channel":
            youtube_result = self.youtube_service.archive_channel_posts(source["handle_or_url"], target_posts)
            posts = youtube_result["posts"]
            pages_fetched = youtube_result["pages_fetched"]
        elif source_type == "reddit_subreddit":
            posts, pages_fetched = await self._collect_reddit_posts(source["handle_or_url"], target_posts)
        elif source_type == "generic_rss":
            posts = await self.fetch_live_posts(source, target_posts)
            pages_fetched = 1
        else:
            raise ValueError(f"Archive is not supported for source type {source_type}")

        saved = self._persist_posts(source_id, posts)
        post_stats = self.posts_service.get_source_post_stats(source_id)

        result = {
            **plan,
            "success": True,
            "posts_fetched": len(posts),
            "pages_fetched": pages_fetched,
            "posts_inserted": saved["inserted"],
            "posts_updated": saved["updated"],
            "stored_posts": post_stats["post_count"],
            "archive_status": self._derive_archive_status(post_stats["post_count"], plan["available_posts"]),
        }

        await self._record_archive_metadata(source_id, result, mode="archive")
        return result

    async def fetch_live_posts(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        """Fetch latest posts for an RSS-style source."""
        source_type = self.classify_source(source)

        if source_type == "telegram_rss":
            posts, _ = await self._collect_telegram_posts(source["handle_or_url"], limit, apply_rate_limits=False)
            return posts

        if source_type == "nitter_rss":
            posts, _ = await self._collect_nitter_posts(source["handle_or_url"], limit)
            return posts

        if source_type == "youtube_channel":
            return self.youtube_service.fetch_live_posts(source["handle_or_url"], limit)

        if source_type == "reddit_subreddit":
            return await self._fetch_reddit_live_posts(source["handle_or_url"], limit)

        feed_text, _ = await self._fetch_text(source["handle_or_url"])
        return self._parse_feed_posts(feed_text, source["handle_or_url"])[:limit]

    async def inspect_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        """Inspect source capabilities and available archive metadata."""
        source_type = self.classify_source(source)
        source_url = source["handle_or_url"]
        source_settings = source.get("settings") or {}

        if source_type == "telegram_rss":
            inspection = await self._inspect_telegram_source(source_url)
        elif source_type == "nitter_rss":
            inspection = await self._inspect_nitter_source(source_url)
        elif source_type == "youtube_channel":
            inspection = self._inspect_youtube_source(source_url)
        elif source_type == "reddit_subreddit":
            inspection = self._inspect_reddit_source(source_url)
        elif source_type == "generic_rss":
            inspection = await self._inspect_generic_rss_source(source_url)
        else:
            raise ValueError(f"Archive planning is not supported for source type {source_type}")

        return {
            **inspection,
            "source_type": source_type,
            "display_name": source_settings.get("display_name") or source_url,
        }

    async def record_live_fetch(self, source_id: str, source: Dict[str, Any], fetched_posts: int) -> None:
        """Refresh archive metadata after a live fetch."""
        try:
            inspection = await self.inspect_source(source)
        except Exception as exc:
            self.logger.warning("Skipping archive metadata refresh for %s: %s", source_id, exc)
            return

        inspection["posts_fetched"] = fetched_posts
        await self._record_archive_metadata(source_id, inspection, mode="live")

    def classify_source(self, source: Dict[str, Any]) -> str:
        """Classify a source into a specific live/archive strategy."""
        platform = source.get("platform")
        handle_or_url = source.get("handle_or_url", "")

        if platform == "reddit":
            return "reddit_subreddit"
        if platform == "youtube":
            return "youtube_channel"

        parsed = urllib.parse.urlparse(handle_or_url)
        host = (parsed.hostname or "").lower()
        segments = [segment for segment in parsed.path.split("/") if segment]

        if host in self.TELEGRAM_HOSTS and len(segments) >= 2 and segments[0] == "rss":
            return "telegram_rss"

        if host in self.NITTER_HOSTS and len(segments) >= 2 and segments[1] == "rss":
            return "nitter_rss"

        if host in self.YOUTUBE_HOSTS and parsed.path == "/feeds/videos.xml":
            return "youtube_channel"

        if host in self.REDDIT_HOSTS and "/r/" in parsed.path:
            return "reddit_subreddit"

        return "generic_rss"

    async def _inspect_telegram_source(self, source_url: str) -> Dict[str, Any]:
        username = self._extract_telegram_username(source_url)
        page_one_posts = await self._fetch_telegram_page(username, 1)

        if not page_one_posts:
            raise ValueError(f"No canonical Telegram posts found for {username}")

        highest_post_id = max(int(post["external_id"]) for post in page_one_posts if post.get("external_id"))
        page_size = max(1, len(page_one_posts))
        last_page_number = await self._find_last_telegram_page(username, highest_post_id, page_size)
        last_page_posts = await self._fetch_telegram_page(username, last_page_number)
        oldest_post_date = last_page_posts[-1]["date"] if last_page_posts else None

        return {
            "available_posts": highest_post_id,
            "page_size": page_size,
            "first_post_date": self._isoformat(oldest_post_date),
            "rate_limit": {
                "page_delay_seconds": self.TELEGRAM_PAGE_DELAY_SECONDS,
                "batch_size": self.TELEGRAM_BATCH_SIZE,
                "batch_cooldown_seconds": self.TELEGRAM_BATCH_COOLDOWN_SECONDS,
            },
        }

    async def _inspect_nitter_source(self, source_url: str) -> Dict[str, Any]:
        username = self._extract_nitter_username(source_url)
        profile_url = f"{self.NITTER_BASE_URL}/{username}"
        profile_html, _ = await self._fetch_text(profile_url)
        available_posts = self._extract_nitter_tweet_count(profile_html)
        rss_text, _ = await self._fetch_text(source_url)
        page_size = max(1, len(self._parse_feed_posts(rss_text, source_url)))

        return {
            "available_posts": available_posts,
            "page_size": page_size,
            "first_post_date": None,
            "rate_limit": {
                "page_delay_seconds": self.NITTER_PAGE_DELAY_SECONDS,
                "batch_size": self.NITTER_BATCH_SIZE,
                "batch_cooldown_seconds": self.NITTER_BATCH_COOLDOWN_SECONDS,
            },
        }

    def _inspect_youtube_source(self, source_url: str) -> Dict[str, Any]:
        return self.youtube_service.inspect_channel(source_url)

    def _inspect_reddit_source(self, source_url: str) -> Dict[str, Any]:
        return {
            "available_posts": 250,
            "page_size": 100,
            "first_post_date": None,
            "rate_limit": {
                "page_delay_seconds": self.REDDIT_PAGE_DELAY_SECONDS,
            },
        }

    async def _inspect_generic_rss_source(self, source_url: str) -> Dict[str, Any]:
        rss_text, _ = await self._fetch_text(source_url)
        posts = self._parse_feed_posts(rss_text, source_url)
        oldest_post_date = posts[-1]["date"] if posts else None

        return {
            "available_posts": len(posts),
            "page_size": max(1, len(posts)),
            "first_post_date": self._isoformat(oldest_post_date),
            "rate_limit": {
                "page_delay_seconds": 0,
            },
        }

    async def _collect_telegram_posts(
        self,
        source_url: str,
        target_posts: int,
        apply_rate_limits: bool = True,
    ) -> Tuple[List[Dict[str, Any]], int]:
        username = self._extract_telegram_username(source_url)
        collected: List[Dict[str, Any]] = []
        seen_urls = set()
        page = 1
        pages_fetched = 0

        while len(collected) < target_posts:
            page_posts = await self._fetch_telegram_page(username, page)
            if not page_posts:
                break

            pages_fetched += 1
            for post in page_posts:
                if post["url"] not in seen_urls:
                    seen_urls.add(post["url"])
                    collected.append(post)
                    if len(collected) >= target_posts:
                        break

            page += 1
            if len(collected) < target_posts and apply_rate_limits:
                await self._sleep_between_telegram_pages(pages_fetched)

        return collected[:target_posts], pages_fetched

    async def _collect_nitter_posts(self, source_url: str, target_posts: int) -> Tuple[List[Dict[str, Any]], int]:
        username = self._extract_nitter_username(source_url)
        collected: List[Dict[str, Any]] = []
        seen_urls = set()
        cursor: Optional[str] = None
        pages_fetched = 0

        while len(collected) < target_posts:
            page_posts, next_cursor = await self._fetch_nitter_page(username, cursor)
            if not page_posts:
                break

            pages_fetched += 1
            for post in page_posts:
                if post["url"] not in seen_urls:
                    seen_urls.add(post["url"])
                    collected.append(post)
                    if len(collected) >= target_posts:
                        break

            if len(collected) >= target_posts or not next_cursor or next_cursor == cursor:
                break

            cursor = next_cursor
            await self._sleep_between_nitter_pages(pages_fetched)

        return collected[:target_posts], pages_fetched

    async def _collect_reddit_posts(self, source_handle: str, target_posts: int) -> Tuple[List[Dict[str, Any]], int]:
        subreddit = self._extract_reddit_subreddit(source_handle)
        collected: List[Dict[str, Any]] = []
        after: Optional[str] = None
        pages_fetched = 0

        while len(collected) < target_posts:
            page_limit = min(100, target_posts - len(collected))
            page_posts, after = await self._fetch_reddit_page(subreddit, after=after, limit=page_limit)
            if not page_posts:
                break

            pages_fetched += 1
            collected.extend(page_posts)

            if not after:
                break

            if len(collected) < target_posts:
                await asyncio.sleep(self.REDDIT_PAGE_DELAY_SECONDS)

        return collected[:target_posts], pages_fetched

    async def _fetch_telegram_page(self, username: str, page: int) -> List[Dict[str, Any]]:
        url = f"{self.TELEGRAM_BASE_URL}/rss/{username}/{page}"
        body, _ = await self._fetch_text(url)

        if body.lstrip().startswith("{"):
            payload = json.loads(body)
            raise ValueError(payload.get("errors", payload))

        posts = self._parse_feed_posts(body, f"{self.TELEGRAM_BASE_URL}/rss/{username}")
        canonical_posts: List[Dict[str, Any]] = []

        for post in posts:
            match = self.TELEGRAM_CANONICAL_RE.match(post["url"])
            if not match:
                continue

            if post.get("title", "").startswith("[Sponsored]"):
                continue

            post["external_id"] = match.group("post_id")
            post["url"] = f"https://t.me/{match.group('username')}/{match.group('post_id')}"
            post["content_html"] = self._normalize_telegram_resources(post.get("content_html", ""))
            post["content"] = self._strip_html(post["content_html"])
            post["media_urls"] = [self._normalize_telegram_resources(media_url) for media_url in post.get("media_urls", [])]
            canonical_posts.append(post)

        return canonical_posts

    async def _fetch_nitter_page(self, username: str, cursor: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        url = f"{self.NITTER_BASE_URL}/{username}/rss"
        if cursor:
            encoded_cursor = urllib.parse.quote(cursor, safe="")
            url = f"{url}?cursor={encoded_cursor}"

        body, headers = await self._fetch_text(url)
        posts = self._parse_feed_posts(body, f"{self.NITTER_BASE_URL}/{username}/rss")

        for post in posts:
            external_id = self._extract_nitter_status_id(post["url"]) or self._extract_nitter_status_id(post.get("guid", ""))
            if external_id:
                post["external_id"] = external_id

        next_cursor = headers.get("min-id")
        return posts, next_cursor

    async def _fetch_reddit_page(
        self,
        subreddit: str,
        after: Optional[str] = None,
        limit: int = 100,
        sort_method: str = "top",
        time_filter: Optional[str] = "all",
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        params = {
            "limit": str(limit),
        }
        if sort_method == "top" and time_filter:
            params["t"] = time_filter
        if after:
            params["after"] = after

        query_string = urllib.parse.urlencode(params)
        url = f"{self.REDDIT_BASE_URL}/r/{subreddit}/{sort_method}.json?{query_string}"
        body, _ = await self._fetch_text(url, user_agent=self.reddit_user_agent)
        payload = json.loads(body)
        data = payload.get("data", {})

        posts: List[Dict[str, Any]] = []
        for child in data.get("children", []):
            if child.get("kind") != "t3":
                continue

            post_data = child.get("data", {})
            permalink = post_data.get("permalink", "")
            post_url = f"https://reddit.com{permalink}" if permalink else post_data.get("url")
            media_urls = []
            if post_data.get("url") and not self.REDDIT_POST_URL_RE.match(post_data["url"]):
                media_urls.append(post_data["url"])

            posts.append({
                "platform": "reddit",
                "source": f"r/{subreddit}",
                "url": post_url,
                "external_id": post_data.get("id"),
                "title": post_data.get("title", ""),
                "content": post_data.get("selftext", "") or post_data.get("title", ""),
                "content_html": post_data.get("selftext_html"),
                "date": datetime.fromtimestamp(post_data.get("created_utc", 0), tz=timezone.utc),
                "media_urls": media_urls,
                "categories": [subreddit] + ([post_data["link_flair_text"]] if post_data.get("link_flair_text") else []),
                "metadata": {},
            })

        return posts, data.get("after")

    async def _fetch_reddit_live_posts(self, source_handle: str, limit: int) -> List[Dict[str, Any]]:
        subreddit = self._extract_reddit_subreddit(source_handle)
        posts, _ = await self._fetch_reddit_page(subreddit, limit=min(limit, 100), sort_method="new", time_filter=None)
        return posts[:limit]

    async def _fetch_text(self, url: str, user_agent: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
        return await asyncio.to_thread(self._fetch_text_sync, url, user_agent)

    def _fetch_text_sync(self, url: str, user_agent: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent or self.user_agent, "Accept": "*/*"},
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                headers = {
                    key.lower(): value
                    for key, value in response.headers.items()
                }
                return body, headers
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"HTTP {exc.code} while fetching {url}: {body[:200]}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"Failed to fetch {url}: {exc.reason}") from exc

    def _parse_feed_posts(self, feed_text: str, source_url: str) -> List[Dict[str, Any]]:
        root = ET.fromstring(feed_text)
        posts: List[Dict[str, Any]] = []

        if self._local_name(root.tag) == "rss":
            channel = next((child for child in root if self._local_name(child.tag) == "channel"), None)
            items = [child for child in (channel if channel is not None else []) if self._local_name(child.tag) == "item"]
            for item in items:
                content_html = self._normalize_feed_urls(
                    self._child_inner_xml(item, "description") or self._child_inner_xml(item, "encoded")
                )
                url = self._normalize_feed_urls(self._child_text(item, "link") or source_url)
                posts.append({
                    "platform": "rss",
                    "source": source_url,
                    "url": url,
                    "guid": self._child_text(item, "guid"),
                    "title": self._normalize_feed_urls(self._child_text(item, "title") or ""),
                    "content": self._strip_html(content_html),
                    "content_html": content_html,
                    "date": self._parse_datetime_value(self._child_text(item, "pubDate") or self._child_text(item, "updated")),
                    "media_urls": self._extract_xml_media_urls(item, content_html),
                    "categories": self._extract_xml_categories(item),
                    "metadata": {},
                })
        elif self._local_name(root.tag) == "feed":
            entries = [child for child in root if self._local_name(child.tag) == "entry"]
            for entry in entries:
                content_html = self._normalize_feed_urls(
                    self._child_inner_xml(entry, "content") or self._child_inner_xml(entry, "summary")
                )
                url = self._normalize_feed_urls(self._extract_atom_link(entry) or source_url)
                posts.append({
                    "platform": "rss",
                    "source": source_url,
                    "url": url,
                    "guid": self._child_text(entry, "id"),
                    "title": self._normalize_feed_urls(self._child_text(entry, "title") or ""),
                    "content": self._strip_html(content_html),
                    "content_html": content_html,
                    "date": self._parse_datetime_value(self._child_text(entry, "published") or self._child_text(entry, "updated")),
                    "media_urls": self._extract_xml_media_urls(entry, content_html),
                    "categories": self._extract_xml_categories(entry),
                    "metadata": {},
                })

        posts.sort(key=lambda post: post.get("date") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return posts

    def _extract_xml_media_urls(self, node: ET.Element, content_html: str) -> List[str]:
        media_urls: List[str] = []

        for child in node.iter():
            local_name = self._local_name(child.tag)
            if local_name in {"enclosure", "content"}:
                media_url = child.attrib.get("url") or child.attrib.get("href")
                if media_url:
                    media_urls.append(self._normalize_feed_urls(media_url))

            if local_name == "link":
                rel = child.attrib.get("rel")
                media_type = child.attrib.get("type", "")
                href = child.attrib.get("href")
                if href and (rel == "enclosure" or media_type.startswith("image/") or media_type.startswith("video/")):
                    media_urls.append(self._normalize_feed_urls(href))

        for image_url in self.IMG_SRC_RE.findall(content_html or ""):
            media_urls.append(self._normalize_feed_urls(image_url))

        deduped = []
        seen = set()
        for media_url in media_urls:
            if media_url and media_url not in seen:
                seen.add(media_url)
                deduped.append(media_url)

        return deduped

    def _extract_xml_categories(self, node: ET.Element) -> List[str]:
        categories: List[str] = []
        for child in node:
            if self._local_name(child.tag) != "category":
                continue
            term = child.attrib.get("term") or child.attrib.get("label") or (child.text or "")
            if term:
                categories.append(term)

        return sorted({category.strip() for category in categories if category and category.strip()})

    async def _find_last_telegram_page(self, username: str, highest_post_id: int, page_size: int) -> int:
        estimated_last_page = max(1, math.ceil(highest_post_id / max(page_size, 1)))
        low = 1
        high = estimated_last_page

        while await self._telegram_page_has_posts(username, high):
            low = high
            high *= 2

        while low < high:
            mid = (low + high + 1) // 2
            if await self._telegram_page_has_posts(username, mid):
                low = mid
            else:
                high = mid - 1

        return low

    async def _telegram_page_has_posts(self, username: str, page: int) -> bool:
        posts = await self._fetch_telegram_page(username, page)
        return bool(posts)

    async def _sleep_between_telegram_pages(self, pages_fetched: int) -> None:
        if pages_fetched % self.TELEGRAM_BATCH_SIZE == 0:
            await asyncio.sleep(self.TELEGRAM_BATCH_COOLDOWN_SECONDS)
        else:
            await asyncio.sleep(self.TELEGRAM_PAGE_DELAY_SECONDS)

    async def _sleep_between_nitter_pages(self, pages_fetched: int) -> None:
        if pages_fetched % self.NITTER_BATCH_SIZE == 0:
            await asyncio.sleep(self.NITTER_BATCH_COOLDOWN_SECONDS)
        else:
            await asyncio.sleep(self.NITTER_PAGE_DELAY_SECONDS)

    def _estimate_pages(self, source_type: str, desired_posts: int, page_size: int) -> int:
        if desired_posts <= 0:
            return 0
        return max(1, math.ceil(desired_posts / max(page_size, 1)))

    def _estimate_seconds(self, source_type: str, estimated_pages: int) -> int:
        if estimated_pages <= 0:
            return 0

        if source_type == "telegram_rss":
            total = estimated_pages
            for page_number in range(1, estimated_pages):
                if page_number % self.TELEGRAM_BATCH_SIZE == 0:
                    total += self.TELEGRAM_BATCH_COOLDOWN_SECONDS
                else:
                    total += self.TELEGRAM_PAGE_DELAY_SECONDS
            return total

        if source_type == "nitter_rss":
            total = estimated_pages
            for page_number in range(1, estimated_pages):
                if page_number % self.NITTER_BATCH_SIZE == 0:
                    total += self.NITTER_BATCH_COOLDOWN_SECONDS
                else:
                    total += self.NITTER_PAGE_DELAY_SECONDS
            return total

        if source_type == "reddit_subreddit":
            return estimated_pages + max(0, estimated_pages - 1) * self.REDDIT_PAGE_DELAY_SECONDS

        if source_type == "youtube_channel":
            return estimated_pages + max(0, estimated_pages - 1) * self.YOUTUBE_PAGE_DELAY_SECONDS

        return estimated_pages

    def _persist_posts(self, source_id: str, posts: List[Dict[str, Any]]) -> Dict[str, int]:
        inserted = 0
        updated = 0

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                for post in posts:
                    _, was_inserted = self.posts_repo.upsert_post(cur, post, source_id)
                    if was_inserted:
                        inserted += 1
                    else:
                        updated += 1
            conn.commit()

        return {"inserted": inserted, "updated": updated}

    async def _record_archive_metadata(self, source_id: str, data: Dict[str, Any], mode: str) -> None:
        stats = self.posts_service.get_source_post_stats(source_id)
        source = self.sources_service.get_source_by_id(source_id)
        merged_settings = self.sources_service.get_source_with_settings(source_id)["settings"] if source else {}
        current_archive = (merged_settings or {}).get("archive", {})

        archive_status = current_archive.get("status", "not_archived")
        if mode == "archive":
            archive_status = self._derive_archive_status(stats["post_count"], data.get("available_posts"))

        archive_settings = {
            "archive": {
                "status": archive_status,
                "stored_posts": stats["post_count"],
                "available_posts": data.get("available_posts"),
                "first_post_date": data.get("first_post_date"),
                "last_archived_at": datetime.now(timezone.utc).isoformat() if mode == "archive" else current_archive.get("last_archived_at"),
                "last_live_fetch_at": datetime.now(timezone.utc).isoformat() if mode == "live" else current_archive.get("last_live_fetch_at"),
                "source_type": data.get("source_type"),
                "page_size": data.get("page_size", current_archive.get("page_size")),
                "estimated_pages": data.get("estimated_pages", current_archive.get("estimated_pages")),
                "estimated_seconds": data.get("estimated_seconds", current_archive.get("estimated_seconds")),
                "last_requested_posts": data.get("desired_posts", current_archive.get("last_requested_posts")),
                "last_pages_fetched": data.get("pages_fetched", current_archive.get("last_pages_fetched")),
            }
        }

        self.sources_service.merge_source_settings(source_id, archive_settings)

    def _derive_archive_status(self, stored_posts: int, available_posts: Optional[int]) -> str:
        if stored_posts <= 0:
            return "not_archived"
        if available_posts and stored_posts >= available_posts:
            return "archived"
        return "partial"

    def _normalize_feed_urls(self, value: str) -> str:
        if not isinstance(value, str):
            return value
        return self._normalize_telegram_resources(value)

    def _normalize_telegram_resources(self, value: str) -> str:
        replacements = (
            ("http://127.0.0.1:9504", self.TELEGRAM_BASE_URL),
            ("http://telegram.local:9504", self.TELEGRAM_BASE_URL),
            ("https://telegram.local:9504", self.TELEGRAM_BASE_URL),
        )

        normalized = value
        for old, new in replacements:
            normalized = normalized.replace(old, new)
        return normalized

    def _safe_text(self, value: Any) -> str:
        return str(value or "")

    def _strip_html(self, html_text: str) -> str:
        text = re.sub(r"<[^>]+>", " ", html_text or "")
        return re.sub(r"\s+", " ", text).strip()

    def _extract_telegram_username(self, source_url: str) -> str:
        segments = [segment for segment in urllib.parse.urlparse(source_url).path.split("/") if segment]
        if len(segments) < 2 or segments[0] != "rss":
            raise ValueError(f"Invalid Telegram RSS URL: {source_url}")
        return segments[1]

    def _extract_nitter_username(self, source_url: str) -> str:
        segments = [segment for segment in urllib.parse.urlparse(source_url).path.split("/") if segment]
        if len(segments) < 2 or segments[1] != "rss":
            raise ValueError(f"Invalid Nitter RSS URL: {source_url}")
        return segments[0]

    def _extract_reddit_subreddit(self, source_handle: str) -> str:
        if "reddit.com" in source_handle:
            parsed = urllib.parse.urlparse(source_handle)
            segments = [segment for segment in parsed.path.split("/") if segment]
            if len(segments) >= 2 and segments[0] == "r":
                return segments[1]
        return source_handle.replace("r/", "").strip("/")

    def _extract_nitter_tweet_count(self, profile_html: str) -> Optional[int]:
        match = re.search(
            r'<li class="posts">.*?<span class="profile-stat-num">([\d,]+)</span>',
            profile_html,
            re.DOTALL,
        )
        if not match:
            return None

        return int(match.group(1).replace(",", ""))

    def _extract_nitter_status_id(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        match = self.NITTER_STATUS_RE.search(value)
        return match.group("post_id") if match else None

    def _isoformat(self, value: Optional[datetime]) -> Optional[str]:
        if not value:
            return None
        return value.isoformat()

    def _local_name(self, tag: str) -> str:
        return tag.split("}", 1)[1] if "}" in tag else tag

    def _child_text(self, node: ET.Element, child_name: str) -> Optional[str]:
        for child in node:
            if self._local_name(child.tag) == child_name:
                return (child.text or "").strip()
        return None

    def _child_inner_xml(self, node: ET.Element, child_name: str) -> str:
        for child in node:
            if self._local_name(child.tag) != child_name:
                continue

            if len(child) == 0:
                return child.text or ""

            text = child.text or ""
            for subchild in child:
                text += ET.tostring(subchild, encoding="unicode")
            return text

        return ""

    def _extract_atom_link(self, entry: ET.Element) -> Optional[str]:
        fallback_href = None
        for child in entry:
            if self._local_name(child.tag) != "link":
                continue
            href = child.attrib.get("href")
            if not href:
                continue
            if child.attrib.get("rel") in (None, "", "alternate"):
                return href
            fallback_href = fallback_href or href
        return fallback_href

    def _parse_datetime_value(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None

        try:
            dt = parsedate_to_datetime(value)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass

        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
