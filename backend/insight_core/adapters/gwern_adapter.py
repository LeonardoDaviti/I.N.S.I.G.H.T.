"""Gwern site adapter: his writing from the sitemap, the daily list from his two index pages.

An explicit exception for a site with its own index pages (issue 0043). Every Gwern rule is
here, none in the shared reader: the archive is the sitemap without the /doc/**/index topic
directories and the /newsletter/ issues (those are the Substack feed); the daily list is
/blog/index (dated by each link's id) and Gwern's own pages on /doc/newest/index; each page
is one request, read by the shared reader from its HTML.
"""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import Inspection, RateLimit


class GwernAdapter(BaseSourceAdapter):
    """Archive Gwern's writing through the sitemap; read each page's HTML once."""

    adapter_type = "gwern_site"
    available_basis = "estimate"   # sitemap candidates; a few may hold no article
    HOSTS = {"gwern.net", "www.gwern.net"}
    PAGE_SIZE = 20
    PAGE_DELAY_SECONDS = 1
    CHECKPOINT_MODES = frozenset({"gwern_index"})
    SITEMAP_PATH = "/sitemap.xml"
    NEWEST_PATH = "/doc/newest/index"
    BLOG_PATH = "/blog/index"
    SKIP_PATHS = {
        "/index",
        "/about",
        "/me",
        "/changelog",
        "/blog/index",
        "/doc/newest/abstract",
    }
    # /doc/**/index are topic directories (links and annotations, not reading); /newsletter/
    # issues are the same as gwern.substack.com/feed, which the feed finder offers.
    BANNED_PREFIXES = ("/static/", "/metadata/", "/newsletter/")
    BANNED_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
        ".pdf", ".epub", ".zip", ".xz", ".json", ".csv",
        ".txt", ".mp4", ".webm", ".mp3", ".wav", ".ico",
        ".css", ".js", ".xml",
    }
    # The page's own metadata block: <span class="page-status">…</span> and its siblings.
    PAGE_FIELDS = ("status", "confidence", "importance")

    LINK_TAG_RE = re.compile(r"(?is)<link\b(?P<attrs>[^>]+)>")
    ANCHOR_TAG_RE = re.compile(r"(?is)<a\b(?P<attrs>[^>]+)>")
    DATE_ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    # A date-range span renders "2010<sub>16ya</sub>" and "1929<sup>–</sup><sub>60</sub>1989":
    # keep the dates and the dash, drop the "years ago" and "lasted" subscripts.
    DATE_RANGE_RE = re.compile(
        r'(?is)(<span class="date-range\b[^"]*"[^>]*>[^<]*)'
        r'(?:<span class="subsup"><sup>([^<]*)</sup><sub>[^<]*</sub></span>([^<]*))?'
        r'(?:<sub>(?:<span[^>]*>[^<]*</span>|[^<]*)</sub>)?(?=</span>)'
    )

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in self.HOSTS

    async def inspect(self, source: Dict[str, Any]) -> Inspection:
        urls = await self._discover_archive_urls(source)
        return Inspection(len(urls), self.PAGE_SIZE, None)

    async def fetch_latest(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        posts: List[Dict[str, Any]] = []
        for url, listed_date in (await self._discover_recent_entries(source)).items():
            post = await self._fetch_page_post(source, url, listed_date)
            if post:
                posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    async def archive_pages(self, source: Dict[str, Any], target: int, checkpoint: Optional[Dict[str, Any]],
                            rate: RateLimit):
        entries = await self._discover_archive_urls(source)
        async for page in self.index_pages(source, entries, target, checkpoint, self._fetch_page_post):
            yield page

    def _base(self, source: Dict[str, Any]) -> str:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or "https://gwern.net"))
        return f"{parsed.scheme or 'https'}://{parsed.netloc or 'gwern.net'}"

    async def _discover_archive_urls(self, source: Dict[str, Any]) -> List[str]:
        body, _ = await self.http.get_text(f"{self._base(source)}{self.SITEMAP_PATH}")
        root = ET.fromstring(body)
        urls: List[str] = []
        for node in root.iter():
            if parsing.local_name(node.tag) != "loc" or not (node.text or "").strip():
                continue
            url = node.text.strip()
            if self._is_candidate_page_url(url):
                urls.append(url)
        return sorted(dict.fromkeys(urls))

    async def _discover_recent_entries(self, source: Dict[str, Any]) -> Dict[str, Optional[str]]:
        """{url: the date its index link gives, or None}, in reading order, each page once:
        Gwern's own pages on /doc/newest/index (most of it is other people's papers), then
        /blog/index newest first, each short post dated by its link's id."""
        base = self._base(source)
        entries: Dict[str, Optional[str]] = {}
        for path in (self.NEWEST_PATH, self.BLOG_PATH):
            body, _ = await self.http.get_text(f"{base}{path}")
            for match in self.ANCHOR_TAG_RE.finditer(body):
                attrs = match.group("attrs") or ""
                href = self._extract_attr(attrs, "href")
                if not href.startswith("/") or "link-page" not in self._extract_attr(attrs, "class"):
                    continue
                url = urllib.parse.urljoin(base, href.split("#", 1)[0])
                if not self._is_candidate_page_url(url):
                    continue
                link_id = self._extract_attr(attrs, "id")
                listed_date = link_id if self.DATE_ID_RE.match(link_id) else None
                if url not in entries or (listed_date and not entries[url]):
                    entries[url] = listed_date
        return entries

    async def _fetch_page_post(self, source: Dict[str, Any], url: str,
                               listed_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        try:
            html, _ = await self.http.get_text(url)
        except Exception:
            return None

        canonical_url = self._extract_canonical_url(html) or url
        title = (
            parsing.meta_content(html, "citation_title")
            or parsing.meta_content(html, "title")
            or self._extract_html_title(html)
            or canonical_url
        )
        article_html = parsing.extract_article_html(self._without_years_ago(html), canonical_url)
        content_text = parsing.strip_html(article_html) or parsing.meta_content(html, "description")
        if not content_text.strip():
            return None

        created = (parsing.meta_content(html, "citation_publication_date")
                   or parsing.meta_content(html, "dc.date.issued") or listed_date)
        modified = parsing.meta_content(html, "dcterms.modified")
        thumbnail = parsing.meta_content(html, "og:image")
        metadata: Dict[str, Any] = {"adapter": self.adapter_type, "created": created, "modified": modified}
        metadata.update(self._page_fields(html))

        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or "https://gwern.net"),
            "url": canonical_url,
            "external_id": urllib.parse.urlparse(canonical_url).path.rstrip("/") or "/",
            "guid": canonical_url,
            "title": title,
            "content": content_text,
            "content_html": article_html,
            "date": parsing.parse_datetime_value(created or modified),
            "media_urls": [thumbnail] if thumbnail else [],
            "categories": self._extract_keywords(html),
            "metadata": metadata,
        }

    def _is_candidate_page_url(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        if (parsed.hostname or "").lower() not in self.HOSTS:
            return False

        path = parsed.path or "/"
        if path in self.SKIP_PATHS or any(path.startswith(prefix) for prefix in self.BANNED_PREFIXES):
            return False
        if path.startswith("/doc/") and path.endswith("/index"):
            return False

        lowered = path.lower().rstrip("/")
        if lowered.endswith(".md") or any(lowered.endswith(ext) for ext in self.BANNED_EXTENSIONS):
            return False
        return "." not in path.rsplit("/", 1)[-1]

    def _without_years_ago(self, html: str) -> str:
        return self.DATE_RANGE_RE.sub(lambda m: m.group(1) + (m.group(2) or "") + (m.group(3) or ""), html)

    def _page_fields(self, html: str) -> Dict[str, str]:
        """status, confidence and importance from the page's metadata block, as shown
        ("finished", "possible", "7"); a field the page lacks is left out."""
        fields: Dict[str, str] = {}
        for name in self.PAGE_FIELDS:
            match = re.search(rf'(?is)<span class="page-{name}"[^>]*>(.*?)</span>\s*(?=<span class="page-|</div>)', html)
            value = parsing.strip_html(match.group(1)).rsplit(":", 1)[-1].strip() if match else ""
            if value:
                fields[name] = value
        return fields

    def _extract_attr(self, attrs: str, name: str) -> str:
        match = re.search(rf'(?<![\w-]){name}="([^"]*)"', attrs)
        return match.group(1) if match else ""

    def _extract_canonical_url(self, html: str) -> str:
        for match in self.LINK_TAG_RE.finditer(html):
            attrs = match.group("attrs") or ""
            if self._extract_attr(attrs, "rel") != "canonical":
                continue
            href = self._extract_attr(attrs, "href")
            if href:
                return href
        return ""

    def _extract_html_title(self, html: str) -> str:
        match = re.search(r"(?is)<title>(.*?)</title>", html)
        if not match:
            return ""
        return parsing.strip_html(match.group(1)).strip()

    def _extract_keywords(self, html: str) -> List[str]:
        raw = parsing.meta_content(html, "keywords")
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]
