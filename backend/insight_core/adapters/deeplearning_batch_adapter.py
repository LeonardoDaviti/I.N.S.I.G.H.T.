"""DeepLearning.AI The Batch newsletter adapter."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from insight_core.adapters.base_adapter import BaseSourceAdapter


class DeepLearningBatchAdapter(BaseSourceAdapter):
    """Archive The Batch via CharonHub sitemap discovery and Next.js post hydration."""

    adapter_type = "deeplearning_batch_site"
    HOSTS = {"www.deeplearning.ai", "deeplearning.ai"}
    PATH_PREFIX = "/the-batch"
    PAGE_SIZE = 10
    PAGE_DELAY_SECONDS = 1
    CHARON_SITEMAP_URL = "https://charonhub.deeplearning.ai/sitemap-posts.xml"
    NEXT_DATA_RE = re.compile(
        r'(?is)<script id="__NEXT_DATA__" type="application/json">\s*(?P<payload>\{.*?\})\s*</script>'
    )
    ISSUE_PATH_RE = re.compile(r"^/issue-(?P<issue>\d+)/?$")

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in self.HOSTS and (parsed.path or "").startswith(self.PATH_PREFIX)

    def default_rate_limit(self) -> Dict[str, Any]:
        return {"page_delay_seconds": self.PAGE_DELAY_SECONDS}

    def checkpoint_is_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "site_index" and checkpoint.get("next_index") is not None

    async def inspect_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        entries = await self._discover_entries()
        first_post_date = entries[-1]["published_at"] if entries else None
        return {
            "available_posts": len(entries),
            "page_size": self.PAGE_SIZE,
            "first_post_date": self.service._isoformat(first_post_date),
            "rate_limit": self.default_rate_limit(),
        }

    async def fetch_live_posts(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        entries = await self._discover_entries()
        posts: List[Dict[str, Any]] = []
        for entry in entries[: max(1, limit)]:
            post = await self._fetch_issue_post(source, entry)
            if post:
                posts.append(post)
        return posts[:limit]

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
        entries = await self._discover_entries()
        next_index = int((checkpoint or {}).get("next_index") or 0)
        pages_fetched = int(initial_pages_fetched or 0)
        collected: List[Dict[str, Any]] = []

        while (len(collected) + initial_collected) < target_posts and next_index < len(entries):
            batch_limit = min(self.PAGE_SIZE, target_posts - (len(collected) + initial_collected))
            batch_entries = entries[next_index: next_index + batch_limit]
            if not batch_entries:
                break

            batch_posts: List[Dict[str, Any]] = []
            for entry in batch_entries:
                post = await self._fetch_issue_post(source, entry)
                if post:
                    batch_posts.append(post)
                    collected.append(post)

            next_index += len(batch_entries)
            pages_fetched += 1
            checkpoint_payload = {
                "mode": "site_index",
                "adapter": self.adapter_type,
                "next_index": next_index,
                "pages_fetched": pages_fetched,
                "collected_posts": len(collected) + initial_collected,
                "total_candidates": len(entries),
            }
            progress_payload = {
                "stage": "page_fetched",
                "platform": "deeplearning_batch",
                "pages_fetched": pages_fetched,
                "posts_collected": len(collected) + initial_collected,
                "target_posts": target_posts,
                "next_index": next_index,
                "progress": min(100.0, ((len(collected) + initial_collected) / max(target_posts, 1)) * 100.0),
                "message": f"Fetched The Batch archive batch {pages_fetched}",
            }
            await self.service._emit_page(page_callback, batch_posts, checkpoint_payload, progress_payload)
            await self.service._emit_progress(progress_callback, progress_payload)

            if (len(collected) + initial_collected) < target_posts and next_index < len(entries):
                await asyncio.sleep(int((rate_limit or {}).get("page_delay_seconds", self.PAGE_DELAY_SECONDS)))

        final_checkpoint = {
            "mode": "site_index",
            "adapter": self.adapter_type,
            "next_index": next_index,
            "pages_fetched": pages_fetched,
            "collected_posts": len(collected) + initial_collected,
            "total_candidates": len(entries),
        }
        return collected[: max(0, target_posts - initial_collected)], pages_fetched, final_checkpoint

    async def _discover_entries(self) -> List[Dict[str, Any]]:
        body, _ = await self.service._fetch_text(self.CHARON_SITEMAP_URL)
        root = ET.fromstring(body)
        entries: List[Dict[str, Any]] = []

        for node in root.iter():
            if self.service._local_name(node.tag) != "url":
                continue
            loc = self.service._child_text(node, "loc") or ""
            lastmod = self.service._child_text(node, "lastmod")
            parsed = urllib.parse.urlparse(loc)
            match = self.ISSUE_PATH_RE.match(parsed.path or "")
            if not match:
                continue
            issue_number = int(match.group("issue"))
            public_url = urllib.parse.urljoin("https://www.deeplearning.ai", f"/the-batch/issue-{issue_number}/")
            entries.append(
                {
                    "issue_number": issue_number,
                    "public_url": public_url,
                    "published_at": self.service._parse_datetime_value(lastmod),
                }
            )

        entries.sort(key=lambda item: item.get("published_at") or self.service._parse_datetime_value("1970-01-01T00:00:00+00:00"), reverse=True)
        return entries

    async def _fetch_issue_post(self, source: Dict[str, Any], entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = str(entry.get("public_url") or "")
        if not url:
            return None

        html, _ = await self.service._fetch_text(url)
        next_payload = self._extract_next_data(html)
        post = self._find_post_payload(next_payload)
        if not post:
            return None

        title = str(post.get("title") or "").strip()
        content_html = str(post.get("html") or "").strip()
        if not content_html.strip():
            content_html = self.service._extract_article_html(html)
        content = self.service._strip_html(content_html)
        if not content.strip():
            content = str(post.get("custom_excerpt") or post.get("excerpt") or "").strip()
        if not content.strip():
            return None

        feature_image = str(post.get("feature_image") or self._extract_meta_content(html, "og:image") or "").strip()
        categories = [
            str(tag.get("name") or "").strip()
            for tag in (post.get("tags") or [])
            if isinstance(tag, dict) and str(tag.get("name") or "").strip()
        ]
        authors = post.get("authors") or []
        primary_author = post.get("primary_author") or {}
        issue_number = entry.get("issue_number")

        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or "https://www.deeplearning.ai/the-batch/"),
            "url": url,
            "external_id": str(issue_number or post.get("slug") or ""),
            "guid": url,
            "title": title or url,
            "content": content,
            "content_html": content_html,
            "date": self.service._parse_datetime_value(str(post.get("published_at") or "")) or entry.get("published_at"),
            "media_urls": [feature_image] if feature_image else [],
            "categories": categories,
            "metadata": {
                "adapter": self.adapter_type,
                "issue_number": issue_number,
                "slug": post.get("slug"),
                "excerpt": post.get("custom_excerpt") or post.get("excerpt"),
                "primary_author": primary_author.get("name"),
                "authors": [author.get("name") for author in authors if isinstance(author, dict) and author.get("name")],
            },
        }

    def _extract_next_data(self, html: str) -> Dict[str, Any]:
        match = self.NEXT_DATA_RE.search(html or "")
        if not match:
            return {}
        try:
            return json.loads(match.group("payload"))
        except json.JSONDecodeError:
            return {}

    def _find_post_payload(self, payload: Any) -> Optional[Dict[str, Any]]:
        if isinstance(payload, dict):
            if payload.get("html") and payload.get("title") and payload.get("published_at"):
                return payload
            for value in payload.values():
                found = self._find_post_payload(value)
                if found:
                    return found
        elif isinstance(payload, list):
            for item in payload:
                found = self._find_post_payload(item)
                if found:
                    return found
        return None

    def _extract_meta_content(self, html: str, meta_name: str) -> str:
        pattern = re.compile(
            rf'(?is)<meta\b[^>]+(?:name|property)="{re.escape(meta_name)}"[^>]+content="([^"]*)"[^>]*>'
        )
        match = pattern.search(html or "")
        return match.group(1) if match else ""
