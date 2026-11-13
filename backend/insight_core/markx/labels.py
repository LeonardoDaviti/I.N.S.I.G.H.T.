"""Mark X Shadow's labels (issue 0086 F): the owner's answers to Haiku's questions, and each feature's precision on them.

The queue (the prototype's E1, plan/research/lab/markx/proto: e1_items.py, fresh_items.py, merge_items.py):
  - the questions behind the decision job's decisions, read as the last run would (decide.think, with an Ask that
    never adds a task) plus the answered connect (F6) and entities (F7) tasks;
  - every decision within `Settings.near` (0.05) of its bar, and every merge question;
  - of the rest, a sample of `Settings.sample` per pool (a feature's accepted side and its rejected side), in a stable
    hash order, weighted back to the pool's size when precision is counted (eval_fresh.py's weights).
Each item is a task (keyed by its content, never by a Mark IX story id): its evidence is the task's input, the exact
text the judge saw. Its verdict is never sent before the item is answered.

An answer is one tap: same event, follow-up, related, different, unsure (a question about how two things relate); or
right, wrong, unsure (the entities a post names); plus an optional note. One tap on a Mark X News member ("wrong
story", "not about this", or "ok" to take it back) is a label too.

Storage: mx_labels (S1), keep everything: a changed answer is a new row, and the newest row of an item counts.
  - a question's label: item_kind check, join (joins and pairs), merge, connection or entity; `a` the task's id,
    `b` the post asked about (the second story's first post for merges and connections);
  - a News member's: item_kind news_row, `a` the post, `b` its Mark X story.

The split: an item's day is its newest post's; the newest `test_share` of the queue's days are test, the rest dev, and
a label keeps the split it was given. Precision is counted per pool (post-stratified: each labelled item weighs its
pool's size over the pool's labelled count), with a Wilson 95% interval on the Kish effective count; each feature's
bar is swept on dev and reported on test.

Where it is built (0182): insight-ingestion's jobs process builds the newest decision run's queue after each run and
keeps it (`keep`: mx_label_queues, mx_label_queue_items); the API reads only the kept queue (`kept`), never
`population`, and says "being built" until it is kept.
"""
from __future__ import annotations

import hashlib
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from insight_core.markx import decide, repo, schemas


@dataclass(frozen=True)
class Settings:
    near: float = 0.05          # a decision this close to its bar is asked, every one (one step of the judge's
                                # confidence, which comes in fives: 0.55, 0.60 and 0.65 around the 0.6 bar)
    sample: int = 6             # of each pool's rest, this many (E1: about two hours; measured, 0086 F Built)
    test_share: float = 0.25    # the newest quarter of the queue's days are test (the prototype held out 4 of 16)
    target: float = 0.95        # the precision a bar is re-picked for on dev (the owner's to set)
    min_dev: int = 10           # a re-picked bar needs at least this many labelled decisions on dev
    seed: str = "markx-e1"      # the sample's order: a stable hash of the seed and the task
    bars: Tuple[float, ...] = (0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


RELATION_ANSWERS = ("same_event", "follow_up", "related", "different", "unsure")
ENTITY_ANSWERS = ("right", "wrong", "unsure")
NEWS_ANSWERS = ("wrong_story", "not_about", "ok")
ABOUT_ANSWERS = frozenset({"same_event", "follow_up"})     # a post about the story's event (a follow-up joins, F2)
SKIP = frozenset({"unsure"})


@dataclass(frozen=True)
class Feature:
    key: str            # the question type (decide.Question.type), or connect / entities
    name: str
    item_kind: str      # mx_labels.item_kind
    acted: str          # what the feature does when it accepts
    question: str       # what the owner is asked

    @property
    def answers(self) -> Tuple[str, ...]:
        return ENTITY_ANSWERS if self.key == "entities" else RELATION_ANSWERS


FEATURES = {f.key: f for f in (
    Feature("check", "F1 checks", "check", "taken out",
            "Is the POST about the STORY's event? (a member Mark IX put in the story)"),
    Feature("join", "F2 joins", "join", "joined", "Is the POST about the STORY's event?"),
    Feature("pair", "F2 new stories", "join", "made a story", "Is the POST about the same event as the STORY's post?"),
    Feature("merge", "Merges", "merge", "merged", "Are STORY A and STORY B the same event?"),
    Feature("connect", "F6 connections", "connection", "connected", "How does STORY B relate to STORY A?"),
    Feature("entities", "F7 entities", "entity", "named right",
            "Are these the post's entities, named right (names, versions, roles)?"),
)}
ORDER = list(FEATURES)


@dataclass
class Item:
    id: str                      # the task
    feature: str
    post: Optional[str]          # mx_labels.b
    day: Optional[datetime]
    p: Optional[float] = None
    bar: Optional[float] = None
    relation: Optional[str] = None
    reason: Optional[str] = None
    accepted: bool = True        # the decision: taken out (checks), joined, made a story, merged, connected
    pool: str = ""
    weight_hint: float = 1.0     # the pool's size over the items the queue offers from it
    queued: bool = False
    rank: str = ""


@dataclass
class Queue:
    run: Optional[str]
    items: Dict[str, Item] = field(default_factory=dict)     # the whole population, queued or not
    order: List[str] = field(default_factory=list)            # the queued items, in the order offered
    pools: Counter = field(default_factory=Counter)           # pool -> population size
    cut: Optional[str] = None                                  # the first test day (ISO date)

    def split_of(self, item: Item) -> str:
        if self.cut is None or item.day is None:
            return "dev"
        return "test" if item.day.date().isoformat() >= self.cut else "dev"

    def sizes(self) -> Counter:
        """(pool, split) -> population."""
        size: Counter = Counter()
        for it in self.items.values():
            size[(it.pool, self.split_of(it))] += 1
        return size

    def bar_of(self, feature: str) -> Optional[float]:
        """The feature's bar: the first item's of the population that has one."""
        return next((it.bar for it in self.items.values() if it.feature == feature and it.bar is not None), None)

    def ensure(self, cur: Any, ids: Iterable[str]) -> None:
        """These items in `items` when the queue has them (a queue built here holds every item already)."""


@dataclass
class Kept(Queue):
    """A queue the jobs process built and kept (mx_label_queues, 0182): its header read whole, its items only as a
    page needs them (`ensure`): the queued ones, one item, the labelled ones. Never a reading of its own."""
    key: Optional[str] = None                                  # mx_label_queues.id (None: nothing kept yet)
    building: bool = False                                     # the newest run's queue is not kept yet
    size: Counter = field(default_factory=Counter)             # (pool, split) -> population
    bars: Dict[str, Optional[float]] = field(default_factory=dict)
    absent: set = field(default_factory=set)                   # ids asked for that the queue doesn't hold

    def sizes(self) -> Counter:
        return self.size

    def bar_of(self, feature: str) -> Optional[float]:
        return self.bars.get(feature)

    def ensure(self, cur: Any, ids: Iterable[str]) -> None:
        want = sorted({str(i) for i in ids if i} - set(self.items) - self.absent)
        if not want or self.key is None:
            return
        cur.execute("""SELECT id::text, feature, post::text, day, p, bar, relation, reason, accepted, pool, weight_hint,
                              queued FROM mx_label_queue_items WHERE queue_id = %s AND id = ANY(%s::uuid[]) ORDER BY seq""",
                    (self.key, [i for i in want if _is_uuid(i)]))
        for iid, feature, post, day, p, bar, relation, reason, accepted, pool, weight_hint, queued in cur.fetchall():
            self.items[iid] = Item(id=iid, feature=feature, post=post, day=day, p=p, bar=bar, relation=relation,
                                   reason=reason, accepted=accepted, pool=pool, weight_hint=weight_hint, queued=queued)
        self.absent |= set(want) - set(self.items)


# ---- the decisions, read without writing --------------------------------------------------------------

class _Reader(decide.Ask):
    """The decision job's Ask that only reads: no task is added; each answer's task is remembered by its call."""

    def __init__(self, cur: Any, now: datetime) -> None:
        super().__init__(cur, now)
        self.task_of: Dict[str, Dict[str, Any]] = {}

    def answer(self, kind: str, text: str, **_kw) -> Optional[Tuple[Dict[str, Any], str]]:
        task = repo.task_for(self.cur, kind=kind, guide=schemas.KINDS[kind].guide, input=text)
        if task is None or task["status"] != "answered":
            return None
        call = repo.valid_call(self.cur, task["id"])
        if call is None:
            return None
        # 0182: only what `population` reads of the task (its input, ~1.5 kB a row, is not held)
        self.task_of[str(call["id"])] = {"id": task["id"], "a": task["a"], "b": task["b"]}
        return call["answer"], str(call["id"])


def _rank(settings: Settings, task_id: str) -> str:
    return hashlib.sha256(f"{settings.seed}:{task_id}".encode()).hexdigest()


def _times(cur: Any, ids: Iterable[Any]) -> Dict[str, datetime]:
    ids = sorted({str(i) for i in ids if i})
    if not ids:
        return {}
    cur.execute("SELECT id::text, COALESCE(surfaced_at, published_at, fetched_at) FROM posts WHERE id = ANY(%s::uuid[])",
                (ids,))
    return dict(cur.fetchall())


# 0182: of a judge's answer `population` reads only the verdict's three fields (connect, and the labelled questions),
# and of an entities answer only whether it names anything, Python's truth of `answer["entities"]`: both taken in SQL,
# so the answers themselves (an entities answer ~0.6-2 kB; ~130k on a server) are never loaded. Measured on a copy
# with 138k answered entities tasks: the population's peak 532 -> 85 MB of Python allocations, the process's 732 ->
# 223 MB, 17 -> 4.5 s; the same items in the same order (issue 0182).
_VERDICT_SQL = "c.answer->'relation', c.answer->'confidence', c.answer->'reason'"
_NAMES_SQL = """CASE jsonb_typeof(c.answer->'entities')
                     WHEN 'array' THEN jsonb_array_length(c.answer->'entities') > 0
                     WHEN 'object' THEN c.answer->'entities' <> '{}'::jsonb
                     WHEN 'string' THEN c.answer->>'entities' <> ''
                     WHEN 'number' THEN (c.answer->>'entities')::numeric <> 0
                     WHEN 'boolean' THEN (c.answer->>'entities')::boolean
                     ELSE false END"""
PAGE = 5000         # rows a fetch (the answered connect and entities tasks are read a page at a time)


def _verdict(relation: Any, confidence: Any, reason: Any) -> decide.Verdict:
    """decide.Verdict.of on the answer's three fields as SQL gave them (an absent field is None, as .get gives it)."""
    return decide.Verdict.of({"relation": relation, "confidence": confidence, "reason": reason})


def _pages(cur: Any) -> Iterable[Tuple[Any, ...]]:
    while True:
        rows = cur.fetchmany(PAGE)
        if not rows:
            return
        yield from rows


def population(cur: Any, *, config: decide.Config = decide.Config(), now: Optional[datetime] = None) -> List[Item]:
    """Every question behind a decision, with its verdict and its decision: the decision job's checks, joins, pairs
    and merges as the last run read them (nothing is written), and the answered connect and entities tasks.
    0182: the decision reading is let go before the tasks are read, and the tasks' answers are read only as far as
    the items need them (`_VERDICT_SQL`, `_NAMES_SQL`), a page at a time: the same items, a lower peak."""
    import gc
    now = now or datetime.now(timezone.utc)
    world = decide.load(cur, now, config)
    ask = _Reader(cur, now)
    answered: List[Tuple[decide.Question, decide.Verdict]] = []
    decide.think(cur, world, config, ask, now, answered=answered)
    del world
    items: Dict[str, Item] = {}
    raw: List[Tuple[Item, Dict[str, Any]]] = []
    for q, v in answered:
        task = ask.task_of.get(v.call or "")
        if task is None or str(task["id"]) in items:
            continue
        if q.type == "check":
            bar = config.tau_keep2 if q.voices <= 2 else config.tau_keep
            accepted = v.p < bar
        elif q.type in ("join", "pair"):
            bar = config.tau_join
            accepted = v.relation in decide.ABOUT and v.p >= bar
        else:
            bar = config.tau_merge
            accepted = v.relation == "same_event" and v.p >= bar
        post = str(task["b"]) if q.type in ("pair", "merge") and task["b"] else str(task["a"]) if task["a"] else None
        it = Item(id=str(task["id"]), feature=q.type, post=post, day=None, p=round(v.p, 4), bar=bar,
                  relation=v.relation, reason=v.reason, accepted=accepted)
        items[it.id] = it
        raw.append((it, task))
    del ask, answered
    gc.collect()                             # the reading's cycles, before the tasks are read
    cur.execute(f"""SELECT t.id::text, t.kind, t.a::text, t.b::text, {_VERDICT_SQL}, {_NAMES_SQL} FROM mx_tasks t
                     JOIN LATERAL (SELECT answer FROM mx_calls WHERE task_id = t.id AND valid
                                    ORDER BY created_at, ctid LIMIT 1) c ON true
                    WHERE t.kind IN ('connect', 'entities') AND t.status = 'answered' AND t.created_at <= %s""", (now,))
    for tid, kind, a, b, relation, confidence, reason, named in _pages(cur):
        if tid in items:
            continue
        if kind == "connect":
            v = _verdict(relation, confidence, reason)
            it = Item(id=tid, feature="connect", post=b or a, day=None, p=round(v.p, 4), bar=config.tau_connect,
                      relation=v.relation, reason=v.reason,
                      accepted=v.relation in decide.CONNECT_RELATIONS and v.p >= config.tau_connect)
        else:
            if not named:
                continue                     # nothing named: nothing to call right or wrong
            it = Item(id=tid, feature="entities", post=a, day=None)
        items[tid] = it
        raw.append((it, {"a": a, "b": b}))
    # labelled questions today's run no longer asks (their story changed, or they left the window) keep counting,
    # each in its feature's "earlier" pool, by its own answer (a check at the 0.30 bar: its story's voices are gone)
    kind_of = {f.item_kind: f.key for f in FEATURES.values()}
    cur.execute(f"""SELECT DISTINCT t.id::text, t.kind, t.a::text, t.b::text, l.item_kind, {_VERDICT_SQL}
                     FROM mx_labels l JOIN mx_tasks t ON t.id = l.a
                     JOIN LATERAL (SELECT answer FROM mx_calls WHERE task_id = t.id AND valid
                                    ORDER BY created_at, ctid LIMIT 1) c ON true
                    WHERE l.item_kind <> 'news_row'""")
    for tid, kind, a, b, item_kind, relation, confidence, reason in _pages(cur):
        if tid in items:
            continue
        feature = kind if kind in FEATURES else kind_of.get(item_kind)
        if feature is None or FEATURES[feature].item_kind != item_kind:
            continue
        it = Item(id=tid, feature=feature, post=b if feature in ("pair", "merge", "connect") and b else a, day=None,
                  pool=f"{feature}:earlier")
        if feature != "entities":
            v = _verdict(relation, confidence, reason)
            it.p, it.relation, it.reason = round(v.p, 4), v.relation, v.reason
            it.bar = {"check": config.tau_keep, "join": config.tau_join, "pair": config.tau_join,
                      "merge": config.tau_merge, "connect": config.tau_connect}[feature]
            it.accepted = _accepts(it, it.bar)
        items[tid] = it
        raw.append((it, {"a": a, "b": b}))
    times = _times(cur, [x for _it, t in raw for x in (t.get("a"), t.get("b"))])
    for it, task in raw:
        ts = [times[str(x)] for x in (task.get("a"), task.get("b")) if x and str(x) in times]
        it.day = max(ts) if ts else None
    return list(items.values())


def _pool(settings: Settings, it: Item) -> str:
    if it.pool.endswith(":earlier"):
        return it.pool
    if it.feature == "merge":
        return "merge:all"
    if it.feature == "entities":
        return "entities:all"
    if it.p is not None and it.bar is not None and abs(it.p - it.bar) <= settings.near + 1e-9:
        return f"{it.feature}:near"
    return f"{it.feature}:{'accepted' if it.accepted else 'rejected'}"


def build(items: Sequence[Item], settings: Settings = Settings(), run: Optional[str] = None) -> Queue:
    """The queue from the population: every item near a bar and every merge, a stable sample of each other pool,
    interleaved feature by feature so a short session still labels every feature."""
    q = Queue(run=run)
    by_pool: Dict[str, List[Item]] = defaultdict(list)
    for it in items:
        it.pool = _pool(settings, it)
        it.rank = _rank(settings, it.id)
        q.items[it.id] = it
        by_pool[it.pool].append(it)
    per_feature: Dict[str, List[Item]] = defaultdict(list)
    for pool, its in sorted(by_pool.items()):
        q.pools[pool] = len(its)
        if pool.endswith(":earlier"):
            continue                          # already labelled: counted, never offered again
        everyone = pool.endswith(":near") or pool == "merge:all"
        if pool.endswith(":near"):
            its.sort(key=lambda i: (abs((i.p or 0) - (i.bar or 0)), i.rank))
        else:
            its.sort(key=lambda i: i.rank)
        take = its if everyone else its[:settings.sample]
        for it in take:
            it.queued = True
            it.weight_hint = len(its) / max(1, len(take))
        per_feature[pool.split(":")[0]].extend(take)
    for f in per_feature:
        per_feature[f].sort(key=lambda i: (0 if i.pool.endswith(":near") or i.pool == "merge:all" else 1, i.rank))
    lanes = [per_feature[f] for f in ORDER if per_feature.get(f)]
    while any(lanes):
        for lane in lanes:
            if lane:
                q.order.append(lane.pop(0).id)
    days = sorted(q.items[i].day.date().isoformat() for i in q.order if q.items[i].day)
    if days:
        distinct = sorted(set(days))
        k = max(1, round(len(distinct) * settings.test_share))
        q.cut = distinct[-k] if len(distinct) > 1 else None
    return q


# ---- the queue, built by the jobs process and kept (0182) ------------------------------------------------
#
# The queue is a whole decision reading (`population`): on a server-sized copy a 2.4 GB peak of Python allocations.
# It was built in insight-api on the first open after each run, and the API's RSS stayed at that high-water mark.
# insight-ingestion's jobs process builds it after each decision run (jobs.Jobs.labels, its own process and
# transaction) and keeps it in mx_label_queues; the API reads only what is kept (`kept`), never `population`.

KEEP_ITEMS = 3      # the newest queues whose items are kept (every header is kept: what it held, its size, its cost)


def _is_uuid(value: str) -> bool:
    import uuid
    try:
        uuid.UUID(value)
        return True
    except (TypeError, ValueError, AttributeError):
        return False


_stamps: Dict[str, str] = {}


def stamp(settings: Settings = Settings()) -> str:
    """The code a kept queue was built by: the decision reading's (decide's version, incremental.code_stamp), this
    module's and the guides', and the settings. A queue of another stamp is never read: after a deploy that changes
    any of them the queue is built again."""
    key = repr(sorted(settings.as_dict().items()))
    if key not in _stamps:
        import importlib
        from insight_core.markx import incremental
        h = hashlib.sha256(f"{decide.CODE_VERSION}\0{incremental.code_stamp()}\0".encode())
        for name in ("insight_core.markx.labels", "insight_core.markx.schemas"):
            with open(importlib.import_module(name).__file__, "rb") as f:
                h.update(name.encode() + b"\0" + f.read() + b"\0")
        h.update(key.encode())
        _stamps[key] = h.hexdigest()
    return _stamps[key]


def queue(cur: Any, *, settings: Settings = Settings(), now: Optional[datetime] = None) -> Queue:
    """The queue for the newest decision run, read now: a whole decision reading (nothing is written). The one place
    a queue is built: `keep` (the jobs process) calls it, and the tests; a page reads only the kept queue (`kept`)."""
    last = repo.last_run(cur)
    run = str(last["id"]) if last else None
    if run is None:
        return Queue(run=None)
    return build(population(cur, now=now), settings, run=run)


def missing(cur: Any, settings: Settings = Settings()) -> bool:
    """Whether the newest decision run has no kept queue of this code's stamp (the jobs process builds it then)."""
    last = repo.last_run(cur)
    if last is None:
        return False
    cur.execute("SELECT 1 FROM mx_label_queues WHERE run_id = %s AND stamp = %s", (last["id"], stamp(settings)))
    return cur.fetchone() is None


def keep(cur: Any, *, settings: Settings = Settings(), now: Optional[datetime] = None,
         peak: Optional[Callable[[], float]] = None) -> Dict[str, Any]:
    """In the jobs process: the newest decision run's queue (`queue`), kept in the caller's transaction, header and
    items; the items of the queues older than the newest KEEP_ITEMS are pruned (their headers stay). Nothing when
    there is no run or its queue is kept already. `peak()`: the process's peak memory in MB, recorded with it."""
    import time
    last = repo.last_run(cur)
    if last is None:
        return {"kept": None, "why": "no decision run yet"}
    run, st = str(last["id"]), stamp(settings)
    cur.execute("SELECT id::text FROM mx_label_queues WHERE run_id = %s AND stamp = %s", (run, st))
    got = cur.fetchone()
    if got:
        return {"kept": got[0], "run": run, "already": True}
    t0 = time.monotonic()
    now = now or datetime.now(timezone.utc)
    q = queue(cur, settings=settings, now=now)
    seconds = round(time.monotonic() - t0, 2)
    key = _store(cur, q, stamp=st, settings=settings, read_at=now, seconds=seconds,
                 peak_mb=round(peak(), 1) if peak else None)
    pruned = prune(cur)
    # the pages read items by key: planned on fresh statistics (before autovacuum's, the copy read 40 ms an item)
    cur.execute("ANALYZE mx_label_queue_items")
    return {"kept": key, "run": run, "items": len(q.items), "queued": len(q.order), "seconds": seconds,
            **({"pruned": pruned} if pruned else {})}


def _store(cur: Any, q: Queue, *, stamp: str, settings: Settings, read_at: datetime, seconds: Optional[float],
           peak_mb: Optional[float]) -> str:
    import json
    sizes = [[pool, split, n] for (pool, split), n in sorted(q.sizes().items())]
    bars = {f: q.bar_of(f) for f in ORDER if any(it.feature == f for it in q.items.values())}
    cur.execute("""INSERT INTO mx_label_queues (run_id, stamp, settings, read_at, cut, queued, pools, sizes, bars, items,
                                                seconds, peak_mb)
                   VALUES (%s, %s, %s::jsonb, %s, %s, %s::uuid[], %s::jsonb, %s::jsonb, %s::jsonb, %s, %s, %s)
                   RETURNING id::text""",
                (q.run, stamp, json.dumps(settings.as_dict()), read_at, q.cut, list(q.order), json.dumps([[p, n] for p, n in q.pools.items()]),
                 json.dumps(sizes), json.dumps(bars), len(q.items), seconds, peak_mb))
    key = cur.fetchone()[0]
    with cur.copy("""COPY mx_label_queue_items (queue_id, id, seq, feature, post, day, p, bar, relation, reason,
                                                accepted, pool, weight_hint, queued) FROM STDIN""") as copy:
        for seq, it in enumerate(q.items.values()):
            copy.write_row((key, it.id, seq, it.feature, it.post, it.day, it.p, it.bar, it.relation, it.reason,
                            it.accepted, it.pool, it.weight_hint, it.queued))
    return key


def prune(cur: Any, keep_items: int = KEEP_ITEMS) -> int:
    """The items of every queue but the newest `keep_items` (by when built) go; their headers stay. How many queues."""
    cur.execute("""UPDATE mx_label_queues SET items_kept = false
                    WHERE id IN (SELECT id FROM mx_label_queues WHERE items_kept ORDER BY built_at DESC, id OFFSET %s)
                   RETURNING id""", (keep_items,))
    ids = [r[0] for r in cur.fetchall()]
    if ids:
        cur.execute("DELETE FROM mx_label_queue_items WHERE queue_id = ANY(%s::uuid[])", (ids,))
    return len(ids)


def kept(cur: Any, settings: Settings = Settings()) -> Kept:
    """The queue a page reads: the newest kept queue of this code's stamp, never a reading of its own. `building` when
    the newest decision run's queue is not kept yet (the jobs process builds it on its next pass): the newest kept
    one is read meanwhile if there is one, else nothing (`key` None, no items). No decision run: run None."""
    last = repo.last_run(cur)
    if last is None:
        return Kept(run=None)
    newest = str(last["id"])
    cur.execute("""SELECT id::text, run_id::text, cut, queued::text[], pools, sizes, bars FROM mx_label_queues
                    WHERE stamp = %s AND items_kept ORDER BY run_id = %s DESC, built_at DESC, id LIMIT 1""",
                (stamp(settings), newest))
    row = cur.fetchone()
    if row is None:
        return Kept(run=newest, building=True)
    key, run, cut, order, pools, sizes, bars = row
    return Kept(run=run, key=key, cut=cut, order=list(order or []), pools=Counter({p: n for p, n in pools or []}),
                size=Counter({(p, s): n for p, s, n in sizes or []}), bars=dict(bars or {}), building=run != newest)


# ---- labels ------------------------------------------------------------------------------------------

def latest(cur: Any, *, labeller: Optional[str] = "owner", kinds: Optional[Sequence[str]] = None) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(item_kind, a): the newest label} (of one labeller, or every labeller's newest when None: then keyed by
    (item_kind, a, labeller))."""
    cur.execute("""SELECT DISTINCT ON (item_kind, a, labeller) id::text, item_kind, a::text, b::text, answer, labeller,
                          split, note, created_at
                     FROM mx_labels WHERE (%(l)s::text IS NULL OR labeller = %(l)s)
                      AND (%(k)s::text[] IS NULL OR item_kind = ANY(%(k)s))
                    ORDER BY item_kind, a, labeller, created_at DESC, ctid DESC""",
                {"l": labeller, "k": list(kinds) if kinds else None})
    names = [d.name for d in cur.description]
    out = {}
    for row in cur.fetchall():
        r = dict(zip(names, row))
        out[(r["item_kind"], r["a"]) if labeller else (r["item_kind"], r["a"], r["labeller"])] = r
    return out


def label(cur: Any, q: Queue, item_id: str, answer: str, *, note: Optional[str] = None,
          labeller: str = "owner") -> Dict[str, Any]:
    """Store one answer to a queue item (a new row, whatever came before) and give back its verdict."""
    q.ensure(cur, [item_id])
    it = q.items.get(item_id)
    if it is None:
        raise KeyError(item_id)
    f = FEATURES[it.feature]
    if answer not in f.answers:
        raise ValueError(f"{answer!r} is not one of {', '.join(f.answers)}")
    note = (note or "").strip() or None
    split = q.split_of(it)
    lid = repo.add_label(cur, item_kind=f.item_kind, a=it.id, b=it.post, answer=answer, split=split, note=note,
                         labeller=labeller)
    return {"label": {"id": str(lid), "answer": answer, "note": note, "split": split}, "verdict": verdict(it)}


def flag(cur: Any, *, post: str, story: str, answer: str, note: Optional[str] = None, labeller: str = "owner") -> Dict[str, Any]:
    """One tap on a Mark X News member: "wrong story", "not about this", or "ok" (taken back)."""
    if answer not in NEWS_ANSWERS:
        raise ValueError(f"{answer!r} is not one of {', '.join(NEWS_ANSWERS)}")
    cur.execute("SELECT 1 FROM mx_story_posts WHERE story_id = %s AND post_id = %s LIMIT 1", (story, post))
    if cur.fetchone() is None:
        raise KeyError(f"{post} in {story}")
    lid = repo.add_label(cur, item_kind="news_row", a=post, b=story, answer=answer, note=(note or "").strip() or None,
                         labeller=labeller)
    return {"id": str(lid), "post": post, "story": story, "answer": answer}


def flags(cur: Any, pairs: Iterable[Tuple[str, str]], labeller: str = "owner") -> Dict[Tuple[str, str], str]:
    """{(post, story): the newest one-tap answer} for these News members (none when "ok" or never tapped)."""
    pairs = list(pairs)
    if not pairs:
        return {}
    cur.execute("""SELECT DISTINCT ON (a, b) a::text, b::text, answer FROM mx_labels
                    WHERE item_kind = 'news_row' AND labeller = %s
                      AND (a, b) IN (SELECT * FROM unnest(%s::uuid[], %s::uuid[]))
                    ORDER BY a, b, created_at DESC, ctid DESC""",
                (labeller, [p for p, _ in pairs], [s for _, s in pairs]))
    return {(a, b): ans for a, b, ans in cur.fetchall() if ans != "ok"}


def verdict(it: Item) -> Dict[str, Any]:
    f = FEATURES[it.feature]
    if it.feature == "entities":
        return {"decision": None}
    if it.feature == "check":
        decision = ("kept as a mention" if it.relation in ("mention", "digest_item") else "taken out") if it.accepted \
            else "kept"
    else:
        decision = f.acted if it.accepted else f"not {f.acted}"
    return {"relation": it.relation, "p": it.p, "reason": it.reason, "bar": it.bar, "decision": decision}


# ---- what an item shows ---------------------------------------------------------------------------------

def item_view(cur: Any, q: Queue, item_id: str, labeller: str = "owner") -> Optional[Dict[str, Any]]:
    """An item as the page shows it: the question, the evidence (the task's input, as the judge saw it), the answers;
    its verdict only once it has a label."""
    q.ensure(cur, [item_id])
    it = q.items.get(item_id)
    if it is None:
        return None
    f = FEATURES[it.feature]
    cur.execute("SELECT kind, input FROM mx_tasks WHERE id = %s", (it.id,))
    row = cur.fetchone()
    if row is None:
        return None
    kind, text = row
    got = latest(cur, labeller=labeller, kinds=[f.item_kind]).get((f.item_kind, it.id))
    out = {"id": it.id, "feature": it.feature, "name": f.name, "question": f.question, "answers": list(f.answers),
           "evidence": text, "day": it.day, "split": got["split"] if got else q.split_of(it),
           "pool": it.pool if got else None,          # the pool names the decision: shown with the verdict only
           "label": ({k: got[k] for k in ("answer", "note", "split", "created_at")} if got else None),
           "verdict": verdict(it) if got else None, "extracted": None,
           "position": (q.order.index(it.id) + 1) if it.id in q.order else None}
    if it.feature == "entities":
        call = repo.valid_call(cur, it.id)
        out["extracted"] = [{k: e.get(k) for k in ("name", "type", "role", "version", "maker")}
                            for e in ((call or {}).get("answer") or {}).get("entities") or []]
    return out


def queue_view(cur: Any, q: Queue, labeller: str = "owner") -> Dict[str, Any]:
    """The queue's state: per feature its items and how many are answered, the next unanswered items, the cut."""
    done = latest(cur, labeller=labeller, kinds=sorted({f.item_kind for f in FEATURES.values()}))
    answered = {a for (_k, a) in done}
    q.ensure(cur, q.order)
    per: Dict[str, Counter] = defaultdict(Counter)
    for i in q.order:
        it = q.items[i]
        per[it.feature]["total"] += 1
        per[it.feature]["done"] += int(i in answered)
    nxt = [i for i in q.order if i not in answered]
    return {"run": q.run, "cut": q.cut, "total": len(q.order), "done": sum(1 for i in q.order if i in answered),
            "features": [{"feature": f, "name": FEATURES[f].name, "total": per[f]["total"], "done": per[f]["done"],
                          "population": sum(n for p, n in q.pools.items() if p.split(":")[0] == f)}
                         for f in ORDER if per.get(f)],
            "next": nxt[:50], "answered": [i for i in q.order if i in answered][-50:],
            "pools": dict(q.pools)}


# ---- precision -------------------------------------------------------------------------------------------

def wilson(k: float, n: float, z: float = 1.96) -> Tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(max(0.0, p * (1 - p) / n + z * z / (4 * n * n)))
    return (max(0.0, (c - r) / d), min(1.0, (c + r) / d))


def right(it: Item, answer: str, accepted: Optional[bool] = None) -> bool:
    """Whether the decision (`accepted`, by default the item's) agrees with the owner's answer."""
    acc = it.accepted if accepted is None else accepted
    if it.feature == "entities":
        return answer == "right"
    about = answer in ABOUT_ANSWERS
    if it.feature == "check":
        return (not about) if acc else about
    if it.feature == "merge":
        return (answer == "same_event") if acc else answer != "same_event"
    if it.feature == "connect":
        return (answer != "different") if acc else answer == "different"
    return about if acc else not about


def _accepts(it: Item, bar: float) -> bool:
    """The item's decision had the feature's bar been `bar`."""
    if it.p is None:
        return it.accepted
    if it.feature == "check":
        return it.p < bar
    if it.feature == "merge":
        return it.relation == "same_event" and it.p >= bar
    if it.feature == "connect":
        return it.relation in decide.CONNECT_RELATIONS and it.p >= bar
    return it.relation in decide.ABOUT and it.p >= bar


def _stat(rows: Sequence[Tuple[Item, str, float]], accepted_side: bool, bar: Optional[float] = None) -> Dict[str, Any]:
    """Weighted share right among the labelled items on one side of the decision (at `bar`, else the item's own)."""
    k = n = sq = 0.0
    m = hits = 0
    for it, ans, w in rows:
        acc = _accepts(it, bar) if bar is not None else it.accepted
        if acc != accepted_side:
            continue
        ok = right(it, ans, acc)
        k += w * ok
        n += w
        sq += w * w
        m += 1
        hits += int(ok)
    if not m:
        return {"labelled": 0, "right": 0, "precision": None, "lo": None, "hi": None, "n_eff": 0}
    n_eff = n * n / sq
    share = k / n
    lo, hi = wilson(share * n_eff, n_eff)
    return {"labelled": m, "right": hits, "precision": round(share, 4), "lo": round(lo, 4), "hi": round(hi, 4),
            "n_eff": round(n_eff, 1)}


def answers_of(cur: Any, q: Queue, labeller: str = "owner") -> Tuple[Dict[str, Tuple[str, str]], int]:
    """({item: (its newest answer, its split)} for the queue's items, how many labels name no item of it now)."""
    got = latest(cur, labeller=labeller, kinds=sorted({f.item_kind for f in FEATURES.values()}))
    q.ensure(cur, [a for (_kind, a) in got])
    out, stale = {}, 0
    for (kind, a), row in got.items():
        it = q.items.get(a)
        if it is None or FEATURES[it.feature].item_kind != kind:
            stale += 1
            continue
        out[a] = (row["answer"], row["split"] or q.split_of(it))
    return out, stale


def score(q: Queue, answers: Dict[str, Tuple[str, str]], settings: Settings = Settings()) -> List[Dict[str, Any]]:
    """Each feature's precision on `answers` ({item: (answer, split)}; unsure left out): at its bar on dev, test and
    both, with the share right on its rejected side too; the bar swept on dev and test; the re-picked bar (the lowest
    whose dev precision reaches `settings.target`; for checks, which take out below their bar, the highest)."""
    size = q.sizes()                                            # (pool, split) -> population
    labelled: Dict[Tuple[str, str], List[Tuple[Item, str]]] = defaultdict(list)
    for iid, (ans, split) in answers.items():
        it = q.items.get(iid)
        if it is not None and ans not in SKIP:
            labelled[(it.pool, split)].append((it, ans))

    def rows(feature: str, split: Optional[str]) -> List[Tuple[Item, str, float]]:
        out = []
        for (pool, sp), rs in labelled.items():
            if pool.split(":")[0] != feature or (split is not None and sp != split):
                continue
            w = max(size[(pool, sp)], len(rs)) / len(rs)       # a label on a day now outside the pool weighs 1
            out += [(it, ans, w) for it, ans in rs]
        return out

    features = []
    for f in ORDER:
        pop = sum(n for (p, _sp), n in size.items() if p.split(":")[0] == f)
        if not pop:
            continue
        feat = FEATURES[f]
        bar = q.bar_of(f)
        splits = {name: {"acted": _stat(rows(f, sp), True), "rejected": _stat(rows(f, sp), False)}
                  for name, sp in (("dev", "dev"), ("test", "test"), ("all", None))}
        sweep, repick = [], None
        if f != "entities":
            for b in settings.bars:
                sweep.append({"bar": b, "dev": _stat(rows(f, "dev"), True, b), "test": _stat(rows(f, "test"), True, b)})
            ok = [s for s in sweep if s["dev"]["precision"] is not None and s["dev"]["precision"] >= settings.target
                  and s["dev"]["labelled"] >= settings.min_dev]
            if ok:
                pick = (max if f == "check" else min)(ok, key=lambda s: s["bar"])
                repick = {"bar": pick["bar"], "dev": pick["dev"], "test": pick["test"]}
        features.append({"feature": f, "name": feat.name, "acted": feat.acted, "bar": bar, "population": pop,
                         "labelled": sum(len(rs) for (p, _sp), rs in labelled.items() if p.split(":")[0] == f),
                         "splits": splits, "sweep": sweep, "repick": repick})
    return features


def precision(cur: Any, q: Queue, *, labeller: str = "owner", settings: Settings = Settings()) -> Dict[str, Any]:
    """`score` on a labeller's labels, with the News one-tap flags by the feature that placed the member."""
    answers, stale = answers_of(cur, q, labeller)
    news = news_flags(cur, labeller=labeller)
    features = score(q, answers, settings)
    for f in features:
        f["flags"] = news.get(f["feature"], {})
    cur.execute("SELECT DISTINCT labeller FROM mx_labels ORDER BY 1")
    labellers = sorted({"owner", *(r[0] for r in cur.fetchall())}, key=lambda x: (x != "owner", x))
    return {"labeller": labeller, "labellers": labellers, "cut": q.cut, "target": settings.target, "features": features, "stale": stale,
            "unsure": sum(1 for a, _s in answers.values() if a in SKIP), "flags": news}


def news_flags(cur: Any, labeller: str = "owner") -> Dict[str, Dict[str, int]]:
    """The one-tap flags on Mark X News members, by the feature that put the member there (its membership's reason
    when flagged): {feature or "rule": {answer: n}}."""
    cur.execute("""SELECT DISTINCT ON (l.a, l.b) l.answer,
                          (SELECT sp.reason FROM mx_story_posts sp WHERE sp.story_id = l.b AND sp.post_id = l.a
                          ORDER BY sp.valid_from <= l.created_at DESC, sp.valid_from DESC LIMIT 1)
                     FROM mx_labels l WHERE l.item_kind = 'news_row' AND l.labeller = %s
                    ORDER BY l.a, l.b, l.created_at DESC, l.ctid DESC""", (labeller,))
    out: Dict[str, Counter] = defaultdict(Counter)
    for answer, reason in cur.fetchall():
        if answer == "ok":
            continue
        r = reason or ""
        f = ("join" if r == "judge:join" else "pair" if r == "judge:pair" else "merge" if r == "merge"
             else "check" if r == "judge:check" else "rule")
        out[f][answer] += 1
    return {k: dict(v) for k, v in out.items()}
