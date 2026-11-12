"""Anchors (issue 0180, 0166 step 3): what a follow-up attaches to, and the follow-ups Pairing's `develops` relation
finds for it. Back in the news (back.py) and later developments (later.py) were each a trigger over Mark IX stories
with private gates; here one module reads every anchor the same way and asks Pairing which later posts develop it.

An **Anchor** is
  - `kind`: `ix_story` (a Mark IX story), `mx_story` (a Mark X story: its current members, not merged away) or
    `happening` (posts of one happening no story holds: their stored keys one happening within the develops row's
    first gap, so a later post of it is a follow-up, not a member);
  - `id`: the story's id, or the happening's earliest post;
  - `members` (back._P, oldest first), `at` / `last` (its first and last post), `voices` (its distinct sources, a
    saved post none: Pairing's voice rule);
  - `happenings`: {member: its happening key} read from mx_happenings through happening.stored (the event-type
    seam's groups), only the groups the develops row pairs (deal, legal);
  - `subject`: its main subject when it has one specific entity (later.mains: 0163's rule), else None;
  - `pages`: its own pages by Pairing's page key (members' addresses, pages 2+ members link, the origin).

The interface:
  - `of(cur, kinds=KINDS, near=None)`: {(kind, id): Anchor}: the story anchors of 2+ voices, the happening anchors of
    the posts dated in `near` (lo, hi).
  - `follow_ups(anchors, posts, keys)`: Pairing's `develops` happening gate over them: {(kind, id): [(at, post)]}.
  - `later_find` / `back_find`: the two engines' candidates (nothing written): the anchor's **happening first**
    (a post whose key develops one of its members' keys: E6's windows, 2+ separate shared parties, no money clash;
    one source is enough, no quiet rule, no 14/7-day wait: the key replaces them), **its subject second** (later's E
    and L, back's E, L and V, with their gates now in Pairing's develops row, over Mark X stories too).
  - `shadow(cur, "back" | "later", ...)`: the decision run's part (from back.stage and later.stage, so inside their
    savepoints): the anchors engine's rows written beside the old engine's (mx_back / mx_later, engine 'anchors'),
    each on its own clock; an error in it is logged and leaves the old engine's rows standing (a concurrent update
    still defers the stage).
  - `shown(cur)`: which engine the pages show (mx_settings SHOWN_KEY: 'old' by default, 'anchors').
  - `compare(cur, "back" | "later")`: the rows only the old engine has, only the anchors engine has, and both.

One post, one anchor per happening (or subject): when a Mark IX story, a Mark X story and a happening anchor all hold
the post's happening, the Mark IX story's row stands (RANK), so the two engines compare on the same anchors.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from insight_core.markx import back, pairing

log = logging.getLogger(__name__)

IX, MX, HAPPENING = "ix_story", "mx_story", "happening"
KINDS = (IX, MX, HAPPENING)
RANK = {IX: 0, MX: 1, HAPPENING: 2}       # one post's row goes to the first of these that holds its match
OLD, ENGINE = back.ENGINE, "anchors"
SHOWN_KEY = "anchors_shown"               # mx_settings: which engine the pages show ('old' by default)
SHADOW_KEY = "anchors_shadow"             # mx_settings: the anchors engine runs beside the old one (on by default)
BACK_SINCE_KEY = "back_anchors_since"
LATER_SINCE_KEY = "later_anchors_since"
POL = back.DEVELOPS
TRIG_ORDER = ("H", "E", "L")


def shown(cur: Any) -> str:
    """The engine whose rows the pages show (SHOWN_KEY; OLD unless set to ENGINE)."""
    from insight_core.markx import repo
    return ENGINE if repo.get_setting(cur, SHOWN_KEY, default=OLD) == ENGINE else OLD


def shadow_on(cur: Any) -> bool:
    from insight_core.markx import repo
    return bool(repo.get_setting(cur, SHADOW_KEY, default=True))


# ---- the anchors ---------------------------------------------------------------------------------------------

@dataclass
class Anchor:
    kind: str
    id: str
    members: List[Any]                                   # back._P, oldest first
    origin: Optional[str] = None
    happenings: Dict[str, Any] = field(default_factory=dict)   # member: its happening key (develops groups)
    subject: Optional[str] = None                        # its one specific main subject (root entity), else None
    pages: Set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.members = sorted(self.members, key=lambda p: (p.at, p.id))
        self.mids = {p.id for p in self.members}

    @property
    def key(self) -> Tuple[str, str]:
        return (self.kind, self.id)

    @property
    def at(self) -> datetime:
        return self.members[0].at

    @property
    def last(self) -> datetime:
        return self.members[-1].at

    @property
    def voices(self) -> int:
        return pairing.voices((p.src, "saved" if p.saved else None) for p in self.members)


def _members(cur: Any, sql: str, params: Sequence[Any] = ()) -> Tuple[Dict[str, List[Any]], Dict[str, Optional[str]]]:
    """({anchor: its members (back._P)}, {anchor: origin}) of a query of (anchor, post, source, date, url, platform,
    handle, origin)."""
    from insight_core.utils.post_links import source_kind
    cur.execute(sql, params)
    by: Dict[str, List[Any]] = defaultdict(list)
    origin: Dict[str, Optional[str]] = {}
    for aid, pid, src, at, url, pl, h, o in cur.fetchall():
        if at is not None:
            by[aid].append(back._P(pid, src, at, url, source_kind(pl, h) == "saved"))
            origin.setdefault(aid, o)
    return by, origin


def _stories(cur: Any, kinds: Sequence[str]) -> List[Anchor]:
    date = back._date()
    out: List[Anchor] = []
    if IX in kinds:
        by, origin = _members(cur, f"""SELECT sp.story_id::text, p.id::text, p.source_id::text, {date}, p.url,
                                              s.platform, s.handle_or_url, st.origin_url
                                         FROM story_posts sp JOIN stories st ON st.id = sp.story_id
                                         JOIN posts p ON p.id = sp.post_id JOIN sources s ON s.id = p.source_id""")
        out += [Anchor(IX, sid, ms, origin.get(sid)) for sid, ms in by.items()]
    if MX in kinds:
        by, origin = _members(cur, f"""SELECT m.story_id::text, p.id::text, p.source_id::text, {date}, p.url,
                                              s.platform, s.handle_or_url, NULL
                                         FROM mx_story_posts m JOIN mx_stories x ON x.id = m.story_id
                                         JOIN posts p ON p.id = m.post_id JOIN sources s ON s.id = p.source_id
                                        WHERE m.valid_to IS NULL AND x.merged_into IS NULL""")
        out += [Anchor(MX, sid, ms, None) for sid, ms in by.items()]
    return [a for a in out if a.voices >= POL.min_voices]


def _happening_anchors(cur: Any, near: Tuple[datetime, datetime], stories: Sequence[Anchor]) -> List[Anchor]:
    """The happening anchors of the posts dated in `near` whose stored key is of a develops group and no story anchor
    holds (`held`): their keys one happening (happening.same) within the group's same-story window (Pairing's
    same_story row: deal 30 days, legal 7), chained. A later post of the happening may be a member and a follow-up
    of its earlier members at once (`follow_ups`)."""
    from insight_core.markx import happening
    from insight_core.utils.post_links import source_kind
    groups = list(POL.develops_groups)
    if not groups:
        return []
    held = {m for a in stories for m in a.mids}
    cur.execute(f"""SELECT h.post_id::text, p.source_id::text, {back._date()}, p.url, s.platform, s.handle_or_url
                      FROM mx_happenings_now h JOIN posts p ON p.id = h.post_id JOIN sources s ON s.id = p.source_id
                     WHERE h.grp = ANY(%s) AND {back._date()} BETWEEN %s AND %s""", (groups, near[0], near[1]))
    rows = [r for r in cur.fetchall() if r[0] not in held and r[2] is not None]
    keys = happening.stored(cur, [r[0] for r in rows])
    one = pairing.policy(pairing.SAME_STORY)
    told: Dict[Tuple[str, FrozenSet[str]], List[Tuple[datetime, Any]]] = defaultdict(list)
    for a in stories:   # a story telling the happening holds it: its stray posts make no anchor of their own
        for m in a.members:
            if m.id in a.happenings:
                for x in a.happenings[m.id].indexes():
                    told[x].append((m.at, a.happenings[m.id]))

    def by_a_story(at: datetime, k: Any) -> bool:
        span = one.happening_span(k.group)
        return any(abs(at - t) <= span and happening.same(km, k, span) for x in k.indexes() for t, km in told.get(x, ()))
    posts = sorted((back._P(pid, src, at, url, source_kind(pl, h) == "saved") for pid, src, at, url, pl, h in rows
                    if pid in keys and keys[pid].group in groups and not by_a_story(at, keys[pid])),
                   key=lambda p: (p.at, p.id))
    parent = {p.id: p.id for p in posts}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    index: Dict[Tuple[str, FrozenSet[str]], List[Any]] = defaultdict(list)
    one = pairing.policy(pairing.SAME_STORY)
    for p in posts:
        k = keys[p.id]
        span = one.happening_span(k.group)
        for x in k.indexes():
            for q in index[x]:
                if p.at - q.at <= span and happening.same(keys[q.id], k, span):
                    parent[find(p.id)] = find(q.id)
            index[x].append(p)
    groups_of: Dict[str, List[Any]] = defaultdict(list)
    for p in posts:
        groups_of[find(p.id)].append(p)
    out = []
    for ms in groups_of.values():
        a = Anchor(HAPPENING, min(ms, key=lambda p: (p.at, p.id)).id, ms, None)
        a.happenings = {p.id: keys[p.id] for p in ms}
        out.append(a)
    return out


def of(cur: Any, *, kinds: Sequence[str] = KINDS, near: Optional[Tuple[datetime, datetime]] = None
       ) -> Dict[Tuple[str, str], Anchor]:
    """{(kind, id): Anchor}: the story anchors of `kinds` of 2+ voices (their members' stored happening keys of the
    develops groups), and, with `near` (lo, hi), the happening anchors of the posts dated in it."""
    from insight_core.markx import happening
    st = _stories(cur, kinds)
    keys = happening.stored(cur, sorted({m.id for a in st for m in a.members}))
    groups = set(POL.develops_groups)
    for a in st:
        a.happenings = {m.id: keys[m.id] for m in a.members if m.id in keys and keys[m.id].group in groups}
    out = {a.key: a for a in st}
    if HAPPENING in kinds and near is not None:
        out.update({a.key: a for a in _happening_anchors(cur, near, st)})
    return out


# ---- follow-ups: the happening first ----------------------------------------------------------------------------

def follow_ups(anchors: Mapping[Tuple[str, str], Anchor], posts: Iterable[Any], keys: Mapping[str, Any]
               ) -> Dict[Tuple[str, str], List[Tuple[datetime, str, List[str]]]]:
    """{anchor: [(date, post, the members it follows up)], sorted} of the posts (back._P, voices) whose happening key
    (`keys`) develops one of the anchor's members' keys (pairing.develops: the gap from that member within the
    group's window, from its first gap on). A story anchor: never one of its members, and from the first gap after
    its last post (its own coverage is no follow-up). A happening anchor: its members dated a first gap or more
    before the post (a post of it may follow up its earlier posts: the story is the happening as it stood then).
    Then one anchor per post and happening: the first by RANK, then the latest last post, then the id."""
    index: Dict[Tuple[str, FrozenSet[str]], Set[Tuple[str, str]]] = defaultdict(set)
    for a in anchors.values():
        for k in a.happenings.values():
            for x in k.indexes():
                index[x].add(a.key)
    best: Dict[Tuple[str, Tuple[str, FrozenSet[str]]], Tuple[Tuple, Tuple[str, str], datetime, List[str]]] = {}
    for p in posts:
        k = keys.get(p.id)
        if k is None or p.saved or POL.develops_span(k.group) is None:
            continue
        lo = POL.develops_span(k.group)[0]
        for ak in sorted({ak for x in k.indexes() for ak in index.get(x, ())}):
            a = anchors[ak]
            if a.kind == HAPPENING:
                before = [m for m in a.members if p.at - m.at >= lo and m.id != p.id]
            elif p.id in a.mids or p.at - a.last < lo:
                continue
            else:
                before = a.members
            if not before or not any(pairing.develops(POL, km, k, p.at - m.at)
                                     for m in before if (km := a.happenings.get(m.id)) is not None):
                continue
            ident = (p.id, (k.group, k.parties))
            rank = (RANK[a.kind], -before[-1].at.timestamp(), a.id)
            if ident not in best or rank < best[ident][0]:
                best[ident] = (rank, ak, p.at, [m.id for m in before])
    out: Dict[Tuple[str, str], List[Tuple[datetime, str, List[str]]]] = defaultdict(list)
    for (pid, _i), (_r, ak, at, ms) in best.items():
        if pid not in {x[1] for x in out[ak]}:
            out[ak].append((at, pid, ms))
    return {ak: sorted(v) for ak, v in out.items()}


def _keys(cur: Any, ids: Sequence[str]) -> Dict[str, Any]:
    """The posts' happening keys of a develops group (happening.keys: stored, computed again where they moved)."""
    from insight_core.markx import happening
    groups = set(POL.develops_groups)
    return {p: k for p, k in happening.keys(cur, list(ids)).items() if k.group in groups}


def _wholes(cur: Any, posts: Sequence[Any]) -> List[Any]:
    """The posts that may be judged as a whole (the develops row's unit rule, Pairing's for every relation: a roundup
    never is, until its items are units)."""
    if POL.roundups != pairing.ROUNDUP_WHOLE_EXCLUDED or not posts:
        return list(posts)
    cur.execute("SELECT post_id::text FROM mx_readings WHERE guide = 'read-v2' AND kind = 'roundup' "
                "AND post_id = ANY(%s::uuid[])", ([p.id for p in posts],))
    out = {r[0] for r in cur.fetchall()}
    return [p for p in posts if p.id not in out]


def _reach() -> timedelta:
    return max((hi for _lo, hi in POL.develops_windows.values()), default=timedelta(0))


# ---- the later engine ---------------------------------------------------------------------------------------

def later_find(cur: Any, *, now: datetime, since: datetime, limit: int, after: Optional[str] = None
               ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """The anchors engine's Later rows of the posts dated in [since, now] (later's clock and cap): the anchor's
    happening first (H), its subject second (later's E and L over Mark IX and Mark X stories). ([{anchor_kind, story
    (the anchor's id), post, members, entity, trig, post_at, last_at}], clock). Nothing is written."""
    from insight_core.markx import later
    recent, more = later._recent(cur, since, now, limit, after)
    clock = ({"at": recent[-1].at.isoformat(), "after": recent[-1].id} if more
             else {"at": now.isoformat(), "after": None})
    clock["rule"] = later.RULE
    recent = _wholes(cur, [p for p in recent if not p.saved])
    if not recent:
        return [], clock
    keys = _keys(cur, [p.id for p in recent])
    lo, hi = min(p.at for p in recent) - _reach(), max(p.at for p in recent)
    anchors = of(cur, near=(lo, hi))
    stops = later.stopped(cur, sorted({a.id for a in anchors.values()}))
    anchors = {k: a for k, a in anchors.items() if a.id not in stops}
    rows: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    at = {p.id: p for p in recent}
    for ak, hits in follow_ups(anchors, recent, keys).items():
        a = anchors[ak]
        for t, pid, ms in hits:
            last = max(m.at for m in a.members if m.id in set(ms))
            rows[(ak[0], ak[1], pid)] = {"anchor_kind": a.kind, "story": a.id, "post": pid, "members": ms,
                                         "entity": None, "trig": {"H"}, "post_at": t, "last_at": last}
    # the subject second: later's own rule (a specific main subject; E, L; one story per post and subject; quiet)
    stories = {a.id: a for a in anchors.values() if a.kind in (IX, MX)}
    ids = later._Ids(cur)
    longs = later.mains(cur, {sid: a.members for sid, a in stories.items()},
                        {sid: a.origin for sid, a in stories.items()}, ids=ids, with_pages=True)
    for c in later.match(cur, recent, longs, ids, grown=True,
                         rank=lambda s: (RANK[stories[s.id].kind],) + later._rank(s)):   # a Mark IX story first
        a = stories[c["story"]]
        row = rows.setdefault((a.kind, a.id, c["post"]), {
            "anchor_kind": a.kind, "story": a.id, "post": c["post"], "members": c["members"], "entity": None,
            "trig": set(), "post_at": c["post_at"], "last_at": c["last_at"]})
        row["entity"] = c["entity"]
        row["trig"] |= set(c["trig"])
    out = _one_anchor(list(rows.values()), lambda r: {r["post"]})
    for r in out:
        r["trig"] = [t for t in TRIG_ORDER if t in r["trig"]]
    return sorted(out, key=lambda r: (r["post_at"], r["story"], r["post"])), clock


def _one_anchor(rows: List[Dict[str, Any]], posts_of: Any) -> List[Dict[str, Any]]:
    """Rows of one follow-up under anchors that overlap (a Mark IX story and the Mark X story of its posts): the
    first by RANK keeps it (their triggers joined), the others are dropped."""
    kept: List[Dict[str, Any]] = []
    for r in sorted(rows, key=lambda r: (RANK[r["anchor_kind"]], -r["last_at"].timestamp(), r["story"])):
        mem, ps = set(r["members"]), posts_of(r)
        twin = next((k for k in kept if ps & posts_of(k) and mem & set(k["members"])), None)
        if twin is None:
            kept.append(r)
        elif isinstance(twin["trig"], set):
            twin["trig"] |= set(r["trig"])
    return kept


# ---- the back engine ----------------------------------------------------------------------------------------

def back_find(cur: Any, *, now: datetime, since: datetime) -> List[Dict[str, Any]]:
    """The anchors engine's back candidates of the posts dated in [since, now]: back's trigger (a burst of 2+ voices
    in 72 hours) over Mark IX and Mark X stories, its E, L and V and, first, H: posts whose happening develops the
    story's (from the group's first gap after its last post, not 14 / 7 days). Pages by Pairing's page key. Once a
    story, again 30 days after its last window when it keeps listening (a specific subject or a happening key) and is
    still followed. [{anchor_kind, story, members, first_at, last_at, window_at, trig, posts, post_trig}]."""
    from insight_core.markx import later
    anchors = of(cur, kinds=(IX, MX))
    if not anchors:
        return []
    by_id = {a.id: a for a in anchors.values()}
    cur.execute("SELECT anchor_kind, story::text, max(window_at) FROM mx_back WHERE engine = %s GROUP BY 1, 2",
                (ENGINE,))
    fired = {(k, s): t for k, s, t in cur.fetchall()}
    st: Dict[str, back.Story] = {}
    again_of: Dict[str, datetime] = {}
    lived: Set[str] = set()
    if fired:
        was = [a for a in anchors.values() if a.key in fired]
        ids = later._Ids(cur)
        lived = set(later.mains(cur, {a.id: a.members for a in was}, {a.id: a.origin for a in was}, ids=ids))
        lived |= {a.id for a in was if a.happenings}
        lived -= later.stopped(cur, sorted(lived))
    for a in anchors.values():
        s = back.Story(a.id, list(a.members), a.origin)
        if a.key in fired:
            if a.id not in lived:
                continue
            s.again = fired[a.key] + POL.again
            again_of[a.id] = s.again
        if s.t0() <= now or a.happenings:
            st[a.id] = s
    if not st:
        return []
    back.fill(cur, st, page=pairing.page_key)
    recent = {p.id: p for p in _wholes(cur, list(back.recent_posts(cur, now=now, since=since).values()))}
    extra: Dict[str, List[Tuple[datetime, str]]] = {}
    if recent:
        keys = _keys(cur, sorted(recent))
        for (kind, aid), hits in follow_ups({a.key: a for a in anchors.values() if a.id in st},
                                            recent.values(), keys).items():
            hits = [(t, p) for t, p, _ms in hits if t >= again_of.get(aid, t)]
            if hits:
                extra[aid] = hits
    found = back.triggers(cur, st, now=now, since=since, page=pairing.page_key, recent=recent, extra=extra)
    for c in found:
        c["anchor_kind"] = by_id[c["story"]].kind
    return _one_anchor(found, lambda r: set(r["posts"]))


# ---- the decision run's part (Shadow) -----------------------------------------------------------------------------

def shadow(cur: Any, which: str, *, now: datetime, run_id: Any = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """The anchors engine's rows of one module ("back" or "later") written beside the old engine's, on its own clock,
    in a savepoint: an error is logged and counted (the old engine's rows stand); a concurrent update (serialization
    failure, deadlock) is raised, so the caller's stage is deferred as before. Its counts."""
    from psycopg import errors as psycopg_errors

    from insight_core.markx import later, repo
    if not shadow_on(cur):
        return {"off": True}
    t0 = time.monotonic()
    try:
        with cur.connection.transaction():
            if which == "back":
                last = repo.get_setting(cur, BACK_SINCE_KEY, default=None)
                since = (datetime.fromisoformat(last) - back.WINDOW - back.MARGIN) if last \
                    else now - timedelta(days=back.FIRST_SCAN_DAYS)
                found = back_find(cur, now=now, since=since)
                out: Dict[str, Any] = {"since": since.isoformat(), "found": len(found),
                                       "added": back.write(cur, found, run_id=run_id, engine=ENGINE)}
                repo.set_setting(cur, BACK_SINCE_KEY, now.isoformat())
            else:
                last = repo.get_setting(cur, LATER_SINCE_KEY, default=None) or {}
                if last.get("rule") != later.RULE:
                    last = {}
                after = last.get("after")
                since = (datetime.fromisoformat(last["at"]) - (timedelta(0) if after else later.MARGIN)) \
                    if last.get("at") else now - timedelta(days=later.FIRST_SCAN_DAYS)
                found, clock = later_find(cur, now=now, since=since, limit=limit or later.PER_RUN, after=after)
                out = {"since": since.isoformat(), "clock": clock, "found": len(found),
                       "added": later.write(cur, found, run_id=run_id, now=now, engine=ENGINE)}
                repo.set_setting(cur, LATER_SINCE_KEY, clock)
    except (psycopg_errors.SerializationFailure, psycopg_errors.DeadlockDetected):
        raise
    except Exception as exc:   # Shadow: the anchors engine never takes the old one down with it
        log.exception("Mark X anchors (%s): the Shadow engine failed; the old engine's rows stand", which)
        return {"error": str(exc).strip().splitlines()[0][:200] if str(exc).strip() else type(exc).__name__}
    out["seconds"] = round(time.monotonic() - t0, 3)
    return out


# ---- the comparison --------------------------------------------------------------------------------------------

def _rows(cur: Any, which: str) -> List[Dict[str, Any]]:
    if which == "back":
        cur.execute("""SELECT id::text, engine, anchor_kind, COALESCE(anchor_id, story)::text, members::text[],
                              posts::text[], trig, window_at, task_id::text FROM mx_back ORDER BY window_at, id""")
        return [{"id": i, "engine": e, "anchor_kind": k, "anchor": a, "members": list(m), "posts": list(p),
                 "trig": list(t), "at": w, "task": tid} for i, e, k, a, m, p, t, w, tid in cur.fetchall()]
    from insight_core.markx import later
    cur.execute("""SELECT id::text, engine, anchor_kind, COALESCE(anchor_id, story)::text, members::text[], post::text,
                          trig, post_at, task_id::text, verdict FROM mx_later WHERE rule = %s ORDER BY post_at, id""",
                (later.RULE,))
    return [{"id": i, "engine": e, "anchor_kind": k, "anchor": a, "members": list(m), "posts": [p], "trig": list(t),
             "at": w, "task": tid, "verdict": v} for i, e, k, a, m, p, t, w, tid, v in cur.fetchall()]


def compare(cur: Any, which: str) -> Dict[str, Any]:
    """The old engine's rows against the anchors engine's ("back" or "later"): a row of one is matched by a row of
    the other sharing a follow-up post and a member of the anchor (or the anchor itself). {only_old, only_new, both
    (pairs of ids), counts {old, new, only_old, only_new, both, new_by_kind, new_by_trig, only_new_by_kind,
    only_new_by_trig}}."""
    from collections import Counter
    rows = _rows(cur, which)
    old = [r for r in rows if r["engine"] == OLD]
    new = [r for r in rows if r["engine"] == ENGINE]
    by_post: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in new:
        for p in r["posts"]:
            by_post[p].append(r)

    def same(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        return a["anchor"] == b["anchor"] or bool(set(a["members"]) & set(b["members"]))
    both, matched_new = [], set()
    only_old = []
    for r in old:
        hit = [n for p in r["posts"] for n in by_post.get(p, ()) if same(r, n)]
        if hit:
            both.append({"old": r["id"], "new": sorted({n["id"] for n in hit})})
            matched_new |= {n["id"] for n in hit}
        else:
            only_old.append(r)
    only_new = [r for r in new if r["id"] not in matched_new]

    def short(r: Dict[str, Any]) -> Dict[str, Any]:
        return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in r.items() if k != "members"}
    counts = {"old": len(old), "new": len(new), "only_old": len(only_old), "only_new": len(only_new),
              "both": len(both),
              "new_by_kind": dict(Counter(r["anchor_kind"] for r in new)),
              "new_by_trig": dict(Counter("+".join(r["trig"]) for r in new)),
              "only_new_by_kind": dict(Counter(r["anchor_kind"] for r in only_new)),
              "only_new_by_trig": dict(Counter("+".join(r["trig"]) for r in only_new)),
              "old_by_trig": dict(Counter("+".join(r["trig"]) for r in old))}
    return {"which": which, "counts": counts, "only_old": [short(r) for r in only_old],
            "only_new": [short(r) for r in only_new], "both": both, "shown": shown(cur)}


__all__ = ["Anchor", "ENGINE", "HAPPENING", "IX", "KINDS", "MX", "OLD", "SHOWN_KEY", "back_find", "compare",
           "follow_ups", "later_find", "of", "shadow", "shown"]
