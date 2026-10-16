"""Phil Schmid Cloud Attention newsletter adapter."""

from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Dict, List, Optional

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import Inspection, RateLimit
from insight_core.utils.json_safe import iso


class PhilSchmidCloudAttentionAdapter(BaseSourceAdapter):
    """Archive Cloud Attention through paginated issue pages."""

    adapter_type = "philschmid_cloud_attention"
    HOSTS = {"www.philschmid.de", "philschmid.de"}
    PATH_PREFIX = "/cloud-attention"
    PAGE_SIZE = 8
    PAGE_DELAY_SECONDS = 1
    ISSUE_RE = re.compile(r'href="(?P<href>/cloud-attention/issue-\d+)"', re.IGNORECASE)
    PAGE_RE = re.compile(r"[?&]page=(\d+)")
    JSON_LD_RE = re.compile(r'(?is)<script type="application/ld\+json">\s*(?P<payload>\{.*?\})\s*</script>')

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in self.HOSTS and (parsed.path or "").startswith(self.PATH_PREFIX)

    async def inspect(self, source: Dict[str, Any]) -> Inspection:
        entries = await self._discover_entries(source)
        first_post_date = None
        if entries:
            oldest_post = await self._fetch_issue_post(source, entries[-1], include_html=False)
            first_post_date = iso((oldest_post or {}).get("date"))

        return Inspection(len(entries), self.PAGE_SIZE, first_post_date)

    async def fetch_latest(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        entries = await self._discover_entries(source)
        posts: List[Dict[str, Any]] = []
        for entry in entries[: max(1, limit)]:
            post = await self._fetch_issue_post(source, entry)
            if post:
                posts.append(post)
        return posts[:limit]

    async def archive_pages(self, source: Dict[str, Any], target: int, checkpoint: Optional[Dict[str, Any]],
                            rate: RateLimit):
        entries = await self._discover_entries(source)
        async for page in self.index_pages(source, entries, target, checkpoint, self._fetch_issue_post):
            yield page

    async def _discover_entries(self, source: Dict[str, Any]) -> List[Dict[str, Any]]:
        base = self._archive_url(source)
        first_html, _ = await self.http.get_text(base)
        max_page = self._extract_max_page(first_html)
        urls: List[str] = []
        seen = set()

        for page in range(1, max_page + 1):
            if page == 1:
                html = first_html
            else:
                html, _ = await self.http.get_text(f"{base}?page={page}")
            for match in self.ISSUE_RE.finditer(html):
                absolute_url = urllib.parse.urljoin(base, match.group("href"))
                if absolute_url in seen:
                    continue
                seen.add(absolute_url)
                urls.append(absolute_url)

        return [{"url": url} for url in urls]

    async def _fetch_issue_post(
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
        metadata = self._extract_json_ld(html)
        article_html = parsing.extract_article_html(html) if include_html else ""
        content = parsing.strip_html(article_html or "")
        if not content.strip():
            content = str(metadata.get("description") or parsing.meta_content(html, "description") or "").strip()
        if not content.strip():
            return None

        parsed = urllib.parse.urlparse(url)
        issue_slug = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or self._archive_url(source)),
            "url": url,
            "external_id": issue_slug,
            "guid": url,
            "title": str(metadata.get("headline") or parsing.meta_content(html, "og:title") or url).strip(),
            "content": content,
            "content_html": article_html,
            "date": parsing.parse_datetime_value(str(metadata.get("datePublished") or "")),
            "media_urls": [parsing.meta_content(html, "og:image")] if parsing.meta_content(html, "og:image") else [],
            "categories": ["Cloud Attention"],
            "metadata": {
                "adapter": self.adapter_type,
                "issue_slug": issue_slug,
                "description": metadata.get("description") or parsing.meta_content(html, "description"),
                "author": ((metadata.get("author") or {}).get("name") if isinstance(metadata.get("author"), dict) else None),
            },
        }

    def _archive_url(self, source: Dict[str, Any]) -> str:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or "https://www.philschmid.de/cloud-attention"))
        return f"{parsed.scheme or 'https'}://{parsed.netloc or 'www.philschmid.de'}{self.PATH_PREFIX}"

    def _extract_max_page(self, html: str) -> int:
        pages = [int(value) for value in self.PAGE_RE.findall(html or "")]
        return max(pages) if pages else 1

    def _extract_json_ld(self, html: str) -> Dict[str, Any]:
        for match in self.JSON_LD_RE.finditer(html or ""):
            try:
                payload = json.loads(match.group("payload"))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and payload.get("@type") == "BlogPosting":
                return payload
        return {}
