"""How a Mark X story is built (issue 0128): its event type, its leaks, its original and its published order.

The event type is its members' most common news type from their readings (`folds.story_type`). A leak before the
release joins it when at most JOIN_HOURS before or the only voice that leaked; a leak story links "came true" to a
later release story only through Mark X's judged connection (`came_true`; a shared subject alone measured wrong). The
original is found by code (`original`: the page most members link, else the maker's own post or page), shown first;
the rest in published order. Nothing is stored: computed when a page is built from what Mark X keeps. Reads only.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from insight_core.markx import event_types, folds, pairing
from insight_core.utils import voice

PUBLISHED = pairing.published_date("p")
JOIN_HOURS = 24          # a leak this close before its release, with no coverage of its own, joins the release
CAME_TRUE_DAYS = 30      # a leak story is linked to a release at most this long after its first post
LEAK = event_types.LEAK
NEWS_TYPES = event_types.NEWS_TYPES
CONNECTED = ("development", "follows_up", "same_event")
# only Mark X's own judged connections link a leak story to its release (a shared main subject alone measured 0 of 5
# right: 0128)
ORIGINAL_ORDER = ("links", "maker", "maker-page", "maker-link")
CODE = "built-v1"


# ---- the rules (pure) -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Post:
    id: str
    source: str
    at: datetime                       # published (PUBLISHED)
    event_type: Optional[str]          # None: no read-v3 reading yet
    origin: Optional[str] = None
    kind: Optional[str] = None         # its source's kind (post_links.source_kind): a saved page is no voice


def _read(posts: Iterable[Post]) -> List[Post]:
    return sorted((p for p in posts if p.event_type is not None), key=lambda p: (p.at, p.id))


def _members(posts: Iterable[Post]) -> List[folds.Member]:
    return [folds.Member(id=p.id, at=p.at, event_type=p.event_type, origin=p.origin) for p in posts]


def event_type(posts: Sequence[Post]) -> Optional[str]:
    st = folds.story_type(_members(posts))
    if st is not None:
        return st
    ids = _read(posts)
    if not ids:
        return None
    c = Counter(p.event_type for p in ids)
    first = {}
    for n, p in enumerate(ids):
        first.setdefault(p.event_type, n)
    return max(c, key=lambda t: (c[t], -first[t]))


def release_at(posts: Sequence[Post]) -> Optional[datetime]:
    """The story's release: its earliest member of the story's news type (a leak is never one)."""
    st = folds.story_type(_members(posts))
    times = [p.at for p in _read(posts) if st is not None and p.event_type == st]
    return min(times) if times else None


def _hours(a: datetime, b: datetime) -> float:
    return round((b - a).total_seconds() / 3600, 1)


def leaks_inside(posts: Sequence[Post], join_hours: float = JOIN_HOURS) -> List[Dict[str, Any]]:
    """The leak members before the release, earliest first: {post, hours before, joins, own_coverage}."""
    rel = release_at(posts)
    if rel is None:
        return []
    leaks = [p for p in _read(posts) if p.event_type == LEAK and p.at < rel]
    early = [p for p in leaks if _hours(p.at, rel) > join_hours]
    own = voices(early) >= 2
    return [{"post": p.id, "hours": _hours(p.at, rel), "joins": not (own and p in early),
             "own_coverage": own and p in early} for p in leaks]


def voices(posts: Iterable[Post]) -> int:
    """A story's voices by Voice's MARKX rule over each member's source: a saved page is none."""
    return voice.count((voice.Said(p.source, p.kind) for p in posts), voice.Policy.MARKX)


def came_true(stories: Mapping[str, Sequence[Post]], *, connected: Iterable[FrozenSet[str]] = (),
              join_hours: float = JOIN_HOURS, days: float = CAME_TRUE_DAYS) -> List[Dict[str, Any]]:
    """Every leak story a judged connection links to a later release story: {leak, release, hours (leak's first post
    to the release), joins (a one-voice leak hours before), via ("connection")}, ordered by release, then leak."""
    connected = {frozenset(c) for c in connected}
    kinds = {s: event_type(ps) for s, ps in stories.items()}
    firsts = {s: min(p.at for p in ps) for s, ps in stories.items() if ps}
    out = []
    for r in sorted(s for s, k in kinds.items() if k in NEWS_TYPES):
        rel = release_at(stories[r])
        if rel is None:
            continue
        for leak in sorted(s for s, k in kinds.items() if k == LEAK and s != r):
            t0 = firsts[leak]
            if not (t0 < rel <= t0 + timedelta(days=days)) or frozenset((leak, r)) not in connected:
                continue
            hours = _hours(t0, rel)
            out.append({"leak": leak, "release": r, "hours": hours,
                        "joins": voices(stories[leak]) == 1 and hours <= join_hours, "via": "connection"})
    return sorted(out, key=lambda x: (x["release"], x["leak"]))


def original(st: Any) -> Optional[Dict[str, str]]:
    """The story's original found by code (a perspectives.Story): links first, then the maker's own post, the maker's
    page, a link post carrying it; the earliest of a kind. None: no member is the original."""
    found = [(i, st.code[i][1]) for i in st.ids if st.code.get(i, ("", ""))[0] == "original"]
    found += [(i, "maker") for i in st.ids if i in getattr(st, "hint", {})]
    if not found:
        return None
    rank = {h: n for n, h in enumerate(ORIGINAL_ORDER)}
    i, how = min(found, key=lambda x: (rank.get(x[1], len(rank)), st.ids.index(x[0])))
    return {"post": i, "how": how}


def first_order(st: Any, ids: Sequence[str]) -> List[str]:
    """`ids` in published order (a saved page by its own date), the original first."""
    from insight_core.markx.perspectives import pub
    o = original(st)
    head = o["post"] if o else None
    known = [i for i in ids if i in st.by]
    return sorted(known, key=lambda i: (i != head, pub(st.by[i]), i)) + [i for i in ids if i not in st.by]


# ---- from the database ----------------------------------------------------------------------------

def published(cur: Any, ids: Iterable[str]) -> Dict[str, datetime]:
    """{post: its published time} (PUBLISHED)."""
    ids = sorted({str(i) for i in ids})
    if not ids:
        return {}
    cur.execute(f"SELECT p.id::text, {PUBLISHED} FROM posts p WHERE p.id = ANY(%s::uuid[])", (ids,))
    return dict(cur.fetchall())


def in_published_order(cur: Any, posts: Mapping[str, Any]) -> Dict[str, Any]:
    """perspectives.Member rows with `at` set to their published time, for the order a page shows (never an input)."""
    at = published(cur, posts)
    return {i: replace(p, at=at.get(i, p.at)) for i, p in posts.items()}


def _load(cur: Any, story_ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    """{story: [{id, source, kind (its source's), at (published), event_type, origin}]} over each story's current
    members."""
    from insight_core.utils.post_links import source_kind
    if not story_ids:
        return {}
    cur.execute(f"""SELECT sp.story_id::text, sp.post_id::text, p.source_id::text, {PUBLISHED}, s.platform, s.handle_or_url
                      FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id JOIN sources s ON s.id = p.source_id
                     WHERE sp.story_id = ANY(%s::uuid[]) AND sp.valid_to IS NULL AND sp.role = 'member'""",
                (list(story_ids),))
    rows = cur.fetchall()
    types = event_types.types_of(cur, [r[1] for r in rows])   # a post's type through the seam
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for sid, pid, src, at, platform, handle in rows:
        et, origin = types[pid]
        out[sid].append({"id": pid, "source": src, "kind": source_kind(platform, handle), "at": at, "event_type": et,
                         "origin": origin})
    return dict(out)


def _neighbours(cur: Any, lo: datetime, hi: datetime, have: Set[str], among: Optional[Iterable[str]] = None) -> List[str]:
    """The current, unmerged Mark X stories of 2+ members with a member published in [lo, hi] and a read-v3 reading
    of a leak or a news type: the stories a viewed one may be linked "came true" to. `among`: only these stories
    (those a judged connection joins to a viewed one)."""
    among = None if among is None else sorted(set(among) - have)
    if among is not None and not among:
        return []
    cur.execute(f"""SELECT DISTINCT sp.story_id::text FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id
                      JOIN mx_stories s ON s.id = sp.story_id AND s.merged_into IS NULL
                     WHERE sp.valid_to IS NULL AND sp.role = 'member' AND {PUBLISHED} BETWEEN %(lo)s AND %(hi)s
                       {"AND sp.story_id = ANY(%(among)s::uuid[])" if among is not None else ""}
                       AND {event_types.typed_sql("sp.post_id", "%(types)s", event_types.type_guides(cur))}""",
                {"lo": lo, "hi": hi, "types": [LEAK, *NEWS_TYPES], "among": among})
    return sorted({r[0] for r in cur.fetchall()} - have)


def _connected(cur: Any, story_ids: Sequence[str]) -> Set[FrozenSet[str]]:
    if not story_ids:
        return set()
    cur.execute("""SELECT a::text, b::text FROM mx_connections WHERE valid_to IS NULL AND a_kind = 'story'
                     AND b_kind = 'story' AND relation = ANY(%s) AND (a = ANY(%s::uuid[]) OR b = ANY(%s::uuid[]))
                     AND rule IS DISTINCT FROM 'chain_stops'""",   # a story chain is graph's, not decide's
                (list(CONNECTED), list(story_ids), list(story_ids)))
    return {frozenset(r) for r in cur.fetchall()}


def _titles(cur: Any, story_ids: Sequence[str], firsts: Mapping[str, str]) -> Dict[str, str]:
    if not story_ids:
        return {}
    cur.execute("SELECT id::text, headline FROM mx_stories WHERE id = ANY(%s::uuid[])", (list(story_ids),))
    heads = {s: h for s, h in cur.fetchall() if h}
    rest = [firsts[s] for s in story_ids if s not in heads and s in firsts]
    if rest:
        cur.execute("""SELECT p.id::text, COALESCE(pp.title, p.title) FROM posts p LEFT JOIN post_parts pp ON pp.post_id = p.id
                        WHERE p.id = ANY(%s::uuid[])""", (rest,))
        t = dict(cur.fetchall())
        for s in story_ids:
            if s not in heads and firsts.get(s) in t:
                heads[s] = t[firsts[s]] or ""
    return heads


def stories_of(cur: Any, story_ids: Iterable[str], *, book: Any = None, links: bool = True) -> Dict[str, Any]:
    """{story: its perspectives.Story (published order, a saved page by its own date) with the maker found by
    identity}, for the original and the order; the Makers read once."""
    from insight_core.markx import identity, perspectives as P
    rows = _load(cur, sorted(set(story_ids)))
    every = sorted({m["id"] for ms in rows.values() for m in ms})
    if not every:
        return {}
    posts = in_published_order(cur, P.load_members(cur, every))
    book = book if book is not None else identity.lazy_book(cur)
    makers = P.Makers(book, P.mentions_of(cur, every))
    makers.prepare(posts)   # what the stories ask of the book, in a few reads, not one each
    return {sid: P.Story([m["id"] for m in ms if m["id"] in posts], posts, makers)
            for sid, ms in rows.items() if any(m["id"] in posts for m in ms)}


def _near(cur: Any, ids: Sequence[str], rows: Mapping[str, Any]) -> List[str]:
    """The stories the viewed `ids` (`rows`: their members, `_load`) may be linked "came true" to: a story is linked
    only through a judged connection, so only the stories connected to a viewed one, with a member in the viewed
    members' time span widened by CAME_TRUE_DAYS (`_neighbours`)."""
    times = [m["at"] for ms in rows.values() for m in ms if m["at"]]
    if not times:
        return []
    among = {s for c in _connected(cur, ids) for s in c}
    return _neighbours(cur, min(times) - timedelta(days=CAME_TRUE_DAYS), max(times) + timedelta(days=CAME_TRUE_DAYS),
                       set(rows), among)


def build(cur: Any, story_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """{story: how it is built}: event type (and how many members are read), the original first or the source page,
    the published order, the leaks inside and the "came true" links both ways."""
    return build_within(cur, story_ids)[0]


def build_within(cur: Any, story_ids: Iterable[str], within: Optional[Mapping[str, Iterable[str]]] = None
                 ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Set[str]]]:
    """(`build` of `story_ids`, {name: the stories `build` of only that subset of them would read}). A story's
    "came true" links reach only the stories its build reads (its world: the viewed ones and their `_near`), so
    `narrowed` to a subset's world, a story's build is the subset's own build of it, without reading it again."""
    from insight_core.markx import identity
    ids = sorted({str(s) for s in story_ids if s})
    rows = _load(cur, ids)
    worlds: Dict[str, Set[str]] = {}
    for name, sub in (within or {}).items():
        sub_ids = sorted({str(s) for s in sub if s} & set(ids))
        sub_rows = {s: rows[s] for s in sub_ids if s in rows}
        worlds[name] = set(sub_rows) | set(_near(cur, sub_ids, sub_rows))
    if not rows:
        return {}, worlds
    book = identity.lazy_book(cur)   # what the stories ask of the book, not the whole book
    rows.update(_load(cur, _near(cur, ids, rows)))
    world = {sid: [Post(id=m["id"], source=m["source"], at=m["at"], event_type=m["event_type"], origin=m["origin"],
                        kind=m["kind"]) for m in ms]
             for sid, ms in rows.items()}
    links = came_true(world, connected=_connected(cur, sorted(world)))
    firsts = {s: min(ps, key=lambda p: (p.at, p.id)).id for s, ps in world.items() if ps}
    titles = _titles(cur, sorted({x[k] for x in links for k in ("leak", "release")}), firsts)
    sts = stories_of(cur, ids, book=book)
    differ = disputes(cur, ids)
    out: Dict[str, Dict[str, Any]] = {}
    for sid in ids:
        ps = world.get(sid)
        if not ps:
            continue
        st = sts.get(sid)
        o = original(st) if st is not None else None
        order = first_order(st, [p.id for p in ps]) if st is not None else [p.id for p in _read(ps)]
        out[sid] = {
            "code": CODE,
            "event_type": event_type(ps),
            "read": {"read": sum(1 for p in ps if p.event_type is not None), "members": len(ps)},
            "original": o,
            "source_page": (st.src_page if st is not None and o is None else None),
            "order": order,
            "release_at": release_at(ps),
            "leaks": leaks_inside(ps),
            "came_true": [{"story": x["release"], "headline": titles.get(x["release"], ""), "hours": x["hours"],
                           "joins": x["joins"], "via": x["via"]} for x in links if x["leak"] == sid],
            "leaked_before": [{"story": x["leak"], "headline": titles.get(x["leak"], ""), "hours": x["hours"],
                               "joins": x["joins"], "via": x["via"],
                               "posts": [p.id for p in sorted(world[x["leak"]], key=lambda p: (p.at, p.id))]}
                              for x in links if x["release"] == sid],
            "disputes": differ.get(sid, []),
        }
    return out, worlds


def narrowed(b: Optional[Dict[str, Any]], world: Set[str]) -> Optional[Dict[str, Any]]:
    """A story's build (`build`, or annotate's `built`) with only the "came true" links into `world`
    (`build_within`): the same dict when none goes outside it."""
    if b is None:
        return None
    keep = {k: [x for x in b.get(k) or [] if x["story"] in world] for k in ("came_true", "leaked_before") if k in b}
    if all(len(keep[k]) == len(b[k]) for k in keep):
        return b
    return {**b, **keep}


def disputes(cur: Any, story_ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Where each story's sources differ, as its current sheet keeps it (perspectives.disputes_of); none while the
    switch is off."""
    from insight_core.markx import perspectives
    if not story_ids or not perspectives.disputes_on(cur):
        return {}
    cur.execute("""SELECT story_id::text, sheet->'disputes' FROM mx_sheets
                    WHERE valid_to IS NULL AND story_id = ANY(%s::uuid[]) AND jsonb_typeof(sheet->'disputes') = 'array'""",
                (list(story_ids),))
    return {sid: got for sid, got in cur.fetchall() if got}


def line_roles(b: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{post: its role in how the story is built}: the original, or a leak before the release."""
    out: Dict[str, Dict[str, Any]] = {}
    if b.get("original"):
        out[b["original"]["post"]] = {"role": "original", "how": b["original"]["how"]}
    for x in b.get("leaks") or ():
        out.setdefault(x["post"], {"role": "leak", "hours": x["hours"], "joins": x["joins"],
                                   "own_coverage": x["own_coverage"]})
    return out


def annotate(cur: Any, items: Sequence[Dict[str, Any]],
             within: Optional[Mapping[str, Iterable[str]]] = None) -> Dict[str, Set[str]]:
    """The News page's rows (news.page): each row's `built` (its main story's), its lines in published order with the
    original first, and each line's `built` role. A line of another story keeps its place by time. `within`: {name:
    row ids}, a subset of the rows a page shows apart -> {name: its world} (`build_within`; `narrowed` gives such a
    row's `built` as the subset's own page builds it)."""
    from insight_core.markx import news as mx_news
    mains = {r["id"]: r.get("main") or mx_news.main_story({"posts": [{"story": l.get("story"), "post_id": l["id"]}
                                                                      for l in r["posts"]]}) for r in items}
    got, worlds = build_within(cur, {s for s in mains.values() if s},
                               {name: {mains[i] for i in rids if mains.get(i)} for name, rids in (within or {}).items()})
    for r in items:
        b = got.get(mains[r["id"]] or "")
        r["built"] = None if b is None else {k: v for k, v in b.items() if k != "order"}
        roles = line_roles(b) if b else {}
        rank = {p: n for n, p in enumerate(b["order"])} if b else {}
        head = (b.get("original") or {}).get("post") if b else None
        r["posts"].sort(key=lambda l: (l["id"] != head, l.get("at") is None, l.get("at") or datetime.min, rank.get(l["id"], 0),
                                       l["id"]))
        for line in r["posts"]:
            line["built"] = roles.get(line["id"]) if line.get("story") == mains[r["id"]] else None
    return worlds
