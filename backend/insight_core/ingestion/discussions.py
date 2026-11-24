"""Discussions: a post's comment thread on a discussion site, read through the site's public JSON (issue 0280).

One mechanism for every host in HOSTS, a small table: how to tell a thread's address (`thread_of`), the GETs that read
it (`requests`) and how its answer becomes comments (`parse`). Hacker News: Algolia's item endpoint gives the whole tree
in one GET, and the Firebase item gives the top-level comments in the site's own rank order (a second GET); Lobsters:
the story's `.json` gives every comment with its score. No Reddit (every server path is blocked, plan/issues/0262).

Forums (v10.47, 0280 D1): a forum thread is a post (ingestion/kinds/forum.py reads it, its first message the text)
and its replies are its discussion, by the forum software its metadata names (metadata.forum {software, thread}), on
the forum's own site: Discourse (the topic's `.json`, its first posts and every post's id, then the rest by id,
PAGE_POSTS a GET; a reply's parent its reply_to_post_number; `?print=true` is refused after a few a minute), Flarum
(the discussion's JSON:API posts, PAGE_POSTS a page; a reply's parent its first post mention) and FluxBB/PunBB (the
topic's Atom feed: its newest FEED_POSTS posts, flat). Quoted messages are cut from a reply (`unquoted`). A forum's
request host is its own site, paced by FORUM_FLOOR (`floor`); a thread reads at most MAX_PAGES GETs.

A thread is cut to CAP comments (`cap`): the top-level comments in the site's order (score, else rank), each with its
best replies (most replies under them, then the earliest), breadth first, so a long thread keeps its many voices and
the replies that drew the most discussion. A comment's text is plain (HTML read once, links kept apart in `links`),
cut to TEXT_CHARS. Pure: no database, no clock; the requests go through the caller's KindHttp and HostLimiter.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

CAP = 200                 # comments kept per thread
TOP_LEVEL = 60            # top-level comments, at most (the rest of the cap goes to their replies)
REPLIES_EACH = 4          # replies kept under a comment, at most, per level
TEXT_CHARS = 1500         # a comment's text kept
MAX_DEPTH = 4             # replies deeper than this are not kept


@dataclass(frozen=True)
class Host:
    name: str             # the reader's name ("Hacker News")
    key: str              # discussion_threads.host
    floors: Dict[str, float]   # seconds between request starts, by request host (gates.HOST_FLOORS)
    forum: bool = False   # a forum software: the thread is on the forum's own site, which names it
    text: bool = False    # its answers are documents (a feed), not JSON


HN = Host("Hacker News", "hn", {"hn.algolia.com": 1.0, "hacker-news.firebaseio.com": 1.0})
LOBSTERS = Host("Lobsters", "lobsters", {"lobste.rs": 3.0})
DISCOURSE = Host("Discourse", "discourse", {}, forum=True)
FLARUM = Host("Flarum", "flarum", {}, forum=True)
FLUXBB = Host("FluxBB", "fluxbb", {}, forum=True, text=True)
HOSTS: Dict[str, Host] = {h.key: h for h in (HN, LOBSTERS, DISCOURSE, FLARUM, FLUXBB)}
FLOORS: Dict[str, float] = {k: v for h in HOSTS.values() for k, v in h.floors.items()}
FORUM_FLOOR = 10.0        # seconds between request starts to a forum's site (a host FLOORS does not name): a FluxBB
                          # forum answered 429 after 11 requests 2 s apart and again after 7 more 5 s apart (2026-11-24);
                          # a 429 then doubles the gap (gates.HostLimiter.limited)
PAGE_POSTS = 50           # Flarum's most posts a page; Discourse's posts asked by id a GET
MAX_PAGES = 4             # a thread's pages read, at most (4 Flarum pages: CAP comments)
FEED_POSTS = 50           # FluxBB's most posts in a topic feed


def floor(host: str) -> float:
    """Seconds between request starts to a request host: its FLOORS entry, else a forum site's FORUM_FLOOR."""
    return FLOORS.get(host, FORUM_FLOOR)

_HN_ITEM = re.compile(r"^(?:www\.)?news\.ycombinator\.com$")
_LOBSTERS = re.compile(r"^/s/([a-z0-9]{4,10})(?:/|$|\.json)")


@dataclass(frozen=True)
class Thread:
    """A thread's address: its host, its id there and the page a reader opens."""
    host: str
    id: str
    url: str

    @property
    def name(self) -> str:
        """The reader's name: the host's; a forum's, its site ("www." aside)."""
        if HOSTS[self.host].forum:
            return (urlsplit(self.url).hostname or "").lower().removeprefix("www.") or HOSTS[self.host].name
        return HOSTS[self.host].name


def thread_of(url: Optional[str]) -> Optional[Thread]:
    """The thread at a page's address (news.ycombinator.com/item?id=N, lobste.rs/s/<id>), else None."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if _HN_ITEM.match(host) and parts.path == "/item":
        got = (parse_qs(parts.query).get("id") or [""])[0]
        return Thread("hn", got, f"https://news.ycombinator.com/item?id={got}") if got.isdigit() else None
    if host in ("lobste.rs", "www.lobste.rs"):
        m = _LOBSTERS.match(parts.path)
        return Thread("lobsters", m.group(1), f"https://lobste.rs/s/{m.group(1)}") if m else None
    return None


def forum_thread(url: Optional[str], metadata: Optional[Dict[str, Any]]) -> Optional[Thread]:
    """A forum thread's post (metadata.forum {software, thread}, set by the forum kind), else None."""
    forum = (metadata or {}).get("forum")
    if not url or not isinstance(forum, dict):
        return None
    software, tid = forum.get("software"), str(forum.get("thread") or "")
    host = HOSTS.get(software) if isinstance(software, str) else None
    if host is None or not host.forum or not tid.isdigit() or not url.startswith(("https://", "http://")):
        return None
    return Thread(host.key, tid, url)


def post_thread(url: Optional[str], metadata: Optional[Dict[str, Any]]) -> Optional[Thread]:
    """A post's discussion: a forum thread's own replies (metadata.forum), else its feed's comments address
    (metadata.comments_url) on a discussion host, else the post itself when it is a thread (an Ask HN, a Lobsters
    text story)."""
    return forum_thread(url, metadata) or thread_of((metadata or {}).get("comments_url")) or thread_of(url)


def _base(t: Thread, marker: str) -> str:
    """The forum's address its thread pages sit under: scheme, host and any folder before `marker`."""
    parts = urlsplit(t.url)
    at = parts.path.find(marker)
    return f"{parts.scheme}://{parts.netloc}{parts.path[:at] if at > 0 else ''}"


def requests(t: Thread) -> List[str]:
    """The first GETs that read a thread, in order (a forum's further pages: `more`)."""
    if t.host == "hn":
        return [f"https://hn.algolia.com/api/v1/items/{t.id}",
                f"https://hacker-news.firebaseio.com/v0/item/{t.id}.json"]
    if t.host == "discourse":
        return [f"{_base(t, '/t/')}/t/{t.id}.json"]
    if t.host == "flarum":
        return [_flarum_page(t, 0)]
    if t.host == "fluxbb":
        return [f"{_base(t, '/viewtopic.php')}/extern.php?action=feed&type=atom&tid={t.id}&show={FEED_POSTS}"]
    return [f"https://lobste.rs/s/{t.id}.json"]


def _flarum_page(t: Thread, offset: int) -> str:
    return (f"{_base(t, '/d/')}/api/posts?filter%5Bdiscussion%5D={t.id}&sort=number&include=user"
            f"&page%5Blimit%5D={PAGE_POSTS}&page%5Boffset%5D={offset}")


def _discourse_posts(answers: List[Any]) -> List[Dict[str, Any]]:
    return [p for a in answers if isinstance(a, dict) for p in (a.get("post_stream") or {}).get("posts") or []
            if isinstance(p, dict)]


def more(t: Thread, answers: List[Any]) -> Optional[str]:
    """The thread's next page after `answers`, else None, at most MAX_PAGES: Flarum's next PAGE_POSTS while each page
    is full (its own links.next drops the /api folder, so the offset is counted here); Discourse's next PAGE_POSTS
    posts of the topic's stream not read yet."""
    if t.host not in ("flarum", "discourse") or not answers or len(answers) >= MAX_PAGES:
        return None
    if t.host == "discourse":
        first = answers[0] if isinstance(answers[0], dict) else {}
        have = {p.get("id") for p in _discourse_posts(answers)}
        left = [i for i in (first.get("post_stream") or {}).get("stream") or [] if i not in have][:PAGE_POSTS]
        if not left:
            return None
        return f"{_base(t, '/t/')}/t/{t.id}/posts.json?" + "&".join(f"post_ids%5B%5D={i}" for i in left)
    last = answers[-1]
    if not isinstance(last, dict) or len(last.get("data") or []) < PAGE_POSTS:
        return None
    return _flarum_page(t, PAGE_POSTS * len(answers))


def comment_url(t: Thread, cid: str) -> str:
    """A comment's own page."""
    if t.host == "hn":
        return f"https://news.ycombinator.com/item?id={cid}"
    if t.host == "lobsters":
        return f"https://lobste.rs/c/{cid}"
    if t.host == "discourse":
        return f"{_base(t, '/t/')}/t/{t.id}/{cid}"
    if t.host == "flarum":
        return f"{_base(t, '/d/')}/d/{t.id}/{cid}"
    return f"{_base(t, '/viewtopic.php')}/viewtopic.php?pid={cid}#p{cid}"


@dataclass
class Comment:
    id: str
    parent: Optional[str]          # None: a top-level comment
    author: Optional[str]
    at: Optional[datetime]
    text: str
    score: Optional[int] = None
    replies: int = 0               # comments under it, all depths
    rank: int = 0                  # its place among its siblings in the site's order
    depth: int = 0
    links: List[str] = field(default_factory=list)


@dataclass
class Parsed:
    total: int                     # comments the site counts
    created_at: Optional[datetime]  # the thread's
    title: Optional[str]
    comments: List[Comment]        # every comment read, before the cap


# ---- text ------------------------------------------------------------------------------------------

_HREF = re.compile(r"""<a\s[^>]*?href=["']([^"']+)["']""", re.I)
_BREAK = re.compile(r"<\s*(?:p|br|/p|li|/li|pre|/pre|blockquote|/blockquote)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n\s*\n+")


def plain(markup: Optional[str]) -> Tuple[str, List[str]]:
    """(the comment's text, plain, paragraphs kept; the addresses it links, in order, once each)."""
    s = markup or ""
    hrefs = (html.unescape(u) for u in _HREF.findall(s))
    links = list(dict.fromkeys(u for u in hrefs if u.startswith(("http://", "https://"))))
    s = _TAG.sub("", _BREAK.sub("\n", s))
    s = html.unescape(s).replace("\r", "")
    lines = [re.sub(r"[ \t ]+", " ", ln).strip() for ln in s.split("\n")]
    text = _BLANKS.sub("\n", "\n".join(lines)).strip()
    return text, links


def _when(v: Any) -> Optional[datetime]:
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v, tz=timezone.utc)
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


# ---- each host's answer ------------------------------------------------------------------------------

def _hn(answers: List[Any]) -> Parsed:
    tree = answers[0] if answers and isinstance(answers[0], dict) else {}
    order = answers[1] if len(answers) > 1 and isinstance(answers[1], dict) else {}
    rank = {str(k): n for n, k in enumerate(order.get("kids") or [])}
    out: List[Comment] = []

    def walk(node: Dict[str, Any], parent: Optional[str], depth: int, n: int, at: Optional[int] = None) -> int:
        """Adds the node's comment and its replies; returns how many comments are under it. A deleted comment's
        replies take its place (`at`: its rank, for a deleted top-level comment's)."""
        cid = str(node.get("id"))
        text, links = plain(node.get("text"))
        mine = (rank.get(cid, len(rank) + n) if at is None else at) if parent is None else n
        c = Comment(cid, parent, node.get("author"), _when(node.get("created_at_i") or node.get("created_at")),
                    text, node.get("points") if isinstance(node.get("points"), int) else None,
                    rank=mine, depth=depth, links=links)
        live = bool(text) and c.author is not None     # a deleted or dead comment has no author or no text
        if live:
            out.append(c)
        under = 0
        for i, ch in enumerate(node.get("children") or []):
            if isinstance(ch, dict) and ch.get("type", "comment") == "comment":
                under += walk(ch, cid if live else parent, depth + 1 if live else depth, i,
                              None if live or parent is not None else mine)
        c.replies = under
        return under + (1 if live else 0)

    for i, ch in enumerate(tree.get("children") or []):
        if isinstance(ch, dict):
            walk(ch, None, 0, i)
    total = order.get("descendants") if isinstance(order.get("descendants"), int) else len(out)
    return Parsed(total, _when(tree.get("created_at_i") or tree.get("created_at")), tree.get("title"), out)


def _lobsters(answers: List[Any]) -> Parsed:
    story = answers[0] if answers and isinstance(answers[0], dict) else {}
    out: List[Comment] = []
    by_id: Dict[str, Comment] = {}
    for n, c in enumerate(story.get("comments") or []):
        if not isinstance(c, dict) or c.get("is_deleted") or c.get("is_moderated"):
            continue
        text, links = plain(c.get("comment") or "")
        if not text:
            continue
        parent = c.get("parent_comment")
        com = Comment(str(c.get("short_id")), str(parent) if parent else None, c.get("commenting_user"),
                      _when(c.get("created_at")), text, c.get("score") if isinstance(c.get("score"), int) else None,
                      rank=n, depth=int(c.get("depth") or 0), links=links)
        out.append(com)
        by_id[com.id] = com
    for c in reversed(out):   # replies under each comment, all depths (a parent comes before its replies)
        p = by_id.get(c.parent or "")
        if p is not None:
            p.replies += c.replies + 1
    for c in out:
        if c.parent and c.parent not in by_id:   # its parent was removed: it stands as a top-level comment
            c.parent, c.depth = None, 0
    total = story.get("comment_count") if isinstance(story.get("comment_count"), int) else len(out)
    return Parsed(total, _when(story.get("created_at")), story.get("title"), out)


_QUOTED = re.compile(r"(?is)<(blockquote|aside)\b[^>]*>(?:(?!<(?:blockquote|aside)\b).)*?</\1\s*>")
_CITE = re.compile(r"(?is)<cite\b[^>]*>.*?</cite\s*>")


def unquoted(markup: Optional[str]) -> str:
    """A forum message without the messages it quotes (blockquotes and Discourse's quote asides, nested ones too,
    and their "X wrote:" lines): a reply's own words."""
    s = _CITE.sub("", markup or "")
    while True:
        cut = _QUOTED.sub("", s)
        if cut == s:
            return s
        s = cut


def _linked(out: List[Comment]) -> List[Comment]:
    """Replies counted under each comment (all depths), depths from the parents; a reply whose parent is not kept
    stands as a top-level comment. `out` in the thread's order, a parent before its replies."""
    by_id = {c.id: c for c in out}
    for c in out:
        if c.parent and c.parent not in by_id:
            c.parent = None
        c.depth = by_id[c.parent].depth + 1 if c.parent else 0
    for c in reversed(out):
        p = by_id.get(c.parent or "")
        if p is not None:
            p.replies += c.replies + 1
    return out


def _discourse(answers: List[Any]) -> Parsed:
    """A topic's `.json` and its further posts by id: its posts after the first (the topic's own text), regular ones only (no
    moderator notes or small actions), hidden and deleted ones skipped; a comment's id its post number; likes the
    score."""
    topic = answers[0] if answers and isinstance(answers[0], dict) else {}
    out: List[Comment] = []
    posts = sorted({p.get("id"): p for p in _discourse_posts(answers)}.values(), key=lambda p: p.get("post_number") or 0)
    for n, p in enumerate(posts):
        if (p.get("post_number") in (None, 1) or p.get("post_type", 1) != 1
                or p.get("hidden") or p.get("deleted_at") or p.get("user_deleted")):
            continue
        text, links = plain(unquoted(p.get("cooked")))
        if not text:
            continue
        likes = next((a.get("count") for a in p.get("actions_summary") or []
                      if isinstance(a, dict) and a.get("id") == 2 and isinstance(a.get("count"), int)), 0)
        parent = p.get("reply_to_post_number")
        out.append(Comment(str(p["post_number"]), str(parent) if parent and parent != 1 else None,
                           p.get("username"), _when(p.get("created_at")), text, likes, rank=n, links=links))
    total = topic.get("posts_count") - 1 if isinstance(topic.get("posts_count"), int) else len(out)
    return Parsed(max(total, len(out)), _when(topic.get("created_at")), topic.get("title"), _linked(out))


_MENTION = re.compile(r"""<a\s[^>]*class=["'][^"']*PostMention[^"']*["'][^>]*>.*?</a>""", re.I | re.S)
_MENTION_ID = re.compile(r"""class=["'][^"']*PostMention[^"']*["'][^>]*data-id=["'](\d+)["']"""
                         r"""|data-id=["'](\d+)["'][^>]*class=["'][^"']*PostMention""", re.I)


def _flarum(answers: List[Any]) -> Parsed:
    """The discussion's posts pages: comments after the first (the discussion's own text; events such as a tag
    change are no comment), a comment's id its post number, its parent the post its first mention names (a mention
    is no text), likes the score."""
    pages = [a for a in answers if isinstance(a, dict)]
    users = {u.get("id"): (u.get("attributes") or {}) for a in pages for u in a.get("included") or []
             if isinstance(u, dict) and u.get("type") == "users"}
    posts = [p for a in pages for p in a.get("data") or [] if isinstance(p, dict) and p.get("type") == "posts"]
    number = {p.get("id"): str((p.get("attributes") or {}).get("number")) for p in posts}
    out: List[Comment] = []
    for n, p in enumerate(posts):
        a = p.get("attributes") or {}
        if a.get("number") in (None, 1) or a.get("contentType") != "comment" or a.get("isHidden"):
            continue
        markup = a.get("contentHtml") or ""
        m = _MENTION_ID.search(markup)
        parent = number.get(m.group(1) or m.group(2)) if m else None
        text, links = plain(unquoted(_MENTION.sub("", markup)))
        if not text:
            continue
        user = ((p.get("relationships") or {}).get("user") or {}).get("data") or {}
        who = users.get(user.get("id")) or {}
        out.append(Comment(str(a["number"]), parent if parent and parent != "1" else None,
                           who.get("displayName") or who.get("username"), _when(a.get("createdAt")), text,
                           a.get("likesCount") if isinstance(a.get("likesCount"), int) else None, rank=n,
                           links=links))
    return Parsed(len(out), None, None, _linked(out))


_FLUX_PID = re.compile(r"[?&]pid=(\d+)")


def _fluxbb(answers: List[Any]) -> Parsed:
    """A topic's Atom feed (its newest FEED_POSTS posts, newest first; flat, no parents): read oldest first; when the
    feed holds fewer than FEED_POSTS, its oldest is the topic's own post and is no comment."""
    from insight_core.ingestion.kinds.parsing import child_inner_xml, child_text, local_name, read_feed
    doc = answers[0] if answers and isinstance(answers[0], str) else ""
    if not doc:
        return Parsed(0, None, None, [])
    root, _broken = read_feed(doc)
    rows = []
    for e in (c for c in root if local_name(c.tag) == "entry"):
        link = next((c.attrib.get("href", "") for c in e if local_name(c.tag) == "link"), "") or child_text(e, "id") or ""
        m = _FLUX_PID.search(link)
        author = next((child_text(c, "name") for c in e if local_name(c.tag) == "author"), None)
        when = _when(child_text(e, "published") or child_text(e, "updated"))
        if m:
            rows.append((when or datetime.min.replace(tzinfo=timezone.utc), int(m.group(1)), author,
                         child_inner_xml(e, "content") or child_inner_xml(e, "summary")))
    rows.sort(key=lambda r: (r[0], r[1]))
    whole = len(rows) < FEED_POSTS
    if whole and rows:
        rows = rows[1:]
    out = []
    for n, (when, pid, author, markup) in enumerate(rows):
        text, links = plain(unquoted(html.unescape(markup or "") if "&lt;" in (markup or "") else markup))
        if text:
            out.append(Comment(str(pid), None, author, when, text, rank=n, links=links))
    return Parsed(len(out), None, None, out)


PARSERS: Dict[str, Callable[[List[Any]], Parsed]] = {"hn": _hn, "lobsters": _lobsters, "discourse": _discourse,
                                                     "flarum": _flarum, "fluxbb": _fluxbb}


def parse(t: Thread, answers: List[Any]) -> Parsed:
    return PARSERS[t.host](answers)


def _best(cs: List[Comment]) -> List[Comment]:
    """Siblings, best first: by score when the site gives one, then by the site's order (rank), then most replies."""
    return sorted(cs, key=lambda c: (-(c.score if c.score is not None else 0), c.rank, -c.replies, c.id))


def cap(comments: List[Comment], limit: int = CAP) -> List[Comment]:
    """The comments kept, in reading order (each top-level comment, then its kept replies, depth first): the TOP_LEVEL
    best top-level comments, then their best replies taken breadth first (REPLIES_EACH a comment a level, at most
    MAX_DEPTH deep) until `limit`. A reply's best is the one with most replies under it, then the earliest."""
    kids: Dict[Optional[str], List[Comment]] = {}
    for c in comments:
        kids.setdefault(c.parent, []).append(c)
    for k, v in kids.items():
        if k is not None:   # replies: the one that drew the most discussion first, then the earliest
            v.sort(key=lambda c: (-c.replies, c.at or datetime.max.replace(tzinfo=timezone.utc), c.id))
    tops = _best(kids.get(None, []))[:min(TOP_LEVEL, limit)]
    kept = {c.id for c in tops}
    level = tops
    while level and len(kept) < limit:
        nxt: List[Comment] = []
        for c in level:
            if c.depth >= MAX_DEPTH:
                continue
            for r in kids.get(c.id, [])[:REPLIES_EACH]:
                if len(kept) >= limit:
                    break
                kept.add(r.id)
                nxt.append(r)
        level = nxt
    out: List[Comment] = []

    def emit(c: Comment) -> None:
        out.append(c)
        for r in kids.get(c.id, []):
            if r.id in kept:
                emit(r)

    for c in tops:
        emit(c)
    for c in out:
        c.text = c.text[:TEXT_CHARS]
    return out


Get = Callable[[str], Awaitable[Any]]


async def read(t: Thread, get: Get) -> Parsed:
    """The thread read through `get` (a paced GET: the caller's limiter and KindHttp; JSON, else with text=True the
    document, for a host whose answers are documents), every GET in order, then its further pages (`more`). A
    missing rank (HN's second GET failing) or a later page failing still reads what came; the first failing raises."""
    urls = requests(t)
    text = HOSTS[t.host].text

    async def one(u: str) -> Any:
        return await get(u, text=True) if text else await get(u)

    answers: List[Any] = [await one(urls[0])]
    for u in urls[1:]:
        try:
            answers.append(await one(u))
        except Exception:  # noqa: BLE001 - the order only ranks; the tree is the thread
            answers.append(None)
    while (nxt := more(t, answers)) is not None:
        try:
            answers.append(await one(nxt))
        except Exception:  # noqa: BLE001 - the pages read are the thread so far
            break
    return parse(t, answers)


__all__ = ["CAP", "Comment", "FLOORS", "HOSTS", "Host", "Parsed", "Thread", "cap", "comment_url", "floor",
           "forum_thread", "more", "parse", "plain", "post_thread",
           "read", "requests", "thread_of"]
