"""Zero To Mastery AI & ML Monthly newsletter adapter."""

from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import Inspection, RateLimit
from insight_core.utils.json_safe import iso


class ZeroToMasteryMonthlyAdapter(BaseSourceAdapter):
    """Archive ZTM monthly newsletters via Gatsby page-data discovery."""

    adapter_type = "zerotomastery_ml_monthly"
    HOSTS = {"zerotomastery.io", "www.zerotomastery.io"}
    ARCHIVE_PREFIX = "/newsletters/machine-learning-monthly"
    BLOG_PREFIX = "/blog/"
    PAGE_SIZE = 9
    PAGE_DELAY_SECONDS = 1

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        return host in self.HOSTS and path.startswith(self.ARCHIVE_PREFIX)

    async def inspect(self, source: Dict[str, Any]) -> Inspection:
        entries = await self._discover_entries(source)
        first_post_date = iso((entries[-1] or {}).get("date")) if entries else None
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
        async for page in self.index_pages(source, entries, target, checkpoint, rate, self._fetch_entry_post):
            yield page

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

        html, _ = await self.http.get_text(url)
        article_html = parsing.extract_article_html(html)
        content = parsing.strip_html(article_html or "")
        if not content.strip():
            content = str(entry.get("excerpt") or parsing.meta_content(html, "description") or "").strip()
        if not content.strip():
            return None

        image_url = str(entry.get("hero_image") or parsing.meta_content(html, "og:image") or "").strip()
        author = entry.get("author") or {}
        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or self._archive_url(source)),
            "url": url,
            "external_id": str(entry.get("slug") or ""),
            "guid": url,
            "title": str(entry.get("title") or parsing.meta_content(html, "og:title") or url).strip(),
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
        body, _ = await self.http.get_text(url)
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
            return parsing.parse_datetime_value(cleaned)

    def _base_url(self, source: Dict[str, Any]) -> str:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or "https://zerotomastery.io"))
        return f"{parsed.scheme or 'https'}://{parsed.netloc or 'zerotomastery.io'}"

    def _archive_url(self, source: Dict[str, Any]) -> str:
        return urllib.parse.urljoin(self._base_url(source), f"{self.ARCHIVE_PREFIX}/1/")
