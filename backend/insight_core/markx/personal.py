"""The reader's interest (Stealth v10.42): the personal half of News' order, owned here.

News' order (markx/news_rank.py) is the GLOBAL importance of a row (its significance and coverage) times the reader's
PERSONAL interest in it. Interest is never kept per row: it is kept per **thing** (an entity), per **kind of news**
and per **source**, so one tap on a row teaches every row that shares what was tapped.

**What a row is made of** (`row_facts`, in the jobs process when the rows are ranked; kept in mx_news_rank.why's
`personal`): its things (its posts' current entities, subjects and actors first, then publishers and mentions, at
most THINGS_MAX), its kind and its posts' sources. The kind (`subtype_kind`) is its posts' ent-v6 event type and
subtype, the most common pair ("model_release/build": quants, conversions, adapters of an existing model;
"research_result/method"); a row none of whose posts has a subtype yet (read before ent-v6) falls back to `kind_of`:
the significance answer's event, and for a release of a thing by someone other than its maker (quants, ports,
hosting, day-0 support) the same build key, so one tap teaches rows read before and after ent-v6.

**What the reader taught** (`teach`, mx_interests, keep everything): "More" or "Less" of one thing, kind or source,
"none" (not a reason) or "undo" (back to what was learned); the newest row of a (dim, key) counts. Seeds (`seed`,
origin seed: the reader's stated interests) weigh SEED, a tap LABEL[dim]: a named thing counts more than a source,
a source more than a kind.

**What INSIGHT learned** (`learn`, the jobs process, mx_interest_weights, replaced each time): from what the reader
already does (post_interactions' opens and read time, post_reader_state's keeps, Laters and reading to the end), each
act decaying by HALF_LIFE_DAYS, a thing, source or kind read more than its share of the posts (`lift_weight`, smoothed
by PRIOR_POSTS) is up to IMPLICIT_MAX, one read less is down to IMPLICIT_MIN (a skip is weak); and a thing that is a
subject of TRACK_MIN+ posts of a topic track is TRACK_PRIOR (a mild prior). A taught key replaces the learned one.

**A row's interest** (`score`, pure): the things' part (the most liked thing plus the most disliked: one row never
adds up five liked things), the kind's and the sources'; when a thing the reader named disagrees with the kind, the
thing wins (a quant release of a model the reader follows rises; one of a model they do not follow sinks). The sum p
is clipped to +-P_MAX and the row's factor is exp(SCALE * p), x0.47 to x2.1. `why` names the largest reason in words
("you follow Inkling 2 Small", "you lowered 'builds of an existing model'"). v10.44: a thing counts by its role and
place in the row (`presence`: a subject or actor of the lead or of most posts fully, a mention in one member not at
all), a source by its share of the row (`source_share`: the lead's fully); a reason names a thing, source or kind by
its shown name, never an id or an address, and one with no such name is no reason (`shown_name`, `source_names`).

**Where it runs.** The facts and the learned weights in the jobs process (news_rank.keep); the API reads the taps and
the learned weights of the shown rows' keys only (`weights`: one small query each) and scores each row in Python.
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

DIMS = ("thing", "kind", "source")
ANSWERS = ("more", "less", "none", "undo")
LABEL = {"thing": 1.0, "source": 0.8, "kind": 0.7}   # a tap: a named thing counts most, a kind least
SEED = 0.6                                           # a stated interest
TRACK_PRIOR = 0.25                                   # a subject of a topic track's posts
TRACK_MIN = 3                                        # ... of this many of them
IMPLICIT_MAX, IMPLICIT_MIN = 0.4, -0.2               # what reads alone can say (measured: 0.5 let two opens
                                                     # of a rare thing outweigh a stated interest)
SURE_HALF = 2.0                                      # a liking from this much reading is half sure
HALF_LIFE_DAYS = 30.0
PROFILE_DAYS = 90
PRIOR_POSTS = 20.0                                   # a key's read share smoothed toward the overall one
LIFT_FULL = 8.0                                      # read this many times its share: IMPLICIT_MAX
WEIGHT_MIN = 0.02                                    # a learned weight smaller than this is not kept
ROLE_FACTOR = {"subject": 1.0, "actor": 1.0, "source": 0.7, "mention": 0.5}   # a learned weight, by the thing's role
ROLES = tuple(ROLE_FACTOR)
THINGS_MAX = 8
CHIPS = 5                                            # the things a row offers to teach
P_MAX, SCALE = 1.5, 0.5
SHOWN = 0.1                                          # a row's why is shown from this |p|
ACTS = {"opened": 1.0, "long_read": 0.5, "to_end": 0.5, "kept": 1.5, "later": 0.5}
LONG_READ_SECONDS = 60
POST_MAX = 3.0                                       # one post's acts, at most
RELEASES = ("new_model", "release_update", "product_launch", "new_tool")
MADE = ("model", "software", "product")
EVENT_WORDS = {"new_method": "new methods", "new_model": "new models", "new_tool": "new tools",
               "release_update": "release updates", "research_result": "research results", "benchmark": "benchmarks",
               "product_launch": "product launches", "deal_funding": "deals and funding", "policy_legal": "policy and law",
               "security_incident": "security incidents", "outage": "outages", "people": "people moves",
               "opinion_analysis": "opinion and analysis", "tutorial": "tutorials"}
BUILD = {"model": "model_release", "software": "product_release", "product": "product_release"}   # a made thing's type
SUBTYPE_WORDS = {"new_model": "new models", "build": "builds of an existing {thing} (quants, conversions, adapters, ports)",
                 "dataset": "datasets", "product": "product launches", "software": "software releases",
                 "method": "new methods", "benchmark": "benchmarks", "finding": "research findings", "guide": "guides",
                 "security": "security incidents", "failure": "outages and failures"}


def _build_kind(event_type: str) -> Dict[str, str]:
    thing = "model" if event_type == "model_release" else "product or program"
    return {"key": f"{event_type}/build", "words": SUBTYPE_WORDS["build"].format(thing=thing)}


def subtype_kind(typed: Sequence[Tuple[Optional[str], Optional[str]]]) -> Optional[Dict[str, str]]:
    """Pure: a row's kind from its posts' (event type, subtype), in the row's order: the most common pair with a
    subtype (a tie: the first given), {key "type/subtype", words}; None when no post has a subtype."""
    pairs = [(t, st) for t, st in typed if t and st]
    if not pairs:
        return None
    count = Counter(pairs)
    t, st = max(pairs, key=lambda p: count[p])      # max keeps the first of equals
    if st == "build":
        return _build_kind(t)
    return {"key": f"{t}/{st}", "words": SUBTYPE_WORDS.get(st, st.replace("_", " "))}


# ---- what a row is made of ---------------------------------------------------------------------------------

def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _same(a: str, b: str) -> bool:
    return bool(a and b) and (a.startswith(b) or b.startswith(a))


def kind_of(event: Optional[str], main: Optional[Dict[str, Any]], shippers: Sequence[str],
            named: Sequence[str] = ()) -> Optional[Dict[str, str]]:
    """A row's kind of news: {key, words}. `main` its main subject {name, type, maker}; `shippers` the organisations
    that act in it (its posts' actors); `named` who acts in it or publishes it (its actors and publishers, any kind). A
    release (RELEASES) of a made thing (MADE) whose maker is known, that an organisation ships, and whose maker neither
    acts in it nor publishes it (nor is a shipper's name the start of the thing's: Qwen ships Qwen3.8) is a build of
    someone else's thing (quants, ports, hosting, day-0 support: `_build_kind`, the key ent-v6's subtype gives); else
    the event; None for no event or "other"."""
    if event in RELEASES and main and main.get("type") in MADE and main.get("maker") and shippers:
        maker, thing = _norm(main["maker"]), _norm(main.get("name"))
        own = any(_same(_norm(n), maker) for n in list(named) + list(shippers)) \
            or any(_norm(m) and thing.startswith(_norm(m)) for m in shippers)
        if not own:
            return _build_kind(BUILD[main["type"]])
    if not event or event == "other":
        return None
    return {"key": event, "words": EVENT_WORDS.get(event, event.replace("_", " "))}


def facts_of(mentions: Sequence[Tuple[str, str, str, str, Optional[str], Optional[str]]], event: Optional[str],
             sources: Sequence[str], typed: Sequence[Tuple[Optional[str], Optional[str]]] = (),
             lead: Optional[Tuple[str, Optional[str]]] = None) -> Dict[str, Any]:
    """Pure: one row's facts from its posts' mentions [(post, role, entity id, name, type, maker)], its significance
    event, its posts' sources (one a post) and its lead (post id, source id). {things: [{id, name, type, role, posts,
    core, lead_role}], kind, sources, source_posts, n, lead_source}: `core` the posts naming the thing as subject or
    actor, `lead_role` its best role in the lead post (v10.44: what `presence` weighs)."""
    best: Dict[str, Dict[str, Any]] = {}
    posts: Dict[str, set] = defaultdict(set)
    core: Dict[str, set] = defaultdict(set)
    in_lead: Dict[str, str] = {}
    makers: Dict[str, Counter] = defaultdict(Counter)
    actors: set = set()
    publishers: set = set()
    for pid, role, eid, name, typ, maker in mentions:
        if role not in ROLE_FACTOR or not eid:
            continue
        posts[eid].add(pid)
        if role in ("subject", "actor"):
            core[eid].add(pid)
        if lead and pid == lead[0] and (eid not in in_lead or ROLES.index(role) < ROLES.index(in_lead[eid])):
            in_lead[eid] = role
        if role == "actor":
            actors.add(eid)
        elif role == "source":
            publishers.add(eid)
        if maker:
            makers[eid][maker] += 1
        t = best.get(eid)
        if t is None or ROLES.index(role) < ROLES.index(t["role"]):
            best[eid] = {"id": eid, "name": name, "type": typ, "role": role}
    rank = {"subject": 0, "actor": 0, "source": 1, "mention": 2}
    things = sorted(best.values(), key=lambda t: (rank[t["role"]], -len(posts[t["id"]]), t["name"] or ""))[:THINGS_MAX]
    for t in things:
        t["posts"] = len(posts[t["id"]])
        t["core"] = len(core[t["id"]])
        t["lead_role"] = in_lead.get(t["id"])
    subjects = [t for t in things if t["role"] == "subject"]
    main = None
    if subjects:
        m = subjects[0]
        main = {"name": m["name"], "type": m["type"], "maker": (makers[m["id"]].most_common(1) or [(None,)])[0][0]}
    acting = Counter({eid: len(posts[eid]) for eid, t in best.items() if t["type"] == "org" and eid in actors})
    shippers = [best[eid]["name"] for eid, _n in acting.most_common()]
    named = [t["name"] for eid, t in best.items() if eid in actors or eid in publishers]
    kind = subtype_kind(typed) or kind_of(event, main, shippers, named)
    return {"things": things, "kind": kind, "sources": sorted(set(sources)), "source_posts": dict(Counter(sources)),
            "n": max(len(sources), max((len(v) for v in posts.values()), default=0)),
            "lead_source": lead[1] if lead else None}


def row_facts(cur: Any, rows: Sequence[Dict[str, Any]], events: Mapping[str, Optional[str]]) -> Dict[str, Dict[str, Any]]:
    """{row id: its facts} from the database: its posts' current entities (named and made as the entity pages say:
    a mention's own maker is not trusted, measured: posts disagree on it), its posts' event types and subtypes
    (event_types.of_posts), its significance event (`events`) and its posts' sources."""
    from insight_core.markx import event_types
    of_post: Dict[str, List[str]] = defaultdict(list)
    source_of: Dict[str, str] = {}
    for r in rows:
        for p in r.get("posts") or []:
            of_post[p["post_id"]].append(str(r["id"]))
    ids = sorted(of_post)
    mentions: Dict[str, List[Tuple]] = defaultdict(list)
    sources: Dict[str, List[str]] = defaultdict(list)
    if ids:
        cur.execute("SELECT id::text, source_id::text FROM posts WHERE id = ANY(%s::uuid[])", (ids,))
        for pid, sid in cur.fetchall():
            source_of[pid] = sid
            for rid in of_post[pid]:
                sources[rid].append(sid)
        cur.execute("""SELECT m.post_id::text, m.role, m.entity_id::text, COALESCE(e.shown_name, e.name, m.name),
                              COALESCE(e.shown_type, e.type, m.type), e.maker
                         FROM mx_mentions_now m JOIN mx_entities e ON e.id = m.entity_id
                        WHERE m.post_id = ANY(%s::uuid[]) AND m.role = ANY(%s)""", (ids, list(ROLES)))
        for row in cur.fetchall():
            for rid in of_post[row[0]]:
                mentions[rid].append(row)
    types = event_types.of_posts(cur, ids) if ids else {}
    typed = {str(r["id"]): [(types[p["post_id"]].type, types[p["post_id"]].subtype) for p in r.get("posts") or []
                            if p["post_id"] in types] for r in rows}

    def lead(r: Dict[str, Any]) -> Optional[Tuple[str, Optional[str]]]:
        first = (r.get("posts") or [None])[0]       # a row's posts in lead order (news.lead_order)
        return (first["post_id"], source_of.get(first["post_id"])) if first else None
    return {str(r["id"]): facts_of(mentions.get(str(r["id"]), ()), events.get(str(r["id"])),
                                   sources.get(str(r["id"]), ()), typed[str(r["id"])], lead(r)) for r in rows}


# ---- what the reader taught ---------------------------------------------------------------------------------

def teach(cur: Any, *, dim: str, key: str, answer: str, name: Optional[str] = None, row: Optional[str] = None,
          post: Optional[str] = None, origin: str = "reader") -> Dict[str, Any]:
    """One tap (or a seed): kept, never replaced; the newest of a (dim, key) counts."""
    if dim not in DIMS:
        raise ValueError(f"dim must be one of {', '.join(DIMS)}")
    if answer not in ANSWERS:
        raise ValueError(f"answer must be one of {', '.join(ANSWERS)}")
    if not (key or "").strip():
        raise ValueError("key is empty")
    cur.execute("""INSERT INTO mx_interests (dim, key, name, answer, row_id, post_id, origin, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, clock_timestamp()) RETURNING id::text, created_at""",
                (dim, key.strip(), (name or "").strip() or None, answer, row, post, origin))
    lid, at = cur.fetchone()
    return {"id": lid, "dim": dim, "key": key.strip(), "answer": answer, "at": at.isoformat()}


def taught(cur: Any) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(dim, key): the newest tap {answer, name, origin, at}}, undone ones left out."""
    cur.execute("""SELECT DISTINCT ON (dim, key) dim, key, answer, name, origin, created_at FROM mx_interests
                    ORDER BY dim, key, created_at DESC, id""")
    return {(d, k): {"answer": a, "name": n, "origin": o, "at": at} for d, k, a, n, o, at in cur.fetchall()
            if a != "undo"}


def seed(cur: Any, names: Iterable[str]) -> List[Dict[str, Any]]:
    """The reader's stated interests as seed taps: each name's entity (the one with the most mentions of that name;
    a name with none is skipped)."""
    out = []
    for name in names:
        cur.execute("""SELECT e.id::text, COALESCE(e.shown_name, e.name) FROM mx_entities e
                        WHERE lower(COALESCE(e.shown_name, e.name)) = lower(%s)
                        ORDER BY (SELECT count(*) FROM mx_mentions_now m WHERE m.entity_id = e.id) DESC LIMIT 1""",
                    (name.strip(),))
        got = cur.fetchone()
        if got:
            out.append(teach(cur, dim="thing", key=got[0], name=got[1], answer="more", origin="seed"))
    return out


# ---- what INSIGHT learned -----------------------------------------------------------------------------------

def decay(at: datetime, now: datetime) -> float:
    return 0.5 ** (max((now - at).total_seconds(), 0.0) / 86400.0 / HALF_LIFE_DAYS)


def engagement(acts: Iterable[Tuple[str, str, datetime]], now: datetime) -> Dict[str, float]:
    """{post: its acts' weight (ACTS), each decayed by its age, at most POST_MAX}: acts [(post, act, at)]."""
    out: Dict[str, float] = defaultdict(float)
    for pid, act, at in acts:
        out[pid] += ACTS[act] * decay(at, now)
    return {p: min(POST_MAX, v) for p, v in out.items()}


def lift_weight(engaged: float, exposed: int, rate: float) -> float:
    """How much more (or less) than its share the reader reads a key: IMPLICIT_MAX * log(lift) / log(LIFT_FULL), in
    [IMPLICIT_MIN, IMPLICIT_MAX], the share smoothed toward `rate` by PRIOR_POSTS; a liking as sure as the reads
    behind it (engaged / (engaged + SURE_HALF): two opens are half sure)."""
    if rate <= 0 or exposed <= 0:
        return 0.0
    lift = ((engaged + PRIOR_POSTS * rate) / (exposed + PRIOR_POSTS)) / rate
    w = max(IMPLICIT_MIN, min(IMPLICIT_MAX, IMPLICIT_MAX * math.log(lift) / math.log(LIFT_FULL)))
    return round(w * engaged / (engaged + SURE_HALF) if w > 0 else w, 4)


def learned(stats: Mapping[Tuple[str, str], Tuple[float, int]], rate: float,
            tracks: Mapping[str, str] = {}, names: Mapping[Tuple[str, str], str] = {}) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """Pure: {(dim, key): {weight, name, why}} from {(dim, key): (engaged, exposed)} and {thing: its track}."""
    out: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for k, (e, n) in stats.items():
        w = lift_weight(e, n, rate)
        if abs(w) >= WEIGHT_MIN:
            out[k] = {"weight": w, "name": names.get(k), "why": {"read": round(e, 2), "posts": n}}
    for thing, track in tracks.items():
        k = ("thing", thing)
        got = out.setdefault(k, {"weight": 0.0, "name": names.get(k), "why": {}})
        got["weight"] = round(got["weight"] + TRACK_PRIOR, 4)
        got["why"]["track"] = track
    return out


def _acts(cur: Any, since: datetime) -> List[Tuple[str, str, datetime]]:
    cur.execute("""SELECT post_id::text, 'opened', created_at FROM post_interactions
                    WHERE interaction_type = 'opened' AND created_at >= %(s)s
                   UNION ALL
                   SELECT post_id::text, 'long_read', created_at FROM post_interactions
                    WHERE interaction_type = 'reading_session' AND created_at >= %(s)s
                      AND jsonb_typeof(interaction_value->'duration_seconds') = 'number'
                      AND (interaction_value->>'duration_seconds')::float >= %(long)s
                   UNION ALL
                   SELECT post_id::text, 'kept', starred_at FROM post_reader_state WHERE starred_at >= %(s)s
                   UNION ALL
                   SELECT post_id::text, 'later', later_at FROM post_reader_state WHERE later_at >= %(s)s
                   UNION ALL
                   SELECT post_id::text, 'to_end', updated_at FROM post_reader_state
                    WHERE updated_at >= %(s)s AND resume_blocks >= 4 AND resume_block >= resume_blocks - 1""",
                {"s": since, "long": LONG_READ_SECONDS})
    return cur.fetchall()


def gather(cur: Any, now: datetime, facts: Mapping[str, Dict[str, Any]] = {}, rows: Sequence[Dict[str, Any]] = ()
           ) -> Tuple[Dict[Tuple[str, str], Tuple[float, int]], float, Dict[str, str], Dict[Tuple[str, str], str]]:
    """What `learned` reads, from the database: each key's (engaged, exposed) over PROFILE_DAYS (sources: their posts;
    things: the posts naming them as subject or actor, for the things of an engaged post; kinds: the ranked rows of
    each kind, `facts` and `rows`), the overall rate, the tracks' subjects and the keys' names."""
    from insight_core.markx import pairing
    since = now - timedelta(days=PROFILE_DAYS)
    eng = engagement(_acts(cur, since), now)
    ids = sorted(eng)
    stats: Dict[Tuple[str, str], Tuple[float, int]] = {}
    names: Dict[Tuple[str, str], str] = {}
    cur.execute(f"""SELECT p.source_id::text, count(*) FROM posts p WHERE {pairing.ix_date('p')} >= %s GROUP BY 1""",
                (since,))
    exposed = dict(cur.fetchall())
    cur.execute("SELECT id::text, source_id::text FROM posts WHERE id = ANY(%s::uuid[])", (ids,))
    src_eng: Dict[str, float] = defaultdict(float)
    for pid, sid in cur.fetchall():
        src_eng[sid] += eng[pid]
    total_posts = sum(exposed.values()) or 1
    rate = sum(eng.values()) / total_posts
    for sid, n in exposed.items():
        stats[("source", sid)] = (src_eng.get(sid, 0.0), int(n))
    cur.execute("""SELECT DISTINCT m.post_id::text, m.entity_id::text, COALESCE(e.shown_name, e.name)
                     FROM mx_mentions_now m JOIN mx_entities e ON e.id = m.entity_id
                    WHERE m.post_id = ANY(%s::uuid[]) AND m.role IN ('subject', 'actor')""", (ids,))
    ent_eng: Dict[str, float] = defaultdict(float)
    for pid, eid, name in cur.fetchall():
        ent_eng[eid] += eng[pid]
        names[("thing", eid)] = name
    if ent_eng:
        cur.execute(f"""SELECT m.entity_id::text, count(DISTINCT m.post_id) FROM mx_mentions_now m
                          JOIN posts p ON p.id = m.post_id
                         WHERE m.entity_id = ANY(%s::uuid[]) AND m.role IN ('subject', 'actor')
                           AND {pairing.ix_date('p')} >= %s GROUP BY 1""", (sorted(ent_eng), since))
        for eid, n in cur.fetchall():
            stats[("thing", eid)] = (ent_eng[eid], max(int(n), 1))
    kind_rows: Dict[str, List[float]] = defaultdict(list)
    for r in rows:
        k = (facts.get(str(r["id"])) or {}).get("kind")
        if k:
            names[("kind", k["key"])] = k["words"]
            kind_rows[k["key"]].append(max((eng.get(p["post_id"], 0.0) for p in r.get("posts") or []), default=0.0))
    row_rate = (sum(sum(v) for v in kind_rows.values()) / max(1, sum(len(v) for v in kind_rows.values())))
    for k, vals in kind_rows.items():
        # a kind's share over the ranked rows (a row engaged when one of its posts is), on the rows' own rate
        stats[("kind", k)] = (sum(vals) * (rate / row_rate if row_rate else 0.0), len(vals))
    cur.execute("""SELECT f.name, m.entity_id::text, COALESCE(e.shown_name, e.name), count(DISTINCT i.post_id)
                     FROM mx_track_items i JOIN mx_tracks t ON t.folder_id = i.track_id JOIN folders f ON f.id = t.folder_id
                     JOIN mx_mentions_now m ON m.post_id = i.post_id AND m.role = 'subject'
                     JOIN mx_entities e ON e.id = m.entity_id
                    WHERE i.verdict GROUP BY 1, 2, 3 HAVING count(DISTINCT i.post_id) >= %s
                    ORDER BY 4 DESC""", (TRACK_MIN,))
    tracks: Dict[str, str] = {}
    for track, eid, name, _n in cur.fetchall():
        tracks.setdefault(eid, track)
        names[("thing", eid)] = name
    return stats, rate, tracks, names


def learn(cur: Any, now: datetime, facts: Mapping[str, Dict[str, Any]] = {}, rows: Sequence[Dict[str, Any]] = ()
          ) -> Dict[str, Any]:
    """In the jobs process: the learned weights computed and kept (mx_interest_weights, replaced)."""
    stats, rate, tracks, names = gather(cur, now, facts, rows)
    got = learned(stats, rate, tracks, names)
    cur.execute("DELETE FROM mx_interest_weights")
    cur.executemany("""INSERT INTO mx_interest_weights (dim, key, weight, name, why, learned_at)
                       VALUES (%s, %s, %s, %s, %s::jsonb, %s)""",
                    [(d, k, w["weight"], w["name"], json.dumps(w["why"]), now) for (d, k), w in got.items()])
    return {"weights": len(got), "rate": round(rate, 5)}


# ---- a row's interest ---------------------------------------------------------------------------------------

@dataclass
class Weight:
    value: float
    by: str                     # "reader" (a tap), "seed", "learned"
    answer: Optional[str] = None
    name: Optional[str] = None
    why: Dict[str, Any] = field(default_factory=dict)


def weights(cur: Any, keys: Iterable[Tuple[str, str]]) -> Dict[Tuple[str, str], Weight]:
    """{(dim, key): its Weight} for these keys: the newest tap when there is one (none: weight 0), else the learned
    weight. Two small queries: the taps (a few hundred rows at most) and the learned weights of these keys."""
    keys = sorted(set(keys))
    out: Dict[Tuple[str, str], Weight] = {}
    if keys:
        cur.execute("""SELECT dim, key, weight, name, why FROM mx_interest_weights
                        WHERE (dim, key) IN (SELECT * FROM unnest(%s::text[], %s::text[]))""",
                    ([d for d, _ in keys], [k for _, k in keys]))
        for d, k, w, n, why in cur.fetchall():
            out[(d, k)] = Weight(float(w), "learned", name=n, why=why or {})
    for (d, k), t in taught(cur).items():
        value = 0.0 if t["answer"] == "none" else (SEED if t["origin"] == "seed" else LABEL[d]) * (1 if t["answer"] == "more" else -1)
        out[(d, k)] = Weight(value, t["origin"], answer=t["answer"], name=t["name"])
    return out


def keys_of(facts: Optional[Dict[str, Any]]) -> List[Tuple[str, str]]:
    f = facts or {}
    return ([("thing", t["id"]) for t in f.get("things") or []] + [("source", s) for s in f.get("sources") or []]
            + ([("kind", f["kind"]["key"])] if f.get("kind") else []))


def _words(dim: str, w: Weight, amount: float, name: str, kind_words: str = "") -> str:
    if dim == "kind":
        name = f"'{kind_words}'"
    if w.by in ("reader", "seed"):
        if dim == "thing":
            return f"you follow {name}" if amount > 0 else f"you lowered {name}"
        return f"you raised {name}" if amount > 0 else f"you lowered {name}"
    if dim == "thing" and w.why.get("track") and amount > 0 and not w.why.get("read"):
        return f"{name} is in your track {w.why['track']}"
    what = {"thing": f"posts about {name}", "source": name, "kind": name}[dim]
    return f"you often read {what}" if amount > 0 else f"you rarely open {what}"


_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def shown_name(name: Optional[str]) -> Optional[str]:
    """A name a reason may show: never an id or an address (v10.44: "you rarely open f91c49bc-…"); None otherwise."""
    name = " ".join((name or "").split())
    if not name or _ID.match(name) or "://" in name or name.lower().startswith("www."):
        return None
    return name


def presence(thing: Dict[str, Any], n: int) -> float:
    """How much of a row a thing is (v10.44), 0..1, by its role and place: a subject or actor of the lead post or of
    most posts is the row (1); a subject or actor of fewer members, their share of the row; a publisher or mention
    counts only in the lead (half its role's factor) or in most posts (half its role's factor times its share), else
    not at all (production c67ad1c9 rose x1.49 for "Brave", named once by a member)."""
    n = max(int(n or 1), 1)
    core, lead_role = int(thing.get("core") or 0), thing.get("lead_role")
    if lead_role in ("subject", "actor") or core * 2 > n:
        return 1.0
    if core:
        return core / n
    if lead_role:
        return 0.5 * ROLE_FACTOR.get(lead_role, 0.5)
    posts = int(thing.get("posts") or 0)
    return 0.5 * ROLE_FACTOR.get(thing.get("role"), 0.5) * posts / n if posts * 2 > n else 0.0


def source_share(f: Dict[str, Any], source: str, lead: Optional[str]) -> float:
    """How much of a row a source is (v10.44): the lead's source 1, another its share of the row's posts, halved
    (production f44a0877, a Hacker News lead: "you rarely open blognot", a member's source)."""
    counts = f.get("source_posts")
    if source == lead or not counts:
        return 1.0
    return 0.5 * counts.get(source, 0) / max(int(f.get("n") or 1), 1)


def score(ws: Mapping[Tuple[str, str], Weight], facts: Optional[Dict[str, Any]],
          source_names: Mapping[str, str] = {}, lead_source: Optional[str] = None) -> Dict[str, Any]:
    """Pure: a row's interest {p, factor, why, reasons [{dim, key, name, amount, words}]} (see the module). A thing's
    weight counts by its `presence` (facts kept before v10.44, without `core`: a tap fully, a learned weight by its
    role's factor), a source's by its `source_share` (`lead_source`: the shown row's lead's source, else the kept
    one); a reason with no name to show (an id, an address) is no reason."""
    f = facts or {}
    reasons: List[Dict[str, Any]] = []
    lead = lead_source or f.get("lead_source")
    n = f.get("n") or 1

    def thing_factor(t: Dict[str, Any]) -> Callable[[Weight], float]:
        if "core" in t:
            return lambda w, k=presence(t, n): k
        return lambda w: 1.0 if w.by != "learned" else ROLE_FACTOR.get(t["role"], 0.5)

    def part(dim: str, items: List[Tuple[str, Optional[str], Callable[[Weight], float]]]) -> List[Dict[str, Any]]:
        got = []
        for key, name, factor in items:
            w = ws.get((dim, key))
            if w is None or w.value == 0:
                continue
            shown = shown_name(name) or shown_name(w.name)
            amount = round(w.value * factor(w), 4)
            if shown is None or amount == 0:
                continue
            got.append({"dim": dim, "key": key, "name": shown, "amount": amount, "w": w})
        pos = max((g for g in got if g["amount"] > 0), key=lambda g: g["amount"], default=None)
        neg = min((g for g in got if g["amount"] < 0), key=lambda g: g["amount"], default=None)
        return [g for g in (pos, neg) if g]

    things = part("thing", [(t["id"], t["name"], thing_factor(t)) for t in f.get("things") or []])
    sources = part("source", [(s, source_names.get(s), lambda w, k=source_share(f, s, lead): k)
                              for s in f.get("sources") or []])
    kind = part("kind", [(f["kind"]["key"], f["kind"]["words"], lambda w: 1.0)]) if f.get("kind") else []
    named = [g for g in things if g["w"].by in ("reader", "seed")]
    for g in kind:
        if any((n["amount"] > 0) != (g["amount"] > 0) for n in named):
            g["beaten"] = True    # a thing the reader named beats the kind
    reasons = things + sources + kind
    p = sum(g["amount"] for g in reasons if not g.get("beaten"))
    p = max(-P_MAX, min(P_MAX, p))
    out = []
    for g in sorted(reasons, key=lambda g: (bool(g.get("beaten")), -abs(g["amount"]))):
        words = _words(g["dim"], g["w"], g["amount"], g["name"], (f.get("kind") or {}).get("words", ""))
        out.append({"dim": g["dim"], "key": g["key"], "name": g["name"], "amount": g["amount"], "words": words,
                    "by": g["w"].by, "beaten": bool(g.get("beaten"))})
    top = next((r for r in out if not r["beaten"]), None)
    return {"p": round(p, 4), "factor": round(math.exp(SCALE * p), 4),
            "why": top["words"] if top and abs(p) >= SHOWN else None, "reasons": out}


def teachable(facts: Optional[Dict[str, Any]], source: Optional[Tuple[str, str]],
              ws: Mapping[Tuple[str, str], Weight]) -> Dict[str, Any]:
    """What a row (or a post) offers to teach: its first CHIPS things, its kind, its source; each with its tap."""
    f = facts or {}

    def tap(dim: str, key: str) -> Optional[str]:
        w = ws.get((dim, key))
        return w.answer if w and w.by == "reader" else None

    return {"things": [{"id": t["id"], "name": t["name"], "type": t["type"], "answer": tap("thing", t["id"])}
                       for t in (f.get("things") or [])[:CHIPS]],
            "kind": ({**f["kind"], "answer": tap("kind", f["kind"]["key"])} if f.get("kind") else None),
            "source": ({"id": source[0], "name": source[1], "answer": tap("source", source[0])} if source else None)}


def source_names(cur: Any, ids: Iterable[str]) -> Dict[str, str]:
    """{source id: the name a reason shows} (v10.44): its display name, else its name, else its address's
    publication (a feed's host, "garymarcus.substack.com"), else its handle ("blognot"); never an address."""
    from insight_core.utils.addresses import host_of, publication_of
    ids = sorted({i for i in ids if i and _ID.match(i)})
    if not ids:
        return {}
    cur.execute("""SELECT id::text, NULLIF(btrim(settings->>'display_name'), ''), NULLIF(btrim(settings->>'name'), ''),
                          handle_or_url FROM sources WHERE id = ANY(%s::uuid[])""", (ids,))
    out = {}
    for sid, display, name, handle in cur.fetchall():
        got = shown_name(display) or shown_name(name)
        if got is None and handle:
            got = shown_name(publication_of(host_of(handle))) if "://" in handle else shown_name(handle)
        if got:
            out[sid] = got
    return out


def for_items(cur: Any, rows: Mapping[str, Tuple[Optional[Dict[str, Any]], Optional[Tuple[str, str]]]]
              ) -> Dict[str, Dict[str, Any]]:
    """In the API: {row: {p, factor, why, reasons, teach}} for {row: (its kept facts, (lead source id, name))}."""
    keys = [k for facts, src in rows.values() for k in keys_of(facts)] + [("source", s[0]) for _f, s in rows.values() if s]
    ws = weights(cur, keys)
    names = source_names(cur, [k for d, k in keys if d == "source" and (d, k) in ws]
                         + [s[0] for _f, s in rows.values() if s])
    out = {}
    for rid, (facts, src) in rows.items():
        if src:
            src = (src[0], shown_name(src[1]) or names.get(src[0]) or src[1])
        shown = {**names, **({src[0]: src[1]} if src and shown_name(src[1]) else {})}
        out[rid] = {**score(ws, facts, shown, src[0] if src else None), "teach": teachable(facts, src, ws)}
    return out


def post_facts(cur: Any, post_id: str) -> Dict[str, Any]:
    """The post page's teach panel: the post's own things, the kind of the News row it is in (the newest rank of a
    row holding it; none outside News), its source, each with its tap."""
    cur.execute("SELECT p.source_id::text, COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url) "
                "FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = %s", (post_id,))
    got = cur.fetchone()
    if got is None:
        raise KeyError(post_id)
    cur.execute("""SELECT r.row_id::text, r.why->'personal'->'kind' FROM mx_news_rank r
                     JOIN mx_news n ON n.id = r.row_id AND n.run_id = r.run_id
                    WHERE n.posts @> %s::jsonb ORDER BY r.ranked_at DESC LIMIT 1""",
                (json.dumps([{"post_id": post_id}]),))
    row = cur.fetchone()
    facts = row_facts(cur, [{"id": post_id, "posts": [{"post_id": post_id}]}], {})[post_id]
    facts["kind"] = row[1] if row else None
    ws = weights(cur, keys_of(facts) + [("source", got[0])])
    name = source_names(cur, [got[0]]).get(got[0]) or got[1]
    return {"post": post_id, "row": row[0] if row else None, **teachable(facts, (got[0], name), ws)}
