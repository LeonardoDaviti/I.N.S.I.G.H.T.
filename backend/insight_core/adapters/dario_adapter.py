"""Dario Amodei personal site adapter."""

from __future__ import annotations

import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import Inspection, RateLimit
from insight_core.utils.json_safe import iso


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

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        host = (parsed.hostname or "").lower()
        path = (parsed.path or "/").rstrip("/") or "/"
        return host in self.HOSTS and path in self.ARCHIVE_PATHS

    async def inspect(self, source: Dict[str, Any]) -> Inspection:
        entries = await self._discover_entries(source)
        first_post_date = None
        if entries:
            oldest_post = await self._fetch_entry_post(source, entries[-1], include_html=False)
            first_post_date = iso((oldest_post or {}).get("date"))

        return Inspection(len(entries), self.PAGE_SIZE, first_post_date)

    async def fetch_latest(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        entries = await self._discover_entries(source)
        posts: List[Dict[str, Any]] = []
        for entry in entries[: max(1, limit)]:
            post = await self._fetch_entry_post(source, entry)
            if post:
                posts.append(post)
        return posts[:limit]

    async def archive_pages(self, source: Dict[str, Any], target: int, checkpoint: Optional[Dict[str, Any]],
                            rate: RateLimit):
        entries = await self._discover_entries(source)
        async for page in self.index_pages(source, entries, target, checkpoint, self._fetch_entry_post):
            yield page

    async def _discover_entries(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        base = self._base_url(source)
        html, _ = await self.http.get_text(base)
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

        html, _ = await self.http.get_text(url)
        article_html = self._extract_content_html(html) if include_html else ""
        if include_html and not article_html:
            article_html = parsing.extract_article_html(html)

        content_text = parsing.strip_html(article_html or "")
        if not content_text.strip():
            content_text = parsing.meta_content(html, "description")
        if not content_text.strip():
            return None

        title = self._extract_text(self.TITLE_RE, html) or parsing.meta_content(html, "og:title") or url
        raw_date = self._extract_text(self.DATE_RE, html)
        published_at = self._parse_date(raw_date)
        image_url = parsing.meta_content(html, "og:image")
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
        return parsing.strip_html(match.group(1)).strip()

    def _extract_content_html(self, html: str) -> str:
        match = self.CONTENT_RE.search(html or "")
        if not match:
            return ""
        return match.group(1).strip()

    def _parse_date(self, raw_date: str) -> Optional[datetime]:
        cleaned = (raw_date or "").strip()
        if not cleaned:
            return None

        for fmt in ("%B %Y", "%b %Y"):
            try:
                return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue

        return parsing.parse_datetime_value(cleaned)
