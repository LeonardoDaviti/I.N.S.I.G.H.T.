"""Mark X's incremental decision runs (issue 0116), their state kept in Postgres (issue 0169).

0116 kept what the last run read in the process (a memo) and re-read only what changed. Since the jobs left the API
(0112 Decided 10) every decision run is a process of its own, so no run found a memo and every run was full: on the
server 137 s, 28,902 texts read, 2.8 GiB in "questions and decisions". 0169 keeps the state in tables instead
(migration 0113), so a run in a fresh process reads only what changed since the last run:

  - **What a run needs of a post is small.** The rules read a post's voice (a repost's author when a source follows
    that author, else its source), kind, time and word count (decide.Post);
    the reading's kind and events; whether it was read. Those come from `mx_inc_posts` (kept by the post's **stamp**,
    plan_marks.STAMP: the row versions of what tasks.load_posts reads) and from mx_readings' own columns. A post's
    text is read only when its stamp changed (or it is new), and when a render that misses needs it (below).
  - **A question's input is kept by what it shows.** Each render (check, join, pair, merge, card, connect, headline,
    a News row's headline) is keyed by its kind, the stamps of the posts it shows (and their readings' row versions
    where it shows a reading) and any answer it shows (a merge's cards): `mx_inc_inputs` holds key -> the input's
    sha256, which is all a run needs to find the question's task and its answer. A key that misses is rendered from
    the texts, read then (`Lazy*`). Near-copies (0112 bug 3) are kept the same way by their members' stamps
    (`mx_inc_copies`).
  - **The answers** are read for the tasks a run asks (the ones its kept inputs name, in one query, then any other on
    first use), never every call of every task.
  - **The dirty set** is still every judge task whose (status, valid calls) changed since the last run, now against
    `mx_inc_tasks` (what the last run saw); it is reported with its closure (`counts.run`), as 0116 did.
  - **News** keeps the last run's inputs and rows (`mx_inc_state.news`), so it is made again only for the rows the
    changed stories reach (0116's `news.write`). 0177: and the rows of the posts whose StoryPost inputs changed (their
    text stamp, their links' resolution) or whose Mark IX surge did, by digests kept with them; in full only when the
    source facts a StoryPost reads changed (or no digests were kept).

**The rules still run over the whole world**: the plan, glue, merges, the second pass and the matching of stories are
global and cost little next to reading (0116: 50 ms on 6,606 posts); running them in full is what keeps the result a
full run's. Only the reading is incremental, and every kept result is keyed by the content it was made from, so a key
that matches can only give what a render would.

**When a run is full** (nothing kept is trusted, everything is read and the state written again): no state, or not
the last finished run's (a run that failed rolls its state back with it, so the state stays the last finished run's
and the next run is incremental), the code (`code_stamp`: the modules whose code makes what is kept), config or a
guide changed, nightly (the first run after NIGHTLY_HOUR), and with `run(full=True)`. A full run with a state first
reads the snapshot as an incremental run would (writing nothing), then in full; any difference is logged as an
incremental-run bug (`counts.check`). The first run after deploying 0169 is full: it writes the state.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple
from uuid import UUID

from insight_core.markx.unchanged import table_stamps   # 0183: one table stamp for every pass

log = logging.getLogger(__name__)

KINDS = ("check", "join", "pair", "merge", "card", "headline", "connect", "briefing")   # the tasks a run reads
TEXT_TABLES = ("posts", "post_parts", "post_links", "sources")     # what Mark X's texts are read from
NEWS_TABLES = TEXT_TABLES + ("news_surges", "story_mentions")      # ... and Mark IX's StoryPosts, surges, roundups
NIGHTLY_HOUR = 4                                                   # server time: the first run after it is full
HUB, HUB_MIN = 0.25, 40                                            # a closure over this share of 40+ stories: flagged
GUIDE = "read-v2"                                                  # the readings the decisions read (tasks.readings)
NAME = "decide"                                                    # mx_inc_state's row
TEXT_PAGE = 2000                                                   # 0204: the posts whose texts a reading reads at once
# The modules whose code makes what the state keeps (the rules' posts, the renders, near-copies, News' rows): any
# change to them makes the next run full (a deploy then starts from a full run, as before 0169).
CODE_MODULES = ("insight_core.markx.decide", "insight_core.markx.incremental", "insight_core.markx.tasks",
                "insight_core.markx.news", "insight_core.markx.pairing", "insight_core.markx.plan_marks",
                "insight_core.utils.post_parts", "insight_core.utils.post_links", "insight_core.utils.news_rules",
                "insight_core.utils.story_rules", "insight_core.services.news_service",
                "insight_core.services.stories_service", "insight_core.db.repo_stories", "insight_core.db.repo_news",
                "insight_core.utils.voice", "insight_core.utils.byline")

# The state's own version, in the key with code_stamp: v2 keeps each post's voice (a followed author's repost counts
# as that author), so the first run after it is full and writes every post again.
STATE_VERSION = "inc-v2-voices"   # v10.15: the voice a post counts as (voice.counted_source, then pairing's)

_code: Optional[str] = None


def code_stamp() -> str:
    """The sha256 of CODE_MODULES' source files."""
    global _code
    if _code is None:
        import importlib
        h = hashlib.sha256(STATE_VERSION.encode())
        for name in CODE_MODULES:
            with open(importlib.import_module(name).__file__, "rb") as f:
                h.update(name.encode() + b"\0" + f.read() + b"\0")
        _code = h.hexdigest()
    return _code


def accounts_stamp(cur: Any) -> str:
    """The sha256 of which source follows which account (voice.followed_accounts): a repost's voice depends on it
    and no post's stamp says so, so it is in the state's key (a change makes the next run full)."""
    from insight_core.utils import voice
    return _sha(json.dumps(sorted(voice.followed_accounts(cur).items())))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---- the state's values in jsonb: exact round trips of what a run keeps --------------------------------------

def _enc(v: Any) -> Any:
    if isinstance(v, datetime):
        return {"$dt": v.isoformat()}
    if isinstance(v, date):
        return {"$d": v.isoformat()}
    if isinstance(v, (set, frozenset)):
        return {"$set" if isinstance(v, set) else "$fset": sorted((_enc(x) for x in v), key=json.dumps)}
    if isinstance(v, tuple):
        return {"$t": [_enc(x) for x in v]}
    if isinstance(v, UUID):
        return {"$u": str(v)}
    if isinstance(v, Decimal):
        return {"$dec": str(v)}
    if isinstance(v, dict):
        return {"$o": [[_enc(k), _enc(x)] for k, x in v.items()]}
    if isinstance(v, list):
        return [_enc(x) for x in v]
    return v


def _dec(v: Any) -> Any:
    if isinstance(v, list):
        return [_dec(x) for x in v]
    if isinstance(v, dict):
        (tag, x), = v.items()
        if tag == "$dt":
            return datetime.fromisoformat(x)
        if tag == "$d":
            return date.fromisoformat(x)
        if tag == "$set":
            return {_dec(y) for y in x}
        if tag == "$fset":
            return frozenset(_dec(y) for y in x)
        if tag == "$t":
            return tuple(_dec(y) for y in x)
        if tag == "$u":
            return UUID(x)
        if tag == "$dec":
            return Decimal(x)
        if tag == "$o":
            return {_dec(k): _dec(y) for k, y in x}
        raise ValueError(f"unknown tag {tag}")
    return v


def encode(v: Any) -> str:
    return json.dumps(_enc(v))


def decode(v: Any) -> Any:
    return None if v is None else _dec(v if not isinstance(v, str) else json.loads(v))


# ---- the state ------------------------------------------------------------------------------------------

@dataclass
class State:
    """One reading's view of the kept state. `full`: nothing kept is trusted (everything read, all of it written after);
    `dry`: nothing is written (the check's incremental reading)."""
    db: str
    key: str
    full: bool = True
    dry: bool = False
    run_id: Optional[str] = None                                   # the run that left the kept state
    stamps: Dict[str, Tuple] = field(default_factory=dict)         # table -> (rows, newest xmin, sum of xmin hashes)
    news: Optional[Dict[str, Any]] = None                          # the last run's News inputs and rows
    want: Optional[Dict[str, Dict[str, Tuple]]] = None             # the last run's memberships, by final story key
    surges: Optional[Tuple[Tuple, List[Any]]] = None               # (news_surges' stamp, the surges as news reads them)
    report: Dict[str, Any] = field(default_factory=dict)           # this run's dirty set and reading, for counts.run
    # the judge tasks and their answers
    tasks: Dict[Tuple[str, str], Tuple[str, str, int]] = field(default_factory=dict)   # (kind, hash) -> (id, status, n)
    keys: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # task id -> (kind, input hash)
    was: Dict[str, Tuple[str, int]] = field(default_factory=dict)  # task id -> (status, n) as the last run saw it
    calls: Dict[str, List[Tuple[Dict[str, Any], str]]] = field(default_factory=dict)  # task id -> valid calls, oldest first
    call_task: Dict[str, str] = field(default_factory=dict)        # call id -> its task
    # the posts
    rules: Dict[str, Any] = field(default_factory=dict)            # post -> decide.Post (the world's)
    stamp: Dict[str, str] = field(default_factory=dict)            # post -> its text stamp (plan_marks.STAMP)
    fresh_posts: Dict[str, Tuple] = field(default_factory=dict)    # post -> its mx_inc_posts row, to write
    read_stamp: Dict[str, str] = field(default_factory=dict)       # post -> its reading's row version
    kinds: Dict[str, Any] = field(default_factory=dict)            # post -> its reading's kind (read posts only)
    events: Dict[str, Any] = field(default_factory=dict)           # post -> its reading's events
    texts: Dict[str, Any] = field(default_factory=dict)            # post -> tasks.Post, as read this run
    readings: Dict[str, dict] = field(default_factory=dict)        # post -> its reading, as read this run
    # the kept results, by the content they were made from
    inputs_kept: Dict[str, str] = field(default_factory=dict)      # render key -> input hash (the last run's)
    inputs: Dict[str, Tuple[str, str]] = field(default_factory=dict)   # render key -> (kind, input hash) (this run's)
    copies_kept: Dict[str, frozenset] = field(default_factory=dict)
    copies: Dict[str, frozenset] = field(default_factory=dict)

    @property
    def kept(self) -> bool:
        return not self.full


def _db(cur: Any) -> str:
    cur.execute("SELECT current_database()")
    return cur.fetchone()[0]


def _last_run(cur: Any) -> Optional[str]:
    # v10.11: runs started in one transaction (the tests') share started_at; finished_at (clock_timestamp) tells them
    # apart, where ctid alone did not once a run's row grew (0145's two kinds in its config) and moved on its page.
    cur.execute("""SELECT id::text FROM mx_runs WHERE finished_at IS NOT NULL
                    ORDER BY started_at DESC, finished_at DESC, ctid DESC LIMIT 1""")
    row = cur.fetchone()
    return row[0] if row else None


def open_state(cur: Any, key: str) -> Tuple[State, bool]:
    """The kept state and whether it is the last finished run's with this key (warm): then a reading may trust it.
    Read before the run starts its own mx_runs row."""
    db = _db(cur)
    cur.execute("SELECT run_id::text, key FROM mx_inc_state WHERE name = %s", (NAME,))
    row = cur.fetchone()
    warm = row is not None and row[1] == key and row[0] is not None and row[0] == _last_run(cur)
    if not warm:
        return State(db=db, key=key, full=True), False
    cur.execute("SELECT stamps, news, want FROM mx_inc_state WHERE name = %s", (NAME,))
    stamps, news, want = cur.fetchone()
    return State(db=db, key=key, full=False, run_id=row[0], stamps=decode(stamps) or {}, news=decode(news),
                 want=decode(want)), True


def fresh(state: State) -> State:
    """A full reading of the same database and key."""
    return State(db=state.db, key=state.key, full=True)


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


# ---- the dirty set -----------------------------------------------------------------------------------------

def refresh(cur: Any, state: State) -> Dict[str, Any]:
    """Every judge task's (status, valid calls) in one query, against what the last run saw (mx_inc_tasks): those that
    changed are the dirty tasks (reported only when the state is trusted). The table stamps say which of Mark IX's
    tables changed. Then the kept inputs and near-copies (a trusted state only) and the answers of the tasks they
    name, in one query (a full reading: every answer).

    v10.17.2 (0204): each task's calls are counted by its own (mx_calls_task_idx), not by grouping every valid call
    of every kind (~1M on the server, mostly reads and entities: 0.84 s a run at server scale, now 0.03 s)."""
    cur.execute("""SELECT t.id::text, t.kind, t.input_hash, t.status, c.n, t.a::text, t.b::text, s.status, s.n
                     FROM mx_tasks t
                     CROSS JOIN LATERAL (SELECT count(*) n FROM mx_calls c WHERE c.task_id = t.id AND c.valid) c
                     LEFT JOIN mx_inc_tasks s ON s.task_id = t.id
                    WHERE t.kind = ANY(%s)""", (list(KINDS),))
    index, keys, was, dirty, posts = {}, {}, {}, [], set()
    for tid, kind, h, status, n, a, b, s_status, s_n in cur.fetchall():
        index[(kind, h)] = (tid, status, int(n))
        keys[tid] = (kind, h)
        if s_status is not None:
            was[tid] = (s_status, int(s_n))
        if was.get(tid) != (status, int(n)) and state.kept:
            dirty.append(tid)
            posts.update(p for p in (a, b) if p)
    state.tasks, state.keys, state.was = index, keys, was
    stamps = table_stamps(cur, NEWS_TABLES)
    changed = sorted(t for t in NEWS_TABLES if state.stamps.get(t) != stamps[t]) if state.kept else list(NEWS_TABLES)
    state.stamps = stamps
    state.report = {"dirty_tasks": len(dirty), "dirty_posts": sorted(posts), "ix_changed": changed,
                    "texts_read": 0, "texts_loaded": 0, "inputs_rendered": 0, "inputs_kept": 0}
    if state.kept:
        cur.execute("SELECT key, input_hash FROM mx_inc_inputs")
        state.inputs_kept = dict(cur.fetchall())
        cur.execute("SELECT key, copies FROM mx_inc_copies")
        state.copies_kept = {k: frozenset(v) for k, v in cur.fetchall()}
        named = {h for h in state.inputs_kept.values()}
        need = sorted({tid for (kind, h), (tid, status, n) in index.items() if n and h in named} | set(dirty))
    else:
        need = sorted(tid for (tid, status, n) in index.values() if n)
    _read_calls(cur, state, need)
    return state.report


def _read_calls(cur: Any, state: State, ids: Sequence[str]) -> None:
    ids = [t for t in ids if t not in state.calls]
    if not ids:
        return
    cur.execute("""SELECT task_id::text, id::text, answer FROM mx_calls WHERE valid AND task_id = ANY(%s::uuid[])
                    ORDER BY task_id, created_at, ctid""", (ids,))
    got: Dict[str, List] = defaultdict(list)
    for tid, cid, answer in cur.fetchall():
        got[tid].append((answer, cid))
    for tid in ids:
        state.calls[tid] = got.get(tid, [])
        for _a, cid in state.calls[tid]:
            state.call_task[cid] = tid


def calls_of(cur: Any, state: State, tid: str) -> List[Tuple[Dict[str, Any], str]]:
    """A task's valid calls, oldest first (read on first use when the kept inputs didn't name it)."""
    if tid not in state.calls:
        _read_calls(cur, state, [tid])
    return state.calls[tid]


# ---- the posts -------------------------------------------------------------------------------------------

def _stamps_sql(where: str) -> str:
    from insight_core.markx.plan_marks import STAMP
    return f"SELECT p.id::text, {STAMP} FROM posts p WHERE {where}"


def stamps_of(cur: Any, state: State, ids: Iterable[str]) -> Dict[str, str]:
    """The posts' text stamps (those not known to this reading are read)."""
    ids = sorted(set(ids))
    missing = [i for i in ids if i not in state.stamp]
    if missing:
        from insight_core.markx.plan_marks import execute
        state.stamp.update(dict(execute(cur, _stamps_sql("p.id = ANY(%(ids)s::uuid[])"), {"ids": missing})))
    return {i: state.stamp[i] for i in ids if i in state.stamp}


def world(cur: Any, state: State, ids: Iterable[str]) -> Tuple["LazyTexts", Dict[str, Any], "LazyReadings"]:
    """The world's posts as the rules read them (decide.Post), their texts and their readings, both read on use. A
    post's rules' Post is kept by its stamp: read again (its text) only when the stamp changed or it is new (a full
    reading: every post's), a page at a time; none of those texts is kept (v10.17.2, 0204)."""
    from insight_core.markx import decide, tasks
    from insight_core.markx.plan_marks import execute
    ids = sorted(set(ids))
    rules: Dict[str, Any] = {}
    stale: List[str] = []
    if state.kept:
        quiet = not set(state.report.get("ix_changed") or ()) & set(TEXT_TABLES)
        if quiet:   # no row of Mark IX's text tables changed: the kept stamps are the stamps
            cur.execute("""SELECT post_id::text, stamp, voice, kind, at, words FROM mx_inc_posts
                            WHERE post_id = ANY(%s::uuid[])""", (ids,))
            rows = {r[0]: r for r in cur.fetchall()}
            stamps_of(cur, state, [i for i in ids if i not in rows])
        else:
            rows = {r[0]: r for r in execute(cur, f"""
                SELECT p.id::text, ip.stamp, ip.voice, ip.kind, ip.at, ip.words, {_stamp_expr()}
                  FROM posts p LEFT JOIN mx_inc_posts ip ON ip.post_id = p.id
                 WHERE p.id = ANY(%(ids)s::uuid[])""", {"ids": ids})}
            for pid, r in rows.items():
                state.stamp[pid] = r[6]
        for pid in ids:
            r = rows.get(pid)
            if r is not None and pid not in state.stamp:
                state.stamp[pid] = r[1]
            if r is not None and r[1] is not None and r[2] is not None and r[1] == state.stamp.get(pid):
                rules[pid] = decide.Post(pid, r[2], r[3], r[4], r[5])
            elif pid in state.stamp:
                stale.append(pid)
    else:
        stamps_of(cur, state, ids)
        stale = [i for i in ids if i in state.stamp]
    for k in range(0, len(stale), TEXT_PAGE):   # v10.17.2 (0204): a page of texts at a time, none kept (below)
        part = stale[k:k + TEXT_PAGE]
        got = tasks.load_posts(cur, part)
        for pid in part:
            p = got.get(pid)
            if p is None:
                continue
            rules[pid] = decide.Post(pid, p.voice, p.kind, p.at, tasks.words(p))   # 0168 E: the voice it counts as
            state.fresh_posts[pid] = (state.stamp[pid], p.source_id, p.voice, p.kind, p.at, rules[pid].words)
        state.report["texts_loaded"] += len(got)
    state.report["texts_read"] = len(stale)
    state.rules = {pid: rules[pid] for pid in ids if pid in rules}
    cur.execute("""SELECT post_id::text, xmin::text || ctid::text, reading->'kind', reading->'events' FROM mx_readings
                    WHERE guide = %s AND post_id = ANY(%s::uuid[])""", (GUIDE, ids))   # as tasks.readings(ids)
    for pid, stamp, kind, events in cur.fetchall():
        state.read_stamp[pid], state.kinds[pid], state.events[pid] = stamp, kind, events
    # v10.17.2 (0204): the texts and readings are read when a render shows them (`rendered`: its posts' in one query),
    # on a full reading too: it held every post's text and reading for the whole reading (130k posts, ~2.7 GB at
    # server scale, the full run's peak), of which the questions show a few thousand
    return LazyTexts(cur, state), state.rules, LazyReadings(cur, state)


def _stamp_expr() -> str:
    from insight_core.markx.plan_marks import STAMP
    return STAMP


class LazyTexts(Mapping):
    """The world's texts (tasks.Post), read when first used. Holds the world's posts; others may be read through it
    (`load`) but are not in it."""

    def __init__(self, cur: Any, state: State) -> None:
        self.cur, self.state = cur, state

    def load(self, ids: Iterable[str]) -> Dict[str, Any]:
        from insight_core.markx import tasks
        s = self.state
        missing = sorted({i for i in ids if i not in s.texts})
        if missing:
            got = tasks.load_posts(self.cur, missing)
            s.texts.update(got)
            s.report["texts_loaded"] = s.report.get("texts_loaded", 0) + len(got)
        return {i: s.texts[i] for i in ids if i in s.texts}

    def __getitem__(self, pid: str) -> Any:
        if pid not in self.state.rules:
            raise KeyError(pid)
        if pid not in self.state.texts:
            self.load([pid])
        return self.state.texts[pid]

    def __contains__(self, pid: object) -> bool:
        return pid in self.state.rules

    def __iter__(self) -> Iterator[str]:
        return iter(self.state.rules)

    def __len__(self) -> int:
        return len(self.state.rules)

    def items(self):   # every text: read at once
        self.load(self.state.rules)
        return [(i, self.state.texts[i]) for i in self.state.rules if i in self.state.texts]


def release(state: State) -> None:
    """0183: the texts and readings this run read, let go once the reading is done (the decision run's stages after
    News read neither; were held to the run's end, beside the entity book: a full run's every text). A text or reading
    used after is read again, from the run's one snapshot."""
    state.texts.clear()
    state.readings.clear()


class LazyReadings(Mapping):
    """The world's readings, read when first used; which posts have one is known from the start."""

    def __init__(self, cur: Any, state: State) -> None:
        self.cur, self.state = cur, state

    def prefetch(self, ids: Iterable[str]) -> None:
        from insight_core.markx import tasks
        s = self.state
        missing = sorted({i for i in ids if i in s.kinds and i not in s.readings})
        if missing:
            s.readings.update(tasks.readings(self.cur, missing, GUIDE))

    def __getitem__(self, pid: str) -> dict:
        if pid not in self.state.kinds:
            raise KeyError(pid)
        if pid not in self.state.readings:
            self.prefetch([pid])
        return self.state.readings[pid]

    def __contains__(self, pid: object) -> bool:
        return pid in self.state.kinds

    def __iter__(self) -> Iterator[str]:
        return iter(self.state.kinds)

    def __len__(self) -> int:
        return len(self.state.kinds)


# ---- the renders, kept by what they show -----------------------------------------------------------------------

class Input:
    """A question's input: its sha256 always, its text when rendered (a kept one is rendered only when the task must
    be added)."""
    __slots__ = ("hash", "_text", "_render")

    def __init__(self, h: str, text: Optional[str] = None, render: Optional[Callable[[], str]] = None) -> None:
        self.hash, self._text, self._render = h, text, render

    @property
    def text(self) -> str:
        if self._text is None:
            self._text = self._render()
            if _sha(self._text) != self.hash:   # a kept key must render what it was kept for: a bug, logged
                log.error("Mark X incremental run: a kept input renders otherwise (%s); the state is wrong", self.hash)
                self.hash = _sha(self._text)
        return self._text

    def __str__(self) -> str:
        return self.text


def text_of(text: Any) -> str:
    return text.text if isinstance(text, Input) else text


def hash_of(text: Any) -> str:
    return text.hash if isinstance(text, Input) else _sha(text)


def _fingerprint(state: State, ids: Sequence[str], reads: bool) -> str:
    parts = []
    for i in ids:
        if i == "|":
            parts.append("|")
            continue
        p = f"{i}:{state.stamp.get(i)}"
        if reads:
            p += f":{state.read_stamp.get(i)}"
        parts.append(p)
    return "\n".join(parts)


def rendered(state: Optional[State], kind: str, ids: Sequence[str], render: Callable[[], str], *, reads: bool = False,
             extra: Sequence[str] = (), texts: Optional[LazyTexts] = None,
             readings: Optional[LazyReadings] = None) -> Any:
    """`render()`'s input (a str without a state; else an Input), kept by the stamps of `ids` (the posts it shows, "|"
    between groups; `reads`: and their readings' row versions) and `extra` (any answer it shows). A render that misses
    reads its posts' texts (and readings) in one query first."""
    if state is None:
        return render()
    stamps_of_needed = [i for i in ids if i != "|" and i not in state.stamp]
    if stamps_of_needed and texts is not None:
        stamps_of(texts.cur, state, stamps_of_needed)
    key = _sha("\0".join((kind, _fingerprint(state, ids, reads), *extra)))

    def made() -> str:
        if texts is not None:
            texts.load([i for i in ids if i != "|"])
        if readings is not None:
            readings.prefetch([i for i in ids if i != "|"])
        return render()
    if state.kept and key in state.inputs_kept:
        h = state.inputs_kept[key]
        state.report["inputs_kept"] = state.report.get("inputs_kept", 0) + 1
        out = Input(h, render=made)
    else:
        text = made()
        state.report["inputs_rendered"] = state.report.get("inputs_rendered", 0) + 1
        out = Input(_sha(text), text=text)
    state.inputs[key] = (kind, out.hash)
    return out


def copies(state: State, ids: Sequence[str], texts: LazyTexts) -> frozenset:
    """tasks.near_copies of a story's members, kept by their stamps."""
    from insight_core.markx import tasks
    key = _sha("copies\0" + _fingerprint(state, ids, False))
    if state.kept and key in state.copies_kept:
        found = state.copies_kept[key]
    else:
        got = texts.load(ids)
        found = frozenset(tasks.near_copies([got[i] for i in ids if i in got]))
    state.copies[key] = found
    return found


def surges(cur: Any, memo: Optional[State]) -> List[Any]:
    """Mark IX's stored surges, longest first as News reads them (news_rules.longest), read once a reading."""
    from insight_core.db.repo_news import NewsRepository
    from insight_core.utils.news_rules import longest
    stamp = (memo.stamps or {}).get("news_surges") if memo is not None else None
    if memo is not None and stamp is not None and memo.surges is not None and memo.surges[0] == stamp:
        return memo.surges[1]
    found = sorted(longest(NewsRepository.stored_surges(cur)), key=lambda s: (s.at, s.name))
    if memo is not None and stamp is not None:
        memo.surges = (stamp, found)
    return found


# ---- what a run leaves -------------------------------------------------------------------------------------

def save(cur: Any, state: State, run_id: Any, want: Dict[str, Dict[str, Tuple]]) -> Dict[str, int]:
    """The state this run leaves (nothing for a dry reading): its posts' rules (the world's only), the inputs and
    near-copies it used (only those), what it saw of every judge task, its stamps, News and memberships."""
    if state.dry:
        return {}
    out: Dict[str, int] = {}
    world_ids = sorted(state.rules)
    cur.execute("""DELETE FROM mx_inc_posts ip
                    WHERE NOT EXISTS (SELECT 1 FROM unnest(%s::uuid[]) w(id) WHERE w.id = ip.post_id)""", (world_ids,))
    out["posts_dropped"] = cur.rowcount
    rows = [(pid, *r) for pid, r in state.fresh_posts.items() if pid in state.rules]
    if rows:
        cur.execute("""INSERT INTO mx_inc_posts (post_id, stamp, source_id, voice, kind, at, words)
                       SELECT * FROM unnest(%s::uuid[], %s::text[], %s::text[], %s::text[], %s::text[],
                                            %s::timestamptz[], %s::int[])
                       ON CONFLICT (post_id) DO UPDATE SET stamp = EXCLUDED.stamp, source_id = EXCLUDED.source_id,
                              voice = EXCLUDED.voice,
                              kind = EXCLUDED.kind, at = EXCLUDED.at, words = EXCLUDED.words""",
                    tuple(list(col) for col in zip(*rows)))
    out["posts_written"] = len(rows)
    for table, kept, now_ in (("mx_inc_inputs", state.inputs_kept, state.inputs),
                              ("mx_inc_copies", state.copies_kept, state.copies)):
        if state.full:
            cur.execute(f"DELETE FROM {table}")
            gone = []
        else:
            gone = sorted(set(kept) - set(now_))
            if gone:
                cur.execute(f"DELETE FROM {table} WHERE key = ANY(%s)", (gone,))
        if table == "mx_inc_inputs":
            new = [(k, kind, h) for k, (kind, h) in now_.items() if state.full or kept.get(k) != h]
            if new:
                cur.execute("""INSERT INTO mx_inc_inputs (key, kind, input_hash)
                               SELECT * FROM unnest(%s::text[], %s::text[], %s::text[])
                               ON CONFLICT (key) DO UPDATE SET kind = EXCLUDED.kind, input_hash = EXCLUDED.input_hash""",
                            tuple(list(col) for col in zip(*new)))
        else:
            new = [(k, sorted(v)) for k, v in now_.items() if state.full or kept.get(k) != v]
            if new:
                cur.executemany("""INSERT INTO mx_inc_copies (key, copies) VALUES (%s, %s)
                                   ON CONFLICT (key) DO UPDATE SET copies = EXCLUDED.copies""", new)
        out[table[7:] + "_written"], out[table[7:] + "_dropped"] = len(new), len(gone)
    seen = [(tid, status, n) for (_k, (tid, status, n)) in state.tasks.items() if state.was.get(tid) != (status, n)]
    if seen:
        cur.execute("""INSERT INTO mx_inc_tasks (task_id, status, n)
                       SELECT * FROM unnest(%s::uuid[], %s::text[], %s::int[])
                       ON CONFLICT (task_id) DO UPDATE SET status = EXCLUDED.status, n = EXCLUDED.n""",
                    tuple(list(col) for col in zip(*seen)))
    out["tasks_written"] = len(seen)
    cur.execute("""INSERT INTO mx_inc_state (name, run_id, key, stamps, news, want, saved_at)
                   VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, now())
                   ON CONFLICT (name) DO UPDATE SET run_id = EXCLUDED.run_id, key = EXCLUDED.key, stamps = EXCLUDED.stamps,
                          news = EXCLUDED.news, want = EXCLUDED.want, saved_at = EXCLUDED.saved_at""",
                (NAME, str(run_id), state.key, encode(state.stamps), encode(state.news), encode(want)))
    return out


# ---- the closure (reported) ----------------------------------------------------------------------------------

def closure(memo: State, want: Dict[str, Dict[str, Tuple]], ix: Dict[str, Sequence[Any]]) -> Dict[str, Any]:
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

def digest(want: Dict[str, Dict[str, Tuple]], connections: Sequence[Dict[str, Any]],
           news_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """A run's results without its keys or ids: each story by its memberships (post, role, reason, p, call); each
    typed connection by its ends (a post, or a story's member posts: the caller maps them) and its answer; each News
    row with its posts and tag."""
    stories = {tuple(sorted((p, *r) for p, r in ms.items())) for ms in want.values()}
    conns = {(c["a_kind"], c["a"], c["b_kind"], c["b"], c["relation"], round(float(c["p"]), 4), c.get("call"))
             for c in connections}
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
