"""Mark X's story decisions: from Mark IX's stories and Haiku's valid answers to Mark X's stories (issue 0086 E).

The rules (`plan_pass1`, `plan_pass2`, `decide`, `settle`, `settle_check`) are pure functions of Mark IX's stories,
the candidates, the valid answers and `Config`: checks demote or remove members, joins and pairs add posts, merges
join stories, late posts become connections, a story-changing answer counts only once a second answer agrees, and a
member Mark IX joined by a link is never removed. Question ids (`check:<story>:<post>`, `join:`, `pair:`, `merge:`,
`merge2:`, `merge3:`) key stories inside one run only; the job matches them to Mark X's stories by their member posts.
The job (`run`, inside `snapshot`) reads Mark IX's tables read only, asks the questions as tasks, and writes Mark X's
stories, memberships, connections, refusals and News (closing what changed, never deleting): mx_* tables only. One
run at a time (a Postgres advisory lock).
"""
from __future__ import annotations

import contextlib
import logging
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from psycopg import errors as psycopg_errors

from insight_core.markx import pairing, validate
from insight_core.utils import voice

log = logging.getLogger(__name__)

CODE_VERSION = "markx-decide-v1"
CERTAIN = frozenset({"thread", "quote", "address"})    # a tree reason that is not a guess: no check (unless a roundup)
LINKED = frozenset({"citation", "quote", "address"})    # joined by a link to the story's page
ABOUT = frozenset({"same_event", "development", "reaction"})
ORDER = {"check": 0, "join": 1, "pair": 2, "merge": 3}
LATE = timedelta(hours=72)                              # Mark IX's link window
_SAME = pairing.POLICIES[pairing.SAME_STORY]
_CONNECTED = pairing.POLICIES[pairing.CONNECTED]


@dataclass(frozen=True)
class Config:
    """The bars and rules. `prototype()` is the recorded prototype run's (no guards, no late rule)."""
    tau_join: float = 0.60
    tau_merge: float = 0.85
    tau_keep: float = 0.30          # a check removes below it ...
    tau_keep2: float = 0.15         # ... in a 2-voice story below this (rule B)
    tau_connect: float = 0.60
    tau_refuse: float = 0.60        # a merge or connect "different" at this p or more is stored (mx_refusals)
    min_words: int = _SAME.min_words
    cand_lo: float = _SAME.cosine
    story_lo: float = _SAME.story_cosine
    story_days: int = _SAME.story_window.days
    connect_lo: float = _CONNECTED.story_cosine     # connect questions: story pairs at this centroid cosine ...
    connect_days: int = _CONNECTED.story_window.days   # ... at most this far apart ...
    connect_voices: int = _CONNECTED.min_voices     # ... both stories of this many voices or more ...
    connect_new: int = 100          # ... and at most this many new connect tasks a run, the newest pairs first ...
    connect_open: int = 100         # ... and none while this many connect tasks wait (open or leased)
    # a connect pair whose first posts' vectors are below this cosine is settled as unconnected, never asked; None:
    # every pair is asked (measured: plan/issues/0210)
    connect_settle_below: Optional[float] = None
    connect_shadow_below: Optional[float] = 0.45    # counted (tasks_shadow_settled), asked anyway
    relate_open: int = 100
    back_open: int = 50
    check_threads: bool = True
    roundup_first: bool = True      # ... and a roundup that is its story's first post
    two_event_guard: bool = True    # a post with several events is demoted, never removed
    late_rule: bool = True
    confirm: bool = True            # a story-changing join, pair or merge counts once asked again
    reason_rule: bool = True        # ... and never while its own reason says the post is not about the story
    # a story-changing answer with no quote of its own post is asked again under the current guide (it counts until
    # that answer is in)
    reask_unquoted: bool = True
    link_keeps: bool = True         # a check demotes a member Mark IX joined by a link at most, never removes it
    confirm_check: bool = True      # a check taking out a 2-voice story's second voice counts once asked again
    # two stories whose members link one document page are a merge question; off: wrong on every case (0121 D5)
    document_merges: bool = False
    document_days: int = _SAME.document_window.days   # ... when two of their posts linking it are at most this far apart
    days: int = 30                  # the window a run decides ...
    story_window: bool = True       # ... read from the owner's story window each run (markx/story_window.py)
    # two stories whose core members overlap are a merge question (`plan_overlaps`), any event kind: at least
    # `overlap_min` posts are core members of both, and they are at least `overlap_share` of the smaller story's
    # members; never two the judge kept apart this run (a merge answered "different" or "development"). The overlap
    # only proposes: the two are one story when that merge's answer says same_event at `tau_merge` (`decide`'s
    # merges), never without an answer (0280 K1: code-only at 2 posts / half it merged 2 wrong pairs of 38). With the
    # judge deciding, the bar is loosened to 1 post / 0.3 (the 2026-11-19 server copy: 172 candidates, about 3 new a
    # day). Measured with judge-story-v2 (v10.49, one release is one row): 39 right and 1 wrong merge of 79 labeled
    # pairs (precision 0.975, recall 0.68; code-only at 2 / 0.5: 36 and 2, 0.947 / 0.63; judge-story-v1: 23 and 1),
    # 33 right and 0 wrong of 40 fresh held-out pairs (code-only: 13 and 0). 0: off.
    # v10.49.1: OFF on production. A mixed story's card (its first members) let a merge absorb a two-week saga
    # (Nvidia's Nov 8 scandal posts into the Nov 23 reinstatement): the story started Nov 8 and News dropped its
    # biggest row. Back on once cards follow the story's main subject and a saga guard is measured (0281 E).
    overlap_min: int = 0
    overlap_share: float = 0.3

    @staticmethod
    def prototype() -> "Config":
        return Config(two_event_guard=False, late_rule=False, check_threads=False, confirm=False, reason_rule=False,
                      link_keeps=False, confirm_check=False, document_merges=False, roundup_first=False,
                      reask_unquoted=False, overlap_min=0)

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
    """A post as the rules read it. `at`: anything that orders. `source`: the voice it counts as (tasks.Post.voice)."""
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
    type: str
    story: Optional[str] = None               # check, join: the story; merge: one story
    post: Optional[str] = None                # check, join, pair: the post asked about
    anchor: Optional[str] = None              # join: the candidate's other post; pair: the post asked against
    other: Optional[str] = None
    voices: int = 0                           # check: the story's voices (rule B)
    cos: Optional[float] = None
    why: Optional[str] = None
    roundup: bool = False
    side: Tuple[str, ...] = ()                # the story's posts the question shows
    side_b: Tuple[str, ...] = ()
    second: bool = False
    last_voice: bool = False                  # check: taking it out leaves its story one voice


@dataclass(frozen=True)
class Verdict:
    relation: str
    p: float                                  # p "about": the confidence when the relation is about, else 1 - it
    reason: Optional[str] = None
    call: Optional[str] = None

    @staticmethod
    def of(answer: Dict[str, Any], call: Optional[str] = None) -> "Verdict":
        """A judge answer (relation, confidence 0-100) as the prototype read it (ingest.py)."""
        conf = float(answer.get("confidence") if answer.get("confidence") is not None else 50) / 100
        rel = answer.get("relation")
        return Verdict(rel, conf if rel in ABOUT else 1 - conf, answer.get("reason"), call)


@dataclass
class Outcome:
    about: Dict[str, Dict[str, Dict[str, Any]]]       # story -> post -> evidence (after glue and merges)
    mentions: Dict[str, Dict[str, Dict[str, Any]]]
    log: List[Dict[str, Any]]
    connections: List[Dict[str, Any]]
    merged_into: Dict[str, str]
    ix: Set[str]
    final: Dict[str, str] = field(default_factory=dict)        # every key -> the story it ended in (glue, merges)
    merge_calls: Dict[str, Optional[str]] = field(default_factory=dict)
    came_from: Dict[Tuple[str, str], str] = field(default_factory=dict)   # (story, post) -> the key it was in before merges
    refusals: List[Dict[str, Any]] = field(default_factory=list)

    def stories(self, posts: Dict[str, Post], min_posts: int = 2) -> List[Dict[str, Any]]:
        """Every story of `min_posts`+ known posts, posts earliest first."""
        out = []
        for key, ms in self.about.items():
            known = [p for p in ms if p in posts]
            if len(known) >= min_posts:
                out.append({"story": key, "posts": sorted(ms, key=lambda p: _at_key(posts, p))})
        return out


def _at_key(posts: Dict[str, Post], pid: str):
    """Sort key of a post id by its time, unknown posts first."""
    p = posts.get(pid)
    return (1, p.at) if p else (0,)


def voices(posts: Dict[str, Post], ids: Iterable[str]) -> int:
    """How many voices the known posts among `ids` are (Voice's MARKX rule over each Post's counted source)."""
    return voice.count((voice.Said(posts[i].source, posts[i].kind) for i in ids if i in posts), voice.Policy.MARKX)


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
    """The first pass's questions: checks of every uncertain member and every roundup member of a 2+ voice story
    (with `config.check_threads`, also members joined by `thread`); a check shows the story's other reports, else its
    other members, never an empty story. Each candidate pair (a, b, cosine or None) becomes a merge when both posts are
    in 2+ voice stories, a join when one is, a pair when neither; then the story pairs (x, y, centroid cosine) not
    asked yet. `kinds`: each post's reading kind. `in_window(a)`: whether a pair's earlier post is in the window.
    `copies`: each story's near-copy members (tasks.near_copies), never checked."""
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
        # the origin is Mark IX's tree root (the member with no parent reason), not its earliest post
        origin = next((m.post for m in ms if m.why is None), ms[0].post)
        for m in ms:
            p = posts[m.post]
            roundup = kinds.get(m.post) == "roundup"
            # a roundup is checked even when it is the story's first post (two digests citing one page make a story)
            if (m.post == origin and not (roundup and config.roundup_first)) or not voice.is_voice(p.kind) \
                    or m.post in copies.get(key, ()):
                continue
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
            continue
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
    for x, y, cos in story_pairs:   # cos None: found by a shared document, not by meaning
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
    """The second pass: every story the first pass made from lone posts against every other 2+ voice story, centroid
    >= story_lo, first posts at most story_days apart. `centroid_cos(posts_a, posts_b)`: their mean vectors' cosine
    (None when either has none). `within(at_a, at_b)`: the days rule. `documents(posts_a, posts_b)`: whether two of
    their posts link one document page within `document_days`; such a pair is asked whatever its centroid and days."""
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


def plan_overlaps(posts: Dict[str, Post], out: Outcome, config: Config = Config()) -> List[Question]:
    """The third pass: a merge question (`merge3:`) for each pair of `out`'s stories whose core members overlap
    (`overlapping`), never a pair the judge kept apart this run. Each side shows its story's own members first (the
    posts not in the other, earliest first), then the shared ones, 3 at most: a post in both says nothing about
    whether the two are one event (0280 K1: one aggregator post in an image-ads story and a GPT-6 story)."""
    if config.overlap_min <= 0:
        return []

    def f(k: str) -> str:
        return out.final.get(k, k)

    def earliest(ps: Iterable[str]) -> List[str]:
        return sorted(ps, key=lambda p: _at_key(posts, p))

    apart = {frozenset((f(x["a"]), f(x["b"]))) for x in out.refusals}
    apart |= {frozenset((f(c["a"]), f(c["b"]))) for c in out.connections
              if c["a_kind"] == "story" and c["b_kind"] == "story"}
    qs = []
    for x, y, _ in overlapping(posts, out.about, out.came_from, out.merge_calls, out.ix, apart, config):
        mx, my = [p for p in out.about[x] if p in posts], [p for p in out.about[y] if p in posts]
        both = earliest(set(mx) & set(my))
        side = tuple((earliest(set(mx) - set(my)) + both)[:3])
        side_b = tuple((earliest(set(my) - set(mx)) + both)[:3])
        qs.append(Question(f"merge3:{x}:{y}", "merge", story=x, other=y, side=side, side_b=side_b))
    return qs


# ---- the decisions ------------------------------------------------------------------------------------

def decide(posts: Dict[str, Post], stories: Dict[str, Sequence[Member]], answered: Iterable[Tuple[Question, Verdict]],
           config: Config = Config(), events: Optional[Dict[str, Optional[str]]] = None) -> Outcome:
    """The verdicts (question, verdict) into edges: checks first, then joins and pairs, pair stories that share a post
    glued, then merges, ordered by kind, then question id. `events`: each post's reading `events` (two-event guard)."""
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
    refusals: List[Dict[str, Any]] = []
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
            demoting = rel in ("mention", "digest_item")
            if pa < strict:
                ev = about[q.story].pop(q.post, None)
                kind = "demote" if demoting else "remove"
                guarded = None
                if kind == "remove" and config.two_event_guard and events.get(q.post) == "several":
                    guarded = "two-event"
                elif kind == "remove" and config.link_keeps and q.why in LINKED:
                    guarded = "link"           # it links the story's page: a mention at most
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
                                            "shown": {"b": list(q.side)},
                                            "relation": relation, "p": pa, "call": v.call, "tid": q.tid,
                                            "reason": v.reason, "late": True})
                        log.append({"tid": q.tid, "change": "late_connection", "story": key, "post": q.post,
                                    "relation": rel, "p_about": pa, "reason": v.reason, "call": v.call})
                        continue
                if key not in about:
                    about[key][q.anchor] = {"by": "meaning-anchor", "call": v.call, "p_about": pa, "type": q.type,
                                            "relation": rel}
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
        if rel == "different" and pa >= config.tau_refuse:
            # the judge keeps the two stories apart (a cannot-link for News's grouping), with what it was shown
            refusals.append({"a": q.story, "b": q.other, "p": pa, "call": v.call, "tid": q.tid, "reason": v.reason,
                             "shown": {"a": list(q.side), "b": list(q.side_b)}})
        if rel == "development" and pa >= config.tau_merge:
            log.append({"tid": q.tid, "change": "development_link", "story": q.story, "other": q.other,
                        "p_about": pa, "cos": q.cos, "reason": v.reason, "call": v.call})
            connections.append({"a_kind": "story", "a": q.story, "b_kind": "story", "b": q.other,
                                "shown": {"a": list(q.side), "b": list(q.side_b)},
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
    def merge_all() -> Tuple[Dict[str, Dict[str, Dict[str, Any]]], Dict[Tuple[str, str], str]]:
        out_: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
        came: Dict[Tuple[str, str], str] = {}
        for key, ms in about.items():
            out_[find(key)].update(ms)
            for p in ms:
                came[(find(key), p)] = key
        return out_, came

    merged, came_from = merge_all()
    keys = set(glue) | set(alias) | set(about) | set(mentions) | set(members)
    return Outcome(about=dict(merged), mentions={k: dict(v) for k, v in mentions.items()}, log=log,
                   connections=connections, merged_into={k: find(k) for k in alias}, ix=set(members),
                   final={k: find(g(k)) for k in keys}, merge_calls=merge_calls, came_from=came_from,
                   refusals=refusals)


def core(ev: Dict[str, Any], merged_in: bool) -> bool:
    """Whether a member's evidence says the post is about its story's own event: Mark IX joined it, the judge said
    same_event (a join, a pair or its anchor), or a merge brought it in; not a development or a reaction joined."""
    return merged_in or ev.get("by") == "rule" or (ev.get("by") in ("judge", "meaning-anchor")
                                                   and ev.get("relation") == "same_event")


def overlapping(posts: Dict[str, Post], stories: Dict[str, Dict[str, Dict[str, Any]]],
                came_from: Dict[Tuple[str, str], str], merge_calls: Dict[str, Optional[str]], ix: Iterable[str],
                apart: Set[FrozenSet[str]], config: Config = Config()) -> List[Tuple[str, str, int]]:
    """The story pairs that are one story by their overlap, as (keep, drop, shared core posts), each pair once, in a
    stable order: two stories in which at least `config.overlap_min` posts are core members of both (`core`), those
    being at least `config.overlap_share` of the smaller story's known members, and never a pair in `apart`. One
    event told by several stories (0280 K1: four Mark X stories of one reinstatement) whatever its kind; a launch's
    stories are joined by the chain as well. Between the two, a Mark IX story keeps its key, else the older one."""
    ix = set(ix)
    known = {k: [p for p in ms if p in posts] for k, ms in stories.items()}
    cores: Dict[str, List[str]] = defaultdict(list)
    for key, ms in sorted(stories.items()):
        for p, ev in ms.items():
            origin = came_from.get((key, p), key)
            if p in posts and core(ev, origin != key and bool(merge_calls.get(origin))):
                cores[p].append(key)
    shared: Counter = Counter()
    for p, keys in cores.items():
        for n, x in enumerate(keys):
            for y in keys[n + 1:]:
                shared[(x, y)] += 1
    out = []
    for (x, y), n in sorted(shared.items()):
        small = min(len(known[x]), len(known[y]))
        if n < config.overlap_min or n < config.overlap_share * small or frozenset((x, y)) in apart:
            continue
        keep, drop = sorted([x, y], key=lambda s: (s not in ix, _first_key(posts, stories[s]), s))
        out.append((keep, drop, n))
    return out


def _late(at: Any, began: Any) -> bool:
    try:
        return at - began > LATE
    except TypeError:          # ISO strings (the prototype's reproduction): never late
        return False


def _first_key(posts: Dict[str, Post], ms: Dict[str, Any]):
    known = [posts[p].at for p in ms if p in posts]
    return (0, min(known)) if known else (1,)


# ---- asked again (0112 Decided 8) ---------------------------------------------------------------------
# A join, pair or merge that would change a story counts only when a second answer agrees, and an "about" answer whose
# own reason says the post is not about the story never counts (measured: plan/issues/0112).

MAX_ASKS = 3       # a question is asked at most this many times (a first answer, its second, one more on a split)

# The class of reason text that says "not this story" (never a name or a site): the reason names another relation or
# thing for the post ("a different event", "closer to a mention"; not "a different angle" of the same event); says the
# story's subject is not the post's; says unrelated, absent, not mentioned; or says the event is one point of a wider
# post (0217). Not in the class: "rather than the release itself", "only as background", "does not mention <detail>".
_OTHER_RELATION = (r"\b(?:relation|it|this|which)\s+(?:is|should be|falls under|reads as|is best read as|is closer to"
                   r"|is actually)\s+(?:actually\s+|best read as\s+|closer to\s+)?(?:an?\s+)?"
                   r"(?:different|mention|unrelated|digest item)\b"
                   r"(?!\s+(?:angle|reading|aspect|take|framing|view|perspective|detail))"
                   r"|\bfalls under different\b|\bshould be different\b|\ba mention rather than\b|\bis a mismatch\b"
                   r"|\bmismatch in subject\b"
                   r"|\bis a different (?:event|happening|story|model|release|product|project|company|claim"
                   r"|announcement|report|subject)\b"
                   r"|\ba different (?:event|happening|model|release|product|project|company|claim) from\b"
                   r"|(?<!not )\ban? different (?:\w+\s+){0,2}(?:post|piece|article|video|thread|tweet)\b"
                   r"|(?<!not )(?<!no )\b(?:related but|but|is|are|as|a|an) distinct\b|(?<!not )\bdistinct from\b")
_NOT_ITS_SUBJECT = r"\bnot (?:its|the post's) (?:main )?(?:subject|topic)\b"
_UNRELATED = r"\bunrelated\b|\babsent from\b|\bno relation\b|\bnot related\b|\bnot mentioned\b"
_ONE_POINT = r"\bas one of (?:several|many) (?:points|themes|topics|items)\b|\bas a related theme\b|\bonly in background\b"
NOT_THIS_STORY = re.compile("|".join((_OTHER_RELATION, _NOT_ITS_SUBJECT, _UNRELATED, _ONE_POINT)), re.I)


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
    """Whether a story-changing answer can count once a second one agrees: a join's "about" at the join bar, a pair's
    or a merge's "same event" at its bar. A pair's development or reaction never makes a story."""
    if not changes_story(kind, v, config):
        return False
    return kind == "join" or v.relation == "same_event"


def settle(kind: str, answers: Sequence[Verdict], config: Config = Config()) -> Tuple[Optional[Verdict], bool]:
    """(the verdict that counts or None, whether to ask again) from a question's valid answers, oldest first. The
    newest decides: one that changes nothing counts as it is; one that would change a story counts only when the one
    before it agrees (both `agreeing`, neither reason against it), as one verdict at the lower p, named by the earlier
    call, with the relation that says less. Until then it is asked again, MAX_ASKS times at most."""
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
    """(the verdict that counts or None, whether to ask again) of a check that would take out a 2-voice story's second
    voice, answers oldest first. One that keeps the post (p at `bar` or more) counts at once; one that takes it out
    counts only when the one before agrees, as one verdict that says less (a mention over a removal, the higher p,
    the earlier call). Until then asked again, MAX_ASKS times at most; then the post stays."""
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
    return [(q, verdicts[q.tid]) for q in questions if q.tid in verdicts]


# ---- the job ------------------------------------------------------------------------------------------
# Everything below reads Mark IX's tables and writes mx_* ones only.

MODEL = "bge-m3"
LOCK_KEY = 860_086_005                 # the advisory lock one run holds (pg_try_advisory_xact_lock)
CAP = 500                              # new tasks of one kind a run may add (the rest wait for the next run)
BRIEFING_HOUR = 20                     # each day, after 20:00 server time
BRIEFING_STORIES = 10


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Ask:
    """The answers a run reads, and the tasks it adds for the questions not asked yet (content-only inputs: one task
    per question whatever ids come with it)."""

    def __init__(self, cur: Any, now: datetime, caps: Optional[Dict[str, int]] = None, memo: Any = None,
                 dry: bool = False, old_after: Optional[int] = None, old_cap: int = 0) -> None:
        self.cur, self.now = cur, now
        self.caps = dict(caps or {})          # new tasks a kind may add this run (CAP for the kinds not named)
        self.old_after = old_after            # while the story window reaches back, a question whose post is older
        self.old_cap = old_cap                # than this many days is one of a page (old_cap a kind a run)
        self.old_added: Counter = Counter()
        self.waiting_old: Counter = Counter()
        self.memo = memo                      # the snapshot's tasks and calls (incremental.refresh)
        self.dry = dry
        self.added: Counter = Counter()
        self.raced: Counter = Counter()
        self.waiting: Counter = Counter()
        self.answered: Counter = Counter()
        self.settled: Counter = Counter()
        self.shadow_settled: Counter = Counter()
        self.again: Dict[str, str] = {}       # a first call whose question is to be asked again -> its kind
        self.reasked: Counter = Counter()
        self.last_earlier = False
    def answer(self, kind: str, text: Any, *, a: Any = None, b: Any = None, day: Any = None,
               priority: int = 0, add: bool = True) -> Optional[Tuple[Dict[str, Any], str]]:
        """(the valid answer, its call id), or None: a new task is added up to the kind's cap a run (`caps`, else
        CAP); with `add` False it is never added, only a stored answer is read. A task another transaction committed
        since the snapshot raises a serialization failure on add, caught in a savepoint (`raced`). `text`: the input,
        or an incremental.Input (rendered only when the task is added)."""
        from insight_core.markx import incremental, repo, schemas, tasks
        memo = self.memo if kind in incremental.KINDS else None
        if memo is not None:
            h = incremental.hash_of(text)
            got = memo.tasks.get((kind, h))
            task = None if got is None else {"id": got[0], "status": got[1], "earlier": got[3]}
        else:   # an answered task under any of the kind's guides first (a question re-asked keeps its earlier answer)
            task = None
            for guide in schemas.answer_guides(kind):
                got = repo.task_for(self.cur, kind=kind, guide=guide, input=incremental.text_of(text))
                if got is not None and (task is None or (got["status"] == "answered") > (task["status"] == "answered")):
                    task = got
                if task is not None and task["status"] == "answered":
                    break
        if task is None and not add:
            self.settled[kind] += 1
            return None
        if task is None:
            old = self.old_after is not None and priority > self.old_after
            if old:
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
                memo.tasks[(kind, h)] = (str(tid), "open", 0, False)
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
        current = schemas.KINDS[kind].guide
        self.last_earlier = bool(task.get("earlier", task.get("guide", current) != current))
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

    def reask(self, kind: str, text: Any, *, a: Any = None, b: Any = None, priority: int = 0) -> bool:
        """The question asked anew under its kind's current guide (the earlier answer counts until this one is in).
        Within the kind's cap; nothing in a dry run. Whether a task was added."""
        from insight_core.markx import incremental, tasks
        if self.dry or self.added[kind] >= self.caps.get(kind, CAP):
            return False
        try:
            with self.cur.connection.transaction():
                _tid, new = tasks.add(self.cur, kind, incremental.text_of(text), a=a, b=b, priority=priority)
        except psycopg_errors.SerializationFailure:
            self.raced[kind] += 1
            return False
        if new:
            self.added[kind] += 1
            self.reasked[kind] += 1
        return new

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
                            self.memo.tasks[key] = (tid, "open", *self.memo.tasks[key][2:])
            except psycopg_errors.SerializationFailure:
                self.raced[kind] += 1
        return dict(out)


@dataclass
class World:
    """What one run reads: Mark IX's stories touching the window, their posts and the candidates' posts (Mark X's
    text), the readings, and the window's start."""
    since: datetime
    stories: Dict[str, List[Member]]
    text: Dict[str, Any]
    posts: Dict[str, Post]
    readings: Dict[str, dict]
    candidates: List[Tuple[str, str, Optional[float]]]
    ix_mentions: Dict[str, Set[str]] = field(default_factory=dict)   # Mark IX story -> the roundups mentioning it
    memo: Any = None

    def kinds(self) -> Dict[str, Optional[str]]:
        if self.memo is not None:
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
        """Each Mark IX story's members that are a near-copy of another of its members; with the run's state, the
        next stories' members are read ahead a page at a time (incremental.prefetch)."""
        from insight_core.markx import tasks
        from insight_core.markx import incremental
        out = {}
        items = list(self.stories.items())
        ahead = 0
        for n, (key, ms) in enumerate(items):
            if self.memo is not None and n >= ahead:
                page: List[List[str]] = []
                while ahead < len(items) and (not page or sum(map(len, page)) < incremental.TEXT_PAGE):
                    page.append([m.post for m in items[ahead][1]])
                    ahead += 1
                incremental.prefetch(self.text, None, page)
            ids = [m.post for m in ms if m.post in self.text]
            found = (incremental.copies(self.memo, ids, self.text) if self.memo is not None
                     else tasks.near_copies([self.text[i] for i in ids]))
            if found:
                out[key] = found
        return out


def _window(cur: Any, table: str, posts: Dict[str, Post], since: datetime) -> List[Tuple[str, str, Optional[float]]]:
    """The window's candidate pairs (a, b, cosine; None for a pair not found by meaning), strongest first: each pair
    of `table` (embed.current_pairs) once, at its embedding cosine, both posts in the world and the first in the
    window. Read as a stream, on the world's own id strings."""
    canon = {p: p for p in posts}
    out: List[Tuple[str, str, Optional[float]]] = []
    last: Optional[Tuple[str, str]] = None
    best: Optional[float] = None

    def keep() -> None:
        a, b = last
        if a in posts and b in posts and posts[a].at >= since:
            out.append((canon[a], canon[b], best))
    with cur.connection.cursor(name=f"mx_window_{id(out)}") as c:
        c.itersize = 20000
        c.execute(f"SELECT a::text, b::text, source, score, now FROM {table} ORDER BY a, b")
        for a, b, source, score, now in c:
            if source != "embedding":
                cos = None
            elif now is not None:
                cos = round(float(now), 4)
            else:
                cos = None if score is None else float(score)
            if (a, b) != last:
                if last is not None:
                    keep()
                last, best = (a, b), cos
            elif cos is not None and (best is None or cos > best):
                best = cos
    if last is not None:
        keep()
    out.sort(key=lambda abc: (abc[2] is None, -(abc[2] or 0.0), abc[0], abc[1]))
    return out


def load(cur: Any, now: datetime, config: Config, memo: Any = None) -> World:
    """Mark IX's stories with a post in the last `config.days` (read only), every post of them and of the window's
    candidate pairs, and their readings. With `memo` (incremental.State), texts and readings are read only when used."""
    from insight_core.markx import embed, incremental, tasks
    since = now - timedelta(days=config.days)
    cur.execute(f"""SELECT sp.story_id::text, sp.post_id::text, sp.role, sp.parent_reason FROM story_posts sp
                    WHERE sp.story_id IN (SELECT sp2.story_id FROM story_posts sp2 JOIN posts p ON p.id = sp2.post_id
                                           WHERE {pairing.ordinary_date('p')} >= %s)""",
                (since,))
    rows = cur.fetchall()
    if memo is None:
        # only the candidate pairs the window keeps (their first post in it)
        rows_sql = f"""SELECT NULL::bigint AS k, c.a, c.b, c.source, c.score FROM mx_candidates c JOIN posts pa ON pa.id = c.a
                        WHERE c.kind = 'post_post' AND c.source <> 'link' AND {pairing.ordinary_date('pa')} >= %(since)s
                          AND EXISTS (SELECT 1 FROM posts pb WHERE pb.id = c.b)"""
    else:
        rows_sql = """SELECT NULL::bigint AS k, a, b, source, score FROM mx_candidates
                       WHERE kind = 'post_post' AND source <> 'link'"""
    # the pairs by the current vectors, streamed once the world is known (holding every pair was ~400 MB: 0218)
    table = embed.current_pairs(cur, rows_sql, {"since": since})
    cur.execute(f"SELECT DISTINCT unnest(ARRAY[a, b])::text FROM {table}")
    ids = {r[1] for r in rows} | {r[0] for r in cur.fetchall()}
    if memo is not None:
        text, posts, readings = incremental.world(cur, memo, ids)
    else:
        text = tasks.load_posts(cur, ids)
        posts = {pid: Post(pid, p.voice, p.kind, p.at, tasks.words(p)) for pid, p in text.items()}
        readings = tasks.readings(cur, ids)
    stories: Dict[str, List[Member]] = defaultdict(list)
    for sid, pid, role, why in rows:
        if pid in posts:
            stories[sid].append(Member(pid, role, why))
    for ms in stories.values():
        ms.sort(key=lambda m: (posts[m.post].at, m.post))
    window = _window(cur, table, posts, since)
    cur.execute(f"DROP TABLE IF EXISTS {table}")
    if memo is not None:
        incremental.ahead(memo, {m.post for ms in stories.values() if len(ms) > 1 for m in ms}
                          | {p for a, b, _ in window for p in (a, b)})
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
            shown = ps[:tasks.CARD_MEMBERS]
            got = None
            if ps and self._read(shown):
                text = self._render("card", shown, lambda: tasks.card_input(self._p(shown), self.w.readings), reads=True)
                got = self.ask.answer("card", text, a=ps[0], priority=self._priority(ps[0]))
            self.cards[key] = got[0] if got else None
        return self.cards[key]

    def _render(self, kind: str, ids: Sequence[str], render: Callable[[], str], **kw) -> Any:
        """The input, kept by what it shows (incremental.rendered); a str without the run's state."""
        from insight_core.markx import incremental
        m = self.w.memo
        return incremental.rendered(m, kind, ids, render, texts=self.w.text if m is not None else None,
                                    readings=self.w.readings if m is not None else None, **kw)

    def shows(self, q: Question, outcome: Optional[Outcome] = None) -> List[str]:
        """The posts `q`'s input shows, to read ahead (a guide only: a post left out is read when rendered)."""
        from insight_core.markx import tasks
        if q.type == "check":
            return [q.post, *q.side]
        if q.type == "join":
            return [q.post, *self.story_posts(q.story), *q.side]
        if q.type == "pair":
            return [q.anchor, q.post]
        if q.type == "merge":
            cards = [p for k in (q.story, q.other) if k not in self.cards
                     for p in self.w.earliest(self.story_posts(k, outcome))[:tasks.CARD_MEMBERS]]
            return [*q.side, *q.side_b, *cards]
        return []

    def story_posts(self, key: str, outcome: Optional[Outcome] = None) -> List[str]:
        if key in self.members:
            return [m.post for m in self.members[key]]
        return sorted((outcome.about.get(key, {}) if outcome else {}), key=lambda p: _at_key(self.w.posts, p))

    def settled(self, q: Question, text: Any, **kw) -> Optional[Verdict]:
        """A join's, pair's or merge's verdict as it counts (`settle`): asked again when it would change a story and
        no second answer agrees yet (`Ask.reopen`)."""
        got = self.ask.answer(q.type, text, **kw)
        if got is None:
            return None
        first = Verdict.of(got[0], got[1])
        c = self.config
        if not changes_story(q.type, first, c):
            return first
        # an unquoted story-changing answer cannot be told from one written for another question of its batch: ask it
        # under the current guide; the earlier answers count until then, never reopened
        unquoted = c.reask_unquoted and self.ask.last_earlier and validate.unquoted(q.type, got[0])
        if unquoted:
            self.ask.reask(q.type, text, **kw)
        if not (c.confirm or c.reason_rule):
            return first
        v, again = settle(q.type, [first] + self.ask.later(got[1]), c)
        if again and not unquoted:
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
    """Pairing's document source over this run's world (the stories two of whose posts link one document page
    within `document_days`; a roundup's links never count)."""

    def __init__(self, world: World, config: Config) -> None:
        super().__init__(world.text, world.posts, world.kinds(), config.same_story())
        self.w = world


def _question_at(q: Question, world: World) -> Any:
    """A question's newest post time (its post, anchor and the posts it shows)."""
    ids = [x for x in (q.post, q.anchor, *q.side, *q.side_b) if x and x in world.posts]
    return max((world.posts[x].at for x in ids), default=world.since)


def _ask_all(q: "Questions", qs: Sequence[Question], world: World, outcome: Optional[Outcome] = None) -> List[Optional[Verdict]]:
    """Each question's verdict, in `qs`'s order. While the story window reaches back, they are asked newest first (a
    run's page of old questions is the newest); decisions never depend on the order asked. With the run's state, the
    posts the next questions show are read ahead a page at a time."""
    from insight_core.markx import incremental
    order = list(range(len(qs)))
    if q.ask.old_after is not None:
        order.sort(key=lambda n: (_question_at(qs[n], world), qs[n].tid), reverse=True)
    out: List[Optional[Verdict]] = [None] * len(qs)
    ahead = 0
    for i, n in enumerate(order):
        if world.memo is not None and i >= ahead:
            page: List[List[str]] = []
            reads: List[List[str]] = []
            size = 0
            while ahead < len(order) and (not page or size < incremental.TEXT_PAGE):
                shown = q.shows(qs[order[ahead]], outcome)
                page.append(shown)
                size += len(shown)
                if qs[order[ahead]].type != "check":
                    reads.append(shown)
                ahead += 1
            incremental.prefetch(world.text, None, page)
            if reads:
                incremental.prefetch(world.text, world.readings, reads)
        out[n] = q.verdict(qs[n]) if outcome is None else q.verdict(qs[n], outcome)
    return out


def think(cur: Any, world: World, config: Config, ask: Ask, now: datetime) -> Tuple[Outcome, Dict[str, Any]]:
    """The two passes over this world: questions, the verdicts found, the decisions."""
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
    # stories whose core members overlap: a merge question each, one story only on its answer
    q3 = plan_overlaps(world.posts, out, config)
    got3 = _ask_all(q, q3, world, out)
    ans3 = [(x, got3[n]) for n, x in enumerate(q3) if got3[n] is not None]
    if ans3:
        out = decide(world.posts, world.stories, ans1 + ans2 + ans3, config, world.events())
    counts = {"questions": dict(Counter(x.type for x in q1 + q2 + q3)), "answered": len(ans1) + len(ans2) + len(ans3),
              "pass2": len(q2), "pass3": len(q3), "changes": dict(Counter(c["change"] for c in out.log))}
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


def _start(members: Iterable[str], posts: Dict[str, Post]) -> Any:
    """A story's first_at: its earliest post that is not background (story_rules.story_start)."""
    from insight_core.utils.story_rules import story_start
    ps = [posts[p] for p in members if p in posts]
    return story_start(ps, {p.id: p.at for p in ps})


# the dating rule is stamped (a fingerprint of `_start` over stamps.story_dates): a run that finds another stamp than
# the one kept re-dates every current story once (`redate`), since `persist` dates only the stories in its window
DATES_KEY = "story_dates_rule"


def dates_stamp() -> str:
    """The dating rule's stamp: what `_start` makes of stamps.story_dates() (changes with the rule's output only)."""
    from insight_core.utils import stamps
    made = []
    for case in stamps.story_dates():
        posts = {pid: Post(pid, pid, kind, at, 0) for pid, kind, at in case}
        made.append(_start(list(posts), posts))
    return stamps.fingerprint(made)


def redate(cur: Any) -> Dict[str, int]:
    """Every current Mark X story's first_at by the current rule: an UPDATE only where the date moves. Idempotent."""
    from insight_core.utils.post_links import source_kind
    cur.execute(f"""SELECT sp.story_id::text, sp.post_id::text, s.platform, s.handle_or_url, {pairing.ordinary_date('p')},
                           st.first_at
                      FROM mx_story_posts sp JOIN mx_stories st ON st.id = sp.story_id AND st.merged_into IS NULL
                      JOIN posts p ON p.id = sp.post_id JOIN sources s ON s.id = p.source_id
                     WHERE sp.valid_to IS NULL""")
    members: Dict[str, Dict[str, Post]] = defaultdict(dict)
    stored: Dict[str, Any] = {}
    for sid, pid, platform, handle, at, first_at in cur.fetchall():
        if at is not None:
            members[sid][pid] = Post(pid, pid, source_kind(platform, handle), at, 0)
        stored[sid] = first_at
    moved = 0
    for sid, posts in sorted(members.items()):
        first = _start(list(posts), posts)
        if first is not None and stored.get(sid) != first:
            cur.execute("UPDATE mx_stories SET first_at = %s WHERE id = %s", (first, sid))
            moved += 1
    return {"stories": len(stored), "moved": moved}


def redate_due(cur: Any) -> Optional[Dict[str, int]]:
    """`redate` once the dating rule's stamp is not the one kept (then kept); None when it is."""
    from insight_core.markx import repo
    stamp = dates_stamp()
    if repo.get_setting(cur, DATES_KEY) == stamp:
        return None
    got = redate(cur)
    repo.set_setting(cur, DATES_KEY, stamp)
    return got


def persist(cur: Any, run_id: Any, out: Outcome, world: World, now: datetime,
            write: bool = True) -> Tuple[Dict[str, str], Counter]:
    """Match each final story to the Mark X story holding most of its members (one each), open what is new and
    close what changed (valid_to; nothing is deleted). Returns {final key: Mark X story id} and the counts. With
    `write` False, only the match: a new story is "new:<key>", nothing is written."""
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
            first = _start(want[key], world.posts)
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
        first = _start(want[key], world.posts)
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
    the ones no longer found close (valid_to). One found again over other shown members is closed and opened anew."""
    from insight_core.markx import repo
    counts: Counter = Counter()
    want = {(c["a_kind"], c["a"], c["b_kind"], c["b"], c["relation"]): c for c in wanted_rows}
    # the graph's post-post edges and story chains are markx/graph.py's, never closed here
    cur.execute("""SELECT a_kind, a::text, b_kind, b::text, relation, p, call_id::text, rule, evidence->'shown'
                     FROM mx_connections
                    WHERE valid_to IS NULL AND (a = ANY(%(s)s::uuid[]) OR b = ANY(%(s)s::uuid[]))
                      AND NOT (a_kind = 'post' AND b_kind = 'post')
                      AND rule IS DISTINCT FROM 'chain_stops'""", {"s": sorted(scope)})
    have = {tuple(r[:5]): r for r in cur.fetchall()}

    def same(c: Dict[str, Any], r: Tuple) -> bool:
        return (_p(c.get("p")) == _p(r[5]) and (c.get("call") or None) == (r[6] or None)
                and (c.get("shown") or None) == (r[8] or None))
    for k, r in have.items():
        if k not in want or not same(want[k], r):
            repo.close_connection(cur, a_kind=k[0], a=k[1], b_kind=k[2], b=k[3], relation=k[4], at=now)
            counts["closed"] += 1
    for k, c in want.items():
        if k not in have or not same(c, have[k]):
            repo.open_connection(cur, a_kind=k[0], a=k[1], b_kind=k[2], b=k[3], relation=k[4], run_id=run_id,
                                 p=_p(c.get("p")), call_id=c.get("call"), rule=c.get("rule"),
                                 evidence={"reason": c.get("reason"), "question": c.get("tid"),
                                           **({"shown": c["shown"]} if c.get("shown") else {})}, at=now)
            counts["opened"] += 1
    return counts


# A connect answer's relation as stored (same topic as "related").
CONNECT_RELATIONS = {"development": "development", "reaction": "reaction", "same_event": "same_event",
                     "mention": "related", "digest_item": "related"}


def connections(cur: Any, out: Outcome, ids: Dict[str, str], world: World, ask: Ask, config: Config,
                news_keys: Sequence[str], apart: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Typed connections: the merges' developments, the late posts', and the connect questions' between News
    stories of `connect_voices`+ voices at most `connect_days` apart, centroids at `connect_lo` or more, not merged.
    Asked newest first, so the run's cap on new connect tasks keeps the newest; the rest wait for later runs."""
    from insight_core.markx import incremental, tasks
    rows: List[Dict[str, Any]] = []
    members = members_of(out, ids)

    def sid(key: str) -> Optional[str]:
        return ids.get(out.final.get(key, key))
    for c in out.connections:
        a = sid(c["a"]) if c["a_kind"] == "story" else c["a"]
        b = sid(c["b"]) if c["b_kind"] == "story" else c["b"]
        row = dict(c, a=a, b=b)
        if a and b and a != b and c.get("call") and holds(row, members):
            rows.append(row)
    groups = {k: sorted((p for p in out.about[k] if p in world.posts), key=lambda p: _at_key(world.posts, p))
              for k in news_keys}
    found = pairing.story_pairs(cur, config.connected(), groups, world.posts)
    groups = {k: ps for k, ps in groups.items() if ps and voices(world.posts, ps) >= config.connect_voices}
    first = {k: world.posts[ps[0]].at for k, ps in groups.items()}
    pairs = []
    for (x, y), cos in found.items():
        if ids.get(x) == ids.get(y):
            continue
        x0, y0 = sorted([x, y], key=lambda k: (first[k], k))
        pairs.append((x0, y0, cos))
    pairs.sort(key=lambda t: (-first[t[1]].timestamp(), -first[t[0]].timestamp(), -t[2], t[0], t[1]))
    # pairs whose first posts' vectors are far apart are settled as unconnected (read, never asked)
    far, shadow = set(), set()
    if (config.connect_settle_below is not None or config.connect_shadow_below is not None) and pairs:
        cos = pairing.post_cosines(cur, [(groups[x0][0], groups[y0][0]) for x0, y0, _ in pairs])
        if config.connect_settle_below is not None:
            far = {k for k, c in cos.items() if c < config.connect_settle_below}
        if config.connect_shadow_below is not None:
            shadow = {k for k, c in cos.items() if c < config.connect_shadow_below}
    for x0, y0, _cos in pairs:
        text = incremental.rendered(world.memo, "connect", (*groups[x0], "|", *groups[y0]), lambda: tasks.connect_input(
            tasks._earliest([world.text[p] for p in groups[x0]]), tasks._earliest([world.text[p] for p in groups[y0]])),
            texts=world.text if world.memo is not None else None)
        key = (str(groups[x0][0]), str(groups[y0][0]))
        if key in shadow:
            ask.shadow_settled["connect"] += 1
        v = ask.verdict("connect", text, a=groups[x0][0], b=groups[y0][0], add=key not in far)
        if v is not None and apart is not None and v.relation == "different" and v.p is not None \
                and v.p >= config.tau_refuse:   # kept apart, stored with what the question showed
            apart.append({"a": ids[x0], "b": ids[y0], "p": v.p, "call": v.call, "tid": f"connect:{x0}:{y0}",
                          "reason": v.reason,
                          "shown": {"a": groups[x0][:tasks.CONNECT_MEMBERS], "b": groups[y0][:tasks.CONNECT_MEMBERS]}})
        if v is None or v.relation not in CONNECT_RELATIONS:
            continue
        if v.p < config.tau_connect:
            continue
        rows.append({"a_kind": "story", "a": ids[x0], "b_kind": "story", "b": ids[y0],
                     "relation": CONNECT_RELATIONS[v.relation], "p": v.p, "call": v.call, "reason": v.reason,
                     "tid": f"connect:{x0}:{y0}",
                     "shown": {"a": groups[x0][:tasks.CONNECT_MEMBERS], "b": groups[y0][:tasks.CONNECT_MEMBERS]}})
    return rows


def refusals(out: Outcome, ids: Dict[str, str], apart: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The run's refused verdicts between two stored stories: its merges answered "different" and its connect
    answers `apart`, while the members each question showed are still those stories' (else stale); two keys that
    ended in one story refuse nothing. One row a pair (a < b), the highest p."""
    members = members_of(out, ids)
    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    rows = [dict(r, a=ids.get(out.final.get(r["a"], r["a"])), b=ids.get(out.final.get(r["b"], r["b"])))
            for r in out.refusals] + [dict(r) for r in apart]
    for r in rows:
        a, b = r.get("a"), r.get("b")
        if not a or not b or a == b:
            continue
        shown = r.get("shown") or {}
        if not all(set(shown.get(end) or []) <= members.get(r[end], set()) for end in ("a", "b")):
            continue
        if a > b:
            a, b, shown = b, a, {"a": shown.get("b"), "b": shown.get("a")}
        row = dict(r, a=a, b=b, shown=shown)
        if (a, b) not in best or (row["p"], row["tid"]) > (best[(a, b)]["p"], best[(a, b)]["tid"]):
            best[(a, b)] = row
    return [best[k] for k in sorted(best)]


def persist_refusals(cur: Any, run_id: Any, rows: Sequence[Dict[str, Any]], scope: Set[str], now: datetime) -> Counter:
    """The run's refusals become the current ones touching its stories (`scope`): new ones open, the ones no longer
    found (or found with another p, call or shown members) close. Never deleted."""
    import json as _json
    counts: Counter = Counter()
    want = {(r["a"], r["b"]): r for r in rows}
    cur.execute("""SELECT a::text, b::text, p, call_id::text, shown FROM mx_refusals
                    WHERE valid_to IS NULL AND (a = ANY(%(s)s::uuid[]) OR b = ANY(%(s)s::uuid[]))""",
                {"s": sorted(scope)})
    have = {(a, b): (p, call, shown) for a, b, p, call, shown in cur.fetchall()}

    def same(r: Dict[str, Any], h: Tuple) -> bool:
        return (_p(r.get("p")) == _p(h[0]) and (r.get("call") or None) == (h[1] or None)
                and (r.get("shown") or None) == (h[2] or None))
    for k, h in have.items():
        if k not in want or not same(want[k], h):
            cur.execute("UPDATE mx_refusals SET valid_to = %s WHERE a = %s AND b = %s AND valid_to IS NULL",
                        (now, k[0], k[1]))
            counts["closed"] += 1
    for k, r in want.items():
        if k not in have or not same(r, have[k]):
            cur.execute("""INSERT INTO mx_refusals (a, b, relation, p, call_id, question, shown, reason, valid_from, run_id)
                           VALUES (%s, %s, 'different', %s, %s, %s, %s::jsonb, %s, %s, %s)
                           ON CONFLICT (a, b, relation) WHERE valid_to IS NULL DO NOTHING""",
                        (k[0], k[1], _p(r.get("p")), r.get("call"), r.get("tid"), _json.dumps(r.get("shown") or {}),
                         r.get("reason"), now, run_id))
            counts["opened"] += 1
    return counts


def members_of(out: Outcome, ids: Dict[str, str]) -> Dict[str, Set[str]]:
    """{Mark X story id: its member posts in this run} (the run's stories, by the ids persist gave them)."""
    got: Dict[str, Set[str]] = defaultdict(set)
    for key, ms in out.about.items():
        if key in ids:
            got[ids[key]] |= set(ms)
    return dict(got)


def holds(c: Dict[str, Any], members: Dict[str, Set[str]]) -> bool:
    """A connection holds while the members its question showed are still members of the stories it joins; one with
    no record of what it showed holds."""
    for end in ("a", "b"):
        shown = (c.get("shown") or {}).get(end)
        if c.get(f"{end}_kind") == "story" and shown and not set(shown) <= members.get(c[end], set()):
            return False
    return True


def headlines(cur: Any, out: Outcome, ids: Dict[str, str], world: World, ask: Ask, news_keys: Sequence[str]) -> int:
    """Haiku's headline for every News story, from its core members (tasks.headline_members): asked again when the
    core changes, stored when answered."""
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
        # kept by every member's stamp: a run where no member changed reads no text
        text = incremental.rendered(world.memo, "headline", ps,
                                    lambda: tasks.headline_input([world.text[p] for p in ps]),
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
    """A run's reading of its snapshot through `memo` (incremental.refresh, then load and think): (world, ask,
    outcome, counts). `dry`: nothing is added or asked again."""
    from insight_core.markx import incremental
    incremental.refresh(cur, memo)
    world = load(cur, now, config, memo=memo)
    cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'connect' AND status IN ('open', 'leased')")
    waiting = cur.fetchone()[0]
    from insight_core.markx import story_window
    back = config.days > story_window.RECENT       # the window reaches back: old questions come in pages
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
        began: Optional[float] = None, skip: Iterable[str] = (),
        on_kind: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """One decision run on the caller's transaction (`snapshot()`); skipped when another holds the lock. Writes mx_*
    rows only. `stage(name)` is called as each stage begins; one that raises stops the run and the caller's transaction
    rolls back (nothing half done, the state too).

    A run is incremental (markx/incremental.py: it reads again only what changed since the last run) unless `full`,
    no state of the last finished run, a changed code/config/guide, or no full run since NIGHTLY_HOUR. A full run with
    a state first reads the snapshot incrementally, writing nothing, and logs any difference (`counts.check`). Every
    run saves its state in the same transaction.

    `entity_budget`: the entities stage's own seconds (its full pass resumes next run). `limit`, `began`: the caller's
    LIMIT and start (time.monotonic), for whether the story window may step back. `skip`: stages of jobs.SKIPPABLE
    deferred this run. `on_kind(kind)`: called with "full" | "incremental" before the reading."""
    import json as _json
    import time as _time
    from insight_core.markx import incremental, news as mx_news, repo, schemas
    timed: List[Tuple[str, float]] = []
    skip = frozenset(skip)

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
    recent_days = min(config.days, story_window.RECENT)   # surges keep the News window, never the backfill's
    if config.story_window:
        config = replace(config, days=story_window.days_for_run(cur, now))
    mark("load")
    schemas.ensure_guides(cur)
    guides = {k.name: k.guide for k in schemas.KINDS.values()}
    key = _json.dumps([CODE_VERSION, incremental.reading_stamp(), incremental.accounts_stamp(cur), config.as_dict(),
                       guides], sort_keys=True, default=str)
    memo, warm = incremental.open_state(cur, key)
    why_full = memo.why_full
    nightly = warm and full is None and incremental.nightly_due(cur, now)
    kind = "full" if (full or not warm or nightly) else "incremental"
    if on_kind is not None:
        on_kind(kind)
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
    previous = cur.fetchone()[0]
    run_id = repo.start_run(cur, code_version=CODE_VERSION, config={**config.as_dict(), "guides": guides})
    mark("questions and decisions")
    world, ask, out, counts = _reading(cur, memo, now, config)
    world.candidates = []   # the first pass's input only, let go (~450k pairs at the server's size)
    counts["tasks_reasked"] = ask.reopen()
    mark("write")
    ids, written = persist(cur, run_id, out, world, now)
    redated = redate_due(cur)      # a new dating rule re-dates the stories stored before it, once
    if redated is not None:
        counts["redated"] = redated
    news_keys = [s["story"] for s in out.stories(world.posts) if voices(world.posts, s["posts"]) >= 2]
    mark("connections")
    apart: List[Dict[str, Any]] = []
    conns = connections(cur, out, ids, world, ask, config, news_keys, apart=apart)
    counts["connections"] = dict(persist_connections(cur, run_id, conns, set(ids.values()) | set(world.posts), now))
    counts["refusals"] = dict(persist_refusals(cur, run_id, refusals(out, ids, apart), set(ids.values()), now))
    deferred: Dict[str, str] = {}

    def guarded(name: str, fn: Callable[[], Any], default: Any = None) -> Any:
        """A stage after the run's own decisions, in a savepoint: a serialization failure or deadlock (a row another
        transaction changed since the snapshot) undoes only that stage's writes and defers it to the next run."""
        if timed and timed[-1][0] in skip:
            deferred[name] = "skipped this run: two runs in a row went over the time limit in this stage"
            log.warning("Mark X decision run: the %s stage is skipped this run (deferred to the next)", name)
            return default
        added, old_added = Counter(ask.added), Counter(ask.old_added)
        try:
            with cur.connection.transaction():
                return fn()
        except (psycopg_errors.SerializationFailure, psycopg_errors.DeadlockDetected) as exc:
            ask.added, ask.old_added = added, old_added
            deferred[name] = str(exc).strip().splitlines()[0][:200]
            log.warning("Mark X decision run: the %s stage met a concurrent update and is deferred to the next run: %s",
                        name, deferred[name])
            return default
    mark("back")
    from insight_core.markx import back
    from insight_core.markx import consumers
    counts["back"] = (guarded("back", lambda: back.stage(cur, now=now, run_id=run_id, open_cap=config.back_open))
                      if consumers.wanted(cur, back.KIND) else {"off": consumers.NOT_ASKED})
    mark("headlines")
    counts["headlines_changed"] = headlines(cur, out, ids, world, ask, news_keys)
    mark("news")
    counts["news"] = mx_news.write(cur, run_id, out=out, ids=ids, world=world, now=now, ask=ask,
                                   headed={ids[k] for k in news_keys})
    from insight_core.markx import news_sections
    counts["news_titles"] = guarded("news_titles", lambda: news_sections.title_rows(cur, now=now))
    from insight_core.markx import significance
    counts["news_significance"] = guarded("news_significance", lambda: significance.plan(cur, now=now))
    if check is not None:
        diff = incremental.differences(check, _digest(out, ids, world, conns, memo.news["rows"] if memo.news else []))
        counts["check"] = {"same": not diff, **({"differences": diff} if diff else {})}
        if diff:
            log.warning("Mark X incremental-run bug: a full run reads this snapshot otherwise: %s", diff)
    incremental.release(memo)
    # what the run's end needs of the reading, taken now; the reading itself is let go before the entity stages
    want = wanted(out, world.posts)
    closure = (incremental.closure(memo, want, world.stories) if kind == "incremental" else
               {"closure": len(want), "stories": len(want)})
    read = {"stories": len(ids), "window_since": world.since.isoformat(), "posts": len(world.posts)}
    del world, out, conns, ids, news_keys
    mark("entities")
    from insight_core.markx import entity_stage
    got = guarded("entities", lambda: entity_stage.entities(cur, ask=ask, now=now, run_id=run_id, since=previous,
                                                             full=full, budget=entity_budget))
    days = set()                        # deferred: it linked nothing, no day to recount; and no "entities" counts,
    linked: List[str] = []              # so the next run resumes a full pass from the last finished run's record
    if got is not None:
        counts["entities"], days = got
        linked = counts["entities"].pop("posts_linked", [])
    # the graph after the entities stage, so a new post's edges are made in the run that links its mentions; a graph
    # stage that does not run keeps them for the next one (graph.defer)
    mark("graph")
    from insight_core.markx import graph
    counts["graph"] = guarded("graph", lambda: graph.stage(cur, now=now, run_id=run_id, open_cap=config.relate_open,
                                                           linked=linked))
    if counts["graph"] is None:
        graph.defer(cur, linked)
    del linked
    mark("surges")
    counts["surges"] = guarded("surges", lambda: entity_stage.surges(cur, now=now, run_id=run_id, days=days,
                                                                      since=previous, window_days=recent_days))
    mark("perspectives_plan")
    from insight_core.markx import perspectives
    counts["perspectives"] = (guarded("perspectives", lambda: perspectives.stage(cur, ask=ask, now=now, run_id=run_id))
                              if consumers.wanted(cur, "perspective") or consumers.wanted(cur, "sheet")
                              else {"off": consumers.NOT_ASKED})
    counts["briefing"] = guarded("briefing", lambda: mx_news.briefing(cur, ask=ask, now=now, hour=BRIEFING_HOUR,
                                                                      limit=BRIEFING_STORIES))
    if deferred:
        counts["deferred"] = deferred
    if config.story_window and story_window.backfilling(cur):
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
    counts["run"] = {"kind": kind, "now": now.isoformat(), **({"nightly": True} if nightly else {}),
                     **({"why_full": why_full} if why_full else {}), **({"forced": True} if full else {}),
                     "dirty_tasks": memo.report.get("dirty_tasks", 0) if kind == "incremental" else None,
                     "dirty_posts": len(memo.report.get("dirty_posts") or ()) if kind == "incremental" else None,
                     "texts_read": memo.report.get("texts_read"), "ix_changed": memo.report.get("ix_changed"),
                     **{k: memo.report.get(k) for k in ("texts_loaded", "inputs_rendered", "inputs_kept")},
                     **closure}
    counts["run"]["state"] = incremental.save(cur, memo, run_id, want)
    counts["run"]["seconds"] = round(_time.monotonic() - started, 3)
    counts.update({"stories": read["stories"], "memberships": dict(written), "tasks_added": dict(ask.added),
                   "tasks_waiting": dict(ask.waiting), "tasks_raced": dict(ask.raced), "answers_read": dict(ask.answered),
                   "tasks_settled": dict(ask.settled),
                   "tasks_shadow_settled": dict(ask.shadow_settled),
                   "tasks_requoted": dict(ask.reasked),
                   "isolation": isolation,
                   "window_since": read["window_since"], "posts": read["posts"]})
    repo.finish_run(cur, run_id, counts=counts)
    return {"run": str(run_id), **counts}


# ---- when it runs -----------------------------------------------------------------------------------

@contextlib.contextmanager
def snapshot(url: Optional[str] = None):
    """A REPEATABLE READ transaction for one decision run: every read sees one snapshot, so a story-job commit
    mid-run is never half seen. The run's own rows are written under its advisory lock; its task inserts and reopens
    race the worker and are taken in savepoints, as is every stage after the decisions (`run`'s `guarded`)."""
    from insight_core.db import database
    if url is None:
        from insight_core.services.registry import services
        url = services().db_url
    with database.transaction(url) as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        yield cur

