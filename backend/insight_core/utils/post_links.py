"""The outside links inside a post (issue 0050), and the small facts about an address the
story rules read: its site, whether it is a home page, whether it reads like an article.

A post's links are read from its HTML (`content_html`; a YouTube description counts when it is
stored as HTML), made absolute against the post's own address and normalized as posts are
(0049, `url_normalization`). Not kept: links to the post's own publication (its host, issue 0070:
another publication on its site is cited), media files, and links back into the platform the post
came from (Reddit's `[comments]` and user pages, t.me, x.com),
except a link to a tweet (issue 0066): on X, another post is a connection (a quote, a reply's link).
A source's signature (a link in 25% of its posts, 4 or more) can only be told over all of its
posts: the story job marks those (`post_links.boilerplate`).

Ported from the prototype (`plan/research/dedup-prototype/links.py`), the reference for these
rules.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional
from urllib.parse import urljoin, urlparse

from insight_core.utils.url_normalization import TWEET_PATH, normalize_url

HREF = re.compile(r'<a\b[^>]*?href=["\']([^"\']+)["\']', re.I)
# The rest of the opening tag, then the link's own text up to its closing tag.
LINK_TEXT = re.compile(r'[^>]*>(.*?)</a\s*>', re.I | re.S)
TAG = re.compile(r'<[^>]+>')
MEDIA = re.compile(r'\.(jpe?g|png|gif|webp|svg|mp4|webm|mp3|m4a|pdf)$', re.I)
LINK_TEXT_MAX = 300

# A post's links into the platform it came from say where it was posted, not what it is about.
PLATFORM_SITES = {
    "reddit": frozenset({"reddit.com", "redd.it"}),
    "hn": frozenset({"ycombinator.com"}),
    "x": frozenset({"x.com", "twitter.com"}),
    "telegram": frozenset({"t.me", "telegram.me", "telegram.org"}),
    "youtube": frozenset({"youtube.com", "youtu.be"}),
}
# The kind of place a source is, as the voice and share rules need it (not the fetch kind).
_KIND_PATTERNS = (
    ("reddit", re.compile(r"reddit", re.I)),
    ("telegram", re.compile(r"tg\.|(^|//|\.)t\.me/|telegram", re.I)),
    ("x", re.compile(r"nitter|//(www\.)?(x|twitter)\.com/", re.I)),
    ("arxiv", re.compile(r"arxiv", re.I)),
    ("hn", re.compile(r"hnrss|ycombinator", re.I)),
)
# A Reddit post's author, as its feed writes it: "submitted by <a href=".../user/name">".
REDDIT_AUTHOR = re.compile(r'submitted by\s*(?:&#32;)?\s*<a href="https://www\.reddit\.com/user/([^"/]+)')
# A quoted tweet, as Nitter writes it (issue 0066): the quote's address in the <cite> of its <blockquote>.
QUOTED = re.compile(r'<blockquote>.*?<cite>\s*<a\b[^>]*?href=["\']([^"\']+)["\']', re.I | re.S)
# A page's own words in a post (issue 0070): Nitter's quote of a tweet (its author in bold, its text,
# then a <footer> citing it), and a link preview, as the Telegram bridge writes one (a <blockquote>
# citing the page: its site in <cite>, then its title in bold and its description).
QUOTE_TEXT = re.compile(r'<blockquote>\s*<b>[^<]*</b>(.*?)<footer>\W*<cite>\s*<a\b[^>]*?href=["\']([^"\']+)["\']', re.I | re.S)
PREVIEW = re.compile(r'<blockquote cite=["\']([^"\']+)["\']>\s*<cite>\s*<b>([^<]*)</b>\s*</cite>\s*</br>'
                     r'(?:\s*<b>([^<]*)</b>\s*</br>)?([^<]*)', re.I)
LINE_END = re.compile(r'<br\s*/?>|</br>|</p\s*>', re.I)
# A preview titled by an account ("Claude (@claudeai) on X", "name (@name@mastodon.social)") is a post's:
# its description is the post's text.
BY_ACCOUNT = re.compile(r'\(@[^)\s]+\)')
# An article-like address: a date in the path, or a slug of 4+ words.
ARTICLE = re.compile(r'(/(19|20)\d\d[/-]|[a-z0-9]+(-[a-z0-9]+){3,})')
# A site's section (issue 0060): the first path segment SECTION_SHARE of its articles share, at least
# SECTION_MIN of them, never one that orders by time or by number (/2026/, /10/, /2026-10-31/).
# Follow starts there (ingestion/where_linked.py); Discover suggests it (issue 0065).
SECTION_SHARE = 0.6
SECTION_MIN = 2
NUMBERISH = re.compile(r"^\d[\d_.-]*$")
# A language tag's shape (issue 0067): en, ru-RU, zh-hans, en_US, es-419. Many sections share it (/ai/, /us/,
# huggingface.co/ai-sage), so a first segment of this shape is read as a language only when a section and a
# page follow it, never a date or a number: openai.com/ru-RU/index/x, not arstechnica.com/ai/2026/10/x.
LANGUAGE = re.compile(r"^[a-z]{2}(?:[-_](?:[a-z]{2}|[a-z]{4}|\d{3}))?$", re.I)


@dataclass(frozen=True)
class PostLink:
    url: str              # normalized (0049)
    site: str             # site_of(its host)
    position: int         # 0: the post's first outside link
    text: Optional[str]   # the link's own words


def source_kind(platform: Optional[str], handle_or_url: Optional[str]) -> str:
    """reddit, telegram, x, arxiv, hn, youtube, saved (the pages you save, from any site) or site."""
    platform = (platform or "").lower()
    if platform in ("reddit", "telegram", "youtube", "saved"):
        return platform
    handle = handle_or_url or ""
    for kind, pattern in _KIND_PATTERNS:
        if pattern.search(handle):
            return kind
    return "site"


@lru_cache(maxsize=1)
def _hosting_suffixes() -> FrozenSet[str]:
    """The Public Suffix List's private section (public_suffix_private.dat): the hosting platforms
    that register there so each subdomain is its own site (github.io, bearblog.dev). Its rules as
    written: a suffix, `*.` before one, `!` before an exception."""
    path = Path(__file__).with_name("public_suffix_private.dat")
    return frozenset(line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("//"))


def site_of(host: Optional[str]) -> str:
    """The registrable part of a host: one label under a hosting platform's suffix (issue 0068:
    karpathy.github.io and lilianweng.github.io are two sites), else its last two labels, three for
    a co.uk-like ending. Where a post is (Discover's places, a site's sections, a link to its own
    site); who said it is its publication (publication_of, issue 0069)."""
    host = (host or "").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    suffixes = _hosting_suffixes()
    for i in range(1, len(parts)):   # the longest suffix first
        suffix = ".".join(parts[i:])
        if "!" + suffix in suffixes:
            return suffix
        if suffix in suffixes or (i + 1 < len(parts) and "*." + ".".join(parts[i + 1:]) in suffixes):
            return ".".join(parts[i - 1:])
    if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def publication_of(host: Optional[str]) -> str:
    """A publication (issue 0069): a host without `www.`. A website source's voice is the one it
    publishes at, so writers on one platform (Substack, github.io) are voices of their own, and two
    sources at one host (a feed and a page watch) are one."""
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def bare(url: str) -> str:
    """A normalized address without its scheme: `host/path?query`."""
    return url.split("://", 1)[-1]


def host_of(url: Optional[str]) -> str:
    return bare(url or "").split("/", 1)[0].split(":", 1)[0].lower()


def is_home(url: str) -> bool:
    """A site root or a one-segment path (a profile): it says who, not what."""
    _, _, rest = bare(url).partition("/")
    return "/" not in rest and "?" not in rest and "#" not in rest


# A reference page's path segment (issue 0051): a vocabulary of page kinds, not a list of sites.
REFERENCE = re.compile(r"/(docs?|documentation|products?|pricing|support|help|api|reference|release-notes"
                       r"|changelog|wiki|articles|collections|download|login|signup)(/|$)")


def is_reference(url: str) -> bool:
    """A docs, product, pricing, help ... page, or a home page: a page you look things up in."""
    if is_home(url):
        return True
    _, _, rest = bare(url).partition("/")
    return bool(REFERENCE.search("/" + rest))


# A first path segment that names a kind of account, the account's name following it:
# reddit.com/r/<sub>, reddit.com/u/<user>, youtube.com/channel/<id>, youtube.com/c/<name>.
ACCOUNT_NAMESPACES = frozenset({"r", "u", "user", "c", "channel"})


def account_key(url: str) -> str:
    """The account an address on a platform is under: `host/first segment`, two segments when the
    first only says what kind of account follows (`reddit.com/r/xreal`). Lowercase."""
    host, _, rest = bare(url).partition("/")
    segments = rest.split("?", 1)[0].split("/")
    first = segments[0].lower()
    if first in ACCOUNT_NAMESPACES and len(segments) > 1 and segments[1]:
        return f"{host.lower()}/{first}/{segments[1].lower()}"
    return f"{host.lower()}/{first}"


def titled_link_text(text: Optional[str]) -> bool:
    """Link words that name a page: 3+ words starting with a capital or a digit, not an address and
    not cut mid-sentence. Measured on the server's data (2026-10-30, issue 0051): link words in the
    middle of a sentence ("over 100,000 commits", "full paper on arXiv") named the top classics
    badly; with this rule 20 of the top 30 titles were right, against 16, and the rest show the
    page's address."""
    if not text or re.match(r"https?://", text) or len(text.split()) < 3:
        return False
    return (text[0].isupper() or text[0].isdigit()) and not text.rstrip().endswith((",", ";", ":"))


def section_of(url: str) -> str:
    """The section an address is in: its first path segment when a page sits under it, "" for a
    page at the site's root or under a date or a number (/2026/10/x). A language before it is skipped
    (LANGUAGE): openai.com/ru-RU/index/x is in /index."""
    _, _, rest = bare(url).partition("/")
    segments = [segment for segment in rest.split("?", 1)[0].split("#", 1)[0].split("/") if segment]
    if len(segments) >= 3 and LANGUAGE.match(segments[0]) and not NUMBERISH.match(segments[1]):
        segments = segments[1:]
    return segments[0] if len(segments) >= 2 and not NUMBERISH.match(segments[0]) else ""


def is_article(url: str) -> bool:
    _, _, rest = bare(url).partition("/")
    return bool(ARTICLE.search("/" + rest.lower()))


def is_tweet(url: Optional[str]) -> bool:
    """A normalized address that is a tweet (issue 0066: every form of one is x.com/<user>/status/<id>)."""
    return host_of(url) == "x.com" and bool(TWEET_PATH.match("/" + bare(url or "").partition("/")[2]))


def quoted_tweet(content_html: Optional[str]) -> Optional[str]:
    """The tweet a tweet quotes, normalized: the address Nitter cites in the quote's <blockquote>."""
    match = QUOTED.search(content_html or "")
    url = normalize_url(html.unescape(match.group(1))) if match else None
    return url if is_tweet(url) else None


def quoted_words(content_html: Optional[str]) -> Dict[str, str]:
    """The pages a post quotes, normalized, each with its own words as quoted (issue 0070), plain
    text a line a line: a quoted tweet's text; a link preview's title, not one that only repeats the
    site's name, or for a post's preview (titled by its account, BY_ACCOUNT) its description."""
    found: Dict[str, str] = {}
    for text, url in QUOTE_TEXT.findall(content_html or ""):
        found.setdefault(normalize_url(html.unescape(url)) or "", text)
    for url, site, title, description in PREVIEW.findall(content_html or ""):
        url = normalize_url(html.unescape(url)) or ""
        words = description if BY_ACCOUNT.search(title) else title if title.strip().casefold() != site.strip().casefold() else ""
        if words.strip():
            found.setdefault(url, words)
    plain = {url: html.unescape(TAG.sub("", LINE_END.sub("\n", text))).strip() for url, text in found.items()}
    return {url: text for url, text in plain.items() if url and text}


def reddit_author(content_html: Optional[str]) -> Optional[str]:
    match = REDDIT_AUTHOR.search(content_html or "")
    return match.group(1).lower() if match else None


def _link_text(content_html: str, start: int) -> Optional[str]:
    match = LINK_TEXT.match(content_html, start)
    if not match:
        return None
    text = " ".join(html.unescape(TAG.sub(" ", match.group(1))).split())
    return text[:LINK_TEXT_MAX] or None


# A bare address in stored plain text (a post with no HTML body), as the reader links it.
BARE_URL = re.compile(r'https?://[^\s<>"\'`\]\[(){}]+', re.I)
BODY_HREFS_MAX = 500


def body_hrefs(content_html: Optional[str], content: Optional[str] = None) -> List[str]:
    """Every link target of a post's text as the reader gets it (issue 0057): the HTML's hrefs,
    entities decoded; with no HTML, the bare addresses of the plain text (without trailing
    punctuation). Each once, first seen first; any platform, the post's own site included."""
    if content_html and not HREF.search(content_html) and "&lt;a" in content_html:
        content_html = html.unescape(content_html)   # escaped HTML (Reddit's): the reader decodes it too
    if content_html:
        found = (html.unescape(m.group(1)).strip() for m in HREF.finditer(content_html))
    else:
        found = (m.group(0).rstrip(".,;:!?'\"") for m in BARE_URL.finditer(content or ""))
    out: List[str] = []
    for href in found:
        if href and href not in out:
            out.append(href)
            if len(out) >= BODY_HREFS_MAX:
                break
    return out


def extract_links(content_html: Optional[str], post_url: Optional[str], kind: str) -> List[PostLink]:
    """The outside links of one post, first seen first, each address once."""
    if not content_html:
        return []
    own = normalize_url(post_url) or ""
    # Its own publication (issue 0070: another publication on its site, a Substack writer another, is
    # cited), and where it was read from too: a tweet's address is x.com, but your Nitter's profiles
    # are its own.
    mine = {publication_of(host_of(own)), publication_of(host_of(post_url))}
    platform = PLATFORM_SITES.get(kind, frozenset())
    seen = set()
    out: List[PostLink] = []
    for match in HREF.finditer(content_html):
        href = html.unescape(match.group(1)).strip()
        try:
            absolute = urljoin(post_url or "", href)
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                continue
        except ValueError:
            continue
        url = normalize_url(absolute)
        if not url or url in seen or url == own:
            continue
        seen.add(url)
        site = site_of(host_of(url))
        if ((site in platform or publication_of(host_of(url)) in mine) and not is_tweet(url)) or MEDIA.search(urlparse(url).path):
            continue
        out.append(PostLink(url, site, len(out), _link_text(content_html, match.end())))
    return out
