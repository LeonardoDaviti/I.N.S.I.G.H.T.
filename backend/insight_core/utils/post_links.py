"""The outside links inside a post (issue 0050), and the small facts about an address the
story rules read: its site, whether it is a home page, whether it reads like an article.

A post's links are read from its HTML (`content_html`; a YouTube description counts when it is
stored as HTML), made absolute against the post's own address and normalized as posts are
(0049, `url_normalization`). Not kept: links to the post's own site, media files, and links
back into the platform the post came from (Reddit's `[comments]` and user pages, t.me, x.com).
A source's signature (a link in 25% of its posts, 4 or more) can only be told over all of its
posts: the story job marks those (`post_links.boilerplate`).

Ported from the prototype (`plan/research/dedup-prototype/links.py`), the reference for these
rules.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from insight_core.utils.url_normalization import normalize_url

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
# An article-like address: a date in the path, or a slug of 4+ words.
ARTICLE = re.compile(r'(/(19|20)\d\d[/-]|[a-z0-9]+(-[a-z0-9]+){3,})')


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


def site_of(host: Optional[str]) -> str:
    """The registrable part of a host: its last two labels, three for a co.uk-like ending."""
    host = (host or "").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) >= 3 and len(parts[-2]) <= 3 and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def bare(url: str) -> str:
    """A normalized address without its scheme: `host/path?query`."""
    return url.split("://", 1)[-1]


def host_of(url: Optional[str]) -> str:
    return bare(url or "").split("/", 1)[0].split(":", 1)[0].lower()


def is_home(url: str) -> bool:
    """A site root or a one-segment path (a profile): it says who, not what."""
    _, _, rest = bare(url).partition("/")
    return "/" not in rest and "?" not in rest and "#" not in rest


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


def is_article(url: str) -> bool:
    _, _, rest = bare(url).partition("/")
    return bool(ARTICLE.search("/" + rest.lower()))


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
    blocked = {site_of(host_of(normalize_url(post_url) or ""))} | PLATFORM_SITES.get(kind, frozenset())
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
        if not url or url in seen:
            continue
        seen.add(url)
        site = site_of(host_of(url))
        if site in blocked or MEDIA.search(urlparse(url).path):
            continue
        out.append(PostLink(url, site, len(out), _link_text(content_html, match.end())))
    return out
