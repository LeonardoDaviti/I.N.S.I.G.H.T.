"""Tornike Gomareli's blog, pipecraft.me: a client-rendered site with no feed.

The page is an empty shell filled in by JavaScript. The posts come from the site's own
JSON API, the one its pages call:
  /api/posts                    the index: {"posts": [...], "essays": [...], "projects": [...],
                                "talks": [...]}, each entry {slug, title, date, section, ...}
  /api/posts/<section>/<slug>   one entry plus "content", the post's whole HTML
A post is an entry of "posts" or "essays" (the site's own writing list); projects and talks
are product pages and videos. Any pipecraft.me URL is the whole blog.
"""

from __future__ import annotations

import urllib.parse
from typing import Any, Dict, List, Optional

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import Inspection, RateLimit, Source
from insight_core.utils.json_safe import iso

SECTIONS = ("posts", "essays")


class PipecraftAdapter(BaseSourceAdapter):
    adapter_type = "pipecraft_site"
    HOSTS = {"pipecraft.me", "www.pipecraft.me"}
    PAGE_SIZE = 5

    def matches(self, source: Source) -> bool:
        return (urllib.parse.urlparse(str(source.get("handle_or_url") or "")).hostname or "").lower() in self.HOSTS

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        posts = [await self._fetch_entry_post(source, entry) for entry in (await self._entries(source))[:limit]]
        return [post for post in posts if post]

    async def inspect(self, source: Source) -> Inspection:
        entries = await self._entries(source)
        oldest = parsing.parse_datetime_value(entries[-1].get("date")) if entries else None
        return Inspection(len(entries), self.PAGE_SIZE, iso(oldest))

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        entries = await self._entries(source)
        async for page in self.index_pages(source, entries, target, checkpoint, self._fetch_entry_post):
            yield page

    async def _entries(self, source: Source) -> List[Dict[str, Any]]:
        """The index's posts and essays, newest first."""
        index = await self.http.get_json(f"{self._origin(source)}/api/posts")
        entries = [entry for section in SECTIONS for entry in index.get(section) or []
                   if entry.get("slug") and entry.get("section")]
        return sorted(entries, key=lambda entry: str(entry.get("date") or ""), reverse=True)

    async def _fetch_entry_post(self, source: Source, entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        path = f"{entry['section']}/{entry['slug']}"
        origin = self._origin(source)
        detail = await self.http.get_json(f"{origin}/api/posts/{path}")
        content_html = str(detail.get("content") or "")
        if not content_html.strip():
            return None
        url = f"{origin}/{path}"
        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or origin),
            "url": url,
            "external_id": path,
            "guid": url,
            "title": str(detail.get("title") or entry.get("title") or url).strip(),
            "content": parsing.strip_html(content_html),
            "content_html": content_html,
            "date": parsing.parse_datetime_value(detail.get("date") or entry.get("date")),
            "media_urls": parsing.extract_html_image_urls(content_html),
            "categories": [entry["section"]],
            "metadata": {"adapter": self.adapter_type},
        }

    def _origin(self, source: Source) -> str:
        host = urllib.parse.urlparse(str(source.get("handle_or_url") or "")).hostname or "www.pipecraft.me"
        return f"https://{host.lower()}"
