"""Dario Amodei personal site adapter."""

from __future__ import annotations

import asyncio
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from insight_core.adapters.base_adapter import BaseSourceAdapter


class DarioAmodeiAdapter(BaseSourceAdapter):
    """Archive essays/posts from darioamodei.com via direct HTML discovery."""

    adapter_type = "dario_site"
    HOSTS = {"darioamodei.com", "www.darioamodei.com"}
    PAGE_SIZE = 4
    PAGE_DELAY_SECONDS = 1
    ARCHIVE_PATHS = {"/", "/archive"}
    ENTRY_RE = re.compile(r'href="(?P<href>/(?:essay|post)/[a-z0-9\-]+)"', re.IGNORECASE)
    TITLE_RE = re.compile(r'(?is)<h1 class="post-title">(.*?)</h1>')
    DATE_RE = re.compile(r'(?is)<div class="post-date">(.*?)</div>')
    CONTENT_RE = re.compile(r'(?is)<div data-toc-contents="" class="rich-text w-richtext">(.*?)</div>')
    META_CONTENT_RE = re.compile(
        r'(?is)<meta\b[^>]+(?:name|property)="(?P<name>[^"]+)"[^>]+content="(?P<content>[^"]*)"[^>]*>'
    )

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "/").rstrip("/") or "/"
        return host in self.HOSTS and path in self.ARCHIVE_PATHS

    def default_rate_limit(self) -> Dict[str, Any]:
        return {"page_delay_seconds": self.PAGE_DELAY_SECONDS}

    def checkpoint_is_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "site_index" and checkpoint.get("next_index") is not None

    async def inspect_source(self, source: Dict[str, Any]) -> Dict[str, Any]:
        entries = await self._discover_entries(source)
        first_post_date = None
        if entries:
            oldest_post = await self._fetch_entry_post(source, entries[-1], include_html=False)
            first_post_date = self.service._isoformat((oldest_post or {}).get("date"))

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
                "platform": "dario",
                "pages_fetched": pages_fetched,
                "posts_collected": len(collected) + initial_collected,
                "target_posts": target_posts,
                "next_index": next_index,
                "progress": min(100.0, ((len(collected) + initial_collected) / max(target_posts, 1)) * 100.0),
                "message": f"Fetched Dario archive batch {pages_fetched}",
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
        base = self._base_url(source)
        html, _ = await self.service._fetch_text(base)
        urls: List[str] = []
        seen = set()
        for match in self.ENTRY_RE.finditer(html):
            absolute_url = urllib.parse.urljoin(base, match.group("href"))
            if absolute_url in seen:
                continue
            seen.add(absolute_url)
            urls.append(absolute_url)
        return [{"url": url} for url in urls]

    async def _fetch_entry_post(
        self,
        source: Dict[str, Any],
        entry: Dict[str, Any],
        *,
        include_html: bool = True,
    ) -> Optional[Dict[str, Any]]:
        url = str(entry.get("url") or "")
        if not url:
            return None

        html, _ = await self.service._fetch_text(url)
        article_html = self._extract_content_html(html) if include_html else ""
        if include_html and not article_html:
            article_html = self.service._extract_article_html(html)

        content_text = self.service._strip_html(article_html or "")
        if not content_text.strip():
            content_text = self._extract_meta_content(html, "description")
        if not content_text.strip():
            return None

        title = self._extract_text(self.TITLE_RE, html) or self._extract_meta_content(html, "og:title") or url
        raw_date = self._extract_text(self.DATE_RE, html)
        published_at = self._parse_date(raw_date)
        image_url = self._extract_meta_content(html, "og:image")
        parsed = urllib.parse.urlparse(url)
        path = parsed.path.rstrip("/") or "/"

        metadata: Dict[str, Any] = {
            "adapter": self.adapter_type,
            "entry_path": path,
            "entry_type": path.split("/", 2)[1] if path.count("/") >= 1 else None,
        }
        if raw_date:
            metadata["display_date"] = raw_date

        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or self._base_url(source)),
            "url": url,
            "external_id": path,
            "guid": url,
            "title": title.strip(),
            "content": content_text,
            "content_html": article_html,
            "date": published_at,
            "media_urls": [image_url] if image_url else [],
            "categories": [metadata["entry_type"]] if metadata.get("entry_type") else [],
            "metadata": metadata,
        }

    def _base_url(self, source: Dict[str, Any]) -> str:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or "https://darioamodei.com"))
        return f"{parsed.scheme or 'https'}://{parsed.netloc or 'darioamodei.com'}"

    def _extract_text(self, pattern: re.Pattern[str], html: str) -> str:
        match = pattern.search(html or "")
        if not match:
            return ""
        return self.service._strip_html(match.group(1)).strip()

    def _extract_content_html(self, html: str) -> str:
        match = self.CONTENT_RE.search(html or "")
        if not match:
            return ""
        return match.group(1).strip()

    def _extract_meta_content(self, html: str, meta_name: str) -> str:
        meta_name = meta_name.lower()
        for match in self.META_CONTENT_RE.finditer(html or ""):
            if (match.group("name") or "").lower() == meta_name:
                return match.group("content") or ""
        return ""

    def _parse_date(self, raw_date: str) -> Optional[datetime]:
        cleaned = (raw_date or "").strip()
        if not cleaned:
            return None

        for fmt in ("%B %Y", "%b %Y"):
            try:
                return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        return self.service._parse_datetime_value(cleaned)
