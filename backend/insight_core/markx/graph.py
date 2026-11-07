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
     A link that stops resolving, or becomes boilerplate, closes its edge.
  2. **The judge** (`relate`, relate-v1 = G2's frozen judge v3, asked RELATE_RUNS times; the majority, "unknown" when
     no two agree; p = the share of the runs that agree). Candidates: the same ent-v3 subject (one entity after 0119 A
     identity) on both sides, cosine >= RELATE_COS, the older post RELATE_DAYS back at most (mx_candidates kind
     'relate', source 'entity'); and every author-link edge, so its type can be refined. A same-subject edge
     (rule NULL, its call) is "uncertain" (shown marked, with label buttons) until re-measured. On an author-link
     edge the judge only refines the relation (builds_on, follows_up, same_event); any other answer leaves it
     `refers_back`, never removes it. Planned capped like connect (`decide.Config.relate_open` open at a time).
  3. **next_version from entity identity** (no model; the judge's next_version calls were 1 of 4 right as a type):
     the newer post's subject is the version right after the older post's subject in one family (0119 A), the older
     post GAP_DAYS back or more; the predecessor's earliest NEXT_VERSION_POSTS posts. rule `entity_next_version`,
     evidence both entity keys. It replaces any judge call of next_version on that pair.

Dates are G2's: COALESCE(published_at, surfaced_at, fetched_at).
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

log = logging.getLogger(__name__)

GAP_DAYS = 30                 # the older post at least this far back (G2)
RELATE_DAYS = 180             # same-subject candidates: the older post at most this far back (G2: meaningful within 90)
RELATE_COS = 0.75             # ... at this cosine or more (G2's source b)
RELATE_RUNS = 3               # the judge asked three times a pair, the majority
RELATE_OPEN = 100             # the planner's cap (decide.Config.relate_open)
RULE_OTHER, RULE_OWN, RULE_NEXT = "author_link_other", "author_link_own", "entity_next_version"
LINK_RULES = (RULE_OTHER, RULE_OWN)
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
BEFORE_SHOWN = 10
EXCERPT = 1100                # G2's render: 1,100 characters a post
ANCHOR = 300
DOCS_SHOWN = 4
POST_DATE = "COALESCE({p}.published_at, {p}.surfaced_at, {p}.fetched_at)"
MODEL = "bge-m3"


def _date(alias: str = "p") -> str:
    return POST_DATE.format(p=alias)


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
                           r.reason_kind
                      FROM post_refs r JOIN posts p ON p.id = r.post_id
                     WHERE r.post_id = ANY(%s::uuid[]) AND r.valid_to IS NULL AND NOT r.boilerplate
                     ORDER BY r.post_id, r.position""", (ids,))
    rows = cur.fetchall()
    targets = resolve(cur, [(pid, _absolute(url, href), address) for pid, url, _s, _at, address, href, _r, _k in rows])
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    gap = timedelta(days=GAP_DAYS)
    for (pid, _url, src, at, address, href, reason, kind), got in zip(rows, targets):
        if got is None or at is None or got[2] is None:
            continue
        tid, tsrc, tat = got
        if tat > at - gap or (pid, tid) in out:
            continue
        own = tsrc == src
        out[(pid, tid)] = {"rule": RULE_OWN if own else RULE_OTHER, "p": P_OWN if own else P_OTHER,
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
    new = [dict(w, a=k[0], b=k[1], relation="refers_back") for k, w in want.items()
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
    cur.execute("SELECT DISTINCT post_id::text FROM post_refs WHERE created_at >= %s OR valid_to >= %s", (since, since))
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
    """Every post's ent-v3 subjects as their root entities (redirects read through), with the posts' dates."""

    def __init__(self, cur: Any) -> None:
        from insight_core.markx import schemas
        cur.execute("SELECT from_id::text, to_id::text FROM mx_entity_redirects WHERE undone_at IS NULL")
        self.redirect = dict(cur.fetchall())
        cur.execute(f"""SELECT m.post_id::text, m.entity_id::text, {_date()}
                          FROM mx_mentions m JOIN posts p ON p.id = m.post_id
                         WHERE m.guide = %s AND m.role = 'subject' AND m.entity_id IS NOT NULL""",
                    (schemas.KINDS["entities"].guide,))
        self.of: Dict[str, Set[str]] = defaultdict(set)
        self.at: Dict[str, datetime] = {}
        for pid, eid, at in cur.fetchall():
            if at is None:
                continue
            self.of[pid].add(self.root(eid))
            self.at[pid] = at
        self.posts: Dict[str, List[Tuple[datetime, str]]] = defaultdict(list)
        for pid, roots in self.of.items():
            for r in roots:
                self.posts[r].append((self.at[pid], pid))
        for xs in self.posts.values():
            xs.sort()

    def root(self, eid: str) -> str:
        seen = set()
        while eid in self.redirect and eid not in seen:
            seen.add(eid)
            eid = self.redirect[eid]
        return eid

    def between(self, root: str, lo: datetime, hi: datetime) -> List[str]:
        xs = self.posts.get(root) or []
        i = bisect.bisect_left(xs, (lo, ""))
        j = bisect.bisect_right(xs, (hi, "￿"))
        return [p for _, p in xs[i:j]]


# ---- 3. next_version from identity ----------------------------------------------------------------------------

def _vnorm(t: Any) -> Optional[Tuple[int, ...]]:
    """A version tuple to order by: a leading letter prefix dropped (K3.1 = 3.1, as names.ver_eq); None unless the
    rest is numbers."""
    if not t:
        return None
    t = tuple(t)
    if isinstance(t[0], str):
        t = t[1:]
    if not t or not all(isinstance(x, int) and not isinstance(x, bool) for x in t):
        return None
    while len(t) > 1 and t[-1] == 0:   # 5.0 = 5
        t = t[:-1]
    return t


def next_version_edges(cur: Any, subjects: Subjects) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(newer, older): the edge}: the newer post's subject is the next version, in one family, after the older post's
    subject; the older post GAP_DAYS back or more, the predecessor's earliest NEXT_VERSION_POSTS posts."""
    roots = sorted({r for rs in subjects.of.values() for r in rs})
    if not roots:
        return {}
    cur.execute("""SELECT id::text, level, parent::text, version_key, variant, size, build, key, name FROM mx_entities
                    WHERE id = ANY(%s::uuid[])""", (roots,))
    ents = {}
    for eid, level, parent, vkey, variant, size, build, key, name in cur.fetchall():
        v = _vnorm(vkey)
        if level != "version" or parent is None or v is None or variant or size or build:
            continue
        ents[eid] = (subjects.root(parent), v, key, name)
    family: Dict[str, Set[Tuple[int, ...]]] = defaultdict(set)
    for fam, v, _k, _n in ents.values():
        family[fam].add(v)
    order = {fam: sorted(vs) for fam, vs in family.items()}
    group: Dict[Tuple[str, Tuple[int, ...]], List[Tuple[datetime, str, str]]] = defaultdict(list)
    for pid, rs in subjects.of.items():
        for r in rs:
            if r in ents:
                fam, v, _k, _n = ents[r]
                group[(fam, v)].append((subjects.at[pid], pid, r))
    for xs in group.values():
        xs.sort()
    gap = timedelta(days=GAP_DAYS)
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for (fam, v), posts in group.items():
        vs = order[fam]
        i = vs.index(v)
        if i == 0:
            continue
        before = group.get((fam, vs[i - 1])) or []
        for at, pid, r in posts:
            olders = [(oat, op, orr) for oat, op, orr in before if oat <= at - gap and op != pid][:NEXT_VERSION_POSTS]
            for _oat, op, orr in olders:
                out[(pid, op)] = {"rule": RULE_NEXT, "p": 1.0, "relation": "next_version",
                                  "evidence": {"newer": ents[r][2], "older": ents[orr][2], "newer_name": ents[r][3],
                                               "older_name": ents[orr][3], "newer_entity": r, "older_entity": orr}}
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


# ---- 2. the judge: candidates, the input, the verdicts -----------------------------------------------------

def discover(cur: Any, subjects: Subjects, scope: Iterable[str]) -> int:
    """The same-subject candidates (mx_candidates kind 'relate', source 'entity') touching the posts of `scope`, as the
    newer or the older post: the same subject entity, the older GAP_DAYS to RELATE_DAYS back, cosine >= RELATE_COS.
    How many are new."""
    from insight_core.markx import repo
    lo, hi = timedelta(days=GAP_DAYS), timedelta(days=RELATE_DAYS)
    pairs: Set[Tuple[str, str]] = set()
    for pid in set(scope):
        at = subjects.at.get(pid)
        if at is None:
            continue
        for r in subjects.of.get(pid, ()):
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
                     LIMIT %(n)s""", {"rules": list(LINK_RULES), "n": room})
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
    two or more agree on (p: their share, call: the first of them), else "unknown"; None until RELATE_RUNS came."""
    runs = list(answers)[:RELATE_RUNS]
    if len(runs) < RELATE_RUNS:
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


def after_answer(cur: Any, task: Dict[str, Any]) -> bool:
    """A relate task's valid answer (tasks.record): asked again until it has RELATE_RUNS valid answers. Whether it
    was opened again."""
    cur.execute("SELECT count(*) FROM mx_calls WHERE task_id = %s AND valid", (task["id"],))
    if cur.fetchone()[0] >= RELATE_RUNS:
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
    links = {(e["a"], e["b"]): e for e in _current(cur, rules=LINK_RULES, pairs=pairs)}
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
    cur.execute("""SELECT DISTINCT m.post_id::text FROM mx_mentions m JOIN mx_calls c ON c.id = m.call_id
                    WHERE m.guide = %s AND m.role = 'subject' AND c.created_at >= %s""",
                (schemas.KINDS["entities"].guide, since))
    out = {r[0] for r in cur.fetchall()}
    cur.execute("""SELECT DISTINCT m.post_id::text FROM mx_entity_redirects r
                     JOIN mx_mentions m ON m.entity_id IN (r.from_id, r.to_id)
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
    ids = sorted(subjects.of)
    i = bisect.bisect_right(ids, state["after"])
    added = 0
    while i < len(ids):
        part = ids[i:i + chunk]
        added += discover(cur, subjects, part)
        state["after"] = part[-1]
        i += len(part)
        if deadline is not None and time.monotonic() >= deadline:
            break
    state["done"] = i >= len(ids)
    state["candidates"] = state.get("candidates", 0) + added
    repo.set_setting(cur, RELATE_BACKFILL_KEY, state)
    return {"done": state["done"], "candidates": added}


def stage(cur: Any, *, now: datetime, run_id: Any, open_cap: int = RELATE_OPEN,
          budget: Optional[float] = BACKFILL_SECONDS) -> Dict[str, Any]:
    """The decision run's graph, in its `connections` stage: the author-link edges of what changed since the last run,
    the backfill's next share (`budget` seconds), the identity next_version edges, the same-subject candidates, the
    settled verdicts applied, and the relate questions planned. Its counts."""
    from insight_core.markx import repo
    t0 = time.monotonic()
    deadline = None if budget is None else t0 + budget
    since = _since(cur, now)
    out: Dict[str, Any] = {"since": since.isoformat()}
    dirty = dirty_posts(cur, since)
    state = repo.get_setting(cur, BACKFILL_KEY, default=None) or {}
    if not (state.get("done") and state.get("version") == BACKFILL_VERSION):   # the backfill reads the rest itself
        after = state.get("after") if state.get("version") == BACKFILL_VERSION else None
        dirty = {p for p in dirty if after is not None and p <= after}
    out["links"] = dict(sync_links(cur, dirty, now=now, run_id=run_id))
    out["backfill"] = backfill(cur, now=now, run_id=run_id, deadline=deadline)
    t1 = time.monotonic()
    subjects = Subjects(cur)
    out["next_version"] = dict(sync_next_version(cur, subjects, now=now, run_id=run_id))
    relate: Dict[str, Any] = {"candidates": discover(cur, subjects, _subject_scope(cur, since))}
    relate["backfill"] = _relate_backfill(cur, subjects, deadline=None if deadline is None else max(deadline, t1 + 5))
    found = verdicts(cur, since=since)
    relate.update(apply_pairs(cur, list(found), now=now, run_id=run_id, found=found))
    relate["settled"] = len(found)
    relate["planned"] = plan(cur, open_cap=open_cap, now=now)
    out["relate"] = relate
    repo.set_setting(cur, SINCE_KEY, now.isoformat())
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


_RANK = {RULE_OTHER: 0, RULE_OWN: 1, RULE_NEXT: 2, None: 3}


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
