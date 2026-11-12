"""Mark X News in sections (issue 0174, Stealth v10.16): Haiku divides the News page into 3-8 titled sections, and
every row shows a Haiku headline.

**The question** (kind `news_sections`, guide news-sections-v1, one a call): the current News rows (the newest written
run's, inside News' window, in News' own order: `news.rank_key`), each keyed r1..rN with its headline (`news.headlines`),
its main entities and their types (the current entities of its posts, subjects before actors, most posts first), its
kind of happening when one is read (`event_types.of_stories`, the event-type seam) and its voices; and the
section titles of the last valid answer, each row saying the section it was in. Sphere-agnostic: no list of sections in
code, the titles are Haiku's. The keys map back to rows through the ask (mx_news_section_asks: the row ids in key order).

**When** (`plan`, the lease's planner, tasks.PLANNERS): when the current rows differ from the last asked ones by
CHANGE_SHARE or more (new and removed rows over the last asked count), or never asked; at most once every EVERY; never
while one is waiting (open or leased). A failed question does not count as the last asked one.

**The answer** (`after_answer`, from tasks.record): one mx_news_sections row a section (keep everything), ordered by
its most important row. `view` gives the page the newest answer's sections over the rows it shows, in the page's order;
the rows the answer did not cover (added since) are `new`, shown first ("New since"). A pending question never holds
the page back: the last valid sectioning is shown meanwhile.

**Titles** (`title_rows`, the decision run's stage after News): every row still showing its lead's title has its
headline task asked first (priority PRIORITY: the open ones raised, a missing one added); a failed one is counted.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

KIND, GUIDE = "news_sections", "news-sections-v1"
MIN_ROWS = 8                          # fewer rows: no sections (3 sections of 1-2 rows read worse than the list)
CHANGE_SHARE = 0.20                   # new + removed rows over the last asked rows: asked again from this share
EVERY = timedelta(minutes=30)         # at most one question in this time
PRIORITY = -1                         # first among its kind's open tasks (repo.lease_tasks: a caller's urgency)
ENTITIES_SHOWN = 3
HEADLINE_CHARS = 160
NEW_SINCE = "New since"


# ---- the rows ------------------------------------------------------------------------------------------------

def current_rows(cur: Any, now: datetime) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """(the newest written run, its rows inside News' window in News' order) as the page reads them."""
    from insight_core.markx import news, repo
    from insight_core.utils.news_rules import NEWS_DAYS
    run = news.last_written(cur)
    if run is None:
        return None, []
    since = now - timedelta(days=NEWS_DAYS)
    rows = [r for r in repo.news_rows(cur, run) if r["first_at"] >= since]
    rows.sort(key=lambda r: news.rank_key(r, now))
    return run, rows


def _entities(cur: Any, rows: Sequence[Dict[str, Any]]) -> Dict[str, List[Tuple[str, Optional[str]]]]:
    """{row id: [(name, type)]}: the current subjects of its posts, then their actors, most posts first."""
    from insight_core.markx import schemas
    of_post = defaultdict(list)
    for r in rows:
        for p in r.get("posts") or []:
            of_post[p["post_id"]].append(str(r["id"]))
    if not of_post:
        return {}
    cur.execute("""SELECT post_id::text, role, name_key, name, type FROM mx_mentions_now
                    WHERE post_id = ANY(%s::uuid[]) AND role IN ('subject', 'actor') ORDER BY post_id, name""",
                (sorted(of_post),))
    score: Dict[str, Counter] = defaultdict(Counter)
    shown: Dict[Tuple[str, str], Tuple[str, Optional[str]]] = {}
    for pid, role, key, name, typ in cur.fetchall():
        if not key or not name:
            continue
        for rid in of_post[pid]:
            score[rid][key] += 2 if role == "subject" else 1
            shown.setdefault((rid, key), (re.sub(r"\s+", " ", name).strip(), schemas.entity_type(typ)))
    return {rid: [shown[(rid, k)] for k, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:ENTITIES_SHOWN]]
            for rid, c in score.items()}


def _types(cur: Any, rows: Sequence[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """{row id: its kind of happening}: the event-type seam's story type over its posts (None: none has a type)."""
    from insight_core.markx import event_types   # 0175: whichever guide gave the posts' types
    if not any(r.get("posts") for r in rows):
        return {}
    return event_types.of_stories(cur, {str(r["id"]): [p["post_id"] for p in r.get("posts") or []] for r in rows})


def last_sectioning(cur: Any) -> Optional[Dict[str, Any]]:
    """The newest valid answer's sections: {task, call, at, sections: [{title, rows}]} in their order; None: none yet."""
    cur.execute("""SELECT task_id::text, call_id::text, at FROM mx_news_sections
                    ORDER BY at DESC, call_id DESC LIMIT 1""")
    row = cur.fetchone()
    if row is None:
        return None
    task, call, at = row
    cur.execute("SELECT title, row_ids FROM mx_news_sections WHERE call_id = %s ORDER BY position", (call,))
    return {"task": task, "call": call, "at": at,
            "sections": [{"title": t, "rows": [str(x) for x in ids]} for t, ids in cur.fetchall()]}


def _squash(s: Optional[str], n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def question(cur: Any, rows: Sequence[Dict[str, Any]], last: Optional[Dict[str, Any]] = None) -> str:
    """The input: the rows keyed r1..rN in their order, each with its headline, entities, type, voices and last
    section (s1..sM, the last answer's titles in their order)."""
    from insight_core.markx import news
    heads = news.headlines(cur, rows)
    ents = _entities(cur, rows)
    types = _types(cur, rows)
    titles = [s["title"] for s in (last or {}).get("sections") or []]
    was = {rid: f"s{n}" for n, s in enumerate((last or {}).get("sections") or [], 1) for rid in s["rows"]}
    lines = [f"NEWS: {len(rows)} rows, most important first"]
    if titles:
        lines.append("LAST TIME'S SECTIONS: " + " | ".join(f"[s{n}] {t}" for n, t in enumerate(titles, 1)))
    lines.append("")
    for n, r in enumerate(rows, 1):
        rid = str(r["id"])
        parts = [f"[r{n}] {_squash(heads[rid]['text'], HEADLINE_CHARS) or '(no title)'}"]
        if ents.get(rid):
            parts.append("entities: " + ", ".join(f"{name} ({typ})" if typ else name for name, typ in ents[rid]))
        if types.get(rid):
            parts.append("type: " + types[rid].replace("_", " "))
        parts.append(f"{r['voices']} voice" + ("" if r["voices"] == 1 else "s"))
        if rid in was:
            parts.append(f"last: {was[rid]}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


# ---- when ---------------------------------------------------------------------------------------------------

def changed_share(before: Sequence[str], now: Sequence[str]) -> float:
    """New and removed rows over the rows asked before (1.0 when none were)."""
    a, b = set(map(str, before)), set(map(str, now))
    return 1.0 if not a else len(a ^ b) / len(a)


def due(asks: Sequence[Dict[str, Any]], rows: Sequence[str], now: datetime) -> Tuple[bool, str]:
    """Whether to ask now, and why (or why not): `asks` newest first, each {row_ids, asked_at, status}."""
    if len(rows) < MIN_ROWS:
        return False, f"{len(rows)} rows, fewer than {MIN_ROWS}"
    if any(a["status"] in ("open", "leased") for a in asks):
        return False, "one is waiting"
    if asks and now - asks[0]["asked_at"] < EVERY:
        return False, "asked less than 30 minutes ago"
    base = next((a for a in asks if a["status"] != "failed"), None)
    if base is None:
        return True, "first time"
    share = changed_share(base["row_ids"], rows)
    if share < CHANGE_SHARE:
        return False, f"{share:.0%} of the rows changed"
    return True, f"{share:.0%} of the rows changed"


def asks(cur: Any) -> List[Dict[str, Any]]:
    cur.execute("""SELECT a.task_id::text, a.row_ids, a.asked_at, t.status FROM mx_news_section_asks a
                     JOIN mx_tasks t ON t.id = a.task_id ORDER BY a.asked_at DESC, a.task_id""")
    return [{"task_id": t, "row_ids": ids, "asked_at": at, "status": st} for t, ids, at, st in cur.fetchall()]


def plan(cur: Any, *, now: Optional[datetime] = None, **_kw: Any) -> int:
    """The sections question for the current rows when `due`: 1 when a task was added, else 0."""
    from insight_core.markx import tasks
    now = now or datetime.now(timezone.utc)
    run, rows = current_rows(cur, now)
    if run is None:
        return 0
    ids = [str(r["id"]) for r in rows]
    ok, _why = due(asks(cur), ids, now)
    if not ok:
        return 0
    last = last_sectioning(cur)
    text = question(cur, rows, last)
    tid, new = tasks.add(cur, KIND, text, a=run, priority=PRIORITY)
    cur.execute("""INSERT INTO mx_news_section_asks (task_id, run_id, row_ids, titles, asked_at)
                   VALUES (%s, %s, %s::jsonb, %s::jsonb, %s) ON CONFLICT (task_id) DO NOTHING""",
                (tid, run, json.dumps(ids), json.dumps([s["title"] for s in (last or {}).get("sections") or []]), now))
    return 1 if new else 0


# ---- the answer ---------------------------------------------------------------------------------------------

def sections_of(answer: Dict[str, Any], row_ids: Sequence[str]) -> List[Tuple[str, List[str]]]:
    """[(title, row ids in key order)] ordered by each section's most important row (its lowest key)."""
    def num(k: str) -> int:
        return int(k[1:])
    out = []
    for s in answer.get("sections") or []:
        keys = sorted({k for k in s.get("row_ids") or [] if 1 <= num(k) <= len(row_ids)}, key=num)
        if keys:
            out.append((num(keys[0]), s["title"].strip(), [str(row_ids[num(k) - 1]) for k in keys]))
    return [(t, ids) for _, t, ids in sorted(out, key=lambda x: x[0])]


def after_answer(cur: Any, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> int:
    """A valid answer's sections as rows (mx_news_sections): how many."""
    cur.execute("SELECT run_id, row_ids FROM mx_news_section_asks WHERE task_id = %s", (task["id"],))
    row = cur.fetchone()
    if row is None:
        return 0
    run, row_ids = row
    got = sections_of(answer, row_ids)
    for n, (title, ids) in enumerate(got):
        cur.execute("""INSERT INTO mx_news_sections (task_id, call_id, run_id, position, title, row_ids)
                       VALUES (%s, %s, %s, %s, %s, %s::uuid[]) ON CONFLICT DO NOTHING""",
                    (task["id"], call_id, run, n, title, ids))
    return len(got)


# ---- the page -----------------------------------------------------------------------------------------------

def view(cur: Any, items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The page's sections over its rows (`items`, in the page's order): {at, pending, groups: [{title, rows}], new}.
    A section's place is its most important row's on the page; `new`: the rows no answer covered yet. No answer yet:
    at None, no groups."""
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_news_section_asks a JOIN mx_tasks t ON t.id = a.task_id
                                   WHERE t.status IN ('open', 'leased'))""")
    pending = bool(cur.fetchone()[0])
    last = last_sectioning(cur)
    if last is None:
        return {"at": None, "pending": pending, "groups": [], "new": []}
    of = {rid: s["title"] for s in last["sections"] for rid in s["rows"]}
    groups: Dict[str, List[str]] = {}
    new: List[str] = []
    for item in items:
        rid = str(item["id"])
        if rid in of:
            groups.setdefault(of[rid], []).append(rid)
        else:
            new.append(rid)
    return {"at": last["at"], "pending": pending, "groups": [{"title": t, "rows": ids} for t, ids in groups.items()],
            "new": new}


# ---- titles ---------------------------------------------------------------------------------------------------

def title_rows(cur: Any, *, now: Optional[datetime] = None) -> Dict[str, int]:
    """Every current row still titled by its lead (no Haiku headline yet) gets its headline asked first: its open
    headline tasks (by any of its posts) raised to PRIORITY, or, when none is open or leased, the row's own headline
    question added at PRIORITY (news.row_headline_input: the page finds its answer by it). {untitled, raised, added,
    waiting (leased now), failed}."""
    from insight_core.markx import news, tasks
    now = now or datetime.now(timezone.utc)
    _run, rows = current_rows(cur, now)
    heads = news.headlines(cur, rows) if rows else {}
    untitled = [r for r in rows if heads[str(r["id"])]["from"] != "haiku"]
    out = {"untitled": len(untitled), "raised": 0, "added": 0, "waiting": 0, "failed": 0}
    if not untitled:
        return out
    posts = news._row_posts(cur, untitled)
    for r in untitled:
        ids = [p["post_id"] for p in r.get("posts") or []]
        cur.execute("""UPDATE mx_tasks SET priority = %s WHERE kind = 'headline' AND status = 'open' AND priority > %s
                          AND a = ANY(%s::uuid[])""", (PRIORITY, PRIORITY, ids))
        out["raised"] += cur.rowcount
        cur.execute("SELECT status FROM mx_tasks WHERE kind = 'headline' AND a = ANY(%s::uuid[])", (ids,))
        states = {s for (s,) in cur.fetchall()}
        if "open" in states:
            continue
        if "leased" in states:
            out["waiting"] += 1
            continue
        text = news.row_headline_input(r, posts)
        if text is None:
            continue
        tid, new = tasks.add(cur, "headline", text, a=ids[0], priority=PRIORITY)
        if new:
            out["added"] += 1
        else:
            cur.execute("SELECT status FROM mx_tasks WHERE id = %s", (tid,))
            status = cur.fetchone()[0]
            if status == "failed":
                out["failed"] += 1
            elif status == "open":
                cur.execute("UPDATE mx_tasks SET priority = %s WHERE id = %s AND priority > %s", (PRIORITY, tid, PRIORITY))
                out["raised"] += cur.rowcount
    return out
