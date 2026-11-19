"""Stalker's first edges (issue 0131): the older posts a post connects to, 30 days back or more, as mx_connections rows
between two posts (a = the newer, b = the older). Shadow: mx_* tables only; Mark IX is only read.

Three sources, each naming its rule or its call and carrying its evidence (keep everything: an edge is closed with
valid_to, never deleted):

  1. **Authors' links** (no model; G2: another source's 40/40, the same source's 37/40): a post_refs row (0125) of the
     newer post, open and not boilerplate, that resolves to a stored post (as Connected resolves it: the post at that
     exact url, else the first seen at its normalized address, never the post itself) at least GAP_DAYS older.
     relation `refers_back`; rule `author_link_other` (p 1.0) or `author_link_own` (the same source, p 0.9: the owner's
     decision 1); evidence {href, address, reason, reason_kind}, the reason line Connected shows. Under GAP_DAYS no
     edge: the link stays a Connected row. Written incrementally by the decision run's `connections` stage (`stage`:
     the posts whose refs changed, the links whose target was stored since, the edges whose ref closed or became
     boilerplate) and by a resumable backfill over the archive (BACKFILL_SECONDS a run, mx_settings BACKFILL_KEY).
     A link that stops resolving, or becomes boilerplate, closes its edge. A same-source link that is series
     navigation (post_refs.navigation, 0134: both ends in one series, or "previous part" link words) is relation
     `next_in_series`, rule `series`, never `refers_back`, and the judge never refines it.
  2. **The judge** (`relate`, relate-v1 = G2's frozen judge v3, asked RELATE_RUNS times; the majority, "unknown" when
     no two agree; p = the share of the runs that agree). Candidates: the same ent-v3 subject (one entity after 0119 A
     identity) on both sides, cosine >= RELATE_COS, the older post RELATE_DAYS back at most (mx_candidates kind
     'relate', source 'entity'); and every author-link edge, so its type can be refined. A same-subject edge
     (rule NULL, its call) is "uncertain" (shown marked, with label buttons) until re-measured. On an author-link
     edge the judge only refines the relation (builds_on, follows_up, same_event); any other answer leaves it
     `refers_back`, never removes it. Planned capped like connect (`decide.Config.relate_open` open at a time).
  3. **next_version from entity identity** (no model; the judge's next_version calls were 1 of 4 right as a type):
     the newer post's subject is the version right after the older post's subject on its family's version line
     (timeline.version_lines, 0220: a letter starts its own line, another maker's thing, a version named once and a
     build number are off it; 0234: a product line of its own, a version its maker never announced (or, the maker
     silent here, fewer than two voices report) is off, the line in release order), the older post GAP_DAYS back or
     more; the previous stop's earliest NEXT_VERSION_POSTS
     posts. rule `entity_next_version`,
     evidence both entity keys. It replaces any judge call of next_version on that pair.

Dates are G2's: published first (Pairing's `published_date`, 0128's published).
"""
from __future__ import annotations

import bisect
import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urljoin

from psycopg import errors as psycopg_errors

from insight_core.markx import pairing

log = logging.getLogger(__name__)

GAP_DAYS = 30                 # the older post at least this far back (G2)
RELATE_DAYS = 180             # same-subject candidates: the older post at most this far back (G2: meaningful within 90)
RELATE_COS = 0.75             # ... at this cosine or more (G2's source b)
RELATE_RUNS = 3               # the judge asked three times a pair, the majority
# 0191: a first answer that settles its pair alone: never asked a second and third time (on the lab's 320 labelled pairs,
# each run in turn taken as the first, 0 of 960 meaningful decisions changed; 9% of relate calls saved). Stopping on
# `background` too saved 45% but lost 20 of 279 meaningful edges, so it is not done.
RELATE_SETTLES = ("unrelated",)
RELATE_OPEN = 100             # the planner's cap (decide.Config.relate_open)
RULE_OTHER, RULE_OWN, RULE_NEXT = "author_link_other", "author_link_own", "entity_next_version"
RULE_SERIES, NEXT_IN_SERIES = "series", "next_in_series"   # 0134: a same-source link that is series navigation
LINK_RULES = (RULE_OTHER, RULE_OWN, RULE_SERIES)
JUDGED_LINK_RULES = (RULE_OTHER, RULE_OWN)   # the judge refines these; a series edge is never asked
RULES = LINK_RULES + (RULE_NEXT,)
P_OTHER, P_OWN = 1.0, 0.9     # decision 1: the same source's links are edges at p 0.9
MEANINGFUL = ("same_event", "follows_up", "next_version", "builds_on", "refers_back")
REFINES = ("builds_on", "follows_up", "same_event")   # what the judge may make of an author-link edge
UNKNOWN = "unknown"
NEXT_VERSION_POSTS = 3
BACKFILL_SECONDS = 20.0       # the backfill's share of a decision run (the 120 s limit)
BACKFILL_BATCH = 500
BACKFILL_VERSION = 1          # a bump re-runs the backfill
BACKFILL_KEY = "graph_backfill"
SINCE_KEY = "graph_since"     # the last run's clock: what changed since is read again
MARGIN = timedelta(hours=1)   # read again a bit before it (a transaction that committed after the last snapshot)
PENDING_KEY = "graph_pending"   # v10.25 (0227): the posts a run linked while its graph stage did not run (`defer`)
BEFORE_SHOWN = 10
EXCERPT = 1100                # G2's render: 1,100 characters a post
ANCHOR = 300
DOCS_SHOWN = 4
MODEL = "bge-m3"


def _date(alias: str = "p") -> str:
    return pairing.published_date(alias)   # G2's dates: 0128's published


def _savepoint(cur: Any, fn, *args, **kw):
    """fn in a savepoint when the cursor's connection is in a transaction (a race with another writer, a unique
    index, leaves the caller's transaction usable)."""
    try:
        with cur.connection.transaction():
            return fn(*args, **kw)
    except (psycopg_errors.SerializationFailure, psycopg_errors.UniqueViolation):
        return None


# ---- 1. authors' links -------------------------------------------------------------------------------------

def resolve(cur: Any, refs: Sequence[Tuple[str, str, str]]) -> List[Optional[Tuple[str, str, datetime]]]:
    """For each (linking post, absolute url, normalized address): the stored post it resolves to, as Connected does
    (the post at that exact url, else the first seen at the address, never the linking post), as (id, source id,
    date), or None."""
    if not refs:
        return []
    cur.execute(f"""SELECT k.n, t.id::text, t.source_id::text, {_date('t')}
                      FROM unnest(%s::uuid[], %s::text[], %s::text[]) WITH ORDINALITY AS k(post, url, address, n)
                      JOIN LATERAL (SELECT tp.id, tp.source_id, tp.published_at, tp.surfaced_at, tp.fetched_at
                                      FROM posts tp
                                     WHERE (tp.url = k.url OR tp.normalized_url = k.address) AND tp.id <> k.post
                                     ORDER BY tp.url = k.url DESC, tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE""",
                ([r[0] for r in refs], [r[1] for r in refs], [r[2] for r in refs]))
    out: List[Optional[Tuple[str, str, datetime]]] = [None] * len(refs)
    for n, tid, src, at in cur.fetchall():
        out[n - 1] = (tid, src, at)
    return out


def _absolute(url: Optional[str], href: str) -> str:
    try:
        return urljoin(url or "", href)
    except ValueError:
        return href


def link_edges(cur: Any, post_ids: Iterable[str]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(newer, older): the edge} the posts' open, kept refs make: one per older post, its first link in the text."""
    ids = sorted({str(p) for p in post_ids})
    if not ids:
        return {}
    cur.execute(f"""SELECT r.post_id::text, p.url, p.source_id::text, {_date()}, r.target_address, r.href, r.reason,
                           r.reason_kind, r.navigation
                      FROM post_refs r JOIN posts p ON p.id = r.post_id
                     WHERE r.post_id = ANY(%s::uuid[]) AND r.valid_to IS NULL AND NOT r.boilerplate
                     ORDER BY r.post_id, r.position""", (ids,))
    rows = cur.fetchall()
    targets = resolve(cur, [(pid, _absolute(url, href), address) for pid, url, _s, _at, address, href, _r, _k, _n in rows])
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    gap = timedelta(days=GAP_DAYS)
    for (pid, _url, src, at, address, href, reason, kind, nav), got in zip(rows, targets):
        if got is None or at is None or got[2] is None:
            continue
        tid, tsrc, tat = got
        if tat > at - gap or (pid, tid) in out:
            continue
        own = tsrc == src
        series = own and nav   # 0134: series navigation is next_in_series, never refers_back
        out[(pid, tid)] = {"rule": RULE_SERIES if series else RULE_OWN if own else RULE_OTHER,
                           "relation": NEXT_IN_SERIES if series else "refers_back", "p": P_OWN if own else P_OTHER,
                           "evidence": {"href": href, "address": address, "reason": reason, "reason_kind": kind}}
    return out


def _current(cur: Any, *, rules: Optional[Sequence[str]] = None, a: Optional[Sequence[str]] = None,
             pairs: Optional[Sequence[Tuple[str, str]]] = None, judged: bool = False) -> List[Dict[str, Any]]:
    """The current post-to-post edges: of `rules` (or, `judged`, the judge's own: rule NULL), touching `a` as the newer
    post or one of `pairs`."""
    where = ["x.valid_to IS NULL", "x.a_kind = 'post'", "x.b_kind = 'post'"]
    params: List[Any] = []
    if judged:
        where.append("x.rule IS NULL")
    elif rules is not None:
        where.append("x.rule = ANY(%s)")
        params.append(list(rules))
    if a is not None:
        where.append("x.a = ANY(%s::uuid[])")
        params.append(sorted(set(a)))
    if pairs is not None:
        where.append("(x.a, x.b) IN (SELECT * FROM unnest(%s::uuid[], %s::uuid[]))")
        params += [[p[0] for p in pairs], [p[1] for p in pairs]]
    cur.execute(f"""SELECT x.a::text, x.b::text, x.relation, x.rule, x.p, x.call_id::text, x.evidence
                      FROM mx_connections x WHERE {' AND '.join(where)}""", params)
    return [{"a": a_, "b": b_, "relation": rel, "rule": rule, "p": p, "call": call, "evidence": ev or {}}
            for a_, b_, rel, rule, p, call, ev in cur.fetchall()]


def _open(cur: Any, rows: Sequence[Dict[str, Any]], *, run_id: Any, now: datetime) -> int:
    """Open these edges (a, b, relation, p, call, rule, evidence) from `now`; one already current is left."""
    if not rows:
        return 0
    n = 0
    for r in rows:
        if r.get("rule") is not None:   # a rule's edge takes the place of the judge's own one of its relation
            cur.execute("""UPDATE mx_connections SET valid_to = GREATEST(valid_from, %s)
                            WHERE a_kind = 'post' AND a = %s AND b_kind = 'post' AND b = %s AND relation = %s
                              AND rule IS NULL AND valid_to IS NULL""", (now, r["a"], r["b"], r["relation"]))
        cur.execute("""INSERT INTO mx_connections (a_kind, a, b_kind, b, relation, p, call_id, rule, run_id, evidence, valid_from)
                       VALUES ('post', %s, 'post', %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                       ON CONFLICT (a_kind, a, b_kind, b, relation) WHERE valid_to IS NULL DO NOTHING""",
                    (r["a"], r["b"], r["relation"], r.get("p"), r.get("call"), r.get("rule"), run_id,
                     json.dumps(r.get("evidence") or {}, ensure_ascii=False, default=str), now))
        n += cur.rowcount
    return n


def _close(cur: Any, rows: Sequence[Dict[str, Any]], *, now: datetime) -> int:
    n = 0
    for r in rows:
        cur.execute("""UPDATE mx_connections SET valid_to = GREATEST(valid_from, %s)
                        WHERE a_kind = 'post' AND a = %s AND b_kind = 'post' AND b = %s AND relation = %s
                          AND valid_to IS NULL""", (now, r["a"], r["b"], r["relation"]))
        n += cur.rowcount
    return n


def sync_links(cur: Any, post_ids: Iterable[str], *, now: datetime, run_id: Any) -> Counter:
    """The author-link edges of these newer posts become exactly what their refs make now: new ones open (as
    `refers_back`, or refined by a settled verdict), the ones no longer made close."""
    ids = sorted({str(p) for p in post_ids})
    if len(ids) > BACKFILL_BATCH:   # BACKFILL_BATCH posts at a time: the memory stays a batch's
        counts = Counter()
        for k in range(0, len(ids), BACKFILL_BATCH):
            counts.update(sync_links(cur, ids[k:k + BACKFILL_BATCH], now=now, run_id=run_id))
        return counts
    counts = Counter(posts=len(ids))
    if not ids:
        return counts
    want = link_edges(cur, ids)
    have = {(e["a"], e["b"]): e for e in _current(cur, rules=LINK_RULES, a=ids)}
    gone = [e for k, e in have.items() if k not in want or want[k]["rule"] != e["rule"]]
    counts["closed"] += _close(cur, gone, now=now)
    new = [dict(w, a=k[0], b=k[1]) for k, w in want.items()
           if k not in have or have[k]["rule"] != w["rule"]]
    counts["opened"] += _open(cur, new, run_id=run_id, now=now)
    touched = [(e["a"], e["b"]) for e in gone] + [(e["a"], e["b"]) for e in new]
    if touched:
        counts.update(apply_pairs(cur, touched, now=now, run_id=run_id))
    return counts


def dirty_posts(cur: Any, since: datetime) -> Set[str]:
    """The newer posts whose author-link edges may have changed since `since`: their refs were read again, a ref of
    theirs opened or closed, a post stored since is at one of their links' addresses, or an edge's ref closed, became
    boilerplate or its older post is gone."""
    from insight_core.utils.url_normalization import normalize_url
    out: Set[str] = set()
    cur.execute("SELECT id::text FROM posts WHERE refs_scanned_at >= %s", (since,))
    out |= {r[0] for r in cur.fetchall()}
    cur.execute("SELECT DISTINCT post_id::text FROM post_refs WHERE created_at >= %s OR valid_to >= %s "
                "OR navigation_at >= %s", (since, since, since))   # 0134: a navigation flag changed
    out |= {r[0] for r in cur.fetchall()}
    cur.execute("SELECT normalized_url, url FROM posts WHERE created_at >= %s", (since,))
    addresses: Set[str] = set()
    for normalized, url in cur.fetchall():
        try:
            got = normalize_url(url) if url else None
        except ValueError:
            got = None
        addresses |= {x for x in (normalized, got) if x}
    if addresses:
        cur.execute("SELECT DISTINCT post_id::text FROM post_refs WHERE target_address = ANY(%s) AND valid_to IS NULL",
                    (sorted(addresses),))
        out |= {r[0] for r in cur.fetchall()}
    out |= stale_links(cur)
    return out


def stale_links(cur: Any) -> Set[str]:
    """The newer posts of current author-link edges whose ref row is gone, closed or boilerplate, or whose older post
    is no post."""
    cur.execute("""SELECT DISTINCT x.a::text FROM mx_connections x
                     LEFT JOIN post_refs r ON r.post_id = x.a AND md5(r.target_address) = md5(x.evidence->>'address')
                                          AND r.target_address = x.evidence->>'address'
                     LEFT JOIN posts o ON o.id = x.b
                    WHERE x.valid_to IS NULL AND x.a_kind = 'post' AND x.b_kind = 'post' AND x.rule = ANY(%s)
                      AND (r.post_id IS NULL OR r.valid_to IS NOT NULL OR r.boilerplate OR o.id IS NULL)""",
                (list(LINK_RULES),))
    return {r[0] for r in cur.fetchall()}


def backfill(cur: Any, *, now: datetime, run_id: Any, deadline: Optional[float] = None,
             batch: int = BACKFILL_BATCH) -> Dict[str, Any]:
    """The archive's author-link edges, BACKFILL_BATCH linking posts at a time in id order, until `deadline` (a
    time.monotonic() value; None: to the end). Resumable: where it got to is kept in mx_settings (BACKFILL_KEY), and
    a finished backfill does nothing more until BACKFILL_VERSION changes. Its counts so far."""
    from insight_core.markx import repo
    state = dict(repo.get_setting(cur, BACKFILL_KEY, default=None) or {})
    if state.get("version") != BACKFILL_VERSION:
        state = {"version": BACKFILL_VERSION, "after": None, "done": False, "posts": 0, "opened": 0, "closed": 0,
                 "seconds": 0.0, "started_at": now.isoformat()}
    if state.get("done"):
        return {"done": True, "ran": False}
    t0 = time.monotonic()
    ran = Counter()
    while True:
        cur.execute("""SELECT DISTINCT post_id FROM post_refs
                        WHERE valid_to IS NULL AND NOT boilerplate AND (%(after)s::uuid IS NULL OR post_id > %(after)s::uuid)
                        ORDER BY post_id LIMIT %(n)s""", {"after": state["after"], "n": batch})
        ids = [str(r[0]) for r in cur.fetchall()]
        if ids:
            got = sync_links(cur, ids, now=now, run_id=run_id)
            for k in ("posts", "opened", "closed"):
                state[k] = state.get(k, 0) + got.get(k, 0)
                ran[k] += got.get(k, 0)
            state["after"] = ids[-1]
        if len(ids) < batch:
            state["done"] = True
            state["finished_at"] = now.isoformat()
            break
        if deadline is not None and time.monotonic() >= deadline:
            break
    state["seconds"] = round(state.get("seconds", 0.0) + time.monotonic() - t0, 3)
    repo.set_setting(cur, BACKFILL_KEY, state)
    if ran["posts"] or state["done"]:
        log.info("Mark X graph backfill: %d posts, %d edges opened this run (%s so far: %d posts, %d edges)%s",
                 ran["posts"], ran["opened"], "done" if state["done"] else "not done", state["posts"], state["opened"],
                 "" if state["done"] else f", resumes after {state['after']}")
    return {"ran": True, "done": state["done"], "posts": ran["posts"], "opened": ran["opened"],
            "closed": ran["closed"], "total": {k: state[k] for k in ("posts", "opened", "closed", "seconds")}}


# ---- the subjects (ent-v3, one entity after 0119 A identity) ---------------------------------------------------

class Subjects:
    """The posts' ent-v3 subjects as their root entities (redirects read through), with the posts' dates. v10.23
    (0218): read by need, for the posts and roots a step asks (`posts`, `want`, `versions`, `post_ids`): every post's
    subjects were read at once (~400k rows at the server-sized copy's 1.5M mentions: the graph stage's peak, the run's
    largest after the entity book was read by need)."""

    def __init__(self, cur: Any) -> None:
        from insight_core.markx import schemas
        self._cur = cur
        self._guide = schemas.mention_guides()   # 0133: the current set
        cur.execute("SELECT from_id::text, to_id::text FROM mx_entity_redirects WHERE undone_at IS NULL")
        self.redirect = dict(cur.fetchall())
        self._leading: Optional[Dict[str, List[str]]] = None
        self._by_root: Dict[str, List[Tuple[datetime, str]]] = {}

    def root(self, eid: str) -> str:
        seen = set()
        while eid in self.redirect and eid not in seen:
            seen.add(eid)
            eid = self.redirect[eid]
        return eid

    def members_of(self, roots: Iterable[str]) -> Dict[str, List[str]]:
        """{root: every id whose root it is (itself first)}."""
        if self._leading is None:
            self._leading = defaultdict(list)
            for f in self.redirect:
                self._leading[self.root(f)].append(f)
        return {r: [r] + sorted(self._leading.get(r, [])) for r in roots}

    def _members(self, roots: Iterable[str]) -> List[str]:
        """Every id whose root is one of `roots` (the roots themselves too)."""
        if self._leading is None:
            self._leading = defaultdict(list)
            for f in self.redirect:
                self._leading[self.root(f)].append(f)
        return sorted({x for r in roots for x in [r] + self._leading.get(r, [])})

    def _rows(self, where: str, args: Sequence[Any]) -> Iterable[Tuple[str, str, datetime]]:
        """(post, entity, date) of the subject mentions `where` says, a page at a time (no date: none)."""
        self._cur.execute(f"""SELECT m.post_id::text, m.entity_id::text, {_date()}
                                FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                               WHERE m.guide = ANY(%s) AND m.role = 'subject' AND m.entity_id IS NOT NULL
                                 AND {where}""", (self._guide, *args))
        while True:
            page = self._cur.fetchmany(20000)
            if not page:
                return
            for pid, eid, at in page:
                if at is not None:
                    yield pid, eid, at

    def posts(self, pids: Iterable[str]) -> Tuple[Dict[str, Set[str]], Dict[str, datetime]]:
        """({post: its subjects' roots}, {post: its date}) of `pids`."""
        of: Dict[str, Set[str]] = defaultdict(set)
        at: Dict[str, datetime] = {}
        ids = sorted(set(pids))
        if ids:
            for pid, eid, d in self._rows("m.post_id = ANY(%s::uuid[])", (ids,)):
                of[pid].add(self.root(eid))
                at[pid] = d
        return of, at

    def want(self, roots: Iterable[str]) -> None:
        """The posts of `roots` (each a subject of theirs), by date, for `between`; what was read before let go."""
        roots = set(roots)
        got: Dict[str, Set[Tuple[datetime, str]]] = defaultdict(set)
        ids = self._members(roots)
        if ids:
            for pid, eid, d in self._rows("m.entity_id = ANY(%s::uuid[])", (ids,)):
                r = self.root(eid)
                if r in roots:
                    got[r].add((d, pid))
        self._by_root = {r: sorted(xs) for r, xs in got.items()}

    def versions(self, roots: Iterable[str]) -> Iterable[Tuple[str, str, datetime]]:
        """(post, root, date) of every post a subject of which has its root in `roots` (once a post and root)."""
        roots = set(roots)
        seen: Set[Tuple[str, str]] = set()
        ids = self._members(roots)
        if ids:
            for pid, eid, d in self._rows("m.entity_id = ANY(%s::uuid[])", (ids,)):
                r = self.root(eid)
                if r in roots and (pid, r) not in seen:
                    seen.add((pid, r))
                    yield pid, r, d

    def post_ids(self, after: str, n: int) -> List[str]:
        """The next `n` posts with a subject (and a date) after `after` ('': the first), in id order."""
        self._cur.execute(f"""SELECT DISTINCT m.post_id::text FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                               WHERE m.guide = ANY(%s) AND m.role = 'subject' AND m.entity_id IS NOT NULL
                                 AND {_date()} IS NOT NULL AND (%s = '' OR m.post_id > %s::uuid)
                               ORDER BY 1 LIMIT %s""", (self._guide, after or "", after or None, n))
        return [r[0] for r in self._cur.fetchall()]

    def between(self, root: str, lo: datetime, hi: datetime) -> List[str]:
        xs = self._by_root.get(root) or []
        i = bisect.bisect_left(xs, (lo, ""))
        j = bisect.bisect_right(xs, (hi, "\uffff"))
        return [p for _, p in xs[i:j]]


# ---- 3. next_version from identity ----------------------------------------------------------------------------

def next_version_edges(cur: Any, subjects: Subjects) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(newer, older): the edge}: the newer post's subject is the version right after the older post's subject on its
    family's version line (timeline.version_lines, 0220: the line the entity page shows); the older post GAP_DAYS back
    or more, the previous stop's earliest NEXT_VERSION_POSTS posts."""
    from insight_core.markx import timeline as TL
    # v10.23 (0218): the versions first (the roots that can make an edge), then only their posts. 0220: their counts
    # (posts naming each, about each) by the database, one row a version
    cur.execute("""SELECT id::text, parent::text, version_key, key, name, maker, variant, size, build FROM mx_entities
                    WHERE level = 'version' AND parent IS NOT NULL AND status <> 'not_entity'""")
    fams: Dict[str, List[Tuple[str, str, Any, Optional[str], Optional[str]]]] = defaultdict(list)
    keys: Dict[str, Tuple[str, str]] = {}
    for eid, parent, vkey, key, name, maker, variant, size, build in cur.fetchall():
        if size or build or subjects.root(eid) != eid or TL.line_key(vkey) is None:   # 0234: a variant's own line
            continue
        fams[subjects.root(parent)].append((eid, name, vkey, maker, variant))
        keys[eid] = (key, name)
    fams = {f: rows for f, rows in fams.items() if len(rows) >= 2}
    if not fams:
        return {}
    roots = [r for rows in fams.values() for r, *_ in rows]
    counts = TL.version_counts(cur, subjects.members_of(roots))
    cur.execute("SELECT id::text, name, maker FROM mx_entities WHERE id = ANY(%s::uuid[])", (sorted(fams),))
    fam_of = {fid: (name, maker) for fid, name, maker in cur.fetchall()}
    stop_of: Dict[str, Tuple[str, int, int]] = {}
    for fam, rows in sorted(fams.items()):
        name, maker = fam_of.get(fam, (None, None))
        for li, line in enumerate(TL.version_lines(TL.line_versions(rows, counts), family_name=name, family_maker=maker,
                                                   same_maker=TL.same_maker)):
            for si, stop in enumerate(line):
                for v in stop.versions:
                    stop_of[v.id] = (fam, li, si)
    group: Dict[Tuple[str, int, int], List[Tuple[datetime, str, str]]] = defaultdict(list)
    for pid, r, at in subjects.versions(stop_of):
        group[stop_of[r]].append((at, pid, r))
    for xs in group.values():
        xs.sort()
    gap = timedelta(days=GAP_DAYS)
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (fam, li, si), posts in sorted(group.items()):   # v10.23: one order (a pair two families name: the last)
        if si == 0:
            continue
        before = group.get((fam, li, si - 1)) or []
        for at, pid, r in posts:
            olders = [(oat, op, orr) for oat, op, orr in before if oat <= at - gap and op != pid][:NEXT_VERSION_POSTS]
            for _oat, op, orr in olders:
                out[(pid, op)] = {"rule": RULE_NEXT, "p": 1.0, "relation": "next_version",
                                  "evidence": {"newer": keys[r][0], "older": keys[orr][0], "newer_name": keys[r][1],
                                               "older_name": keys[orr][1], "newer_entity": r, "older_entity": orr}}
    return out


def sync_next_version(cur: Any, subjects: Subjects, *, now: datetime, run_id: Any) -> Counter:
    """The identity next_version edges become exactly `next_version_edges`; a judge's next_version on such a pair
    closes (identity replaces it)."""
    want = next_version_edges(cur, subjects)
    have = {(e["a"], e["b"]): e for e in _current(cur, rules=[RULE_NEXT])}
    counts: Counter = Counter()
    counts["closed"] = _close(cur, [e for k, e in have.items() if k not in want], now=now)
    counts["opened"] = _open(cur, [dict(w, a=k[0], b=k[1]) for k, w in want.items() if k not in have],
                             run_id=run_id, now=now)
    if want:
        judged = [e for e in _current(cur, judged=True, pairs=list(want)) if e["relation"] == "next_version"]
        counts["judge_replaced"] = _close(cur, judged, now=now)
    counts["current"] = len(want)
    return counts


# ---- 4. between entities: the relations a post states (0220) ----------------------------------------------------
# The entities answer's `relations` ({a, rel, b}, ent-v3 / ent-v4.2), each side read as one of that answer's own
# mentions (its name or span), then its entity's root. An edge a -> b of the relation, rule `stated`, evidence {posts:
# the posts stating it, since: the first one's date}, valid_from its first post's date; a post that stops stating it
# leaves its evidence, an edge with none left closes (kept). Only the relations entity_bands.json `relations` switches
# on are written: measured blind on frozen sets (plan/issues/0220): based_on 95/95, released 89/90 held out once the
# thing's own mention states the same maker (`released` as stated alone: 87/90); acquired 25/25 (too few rows for the
# bar), part_of 63/70, partnered_with 86/106: off.
RULE_STATED = "stated"
RELATIONS_KEY = "graph_relations"      # the backfill's cursor
RELATIONS_VERSION = 1
RELATIONS_BATCH = 500


def relations_on() -> Set[str]:
    """The relations written and shown (entity_bands.json `relations`)."""
    from insight_core.markx import identity as I
    got = I.bands().get("relations") or {}
    return {r for r, on in (got.get("on") or {}).items() if on}


def corroborated(rel: str, a: str, b_maker: Optional[str]) -> bool:
    """Whether a stated relation stands on its own post (pure): `released` only when the thing's own mention names the
    same maker (the relation alone was 87/90: a host, a quantiser or an OEM 'released' another's model)."""
    from insight_core.markx import names as N
    return rel != "released" or (bool(b_maker) and N.key(b_maker) == N.key(a))


# 0224: ent-v5 (the reading, on) asks no `relations` (0223: asking them in its guide failed, and the guide must not
# change), but its fields already say two. Read from one post's current ent-v5 mentions (every window), never asked:
#   released: the reading's subject (a model, product or software) whose own `maker` is the name (or span) of an org
#             or person the same reading lists as the subject or the actor -> that maker `released` it. Any thing with
#             its maker anywhere in the reading was 135/193 = 69.9% stated (held out 1): a thing merely named (Codex
#             used, iOS 12 in passing) with a maker the post never ties to it. As written (the main event's maker
#             and thing): held out 2 175/180 = 97.2% [93.7-98.8]: on;
#   based_on: the reading's subject (a model, product or software) `based_on` each `predecessor` of those types
#             (held out 1: 20/33 = 60.6%: a predecessor is mostly what the subject replaces or is compared with).
# Each switched on by entity_bands.json `relations.derived` (and the relation itself on); measured blind on frozen
# held-out sets (plan/issues/0223, section "0224").
DERIVED_GUIDE = "ent-v5"
THING_TYPES = ("model", "product", "software")
MAKER_TYPES = ("org", "person")
MAKER_ROLES = ("subject", "actor")


def derived_on() -> Set[str]:
    """The relations read from ent-v5's fields (entity_bands.json `relations.derived`, each also switched on)."""
    from insight_core.markx import identity as I
    got = (I.bands().get("relations") or {}).get("derived") or {}
    return {r for r, on in got.items() if on} & relations_on()


def derived(mentions: Sequence[Dict[str, Any]], on: Iterable[str] = ("released", "based_on")) -> List[Tuple[int, str, int]]:
    """(pure) The relations one post's ent-v5 mentions say by their fields: [(a, relation, b)], indexes into
    `mentions` ({name, span, type, role, maker}), never a thing to itself, each once."""
    from insight_core.markx import names as N
    on = set(on)
    keys: Dict[str, List[int]] = defaultdict(list)
    for i, m in enumerate(mentions):
        for k in {N.key(m.get("name")), N.key(m.get("span"))}:
            if k:
                keys[k].append(i)
    own = [N.key(m.get("name")) for m in mentions]
    out: List[Tuple[int, str, int]] = []
    if "released" in on:
        for b, m in enumerate(mentions):
            if m.get("type") not in THING_TYPES or m.get("role") != "subject" or not N.key(m.get("maker")):
                continue
            a = next((i for i in keys.get(N.key(m.get("maker")), ())
                      if i != b and own[i] != own[b] and mentions[i].get("type") in MAKER_TYPES
                      and mentions[i].get("role") in MAKER_ROLES), None)
            if a is not None:
                out.append((a, "released", b))
    if "based_on" in on:   # 0234: both in one window (`call`, when given): a long post's items are not each other's
        things = [i for i, m in enumerate(mentions) if m.get("type") in THING_TYPES]
        for a in (i for i in things if mentions[i].get("role") == "subject"):
            for b in (j for j in things if mentions[j].get("role") == "predecessor"):
                if own[a] != own[b] and mentions[a].get("call") == mentions[b].get("call"):
                    out.append((a, "based_on", b))
    seen: Set[Tuple[str, str, str]] = set()
    uniq = []
    for a, rel, b in out:
        if (own[a], rel, own[b]) not in seen:
            seen.add((own[a], rel, own[b]))
            uniq.append((a, rel, b))
    return uniq


def _derived_stated(cur: Any, ids: Sequence[str], root: Any, on: Set[str]) -> Dict[Tuple[str, str, str], Dict[str, datetime]]:
    """`derived` over these posts' current ent-v5 mentions (pins read): {(a root, b root, relation): {post: date}}.
    0234: a `based_on` pair stands only when its check (kind `derive`) settled `derived`."""
    cur.execute(f"""SELECT m.post_id::text, m.name, m.span, m.type, m.role, m.maker, m.entity_id::text, {_date()},
                          (SELECT x.entity_id::text FROM mx_entity_pins x WHERE x.undone_at IS NULL AND x.post_id = m.post_id
                              AND x.guide = m.guide AND x.n = m.n ORDER BY x.created_at DESC LIMIT 1), m.call_id::text
                     FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                    WHERE m.post_id = ANY(%s::uuid[]) AND m.guide = %s ORDER BY m.post_id, m.n""", (list(ids), DERIVED_GUIDE))
    posts: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    dates: Dict[str, datetime] = {}
    for pid, name, span, typ, role, maker, eid, at, pin, call in cur.fetchall():
        if at is not None:
            posts[pid].append({"name": name, "span": span, "type": typ, "role": role, "maker": maker, "eid": pin or eid,
                               "call": call})
            dates[pid] = at
    found = []
    for pid, ms in posts.items():
        for a, rel, b in derived(ms, on):
            if ms[a]["eid"] and ms[b]["eid"]:
                ra, rb = root(ms[a]["eid"]), root(ms[b]["eid"])
                if ra != rb:
                    found.append(((ra, rb, rel), pid, dates[pid],
                                  *[(x["eid"], x["maker"], x["type"], x["name"]) for x in (ms[a], ms[b])]))
    out = _same_makers(cur, found, root)
    based = [t for t in out if t[2] == "based_on"]
    if based:
        said = derive_verdicts(cur, [(a, b) for a, b, _ in based], root)
        for t in based:
            if (said.get((t[0], t[1])) or {}).get("relation") != DERIVE_YES:
                del out[t]
    return out


# ---- 0234: based_on from new posts, checked by a small question of its own ------------------------------------------
# ent-v5's `predecessor` is a candidate, not a relation (0224: the subject based_on each predecessor was 20/33 right: a
# predecessor is mostly what the subject replaces or is compared with). Each (subject, predecessor) pair one post's
# reading names in one window is asked once (kind `derive`, guide derive-v1, a = the subject's root, b = the
# predecessor's): that window's text and the two names; `derived` (made from it) is the only answer that makes the edge.
# The jobs process plans it (tasks.BACKGROUND_PLANNED, like the chains); the decision run's graph stage writes the edges
# (`stated` reads the settled verdicts; `_relation_scope` reads again the posts of the pairs answered since). Measured on
# a frozen held-out base-cue set (plan/issues/0234).
DERIVE_KIND, DERIVE_GUIDE = "derive", "derive-v1"
DERIVE_YES = "derived"
DERIVE_RUNS = 3                        # answers a pair is asked for; an edge needs all of them to say derived
DERIVE_PLAN_MAX = 200                  # new questions a pass, at most
DERIVE_MARK = "derive_planned"         # mx_settings: the last pass's clock (the readings since are read)
DERIVE_CHARS = 3500                    # the window's text a question shows, at most (its head and both names' places)
DERIVE_AROUND = 600


def derive_config() -> Dict[str, Any]:
    """entity_bands.json `relations.derive`: `ask` (the planner asks the checks; off: nothing is asked) and `runs`."""
    from insight_core.markx import identity as I
    got = (I.bands().get("relations") or {}).get("derive") or {}
    return {"ask": bool(got.get("ask", False)), "runs": max(1, int(got.get("runs", DERIVE_RUNS)))}


def _excerpt(text: str, spans: Sequence[Optional[str]], limit: int = DERIVE_CHARS, around: int = DERIVE_AROUND) -> str:
    """The window's text as a question shows it (pure): the whole when short; else its head and the place of each name
    (`spans`, the first time each is written), cut marks between."""
    text = text or ""
    if len(text) <= limit:
        return text
    head = max(limit - 2 * (2 * around), limit // 3)
    cover = [(0, head)]
    for s in spans:
        i = text.find(s) if s else -1
        if i < 0 or any(lo <= i < hi for lo, hi in cover):
            continue
        cover.append((max(0, i - around), min(len(text), i + len(s) + around)))
    cover.sort()
    out, end = [], 0
    for lo, hi in cover:
        lo = max(lo, end)
        if hi <= lo:
            continue
        out.append(("" if lo == 0 else " [...] ") + text[lo:hi])
        end = hi
    return "".join(out) + (" [...]" if end < len(text) else "")


def derive_question(a: Dict[str, Any], b: Dict[str, Any], window: str) -> str:
    """One derive item (pure): A and B (each its name, type and how the post writes it) and the POST (the reading's own
    window: its header lines and its text, cut around both names)."""
    from insight_core.markx import names as N
    head, _, text = (window or "").partition("\nText: ")

    def side(tag: str, m: Dict[str, Any]) -> str:
        shown = f' (written "{m["span"]}")' if m.get("span") and N.key(m["span"]) != N.key(m.get("name")) else ""
        return f'{tag}: "{m.get("name")}" ({m.get("type") or "thing"}){shown}'
    return "\n".join([side("A", a), side("B", b), "POST:", head, "Text: " + _excerpt(text, [a.get("span"), b.get("span")])])


def derive_verdict(answers: Sequence[Tuple[str, Dict[str, Any]]], runs: int = DERIVE_RUNS) -> Optional[Dict[str, Any]]:
    """A pair's settled verdict from its first `runs` valid answers [(call id, answer)], oldest first: the relation all
    of them give, "unknown" when they differ; None until `runs` came. Pure."""
    got = list(answers)[:runs]
    if len(got) < runs:
        return None
    rels = [str(x.get("relation")) for _, x in got]
    return {"relation": rels[0] if len(set(rels)) == 1 else UNKNOWN, "call": got[0][0], "runs": rels}


def derive_after_answer(cur: Any, task: Dict[str, Any]) -> bool:
    """A derive task's valid answer (tasks.record): open again until it has the configured runs."""
    cur.execute("SELECT count(*) FROM mx_calls WHERE task_id = %s AND valid", (task["id"],))
    if cur.fetchone()[0] >= derive_config()["runs"]:
        return False
    cur.execute("UPDATE mx_tasks SET status = 'open', lease_until = NULL, leased_by = NULL WHERE id = %s", (task["id"],))
    return cur.rowcount == 1


def derive_verdicts(cur: Any, pairs: Sequence[Tuple[str, str]], root: Any) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(a root, b root): the settled verdict} of the asked pairs among `pairs` (each side's root now: a merge after the
    ask keeps the answer); the newest task of a pair decides."""
    want = {(a, b) for a, b in pairs}
    if not want:
        return {}
    cur.execute("""SELECT t.id::text, t.a::text, t.b::text FROM mx_tasks t
                    WHERE t.kind = %s AND t.status = 'answered' AND t.b = ANY(%s::uuid[])
                       OR t.kind = %s AND t.status = 'answered' AND t.b IN (
                          SELECT r.from_id FROM mx_entity_redirects r WHERE r.undone_at IS NULL AND r.to_id = ANY(%s::uuid[]))
                    ORDER BY t.created_at, t.id""",
                (DERIVE_KIND, sorted({b for _, b in want}), DERIVE_KIND, sorted({b for _, b in want})))
    tasks_of: Dict[Tuple[str, str], str] = {}
    for tid, a, b in cur.fetchall():
        k = (root(a), root(b))
        if k in want:
            tasks_of[k] = tid
    if not tasks_of:
        return {}
    cur.execute("""SELECT task_id::text, id::text, answer FROM mx_calls WHERE valid AND task_id = ANY(%s::uuid[])
                    ORDER BY created_at, ctid""", (sorted(set(tasks_of.values())),))
    calls: Dict[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
    for tid, cid, ans in cur.fetchall():
        calls[tid].append((cid, ans or {}))
    runs = derive_config()["runs"]
    out = {}
    for k, tid in tasks_of.items():
        v = derive_verdict(calls.get(tid) or [], runs)
        if v:
            out[k] = v
    return out


def derive_candidates(cur: Any, *, since: Optional[datetime], limit: int) -> Tuple[List[Dict[str, Any]], Optional[datetime]]:
    """The (subject, predecessor) pairs of the ent-v5 readings made since `since` (every one when None), oldest call
    first, at most `limit` calls: [{post, a, b (their mentions: name, span, type, eid), window}] and the newest call's
    time read (None: every call since was read)."""
    cur.execute(f"""SELECT c.id::text, c.created_at FROM mx_calls c
                     WHERE c.valid AND (%s::timestamptz IS NULL OR c.created_at >= %s) AND EXISTS (
                           SELECT 1 FROM mx_mentions_now m WHERE m.call_id = c.id AND m.guide = %s AND m.role = 'predecessor'
                              AND m.type = ANY(%s))
                     ORDER BY c.created_at, c.id LIMIT %s""", (since, since, DERIVED_GUIDE, list(THING_TYPES), limit + 1))
    rows = cur.fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return [], None
    cur.execute("""SELECT m.call_id::text, m.post_id::text, m.n, m.name, m.span, m.type, m.role, m.maker, m.entity_id::text,
                          (SELECT x.entity_id::text FROM mx_entity_pins x WHERE x.undone_at IS NULL AND x.post_id = m.post_id
                              AND x.guide = m.guide AND x.n = m.n ORDER BY x.created_at DESC LIMIT 1), t.input
                     FROM mx_mentions_now m JOIN mx_calls c ON c.id = m.call_id JOIN mx_tasks t ON t.id = c.task_id
                    WHERE m.call_id = ANY(%s::uuid[]) AND m.guide = %s ORDER BY m.call_id, m.n""",
                ([r[0] for r in rows], DERIVED_GUIDE))
    calls: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    window: Dict[str, Tuple[str, str]] = {}
    for cid, pid, _n, name, span, typ, role, maker, eid, pin, inp in cur.fetchall():
        calls[cid].append({"name": name, "span": span, "type": typ, "role": role, "maker": maker, "eid": pin or eid,
                           "call": cid})
        window[cid] = (pid, inp or "")
    out = []
    for cid, _at in rows:
        ms = calls.get(cid) or []
        for a, _rel, b in derived(ms, ("based_on",)):
            if ms[a]["eid"] and ms[b]["eid"]:
                out.append({"post": window[cid][0], "a": ms[a], "b": ms[b], "window": window[cid][1]})
    return out, (rows[-1][1] if more else None)


def plan_derive(cur: Any, *, now: Optional[datetime] = None, limit: int = DERIVE_PLAN_MAX) -> Dict[str, int]:
    """The jobs process's plan job (tasks.BACKGROUND_PLANNED): the (subject, predecessor) pairs of the readings made
    since the last pass (mx_settings DERIVE_MARK), each pair of roots asked once (a = the subject, b = the
    predecessor), at most `limit` new questions a pass; the mark moves to where it stopped. {pairs, asked, again}."""
    from insight_core.markx import identity as I, repo, tasks
    now = now or datetime.now(timezone.utc)
    out: Dict[str, int] = {"pairs": 0, "asked": 0, "again": 0}
    if not derive_config()["ask"] or "based_on" not in relations_on():
        return out
    mark = repo.get_setting(cur, DERIVE_MARK, default=None) or {}
    since = datetime.fromisoformat(mark["at"]) - MARGIN if mark.get("at") else None
    cands, stopped = derive_candidates(cur, since=since, limit=limit * 4)
    book = I.lazy_book(cur)
    book.ents.want({m["eid"] for c in cands for m in (c["a"], c["b"])})
    pairs: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for c in cands:
        if c["a"]["eid"] in book.ents and c["b"]["eid"] in book.ents:
            k = (book.root(c["a"]["eid"]), book.root(c["b"]["eid"]))
            if k[0] != k[1]:
                pairs.setdefault(k, c)
    out["pairs"] = len(pairs)
    if pairs:
        keys = sorted(pairs)
        cur.execute("""SELECT a::text, b::text FROM mx_tasks WHERE kind = %s
                        AND (a, b) IN (SELECT * FROM unnest(%s::uuid[], %s::uuid[]))""",
                    (DERIVE_KIND, [k[0] for k in keys], [k[1] for k in keys]))
        asked = {tuple(r) for r in cur.fetchall()}
        for k in keys:
            if k in asked:
                out["again"] += 1
                continue
            if out["asked"] >= limit:
                break
            c = pairs[k]
            _tid, new = tasks.add(cur, DERIVE_KIND, derive_question(c["a"], c["b"], c["window"]), a=k[0], b=k[1])
            out["asked"] += bool(new)
    if out["asked"] < limit:
        repo.set_setting(cur, DERIVE_MARK, {"at": (stopped or now).isoformat()})
    return out


def stated(cur: Any, post_ids: Sequence[str], root: Any) -> Dict[Tuple[str, str, str], Dict[str, datetime]]:
    """{(a root, b root, relation): {post: its date}}: what these posts' current entities answers state, each side one
    of that answer's mentions (pins read), the relations switched on, never an entity to itself; and (0224) what
    their ent-v5 readings' fields say (`derived`), the derived relations switched on."""
    ids = sorted(set(post_ids))
    out = _stated_answers(cur, ids, root)
    d_on = derived_on() if ids else set()
    if d_on:
        for t, dates in _derived_stated(cur, ids, root, d_on).items():
            out.setdefault(t, {}).update(dates)
    return out


def _stated_answers(cur: Any, ids: Sequence[str], root: Any) -> Dict[Tuple[str, str, str], Dict[str, datetime]]:
    """The relations the answers' own `relations` state (ent-v3 / ent-v4.2, 0220)."""
    from insight_core.markx import names as N, schemas
    on = relations_on()
    if not on or not ids:
        return {}
    guides = schemas.mention_guides()
    cur.execute(f"""SELECT DISTINCT m.post_id::text, m.call_id::text, c.answer->'relations', {_date()}
                      FROM mx_mentions_now m JOIN mx_calls c ON c.id = m.call_id JOIN posts p ON p.id = m.post_id
                     WHERE m.post_id = ANY(%s::uuid[]) AND m.guide = ANY(%s)
                       AND jsonb_typeof(c.answer->'relations') = 'array' AND c.answer->'relations' <> '[]'::jsonb""",
                (ids, guides))
    calls = {cid: (pid, rels, at) for pid, cid, rels, at in cur.fetchall() if at is not None}
    if not calls:
        return {}
    cur.execute("""SELECT m.call_id::text, m.post_id::text, m.guide, m.n, m.name, m.span, m.entity_id::text, m.maker,
                          (SELECT x.entity_id::text FROM mx_entity_pins x WHERE x.undone_at IS NULL AND x.post_id = m.post_id
                              AND x.guide = m.guide AND x.n = m.n ORDER BY x.created_at DESC LIMIT 1), m.type
                     FROM mx_mentions_now m WHERE m.call_id = ANY(%s::uuid[]) ORDER BY m.call_id, m.n""", (sorted(calls),))
    names: Dict[str, Dict[str, Tuple[str, Optional[str], Optional[str], Optional[str]]]] = defaultdict(dict)
    for cid, _pid, _g, _n, name, span, eid, maker, pin, typ in cur.fetchall():
        eid = pin or eid
        if eid:
            for k in (N.key(name), N.key(span)):
                if k:
                    names[cid].setdefault(k, (eid, maker, typ, name))
    found = []
    for cid, (pid, rels, at) in calls.items():
        for r in rels if isinstance(rels, list) else []:
            if not isinstance(r, dict) or r.get("rel") not in on:
                continue
            a, b = names[cid].get(N.key(r.get("a"))), names[cid].get(N.key(r.get("b")))
            if not a or not b or not corroborated(r["rel"], r.get("a") or "", b[1]):
                continue
            ra, rb = root(a[0]), root(b[0])
            if ra != rb:
                found.append(((ra, rb, r["rel"]), pid, at, a, b))
    return _same_makers(cur, found, root)


def _same_makers(cur: Any, found: Sequence[Tuple[Tuple[str, str, str], str, datetime, Tuple, Tuple]],
                 root: Any) -> Dict[Tuple[str, str, str], Dict[str, datetime]]:
    """0230: the relations found, each side's post about the entity's own maker (identity.namesakes: never another
    maker's thing of the name): {(a root, b root, relation): {post: date}}. A side: (entity, maker, type, name)."""
    from insight_core.markx import identity as I
    sides = [(t[k], s[2], s[1], s[3]) for t, _p, _at, a, b in found for k, s in ((0, a), (1, b))]
    bad = I.namesakes(cur, sides, root)
    out: Dict[Tuple[str, str, str], Dict[str, datetime]] = defaultdict(dict)
    for k, (t, pid, at, _a, _b) in enumerate(found):
        if 2 * k not in bad and 2 * k + 1 not in bad:
            out[t][pid] = at
    return out


def _stated_current(cur: Any, post_ids: Optional[Sequence[str]] = None,
                    pairs: Optional[Sequence[Tuple[str, str, str]]] = None) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    """The current `stated` edges citing one of `post_ids`, or of `pairs`: {(a, b, relation): evidence}."""
    where, params = ["valid_to IS NULL", "a_kind = 'entity'", "b_kind = 'entity'", "rule = %s"], [RULE_STATED]
    if post_ids is not None:
        where.append("evidence->'posts' ?| %s::text[]")
        params.append(sorted(set(post_ids)))
    if pairs is not None:
        where.append("(a, b, relation) IN (SELECT * FROM unnest(%s::uuid[], %s::uuid[], %s::text[]))")
        params += [[p[0] for p in pairs], [p[1] for p in pairs], [p[2] for p in pairs]]
    cur.execute(f"SELECT a::text, b::text, relation, evidence FROM mx_connections WHERE {' AND '.join(where)}", params)
    return {(a, b, rel): ev or {} for a, b, rel, ev in cur.fetchall()}


def sync_relations(cur: Any, post_ids: Iterable[str], root: Any, *, now: datetime, run_id: Any) -> Counter:
    """These posts' stated relations become exactly what their answers state now: a post joins an edge's evidence
    (opening it, valid from its date), leaves the evidence of one it no longer states; an edge with no post left
    closes (kept). RELATIONS_BATCH posts at a time."""
    ids = sorted({str(p) for p in post_ids})
    counts: Counter = Counter()
    for k in range(0, len(ids), RELATIONS_BATCH):
        part = ids[k:k + RELATIONS_BATCH]
        want = stated(cur, part, root)
        have = _stated_current(cur, post_ids=part)
        have.update(_stated_current(cur, pairs=[t for t in want if t not in have]) if want else {})
        mine = set(part)
        for t in sorted(set(want) | set(have)):
            ev = have.get(t)
            posts = {p: at for p, at in ((ev or {}).get("dates") or {}).items() if p not in mine}
            posts.update({p: at.isoformat() for p, at in want.get(t, {}).items()})
            if ev is None:
                first = min(want[t].values())
                cur.execute("""INSERT INTO mx_connections (a_kind, a, b_kind, b, relation, p, rule, run_id, evidence, valid_from)
                               VALUES ('entity', %s, 'entity', %s, %s, 1.0, %s, %s, %s::jsonb, %s)
                               ON CONFLICT (a_kind, a, b_kind, b, relation) WHERE valid_to IS NULL DO NOTHING""",
                            (t[0], t[1], t[2], RULE_STATED, run_id, _evidence(posts), first))
                counts["opened"] += cur.rowcount
            elif not posts:
                cur.execute("""UPDATE mx_connections SET valid_to = GREATEST(valid_from, %s)
                                WHERE a_kind = 'entity' AND a = %s AND b_kind = 'entity' AND b = %s AND relation = %s
                                  AND valid_to IS NULL""", (now, *t))
                counts["closed"] += cur.rowcount
            elif posts != (ev.get("dates") or {}):
                cur.execute("""UPDATE mx_connections SET evidence = %s::jsonb
                                WHERE a_kind = 'entity' AND a = %s AND b_kind = 'entity' AND b = %s AND relation = %s
                                  AND valid_to IS NULL""", (_evidence(posts), *t))
                counts["evidence"] += cur.rowcount
    counts["posts"] = len(ids)
    return counts


def _evidence(dates: Dict[str, str]) -> str:
    """{posts (oldest first), since, dates {post: iso date}}."""
    order = sorted(dates, key=lambda p: (dates[p], p))
    return json.dumps({"posts": order, "since": dates[order[0]] if order else None, "dates": dates})


def _derived_sql(alias: str = "m") -> str:
    """SQL: the mention row `alias` (mx_mentions_now) may say a derived relation (0224); FALSE when none is on."""
    on = derived_on()
    parts = (["{a}.type IN ('model', 'product', 'software') AND {a}.role = 'subject' AND {a}.maker IS NOT NULL"]
             if "released" in on else []) + \
            (["{a}.type IN ('model', 'product', 'software') AND {a}.role = 'predecessor'"] if "based_on" in on else [])
    if not parts:
        return "FALSE"
    return f"({alias}.guide = '{DERIVED_GUIDE}' AND (" + " OR ".join(f"({p.format(a=alias)})" for p in parts) + "))"


def _relation_scope(cur: Any, since: datetime, counts: Optional[Dict[str, Any]] = None) -> Set[str]:
    """The posts whose entities answer stating a relation is new since, and the evidence posts of the stated edges
    whose side is no longer a root (merged since: they open again on the root). `counts` (v10.25, 0226): how many
    posts each read found and its seconds (the run's `graph.relations.scope`; 0225 #16 is measured there first)."""
    from insight_core.markx import schemas
    t0 = time.monotonic()
    cur.execute(f"""SELECT DISTINCT m.post_id::text FROM mx_mentions_now m JOIN mx_calls c ON c.id = m.call_id
                    WHERE m.guide = ANY(%s) AND c.created_at >= %s
                      AND ((jsonb_typeof(c.answer->'relations') = 'array' AND c.answer->'relations' <> '[]'::jsonb)
                           OR {_derived_sql()}
                           OR EXISTS (SELECT 1 FROM mx_connections x WHERE x.valid_to IS NULL AND x.rule = %s
                                        AND x.a_kind = 'entity' AND x.evidence->'posts' ? m.post_id::text))""",
                (schemas.mention_guides(), since, RULE_STATED))
    out = {r[0] for r in cur.fetchall()}   # a post read again that states nothing now leaves its edges' evidence
    if "based_on" in derived_on():   # 0234: the posts naming a predecessor whose pair's check was answered since
        cur.execute("""SELECT DISTINCT m.post_id::text FROM mx_tasks t
                         JOIN mx_mentions_now m ON m.guide = %s AND m.role = 'predecessor' AND (m.entity_id = t.b
                              OR m.entity_id IN (SELECT r.from_id FROM mx_entity_redirects r
                                                  WHERE r.undone_at IS NULL AND r.to_id = t.b))
                        WHERE t.kind = %s AND t.answered_at >= %s""", (DERIVED_GUIDE, DERIVE_KIND, since))
        out |= {r[0] for r in cur.fetchall()}
    t1 = time.monotonic()
    cur.execute("""SELECT DISTINCT jsonb_array_elements_text(x.evidence->'posts') FROM mx_connections x
                    WHERE x.valid_to IS NULL AND x.rule = %s AND x.a_kind = 'entity'
                      AND EXISTS (SELECT 1 FROM mx_entity_redirects r WHERE r.undone_at IS NULL AND r.from_id IN (x.a, x.b))""",
                (RULE_STATED,))
    merged = {r[0] for r in cur.fetchall()}
    if counts is not None:
        counts.update(since_posts=len(out), merged_posts=len(merged), since_seconds=round(t1 - t0, 3),
                      merged_seconds=round(time.monotonic() - t1, 3))
    return out | merged


def _relations_backfill(cur: Any, root: Any, *, now: datetime, run_id: Any, deadline: Optional[float]) -> Dict[str, Any]:
    """Every post whose entities answer states a relation, once (then only what changes), in post id order,
    RELATIONS_BATCH at a time until the deadline; resumable (mx_settings RELATIONS_KEY)."""
    from insight_core.markx import repo, schemas
    state = dict(repo.get_setting(cur, RELATIONS_KEY, default=None) or {})
    on = sorted(relations_on()) + sorted(f"derived:{r}" for r in derived_on())   # 0224: a derived one on: read again
    if state.get("version") != RELATIONS_VERSION or state.get("on") != on:   # a relation switched on: read again
        state = {"version": RELATIONS_VERSION, "on": on, "after": "", "done": False}
    if state["done"] or not on:
        return {"done": state["done"]}
    counts: Counter = Counter()
    while True:
        cur.execute(f"""SELECT DISTINCT m.post_id::text FROM mx_mentions_now m JOIN mx_calls c ON c.id = m.call_id
                        WHERE m.guide = ANY(%s) AND (%s = '' OR m.post_id > %s::uuid)
                          AND ((jsonb_typeof(c.answer->'relations') = 'array' AND c.answer->'relations' <> '[]'::jsonb)
                               OR {_derived_sql()})
                        ORDER BY 1 LIMIT %s""", (schemas.mention_guides(), state["after"], state["after"] or None,
                                                 RELATIONS_BATCH))
        part = [r[0] for r in cur.fetchall()]
        if part:
            counts.update(sync_relations(cur, part, root, now=now, run_id=run_id))
            state["after"] = part[-1]
        if len(part) < RELATIONS_BATCH:
            state["done"] = True
            break
        if deadline is not None and time.monotonic() >= deadline:
            break
    repo.set_setting(cur, RELATIONS_KEY, state)
    return {"done": state["done"], **counts}


def entity_relations(cur: Any, members: Iterable[str]) -> List[Dict[str, Any]]:
    """The entity page's relations (0220): its current stated edges of the relations switched on, either side being
    one of `members` (its cluster): [{relation, direction (out: it -> other; in), other (an id), since, posts}].
    0230: and identity's based_on of another maker's thing made from a family (rule identity.FAMILY_RULE, no posts)."""
    from insight_core.markx import identity as I
    on = sorted(relations_on())
    ids = sorted(set(members))
    if not on or not ids:
        return []
    cur.execute("""SELECT a::text, b::text, relation, evidence FROM mx_connections
                    WHERE valid_to IS NULL AND rule = ANY(%s) AND a_kind = 'entity' AND b_kind = 'entity'
                      AND relation = ANY(%s) AND (a = ANY(%s::uuid[]) OR b = ANY(%s::uuid[]))""",
                ([RULE_STATED, I.FAMILY_RULE], on, ids, ids))
    mine = set(ids)
    out = []
    for a, b, rel, ev in cur.fetchall():
        ev = ev or {}
        out.append({"relation": rel, "direction": "out" if a in mine else "in", "other": b if a in mine else a,
                    "since": ev.get("since"), "posts": ev.get("posts") or []})
    return out


# ---- 2. the judge: candidates, the input, the verdicts -----------------------------------------------------

def discover(cur: Any, subjects: Subjects, scope: Iterable[str]) -> int:
    """The same-subject candidates (mx_candidates kind 'relate', source 'entity') touching the posts of `scope`, as the
    newer or the older post: the same subject entity, the older GAP_DAYS to RELATE_DAYS back, cosine >= RELATE_COS.
    How many are new."""
    from insight_core.markx import repo
    lo, hi = timedelta(days=GAP_DAYS), timedelta(days=RELATE_DAYS)
    pairs: Set[Tuple[str, str]] = set()
    of, ats = subjects.posts(scope)   # v10.23 (0218): the scope's subjects, then their roots' posts, read by need
    subjects.want({r for rs in of.values() for r in rs})
    for pid in set(scope):
        at = ats.get(pid)
        if at is None:
            continue
        for r in of.get(pid, ()):
            pairs |= {(pid, o) for o in subjects.between(r, at - hi, at - lo) if o != pid}
            pairs |= {(n, pid) for n in subjects.between(r, at + lo, at + hi) if n != pid}
    if not pairs:
        return 0
    ps = sorted(pairs)
    added = 0
    for k in range(0, len(ps), 20000):
        chunk = ps[k:k + 20000]
        cur.execute("""SELECT k.a::text, k.b::text, 1 - (ea.v <=> eb.v)
                         FROM unnest(%s::uuid[], %s::uuid[]) AS k(a, b)
                         JOIN mx_embeddings ea ON ea.post_id = k.a AND ea.model = %s
                         JOIN mx_embeddings eb ON eb.post_id = k.b AND eb.model = %s
                        WHERE 1 - (ea.v <=> eb.v) >= %s""",
                    ([a for a, _ in chunk], [b for _, b in chunk], MODEL, MODEL, RELATE_COS))
        for a, b, cos in cur.fetchall():
            added += bool(repo.add_candidate(cur, kind="relate", a=a, b=b, source="entity", score=round(float(cos), 4)))
    return added


def _side(p: Any, at: Optional[datetime]) -> str:
    """g2_sample.side: [platform | source] date, the title, the text's first EXCERPT characters (the quote too)."""
    txt = " ".join((p.text or "").split())
    if p.quote:
        txt += " [quoted post: " + " ".join(str(p.quote).split())[:400] + "]"
    day = at.astimezone(timezone.utc).isoformat()[:10] if at else ""
    return (f"[{p.kind} | {p.source}] {day}\nTitle: {p.title or '(none)'}\n"
            f"Text: {txt[:EXCERPT] + ('…' if len(txt) > EXCERPT else '') or '(no text)'}")


def relate_input(newer: Any, older: Any, *, newer_at: Optional[datetime], older_at: Optional[datetime],
                 anchor: Optional[str], docs: Sequence[str]) -> str:
    """g2_sample.render: both posts, then the two evidence lines (the newer post's words around its link to the older
    post; the outside pages both link)."""
    lines = ["NEWER POST — " + _side(newer, newer_at), "", "OLDER POST — " + _side(older, older_at), "", "EVIDENCE",
             "- The newer post links to the older post: "
             + (f"yes, around the words \"{anchor}\"" if anchor is not None else "no"),
             "- Outside pages both posts link: " + (", ".join(docs[:DOCS_SHOWN]) if docs else "none")]
    return "\n".join(lines)


LINKED = "- The newer post links to the older post: yes"


def linked(input: str) -> bool:
    """Whether a relate question was asked about an author's link (it may then only refine the edge)."""
    return LINKED in (input or "")


def _page(u: str) -> Optional[str]:
    """The lab's form of an outside page (g2_prep.links): no scheme, www, fragment or query, a page and not a home page."""
    u = re.sub(r"^https?://(www\.)?", "", (u or "").split("#")[0].strip().lower()).rstrip("/")
    if not re.search(r"(youtube\.com/watch|news\.ycombinator\.com/item)", u):
        u = re.sub(r"\?.*$", "", u)
    return u if "/" in u and len(u.split("/", 1)[1]) >= 3 else None


def shared_pages(cur: Any, a: str, b: str) -> List[str]:
    """The outside pages (kept links no stored post is at) both posts link."""
    cur.execute("""SELECT DISTINCT x.target_url FROM post_links x JOIN post_links y ON y.target_url = x.target_url
                    WHERE x.post_id = %s AND y.post_id = %s AND NOT x.boilerplate AND NOT y.boilerplate
                      AND NOT EXISTS (SELECT 1 FROM posts tp WHERE tp.normalized_url = x.target_url OR tp.url = x.target_url)
                    ORDER BY 1""", (a, b))
    return sorted({p for p in (_page(r[0]) for r in cur.fetchall()) if p})


def _dates(cur: Any, ids: Iterable[str]) -> Dict[str, datetime]:
    ids = sorted(set(ids))
    if not ids:
        return {}
    cur.execute(f"SELECT p.id::text, {_date()} FROM posts p WHERE p.id = ANY(%s::uuid[])", (ids,))
    return dict(cur.fetchall())


def plan(cur: Any, *, open_cap: int = RELATE_OPEN, now: Optional[datetime] = None, **_kw) -> int:
    """New relate tasks, newest newer post first, while fewer than `open_cap` wait (open or leased): every current
    author-link edge and every same-subject candidate with no relate task yet. How many were added."""
    from insight_core.markx import tasks
    cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = 'relate' AND status IN ('open', 'leased')")
    room = open_cap - cur.fetchone()[0]
    if room <= 0:
        return 0
    cur.execute(f"""WITH c AS (SELECT x.a, x.b, x.evidence FROM mx_connections x
                                WHERE x.valid_to IS NULL AND x.a_kind = 'post' AND x.b_kind = 'post' AND x.rule = ANY(%(rules)s)
                               UNION ALL
                               SELECT m.a, m.b, NULL FROM mx_candidates m WHERE m.kind = 'relate' AND m.source = 'entity')
                    SELECT DISTINCT ON ({_date()}, c.a, c.b) c.a::text, c.b::text, c.evidence, {_date()}
                      FROM c JOIN posts p ON p.id = c.a
                     WHERE NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = 'relate' AND t.a = c.a AND t.b = c.b)
                     ORDER BY {_date()} DESC, c.a, c.b, c.evidence IS NULL
                     LIMIT %(n)s""", {"rules": list(JUDGED_LINK_RULES), "n": room})
    picks = [(a, b, ev) for a, b, ev, _at in cur.fetchall()]
    if not picks:
        return 0
    posts = tasks.load_posts(cur, {x for a, b, _ in picks for x in (a, b)})
    dates = _dates(cur, posts)
    now = now or datetime.now(timezone.utc)
    added = 0
    for a, b, ev in picks:
        if a not in posts or b not in posts:
            continue
        anchor = None
        if ev:
            anchor = " ".join((ev.get("reason") or "").split())[:ANCHOR]
        text = relate_input(posts[a], posts[b], newer_at=dates.get(a), older_at=dates.get(b), anchor=anchor,
                            docs=shared_pages(cur, a, b))
        age = max(0, int((now - dates[a]).total_seconds() // 86400)) if dates.get(a) else 0
        got = _savepoint(cur, tasks.add, cur, "relate", text, a=a, b=b, priority=age)
        added += bool(got and got[1])
    return added


def verdict(answers: Sequence[Tuple[str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """The settled verdict of a pair's first RELATE_RUNS valid answers [(call id, answer)], oldest first: the relation
    two or more agree on (p: their share, call: the first of them), else "unknown"; None until RELATE_RUNS came, except
    a pair whose first answer settles it alone (0191, RELATE_SETTLES: that relation, p None, one run)."""
    runs = list(answers)[:RELATE_RUNS]
    if len(runs) < RELATE_RUNS:
        if runs and settles(runs[0][1]):
            rel = str(runs[0][1].get("relation"))
            reason = str(runs[0][1].get("reason") or "")
            return {"relation": rel, "p": None, "call": runs[0][0], "runs": [rel], "reasons": [reason], "reason": reason}
        return None
    rels = [str(a.get("relation")) for _, a in runs]
    top, n = Counter(rels).most_common(1)[0]
    agree = n >= 2
    relation = top if agree else UNKNOWN
    call = next((c for c, a in runs if str(a.get("relation")) == top), None) if agree else runs[0][0]
    return {"relation": relation, "p": round(n / RELATE_RUNS, 4) if agree else None, "call": call,
            "runs": rels, "reasons": [str(a.get("reason") or "") for _, a in runs],
            "reason": next((str(a.get("reason") or "") for _, a in runs if str(a.get("relation")) == top), None)
            if agree else None}


def verdicts(cur: Any, pairs: Optional[Sequence[Tuple[str, str]]] = None, *,
             since: Optional[datetime] = None) -> Dict[Tuple[str, str], Tuple[Dict[str, Any], str]]:
    """{(newer, older): (its settled verdict, its question's input)} of the relate tasks of `pairs`, or answered since
    `since`; a pair with several tasks (its posts' text changed) takes its newest settled one."""
    where, params = ["t.kind = 'relate'", "t.a IS NOT NULL", "t.b IS NOT NULL"], []
    if pairs is not None:
        if not pairs:
            return {}
        where.append("(t.a, t.b) IN (SELECT * FROM unnest(%s::uuid[], %s::uuid[]))")
        params += [[p[0] for p in pairs], [p[1] for p in pairs]]
    if since is not None:
        where.append("t.answered_at >= %s")
        params.append(since)
    cur.execute(f"""SELECT t.id::text, t.a::text, t.b::text, t.input, t.created_at FROM mx_tasks t
                     WHERE {' AND '.join(where)} ORDER BY t.created_at, t.id""", params)
    tasks_ = cur.fetchall()
    if not tasks_:
        return {}
    cur.execute("""SELECT task_id::text, id::text, answer FROM mx_calls WHERE valid AND task_id = ANY(%s::uuid[])
                    ORDER BY created_at, ctid""", ([t[0] for t in tasks_],))
    calls: Dict[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
    for tid, cid, ans in cur.fetchall():
        calls[tid].append((cid, ans or {}))
    out: Dict[Tuple[str, str], Tuple[Dict[str, Any], str]] = {}
    for tid, a, b, text, _at in tasks_:
        v = verdict(calls.get(tid) or [])
        if v is not None:
            out[(a, b)] = (v, text)
    return out


def settles(answer: Optional[Dict[str, Any]]) -> bool:
    """0191: a first answer that settles its pair without a second and third run."""
    return isinstance(answer, dict) and str(answer.get("relation")) in RELATE_SETTLES


def after_answer(cur: Any, task: Dict[str, Any]) -> bool:
    """A relate task's valid answer (tasks.record): asked again until it has RELATE_RUNS valid answers, unless its
    first answer settles it alone (0191). Whether it was opened again."""
    cur.execute("SELECT answer FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at, ctid", (task["id"],))
    got = [r[0] for r in cur.fetchall()]
    if len(got) >= RELATE_RUNS or (len(got) == 1 and settles(got[0])):
        return False
    cur.execute("UPDATE mx_tasks SET status = 'open', lease_until = NULL, leased_by = NULL WHERE id = %s", (task["id"],))
    return cur.rowcount == 1


def apply_pairs(cur: Any, pairs: Iterable[Tuple[str, str]], *, now: datetime, run_id: Any,
                found: Optional[Dict[Tuple[str, str], Tuple[Dict[str, Any], str]]] = None) -> Counter:
    """The judge's part on these pairs, from their settled verdicts:
      - an author-link edge's relation is the verdict's when it is builds_on, follows_up or same_event, else
        refers_back (never removed); the judge's own edges on that pair close;
      - a same-subject question (no link) whose verdict is meaningful is the pair's judge edge (rule NULL, its call,
        p the agreeing share, the three reasons), uncertain; next_version only where identity has none."""
    pairs = sorted(set(pairs))
    counts: Counter = Counter()
    if not pairs:
        return counts
    found = verdicts(cur, pairs) if found is None else found
    links = {(e["a"], e["b"]): e for e in _current(cur, rules=JUDGED_LINK_RULES, pairs=pairs)}
    nexts = {(e["a"], e["b"]) for e in _current(cur, rules=[RULE_NEXT], pairs=pairs)}
    judged: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for e in _current(cur, judged=True, pairs=pairs):
        judged[(e["a"], e["b"])].append(e)
    for key in pairs:
        v, text = found.get(key, (None, ""))
        link = links.get(key)
        if link is not None:
            want = v["relation"] if v and v["relation"] in REFINES else "refers_back"
            if link["relation"] != want:
                ev = {k: x for k, x in link["evidence"].items() if k != "judge"}
                if v:
                    ev["judge"] = {k: v[k] for k in ("relation", "p", "runs", "reasons")}
                _close(cur, [link], now=now)
                _open(cur, [dict(link, relation=want, evidence=ev, call=v["call"] if v and want != "refers_back" else
                                 link.get("call"))], run_id=run_id, now=now)
                counts["refined" if want != "refers_back" else "unrefined"] += 1
            counts["judge_closed"] += _close(cur, judged.get(key, []), now=now)
            continue
        want = None
        if v and not linked(text) and v["relation"] in MEANINGFUL and not (v["relation"] == "next_version" and key in nexts):
            want = v["relation"]
        stale = [e for e in judged.get(key, []) if e["relation"] != want]
        counts["judge_closed"] += _close(cur, stale, now=now)
        if want and not any(e["relation"] == want for e in judged.get(key, [])):
            counts["judge_opened"] += _open(cur, [{"a": key[0], "b": key[1], "relation": want, "p": v["p"],
                                                   "call": v["call"], "rule": None,
                                                   "evidence": {"uncertain": True, "source": "same_subject",
                                                                "reasons": v["reasons"], "runs": v["runs"],
                                                                "reason": v["reason"]}}], run_id=run_id, now=now)
    return counts


# ---- the stage ------------------------------------------------------------------------------------------------

def _since(cur: Any, now: datetime) -> datetime:
    from insight_core.markx import repo
    got = repo.get_setting(cur, SINCE_KEY, default=None)
    try:
        at = datetime.fromisoformat(got) if got else None
    except (TypeError, ValueError):
        at = None
    return (at or now - timedelta(days=1)) - MARGIN


def _subject_scope(cur: Any, since: datetime) -> Set[str]:
    """The posts whose ent-v3 subjects are new since (their call), or whose subject entity was merged or unmerged."""
    from insight_core.markx import schemas
    cur.execute("""SELECT DISTINCT m.post_id::text FROM mx_mentions_now m JOIN mx_calls c ON c.id = m.call_id
                    WHERE m.guide = ANY(%s) AND m.role = 'subject' AND c.created_at >= %s""",
                (schemas.mention_guides(), since))
    out = {r[0] for r in cur.fetchall()}
    cur.execute("""SELECT DISTINCT m.post_id::text FROM mx_entity_redirects r
                     JOIN mx_mentions_now m ON m.entity_id IN (r.from_id, r.to_id)
                    WHERE m.role = 'subject' AND (r.at >= %s OR r.undone_at >= %s)""", (since, since))
    return out | {r[0] for r in cur.fetchall()}


RELATE_BACKFILL_KEY = "graph_relate_backfill"


def _relate_backfill(cur: Any, subjects: Subjects, *, deadline: Optional[float], chunk: int = 1000) -> Dict[str, Any]:
    """Every subject post's same-subject candidates once (then only what changes since), CHUNK posts at a time."""
    from insight_core.markx import repo
    state = dict(repo.get_setting(cur, RELATE_BACKFILL_KEY, default=None) or {})
    if state.get("version") != BACKFILL_VERSION:
        state = {"version": BACKFILL_VERSION, "after": "", "done": False, "candidates": 0}
    if state["done"]:
        return {"done": True}
    added, done = 0, False
    while True:
        part = subjects.post_ids(state["after"], chunk + 1)   # v10.23 (0218): a chunk at a time, in id order
        done = len(part) <= chunk
        part = part[:chunk]
        if not part:
            break
        added += discover(cur, subjects, part)
        state["after"] = part[-1]
        if done or (deadline is not None and time.monotonic() >= deadline):
            break
    state["done"] = done
    state["candidates"] = state.get("candidates", 0) + added
    repo.set_setting(cur, RELATE_BACKFILL_KEY, state)
    return {"done": state["done"], "candidates": added}


def defer(cur: Any, linked: Iterable[str]) -> None:
    """v10.25 (0227): the posts a run's entities stage linked while its graph stage did not run (deferred by a
    concurrent update, or skipped): kept for the next graph stage, which reads them with its own (`stage`'s `linked`).
    Their answers may be older than the next stage's look-back (MARGIN), so without this their edges would wait for a
    backfill."""
    from insight_core.markx import repo
    ids = {str(p) for p in linked}
    if ids:
        repo.set_setting(cur, PENDING_KEY, sorted(ids | set(repo.get_setting(cur, PENDING_KEY, default=None) or [])))


def stage(cur: Any, *, now: datetime, run_id: Any, open_cap: int = RELATE_OPEN,
          budget: Optional[float] = BACKFILL_SECONDS, linked: Iterable[str] = ()) -> Dict[str, Any]:
    """The decision run's graph, after its entities stage: the author-link edges of what changed since the last run,
    the backfill's next share (`budget` seconds), the identity next_version edges, the relations posts state between
    entities (0220), the same-subject candidates, the settled verdicts applied, and the relate questions planned. Its
    counts.

    v10.25 (0227): `linked` is the posts whose mentions the run's entities stage linked (or linked otherwise), and the
    ones a run before kept for it (`defer`): their relations and same-subject candidates are read again whatever their
    answers' age. The scopes by an answer's time (since the last stage, less MARGIN) miss a post whose mentions were
    linked later than its answer came (a linking backlog, runs more than MARGIN apart); before, the stage also ran
    before the entities stage, so a new post's edges waited for the next run."""
    from insight_core.markx import repo
    t0 = time.monotonic()
    deadline = None if budget is None else t0 + budget
    since = _since(cur, now)
    out: Dict[str, Any] = {"since": since.isoformat()}
    kept = repo.get_setting(cur, PENDING_KEY, default=None) or []
    linked = {str(p) for p in linked} | set(kept)
    out["linked"] = len(linked)
    timing: Dict[str, float] = {}   # v10.25 (0226): each step's seconds (the server's stage: 6 s to 514 s a run)
    mark = [t0]

    def tick(step: str) -> None:
        at = time.monotonic()
        timing[step] = round(at - mark[0], 3)
        mark[0] = at
    dirty = dirty_posts(cur, since)
    state = repo.get_setting(cur, BACKFILL_KEY, default=None) or {}
    if not (state.get("done") and state.get("version") == BACKFILL_VERSION):   # the backfill reads the rest itself
        after = state.get("after") if state.get("version") == BACKFILL_VERSION else None
        dirty = {p for p in dirty if after is not None and p <= after}
    out["links"] = dict(sync_links(cur, dirty, now=now, run_id=run_id))
    tick("links")
    out["backfill"] = backfill(cur, now=now, run_id=run_id, deadline=deadline)
    tick("backfill")
    t1 = time.monotonic()
    subjects = Subjects(cur)
    out["next_version"] = dict(sync_next_version(cur, subjects, now=now, run_id=run_id))
    tick("next_version")
    # 0220: the relations posts state between entities (what changed since, then the backfill's share)
    scope: Dict[str, Any] = {}
    rels: Dict[str, Any] = dict(sync_relations(cur, _relation_scope(cur, since, scope) | linked, subjects.root, now=now,
                                               run_id=run_id))
    rels["scope"] = scope
    tick("relations")
    rels["backfill"] = _relations_backfill(cur, subjects.root, now=now, run_id=run_id,
                                           deadline=None if deadline is None else max(deadline, time.monotonic() + 5))
    out["relations"] = rels
    tick("relations_backfill")
    relate: Dict[str, Any] = {"candidates": discover(cur, subjects, _subject_scope(cur, since) | linked)}
    tick("discover")
    relate["backfill"] = _relate_backfill(cur, subjects, deadline=None if deadline is None else max(deadline, t1 + 5))
    tick("relate_backfill")
    found = verdicts(cur, since=since)
    relate.update(apply_pairs(cur, list(found), now=now, run_id=run_id, found=found))
    relate["settled"] = len(found)
    tick("verdicts")
    relate["planned"] = plan(cur, open_cap=open_cap, now=now)
    tick("plan")
    out["relate"] = relate
    repo.set_setting(cur, SINCE_KEY, now.isoformat())
    if kept:
        repo.set_setting(cur, PENDING_KEY, [])
    out["timing"] = timing
    out["seconds"] = round(time.monotonic() - t0, 3)
    return out


# ---- the post panel's Before list ---------------------------------------------------------------------------

def _shown(e: Dict[str, Any], title: Optional[str]) -> Optional[str]:
    from insight_core.utils.post_refs import shown_reason
    ev = e["evidence"] or {}
    if e["rule"] in LINK_RULES:
        return shown_reason(ev.get("reason"), ev.get("reason_kind"), title)[0]
    if e["rule"] == RULE_NEXT:
        return f"{ev.get('newer_name') or ev.get('newer')} is the next version after {ev.get('older_name') or ev.get('older')}"
    return ev.get("reason") or next((r for r in ev.get("reasons") or [] if r), None)


_RANK = {RULE_OTHER: 0, RULE_OWN: 1, RULE_SERIES: 1, RULE_NEXT: 2, None: 3}


def before(cur: Any, post_id: str, *, shown: int = BEFORE_SHOWN) -> Dict[str, Any]:
    """The older posts this post connects to, one row each (an author's link first, then identity, then the judge),
    oldest first: {"items": [{post_id, relation, rule, p, reason, uncertain, at, title, source, label}], "more"}."""
    from insight_core.markx import news
    rows = _current(cur, a=[post_id])
    best: Dict[str, Dict[str, Any]] = {}
    for e in rows:
        b = e["b"]
        if b not in best or _RANK.get(e["rule"], 3) < _RANK.get(best[b]["rule"], 3):
            best[b] = e
    posts = news._posts(cur, best)
    marks = labels(cur, post_id, list(best))
    items = []
    for b, e in best.items():
        p = posts.get(b) or {}
        at = p.get("at")
        items.append({"post_id": b, "relation": e["relation"], "rule": e["rule"], "p": e["p"],
                      "reason": _shown(e, p.get("title")), "uncertain": e["rule"] is None,
                      "at": at.isoformat() if at else None, "title": p.get("title") or None, "source": p.get("source"),
                      "byline": p.get("byline"),
                      "label": marks.get(b)})
    items.sort(key=lambda r: (r["at"] or "", r["post_id"]))
    return {"items": items[:shown], "more": max(0, len(items) - shown)}


# ---- the owner's right / wrong on an edge (mx_labels item_kind 'connection': a = the newer post, b = the older) --

EDGE_ANSWERS = ("right", "wrong", "undo")


def labels(cur: Any, newer: str, olders: Sequence[str]) -> Dict[str, Optional[str]]:
    if not olders:
        return {}
    cur.execute("""SELECT DISTINCT ON (b) b::text, answer FROM mx_labels
                    WHERE item_kind = 'connection' AND a = %s AND b = ANY(%s::uuid[]) AND labeller = 'owner'
                    ORDER BY b, created_at DESC, ctid DESC""", (newer, list(olders)))
    return {b: (None if answer == "undo" else answer) for b, answer in cur.fetchall()}


def label(cur: Any, *, newer: str, older: str, answer: str, note: Optional[str] = None) -> Dict[str, Any]:
    """The owner's ✓ / ✗ (or undo) on a current edge between two posts. ValueError: another answer; KeyError: no edge."""
    from insight_core.markx import repo
    if answer not in EDGE_ANSWERS:
        raise ValueError(f"answer: one of {', '.join(EDGE_ANSWERS)}")
    edges = [e for e in _current(cur, a=[newer]) if e["b"] == older]
    if not edges:
        raise KeyError(older)
    e = min(edges, key=lambda x: _RANK.get(x["rule"], 3))
    note = (note or "").strip()
    lid = repo.add_label(cur, item_kind="connection", a=newer, b=older, answer=answer,
                         note=f"{e['relation']}|{e['rule'] or 'judge'}" + (f"|{note}" if note else ""))
    return {"id": str(lid), "answer": answer, "label": None if answer == "undo" else answer, "relation": e["relation"]}


# ---- 4. chains between stories (issue 0219) -------------------------------------------------------------------
# A later story and an earlier one about the same exact thing (both stops on its line, markx/stops.py) get one typed
# edge: a = the later story, b = the earlier, a_kind = b_kind = 'story', rule CHAIN_RULE (the candidate rule that
# proposed them) and call_id the judge's call. decide's story connections never read or close them (their rule).

CHAIN_KIND, CHAIN_GUIDE = "chain", "chain-v1"
CHAIN_RULE = "chain_stops"            # both stories are stops of one thing (stored stop answers saying about)
CHAIN_DAYS = 30                       # the later story's first post at most this many days after the earlier's
CHAIN_PREV = 3                        # a stop is paired with at most this many stops before it (and after it)
CHAIN_RUNS = 2                        # answers a pair is asked for; an edge needs both to agree (0219 dev: same_release
                                      # 37/40 on one run, 35/36 when two runs agree)
CHAIN_PLAN_MAX = 300                  # new questions a pass, at most
CHAIN_MARK = "chains_planned"         # mx_settings: the last pass's clock (the stops answered since are paired)
CHAIN_SYNCED = "chains_synced"        # mx_settings: the last sync's clock (the pairs answered since are read again)
CHAIN_DEPTH = 3                       # links followed from a story, each way
CHAIN_SHOWN = 12                      # links shown each way, at most
CHAIN_RELATIONS = ("same_release", "same_event", "follows_up", "development", "reaction", "builds_on", "unrelated")
CHAIN_LINKS = CHAIN_RELATIONS[:-1]    # what makes an edge (unrelated makes none)


def chain_question(thing: Dict[str, Any], earlier: Tuple[Optional[str], Sequence[Any]],
                   later: Tuple[Optional[str], Sequence[Any]]) -> str:
    """One chain item: THING, the EARLIER and the LATER story (each its headline, dates and earliest posts, as the stop
    question shows a story: stops.story_lines), and the days between their first posts. Pure."""
    from insight_core.markx import stops as ST
    out = [ST.thing_line(thing), *ST.story_lines(earlier[0], earlier[1], "EARLIER STORY"),
           *ST.story_lines(later[0], later[1], "LATER STORY")]
    firsts = [min((x.at for x in side[1]), default=None) for side in (earlier, later)]
    if firsts[0] is not None and firsts[1] is not None:
        days = (firsts[1] - firsts[0]).total_seconds() / 86400
        out.append(f"GAP: the later story starts {days:.0f} days after the earlier one" if days >= 1 else
                   "GAP: the later story starts the same day as the earlier one")
    return "\n".join(out)


def chain_config() -> Dict[str, Any]:
    """entity_bands.json `chains`: `on` (the planner asks and syncs; the story page shows), `shown` (the relations a
    reader sees; the others are stored, not shown: they failed their bar) and `one_row` (0236: News makes the stories
    a current same_release edge joins one row: `release_groups`)."""
    from insight_core.markx import identity as I
    got = I.bands().get("chains") or {}
    return {"on": bool(got.get("on", False)),
            "shown": tuple(r for r in got.get("shown") or () if r in CHAIN_LINKS),
            "one_row": bool(got.get("one_row", False))}


def chain_pairs(stops: Dict[str, Sequence[Tuple[datetime, str]]], fresh: Optional[Set[str]] = None,
                *, days: int = CHAIN_DAYS, prev: int = CHAIN_PREV) -> Dict[Tuple[str, str], str]:
    """The candidate pairs {(later, earlier): thing} of each thing's stops {thing: [(first post at, story)]}: a stop
    and each of the `prev` stops before it whose first post is at most `days` earlier. `fresh`: only the pairs with a
    story in it. A pair two things propose goes to the one with the fewer stops (the narrower thing). Pure."""
    out: Dict[Tuple[str, str], str] = {}
    size = {t: len(v) for t, v in stops.items()}
    span = timedelta(days=days)
    for thing in sorted(stops):
        order = sorted(set(stops[thing]))
        for j in range(len(order)):
            for i in range(j - 1, max(-1, j - 1 - prev), -1):
                if order[j][0] - order[i][0] > span:
                    break
                key = (order[j][1], order[i][1])
                if key[0] == key[1] or (fresh is not None and not ({key[0], key[1]} & fresh)):
                    continue
                if key not in out or (size[thing], thing) < (size[out[key]], out[key]):
                    out[key] = thing
    return out


def chain_verdict(answers: Sequence[Tuple[str, Dict[str, Any]]], runs: int = CHAIN_RUNS) -> Optional[Dict[str, Any]]:
    """A pair's settled verdict from its first `runs` valid answers [(call id, answer)], oldest first: the relation all
    of them give (call: the first; reason: its reason), "unknown" when they differ; None until `runs` came."""
    got = list(answers)[:runs]
    if len(got) < runs:
        return None
    rels = [str(a.get("relation")) for _, a in got]
    same = len(set(rels)) == 1
    return {"relation": rels[0] if same else UNKNOWN, "call": got[0][0], "runs": rels,
            "reason": str(got[0][1].get("reason") or "") if same else None}


def chain_after_answer(cur: Any, task: Dict[str, Any]) -> bool:
    """A chain task's valid answer (tasks.record): open again until it has CHAIN_RUNS valid answers."""
    cur.execute("SELECT count(*) FROM mx_calls WHERE task_id = %s AND valid", (task["id"],))
    if cur.fetchone()[0] >= CHAIN_RUNS:
        return False
    cur.execute("UPDATE mx_tasks SET status = 'open', lease_until = NULL, leased_by = NULL WHERE id = %s", (task["id"],))
    return cur.rowcount == 1


def chain_stops(cur: Any, book: Any, *, since: Optional[datetime] = None
                ) -> Tuple[Dict[str, List[Tuple[datetime, str]]], Set[str]]:
    """Each thing's stops ({root: [(the story's first current member's date, story)]}: the stored stop answers saying
    about, under any name of its cluster; stories merged away or with no current member left out), and the stories
    whose stop answer came since `since` (every one when None)."""
    from insight_core.markx import stops as ST
    rows = ST.answered(cur)
    fresh = {s for s, _e, _ab, at in rows if since is None or at >= since}
    yes = [(s, e) for s, e, about, _at in rows if about]
    if not yes:
        return {}, set()
    book.ents.want({e for _, e in yes})
    first = _story_firsts(cur, sorted({s for s, _ in yes}), current=True)
    out: Dict[str, Set[Tuple[datetime, str]]] = defaultdict(set)
    for s, e in yes:
        if s in first and e in book.ents:
            out[book.root(e)].add((first[s], s))
    return {t: sorted(v) for t, v in out.items()}, fresh & set(first)


def plan_chains(cur: Any, *, now: Optional[datetime] = None, limit: int = CHAIN_PLAN_MAX) -> Dict[str, int]:
    """The jobs process's plan job (tasks.BACKGROUND_PLANNED): the settled answers made edges first (sync_chains), then
    the candidate pairs touching the stops answered since the last pass (mx_settings CHAIN_MARK), each pair asked once
    (a = the later story, b = the earlier), at most `limit` a pass, the newest later story first; the mark moves only
    when every new pair was asked. {pairs, asked, again, opened, closed}."""
    from insight_core.markx import identity as I, repo, stops as ST, tasks
    now = now or datetime.now(timezone.utc)
    out: Dict[str, int] = {"pairs": 0, "asked": 0, "again": 0}
    if not chain_config()["on"]:
        return out
    synced = (repo.get_setting(cur, CHAIN_SYNCED, default=None) or {}).get("at")
    out.update(sync_chains(cur, now=now, since=datetime.fromisoformat(synced) - MARGIN if synced else None))
    repo.set_setting(cur, CHAIN_SYNCED, {"at": now.isoformat()})
    mark = repo.get_setting(cur, CHAIN_MARK, default=None) or {}
    since = datetime.fromisoformat(mark["at"]) - MARGIN if mark.get("at") else None
    book = I.lazy_book(cur)
    stops, fresh = chain_stops(cur, book, since=since)
    pairs = chain_pairs(stops, fresh)
    out["pairs"] = len(pairs)
    todo: List[Tuple[str, str]] = []
    if pairs:
        keys = sorted(pairs)
        cur.execute("""SELECT a::text, b::text FROM mx_tasks WHERE kind = %s
                        AND (a, b) IN (SELECT * FROM unnest(%s::uuid[], %s::uuid[]))""",
                    (CHAIN_KIND, [k[0] for k in keys], [k[1] for k in keys]))
        asked = {tuple(r) for r in cur.fetchall()}
        firsts = {s: at for v in stops.values() for at, s in v}
        todo = sorted((k for k in keys if k not in asked), key=lambda k: (firsts[k[0]], k), reverse=True)
        out["again"] = len(keys) - len(todo)
    if todo[:limit]:
        shown, roles, heads = ST.stories_shown(cur, book, sorted({s for k in todo[:limit] for s in k}))
        for later, earlier in todo[:limit]:
            thing = pairs[(later, earlier)]
            text = chain_question(ST._thing(book, thing),
                                  (heads.get(earlier), ST.lines_for(shown.get(earlier, []), roles, thing)),
                                  (heads.get(later), ST.lines_for(shown.get(later, []), roles, thing)))
            _tid, new = tasks.add(cur, CHAIN_KIND, text, a=later, b=earlier, priority=0)
            out["asked"] += bool(new)
    if len(todo) <= limit:
        repo.set_setting(cur, CHAIN_MARK, {"at": now.isoformat()})
    return out


def _chain_current(cur: Any) -> List[Dict[str, Any]]:
    cur.execute("""SELECT a::text, b::text, relation FROM mx_connections
                    WHERE valid_to IS NULL AND a_kind = 'story' AND b_kind = 'story' AND rule = %s""", (CHAIN_RULE,))
    return [{"a": a, "b": b, "relation": rel} for a, b, rel in cur.fetchall()]


def sync_chains(cur: Any, *, now: datetime, run_id: Any = None, since: Optional[datetime] = None) -> Dict[str, int]:
    """The chain edges become what the settled answers say of the pairs still proposed: a linking verdict opens its
    edge (relation, p 1.0: its runs agree; the call; evidence {reason, thing, runs}); an edge whose verdict changed,
    or whose pair is no longer two stops of one thing (a stop answer now saying not about, a story merged away or
    emptied), closes (kept, never deleted). `since`: only the pairs with an answer since then are read again (every
    current edge is still checked against the pairs proposed). Every relation is stored; what is shown is
    chain_config's."""
    from insight_core.markx import identity as I
    stops, _ = chain_stops(cur, I.lazy_book(cur))
    cands = chain_pairs(stops)
    cur.execute(f"""SELECT DISTINCT ON (t.a, t.b) t.a::text, t.b::text, t.id::text FROM mx_tasks t
                     WHERE t.kind = %(k)s AND t.status = 'answered'
                       {"AND (t.a, t.b) IN (SELECT a, b FROM mx_tasks WHERE kind = %(k)s AND answered_at >= %(since)s)"
                        if since is not None else ""}
                     ORDER BY t.a, t.b, t.created_at DESC, t.id DESC""", {"k": CHAIN_KIND, "since": since})
    got = cur.fetchall()
    touched = {(a, b) for a, b, _t in got}
    newest = {(a, b): tid for a, b, tid in got if (a, b) in cands}
    calls: Dict[str, List[Tuple[str, Dict[str, Any]]]] = defaultdict(list)
    ids = sorted(newest.values())
    for k in range(0, len(ids), 5000):
        cur.execute("""SELECT task_id::text, id::text, answer FROM mx_calls WHERE valid AND task_id = ANY(%s::uuid[])
                        ORDER BY created_at, ctid""", (ids[k:k + 5000],))
        for tid, cid, ans in cur.fetchall():
            calls[tid].append((cid, ans or {}))
    want: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for key, tid in newest.items():
        v = chain_verdict(calls.get(tid) or [])
        if v and v["relation"] in CHAIN_LINKS:
            want[key] = dict(v, thing=cands[key])
    out = {"opened": 0, "closed": 0}
    kept = set()
    for e in _chain_current(cur):
        key = (e["a"], e["b"])
        if key in cands and (key not in touched or (key in want and want[key]["relation"] == e["relation"])):
            kept.add(key)
            continue
        cur.execute("""UPDATE mx_connections SET valid_to = GREATEST(valid_from, %s)
                        WHERE a_kind = 'story' AND a = %s AND b_kind = 'story' AND b = %s AND relation = %s
                          AND rule = %s AND valid_to IS NULL""", (now, e["a"], e["b"], e["relation"], CHAIN_RULE))
        out["closed"] += cur.rowcount
    for (a, b), v in sorted(want.items()):
        if (a, b) in kept:
            continue
        cur.execute("""INSERT INTO mx_connections (a_kind, a, b_kind, b, relation, p, call_id, rule, run_id, evidence, valid_from)
                       VALUES ('story', %s, 'story', %s, %s, 1.0, %s, %s, %s, %s::jsonb, %s)
                       ON CONFLICT (a_kind, a, b_kind, b, relation) WHERE valid_to IS NULL DO NOTHING""",
                    (a, b, v["relation"], v["call"], CHAIN_RULE, run_id,
                     json.dumps({"reason": v["reason"], "thing": v["thing"], "runs": v["runs"]}, ensure_ascii=False), now))
        out["opened"] += cur.rowcount
    return out


def chain(cur: Any, story_id: str, *, as_of: Optional[datetime] = None, depth: int = CHAIN_DEPTH,
          shown: int = CHAIN_SHOWN, relations: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """A story's chain: what led to it (`before`: the earlier stories its edges reach, then theirs, `depth` links at
    most) and what followed (`after`), each link {story, headline, first_at, relation, reason, depth, via}, the nearest
    first, then by date, `shown` a side (`before_more`, `after_more`: the rest); `as_of`: only the edges valid at that
    moment (what INSIGHT knew then). `relations`: those shown (chain_config's by default). One recursive query a side;
    nothing is asked."""
    rels = list(chain_config()["shown"] if relations is None else relations)
    out: Dict[str, Any] = {"before": [], "after": [], "before_more": 0, "after_more": 0,
                           "as_of": as_of.isoformat() if as_of else None}
    if not rels:
        return out
    for side, near, far in (("before", "a", "b"), ("after", "b", "a")):
        cur.execute(f"""
            WITH RECURSIVE walk(story, via, relation, reason, depth, seen) AS (
                SELECT x.{far}, x.{near}, x.relation, x.evidence->>'reason', 1, ARRAY[x.{near}, x.{far}]
                  FROM mx_connections x
                 WHERE x.{near} = %(s)s::uuid AND {_CHAIN_VALID}
                UNION ALL
                SELECT x.{far}, x.{near}, x.relation, x.evidence->>'reason', w.depth + 1, w.seen || x.{far}
                  FROM walk w JOIN mx_connections x ON x.{near} = w.story
                 WHERE w.depth < %(depth)s AND NOT x.{far} = ANY(w.seen) AND {_CHAIN_VALID})
            SELECT DISTINCT ON (w.story) w.story::text, w.via::text, w.relation, w.reason, w.depth, s.headline
              FROM walk w JOIN mx_stories s ON s.id = w.story
             ORDER BY w.story, w.depth, w.relation""",
                    {"rels": rels, "at": as_of or datetime.now(timezone.utc), "s": story_id,
                     "depth": depth})
        rows = cur.fetchall()
        firsts = _story_firsts(cur, [r[0] for r in rows])
        items = [{"story": s, "via": via, "relation": rel, "reason": reason, "depth": d, "headline": head,
                  "first_at": firsts[s].isoformat() if firsts.get(s) else None}
                 for s, via, rel, reason, d, head in rows]
        items.sort(key=lambda r: (r["depth"], r["first_at"] or "", r["story"]))
        out[side] = items[:shown]
        out[side + "_more"] = max(0, len(items) - shown)
    return out


def release_components(edges: Iterable[Tuple[str, str, Optional[str]]]) -> List[List[str]]:
    """0236: the one-release groups of these same_release edges [(a, b, thing)]: each story keeps only the edges of
    its own release thing (the thing most of its edges are about, then the lowest id), so a group is one thing and a
    story that is a stop of two things never chains them; each group 2+ stories, sorted. Pure."""
    edges = sorted((str(a), str(b), str(t or "")) for a, b, t in edges if a != b)
    by: Dict[str, Counter] = defaultdict(Counter)
    for a, b, t in edges:
        by[a][t] += 1
        by[b][t] += 1
    own = {s: min(c, key=lambda t: (-c[t], t)) for s, c in by.items()}
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            x = parent[x]
        return x
    for a, b, t in edges:
        if own[a] == t and own[b] == t:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)
    groups: Dict[str, List[str]] = defaultdict(list)
    for s in sorted(by):
        groups[find(s)].append(s)
    return sorted(g for g in groups.values() if len(g) >= 2)


def release_groups(cur: Any, story_ids: Iterable[str]) -> List[List[str]]:
    """0236 (the one-release row, 0217's input): the groups of `story_ids` the current same_release chain edges join
    (`release_components`: one thing a group); [] while chain_config's `one_row` is off. An edge is between two stops
    of one exact thing (stop-v1 says each story is about it), so a story that only mentions the thing is in none (the
    runaway guard). One read of the chain rows."""
    ids = sorted({str(s) for s in story_ids if s})
    if not ids or not chain_config().get("one_row"):
        return []
    cur.execute(f"""SELECT a::text, b::text, evidence->>'thing' FROM mx_connections
                     WHERE valid_to IS NULL AND a_kind = 'story' AND b_kind = 'story' AND rule = '{CHAIN_RULE}'
                       AND relation = 'same_release' AND a = ANY(%(s)s::uuid[]) AND b = ANY(%(s)s::uuid[])""", {"s": ids})
    return release_components(cur.fetchall())


# the rule written as a literal, so the planner proves migration 0154's partial indexes even from a prepared plan
_CHAIN_VALID = (f"x.a_kind = 'story' AND x.b_kind = 'story' AND x.rule = '{CHAIN_RULE}' AND x.relation = ANY(%(rels)s) "
                "AND x.valid_from <= %(at)s AND (x.valid_to IS NULL OR x.valid_to > %(at)s)")


def _story_firsts(cur: Any, story_ids: Sequence[str], *, current: bool = False) -> Dict[str, datetime]:
    """{story: its first member's date} (`current`: its current members, stories merged away left out)."""
    if not story_ids:
        return {}
    cur.execute(f"""SELECT sp.story_id::text, min({pairing.post_date('p')})
                      FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id
                      {"JOIN mx_stories s ON s.id = sp.story_id AND s.merged_into IS NULL" if current else ""}
                     WHERE sp.role = 'member' AND sp.story_id = ANY(%s::uuid[]) {"AND sp.valid_to IS NULL" if current else ""}
                     GROUP BY sp.story_id""", (sorted(set(story_ids)),))
    return {s: at for s, at in cur.fetchall() if at is not None}
