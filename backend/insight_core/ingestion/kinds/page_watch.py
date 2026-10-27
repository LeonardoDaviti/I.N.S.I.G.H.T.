"""page_watch: a page without a feed, followed through its links and the site's sitemap (issue 0028).

A source is platform rss, handle_or_url the listing page (https://www.anthropic.com/news) and
settings.page_watch = {"prefix": "/news/"}; the setting is what selects this kind. The prefix
is optional: by default it is the listing page's path ("/news" -> "/news/"), or for a site's
home page the most common first segment of its deeper links.

The articles are the union of
  - the listing page's same-host links under the prefix, in page order (newest first), and
  - the sitemap's URLs under the prefix (robots.txt's Sitemap: lines, else /sitemap.xml; an
    index is followed to at most MAX_SITEMAPS files; .gz files are skipped),
the listing page itself left out. A live fetch reads the ones not stored yet, listing links
first, then the sitemap's by lastmod (newest first); an archive reads them all, one article
page per archive page so the host gate spaces them.

An article page is read with the full-text reader (extract_article_html). Its date is the
page's own (article:published_time, JSON-LD datePublished, meta date, <time datetime>), else
the sitemap's lastmod, else now: a sitemap's lastmod is often a redeploy date, not the
publication's. A page with no article body, or with neither a date nor og:type article (a
category page), is not a post; a live fetch remembers it for the process's life. A site that
builds its pages with JavaScript yields no bodies, so no posts (the preview says so).
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import Inspection, RateLimit, Source
from insight_core.ingestion.kinds.generic_rss import StoredUrls
from insight_core.utils.json_safe import iso

logger = logging.getLogger("insight.ingestion.page_watch")

MAX_SITEMAPS = 5          # sitemap files read per discovery (robots' ones, an index's children)
EXTRA_READS = 5           # pages a live fetch may read beyond its limit, for pages that are no post
PREVIEW_ITEMS = 5
PREVIEW_READS = 8         # the first candidates a preview reads, to show PREVIEW_ITEMS posts
PREVIEW_FAN_OUT = 4

LINK_RE = re.compile(r"""(?is)<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""")
JSON_LD_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
TIME_RE = re.compile(r"""(?is)<time\b[^>]*?\bdatetime\s*=\s*["']([^"']+)["']""")
TITLE_RE = re.compile(r"(?is)<title\b[^>]*>(.*?)</title>")
H1_RE = re.compile(r"(?is)<h1\b[^>]*>(.*?)</h1>")
SITE_SUFFIX_RE = re.compile(r"\s+[|\\·–—-]\s+([^|\\·–—-]{1,40})$")    # "Title \ Anthropic"
META_DATES = ("date", "dc.date", "pubdate")       # <meta name> dates, after the two above
LISTING_MAX_BYTES = 4_000_000                     # a listing page is read up to this (groq.com's: 0.9 MB)
# A date written on the page ("June 29, 2026", "Jun 29, 2026"): ai.meta.com's articles have no other.
TEXT_DATE_RE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, (?:19|20)\d\d\b")
SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def normalise_prefix(value: Any) -> str:
    """"news" -> "/news/"; "" -> "/" (the whole site)."""
    path = urllib.parse.urlparse(str(value or "").strip()).path.strip("/")
    return f"/{path}/" if path else "/"


def _clean(url: str, base: Optional[str] = None) -> Optional[str]:
    """An absolute http(s) URL without its fragment or trailing slash; None for anything else."""
    absolute = urllib.parse.urldefrag(urllib.parse.urljoin(base or url, html.unescape(url.strip())))[0]
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return urllib.parse.urlunparse(parsed._replace(path=parsed.path.rstrip("/") or "/"))


def _site(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def infer_prefix(listing_url: str, links: Sequence[str]) -> str:
    """The listing page's path; for a home page, the most common first segment of its
    same-host links two or more segments deep ("/" when it has none)."""
    path = urllib.parse.urlparse(listing_url).path.strip("/")
    if path:
        return f"/{path}/"
    site = _site(listing_url)
    firsts = Counter(segments[0] for link in links
                     if _site(link) == site and len(segments := parsing.path_segments(link)) >= 2)
    return f"/{firsts.most_common(1)[0][0]}/" if firsts else "/"


@dataclass(frozen=True)
class Discovery:
    prefix: str
    listed: Tuple[str, ...]                          # the listing page's article links, page order
    sitemap: Dict[str, Optional[datetime]]           # the sitemap's article URLs -> lastmod

    def candidates(self) -> List[str]:
        """Listing links first (page order), then the sitemap's others by lastmod, newest first."""
        listed = set(self.listed)
        rest = sorted((url for url in self.sitemap if url not in listed),
                      key=lambda url: self.sitemap[url] or EPOCH, reverse=True)
        return [*self.listed, *rest]


async def discover(http: KindHttp, listing_url: str, prefix: Optional[str] = None) -> Discovery:
    """The articles of a listing page. Raises when the listing page cannot be read; a missing
    or broken sitemap is just no sitemap."""
    # Where the listing landed, not the address given: deepmind.google/discover/blog/ is /blog/.
    body, landed = await http.get_start(listing_url, LISTING_MAX_BYTES)
    page = body.decode("utf-8", "replace")
    listing = _clean(landed) or landed
    links = [url for href in LINK_RE.findall(page) if (url := _clean(href, landed))]
    prefix = normalise_prefix(prefix) if prefix else infer_prefix(listing, links)
    site = _site(listing)

    def under(url: str) -> bool:
        path = urllib.parse.urlparse(url).path
        return _site(url) == site and url != listing and path.startswith(prefix) and path + "/" != prefix

    listed = tuple(dict.fromkeys(url for url in links if under(url)))
    sitemap: Dict[str, Optional[datetime]] = {}
    for loc, lastmod in await _sitemap_entries(http, listing, prefix):
        url = _clean(loc)
        if url and under(url):
            sitemap.setdefault(url, parsing.parse_datetime_value(lastmod))
    return Discovery(prefix, listed, sitemap)


async def _sitemap_entries(http: KindHttp, listing: str, prefix: str) -> List[Tuple[str, Optional[str]]]:
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(listing))
    try:
        robots, _ = await http.get_text(f"{origin}/robots.txt")
    except Exception:  # noqa: BLE001 - no robots.txt: the usual address
        robots = ""
    queue = [line.split(":", 1)[1].strip() for line in robots.splitlines()
             if line.lower().startswith("sitemap:")] or [f"{origin}/sitemap.xml"]
    section = prefix.strip("/").split("/")[0]
    entries: List[Tuple[str, Optional[str]]] = []
    read = 0
    while queue and read < MAX_SITEMAPS:
        url = queue.pop(0)
        if urllib.parse.urlparse(url).path.endswith(".gz"):
            continue
        read += 1
        try:
            body, _ = await http.get_text(url)
            root = ET.fromstring(body.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - a broken sitemap is no sitemap
            logger.debug("Page watch: sitemap %s skipped (%s)", url, exc)
            continue
        locs = [(parsing.child_text(node, "loc") or "", parsing.child_text(node, "lastmod")) for node in root
                if parsing.local_name(node.tag) in ("url", "sitemap")]
        if parsing.local_name(root.tag) == "sitemapindex":
            # An index's children that name the section (or posts) first.
            children = [loc for loc, _ in locs if loc]
            queue.extend(sorted(children, key=lambda child: not (section and section in child or "post" in child)))
        else:
            entries.extend((loc, lastmod) for loc, lastmod in locs if loc)
    return entries


def page_date(page: str) -> Optional[datetime]:
    """The page's own publication date: meta article:published_time, JSON-LD datePublished,
    meta date, the first <time datetime>, then a date written on the page when it has only one
    (a category page lists many)."""
    json_ld, time_tag = JSON_LD_DATE_RE.search(page), TIME_RE.search(page)
    values = (parsing.meta_content(page, "article:published_time"), json_ld and json_ld.group(1),
              *(parsing.meta_content(page, name) for name in META_DATES), time_tag and time_tag.group(1))
    for value in values:
        if value and (date := parsing.parse_datetime_value(value.strip())) is not None:
            return date
    written = set(TEXT_DATE_RE.findall(parsing.strip_html(SCRIPT_STYLE_RE.sub(" ", page))))
    return _written_date(written.pop()) if len(written) == 1 else None


def _written_date(text: str) -> Optional[datetime]:
    """"June 29, 2026" or "Sept. 3, 2025" -> that day, UTC."""
    month, rest = text.split(" ", 1)
    try:
        return datetime.strptime(f"{month[:3]} {rest}", "%b %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _title(page: str, url: str) -> str:
    """og:title, else <title>, else the first <h1>; less a " | Site" suffix: the og:site_name's,
    or any short one on a <title>."""
    site = html.unescape(parsing.meta_content(page, "og:site_name")).strip()
    title, from_title_tag = html.unescape(parsing.meta_content(page, "og:title")).strip(), False
    if not title:
        for pattern in (TITLE_RE, H1_RE):
            match = pattern.search(page)
            if match and (title := parsing.strip_html(match.group(1))):
                from_title_tag = pattern is TITLE_RE
                break
    suffix = SITE_SUFFIX_RE.search(title)
    if suffix and (from_title_tag or (site and suffix.group(1).strip() == site)):
        title = title[:suffix.start()]
    return title or url


async def read_page(http: KindHttp, source_url: str, url: str, lastmod: Optional[datetime]) -> Optional[Dict[str, Any]]:
    """The post at url, or None when the page is no article (see the module docstring)."""
    page, _ = await http.get_text(url)
    return post_from(page, source_url, url, lastmod)


def post_from(page: str, source_url: str, url: str, lastmod: Optional[datetime]) -> Optional[Dict[str, Any]]:
    content_html = parsing.extract_article_html(page)
    content = parsing.strip_html(content_html)
    date = page_date(page)
    if not content or (date is None and parsing.meta_content(page, "og:type").lower() != "article"):
        return None
    image = parsing.normalize_media_url(parsing.meta_content(page, "og:image"))
    media_urls = list(dict.fromkeys([*([image] if image else []), *parsing.extract_html_image_urls(content_html)]))
    return {
        "platform": "rss",
        "source": source_url,
        "url": url,
        "external_id": urllib.parse.urlparse(url).path,
        "guid": url,
        "title": _title(page, url),
        "content": content,
        "content_html": content_html,
        "date": date or lastmod or datetime.now(timezone.utc),
        "media_urls": media_urls,
        "categories": [],
        "metadata": {"adapter": PageWatchKind.adapter_type},
    }


async def preview(http: KindHttp, url: str, prefix: Optional[str] = None) -> Dict[str, Any]:
    """What following the page would give: {prefix, found, sitemap, items[{url, title, published_at}]},
    items the first PREVIEW_ITEMS posts (read PREVIEW_FAN_OUT at a time)."""
    address = (url or "").strip()
    if not address:
        raise ValueError("An address is needed to follow a page")
    address = address if "://" in address else f"https://{address}"
    found = await discover(http, address, prefix)
    candidates = found.candidates()
    fan_out = asyncio.Semaphore(PREVIEW_FAN_OUT)

    async def one(candidate: str) -> Optional[Dict[str, Any]]:
        async with fan_out:
            try:
                return await read_page(http, address, candidate, found.sitemap.get(candidate))
            except Exception as exc:  # noqa: BLE001 - an unreadable page is just not shown
                logger.debug("Page watch preview: %s skipped (%s)", candidate, exc)
                return None

    posts = [post for post in await asyncio.gather(*map(one, candidates[:PREVIEW_READS])) if post]
    return {
        "prefix": found.prefix,
        "found": len(candidates),
        "sitemap": bool(found.sitemap),
        "items": [{"url": post["url"], "title": post["title"], "published_at": iso(post["date"])}
                  for post in posts[:PREVIEW_ITEMS]],
    }


class PageWatchKind(BaseSourceAdapter):
    adapter_type = "page_watch"
    available_basis = "estimate"        # discovered candidate pages; some may be no post
    PAGE_SIZE = 1                       # one article page per archive page: the host gate spaces them
    PAGE_DELAY_SECONDS = 2

    def __init__(self, http: KindHttp, *, stored_urls: Optional[StoredUrls] = None) -> None:
        super().__init__(http)
        self.stored_urls = stored_urls
        self._no_posts: set[str] = set()     # pages read that were no post (category pages)

    def matches(self, source: Source) -> bool:
        return isinstance((source.get("settings") or {}).get("page_watch"), dict)

    async def _discover(self, source: Source) -> Discovery:
        settings = (source.get("settings") or {}).get("page_watch") or {}
        return await discover(self.http, str(source["handle_or_url"]), settings.get("prefix"))

    async def _page(self, url: str) -> Optional[str]:
        """The page at url; None when it cannot be read, unless the host is limiting us."""
        try:
            page, _ = await self.http.get_text(url)
            return page
        except ValueError as exc:
            if isinstance(exc, HttpError) and exc.limiting:
                raise
            logger.info("Page watch: %s could not be read (%s)", url, exc)
            return None

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        found = await self._discover(source)
        candidates = [url for url in found.candidates() if url not in self._no_posts]
        stored = (await asyncio.to_thread(self.stored_urls, candidates)
                  if self.stored_urls and candidates else set())
        posts: List[Dict[str, Any]] = []
        reads = 0
        for url in (url for url in candidates if url not in stored):
            if len(posts) >= limit or reads >= limit + EXTRA_READS:
                break
            if reads:
                await self.http.sleep(self.PAGE_DELAY_SECONDS)
            reads += 1
            page = await self._page(url)
            if page is None:
                continue
            post = post_from(page, str(source["handle_or_url"]), url, found.sitemap.get(url))
            if post is None:
                self._no_posts.add(url)
            else:
                posts.append(post)
        return posts

    async def inspect(self, source: Source) -> Inspection:
        found = await self._discover(source)
        return Inspection(len(found.candidates()), self.PAGE_SIZE, None, raw={
            "prefix": found.prefix, "listing_links": len(found.listed), "sitemap_urls": len(found.sitemap)})

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        found = await self._discover(source)

        async def fetch_one(src: Source, url: str) -> Optional[Dict[str, Any]]:
            page = await self._page(url)
            return post_from(page, str(src["handle_or_url"]), url, found.sitemap.get(url)) if page else None

        async for page in self.index_pages(source, found.candidates(), target, checkpoint, fetch_one):
            yield page


__all__ = ["Discovery", "PageWatchKind", "discover", "infer_prefix", "normalise_prefix", "preview"]
