"""A feed address that can also be read another way, when its own host fails: the one place that says so.

Today: hnrss.org's Hacker News feeds. hnrss is a thin layer over Hacker News' search API (Algolia's search_by_date,
github.com/hnrss/hnrss: params.go, handlers.go, algolia.go, rss.go): an address's path picks the tags (/newest
"(story,poll)", /frontpage "front_page" within the past week, /ask "ask_hn", /show "show_hn"), its points= and
comments= are minimums at the time of the read (numericFilters), q= a quoted title search, count= the page size (at
most 100; none: Algolia's 20). `alternate` maps such an address to the same search; `read_instead` asks it and
renders the answer as the document hnrss would have served (`hnrss_document`): each item's link the story's address,
else its HN item page, its guid and comments the HN item page, its date the story's. The same parser then reads it
(kinds/parsing.parse_feed_posts), so every post has the address, title and date it has from hnrss: a story read
while hnrss is down is the same post when hnrss returns.

Only on failure: the address the owner added stays the one read (with its conditional 304s), and a fetch that read
through the alternate says so in its warning. Requests go through the caller's KindHttp (the app's User-Agent).
Pure but for that one GET; no database.
"""
from __future__ import annotations

import html
import logging
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from typing import Any, Callable, Dict, List, Mapping, Optional
from xml.sax.saxutils import escape, quoteattr

logger = logging.getLogger("insight.ingestion.feed_alternates")

HNRSS_HOSTS = frozenset({"hnrss.org", "www.hnrss.org"})
ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search_by_date?"
HN_ITEM = "https://news.ycombinator.com/item?id="
HITS_LIMIT = 100           # hnrss's HitsPerPageLimit
HITS_ON_BAD_COUNT = 20     # hnrss's page size for a count= that is no number
FRONT_PAGE_DAYS = 7        # /frontpage: stories created within the past week (hnrss's workaround for stale tags)

# path -> (Algolia tags, the feed's title, its link): hnrss's handlers
_ENDPOINTS: Dict[str, tuple] = {
    "/newest": ("(story,poll)", "Newest", "https://news.ycombinator.com/newest"),
    "/frontpage": ("front_page", "Front Page", "https://news.ycombinator.com/"),
    "/ask": ("ask_hn", "Ask HN", "https://news.ycombinator.com/ask"),
    "/show": ("show_hn", "Show HN", "https://news.ycombinator.com/shownew"),
}


@dataclass(frozen=True)
class Alternate:
    """How an address is also read: the request, who answers it, and how its answer becomes the address's
    document (render(answer text) -> the feed text)."""
    url: str
    host: str
    name: str                                   # the reader's name for the line ("Hacker News' search")
    render: Callable[[str], str]


@dataclass(frozen=True)
class AlternateRead:
    text: str          # the document, as the address itself would have answered
    line: str          # the fetch's warning: why and through what it was read


def alternate(url: str, *, now: Optional[datetime] = None) -> Optional[Alternate]:
    """How the address can also be read, else None (an address no alternate reads)."""
    return _hnrss(url, now or datetime.now(timezone.utc))


async def read_instead(http: Any, url: str, error: BaseException, *,
                       now: Optional[datetime] = None) -> Optional[AlternateRead]:
    """The address read through its alternate after its own read failed with `error`; None when it has none or
    the alternate failed too (the caller raises its own error: the source's failure stays the address's)."""
    other = alternate(url, now=now)
    if other is None:
        return None
    try:
        body, _ = await http.get_text(other.url)
        text = other.render(body)
    except Exception as exc:  # noqa: BLE001 - the address's own failure is the one reported
        logger.warning("%s failed (%s) and %s failed too: %s", url, _why(error), other.host, exc)
        return None
    logger.info("%s failed (%s): read from %s instead", url, _why(error), other.host)
    return AlternateRead(text, f"{_host(url)} {_why(error)}: read from {other.name} ({other.host}) instead")


def _why(error: BaseException) -> str:
    status = getattr(error, "status", None)
    if status:
        return f"answered HTTP {status}"
    if getattr(error, "timed_out", False):
        return "did not answer in time"
    return f"failed ({str(error)[:120] or type(error).__name__})"


def _host(url: str) -> str:
    return (urllib.parse.urlsplit(url).hostname or url).lower()


# --------------------------------------------------------------------------- hnrss.org from Algolia

def _hnrss(url: str, now: datetime) -> Optional[Alternate]:
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    if (parts.hostname or "").lower() not in HNRSS_HOSTS:
        return None
    endpoint = _ENDPOINTS.get(parts.path.rstrip("/") or "/")
    if endpoint is None:
        return None          # .atom, .jsonfeed, users, items, comments: hnrss's own
    tags, name, link = endpoint
    form = {k: v[0] for k, v in urllib.parse.parse_qs(parts.query, keep_blank_values=True).items()}
    params = algolia_params(form, tags, now)
    query = form.get("q", "")
    title = f'Hacker News - {name}: "{query}"' if query else f"Hacker News: {name}"
    return Alternate(ALGOLIA_SEARCH + urllib.parse.urlencode(params), "hn.algolia.com", "Hacker News' search",
                     lambda body: hnrss_document(body, title=title, link=link, self_link=url,
                                                 link_to=form.get("link", ""),
                                                 description=form.get("description", "") != "0"))


def algolia_params(form: Mapping[str, str], tags: str, now: datetime) -> Dict[str, str]:
    """hnrss's SearchParams.Values for a request's query string (`form`) and its endpoint's tags."""
    params: Dict[str, str] = {}
    query = form.get("q", "")
    if " OR " in query:
        words = " ".join(f'"{word}"' for word in query.replace(" OR ", " ").split())
        params["query"], params["optionalWords"] = words, words
    elif query:
        params["query"] = f'"{query}"'
    filters: List[str] = []
    if form.get("points"):
        filters.append(f"points>={form['points']}")
    if form.get("comments"):
        filters.append(f"num_comments>={form['comments']}")
    if tags == "front_page":
        filters.append(f"created_at_i>={int((now - timedelta(days=FRONT_PAGE_DAYS)).timestamp())}")
    if filters:
        params["numericFilters"] = ",".join(filters)
    attrs = form.get("search_attrs") or "title"
    if attrs != "default":
        params["restrictSearchableAttributes"] = attrs
    if form.get("count"):
        try:
            params["hitsPerPage"] = str(min(int(form["count"]), HITS_LIMIT))
        except ValueError:
            params["hitsPerPage"] = str(HITS_ON_BAD_COUNT)
    params["tags"] = tags
    return params


def _cdata(text: str) -> str:
    """Go's xml cdata: a "]]>" inside is split across two sections."""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def _description(hit: Mapping[str, Any], permalink: str) -> str:
    """hnrss's GetDescription for a story (algolia.go)."""
    story_text = hit.get("story_text") or ""
    tail = (f'<p>Comments URL: <a href="{permalink}">{permalink}</a></p>\n'
            f"<p>Points: {hit.get('points') or 0}</p>\n<p># Comments: {hit.get('num_comments') or 0}</p>\n")
    if story_text:
        return f"\n<p>{html.unescape(story_text)}</p>\n<hr>\n{tail}"
    article = hit.get("url") or ""
    return "\n" + (f'<p>Article URL: <a href="{article}">{article}</a></p>' if article else "") + "\n" + tail


def _created(hit: Mapping[str, Any]) -> datetime:
    when = hit.get("created_at_i")
    if isinstance(when, (int, float)):
        return datetime.fromtimestamp(when, timezone.utc)
    try:
        return datetime.strptime(str(hit.get("created_at")), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        try:
            return datetime.strptime(str(hit.get("created_at")), "%Y-%m-%dT%H:%M:%S.%f%z").replace(microsecond=0)
        except ValueError:
            return datetime.now(timezone.utc).replace(microsecond=0)   # hnrss: UTCNow()


def hnrss_document(body: str, *, title: str, link: str, self_link: str, link_to: str = "",
                   description: bool = True) -> str:
    """The RSS hnrss serves for an Algolia search_by_date answer (rss.go NewRSS). Raises ValueError for an answer
    that is no search answer."""
    import json

    answer = json.loads(body)
    hits = answer.get("hits") if isinstance(answer, dict) else None
    if not isinstance(hits, list):
        raise ValueError("Hacker News' search answered no hits")
    items = []
    for hit in hits:
        if not isinstance(hit, dict) or not str(hit.get("objectID") or "").isdigit():
            continue
        permalink = HN_ITEM + str(hit["objectID"])
        target = hit.get("url") if (link_to or "url") == "url" and hit.get("url") else permalink
        items.append(
            "<item>"
            f"<title>{_cdata(html.unescape(str(hit.get('title') or '')))}</title>"
            + (f"<description>{_cdata(_description(hit, permalink))}</description>" if description else "")
            + f"<pubDate>{format_datetime(_created(hit))}</pubDate>"
            f"<link>{escape(target)}</link>"
            f"<dc:creator>{escape(str(hit.get('author') or ''))}</dc:creator>"
            f"<comments>{escape(permalink)}</comments>"
            f'<guid isPermaLink="false">{escape(permalink)}</guid>'
            "</item>")
    return ('<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:atom="http://www.w3.org/2005/Atom">'
            f"<channel><title>{escape(title)}</title><link>{escape(link)}</link>"
            "<description>Hacker News RSS</description><docs>https://hnrss.org/</docs>"
            "<generator>INSIGHT (hnrss's document, from hn.algolia.com)</generator>"
            f'<atom:link href={quoteattr(self_link)} rel="self" type="application/rss+xml"></atom:link>'
            + "".join(items) + "</channel></rss>")
