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
     A page that cannot be read (a feed gone) takes its home page's links instead. The ones
     that answer on the same site are reported as the finding's pages: with no feed, the
     pages to follow instead of a home page (issue 0041). With none named, the page's own menu
     links (header and navigation, then footer) are reported instead, unread: the preview
     chooses among them by their articles (issue 0047).
  4. Common feed paths, under those blogs first, then at the site's root: the first that is a feed.
The home page's menu link named Blog (or Writing, Posts, Essays) to another domain is a
candidate after the site's own feeds (issue 0108: a person's site whose blog is elsewhere): its
feeds follow the site's, or are the finding when the site has none. A platform's takes its rule.
A feed found whose entries carry no body may be a blog that moved (issue 0108): its first entry's
page is read, and when it redirects (by HTTP, a meta refresh or a canonical link) to another site,
the finder runs on that page too. Its feeds come first; the old feed follows, saying where its
posts now live (Feed.moved_to).
A candidate is proved by reading only its first FEED_BYTES into a pull parser: the root must
be rss, feed or RDF, and it is accepted at its first item or entry. At most FAN_OUT requests
run at once, each within REQUEST_TIMEOUT_S, the whole search within BUDGET_S: a slow or
blocked site gives "none", never a hang. Once one candidate is proved, the others of its stage
get PROOF_GRACE_S more, so a hanging one never holds back a feed already found.
JSON Feed is not looked for: INSIGHT reads RSS and Atom.

Issue 0137 (new spheres, round 2):
- A t.me channel or an x.com account pasted takes the configured bridge (TELEGRAM_RSS_HOSTS, NITTER_HOSTS);
  a bridge's address is probed before "direct": one answering 4xx/5xx is never direct.
- A page that refuses us (401/403/429) has, after the common paths, the feeds its site's robots.txt and
  sitemap name, and the shapes of the feeds your other sources at that publisher use, with this page's
  own path words (`known`), tried; no publisher's path is named here.
- A link saying RSS or feeds that is no feed is a feed directory: one is followed, and the feeds on it
  are known by their content, not their extension.
- An Apple Podcasts page asks the public lookup for the show's feed.
- A saved search is never the only offer while the search can go on; else the finding says so (`note`).
- Every feed offered is read whole with the fetcher's own parser (parse_feed_posts, a bare & repaired):
  one it cannot read is refused with the parser's message.
- A feed sharing no item with the page's 3+ articles, or whose newest item is 30+ days older than the
  page's newest article, is flagged (`Feed.flag`): the site's feed, not this page's.
- "none" says why (`reason`): blocked, rate-limited, needs login, gone, server error, empty feed, no
  bridge, none found.
"""
from __future__ import annotations

import asyncio
import logging
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Literal, Optional, Sequence, Tuple

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.nitter_rss import nitter_origin
from insight_core.ingestion.kinds.parsing import (
    item_path,
    local_name,
    moved_to,
    origin_from_source,
    path_segments,
    web_address,
)
from insight_core.ingestion.kinds.telegram_rss import bridge_origin
from insight_core.utils.addresses import BLOG_HOSTS, blog_site, host_of, publication_of, same_site
from insight_core.utils.url_normalization import normalize_url

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
MAX_BLOG_LINKS = 2
# A home page that names no blog may still have one under another word ("Now", "Latest"): its
# own menu links, header and navigation before the footer, the shallowest first, at most twelve
# (a menu may lead with ten sign-up, demo and product pages before its blog).
MENU_TAGS = ("header", "nav", "footer")
# A home page's menu link so named, on another domain, is its blog elsewhere (issue 0108): at most two.
ELSEWHERE_BLOG_TEXTS = frozenset({"blog", "writing", "posts", "essays"})
MAX_MENU_LINKS = 12
COMMON_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml", "/index.xml", "/feed.atom", "/feed.rss",
                "/?feed=rss2", "/feeds/posts/default")

# A page that refuses us (issue 0135: a journal's bot protection) while its feed addresses answer:
# these paths are tried under the page itself, then at the site's root, before anything else.
BLOCKED_STATUSES = (401, 403, 429)
BLOCKED_PATHS = ("/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml")
REFUSED = "this feed has items INSIGHT can't read"
# A feed that reads as a saved search (issue 0135): its title's words, its address's query or path.
SEARCH_WORDS = frozenset({"search", "query"})
SEARCH_PARAMS = frozenset({"q", "query", "term", "terms", "search", "s", "keyword", "keywords"})

# Issue 0137.
PARSED_FEEDS = 3                 # the feeds offered that are read whole with the fetcher's parser
PARSE_TIMEOUT_S = 8.0
SEARCH_ONLY = "only a saved search was found"
SCOPE_MIN_ARTICLES = 3           # a page listing this many articles, none of them in a feed: another scope
STALE_AFTER = timedelta(days=30)  # a feed whose newest item is this much older than the page's newest article
OTHER_SCOPE, STALE = "other_scope", "stale"
MAX_DIRECTORY_FEEDS = 6          # the feeds a feed directory offers, proved by their content
MAX_LEARNED = 8                  # the addresses tried from the shapes of your other feeds at a publisher
MAX_SITEMAPS = 2                 # a blocked site's sitemaps read for their feed addresses
SITEMAP_BYTES = 2_000_000
LOC_RE = re.compile(r"(?is)<loc>\s*([^<\s]+)\s*</loc>")
SITEMAP_LINE_RE = re.compile(r"(?im)^\s*sitemap\s*:\s*(\S+)")
URL_IN_TEXT_RE = re.compile(r"""https?://[^\s<>"']+""")
PAGE_TIME_RE = re.compile(r"""(?is)<time\b[^>]*?\bdatetime\s*=\s*["']([^"']+)["']""")
PAGE_PUBLISHED_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
# Path words that name a kind of page, not the page itself: never put into a learned shape.
GENERIC_SEGMENTS = frozenset({"journal", "journals", "home", "toc", "current", "issue", "issues", "loi", "doi",
                              "abs", "full", "action", "en", "index", "about", "blog", "news", "author", "authors",
                              "page", "pages", "topics", "topic", "section", "sections", "category", "tag"})
FEED_WORDS = frozenset({"rss", "atom", "feed", "feeds", "xml", "rdf", "rss2", "etoc"})
DIRECTORY_WORDS = frozenset({"rss", "feeds", "atom"})
# A pasted address on a platform INSIGHT reads through a bridge (issue 0137 A3).
TELEGRAM_HOSTS = frozenset({"t.me", "telegram.me"})
X_HOSTS = frozenset({"x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com"})
X_RESERVED = frozenset({"home", "search", "explore", "i", "intent", "share", "hashtag", "settings", "messages",
                        "notifications", "login", "signup", "tos", "privacy"})
TELEGRAM_RESERVED = frozenset({"c", "joinchat", "addstickers", "addemoji", "share", "proxy", "socks", "login"})
BRIDGE_KINDS = frozenset({"nitter_rss", "telegram_rss"})
APPLE_PODCAST_HOSTS = frozenset({"podcasts.apple.com", "itunes.apple.com"})
APPLE_ID_RE = re.compile(r"(?:^|/)id(\d{4,})(?:$|[/?])")
APPLE_LOOKUP = "https://itunes.apple.com/lookup?id={}&entity=podcast"
# "none" says why (issue 0137 B5), from the address's own answer.
REASON_BY_STATUS = {401: "needs login", 407: "needs login", 403: "blocked", 429: "rate-limited", 404: "gone", 410: "gone"}
NONE_FOUND, EMPTY_FEED, NO_BRIDGE, SERVER_ERROR = "none found", "empty feed", "no bridge", "server error"

FEED_ROOTS = {"rss", "feed", "rdf"}
FEED_SEGMENTS = {"rss", "atom", "feed"}
FEED_ENDINGS = (".rss", ".atom", "feed.xml", "rss.xml", "atom.xml", "index.xml")
FEED_LINK_TEXTS = {"rss", "atom", "feed", "rss feed", "atom feed"}
# An item's body: RSS's description and content:encoded, Atom's summary and content (issue 0108).
BODY_ELEMENTS = frozenset({"description", "encoded", "summary", "content"})

Status = Literal["feed", "found", "direct", "none"]


@dataclass(frozen=True)
class Feed:
    url: str
    title: str                  # the feed's own <title>; "" when it has none
    # The item addresses in the part of the feed read to prove it (issue 0060: what it holds).
    items: Tuple[str, ...] = field(default=(), compare=False)
    # Their titles, in feed order (issue 0072: the source doctor's evidence and preview).
    titles: Tuple[str, ...] = field(default=(), compare=False)
    # Every entry read carries no body (issue 0108: its posts may have moved).
    bodiless: bool = field(default=False, compare=False)
    # The site its posts now live at ("blog.example"), when its first entry's page moved there (0108).
    moved_to: str = field(default="", compare=False)
    # Its items are where INSIGHT's parser reads them (issue 0135, parsing.ITEM_PATHS); an unreadable
    # feed is never offered: the finding says it was refused.
    readable: bool = field(default=True, compare=False)
    # It reads as a saved search ("Keyword search for query", ?q=): ranked below the site's own feeds.
    search: bool = field(default=False, compare=False)
    # Its newest item's date, as far as it was read (issue 0137 B2).
    newest: Optional[datetime] = field(default=None, compare=False)
    # The site's feed, not this page's (issue 0137 B2): OTHER_SCOPE (none of the page's articles) or STALE.
    flag: str = field(default="", compare=False)
    # The whole document, when the read that proved it held all of it (issue 0137 B4: parsed without asking again).
    whole: bytes = field(default=b"", compare=False, repr=False)


@dataclass(frozen=True)
class FeedFinding:
    status: Status              # feed: the address is one; found: feeds for it; direct: a kind reads it
    feeds: Tuple[Feed, ...] = ()
    pages: Tuple[str, ...] = ()  # none: the site's own blog or news pages the search read (stage 3)
    menu: Tuple[str, ...] = ()   # none, when no page is named so: the page's own menu links, unread
    landed: str = field(default="", compare=False)   # where the address itself landed, when it was read
    # A section address read, with its home page read beside it (stage 2): the home page's own
    # blog or news links, else its menu links, unread. Follow from a section (issue 0060) offers
    # them when the section gives nothing, without looking at the home page again.
    home_pages: Tuple[str, ...] = field(default=(), compare=False)
    home_menu: Tuple[str, ...] = field(default=(), compare=False)
    # A feed was found whose items INSIGHT cannot read (issue 0135): REFUSED, else "". A feed the
    # fetcher's parser refuses says the parser's message (issue 0137 B4).
    refused: str = field(default="", compare=False)
    # Why none (issue 0137 B5): REASON_BY_STATUS's, EMPTY_FEED, NO_BRIDGE, SERVER_ERROR or NONE_FOUND; "" else.
    reason: str = field(default="", compare=False)
    # SEARCH_ONLY when the only feed found is a saved search (issue 0137 A5).
    note: str = field(default="", compare=False)


async def find_feeds(http: KindHttp, registry: KindRegistry, url: str, known: Sequence[str] = ()) -> FeedFinding:
    """The feeds for the page at url (a scheme is added when missing). Never raises for a
    site's failure or slowness; ValueError for an empty address. `known`: the feed addresses your
    sources use (issue 0137 A2: a blocked page tries their shapes at its own publisher)."""
    address = _normalise(url)
    search = _Search(http, known)
    started = time.monotonic()
    kind = registry.resolve({"platform": "rss", "handle_or_url": address}).name
    bridged = bridge_feed(address) if kind == "generic_rss" else None
    if kind != "generic_rss" or bridged is not None:
        finding = await search.through_bridge(address, kind, bridged)
    else:
        try:
            async with asyncio.timeout(BUDGET_S):
                finding = await search.run(address)
        except TimeoutError:
            finding = FeedFinding("none", pages=search.pages, menu=search.menu)
        if finding.feeds:
            finding = await search.parsed(finding)
        if search.refused and not finding.feeds and not finding.refused:
            finding = replace(finding, refused=REFUSED)
        if search.landed:
            finding = replace(finding, landed=search.landed, home_pages=search.home_pages, home_menu=search.home_menu)
    if finding.status == "none" and not finding.reason:
        finding = replace(finding, reason=search.reason(address))
    logger.info("Feed finder: %s -> %s, %d feed(s), %d request(s), %.1fs%s", address, finding.status,
                len(finding.feeds), search.requests, time.monotonic() - started,
                f" ({finding.reason})" if finding.reason else "")
    return finding


def bridge_feed(url: str) -> Optional[Tuple[str, Optional[str]]]:
    """(the platform, the bridge's feed address) for a pasted t.me channel or x.com account (issue 0137
    A3): the configured Telegram bridge's /rss/<channel>, your Nitter's /<user>/rss; the address None when
    no bridge is set. None for any other address."""
    host = publication_of(host_of(url))
    segments = path_segments(url)
    if host in TELEGRAM_HOSTS and segments:
        channel = segments[1] if segments[0] == "s" and len(segments) > 1 else segments[0]
        if channel.lower() in TELEGRAM_RESERVED or channel.startswith("+") or not channel.replace("_", "").isalnum():
            return None
        origin = bridge_origin()
        return "telegram", f"{origin}/rss/{channel}" if origin else None
    if host in X_HOSTS and segments:
        user = segments[0].lstrip("@")
        if user.lower() in X_RESERVED or not user.replace("_", "").isalnum():
            return None
        origin = nitter_origin()
        return "x", f"{origin}/{user}/rss" if origin else None
    return None


async def page_feeds(http: KindHttp, url: str) -> Tuple[Feed, ...]:
    """The feeds the page at url names itself (stage 1 only): the page when it is one, else its
    feed links that are feeds. Never raises for a site's failure or slowness. Follow from a
    section (issue 0060) reads the home page's feeds beside the section's: a newspaper's tech
    feed may hold fewer of the linked articles than its feed of everything."""
    search = _Search(http)
    try:
        async with asyncio.timeout(BUDGET_S):
            page = await search._get(_normalise(url), PAGE_BYTES)
            if not page:
                return ()
            body, here = page
            title = _feed_title(body)
            if title is not None:
                feed = _feed(here, title, body, here)
                return (feed,) if feed.readable else ()
            return await search._prove(_feed_links(body, here))
    except TimeoutError:
        return ()


def _normalise(url: str) -> str:
    parsed = urllib.parse.urlparse(web_address(url, "An address is needed to look for its feed"))
    return urllib.parse.urlunparse(parsed._replace(path=parsed.path or "/"))


class _Search:
    def __init__(self, http: KindHttp, known: Sequence[str] = ()) -> None:
        self.http = http
        self.known = tuple(known)               # your sources' feed addresses (issue 0137 A2)
        self.statuses: Dict[str, int] = {}      # url -> the HTTP error it answered (issue 0137 B5)
        self.empty_feed = False                 # the address is a feed with no item (B5)
        self.searches: Tuple[Feed, ...] = ()    # saved searches kept aside while the search goes on (A5)
        self.directories: List[str] = []        # links saying RSS or feeds that are pages (B3)
        self.followed_directory = False
        self.articles: Tuple[str, ...] = ()     # the page's own article links (B2)
        self.page_newest: Optional[datetime] = None
        self.fan_out = asyncio.Semaphore(FAN_OUT)
        self.tried: set[str] = set()
        self.requests = 0
        self.pages: Tuple[str, ...] = ()
        self.menu: Tuple[str, ...] = ()
        self.landed = ""
        self.home_pages: Tuple[str, ...] = ()
        self.home_menu: Tuple[str, ...] = ()
        self.elsewhere: Tuple[str, ...] = ()   # the home page's menu blog links on another domain (0108)
        self.refused = False                   # a feed was found that INSIGHT cannot read (0135)
        self.blocked: set[str] = set()         # the addresses that refused us (BLOCKED_STATUSES, 0135)

    async def run(self, url: str) -> FeedFinding:
        finding = await self._run(url)
        if self.elsewhere and finding.status in ("found", "none"):
            finding = await self._with_elsewhere(finding)
        if finding.status == "none" and self.searches:
            # Only a saved search was found (issue 0137 A5): offered, and said so.
            return FeedFinding("found", self.searches, note=SEARCH_ONLY)
        return await self._past_moved(finding)

    async def through_bridge(self, address: str, kind: str, bridged: Optional[Tuple[str, Optional[str]]]) -> FeedFinding:
        """A pasted t.me or x.com address (bridged) through the configured bridge, or an address a kind
        reads: a bridge's is probed first, and one answering an HTTP error is never "direct" (issue 0137 A3)."""
        if bridged is not None:
            platform, feed_url = bridged
            if feed_url is None:
                return FeedFinding("none", reason=NO_BRIDGE)
            got = await self._sniff(feed_url)
            if got:
                return FeedFinding("found", (replace(got[1], url=feed_url),))
            return FeedFinding("none", reason=self.reason(feed_url) if feed_url in self.statuses else NO_BRIDGE)
        if kind in BRIDGE_KINDS:
            await self._get(address, FEED_BYTES)
            if address in self.statuses:
                return FeedFinding("none", reason=self.reason(address))
        return FeedFinding("direct")

    def reason(self, address: str) -> str:
        """Why the search found nothing (issue 0137 B5), from the address's own answer."""
        if self.empty_feed:
            return EMPTY_FEED
        status = self.statuses.get(address) or self.statuses.get(self.landed) or 0
        if status in REASON_BY_STATUS:
            return REASON_BY_STATUS[status]
        return SERVER_ERROR if status >= 500 else NONE_FOUND

    async def parsed(self, finding: FeedFinding) -> FeedFinding:
        """The finding with its first PARSED_FEEDS feeds read whole with the fetcher's own parser (issue
        0137 B4): one it refuses is never offered (the parser's message says why); and flagged when it is
        the site's feed, not this page's (B2). A feed that cannot be fetched again now is kept as proved."""
        checked = await asyncio.gather(*(self._parse(feed) for feed in finding.feeds[:PARSED_FEEDS]))
        feeds = [feed for feed, _ in checked if feed is not None] + list(finding.feeds[PARSED_FEEDS:])
        if not feeds:
            refused = next(error for _, error in checked if error)
            return FeedFinding("none", pages=self.pages, menu=self.menu, refused=refused)
        return replace(finding, feeds=tuple(feeds))

    async def _parse(self, feed: Feed) -> Tuple[Optional[Feed], str]:
        if feed.whole:
            text = feed.whole.decode("utf-8", errors="replace")
        else:
            try:
                self.requests += 1
                text, _ = await asyncio.wait_for(self.http.get_text(feed.url), PARSE_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 - not read again now: kept as the finder proved it
                logger.debug("Feed finder: %s not read whole (%s)", feed.url, type(exc).__name__)
                return self._flagged(feed), ""
        try:
            posts = parsing.parse_feed_posts(text, feed.url)
        except ET.ParseError as exc:
            return None, f"the feed can't be read: {exc}"
        if not posts and parsing.feed_items(text):
            return None, REFUSED
        dates = [post["date"] for post in posts if isinstance(post.get("date"), datetime)]
        items = tuple(post["url"] for post in posts if isinstance(post.get("url"), str))
        return self._flagged(replace(feed, items=items or feed.items, newest=max(dates) if dates else feed.newest)), ""

    def _flagged(self, feed: Feed) -> Feed:
        """The feed flagged OTHER_SCOPE when it holds none of the page's 3+ articles, else STALE when its
        newest item is STALE_AFTER older than the page's newest article (issue 0137 B2)."""
        if len(self.articles) >= SCOPE_MIN_ARTICLES and feed.items:
            if not {_article_key(url) for url in feed.items} & {_article_key(url) for url in self.articles}:
                return replace(feed, flag=OTHER_SCOPE)
        if self.page_newest and feed.newest and feed.newest < self.page_newest - STALE_AFTER:
            return replace(feed, flag=STALE)
        return feed

    def _offer(self, feeds: Tuple[Feed, ...]) -> Tuple[Feed, ...]:
        """The feeds when one is the site's own; saved searches alone are kept aside (issue 0137 A5)."""
        if feeds and all(feed.search for feed in feeds):
            self.searches += tuple(feed for feed in feeds if feed not in self.searches)
            return ()
        return feeds

    async def _with_elsewhere(self, finding: FeedFinding) -> FeedFinding:
        """The finding with the feeds of the home page's blog on another domain after its own (issue
        0108): a platform's by its rule, else the feeds its page names, or the page when it is one."""
        rules = [rule for link in self.elsewhere if (rule := _platform_feed(link))]
        pages = [link for link in self.elsewhere if not _platform_feed(link)]
        candidates = list(rules)
        for got in await asyncio.gather(*(self._get(link, PAGE_BYTES) for link in pages)):
            if got:
                candidates += [got[1]] if _feed_title(got[0]) is not None else _feed_links(*got)
        known = {feed.url for feed in finding.feeds}
        more = tuple(feed for feed in await self._prove(candidates) if feed.url not in known)
        return replace(finding, status="found", feeds=finding.feeds + more, pages=(), menu=()) if more else finding

    async def _past_moved(self, finding: FeedFinding) -> FeedFinding:
        """The finding, and when the first of its feeds whose entries carry no body has posts on
        another site now (issue 0108), the feeds found from that post's page first, the old feed
        then saying where its posts live. Its status is "found" then: a choice."""
        old = next((feed for feed in finding.feeds if feed.bodiless and feed.items), None)
        if old is None:
            return finding
        got = await self._get(old.items[0], FEED_BYTES)
        if got is None:
            return finding
        body, landed = got
        target = landed if not same_site(host_of(landed), host_of(old.items[0])) else \
            moved_to(body.decode("utf-8", errors="replace"), landed)
        if not target or same_site(host_of(target), host_of(old.items[0])):
            return finding
        there = _Search(self.http)
        moved = await there._run(target)
        self.requests += there.requests
        if not moved.feeds:
            return finding
        # Found already (the home page's blog elsewhere, 0108's other way), it moves to the front.
        first = {feed.url for feed in moved.feeds}
        host = publication_of(host_of(target))
        feeds = tuple(moved.feeds) + tuple(replace(feed, moved_to=host) if feed is old else feed
                                           for feed in finding.feeds if feed.url not in first)
        logger.info("Feed finder: the posts of %s now live at %s", old.url, host)
        return replace(finding, status="found", feeds=feeds)

    async def _run(self, url: str) -> FeedFinding:
        if urllib.parse.urlparse(url).scheme not in ("http", "https"):
            return FeedFinding("none")
        rule = _platform_feed(url)
        if rule and (feeds := await self._prove([rule])):
            return FeedFinding("found", feeds)
        if (show := await self._apple_podcast(url)) is not None:
            return show

        page = await self._get(url, PAGE_BYTES)
        here = url
        if page:
            body, here = page
            self.landed = here
            self.tried.update({url, here})
            title = _feed_title(_repaired(body))
            if title is not None:
                feed = _feed(here, title, _repaired(body), here, whole=body if len(body) < PAGE_BYTES else None)
                if not feed.readable:
                    # A feed whose items the parser would not read stores nothing (issue 0135).
                    self.refused = True
                    return FeedFinding("none")
                return FeedFinding("feed", (feed,))
            if _is_feed_root(_repaired(body)):
                self.empty_feed = True          # a feed with no item yet (issue 0137 B5)
                return FeedFinding("none")
            links = _links(body)
            if path_segments(here):
                self.articles = tuple(_article_links(links, here))
                self.page_newest = _page_newest(body)
            else:
                self.elsewhere = tuple(_elsewhere_blogs(links, here))
            if feeds := self._offer(await self._prove(_feed_links(body, here)) or await self._directory()):
                return FeedFinding("found", feeds)
        elif url in self.blocked:
            # The page refuses us; its feed addresses may not (issue 0135): the known feed paths
            # under the page, then at the site's root, before the pages around it (refused too).
            page_base = url.split("?", 1)[0].rstrip("/")
            bases = dict.fromkeys([page_base, origin_from_source(url, "")])
            if feeds := self._offer(await self._prove([base + path for base in bases for path in BLOCKED_PATHS],
                                                      limit=None, first=True)):
                return FeedFinding("found", feeds[:1])
            # Then the feeds its robots.txt and sitemap name, and the shapes of your other feeds at this
            # publisher with this page's own words (issue 0137 A2).
            if feeds := self._offer(await self._prove(await self._site_listed(url), limit=None)
                                    or await self._prove(learned_feeds(url, self.known), limit=None, first=True)):
                return FeedFinding("found", feeds)

        around = _around(here, url)
        pages = await asyncio.gather(*(self._get(other, PAGE_BYTES) for other in around))
        if feeds := self._offer(await self._prove([link for got in pages if got for link in _feed_links(*got)])
                                or await self._directory()):
            return FeedFinding("found", feeds)

        # An address that cannot be read (a feed gone) takes its home page's links instead.
        origin = origin_from_source(here, "")
        home = dict(zip(around, pages)).get(f"{origin}/")
        if home and not self.elsewhere:
            self.elsewhere = tuple(_elsewhere_blogs(_links(home[0]), home[1]))
        linking = page or home
        if page and home:
            home_links = _links(home[0])
            self.home_pages = tuple(_blog_links(home_links, home[1]))
            self.home_menu = () if self.home_pages else tuple(_menu_links(home_links, home[1]))
        links = _links(linking[0]) if linking else _FeedLinks()
        blogs = _blog_links(links, linking[1]) if linking else []
        blog_pages = await asyncio.gather(*(self._get(blog, PAGE_BYTES) for blog in blogs))
        site = blog_site(host_of(here))
        self.pages = tuple(dict.fromkeys(got[1] for got in blog_pages if got and blog_site(host_of(got[1])) == site
                                         and got[1].rstrip("/") != here.rstrip("/")))
        if linking and not self.pages:
            self.menu = tuple(_menu_links(links, linking[1]))
        if feeds := self._offer(await self._prove([link for got in blog_pages if got for link in _feed_links(*got)])):
            return FeedFinding("found", feeds)

        # Common paths under the blogs the page links first (more specific), then at the root.
        bases = [*(blog.rstrip("/") for blog in blogs), origin]
        guesses = [base + path for base in dict.fromkeys(bases) for path in COMMON_PATHS]
        if feeds := self._offer(await self._prove(guesses, limit=None, first=True)):
            return FeedFinding("found", feeds[:1])
        return FeedFinding("none", pages=self.pages, menu=self.menu)

    async def _apple_podcast(self, url: str) -> Optional[FeedFinding]:
        """An Apple Podcasts show page: the public lookup's feedUrl for its id, proved (issue 0137 B3);
        None for any other address, or when the lookup gives no feed that is one."""
        found = APPLE_ID_RE.search(urllib.parse.urlparse(url).path)
        if host_of(url) not in APPLE_PODCAST_HOSTS or not found:
            return None
        got = await self._get(APPLE_LOOKUP.format(found.group(1)), FEED_BYTES)
        try:
            results = json.loads(got[0].decode("utf-8", errors="replace")).get("results") or [] if got else []
        except (ValueError, AttributeError):
            results = []
        feeds = [result["feedUrl"] for result in results if isinstance(result, dict) and isinstance(result.get("feedUrl"), str)]
        proved = await self._prove(feeds[:1])
        return FeedFinding("found", proved) if proved else None

    async def _directory(self) -> Tuple[Feed, ...]:
        """The feeds on the first feed directory met (a link saying RSS or feeds that is a page, issue 0137
        B3), known by their content: its feed links first, then its other links on the site. One is followed."""
        if self.followed_directory or not self.directories:
            return ()
        self.followed_directory = True
        got = await self._get(self.directories[0], PAGE_BYTES)
        if not got:
            return ()
        body, here = got
        links = _links(body)
        site = blog_site(host_of(here))
        others = [url for href in links.content if (url := _absolute(here, href)) and blog_site(host_of(url)) == site
                  and _says_feed(url, "")]
        logger.info("Feed finder: %s read as a feed directory", here)
        return (await self._prove([*_feed_links(body, here), *others], limit=MAX_DIRECTORY_FEEDS * 2))[:MAX_DIRECTORY_FEEDS]

    async def _site_listed(self, url: str) -> List[str]:
        """The feed addresses a site's robots.txt and sitemaps name (issue 0137 A2): robots' own feed-like
        addresses, then the feed-like <loc>s of its sitemaps (robots' Sitemap lines, else /sitemap.xml), a
        sitemap index's children that say feed or rss first, at most MAX_SITEMAPS read."""
        origin = origin_from_source(url, "")
        robots = await self._get(f"{origin}/robots.txt", FEED_BYTES)
        text = robots[0].decode("utf-8", errors="replace") if robots else ""
        sitemaps = SITEMAP_LINE_RE.findall(text) or [f"{origin}/sitemap.xml"]
        found = [address for address in URL_IN_TEXT_RE.findall(text) if _says_feed(address, "") and address not in sitemaps]
        read = 0
        while sitemaps and read < MAX_SITEMAPS:
            got = await self._get(sitemaps.pop(0), SITEMAP_BYTES)
            read += 1
            if not got:
                continue
            locs = LOC_RE.findall(got[0].decode("utf-8", errors="replace"))
            if b"<sitemapindex" in got[0][:4096].lower():
                sitemaps = sorted(locs, key=lambda loc: not _says_feed(loc, "")) + sitemaps
                continue
            found += [loc for loc in locs if _says_feed(loc, "")]
        same = publication_of(host_of(url))
        return [address for address in dict.fromkeys(found)
                if same_site(host_of(address), host_of(url)) or publication_of(host_of(address)) == same][:MAX_CANDIDATES]

    async def _get(self, url: str, max_bytes: int) -> Optional[Tuple[bytes, str]]:
        """(the start of the body, the final URL), or None when the request fails or is slow."""
        async with self.fan_out:
            self.requests += 1
            try:
                return await asyncio.wait_for(self.http.get_start(url, max_bytes), REQUEST_TIMEOUT_S)
            except Exception as exc:  # noqa: BLE001 - a failed candidate is just not a feed
                status = getattr(exc, "status", None)
                if status in BLOCKED_STATUSES:
                    self.blocked.add(url)
                if isinstance(status, int) and status >= 400:
                    self.statuses[url] = status
                logger.debug("Feed finder: %s failed (%s %s)", url, type(exc).__name__, status or "")
                return None

    async def _sniff(self, url: str) -> Optional[Tuple[str, Feed]]:
        """(the final URL, the feed) when url is a feed, else None. A page met on a link saying RSS or
        feeds is kept as a feed directory (issue 0137 B3)."""
        got = await self._get(url, FEED_BYTES)
        if got is None:
            return None
        start = _repaired(got[0])
        title = _feed_title(start)
        if title is None:
            if _says_feed(url, "") and b"<html" in got[0][:4096].lower():
                self.directories.append(got[1])
            return None
        feed = _feed(url, title, start, got[1], whole=got[0] if len(got[0]) < FEED_BYTES else None)
        if not feed.readable:
            self.refused = True
            return None
        return got[1], feed

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
        # A saved search after the site's own feeds (issue 0135); the order otherwise kept.
        return tuple(sorted(feeds.values(), key=lambda feed: feed.search))


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
    host = publication_of(host_of(url))
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


def _feed(url: str, title: str, start: bytes, final: str, whole: Optional[bytes] = None) -> Feed:
    """The feed at url (read from start, landed at final), with what it holds, whether INSIGHT
    reads its items and whether it is a saved search (issue 0135), and its newest item's date (0137);
    whole: the answer as it came, when it is all of the document."""
    items, titles, bodiless = _feed_entries(start, final)
    return Feed(url, title, items, titles, bodiless, readable=_readable(start),
                search=is_search_feed(title, final), newest=_newest_item(start), whole=whole or b"")


def _repaired(start: bytes) -> bytes:
    """The start of an answer with a feed's recoverable errors repaired (parsing.repaired_xml, issue 0137
    B4: a bare &, a stray control character), as the fetcher reads it; a page is left as it is."""
    head = start[:512].lstrip().lower()
    if not head.startswith(b"<?xml") and not head.startswith((b"<rss", b"<feed", b"<rdf")):
        return start
    return parsing.repaired_xml(start.decode("utf-8", errors="replace")).encode("utf-8")


def _is_feed_root(start: bytes) -> bool:
    """Whether start begins an RSS, Atom or RDF document (with or without items)."""
    parser = ET.XMLPullParser(events=("start",))
    try:
        for offset in range(0, len(start), PARSE_CHUNK):
            parser.feed(start[offset:offset + PARSE_CHUNK])
            for _, element in parser.read_events():
                return local_name(element.tag).lower() in FEED_ROOTS
    except ET.ParseError:
        return False
    return False


def _newest_item(start: bytes) -> Optional[datetime]:
    """The newest date of the items read in start (pubDate, published, updated, dc:date)."""
    parser = ET.XMLPullParser(events=("end",))
    newest: Optional[datetime] = None
    try:
        for offset in range(0, len(start), PARSE_CHUNK):
            parser.feed(start[offset:offset + PARSE_CHUNK])
            for _, element in parser.read_events():
                if local_name(element.tag).lower() in ("pubdate", "published", "updated", "date"):
                    when = parsing.parse_datetime_value((element.text or "").strip())
                    if when and (newest is None or when > newest):
                        newest = when
    except ET.ParseError:
        pass
    return newest


def _page_newest(body: bytes) -> Optional[datetime]:
    """The newest date a page shows for its articles (issue 0137 B2): its <time datetime> and JSON-LD
    datePublished values."""
    text = body.decode("utf-8", errors="replace")
    dates = [when for value in PAGE_TIME_RE.findall(text) + PAGE_PUBLISHED_RE.findall(text)
             if (when := parsing.parse_datetime_value(value))]
    return max(dates) if dates else None


def _article_links(links: "_FeedLinks", page_url: str) -> List[str]:
    """The page's own article links (issue 0137 B2): on its site, outside its menus, two or more path
    segments deep, the last a slug of three words or more ("/blog/why-rates-rose"), once each."""
    site = blog_site(host_of(page_url))
    found = []
    for href in links.content:
        url = _absolute(page_url, href)
        if not url or blog_site(host_of(url)) != site or url.rstrip("/") == page_url.rstrip("/"):
            continue
        segments = path_segments(url)
        last = segments[-1].lower().rsplit(".", 1)[0] if segments else ""
        if len(segments) >= 2 and parsing.SLUG_RE.match(last) and last.count("-") >= 2:
            found.append(url)
    return list(dict.fromkeys(found))


def _article_key(url: str) -> str:
    """An article's address compared by host and path: a feed's ?rss=yes or tracking query aside."""
    normalized = normalize_url(url) or url
    parsed = urllib.parse.urlparse(normalized)
    return f"{publication_of(parsed.hostname or '')}{parsed.path.rstrip('/')}"


def _says_feed(href: str, text: str) -> bool:
    """A link whose address or words say RSS or feeds (issue 0137 B3: a feed, or a page listing feeds)."""
    words = set("".join(ch if ch.isalnum() else " " for ch in text.lower()).split())
    try:
        parsed = urllib.parse.urlparse(href.lower())
    except ValueError:
        return False
    segments = {segment.rsplit(".", 1)[0] for segment in parsed.path.split("/")}
    return bool(words & DIRECTORY_WORDS or segments & (FEED_SEGMENTS | {"feeds"}) or _looks_like_feed(href, text))


def learned_feeds(page_url: str, known: Sequence[str]) -> List[str]:
    """Feed addresses in the shape of your other feeds at this page's publisher (issue 0137 A2), with
    this page's own path words in place of each of theirs that is no feed word: a stored
    /<code>/current.rss beside a page /<other-code>/home gives /<other-code>/current.rss; a stored
    ?jc=<code> gives ?jc=<other-code>. Learned from what you follow; no publisher is named. At most
    MAX_LEARNED, the stored addresses themselves left out."""
    site = publication_of(host_of(page_url))
    words = [segment for segment in path_segments(page_url)
             if segment.lower() not in GENERIC_SEGMENTS and segment.lower() not in FEED_WORDS and "." not in segment]
    found: List[str] = []
    for feed in known:
        if not words or publication_of(host_of(feed)) != site:
            continue
        parsed = urllib.parse.urlparse(feed)
        segments = [segment for segment in parsed.path.split("/") if segment]
        params = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        for word in words:
            for index, segment in enumerate(segments):
                if segment.lower() in FEED_WORDS or "." in segment or segment.lower() in GENERIC_SEGMENTS:
                    continue
                path = "/" + "/".join(segments[:index] + [word] + segments[index + 1:])
                found.append(urllib.parse.urlunparse(parsed._replace(path=path)))
            for index, (key, value) in enumerate(params):
                if not value or value.lower() in FEED_WORDS or not value.replace("-", "").replace("_", "").isalnum():
                    continue
                query = urllib.parse.urlencode(params[:index] + [(key, word)] + params[index + 1:])
                found.append(urllib.parse.urlunparse(parsed._replace(query=query)))
    return [url for url in dict.fromkeys(found) if url not in known][:MAX_LEARNED]


def _readable(start: bytes) -> bool:
    """Whether start holds an item where parse_feed_posts reads one (parsing.ITEM_PATHS), as far as
    it reads: a feed with items elsewhere (an RSS item outside its channel) would store nothing."""
    parser = ET.XMLPullParser(events=("start", "end"))
    path: List[str] = []
    seen_item = False
    try:
        for offset in range(0, len(start), PARSE_CHUNK):
            parser.feed(start[offset:offset + PARSE_CHUNK])
            for event, element in parser.read_events():
                name = local_name(element.tag).lower()
                if event == "start":
                    path.append(name)
                    if name in ("item", "entry"):
                        if item_path(path):
                            return True
                        seen_item = True
                elif path:
                    path.pop()
    except ET.ParseError:
        pass
    return not seen_item


def is_search_feed(title: str, url: str) -> bool:
    """A feed that reads as a saved search (issue 0135): its title says search or query ("Keyword
    search for query"), or its address searches (?q=, ?term=, /search/)."""
    words = set("".join(ch if ch.isalnum() else " " for ch in (title or "").lower()).split())
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError:
        return bool(words & SEARCH_WORDS)
    params = {key.lower() for key, value in urllib.parse.parse_qsl(parsed.query) if value}
    return bool(words & SEARCH_WORDS or params & SEARCH_PARAMS or "search" in path_segments(url.lower()))


def _feed_items(start: bytes, feed_url: str) -> Tuple[str, ...]:
    """The item addresses in start (_feed_entries)."""
    return _feed_entries(start, feed_url)[0]


def _feed_entries(start: bytes, feed_url: str) -> Tuple[Tuple[str, ...], Tuple[str, ...], bool]:
    """(the item addresses, the item titles, whether no item read carries a body) in start, as far
    as it reads, in feed order. An address is absolute, once each: an RSS item's <link> (else a
    permalink <guid>), an Atom entry's alternate <link href>. A title is the item's <title> text, its
    spaces single. A body is a description, summary or content with any text (issue 0108)."""
    parser = ET.XMLPullParser(events=("start", "end"))
    found: List[str] = []
    titles: List[str] = []
    depth = 0           # inside an item or entry
    link: Optional[str] = None
    titled = False      # an item's first title only (not a media:title after it)
    entries = bodies = 0
    body = False        # the item read so far has a body
    try:
        for offset in range(0, len(start), PARSE_CHUNK):
            parser.feed(start[offset:offset + PARSE_CHUNK])
            for event, element in parser.read_events():
                name = local_name(element.tag).lower()
                if depth and event == "end" and name in BODY_ELEMENTS and "".join(element.itertext()).strip():
                    body = True
                if name in ("item", "entry"):
                    if event == "start":
                        depth, link, titled, body = depth + 1, None, False, False
                    else:
                        depth -= 1
                        entries, bodies = entries + 1, bodies + body
                        if link and (url := _absolute(feed_url, link)):
                            found.append(url)
                elif depth and event == "end" and name == "title" and not titled:
                    titled = True
                    if text := " ".join("".join(element.itertext()).split()):
                        titles.append(text)
                elif depth and event == "end" and link is None:
                    if name == "link":
                        href = element.get("href")
                        value = (href if href is not None else element.text or "").strip()
                        if element.get("rel", "alternate") == "alternate" and value:
                            link = value
                    elif name == "guid" and element.get("isPermaLink", "true") != "false":
                        text = (element.text or "").strip()
                        link = text if text.startswith(("http://", "https://")) else None
    except ET.ParseError:
        pass
    return tuple(dict.fromkeys(found)), tuple(titles), entries > 0 and bodies == 0


def _feed_links(body: bytes, page_url: str) -> List[str]:
    """The page's feed candidates, absolute: <link rel="alternate"> feeds, then feed-like <a>."""
    links = _links(body)
    base = (_absolute(page_url, links.base) if links.base else None) or page_url
    absolute = (_absolute(base, href) for href in links.alternates + links.anchors)
    return list(dict.fromkeys(url for url in absolute if url))


def _links(body: bytes) -> "_FeedLinks":
    links = _FeedLinks()
    try:
        links.feed(body.decode("utf-8", errors="replace"))
        links.close()
    except Exception:  # noqa: BLE001 - keep what was read before the page broke the parser
        pass
    return links


def _on_blog_site(links: Iterable[str], page_url: str) -> List[str]:
    """The links, absolute, on the page's blog site (addresses.blog_site: a blog./news. subdomain
    included), less the page itself, once each, the shallowest first: /blog before /blog/tag/research."""
    site = blog_site(host_of(page_url))
    absolute = (_absolute(page_url, href) for href in links)
    same = (url for url in absolute if url and url.rstrip("/") != page_url.rstrip("/") and blog_site(host_of(url)) == site)
    return sorted(dict.fromkeys(same), key=lambda url: len(path_segments(url)))


def _blog_links(links: "_FeedLinks", page_url: str) -> List[str]:
    """The page's links to its own blog or newsroom (see BLOG_LINK_TEXTS), at most MAX_BLOG_LINKS."""
    return _on_blog_site(links.blogs, page_url)[:MAX_BLOG_LINKS]


def _menu_links(links: "_FeedLinks", page_url: str) -> List[str]:
    """The page's own menu links (MENU_TAGS), header and navigation before the footer, the
    shallowest first, at most MAX_MENU_LINKS: the pages that may be its blog under another word."""
    menu = [href for _, href in sorted(links.menu, key=lambda link: link[0])]
    # A link with a query is the page in another state (a sign-up form), not a page of its own.
    return [url for url in _on_blog_site(menu, page_url)
            if path_segments(url) and not urllib.parse.urlparse(url).query][:MAX_MENU_LINKS]


def _elsewhere_blogs(links: "_FeedLinks", page_url: str) -> List[str]:
    """The page's menu links named a blog (ELSEWHERE_BLOG_TEXTS) on another site, absolute, once
    each, at most MAX_BLOG_LINKS (issue 0108)."""
    site = blog_site(host_of(page_url))
    absolute = (_absolute(page_url, href) for href in links.named)
    other = (url for url in absolute if url and not same_site(host_of(url), host_of(page_url))
             and blog_site(host_of(url)) != site)
    return list(dict.fromkeys(other))[:MAX_BLOG_LINKS]


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
        self.menu: List[Tuple[int, str]] = []        # (0 header or navigation, 1 footer), href
        self.named: List[str] = []                   # menu links named a blog elsewhere (issue 0108)
        self.content: List[str] = []                 # links outside the menus (issue 0137: articles, directories)
        self._regions: List[str] = []                # the open MENU_TAGS
        # [href, text so far, its first piece of text]: a menu item's label comes before its
        # description ("Blog", then "Product updates, insights…").
        self._anchor: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs: Sequence[Tuple[str, Optional[str]]]) -> None:
        values = {name: value or "" for name, value in attrs}
        href = values.get("href", "")
        if tag == "base" and self.base is None and href:
            self.base = href
        elif (tag == "link" and href and "alternate" in values.get("rel", "").lower().split()
              and _is_feed_type(values.get("type", "")) and not _is_comments(href, values.get("title", ""))):
            self.alternates.append(href)
        elif tag in MENU_TAGS:
            self._regions.append(tag)
        elif tag == "a" and href:
            self._anchor = [href, "", "", "menu" if self._regions else ""]
            if self._regions:
                self.menu.append((int("footer" in self._regions), href))
            else:
                self.content.append(href)

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor[1] += data
            self._anchor[2] = self._anchor[2] or data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._regions:
            del self._regions[len(self._regions) - 1 - self._regions[::-1].index(tag):]
        if tag == "a" and self._anchor is not None:
            href, text, label, region = self._anchor
            self._anchor = None
            if region and " ".join(text.lower().split()) in ELSEWHERE_BLOG_TEXTS:
                self.named.append(href)
            if (_looks_like_feed(href, text) or _says_feed(href, text)) and not _is_comments(href, text):
                self.anchors.append(href)
            elif ({" ".join(text.lower().split()), " ".join(label.lower().split())} & BLOG_LINK_TEXTS
                  or host_of(href).startswith(BLOG_HOSTS)):
                self.blogs.append(href)


def _is_comments(href: str, label: str) -> bool:
    return "comment" in f"{href} {label}".lower()


__all__ = ["Feed", "FeedFinding", "find_feeds", "page_feeds"]
