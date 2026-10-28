"""page_watch: a page without a feed, followed through its links and the site's sitemap (issue 0028).

A source is platform rss, handle_or_url the listing page (https://www.anthropic.com/news) and
settings.page_watch = {"prefix": "/news/"}; the setting is what selects this kind. The prefix
is optional: by default it is the listing page's path ("/news" -> "/news/"), or for a site's
home page the most common first segment of its deeper links.

The articles are the union of
  - the listing page's same-host links under the prefix, in page order (newest first), and
  - the sitemap's URLs under the prefix (robots.txt's Sitemap: lines, else /sitemap.xml; an
    index is followed to at most MAX_SITEMAPS files, each read up to SITEMAP_MAX_BYTES; .gz
    files are skipped),
the listing page itself left out. A live fetch reads the ones not stored yet, listing links
first, then the sitemap's by lastmod (newest first); an archive reads them all, one article
page per archive page so the host gate spaces them.

An article page is read with the full-text reader (extract_article_html). Its date is the
page's own (article:published_time, JSON-LD datePublished, meta date, its one <time datetime>), else
the sitemap's lastmod, else now: a sitemap's lastmod is often a redeploy date, not the
publication's. A page with no article body, or with neither a date nor og:type article (a
category page), is not a post. A live fetch remembers the pages it skipped for the process's
life (one that failed, for a day) and reads at most SKIP_READS of them besides its posts, so
they never use up its limit. A site that builds its pages with JavaScript yields no bodies,
so no posts (the preview says so).
"""
from __future__ import annotations

import asyncio
import html
import logging
import math
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.db.repo_posts import PAGE_READ_KEY
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import Inspection, RateLimit, Source
from insight_core.ingestion.kinds.generic_rss import StoredUrls
from insight_core.utils.json_safe import iso

logger = logging.getLogger("insight.ingestion.page_watch")

MAX_SITEMAPS = 5          # sitemap files read per discovery (robots' ones, an index's children)
SITEMAP_MAX_BYTES = 5_000_000   # a sitemap is read up to this; a longer one keeps its first entries
SKIP_READS = 10           # pages a live fetch may read that are no post or fail, besides its posts
FAILED_RETRY_S = 24 * 3600   # a page that failed is read again after this; one that is no post, never
PREVIEW_ITEMS = 5
PREVIEW_READS = 8         # the first candidates a preview reads, to show PREVIEW_ITEMS posts
PREVIEW_FAN_OUT = 4
OFFER_BUDGET_S = 15.0     # the previews of a site's blog or news pages, run at once (issue 0041)
# A menu link is offered as an article list (issue 0047) when its preview read this many posts
# dated this recently (of the PREVIEW_READS read; a list may lead with its category pages).
MENU_POSTS = 3
MENU_RECENT = timedelta(days=365)

# The pages skipped by a live fetch (no post, or failed): url -> the time.monotonic() to read
# it again. For the process's life: a run builds its own registry, so a kind's own set would
# last one run (issue 0029).
SKIPPED: Dict[str, float] = {}

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
    """An absolute http(s) URL without its fragment or trailing slash; None for anything else
    (a malformed one, "http://[x/", too)."""
    try:
        absolute = urllib.parse.urldefrag(urllib.parse.urljoin(base or url, html.unescape(url.strip())))[0]
        parsed = urllib.parse.urlparse(absolute)
    except ValueError:
        return None
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


# One run's reads of a site's robots.txt and sitemaps, by address: the previews of one offer
# share them, so a site's sitemap is read once, not once per page previewed (issue 0047).
SiteReads = Dict[str, "asyncio.Future[Tuple[Any, str]]"]


async def discover(http: KindHttp, listing_url: str, prefix: Optional[str] = None,
                   reads: Optional[SiteReads] = None) -> Discovery:
    """The articles of a listing page. Raises when the listing page cannot be read; a missing
    or broken sitemap is just no sitemap. `reads`: the run's shared robots and sitemap reads."""
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
    for loc, lastmod in await _sitemap_entries(http, listing, prefix, reads):
        url = _clean(loc)
        if url and under(url):
            sitemap.setdefault(url, parsing.parse_datetime_value(lastmod))
    return Discovery(prefix, listed, sitemap)


async def _shared(reads: Optional[SiteReads], url: str,
                  read: Callable[[], Awaitable[Tuple[Any, str]]]) -> Tuple[Any, str]:
    """read(), once per url within a run: a second caller awaits the first's read. A preview
    cut by the budget never cancels a read another preview awaits."""
    if reads is None:
        return await read()
    if url not in reads:
        reads[url] = asyncio.ensure_future(read())
    return await asyncio.shield(reads[url])


async def _sitemap_entries(http: KindHttp, listing: str, prefix: str,
                           reads: Optional[SiteReads] = None) -> List[Tuple[str, Optional[str]]]:
    origin = parsing.origin_from_source(listing, "")
    try:
        robots, _ = await _shared(reads, f"{origin}/robots.txt", lambda: http.get_text(f"{origin}/robots.txt"))
    except Exception:  # noqa: BLE001 - no robots.txt: the usual address
        robots = ""
    queue = [line.split(":", 1)[1].strip() for line in robots.splitlines()
             if line.lower().startswith("sitemap:")] or [f"{origin}/sitemap.xml"]
    section = prefix.strip("/").split("/")[0]
    entries: List[Tuple[str, Optional[str]]] = []
    read = 0
    while queue and read < MAX_SITEMAPS:
        url = _clean(queue.pop(0))
        if url is None or urllib.parse.urlparse(url).path.endswith(".gz"):
            continue
        read += 1
        try:
            body, _ = await _shared(reads, url, lambda: http.get_start(url, SITEMAP_MAX_BYTES))
        except Exception as exc:  # noqa: BLE001 - a missing sitemap is no sitemap
            logger.debug("Page watch: sitemap %s skipped (%s)", url, exc)
            continue
        root, locs = _sitemap_locs(body)
        if root == "sitemapindex":
            # An index's children that name the section (or posts) first.
            children = [loc for loc, _ in locs if loc]
            queue.extend(sorted(children, key=lambda child: not (section and section in child or "post" in child)))
        else:
            entries.extend((loc, lastmod) for loc, lastmod in locs if loc)
    return entries


def _sitemap_locs(body: bytes) -> Tuple[str, List[Tuple[str, Optional[str]]]]:
    """(the root's name, the (loc, lastmod) of each <url> or <sitemap>), as far as the file is
    readable: a sitemap cut at SITEMAP_MAX_BYTES or broken halfway keeps the entries before."""
    parser = ET.XMLPullParser(events=("start", "end"))
    root, locs = "", []
    try:
        parser.feed(body)
        # The parser reports a broken document here, at the read, after the events before it.
        for event, node in parser.read_events():
            name = parsing.local_name(node.tag)
            if not root:
                root = name
            elif event == "end" and name in ("url", "sitemap"):
                locs.append((parsing.child_text(node, "loc") or "", parsing.child_text(node, "lastmod")))
    except ET.ParseError:
        pass
    return root, locs


def page_date(page: str) -> Optional[datetime]:
    """The page's own publication date: meta article:published_time, JSON-LD datePublished,
    meta date, then a <time datetime> or a date written on the page, each only when the page
    has one (a tag or category page lists many)."""
    json_ld, times = JSON_LD_DATE_RE.search(page), {value.strip() for value in TIME_RE.findall(page)}
    one_time = times.pop() if len(times) == 1 else None
    values = (parsing.meta_content(page, "article:published_time"), json_ld and json_ld.group(1),
              *(parsing.meta_content(page, name) for name in META_DATES), one_time)
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


def page_title(page: str, url: str) -> str:
    """og:title, else <title>, else the first <h1>; less a " | Site" suffix: the og:site_name's
    (or one that starts with it: "| Mistral AI" for "Mistral"), or any short one on a <title>."""
    site = html.unescape(parsing.meta_content(page, "og:site_name")).strip()
    title, from_title_tag = html.unescape(parsing.meta_content(page, "og:title")).strip(), False
    if not title:
        for pattern in (TITLE_RE, H1_RE):
            match = pattern.search(page)
            if match and (title := parsing.strip_html(match.group(1))):
                from_title_tag = pattern is TITLE_RE
                break
    suffix = SITE_SUFFIX_RE.search(title)
    named = suffix.group(1).strip() if suffix else ""
    if suffix and (from_title_tag or (site and (named == site or named.startswith(f"{site} ")))):
        title = title[:suffix.start()]
    return title or url


def post_from(page: str, source_url: str, url: str, lastmod: Optional[datetime]) -> Optional[Dict[str, Any]]:
    """The post the page at url is, or None when it is no article (see the module docstring)."""
    date = page_date(page)
    if date is None and parsing.meta_content(page, "og:type").lower() != "article":
        return None
    return article_post(page, source_url, url, date or lastmod, adapter=PageWatchKind.adapter_type)


def article_post(page: str, source_url: str, url: str, date: Optional[datetime], *,
                 adapter: str, platform: str = "rss") -> Optional[Dict[str, Any]]:
    """The post any article page is: its body (the full-text reader), title, date (else now) and
    images; None when the page has no article body. Page watch and a saved page (issue 0031)."""
    content_html, fidelity = parsing.read_article_page(page, base_url=url)
    content = parsing.strip_html(content_html)
    if not content:
        return None
    image = parsing.normalize_media_url(parsing.meta_content(page, "og:image"))
    media_urls = list(dict.fromkeys([*([image] if image else []), *parsing.extract_html_image_urls(content_html)]))
    return {
        "platform": platform,
        "source": source_url,
        "url": url,
        "external_id": urllib.parse.urlparse(url).path,
        "guid": url,
        "title": page_title(page, url),
        "content": content,
        "content_html": content_html,
        "date": date or datetime.now(timezone.utc),
        "media_urls": media_urls,
        "categories": [],
        "metadata": {"adapter": adapter, PAGE_READ_KEY: fidelity},
    }


async def preview(http: KindHttp, url: str, prefix: Optional[str] = None,
                  reads: Optional[SiteReads] = None) -> Dict[str, Any]:
    """What following the page would give: {prefix, found, sitemap, items[{url, title, published_at}]},
    items the first PREVIEW_ITEMS posts (read PREVIEW_FAN_OUT at a time)."""
    address = parsing.web_address(url, "An address is needed to follow a page")
    if urllib.parse.urlparse(address).scheme.lower() not in ("http", "https"):
        raise ValueError("Only an http or https page can be followed")
    try:
        found = await discover(http, address, prefix, reads)
    except HttpError as exc:
        # The detail goes back to the caller: the status, never the site's answer.
        logger.info("Page watch preview: %s could not be read (%s)", address, str(exc)[:300])
        reason = f"HTTP {exc.status}" if exc.status else "no answer in time" if exc.timed_out else "no connection"
        raise ValueError(f"The page could not be read ({reason})") from None
    candidates = found.candidates()
    fan_out = asyncio.Semaphore(PREVIEW_FAN_OUT)

    async def one(candidate: str) -> Optional[Dict[str, Any]]:
        async with fan_out:
            try:
                page, _ = await http.get_text(candidate)
                return post_from(page, address, candidate, found.sitemap.get(candidate))
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


def is_home(url: str) -> bool:
    """Whether the address is a site's home page (no path): a poor page to follow (issue 0041)."""
    return not parsing.path_segments(parsing.web_address(url, "An address is needed"))


async def offers(http: KindHttp, pages: Sequence[str], menu: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """The pages that can be followed instead of a home page (issue 0041), each {url, **preview},
    the most articles first: the preview's count, among the pages it read an article from. The
    previews run at once; one that fails or is not done within OFFER_BUDGET_S is left out.
    When none of them is offered, the home page's menu links (issue 0047) are previewed in what
    is left of the budget, and only an article list is offered (see _article_list)."""
    deadline = asyncio.get_running_loop().time() + OFFER_BUDGET_S
    reads: SiteReads = {}
    found = [offer for offer in await _previews(http, pages, deadline, reads) if offer["items"]]
    if not found:
        started = datetime.now(timezone.utc)
        found = [offer for offer in await _previews(http, [page for page in menu if page not in pages], deadline, reads)
                 if _article_list(offer["items"], started)]
    return sorted(found, key=lambda offer: -offer["found"])


def _article_list(items: Sequence[Mapping[str, Any]], started: datetime) -> bool:
    """Whether a preview's posts read as a list of articles to follow: at least MENU_POSTS of them
    dated within MENU_RECENT. Pages of people or policies have dates too, old or few recent (a
    leader's joining year, a policy's last update). A post with no date of its own is dated when
    it was read, after the preview started: it is left out."""
    recent = [date for item in items if (date := parsing.parse_datetime_value(item["published_at"]))
              and started - MENU_RECENT <= date < started]
    return len(recent) >= MENU_POSTS


async def _previews(http: KindHttp, pages: Sequence[str], deadline: float,
                    reads: SiteReads) -> List[Dict[str, Any]]:
    """{url, **preview} of each page, in page order, the ones done by the deadline."""
    tasks = {asyncio.create_task(preview(http, page, reads=reads)): page for page in dict.fromkeys(pages)}
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, timeout=max(0.0, deadline - asyncio.get_running_loop().time()))
    for task in pending:
        task.cancel()
    for read in reads.values():
        if not read.done():
            read.cancel()
    found = []
    for task, page in tasks.items():
        if task not in done:
            logger.info("Page watch: %s not offered (no preview in %.0fs)", page, OFFER_BUDGET_S)
        elif task.exception() is not None:
            logger.info("Page watch: %s not offered (%s)", page, task.exception())
        else:
            found.append({"url": page, **task.result()})
    return found


class PageWatchKind(BaseSourceAdapter):
    adapter_type = "page_watch"
    available_basis = "estimate"        # discovered candidate pages; some may be no post
    PAGE_SIZE = 1                       # one article page per archive page: the host gate spaces them
    PAGE_DELAY_SECONDS = 2

    def __init__(self, http: KindHttp, *, stored_urls: Optional[StoredUrls] = None) -> None:
        super().__init__(http)
        self.stored_urls = stored_urls

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
        now = time.monotonic()
        candidates = [url for url in found.candidates() if SKIPPED.get(url, now) <= now]
        stored = (await asyncio.to_thread(self.stored_urls, candidates)
                  if self.stored_urls and candidates else set())
        posts: List[Dict[str, Any]] = []
        reads = skips = 0
        for url in (url for url in candidates if url not in stored):
            if len(posts) >= limit or skips >= SKIP_READS:
                break
            if reads:
                await self.http.sleep(self.PAGE_DELAY_SECONDS)
            reads += 1
            page = await self._page(url)
            post = post_from(page, str(source["handle_or_url"]), url, found.sitemap.get(url)) if page else None
            if post is None:
                skips += 1
                SKIPPED[url] = time.monotonic() + FAILED_RETRY_S if page is None else math.inf
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


__all__ = ["Discovery", "PageWatchKind", "article_post", "discover", "infer_prefix", "is_home", "normalise_prefix",
           "offers", "page_date", "page_title", "preview"]
