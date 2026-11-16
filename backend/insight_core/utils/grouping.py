"""Which stories are one News row (issue 0217, Stealth v10.23): one deep module, pure functions, no database.

`group(items, edges, policy) -> Grouping` partitions items (Mark X stories, and posts of no story as one-post items)
into groups (News rows). Every join is tested against each group's **core**, never through one member, so a row's
reach is not the transitive closure of its members' weakest links (0203's runaway: a digest said a CEO's name).

**The core** of an item is computed from its own lead posts only (`Policy.k_lead` earliest reports; a reply, a quote
or a round-up never leads), so one late post or a digest cannot change what it is about:
  - its **thing**: the exact thing its lead posts are about (a subject said by at least `core_share` of them, or by
    the first), the most specific one (a variant over its bare version: "qwen4 max" over "qwen4");
  - its **names**: the surging names that are its core names (the caller's, `news_rules.core_names`);
  - its **event**: the closed event type most of its lead posts have (`schemas.EVENT_TYPES`);
  - its **time**: its first post.
A group's core is its **anchor**'s: the item with the most voices, then posts, then the earliest (a row's main
story, 0121).

**Edges** (`Edge.source`), and what admits each:
  - `judge` (Mark X's story verdicts): `same_event` at p builds with weight `w_same * logit(p)`; `development` /
    `follows_up` weigh 0 (they stay typed connections); `different` at `tau_diff`+ is a hard **cannot-link**, below
    it a negative weight. A verdict counts only while the posts it was shown are still in its two items (`shown`;
    0205's stale connections).
  - `name` (a surging name both items' posts say): admitted only when the name says one of each side's core names.
  - `rule` (a post in two stories, a thread, a quote): an **attachment**, never a bridge between two groups.
  - `core` (made here, not passed): two items about the same exact thing (a versioned model or product), both of
    the release family (rumour, teaser, preview, launch, availability, benchmark, breakdown: every event type but a
    deal, a legal or policy matter, an incident or a statement; at least one of them a release or a leak) within
    `span_days`: the owner's "everything about one release of one exact thing is ONE row" (0217, 2026-11-16).
    A bare version ("qwen4") joins a variant ("qwen4 max") only when one variant of it is in reach.

**Admission between groups** (`Policy.admit`): an edge between items x in G and y in H holds only when each end
holds against its group's core (it is the anchor, it has the anchor's thing, or the edge's name says the anchor's
core name), and no **conflict** separates the two groups: no cannot-link, no two different exact things, no two
event types that cannot be one happening (a release and a resignation). The conflict test is over every pair of
items (complete link), so a chain cannot carry a row where its anchor would refuse.

**Algorithms** (`Policy.algo`): `uf` (the candidate edges in one canonical order, each join if admitted and above
`theta`), `agg` (average-linkage agglomeration: merge the pair of groups whose mean admitted weight over item pairs
is highest, while above `theta`) and `cc` (correlation clustering: pivots in a canonical order, then single-item
moves that raise the within-group weight). All three are **order-independent** (inputs are canonicalised first and
every tie breaks on ids) and deterministic.

`Grouping.rejected` lists every passed or made edge that joined nothing, with why: `bridge` (an attachment),
`stale`, `name` (says no core name), `core` (an end holds not against its group's core), `conflict`, `cannot`,
`weak` (below theta or not enough on average), `same` (already one group): "why isn't X in this row" is a lookup.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

# ---- the facts --------------------------------------------------------------------------------------------------

RELEASES = frozenset({"model_release", "product_release"})
CONNECTED = ("development", "follows_up", "same_event")   # the judge's verdicts that connect two stories
LEAK = "leak_rumour"
# Types that are their own happening: two items of two of these (or one of these and a release) are never one row.
OWN_HAPPENINGS = frozenset({"model_release", "product_release", "business_event", "policy_legal", "incident",
                            "public_statement", "research_result"})
# Two kinds of happening one row may hold: a release and its results (a benchmark, an evaluation, a paper on it).
KIN = frozenset({frozenset({"model_release", "product_release"}), frozenset({"model_release", "research_result"}),
                 frozenset({"product_release", "research_result"})})
# The release family: what can be a line of one release's row (a stage, availability, a benchmark, a breakdown). A
# round-up is none: it lists the release among others.
NOT_RELEASE_FAMILY = frozenset({"business_event", "policy_legal", "incident", "public_statement", "digest"})


_WORD = re.compile(r"[^\W_]+(?:[.][^\W_]+)*", re.UNICODE)
# Words of a release's stage, never of the thing's name: a preview of Max is Max.
_STAGES = frozenset({"preview", "beta", "alpha", "exp", "experimental", "early", "access", "rc", "candidate",
                     "release", "ga", "launch", "teaser"})


def _norm(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\-_./]+", "", s)


@dataclass(frozen=True, order=True)
class Thing:
    """An exact thing: a model or product with its version (`name`, e.g. "qwen4"), and its variant ("max") or ""."""
    name: str
    variant: str = ""

    @staticmethod
    def of(*, name: Optional[str] = None, family: Optional[str] = None, version: Optional[str] = None,
           variant: Optional[str] = None) -> Optional["Thing"]:
        """The thing an entity reading says, or None when it names no version (a bare product or company is no exact
        thing: "Claude Code" twice in a week is two stories). The name is the family's last word and the version
        ("Claude Fable 5.2", "Anthropic Fable 5.2" and "Fable 5.2" are one; "V4.1" and "4.1" are one); a stage
        word is no variant ("Max-Preview" is "Max": a preview is a stage of the release, 0217)."""
        v = _norm(version)
        v = v[1:] if len(v) > 1 and v[0] == "v" and v[1].isdigit() else v
        if not v:
            return None
        words = _WORD.findall(unicodedata.normalize("NFKC", family or ""))
        if not words:
            raw = unicodedata.normalize("NFKC", name or "")
            i = raw.lower().find((version or "").lower()) if version else -1
            words = _WORD.findall(raw[:i]) if i > 0 else []
        fam = _norm(words[-1]) if words else ""
        if not fam:
            return None
        nm = v if v.startswith(fam) else fam + v
        var = "".join(w for w in (_norm(x) for x in _WORD.findall(unicodedata.normalize("NFKC", variant or "")))
                      if w not in _STAGES and w not in nm)
        return Thing(nm, var)

    def fits(self, other: "Thing") -> bool:
        return self.name == other.name and (not self.variant or not other.variant or self.variant == other.variant)


@dataclass(frozen=True)
class Post:
    id: str
    at: datetime
    things: Tuple[Thing, ...] = ()     # the exact things it has as a subject (not a mention)
    event: Optional[str] = None        # its closed event type, None: no reading
    report: bool = True                # False: a reply, a quote, a share or a round-up (never a lead)


@dataclass(frozen=True)
class Item:
    id: str
    posts: Tuple[Post, ...]
    voices: int = 0
    names: FrozenSet[str] = frozenset()    # its core surging names (news_rules.core_names)
    event: Optional[str] = None            # its kind of happening when the caller knows it (Mark X: the story's type
                                           # by the event-type seam); None: its lead posts' most common type
    main: Optional[str] = None             # its main surging name (news_rules.main_name)


@dataclass(frozen=True)
class Edge:
    a: str
    b: str
    source: str                      # judge | name | rule | core
    relation: Optional[str] = None   # judge: same_event | development | follows_up | different
    p: Optional[float] = None
    name: Optional[str] = None       # name: the surging name
    shown: FrozenSet[str] = frozenset()   # judge: the posts its question showed (empty: not known, holds)

    def key(self) -> Tuple:
        return (self.source, self.relation or "", self.name or "", -(self.p or 0.0), self.a, self.b)


@dataclass(frozen=True)
class Policy:
    algo: str = "uf"                 # uf | agg | cc
    admit: bool = True               # the core check (False: C, edges as given)
    release: bool = True             # make the `core` edges (one release, one row)
    theta: float = 0.0               # a join needs more than this (uf: the edge's weight; agg: the mean)
    tau_diff: Optional[float] = 0.75  # a `different` at this p or more is a cannot-link; None: off
    k_lead: int = 3
    core_share: float = 0.5
    span_days: float = 7.0
    w_same: float = 1.0
    w_diff: float = 1.0
    w_name: float = 1.0
    w_core: float = 2.0
    tau_same: float = 0.5            # a same_event below this p builds nothing
    w_dev: float = 0.0               # a development / follow-up between two cores of one kind of happening (a stage
                                     # of one IPO, one lawsuit): its weight; 0, a typed connection only (the spec's)
    ls_rounds: int = 2               # cc: rounds of single-item moves
    large_posts: int = 5             # two items this large join by a name only by both main names (and the judge)
    line_days: Optional[float] = None   # a release line that is no stage joins a stage only this near; None: span_days


@dataclass(frozen=True)
class Evidence:
    """What a caller hands News besides its stories and names (news_rules.news' `grouped`): each post's facts, each
    story's kind of happening, the judge's story verdicts and the policy. Mark IX: no verdicts."""
    posts: Mapping[str, Post]
    stories: Mapping[str, Optional[str]] = field(default_factory=dict)
    judged: Sequence[Edge] = ()
    policy: Policy = field(default_factory=Policy)


@dataclass(frozen=True)
class Core:
    thing: Optional[Thing]
    names: FrozenSet[str]
    event: Optional[str]
    at: datetime
    lead: Tuple[str, ...]


@dataclass
class Group:
    id: str                          # its anchor item
    members: List[str]               # items, first first
    core: Core
    lines: List[Tuple[str, Optional[str]]] = field(default_factory=list)   # (item, its event type), first first


@dataclass
class Grouping:
    groups: List[Group]
    rejected: List[Tuple[Edge, str]]
    group_of: Dict[str, str]


# ---- the core ---------------------------------------------------------------------------------------------------

def core_of(item: Item, policy: Policy = Policy()) -> Core:
    posts = sorted(item.posts, key=lambda p: (p.at, p.id))
    if not posts:
        return Core(None, item.names, None, datetime.min, ())
    reports = [p for p in posts if p.report]
    leads = reports[:policy.k_lead] or posts[:1]
    said: Dict[Thing, int] = defaultdict(int)
    for p in (leads if reports else ()):   # replies and round-ups alone are about no exact thing
        for t in set(p.things):
            said[t] += 1
    first = set(leads[0].things) if reports else set()
    held = [t for t, n in said.items() if t in first or n >= policy.core_share * len(leads)]
    # the most specific: a variant over its bare version, then the most said, then the name
    held = [t for t in held if not (not t.variant and any(o.name == t.name and o.variant for o in held))]
    thing = max(held, key=lambda t: (said[t], t in first, t.variant, t.name), default=None) if held else None
    types: Dict[str, int] = defaultdict(int)
    for p in leads:
        if p.event:
            types[p.event] += 1
    order = {p.event: n for n, p in reversed(list(enumerate(leads))) if p.event}
    event = item.event or (max(types, key=lambda t: (types[t], -order[t])) if types else None)
    return Core(thing, item.names, event, posts[0].at, tuple(p.id for p in leads))


def _conflict(a: Core, b: Core) -> bool:
    """Two cores that cannot be one row: two different exact things, two happenings of different kinds, or two
    releases that are not of one thing (one of an exact thing, the other of none; a bare version's release and its
    variant's: "Orbit 4" and "Orbit 4 Flash" are two models)."""
    if a.thing and b.thing and not a.thing.fits(b.thing):
        return True
    if a.event in RELEASES and b.event in RELEASES:
        if bool(a.thing) != bool(b.thing):
            return True
        if a.thing and b.thing and a.thing.variant != b.thing.variant:
            return True
    if a.event in OWN_HAPPENINGS and b.event in OWN_HAPPENINGS and a.event != b.event \
            and frozenset({a.event, b.event}) not in KIN:
        return True
    return False


def _release_pair(a: Core, b: Core, policy: Policy) -> bool:
    if not (a.thing and b.thing and a.thing.fits(b.thing)):
        return False
    if a.event in NOT_RELEASE_FAMILY or b.event in NOT_RELEASE_FAMILY:
        return False
    if not ({a.event, b.event} & (RELEASES | {LEAK})):
        return False
    if _conflict(a, b):
        return False
    apart = abs((a.at - b.at).total_seconds())
    if policy.line_days is not None and not (a.event in RELEASES | {LEAK} and b.event in RELEASES | {LEAK}):
        # a line that is no stage (a benchmark, a breakdown) joins a stage only near it: research weeks after a launch
        # is its own story (0217's held-out breakage)
        return apart <= policy.line_days * 86400
    return apart <= policy.span_days * 86400


def releases(items: Sequence[Item], policy: Policy) -> List[Tuple[str, str]]:
    """The owner's release rule alone (0217's narrow arm): the pairs of items about one release of one exact thing,
    as `group` makes its `core` edges (order-independent: the pairs sorted)."""
    by_id = {i.id: i for i in items}
    ids = sorted(by_id)
    cores = {i: core_of(by_id[i], policy) for i in ids}
    return sorted((e.a, e.b) for e in _release_edges(ids, cores, policy))


# The setting chosen on the dev window (0217: 2026-11-07..12, labelled pairs; average linkage over admitted edges,
# a mean weight above 1, a release's stages within 14 days, one release's edges weighing 3). Mark X's News reads it.
CHOSEN = Policy(algo="agg", theta=1.0, span_days=14.0, w_core=3.0)


def _says(name: str, names: Iterable[str]) -> bool:
    return any(f" {c} " in f" {name} " for c in names)


def _logit(p: float) -> float:
    p = min(max(p, 1e-3), 1 - 1e-3)
    return math.log(p / (1 - p))


# ---- the grouping -----------------------------------------------------------------------------------------------

def group(items: Sequence[Item], edges: Sequence[Edge], *, policy: Policy = Policy()) -> Grouping:
    """The partition of `items` (every item in exactly one group), each group's core and lines, and the edges that
    joined nothing with why. Order-independent: the same items and edges in any order give the same groups."""
    by_id: Dict[str, Item] = {}
    for it in sorted(items, key=lambda i: i.id):
        by_id.setdefault(it.id, it)
    ids = sorted(by_id)
    cores = {i: core_of(by_id[i], policy) for i in ids}
    posts_of = {i: {p.id for p in by_id[i].posts} for i in ids}
    rejected: List[Tuple[Edge, str]] = []

    # canonical edges: each pair once per (source, relation, name), the highest p; a < b
    canon: Dict[Tuple, Edge] = {}
    for e in edges:
        if e.a == e.b or e.a not in by_id or e.b not in by_id:
            continue
        a, b = sorted((e.a, e.b))
        e = replace(e, a=a, b=b)
        k = (a, b, e.source, e.relation or "", e.name or "")
        if k not in canon or (e.p or 0) > (canon[k].p or 0) or ((e.p or 0) == (canon[k].p or 0) and e.key() < canon[k].key()):
            canon[k] = e
    given = [canon[k] for k in sorted(canon)]
    if policy.release:
        given += _release_edges(ids, cores, policy)

    weights: Dict[Tuple[str, str], float] = defaultdict(float)
    via: Dict[Tuple[str, str], List[Edge]] = defaultdict(list)
    cannot: Set[Tuple[str, str]] = set()
    judged = any(e.source == "judge" for e in given)
    connected = {(e.a, e.b) for e in given if e.source == "judge" and e.relation in CONNECTED
                 and not (e.shown and not e.shown <= (posts_of[e.a] | posts_of[e.b]))} if judged else None
    for e in given:
        pair = (e.a, e.b)
        if e.source == "rule":
            rejected.append((e, "bridge"))
            continue
        if e.source == "judge" and e.shown and not e.shown <= (posts_of[e.a] | posts_of[e.b]):
            rejected.append((e, "stale"))
            continue
        if e.source == "judge" and e.relation == "different":
            if policy.tau_diff is not None and (e.p or 0) >= policy.tau_diff:
                cannot.add(pair)
            elif e.p is not None:
                weights[pair] -= policy.w_diff * _logit(e.p)
            rejected.append((e, "cannot"))
            continue
        w = _weight(e, policy)
        if e.source == "judge" and e.relation in ("development", "follows_up") and policy.w_dev \
                and cores[e.a].event in OWN_HAPPENINGS and cores[e.a].event == cores[e.b].event:
            w = policy.w_dev * _logit(e.p if e.p is not None else 0.0)
        if w <= 0:
            rejected.append((e, "weak"))
            continue
        if e.source == "name" and not _name_holds(e, by_id, cores, connected, policy):
            rejected.append((e, "name"))
            continue
        if policy.admit and _conflict(cores[e.a], cores[e.b]):
            rejected.append((e, "conflict"))
            continue
        weights[pair] += w
        via[pair].append(e)

    state = _State(ids, by_id, cores, cannot, policy)
    if policy.algo == "uf":
        _uf(state, via, weights, rejected)
    elif policy.algo == "agg":
        _agg(state, via, weights, rejected)
    elif policy.algo == "cc":
        _cc(state, via, weights, rejected)
    else:
        raise ValueError(f"grouping: no algorithm {policy.algo!r}")
    return state.result(rejected)


def _name_holds(e: Edge, by_id: Mapping[str, Item], cores: Mapping[str, Core],
                connected: Optional[Set[Tuple[str, str]]], policy: Policy) -> bool:
    """A surging name joins two items only when it says a core name of each (0203's core names); two large items
    (`large_posts`+ posts each) only by each one's main name and, with a judge, only when the judge connected them
    (0203's large-story rule, which every arm keeps)."""
    name = e.name or ""
    if not (_says(name, cores[e.a].names) and _says(name, cores[e.b].names)):
        return False
    a, b = by_id[e.a], by_id[e.b]
    if len(a.posts) >= policy.large_posts and len(b.posts) >= policy.large_posts:
        if not (a.main and b.main and _says(name, [a.main]) and _says(name, [b.main])):
            return False
        if connected is not None and (e.a, e.b) not in connected:
            return False
    return True


def _weight(e: Edge, policy: Policy) -> float:
    if e.source == "core":
        return policy.w_core
    if e.source == "name":
        return policy.w_name
    if e.source == "judge" and e.relation == "same_event":
        p = e.p if e.p is not None else 0.0
        return policy.w_same * _logit(p) if p >= policy.tau_same else 0.0
    return 0.0


def _release_edges(ids: Sequence[str], cores: Mapping[str, Core], policy: Policy) -> List[Edge]:
    """The `core` edges: items about one exact thing of the release family within span_days. Blocked by the thing's
    name, so the work is the items about one thing, never all pairs. A bare version joins a variant only when its
    span reaches one variant of the name."""
    by_name: Dict[str, List[str]] = defaultdict(list)
    for i in ids:
        if cores[i].thing:
            by_name[cores[i].thing.name].append(i)
    out: List[Edge] = []
    for name in sorted(by_name):
        xs = sorted(by_name[name], key=lambda i: (cores[i].at, i))
        for n, a in enumerate(xs):
            for b in xs[n + 1:]:
                if not _release_pair(cores[a], cores[b], policy):
                    continue
                ta, tb = cores[a].thing, cores[b].thing
                if (not ta.variant) != (not tb.variant):
                    bare = a if not ta.variant else b
                    variants = {cores[o].thing.variant for o in xs if o != bare and cores[o].thing.variant
                                and _release_pair(cores[bare], cores[o], policy)}
                    if len(variants) != 1:
                        continue
                out.append(Edge(*sorted((a, b)), source="core"))
    return out


class _State:
    """The groups as they are merged: members, the anchor (core), and the complete-link conflict test."""

    def __init__(self, ids, by_id, cores, cannot, policy):
        self.by_id, self.cores, self.cannot, self.policy = by_id, cores, cannot, policy
        self.of: Dict[str, str] = {i: i for i in ids}
        self.members: Dict[str, List[str]] = {i: [i] for i in ids}
        # the items that are the group's own event (joined to its anchor by same-event or one-release edges): an
        # edge at one of them holds against the core; an item joined by a name is a line, never a bridge
        self.own: Dict[str, Set[str]] = {i: {i} for i in ids}

    def anchor(self, g: str) -> str:
        return min(self.members[g], key=lambda i: (-self.by_id[i].voices, -len(self.by_id[i].posts),
                                                   self.cores[i].at, i))

    def blocked(self, g: str, h: str) -> Optional[str]:
        for x in self.members[g]:
            for y in self.members[h]:
                if tuple(sorted((x, y))) in self.cannot:
                    return "cannot"
                if self.policy.admit and _conflict(self.cores[x], self.cores[y]):
                    return "conflict"
        return None

    def holds(self, e: Edge, x: str, g: str) -> bool:
        """An edge's end x holds against its group g's core: x is g's anchor, has the anchor's exact thing, or the
        edge's name says the anchor's core name."""
        if not self.policy.admit or len(self.members[g]) == 1 or x in self.own[g]:
            return True
        a = self.anchor(g)
        ca, cx = self.cores[a], self.cores[x]
        if ca.thing and cx.thing and ca.thing.fits(cx.thing):
            return True
        return e.source == "name" and _says(e.name or "", ca.names)

    def admitted(self, e: Edge) -> bool:
        return self.holds(e, e.a, self.of[e.a]) and self.holds(e, e.b, self.of[e.b])

    def merge(self, g: str, h: str, by: Optional[Edge] = None) -> str:
        """g and h as one group. Joined by the same event (a judged same_event, one release), each side's own items
        stay the group's own; by a name, only the side whose anchor leads keeps its own."""
        same = by is None or by.source != "name"
        keep, drop = sorted((g, h))
        own = self.own.pop(drop) | self.own[keep] if same else None
        if not same:
            ag, ah = self.anchor(g), self.anchor(h)
            lead = min((ag, ah), key=lambda i: (-self.by_id[i].voices, -len(self.by_id[i].posts), self.cores[i].at, i))
            own = self.own[g] if lead == ag else self.own[h]
            self.own.pop(drop)
        for i in self.members[drop]:
            self.of[i] = keep
        self.members[keep] = self.members[keep] + self.members.pop(drop)
        self.own[keep] = set(own)
        return keep

    def result(self, rejected) -> Grouping:
        groups = []
        for g, ms in self.members.items():
            ms = sorted(ms, key=lambda i: (self.cores[i].at, i))
            a = self.anchor(g)
            groups.append(Group(id=a, members=ms, core=self.cores[a],
                                lines=[(i, self.cores[i].event) for i in ms]))
        groups.sort(key=lambda g: (self.cores[g.members[0]].at, g.id))
        group_of = {i: g.id for g in groups for i in g.members}
        return Grouping(groups=groups, rejected=rejected, group_of=group_of)


def _uf(state: _State, via, weights, rejected) -> None:
    """Union over the edges, strongest first, then by ids: each join only when both ends hold against their groups'
    cores and nothing conflicts."""
    order = sorted(via, key=lambda pr: (-weights[pr], pr))
    for pr in order:
        e = min(via[pr], key=lambda e: e.key())
        g, h = state.of[pr[0]], state.of[pr[1]]
        if g == h:
            continue
        if weights[pr] <= state.policy.theta:
            rejected.append((e, "weak"))
            continue
        if not state.admitted(e):
            rejected.append((e, "core"))
            continue
        why = state.blocked(g, h)
        if why:
            rejected.append((e, why))
            continue
        state.merge(g, h, e)


def _agg(state: _State, via, weights, rejected) -> None:
    """Average linkage: the pair of groups with the highest mean admitted weight over their item pairs merges first
    (ties: the smaller first ids), while the mean is above theta and nothing blocks it."""
    refused: Set[Tuple[str, str]] = set()
    while True:
        between: Dict[Tuple[str, str], float] = defaultdict(float)
        by: Dict[Tuple[str, str], Edge] = {}
        for (a, b), es in via.items():
            g, h = state.of[a], state.of[b]
            if g == h:
                continue
            ok = [e for e in es if state.admitted(e)]
            if ok:
                gh = tuple(sorted((g, h)))
                between[gh] += weights[(a, b)]
                e = min(ok, key=lambda e: (e.source == "name", e.key()))
                if gh not in by or (e.source == "name", e.key()) < (by[gh].source == "name", by[gh].key()):
                    by[gh] = e
        for (a, b), w in weights.items():   # the negative weights count in the mean too
            if w < 0:
                g, h = state.of[a], state.of[b]
                if g != h:
                    between[tuple(sorted((g, h)))] += w
        best = None
        for (g, h), s in between.items():
            if (g, h) in refused:
                continue
            mean = s / (len(state.members[g]) * len(state.members[h]))
            if mean <= state.policy.theta:
                continue
            k = (-mean, g, h)
            if best is None or k < best[0]:
                best = (k, g, h)
        if best is None:
            break
        _, g, h = best
        if state.blocked(g, h):
            refused.add((g, h))
            continue
        keep = state.merge(g, h, by[(g, h)])
        refused = {pr for pr in refused if keep not in pr}
    for pr, es in via.items():
        if state.of[pr[0]] != state.of[pr[1]]:
            rejected.append((min(es, key=lambda e: e.key()), "weak"))


def _cc(state: _State, via, weights, rejected) -> None:
    """Correlation clustering: pivots by id, each taking its positive admitted neighbours that nothing blocks; then
    single-item moves that raise the within-group weight, items by id, `ls_rounds` rounds."""
    adj: Dict[str, Dict[str, float]] = defaultdict(dict)
    for (a, b), w in weights.items():
        adj[a][b] = w
        adj[b][a] = w
    ids = sorted(state.of)
    taken: Set[str] = set()
    for pivot in ids:
        if pivot in taken:
            continue
        taken.add(pivot)
        for other in sorted(adj[pivot], key=lambda o: (-adj[pivot][o], o)):
            if other in taken or adj[pivot][other] <= state.policy.theta:
                continue
            g, h = state.of[pivot], state.of[other]
            if state.blocked(g, h):
                continue
            e = min(via[tuple(sorted((pivot, other)))], key=lambda e: (e.source == "name", e.key())) \
                if tuple(sorted((pivot, other))) in via else None
            if e is None or not state.admitted(e):
                continue
            state.merge(g, h, e)
            taken.add(other)
    for _ in range(state.policy.ls_rounds):
        moved = False
        for i in ids:
            here = state.of[i]
            gain_here = sum(w for o, w in adj[i].items() if state.of[o] == here and o != i)
            best = None
            for g in sorted({state.of[o] for o in adj[i]} - {here}):
                gain = sum(w for o, w in adj[i].items() if state.of[o] == g)
                if gain > gain_here + 1e-9 and gain > state.policy.theta and (best is None or gain > best[0]) \
                        and not _blocked_item(state, i, g):
                    best = (gain, g)
            if best:
                state.members[here].remove(i)
                state.own[here].discard(i)
                if not state.members[here]:
                    del state.members[here], state.own[here]
                state.members[best[1]].append(i)
                state.own[best[1]].add(i)
                state.of[i] = best[1]
                moved = True
        if not moved:
            break
    for pr, es in via.items():
        if state.of[pr[0]] != state.of[pr[1]]:
            rejected.append((min(es, key=lambda e: e.key()), "weak"))


def _blocked_item(state: _State, i: str, g: str) -> bool:
    for y in state.members[g]:
        if tuple(sorted((i, y))) in state.cannot:
            return True
        if state.policy.admit and _conflict(state.cores[i], state.cores[y]):
            return True
    return False


__all__ = ["Thing", "Post", "Item", "Edge", "Policy", "Evidence", "Core", "Group", "Grouping", "group", "core_of"]
