"""A followed source's own pages, as its stored posts show them (issue 0084 B): which address is a
post page of which source, and which links of a post point to its own publication.

**Own links.** post_links never keeps a post's links to its own publication (post_links.extract_links,
issue 0070): a writer citing their own older post is no connection between voices. Those are the
links a source's own older posts are found by, so `own_links` reads them from the stored HTML the way
extract_links reads the others (the same hrefs, made absolute and normalized; no media, not the post
itself). A link in a quarter of a source's posts (4 at least) is its signature (story_rules'
SIGNATURE_SHARE, SIGNATURE_MIN_POSTS: a subscribe page, a series index), not a post it cites.

**Whose page an address is** (`OwnPages.owner`):
- *on a platform* (Discover's platforms: X, Telegram, Reddit, YouTube) a post of the account a source
  follows, its account as 0065 reads it (discover_address) and a post by its shape (a tweet, a
  Telegram /<channel>/<number>, a Reddit thread): x.com/<user>/status/<id> is the followed <user>'s;
  youtube.com/watch?v=… names no channel, so no one's;
- *elsewhere* an address of the same shape as the source's stored posts on the same publication
  (its host without www.). A shape is the path's segments, each a number (`#`) or a word (`*`), and
  the query's keys; its first segment stays as written when 2+ of the source's posts there share it
  (a section: /p/<slug>, /news/<slug>, /blog?id=), so /p/x is a Substack post page and /about,
  /archive and /p/x/comments are not. Only its posts on the site it publishes on count (a link blog
  stores posts at the pages it links). A Ghost blog's /<slug>/ is a shape of words only: it holds
  when half the source's posts there have it (GENERIC_SHARE), and a page named for a kind of page
  (NOT_POST: about, tag, author, page, subscribe…; by such a shape also post_links.REFERENCE: docs,
  pricing, product…) is none.
- One shape on one publication held by two sources (a site's feed and a page watch of it) is the one
  with more posts there. Hacker News and Saved own nothing (story_rules.NOT_PUBLISHERS).

Pure: the database side is db/repo_linked.py.
"""
from __future__ import annotations

import html
from collections import Counter, defaultdict
from typing import Collection, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qsl, urljoin, urlsplit

from insight_core.utils.addresses import host_of, publication_of, site_of
from insight_core.utils.discover_rules import DISCOVER_PLATFORMS, PLATFORM_POST, TWEET, discover_address
from insight_core.utils.post_links import HREF, MEDIA, NUMBERISH, REFERENCE, SECTION_MIN
from insight_core.utils.story_rules import NOT_PUBLISHERS, SIGNATURE_MIN_POSTS, SIGNATURE_SHARE
from insight_core.utils.url_normalization import normalize_url

# Path segments that name a kind of page, not a post: a vocabulary, not a list of sites.
NOT_POST = frozenset({
    "about", "archive", "archives", "tag", "tags", "topic", "topics", "category", "categories", "author",
    "authors", "page", "search", "subscribe", "feed", "rss", "atom", "contact", "privacy", "terms", "login",
    "signin", "signup", "account", "comments", "comment", "share", "sitemap", "recommendations", "leaderboard",
    "form", "forms",
})

# A shape of words only (no section, no number) holds a source's pages when half of its posts on that
# publication have it. On the server's copy (2026-11-05) the blogs at their root have 85-100% of their
# posts so, and a few stray root pages of a sectioned site 0-2% (a news site's /<product>).
GENERIC_SHARE = 0.5

Shape = Tuple[str, ...]
# (kind as post_links.source_kind says it, the platform account it follows or None, the sites it
# publishes on (its address's and SourceFacts.home_site), its stored posts' addresses)
SourcePosts = Tuple[str, Optional[str], Collection[str], Sequence[str]]


def own_links(content_html: Optional[str], post_url: Optional[str]) -> List[str]:
    """The links of one post to its own publication, normalized, first seen first, each once: not the
    post itself, no media file. What post_links.extract_links leaves out as the post's own."""
    if not content_html:
        return []
    if not HREF.search(content_html) and "&lt;a" in content_html:
        content_html = html.unescape(content_html)   # escaped HTML (Reddit's): the reader decodes it too
    own = normalize_url(post_url) or ""
    mine = publication_of(host_of(own))
    if not mine:
        return []
    # Where its own links can point before they are normalized: its publication, and the host it was
    # read from (a tweet read through your Nitter links its Nitter pages, normalized to x.com).
    near = {mine, publication_of(host_of(post_url))}
    out: List[str] = []
    for match in HREF.finditer(content_html):
        href = html.unescape(match.group(1)).strip()
        try:
            parts = urlsplit(urljoin(post_url or "", href))
            if parts.scheme not in ("http", "https") or publication_of(parts.hostname) not in near:
                continue
        except ValueError:
            continue
        url = normalize_url(parts.geturl())
        if not url or url == own or url in out or publication_of(host_of(url)) != mine or MEDIA.search(urlsplit(url).path):
            continue
        out.append(url)
    return out


def signature_links(links_by_post: Mapping[str, Iterable[str]]) -> Set[str]:
    """The links in SIGNATURE_SHARE of these posts and SIGNATURE_MIN_POSTS of them at least: a source's
    signature (its subscribe page, a series' index), as story_rules marks other links boilerplate."""
    posts = len(links_by_post)
    seen = Counter(url for links in links_by_post.values() for url in set(links))
    return {url for url, n in seen.items() if n >= SIGNATURE_MIN_POSTS and n >= SIGNATURE_SHARE * posts}


def _platform_post(url: str) -> bool:
    """A post of an account on a platform by its address: a tweet, /<channel>/<number> (Telegram), a
    Reddit thread. Not an article-like address there (a file name under a channel is no post)."""
    path = urlsplit(url).path or "/"
    return bool(TWEET.match(path) or PLATFORM_POST.match(path) or "/comments/" in path)


def _loose(shape: Shape) -> bool:
    """A shape of words only, no section and no number (/<slug>, /<a>/<b>): it holds a site's posts
    only when it is the shape of half of them (GENERIC_SHARE)."""
    return all(token == "*" for token in shape)


def _shapes(url: str) -> Optional[Tuple[Optional[Shape], Shape]]:
    """(the shape with its first segment as written, or None; the shape of words and numbers) of an
    address; None when a segment names a kind of page (NOT_POST) or it has no path or query."""
    parts = urlsplit(url)
    segments = [s.lower() for s in parts.path.split("/") if s]
    keys = sorted({key.lower() for key, _ in parse_qsl(parts.query, keep_blank_values=True)})
    if any(segment in NOT_POST for segment in segments):
        return None
    tail = ("?" + ",".join(keys),) if keys else ()
    generic = tuple("#" if NUMBERISH.match(s) else "*" for s in segments) + tail
    if not generic:
        return None
    literal = ((segments[0],) + generic[1:]) if segments and not NUMBERISH.match(segments[0]) and len(generic) >= 2 else None
    return literal, generic


class OwnPages:
    """Whose post page an address is, learned from every source's stored posts (see the module)."""

    def __init__(self, sources: Mapping[str, SourcePosts]) -> None:
        self.of_account: Dict[str, str] = {}
        # (publication, shape) -> {source: its posts of that shape there}
        held: Dict[Tuple[str, Shape], Counter] = defaultdict(Counter)
        for source_id, (kind, account, homes, urls) in sorted(sources.items()):
            if kind in NOT_PUBLISHERS:
                continue
            if account and site_of(account.split("/", 1)[0]) in DISCOVER_PLATFORMS:
                self.of_account.setdefault(account, source_id)
                continue
            # Its posts on the site it publishes on: a link post stored at the page it links (a
            # link blog's) is not its page.
            forms = [(publication_of(host_of(url)), shapes) for url in urls
                     if site_of(host_of(url)) in homes and (shapes := _shapes(url))]
            forms = [(pub, shapes) for pub, shapes in forms if pub and site_of(pub) not in DISCOVER_PLATFORMS]
            sections = Counter((pub, literal) for pub, (literal, _) in forms if literal)
            mine = Counter((pub, literal if literal and sections[(pub, literal)] >= SECTION_MIN else generic)
                           for pub, (literal, generic) in forms)
            on_pub = Counter(pub for pub, _ in forms)
            for (pub, shape), n in mine.items():
                if _loose(shape) and n < GENERIC_SHARE * on_pub[pub]:
                    continue   # a few pages at the site's root (/sora) don't make every root page a post
                held[(pub, shape)][source_id] += n
        self.held = {key: min(counter.items(), key=lambda item: (-item[1], item[0]))[0] for key, counter in held.items()}

    def owner(self, url: str) -> Optional[str]:
        """The source whose post page this address is, or None."""
        found = self.page(url)
        return found[0] if found else None

    def page(self, url: str) -> Optional[Tuple[str, str]]:
        """(the source whose post page this address is, the page's address), or None. A query the
        source's post pages don't have (a referral's ?r=…) is no part of the page: the address is
        the page's without it, so a stored post at that page is the same page."""
        url = normalize_url(url) or ""
        host = host_of(url)
        if not host:
            return None
        if site_of(host) in DISCOVER_PLATFORMS:   # a tweet on any host is normalized to x.com
            key = discover_address(url)[0]
            found = self.of_account.get(key) if key and _platform_post(url) else None
            return (found, url) if found else None
        found = self._held(url, host)
        if found is None and urlsplit(url).query:
            url = urlsplit(url)._replace(query="").geturl()
            found = self._held(url, host)
        return (found, url) if found else None

    def _held(self, url: str, host: str) -> Optional[str]:
        shapes = _shapes(url)
        if shapes is None:
            return None
        literal, generic = shapes
        pub = publication_of(host)
        found = self.held.get((pub, literal)) if literal else None
        if found is None and not (_loose(generic) and REFERENCE.search(urlsplit(url).path.lower())):
            found = self.held.get((pub, generic))   # not a docs, pricing or product page by a loose shape
        return found


__all__ = ["NOT_POST", "OwnPages", "own_links", "signature_links"]
