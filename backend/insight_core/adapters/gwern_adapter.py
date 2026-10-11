"""Gwern site-map and markdown-backed source adapter."""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import Inspection, RateLimit


class GwernAdapter(BaseSourceAdapter):
    """Archive Gwern through sitemap discovery and per-page markdown sources."""

    adapter_type = "gwern_site"
    available_basis = "estimate"   # sitemap candidates; some pages are not essays
    HOSTS = {"gwern.net", "www.gwern.net"}
    PAGE_SIZE = 20
    PAGE_DELAY_SECONDS = 1
    CHECKPOINT_MODES = frozenset({"gwern_index"})
    SITEMAP_PATH = "/sitemap.xml"
    NEWEST_PATH = "/doc/newest/index"
    SKIP_PATHS = {
        "/index",
        "/about",
        "/me",
        "/changelog",
        "/blog/index",
        "/doc/newest/index",
        "/doc/newest/abstract",
        "/doc/index",
    }
    BANNED_PREFIXES = ("/static/", "/metadata/")
    BANNED_EXTENSIONS = {
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
        ".pdf", ".epub", ".zip", ".xz", ".json", ".csv",
        ".txt", ".mp4", ".webm", ".mp3", ".wav", ".ico",
        ".css", ".js", ".xml",
    }

    LINK_TAG_RE = re.compile(r"(?is)<link\b(?P<attrs>[^>]+)>")
    ANCHOR_TAG_RE = re.compile(r"(?is)<a\b(?P<attrs>[^>]+)>")

    def matches(self, source: Dict[str, Any]) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in self.HOSTS

    async def inspect(self, source: Dict[str, Any]) -> Inspection:
        urls = await self._discover_archive_urls(source)
        return Inspection(len(urls), self.PAGE_SIZE, None)

    async def fetch_latest(self, source: Dict[str, Any], limit: int) -> List[Dict[str, Any]]:
        urls = await self._discover_recent_urls(source, limit=max(limit * 3, 12))
        posts: List[Dict[str, Any]] = []
        seen = set()
        for url in urls:
            if url in seen:
                continue
            seen.add(url)
            post = await self._fetch_page_post(source, url)
            if not post:
                continue
            posts.append(post)
            if len(posts) >= limit:
                break
        return posts

    async def archive_pages(self, source: Dict[str, Any], target: int, checkpoint: Optional[Dict[str, Any]],
                            rate: RateLimit):
        entries = await self._discover_archive_urls(source)
        async for page in self.index_pages(source, entries, target, checkpoint, rate, self._fetch_page_post):
            yield page

    async def _discover_archive_urls(self, source: Dict[str, Any]) -> List[str]:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or "https://gwern.net"))
        base = f"{parsed.scheme or 'https'}://{parsed.netloc or 'gwern.net'}"
        sitemap_url = f"{base}{self.SITEMAP_PATH}"
        body, _ = await self.http.get_text(sitemap_url)
        root = ET.fromstring(body)
        urls: List[str] = []
        for node in root.iter():
            if parsing.local_name(node.tag) != "loc" or not (node.text or "").strip():
                continue
            url = node.text.strip()
            if self._is_candidate_page_url(url):
                urls.append(url)
        return sorted(dict.fromkeys(urls))

    async def _discover_recent_urls(self, source: Dict[str, Any], limit: int) -> List[str]:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or "https://gwern.net"))
        base = f"{parsed.scheme or 'https'}://{parsed.netloc or 'gwern.net'}"
        newest_url = f"{base}{self.NEWEST_PATH}"
        body, _ = await self.http.get_text(newest_url)
        urls: List[str] = []
        seen = set()

        for match in self.ANCHOR_TAG_RE.finditer(body):
            attrs = match.group("attrs") or ""
            href = self._extract_attr(attrs, "href")
            class_name = self._extract_attr(attrs, "class")
            if not href or not href.startswith("/"):
                continue
            if "link-page" not in class_name:
                continue
            absolute_url = urllib.parse.urljoin(base, href)
            if not self._is_candidate_page_url(absolute_url):
                continue
            if absolute_url in seen:
                continue
            seen.add(absolute_url)
            urls.append(absolute_url)
            if len(urls) >= limit:
                break

        return urls

    async def _fetch_page_post(self, source: Dict[str, Any], url: str) -> Optional[Dict[str, Any]]:
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
        markdown_url = self._extract_markdown_url(html) or f"{canonical_url}.md"
        article_html = parsing.extract_article_html(html)
        markdown_body = ""
        try:
            markdown_text, _ = await self.http.get_text(markdown_url)
            markdown_body = self._strip_front_matter(markdown_text)
        except Exception:
            markdown_body = ""

        content_text = markdown_body.strip() or parsing.strip_html(article_html) or (parsing.meta_content(html, "description") or "")
        if not content_text.strip():
            return None

        created_at = (
            parsing.meta_content(html, "citation_publication_date")
            or parsing.meta_content(html, "dc.date.issued")
            or parsing.meta_content(html, "dcterms.modified")
        )
        thumbnail = parsing.meta_content(html, "og:image")
        categories = self._extract_keywords(html)
        media_urls = [thumbnail] if thumbnail else []
        external_id = urllib.parse.urlparse(canonical_url).path.rstrip("/") or "/"

        return {
            "platform": "rss",
            "source": str(source.get("handle_or_url") or "https://gwern.net"),
            "url": canonical_url,
            "external_id": external_id,
            "guid": canonical_url,
            "title": title,
            "content": content_text,
            "content_html": article_html,
            "date": parsing.parse_datetime_value(created_at),
            "media_urls": media_urls,
            "categories": categories,
            "metadata": {
                "adapter": self.adapter_type,
                "markdown_url": markdown_url,
                "created": parsing.meta_content(html, "citation_publication_date") or parsing.meta_content(html, "dc.date.issued"),
                "modified": parsing.meta_content(html, "dcterms.modified"),
            },
        }

    def _is_candidate_page_url(self, url: str) -> bool:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if host not in self.HOSTS:
            return False

        path = parsed.path or "/"
        if any(path.startswith(prefix) for prefix in self.BANNED_PREFIXES):
            return False
        if path in self.SKIP_PATHS:
            return False

        lowered = path.lower()
        if lowered.endswith(".md"):
            return False
        if lowered.endswith("/"):
            lowered = lowered[:-1]

        for extension in self.BANNED_EXTENSIONS:
            if lowered.endswith(extension):
                return False

        if path.endswith("/index"):
            return True

        final_segment = path.rsplit("/", 1)[-1]
        return "." not in final_segment

    def _extract_attr(self, attrs: str, name: str) -> str:
        match = re.search(rf'\b{name}="([^"]*)"', attrs)
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

    def _extract_markdown_url(self, html: str) -> str:
        for match in self.LINK_TAG_RE.finditer(html):
            attrs = match.group("attrs") or ""
            rel = self._extract_attr(attrs, "rel")
            href = self._extract_attr(attrs, "href")
            link_type = self._extract_attr(attrs, "type")
            if rel == "alternate" and href and "markdown" in link_type.lower():
                return href
        return ""

    def _extract_html_title(self, html: str) -> str:
        match = re.search(r"(?is)<title>(.*?)</title>", html)
        if not match:
            return ""
        return parsing.strip_html(match.group(1)).strip()

    def _strip_front_matter(self, markdown_text: str) -> str:
        text = markdown_text or ""
        if text.startswith("---\n"):
            end = text.find("\n...\n")
            if end != -1:
                return text[end + 5 :].strip()
        return text.strip()

    def _extract_keywords(self, html: str) -> List[str]:
        raw = parsing.meta_content(html, "keywords")
        if not raw:
            return []
        return [item.strip() for item in raw.split(",") if item.strip()]
