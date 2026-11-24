"""forum: one board of a forum (a category, a tag, a subforum), its threads as posts (issue 0280 D1).

One reader for every forum software in SOFTWARE, by what the software itself publishes, never by the site:
  discourse  a category's, tag's or the latest topics' RSS (`/c/<slug>/<id>.rss`, `/tag/<t>.rss`, `/latest.rss`):
             each topic's first post whole, its "N posts - M participants / Read full topic" trailer cut.
  flarum     the JSON:API discussions of a tag (`/api/discussions?filter[tag]=<slug>`), newest first, with each
             discussion's first post.
  fluxbb     a forum's Atom feed (`/extern.php?action=feed&type=atom&fid=<id>`), read in posting order so each
             entry is its topic's first post (FluxBB and PunBB).
A source's address is the board's (what `board_of` reads); the feed finder offers them (`detect` tells the software
from a forum's page, `boards` lists its boards). A thread is a post: its address the thread's page, its text the
first message, metadata.forum {software, thread, replies} — the thread's replies are its discussion
(ingestion/discussions.py, the same software keys). A feed document that does not say it is the software's (the
Discourse namespace, FluxBB's or PunBB's generator) is read as a plain feed: its posts carry no metadata.forum.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    PolitenessProfile,
    RateLimit,
    ReadCheck,
    Source,
    resume_counts,
)
from insight_core.utils.content_fingerprints import strip_html

SOFTWARE = ("discourse", "flarum", "fluxbb")
PAGE_SIZE = 50                 # Flarum's most discussions a page; FluxBB's most entries a feed
MAX_BOARDS = 40                # boards the finder offers, at most
FORUM_PROFILE = PolitenessProfile(concurrency_pool="host-lock", page_delay_s=2)

# what a forum's own page says about its software
_DETECT = (
    ("discourse", re.compile(r"""<meta\s+name=["']generator["']\s+content=["']Discourse\b""", re.I)),
    ("flarum", re.compile(r"""id=["']flarum-(?:json-payload|loading)["']""", re.I)),
    ("fluxbb", re.compile(r"""Powered by\s*<a\s[^>]*href=["']https?://(?:www\.)?(?:fluxbb|punbb)\.(?:org|informer\.com)""", re.I)),
)
_DISCOURSE_FEED = re.compile(r"^(?P<base>.*?)/(?:c/(?:[^/]+/)*\d+|tag/[^/]+|latest)\.rss$")
_DISCOURSE_TOPIC = re.compile(r"/t/(?:[^/]+/)?(\d+)(?:/\d+)?/?$")
_DISCOURSE_TRAILER = re.compile(r"(?is)\s*<p>\s*<small>\s*\d+\s+posts?\s*-\s*\d+\s+participants?\s*</small>\s*</p>"
                                r"\s*<p>\s*<a\s[^>]*>\s*Read full topic\s*</a>\s*</p>\s*$")
_DISCOURSE_POSTS = re.compile(r"(?is)<small>\s*(\d+)\s+posts?\s*-")
_FLUX_TOPIC = re.compile(r"[?&]id=(\d+)")


@dataclass(frozen=True)
class Board:
    software: str
    base: str                  # the forum's address (scheme, host, folder), no trailing "/"
    address: str               # the source's address
    tag: Optional[str] = None  # Flarum: the tag's slug (None: every discussion)


def _parts(url: str) -> Optional[urllib.parse.SplitResult]:
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return None
    return parts if parts.scheme in ("http", "https") and parts.hostname else None


def board_of(url: Optional[str]) -> Optional[Board]:
    """The board a source address names, by the software's own listing shapes, else None."""
    parts = _parts(url or "")
    if parts is None:
        return None
    origin = f"{parts.scheme}://{parts.netloc}"
    query = urllib.parse.parse_qs(parts.query)
    path = parts.path.rstrip("/")
    if path.endswith("/api/discussions"):
        tag = (query.get("filter[tag]") or [None])[0]
        return Board("flarum", origin + path[: -len("/api/discussions")], url, tag or None)
    if path.endswith("/extern.php") and (query.get("action") or [""])[0] == "feed" and "tid" not in query:
        return Board("fluxbb", origin + path[: -len("/extern.php")], url)
    m = _DISCOURSE_FEED.match(path)
    if m:
        return Board("discourse", origin + m.group("base"), url)
    return None


def detect(page: str) -> Optional[str]:
    """The forum software a page says it runs (SOFTWARE), else None."""
    head = page[:400_000]
    return next((name for name, pattern in _DETECT if pattern.search(head)), None)


# ---- the posts ------------------------------------------------------------------------------------

def _forum(software: str, thread: str, replies: Optional[int]) -> Dict[str, Any]:
    return {"software": software, "thread": thread, **({"replies": replies} if isinstance(replies, int) else {})}


def _feed_authors(doc: str) -> Dict[str, List[str]]:
    """{item address: its authors} of a feed (an item's dc:creator, an entry's author), which the feed parser keeps
    for RSS 1.0 only."""
    try:
        root, _broken = parsing.read_feed(doc)
    except Exception:  # noqa: BLE001 - no authors: the posts as parsed
        return {}
    out: Dict[str, List[str]] = {}
    for node in root.iter():
        if parsing.local_name(node.tag) not in ("item", "entry"):
            continue
        link = parsing.child_text(node, "link") or next(
            (c.attrib.get("href") for c in node if parsing.local_name(c.tag) == "link" and c.attrib.get("href")), None)
        names = [n for c in node if parsing.local_name(c.tag) in ("creator", "author")
                 for n in parsing.element_authors(c)]
        if link and names:
            out[parsing.normalize_feed_urls(link.strip())] = list(dict.fromkeys(names))
    return out


def _tag(post: Dict[str, Any], authors: Dict[str, List[str]], forum: Optional[Dict[str, Any]]) -> None:
    names = authors.get(post.get("url") or "")
    post["metadata"] = {**(post.get("metadata") or {}), **({"authors": names} if names else {}),
                        **({"forum": forum} if forum else {})}


def discourse_posts(doc: str, source_url: str) -> List[Dict[str, Any]]:
    """A Discourse RSS document's topics: the first post whole (the trailer cut), the replies counted from it."""
    posts = parsing.parse_feed_posts(doc, source_url)
    ours = "discourse.org" in doc[:2000]
    authors = _feed_authors(doc)
    for post in posts:
        markup = post.get("content_html") or ""
        count = _DISCOURSE_POSTS.search(markup[-600:])
        cut = _DISCOURSE_TRAILER.sub("", markup)
        post["content_html"], post["content"] = cut, strip_html(cut)
        m = _DISCOURSE_TOPIC.search(urllib.parse.urlsplit(post.get("url") or "").path)
        _tag(post, authors, _forum("discourse", m.group(1), int(count.group(1)) - 1 if count else None)
             if ours and m else None)
    return posts


def fluxbb_posts(doc: str, source_url: str) -> List[Dict[str, Any]]:
    """A FluxBB/PunBB Atom document's topics (read in posting order: each entry its topic's first post)."""
    posts = parsing.parse_feed_posts(doc, source_url)
    ours = re.search(r"<generator[^>]*>\s*(?:FluxBB|PunBB)", doc[:3000], re.I) is not None
    authors = _feed_authors(doc)
    for post in posts:
        m = _FLUX_TOPIC.search("?" + urllib.parse.urlsplit(post.get("url") or "").query)
        _tag(post, authors, _forum("fluxbb", m.group(1), None) if ours and m and "viewtopic" in (post.get("url") or "")
             else None)
    return posts


def flarum_posts(payload: Dict[str, Any], board: Board) -> List[Dict[str, Any]]:
    """A Flarum discussions page (with firstPost, user and tags included): each discussion, its first post the text."""
    included = {(i.get("type"), i.get("id")): i.get("attributes") or {}
                for i in payload.get("included") or [] if isinstance(i, dict)}
    out: List[Dict[str, Any]] = []
    for d in payload.get("data") or []:
        if not isinstance(d, dict) or d.get("type") != "discussions":
            continue
        a, rel = d.get("attributes") or {}, d.get("relationships") or {}
        first = ((rel.get("firstPost") or {}).get("data") or {}).get("id")
        user = ((rel.get("user") or {}).get("data") or {}).get("id")
        markup = (included.get(("posts", first)) or {}).get("contentHtml") or ""
        who = included.get(("users", user)) or {}
        name = who.get("displayName") or who.get("username")
        tags = [included.get(("tags", t.get("id")), {}).get("name") for t in (rel.get("tags") or {}).get("data") or []
                if isinstance(t, dict)]
        slug = a.get("slug") or str(d.get("id"))
        count = a.get("commentCount")
        out.append({
            "platform": "rss",
            "source": board.address,
            "url": f"{board.base}/d/{slug}",
            "guid": f"{board.base}/d/{d.get('id')}",
            "title": " ".join(str(a.get("title") or "").split()),
            "content": strip_html(markup),
            "content_html": markup,
            "date": parsing.parse_datetime_value(a.get("createdAt")),
            "date_precision": parsing.date_precision(a.get("createdAt")),
            "media_urls": [],
            "categories": [t for t in tags if t],
            "metadata": {"forum": _forum("flarum", str(d.get("id")), count - 1 if isinstance(count, int) else None),
                         **({"authors": [name]} if name else {})},
        })
    return out


def flarum_url(board: Board, offset: int = 0, limit: int = PAGE_SIZE) -> str:
    params = {"sort": "-createdAt", "include": "firstPost,user,tags", "page[limit]": str(max(1, min(PAGE_SIZE, limit))),
              "page[offset]": str(offset)}
    if board.tag:
        params["filter[tag]"] = board.tag
    return f"{board.base}/api/discussions?{urllib.parse.urlencode(params)}"


def feed_url(board: Board, limit: int = PAGE_SIZE) -> str:
    """The board's feed as read: FluxBB in posting order (each entry a topic's first post), its most entries."""
    if board.software != "fluxbb":
        return board.address
    parts = urllib.parse.urlsplit(board.address)
    query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k not in ("order", "show")]
    query += [("order", "posted"), ("show", str(max(1, min(PAGE_SIZE, limit))))]
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


# ---- the boards a forum offers (the feed finder) -----------------------------------------------------

def _title(page: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", page)
    return " ".join(strip_html(m.group(1)).split()) if m else ""


def forum_name(page: str) -> str:
    """The forum's own name: its og:site_name, else its page title's last part ("Announcements - X Forum": X Forum)."""
    m = re.search(r"""<meta\s+property=["']og:site_name["']\s+content=["']([^"']+)["']""", page, re.I)
    if m:
        return " ".join(strip_html(m.group(1)).split())
    return re.split(r"\s+[-/|·]\s+", _title(page))[-1].strip()


def base_of(software: str, page: str, here: str) -> str:
    """The forum's address from its page: Flarum's payload baseUrl, Discourse's search description's folder,
    FluxBB's page folder; else the page's origin."""
    parts = urllib.parse.urlsplit(here)
    origin = f"{parts.scheme}://{parts.netloc}"
    if software == "flarum":
        m = re.search(r'"baseUrl"\s*:\s*"([^"]+)"', page)
        if m:
            return m.group(1).replace("\\/", "/").rstrip("/")
    if software == "discourse":
        m = re.search(r"""<link[^>]*opensearchdescription[^>]*href=["']([^"']+)/opensearch\.xml["']""", page)
        if m and m.group(1).startswith(("http://", "https://")):
            return m.group(1).rstrip("/")
    if software == "fluxbb":
        folder, last = parts.path.rsplit("/", 1) if "/" in parts.path else ("", parts.path)
        return origin + (folder if "." in last else parts.path.rstrip("/"))   # a script's folder (viewforum.php)
    return origin


def page_board(software: str, base: str, here: str) -> Optional[str]:
    """The board the page itself is (a category, tag or subforum page), as a source address; else None."""
    path = urllib.parse.urlsplit(here).path.rstrip("/")
    tail = path[len(urllib.parse.urlsplit(base).path.rstrip("/")):]
    if software == "discourse":
        m = re.match(r"^/(c/(?:[^/]+/)*\d+|tag/[^/]+)(?:/l/[a-z]+)?$", tail)
        return f"{base}/{m.group(1)}.rss" if m else None
    if software == "flarum":
        m = re.match(r"^/t/([^/]+)$", tail)
        return f"{base}/api/discussions?filter[tag]={m.group(1)}" if m else None
    if software == "fluxbb" and tail.endswith("/viewforum.php"):
        fid = urllib.parse.parse_qs(urllib.parse.urlsplit(here).query).get("id", [""])[0]
        return f"{base}/extern.php?action=feed&type=atom&fid={fid}" if fid.isdigit() else None
    return None


def board_list_url(software: str, base: str) -> Optional[str]:
    """The one GET that lists a forum's boards (FluxBB: its index page)."""
    return {"discourse": f"{base}/categories.json?include_subcategories=true", "flarum": f"{base}/api/tags",
            "fluxbb": f"{base}/index.php"}.get(software)


def boards_listed(software: str, base: str, body: str) -> List[Tuple[str, str]]:
    """[(source address, board name)] from the board list's answer, in the forum's own order, everything first."""
    out: List[Tuple[str, str]] = []
    if software == "discourse":
        out.append((f"{base}/latest.rss", "Latest"))
        try:
            cats = (json.loads(body).get("category_list") or {}).get("categories") or []
        except (ValueError, AttributeError):
            cats = []
        for c in cats:
            if not isinstance(c, dict) or not c.get("id"):
                continue
            out.append((f"{base}/c/{c.get('slug') or c['id']}/{c['id']}.rss", str(c.get("name") or c.get("slug"))))
            for s in c.get("subcategory_list") or []:
                if isinstance(s, dict) and s.get("id"):
                    out.append((f"{base}/c/{c.get('slug')}/{s.get('slug') or s['id']}/{s['id']}.rss",
                                f"{c.get('name')} / {s.get('name')}"))
    elif software == "flarum":
        out.append((f"{base}/api/discussions", "All discussions"))
        try:
            tags = json.loads(body).get("data") or []
        except (ValueError, AttributeError):
            tags = []
        rows = [t for t in tags if isinstance(t, dict) and (t.get("attributes") or {}).get("slug")]
        # primary tags (a position) in their order, then the secondary ones by size
        rows.sort(key=lambda t: (t["attributes"].get("position") is None, t["attributes"].get("position") or 0,
                                 -(t["attributes"].get("discussionCount") or 0)))
        out += [(f"{base}/api/discussions?filter[tag]={t['attributes']['slug']}", str(t["attributes"].get("name")))
                for t in rows]
    elif software == "fluxbb":
        out.append((f"{base}/extern.php?action=feed&type=atom", "Active topics"))
        for fid, name in re.findall(r"""<a\s[^>]*href=["'](?:[^"']*/)?viewforum\.php\?id=(\d+)["'][^>]*>(.*?)</a>""",
                                    body, re.I | re.S):
            out.append((f"{base}/extern.php?action=feed&type=atom&fid={fid}", " ".join(strip_html(name).split())))
    seen: set = set()
    return [row for row in out if not (row[0] in seen or seen.add(row[0]))]


def offered(software: str, base: str, here: str, page: str, listed: str) -> List[Tuple[str, str]]:
    """[(address, title)]: the page's own board first, then the forum's boards (MAX_BOARDS), each titled with the
    forum's name."""
    forum = forum_name(page)
    rows = boards_listed(software, base, listed)
    own = page_board(software, base, here)
    if own:
        rows = [r for r in rows if r[0] == own] + [r for r in rows if r[0] != own]
        if not any(r[0] == own for r in rows):
            rows.insert(0, (own, re.split(r"\s+[-/|·]\s+", _title(page))[0] or own))
    return [(url, f"{forum}: {name}" if forum and forum not in name else name) for url, name in rows[:MAX_BOARDS]]


# ---- the kind ---------------------------------------------------------------------------------------

class ForumKind(BaseKind):
    name = "forum"
    chronological = True           # newest threads first
    available_basis = "unknown"
    profile = FORUM_PROFILE

    def __init__(self, http: KindHttp) -> None:
        self.http = http

    def matches(self, source: Source) -> bool:
        return board_of(str(source.get("handle_or_url") or "")) is not None

    def _board(self, source: Source) -> Board:
        board = board_of(str(source.get("handle_or_url") or ""))
        if board is None:
            raise ValueError(f"Not a forum board address: {source.get('handle_or_url')}")
        return board

    async def _flarum(self, board: Board, offset: int, limit: int) -> Tuple[List[Dict[str, Any]], int]:
        body, _ = await self.http.get_text(flarum_url(board, offset, limit))
        payload = json.loads(body)
        return flarum_posts(payload, board), len(payload.get("data") or [])

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        board = self._board(source)
        if board.software == "flarum":
            posts, _ = await self._flarum(board, 0, limit)
            return posts[:limit]
        body, _ = await self.http.get_text(feed_url(board, limit))
        read = discourse_posts if board.software == "discourse" else fluxbb_posts
        return read(body, board.address)[:limit]

    async def test_read(self, source: Source) -> Optional[ReadCheck]:
        try:
            posts = await self.fetch_latest(source, 5)
        except Exception as exc:  # noqa: BLE001 - a failed read is the reason, never the add's error
            return ReadCheck(str(exc) or type(exc).__name__)
        return None if posts else ReadCheck("the board lists no thread")

    async def inspect(self, source: Source) -> Inspection:
        self._board(source)
        return Inspection(None, PAGE_SIZE, None)     # a board's feed or API names no total

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "forum_offset"

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        """Flarum: its discussions PAGE_SIZE a page back to the oldest; a feed board: what its feed lists (one
        page)."""
        board = self._board(source)
        if board.software != "flarum":
            yield ArchivePage((await self.fetch_latest(source, target))[:target], None)
            return
        collected, pages = resume_counts(checkpoint)
        offset = int((checkpoint or {}).get("offset") or 0)
        while collected < target:
            posts, listed = await self._flarum(board, offset, PAGE_SIZE)
            pages += 1
            offset += listed
            posts = posts[:max(0, target - collected)]
            collected += len(posts)
            done = listed < PAGE_SIZE or collected >= target
            yield ArchivePage(posts, None if done else {"mode": "forum_offset", "offset": offset,
                                                        "pages_fetched": pages, "collected_posts": collected})
            if done:
                break


__all__ = ["Board", "ForumKind", "SOFTWARE", "base_of", "board_list_url", "board_of", "detect", "discourse_posts",
           "flarum_posts", "fluxbb_posts", "forum_name", "offered", "page_board"]
