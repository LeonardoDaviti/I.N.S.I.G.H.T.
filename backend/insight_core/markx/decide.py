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
         second answer agrees; the run reopens its task (`Ask.reopen`), its first call kept. An "about" answer whose
         own reason says the post is not about the story (`contradicts`) never counts, and is asked again.
      9. Checks and links (0121 Decided 1): a check never removes a member Mark IX joined by a link to the story's
         page (a citation of its parent or the origin page, a quote, the same address: `LINKED`); it demotes it to a
         mention at most. A check that would take out a 2-voice story's second voice counts only once a second answer
         agrees (`settle_check`), as joins do.
    A question is a `Question` with the prototype's id (`check:<story>:<post>`, `join:`, `pair:`, `merge:`,
    `merge2:`); a story is keyed, inside one run only, by its Mark IX story's key or a pair's anchor post. Nothing
    keyed so is stored: the job matches its stories to Mark X's by their member posts.
  - **The job** (`run`): reads Mark IX's stories (read only), the readings, S2's candidates and the answers; asks
    the questions the rules need as tasks (markx/tasks.py builds each input from content only); turns the valid
    answers into verdicts; and writes Mark X's stories, memberships and connections (closing what changed, never
    deleting), then Mark X's News (markx/news.py). Each run is one mx_runs row. It writes only mx_* tables.

When it runs (markx/jobs.py's `Scheduler`): when the API start's story job finishes, after the worker's uploads (answers and
vectors, debounced), and hourly, only when
INSIGHT_MARKX is on, one run at a time (a Postgres advisory lock across processes).
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from psycopg import errors as psycopg_errors

from insight_core.markx import pairing

log = logging.getLogger(__name__)

CODE_VERSION = "markx-decide-v1"
CERTAIN = frozenset({"thread", "quote", "address"})    # a tree reason that is not a guess: no check (unless a roundup)
LINKED = frozenset({"citation", "quote", "address"})    # joined by a link to the story's page (0121 Decided 1)
NOT_VOICE = pairing.NOT_VOICE
ABOUT = frozenset({"same_event", "development", "reaction"})
ORDER = {"check": 0, "join": 1, "pair": 2, "merge": 3}
LATE = timedelta(hours=72)                              # Mark IX's link window (experiment W)
_SAME = pairing.POLICIES[pairing.SAME_STORY]             # the bars below default to Pairing's policy rows (0166)
_CONNECTED = pairing.POLICIES[pairing.CONNECTED]


@dataclass(frozen=True)
class Config:
    """The bars and rules (0086 E). `prototype()` is the recorded run's (no guard, no late rule)."""
    tau_join: float = 0.60          # joins and new stories (measured best: 98% right, 95% on held-out days)
    tau_merge: float = 0.85         # merges, until E1's merge labels set the bar
    tau_keep: float = 0.30          # a check removes below it ...
    tau_keep2: float = 0.15         # ... in a 2-voice story below this (rule B)
    tau_connect: float = 0.60       # F6's development bar, for typed connections
    min_words: int = _SAME.min_words                # rule A
    cand_lo: float = _SAME.cosine                   # an embedding candidate's cosine
    story_lo: float = _SAME.story_cosine            # story pairs' centroid cosine
    story_days: int = _SAME.story_window.days       # story pairs' first posts at most this far apart
    connect_lo: float = _CONNECTED.story_cosine     # connect questions: story pairs at this centroid cosine ...
    connect_days: int = _CONNECTED.story_window.days   # ... at most this far apart ...
    connect_voices: int = _CONNECTED.min_voices     # ... both stories of this many voices or more ...
    connect_new: int = 100          # ... and at most this many new connect tasks a run, the newest pairs first ...
    connect_open: int = 100         # ... and none while this many connect tasks wait (open or leased)
    relate_open: int = 100          # 0131: no new relate question while this many wait (open or leased)
    back_open: int = 50             # 0136: no new back question while this many wait (open or leased)
    check_threads: bool = True      # F1 also checks a member Mark IX joined by `thread` (the S5 review's W1)
    two_event_guard: bool = True    # a post with several events is demoted, never removed
    late_rule: bool = True          # the late-post table
    confirm: bool = True            # a story-changing join, pair or merge counts once asked again (0112 Decided 8)
    reason_rule: bool = True        # ... and never while its own reason says the post is not about the story
    link_keeps: bool = True         # a check demotes a member Mark IX joined by a link at most, never removes it (0121 D1)
    confirm_check: bool = True      # a check taking out a 2-voice story's second voice counts once asked again (0121 D1)
    # Two stories whose members link one document page are a merge question (0121 D5). Off (the owner, 2026-11-06):
    # over the server copy's whole history it asked 7 questions, all wrong (stories citing one background paper),
    # and 0 in the 30-day window; it missed the filing it was for.
    document_merges: bool = False
    document_days: int = _SAME.document_window.days   # ... when two of their posts linking it are at most this far apart
    days: int = 30                  # the window a run decides (corrections 8) ...
    story_window: bool = True       # ... read from the owner's story window each run (0144 A: markx/story_window.py)

    @staticmethod
    def prototype() -> "Config":
        return Config(two_event_guard=False, late_rule=False, check_threads=False, confirm=False, reason_rule=False,
                      link_keeps=False, confirm_check=False, document_merges=False)

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def same_story(self) -> pairing.Policy:
        """Pairing's same-story row with this config's bars."""
        return pairing.policy(pairing.SAME_STORY, cosine=self.cand_lo, min_words=self.min_words,
                              story_cosine=self.story_lo, story_window=timedelta(days=self.story_days),
                              document_window=timedelta(days=self.document_days))

    def connected(self) -> pairing.Policy:
        """Pairing's connected row with this config's bars."""
        return pairing.policy(pairing.CONNECTED, story_cosine=self.connect_lo,
                              story_window=timedelta(days=self.connect_days), min_voices=self.connect_voices)


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
    last_voice: bool = False                  # check: taking it out leaves its story one voice (0121 Decided 1)


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
    return pairing.voices((posts[i].source, posts[i].kind) for i in ids if i in posts)


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
            last = voices(posts, [x.post for x in ms if x.post != m.post]) < 2
            out.append(Question(f"check:{key}:{m.post}", "check", story=key, post=m.post, voices=nv[key], why=m.why,
                                roundup=roundup, side=shown, last_voice=last))
    pol = config.same_story()
    seen: Set[Any] = set()
    for a, b, cos in candidates:
        if not pairing.admits(pol, a, b, cos, posts, kinds):
            continue                                           # Pairing's gate: the bar, rule A, a roundup as a whole
        if in_window is not None and not in_window(a):
            continue
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
    for x, y, cos in story_pairs:   # cos None: found by a shared document, not by meaning (0121 Decided 5)
        if x not in members or y not in members or not pairing.admits_stories(pol, cos, nv[x], nv[y]):
            continue
        k = tuple(sorted([x, y]))
        if k in seen:
            continue
        seen.add(k)
        x0, y0 = sorted([x, y], key=lambda s: first[s])
        out.append(Question(f"merge:{x0}:{y0}", "merge", story=x0, other=y0, cos=None if cos is None else round(cos, 3),
                            side=tuple(side(x0)[:3]), side_b=tuple(side(y0)[:3])))
    return out


def plan_pass2(posts: Dict[str, Post], first_pass: Outcome,
               centroid_cos: Callable[[Sequence[str], Sequence[str]], Optional[float]],
               config: Config = Config(), within: Optional[Callable[[Any, Any], bool]] = None,
               documents: Optional[Callable[[Sequence[str], Sequence[str]], bool]] = None) -> List[Question]:
    """The second pass (pipeline.plan2): every story the first pass made from lone posts against every other 2+ voice
    story, centroid >= story_lo, first posts at most story_days apart. `centroid_cos(posts_a, posts_b)`: the cosine
    of two post sets' mean vectors (None when either has none). `within(at_a, at_b)`: the days rule (default: a
    timedelta of story_days). `documents(posts_a, posts_b)`: whether two of their posts link one document page within
    `document_days` (0121 Decided 5): such a pair is asked whatever its centroid and days."""
    pol = config.same_story()
    within = within or pol.story_within
    st: Dict[str, Tuple[List[str], Any, bool]] = {}
    for s in first_pass.stories(posts):
        ps = sorted((p for p in s["posts"] if p in posts), key=lambda p: posts[p].at)
        if voices(posts, ps) < pol.min_voices:
            continue
        st[s["story"]] = (ps, posts[ps[0]].at, s["story"] in first_pass.ix)
    out, seen = [], set()
    for x in [k for k, v in st.items() if not v[2]]:
        for y, vy in st.items():
            if y == x or tuple(sorted([x, y])) in seen:
                continue
            c = centroid_cos(st[x][0], vy[0]) if within(st[x][1], vy[1]) else None
            if c is not None and c < pol.story_cosine:
                c = None
            if c is None and not (documents is not None and documents(st[x][0], vy[0])):
                continue
            seen.add(tuple(sorted([x, y])))
            x0, y0 = sorted([x, y], key=lambda s: st[s][1])
            out.append(Question(f"merge2:{x0}:{y0}", "merge", story=x0, other=y0, cos=None if c is None else round(c, 3),
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
                guarded = None
                if kind == "remove" and config.two_event_guard and events.get(q.post) == "several":
                    guarded = "two-event"
                elif kind == "remove" and config.link_keeps and q.why in LINKED:
                    guarded = "link"           # it links the story's page: a mention at most (0121 Decided 1)
                if guarded:
                    kind = "demote"
                if kind == "demote":
                    mentions[q.story][q.post] = {"by": "judge", "relation": rel, "reason": v.reason, "p_about": pa,
                                                 "call": v.call, **({"guard": guarded} if guarded else {})}
                log.append({"tid": q.tid, "change": kind, "story": q.story, "post": q.post, "relation": rel,
                            "p_about": pa, "reason": v.reason, "was": ev, "call": v.call,
                            **({"guard": guarded} if guarded else {})})
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
# second answer agrees; and an "about" answer whose own reason says the post is not about the story never counts.

MAX_ASKS = 3       # a question is asked at most this many times (a first answer, its second, one more on a split)

# The class of reason text that says "not this story", read from v10.0's 1,814 accepted "about" answers (35 match:
# 1.9%; of the 80 judged, it fires on 4 wrong joins and no right one). Three families, never a name or a site:
#   1. the reason names another relation or another thing for the post: "so it is a different event", "this is closer
#      to a mention", "a mention rather than a retelling", "the relation should be different", "a mismatch", "a
#      different model from ...", "a different commentary post", "a related but distinct event" (but not "a
#      different angle/reading/framing" of the same event, nor "not a distinct release event");
#   2. it says the story's subject is not the post's: "<the story's subject> is not its (main) subject";
#   3. it says unrelated, absent, no relation, not mentioned ("the family is absent from its text").
# Not in the class: "rather than the release itself" (a reaction or a hands-on report: still about it), "only as
# background" (as often said of a side subject as of the story), "does not mention <a detail>".
_OTHER_RELATION = (r"\b(?:relation|it|this|which)\s+(?:is|should be|falls under|reads as|is best read as|is closer to"
                   r"|is actually)\s+(?:actually\s+|best read as\s+|closer to\s+)?(?:an?\s+)?"
                   r"(?:different|mention|unrelated|digest item)\b"
                   r"(?!\s+(?:angle|reading|aspect|take|framing|view|perspective|detail))"
                   r"|\bfalls under different\b|\bshould be different\b|\ba mention rather than\b|\bis a mismatch\b"
                   r"|\bmismatch in subject\b"
                   r"|\bis a different (?:event|happening|story|model|release|product|project|company|claim"
                   r"|announcement|report|subject)\b"
                   r"|\ba different (?:event|happening|model|release|product|project|company|claim) from\b"
                   # "a different commentary post", "a different piece" (the v10.0.1 review: a pair at 0.95)
                   r"|(?<!not )\ban? different (?:\w+\s+){0,2}(?:post|piece|article|video|thread|tweet)\b"
                   # "a related but distinct event", "distinct from"; never "not a distinct release event"
                   r"|(?<!not )(?<!no )\b(?:related but|but|is|are|as|a|an) distinct\b|(?<!not )\bdistinct from\b")
_NOT_ITS_SUBJECT = r"\bnot (?:its|the post's) (?:main )?(?:subject|topic)\b"
_UNRELATED = r"\bunrelated\b|\babsent from\b|\bno relation\b|\bnot related\b|\bnot mentioned\b"
NOT_THIS_STORY = re.compile("|".join((_OTHER_RELATION, _NOT_ITS_SUBJECT, _UNRELATED)), re.I)


def contradicts(reason: Optional[str]) -> bool:
    """Whether an answer's own reason says the post is not about the story (the class above)."""
    return bool(reason) and NOT_THIS_STORY.search(reason) is not None


def changes_story(kind: str, v: Verdict, config: Config = Config()) -> bool:
    """Whether this answer, if it counted, would change a story: a join or pair "about" at the join bar (a member, or a
    late post's connection), a merge's "same event" at the merge bar. A merge's development is a typed connection."""
    if v.p is None:
        return False
    if kind == "merge":
        return v.relation == "same_event" and v.p >= config.tau_merge
    return kind in ("join", "pair") and v.relation in ABOUT and v.p >= config.tau_join


def agreeing(kind: str, v: Verdict, config: Config = Config()) -> bool:
    """Whether a story-changing answer can count once a second one agrees (0112 Decided 8, the coordinator's "both
    about"): a join's "about" (same event, development, reaction) at the join bar, a pair's or a merge's "same event"
    at its bar. A pair's development or reaction never makes a story."""
    if not changes_story(kind, v, config):
        return False
    return kind == "join" or v.relation == "same_event"


def settle(kind: str, answers: Sequence[Verdict], config: Config = Config()) -> Tuple[Optional[Verdict], bool]:
    """(the verdict that counts, or None for none yet; whether to ask again) from a question's valid answers, oldest
    first. The newest answer decides: one that changes nothing counts as it is; one that would change a story counts
    only when the answer before it agrees: both `agreeing` (for a join both "about", whatever the relations; for a
    pair or a merge both "same event"), neither reason against it. It counts as one verdict at the lower p, named by
    the earlier call, with the relation of the two that says less (a development or reaction over a same event: the
    late-post table reads it). A pair's development or reaction never counts and is not asked again; an answer whose
    reason is against it never counts. Until then the question is asked again, MAX_ASKS times at most."""
    if not answers:
        return None, False
    last = answers[-1]
    if not changes_story(kind, last, config):
        return last, False
    more = len(answers) < MAX_ASKS
    if config.reason_rule and contradicts(last.reason):
        return None, more
    if not config.confirm:
        return last, False
    if not agreeing(kind, last, config):
        return None, False
    if len(answers) >= 2:
        prev = answers[-2]
        if agreeing(kind, prev, config) and not (config.reason_rule and contradicts(prev.reason)):
            relation = last.relation if last.relation != "same_event" else prev.relation
            return Verdict(relation, min(prev.p, last.p), prev.reason, prev.call), False
    return None, more


def settle_check(answers: Sequence[Verdict], bar: float, config: Config = Config()) -> Tuple[Optional[Verdict], bool]:
    """(the verdict that counts, or None; whether to ask again) from the valid answers, oldest first, of a check that
    would take out a 2-voice story's second voice (0121 Decided 1, as `settle` for joins). The newest answer decides:
    one that keeps the post (p "about" at `bar` or more) counts at once; one that takes it out counts only when the
    answer before it takes it out too, as one verdict that says less: a mention over a removal, the higher p, named
    by the earlier call. Until then the check is asked again, MAX_ASKS times at most; then the post stays."""
    if not answers:
        return None, False
    last = answers[-1]
    if last.p is None or last.p >= bar or not config.confirm_check:
        return last, False
    if len(answers) >= 2 and answers[-2].p is not None and answers[-2].p < bar:
        prev = answers[-2]
        demoting = [x for x in (prev, last) if x.relation in ("mention", "digest_item")]
        relation = demoting[0].relation if demoting else prev.relation
        return Verdict(relation, max(prev.p, last.p), prev.reason, prev.call), False
    return None, len(answers) < MAX_ASKS


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

    def __init__(self, cur: Any, now: datetime, caps: Optional[Dict[str, int]] = None, memo: Any = None,
                 dry: bool = False, old_after: Optional[int] = None, old_cap: int = 0) -> None:
        self.cur, self.now = cur, now
        self.caps = dict(caps or {})          # new tasks a kind may add this run (CAP for the kinds not named)
        self.old_after = old_after            # 0144 A: while the story window reaches back, a question whose post is
        self.old_cap = old_cap                # older than this many days is one of a page (old_cap a kind a run) ...
        self.old_added: Counter = Counter()
        self.waiting_old: Counter = Counter()
        self.memo = memo                      # 0116/0169: the tasks and calls of this snapshot (incremental.refresh)
        self.dry = dry                        # nothing added, nothing reopened (the check's incremental reading)
        self.added: Counter = Counter()
        self.raced: Counter = Counter()
        self.waiting: Counter = Counter()
        self.answered: Counter = Counter()
        self.again: Dict[str, str] = {}       # a first call whose question is to be asked again -> its kind (0112 D8)

    def answer(self, kind: str, text: Any, *, a: Any = None, b: Any = None, day: Any = None,
               priority: int = 0) -> Optional[Tuple[Dict[str, Any], str]]:
        """(the valid answer, its call id), or None: the task is added when it is new (up to the kind's cap a run:
        `caps`, else CAP). In the run's snapshot (`snapshot`) a task another transaction committed since is not
        seen; adding it again is a serialization failure, caught in a savepoint: the task exists and is not
        answered in this snapshot, so the run goes on (`raced` counts them). `text`: the input, or an
        incremental.Input (0169: its hash kept, rendered only when the task is added)."""
        from insight_core.markx import incremental, repo, schemas, tasks
        spec = schemas.KINDS[kind]
        memo = self.memo if kind in incremental.KINDS else None
        if memo is not None:
            h = incremental.hash_of(text)
            got = memo.tasks.get((kind, h))
            task = None if got is None else {"id": got[0], "status": got[1]}
        else:
            task = repo.task_for(self.cur, kind=kind, guide=spec.guide, input=incremental.text_of(text))
        if task is None:
            old = self.old_after is not None and priority > self.old_after
            if old:                           # ... at the backfill's priority, beside today's (story_window)
                from insight_core.markx.story_window import BACKFILL_PRIORITY
                if self.dry or self.old_added[kind] >= self.old_cap:
                    self.waiting[kind] += 1
                    self.waiting_old[kind] += 1
                    return None
                priority = BACKFILL_PRIORITY
            elif self.dry or self.added[kind] >= self.caps.get(kind, CAP):
                self.waiting[kind] += 1
                return None
            try:
                with self.cur.connection.transaction():
                    tid, _new = tasks.add(self.cur, kind, incremental.text_of(text), a=a, b=b, day=day,
                                          priority=priority)
            except psycopg_errors.SerializationFailure:
                self.raced[kind] += 1
                return None
            (self.old_added if old else self.added)[kind] += 1
            if memo is not None:
                memo.tasks[(kind, h)] = (str(tid), "open", 0)
                memo.keys[str(tid)] = (kind, h)
            return None
        if task["status"] != "answered":
            return None
        if memo is not None:
            calls = incremental.calls_of(self.cur, memo, task["id"])
            call = {"id": calls[0][1], "answer": calls[0][0]} if calls else None
        else:
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
        if self.memo is not None and first_call in self.memo.call_task:
            return [Verdict.of(ans, cid) for ans, cid in self.memo.calls[self.memo.call_task[first_call]][1:]]
        self.cur.execute("""SELECT id::text, answer FROM mx_calls
                             WHERE task_id = (SELECT task_id FROM mx_calls WHERE id = %s) AND valid
                             ORDER BY created_at, ctid""", (first_call,))
        return [Verdict.of(ans, cid) for cid, ans in self.cur.fetchall() if cid != first_call]

    def ask_again(self, kind: str, first_call: Optional[str]) -> None:
        if first_call and not self.dry:
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
                        tid = self.memo.call_task.get(call) if self.memo is not None else None
                        if tid and tid in self.memo.keys:
                            key = self.memo.keys[tid]
                            self.memo.tasks[key] = (tid, "open", self.memo.tasks[key][2])
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
    memo: Any = None                           # 0116/0169: the reading's state (incremental.State), when kept

    def kinds(self) -> Dict[str, Optional[str]]:
        if self.memo is not None:              # 0169: from mx_readings, without reading every reading
            return dict(self.memo.kinds)
        return {k: r.get("kind") for k, r in self.readings.items()}

    def events(self) -> Dict[str, Optional[str]]:
        if self.memo is not None:
            return dict(self.memo.events)
        return {k: r.get("events") for k, r in self.readings.items()}

    def earliest(self, ids: Iterable[str]) -> List[str]:
        """The known posts of `ids`, earliest first (tasks._earliest's order: time, then id)."""
        return sorted((i for i in ids if i in self.posts), key=lambda i: (self.posts[i].at, i))

    def copies(self) -> Dict[str, Set[str]]:
        """Each Mark IX story's members that are a near-copy of another of its members (0112 bug 3)."""
        from insight_core.markx import tasks
        from insight_core.markx import incremental
        out = {}
        for key, ms in self.stories.items():
            ids = [m.post for m in ms if m.post in self.text]
            found = (incremental.copies(self.memo, ids, self.text) if self.memo is not None
                     else tasks.near_copies([self.text[i] for i in ids]))
            if found:
                out[key] = found
        return out


def load(cur: Any, now: datetime, config: Config, memo: Any = None) -> World:
    """Mark IX's stories with a post in the last `config.days` (read only), every post of them and of the window's
    candidate pairs, and their readings. With `memo` (0116, 0169: incremental.State), the rules' posts are kept by
    their stamps and a text or reading is read only when used (incremental.world)."""
    from insight_core.markx import embed, incremental, tasks
    since = now - timedelta(days=config.days)
    cur.execute("""SELECT sp.story_id::text, sp.post_id::text, sp.role, sp.parent_reason FROM story_posts sp
                    WHERE sp.story_id IN (SELECT sp2.story_id FROM story_posts sp2 JOIN posts p ON p.id = sp2.post_id
                                           WHERE COALESCE(p.surfaced_at, p.published_at, p.fetched_at) >= %s)""",
                (since,))
    rows = cur.fetchall()
    cur.execute("SELECT a::text, b::text, source, score FROM mx_candidates WHERE kind = 'post_post' AND source <> 'link'")
    pairs: Dict[Tuple[str, str], Optional[float]] = {}
    for a, b, source, score in embed.current_candidates(cur, cur.fetchall()):   # by the vectors now (embed text v2)
        cos = float(score) if source == "embedding" and score is not None else None
        if (a, b) not in pairs:
            pairs[(a, b)] = cos
        elif cos is not None and (pairs[(a, b)] is None or cos > pairs[(a, b)]):
            pairs[(a, b)] = cos
    ids = {r[1] for r in rows} | {p for ab in pairs for p in ab}
    if memo is not None:       # 0169: the rules' posts kept by their stamps; texts and readings read on use
        text, posts, readings = incremental.world(cur, memo, ids)
    else:
        text = tasks.load_posts(cur, ids)
        posts = {pid: Post(pid, p.source_id, p.kind, p.at, tasks.words(p)) for pid, p in text.items()}
        readings = tasks.readings(cur, ids)
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
    return World(since=since, stories=dict(sorted(stories.items())), text=text, posts=posts, readings=readings,
                 candidates=window, ix_mentions=dict(ix_mentions), memo=memo)


def centroid_cosines(cur: Any, groups: Dict[str, Sequence[str]], lo: float,
                     only: Optional[Iterable[str]] = None) -> Dict[Tuple[str, str], float]:
    """{(x, y): cosine} of the groups' mean vectors (x < y), at `lo` or more; with `only`, pairs touching one of them
    (Pairing's centroid source)."""
    return pairing.centroid_cosines(cur, groups, lo, only, MODEL)


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
            ps = self.w.earliest(posts)
            shown = ps[:tasks.CARD_MEMBERS]   # all card_input shows (tasks._earliest(...)[:CARD_MEMBERS])
            got = None
            if ps and self._read(shown):
                text = self._render("card", shown, lambda: tasks.card_input(self._p(shown), self.w.readings), reads=True)
                got = self.ask.answer("card", text, a=ps[0], priority=self._priority(ps[0]))
            self.cards[key] = got[0] if got else None
        return self.cards[key]

    def _render(self, kind: str, ids: Sequence[str], render: Callable[[], str], **kw) -> Any:
        """0169: the input, kept by what it shows (incremental.rendered); a str without the run's state."""
        from insight_core.markx import incremental
        m = self.w.memo
        return incremental.rendered(m, kind, ids, render, texts=self.w.text if m is not None else None,
                                    readings=self.w.readings if m is not None else None, **kw)

    def story_posts(self, key: str, outcome: Optional[Outcome] = None) -> List[str]:
        if key in self.members:
            return [m.post for m in self.members[key]]
        return sorted((outcome.about.get(key, {}) if outcome else {}), key=lambda p: _at_key(self.w.posts, p))

    def settled(self, q: Question, text: Any, **kw) -> Optional[Verdict]:
        """A join's, pair's or merge's verdict as it counts (`settle`): asked again when it would change a story and
        no second answer agrees yet (the run reopens it: `Ask.reopen`)."""
        got = self.ask.answer(q.type, text, **kw)
        if got is None:
            return None
        first = Verdict.of(got[0], got[1])
        c = self.config
        if not (c.confirm or c.reason_rule) or not changes_story(q.type, first, c):
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
            text = self._render("check", (q.post, "|", *q.side), lambda: tasks.check_input(t[q.post], self._p(q.side)))
            got = self.ask.answer("check", text, a=q.post, priority=self._priority(q.post))
            if got is None:
                return None
            first = Verdict.of(got[0], got[1])
            if not (q.last_voice and self.config.confirm_check):
                return first
            bar = self.config.tau_keep2 if q.voices <= 2 else self.config.tau_keep
            v, again = settle_check([first] + self.ask.later(got[1]), bar, self.config)
            if again:
                self.ask.ask_again("check", got[1])
            return v
        if q.type == "join":
            ms = [p for p in self.story_posts(q.story) if p != q.post]
            if q.post not in t or not self._read([q.post]):
                return None
            text = self._render("join", (q.post, "|", *ms, "|", *q.side), lambda: tasks.join_input(
                t[q.post], rd.get(q.post), self._p(q.side), tasks.rule_card(tasks._earliest(self._p(ms)), rd)),
                reads=True)
            return self.settled(q, text, a=q.post, priority=self._priority(q.post))
        if q.type == "pair":
            if q.post not in t or q.anchor not in t or not self._read([q.post, q.anchor]):
                return None
            text = self._render("pair", (q.anchor, "|", q.post), lambda: tasks.pair_input(t[q.anchor], t[q.post], rd),
                                reads=True)
            return self.settled(q, text, a=q.anchor, b=q.post, priority=self._priority(q.post))
        if q.type == "merge":
            pa, pb = self.story_posts(q.story, outcome), self.story_posts(q.other, outcome)
            ca, cb = self.card(q.story, pa), self.card(q.other, pb)
            if ca is None or cb is None or not pa or not pb:
                return None
            import json as _json
            text = self._render("merge", (*q.side, "|", *q.side_b),
                                lambda: tasks.merge_input(ca, self._p(q.side), cb, self._p(q.side_b)),
                                extra=(_json.dumps(ca, sort_keys=True, default=str),
                                       _json.dumps(cb, sort_keys=True, default=str)))
            return self.settled(q, text, a=pa[0], b=pb[0], priority=self._priority(pb[0]))
        return None


class Documents(pairing.Documents):
    """0121 Decided 5 (the owner's call, default yes): Pairing's document source over this run's world (the document
    pages each post links, a roundup's never; the stories two of whose posts link one within `document_days`)."""

    def __init__(self, world: World, config: Config) -> None:
        super().__init__(world.text, world.posts, world.kinds(), config.same_story())
        self.w = world


def _question_at(q: Question, world: World) -> Any:
    """A question's newest post time (its post, anchor and the posts it shows)."""
    ids = [x for x in (q.post, q.anchor, *q.side, *q.side_b) if x and x in world.posts]
    return max((world.posts[x].at for x in ids), default=world.since)


def _ask_all(q: "Questions", qs: Sequence[Question], world: World, outcome: Optional[Outcome] = None) -> List[Optional[Verdict]]:
    """Each question's verdict, in `qs`'s order. While the story window reaches back (the Ask's `old_after`), they are
    asked newest first (0144 A2: a run's page of old questions is the newest ones); the decisions never depend on the
    order asked (`decide` sorts by kind, then question id)."""
    order = list(range(len(qs)))
    if q.ask.old_after is not None:
        order.sort(key=lambda n: (_question_at(qs[n], world), qs[n].tid), reverse=True)
    out: List[Optional[Verdict]] = [None] * len(qs)
    for n in order:
        out[n] = q.verdict(qs[n]) if outcome is None else q.verdict(qs[n], outcome)
    return out


def think(cur: Any, world: World, config: Config, ask: Ask, now: datetime,
          answered: Optional[List[Tuple[Question, Verdict]]] = None) -> Tuple[Outcome, Dict[str, Any]]:
    """The two passes over this world: questions, the verdicts found, the decisions. `answered`, when given, is
    extended with every (question, verdict) the decisions read (the labels' queue, markx/labels.py)."""
    q = Questions(world, ask, now, config)
    pol = config.same_story()
    nv = {k: voices(world.posts, [m.post for m in ms]) for k, ms in q.members.items()}
    multi = {k: [m.post for m in ms] for k, ms in q.members.items() if nv[k] >= pol.min_voices}
    story_pairs = [(x, y, c) for (x, y), c in sorted(pairing.story_pairs(cur, pol, multi, world.posts).items())]
    docs = Documents(world, config) if config.document_merges else None
    if docs is not None:
        found = {tuple(sorted(xy)) for xy in ((x, y) for x, y, _ in story_pairs)}
        story_pairs += [(x, y, None) for x, y in docs.pairs(multi) if (x, y) not in found]
    q1 = plan_pass1(world.posts, world.stories, world.kinds(), world.candidates, story_pairs, config,
                    in_window=lambda a: world.posts[a].at >= world.since, copies=world.copies())
    got1 = _ask_all(q, q1, world)
    ans1 = [(x, got1[n]) for n, x in enumerate(q1) if got1[n] is not None]
    p1 = decide(world.posts, world.stories, ans1, config, world.events())
    groups = {s["story"]: [p for p in s["posts"] if p in world.posts] for s in p1.stories(world.posts)
              if voices(world.posts, s["posts"]) >= pol.min_voices}
    new = [k for k in groups if k not in p1.ix]
    cos2 = centroid_cosines(cur, groups, pol.story_cosine, only=new) if new else {}
    by_posts = {tuple(ps): k for k, ps in groups.items()}

    def centroid_cos(pa: Sequence[str], pb: Sequence[str]) -> Optional[float]:
        x, y = by_posts.get(tuple(pa)), by_posts.get(tuple(pb))
        return cos2.get((min(x, y), max(x, y))) if x and y else None
    q2 = plan_pass2(world.posts, p1, centroid_cos, config, documents=docs.shared if docs is not None else None)
    got2 = _ask_all(q, q2, world, p1)
    ans2 = [(x, got2[n]) for n, x in enumerate(q2) if got2[n] is not None]
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


def persist(cur: Any, run_id: Any, out: Outcome, world: World, now: datetime,
            write: bool = True) -> Tuple[Dict[str, str], Counter]:
    """Match each final story to the Mark X story holding most of its members (one each), open what is new and
    close what changed (valid_to; nothing is deleted). Returns {final key: Mark X story id} and the counts. With
    `write` False (0116's check), only the match: a new story is "new:<key>", nothing is written."""
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
            ids[key] = str(repo.add_story(cur, first_at=first, run_id=run_id)) if write else f"new:{key}"
            counts["stories_new"] += 1
    if not write:
        return ids, counts
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
    # 0131: the graph's edges between two posts are markx/graph.py's (its own stage), never closed here
    cur.execute("""SELECT a_kind, a::text, b_kind, b::text, relation, p, call_id::text, rule FROM mx_connections
                    WHERE valid_to IS NULL AND (a = ANY(%(s)s::uuid[]) OR b = ANY(%(s)s::uuid[]))
                      AND NOT (a_kind = 'post' AND b_kind = 'post')""", {"s": sorted(scope)})
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
    from insight_core.markx import incremental, tasks
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
    found = pairing.story_pairs(cur, config.connected(), groups, world.posts)   # voices, bar, days: Pairing's
    groups = {k: ps for k, ps in groups.items() if ps and voices(world.posts, ps) >= config.connect_voices}
    first = {k: world.posts[ps[0]].at for k, ps in groups.items()}
    pairs = []
    for (x, y), cos in found.items():
        if ids.get(x) == ids.get(y):
            continue
        x0, y0 = sorted([x, y], key=lambda k: (first[k], k))
        pairs.append((x0, y0, cos))
    pairs.sort(key=lambda t: (-first[t[1]].timestamp(), -first[t[0]].timestamp(), -t[2], t[0], t[1]))
    for x0, y0, _cos in pairs:
        text = incremental.rendered(world.memo, "connect", (*groups[x0], "|", *groups[y0]), lambda: tasks.connect_input(
            tasks._earliest([world.text[p] for p in groups[x0]]), tasks._earliest([world.text[p] for p in groups[y0]])),
            texts=world.text if world.memo is not None else None)
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
    cur.execute("SELECT id::text, headline, headline_call::text FROM mx_stories WHERE id = ANY(%s::uuid[])",
                ([ids[k] for k in news_keys],))
    stored = {sid: {"headline": h, "headline_call": c} for sid, h, c in cur.fetchall()}
    from insight_core.markx import incremental
    for key in news_keys:
        ps = world.earliest(p for p in out.about[key] if p in world.text)
        if not ps:
            continue
        shown = ps[:tasks.HEADLINE_MEMBERS]   # all headline_input shows (tasks._earliest(...)[:HEADLINE_MEMBERS])
        text = incremental.rendered(world.memo, "headline", shown,
                                    lambda: tasks.headline_input([world.text[p] for p in shown]),
                                    texts=world.text if world.memo is not None else None)
        got = ask.answer("headline", text, a=ps[0])
        if got is None:
            continue
        story = stored.get(ids[key])
        text = (got[0].get("headline_en") or "").strip()
        if story and text and (story.get("headline") != text or str(story.get("headline_call") or "") != got[1]):
            repo.set_story_headline(cur, ids[key], headline=text, headline_call=got[1])
            changed += 1
    return changed


def _reading(cur: Any, memo: Any, now: datetime, config: Config, dry: bool = False):
    """A run's reading of its snapshot through `memo` (0116, 0169: incremental.State; incremental.refresh, then load
    and think): (world, ask, outcome, counts). `dry`: nothing is added or asked again (the check's incremental
    reading)."""
    from insight_core.markx import incremental
    incremental.refresh(cur, memo)
    world = load(cur, now, config, memo=memo)
    cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'connect' AND status IN ('open', 'leased')")
    waiting = cur.fetchone()[0]
    from insight_core.markx import story_window
    back = config.days > story_window.RECENT       # 0144 A: the window reaches back: old questions come in pages
    ask = Ask(cur, now, caps={"connect": max(0, min(config.connect_new, config.connect_open - waiting))}, memo=memo,
              dry=dry, old_after=story_window.RECENT if back else None, old_cap=story_window.BACKFILL_PAGE)
    out, counts = think(cur, world, config, ask, now)
    return world, ask, out, counts


def _digest(out: Outcome, ids: Dict[str, str], world: World, conns: Sequence[Dict[str, Any]],
            news_rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """incremental.digest of a reading: a story connection's ends as its member posts (ids differ between readings)."""
    from insight_core.markx import incremental
    members = {sid: tuple(sorted(out.about.get(key, {}))) for key, sid in ids.items()}
    ends = [dict(c, a=c["a"] if c["a_kind"] == "post" else members.get(c["a"], c["a"]),
                 b=c["b"] if c["b_kind"] == "post" else members.get(c["b"], c["b"])) for c in conns]
    return incremental.digest(wanted(out, world.posts), ends, news_rows)


def run(cur: Any, *, config: Config = Config(), now: Optional[datetime] = None,
        stage: Optional[Callable[[str], None]] = None, full: Optional[bool] = None,
        entity_budget: Optional[float] = None, limit: Optional[float] = None,
        began: Optional[float] = None) -> Dict[str, Any]:
    """One decision run on the caller's transaction: skipped when another holds the lock. Writes mx_* rows only.
    insight-ingestion runs it in `snapshot()` (markx/jobs.py), so every read of Mark IX's tables sees one snapshot.
    `stage(name)` is called as each stage begins (0112 Decided 12: the stage logs and the time limit); one that
    raises stops the run between stages, and the caller's transaction rolls back: nothing half done (and, 0169, the
    state it would have left with it: the next run starts from the last finished run's).

    0116, 0169: a run is incremental (it reads again only what changed since the last run, by the state the last
    run left in Postgres: markx/incremental.py) unless `full`, or there is no state of the last finished run, the
    code, config or a guide changed, or no full run started since the night's NIGHTLY_HOUR. A full run with a state
    first reads the snapshot as an incremental run would, writing nothing, and logs any difference from the full
    reading (`counts.check`). Every run leaves its state in the same transaction (a failed run leaves the last).

    0128: `entity_budget` is the entities stage's own seconds (entity_stage.entities); its full pass stops after a
    chunk past it and the next run resumes it. None: no limit.

    v10.13.9: the story window steps back only when this run left room (story_window.room): `limit` is the caller's
    LIMIT (jobs.LIMIT when None), `began` the time.monotonic() its run began (jobs: before its candidate finder, as
    LIMIT counts; this call's start when None)."""
    import json as _json
    import time as _time
    from insight_core.markx import incremental, news as mx_news, repo, schemas
    timed: List[Tuple[str, float]] = []           # (stage, when it began): the room check's own clock

    def mark(name: str) -> None:
        if stage is not None:
            stage(name)
        timed.append((name, _time.monotonic()))
    cur.execute("SHOW transaction_isolation")
    isolation = cur.fetchone()[0]
    cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK_KEY,))
    if not cur.fetchone()[0]:
        return {"skipped": "another decision run holds the lock"}
    started = _time.monotonic()
    now = now or _now()
    from insight_core.markx import story_window
    recent_days = min(config.days, story_window.RECENT)   # surges keep the News window (0144: never the backfill's)
    if config.story_window:                               # 0144 A1: the owner's story window, read each run
        config = replace(config, days=story_window.days_for_run(cur, now))
    mark("load")
    schemas.ensure_guides(cur)
    guides = {k.name: k.guide for k in schemas.KINDS.values()}
    key = _json.dumps([CODE_VERSION, incremental.code_stamp(), config.as_dict(), guides], sort_keys=True, default=str)
    memo, warm = incremental.open_state(cur, key)
    nightly = warm and full is None and incremental.nightly_due(cur, now)
    kind = "full" if (full or not warm or nightly) else "incremental"
    check = None
    if kind == "full" and warm:
        prev = memo
        prev.dry = True
        memo = incremental.fresh(prev)
        p_world, p_ask, p_out, _ = _reading(cur, prev, now, config, dry=True)
        p_ids, _ = persist(cur, None, p_out, p_world, now, write=False)
        p_keys = [s["story"] for s in p_out.stories(p_world.posts) if voices(p_world.posts, s["posts"]) >= 2]
        p_conns = connections(cur, p_out, p_ids, p_world, p_ask, config, p_keys)
        p_news = mx_news.write(cur, None, out=p_out, ids=p_ids, world=p_world, now=now, store=False)["made_rows"]
        check = _digest(p_out, p_ids, p_world, p_conns, p_news)
        del prev, p_world, p_ask, p_out, p_ids, p_conns, p_news
    cur.execute("SELECT max(started_at) FROM mx_runs WHERE finished_at IS NOT NULL")
    previous = cur.fetchone()[0]                    # 0119: what the entities stage reads as new since
    run_id = repo.start_run(cur, code_version=CODE_VERSION, config={**config.as_dict(), "guides": guides})
    mark("questions and decisions")     # the checks, joins and pairs, glue and merges, the second pass
    world, ask, out, counts = _reading(cur, memo, now, config)
    counts["tasks_reasked"] = ask.reopen()        # asked again before they count (0112 Decided 8)
    mark("write")
    ids, written = persist(cur, run_id, out, world, now)
    news_keys = [s["story"] for s in out.stories(world.posts) if voices(world.posts, s["posts"]) >= 2]
    mark("connections")
    conns = connections(cur, out, ids, world, ask, config, news_keys)
    counts["connections"] = dict(persist_connections(cur, run_id, conns, set(ids.values()) | set(world.posts), now))
    # v10.13.9: graph and back are stages of their own (were inside "connections", 95.8 s on the server, unsplit).
    # graph counts in LIMIT: its backfills stop at their own deadline, sized as a share of LIMIT (BACKFILL_SECONDS)
    mark("graph")
    from insight_core.markx import graph   # 0131: Stalker's first edges (authors' links, identity, the judge)
    counts["graph"] = graph.stage(cur, now=now, run_id=run_id, open_cap=config.relate_open)
    mark("back")
    from insight_core.markx import back    # 0136: back in the news (the trigger, then the back questions)
    counts["back"] = back.stage(cur, now=now, run_id=run_id, open_cap=config.back_open)
    mark("later")
    from insight_core.markx import later   # 0163: later developments (the follow-up trigger, then their back questions)
    counts["later"] = later.stage(cur, now=now, run_id=run_id, open_cap=config.back_open)
    mark("headlines")
    counts["headlines_changed"] = headlines(cur, out, ids, world, ask, news_keys)
    mark("news")
    counts["news"] = mx_news.write(cur, run_id, out=out, ids=ids, world=world, now=now, ask=ask,
                                   headed={ids[k] for k in news_keys})
    if check is not None:
        diff = incremental.differences(check, _digest(out, ids, world, conns, memo.news["rows"] if memo.news else []))
        counts["check"] = {"same": not diff, **({"differences": diff} if diff else {})}
        if diff:
            log.warning("Mark X incremental-run bug: a full run reads this snapshot otherwise: %s", diff)
    mark("entities")                    # 0119 A1: linking, merges, the review queue, the alias and collide questions
    from insight_core.markx import entity_stage
    counts["entities"], days = entity_stage.entities(cur, ask=ask, now=now, run_id=run_id, since=previous,
                                                     full=full, budget=entity_budget)
    mark("surges")                      # 0119 A2
    counts["surges"] = entity_stage.surges(cur, now=now, run_id=run_id, days=days, since=previous,
                                           window_days=recent_days)
    mark("perspectives_plan")           # 0119 B: perspectives inside a story and the story sheet
    from insight_core.markx import perspectives
    counts["perspectives"] = perspectives.stage(cur, ask=ask, now=now, run_id=run_id)
    counts["briefing"] = mx_news.briefing(cur, ask=ask, now=now, hour=BRIEFING_HOUR, limit=BRIEFING_STORIES)
    if config.story_window and story_window.backfilling(cur):   # 0144 A2: the backfill steps back once this step is asked and found
        from insight_core.markx import candidates as mx_candidates
        since_next = story_window.next_since(cur, now)
        from insight_core.markx import jobs as mx_jobs
        at = _time.monotonic()
        took = {name: round((timed[i + 1][1] if i + 1 < len(timed) else at) - t, 1)
                for i, (name, t) in enumerate(timed)}
        own = sum(s for name, s in took.items() if name in mx_jobs.OWN_BUDGET)
        held = story_window.room(at - (started if began is None else began) - own,
                                 mx_jobs.LIMIT if limit is None else limit,
                                 entities=took.get("entities"), entity_budget=entity_budget)
        counts["story_window"] = {"days": config.days, **story_window.advance(
            cur, now, waiting_old=sum(ask.waiting_old.values()),
            candidates_left=mx_candidates.unfound_count(cur, since_next) if since_next else 0, held=held),
            "old_added": dict(ask.old_added), "old_waiting": dict(ask.waiting_old)}
    want = wanted(out, world.posts)
    counts["run"] = {"kind": kind, "now": now.isoformat(), **({"nightly": True} if nightly else {}),
                     "dirty_tasks": memo.report.get("dirty_tasks", 0) if kind == "incremental" else None,
                     "dirty_posts": len(memo.report.get("dirty_posts") or ()) if kind == "incremental" else None,
                     "texts_read": memo.report.get("texts_read"), "ix_changed": memo.report.get("ix_changed"),
                     **{k: memo.report.get(k) for k in ("texts_loaded", "inputs_rendered", "inputs_kept")},
                     **(incremental.closure(memo, want, world.stories) if kind == "incremental" else
                        {"closure": len(want), "stories": len(want)})}
    counts["run"]["state"] = incremental.save(cur, memo, run_id, want)   # 0169: what the next run starts from
    counts["run"]["seconds"] = round(_time.monotonic() - started, 3)
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

