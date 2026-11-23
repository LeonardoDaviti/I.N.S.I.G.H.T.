"""Questions with citations: the reader asks in words on the search page and gets an answer built only from their own
posts, every sentence cited, or "not in your sources".

`gather` (no model) picks the posts: the search page's best for the question taking turns with the named entities'
posts and their brief lines as NOTES, at most MAX_POSTS. `ask` adds one `question` task (the worker answers; the page
polls `view`); the same question with the same posts is the same task. `kept` shows a sentence only with a cite inside
the given posts and every figure in a post it cites (validate.missing_figures); nothing kept: "not in your sources".
Behind entity_bands.json `search.answers`; off, the API is 404.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from psycopg import Cursor

SWITCH = ("search", "answers")
KIND = "question"
SUBJECT = "question"
SEARCH_POSTS = 10        # the search page's first posts for the question
ENTITIES = 2             # entities the question names, at most
ENTITY_POSTS = 4         # each one's posts (its own and its maker's first, then the newest)
BRIEF_LINES = 6          # an entity brief's lines shown as notes, at most
MAX_POSTS = 16           # posts a question shows, at most
TEXT_CHARS = 1200        # each post's text shown
TITLE_CHARS = 200
MAX_Q_CHARS = 300
NOT_IN_SOURCES = "not in your sources"

_POST = re.compile(r"^\[(\d{1,3})\] (.*)$", re.M)


def on() -> bool:
    from insight_core.markx import identity
    return bool((identity.bands().get(SWITCH[0]) or {}).get(SWITCH[1], False))


def _clean(s: Optional[str], limit: int) -> str:
    return re.sub(r"\s+", " ", s or "").strip()[:limit]


def _search_posts(cur: Cursor, q: str, now: datetime) -> List[str]:
    from insight_core.db.repo_search import SearchQuery, SearchRepository
    from insight_core.markx import search
    items, _ = SearchRepository().search(cur, SearchQuery.parse(q=q, order="best", limit=SEARCH_POSTS), now=now,
                                         markx=search.enabled())
    return [str(i["id"]) for i in items if i.get("id")]


def gather(cur: Cursor, q: str, *, now: Optional[datetime] = None) -> Tuple[List[str], List[Dict[str, Any]]]:
    """(the posts to answer from, in order; the notes: [{entity, text, posts: [ids]}])."""
    from insight_core.markx import entity_brief, identity, search
    now = now or datetime.now(timezone.utc)
    posts: List[str] = []
    notes: List[Dict[str, Any]] = []

    def add(ids: Sequence[str]) -> None:
        for p in ids:
            if p not in posts and len(posts) < MAX_POSTS:
                posts.append(p)

    found = _search_posts(cur, q, now)
    cards = search.entity_cards(cur, q, ENTITIES) if search.enabled() else []
    book = identity.lazy_book(cur) if cards else None
    own: List[str] = []
    for c in cards:
        root = c["id"]
        brief = entity_brief.view(cur, root, names=[c["name"]])
        for kind in ("what", "how", "results"):
            for ln in (brief or {}).get(kind) or []:
                if len([n for n in notes if n["entity"] == c["name"]]) >= BRIEF_LINES:
                    break
                ids = [x["post"] for x in ln.get("cites") or []][:3]
                text = ln["text"] + (f" ({ln['note']})" if ln.get("note") else "")
                notes.append({"entity": c["name"], "text": _clean(text, 300), "posts": ids})
                own += [i for i in ids if i not in own]
        own += [p for p in entity_brief.report_posts(cur, book, root)[:ENTITY_POSTS] if p not in own]
    # the search's posts and the entities' posts take turns so neither crowds out the other
    a, b = list(found), list(own)
    while (a or b) and len(posts) < MAX_POSTS:
        if a:
            add([a.pop(0)])
        if b:
            add([b.pop(0)])
    notes = [dict(n, posts=[p for p in n["posts"] if p in posts]) for n in notes]
    return posts, [n for n in notes if n["posts"]]


def question_input(cur: Cursor, q: str, posts: Sequence[str], notes: Sequence[Dict[str, Any]], *,
                   today: str) -> Tuple[str, List[str]]:
    """The question as the worker sends it: QUESTION, TODAY, the NOTES (each with its posts' numbers) and the POSTS
    numbered [1]..[n] (source, date, title, text): (the input, the posts in their numbers' order)."""
    from insight_core.markx import tasks
    loaded = tasks.load_posts(cur, list(posts))
    order = [p for p in posts if p in loaded]
    num = {p: n for n, p in enumerate(order, 1)}
    lines = [f"QUESTION: {_clean(q, MAX_Q_CHARS)}", f"TODAY: {today}", ""]
    shown = [n for n in notes if any(p in num for p in n["posts"])]
    if shown:
        lines.append("NOTES:")
        for n in shown:
            refs = "".join(f"[{num[p]}]" for p in n["posts"] if p in num)
            lines.append(f"- {n['entity']}: {n['text']} {refs}")
        lines.append("")
    lines.append("POSTS:")
    for p in order:
        post = loaded[p]
        when = post.at.date().isoformat() if post.at else "undated"
        title = _clean(post.title, TITLE_CHARS)
        text = _clean(post.text, TEXT_CHARS + len(title) + 1)
        if title and text.startswith(title):
            text = text[len(title):].strip()
        text = text[:TEXT_CHARS]
        lines.append(f"[{num[p]}] {post.who or 'unknown'}, {when}: {title or '(no title)'}" + (f" — {text}" if text else ""))
    return "\n".join(lines), order


def numbered(input: str) -> Dict[int, str]:
    """{n: the post's line} of a question's input."""
    return {int(n): line for n, line in _POST.findall(input or "")}


def kept(answer: Optional[Dict[str, Any]], input: str) -> Tuple[List[Dict[str, Any]], int]:
    """(the sentences shown: {text, cites: [n]}, how many were dropped). A sentence is kept with its cites inside the
    question's posts, at least one, and every figure it gives in a post it cites."""
    from insight_core.markx import validate
    rows = numbered(input)
    out, dropped = [], 0
    if not answer or not answer.get("answerable"):
        return [], len((answer or {}).get("sentences") or [])
    for s in answer.get("sentences") or []:
        cites = list(dict.fromkeys(c for c in s.get("cites") or [] if isinstance(c, int) and c in rows))
        text = " ".join(str(s.get("text") or "").split())
        if not text or not cites or validate.missing_figures(text, " ".join(rows[c] for c in cites)):
            dropped += 1
            continue
        out.append({"text": text, "cites": cites})
    return out, dropped


def ask(cur: Cursor, q: str, *, now: Optional[datetime] = None) -> str:
    """The reader's question: its row (and its task, unless nothing was found to answer from): the row's id."""
    from insight_core.markx import repo, schemas
    q = _clean(q, MAX_Q_CHARS)
    if len(q) < 3:
        raise ValueError("a question, please")
    now = now or datetime.now(timezone.utc)
    posts, notes = gather(cur, q, now=now)
    task_id = None
    order: List[str] = []
    if posts:
        text, order = question_input(cur, q, posts, notes, today=now.date().isoformat())
        if order:
            schemas.ensure_guides(cur)
            task_id, _new = repo.add_task(cur, kind=KIND, guide=schemas.KINDS[KIND].guide, subject_kind=SUBJECT,
                                          input=text, priority=-1)
    cur.execute("INSERT INTO mx_questions (q, task_id, post_ids) VALUES (%s, %s, %s::uuid[]) RETURNING id::text",
                (q, task_id, order))
    qid = cur.fetchone()[0]
    if task_id is not None:
        cur.execute("UPDATE mx_tasks SET a = %s WHERE id = %s AND a IS NULL", (qid, task_id))
    return qid


def view(cur: Cursor, qid: str) -> Optional[Dict[str, Any]]:
    """{id, q, status: waiting | answered | failed, sentences: [{text, cites: [n]}], posts: [{n, id, title, url, at,
    source}], not_in_sources, dropped}, or None (no such question)."""
    from insight_core.markx import entity_brief
    cur.execute("""SELECT q.id::text, q.q, q.post_ids::text[], t.id::text, t.status, t.input, q.created_at
                     FROM mx_questions q LEFT JOIN mx_tasks t ON t.id = q.task_id WHERE q.id = %s""", (qid,))
    row = cur.fetchone()
    if row is None:
        return None
    _id, q, ids, task_id, status, input, asked = row
    out: Dict[str, Any] = {"id": _id, "q": q, "asked_at": asked.isoformat() if asked else None, "sentences": [],
                           "posts": [], "not_in_sources": False, "dropped": 0}
    if task_id is None:
        return dict(out, status="answered", not_in_sources=True)
    cur.execute("SELECT answer FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at DESC LIMIT 1", (task_id,))
    got = cur.fetchone()
    if got is None:
        return dict(out, status="waiting" if status in ("open", "leased") else "failed")
    sentences, dropped = kept(got[0], input)
    if not sentences:
        return dict(out, status="answered", not_in_sources=True, dropped=dropped)
    cited = sorted({c for s in sentences for c in s["cites"]})
    by_n = {n: ids[n - 1] for n in cited if 1 <= n <= len(ids)}
    info = entity_brief._posts(cur, list(by_n.values()))
    return dict(out, status="answered", sentences=sentences, dropped=dropped,
                posts=[dict(info[p], n=n) for n, p in sorted(by_n.items()) if p in info])


__all__ = ["NOT_IN_SOURCES", "ask", "gather", "kept", "on", "question_input", "view"]
