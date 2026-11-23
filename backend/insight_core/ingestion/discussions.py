"""Discussions: a post's comment thread on a discussion site, read through the site's public JSON (issue 0280).

One mechanism for every host in HOSTS, a small table: how to tell a thread's address (`thread_of`), the GETs that read
it (`requests`) and how its answer becomes comments (`parse`). Hacker News: Algolia's item endpoint gives the whole tree
in one GET, and the Firebase item gives the top-level comments in the site's own rank order (a second GET); Lobsters:
the story's `.json` gives every comment with its score. No Reddit (every server path is blocked, plan/issues/0262).

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


HN = Host("Hacker News", "hn", {"hn.algolia.com": 1.0, "hacker-news.firebaseio.com": 1.0})
LOBSTERS = Host("Lobsters", "lobsters", {"lobste.rs": 3.0})
HOSTS: Dict[str, Host] = {h.key: h for h in (HN, LOBSTERS)}
FLOORS: Dict[str, float] = {k: v for h in HOSTS.values() for k, v in h.floors.items()}

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


def post_thread(url: Optional[str], metadata: Optional[Dict[str, Any]]) -> Optional[Thread]:
    """A post's discussion: its feed's comments address (metadata.comments_url) on a discussion host, else the post
    itself when it is a thread (an Ask HN, a Lobsters text story)."""
    return thread_of((metadata or {}).get("comments_url")) or thread_of(url)


def requests(t: Thread) -> List[str]:
    """The GETs that read a thread, in order."""
    if t.host == "hn":
        return [f"https://hn.algolia.com/api/v1/items/{t.id}",
                f"https://hacker-news.firebaseio.com/v0/item/{t.id}.json"]
    return [f"https://lobste.rs/s/{t.id}.json"]


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


PARSERS: Dict[str, Callable[[List[Any]], Parsed]] = {"hn": _hn, "lobsters": _lobsters}


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
    """The thread read through `get` (a paced JSON GET: the caller's limiter and KindHttp), every GET in order. A
    missing rank (HN's second GET failing) still reads the tree; any other failure raises."""
    urls = requests(t)
    answers: List[Any] = [await get(urls[0])]
    for u in urls[1:]:
        try:
            answers.append(await get(u))
        except Exception:  # noqa: BLE001 - the order only ranks; the tree is the thread
            answers.append(None)
    return parse(t, answers)


__all__ = ["CAP", "Comment", "FLOORS", "HOSTS", "Host", "Parsed", "Thread", "cap", "parse", "plain", "post_thread",
           "read", "requests", "thread_of"]
