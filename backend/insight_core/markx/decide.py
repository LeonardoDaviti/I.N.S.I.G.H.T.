"""Mark X Shadow's decisions (issue 0086 E): from Mark IX's stories and Haiku's valid answers to Mark X's stories.

Two layers:
  - **The rules** (`plan_pass1`, `plan_pass2`, `decide`): pure functions of (Mark IX's current stories, the
    candidates, the valid answers, `Config`), ported from the prototype (plan/research/lab/markx/proto: pipeline.py
    `plan`, `plan2`, `decide`, hybrid.py's evidence per question), none tuned on the server's window:
      1. Mark X starts from Mark IX's stories: the link rules stay the first evidence.
      2. Gates: a post under 20 words is never judged nor removed (rule A); a roundup is never a candidate as a
         whole, its membership is checked, and "mention" or "digest item" makes it one (roundups as mentions).
      3. Checks (F1): "mention" or "digest item" demotes a member to a mention; anything under p 0.30 (0.15 in a
         2-voice story, rule B) removes it. The two-event guard: a post whose reading has several events is demoted,
         never removed.
      4. Joins and new stories (F2): "about" (same event, development, reaction) at p >= 0.6. Pair stories that
         share a post are one story.
      5. Merges: "same event" at p >= 0.85; "development" at that bar is a typed connection, not a merge.
      6. A second pass compares every new story with the others (`plan_pass2`), and its merges are decided with
         the first pass's.
      7. Late posts (the late-post table): a join of a post more than 72 hours after its story began needs the
         judge's "same event" at the merge bar; a development is a "follows up" connection instead, a reaction
         a "background" one, anything else about it "related"; the story's date never moves.
      8. Asked again (0112 Decided 8, `settle`): a join, pair or merge that would change a story counts only once a
         second answer agrees; the run reopens its task (`Ask.reopen`), its first call kept.
    A question is a `Question` with the prototype's id (`check:<story>:<post>`, `join:`, `pair:`, `merge:`,
    `merge2:`); a story is keyed, inside one run only, by its Mark IX story's key or a pair's anchor post. Nothing
    keyed so is stored: the job matches its stories to Mark X's by their member posts.
  - **The job** (`run`): reads Mark IX's stories (read only), the readings, S2's candidates and the answers; asks
    the questions the rules need as tasks (markx/tasks.py builds each input from content only); turns the valid
    answers into verdicts; and writes Mark X's stories, memberships and connections (closing what changed, never
    deleting), then Mark X's News (markx/news.py). Each run is one mx_runs row. It writes only mx_* tables.

When it runs (`Scheduler`): when the API start's story job finishes, after the worker's uploads (answers and
vectors, debounced), and hourly, only when
INSIGHT_MARKX is on, one run at a time (a Postgres advisory lock across processes).
"""
from __future__ import annotations

import contextlib
import logging
import os
import threading
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from psycopg import errors as psycopg_errors

log = logging.getLogger(__name__)

CODE_VERSION = "markx-decide-v1"
CERTAIN = frozenset({"thread", "quote", "address"})    # a tree reason that is not a guess: no check (unless a roundup)
NOT_VOICE = frozenset({"saved"})
ABOUT = frozenset({"same_event", "development", "reaction"})
ORDER = {"check": 0, "join": 1, "pair": 2, "merge": 3}
LATE = timedelta(hours=72)                              # Mark IX's link window (experiment W)


@dataclass(frozen=True)
class Config:
    """The bars and rules (0086 E). `prototype()` is the recorded run's (no guard, no late rule)."""
    tau_join: float = 0.60          # joins and new stories (measured best: 98% right, 95% on held-out days)
    tau_merge: float = 0.85         # merges, until E1's merge labels set the bar
    tau_keep: float = 0.30          # a check removes below it ...
    tau_keep2: float = 0.15         # ... in a 2-voice story below this (rule B)
    tau_connect: float = 0.60       # F6's development bar, for typed connections
    min_words: int = 20             # rule A
    cand_lo: float = 0.65           # an embedding candidate's cosine
    story_lo: float = 0.70          # story pairs' centroid cosine
    story_days: int = 14            # story pairs' first posts at most this far apart
    connect_lo: float = 0.60        # connect questions: story pairs at this centroid cosine ...
    connect_days: int = 30          # ... at most this far apart ...
    connect_voices: int = 2         # ... both stories of this many voices or more ...
    connect_new: int = 100          # ... and at most this many new connect tasks a run, the newest pairs first ...
    connect_open: int = 100         # ... and none while this many connect tasks wait (open or leased)
    check_threads: bool = True      # F1 also checks a member Mark IX joined by `thread` (the S5 review's W1)
    two_event_guard: bool = True    # a post with several events is demoted, never removed
    late_rule: bool = True          # the late-post table
    confirm: bool = True            # a story-changing join, pair or merge counts once asked again (0112 Decided 8)
    days: int = 30                  # the window a run decides (corrections 8)

    @staticmethod
    def prototype() -> "Config":
        return Config(two_event_guard=False, late_rule=False, check_threads=False, confirm=False)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Post:
    """A post as the rules read it. `at`: anything that orders (a datetime; the prototype's ISO strings)."""
    id: str
    source: str
    kind: str
    at: Any
    words: int


@dataclass(frozen=True)
class Member:
    """A post in a Mark IX story: its role (report, share) and its tree reason (why it joined)."""
    post: str
    role: Optional[str] = None
    why: Optional[str] = None


@dataclass(frozen=True)
class Question:
    tid: str
    type: str                                 # check, join, pair, merge
    story: Optional[str] = None               # check, join: the story; merge: one story
    post: Optional[str] = None                # check, join, pair: the post asked about
    anchor: Optional[str] = None              # join: the candidate's other post; pair: the post asked against
    other: Optional[str] = None               # merge: the other story
    voices: int = 0                           # check: the story's voices (rule B)
    cos: Optional[float] = None
    why: Optional[str] = None                 # check: the member's tree reason
    roundup: bool = False                     # check: the member is a roundup
    side: Tuple[str, ...] = ()                # the story's posts the question shows
    side_b: Tuple[str, ...] = ()              # merge: the other story's posts shown
    second: bool = False                      # merge: asked by the second pass


@dataclass(frozen=True)
class Verdict:
    relation: str
    p: float                                  # p "about": the confidence when the relation is about, else 1 - it
    reason: Optional[str] = None
    call: Optional[str] = None                # the valid mx_calls row

    @staticmethod
    def of(answer: Dict[str, Any], call: Optional[str] = None) -> "Verdict":
        """A judge answer (relation, confidence 0-100) as the prototype read it (ingest.py)."""
        conf = float(answer.get("confidence") if answer.get("confidence") is not None else 50) / 100
        rel = answer.get("relation")
        return Verdict(rel, conf if rel in ABOUT else 1 - conf, answer.get("reason"), call)


@dataclass
class Outcome:
    about: Dict[str, Dict[str, Dict[str, Any]]]       # story -> post -> evidence (after glue and merges)
    mentions: Dict[str, Dict[str, Dict[str, Any]]]    # story -> post -> evidence (as demoted)
    log: List[Dict[str, Any]]                         # every change, the prototype's changes.jsonl
    connections: List[Dict[str, Any]]                 # typed connections (development links, late posts)
    merged_into: Dict[str, str]                       # a story merged away -> the story it went into
    ix: Set[str]                                      # Mark IX's story keys
    final: Dict[str, str] = field(default_factory=dict)        # every key -> the story it ended in (glue, merges)
    merge_calls: Dict[str, Optional[str]] = field(default_factory=dict)   # a key merged away -> the merge's call
    came_from: Dict[Tuple[str, str], str] = field(default_factory=dict)   # (story, post) -> the key it was in before merges

    def stories(self, posts: Dict[str, Post], min_posts: int = 2) -> List[Dict[str, Any]]:
        """Every story of `min_posts`+ known posts, posts earliest first (the prototype's stories_all)."""
        out = []
        for key, ms in self.about.items():
            known = [p for p in ms if p in posts]
            if len(known) >= min_posts:
                out.append({"story": key, "posts": sorted(ms, key=lambda p: _at_key(posts, p))})
        return out


def _at_key(posts: Dict[str, Post], pid: str):
    """The prototype's sort of a post id by its time, unknown posts first ("" sorts first)."""
    p = posts.get(pid)
    return (1, p.at) if p else (0,)


def voices(posts: Dict[str, Post], ids: Iterable[str]) -> int:
    return len({posts[i].source for i in ids if i in posts and posts[i].kind not in NOT_VOICE})


def ix_members(posts: Dict[str, Post], stories: Dict[str, Sequence[Member]]) -> Dict[str, List[Member]]:
    """Each Mark IX story's members among the known posts, earliest first (stable for equal times)."""
    out = {}
    for key, ms in stories.items():
        known = [m for m in ms if m.post in posts]
        known.sort(key=lambda m: posts[m.post].at)
        out[key] = known
    return out


# ---- the questions ----------------------------------------------------------------------------------

def plan_pass1(posts: Dict[str, Post], stories: Dict[str, Sequence[Member]], kinds: Dict[str, Optional[str]],
               candidates: Iterable[Tuple[str, str, Optional[float]]],
               story_pairs: Iterable[Tuple[str, str, float]], config: Config = Config(),
               in_window: Optional[Callable[[str], bool]] = None,
               copies: Optional[Dict[str, Set[str]]] = None) -> List[Question]:
    """The first pass's questions (pipeline.plan): checks of every uncertain member and every roundup member of a
    2+ voice story (and, with `config.check_threads`, of every member joined by `thread`: one thread can hang
    unrelated replies on a story, which its root's check never reaches). A check shows the story's reports but the
    post, or its other members of any role when the post is its only report (0112 bug 2), never an empty story; for each candidate pair (a, b, cosine; None for a pair not found by meaning), a merge when both
    posts are in 2+ voice stories, a join when one is, a pair when neither; then the story pairs (x, y, centroid
    cosine) not asked yet. `kinds`: each post's reading kind. `in_window(a)`: whether a pair's earlier post is in
    the window decided (the prototype's context posts were not). `copies`: each story's members that are a near-copy
    of another of its members (tasks.near_copies), never checked (0112 bug 3)."""
    members = ix_members(posts, stories)
    copies = copies or {}
    home: Dict[str, List[str]] = {}
    for key, ms in members.items():
        for m in ms:
            home.setdefault(m.post, []).append(key)
    nv = {key: voices(posts, [m.post for m in ms]) for key, ms in members.items()}
    certain = CERTAIN - {"thread"} if config.check_threads else CERTAIN

    def side(key: str) -> List[str]:
        return [m.post for m in members[key] if m.role == "report"] or [m.post for m in members[key]]

    out: List[Question] = []
    for key, ms in members.items():
        if nv[key] < 2:
            continue
        origin = ms[0].post
        for m in ms:
            p = posts[m.post]
            if m.post == origin or p.kind in NOT_VOICE or m.post in copies.get(key, ()):
                continue
            roundup = kinds.get(m.post) == "roundup"
            if m.why in certain and not roundup:
                continue
            if p.words < config.min_words and not roundup:
                continue                                       # rule A: nothing to judge, keep
            shown = tuple(q for q in side(key) if q != m.post)[:3] or tuple(x.post for x in ms if x.post != m.post)[:3]
            if not shown:
                continue                                       # a story's only post: nothing to check it against
            out.append(Question(f"check:{key}:{m.post}", "check", story=key, post=m.post, voices=nv[key], why=m.why,
                                roundup=roundup, side=shown))
    seen: Set[Any] = set()
    for a, b, cos in candidates:
        if cos is not None and cos < config.cand_lo:
            continue
        if in_window is not None and not in_window(a):
            continue
        pa, pb = posts.get(a), posts.get(b)
        if not pa or not pb or pa.words < config.min_words or pb.words < config.min_words:
            continue
        if kinds.get(a) == "roundup" or kinds.get(b) == "roundup":
            continue                                           # a roundup is matched per item, never whole
        sa, sb = home.get(a, []), home.get(b, [])
        if set(sa) & set(sb):
            continue                                           # one Mark IX story already
        multi_a = [s for s in sa if nv[s] >= 2]
        multi_b = [s for s in sb if nv[s] >= 2]
        if multi_a and multi_b:
            for x in multi_a:
                for y in multi_b:
                    k = tuple(sorted([x, y]))
                    if k in seen:
                        continue
                    seen.add(k)
                    out.append(Question(f"merge:{x}:{y}", "merge", story=x, other=y, cos=cos,
                                        side=tuple(side(x)[:3]), side_b=tuple(side(y)[:3])))
            continue
        if multi_b and not multi_a:
            a, b, multi_a = b, a, multi_b
        if multi_a:
            key = multi_a[0]
            tid = f"join:{key}:{b}"
            if tid in seen:
                continue
            seen.add(tid)
            out.append(Question(tid, "join", story=key, post=b, anchor=a, cos=cos, side=tuple(side(key)[:3])))
        else:
            tid = f"pair:{a}:{b}"
            if tid in seen:
                continue
            seen.add(tid)
            out.append(Question(tid, "pair", post=b, anchor=a, cos=cos, side=(a,)))
    first = {key: posts[ms[0].post].at for key, ms in members.items() if ms}
    for x, y, cos in story_pairs:
        if x not in members or y not in members or nv[x] < 2 or nv[y] < 2 or cos < config.story_lo:
            continue
        k = tuple(sorted([x, y]))
        if k in seen:
            continue
        seen.add(k)
        x0, y0 = sorted([x, y], key=lambda s: first[s])
        out.append(Question(f"merge:{x0}:{y0}", "merge", story=x0, other=y0, cos=round(cos, 3),
                            side=tuple(side(x0)[:3]), side_b=tuple(side(y0)[:3])))
    return out


def plan_pass2(posts: Dict[str, Post], first_pass: Outcome,
               centroid_cos: Callable[[Sequence[str], Sequence[str]], Optional[float]],
               config: Config = Config(), within: Optional[Callable[[Any, Any], bool]] = None) -> List[Question]:
    """The second pass (pipeline.plan2): every story the first pass made from lone posts against every other 2+ voice
    story, centroid >= story_lo, first posts at most story_days apart. `centroid_cos(posts_a, posts_b)`: the cosine
    of two post sets' mean vectors (None when either has none). `within(at_a, at_b)`: the days rule (default: a
    timedelta of story_days)."""
    span = timedelta(days=config.story_days)
    within = within or (lambda ta, tb: abs(ta - tb) <= span)
    st: Dict[str, Tuple[List[str], Any, bool]] = {}
    for s in first_pass.stories(posts):
        ps = sorted((p for p in s["posts"] if p in posts), key=lambda p: posts[p].at)
        if voices(posts, ps) < 2:
            continue
        st[s["story"]] = (ps, posts[ps[0]].at, s["story"] in first_pass.ix)
    out, seen = [], set()
    for x in [k for k, v in st.items() if not v[2]]:
        for y, vy in st.items():
            if y == x or tuple(sorted([x, y])) in seen:
                continue
            if not within(st[x][1], vy[1]):
                continue
            c = centroid_cos(st[x][0], vy[0])
            if c is None or c < config.story_lo:
                continue
            seen.add(tuple(sorted([x, y])))
            x0, y0 = sorted([x, y], key=lambda s: st[s][1])
            out.append(Question(f"merge2:{x0}:{y0}", "merge", story=x0, other=y0, cos=round(c, 3),
                                side=tuple(st[x0][0][:3]), side_b=tuple(st[y0][0][:3]), second=True))
    return out


# ---- the decisions ------------------------------------------------------------------------------------

def decide(posts: Dict[str, Post], stories: Dict[str, Sequence[Member]], answered: Iterable[Tuple[Question, Verdict]],
           config: Config = Config(), events: Optional[Dict[str, Optional[str]]] = None) -> Outcome:
    """The verdicts (question, verdict) into edges (pipeline.decide): checks first, then joins and pairs, pair
    stories that share a post glued, then merges, in the prototype's order (by kind, then question id).
    `events`: each post's reading `events` (the two-event guard)."""
    members = ix_members(posts, stories)
    events = events or {}
    about: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    mentions: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for key, ms in members.items():
        for m in ms:
            about[key][m.post] = {"by": "rule", "why": m.why, "role": m.role}
    first = {key: posts[ms[0].post].at for key, ms in members.items() if ms}
    log: List[Dict[str, Any]] = []
    connections: List[Dict[str, Any]] = []
    alias: Dict[str, str] = {}

    def find(s: str) -> str:
        while s in alias:
            s = alias[s]
        return s

    merges = []
    merge_calls: Dict[str, Optional[str]] = {}
    for q, v in sorted(answered, key=lambda qv: (ORDER[qv[0].type], qv[0].tid)):
        if q.type == "merge":
            merges.append((q, v))
            continue
        pa, rel = v.p, v.relation
        if pa is None:
            continue
        if q.type == "check":
            strict = config.tau_keep2 if q.voices <= 2 else config.tau_keep
            if pa < strict:
                ev = about[q.story].pop(q.post, None)
                kind = "demote" if rel in ("mention", "digest_item") else "remove"
                guarded = kind == "remove" and config.two_event_guard and events.get(q.post) == "several"
                if guarded:
                    kind = "demote"
                if kind == "demote":
                    mentions[q.story][q.post] = {"by": "judge", "relation": rel, "reason": v.reason, "p_about": pa,
                                                 "call": v.call, **({"guard": "two-event"} if guarded else {})}
                log.append({"tid": q.tid, "change": kind, "story": q.story, "post": q.post, "relation": rel,
                            "p_about": pa, "reason": v.reason, "was": ev, "call": v.call,
                            **({"guard": "two-event"} if guarded else {})})
        elif q.type in ("join", "pair"):
            if rel in ABOUT and pa >= config.tau_join:
                key = q.story or q.anchor
                began = first.get(key) if q.type == "join" else None
                if config.late_rule and began is not None and _late(posts[q.post].at, began):
                    if not (rel == "same_event" and pa >= config.tau_merge):
                        relation = {"development": "follows_up", "reaction": "background"}.get(rel, "related")
                        connections.append({"a_kind": "post", "a": q.post, "b_kind": "story", "b": key,
                                            "relation": relation, "p": pa, "call": v.call, "tid": q.tid,
                                            "reason": v.reason, "late": True})
                        log.append({"tid": q.tid, "change": "late_connection", "story": key, "post": q.post,
                                    "relation": rel, "p_about": pa, "reason": v.reason, "call": v.call})
                        continue
                if key not in about:
                    about[key][q.anchor] = {"by": "meaning-anchor", "call": v.call, "p_about": pa, "type": q.type}
                about[key][q.post] = {"by": "judge", "relation": rel, "p_about": pa, "cos": q.cos, "reason": v.reason,
                                      "call": v.call, "type": q.type}
                log.append({"tid": q.tid, "change": "join" if q.type == "join" else "new_pair", "story": key,
                            "post": q.post, "anchor": q.anchor, "relation": rel, "p_about": pa, "cos": q.cos,
                            "reason": v.reason, "call": v.call})
    # pair stories that share a post are one story (glue), before any merge
    post_in: Dict[str, Set[str]] = defaultdict(set)
    for key, ms in about.items():
        if key not in members:
            for p in ms:
                post_in[p].add(key)
    glue: Dict[str, str] = {}

    def g(s: str) -> str:
        while s in glue:
            s = glue[s]
        return s

    for p, ss in post_in.items():
        ss = sorted(ss)
        for s in ss[1:]:
            if g(s) != g(ss[0]):
                glue[g(s)] = g(ss[0])
    glued: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for key, ms in about.items():
        glued[g(key)].update(ms)
    about = glued
    for q, v in merges:
        pa, rel = v.p, v.relation
        if pa is None:
            continue
        if rel == "development" and pa >= config.tau_merge:
            log.append({"tid": q.tid, "change": "development_link", "story": q.story, "other": q.other,
                        "p_about": pa, "cos": q.cos, "reason": v.reason, "call": v.call})
            connections.append({"a_kind": "story", "a": q.story, "b_kind": "story", "b": q.other,
                                "relation": "development", "p": pa, "call": v.call, "tid": q.tid, "reason": v.reason})
        elif rel == "same_event" and pa >= config.tau_merge:
            x, y = find(g(q.story)), find(g(q.other))
            if x != y:
                # a Mark IX story keeps its key; between two of a kind, the older one does
                keep, drop = sorted([x, y], key=lambda s: (s not in members, _first_key(posts, about[s])))
                alias[drop] = keep
                merge_calls[drop] = v.call
                log.append({"tid": q.tid, "change": "merge", "story": keep, "other": drop, "p_about": pa,
                            "cos": q.cos, "reason": v.reason, "call": v.call})
    merged: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    came_from: Dict[Tuple[str, str], str] = {}
    for key, ms in about.items():
        merged[find(key)].update(ms)
        for p in ms:
            came_from[(find(key), p)] = key
    keys = set(glue) | set(alias) | set(about) | set(mentions) | set(members)
    return Outcome(about=dict(merged), mentions={k: dict(v) for k, v in mentions.items()}, log=log,
                   connections=connections, merged_into={k: find(k) for k in alias}, ix=set(members),
                   final={k: find(g(k)) for k in keys}, merge_calls=merge_calls, came_from=came_from)


def _late(at: Any, began: Any) -> bool:
    try:
        return at - began > LATE
    except TypeError:          # ISO strings (the reproduction): never late, the prototype had no late rule
        return False


def _first_key(posts: Dict[str, Post], ms: Dict[str, Any]):
    known = [posts[p].at for p in ms if p in posts]
    return (0, min(known)) if known else (1,)


# ---- asked again (0112 Decided 8) ---------------------------------------------------------------------
# v10.0's accepted joins and pairs were right 62 of 80 (78%) by a blind judge; the same questions asked again at batch
# 20 kept 53/59 and 50/54 right (90%, 93%). So a join, pair or merge that would change a story counts only when a
# second answer agrees.

MAX_ASKS = 3       # a question is asked at most this many times (a first answer, its second, one more on a split)

def changes_story(kind: str, v: Verdict, config: Config = Config()) -> bool:
    """Whether this answer, if it counted, would change a story: a join or pair "about" at the join bar (a member, or a
    late post's connection), a merge's "same event" at the merge bar. A merge's development is a typed connection."""
    if v.p is None:
        return False
    if kind == "merge":
        return v.relation == "same_event" and v.p >= config.tau_merge
    return kind in ("join", "pair") and v.relation in ABOUT and v.p >= config.tau_join


def settle(kind: str, answers: Sequence[Verdict], config: Config = Config()) -> Tuple[Optional[Verdict], bool]:
    """(the verdict that counts, or None for none yet; whether to ask again) from a question's valid answers, oldest
    first. The newest answer decides: one that changes nothing counts as it is; one that would change a story counts
    only when the answer before it agrees (the same relation, both at the bar), as one verdict at the lower p, named by
    the earlier call. Until then the question is asked again, MAX_ASKS times at most."""
    if not answers:
        return None, False
    last = answers[-1]
    if not changes_story(kind, last, config):
        return last, False
    more = len(answers) < MAX_ASKS
    if not config.confirm:
        return last, False
    if len(answers) >= 2:
        prev = answers[-2]
        if prev.relation == last.relation and changes_story(kind, prev, config):
            return Verdict(last.relation, min(prev.p, last.p), prev.reason, prev.call), False
    return None, more


def answered_pairs(questions: Sequence[Question], verdicts: Dict[str, Verdict]) -> List[Tuple[Question, Verdict]]:
    """The questions that have a verdict, with it."""
    return [(q, verdicts[q.tid]) for q in questions if q.tid in verdicts]


# ---- the job ------------------------------------------------------------------------------------------
# Everything below reads Mark IX's tables and writes mx_* ones only.

MODEL = "bge-m3"
LOCK_KEY = 860_086_005                 # the advisory lock one run holds (pg_try_advisory_xact_lock)
CAP = 500                              # new tasks of one kind a run may add (the rest wait for the next run)
BRIEFING_HOUR = 20                     # 0086 C: each day, after 20:00 server time
BRIEFING_STORIES = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Ask:
    """The answers a run reads, and the tasks it adds for the questions not asked yet (content-only inputs: the same
    question is one task whatever ids come with it)."""

    def __init__(self, cur: Any, now: datetime, caps: Optional[Dict[str, int]] = None) -> None:
        self.cur, self.now = cur, now
        self.caps = dict(caps or {})          # new tasks a kind may add this run (CAP for the kinds not named)
        self.added: Counter = Counter()
        self.raced: Counter = Counter()
        self.waiting: Counter = Counter()
        self.answered: Counter = Counter()
        self.again: Dict[str, str] = {}       # a first call whose question is to be asked again -> its kind (0112 D8)

    def answer(self, kind: str, text: str, *, a: Any = None, b: Any = None, day: Any = None,
               priority: int = 0) -> Optional[Tuple[Dict[str, Any], str]]:
        """(the valid answer, its call id), or None: the task is added when it is new (up to the kind's cap a run:
        `caps`, else CAP). In the run's snapshot (`snapshot`) a task another transaction committed since is not
        seen; adding it again is a serialization failure, caught in a savepoint: the task exists and is not
        answered in this snapshot, so the run goes on (`raced` counts them)."""
        from insight_core.markx import repo, schemas, tasks
        spec = schemas.KINDS[kind]
        task = repo.task_for(self.cur, kind=kind, guide=spec.guide, input=text)
        if task is None:
            if self.added[kind] >= self.caps.get(kind, CAP):
                self.waiting[kind] += 1
                return None
            try:
                with self.cur.connection.transaction():
                    tasks.add(self.cur, kind, text, a=a, b=b, day=day, priority=priority)
            except psycopg_errors.SerializationFailure:
                self.raced[kind] += 1
                return None
            self.added[kind] += 1
            return None
        if task["status"] != "answered":
            return None
        call = repo.valid_call(self.cur, task["id"])
        if call is None:
            return None
        self.answered[kind] += 1
        return call["answer"], str(call["id"])

    def verdict(self, kind: str, text: str, **kw) -> Optional[Verdict]:
        got = self.answer(kind, text, **kw)
        return None if got is None else Verdict.of(got[0], got[1])

    def later(self, first_call: str) -> List[Verdict]:
        """The question's valid answers after its first (`first_call`), oldest first. Read only."""
        self.cur.execute("""SELECT id::text, answer FROM mx_calls
                             WHERE task_id = (SELECT task_id FROM mx_calls WHERE id = %s) AND valid
                             ORDER BY created_at, ctid""", (first_call,))
        return [Verdict.of(ans, cid) for cid, ans in self.cur.fetchall() if cid != first_call]

    def ask_again(self, kind: str, first_call: Optional[str]) -> None:
        if first_call:
            self.again[first_call] = kind

    def reopen(self) -> Dict[str, int]:
        """The questions to ask again: their tasks open once more (their calls stay), {kind: how many}. An answered
        task only; one another transaction changed since the run's snapshot is left for the next run."""
        out: Counter = Counter()
        for call, kind in sorted(self.again.items()):
            try:
                with self.cur.connection.transaction():
                    self.cur.execute("""UPDATE mx_tasks SET status = 'open', lease_until = NULL, leased_by = NULL
                                         WHERE status = 'answered'
                                           AND id = (SELECT task_id FROM mx_calls WHERE id = %s)""", (call,))
                    if self.cur.rowcount:
                        out[kind] += 1
            except psycopg_errors.SerializationFailure:
                self.raced[kind] += 1
        return dict(out)


@dataclass
class World:
    """What one run reads: Mark IX's stories touching the window, their posts and the candidates' posts (Mark X's
    text), the readings, and the window's start."""
    since: datetime
    stories: Dict[str, List[Member]]
    text: Dict[str, Any]                       # post id -> tasks.Post
    posts: Dict[str, Post]                     # post id -> the rules' Post
    readings: Dict[str, dict]
    candidates: List[Tuple[str, str, Optional[float]]]
    ix_mentions: Dict[str, Set[str]] = field(default_factory=dict)   # Mark IX story -> the roundups mentioning it

    def kinds(self) -> Dict[str, Optional[str]]:
        return {k: r.get("kind") for k, r in self.readings.items()}

    def events(self) -> Dict[str, Optional[str]]:
        return {k: r.get("events") for k, r in self.readings.items()}

    def copies(self) -> Dict[str, Set[str]]:
        """Each Mark IX story's members that are a near-copy of another of its members (0112 bug 3)."""
        from insight_core.markx import tasks
        out = {}
        for key, ms in self.stories.items():
            found = tasks.near_copies([self.text[m.post] for m in ms if m.post in self.text])
            if found:
                out[key] = found
        return out


def load(cur: Any, now: datetime, config: Config) -> World:
    """Mark IX's stories with a post in the last `config.days` (read only), every post of them and of the window's
    candidate pairs, and their readings."""
    from insight_core.markx import tasks
    since = now - timedelta(days=config.days)
    cur.execute("""SELECT sp.story_id::text, sp.post_id::text, sp.role, sp.parent_reason FROM story_posts sp
                    WHERE sp.story_id IN (SELECT sp2.story_id FROM story_posts sp2 JOIN posts p ON p.id = sp2.post_id
                                           WHERE COALESCE(p.surfaced_at, p.published_at, p.fetched_at) >= %s)""",
                (since,))
    rows = cur.fetchall()
    cur.execute("SELECT a::text, b::text, source, score FROM mx_candidates WHERE kind = 'post_post' AND source <> 'link'")
    pairs: Dict[Tuple[str, str], Optional[float]] = {}
    for a, b, source, score in cur.fetchall():
        cos = float(score) if source == "embedding" and score is not None else None
        if (a, b) not in pairs:
            pairs[(a, b)] = cos
        elif cos is not None and (pairs[(a, b)] is None or cos > pairs[(a, b)]):
            pairs[(a, b)] = cos
    ids = {r[1] for r in rows} | {p for ab in pairs for p in ab}
    text = tasks.load_posts(cur, ids)
    posts = {pid: Post(pid, p.source_id, p.kind, p.at, tasks.words(p)) for pid, p in text.items()}
    stories: Dict[str, List[Member]] = defaultdict(list)
    for sid, pid, role, why in rows:
        if pid in posts:
            stories[sid].append(Member(pid, role, why))
    for ms in stories.values():
        ms.sort(key=lambda m: (posts[m.post].at, m.post))
    window = [(a, b, c) for (a, b), c in pairs.items() if a in posts and b in posts and posts[a].at >= since]
    window.sort(key=lambda abc: (abc[2] is None, -(abc[2] or 0.0), abc[0], abc[1]))
    cur.execute("SELECT story_id::text, post_id::text FROM story_mentions WHERE story_id = ANY(%s::uuid[])", (sorted(stories),))
    ix_mentions: Dict[str, Set[str]] = defaultdict(set)
    for sid, pid in cur.fetchall():
        ix_mentions[sid].add(pid)
    return World(since=since, stories=dict(sorted(stories.items())), text=text, posts=posts,
                 readings=tasks.readings(cur, ids), candidates=window, ix_mentions=dict(ix_mentions))


def centroid_cosines(cur: Any, groups: Dict[str, Sequence[str]], lo: float,
                     only: Optional[Iterable[str]] = None) -> Dict[Tuple[str, str], float]:
    """{(x, y): cosine} of the groups' mean vectors (x < y), at `lo` or more; with `only`, pairs touching one of them."""
    keys, ids = [], []
    for k, ps in groups.items():
        for p in ps:
            keys.append(k)
            ids.append(p)
    if not keys:
        return {}
    cur.execute("""WITH g AS (SELECT * FROM unnest(%(k)s::text[], %(p)s::uuid[]) AS g(k, post_id)),
                        c AS (SELECT g.k, avg(e.v::vector) AS v FROM g
                                JOIN mx_embeddings e ON e.post_id = g.post_id AND e.model = %(m)s GROUP BY g.k)
                   SELECT x.k, y.k, 1 - (x.v <=> y.v) FROM c x JOIN c y ON x.k < y.k
                    WHERE (%(only)s::text[] IS NULL OR x.k = ANY(%(only)s) OR y.k = ANY(%(only)s))
                      AND 1 - (x.v <=> y.v) >= %(lo)s""",
                {"k": keys, "p": ids, "m": MODEL, "lo": lo, "only": None if only is None else list(only)})
    return {(x, y): float(c) for x, y, c in cur.fetchall()}


class Questions:
    """Each question's input, built from content (markx/tasks.py's renders), and its verdict when answered."""

    def __init__(self, world: World, ask: Ask, now: datetime, config: Config = Config()) -> None:
        self.w, self.ask, self.now, self.config = world, ask, now, config
        self.members = ix_members(world.posts, world.stories)
        self.cards: Dict[str, Optional[dict]] = {}

    def _p(self, ids: Iterable[str]) -> List[Any]:
        return [self.w.text[i] for i in ids if i in self.w.text]

    def _priority(self, pid: Optional[str]) -> int:
        p = self.w.posts.get(pid) if pid else None
        return max(0, int((self.now - p.at).total_seconds() // 86400)) if p else 0

    def _read(self, ids: Iterable[str]) -> bool:
        return all(i in self.w.readings for i in ids)

    def card(self, key: str, posts: Sequence[str]) -> Optional[dict]:
        """A story's model card (card-v1) from its first 8 members, earliest first; asked once they are read."""
        from insight_core.markx import tasks
        if key not in self.cards:
            ps = tasks._earliest(self._p(posts))
            shown = [p.id for p in ps[:tasks.CARD_MEMBERS]]
            got = None
            if ps and self._read(shown):
                got = self.ask.answer("card", tasks.card_input(ps, self.w.readings), a=ps[0].id,
                                      priority=self._priority(ps[0].id))
            self.cards[key] = got[0] if got else None
        return self.cards[key]

    def story_posts(self, key: str, outcome: Optional[Outcome] = None) -> List[str]:
        if key in self.members:
            return [m.post for m in self.members[key]]
        return sorted((outcome.about.get(key, {}) if outcome else {}), key=lambda p: _at_key(self.w.posts, p))

    def settled(self, q: Question, text: str, **kw) -> Optional[Verdict]:
        """A join's, pair's or merge's verdict as it counts (`settle`): asked again when it would change a story and
        no second answer agrees yet (the run reopens it: `Ask.reopen`)."""
        got = self.ask.answer(q.type, text, **kw)
        if got is None:
            return None
        first = Verdict.of(got[0], got[1])
        c = self.config
        if not c.confirm or not changes_story(q.type, first, c):
            return first
        v, again = settle(q.type, [first] + self.ask.later(got[1]), c)
        if again:
            self.ask.ask_again(q.type, got[1])
        return v

    def verdict(self, q: Question, outcome: Optional[Outcome] = None) -> Optional[Verdict]:
        from insight_core.markx import tasks
        rd, t = self.w.readings, self.w.text
        if q.type == "check":
            if q.post not in t:
                return None
            return self.ask.verdict("check", tasks.check_input(t[q.post], self._p(q.side)), a=q.post,
                                    priority=self._priority(q.post))
        if q.type == "join":
            ms = [p for p in self.story_posts(q.story) if p != q.post]
            if q.post not in t or not self._read([q.post]):
                return None
            card = tasks.rule_card(tasks._earliest(self._p(ms)), rd)
            return self.settled(q, tasks.join_input(t[q.post], rd.get(q.post), self._p(q.side), card),
                                a=q.post, priority=self._priority(q.post))
        if q.type == "pair":
            if q.post not in t or q.anchor not in t or not self._read([q.post, q.anchor]):
                return None
            return self.settled(q, tasks.pair_input(t[q.anchor], t[q.post], rd), a=q.anchor, b=q.post,
                                priority=self._priority(q.post))
        if q.type == "merge":
            pa, pb = self.story_posts(q.story, outcome), self.story_posts(q.other, outcome)
            ca, cb = self.card(q.story, pa), self.card(q.other, pb)
            if ca is None or cb is None or not pa or not pb:
                return None
            return self.settled(q, tasks.merge_input(ca, self._p(q.side), cb, self._p(q.side_b)),
                                a=pa[0], b=pb[0], priority=self._priority(pb[0]))
        return None


def think(cur: Any, world: World, config: Config, ask: Ask, now: datetime,
          answered: Optional[List[Tuple[Question, Verdict]]] = None) -> Tuple[Outcome, Dict[str, Any]]:
    """The two passes over this world: questions, the verdicts found, the decisions. `answered`, when given, is
    extended with every (question, verdict) the decisions read (the labels' queue, markx/labels.py)."""
    q = Questions(world, ask, now, config)
    nv = {k: voices(world.posts, [m.post for m in ms]) for k, ms in q.members.items()}
    multi = {k: [m.post for m in ms] for k, ms in q.members.items() if nv[k] >= 2}
    first = {k: world.posts[ps[0]].at for k, ps in multi.items()}
    span = timedelta(days=config.story_days)
    story_pairs = [(x, y, c) for (x, y), c in sorted(centroid_cosines(cur, multi, config.story_lo).items())
                   if abs(first[x] - first[y]) <= span]
    q1 = plan_pass1(world.posts, world.stories, world.kinds(), world.candidates, story_pairs, config,
                    in_window=lambda a: world.posts[a].at >= world.since, copies=world.copies())
    ans1 = [(x, v) for x in q1 if (v := q.verdict(x)) is not None]
    p1 = decide(world.posts, world.stories, ans1, config, world.events())
    groups = {s["story"]: [p for p in s["posts"] if p in world.posts] for s in p1.stories(world.posts)
              if voices(world.posts, s["posts"]) >= 2}
    new = [k for k in groups if k not in p1.ix]
    cos2 = centroid_cosines(cur, groups, config.story_lo, only=new) if new else {}
    by_posts = {tuple(ps): k for k, ps in groups.items()}

    def centroid_cos(pa: Sequence[str], pb: Sequence[str]) -> Optional[float]:
        x, y = by_posts.get(tuple(pa)), by_posts.get(tuple(pb))
        return cos2.get((min(x, y), max(x, y))) if x and y else None
    q2 = plan_pass2(world.posts, p1, centroid_cos, config)
    ans2 = [(x, v) for x in q2 if (v := q.verdict(x, p1)) is not None]
    out = decide(world.posts, world.stories, ans1 + ans2, config, world.events())
    if answered is not None:
        answered.extend(ans1 + ans2)
    counts = {"questions": dict(Counter(x.type for x in q1 + q2)), "answered": len(ans1) + len(ans2),
              "pass2": len(q2), "changes": dict(Counter(c["change"] for c in out.log))}
    return out, counts


# ---- what a run writes --------------------------------------------------------------------------------

Row = Tuple[str, str, Optional[float], Optional[str]]     # role, reason, p, call


def wanted(out: Outcome, posts: Dict[str, Post]) -> Dict[str, Dict[str, Row]]:
    """The memberships each final story of 2+ posts holds: members by their evidence, posts merged in by the merge,
    mentions and digest items by their check."""
    rows: Dict[str, Dict[str, Row]] = {}
    for s in out.stories(posts):
        key = s["story"]
        mine: Dict[str, Row] = {}
        for pid, ev in out.about[key].items():
            if pid not in posts:
                continue
            origin = out.came_from.get((key, pid), key)
            if origin != key and origin in out.merge_calls and out.merge_calls[origin]:
                mine[pid] = ("member", "merge", None, out.merge_calls[origin])
            elif ev.get("by") == "rule":
                mine[pid] = ("member", f"rule:{ev.get('why') or 'none'}", None, None)
            else:
                mine[pid] = ("member", f"judge:{ev.get('type') or 'join'}", _p(ev.get("p_about")), ev.get("call"))
        rows[key] = mine
    for k, ms in out.mentions.items():
        key = out.final.get(k, k)
        if key not in rows:
            continue
        for pid, ev in ms.items():
            if pid in posts and pid not in rows[key]:
                role = "digest_item" if ev.get("relation") == "digest_item" else "mention"
                rows[key][pid] = (role, "judge:check", _p(ev.get("p_about")), ev.get("call"))
    return rows


def _p(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), 4)


def _same(a: Row, b: Row) -> bool:
    return a[0] == b[0] and a[1] == b[1] and _p(a[2]) == _p(b[2]) and (a[3] or None) == (b[3] or None)


def persist(cur: Any, run_id: Any, out: Outcome, world: World, now: datetime) -> Tuple[Dict[str, str], Counter]:
    """Match each final story to the Mark X story holding most of its members (one each), open what is new and
    close what changed (valid_to; nothing is deleted). Returns {final key: Mark X story id} and the counts."""
    from insight_core.markx import repo
    want = wanted(out, world.posts)
    counts: Counter = Counter()
    touched = sorted({p for ms in want.values() for p in ms} | set(world.posts))
    cur.execute("""SELECT sp.story_id::text, sp.post_id::text, sp.role, sp.reason, sp.p, sp.call_id::text, st.first_at
                     FROM mx_story_posts sp JOIN mx_stories st ON st.id = sp.story_id
                    WHERE sp.valid_to IS NULL AND sp.story_id IN (SELECT story_id FROM mx_story_posts
                                                                    WHERE valid_to IS NULL AND post_id = ANY(%s::uuid[]))""",
                (touched,))
    have: Dict[str, Dict[str, Row]] = defaultdict(dict)
    began: Dict[str, Any] = {}
    for sid, pid, role, reason, p, call, first_at in cur.fetchall():
        have[sid][pid] = (role, reason, p, call)
        began[sid] = first_at
    holders: Dict[str, Set[str]] = defaultdict(set)
    for sid, ms in have.items():
        for pid, row in ms.items():
            if row[0] == "member":
                holders[pid].add(sid)
    ids: Dict[str, str] = {}
    claimed: Set[str] = set()
    order = sorted(want, key=lambda k: (-len(want[k]), min(want[k], key=lambda p: _at_key(world.posts, p))))
    for key in order:
        overlap = Counter(sid for pid, row in want[key].items() if row[0] == "member"
                          for sid in holders.get(pid, ()) if sid not in claimed)
        if overlap:
            best = min(overlap, key=lambda sid: (-overlap[sid], str(began.get(sid) or ""), sid))
            ids[key] = best
            claimed.add(best)
        else:
            first = min((world.posts[p].at for p in want[key] if p in world.posts), default=None)
            ids[key] = str(repo.add_story(cur, first_at=first, run_id=run_id))
            counts["stories_new"] += 1
    for key, sid in ids.items():
        old = have.get(sid, {})
        for pid, row in old.items():
            if pid not in want[key] or not _same(row, want[key][pid]):
                repo.close_membership(cur, story_id=sid, post_id=pid, at=now)
                counts["closed"] += 1
        for pid, row in want[key].items():
            if pid not in old or not _same(old[pid], row):
                repo.open_membership(cur, story_id=sid, post_id=pid, role=row[0], reason=row[1], p=row[2],
                                     call_id=row[3], run_id=run_id, at=now)
                counts["opened"] += 1
        first = min((world.posts[p].at for p in want[key] if p in world.posts), default=None)
        if sid in began and first is not None and began[sid] != first:
            cur.execute("UPDATE mx_stories SET first_at = %s WHERE id = %s", (first, sid))
    final_of_post = {pid: ids[k] for k, ms in want.items() for pid, row in ms.items() if row[0] == "member"}
    for sid in sorted(set(have) - claimed):
        for pid in have[sid]:
            repo.close_membership(cur, story_id=sid, post_id=pid, at=now)
            counts["closed"] += 1
        dest = {final_of_post.get(pid) for pid, row in have[sid].items() if row[0] == "member"}
        if len(dest) == 1 and None not in dest:
            repo.merge_story(cur, sid, into=dest.pop())
        counts["stories_ended"] += 1
    return ids, counts


def persist_connections(cur: Any, run_id: Any, wanted_rows: List[Dict[str, Any]], scope: Set[str],
                        now: datetime) -> Counter:
    """The run's typed connections become the current ones touching `scope` (its stories and posts): new ones open,
    the ones no longer found close (valid_to)."""
    from insight_core.markx import repo
    counts: Counter = Counter()
    want = {(c["a_kind"], c["a"], c["b_kind"], c["b"], c["relation"]): c for c in wanted_rows}
    cur.execute("""SELECT a_kind, a::text, b_kind, b::text, relation, p, call_id::text, rule FROM mx_connections
                    WHERE valid_to IS NULL AND (a = ANY(%(s)s::uuid[]) OR b = ANY(%(s)s::uuid[]))""", {"s": sorted(scope)})
    have = {tuple(r[:5]): r for r in cur.fetchall()}

    def same(c: Dict[str, Any], r: Tuple) -> bool:
        return _p(c.get("p")) == _p(r[5]) and (c.get("call") or None) == (r[6] or None)
    for k, r in have.items():
        if k not in want or not same(want[k], r):
            repo.close_connection(cur, a_kind=k[0], a=k[1], b_kind=k[2], b=k[3], relation=k[4], at=now)
            counts["closed"] += 1
    for k, c in want.items():
        if k not in have or not same(c, have[k]):
            repo.open_connection(cur, a_kind=k[0], a=k[1], b_kind=k[2], b=k[3], relation=k[4], run_id=run_id,
                                 p=_p(c.get("p")), call_id=c.get("call"), rule=c.get("rule"),
                                 evidence={"reason": c.get("reason"), "question": c.get("tid")}, at=now)
            counts["opened"] += 1
    return counts


# A connect answer's relation as stored (0086 E 7: typed; same topic as "related").
CONNECT_RELATIONS = {"development": "development", "reaction": "reaction", "same_event": "same_event",
                     "mention": "related", "digest_item": "related"}


def connections(cur: Any, out: Outcome, ids: Dict[str, str], world: World, ask: Ask, config: Config,
                news_keys: Sequence[str]) -> List[Dict[str, Any]]:
    """Typed connections (F6): the merges' developments, the late posts', and the connect questions' between News
    stories of `connect_voices`+ voices at most `connect_days` apart whose centroids are at `connect_lo` or more and
    that weren't merged. The pairs are asked newest first (by the later story's first post, then the earlier's), so
    the run's cap on new connect tasks (the Ask's: `connect_new`, less what `connect_open` leaves room for) keeps the
    newest; the rest wait for later runs."""
    from insight_core.markx import tasks
    rows: List[Dict[str, Any]] = []

    def sid(key: str) -> Optional[str]:
        return ids.get(out.final.get(key, key))
    for c in out.connections:
        a = sid(c["a"]) if c["a_kind"] == "story" else c["a"]
        b = sid(c["b"]) if c["b_kind"] == "story" else c["b"]
        if a and b and a != b and c.get("call"):
            rows.append(dict(c, a=a, b=b))
    groups = {k: sorted((p for p in out.about[k] if p in world.posts), key=lambda p: _at_key(world.posts, p))
              for k in news_keys}
    groups = {k: ps for k, ps in groups.items() if ps and voices(world.posts, ps) >= config.connect_voices}
    first = {k: world.posts[ps[0]].at for k, ps in groups.items()}
    span = timedelta(days=config.connect_days)
    pairs = []
    for (x, y), cos in centroid_cosines(cur, groups, config.connect_lo).items():
        if abs(first[x] - first[y]) > span or ids.get(x) == ids.get(y):
            continue
        x0, y0 = sorted([x, y], key=lambda k: (first[k], k))
        pairs.append((x0, y0, cos))
    pairs.sort(key=lambda t: (-first[t[1]].timestamp(), -first[t[0]].timestamp(), -t[2], t[0], t[1]))
    for x0, y0, _cos in pairs:
        text = tasks.connect_input(tasks._earliest([world.text[p] for p in groups[x0]]),
                                   tasks._earliest([world.text[p] for p in groups[y0]]))
        v = ask.verdict("connect", text, a=groups[x0][0], b=groups[y0][0])
        if v is None or v.relation not in CONNECT_RELATIONS:
            continue
        if v.p < config.tau_connect:
            continue
        rows.append({"a_kind": "story", "a": ids[x0], "b_kind": "story", "b": ids[y0],
                     "relation": CONNECT_RELATIONS[v.relation], "p": v.p, "call": v.call, "reason": v.reason,
                     "tid": f"connect:{x0}:{y0}"})
    return rows


def headlines(cur: Any, out: Outcome, ids: Dict[str, str], world: World, ask: Ask, news_keys: Sequence[str]) -> int:
    """Haiku's headline (F4) for every News story, from its first 6 members: asked once, stored when answered."""
    from insight_core.markx import repo, tasks
    changed = 0
    for key in news_keys:
        ps = tasks._earliest([world.text[p] for p in out.about[key] if p in world.text])
        if not ps:
            continue
        got = ask.answer("headline", tasks.headline_input(ps), a=ps[0].id)
        if got is None:
            continue
        story = repo.get_story(cur, ids[key])
        text = (got[0].get("headline_en") or "").strip()
        if story and text and (story.get("headline") != text or str(story.get("headline_call") or "") != got[1]):
            repo.set_story_headline(cur, ids[key], headline=text, headline_call=got[1])
            changed += 1
    return changed


def run(cur: Any, *, config: Config = Config(), now: Optional[datetime] = None) -> Dict[str, Any]:
    """One decision run on the caller's transaction: skipped when another holds the lock. Writes mx_* rows only.
    The scheduler and the API run it in `snapshot()`, so every read of Mark IX's tables sees one snapshot."""
    from insight_core.markx import news as mx_news, repo, schemas
    cur.execute("SHOW transaction_isolation")
    isolation = cur.fetchone()[0]
    cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_KEY,))
    if not cur.fetchone()[0]:
        return {"skipped": "another decision run holds the lock"}
    now = now or _now()
    schemas.ensure_guides(cur)
    run_id = repo.start_run(cur, code_version=CODE_VERSION,
                            config={**config.as_dict(), "guides": {k.name: k.guide for k in schemas.KINDS.values()}})
    world = load(cur, now, config)
    cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'connect' AND status IN ('open', 'leased')")
    waiting = cur.fetchone()[0]
    ask = Ask(cur, now, caps={"connect": max(0, min(config.connect_new, config.connect_open - waiting))})
    out, counts = think(cur, world, config, ask, now)
    counts["tasks_reasked"] = ask.reopen()        # asked again before they count (0112 Decided 8)
    ids, written = persist(cur, run_id, out, world, now)
    news_keys = [s["story"] for s in out.stories(world.posts) if voices(world.posts, s["posts"]) >= 2]
    conns = connections(cur, out, ids, world, ask, config, news_keys)
    counts["connections"] = dict(persist_connections(cur, run_id, conns, set(ids.values()) | set(world.posts), now))
    counts["headlines_changed"] = headlines(cur, out, ids, world, ask, news_keys)
    counts["news"] = mx_news.write(cur, run_id, out=out, ids=ids, world=world, now=now)
    counts["briefing"] = mx_news.briefing(cur, ask=ask, now=now, hour=BRIEFING_HOUR, limit=BRIEFING_STORIES)
    counts.update({"stories": len(ids), "memberships": dict(written), "tasks_added": dict(ask.added),
                   "tasks_waiting": dict(ask.waiting), "tasks_raced": dict(ask.raced), "answers_read": dict(ask.answered),
                   "isolation": isolation,
                   "window_since": world.since.isoformat(), "posts": len(world.posts)})
    repo.finish_run(cur, run_id, counts=counts)
    return {"run": str(run_id), **counts}


# ---- when it runs -----------------------------------------------------------------------------------

@contextlib.contextmanager
def snapshot(url: Optional[str] = None):
    """A transaction at REPEATABLE READ for one decision run: its first statement sets the level, so every read of
    Mark IX's stories, News and posts sees the one snapshot taken at the run's first query, and a story-job commit
    landing mid-run is never half seen. The run writes only mx_* rows, which only the run (under its advisory lock)
    updates; the one write another transaction can race is a task insert (the worker's check planner), which `Ask`
    takes in a savepoint."""
    from insight_core.db import database
    if url is None:
        from insight_core.services.registry import services
        url = services().db_url
    with database.transaction(url) as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        yield cur


def _transaction():
    return snapshot()


class Scheduler:
    """After the worker's uploads (`note`, DEBOUNCE seconds after the last) and every EVERY seconds, one run at a
    time; only when INSIGHT_MARKX is on. Never raises into a request or its thread."""
    DEBOUNCE = 60.0
    EVERY = 3600.0

    def __init__(self, transaction: Optional[Callable[[], Any]] = None, debounce: Optional[float] = DEBOUNCE,
                 every: Optional[float] = EVERY, enabled: Optional[Callable[[], bool]] = None) -> None:
        self.transaction = transaction
        self.debounce, self.every = debounce, every
        self.enabled = enabled
        self.lock = threading.Lock()
        self.running = threading.Lock()
        self.timer: Optional[threading.Timer] = None
        self.thread: Optional[threading.Thread] = None
        self.stop = threading.Event()
        self.last: Optional[Dict[str, Any]] = None

    def on(self) -> bool:
        if self.enabled is not None:
            return self.enabled()
        from insight_core.markx.api import enabled
        return enabled()

    def note(self) -> None:
        """An upload arrived: one run DEBOUNCE seconds after the last."""
        if self.debounce is None or not self.on():
            return
        with self.lock:
            if self.timer is not None:
                self.timer.cancel()
            self.timer = threading.Timer(self.debounce, self.run_now)
            self.timer.daemon = True
            self.timer.start()

    def start(self) -> bool:
        """The hourly clock, at the API's start: False (nothing runs) when Mark X is off."""
        if self.every is None or self.thread is not None or not self.on():
            return False
        self.thread = threading.Thread(target=self._hourly, name="markx-decide", daemon=True)
        self.thread.start()
        return True

    def after_stories(self) -> Optional[Dict[str, Any]]:
        """The API's start: its story job has finished, so Mark X decides now over Mark IX's new stories (0112 A),
        not up to EVERY seconds later; nothing when Mark X is off."""
        if not self.on():
            return None
        return self.run_now(candidates_first=True)

    def _hourly(self) -> None:
        while not self.stop.wait(self.every):
            self.run_now(candidates_first=True)

    def run_now(self, candidates_first: bool = False) -> Optional[Dict[str, Any]]:
        if not self.on():
            return None
        with self.lock:
            self.timer = None
        if not self.running.acquire(blocking=False):
            return None
        try:
            if candidates_first:   # the posts whose entities arrived since the candidates' last run (S2)
                from insight_core.markx import candidates
                candidates.pending.flush()
            transaction = self.transaction or _transaction
            with transaction() as cur:
                self.last = run(cur)
            log.info("Mark X decisions: %s", {k: v for k, v in self.last.items() if k in ("stories", "changes", "news")})
            return self.last
        except Exception:   # never into a request or the timer thread
            log.exception("Mark X decisions: the run failed")
            return None
        finally:
            self.running.release()


scheduler = Scheduler()
