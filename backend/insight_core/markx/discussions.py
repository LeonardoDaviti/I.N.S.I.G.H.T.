"""Discussions (issue 0280): a post's Hacker News or Lobsters thread, or a forum thread's own replies (v10.47), fetched
while young, read once by Haiku for what it adds beyond the post, shown folded on the post page.

Which threads: a post with a thread (ingestion/discussions.post_thread) that a reader opened (`want`, from the post
page's request: one insert), or that sits in the newest News run's rows or a track while young (`plan`, the jobs
pass). When: at once when wanted, then FETCH_AFTER the thread began (2 h, 12 h, 48 h), then never (`next_fetch`). The
fetching is the jobs process's (`run`, Jobs.discussions), never the API's, paced per request host (HostLimiter over
ingestion/discussions.FLOORS) and at most PASS_THREADS threads a pass. A fetch keeps at most CAP comments
(discussion_comments, never deleted) and the links they give (discussion_links).

The question (`discussion` kind, discussion-v1): the post's title, site and text, then the kept comments, each with its
id ("[c<id>]"); asked when a fetch keeps at least MIN_COMMENTS and again only when the kept comments grew by half
(`ask_due`). Shown (`view`): the newest valid answer, each point kept only when its quote is in one of the comments it
cites (`kept`), the cited comments with it; tools only with a cited comment. Mark IX tables are only read.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.ingestion import discussions as D

log = logging.getLogger(__name__)

KIND = "discussion"
FETCH_AFTER = (timedelta(hours=2), timedelta(hours=12), timedelta(hours=48))
PLAN_HOURS = 48               # News and track posts this young get their thread wanted
PASS_THREADS = 40             # threads fetched a pass, at most
MIN_COMMENTS = 5              # a thread with fewer kept comments is not asked
ASK_GROWTH = 1.5              # asked again when the kept comments grew this much since
POST_CHARS = 2000             # the post's text the question shows
INPUT_CHARS = 60000           # the question's comments, at most (the rest are not shown)
FAIL_STOP = 3                 # a thread failing this often in a row is not fetched again
ASKED = -1                    # a reader's thread is leased before the planned ones (0)
PATTERN = r"(news\.ycombinator\.com/item|lobste\.rs/s/)"   # a cheap SQL pre-filter (forums: metadata)


def next_fetch(created: Optional[datetime], now: datetime) -> Optional[datetime]:
    """The next fetch after one at `now`: the first FETCH_AFTER point still ahead, else None (done)."""
    if created is None:
        return None
    return next((created + d for d in FETCH_AFTER if created + d > now), None)


# ---- which threads ---------------------------------------------------------------------------------

def _insert(cur: Cursor, rows: Iterable[Tuple[str, D.Thread]], by: str, now: Optional[datetime] = None) -> int:
    """Threads wanted (once each: a post's row is never inserted again), due at `now` (None: the database's)."""
    n = 0
    for pid, t in rows:
        cur.execute("""INSERT INTO discussion_threads (post_id, host, thread_id, url, wanted_by, wanted_at, next_at)
                       VALUES (%s, %s, %s, %s, %s, COALESCE(%s, now()), COALESCE(%s, now()))
                       ON CONFLICT (post_id) DO NOTHING""",
                    (pid, t.host, t.id, t.url, by, now, now))
        n += cur.rowcount
    return n


def thread_for(cur: Cursor, post_id: str) -> Optional[D.Thread]:
    cur.execute("SELECT url, metadata FROM posts WHERE id = %s", (post_id,))
    row = cur.fetchone()
    return D.post_thread(row[0], row[1]) if row else None


def header(cur: Cursor, post_id: str, url: Optional[str], metadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The post page header's link to its thread: {name, url, total (the site's count at the last fetch, else null)},
    from the stored address alone before any fetch; None when the post has no thread."""
    t = D.post_thread(url, metadata)
    if t is None:
        return None
    cur.execute("SELECT total FROM discussion_threads WHERE post_id = %s", (post_id,))
    row = cur.fetchone()
    return {"name": t.name, "url": t.url, "total": row[0] if row else None}


def want(cur: Cursor, post_id: str) -> bool:
    """A reader opened the post: its thread is fetched by the next jobs pass (one insert; the jobs row marked)."""
    t = thread_for(cur, post_id)
    if t is None or not _insert(cur, [(post_id, t)], "reader"):
        return False
    from insight_core.markx import jobs
    jobs.want(cur, "discussions")
    return True


def _young(cur: Cursor, sql: str, args: Sequence[Any]) -> List[Tuple[str, D.Thread]]:
    cur.execute(sql, args)
    out = []
    for pid, url, meta in cur.fetchall():
        t = D.post_thread(url, meta)
        if t is not None:
            out.append((str(pid), t))
    return out


def plan(cur: Cursor, now: datetime) -> Dict[str, int]:
    """The young posts in the newest News run's rows and in tracks get their thread wanted (inserted once)."""
    from insight_core.markx import news, pairing
    since = now - timedelta(hours=PLAN_HOURS)
    got = {"news": 0, "track": 0}
    young = f"""AND {pairing.ordinary_date('p')} >= %s
                AND (p.metadata->>'comments_url' ~ %s OR p.url ~ %s OR p.metadata ? 'forum')
                AND NOT EXISTS (SELECT 1 FROM discussion_threads d WHERE d.post_id = p.id)"""
    run = news.last_written(cur)
    if run:
        got["news"] = _insert(cur, _young(cur, f"""SELECT DISTINCT p.id, p.url, p.metadata
              FROM mx_news n CROSS JOIN LATERAL jsonb_array_elements(n.posts) e
              JOIN posts p ON p.id = (e->>'post_id')::uuid
             WHERE n.run_id = %s {young}""", (run, since, PATTERN, PATTERN)), "news", now)
    got["track"] = _insert(cur, _young(cur, f"""SELECT DISTINCT p.id, p.url, p.metadata
          FROM mx_track_places tp JOIN posts p ON p.id = tp.post_id
         WHERE tp.place = 'track' {young}""", (since, PATTERN, PATTERN)), "track", now)
    return got


# ---- fetching (the jobs process) -------------------------------------------------------------------

def store(cur: Cursor, post_id: str, parsed: D.Parsed, now: datetime, fallback: Optional[datetime]) -> Dict[str, Any]:
    """A fetch's comments kept (upserted, never deleted), their links, and the thread's next fetch."""
    kept = D.cap(parsed.comments)
    for n, c in enumerate(kept):
        cur.execute("""INSERT INTO discussion_comments (post_id, comment_id, parent_id, author, score, at, text,
                                                        position, replies, seen_at)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (post_id, comment_id) DO UPDATE SET score = EXCLUDED.score, text = EXCLUDED.text,
                              position = EXCLUDED.position, replies = EXCLUDED.replies, seen_at = EXCLUDED.seen_at""",
                    (post_id, c.id, c.parent, c.author, c.score, c.at, c.text, n, c.replies, now))
        for url in c.links:
            cur.execute("""INSERT INTO discussion_links (post_id, comment_id, url) VALUES (%s, %s, %s)
                           ON CONFLICT DO NOTHING""", (post_id, c.id, url[:2000]))
    created = parsed.created_at or fallback
    size = sum(len(c.text.encode("utf-8")) for c in kept)
    cur.execute("""UPDATE discussion_threads SET fetched_at = %s, fetches = fetches + 1, failures = 0, last_error = NULL,
                          created_at = COALESCE(%s, created_at), total = %s, kept = %s, bytes = %s, next_at = %s
                    WHERE post_id = %s""",
                (now, created, parsed.total, len(kept), size, next_fetch(created, now), post_id))
    return {"kept": len(kept), "total": parsed.total, "bytes": size}


def failed(cur: Cursor, post_id: str, error: str, now: datetime) -> None:
    """A failed fetch: tried again at the next pass after an hour, stopped after FAIL_STOP in a row."""
    cur.execute("""UPDATE discussion_threads SET failures = failures + 1, last_error = %s,
                          next_at = CASE WHEN failures + 1 >= %s THEN NULL ELSE %s END
                    WHERE post_id = %s""", (error[:300], FAIL_STOP, now + timedelta(hours=1), post_id))


def ask_due(kept: int, asked: Optional[int]) -> bool:
    return kept >= MIN_COMMENTS and (asked is None or kept >= asked * ASK_GROWTH)


def discussion_input(cur: Cursor, post_id: str) -> Optional[str]:
    """The question as the worker sends it, from the thread's last fetch, or None (no post or no comments)."""
    from insight_core.markx import tasks
    from insight_core.utils.addresses import host_of
    cur.execute("""SELECT d.host, d.total, d.fetched_at, p.url FROM discussion_threads d JOIN posts p ON p.id = d.post_id
                    WHERE d.post_id = %s""", (post_id,))
    row = cur.fetchone()
    if row is None or row[2] is None:
        return None
    host, total, fetched, url = row
    name = D.Thread(host, "", url).name
    cur.execute("""SELECT comment_id, parent_id, author, text FROM discussion_comments
                    WHERE post_id = %s AND seen_at = %s ORDER BY position""", (post_id, fetched))
    comments = cur.fetchall()
    post = tasks.load_posts(cur, [post_id]).get(post_id)
    if post is None or not comments:
        return None
    text = post.text[len(post.title):].strip() if post.title and post.text.startswith(post.title) else post.text
    return render(post.title, host_of(url) or url, text, name, total, comments)


def render(title: Optional[str], site: str, text: str, host_name: str, total: Optional[int],
           comments: Sequence[Tuple[str, Optional[str], Optional[str], str]]) -> str:
    """The question's text: the post, then the comments [(id, parent, author, text)] in reading order, replies
    indented under their parent, until INPUT_CHARS."""
    depth: Dict[str, int] = {}
    lines, used, shown = [], 0, 0
    for cid, parent, author, body in comments:
        depth[cid] = depth.get(parent, -1) + 1 if parent else 0
        body = " ".join((body or "").split())
        line = ("  " * min(depth[cid], 4) + f"[c{cid}] {author or 'unknown'}"
                + (f", reply to c{parent}" if parent else "") + f": {body}")
        if used + len(line) > INPUT_CHARS:
            break
        lines.append(line)
        used += len(line) + 1
        shown += 1
    head = [f"POST: {title or '(no title)'}", f"SITE: {site}",
            f"POST TEXT: {' '.join((text or '').split())[:POST_CHARS]}",
            f"THREAD: {host_name}, {total if total is not None else shown} comments, {shown} shown", "COMMENTS:"]
    return "\n".join(head + lines)


def ask(cur: Cursor, post_id: str) -> Optional[str]:
    """The thread's question, added when `ask_due` (its id), else None."""
    from insight_core.markx import tasks
    cur.execute("SELECT kept, asked_kept, wanted_by FROM discussion_threads WHERE post_id = %s", (post_id,))
    row = cur.fetchone()
    if row is None or not ask_due(row[0] or 0, row[1]):
        return None
    text = discussion_input(cur, post_id)
    if text is None:
        return None
    tid, _new = tasks.add(cur, KIND, text, a=post_id, priority=ASKED if row[2] == "reader" else 0)
    cur.execute("UPDATE discussion_threads SET task_id = %s, asked_kept = kept WHERE post_id = %s", (tid, post_id))
    return str(tid)


def due(cur: Cursor, now: datetime, limit: int = PASS_THREADS) -> List[Tuple[str, D.Thread, Optional[datetime]]]:
    """The threads to fetch now, a reader's first: [(post id, thread, the post's date)]."""
    from insight_core.markx import pairing
    cur.execute(f"""SELECT d.post_id::text, d.host, d.thread_id, d.url, {pairing.ordinary_date('p')}
                      FROM discussion_threads d JOIN posts p ON p.id = d.post_id
                     WHERE d.next_at IS NOT NULL AND d.next_at <= %s
                     ORDER BY (d.wanted_by = 'reader' AND d.fetches = 0) DESC, d.next_at LIMIT %s""", (now, limit))
    return [(pid, D.Thread(host, tid, url), at) for pid, host, tid, url, at in cur.fetchall()]


async def _pass(db_url: str, now: datetime, http: Any, limiter: Any) -> Dict[str, Any]:
    from insight_core.db import database
    from insight_core.ingestion.http import HttpError
    from urllib.parse import urlsplit
    with database.transaction(db_url) as cur:
        planned = plan(cur, now)
        todo = due(cur, now)
    out: Dict[str, Any] = {"planned": planned, "fetched": 0, "failed": 0, "requests": 0, "asked": 0, "bytes": 0}

    async def get(url: str, text: bool = False) -> Any:
        host = urlsplit(url).hostname or ""
        async with limiter.slot(host, D.floor(host)):
            out["requests"] += 1
            try:
                got = (await http.get_text(url))[0] if text else await http.get_json(url)
            except HttpError as exc:
                if exc.limiting:
                    await asyncio.sleep(min(limiter.limited(host, exc.retry_after), 30.0))
                raise
            limiter.succeeded(host)
            return got

    for pid, t, at in todo:
        try:
            parsed = await D.read(t, get)
        except Exception as exc:  # noqa: BLE001 - one thread's failure is recorded; the pass goes on
            with database.transaction(db_url) as cur:
                failed(cur, pid, str(exc) or type(exc).__name__, now)
            out["failed"] += 1
            continue
        with database.transaction(db_url) as cur:
            got = store(cur, pid, parsed, now, at)
            if ask(cur, pid):
                out["asked"] += 1
        out["fetched"] += 1
        out["bytes"] += got["bytes"]
    return out


def run(db_url: str, *, now: Optional[datetime] = None, http: Any = None, limiter: Any = None) -> Dict[str, Any]:
    """One pass (the jobs process): plan, then fetch the due threads, each stored and asked in its own transaction."""
    from insight_core.ingestion.gates import HostLimiter
    from insight_core.ingestion.http import KindHttp
    t0 = time.monotonic()
    out = asyncio.run(_pass(db_url, now or datetime.now(timezone.utc), http or KindHttp(),
                            limiter or HostLimiter(D.FLOORS)))
    out["seconds"] = round(time.monotonic() - t0, 1)
    return out


# ---- what the reader sees --------------------------------------------------------------------------

def _answer(cur: Cursor, post_id: str) -> Optional[Dict[str, Any]]:
    cur.execute("""SELECT c.answer, c.created_at FROM mx_tasks t JOIN mx_calls c ON c.task_id = t.id AND c.valid
                    WHERE t.kind = %s AND t.a = %s ORDER BY c.created_at DESC LIMIT 1""", (KIND, post_id))
    row = cur.fetchone()
    return {"answer": row[0], "at": row[1]} if row and isinstance(row[0], dict) else None


def _comments(cur: Cursor, post_id: str, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = sorted({i[1:] if i.startswith("c") else i for i in ids})
    if not ids:
        return {}
    cur.execute("""SELECT comment_id, parent_id, author, score, at, text FROM discussion_comments
                    WHERE post_id = %s AND comment_id = ANY(%s)""", (post_id, ids))
    return {"c" + r[0]: {"id": r[0], "parent": r[1], "author": r[2], "score": r[3],
                         "at": r[4].isoformat() if r[4] else None, "text": r[5]} for r in cur.fetchall()}


def kept(answer: Dict[str, Any], comments: Dict[str, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]],
                                                                              List[Dict[str, Any]], int]:
    """(the points shown, the tools shown, how many points were dropped). A point is shown with its cited comments
    that are stored and its quote in one of them (folded); a tool with a stored cited comment."""
    from insight_core.markx import validate
    points, dropped = [], 0
    for p in answer.get("points") or []:
        cited = [c for c in dict.fromkeys(p.get("comments") or []) if c in comments]
        quote = " ".join(str(p.get("quote") or "").split())
        if not cited or not quote or not any(validate.occurs(quote, comments[c]["text"]) for c in cited):
            dropped += 1
            continue
        points.append({"kind": p.get("kind"), "text": p.get("text"), "quote": quote, "comments": cited})
    tools = []
    for t in answer.get("tools") or []:
        cited = [c for c in dict.fromkeys(t.get("comments") or []) if c in comments]
        if cited:
            tools.append({"name": t.get("name"), "url": t.get("url"), "what": t.get("what"), "comments": cited})
    return points, tools, dropped


def view(cur: Cursor, post_id: str) -> Dict[str, Any]:
    """The post page's Discussion: {thread: null | {host, name, url, total, kept, fetched_at, next_at, failed},
    status: none | waiting | fetched | answered, wanted (a fetch is planned or done), stance, points [{kind, text,
    quote, comments [ids]}], tools, comments {cid: comment} (the cited ones), dropped}. No thread row yet: the thread
    from the post's address (the page then asks `want`)."""
    cur.execute("""SELECT host, thread_id, url, total, kept, fetched_at, next_at, last_error, task_id
                     FROM discussion_threads WHERE post_id = %s""", (post_id,))
    row = cur.fetchone()
    out: Dict[str, Any] = {"thread": None, "status": "none", "wanted": row is not None, "stance": None, "points": [],
                           "tools": [], "comments": {}, "dropped": 0}
    if row is None:
        t = thread_for(cur, post_id)
        if t is not None:
            out.update(status="waiting", thread={"host": t.host, "name": t.name, "url": t.url, "total": None,
                                                 "kept": None, "fetched_at": None, "next_at": None, "failed": None})
        return out
    host, tid, url, total, kept_n, fetched, nxt, error, task_id = row
    out["thread"] = {"host": host, "name": D.Thread(host, tid, url).name, "url": url, "total": total, "kept": kept_n,
                     "fetched_at": fetched.isoformat() if fetched else None,
                     "next_at": nxt.isoformat() if nxt else None, "failed": error}
    if fetched is None:
        out["status"] = "waiting"
        return out
    got = _answer(cur, post_id)
    if got is None:
        out["status"] = "fetched"
        return out
    a = got["answer"]
    ids = [c for x in (a.get("points") or []) + (a.get("tools") or []) for c in x.get("comments") or []]
    comments = _comments(cur, post_id, ids)
    points, tools, dropped = kept(a, comments)
    for c in comments.values():
        c["url"] = D.comment_url(D.Thread(host, tid, url), c["id"])
    used = {c for x in points + tools for c in x["comments"]}
    out.update(status="answered", stance=a.get("stance"), points=points, tools=tools, dropped=dropped,
               answered_at=got["at"].isoformat() if got.get("at") else None,
               comments={k: v for k, v in comments.items() if k in used})
    return out


def counts(cur: Cursor, post_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """{post id: {points, total, name}} for the posts with an answered thread (News rows' "discussion: N points"):
    the points `kept` would show. Two queries for any number of posts."""
    ids = sorted({str(p) for p in post_ids})
    if not ids:
        return {}
    cur.execute("""SELECT DISTINCT ON (t.a) t.a::text, c.answer, d.host, d.total, d.url
                     FROM discussion_threads d JOIN mx_tasks t ON t.kind = %s AND t.a = d.post_id
                     JOIN mx_calls c ON c.task_id = t.id AND c.valid
                    WHERE d.post_id = ANY(%s::uuid[]) ORDER BY t.a, c.created_at DESC""", (KIND, ids))
    rows = [r for r in cur.fetchall() if isinstance(r[1], dict)]
    if not rows:
        return {}
    wanted = [(pid, c[1:]) for pid, a, _h, _t, _u in rows for p in a.get("points") or [] for c in p.get("comments") or []
              if isinstance(c, str) and c.startswith("c")]
    texts: Dict[Tuple[str, str], Dict[str, Any]] = {}
    if wanted:
        cur.execute("""SELECT post_id::text, comment_id, text FROM discussion_comments
                        WHERE (post_id, comment_id) IN (SELECT (x->>0)::uuid, x->>1 FROM jsonb_array_elements(%s::jsonb) x)""",
                    (json.dumps(wanted),))
        texts = {(r[0], r[1]): {"text": r[2]} for r in cur.fetchall()}
    out = {}
    for pid, a, host, total, url in rows:
        comments = {"c" + cid: v for (p, cid), v in texts.items() if p == pid}
        points, _tools, _ = kept(a, comments)
        if points:
            out[pid] = {"points": len(points), "total": total, "name": D.Thread(host, "", url).name}
    return out


__all__ = ["ask", "ask_due", "counts", "discussion_input", "kept", "next_fetch", "plan", "run", "store", "view",
           "want"]
