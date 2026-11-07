"""DeepLearning.AI The Batch newsletter adapter.

Issue 0130 B2: the archive read 38 pages and found 0 posts (2026-11-07); the newest stored issue is of July 2026,
so the issue pages stopped carrying the Next.js post payload this reader parsed. No page of the new layout is stored
anywhere, so the reader does not guess it: an issue page without the payload is read as any article page (page
watch's reader: its body, title and the date the page states); the issue list falls back to the site's own sitemap
when the CMS sitemap can't be read or lists no issue. Issue pages that still read as no post are counted (the
checkpoint's "skipped"); every listed entry is an issue (LISTS_ONLY_POSTS), so the archive reports "the layout
changed" instead of a silent 0, and a live fetch that reads no post from several issue pages fails, saying so.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import Inspection, RateLimit, layout_changed_line
from insight_core.utils.json_safe import iso


class DeepLearningBatchAdapter(BaseSourceAdapter):
    """Archive The Batch via CharonHub sitemap discovery and Next.js post hydration."""

    adapter_type = "deeplearning_batch_site"
    HOSTS = {"www.deeplearning.ai", "deeplearning.ai"}
    PATH_PREFIX = "/the-batch"
    PAGE_SIZE = 10
    PAGE_DELAY_SECONDS = 1
    CHARON_SITEMAP_URL = "https://charonhub.deeplearning.ai/sitemap-posts.xml"
    SITE_LISTING_URL = "https://www.deeplearning.ai/the-batch/"
    LISTS_ONLY_POSTS = True
    # A live fetch that reads this many issue pages and finds no post on any: the layout changed.
    LAYOUT_PROBE = 3
    NEXT_DATA_RE = re.compile(
        r'(?is)<script id="__NEXT_DATA__" type="application/json">\s*(?P<payload>\{.*?\})\s*</script>'
    )
    ISSUE_PATH_RE = re.compile(r"^/issue-(?P<issue>\d+)/?$")
    SITE_ISSUE_PATH_RE = re.compile(r"^/the-batch/issue-(?P<issue>\d+)/?$")

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in self.HOSTS and (parsed.path or "").startswith(self.PATH_PREFIX)

    async def inspect(self, source: Dict[str, Any]) -> Inspection:
        entries = await self._discover_entries()
        first_post_date = entries[-1]["published_at"] if entries else None
        return Inspection(len(entries), self.PAGE_SIZE, iso(first_post_date))

    async def fetch_latest(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        entries = await self._discover_entries()
        posts: List[Dict[str, Any]] = []
        read = 0
        for entry in entries[: max(1, limit)]:
            post = await self._fetch_issue_post(source, entry)
            read += 1
            if post:
                posts.append(post)
            elif not posts and read >= self.LAYOUT_PROBE:
                raise ValueError(layout_changed_line(read))
        return posts[:limit]

    async def archive_pages(self, source: Dict[str, Any], target: int, checkpoint: Optional[Dict[str, Any]],
                            rate: RateLimit):
        entries = await self._discover_entries()
        async for page in self.index_pages(source, entries, target, checkpoint, self._fetch_issue_post):
            yield page

    async def _discover_entries(self) -> List[Dict[str, Any]]:
        """The issues, newest first: the CMS sitemap's, else (it can't be read, or lists none) the site's own."""
        try:
            body, _ = await self.http.get_text(self.CHARON_SITEMAP_URL)
            locs = [(parsing.child_text(node, "loc") or "", parsing.child_text(node, "lastmod"))
                    for node in ET.fromstring(body).iter() if parsing.local_name(node.tag) == "url"]
            entries = self._entries(locs, self.ISSUE_PATH_RE)
        except Exception as exc:  # noqa: BLE001 - the site's own sitemap is the fallback
            if getattr(exc, "limiting", False):
                raise
            entries = []
        if not entries:
            from insight_core.ingestion.kinds.page_watch import ARCHIVE_SITEMAPS, sitemap_entries

            locs = await sitemap_entries(self.http, self.SITE_LISTING_URL, "/the-batch/", max_files=ARCHIVE_SITEMAPS)
            entries = self._entries(locs, self.SITE_ISSUE_PATH_RE)
        return entries

    def _entries(self, locs: List[Any], pattern: "re.Pattern[str]") -> List[Dict[str, Any]]:
        entries: Dict[int, Dict[str, Any]] = {}
        for loc, lastmod in locs:
            match = pattern.match(urllib.parse.urlparse(loc or "").path or "")
            if not match:
                continue
            issue_number = int(match.group("issue"))
            public_url = urllib.parse.urljoin("https://www.deeplearning.ai", f"/the-batch/issue-{issue_number}/")
            entries.setdefault(issue_number, {
                "issue_number": issue_number,
                "public_url": public_url,
                "published_at": parsing.parse_datetime_value(lastmod),
            })
        entries = list(entries.values())

        entries.sort(key=lambda item: item.get("published_at") or parsing.parse_datetime_value("1970-01-01T00:00:00+00:00"), reverse=True)
        return entries

    async def _fetch_issue_post(self, source: Dict[str, Any], entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        url = str(entry.get("public_url") or "")
        if not url:
            return None

        html, _ = await self.http.get_text(url)
        next_payload = self._extract_next_data(html)
        post = self._find_post_payload(next_payload)
        if not post:
            return self._page_post(source, entry, url, html)

        title = str(post.get("title") or "").strip()
        content_html = str(post.get("html") or "").strip()
        if not content_html.strip():
            content_html = parsing.extract_article_html(html)
        content = parsing.strip_html(content_html)
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
            "date": parsing.parse_datetime_value(str(post.get("published_at") or "")) or entry.get("published_at"),
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

    def _page_post(self, source: Dict[str, Any], entry: Dict[str, Any], url: str, html: str) -> Optional[Dict[str, Any]]:
        """An issue page without the Next.js payload, read as any article page (page watch's reader), with the
        date the page states, else the sitemap's; the issue number stays its id. None when no article is there."""
        from insight_core.ingestion.kinds.page_watch import article_post, page_date

        post = article_post(html, str(source.get("handle_or_url") or self.SITE_LISTING_URL), url,
                            page_date(html) or entry.get("published_at"), adapter=self.adapter_type)
        if post is None:
            return None
        issue_number = entry.get("issue_number")
        post["external_id"] = str(issue_number or post["external_id"])
        post["metadata"] = {**post["metadata"], "issue_number": issue_number, "read_as": "page"}
        return post

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

