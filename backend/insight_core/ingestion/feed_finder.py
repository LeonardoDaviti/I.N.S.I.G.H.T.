"""The feed finder (issue 0026): from any page address to the feeds INSIGHT can read.

    finding = await find_feeds(http, registry, "borretti.me/article/no-man-is-an-island")
    finding.status   # "feed" | "found" | "direct" | "none"
    finding.feeds    # (Feed(url="https://borretti.me/feed.xml", title="Fernando Borretti"),)

One search, cheapest first, stopping at the first stage that finds something:
  0. No request. A kind or site adapter reads the address directly ("direct"), or a platform
     rule names its feed (Medium, GitHub releases).
  1. The address itself: a feed ("feed"); else its page's <link rel="alternate"> feeds, then
     its <a> links that look like feeds.
  2. The section page (/blog/) and the home page, fetched in parallel, the same way.
  3. The page's links to its own blog or newsroom (named so, or a blog./news. subdomain of the
     same site), at most two, the same way: www.cloudflare.com leads to blog.cloudflare.com.
  4. Common feed paths, under those blogs first, then at the site's root: the first that is a feed.
A candidate is proved by reading only its first FEED_BYTES into a pull parser: the root must
be rss, feed or RDF, and it is accepted at its first item or entry. At most FAN_OUT requests
run at once, each within REQUEST_TIMEOUT_S, the whole search within BUDGET_S: a slow or
blocked site gives "none", never a hang. Once one candidate is proved, the others of its stage
get PROOF_GRACE_S more, so a hanging one never holds back a feed already found.
JSON Feed is not looked for: INSIGHT reads RSS and Atom.
"""
from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable, List, Literal, Optional, Sequence, Tuple

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds.parsing import local_name, origin_from_source, path_segments, web_address

logger = logging.getLogger("insight.ingestion.feed_finder")

PAGE_BYTES = 3_000_000          # the most of a page read for its links (cloudflare.com: 1.3 MB, the blog link in its footer)
FEED_BYTES = 64 * 1024          # the most of a candidate read to prove it a feed
PARSE_CHUNK = 16 * 1024         # fed to the pull parser at a time, so a page stops early
REQUEST_TIMEOUT_S = 5.0
BUDGET_S = 10.0
PROOF_GRACE_S = 1.0
FAN_OUT = 4
MAX_CANDIDATES = 6              # per stage, from the pages' links
# A page with no feed may link its own blog or newsroom, often on a subdomain
# (www.cloudflare.com -> blog.cloudflare.com): links so named, on the same site, at most two.
BLOG_LINK_TEXTS = frozenset({"blog", "the blog", "our blog", "news", "newsroom", "press", "engineering blog"})
BLOG_HOSTS = ("blog.", "news.", "newsroom.")
MAX_BLOG_LINKS = 2
COMMON_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml", "/feed.atom", "/feed.rss",
                "/?feed=rss2", "/feeds/posts/default")

FEED_ROOTS = {"rss", "feed", "rdf"}
FEED_SEGMENTS = {"rss", "atom", "feed"}
FEED_ENDINGS = (".rss", ".atom", "feed.xml", "rss.xml", "atom.xml", "index.xml")
FEED_LINK_TEXTS = {"rss", "atom", "feed", "rss feed", "atom feed"}

Status = Literal["feed", "found", "direct", "none"]


@dataclass(frozen=True)
class Feed:
    url: str
    title: str                  # the feed's own <title>; "" when it has none


@dataclass(frozen=True)
class FeedFinding:
    status: Status              # feed: the address is one; found: feeds for it; direct: a kind reads it
    feeds: Tuple[Feed, ...] = ()


async def find_feeds(http: KindHttp, registry: KindRegistry, url: str) -> FeedFinding:
    """The feeds for the page at url (a scheme is added when missing). Never raises for a
    site's failure or slowness; ValueError for an empty address."""
    address = _normalise(url)
    if registry.resolve({"platform": "rss", "handle_or_url": address}).name != "generic_rss":
        return FeedFinding("direct")
    search = _Search(http)
    started = time.monotonic()
    try:
        async with asyncio.timeout(BUDGET_S):
            finding = await search.run(address)
    except TimeoutError:
        finding = FeedFinding("none")
    logger.info("Feed finder: %s -> %s, %d feed(s), %d request(s), %.1fs", address, finding.status,
                len(finding.feeds), search.requests, time.monotonic() - started)
    return finding


def _normalise(url: str) -> str:
    parsed = urllib.parse.urlparse(web_address(url, "An address is needed to look for its feed"))
    return urllib.parse.urlunparse(parsed._replace(path=parsed.path or "/"))


class _Search:
    def __init__(self, http: KindHttp) -> None:
        self.http = http
        self.fan_out = asyncio.Semaphore(FAN_OUT)
        self.tried: set[str] = set()
        self.requests = 0

    async def run(self, url: str) -> FeedFinding:
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            return FeedFinding("none")
        rule = _platform_feed(url)
        if rule and (feeds := await self._prove([rule])):
            return FeedFinding("found", feeds)

        page = await self._get(url, PAGE_BYTES)
        here = url
        if page:
            body, here = page
            self.tried.update({url, here})
            title = _feed_title(body)
            if title is not None:
                return FeedFinding("feed", (Feed(here, title),))
            if feeds := await self._prove(_feed_links(body, here)):
                return FeedFinding("found", feeds)

        pages = await asyncio.gather(*(self._get(around, PAGE_BYTES) for around in _around(here, url)))
        if feeds := await self._prove([link for got in pages if got for link in _feed_links(*got)]):
            return FeedFinding("found", feeds)

        blogs = _blog_links(*page) if page else []
        blog_pages = await asyncio.gather(*(self._get(blog, PAGE_BYTES) for blog in blogs))
        if feeds := await self._prove([link for got in blog_pages if got for link in _feed_links(*got)]):
            return FeedFinding("found", feeds)

        # Common paths under the blogs the page links first (more specific), then at the root.
        origin = origin_from_source(here, "")
        bases = [*(blog.rstrip("/") for blog in blogs), origin]
        guesses = [base + path for base in dict.fromkeys(bases) for path in COMMON_PATHS]
        if feeds := await self._prove(guesses, limit=None, first=True):
            return FeedFinding("found", feeds[:1])
        return FeedFinding("none")

    async def _get(self, url: str, max_bytes: int) -> Optional[Tuple[bytes, str]]:
        """(the start of the body, the final URL), or None when the request fails or is slow."""
        async with self.fan_out:
            self.requests += 1
            try:
                return await asyncio.wait_for(self.http.get_start(url, max_bytes), REQUEST_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 - a failed candidate is just not a feed
                logger.debug("Feed finder: %s failed (%s %s)", url, type(exc).__name__,
                             getattr(exc, "status", None) or "")
                return None

    async def _sniff(self, url: str) -> Optional[Tuple[str, Feed]]:
        """(the final URL, the feed) when url is a feed, else None."""
        got = await self._get(url, FEED_BYTES)
        if got is None:
            return None
        title = _feed_title(got[0])
        return None if title is None else (got[1], Feed(url, title))

    async def _prove(self, candidates: Iterable[str], limit: Optional[int] = MAX_CANDIDATES,
                     first: bool = False) -> Tuple[Feed, ...]:
        """The candidates that are feeds, in candidate order (one per final URL), each tried once.
        With first, it returns as soon as the first feed in that order is known."""
        fresh = [url for url in dict.fromkeys(candidates) if url not in self.tried][:limit]
        self.tried.update(fresh)
        tasks = [asyncio.create_task(self._sniff(url)) for url in fresh]
        loop = asyncio.get_running_loop()
        pending, deadline = set(tasks), None
        try:
            while pending:
                wait = None if deadline is None else max(0.0, deadline - loop.time())
                done, pending = await asyncio.wait(pending, timeout=wait, return_when=asyncio.FIRST_COMPLETED)
                if not done:
                    break
                if deadline is None and any(task.result() for task in done):
                    deadline = loop.time() + PROOF_GRACE_S
                if first and _first_known(tasks):
                    break
        finally:
            for task in tasks:
                task.cancel()
        feeds: dict[str, Feed] = {}
        for task in tasks:
            if task.done() and not task.cancelled() and task.result():
                final, feed = task.result()
                feeds.setdefault(final, feed)
        return tuple(feeds.values())


def _first_known(tasks: Sequence["asyncio.Task[Optional[Tuple[str, Feed]]]"]) -> bool:
    """Whether a task has proved a feed and every task before it is done."""
    for task in tasks:
        if not task.done():
            return False
        if task.result():
            return True
    return False


def _platform_feed(url: str) -> Optional[str]:
    """The feed a platform keeps at a known address for this page, else None."""
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    segments = path_segments(url)
    feed = None
    if host == "medium.com" and segments and segments[0].startswith("@"):
        feed = f"https://medium.com/feed/{segments[0]}"
    elif host.endswith(".medium.com"):
        feed = f"https://{host}/feed"
    elif host == "github.com" and len(segments) >= 2:
        feed = f"https://github.com/{segments[0]}/{segments[1]}/releases.atom"
    return feed if feed != url else None


def _around(here: str, url: str) -> List[str]:
    """The section page (first path segment) and the home page of here, less the page itself."""
    origin = origin_from_source(here, "")
    segments = path_segments(here)
    pages = ([f"{origin}/{segments[0]}/"] if len(segments) >= 2 else []) + [f"{origin}/"]
    seen = {here.rstrip("/"), url.rstrip("/")}
    return [page for page in pages if page.rstrip("/") not in seen]


def feed_title(start: bytes) -> Optional[str]:
    """The feed's title when start (up to FEED_BYTES) begins a feed with an item, else None:
    the finder's own proof, for the source doctor's re-check of an old address."""
    return _feed_title(start)


def _feed_title(start: bytes) -> Optional[str]:
    """The feed's title when start begins an RSS, Atom or RDF feed with an item, else None."""
    parser = ET.XMLPullParser(events=("start", "end"))
    root, title = None, None
    try:
        for offset in range(0, len(start), PARSE_CHUNK):
            parser.feed(start[offset:offset + PARSE_CHUNK])
            for event, element in parser.read_events():
                name = local_name(element.tag).lower()
                if root is None:
                    if name not in FEED_ROOTS:
                        return None
                    root = name
                elif event == "start" and name in ("item", "entry"):
                    return " ".join((title or "").split())[:200]
                elif event == "end" and name == "title" and title is None:
                    title = "".join(element.itertext())
    except ET.ParseError:
        return None
    return None


def _feed_links(body: bytes, page_url: str) -> List[str]:
    """The page's feed candidates, absolute: <link rel="alternate"> feeds, then feed-like <a>."""
    links = _FeedLinks()
    try:
        links.feed(body.decode("utf-8", errors="replace"))
        links.close()
    except Exception:  # noqa: BLE001 - keep what was read before the page broke the parser
        pass
    base = (_absolute(page_url, links.base) if links.base else None) or page_url
    absolute = (_absolute(base, href) for href in links.alternates + links.anchors)
    return list(dict.fromkeys(url for url in absolute if url))


def _blog_links(body: bytes, page_url: str) -> List[str]:
    """The page's links to its own blog or newsroom (see BLOG_LINK_TEXTS), absolute, on the same
    site (a blog./news. subdomain included), at most MAX_BLOG_LINKS."""
    links = _FeedLinks()
    try:
        links.feed(body.decode("utf-8", errors="replace"))
        links.close()
    except Exception:  # noqa: BLE001 - keep what was read before the page broke the parser
        pass
    site = _site(_host(page_url))
    absolute = (_absolute(page_url, href) for href in links.blogs)
    same = (url for url in absolute if url and url != page_url and _site(_host(url)) == site)
    return list(dict.fromkeys(same))[:MAX_BLOG_LINKS]


def _host(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower()
    except ValueError:      # a malformed link
        return ""


def _site(host: str) -> str:
    """The host without a www., blog., news. or newsroom. label: the site it belongs to."""
    first, _, rest = host.partition(".")
    return rest if rest and f"{first}." in ("www.",) + BLOG_HOSTS else host


def _absolute(base: str, href: str) -> Optional[str]:
    """href as an absolute http(s) URL without its fragment; None for anything else (a
    malformed one, "http://[x/", too)."""
    try:
        url = urllib.parse.urldefrag(urllib.parse.urljoin(base, href.strip()))[0]
        return url if urllib.parse.urlparse(url).scheme in ("http", "https") else None
    except ValueError:
        return None


def _is_feed_type(value: str) -> bool:
    kind = value.split(";")[0].strip().lower()
    return "json" not in kind and any(word in kind for word in ("rss", "atom", "rdf"))


def _looks_like_feed(href: str, text: str) -> bool:
    try:
        path = urllib.parse.urlparse(href.lower()).path
    except ValueError:      # a malformed link
        return False
    return (bool(FEED_SEGMENTS & set(path.split("/"))) or path.endswith(FEED_ENDINGS)
            or " ".join(text.lower().split()) in FEED_LINK_TEXTS)


class _FeedLinks(HTMLParser):
    """Collects <base href>, the alternate feed links and the feed-like anchors, in page order.
    A comment feed (comment in its title, text or address) is left out."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.base: Optional[str] = None
        self.alternates: List[str] = []
        self.anchors: List[str] = []
        self.blogs: List[str] = []                   # links to the site's own blog or newsroom
        self._anchor: Optional[List[str]] = None     # [href, text so far]

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        values = {name: value or "" for name, value in attrs}
        href = values.get("href", "")
        if tag == "base" and self.base is None and href:
            self.base = href
        elif (tag == "link" and href and "alternate" in values.get("rel", "").lower().split()
              and _is_feed_type(values.get("type", "")) and not _is_comments(href, values.get("title", ""))):
            self.alternates.append(href)
        elif tag == "a" and href:
            self._anchor = [href, ""]

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor[1] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._anchor is not None:
            href, text = self._anchor
            self._anchor = None
            if _looks_like_feed(href, text) and not _is_comments(href, text):
                self.anchors.append(href)
            elif " ".join(text.lower().split()) in BLOG_LINK_TEXTS or _host(href).startswith(BLOG_HOSTS):
                self.blogs.append(href)


def _is_comments(href: str, label: str) -> bool:
    return "comment" in f"{href} {label}".lower()


__all__ = ["Feed", "FeedFinding", "find_feeds"]
