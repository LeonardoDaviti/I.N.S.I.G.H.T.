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
import ssl
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
import psycopg

from insight_core.connectors import create_connector
from insight_core.db.repo_posts import PostsRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.event_memory_service import EventMemoryService
from insight_core.services.posts_service import PostsService
from insight_core.services.entity_memory_service import EntityMemoryService
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
        self.memory_service = EntityMemoryService(db_url)
        self.event_service = EventMemoryService(db_url)
        self.youtube_service = YouTubeService(db_url)
        self.logger = get_component_logger("source_fetch_service")
        self.timeout = int(os.getenv("RSS_TIMEOUT_SECONDS", str(self.DEFAULT_TIMEOUT_SECONDS)))
        self.user_agent = os.getenv("RSS_USER_AGENT", self.DEFAULT_USER_AGENT)
        self.reddit_user_agent = os.getenv(
            "REDDIT_USER_AGENT",
            "INSIGHT Archive Fetcher/1.0",
        )
        self.full_content_hosts = {
            host.strip().lower()
            for host in os.getenv("RSS_FULL_CONTENT_HOSTS", "news.smol.ai").split(",")
            if host.strip()
        }
        self.insecure_tls_hosts = {
            host.strip().lower()
            for host in os.getenv("RSS_SKIP_TLS_VERIFY_HOSTS", "").split(",")
            if host.strip()
        }

    async def plan_archive(
        self,
        source_id: str,
        desired_posts: Optional[int] = None,
        *,
        resume: bool = True,
        rate_limit_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Inspect a source and estimate archive effort."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        inspection = await self.inspect_source(source)
        source_with_settings = self.sources_service.get_source_with_settings(source_id)
        current_archive = (source_with_settings.get("settings") or {}).get("archive", {})
        effective_rate_limit = self._resolve_rate_limit(
            inspection["source_type"],
            current_archive.get("rate_limit"),
            rate_limit_overrides,
        )
        checkpoint = current_archive.get("checkpoint") if resume else None
        resume_available = self._checkpoint_is_resumable(checkpoint)
        resume_collected_posts = int((checkpoint or {}).get("collected_posts") or 0) if resume_available else 0
        desired = desired_posts or inspection["available_posts"] or source.get("settings", {}).get("max_posts_per_fetch", 50)
        desired = min(desired, inspection["available_posts"] or desired)
        remaining_posts = max(0, desired - resume_collected_posts)
        estimated_pages = self._estimate_pages(inspection["source_type"], remaining_posts, inspection["page_size"])

        inspection.update({
            "desired_posts": desired,
            "remaining_posts": remaining_posts,
            "estimated_pages": estimated_pages,
            "estimated_seconds": self._estimate_seconds(inspection["source_type"], estimated_pages, effective_rate_limit),
            "source_id": source_id,
            "current_stored_posts": self.posts_service.get_source_post_stats(source_id)["post_count"],
            "resume": bool(resume and resume_available),
            "resume_available": resume_available,
            "checkpoint": checkpoint if resume_available else None,
            "rate_limit": effective_rate_limit,
        })

        await self._record_archive_metadata(source_id, inspection, mode="plan")
        return inspection

    async def archive_source(
        self,
        source_id: str,
        desired_posts: Optional[int] = None,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
        *,
        resume: bool = True,
        rate_limit_overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Archive historical posts for a single source."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        plan = await self.plan_archive(
            source_id,
            desired_posts,
            resume=resume,
            rate_limit_overrides=rate_limit_overrides,
        )
        source_type = plan["source_type"]
        target_posts = plan["desired_posts"]
        rate_limit = plan.get("rate_limit") or {}
        checkpoint = plan.get("checkpoint") or {}
        resume_collected_posts = int(checkpoint.get("collected_posts") or 0) if plan.get("resume") else 0
        total_pages_fetched = int(checkpoint.get("pages_fetched") or 0) if plan.get("resume") else 0
        total_posts_fetched = 0
        total_inserted = 0
        total_updated = 0
        await self._emit_progress(
            progress_callback,
            {
                "stage": "planning_complete",
                "source_type": source_type,
                "target_posts": target_posts,
                "remaining_posts": plan.get("remaining_posts", target_posts),
                "estimated_pages": plan.get("estimated_pages"),
                "estimated_seconds": plan.get("estimated_seconds"),
                "message": f"Planning complete for {target_posts} posts",
                "progress": min(100.0, (resume_collected_posts / max(target_posts, 1)) * 100.0),
            },
        )

        if plan.get("remaining_posts", 0) <= 0:
            post_stats = self.posts_service.get_source_post_stats(source_id)
            result = {
                **plan,
                "success": True,
                "posts_fetched": 0,
                "pages_fetched": total_pages_fetched,
                "posts_inserted": 0,
                "posts_updated": 0,
                "stored_posts": post_stats["post_count"],
                "archive_status": self._derive_archive_status(post_stats["post_count"], plan["available_posts"]),
                "message": "Archive already covers the requested range",
            }
            await self._record_archive_metadata(source_id, result, mode="archive")
            return result

        async def persist_archive_page(page_posts: List[Dict[str, Any]], checkpoint_payload: Dict[str, Any], _progress_payload: Dict[str, Any]) -> None:
            nonlocal total_pages_fetched, total_posts_fetched, total_inserted, total_updated
            if page_posts:
                saved = self._persist_posts(source_id, page_posts)
                total_posts_fetched += len(page_posts)
                total_inserted += saved["inserted"]
                total_updated += saved["updated"]
            total_pages_fetched = int(checkpoint_payload.get("pages_fetched") or total_pages_fetched)
            await self._record_archive_metadata(
                source_id,
                {
                    **plan,
                    "pages_fetched": total_pages_fetched,
                    "posts_fetched": total_posts_fetched,
                    "posts_inserted": total_inserted,
                    "posts_updated": total_updated,
                    "checkpoint": checkpoint_payload,
                    "rate_limit": rate_limit,
                },
                mode="archive_progress",
            )

        if source_type == "telegram_rss":
            posts, pages_fetched, checkpoint = await self._collect_telegram_posts(
                source["handle_or_url"],
                target_posts,
                start_page=int(checkpoint.get("next_page") or 1) if plan.get("resume") else 1,
                initial_collected=resume_collected_posts,
                initial_pages_fetched=total_pages_fetched,
                progress_callback=progress_callback,
                page_callback=persist_archive_page,
                rate_limit=rate_limit,
            )
        elif source_type == "nitter_rss":
            posts, pages_fetched, checkpoint = await self._collect_nitter_posts(
                source["handle_or_url"],
                target_posts,
                cursor=checkpoint.get("cursor") if plan.get("resume") else None,
                initial_collected=resume_collected_posts,
                initial_pages_fetched=total_pages_fetched,
                progress_callback=progress_callback,
                page_callback=persist_archive_page,
                rate_limit=rate_limit,
            )
        elif source_type == "youtube_channel":
            youtube_result = self.youtube_service.archive_channel_posts(source["handle_or_url"], target_posts)
            posts = youtube_result["posts"]
            pages_fetched = youtube_result["pages_fetched"]
            checkpoint = {
                "mode": "youtube",
                "pages_fetched": pages_fetched,
                "collected_posts": len(posts),
            }
        elif source_type == "reddit_subreddit":
            posts, pages_fetched, checkpoint = await self._collect_reddit_posts(
                source["handle_or_url"],
                target_posts,
                after=checkpoint.get("after") if plan.get("resume") else None,
                initial_collected=resume_collected_posts,
                initial_pages_fetched=total_pages_fetched,
                progress_callback=progress_callback,
                page_callback=persist_archive_page,
                rate_limit=rate_limit,
            )
        elif source_type == "generic_rss":
            posts = await self.fetch_live_posts(source, target_posts)
            pages_fetched = 1
            checkpoint = {
                "mode": "generic_rss",
                "pages_fetched": 1,
                "collected_posts": len(posts),
            }
        else:
            raise ValueError(f"Archive is not supported for source type {source_type}")

        if source_type in {"generic_rss", "youtube_channel"}:
            saved = self._persist_posts(source_id, posts)
            total_posts_fetched += len(posts)
            total_inserted += saved["inserted"]
            total_updated += saved["updated"]
            total_pages_fetched = pages_fetched
        post_stats = self.posts_service.get_source_post_stats(source_id)

        result = {
            **plan,
            "success": True,
            "posts_fetched": total_posts_fetched,
            "pages_fetched": total_pages_fetched,
            "posts_inserted": total_inserted,
            "posts_updated": total_updated,
            "stored_posts": post_stats["post_count"],
            "archive_status": self._derive_archive_status(post_stats["post_count"], plan["available_posts"]),
            "checkpoint": checkpoint,
        }

        await self._record_archive_metadata(source_id, result, mode="archive")
        await self._emit_progress(
            progress_callback,
            {
                "stage": "completed",
                "source_type": source_type,
                "pages_fetched": total_pages_fetched,
                "posts_fetched": total_posts_fetched,
                "posts_inserted": total_inserted,
                "posts_updated": total_updated,
                "stored_posts": post_stats["post_count"],
                "message": f"Archive completed with {total_posts_fetched} posts",
                "progress": 100,
            },
        )
        return result

    async def ingest_source_now(self, source_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
        """Fetch the latest posts for a single source immediately."""
        source = self.sources_service.get_source_by_id(source_id)
        if not source:
            raise ValueError(f"Source {source_id} not found")

        source_settings = source.get("settings") or {}
        target_limit = max(1, int(limit or source_settings.get("max_posts_per_fetch", 20) or 20))
        display_name = source_settings.get("display_name") or source["handle_or_url"]
        platform = source["platform"]

        if platform in {"rss", "reddit", "youtube"}:
            posts = await self.fetch_live_posts(source, target_limit)
        else:
            connector = create_connector(platform)
            if connector is None:
                raise ValueError(f"Connector unavailable or not configured for platform {platform}")

            setup_connector = getattr(connector, "setup_connector", None)
            if callable(setup_connector):
                setup_connector()

            await connector.connect()
            try:
                posts = await connector.fetch_posts(source["handle_or_url"], limit=target_limit)
            finally:
                await connector.disconnect()

        saved = self._persist_posts(source_id, posts)
        if platform in {"rss", "reddit", "youtube"}:
            await self.record_live_fetch(source_id, source, fetched_posts=len(posts))

        post_stats = self.posts_service.get_source_post_stats(source_id)
        return {
            "success": True,
            "source_id": source_id,
            "source": {
                "display_name": display_name,
                "platform": platform,
                "handle_or_url": source["handle_or_url"],
            },
            "fetched_limit": target_limit,
            "posts_fetched": len(posts),
            "posts_inserted": saved["inserted"],
            "posts_updated": saved["updated"],
            "stored_posts": post_stats["post_count"],
        }

    async def fetch_live_posts(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        """Fetch latest posts for an RSS-style source."""
        source_type = self.classify_source(source)

        if source_type == "telegram_rss":
            posts, _, _ = await self._collect_telegram_posts(source["handle_or_url"], limit, apply_rate_limits=False)
            return posts

        if source_type == "nitter_rss":
            posts, _, _ = await self._collect_nitter_posts(source["handle_or_url"], limit)
            return posts

        if source_type == "youtube_channel":
            return self.youtube_service.fetch_live_posts(source["handle_or_url"], limit)

        if source_type == "reddit_subreddit":
            return await self._fetch_reddit_live_posts(source["handle_or_url"], limit)

        feed_text, _ = await self._fetch_text(source["handle_or_url"])
        posts = self._parse_feed_posts(feed_text, source["handle_or_url"])[:limit]
        return await self._maybe_enrich_generic_rss_posts(source, posts)

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
        page_one_posts = await self._fetch_telegram_page(source_url, username, 1)

        if not page_one_posts:
            raise ValueError(f"No canonical Telegram posts found for {username}")

        highest_post_id = max(int(post["external_id"]) for post in page_one_posts if post.get("external_id"))
        page_size = max(1, len(page_one_posts))
        last_page_number = await self._find_last_telegram_page(source_url, username, highest_post_id, page_size)
        last_page_posts = await self._fetch_telegram_page(source_url, username, last_page_number)
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
        profile_url = f"{self._nitter_origin(source_url)}/{username}"
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

    async def _maybe_enrich_generic_rss_posts(self, source: Dict[str, Any], posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not posts:
            return posts

        source_settings = source.get("settings") or {}
        source_host = (urllib.parse.urlparse(source["handle_or_url"]).hostname or "").lower()
        should_expand = bool(source_settings.get("fetch_full_content")) or source_host in self.full_content_hosts
        if not should_expand:
            return posts

        enriched_posts: List[Dict[str, Any]] = []
        for post in posts:
            enriched_posts.append(await self._maybe_expand_article_body(post))
        return enriched_posts

    async def _maybe_expand_article_body(self, post: Dict[str, Any]) -> Dict[str, Any]:
        url = post.get("url")
        if not isinstance(url, str) or not url.startswith("http"):
            return post

        current_content = self._strip_html(post.get("content_html") or post.get("content") or "")
        if len(current_content) >= 1400:
            return post

        try:
            article_html, _ = await self._fetch_text(url)
            extracted_html = self._extract_article_html(article_html)
            extracted_text = self._strip_html(extracted_html)
            if len(extracted_text) <= max(len(current_content) + 250, 700):
                return post

            next_metadata = dict(post.get("metadata") or {})
            next_metadata["full_content_fetched"] = True
            next_post = dict(post)
            next_post["content_html"] = extracted_html
            next_post["content"] = extracted_text
            next_post["metadata"] = next_metadata
            return next_post
        except Exception as exc:
            self.logger.debug("Full-content expansion skipped for %s: %s", url, exc)
            return post

    async def _collect_telegram_posts(
        self,
        source_url: str,
        target_posts: int,
        apply_rate_limits: bool = True,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
        *,
        start_page: int = 1,
        initial_collected: int = 0,
        initial_pages_fetched: int = 0,
        page_callback: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]], Awaitable[None] | None]] = None,
        rate_limit: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
        username = self._extract_telegram_username(source_url)
        collected: List[Dict[str, Any]] = []
        seen_urls = set()
        page = max(1, int(start_page or 1))
        pages_fetched = int(initial_pages_fetched or 0)
        checkpoint = {
            "mode": "telegram_page",
            "next_page": page,
            "pages_fetched": pages_fetched,
            "collected_posts": int(initial_collected or 0),
        }

        while (len(collected) + initial_collected) < target_posts:
            page_posts = await self._fetch_telegram_page(source_url, username, page)
            if not page_posts:
                break

            pages_fetched += 1
            unique_page_posts: List[Dict[str, Any]] = []
            for post in page_posts:
                if post["url"] not in seen_urls:
                    seen_urls.add(post["url"])
                    unique_page_posts.append(post)
                    collected.append(post)
                    if (len(collected) + initial_collected) >= target_posts:
                        break

            checkpoint = {
                "mode": "telegram_page",
                "next_page": page + 1,
                "last_page": page,
                "pages_fetched": pages_fetched,
                "collected_posts": len(collected) + initial_collected,
            }
            progress_payload = {
                "stage": "page_fetched",
                "platform": "telegram",
                "page": page,
                "pages_fetched": pages_fetched,
                "posts_collected": len(collected) + initial_collected,
                "target_posts": target_posts,
                "progress": min(100.0, ((len(collected) + initial_collected) / max(target_posts, 1)) * 100),
                "message": f"Fetched Telegram page {page}",
            }
            await self._emit_page(page_callback, unique_page_posts, checkpoint, progress_payload)
            await self._emit_progress(
                progress_callback,
                progress_payload,
            )

            page += 1
            if (len(collected) + initial_collected) < target_posts and apply_rate_limits:
                await self._sleep_between_telegram_pages(pages_fetched, rate_limit)

        return collected[: max(0, target_posts - initial_collected)], pages_fetched, checkpoint

    async def _collect_nitter_posts(
        self,
        source_url: str,
        target_posts: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
        *,
        cursor: Optional[str] = None,
        initial_collected: int = 0,
        initial_pages_fetched: int = 0,
        page_callback: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]], Awaitable[None] | None]] = None,
        rate_limit: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
        username = self._extract_nitter_username(source_url)
        collected: List[Dict[str, Any]] = []
        seen_urls = set()
        current_cursor: Optional[str] = cursor
        pages_fetched = int(initial_pages_fetched or 0)
        checkpoint = {
            "mode": "nitter_cursor",
            "cursor": current_cursor,
            "pages_fetched": pages_fetched,
            "collected_posts": int(initial_collected or 0),
        }

        while (len(collected) + initial_collected) < target_posts:
            page_posts, next_cursor = await self._fetch_nitter_page(source_url, username, current_cursor)
            if not page_posts:
                break

            pages_fetched += 1
            unique_page_posts: List[Dict[str, Any]] = []
            for post in page_posts:
                if post["url"] not in seen_urls:
                    seen_urls.add(post["url"])
                    unique_page_posts.append(post)
                    collected.append(post)
                    if (len(collected) + initial_collected) >= target_posts:
                        break

            checkpoint = {
                "mode": "nitter_cursor",
                "cursor": next_cursor,
                "last_cursor": current_cursor,
                "pages_fetched": pages_fetched,
                "collected_posts": len(collected) + initial_collected,
            }
            progress_payload = {
                "stage": "page_fetched",
                "platform": "nitter",
                "pages_fetched": pages_fetched,
                "posts_collected": len(collected) + initial_collected,
                "target_posts": target_posts,
                "cursor": next_cursor,
                "progress": min(100.0, ((len(collected) + initial_collected) / max(target_posts, 1)) * 100),
                "message": f"Fetched Nitter page {pages_fetched}",
            }
            await self._emit_page(page_callback, unique_page_posts, checkpoint, progress_payload)
            await self._emit_progress(
                progress_callback,
                progress_payload,
            )

            if (len(collected) + initial_collected) >= target_posts or not next_cursor or next_cursor == current_cursor:
                break

            current_cursor = next_cursor
            await self._sleep_between_nitter_pages(pages_fetched, rate_limit)

        return collected[: max(0, target_posts - initial_collected)], pages_fetched, checkpoint

    async def _collect_reddit_posts(
        self,
        source_handle: str,
        target_posts: int,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]] = None,
        *,
        after: Optional[str] = None,
        initial_collected: int = 0,
        initial_pages_fetched: int = 0,
        page_callback: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]], Awaitable[None] | None]] = None,
        rate_limit: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], int, Dict[str, Any]]:
        subreddit = self._extract_reddit_subreddit(source_handle)
        collected: List[Dict[str, Any]] = []
        current_after: Optional[str] = after
        pages_fetched = int(initial_pages_fetched or 0)
        checkpoint = {
            "mode": "reddit_after",
            "after": current_after,
            "pages_fetched": pages_fetched,
            "collected_posts": int(initial_collected or 0),
        }

        while (len(collected) + initial_collected) < target_posts:
            page_limit = min(100, target_posts - (len(collected) + initial_collected))
            page_posts, next_after = await self._fetch_reddit_page(subreddit, after=current_after, limit=page_limit)
            if not page_posts:
                break

            pages_fetched += 1
            collected.extend(page_posts)
            checkpoint = {
                "mode": "reddit_after",
                "after": next_after,
                "last_after": current_after,
                "pages_fetched": pages_fetched,
                "collected_posts": len(collected) + initial_collected,
            }
            progress_payload = {
                "stage": "page_fetched",
                "platform": "reddit",
                "pages_fetched": pages_fetched,
                "posts_collected": len(collected) + initial_collected,
                "target_posts": target_posts,
                "after": next_after,
                "progress": min(100.0, ((len(collected) + initial_collected) / max(target_posts, 1)) * 100),
                "message": f"Fetched Reddit page {pages_fetched}",
            }
            await self._emit_page(page_callback, page_posts, checkpoint, progress_payload)
            await self._emit_progress(
                progress_callback,
                progress_payload,
            )

            if not next_after:
                break

            current_after = next_after
            if (len(collected) + initial_collected) < target_posts:
                await asyncio.sleep(int((rate_limit or {}).get("page_delay_seconds", self.REDDIT_PAGE_DELAY_SECONDS)))

        return collected[: max(0, target_posts - initial_collected)], pages_fetched, checkpoint

    async def _fetch_telegram_page(self, source_url: str, username: str, page: int) -> List[Dict[str, Any]]:
        telegram_origin = self._telegram_origin(source_url)
        url = f"{telegram_origin}/rss/{username}/{page}"
        body, _ = await self._fetch_text(url)

        if body.lstrip().startswith("{"):
            payload = json.loads(body)
            raise ValueError(payload.get("errors", payload))

        posts = self._parse_feed_posts(body, f"{telegram_origin}/rss/{username}")
        canonical_posts: List[Dict[str, Any]] = []

        for post in posts:
            match = self.TELEGRAM_CANONICAL_RE.match(post["url"])
            if not match:
                continue

            if post.get("title", "").startswith("[Sponsored]"):
                continue

            post["external_id"] = match.group("post_id")
            post["url"] = f"https://t.me/{match.group('username')}/{match.group('post_id')}"
            post["content_html"] = self._normalize_telegram_resources(post.get("content_html", ""), telegram_origin)
            post["content"] = self._strip_html(post["content_html"])
            post["media_urls"] = [
                self._normalize_telegram_resources(media_url, telegram_origin)
                for media_url in post.get("media_urls", [])
            ]
            canonical_posts.append(post)

        return canonical_posts

    async def _fetch_nitter_page(
        self,
        source_url: str,
        username: str,
        cursor: Optional[str],
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        nitter_origin = self._nitter_origin(source_url)
        url = f"{nitter_origin}/{username}/rss"
        if cursor:
            encoded_cursor = urllib.parse.quote(cursor, safe="")
            url = f"{url}?cursor={encoded_cursor}"

        body, headers = await self._fetch_text(url)
        posts = self._parse_feed_posts(body, f"{nitter_origin}/{username}/rss")

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

    async def fetch_reddit_comments_for_post(self, post_url: str, limit: int = 80) -> List[Dict[str, Any]]:
        """Fetch a Reddit post discussion thread on demand via the public JSON endpoint."""
        json_url = self._build_reddit_post_json_url(post_url, limit=max(1, min(limit, 250)))
        body, _ = await self._fetch_text(json_url, user_agent=self.reddit_user_agent)
        payload = json.loads(body)

        if not isinstance(payload, list) or len(payload) < 2:
            return []

        comments_listing = payload[1].get("data", {}).get("children", [])
        comments: List[Dict[str, Any]] = []

        def visit(nodes: List[Dict[str, Any]], depth: int = 0) -> None:
            if len(comments) >= limit:
                return
            for node in nodes:
                if len(comments) >= limit:
                    return
                if node.get("kind") != "t1":
                    continue
                data = node.get("data", {}) or {}
                body_text = str(data.get("body") or "").strip()
                if not body_text or body_text in {"[deleted]", "[removed]"}:
                    continue

                comments.append(
                    {
                        "id": data.get("id"),
                        "author": data.get("author"),
                        "body": body_text,
                        "score": data.get("score"),
                        "depth": depth,
                        "created_at": datetime.fromtimestamp(
                            data.get("created_utc", 0),
                            tz=timezone.utc,
                        ).isoformat(),
                        "permalink": f"https://reddit.com{data.get('permalink', '')}" if data.get("permalink") else None,
                    }
                )

                replies = data.get("replies")
                if isinstance(replies, dict):
                    visit(replies.get("data", {}).get("children", []), depth + 1)

        visit(comments_listing, 0)
        return comments[:limit]

    async def _fetch_text(self, url: str, user_agent: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
        return await asyncio.to_thread(self._fetch_text_sync, url, user_agent)

    async def _emit_progress(
        self,
        progress_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None] | None]],
        payload: Dict[str, Any],
    ) -> None:
        if progress_callback is None:
            return
        result = progress_callback(payload)
        if asyncio.iscoroutine(result):
            await result

    async def _emit_page(
        self,
        page_callback: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]], Awaitable[None] | None]],
        page_posts: List[Dict[str, Any]],
        checkpoint: Dict[str, Any],
        progress_payload: Dict[str, Any],
    ) -> None:
        if page_callback is None:
            return
        result = page_callback(page_posts, checkpoint, progress_payload)
        if asyncio.iscoroutine(result):
            await result

    def _fetch_text_sync(self, url: str, user_agent: Optional[str] = None) -> Tuple[str, Dict[str, str]]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": user_agent or self.user_agent, "Accept": "*/*"},
        )
        parsed = urllib.parse.urlparse(url)
        context = None
        if parsed.scheme == "https" and self._should_skip_tls_verify(parsed.hostname):
            context = ssl._create_unverified_context()

        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=context) as response:
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

    def _build_reddit_post_json_url(self, post_url: str, limit: int) -> str:
        parsed = urllib.parse.urlparse(post_url)
        path = parsed.path.rstrip("/")
        if not path.endswith(".json"):
            path = f"{path}.json"
        query = urllib.parse.urlencode({
            "limit": str(limit),
            "depth": "8",
            "sort": "top",
            "raw_json": "1",
        })
        return urllib.parse.urlunparse((
            parsed.scheme or "https",
            parsed.netloc or "www.reddit.com",
            path,
            "",
            query,
            "",
        ))

    async def _find_last_telegram_page(self, source_url: str, username: str, highest_post_id: int, page_size: int) -> int:
        estimated_last_page = max(1, math.ceil(highest_post_id / max(page_size, 1)))
        low = 1
        high = estimated_last_page

        while await self._telegram_page_has_posts(source_url, username, high):
            low = high
            high *= 2

        while low < high:
            mid = (low + high + 1) // 2
            if await self._telegram_page_has_posts(source_url, username, mid):
                low = mid
            else:
                high = mid - 1

        return low

    async def _telegram_page_has_posts(self, source_url: str, username: str, page: int) -> bool:
        posts = await self._fetch_telegram_page(source_url, username, page)
        return bool(posts)

    async def _sleep_between_telegram_pages(self, pages_fetched: int, rate_limit: Optional[Dict[str, Any]] = None) -> None:
        page_delay = int((rate_limit or {}).get("page_delay_seconds", self.TELEGRAM_PAGE_DELAY_SECONDS))
        batch_size = max(1, int((rate_limit or {}).get("batch_size", self.TELEGRAM_BATCH_SIZE)))
        batch_cooldown = int((rate_limit or {}).get("batch_cooldown_seconds", self.TELEGRAM_BATCH_COOLDOWN_SECONDS))
        if pages_fetched % batch_size == 0:
            await asyncio.sleep(batch_cooldown)
        else:
            await asyncio.sleep(page_delay)

    async def _sleep_between_nitter_pages(self, pages_fetched: int, rate_limit: Optional[Dict[str, Any]] = None) -> None:
        page_delay = int((rate_limit or {}).get("page_delay_seconds", self.NITTER_PAGE_DELAY_SECONDS))
        batch_size = max(1, int((rate_limit or {}).get("batch_size", self.NITTER_BATCH_SIZE)))
        batch_cooldown = int((rate_limit or {}).get("batch_cooldown_seconds", self.NITTER_BATCH_COOLDOWN_SECONDS))
        if pages_fetched % batch_size == 0:
            await asyncio.sleep(batch_cooldown)
        else:
            await asyncio.sleep(page_delay)

    def _estimate_pages(self, source_type: str, desired_posts: int, page_size: int) -> int:
        if desired_posts <= 0:
            return 0
        return max(1, math.ceil(desired_posts / max(page_size, 1)))

    def _estimate_seconds(self, source_type: str, estimated_pages: int, rate_limit: Optional[Dict[str, Any]] = None) -> int:
        if estimated_pages <= 0:
            return 0

        if source_type == "telegram_rss":
            page_delay = int((rate_limit or {}).get("page_delay_seconds", self.TELEGRAM_PAGE_DELAY_SECONDS))
            batch_size = max(1, int((rate_limit or {}).get("batch_size", self.TELEGRAM_BATCH_SIZE)))
            batch_cooldown = int((rate_limit or {}).get("batch_cooldown_seconds", self.TELEGRAM_BATCH_COOLDOWN_SECONDS))
            total = estimated_pages
            for page_number in range(1, estimated_pages):
                if page_number % batch_size == 0:
                    total += batch_cooldown
                else:
                    total += page_delay
            return total

        if source_type == "nitter_rss":
            page_delay = int((rate_limit or {}).get("page_delay_seconds", self.NITTER_PAGE_DELAY_SECONDS))
            batch_size = max(1, int((rate_limit or {}).get("batch_size", self.NITTER_BATCH_SIZE)))
            batch_cooldown = int((rate_limit or {}).get("batch_cooldown_seconds", self.NITTER_BATCH_COOLDOWN_SECONDS))
            total = estimated_pages
            for page_number in range(1, estimated_pages):
                if page_number % batch_size == 0:
                    total += batch_cooldown
                else:
                    total += page_delay
            return total

        if source_type == "reddit_subreddit":
            page_delay = int((rate_limit or {}).get("page_delay_seconds", self.REDDIT_PAGE_DELAY_SECONDS))
            return estimated_pages + max(0, estimated_pages - 1) * page_delay

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

        if posts:
            try:
                memory_result = self.memory_service.process_posts(
                    [
                        {
                            **post,
                            "_source_id": source_id,
                        }
                        for post in posts
                    ]
                )
            except Exception as exc:
                self.logger.warning("Entity memory enrichment skipped for %s: %s", source_id, exc)
                memory_result = {"posts_processed": 0, "mentions_created": 0, "entities_linked": 0}
            try:
                self.event_service.process_posts(
                    [
                        {
                            **post,
                            "_source_id": source_id,
                        }
                        for post in posts
                    ]
                )
            except Exception as exc:
                self.logger.warning("Event memory enrichment skipped for %s: %s", source_id, exc)
        else:
            memory_result = {"posts_processed": 0, "mentions_created": 0, "entities_linked": 0}

        return {
            "inserted": inserted,
            "updated": updated,
            "memory_processed": int(memory_result.get("posts_processed", 0)),
            "memory_mentions": int(memory_result.get("mentions_created", 0)),
            "memory_entities": int(memory_result.get("entities_linked", 0)),
        }

    async def _record_archive_metadata(self, source_id: str, data: Dict[str, Any], mode: str) -> None:
        stats = self.posts_service.get_source_post_stats(source_id)
        source = self.sources_service.get_source_by_id(source_id)
        merged_settings = self.sources_service.get_source_with_settings(source_id)["settings"] if source else {}
        current_archive = (merged_settings or {}).get("archive", {})

        archive_status = current_archive.get("status", "not_archived")
        if mode in {"archive", "archive_progress"}:
            archive_status = self._derive_archive_status(stats["post_count"], data.get("available_posts"))
        history = list(current_archive.get("history") or [])
        if mode in {"plan", "archive", "live"}:
            history.append(self._archive_history_event(mode, stats, data))
        checkpoint = self._prepare_checkpoint(current_archive, data, mode)

        archive_settings = {
            "archive": {
                "status": archive_status,
                "stored_posts": stats["post_count"],
                "available_posts": data.get("available_posts", current_archive.get("available_posts")),
                "first_post_date": data.get("first_post_date", current_archive.get("first_post_date")),
                "last_archived_at": datetime.now(timezone.utc).isoformat() if mode == "archive" else current_archive.get("last_archived_at"),
                "last_live_fetch_at": datetime.now(timezone.utc).isoformat() if mode == "live" else current_archive.get("last_live_fetch_at"),
                "source_type": data.get("source_type", current_archive.get("source_type")),
                "page_size": data.get("page_size", current_archive.get("page_size")),
                "estimated_pages": data.get("estimated_pages", current_archive.get("estimated_pages")),
                "estimated_seconds": data.get("estimated_seconds", current_archive.get("estimated_seconds")),
                "last_requested_posts": data.get("desired_posts", current_archive.get("last_requested_posts")),
                "last_pages_fetched": data.get("pages_fetched", current_archive.get("last_pages_fetched")),
                "remaining_posts": data.get("remaining_posts", current_archive.get("remaining_posts")),
                "rate_limit": data.get("rate_limit", current_archive.get("rate_limit")),
                "checkpoint": checkpoint,
                "resume_ready": self._checkpoint_is_resumable(checkpoint),
                "history": history[-40:],
            }
        }

        self.sources_service.merge_source_settings(source_id, archive_settings)

    def _derive_archive_status(self, stored_posts: int, available_posts: Optional[int]) -> str:
        if stored_posts <= 0:
            return "not_archived"
        if available_posts and stored_posts >= available_posts:
            return "archived"
        return "partial"

    def _resolve_rate_limit(
        self,
        source_type: str,
        current_rate_limit: Optional[Dict[str, Any]] = None,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if source_type == "telegram_rss":
            defaults: Dict[str, Any] = {
                "page_delay_seconds": self.TELEGRAM_PAGE_DELAY_SECONDS,
                "batch_size": self.TELEGRAM_BATCH_SIZE,
                "batch_cooldown_seconds": self.TELEGRAM_BATCH_COOLDOWN_SECONDS,
            }
        elif source_type == "nitter_rss":
            defaults = {
                "page_delay_seconds": self.NITTER_PAGE_DELAY_SECONDS,
                "batch_size": self.NITTER_BATCH_SIZE,
                "batch_cooldown_seconds": self.NITTER_BATCH_COOLDOWN_SECONDS,
            }
        elif source_type == "reddit_subreddit":
            defaults = {
                "page_delay_seconds": self.REDDIT_PAGE_DELAY_SECONDS,
            }
        else:
            defaults = {
                "page_delay_seconds": 0,
            }

        normalized = {**defaults}
        for payload in (current_rate_limit or {}, overrides or {}):
            for key, value in payload.items():
                if value is None or key not in defaults:
                    continue
                normalized[key] = max(0, int(value))
        if "batch_size" in normalized:
            normalized["batch_size"] = max(1, int(normalized["batch_size"]))
        return normalized

    def _checkpoint_is_resumable(self, checkpoint: Any) -> bool:
        if not isinstance(checkpoint, dict):
            return False
        if checkpoint.get("mode") == "telegram_page":
            return bool(checkpoint.get("next_page"))
        if checkpoint.get("mode") == "nitter_cursor":
            return checkpoint.get("cursor") is not None
        if checkpoint.get("mode") == "reddit_after":
            return checkpoint.get("after") is not None
        return False

    def _prepare_checkpoint(self, current_archive: Dict[str, Any], data: Dict[str, Any], mode: str) -> Optional[Dict[str, Any]]:
        if mode == "archive_progress":
            checkpoint = data.get("checkpoint")
            return dict(checkpoint) if isinstance(checkpoint, dict) else current_archive.get("checkpoint")
        if mode == "archive":
            checkpoint = data.get("checkpoint")
            if not isinstance(checkpoint, dict):
                return None
            next_checkpoint = dict(checkpoint)
            next_checkpoint["completed_at"] = datetime.now(timezone.utc).isoformat()
            if data.get("archive_status") == "archived":
                next_checkpoint["completed"] = True
            return next_checkpoint
        return current_archive.get("checkpoint")

    def _archive_history_event(self, mode: str, stats: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "status": data.get("archive_status") or data.get("status"),
            "stored_posts": stats.get("post_count", 0),
            "available_posts": data.get("available_posts"),
            "desired_posts": data.get("desired_posts"),
            "pages_fetched": data.get("pages_fetched"),
            "source_type": data.get("source_type"),
        }

    def _normalize_feed_urls(self, value: str) -> str:
        if not isinstance(value, str):
            return value
        return self._normalize_telegram_resources(value)

    def _normalize_telegram_resources(self, value: str, telegram_origin: Optional[str] = None) -> str:
        target_origin = telegram_origin or self.TELEGRAM_BASE_URL
        replacements = (
            ("http://127.0.0.1:9504", target_origin),
            ("http://telegram.local:9504", target_origin),
            ("https://telegram.local:9504", target_origin),
            (self.TELEGRAM_BASE_URL, target_origin),
            ("http://telegram.local", target_origin),
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

    def _extract_article_html(self, html_text: str) -> str:
        cleaned = re.sub(r"(?is)<(script|style|noscript|iframe|svg).*?</\1>", "", html_text or "")
        candidate_patterns = [
            r"(?is)<article\b[^>]*>(.*?)</article>",
            r"(?is)<main\b[^>]*>(.*?)</main>",
            r'(?is)<div\b[^>]+class="[^"]*(?:entry-content|post-content|article-content|content-body|prose|single-post-content)[^"]*"[^>]*>(.*?)</div>',
        ]

        candidate = ""
        for pattern in candidate_patterns:
            match = re.search(pattern, cleaned)
            if match:
                candidate = match.group(1)
                break

        if not candidate:
            body_match = re.search(r"(?is)<body\b[^>]*>(.*?)</body>", cleaned)
            candidate = body_match.group(1) if body_match else cleaned

        blocks = re.findall(r"(?is)<(?:h1|h2|h3|p|blockquote|li)[^>]*>.*?</(?:h1|h2|h3|p|blockquote|li)>", candidate)
        if not blocks:
            blocks = re.findall(r"(?is)<(?:h1|h2|h3|p|blockquote|li)[^>]*>.*?</(?:h1|h2|h3|p|blockquote|li)>", cleaned)

        text_size = len(self._strip_html(" ".join(blocks)))
        if text_size < 500:
            return ""

        return "\n".join(blocks)

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

    def _telegram_origin(self, source_url: str) -> str:
        return self._origin_from_source(source_url, self.TELEGRAM_BASE_URL)

    def _nitter_origin(self, source_url: str) -> str:
        return self._origin_from_source(source_url, self.NITTER_BASE_URL)

    def _origin_from_source(self, source_url: str, fallback: str) -> str:
        parsed = urllib.parse.urlparse(source_url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
        return fallback

    def _should_skip_tls_verify(self, hostname: Optional[str]) -> bool:
        if not hostname:
            return False
        host = hostname.lower()
        if host in self.insecure_tls_hosts:
            return True
        return host.endswith(".local")

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
