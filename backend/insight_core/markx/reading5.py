"""ent-v5: one reading of a post (read-v2's reading, read-v3's event type and origin, ent-v4.2's entities) from one
call a window, task kind `reading`; `cite` stays its own question.

The switch (mx_settings `reading_guide`, `set_mode`): `off` (default, nothing planned), `shadow` (stored beside the
old kinds, read only by `compare`), `on` (ent-v5 first wherever a reading is picked, its mentions the post's current
set, no old-kind tasks for posts it reads). Every reading picker asks `guides` (Python) or `rank_sql` (SQL). `record`
(from tasks.record) is the one adapter: the reading in read-v3's shape, mentions through ent42's merge. Old rows stay.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from psycopg import Cursor

from insight_core.markx import pairing, plan_marks, repo, tasks

GUIDE, KIND = "ent-v5", "reading"
SETTING = "reading_guide"
MODES = ("off", "shadow", "on")
DEFAULT = "off"
CHARS, LINKS = 6000, 12                     # ent-v4.2's cut and cite's links
_GUIDE_RE = r"^[a-z0-9][a-z0-9.\-]*$"


# ---- the switch ---------------------------------------------------------------------------------------------------

def mode(cur: Cursor) -> str:
    got = repo.get_setting(cur, SETTING, default=DEFAULT)
    return got if got in MODES else DEFAULT


def is_on(cur: Cursor) -> bool:
    return mode(cur) == "on"


def set_mode(cur: Cursor, value: str) -> Dict[str, Any]:
    """Switch ent-v5 (`off`, `shadow`, `on`). Turning it on makes the posts it read take its mention set as current;
    turning it off again gives each of them back the newest other guide's set (no row rewritten either way)."""
    if value not in MODES:
        raise ValueError(f"reading_guide: one of {', '.join(MODES)}")
    was = mode(cur)
    repo.set_setting(cur, SETTING, value)
    moved = 0
    if value == "on" and was != "on":
        cur.execute("""INSERT INTO mx_mention_sets (post_id, guide, call_id)
                       SELECT DISTINCT ON (post_id) post_id, %s, call_id FROM mx_mentions
                        WHERE guide = %s AND win = 0 ORDER BY post_id, n
                       ON CONFLICT (post_id) DO UPDATE SET guide = EXCLUDED.guide, call_id = EXCLUDED.call_id, at = now()""",
                    (GUIDE, GUIDE))
        moved = cur.rowcount
    elif was == "on" and value != "on":
        cur.execute("""WITH back AS (
                         SELECT DISTINCT ON (m.post_id) m.post_id, m.guide, m.call_id
                           FROM mx_mentions m JOIN mx_calls c ON c.id = m.call_id
                          WHERE m.guide <> %s AND m.post_id IN (SELECT post_id FROM mx_mention_sets WHERE guide = %s)
                          ORDER BY m.post_id, c.created_at DESC, m.guide DESC)
                       UPDATE mx_mention_sets s SET guide = b.guide, call_id = b.call_id, at = now()
                         FROM back b WHERE s.post_id = b.post_id""", (GUIDE, GUIDE))
        moved = cur.rowcount
        # a post only ent-v5 read has no other set: no current set again (its rows stay, the pointer goes)
        cur.execute("DELETE FROM mx_mention_sets WHERE guide = %s", (GUIDE,))
        moved += cur.rowcount
    return {"mode": value, "was": was, "sets_moved": moved}


# ---- the one preference list ---------------------------------------------------------------------------------------

def guides(cur: Cursor, *base: str) -> List[str]:
    """The reading guides a picker reads, preferred first: its own (`base`), with ent-v5 first while the switch is on."""
    return ([GUIDE] if is_on(cur) else []) + [g for g in base if g != GUIDE]


ON_SQL = f"EXISTS (SELECT 1 FROM mx_settings s_ WHERE s_.key = '{SETTING}' AND s_.value = '\"on\"'::jsonb)"


def rank_sql(column: str, base: Sequence[str] = ("read-v3", "read-v2")) -> str:
    """SQL: a reading's rank by its guide (`column`): ent-v5 0 while the switch is on, then `base` in order; NULL for a
    guide the picker does not read. Order by it (NULLS LAST) and keep `IS NOT NULL` to pick as `guides` does."""
    import re
    assert all(re.match(_GUIDE_RE, g) for g in base)
    whens = " ".join(f"WHEN '{g}' THEN {n + 1}" for n, g in enumerate(base) if g != GUIDE)
    return f"(CASE {column} WHEN '{GUIDE}' THEN (CASE WHEN {ON_SQL} THEN 0 END) {whens} END)"


def pick(cur: Cursor, ids: Iterable[Any], base: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """{post: its preferred reading row (mx_readings, with `guide`)} among `guides(cur, *base)`."""
    ids = sorted({str(i) for i in ids})
    order = guides(cur, *base)
    if not ids or not order:
        return {}
    cur.execute("""SELECT DISTINCT ON (post_id) * FROM mx_readings WHERE post_id = ANY(%s::uuid[]) AND guide = ANY(%s)
                    ORDER BY post_id, array_position(%s::text[], guide)""", (ids, order, order))
    cols = [d[0] for d in cur.description]
    return {str(r[0]): dict(zip(cols, r)) for r in cur.fetchall()}


def old_kinds_sql(cur: Cursor, post: str = "p.id") -> str:
    """SQL: a planner of read, read3 or entities may ask the post (`post`): always, unless the switch is on and
    ent-v5 reads it."""
    if not is_on(cur):
        return "TRUE"
    return f"NOT EXISTS (SELECT 1 FROM mx_tasks v5 WHERE v5.kind = '{KIND}' AND v5.guide = '{GUIDE}' AND v5.a = {post})"


# ---- the input and the planner -------------------------------------------------------------------------------------

def inputs(p: tasks.Post, *, url: Optional[str], repost: Optional[Dict[str, Any]], cap: int) -> List[str]:
    """The post's inputs, a window each: the first is read-v3's head (address, repost author, published time) over
    the CHARS cut with LINKS links; later ones are `tasks.window_input`'s."""
    head, _, rest = tasks.post_block(p, LINKS, CHARS).partition("\n")
    extra = [f"Address: {url or ''}"]
    if repost and repost.get("author"):
        extra.append(f"Repost: written by @{repost['author']}, reposted by {p.source}")
    extra.append(f"Published: {p.at.astimezone(timezone.utc).isoformat()[:16]}")
    windows = tasks.text_windows(p.text, CHARS, cap)
    return ["\n".join([head, *extra] + ([rest] if rest else []))] + \
           [tasks.window_input(p, w, windows) for w in range(1, len(windows))]


def plan(cur: Cursor, *, limit: int = tasks.PLAN_LIMIT, now: Optional[datetime] = None, **_ignored: Any) -> int:
    """`reading` tasks for new posts only (the fresh lane) that have none, newest first, while the switch is shadow
    or on: how many were added. No archive re-read."""
    if mode(cur) == "off":
        return 0
    since = tasks.fresh_since(now)
    rows = plan_marks.execute(cur,
        f"""SELECT p.id, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now())
                                 - {pairing.ordinary_date('p')})) / 86400))::int, {plan_marks.STAMP}
              FROM posts p
             WHERE {tasks.fresh_sql()}
               AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = p.id)
               AND {plan_marks.unmarked()}
               AND p.filtered_by IS NULL
             ORDER BY {pairing.ordinary_date('p')} DESC, p.id DESC
             LIMIT %(limit)s""",
        {"now": now, "fresh": since, "kind": KIND, "guide": GUIDE, "limit": limit, "days": tasks.FRESH_DATED_DAYS})
    if not rows:
        return 0
    added, passed = add_posts(cur, rows)
    plan_marks.mark(cur, KIND, GUIDE, passed)
    return added


def add_posts(cur: Cursor, rows: Sequence[Any]) -> Any:
    """`reading` tasks (a window each) for rows of (post id, priority, stamp): (how many were added, the (post,
    SAME_INPUT, stamp) rows of posts whose first input is another post's task). The one way a post's reading is
    asked (`plan`, tasks.plan_last_posts)."""
    from insight_core.markx import folds
    ids = [str(r[0]) for r in rows]
    posts = tasks.load_posts(cur, ids)
    extras = folds._extras(cur, list(posts))
    cap = tasks.max_windows(cur)
    added, passed = 0, []
    for pid, age, stamp in rows:
        p = posts.get(str(pid))
        if p is None:
            continue
        url, repost = extras.get(str(pid), (None, None))
        windows = inputs(p, url=url, repost=repost, cap=cap)
        first = tasks.add(cur, KIND, windows[0], a=p.id, priority=age)[1]
        added += int(first) + sum(1 for x in windows[1:] if tasks.add(cur, KIND, x, a=p.id, priority=age)[1])
        if not first:   # its input is another post's task (a repost, a media-only post): not read again
            passed.append((p.id, plan_marks.SAME_INPUT, stamp))
    return added, passed


# ---- the one adapter -----------------------------------------------------------------------------------------------

ENTITY_NULLS = ("maker", "by", "family", "version", "variant", "size", "build")


def as_read3(answer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The answer's reading in read-v3's shape (what every reader of mx_readings.reading parses), or None."""
    r = answer.get("reading")
    if not isinstance(r, dict):
        return None
    return {"kind": r.get("kind"), "events": r.get("events"), "main": answer.get("event"), "items": r.get("items") or [],
            "mentions": r.get("mentions") or [], "lang": r.get("lang"), "type_why": r.get("type_why"),
            "event_type": r.get("event_type"), "origin": r.get("origin")}


def record(cur: Cursor, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> None:
    """A valid ent-v5 answer's rows: the reading (its first window's) and the window's mentions; current only while
    the switch is on."""
    from insight_core.markx import ent42
    pid = task["a"]
    win = tasks.window_of(task["input"])
    on = is_on(cur)
    read3 = as_read3(answer) if win == 0 else None
    if read3 is not None:
        main = read3["main"] or {}
        repo.add_reading(cur, post_id=pid, guide=GUIDE, call_id=call_id, kind=read3["kind"], events=read3["events"],
                         lang=read3["lang"], headline=main.get("headline_en"), reading=read3)
    entities = [{**{f: None for f in ENTITY_NULLS}, **e} for e in answer.get("entities") or [] if isinstance(e, dict)]
    if win:   # a name wholly in the text a window shares with the one before was read there
        shared, rest = tasks.window_overlap(task["input"])
        entities = [e for e in entities if not (e.get("span") and e["span"] in shared and e["span"] not in rest)]
    mentions = ent42.main_mentions(cur, pid, entities) if win == 0 else ent42.window_mentions(cur, pid, entities)
    repo.add_mentions(cur, post_id=pid, guide=GUIDE, call_id=call_id, mentions=mentions, win=win, current=on)
    if on:
        tasks._note_happening(cur, task)
        tasks._note_units(cur, task)


# ---- the Shadow comparison (/markx) ---------------------------------------------------------------------------------

def _names(rows: Iterable[Any]) -> set:
    return {tasks.name_key(n) for n in rows if n}


def compare(cur: Cursor, *, limit: int = 40) -> Dict[str, Any]:
    """The newest posts ent-v5 read beside what each has now (kind, events, event type, origin, headline, entity
    names), and the share of agreement over them."""
    cur.execute("""SELECT r.post_id::text, r.kind, r.events, r.headline, r.reading->>'event_type', r.reading->>'origin',
                          c.created_at, p.title
                     FROM mx_readings r JOIN mx_calls c ON c.id = r.call_id JOIN posts p ON p.id = r.post_id
                    WHERE r.guide = %s ORDER BY c.created_at DESC LIMIT %s""", (GUIDE, limit))
    v5 = {r[0]: r for r in cur.fetchall()}
    ids = list(v5)
    if not ids:
        return {"mode": mode(cur), "posts": [], "agree": {}}
    cur.execute("""SELECT post_id::text, guide, kind, events, headline, reading->>'event_type', reading->>'origin'
                     FROM mx_readings WHERE post_id = ANY(%s::uuid[]) AND guide IN ('read-v2', 'read-v3')""", (ids,))
    old: Dict[str, Dict[str, Any]] = {}
    for pid, g, kind, events, headline, typ, origin in cur.fetchall():
        o = old.setdefault(pid, {})
        if g == "read-v2":
            o.update(kind=kind, events=events, headline=headline)
        else:
            o.update(event_type=typ, origin=origin)
            o.setdefault("kind", kind); o.setdefault("events", events); o.setdefault("headline", headline)
    cur.execute("SELECT post_id::text, name FROM mx_mentions WHERE post_id = ANY(%s::uuid[]) AND guide = %s", (ids, GUIDE))
    ents5: Dict[str, List[str]] = {}
    for pid, name in cur.fetchall():
        ents5.setdefault(pid, []).append(name)
    cur.execute("""SELECT m.post_id::text, m.guide, m.name FROM mx_mentions m
                     JOIN mx_mention_sets s ON s.post_id = m.post_id AND s.guide = m.guide
                    WHERE m.post_id = ANY(%s::uuid[]) AND m.guide <> %s""", (ids, GUIDE))
    cur_ents: Dict[str, List[str]] = {}
    cur_guide: Dict[str, str] = {}
    for pid, g, name in cur.fetchall():
        cur_ents.setdefault(pid, []).append(name)
        cur_guide[pid] = g
    agree = {f: [0, 0] for f in ("kind", "events", "event_type", "origin")}
    jac: List[float] = []
    out = []
    for pid, (_, kind, events, headline, typ, origin, at, title) in v5.items():
        o = old.get(pid, {})
        mine = {"kind": kind, "events": events, "event_type": typ, "origin": origin}
        for f in agree:
            if o.get(f) is not None and mine[f] is not None:
                agree[f][1] += 1
                agree[f][0] += o[f] == mine[f]
        a, b = _names(ents5.get(pid, [])), _names(cur_ents.get(pid, []))
        j = len(a & b) / len(a | b) if (a or b) and pid in cur_ents else None
        if j is not None:
            jac.append(j)
        out.append({"post": pid, "title": title, "at": at.isoformat() if at else None,
                    "v5": {**mine, "headline": headline, "entities": sorted(set(ents5.get(pid, [])))},
                    "current": {**{f: o.get(f) for f in ("kind", "events", "event_type", "origin", "headline")},
                                "entities": sorted(set(cur_ents.get(pid, []))), "entities_guide": cur_guide.get(pid)},
                    "entities_jaccard": None if j is None else round(j, 3)})
    return {"mode": mode(cur), "posts": out,
            "agree": {f: {"same": s, "of": n} for f, (s, n) in agree.items()},
            "entities_jaccard": round(sum(jac) / len(jac), 3) if jac else None}
