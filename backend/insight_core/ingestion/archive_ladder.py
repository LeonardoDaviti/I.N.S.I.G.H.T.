"""The smart archiver (issue 0143): a feed's whole history, by the site's platform and a ladder of strategies.

A feed lists its latest posts (often 10 to 30). What else a site holds is found by its platform's known behaviour,
a class, never a site:

1. **The fingerprint** (`fingerprint`): the platform a feed and its site are built with, from what the archive reads
   anyway: the feed's generator, namespaces and item addresses, the home page's `<meta name=generator>`, its asset
   paths and `link rel` tags, and its response headers. One row of PLATFORMS per platform: adding one is a row and
   a fixture.
2. **The ladder** (STRATEGIES, in order): the feed's own paging (RFC 5005 `rel=next` / `prev-archive`, a
   platform's page parameter), the platform's archive API (WordPress REST, Blogger's JSON feed, the newsletter
   platform's archive on any domain), the sitemap read well (robots, indexes, the posts' file, gzip; issue 0108),
   the blog's listing pages (`rel=next`, `/page/N/`, read by the shape the feed's items have), and, opt-in per
   source (`settings.archive.web_archive`), the Web Archive's address index (CDX). Each is probed with a request
   or two (`Ladder.probe`): its outcome is recorded (`more:<n>`, `no_paging`, `paging_same`, `no_api`,
   `api_refused:<status>`, `no_sitemap`, `sitemap_no_posts`, `listing_unread`, `listing_no_posts`, `off`,
   `blocked`, ...) with the site's size it saw (`estimate`).
3. **Coverage** (`coverage_status`): "archived" only when the stored posts reach 95% of the largest trustworthy
   estimate, or every strategy was tried and none finds more; else "partial", with each strategy's reason.
4. **The learned order** (`ordered`): per platform, which strategy gave posts (system_settings `archive_learned`,
   counts); a new source of that platform tries the best one first. Never per site.

An archive runs the strategies that found more, in order (GenericRssKind.archive_pages); each skips the addresses
already seen or stored and stops once the seen addresses reach 95% of the estimate. A post found by address is read
as an archived post is (`_sitemap_post`: the page's body, title and date), a feed or API page's posts as the feed's
(teasers read in full by 0140's rules). Every request of a probe is counted (`requests`) and spaced PROBE_GAP_S.
"""
from __future__ import annotations

import html
import json
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import parsing
from insight_core.utils.addresses import host_of, publication_of, same_site
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.ingestion.archive_ladder")

LADDER_VERSION = 1
PROBE_GAP_S = 1.0             # between two requests of one probe (the archive's pages are gated as always)
COVERED_SHARE = 0.95          # stored >= this share of the estimate: archived
MAX_FEED_PAGES = 500          # a feed's paging, followed at most this deep
MAX_LISTING_PAGES = 500       # a listing's pages, followed at most this deep
MAX_LISTED = 20_000           # addresses one listing or index strategy keeps
LISTING_PROBES = 4            # listing addresses a probe reads at most
WP_PER_PAGE = 50
BLOGGER_PER_PAGE = 150
LEARNED_KEY = "archive_learned"   # system_settings: {platform: {strategy: posts}}
# v10.13.9: why an archive stopped or a strategy was refused (the checkpoint's "stopped", a probe's outcome)
FOREIGN_SITE = "foreign_site"     # the sitemap, listing or checkpoint names another site than the source's own
LOW_YIELD = "low_yield"           # LOW_YIELD_PAGES pages read, under LOW_YIELD_SHARE of them a post
OWNER_STOP = "stopped_by_owner"   # POST /api/archive/{id}/stop: the owner stopped it (never resumed by itself)
LOW_YIELD_PAGES = 1000
LOW_YIELD_SHARE = 0.05
MIN_PAGE_DELAY_S = 1.0            # a sitemap / listing / Web Archive crawl's least gap between two pages
CDX_URL = "https://web.archive.org/cdx/search/cdx"
WAYBACK_URL = "https://web.archive.org/web"

# Strategy names, in the ladder's default order.
FEED_PAGES = "feed_pages"
API = "api"
SITEMAP = "sitemap"
LISTING = "listing"
WEB_ARCHIVE = "web_archive"
STRATEGIES = (FEED_PAGES, API, SITEMAP, LISTING, WEB_ARCHIVE)
TRUSTWORTHY = (API, SITEMAP, LISTING, FEED_PAGES)   # the estimates coverage counts (CDX lists dead pages too)

# An address's last word that names a list or the site's own page, never a post: /blog/, /archive/, /about/.
# (As a folder, a section word is a post's: /blog/<slug>, /notes/2026/<slug>, /projects/<slug>.)
LIST_WORDS = frozenset({
    "blog", "blogs", "archive", "archives", "posts", "post", "articles", "notes", "writing", "writings", "essays",
    "news", "page", "pages", "tags", "categories", "topics", "authors", "about", "contact", "search", "subscribe",
    "feed", "feeds", "rss", "atom", "now", "projects", "home", "index", "login", "signin", "signup", "series",
    "newsletter", "privacy", "terms", "uses", "links", "cv", "resume", "p",
})
# A folder that holds lists or the site's machinery, never a post, wherever it is: /tag/<name>, /page/2.
TAXONOMY_WORDS = frozenset({
    "page", "tag", "tags", "category", "categories", "topic", "topics", "author", "authors", "label", "labels",
    "tagged", "search", "feed", "feeds", "rss", "atom", "wp-admin", "wp-login.php", "wp-content", "wp-includes",
    "wp-json", "cdn-cgi", "static", "assets", "images", "img", "media", "files", "series",
})
NUMBER_RE = re.compile(r"^\d+$")
NEXT_LINK_RE = re.compile(r"""(?is)<(?:a|link)\b[^>]*\brel\s*=\s*["'][^"']*\bnext\b[^"']*["'][^>]*>""")
HREF_RE = re.compile(r"""(?is)\bhref\s*=\s*["']([^"']+)["']""")
LINK_RE = re.compile(r"""(?is)<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""")
PAGE_NUMBER_RE = re.compile(r"(?i)(?:/page/(\d+)/?$|[?&](?:page|paged)=(\d+)$)")
META_GENERATOR_RE = re.compile(r"""(?is)<meta\b[^>]*\bname\s*=\s*["']generator["'][^>]*>""")
CONTENT_RE = re.compile(r"""(?is)\bcontent\s*=\s*["']([^"']*)["']""")
WP_API_LINK_RE = re.compile(r"""(?is)<link\b[^>]*\brel\s*=\s*["']https://api\.w\.org/["'][^>]*>""")
TOTAL_RESULTS_RE = re.compile(r"(?is)<(?:\w+:)?totalResults>\s*(\d+)\s*</(?:\w+:)?totalResults>")


# ---------------------------------------------------------------------------------------------- the fingerprint


@dataclass(frozen=True)
class Platform:
    """A platform's known behaviour (a class): how its feed pages, its archive API, its listing pages."""

    name: str
    generator: Tuple[str, ...] = ()       # words of a feed's or page's generator (lower case)
    hosts: Tuple[str, ...] = ()           # hosting suffixes ("wordpress.com": any.wordpress.com)
    page_marks: Tuple[str, ...] = ()      # asset paths, scripts and link rels on its pages (lower case)
    feed_marks: Tuple[str, ...] = ()      # what its feeds carry (namespaces, ids, item addresses; lower case)
    header_marks: Tuple[Tuple[str, str], ...] = ()   # (header, a word of its value)
    feed_paging: Optional[str] = None     # "paged" (?paged=N), "path" (<feed>N/), "page" (?page=N); RFC 5005 always
    api: Optional[str] = None             # "wordpress", "blogger", "newsletter"
    listings: Tuple[str, ...] = ()        # its listing pages, tried first


PLATFORMS: Tuple[Platform, ...] = (
    Platform("wordpress", generator=("wordpress",), hosts=("wordpress.com",),
             page_marks=("/wp-content/", "/wp-includes/", "https://api.w.org/"),
             feed_marks=("?p=", "xmlns:wfw", "wordpress.org/export"),
             header_marks=(("x-pingback", "xmlrpc"), ("link", "api.w.org")),
             feed_paging="paged", api="wordpress"),
    Platform("blogger", generator=("blogger",), hosts=("blogspot.com",),
             page_marks=("blogger.com/static", "www.blogger.com/feeds", "blogger.com/dyn-css"),
             feed_marks=("tag:blogger.com,", "blogger.com/feeds"), api="blogger"),
    Platform("ghost", generator=("ghost",), hosts=("ghost.io",),
             page_marks=("/ghost/api/", "content/images/", "ghost-portal", "ghost-sodo"),
             header_marks=(("x-ghost-cache-status", ""),), feed_paging="path", listings=("/page/2/",)),
    Platform("newsletter", generator=("substack",), hosts=("substack.com",),
             page_marks=("substackcdn.com", "substack.com/", "_preloads"),
             feed_marks=("substackcdn.com", "substack.com"), api="newsletter", listings=("/archive",)),
    Platform("bearblog", generator=("bear blog", "bearblog"), hosts=("bearblog.dev",),
             page_marks=("bearblog.dev", "bear ʕ•ᴥ•ʔ"), listings=("/blog/",)),
    Platform("hugo", generator=("hugo",), page_marks=("gohugo.io",), listings=("/posts/", "/blog/")),
    Platform("jekyll", generator=("jekyll",), page_marks=("jekyllrb.com", "jekyll-theme"),
             listings=("/blog/", "/posts/", "/archive/")),
    Platform("medium", generator=("medium",), hosts=("medium.com",), page_marks=("cdn-client.medium.com", "miro.medium.com"),
             feed_marks=("medium.com/p/", "cdn-images-1.medium.com", "?source=rss")),
    Platform("writeas", generator=("writefreely", "write.as"), hosts=("write.as",), page_marks=("writefreely", "write.as/"),
             feed_paging="page"),
    Platform("micro.blog", generator=("micro.blog",), hosts=("micro.blog",), page_marks=("micro.blog",),
             listings=("/archive/",)),
    Platform("tumblr", generator=("tumblr",), hosts=("tumblr.com",), page_marks=("assets.tumblr.com", "static.tumblr.com"),
             feed_paging="page", listings=("/page/2",)),
)
UNKNOWN = Platform("unknown")
BY_NAME = {platform.name: platform for platform in PLATFORMS}


def platform_named(name: Optional[str]) -> Platform:
    return BY_NAME.get(str(name or ""), UNKNOWN)


@dataclass(frozen=True)
class Fingerprint:
    platform: str
    evidence: Tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {"platform": self.platform, "evidence": list(self.evidence)}


def _generators(text: str) -> List[str]:
    """The generator a feed (<generator>, Atom's, its attribute) or a page (<meta name=generator>) names."""
    found = [html.unescape(m.group(1)).strip().lower()
             for m in re.finditer(r"(?is)<(?:\w+:)?generator\b[^>]*>(.*?)</(?:\w+:)?generator>", text or "")]
    found += [m.group(1).strip().lower() for m in re.finditer(r"""(?is)<generator\b[^>]*\buri\s*=\s*["']([^"']+)""", text or "")]
    for tag in META_GENERATOR_RE.findall(text or ""):
        content = CONTENT_RE.search(tag)
        if content:
            found.append(html.unescape(content.group(1)).strip().lower())
    return [value for value in found if value]


def fingerprint(feed_text: str, feed_url: str, *, items: Sequence[str] = (), home: Optional[str] = None,
                headers: Optional[Mapping[str, str]] = None) -> Fingerprint:
    """The platform the feed and its site are built with, and the evidence: the votes of every signal, the most
    votes winning (a generator weighs 3, a host 3, anything else 1); `unknown` with no signal."""
    votes: Dict[str, int] = {}
    evidence: Dict[str, List[str]] = {}

    def vote(platform: str, weight: int, why: str) -> None:
        votes[platform] = votes.get(platform, 0) + weight
        evidence.setdefault(platform, []).append(why)

    feed_lower = (feed_text or "").lower()
    home_lower = (home or "").lower()
    feed_generators, page_generators = _generators(feed_text), _generators(home or "")
    hosts = {host_of(url) for url in (feed_url, *items) if url}
    for platform in PLATFORMS:
        for word in platform.generator:
            if any(word in value for value in feed_generators):
                vote(platform.name, 3, f"feed generator: {word}")
            if any(word in value for value in page_generators):
                vote(platform.name, 3, f"page generator: {word}")
        for suffix in platform.hosts:
            if any(host == suffix or host.endswith("." + suffix) for host in hosts):
                vote(platform.name, 3, f"host: *.{suffix}")
        for mark in platform.feed_marks:
            if mark in feed_lower:
                vote(platform.name, 1, f"feed: {mark}")
        for mark in platform.page_marks:
            if mark in home_lower:
                vote(platform.name, 1, f"page: {mark}")
        for name, word in platform.header_marks:
            value = str((headers or {}).get(name, "")).lower()
            if value and word in value:
                vote(platform.name, 1, f"header: {name}")
    if not votes:
        return Fingerprint(UNKNOWN.name)
    best = max(votes, key=lambda name: (votes[name], -[p.name for p in PLATFORMS].index(name)))
    return Fingerprint(best, tuple(evidence[best]))


# ---------------------------------------------------------------------------------------------- the source's site


def channel_link(feed_text: str) -> Optional[str]:
    """The feed's own link to its site: RSS's channel <link>, Atom's feed-level rel=alternate link; None without one."""
    try:
        root = parsing.feed_root(feed_text or "")
    except Exception:  # noqa: BLE001 - no feed: no link
        return None
    atom = parsing.local_name(root.tag) == "feed"
    for node in root.iter():
        name = parsing.local_name(node.tag)
        if name in ("item", "entry"):
            break   # an item's link is the item's, never the feed's
        if name == "link" and node.text and node.text.strip().startswith("http"):
            return node.text.strip()
        if atom and name == "link" and node.attrib.get("rel") in (None, "", "alternate") \
                and node.attrib.get("href", "").startswith("http"):
            return node.attrib["href"]
    return None


def source_site(feed_url: str, feed_text: str = "", items: Sequence[str] = ()) -> str:
    """The site an archive reads (v10.13.9): the source's own publication, never the host its items link. The
    feed's items' host when it is the feed's own site (a feed at feeds.<site> of posts at <site>); else the feed's
    channel link when it is on the feed's site, or is a home page (a feed served by a feed host for its blog); else
    the feed's own host. A link blog whose items link a newspaper, or a feed of a code host's pages made elsewhere,
    archive their own site, never the one their items name."""
    own = parsing.origin_from_source(feed_url, "")
    feed_host = host_of(feed_url)
    for item in items:
        if isinstance(item, str) and item.startswith("http") and same_site(host_of(item), feed_host):
            return parsing.origin_from_source(item, own)
    link = channel_link(feed_text)
    if link and host_of(link):
        if same_site(host_of(link), feed_host) or (urllib.parse.urlparse(link).path or "/") == "/":
            return parsing.origin_from_source(link, own)
    return own


def own_site(url: Optional[str], site: str, feed_url: str = "") -> bool:
    """Whether an address is on the source's own site: the archive's site (source_site) or the feed's."""
    host = host_of(url)
    return bool(host) and (same_site(host, host_of(site)) or same_site(host, host_of(feed_url)))


# ---------------------------------------------------------------------------------------------- post shapes


def _segments(url: str) -> List[str]:
    return parsing.path_segments(url)


@dataclass(frozen=True)
class PostShape:
    """The addresses a feed's items have: their publication, section, depths, and per position a literal they
    all share or "#" (a number: a date's folders). A listed link of that shape is a post."""

    publication: str
    prefix: str
    depths: Tuple[int, ...]
    positions: Tuple[Tuple[int, str], ...]   # (position, literal or "#") every item agrees on

    def matches(self, url: str) -> bool:
        if not url or publication_of(host_of(url)) != self.publication:
            return False
        path = urllib.parse.urlparse(url).path or "/"
        parts = _segments(url)
        if not path.startswith(self.prefix) or not parts or (path.rstrip("/") + "/") == self.prefix:
            return False
        if len(parts) not in self.depths:
            return False
        literals = {position for position, value in self.positions if value != "#"}
        for position, value in self.positions:
            if position >= len(parts):
                continue
            if value == "#" and not NUMBER_RE.match(parts[position]):
                return False
            if value != "#" and parts[position] != value:
                return False
        # A list's word is no post, unless every feed item has it there (a /blog/<slug> site).
        if parts[-1].lower() in LIST_WORDS and len(parts) - 1 not in literals:
            return False
        return not any(part.lower() in TAXONOMY_WORDS and index not in literals for index, part in enumerate(parts))


def post_shape(links: Sequence[str]) -> Optional[PostShape]:
    """The shape of a feed's items' addresses (None without one): per position before the last, the literal every
    item has there, or "#" where each has a number (a date's folders)."""
    links = [link for link in links if isinstance(link, str) and link.startswith("http")]
    split = [parts for link in links if (parts := _segments(link))]
    if not split:
        return None
    from insight_core.ingestion.kinds.generic_rss import feed_section

    depths = tuple(sorted({len(parts) for parts in split}))
    positions: List[Tuple[int, str]] = []
    for position in range(min(depths) - 1):
        values = {parts[position] for parts in split}
        if all(NUMBER_RE.match(value) for value in values):
            positions.append((position, "#"))
        elif len(values) == 1:
            positions.append((position, next(iter(values))))
    return PostShape(publication_of(host_of(links[0])), feed_section(links), depths, tuple(positions))


def clean(url: str, base: Optional[str] = None) -> Optional[str]:
    """An absolute http(s) address without its fragment; None for anything else."""
    try:
        absolute = urllib.parse.urldefrag(urllib.parse.urljoin(base or url, html.unescape(url.strip())))[0]
        parsed = urllib.parse.urlparse(absolute)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return absolute


def page_links(page: str, base: str) -> List[str]:
    return [url for href in LINK_RE.findall(page or "") if (url := clean(href, base))]


def next_page(page: str, base: str, number: int) -> Optional[str]:
    """A listing's next page: its rel=next, else a link to page number+1 (/page/N/, ?page=N, ?paged=N)."""
    for tag in NEXT_LINK_RE.findall(page or ""):
        href = HREF_RE.search(tag)
        if href and (url := clean(href.group(1), base)) and url != base:
            return url
    for url in page_links(page, base):
        match = PAGE_NUMBER_RE.search(urllib.parse.urlparse(url).path + ("?" + urllib.parse.urlparse(url).query
                                                                          if urllib.parse.urlparse(url).query else ""))
        if match and int(match.group(1) or match.group(2)) == number + 1 and publication_of(host_of(url)) == publication_of(host_of(base)):
            return url
    return None


def last_page_number(page: str, base: str) -> Optional[int]:
    """The highest page number a listing links (its pagination's last page), or None."""
    numbers = []
    for url in page_links(page, base):
        parsed = urllib.parse.urlparse(url)
        match = PAGE_NUMBER_RE.search(parsed.path + (f"?{parsed.query}" if parsed.query else ""))
        if match and publication_of(host_of(url)) == publication_of(host_of(base)):
            numbers.append(int(match.group(1) or match.group(2)))
    return max(numbers) if numbers else None


def with_query(url: str, **params: Any) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items()})
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))


def feed_next(feed_text: str, feed_url: str) -> Optional[str]:
    """RFC 5005: the feed's `rel="next"` (paged) or `rel="prev-archive"` (archived) link, else None."""
    try:
        root = parsing.feed_root(feed_text)
    except Exception:  # noqa: BLE001
        return None
    for node in root.iter():
        if parsing.local_name(node.tag) == "link" and node.attrib.get("rel") in ("next", "prev-archive"):
            href = node.attrib.get("href")
            if href and (url := clean(href, feed_url)) and url != feed_url:
                return url
    return None


def total_results(feed_text: str) -> Optional[int]:
    """OpenSearch's totalResults a feed carries (Blogger's), or None."""
    match = TOTAL_RESULTS_RE.search(feed_text or "")
    return int(match.group(1)) if match else None


def feed_paged_url(feed_url: str, platform: Platform, number: int) -> Optional[str]:
    """The feed's page `number` (2, 3, ...) by the platform's paging, or None."""
    if platform.feed_paging == "paged":
        return with_query(feed_url, paged=number)
    if platform.feed_paging == "page":
        return with_query(feed_url, page=number)
    if platform.feed_paging == "path":
        parsed = urllib.parse.urlparse(feed_url)
        path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
        return urllib.parse.urlunparse(parsed._replace(path=f"{path}{number}/"))
    return None


# ---------------------------------------------------------------------------------------------- coverage


def best_estimate(estimates: Mapping[str, Any]) -> Optional[int]:
    """The largest trustworthy estimate of the site's posts (an API's total, the sitemap's count, a listing's, the
    feed's paging depth), or None."""
    values = [int(value) for name, value in (estimates or {}).items()
              if name in TRUSTWORTHY and isinstance(value, int) and not isinstance(value, bool) and value > 0]
    return max(values) if values else None


def coverage_status(stored: int, smart: Mapping[str, Any]) -> str:
    """not_archived / archived / partial (issue 0143): archived when the stored posts reach COVERED_SHARE of the
    estimate, or every strategy was tried and none finds more; else partial."""
    if stored <= 0:
        return "not_archived"
    estimate = smart.get("estimate")
    if isinstance(estimate, int) and not isinstance(estimate, bool) and estimate > 0 and stored >= COVERED_SHARE * estimate:
        return "archived"
    if smart.get("exhausted") or (smart.get("tried_all") and not smart.get("found_more")):
        return "archived"
    return "partial"


def reasons(smart: Mapping[str, Any]) -> Dict[str, str]:
    """Each strategy's outcome but the ones that found more: why the rest is not stored."""
    return {name: outcome for name, outcome in (smart.get("outcomes") or {}).items()
            if not str(outcome).startswith("more")}


# ---------------------------------------------------------------------------------------------- the learned order


def ordered(platform: str, learned: Optional[Mapping[str, Any]], *, web_archive: bool = False) -> List[str]:
    """The ladder's order for a platform: the strategies that gave its sources the most posts first (learned),
    then the rest in the default order; the Web Archive only when the source opted in, and always last."""
    wins = (learned or {}).get(platform) if isinstance(learned, Mapping) else None
    wins = wins if isinstance(wins, Mapping) else {}
    base = [name for name in STRATEGIES if name != WEB_ARCHIVE]
    first = sorted((name for name in base if int(wins.get(name) or 0) > 0), key=lambda name: -int(wins.get(name) or 0))
    order = first + [name for name in base if name not in first]
    return order + ([WEB_ARCHIVE] if web_archive else [])


def learned_after(learned: Optional[Mapping[str, Any]], platform: str, strategy: str, posts: int) -> Dict[str, Any]:
    """The learned counts with a strategy's posts added for a platform."""
    out = {name: dict(value) for name, value in (learned or {}).items() if isinstance(value, Mapping)}
    out.setdefault(platform, {})
    out[platform][strategy] = int(out[platform].get(strategy) or 0) + int(posts)
    return out


# ---------------------------------------------------------------------------------------------- probes


@dataclass
class Probe:
    """One strategy's look: its outcome, the site's size it saw (estimate, None when it can't say), the new
    addresses it found (beyond the feed), and its state to start from."""

    outcome: str
    estimate: Optional[int] = None
    new: int = 0
    state: Dict[str, Any] = field(default_factory=dict)

    @property
    def more(self) -> bool:
        return self.new > 0


@dataclass
class LadderResult:
    platform: Fingerprint
    order: List[str]
    probes: Dict[str, Probe]
    requests: int
    feed_posts: int

    @property
    def found(self) -> List[str]:
        return [name for name in self.order if name in self.probes and self.probes[name].more]

    @property
    def estimate(self) -> Optional[int]:
        return best_estimate({name: probe.estimate for name, probe in self.probes.items()})

    def smart(self) -> Dict[str, Any]:
        """What settings.archive.smart keeps (the plan's record)."""
        found = self.found
        return {
            "version": LADDER_VERSION,
            "platform": self.platform.platform,
            "evidence": list(self.platform.evidence),
            "order": self.order,
            "strategy": found[0] if found else None,
            "outcomes": {name: probe.outcome for name, probe in self.probes.items()},
            "estimates": {name: probe.estimate for name, probe in self.probes.items() if probe.estimate is not None},
            "estimate": max(filter(None, [self.estimate, self.feed_posts])) if (self.estimate or self.feed_posts) else None,
            "found_more": bool(found),
            "tried_all": all(name in self.probes for name in self.order),
            "exhausted": False,
            "requests": self.requests,
        }


class CountingHttp:
    """A KindHttp that counts its requests (a ladder's cost), everything else as the http it wraps."""

    def __init__(self, http: Any) -> None:
        self.inner = http
        self.count = 0

    async def get_text(self, url: str, **kwargs: Any) -> Tuple[str, Dict[str, str]]:
        self.count += 1
        return await self.inner.get_text(url, **kwargs)

    async def get_start(self, url: str, max_bytes: int) -> Tuple[bytes, str]:
        self.count += 1
        return await self.inner.get_start(url, max_bytes)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


class Ladder:
    """The probes of one source (see the module docstring). `kind` is the GenericRssKind (its http, its sitemap
    reader); `feed` the feed's posts as parsed; `feed_text` and `headers` the feed's answer."""

    def __init__(self, kind: Any, source: Mapping[str, Any], feed: Sequence[Dict[str, Any]], feed_text: str,
                 headers: Optional[Mapping[str, str]] = None, *, learned: Optional[Mapping[str, Any]] = None,
                 site: Optional[str] = None) -> None:
        self.kind = kind
        self.http = CountingHttp(kind.http)
        self.source = source
        self.feed_url = str(source.get("handle_or_url") or "")
        self.feed = list(feed)
        self.feed_text = feed_text or ""
        self.headers = dict(headers or {})
        self.links = [p["url"] for p in feed if isinstance(p.get("url"), str) and p["url"].startswith("http")]
        self.held = {normalize_url(link) for link in self.links} - {None}
        # v10.13.9: the source's own site, never the first item's host (a link blog's items link other sites)
        self.site = site or source_site(self.feed_url, self.feed_text, self.links)
        self.own_links = [link for link in self.links if same_site(host_of(link), host_of(self.site))]
        self.shape = post_shape(self.own_links)
        self.learned = learned
        self._home: Optional[Tuple[str, Dict[str, str]]] = None
        self._home_read = False

    # ------------------------------------------------------------------ requests

    @property
    def requests(self) -> int:
        return self.http.count

    async def get(self, url: str) -> Tuple[str, Dict[str, str]]:
        if self.http.count:
            await self.http.sleep(PROBE_GAP_S)
        return await self.http.get_text(url)

    async def home(self) -> Optional[str]:
        """The site's home page (once), None when it cannot be read."""
        if not self._home_read:
            self._home_read = True
            try:
                self._home = await self.get(self.site + "/")
            except Exception as exc:  # noqa: BLE001 - a home page that fails is no evidence
                logger.debug("Archive ladder: %s/ not read (%s)", self.site, exc)
        return self._home[0] if self._home else None

    def new_addresses(self, urls: Iterable[str]) -> List[str]:
        out, seen = [], set(self.held)
        for url in urls:
            key = normalize_url(url)
            if key and key not in seen:
                seen.add(key)
                out.append(url)
        return out

    # ------------------------------------------------------------------ the ladder

    async def fingerprint(self) -> Fingerprint:
        found = fingerprint(self.feed_text, self.feed_url, items=self.links, headers=self.headers)
        if found.platform == UNKNOWN.name or len(found.evidence) < 2:
            page = await self.home()
            home_headers = self._home[1] if self._home else {}
            found = fingerprint(self.feed_text, self.feed_url, items=self.links, home=page,
                                headers={**self.headers, **home_headers})
        return found

    async def run(self) -> LadderResult:
        """Fingerprint, then probe every strategy of the ladder (a request or two each)."""
        printed = await self.fingerprint()
        settings = self.source.get("settings") or {}
        web_archive = bool((settings.get("archive") or {}).get("web_archive")) if isinstance(settings, Mapping) else False
        order = ordered(printed.platform, self.learned, web_archive=web_archive)
        platform = platform_named(printed.platform)
        probes: Dict[str, Probe] = {}
        for name in order:
            try:
                probes[name] = await getattr(self, f"probe_{name}")(platform)
            except HttpError as exc:
                if exc.limiting:
                    raise
                probes[name] = Probe(f"blocked:{exc.status}" if exc.status in (401, 403, 429) else f"error:{exc.status or 'network'}")
            except Exception as exc:  # noqa: BLE001 - one strategy failing is its outcome, never the archive's
                logger.info("Archive ladder: %s of %s failed (%s)", name, self.feed_url, exc)
                probes[name] = Probe(f"error:{type(exc).__name__}")
        return LadderResult(printed, order, probes, self.requests, len(self.feed))

    # ------------------------------------------------------------------ 1. the feed's own paging

    async def probe_feed_pages(self, platform: Platform) -> Probe:
        estimate = total_results(self.feed_text)
        url = feed_next(self.feed_text, self.feed_url) or feed_paged_url(self.feed_url, platform, 2)
        if url is None:
            return Probe("no_paging", estimate)
        try:
            text, _ = await self.get(url)
            posts = parsing.parse_feed_posts(text, self.feed_url)
        except HttpError as exc:
            if exc.limiting:
                raise
            return Probe(f"paging_refused:{exc.status or 'network'}", estimate)
        except Exception:  # noqa: BLE001 - a page that is no feed
            return Probe("paging_unread", estimate)
        new = self.new_addresses(p["url"] for p in posts if isinstance(p.get("url"), str))
        if not new:
            return Probe("paging_same", estimate)
        return Probe(f"more:{len(new)}", estimate, len(new), {"next": url, "page": 2, "rfc5005": url == feed_next(self.feed_text, self.feed_url)})

    # ------------------------------------------------------------------ 2. the platform's archive API

    async def probe_api(self, platform: Platform) -> Probe:
        if platform.api is None:
            return Probe("no_api")
        return await getattr(self, f"_api_{platform.api.replace('-', '_')}")()

    async def wordpress_root(self) -> str:
        page = await self.home() or ""
        tag = WP_API_LINK_RE.search(page)
        href = HREF_RE.search(tag.group(0)) if tag else None
        return (clean(href.group(1), self.site + "/") if href else None) or f"{self.site}/wp-json/"

    @staticmethod
    def wordpress_url(root: str, page: int) -> str:
        query = urllib.parse.urlencode({"per_page": WP_PER_PAGE, "page": page, "orderby": "date", "order": "desc"})
        if "rest_route=" in root:
            return f"{root.rstrip('/')}/wp/v2/posts&{query}"
        return f"{root.rstrip('/')}/wp/v2/posts?{query}"

    async def _api_wordpress(self) -> Probe:
        root = await self.wordpress_root()
        try:
            text, headers = await self.get(self.wordpress_url(root, 1))
            data = json.loads(text)
        except HttpError as exc:
            if exc.limiting:
                raise
            return Probe(f"api_refused:{exc.status or 'network'}")
        except ValueError:
            return Probe("api_refused:not_json")
        if not isinstance(data, list):
            return Probe("api_refused:not_a_list")
        total = _int(headers.get("x-wp-total"))
        new = self.new_addresses(item.get("link") for item in data if isinstance(item, dict) and isinstance(item.get("link"), str))
        more = len(new) or max(0, (total or 0) - len(self.feed))
        if not more:
            return Probe("api_no_more", total)
        return Probe(f"more:{more}", total, more, {"api": "wordpress", "root": root, "page": 1})

    @staticmethod
    def blogger_url(site: str, start: int) -> str:
        return f"{site}/feeds/posts/default?" + urllib.parse.urlencode(
            {"alt": "json", "start-index": start, "max-results": BLOGGER_PER_PAGE})

    async def _api_blogger(self) -> Probe:
        try:
            text, _ = await self.get(self.blogger_url(self.site, 1))
            data = json.loads(text)
        except HttpError as exc:
            if exc.limiting:
                raise
            return Probe(f"api_refused:{exc.status or 'network'}")
        except ValueError:
            return Probe("api_refused:not_json")
        feed = data.get("feed") if isinstance(data, dict) else None
        if not isinstance(feed, dict):
            return Probe("api_refused:no_feed")
        total = _int(((feed.get("openSearch$totalResults") or {}).get("$t")))
        new = self.new_addresses(link for entry in feed.get("entry") or [] if (link := blogger_link(entry)))
        more = len(new) or max(0, (total or 0) - len(self.feed))
        if not more:
            return Probe("api_no_more", total)
        return Probe(f"more:{more}", total, more, {"api": "blogger", "start": 1})

    async def _api_newsletter(self) -> Probe:
        from insight_core.ingestion.kinds.substack import ARCHIVE_PAGE_SIZE

        url = f"{self.site}/api/v1/archive?" + urllib.parse.urlencode({"sort": "new", "limit": ARCHIVE_PAGE_SIZE})
        try:
            text, _ = await self.get(url)
            data = json.loads(text)
        except HttpError as exc:
            if exc.limiting:
                raise
            return Probe(f"api_refused:{exc.status or 'network'}")
        except ValueError:
            return Probe("api_refused:not_json")
        if not isinstance(data, list):
            return Probe("api_refused:not_a_list")
        links = [item.get("canonical_url") or f"{self.site}/p/{item.get('slug')}" for item in data
                 if isinstance(item, dict) and item.get("slug")]
        new = self.new_addresses(links)
        # A full first page says there are more pages; the API gives no total.
        more = len(new) + (1 if len(data) >= ARCHIVE_PAGE_SIZE else 0)
        if not more:
            return Probe("api_no_more")
        return Probe(f"more:{len(new)}{'+' if len(data) >= ARCHIVE_PAGE_SIZE else ''}", None, more,
                     {"api": "newsletter", "inner": None})

    # ------------------------------------------------------------------ 3. the sitemap

    async def probe_sitemap(self, platform: Platform) -> Probe:
        if self.http.count:
            await self.http.sleep(PROBE_GAP_S)
        site, prefix, listed, entries, refused = await self.kind._sitemap_read(self.feed, site=self.site, http=self.http)
        if refused:
            return Probe(refused)
        if not entries:
            return Probe("no_sitemap")
        new = self.new_addresses(loc for loc, _ in listed)
        if not new:
            return Probe("sitemap_no_posts", len(listed) or None)
        return Probe(f"more:{len(new)}", len(listed), len(new), {"site": site, "prefix": prefix, "_listed": listed})

    # ------------------------------------------------------------------ 4. listing pages

    def listing_candidates(self, platform: Platform) -> List[str]:
        channel = channel_link(self.feed_text)
        prefix = self.shape.prefix if self.shape else "/"
        paths = [*platform.listings, *([prefix] if prefix != "/" else []), "/blog/", "/archive/", "/posts/"]
        found = [clean(path, self.site + "/") for path in paths if not path.startswith("/page/")]
        if channel and publication_of(host_of(channel)) == publication_of(host_of(self.site)):
            found.insert(len(platform.listings), channel)
        found.append(self.site + "/")
        return list(dict.fromkeys(url for url in found if url))

    def listed_posts(self, page: str, base: str) -> List[str]:
        if self.shape is None:
            return []
        listed = clean(base) or base
        return list(dict.fromkeys(url for url in page_links(page, base)
                                  if url.rstrip("/") != listed.rstrip("/") and self.shape.matches(url)))

    async def probe_listing(self, platform: Platform) -> Probe:
        if self.shape is None:
            return Probe("listing_no_shape")
        read_any = False
        for url in self.listing_candidates(platform)[:LISTING_PROBES + len(platform.listings)]:
            if url.rstrip("/") == self.site and self._home is not None:
                page = self._home[0]
            else:
                try:
                    page, _ = await self.get(url)
                except HttpError as exc:
                    if exc.limiting:
                        raise
                    continue
                except Exception:  # noqa: BLE001
                    continue
            read_any = True
            posts = self.listed_posts(page, url)
            new = self.new_addresses(posts)
            if not new:
                continue
            following = next_page(page, url, 1)
            last = last_page_number(page, url)
            estimate = (len(posts) * last if last and following else None) if following else len(posts)
            probe = Probe(f"more:{len(new)}{'+' if following else ''}", estimate, len(new) + (1 if following else 0),
                          {"listing": url})
            return probe   # the first listing holding more (a one-page one: the whole blog)
        return Probe("listing_no_posts" if read_any else "listing_unread")

    # ------------------------------------------------------------------ 5. the Web Archive's index (opt-in)

    def cdx_url(self) -> str:
        prefix = self.shape.prefix if self.shape else "/"
        return CDX_URL + "?" + urllib.parse.urlencode({
            "url": f"{host_of(self.site)}{prefix}*", "output": "json", "fl": "original,timestamp",
            "filter": "statuscode:200", "collapse": "urlkey", "limit": MAX_LISTED})

    async def cdx_entries(self) -> List[Tuple[str, str]]:
        text, _ = await self.get(self.cdx_url())
        rows = json.loads(text)
        out: Dict[str, Tuple[str, str]] = {}
        for row in rows[1:] if isinstance(rows, list) else []:
            if isinstance(row, list) and len(row) >= 2 and isinstance(row[0], str):
                url = clean(row[0])
                if url and url.startswith("http://"):
                    url = "https://" + url[len("http://"):]
                key = normalize_url(url) if url else None
                if url and key and self.shape and self.shape.matches(url):
                    out.setdefault(key, (url, str(row[1])))
        return sorted(out.values(), key=lambda entry: entry[1], reverse=True)

    async def probe_web_archive(self, platform: Platform) -> Probe:
        if self.shape is None:
            return Probe("listing_no_shape")
        try:
            entries = await self.cdx_entries()
        except HttpError as exc:
            if exc.limiting:
                raise
            return Probe(f"api_refused:{exc.status or 'network'}")
        except ValueError:
            return Probe("api_refused:not_json")
        new = self.new_addresses(url for url, _ in entries)
        if not new:
            return Probe("web_archive_no_posts")
        return Probe(f"more:{len(new)}", None, len(new), {})


# ---------------------------------------------------------------------------------------------- API posts


def _int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def blogger_link(entry: Any) -> Optional[str]:
    if not isinstance(entry, dict):
        return None
    for link in entry.get("link") or []:
        if isinstance(link, dict) and link.get("rel") == "alternate" and isinstance(link.get("href"), str):
            return link["href"]
    return None


def _rendered(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("rendered") if "rendered" in value else value.get("$t")
    return str(value or "")


def wordpress_post(item: Mapping[str, Any], source_url: str) -> Optional[Dict[str, Any]]:
    """A post of WordPress's REST API (/wp/v2/posts) as the feed's parser shapes one."""
    link = item.get("link")
    if not isinstance(link, str) or not link.startswith("http"):
        return None
    content_html = _rendered(item.get("content")) or _rendered(item.get("excerpt"))
    when = item.get("date_gmt") or item.get("date")
    date = parsing.parse_datetime_value(f"{when}Z" if isinstance(when, str) and item.get("date_gmt") and not when.endswith("Z") else when)
    return _post(source_url, link, str(item.get("id") or link), html.unescape(parsing.strip_html(_rendered(item.get("title")))),
                 content_html, date, protected=bool((item.get("content") or {}).get("protected")) if isinstance(item.get("content"), dict) else False)


def blogger_post(entry: Mapping[str, Any], source_url: str) -> Optional[Dict[str, Any]]:
    """An entry of Blogger's JSON feed as the feed's parser shapes one."""
    link = blogger_link(entry)
    if not link:
        return None
    content_html = _rendered(entry.get("content")) or _rendered(entry.get("summary"))
    return _post(source_url, link, _rendered(entry.get("id")) or link, _rendered(entry.get("title")), content_html,
                 parsing.parse_datetime_value(_rendered(entry.get("published"))))


def _post(source_url: str, url: str, guid: str, title: str, content_html: str, date: Optional[datetime], *,
          protected: bool = False) -> Dict[str, Any]:
    from insight_core.db.repo_posts import BACKLOG_KEY
    from insight_core.utils.originals_rules import address_hint

    content_html = parsing.normalize_feed_urls(content_html)
    return {
        "platform": "rss",
        "source": source_url,
        "url": url,
        "guid": guid,
        "title": title,
        "content": parsing.strip_html(content_html),
        "content_html": content_html,
        # v10.13.9: no date stays undated (never the fetch's "now"): a backlog post, the saver sorts it before the
        # source's oldest; the address's day, else its month's 1st (originals_rules.address_hint), is its sort hint
        "date": date or address_hint(url),
        "media_urls": parsing.extract_html_image_urls(content_html),
        "categories": [],
        "metadata": {"archive_strategy": API, **({"protected": True} if protected else {})},
        BACKLOG_KEY: True,
    }
