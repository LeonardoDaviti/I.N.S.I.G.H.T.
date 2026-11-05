"""Follow a site where your sources' links point (issue 0060).

    found = await follow(http, registry, "https://claude.com", linked)
    found["start"]   # "https://claude.com/blog": 95% of the linked articles are under /blog/
    found["pages"]   # [{url: .../resources/articles, prefix, found, holds: 26, ...}, ...]

`linked` are the site's article addresses your sources linked (StoriesRepository.linked_articles,
normalized as post_links keeps them). With none, Follow behaves as before (issues 0041, 0047).

1. Where to start. For a home page, when SECTION_SHARE of the linked articles share a first path
   segment that is not a date or a number (/blog/, not /2026/), the finder starts at that section
   (it follows its redirect, /blog -> /resources/articles/): a feed there first, with the
   feeds the home page names beside it (a newspaper's tech feed may hold fewer of the links
   than its feed of everything), else page watching of it, with the pages the finder read.
   A section that cannot be read, or lands on the home page, is no section: the finder took
   the home page's links, as before. When the section gives nothing (no feed, no page with an
   article), the pages the home page names are offered, as before: the finder read the home page
   beside the section (its feeds, and FeedFinding.home_pages / home_menu), so it is not asked again.
   Cost: the finder's requests from the section instead of the home page, the previews of the
   pages offered, at most one article fetched (step 2), and, when the section has feeds, the
   home page and its feed links once more.
2. What each finding holds: the linked articles
   - of a feed: its items read (the part the finder read to prove it), and the articles under
     the section its items share (a feed carries only its latest items, so its items alone
     would rank any feed below any section);
   - of a page to follow: the articles under its path, on its host.
   When no finding holds any article of the linked articles' main section, one of them is
   fetched to see where it moved (/blog/x -> /resources/articles/x), and the linked articles are
   read at their new address too: the one extra request.
3. The ranking: the most held first; a tie goes to the narrower path (/resources/articles/ over
   /resources/); then the order the finder or the preview gave. No site and no word is named.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.ingestion import feed_finder
from insight_core.ingestion.feed_finder import FeedFinding, find_feeds
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import KindRegistry, page_watch
from insight_core.ingestion.kinds.parsing import web_address
from insight_core.utils.addresses import host_of, same_site
from insight_core.utils.post_links import NUMBERISH, SECTION_MIN, SECTION_SHARE
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.ingestion.where_linked")

SAMPLE_BYTES = 16 * 1024    # an article fetched to see where it moved: only its final address is used

Place = Tuple[str, str]     # (host without www., path prefix ending in "/")
Move = Tuple[Place, Place]  # the linked articles under the first now live under the second


def _split(url: str) -> Optional[Tuple[str, List[str]]]:
    """(host without www., path segments) of the normalized address; None for a malformed one."""
    normalized = normalize_url(url)
    if not normalized:
        return None
    parsed = urllib.parse.urlparse(normalized)
    return (parsed.hostname or "").lower(), [segment for segment in parsed.path.split("/") if segment]


def on_site(address: str, linked: Iterable[str]) -> List[str]:
    """The linked articles on the address's host (www. aside), normalized, once each."""
    here = _split(address)
    out: List[str] = []
    for url in linked:
        parts = _split(url)
        if here and parts and parts[0] == here[0] and parts[1]:
            out.append(normalize_url(url) or url)
    return list(dict.fromkeys(out))


def main_section(articles: Sequence[str]) -> Optional[Tuple[str, int]]:
    """(the first segment most articles share, how many), not a date or a number, the articles
    one or more segments under it; None when no article is under a section."""
    firsts = Counter(parts[1][0] for url in articles if (parts := _split(url)) and len(parts[1]) >= 2
                     and not NUMBERISH.match(parts[1][0]))
    return firsts.most_common(1)[0] if firsts else None


def start_section(address: str, articles: Sequence[str]) -> Optional[str]:
    """For a home page: its section that SECTION_SHARE of the articles are under, as an address
    (https://claude.com/blog); None otherwise (a newspaper by date, articles at the root)."""
    if not articles or not page_watch.is_home(address):
        return None
    found = main_section(articles)
    if not found or found[1] < max(SECTION_MIN, SECTION_SHARE * len(articles)):
        return None
    parsed = urllib.parse.urlparse(web_address(address, "An address is needed"))
    return f"{parsed.scheme}://{parsed.netloc}/{found[0]}"


def _under(url: str, place: Place, shapes: Optional[Set[str]] = None) -> bool:
    """Whether url is under the place; at a host's root, with shapes, only an address of one of
    those shapes (see _shape)."""
    parts = _split(url)
    if not parts or parts[0] != place[0]:
        return False
    path = "/" + "/".join(parts[1]) + "/"
    if shapes is not None and place[1] == "/" and _shape(parts[1]) not in shapes:
        return False
    return path.startswith(place[1]) and path != place[1]


def _shape(segments: Sequence[str]) -> str:
    """What an address's first segment is: "#" a date or a number, "" the article itself (at
    the root), else the segment: a feed of /2026/10/x holds /2025/01/y, not /pricing/plans."""
    if len(segments) <= 1:
        return ""
    return "#" if NUMBERISH.match(segments[0]) else segments[0]


def _depth(prefix: str) -> int:
    return len([segment for segment in prefix.split("/") if segment])


def feed_shapes(items: Sequence[str]) -> Set[str]:
    """The shapes of a feed's items (_shape): what its root place holds."""
    return {_shape(parts[1]) for url in items if (parts := _split(url))}


def feed_place(items: Sequence[str]) -> Optional[Place]:
    """The section a feed's items share: their most common host, and the longest path prefix
    their directories share, cut before a date or a number (/2026/10/ is a day, not a section).
    At the root, it holds only the shapes of its items (feed_shapes)."""
    split = [parts for url in items if (parts := _split(url))]
    if not split:
        return None
    host = Counter(parts[0] for parts in split).most_common(1)[0][0]
    common: Optional[List[str]] = None
    for _, segments in (parts for parts in split if parts[0] == host):
        directory = []
        for segment in segments[:-1]:
            if NUMBERISH.match(segment):
                break
            directory.append(segment)
        common = directory if common is None else common[:_shared(common, directory)]
    path = "/".join(common or [])
    return host, f"/{path}/" if path else "/"


def _shared(a: Sequence[str], b: Sequence[str]) -> int:
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n


def moved(sample: str, landed: str) -> Optional[Move]:
    """Where a linked article's section moved, from where it landed: /blog/x -> /resources/articles/x
    is (/blog/, /resources/articles/). None when it did not move or the page is another one."""
    a, b = _split(sample), _split(landed)
    if not a or not b or a == b:
        return None
    common = 0
    while common < min(len(a[1]), len(b[1])) and a[1][-1 - common] == b[1][-1 - common]:
        common += 1
    if not common:          # it landed on another page (a home page, a sign-in): no move known
        return None
    old, new = a[1][:len(a[1]) - common], b[1][:len(b[1]) - common]
    return (a[0], "/" + "".join(f"{s}/" for s in old)), (b[0], "/" + "".join(f"{s}/" for s in new))


def _moved_to(url: str, move: Optional[Move]) -> Optional[str]:
    if not move or not _under(url, move[0]):
        return None
    parts = _split(url)
    assert parts is not None
    rest = parts[1][_depth(move[0][1]):]
    return f"https://{move[1][0]}{move[1][1]}{'/'.join(rest)}"


def holds(articles: Sequence[str], *, place: Optional[Place] = None, items: Sequence[str] = (),
          move: Optional[Move] = None) -> int:
    """How many of the articles a finding holds: one of its items, or under its place (with
    items, a feed: at the root, only the shapes of its items); each article as linked or, when
    its section moved, at its new address."""
    exact: Set[str] = {normalize_url(item) or item for item in items}
    shapes = feed_shapes(items) if items else None

    def held(url: Optional[str]) -> bool:
        return bool(url) and (url in exact or (place is not None and _under(url, place, shapes)))

    return sum(1 for url in articles if held(url) or held(_moved_to(url, move)))


def page_place(offer: Dict[str, Any]) -> Optional[Place]:
    """A page offer's place: its articles' host (where the preview landed), and its prefix."""
    url = offer["items"][0]["url"] if offer.get("items") else offer["url"]
    parts = _split(url)
    return (parts[0], page_watch.normalise_prefix(offer.get("prefix"))) if parts else None


def feed_row(feed: feed_finder.Feed, **more: Any) -> Dict[str, Any]:
    """A feed as the answer lists it: {url, title}, and `moved_to` when its posts now live on another
    site (issue 0108: the site, "blog.example")."""
    return {"url": feed.url, "title": feed.title, **({"moved_to": feed.moved_to} if feed.moved_to else {}), **more}


def rank(articles: Sequence[str], feeds: Sequence[feed_finder.Feed], pages: Sequence[Dict[str, Any]],
         move: Optional[Move] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """The feeds ({url, title, holds}) and the pages ({..., holds}), each the most held first,
    a tie to the narrower path, then in the order given."""
    feed_rows = []
    for order, feed in enumerate(feeds):
        place = feed_place(feed.items)
        feed_rows.append((feed_row(feed, holds=holds(articles, place=place, items=feed.items, move=move)),
                          _depth(place[1]) if place else 0, order))
    page_rows = []
    for order, offer in enumerate(pages):
        place = page_place(offer)
        page_rows.append(({**offer, "holds": holds(articles, place=place, move=move)},
                          _depth(place[1]) if place else 0, order))
    key = lambda row: (-row[0]["holds"], -row[1], row[2])  # noqa: E731
    return [row[0] for row in sorted(feed_rows, key=key)], [row[0] for row in sorted(page_rows, key=key)]


async def where_moved(http: KindHttp, articles: Sequence[str], feeds: Sequence[feed_finder.Feed],
                      pages: Sequence[Dict[str, Any]]) -> Optional[Move]:
    """When no finding holds any article of the main section, one of them is fetched: where it
    landed says where the section moved. None otherwise, or when it cannot be read."""
    found = main_section(articles)
    if not found:
        return None
    section = [url for url in articles if (parts := _split(url)) and len(parts[1]) >= 2 and parts[1][0] == found[0]]
    ranked_feeds, ranked_pages = rank(section, feeds, pages)
    if any(row["holds"] for row in (*ranked_feeds, *ranked_pages)) or not (ranked_feeds or ranked_pages):
        return None
    sample = section[0]
    try:
        _, landed = await asyncio.wait_for(http.get_start(sample, SAMPLE_BYTES), feed_finder.REQUEST_TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001 - no answer: no move known
        logger.info("Where linked: %s could not be read (%s)", sample, type(exc).__name__)
        return None
    return moved(sample, landed)


def _others(found: Sequence[feed_finder.Feed], more: Sequence[feed_finder.Feed]) -> List[feed_finder.Feed]:
    """The feeds of more not in found: by address, or by their first item (one feed at two
    addresses, /feed and www./feed/)."""
    urls = {normalize_url(feed.url) for feed in found}
    firsts = {feed.items[0] for feed in found if feed.items}
    return [feed for feed in more if normalize_url(feed.url) not in urls and not (feed.items and feed.items[0] in firsts)]


async def follow(http: KindHttp, registry: KindRegistry, url: str, linked: Sequence[str]) -> Dict[str, Any]:
    """POST /api/sources/find-feed's answer: {status, feeds, homepage, pages, linked, start}.
    ValueError for an empty address."""
    address = web_address(url, "An address is needed to look for its feed")
    home = page_watch.is_home(address)
    articles = on_site(address, linked)
    start = start_section(address, articles)
    finding: FeedFinding = await find_feeds(http, registry, start or address)
    pages: List[Dict[str, Any]] = []
    # A section that cannot be read (or lands on the home page, or another site) is no section:
    # the finder took the home page's links and feeds, as for the home page.
    read = (bool(finding.landed) and same_site(host_of(normalize_url(finding.landed)), host_of(normalize_url(address)))
            and not page_watch.is_home(finding.landed))
    if start and not read:
        start = None
        if finding.status == "none" and home:
            pages = await page_watch.offers(http, finding.pages, finding.menu)
    elif start and finding.status == "none":
        pages = await page_watch.offers(http, [finding.landed, *finding.pages], finding.menu)
        if not pages:
            # The section gave nothing to follow: the pages the home page names (read beside
            # the section, its feeds already looked for), as for the home page.
            logger.info("Where linked: %s gave nothing; the pages %s names instead", start, address)
            tried = {p.rstrip("/") for p in (start, finding.landed, *finding.pages, *finding.menu)}
            pages = await page_watch.offers(http, [p for p in finding.home_pages if p.rstrip("/") not in tried],
                                            [p for p in finding.home_menu if p.rstrip("/") not in tried])
            start = None
    elif finding.status == "none" and home:
        pages = await page_watch.offers(http, finding.pages, finding.menu)
    found = list(finding.feeds)
    if start and found:
        # The section's feeds beside the home page's own: the narrower is not always the one
        # holding the most (a newspaper's tech feed and its feed of everything).
        found += _others(found, await feed_finder.page_feeds(http, address))
    feeds = [feed_row(feed) for feed in found]
    if articles:
        move = await where_moved(http, articles, found, pages)
        feeds, pages = rank(articles, found, pages, move)
    return {"status": finding.status, "feeds": feeds, "homepage": finding.status == "none" and home,
            "pages": pages, "linked": len(articles), "start": start}


__all__ = ["follow", "start_section", "holds", "feed_place", "moved", "rank", "on_site", "main_section"]
