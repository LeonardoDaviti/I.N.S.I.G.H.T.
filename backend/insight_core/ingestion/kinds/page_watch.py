"""page_watch: a page without a feed, followed through its links and the site's sitemap.

Selected by settings.page_watch = {"prefix": "/news/"} on an rss source whose handle_or_url is the listing page.
The prefix defaults to the listing page's path (for a home page, the most common first segment of its deeper links;
a listing with fewer than SECTION_MIN articles under its own path follows its article links' section). Articles are
the listing's same-host links under the prefix (page order) plus the sitemap's URLs under it; a live fetch reads
the unstored ones, conditionally (304 everywhere: no posts), an archive reads them all one page per archive page.
An article is read with the full-text reader and dated by `page_dating`, else the sitemap's lastmod; a page with no
article body, or with neither a date nor og:type article, is no post. Sitemap-only posts are backlog
(repo_posts.BACKLOG_KEY), never "new to you". Entry points: the kind, `preview`, `offers` and `list_offers` (a site
with no feed tried on its news / press / blog list pages).
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
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from insight_core.adapters.base_adapter import BaseSourceAdapter
from insight_core.db.repo_posts import BACKLOG_KEY, PAGE_READ_KEY
from insight_core.ingestion.http import AddressMemory, Conditional, HttpError, KindHttp
from insight_core.ingestion.kinds import parsing, paywall
from insight_core.ingestion.kinds.base import UNREADABLE, FetchedPosts, Inspection, RateLimit, Source
from insight_core.ingestion.kinds.generic_rss import StoredUrls
from insight_core.utils.addresses import host_of, publication_of
from insight_core.utils.json_safe import iso
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.ingestion.page_watch")

MAX_SITEMAPS = 5          # sitemap files read per discovery (robots' ones, an index's children)
# An archive reads the site's whole sitemap: an index may have more children than a live fetch reads.
ARCHIVE_SITEMAPS = 60
SITEMAP_MAX_BYTES = 5_000_000   # a sitemap is read up to this; a longer one keeps its first entries
# The posts' sitemap files blog platforms write, read by an archive when robots.txt and /sitemap.xml give none.
POST_SITEMAPS = ("sitemap_index.xml", "post-sitemap.xml", "sitemap-posts.xml", "wp-sitemap.xml", "sitemap.xml.gz")
SKIP_READS = 10           # pages a live fetch may read that are no post or fail, besides its posts
FAILED_RETRY_S = 24 * 3600   # a page that failed is read again after this; one that is no post, never
PREVIEW_ITEMS = 5
PREVIEW_READS = 8         # the first candidates a preview reads, to show PREVIEW_ITEMS posts
PREVIEW_FAN_OUT = 4
OFFER_BUDGET_S = 15.0     # the previews of a site's blog or news pages, run at once
# A menu link is offered as an article list when its preview read this many posts dated this recently.
MENU_POSTS = 3
MENU_RECENT = timedelta(days=365)

# The pages skipped by a live fetch (no post, or failed): url -> the time.monotonic() to read it again.
# Module-level so it lasts the process, not one run's registry.
SKIPPED: Dict[str, float] = {}

LINK_RE = re.compile(r"""(?is)<a\b[^>]*?\bhref\s*=\s*["']([^"']+)["']""")
JSON_LD_DATE_RE = re.compile(r'"datePublished"\s*:\s*"([^"]+)"')
# An element's data-published attribute (Distill-style posts: <div data-published="April 23, 2025">), markup too.
DATA_PUBLISHED_RE = re.compile(r"""(?is)<[a-z][^>]*?\bdata-published\s*=\s*["']([^"']+)["']""")
TIME_RE = re.compile(r"""(?is)<time\b[^>]*?\bdatetime\s*=\s*["']([^"']+)["']""")
TITLE_RE = re.compile(r"(?is)<title\b[^>]*>(.*?)</title>")
H1_RE = re.compile(r"(?is)<h1\b[^>]*>(.*?)</h1>")
SITE_SUFFIX_RE = re.compile(r"\s+[|\\·–—-]\s+([^|\\·–—-]{1,40})$")    # "Title \ Anthropic"
META_DATES = ("date", "dc.date", "pubdate")       # <meta name> dates, after the two above
# The scholarly <meta name> dates papers carry, read after the dates above and before a written date; the first
# publication first, so a later version never moves a paper's date.
SCHOLARLY_DATES = ("citation_publication_date", "citation_date", "dc.date.issued", "dcterms.issued",
                   "dc.date.created", "dcterms.created", "prism.publicationdate", "citation_cover_date",
                   "citation_online_date")
# The forms they are written in, each a whole day (UTC). A year or a month alone is no date (it would read as
# precise), so the next tag is used.
SCHOLARLY_YMD_RE = re.compile(r"^(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})$")
SCHOLARLY_Y_MON_D_RE = re.compile(r"^(\d{4})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})$")
SCHOLARLY_D_MON_Y_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})$")
SCHOLARLY_MON_D_Y_RE = re.compile(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})$")
LISTING_MAX_BYTES = 4_000_000                     # a listing page is read up to this
# A date written on the page ("June 29, 2026", "Jun 29, 2026").
TEXT_DATE_RE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, (?:19|20)\d\d\b")
SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b.*?</\1>")
# A page's own month and year standing alone in one element ("February 2026", "published Nov. 2026"): what dates a
# page that states no day (month_date). A month a sentence names ("In March 2024 we ...") is no such element.
MONTH_ALONE_RE = re.compile(
    r"(?i)^(?:(?:first\s+|last\s+)?(?:published|posted|updated|released|dated?)\s*(?:on|in)?\s*:?\s*)?"
    r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?"
    r"|Nov(?:ember)?|Dec(?:ember)?)\.?,?\s+((?:19|20)\d\d)$")
# A page's own day standing alone in one element ("August 12, 2026", "Published: Aug. 12, 2026"): a byline date
# past BYLINE_CHARS, after a long author list (byline_date). A day a sentence names is no such element.
DAY_ALONE_RE = re.compile(
    r"(?i)^(?:(?:first\s+)?(?:published|posted|released|dated?)\s*(?:on)?\s*:?\s*)?"
    r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? \d{1,2}, (?:19|20)\d\d)$")
TAG_RE = re.compile(r"<[^>]+>")
EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def normalise_prefix(value: Any) -> str:
    """"news" -> "/news/"; "" -> "/" (the whole site)."""
    path = urllib.parse.urlparse(str(value or "").strip()).path.strip("/")
    return f"/{path}/" if path else "/"


def _clean(url: str, base: Optional[str] = None) -> Optional[str]:
    """An absolute http(s) URL without its fragment or trailing slash; None for anything else."""
    try:
        absolute = urllib.parse.urldefrag(urllib.parse.urljoin(base or url, html.unescape(url.strip())))[0]
        parsed = urllib.parse.urlparse(absolute)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return urllib.parse.urlunparse(parsed._replace(path=parsed.path.rstrip("/") or "/"))


def infer_prefix(listing_url: str, links: Sequence[str]) -> str:
    """The listing page's path; for a home page, the most common first segment of its same-host pages two or
    more segments deep, when PREFIX_MIN pages or more share it ("/" otherwise: one deep link, a CDN's
    /cdn-cgi/l/email-protection, is no section). Never a date: a path stops above its first year segment."""
    path = urllib.parse.urlparse(listing_url).path.strip("/")
    if path:
        return stable_prefix(f"/{path}/")
    site = publication_of(host_of(listing_url))
    firsts = Counter("" if YEAR_RE.match(segments[0]) else segments[0]
                     for link in {page_key(link): link for link in links}.values()
                     if publication_of(host_of(link)) == site and len(segments := parsing.path_segments(link)) >= 2)
    first, count = firsts.most_common(1)[0] if firsts else ("", 0)
    return f"/{first}/" if first and count >= PREFIX_MIN else "/"


PREFIX_MIN = 2   # pages that make a home page's section


# A prefix ending in a year segment stops matching when the year turns: a prefix is the stable section above it.
YEAR_RE = re.compile(r"^(?:19|20)\d\d$")


def stable_prefix(prefix: str) -> str:
    """The prefix less its first year segment and what follows it: "/2026/" -> "/", "/blog/2026/11/" -> "/blog/"."""
    segments = [segment for segment in prefix.split("/") if segment]
    for n, segment in enumerate(segments):
        if YEAR_RE.match(segment):
            segments = segments[:n]
            break
    return f"/{'/'.join(segments)}/" if segments else "/"


# A page whose last path segment is an action word (apply, sign up, contact) is a form, never a post, wherever it
# sits: linked_rules.NOT_POST's actions plus the form actions it lacks.
ACTION_WORDS = frozenset({
    "apply", "application", "applications", "login", "log-in", "signin", "sign-in", "signup", "sign-up", "register",
    "registration", "subscribe", "unsubscribe", "contact", "contact-us", "form", "forms", "rsvp", "waitlist",
    "account", "checkout", "cart", "join", "enroll", "enrol"})


def action_page(url: str) -> bool:
    """Whether the address's last path segment is an action word (ACTION_WORDS): a form, never a post."""
    segments = parsing.path_segments(url)
    return bool(segments) and segments[-1].lower().rsplit(".", 1)[0] in ACTION_WORDS


FORM_RE = re.compile(r"(?is)<form\b([^>]*)>(.*?)</form\s*>")
FIELD_RE = re.compile(r"(?is)<(textarea|select)\b|<input\b([^>]*)>")
INPUT_TYPE_RE = re.compile(r"""(?i)\btype\s*=\s*["']?([a-z-]+)""")
NO_FIELD_TYPES = frozenset({"hidden", "submit", "button", "image", "reset", "search"})
FORM_FIELDS = 4           # a form of this many fields to fill is the page's purpose (an application, a sign-up)
FORM_TEXT_MAX = 1500      # ... when the page's article text around it is shorter than this


def form_page(page: str, text: str) -> bool:
    """Whether a page's body is a form: FORM_FIELDS fields or more to fill (not a comment or search form) on a
    page of little article text (FORM_TEXT_MAX)."""
    if len(text) >= FORM_TEXT_MAX:
        return False
    for attrs, inner in FORM_RE.findall(page):
        if re.search(r"(?i)comment|search", attrs):
            continue
        fields = 0
        for tag, input_attrs in FIELD_RE.findall(inner):
            kind = INPUT_TYPE_RE.search(input_attrs or "")
            if tag or (kind.group(1).lower() if kind else "text") not in NO_FIELD_TYPES:
                fields += 1
        if fields >= FORM_FIELDS:
            return True
    return False


# A listing's later pages (/news/page/7, ?page=7) are the listing again, never an article or a section to offer.
PAGINATION_SEGMENTS = frozenset({"page", "pages", "p"})
PAGINATION_KEYS = frozenset({"page", "paged", "pg"})
PAGINATION_TITLE_RE = re.compile(r"(?i)(?:\(\s*page\s+\d+\s*\)|\bpage\s+\d+\s+of\s+\d+\b)")


def pagination_page(url: str, title: str = "") -> bool:
    """Whether the address (or the page's title) is a listing's numbered page: /page/<n> or /p/<n> at its end,
    ?page=<n>, a title "News (Page 7)" or "Page 7 of 12"."""
    segments = parsing.path_segments(url)
    if len(segments) >= 2 and segments[-1].isdigit() and segments[-2].lower() in PAGINATION_SEGMENTS:
        return True
    query = urllib.parse.parse_qsl(urllib.parse.urlparse(url).query)
    if any(key.lower() in PAGINATION_KEYS and value.isdigit() for key, value in query):
        return True
    return bool(title and PAGINATION_TITLE_RE.search(title))


# A listing of other posts (a tag, category, topic or author archive) is no post, though it may show an article's
# title and date. By its address (a LISTING_SEGMENT before its last segment, past the source's prefix) or its
# markup (an archive body class, JSON-LD CollectionPage / ProfilePage, a feed of its own other than comments).
LISTING_SITEMAP_RE = re.compile(r"(?i)taxonom|post_tag|(?:^|[-_])(?:tags?|categor(?:y|ies)|authors?|users?)(?:[-_.]|$)")
LISTING_SEGMENTS = frozenset({"tag", "tags", "topic", "topics", "category", "categories", "author", "authors"})
BODY_CLASS_RE = re.compile(r"""(?is)<body\b[^>]*\bclass\s*=\s*["']([^"']*)["']""")
LISTING_BODY_CLASSES = frozenset({"archive", "tag-template", "author-template"})
LISTING_LD_RE = re.compile(r'"@type"\s*:\s*"(?:CollectionPage|ProfilePage)"')
ALTERNATE_FEED_RE = re.compile(r"""(?is)<link\b[^>]*\btype\s*=\s*["']application/(?:rss|atom)\+xml["'][^>]*>""")
HREF_ATTR_RE = re.compile(r"""(?is)\bhref\s*=\s*["']?([^"'\s>]+)""")
OWN_FEED_NAMES = frozenset({"feed", "feed/", "index.xml", "rss", "rss/", "rss.xml", "atom.xml"})
MARKUP_HEAD = 400_000     # a page's markup read for these signs


def listing_address(url: str, prefix: str = "") -> bool:
    """Whether the address is a tag / category / topic / author archive, the source's own prefix aside (a watched
    /topics/ section's pages stay its articles)."""
    segments = parsing.path_segments(url)
    own = len([part for part in str(prefix or "").split("/") if part])
    return len(segments) >= 2 and len(segments) - 2 >= own and segments[-2].lower() in LISTING_SEGMENTS


# The kinds that store a site's own pages read as articles (article_post: external_id is the page's path).
SITE_PAGE_ADAPTERS = frozenset({"page_watch", "generic_rss"})


def read_from_address(external_id: Optional[str], adapter: Optional[str]) -> bool:
    """Whether a stored post is a site page read as an article from its address (an archive's sitemap, listing or
    Web Archive page, a page watch's page), from its row alone: SITE_PAGE_ADAPTERS and an external id that is the
    page's path (article_post's; a page that moved keeps the one it was first read at), never a feed item's guid."""
    return adapter in SITE_PAGE_ADAPTERS and bool(external_id) and str(external_id).startswith("/")


def stored_listing(url: Optional[str], external_id: Optional[str], adapter: Optional[str], prefix: str = "") -> bool:
    """Whether a stored post is a listing of other posts, from its row alone: a site page read as an article
    (read_from_address) at a listing address; never a feed item, saved page or release.
    Asked by utils/item_filter's `listing` rule."""
    return bool(url) and read_from_address(external_id, adapter) and listing_address(str(url), prefix)


def listing_markup(page: str, url: str) -> bool:
    """Whether the page says it lists other posts (LISTING_BODY_CLASSES, LISTING_LD_RE, a feed of its own)."""
    head = page[:MARKUP_HEAD]
    body = BODY_CLASS_RE.search(head)
    if body and LISTING_BODY_CLASSES & set(body.group(1).lower().split()):
        return True
    if LISTING_LD_RE.search(head):
        return True
    own = (url or "").split("#")[0].split("?")[0].rstrip("/") + "/"
    for tag in ALTERNATE_FEED_RE.findall(head):
        href = HREF_ATTR_RE.search(tag)
        if href is None or "comment" in tag.lower():
            continue
        target = urllib.parse.urljoin(url, html.unescape(href.group(1)))
        if target.startswith(own) and target[len(own):] in OWN_FEED_NAMES:
            return True
    return False


def not_post(page: str, url: str, post: Mapping[str, Any]) -> bool:
    """Whether a page read as an article is none whatever it shows: a form, a listing's numbered page, or markup
    saying it lists other posts. Asked by page watch, the archive's sitemap pages and a post's linked pages."""
    return bool(action_page(url) or pagination_page(url, post.get("title") or "")
                or form_page(page, post.get("content") or "") or listing_markup(page, url))


def page_key(url: str) -> str:
    """One key for one page's addresses: www. and the bare host are one, as ingestion normalises them."""
    return normalize_url(url) or url


def twin(url: str) -> str:
    """The address at the other form of its host: www.<host> <-> <host>."""
    parsed = urllib.parse.urlparse(url)
    other = parsed.netloc[4:] if parsed.netloc.lower().startswith("www.") else f"www.{parsed.netloc}"
    return urllib.parse.urlunparse(parsed._replace(netloc=other))


# settings key: where a page watch's listing page lands when that is another page (lands_elsewhere), else null
LANDS_AT_KEY = "lands_at"


def lands_elsewhere(asked: str, landed: str) -> Optional[str]:
    """The landed address when it is another page than the asked one; None for the same page at http/https, www. or
    bare host, a trailing slash, or a different case of host."""
    def same_page(url: str) -> Optional[Tuple[str, str, str]]:
        clean = _clean(url)
        if not clean:
            return None
        parsed = urllib.parse.urlparse(clean)
        host = parsed.netloc.lower()
        return host[4:] if host.startswith("www.") else host, parsed.path.rstrip("/") or "/", parsed.query

    if not landed or same_page(asked) == same_page(landed):
        return None
    return _clean(landed) or landed


# A site's name after its titles ("Title | Blog", "Title — Acme"), learned across a section's titles: the trailing
# segment after a separator most of them share. The separator is spaced after it, before it optionally.
TITLE_SUFFIX_RE = re.compile(r"^(.*\S)\s*[|\\/·•–—-]\s+([^|\\/·•–—]{1,40}?)\s*$")


def title_suffix(title: str) -> Optional[Tuple[str, str]]:
    """(the title before its last " <separator> " segment, that segment), or None."""
    match = TITLE_SUFFIX_RE.match(title or "")
    return (match.group(1), match.group(2).strip()) if match else None


def site_suffixes(titles: Sequence[str]) -> set:
    """The trailing segments (casefolded) that name the site: on two of these titles at least, and half or more."""
    found = Counter(split[1].casefold() for title in titles if (split := title_suffix(title)))
    return {suffix for suffix, n in found.items() if n >= 2 and n * 2 >= len(titles)}


def strip_site_suffix(title: str, suffixes: set) -> str:
    """The title less its trailing segment when that names the site (site_suffixes)."""
    split = title_suffix(title)
    return split[0] if split and split[1].casefold() in suffixes else title


def name_titles(posts: Sequence[Dict[str, Any]], known: Sequence[str] = ()) -> None:
    """Strip the site's name off the posts' titles, learned across them and the `known` titles of their section
    (its listing page's), in place."""
    titles = [str(post["title"]) for post in posts if post.get("title") and post["title"] != post.get("url")]
    suffixes = site_suffixes([*titles, *(title for title in known if title)])
    if suffixes:
        for post in posts:
            if post.get("title"):
                post["title"] = strip_site_suffix(str(post["title"]), suffixes)


# A listing page whose own path holds fewer than SECTION_MIN articles is followed under the section its article
# links share (at least SECTION_MIN of them, never a menu section).
SECTION_MIN = 3
MENU_SECTIONS = frozenset({
    "about", "author", "authors", "careers", "categories", "category", "company", "contact", "customers", "docs",
    "features", "help", "integrations", "jobs", "legal", "login", "partners", "platform", "pricing", "privacy",
    "product", "products", "search", "signup", "solution", "solutions", "support", "tag", "tags", "team", "terms",
    "topic", "topics", "use-cases"})
MENU_BLOCK_RE = re.compile(r"(?is)<(nav|header|footer)\b.*?</\1\s*>")


def article_shaped(url: str) -> bool:
    """Two or more path segments, the last a slug of three words or more ("/post/why-rates-rose"): the feed
    finder's article link (feed_finder._article_links)."""
    segments = parsing.path_segments(url)
    last = segments[-1].lower().rsplit(".", 1)[0] if segments else ""
    return len(segments) >= 2 and bool(parsing.SLUG_RE.match(last)) and last.count("-") >= 2


def section_prefix(listing_url: str, content_links: Sequence[str]) -> Optional[str]:
    """The section the page's articles live in: "/<first segment>/" shared by the most of its same-site,
    article-shaped content links (menus already left out by the caller), at least SECTION_MIN of them, outside
    MENU_SECTIONS; a tie goes to the one linked first. None when there is none."""
    site, listing = publication_of(host_of(listing_url)), listing_url.rstrip("/")
    firsts = Counter(parsing.path_segments(link)[0] for link in dict.fromkeys(content_links)
                     if publication_of(host_of(link)) == site and link.rstrip("/") != listing and article_shaped(link)
                     and parsing.path_segments(link)[0].lower() not in MENU_SECTIONS
                     and not YEAR_RE.match(parsing.path_segments(link)[0]))   # never a year
    if not firsts:
        return None
    first, count = firsts.most_common(1)[0]
    return f"/{first}/" if count >= SECTION_MIN else None


@dataclass(frozen=True)
class Discovery:
    prefix: str
    listed: Tuple[str, ...]                          # the listing page's article links, page order
    sitemap: Dict[str, Optional[datetime]]           # the sitemap's article URLs -> lastmod
    title: str = ""                                  # the listing page's own title (for the site's suffix)
    landed: str = ""                                 # where the listing page landed after its redirects

    def candidates(self) -> List[str]:
        """Listing links first (page order), then the sitemap's others by lastmod, newest first."""
        listed = set(self.listed)
        rest = sorted((url for url in self.sitemap if url not in listed),
                      key=lambda url: self.sitemap[url] or EPOCH, reverse=True)
        return [*self.listed, *rest]


# One run's reads of a site's robots.txt and sitemaps, by address, shared by an offer's previews.
SiteReads = Dict[str, "asyncio.Future[Tuple[Any, str]]"]

# Which of these urls a source's fetch leaves unread (blocking; run in a thread): PostsRepository.kept_urls.
KeptUrls = Callable[[Sequence[str], str], set]

# GET an address, at most max_bytes of it: (the body, the final URL after redirects).
Reader = Callable[[str, int], Awaitable[Tuple[bytes, str]]]


async def discover(http: KindHttp, listing_url: str, prefix: Optional[str] = None,
                   reads: Optional[SiteReads] = None, *,
                   memory: Optional[AddressMemory] = None,
                   read: Optional[Dict[str, Conditional]] = None,
                   max_sitemaps: int = MAX_SITEMAPS) -> Discovery:
    """The articles of a listing page. Raises when the listing page cannot be read; a missing or broken sitemap
    is no sitemap. `reads`: the run's shared robots and sitemap reads. With memory every address is read through
    it (memory.learned: the addresses read); `read`: answers already in hand (discover_changed's)."""
    pending, addresses = dict(read or {}), []

    async def get(url: str, max_bytes: int) -> Tuple[bytes, str]:
        if memory is None:
            return await http.get_start(url, max_bytes)
        answer = pending.pop(url, None) or await memory.get(http, url, max_bytes=max_bytes)
        addresses.append(url)
        return answer.body or b"", answer.url

    found = await _discover(get, http, listing_url, prefix, reads, max_sitemaps=max_sitemaps)
    if memory is not None:
        kept = {url: memory.learned[url] for url in addresses if url in memory.learned}
        memory.learned = kept if len(kept) == len(set(addresses)) else {}
    return found


async def discover_changed(http: KindHttp, listing_url: str, prefix: Optional[str],
                           memory: AddressMemory) -> Optional[Discovery]:
    """discover(), or None when the listing page and every sitemap file the last fetch read
    answer 304. The first that answers in full (or, a sitemap, fails) ends the asking; the
    others are then read in full."""
    read: Dict[str, Conditional] = {}
    if memory.sending(listing_url) is not None:
        for url in [listing_url, *(url for url in memory.stored if url != listing_url)]:
            if url == listing_url:
                answer = await memory.get(http, url, max_bytes=LISTING_MAX_BYTES)   # its failure is the fetch's
            else:
                try:
                    answer = await memory.get(http, url, max_bytes=SITEMAP_MAX_BYTES)
                except Exception:  # noqa: BLE001 - a sitemap gone is a change: discover reads what is there
                    break
            if not answer.not_modified:
                read[url] = answer
                break
        else:
            return None
    memory.full = True     # something changed: what answered 304 is read in full again
    return await discover(http, listing_url, prefix, memory=memory, read=read)


async def _discover(get: Reader, http: KindHttp, listing_url: str, prefix: Optional[str],
                    reads: Optional[SiteReads] = None, *, max_sitemaps: int = MAX_SITEMAPS) -> Discovery:
    # where the listing landed after redirects, not the address given
    body, landed = await get(listing_url, LISTING_MAX_BYTES)
    page = body.decode("utf-8", "replace")
    listing = _clean(landed) or landed
    links = [url for href in LINK_RE.findall(page) if (url := _clean(href, landed))]
    site = publication_of(host_of(listing))
    reads = {} if reads is None else reads    # a sitemap file read for one prefix is not read again for another

    listing_key = page_key(listing)
    tag = TITLE_RE.search(page)
    title = html.unescape(parsing.meta_content(page, "og:title")).strip() or (parsing.strip_html(tag.group(1)) if tag else "")

    def under(url: str, prefix: str) -> bool:
        # never a form or a numbered page of a listing
        path = urllib.parse.urlparse(url).path
        return (publication_of(host_of(url)) == site and url != listing and path.startswith(prefix)
                and path + "/" != prefix and page_key(url) != listing_key
                and not action_page(url) and not pagination_page(url) and not listing_address(url, prefix))

    async def found_under(prefix: str) -> Discovery:
        # one page at www. and at the bare host is one candidate: its first address kept
        first: Dict[str, str] = {}    # page key -> the address kept
        for url in links:
            if under(url, prefix):
                first.setdefault(page_key(url), url)
        listed = tuple(dict.fromkeys(first.values()))
        sitemap: Dict[str, Optional[datetime]] = {}
        for loc, lastmod in await _sitemap_entries(get, http, listing, prefix, reads, max_files=max_sitemaps):
            url = _clean(loc)
            if url and under(url, prefix):
                sitemap.setdefault(first.setdefault(page_key(url), url), parsing.parse_datetime_value(lastmod))
        return Discovery(prefix, listed, sitemap, title, landed=listing)

    if prefix:   # the owner's prefix always wins, less any date it ends in
        return await found_under(stable_prefix(normalise_prefix(prefix)))
    inferred = infer_prefix(listing, links)
    if not parsing.path_segments(listing) or len({page_key(url) for url in links if under(url, inferred)}) >= SECTION_MIN:
        return await found_under(inferred)
    # the listing's own path holds few of its links: unless the sitemap fills it, the section its links share
    content = [url for href in LINK_RE.findall(MENU_BLOCK_RE.sub(" ", page)) if (url := _clean(href, landed))]
    section = section_prefix(listing, content)
    own = await found_under(inferred)
    if section is None or section == inferred or len(own.candidates()) >= SECTION_MIN:
        return own
    other = await found_under(section)
    return other if len(other.candidates()) > len(own.candidates()) else own


async def _shared(reads: Optional[SiteReads], url: str,
                  read: Callable[[], Awaitable[Tuple[Any, str]]]) -> Tuple[Any, str]:
    """read(), once per url within a run: a second caller awaits the first's read. A preview
    cut by the budget never cancels a read another preview awaits."""
    if reads is None:
        return await read()
    if url not in reads:
        reads[url] = asyncio.ensure_future(read())
    return await asyncio.shield(reads[url])


async def sitemap_entries(http: KindHttp, listing: str, prefix: str, *, posts_only: bool = False,
                          max_files: int = MAX_SITEMAPS) -> List[Tuple[str, Optional[str]]]:
    """(loc, lastmod) of the site's sitemap (robots.txt's Sitemap lines, else /sitemap.xml; an index followed to
    at most `max_files` files). posts_only: of an index, only the children naming posts, when it has any."""
    return await _sitemap_entries(http.get_start, http, listing, prefix, posts_only=posts_only, max_files=max_files)


async def _sitemap_entries(get: Reader, http: KindHttp, listing: str, prefix: str,
                           reads: Optional[SiteReads] = None, *, posts_only: bool = False,
                           max_files: int = MAX_SITEMAPS) -> List[Tuple[str, Optional[str]]]:
    origin = parsing.origin_from_source(listing, "")
    try:
        robots, _ = await _shared(reads, f"{origin}/robots.txt", lambda: http.get_text(f"{origin}/robots.txt"))
    except Exception:  # noqa: BLE001 - no robots.txt: the usual address
        robots = ""
    queue = [line.split(":", 1)[1].strip() for line in robots.splitlines()
             if line.lower().startswith("sitemap:")] or [f"{origin}/sitemap.xml"]
    # an archive (posts_only) reads gzip sitemaps too and, with none found, the blog platforms' posts files
    fallbacks = [f"{origin}/{name}" for name in POST_SITEMAPS] if posts_only else []
    section = prefix.strip("/").split("/")[0]
    entries: List[Tuple[str, Optional[str]]] = []
    read = 0
    answered = False
    while (queue or (fallbacks and not answered)) and read < max_files:
        if not queue:
            queue, fallbacks = fallbacks, []
        url = _clean(queue.pop(0))
        if url is None or (urllib.parse.urlparse(url).path.endswith(".gz") and not posts_only):
            continue
        read += 1
        try:
            body, _ = await _shared(reads, url, lambda: get(url, SITEMAP_MAX_BYTES))
        except Exception as exc:  # noqa: BLE001 - a missing sitemap is no sitemap
            logger.debug("Page watch: sitemap %s skipped (%s)", url, exc)
            continue
        if posts_only:
            body = _ungzip(body)
        root, locs = _sitemap_locs(body)
        answered = answered or bool(root)
        if root == "sitemapindex":
            # An index's children that name the section (or posts) first.
            children = [loc for loc, _ in locs if loc]
            # never a taxonomy's or the authors' file (its name may hold "post" too): they list listing pages
            children = [child for child in children if not LISTING_SITEMAP_RE.search(child.rsplit("/", 1)[-1])]
            if posts_only:
                children = [child for child in children if "post" in child.rsplit("/", 1)[-1].lower()] or children
            queue.extend(sorted(children, key=lambda child: not (section and section in child or "post" in child)))
        else:
            entries.extend((loc, lastmod) for loc, lastmod in locs if loc)
    return entries


def _ungzip(body: Any) -> Any:
    """A gzip sitemap's bytes unpacked; anything else as it is."""
    if isinstance(body, bytes) and body[:2] == b"\x1f\x8b":
        import gzip

        try:
            return gzip.decompress(body)
        except (OSError, EOFError):
            return body
    return body


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
                # a news sitemap's <news:publication_date> is the article's own date, before its lastmod
                published = next((parsing.child_text(child, "publication_date") for child in node
                                  if parsing.local_name(child.tag) == "news"), None)
                locs.append((parsing.child_text(node, "loc") or "", published or parsing.child_text(node, "lastmod")))
    except ET.ParseError:
        pass
    return root, locs


FUTURE_SLACK = timedelta(days=1)   # a page date past now + this is no post's date (an event)


# How page_dating dated a page, in the order of trust (0228); HELD: a body date the address or the web's age
# contradicts, so no date rather than a guess.
# MONTH: the page's own month and year alone (month_date), the 1st of that month, stored as precision "month".
DATED_BY_PAGE, DATED_BY_ADDRESS, DATED_BY_BODY, DATED_BY_MONTH, DATE_HELD = "page", "address", "body", "month", "held"
# No page was published before the first web page (1991-08-06): a body date before it is one the text names.
WEB_BEGAN = datetime(1991, 8, 6, tzinfo=timezone.utc)


def page_date(page: str, url: Optional[str] = None) -> Optional[datetime]:
    """The page's own publication date (page_dating's), or None."""
    return page_dating(page, url)[0]


def page_dating(page: str, url: Optional[str] = None) -> Tuple[Optional[datetime], Optional[str]]:
    """(the page's publication date, how it was read: DATED_BY_*), or (None, DATE_HELD | None). In the order of trust:
      1. the page's markup: article:published_time, JSON-LD datePublished, meta date, its one <time datetime>,
         then a scholarly meta date (SCHOLARLY_DATES), then its one data-published attribute;
      2. the day its address names (/2026/10/21/, /2008/Jul/7/);
      3. its body: the byline under its title, else its one written date; held when its address names another
         month or it is before WEB_BEGAN (articles quote dates);
      4. last, its own month and year by its title (month_date): the 1st of that month, DATED_BY_MONTH, held alike.
    The <time> and the written date count only when the page has one; no date past FUTURE_SLACK is taken."""
    json_ld, times = JSON_LD_DATE_RE.search(page), {value.strip() for value in TIME_RE.findall(page)}
    one_time = times.pop() if len(times) == 1 else None
    values = (parsing.meta_content(page, "article:published_time"), json_ld and json_ld.group(1),
              *(parsing.meta_content(page, name) for name in META_DATES), one_time)
    latest = datetime.now(timezone.utc) + FUTURE_SLACK
    for value in values:
        if value and (date := parsing.parse_datetime_value(value.strip())) is not None and date <= latest:
            return date, DATED_BY_PAGE
    for name in SCHOLARLY_DATES:
        if (date := scholarly_date(parsing.meta_content(page, name))) is not None and date <= latest:
            return date, DATED_BY_PAGE
    published = {value.strip() for value in DATA_PUBLISHED_RE.findall(page)}
    if len(published) == 1 and (date := scholarly_date(published.pop())) is not None and date <= latest:
        return date, DATED_BY_PAGE
    from insight_core.utils.originals_rules import address_day, address_month
    if url and (date := address_day(url)) is not None and date <= latest:
        return date, DATED_BY_ADDRESS
    visible = SCRIPT_STYLE_RE.sub(" ", page)
    date = byline_date(visible)
    if date is None:
        written = set(TEXT_DATE_RE.findall(parsing.strip_html(visible)))
        date = _written_date(written.pop()) if len(written) == 1 else None
    how = DATED_BY_BODY
    if date is None and (date := month_date(visible)) is not None:
        how = DATED_BY_MONTH
    if date is None or date > latest:
        return None, None
    month = address_month(url) if url else None
    if date < WEB_BEGAN or (month is not None and (date.year, date.month) != (month.year, month.month)):
        return None, DATE_HELD
    return date, how


def stated_precision(how: Optional[str]) -> Optional[str]:
    """The post's date_precision for how page_dating dated its page: "month" for a month alone, else None (the
    saver tells it by the date: a day alone or a time of day)."""
    return "month" if how == DATED_BY_MONTH else None


BYLINE_CHARS = 80   # how near its one <h1> a page's byline date is written


def byline_date(page: str) -> Optional[datetime]:
    """The date written within BYLINE_CHARS of text after the page's one <h1>, so related posts' dates below
    never count; else a day standing alone in one element (DAY_ALONE_RE) within MONTH_CHARS of text after the
    <h1> or before it (a byline after a long author list), the only day so written on the page: a listing's cards
    each stand their own day alone. `page` without scripts and styles."""
    if len(H1_RE.findall(page)) != 1:
        return None
    after = page[page.lower().index("</h1") :] if "</h1" in page.lower() else ""
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", after[:4000])).split())[:BYLINE_CHARS]
    match = TEXT_DATE_RE.search(text)
    if match:
        return _written_date(match.group(0))
    def alone(pieces: List[str]) -> Set[datetime]:
        return {day for piece in pieces if (found := DAY_ALONE_RE.match(piece.strip(" \t·•|–—-:"))) is not None
                and (day := _written_date(found.group(1))) is not None}

    near = alone(_by_title(page) or [])
    return near.pop() if len(near) == 1 and alone(_pieces(page)) == near else None


MONTH_CHARS = 400   # how much text after its one <h1>, or before it, a page's own month or day is written within


def _by_title(page: str) -> Optional[List[str]]:
    """The text pieces (one per element) within MONTH_CHARS of text after the page's one <h1>, then those before
    it, nearest first; None for a page with no <h1> or many."""
    titles = list(H1_RE.finditer(page))
    if len(titles) != 1:
        return None
    start, end = titles[0].span()

    def near(found: List[str]) -> List[str]:
        kept, chars = [], 0
        for text in found:
            if chars >= MONTH_CHARS:
                break
            kept.append(text)
            chars += len(text) + 1
        return kept

    return near(_pieces(page[end:end + 20_000])) + near(_pieces(page[max(0, start - 20_000):start])[::-1])


def _pieces(markup: str) -> List[str]:
    """The text of each element of `markup`, spaces collapsed, empty ones left out."""
    return [text for part in TAG_RE.split(markup) if (text := " ".join(html.unescape(part).split()))]


def month_date(page: str) -> Optional[datetime]:
    """The 1st of the month (UTC) a page states as its own: a month and year alone in one element (MONTH_ALONE_RE)
    within MONTH_CHARS of text after its one <h1> or before it (_by_title), the only month so written there. None
    for a page with no <h1> or many, or two different months by its title. `page` without scripts and styles."""
    window = _by_title(page)
    if window is None:
        return None
    months = set()
    for text in window:
        if (match := MONTH_ALONE_RE.match(text.strip(" \t·•|–—-:"))) is not None:
            months.add((int(match.group(2)), datetime.strptime(match.group(1)[:3].title(), "%b").month))
    if len(months) != 1:
        return None
    year, month = months.pop()
    return datetime(year, month, 1, tzinfo=timezone.utc)


def scholarly_date(value: str) -> Optional[datetime]:
    """A scholarly meta tag's date (see SCHOLARLY_DATES): an ISO date-time as written, or a whole day
    in one of the forms papers use, UTC; None for a year or a month alone, or anything else."""
    value = html.unescape(value or "").strip()
    if not value or re.fullmatch(r"\d{4}([/.-]\d{1,2})?", value):
        return None
    if (match := SCHOLARLY_YMD_RE.match(value)) is not None:
        year, month, day = match.groups()
    elif (match := SCHOLARLY_Y_MON_D_RE.match(value)) is not None:
        year, month, day = match.group(1), match.group(2), match.group(3)
    elif (match := SCHOLARLY_D_MON_Y_RE.match(value)) is not None:
        year, month, day = match.group(3), match.group(2), match.group(1)
    elif (match := SCHOLARLY_MON_D_Y_RE.match(value)) is not None:
        year, month, day = match.group(3), match.group(1), match.group(2)
    else:
        return parsing.parse_datetime_value(value)
    try:
        if not month.isdigit():
            month = str(datetime.strptime(month[:3].title(), "%b").month)
        return datetime(int(year), int(month), int(day), tzinfo=timezone.utc)
    except ValueError:
        return None


def _written_date(text: str) -> Optional[datetime]:
    """"June 29, 2026" or "Sept. 3, 2025" -> that day, UTC."""
    month, rest = text.split(" ", 1)
    try:
        return datetime.strptime(f"{month[:3]} {rest}", "%b %d, %Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def page_title(page: str, url: str) -> str:
    """og:title, else <title>, else the first <h1>; less a " | Site" suffix (the og:site_name's, or one starting
    with it, or any short one on a <title>). An og:title that is only the site's name is no title."""
    site = html.unescape(parsing.meta_content(page, "og:site_name")).strip()
    title, from_title_tag = html.unescape(parsing.meta_content(page, "og:title")).strip(), False
    tag = TITLE_RE.search(page)
    tag_title = parsing.strip_html(tag.group(1)) if tag else ""
    if title and site and title.casefold() == site.casefold():
        title = ""
    if title and title == tag_title:
        from_title_tag = True
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


def post_from(page: str, source_url: str, url: str, lastmod: Optional[datetime], *,
              new: bool = False) -> Optional[Dict[str, Any]]:
    """The post the page at url is, or None when it is no article. Undated by its markup: its address's day, then
    month, then the sitemap's lastmod. `new`: a page the listing shows now is dated now when nothing dates it; any
    other page stays undated (None)."""
    date, how = page_dating(page, url)
    if date is None and parsing.meta_content(page, "og:type").lower() != "article":
        return None
    precision = stated_precision(how) if date is not None else None
    date = date or (None if new else older_date(url)) or lastmod or (datetime.now(timezone.utc) if new else None)
    post = article_post(page, source_url, url, date, adapter=PageWatchKind.adapter_type, precision=precision)
    if post is not None and not_post(page, url, post):
        return None
    return post


def older_date(url: str) -> Optional[datetime]:
    """An undated page's sort hint by its address (originals_rules.address_hint: the day, else the month's 1st)."""
    from insight_core.utils.originals_rules import address_hint

    return address_hint(url)


async def read_page_post(http: KindHttp, source: Source, url: str, *, adapter: str) -> Optional[Dict[str, Any]]:
    """One page of a website source read as its post, marked backlog. None when the page has no article or no
    date of its own (an old page would sort as new). Raises what the request raises."""
    page, _ = await http.get_text(url)
    date, how = page_dating(page, url)
    if date is None or date > datetime.now(timezone.utc):
        return None
    post = article_post(page, str(source["handle_or_url"]), url, date, adapter=adapter, precision=stated_precision(how))
    if post is None or not_post(page, url, post):
        return None
    post[BACKLOG_KEY] = True
    return post


def article_post(page: str, source_url: str, url: str, date: Optional[datetime], *,
                 adapter: str, platform: str = "rss", precision: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The post any article page is: its body (the full-text reader), title, date and images; None without an
    article body. The date as given, None staying None (never "now"; a caller reading a new page passes now);
    `precision`: its date_precision when the saver can't tell it by the date (stated_precision: "month")."""
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
        "date": date,
        **({"date_precision": precision} if precision and date is not None else {}),
        "media_urls": media_urls,
        "categories": [],
        # when the page says it last changed: what a watched page is checked by
        "metadata": {"adapter": adapter, PAGE_READ_KEY: fidelity,
                     **({"modified": modified} if (modified := parsing.page_modified(page)) else {}),
                     # a page for paying readers: its free part, marked
                     **({"paywalled": True} if paywall.marker(page) else {})},
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
    name_titles(posts, [found.title])   # the site's name off the titles
    return {
        "prefix": found.prefix,
        "found": len(candidates),
        "sitemap": bool(found.sitemap),
        "items": [{"url": post["url"], "title": post["title"], "published_at": iso(post["date"])}
                  for post in posts[:PREVIEW_ITEMS]],
    }


def is_home(url: str) -> bool:
    """Whether the address is a site's home page (no path): a poor page to follow."""
    return not parsing.path_segments(parsing.web_address(url, "An address is needed"))


async def offers(http: KindHttp, pages: Sequence[str], menu: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """The pages that can be followed instead of a home page, each {url, **preview}, the most articles first. The
    previews run at once within OFFER_BUDGET_S; with none offered, the home page's menu links are previewed in
    what is left, and only an article list is offered (_article_list)."""
    deadline = asyncio.get_running_loop().time() + OFFER_BUDGET_S
    reads: SiteReads = {}
    pages = [page for page in pages if not pagination_page(page)]
    menu = [page for page in menu if not pagination_page(page)]
    found = [offer for offer in await _previews(http, pages, deadline, reads) if offer["items"]]
    if not found:
        started = datetime.now(timezone.utc)
        found = [offer for offer in await _previews(http, [page for page in menu if page not in pages], deadline, reads)
                 if _article_list(offer["items"], started)]
    return sorted(found, key=lambda offer: -offer["found"])


def _article_list(items: Sequence[Mapping[str, Any]], started: datetime) -> bool:
    """Whether a preview's posts read as a list of articles: at least MENU_POSTS dated within MENU_RECENT (pages
    of people or policies have old or few dates). A post dated at its read, after the preview started, is left out."""
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


# A site with no feed and no page offered is tried on the pages that list its announcements before it is called
# unfollowable (0240).
LIST_WORDS = frozenset({"news", "newsroom", "press", "blog"})   # what a site names its announcements' list pages
ROOT_LISTS = ("news", "newsroom", "press", "blog")               # ... tried at its root, in this order
LIST_SECTIONS = 2         # the sections its sitemap names by one of LIST_WORDS, the most addresses first
LIST_DEPTH = 3            # how deep in an address such a section is looked for (/en/company/newsroom/)
LIST_TRIES = 6            # list pages previewed a call, at most, one after another: the first dated one is offered
LIST_BUDGET_S = 20.0      # the whole call: its sitemap read and its previews
LIST_DATED = 2            # a list offered: this many of its preview's posts dated, and half of them or more


def list_pages(address: str, sitemap: Sequence[str] = ()) -> List[str]:
    """The pages that may list a site's announcements, in the order tried: the page itself, its parent path and its
    first segment's page; `sitemap`'s sections named by a LIST_WORD, the most addresses first; then, for a home
    page, ROOT_LISTS. A page under a section or an account (feed_finder.section_of) keeps to it. Never a home
    page or a numbered list page; each once."""
    from insight_core.ingestion.feed_finder import section_of
    origin = parsing.origin_from_source(address, "")
    if not origin:
        return []
    segments = parsing.path_segments(address)
    section = section_of(address)
    own = ["/".join(segments), "/".join(segments[:-1]), segments[0]] if section else []
    site = publication_of(host_of(address))
    counts: Counter = Counter()
    for url in sitemap:
        parts = parsing.path_segments(url)
        if publication_of(host_of(url)) != site or (section and (not parts or parts[0].lower() != section)):
            continue
        for depth in range(min(len(parts) - 1, LIST_DEPTH)):
            if parts[depth].lower() in LIST_WORDS:
                counts["/".join(parts[:depth + 1])] += 1
                break
    named = [path for path, _ in counts.most_common(LIST_SECTIONS)]
    out: Dict[str, str] = {}
    for path in (*own, *named, *(() if section else ROOT_LISTS)):
        url = f"{origin}/{path}" if path else ""
        if url and not pagination_page(url):
            out.setdefault(url.rstrip("/").lower(), url)
    return list(out.values())


def dated_list(items: Sequence[Mapping[str, Any]]) -> bool:
    """Whether a preview's posts are a dated stream: LIST_DATED or more, and half or more, dated by their own pages
    (never the time they were read)."""
    dated = sum(1 for item in items if item.get("published_at"))
    return dated >= LIST_DATED and 2 * dated >= len(items)


async def list_offers(http: KindHttp, address: str, tried: Sequence[str] = (),
                      first: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """The first of a site's list pages (`first`, then list_pages, less `tried`) whose preview is a dated stream,
    as [{url, **preview}]; [] when none is. At most LIST_TRIES previews in turn within LIST_BUDGET_S; the sitemap
    is read once and shared. Never raises for a site's failure."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + LIST_BUDGET_S
    reads: SiteReads = {}
    origin = parsing.origin_from_source(address, "")
    if not origin:
        return []
    try:
        entries = await asyncio.wait_for(_sitemap_entries(http.get_start, http, f"{origin}/", "/", reads),
                                         LIST_BUDGET_S / 2)
    except Exception as exc:  # noqa: BLE001 - no sitemap: the pages the address and the root name
        logger.debug("Page watch: %s sitemap not read for its lists (%s)", origin, type(exc).__name__)
        entries = []
    seen = {page.rstrip("/").lower() for page in tried}
    pages = []
    for page in (*first, *list_pages(address, [loc for loc, _ in entries])):
        if page.rstrip("/").lower() not in seen:
            seen.add(page.rstrip("/").lower())
            pages.append(page)
    try:
        for page in pages[:LIST_TRIES]:
            left = deadline - loop.time()
            if left <= 0:
                logger.info("Page watch: %s lists not all read (budget of %.0fs)", origin, LIST_BUDGET_S)
                break
            try:
                offer = await asyncio.wait_for(preview(http, page, reads=reads), left)
            except Exception as exc:  # noqa: BLE001 - a list page that can't be read is no list
                logger.debug("Page watch: %s is no list (%s)", page, type(exc).__name__)
                continue
            if dated_list(offer["items"]):
                logger.info("Page watch: %s has no feed; %s lists it, dated (issue 0240)", address, page)
                return [{"url": page, **offer}]
        return []
    finally:
        for read in reads.values():
            if not read.done():
                read.cancel()


class PageWatchKind(BaseSourceAdapter):
    adapter_type = "page_watch"
    conditional = True                  # fetch_latest takes memory=
    watches = True                      # its stored pages can be re-read for changes
    skips_stored = True                 # its archive leaves stored pages unread
    available_basis = "estimate"        # discovered candidate pages; some may be no post
    PAGE_SIZE = 1                       # one article page per archive page: the host gate spaces them
    PAGE_DELAY_SECONDS = 2

    def __init__(self, http: KindHttp, *, stored_urls: Optional[StoredUrls] = None,
                 kept_urls: Optional[KeptUrls] = None) -> None:
        super().__init__(http)
        self.stored_urls = stored_urls
        self.kept_urls = kept_urls

    async def _stored(self, source: Source, candidates: Sequence[str]) -> set:
        """The candidates a fetch leaves unread: stored already, at their address or its www./bare twin. With
        kept_urls, one another source holds counts only when this source would not take it back."""
        if not candidates or not (self.kept_urls or self.stored_urls):
            return set()
        forms = {url: (url, twin(url)) for url in candidates}
        asked = [form for pair in forms.values() for form in pair]
        if self.kept_urls is not None and source.get("id"):
            held = await asyncio.to_thread(self.kept_urls, asked, str(source["id"]))
        else:
            held = await asyncio.to_thread(self.stored_urls, asked)
        return {url for url, pair in forms.items() if held & set(pair)}

    def matches(self, source: Source) -> bool:
        return isinstance((source.get("settings") or {}).get("page_watch"), dict)

    async def _discover(self, source: Source) -> Discovery:
        settings = (source.get("settings") or {}).get("page_watch") or {}
        return await discover(self.http, str(source["handle_or_url"]), settings.get("prefix"))

    async def _archive_discovery(self, source: Source) -> Discovery:
        settings = (source.get("settings") or {}).get("page_watch") or {}
        return await discover(self.http, str(source["handle_or_url"]), settings.get("prefix"),
                              max_sitemaps=ARCHIVE_SITEMAPS)

    async def _discover_changed(self, source: Source, memory: AddressMemory) -> Optional[Discovery]:
        settings = (source.get("settings") or {}).get("page_watch") or {}
        return await discover_changed(self.http, str(source["handle_or_url"]), settings.get("prefix"), memory)

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

    async def fetch_latest(self, source: Source, limit: int, *,
                           memory: Optional[AddressMemory] = None) -> List[Dict[str, Any]]:
        """With memory, the listing page and its sitemap files are asked conditionally: none changed, no posts."""
        found = await (self._discover(source) if memory is None else self._discover_changed(source, memory))
        if found is None:
            return []
        now = time.monotonic()
        candidates = [url for url in found.candidates() if SKIPPED.get(url, now) <= now]
        stored = await self._stored(source, candidates)
        posts: List[Dict[str, Any]] = []
        reads = skips = 0
        listed = set(found.listed)
        for url in (url for url in candidates if url not in stored):
            if len(posts) >= limit or skips >= SKIP_READS:
                if memory is not None:
                    memory.forget()   # candidates left unread: the next fetch must look again
                break
            if reads:
                await self.http.sleep(self.PAGE_DELAY_SECONDS)
            reads += 1
            page = await self._page(url)
            post = post_from(page, str(source["handle_or_url"]), url, found.sitemap.get(url),
                             new=url in listed) if page else None
            if post is None:
                skips += 1
                SKIPPED[url] = time.monotonic() + FAILED_RETRY_S if page is None else math.inf
            else:
                if url not in listed:
                    post[BACKLOG_KEY] = True   # from the sitemap: never "new to you"
                posts.append(post)
        name_titles(posts, [found.title])   # the site's name off the titles
        got = FetchedPosts(posts)
        # where the listing page now lands, when another page (a site that moved its blog): the attention check
        # lists it; None again once it lands at its own address (merged only when it changed)
        got.recognised = {LANDS_AT_KEY: lands_elsewhere(str(source["handle_or_url"]), found.landed)}
        return got

    def page_post(self, source: Source, url: str, page: str) -> Optional[Dict[str, Any]]:
        return post_from(page, str(source["handle_or_url"]), url, None)

    async def inspect(self, source: Source) -> Inspection:
        """An archive's measurement: the candidates its run reads (the whole sitemap, ARCHIVE_SITEMAPS files)."""
        found = await self._archive_discovery(source)
        return Inspection(len(found.candidates()), self.PAGE_SIZE, None, raw={
            "prefix": found.prefix, "listing_links": len(found.listed), "sitemap_urls": len(found.sitemap)})

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        """Every candidate of the listing page and the whole sitemap, one article page per archive page; stored
        ones are not read again; the checkpoint counts why a candidate added nothing."""
        found = await self._archive_discovery(source)
        candidates = found.candidates()
        stored = await self._stored(source, candidates)

        async def fetch_one(src: Source, url: str) -> Any:
            page = await self._page(url)
            if page is None:
                return UNREADABLE
            post = post_from(page, str(src["handle_or_url"]), url, found.sitemap.get(url))
            if post is not None:
                post[BACKLOG_KEY] = True   # an archive's page: never new to you, undated sorts before the oldest
                name_titles([post], [found.title])
            return post

        async for page in self.index_pages(source, candidates, target, checkpoint, fetch_one, stored=stored):
            yield page


__all__ = ["Discovery", "PageWatchKind", "action_page", "listing_address", "listing_markup", "not_post", "stored_listing", "article_post", "article_shaped", "discover", "discover_changed",
           "form_page", "name_titles", "pagination_page", "site_suffixes", "stable_prefix",
           "infer_prefix", "is_home", "normalise_prefix", "offers", "page_date", "page_dating", "page_title", "preview", "stated_precision",
           "read_page_post", "read_from_address", "section_prefix", "sitemap_entries", "list_pages", "list_offers", "dated_list"]
