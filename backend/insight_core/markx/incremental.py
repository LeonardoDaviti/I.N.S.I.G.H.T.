"""Mark X's incremental decision runs (issue 0116): a run reads again only what changed since the last one.

A full run (decide.run) spends its time reading, not deciding: on the server's copy (30 days, 6,606 posts, 2,300
questions) 0.8 s loads the posts' texts and near-copies, 0.45 s asks the database for each question's task and answer
one query at a time, and 0.9 s rebuilds Mark IX's StoryPosts for every News post. The rules themselves (plan, glue,
merges, both passes) take 0.05 s. So an incremental run keeps, in this process, what the last run read (a `Memo`) and
re-reads only what changed, then runs the same rules over the same world:

  - **The dirty set.** Every answer lands as a call on a task, and calls are never changed or deleted: a task's
    (status, number of valid calls) changes exactly when an answer arrived, a task was asked again or it failed. The
    run reads that pair for every judge task in one query (20 ms) and re-reads the calls of the tasks whose pair
    changed: those are the dirty tasks. Nothing has to mark them, so no writer can forget to (0116's `mx_dirty` table
    is this query: it can't miss an answer, and needs no migration).
  - **The closure** is what those answers reach: the stories their posts are in (Mark IX's and Mark X's, before and
    after), with their merge groups and the stories sharing a post with them. It is reported (`counts.run`); the
    rules are re-run over the whole world because they cost 50 ms and that is what keeps the result a full run's.
  - **Texts** are re-read only for posts whose rows changed (Mark IX's tables' row versions: `xmin`), first by a
    per-table stamp (60 ms), then per post only when a table changed.
  - **News** is recomputed only for the rows its changed stories reach (members, mentions, News rows and surges,
    as Mark IX's own incremental News, 0072 A); the rest of the last run's rows stay. When Mark IX's posts, parts,
    links, sources, surges or roundups changed, News is rebuilt in full.

A run is full when there is no memo of the last run in this process (a start, another process ran last, the last
run failed), when the code version, config or a guide changed, and nightly (the first run after NIGHTLY_HOUR). A
nightly full run with a memo is the check: it first reads the same snapshot as an incremental run would (writing
nothing), then in full; any difference is logged as an incremental-run bug with its stories (`counts.check`).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

log = logging.getLogger(__name__)

KINDS = ("check", "join", "pair", "merge", "card", "headline", "connect", "briefing")   # the tasks a run reads
TEXT_TABLES = ("posts", "post_parts", "post_links", "sources")     # what Mark X's texts are read from
NEWS_TABLES = TEXT_TABLES + ("news_surges", "story_mentions")      # ... and Mark IX's StoryPosts, surges, roundups
NIGHTLY_HOUR = 4                                                   # server time: the first run after it is full
HUB, HUB_MIN = 0.25, 40                                            # a closure over this share of 40+ stories: flagged


@dataclass
class Memo:
    """What the last run read, kept in this process for the next one."""
    db: str
    key: str                                                       # code version, config and guides
    run_id: Optional[str] = None                                   # the run that left it (None while one runs)
    stamps: Dict[str, Tuple] = field(default_factory=dict)         # table -> (rows, newest xmin, sum of xmin hashes)
    post_stamps: Dict[str, Tuple] = field(default_factory=dict)    # post -> its rows' xmins (post, parts, source, links)
    texts: Dict[str, Any] = field(default_factory=dict)            # post -> tasks.Post
    rules: Dict[str, Any] = field(default_factory=dict)            # post -> decide.Post (its words counted once)
    copies: Dict[Tuple, frozenset] = field(default_factory=dict)   # a story's (post, stamp) members -> its near-copies
    tasks: Dict[Tuple[str, str], Tuple[str, str, int]] = field(default_factory=dict)   # (kind, hash) -> (id, status, n)
    keys: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # task id -> (kind, input hash)
    calls: Dict[str, List[Tuple[Dict[str, Any], str]]] = field(default_factory=dict)  # task id -> valid calls, oldest first
    call_task: Dict[str, str] = field(default_factory=dict)        # call id -> its task
    news: Optional[Dict[str, Any]] = None                          # the last run's News inputs and rows
    want: Optional[Dict[str, Dict[str, Tuple]]] = None             # the last run's memberships, by final story key
    report: Dict[str, Any] = field(default_factory=dict)           # this run's dirty set, for counts.run


_memos: Dict[str, Memo] = {}


def _db(cur: Any) -> str:
    cur.execute("SELECT current_database()")
    return cur.fetchone()[0]


def memo_for(cur: Any, key: str) -> Tuple[Memo, bool]:
    """This process's memo of the database and whether it is the last run's (warm): the last finished run is the one
    that left it, with the same code, config and guides. Read before the run starts its own mx_runs row."""
    db = _db(cur)
    memo = _memos.get(db)
    cur.execute("SELECT id::text FROM mx_runs WHERE finished_at IS NOT NULL ORDER BY started_at DESC, ctid DESC LIMIT 1")
    row = cur.fetchone()
    warm = memo is not None and memo.key == key and memo.run_id is not None and row is not None and row[0] == memo.run_id
    return (memo if warm else fresh(db, key)), warm


def fresh(db: str, key: str) -> Memo:
    _memos[db] = Memo(db=db, key=key)
    return _memos[db]


def forget(cur: Any = None) -> None:
    """Every memo of this process (or of this cursor's database) gone: the next run is full."""
    if cur is None:
        _memos.clear()
    else:
        _memos.pop(_db(cur), None)


def nightly_due(cur: Any, now: datetime) -> bool:
    """Whether no full run ran since the last NIGHTLY_HOUR (server time) before `now`, by the runs' own clocks."""
    local = now.astimezone()
    mark = local.replace(hour=NIGHTLY_HOUR, minute=0, second=0, microsecond=0)
    if mark > local:
        mark -= timedelta(days=1)
    cur.execute("""SELECT max((counts->'run'->>'now')::timestamptz) FROM mx_runs
                    WHERE finished_at IS NOT NULL AND counts->'run'->>'kind' = 'full'""")
    last = cur.fetchone()[0]
    return last is None or last < mark


def table_stamps(cur: Any, tables: Iterable[str]) -> Dict[str, Tuple]:
    """Each table's rows, newest row version and a sum of its row versions' hashes (transaction and place): any insert,
    update or delete since changes it (a new version has a newer xmin, or, in the same transaction, another ctid)."""
    out = {}
    for t in tables:
        cur.execute(f"SELECT count(*), max(xmin::text::bigint), sum(hashtext(xmin::text || ctid::text)::bigint) FROM {t}")
        out[t] = tuple(None if x is None else int(x) for x in cur.fetchone())
    return out


def post_stamps(cur: Any, ids: Sequence[str]) -> Dict[str, Tuple]:
    """Each post's row versions: its row, its parts, its source and its links in order."""
    if not ids:
        return {}
    cur.execute("""SELECT p.id::text, p.xmin::text || p.ctid::text, pp.xmin::text || pp.ctid::text, s.xmin::text || s.ctid::text,
                          (SELECT string_agg(l.xmin::text || l.ctid::text, ',' ORDER BY l.position)
                             FROM post_links l WHERE l.post_id = p.id)
                     FROM posts p JOIN sources s ON s.id = p.source_id LEFT JOIN post_parts pp ON pp.post_id = p.id
                    WHERE p.id = ANY(%s::uuid[])""", (list(ids),))
    return {r[0]: tuple(r[1:]) for r in cur.fetchall()}


# ---- the dirty set -----------------------------------------------------------------------------------------

def refresh(cur: Any, memo: Memo) -> Dict[str, Any]:
    """Read again what changed since the memo's run: every judge task's (status, valid calls) in one query, the calls
    of those that changed (the dirty tasks), and Mark IX's table stamps. Returns the report (dirty tasks, their posts,
    which tables changed); the memo holds this snapshot's tasks and calls after."""
    cold = not memo.tasks
    cur.execute("""SELECT t.id::text, t.kind, t.input_hash, t.status, COALESCE(c.n, 0), t.a::text, t.b::text
                     FROM mx_tasks t
                     LEFT JOIN (SELECT task_id, count(*) n FROM mx_calls WHERE valid GROUP BY task_id) c ON c.task_id = t.id
                    WHERE t.kind = ANY(%s)""", (list(KINDS),))
    index, keys, dirty, posts = {}, {}, [], set()
    for tid, kind, h, status, n, a, b in cur.fetchall():
        index[(kind, h)] = (tid, status, int(n))
        keys[tid] = (kind, h)
        old = memo.tasks.get((kind, h))
        if old != (tid, status, int(n)):
            if not cold:
                dirty.append(tid)
                posts.update(p for p in (a, b) if p)
            memo.calls.pop(tid, None)
    memo.tasks, memo.keys = index, keys
    need = [tid for (tid, status, n) in index.values() if n and tid not in memo.calls]
    if need:
        cur.execute("""SELECT task_id::text, id::text, answer FROM mx_calls WHERE valid AND task_id = ANY(%s::uuid[])
                        ORDER BY task_id, created_at, ctid""", (need,))
        got: Dict[str, List] = defaultdict(list)
        for tid, cid, answer in cur.fetchall():
            got[tid].append((answer, cid))
        for tid in need:
            memo.calls[tid] = got.get(tid, [])
    memo.call_task = {cid: tid for tid, cs in memo.calls.items() for _a, cid in cs}
    stamps = table_stamps(cur, NEWS_TABLES)
    changed = sorted(t for t in NEWS_TABLES if memo.stamps.get(t) != stamps[t]) if memo.stamps else list(NEWS_TABLES)
    memo.stamps = stamps
    memo.report = {"dirty_tasks": len(dirty), "dirty_posts": sorted(posts), "ix_changed": changed}
    return memo.report


def texts(cur: Any, memo: Memo, ids: Iterable[str]) -> Dict[str, Any]:
    """The posts' texts (tasks.load_posts), read again only where a row changed: none when Mark IX's text tables are
    as the memo left them, else the posts whose row versions changed; new posts always."""
    from insight_core.markx import tasks
    ids = sorted(set(ids))
    if set(memo.report.get("ix_changed") or ()) & set(TEXT_TABLES) and memo.post_stamps:
        stamps = post_stamps(cur, ids)
        stale = [i for i in ids if i not in memo.texts or memo.post_stamps.get(i) != stamps.get(i)]
    else:
        stale = [i for i in ids if i not in memo.texts]
        stamps = post_stamps(cur, stale)
    got = tasks.load_posts(cur, stale)
    for i in stale:
        memo.rules.pop(i, None)
        if i in got:
            memo.texts[i] = got[i]
            memo.post_stamps[i] = stamps.get(i)
        else:
            memo.texts.pop(i, None)
            memo.post_stamps.pop(i, None)
    memo.report["texts_read"] = len(stale)
    return {i: memo.texts[i] for i in ids if i in memo.texts}


def copies(memo: Memo, members: Sequence[Any]) -> frozenset:
    """tasks.near_copies of a story's members, kept by their row versions."""
    from insight_core.markx import tasks
    key = tuple((m.id, memo.post_stamps.get(m.id)) for m in members)
    if key not in memo.copies:
        memo.copies[key] = frozenset(tasks.near_copies(members))
    return memo.copies[key]


# ---- the closure (reported) ----------------------------------------------------------------------------------

def closure(memo: Memo, want: Dict[str, Dict[str, Tuple]], ix: Dict[str, Sequence[Any]]) -> Dict[str, Any]:
    """The stories the dirty answers reach: those holding a dirty task's post, now or in the last run (Mark X's final
    stories: merge groups), with the Mark IX stories of those posts, and the stories sharing a post with any of them;
    and how many final stories changed their memberships since the last run."""
    seeds = set(memo.report.get("dirty_posts") or ())
    old = memo.want or {}
    by_post: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)
    for tag, rows in (("now", want), ("was", old)):
        for key, ms in rows.items():
            for pid in ms:
                by_post[pid].add((tag, key))
    for key, ms in ix.items():
        for m in ms:
            by_post[m.post].add(("ix", key))
    members = {("now", k): set(ms) for k, ms in want.items()}
    members.update({("was", k): set(ms) for k, ms in old.items()})
    members.update({("ix", k): {m.post for m in ms} for k, ms in ix.items()})
    reached = {s for p in seeds for s in by_post.get(p, ())}
    shared = {s for st in reached for p in members.get(st, ()) for s in by_post.get(p, ())}
    stories = {k for tag, k in reached | shared if tag in ("now", "was")}   # Mark X's final stories, now or before
    changed = {k for k, ms in want.items() if old.get(k) != ms} | {k for k in old if k not in want}
    out = {"closure": len(stories), "stories": len(want), "changed_stories": len(changed)}
    if len(want) >= HUB_MIN and len(stories) > HUB * len(want):
        out["hub"] = True
        log.warning("Mark X incremental run: the closure holds %d of %d stories (over %d%%)", len(stories), len(want),
                    int(HUB * 100))
    return out


# ---- the check: an incremental reading of this snapshot against the full one -------------------------------

def digest(want: Dict[str, Dict[str, Tuple]], connections: Sequence[Dict[str, Any]], final: Dict[str, str],
           about: Dict[str, Dict[str, Any]], news_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """A run's results without its keys or ids: each story by its memberships (post, role, reason, p, call); each
    typed connection by its ends (a post, or a story's member posts); each News row with its posts and tag."""
    def members(key: str) -> Tuple:
        return tuple(sorted(about.get(final.get(key, key), {})))
    stories = {tuple(sorted((p, *r) for p, r in ms.items())) for ms in want.values()}
    conns = set()
    for c in connections:
        a = c["a"] if c["a_kind"] == "post" else members(c["a"])
        b = c["b"] if c["b_kind"] == "post" else members(c["b"])
        conns.add((c["a_kind"], a, c["b_kind"], b, c["relation"], round(float(c["p"]), 4), c.get("call")))
    rows = {json.dumps([str(r["id"]), str(r["first_at"]), r["voices"], r["reports"], r["shares"], r["mentions"],
                        round(float(r["score"]), 2), r.get("tag"), [[p["post_id"], p["role"], p.get("name")]
                                                                      for p in r["posts"]]], default=str)
            for r in news_rows}
    return {"stories": stories, "connections": conns, "news": rows}


def differences(inc: Dict[str, Any], full: Dict[str, Any], limit: int = 20) -> Dict[str, Any]:
    """What the full reading has that the incremental one doesn't, and the reverse, by part (some of each)."""
    out = {}
    for part in ("stories", "connections", "news"):
        a, b = inc[part], full[part]
        if a != b:
            only_inc, only_full = sorted(map(str, a - b)), sorted(map(str, b - a))
            out[part] = {"incremental_only": len(only_inc), "full_only": len(only_full),
                         "examples": {"incremental": [x[:400] for x in only_inc[:limit]],
                                      "full": [x[:400] for x in only_full[:limit]]}}
    return out
