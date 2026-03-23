"""Zero To Mastery AI & ML Monthly newsletter adapter."""

from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from insight_core.adapters.base_adapter import BaseSourceAdapter


class ZeroToMasteryMonthlyAdapter(BaseSourceAdapter):
    """Archive ZTM monthly newsletters via Gatsby page-data discovery."""

    adapter_type = "zerotomastery_ml_monthly"
    HOSTS = {"zerotomastery.io", "www.zerotomastery.io"}
    ARCHIVE_PREFIX = "/newsletters/machine-learning-monthly"
    BLOG_PREFIX = "/blog/"
    PAGE_SIZE = 9
    PAGE_DELAY_SECONDS = 1
    META_CONTENT_RE = re.compile(
        r'(?is)<meta\b[^>]+(?:name|property)="(?P<name>[^"]+)"[^>]+content="(?P<content>[^"]*)"[^>]*>'
    )

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        return host in self.HOSTS and path.startswith(self.ARCHIVE_PREFIX)

    def default_rate_limit(self) -> Dict[str, Any]:
        return {"page_delay_seconds": self.PAGE_DELAY_SECONDS}

    def checkpoint_is_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "site_index" and checkpoint.get("next_index") is not None

    async def inspect_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        entries = await self._discover_entries(source)
        first_post_date = self.service._isoformat((entries[-1] or {}).get("date")) if entries else None
        return {
            "available_posts": len(entries),
            "page_size": self.PAGE_SIZE,
            "first_post_date": first_post_date,
            "rate_limit": self.default_rate_limit(),
        }

    async def fetch_live_posts(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        entries = await self._discover_entries(source)
        posts: List[Dict[str, Any]] = []
        for entry in entries[: max(1, limit)]:
            post = await self._fetch_entry_post(source, entry)
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
        entries = await self._discover_entries(source)
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
                post = await self._fetch_entry_post(source, entry)
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
                "platform": "zerotomastery",
                "pages_fetched": pages_fetched,
                "posts_collected": len(collected) + initial_collected,
                "target_posts": target_posts,
                "next_index": next_index,
                "progress": min(100.0, ((len(collected) + initial_collected) / max(target_posts, 1)) * 100.0),
                "message": f"Fetched Zero To Mastery batch {pages_fetched}",
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

    async def _discover_entries(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        first_page = await self._fetch_archive_page_data(source, 1)
        page_context = (first_page.get("result") or {}).get("pageContext") or {}
        total_pages = max(1, int(page_context.get("numPages") or 1))
        entries = self._extract_archive_entries(source, first_page)

        for page in range(2, total_pages + 1):
            payload = await self._fetch_archive_page_data(source, page)
            entries.extend(self._extract_archive_entries(source, payload))

        deduped: List[Dict[str, Any]] = []
        seen = set()
        for entry in entries:
            slug = str(entry.get("slug") or "")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            deduped.append(entry)
        return deduped

    async def _fetch_entry_post(self, source: Dict[str, Any], entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = str(entry.get("url") or "")
        if not url:
            return None

        html, _ = await self.service._fetch_text(url)
        article_html = self.service._extract_article_html(html)
        content = self.service._strip_html(article_html or "")
        if not content.strip():
            content = str(entry.get("excerpt") or self._extract_meta_content(html, "description") or "").strip()
        if not content.strip():
            return None

        image_url = str(entry.get("hero_image") or self._extract_meta_content(html, "og:image") or "").strip()
        author = entry.get("author") or {}
        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or self._archive_url(source)),
            "url": url,
            "external_id": str(entry.get("slug") or ""),
            "guid": url,
            "title": str(entry.get("title") or self._extract_meta_content(html, "og:title") or url).strip(),
            "content": content,
            "content_html": article_html,
            "date": entry.get("date"),
            "media_urls": [image_url] if image_url else [],
            "categories": list(entry.get("categories") or []),
            "metadata": {
                "adapter": self.adapter_type,
                "slug": entry.get("slug"),
                "author_name": author.get("authorName"),
                "author_slug": author.get("authorSlug"),
                "excerpt": entry.get("excerpt"),
            },
        }

    async def _fetch_archive_page_data(self, source: Dict[str, Any], page: int) -> Dict[str, Any]:
        url = urllib.parse.urljoin(self._base_url(source), f"/page-data{self.ARCHIVE_PREFIX}/{page}/page-data.json")
        body, _ = await self.service._fetch_text(url)
        return json.loads(body)

    def _extract_archive_entries(self, source: Dict[str, Any], payload: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = ((payload.get("result") or {}).get("data") or {})
        edges = ((data.get("allContentfulBlogPost") or {}).get("edges") or [])
        base = self._base_url(source)
        entries: List[Dict[str, Any]] = []
        for edge in edges:
            node = edge.get("node") or {}
            slug = str(node.get("slug") or "").strip()
            if not slug:
                continue
            hero_image = self._extract_gatsby_image_url((((node.get("heroImage") or {}).get("gatsbyImageData")) or {}))
            categories = [
                str(tag.get("label") or "").strip()
                for tag in (node.get("tags") or [])
                if isinstance(tag, dict) and str(tag.get("label") or "").strip()
            ]
            entries.append(
                {
                    "slug": slug,
                    "url": urllib.parse.urljoin(base, f"{self.BLOG_PREFIX}{slug}/"),
                    "title": str(node.get("blogTitle") or node.get("seoPageTitle") or "").strip(),
                    "excerpt": str(node.get("excerpt") or node.get("seoPageDesc") or "").strip(),
                    "date": self._parse_publish_date(str(node.get("publishDate") or "")),
                    "categories": categories,
                    "author": node.get("author") or {},
                    "hero_image": hero_image,
                }
            )
        return entries

    def _extract_gatsby_image_url(self, payload: Dict[str, Any]) -> str:
        sources = ((((payload.get("images") or {}).get("sources")) or []))
        for source in sources:
            srcset = str(source.get("srcSet") or "").strip()
            if not srcset:
                continue
            first_candidate = srcset.split(",", 1)[0].strip().split(" ", 1)[0]
            if first_candidate:
                return first_candidate
        return ""

    def _parse_publish_date(self, raw_date: str) -> Optional[datetime]:
        cleaned = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", (raw_date or "").strip(), flags=re.IGNORECASE)
        if not cleaned:
            return None
        try:
            return datetime.strptime(cleaned, "%B %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            return self.service._parse_datetime_value(cleaned)

    def _base_url(self, source: Dict[str, Any]) -> str:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or "https://zerotomastery.io"))
        return f"{parsed.scheme or 'https'}://{parsed.netloc or 'zerotomastery.io'}"

    def _archive_url(self, source: Dict[str, Any]) -> str:
        return urllib.parse.urljoin(self._base_url(source), f"{self.ARCHIVE_PREFIX}/1/")

    def _extract_meta_content(self, html: str, meta_name: str) -> str:
        meta_name = meta_name.lower()
        for match in self.META_CONTENT_RE.finditer(html or ""):
            if (match.group("name") or "").lower() == meta_name:
                return match.group("content") or ""
        return ""
