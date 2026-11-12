"""page_watch: a page without a feed, followed through its links and the site's sitemap (issue 0028).

A source is platform rss, handle_or_url the listing page (https://www.anthropic.com/news) and
settings.page_watch = {"prefix": "/news/"}; the setting is what selects this kind. The prefix
is optional: by default it is the listing page's path ("/news" -> "/news/"), or for a site's
home page the most common first segment of its deeper links. A listing page whose own path holds
fewer than SECTION_MIN articles (its links and the sitemap's) is followed under the section its
article links share instead (/resources/articles listing /post/<slug> -> "/post/", v10.13.10).

The articles are the union of
  - the listing page's same-host links under the prefix, in page order (newest first), and
  - the sitemap's URLs under the prefix (robots.txt's Sitemap: lines, else /sitemap.xml; an
    index is followed to at most MAX_SITEMAPS files, each read up to SITEMAP_MAX_BYTES; .gz
    files are skipped),
the listing page itself left out. A live fetch reads the ones not stored yet, listing links
first, then the sitemap's by lastmod (newest first); an archive reads them all, one article
page per archive page so the host gate spaces them.

An article page is read with the full-text reader (extract_article_html). Its date is the
page's own (article:published_time, JSON-LD datePublished, meta date, its one <time datetime>, a
paper's scholarly meta date: citation_publication_date and the like, its one written date), else
the sitemap's lastmod, else now: a sitemap's lastmod is often a redeploy date, not the
publication's. A page with no article body, or with neither a date nor og:type article (a
category page), is not a post. A live fetch remembers the pages it skipped for the process's
life (one that failed, for a day) and reads at most SKIP_READS of them besides its posts, so
they never use up its limit. A site that builds its pages with JavaScript yields no bodies,
so no posts (the preview says so).

A live fetch asks conditionally (issue 0044): when the listing page and every sitemap file the
last fetch read answer 304, nothing changed and the fetch is no posts. Validators are kept only
when every address read gave some and the fetch left no candidate unread (otherwise the next
fetch must look again, so it reads in full).

Its stored pages can be watched for changes (issue 0039, page_changes): page_post reads one
again as a fetch does, and article_post keeps the date the page says it changed (metadata
modified). A post found only in the sitemap is marked as backlog (repo_posts.BACKLOG_KEY): it is
never "new to you", so a fetch reading the site's history does not fill the top of the feed.
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
from insight_core.db.repo_posts import BACKLOG_KEY, PAGE_READ_KEY
from insight_core.ingestion.http import AddressMemory, Conditional, HttpError, KindHttp
from insight_core.ingestion.kinds import parsing, paywall
from insight_core.ingestion.kinds.base import UNREADABLE, Inspection, RateLimit, Source
from insight_core.ingestion.kinds.generic_rss import StoredUrls
from insight_core.utils.addresses import host_of, publication_of
from insight_core.utils.json_safe import iso
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.ingestion.page_watch")

MAX_SITEMAPS = 5          # sitemap files read per discovery (robots' ones, an index's children)
# An archive reads the site's whole sitemap for the rest of its pages (issue 0130 B4): a site whose index has more
# children than a live fetch reads (one a year, one a section) keeps its older pages there.
ARCHIVE_SITEMAPS = 60
SITEMAP_MAX_BYTES = 5_000_000   # a sitemap is read up to this; a longer one keeps its first entries
# The posts' sitemap files blog platforms write (an index's, WordPress's, Ghost's), read by an archive when
# robots.txt names none and /sitemap.xml is missing (issue 0143).
POST_SITEMAPS = ("sitemap_index.xml", "post-sitemap.xml", "sitemap-posts.xml", "wp-sitemap.xml", "sitemap.xml.gz")
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
# The scholarly (Highwire / Google Scholar, Dublin Core, PRISM) <meta name> dates papers carry (arXiv,
# bioRxiv, journals, proceedings), read after the dates above and before a date written in the text.
# The first publication comes first: a paper's later version or its issue's cover never moves its date,
# so the online date (arXiv's: the latest version's) is the last.
SCHOLARLY_DATES = ("citation_publication_date", "citation_date", "dc.date.issued", "dcterms.issued",
                   "dc.date.created", "dcterms.created", "prism.publicationdate", "citation_cover_date",
                   "citation_online_date")
# The forms they are written in, each a whole day (UTC): "2026/06/11", "2026-6-11", "2026 Jun 11",
# "Jun 11, 2026", "11 June 2026". A year or a month alone ("2026", "2026/6") is no date: stored as the
# 1st it would read as precise and sort the paper months early, so the next tag (or none) is used.
SCHOLARLY_YMD_RE = re.compile(r"^(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})$")
SCHOLARLY_Y_MON_D_RE = re.compile(r"^(\d{4})\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})$")
SCHOLARLY_D_MON_Y_RE = re.compile(r"^(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})$")
SCHOLARLY_MON_D_Y_RE = re.compile(r"^([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})$")
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


def infer_prefix(listing_url: str, links: Sequence[str]) -> str:
    """The listing page's path; for a home page, the most common first segment of its
    same-host links two or more segments deep ("/" when it has none). Never a date (v10.15 c5): a path
    stops above its first year segment (/blog/2026/11 -> "/blog/"), and links dated at the site's root
    (/2026/<slug>) count for "/"."""
    path = urllib.parse.urlparse(listing_url).path.strip("/")
    if path:
        return stable_prefix(f"/{path}/")
    site = publication_of(host_of(listing_url))
    firsts = Counter("" if YEAR_RE.match(segments[0]) else segments[0] for link in links
                     if publication_of(host_of(link)) == site and len(segments := parsing.path_segments(link)) >= 2)
    first = firsts.most_common(1)[0][0] if firsts else ""
    return f"/{first}/" if first else "/"


# v10.15 c5: a year segment (/2026/) and what follows it (the month, the day) date a page, so a prefix ending in one
# stops matching when the year turns: a prefix is the stable section above them.
YEAR_RE = re.compile(r"^(?:19|20)\d\d$")


def stable_prefix(prefix: str) -> str:
    """The prefix less its first year segment and what follows it: "/2026/" -> "/", "/blog/2026/11/" -> "/blog/"."""
    segments = [segment for segment in prefix.split("/") if segment]
    for n, segment in enumerate(segments):
        if YEAR_RE.match(segment):
            segments = segments[:n]
            break
    return f"/{'/'.join(segments)}/" if segments else "/"


# v10.15 c7: a page whose address names an action (apply, sign up, subscribe, contact) is a form or a door, never a
# post, wherever it sits (/news/<grant>/apply under a news section): its last path segment, as a whole word. The
# actions of linked_rules.NOT_POST (the pages no source's post is) and the form actions it lacks.
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
    """Whether a page's body is a form (v10.15 c7): one of FORM_FIELDS fields or more to fill (never a comment or
    a search form: an article's own) on a page of little article text (FORM_TEXT_MAX)."""
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


# v10.15 c10: a listing's later pages (/news/page/7, /blog/p/3, ?page=7, "News (Page 7)") are the listing again,
# never an article to read or a section to offer.
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


def page_key(url: str) -> str:
    """One key for one page's addresses (v10.15 c6): www. and the bare host are one, as ingestion normalises them."""
    return normalize_url(url) or url


def twin(url: str) -> str:
    """The address at the other form of its host: www.<host> <-> <host>."""
    parsed = urllib.parse.urlparse(url)
    other = parsed.netloc[4:] if parsed.netloc.lower().startswith("www.") else f"www.{parsed.netloc}"
    return urllib.parse.urlunparse(parsed._replace(netloc=other))


# v10.15 c8: a site's name after its titles ("Title | Blog", "Title - Acme Blog", "Title — Acme", "Title / Blog"),
# learned across a section's titles: the trailing segment after a separator that most of them share.
# The separator is spaced after it, before it too or not ("experiences- Acme Developers Blog").
TITLE_SUFFIX_RE = re.compile(r"^(.*\S)\s*[|\\/·•–—-]\s+([^|\\/·•–—]{1,40}?)\s*$")


def title_suffix(title: str) -> Optional[Tuple[str, str]]:
    """(the title before its last " <separator> " segment, that segment), or None."""
    match = TITLE_SUFFIX_RE.match(title or "")
    return (match.group(1), match.group(2).strip()) if match else None


def site_suffixes(titles: Sequence[str]) -> set:
    """The trailing segments (casefolded) that name the site: on two of these titles at least, and on half of them
    or more. One title alone teaches nothing (its own og:site_name is page_title's)."""
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


# v10.13.10: a listing page whose own path holds fewer than SECTION_MIN articles (its links and the sitemap's)
# is followed under the section its article links share instead (a /resources/articles page listing
# /post/<slug>): the first segment shared by the most of its content links in the feed finder's article shape
# (issue 0137 B2), at least SECTION_MIN of them, never a menu section.
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
                     and not YEAR_RE.match(parsing.path_segments(link)[0]))   # never a year (v10.15 c5)
    if not firsts:
        return None
    first, count = firsts.most_common(1)[0]
    return f"/{first}/" if count >= SECTION_MIN else None


@dataclass(frozen=True)
class Discovery:
    prefix: str
    listed: Tuple[str, ...]                          # the listing page's article links, page order
    sitemap: Dict[str, Optional[datetime]]           # the sitemap's article URLs -> lastmod
    title: str = ""                                  # the listing page's own title (v10.15 c8: the site's suffix)

    def candidates(self) -> List[str]:
        """Listing links first (page order), then the sitemap's others by lastmod, newest first."""
        listed = set(self.listed)
        rest = sorted((url for url in self.sitemap if url not in listed),
                      key=lambda url: self.sitemap[url] or EPOCH, reverse=True)
        return [*self.listed, *rest]


# One run's reads of a site's robots.txt and sitemaps, by address: the previews of one offer
# share them, so a site's sitemap is read once, not once per page previewed (issue 0047).
SiteReads = Dict[str, "asyncio.Future[Tuple[Any, str]]"]

# Which of these urls a source's fetch leaves unread (blocking; run in a thread): PostsRepository.kept_urls(urls,
# source_id), v10.15 item 5.
KeptUrls = Callable[[Sequence[str], str], set]

# GET an address, at most max_bytes of it: (the body, the final URL after redirects).
Reader = Callable[[str, int], Awaitable[Tuple[bytes, str]]]


async def discover(http: KindHttp, listing_url: str, prefix: Optional[str] = None,
                   reads: Optional[SiteReads] = None, *,
                   memory: Optional[AddressMemory] = None,
                   read: Optional[Dict[str, Conditional]] = None,
                   max_sitemaps: int = MAX_SITEMAPS) -> Discovery:
    """The articles of a listing page. Raises when the listing page cannot be read; a missing
    or broken sitemap is just no sitemap. `reads`: the run's shared robots and sitemap reads
    (an offer's previews, issue 0047).

    With memory every address is read through it, and memory.learned ends up holding the
    addresses read (none at all when one of them gave no validators). read: answers already
    in hand (discover_changed's), used instead of asking again."""
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
    # Where the listing landed, not the address given: deepmind.google/discover/blog/ is /blog/.
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
        # Never a form (c7) or a numbered page of a listing (c10, v10.15).
        path = urllib.parse.urlparse(url).path
        return (publication_of(host_of(url)) == site and url != listing and path.startswith(prefix)
                and path + "/" != prefix and page_key(url) != listing_key
                and not action_page(url) and not pagination_page(url))

    async def found_under(prefix: str) -> Discovery:
        # One page at www. and at the bare host is one candidate (v10.15 c6): its first address kept.
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
        return Discovery(prefix, listed, sitemap, title)

    if prefix:   # the owner's prefix always wins, less any date it ends in (v10.15 c5)
        return await found_under(stable_prefix(normalise_prefix(prefix)))
    inferred = infer_prefix(listing, links)
    if not parsing.path_segments(listing) or len({page_key(url) for url in links if under(url, inferred)}) >= SECTION_MIN:
        return await found_under(inferred)
    # The listing's own path holds few of its links: unless the sitemap fills it, the section its article links
    # share, when that finds more (v10.13.10).
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
    """(loc, lastmod) of the site's sitemap, as discovery reads it (robots.txt's Sitemap lines, else
    /sitemap.xml; an index followed, at most `max_files` files). posts_only: of an index, only the children
    naming posts, when it has any (issue 0108: a feed's archive reads a blog's post sitemap, not its tags or
    authors)."""
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
    # An archive (posts_only) reads a gzip sitemap too, and when neither robots.txt nor /sitemap.xml gives one,
    # the posts' files the blog platforms name (issue 0143).
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
            if posts_only:
                children = [child for child in children if "post" in child.rsplit("/", 1)[-1].lower()] or children
            queue.extend(sorted(children, key=lambda child: not (section and section in child or "post" in child)))
        else:
            entries.extend((loc, lastmod) for loc, lastmod in locs if loc)
    return entries


def _ungzip(body: Any) -> Any:
    """A gzip sitemap's bytes unpacked (a sitemap.xml.gz, issue 0143); anything else as it is."""
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
                locs.append((parsing.child_text(node, "loc") or "", parsing.child_text(node, "lastmod")))
    except ET.ParseError:
        pass
    return root, locs


FUTURE_SLACK = timedelta(days=1)   # v10.13.7: a page date past now + this is no post's date (an event, a sponsor)


def page_date(page: str, url: Optional[str] = None) -> Optional[datetime]:
    """The page's own publication date: meta article:published_time, JSON-LD datePublished,
    meta date, then a <time datetime>, then a paper's scholarly meta date (SCHOLARLY_DATES, the
    first publication first), then a date written on the page; the <time> and the written date
    only when the page has one (a tag or category page lists many)."""
    json_ld, times = JSON_LD_DATE_RE.search(page), {value.strip() for value in TIME_RE.findall(page)}
    one_time = times.pop() if len(times) == 1 else None
    values = (parsing.meta_content(page, "article:published_time"), json_ld and json_ld.group(1),
              *(parsing.meta_content(page, name) for name in META_DATES), one_time)
    latest = datetime.now(timezone.utc) + FUTURE_SLACK
    for value in values:
        if value and (date := parsing.parse_datetime_value(value.strip())) is not None and date <= latest:
            return date
    for name in SCHOLARLY_DATES:
        if (date := scholarly_date(parsing.meta_content(page, name))) is not None and date <= latest:
            return date
    if url:   # v10.13.7: the day the address names (/2008/Jul/7/) before a date written somewhere on the page
        from insight_core.utils.originals_rules import address_day
        if (date := address_day(url)) is not None and date <= latest:
            return date
    visible = SCRIPT_STYLE_RE.sub(" ", page)
    if (date := byline_date(visible)) is not None and date <= latest:
        return date
    written = set(TEXT_DATE_RE.findall(parsing.strip_html(visible)))
    date = _written_date(written.pop()) if len(written) == 1 else None
    return date if date is not None and date <= latest else None


BYLINE_CHARS = 80   # v10.15 item 5: how near its one <h1> a page's byline date is written


def byline_date(page: str) -> Optional[datetime]:
    """The date written right under the page's title (v10.15 item 5): its one <h1>, then within BYLINE_CHARS of
    text ("Title / July 7, 2026 • 15 minute read"). A page that cards other dated posts below its own (related
    posts) has several written dates; its byline is the one by its title. `page` without scripts and styles."""
    if len(H1_RE.findall(page)) != 1:
        return None
    after = page[page.lower().index("</h1") :] if "</h1" in page.lower() else ""
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", after[:4000])).split())[:BYLINE_CHARS]
    match = TEXT_DATE_RE.search(text)
    return _written_date(match.group(0)) if match else None


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
    """og:title, else <title>, else the first <h1>; less a " | Site" suffix: the og:site_name's
    (or one that starts with it: "| Mistral AI" for "Mistral"), or any short one on a <title>.
    An og:title that is only the site's name (a shop's blog: "Vuzix Corporation") is no
    title; one that is the <title> word for word is read as the <title> (issue 0053)."""
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
    """The post the page at url is, or None when it is no article (see the module docstring). A page whose markup
    states no date is dated by its address (/2026/10/21/, /2008/Jul/7/: v10.13.5), then (v10.13.9) its address's
    month, before the sitemap's lastmod. `new`: a page the watched listing shows now, dated now when nothing dates
    it; any other page (the sitemap's, an archive's, a page read again) stays undated (None)."""
    date = page_date(page, url)
    if date is None and parsing.meta_content(page, "og:type").lower() != "article":
        return None
    date = date or (None if new else older_date(url)) or lastmod or (datetime.now(timezone.utc) if new else None)
    post = article_post(page, source_url, url, date, adapter=PageWatchKind.adapter_type)
    # v10.15: a form (c7) or a listing's numbered page (c10) is no post, whatever its address says.
    if post is not None and (action_page(url) or pagination_page(url, post["title"]) or form_page(page, post["content"])):
        return None
    return post


def older_date(url: str) -> Optional[datetime]:
    """v10.13.9: an older page's sort hint by its address (originals_rules.address_hint: the day, else the month's
    1st), when the page states no date."""
    from insight_core.utils.originals_rules import address_hint

    return address_hint(url)


async def read_page_post(http: KindHttp, source: Source, url: str, *, adapter: str) -> Optional[Dict[str, Any]]:
    """One page of a website source read as its post (issue 0084 B: a page its posts link that no post
    is): the article, its title and the date the page states (0070), marked backlog (an older page,
    never new to you). None when the page has no article or no date of its own: stored at the time it
    was read, an old page would sort as new. Raises what the request raises."""
    page, _ = await http.get_text(url)
    date = page_date(page, url)
    if date is None or date > datetime.now(timezone.utc):
        return None
    post = article_post(page, str(source["handle_or_url"]), url, date, adapter=adapter)
    if post is not None:
        post[BACKLOG_KEY] = True
    return post


def article_post(page: str, source_url: str, url: str, date: Optional[datetime], *,
                 adapter: str, platform: str = "rss") -> Optional[Dict[str, Any]]:
    """The post any article page is: its body (the full-text reader), title, date and images; None when the page
    has no article body. Page watch and a saved page (issue 0031). v10.13.9: the date as given, None staying None
    (never "now": an older page dated at its fetch sits under Today); a caller that reads a genuinely new page
    passes now itself."""
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
        "media_urls": media_urls,
        "categories": [],
        # When the page says it last changed: what a watched page is checked by (issue 0039).
        "metadata": {"adapter": adapter, PAGE_READ_KEY: fidelity,
                     **({"modified": modified} if (modified := parsing.page_modified(page)) else {}),
                     # A page that says it is for paying readers (issue 0167): its free part, marked
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
    name_titles(posts, [found.title])   # the site's name off the titles (v10.15 c8)
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
    # A listing's numbered page (/news/page/7) is never a section to offer (v10.15 c10).
    pages = [page for page in pages if not pagination_page(page)]
    menu = [page for page in menu if not pagination_page(page)]
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
    conditional = True                  # fetch_latest takes memory= (issue 0044)
    watches = True                      # its stored pages can be re-read for changes (issue 0039)
    skips_stored = True                 # its archive leaves stored pages unread (issue 0130 B4)
    available_basis = "estimate"        # discovered candidate pages; some may be no post
    PAGE_SIZE = 1                       # one article page per archive page: the host gate spaces them
    PAGE_DELAY_SECONDS = 2

    def __init__(self, http: KindHttp, *, stored_urls: Optional[StoredUrls] = None,
                 kept_urls: Optional[KeptUrls] = None) -> None:
        super().__init__(http)
        self.stored_urls = stored_urls
        self.kept_urls = kept_urls

    async def _stored(self, source: Source, candidates: Sequence[str]) -> set:
        """The candidates a fetch leaves unread: stored already, at their address or at its www./bare twin (v10.15
        c6). With kept_urls (PostsRepository.kept_urls), one another source holds counts only when this source
        would not take it back (v10.15 item 5: a page in Saved, an aggregator's): reading it is what moves it."""
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
        """With memory (the runner's), the listing page and its sitemap files are asked
        conditionally: when none changed, no posts."""
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
                    post[BACKLOG_KEY] = True   # from the sitemap: never "new to you" (issue 0039)
                posts.append(post)
        name_titles(posts, [found.title])   # the site's name off the titles (v10.15 c8)
        return posts

    def page_post(self, source: Source, url: str, page: str) -> Optional[Dict[str, Any]]:
        return post_from(page, str(source["handle_or_url"]), url, None)

    async def inspect(self, source: Source) -> Inspection:
        """An archive's measurement: the candidates its run reads (the whole sitemap, ARCHIVE_SITEMAPS files)."""
        found = await self._archive_discovery(source)
        return Inspection(len(found.candidates()), self.PAGE_SIZE, None, raw={
            "prefix": found.prefix, "listing_links": len(found.listed), "sitemap_urls": len(found.sitemap)})

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        """Every candidate of the listing page and the site's whole sitemap (ARCHIVE_SITEMAPS files), one article
        page per archive page; the ones already stored are not read again, and the checkpoint counts why a
        candidate added nothing (issue 0130 B4: stored, no post, unreadable)."""
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
                name_titles([post], [found.title])   # v10.15 c8
            return post

        async for page in self.index_pages(source, candidates, target, checkpoint, fetch_one, stored=stored):
            yield page


__all__ = ["Discovery", "PageWatchKind", "action_page", "article_post", "article_shaped", "discover", "discover_changed",
           "form_page", "name_titles", "pagination_page", "site_suffixes", "stable_prefix",
           "infer_prefix", "is_home", "normalise_prefix", "offers", "page_date", "page_title", "preview",
           "read_page_post", "section_prefix", "sitemap_entries"]
