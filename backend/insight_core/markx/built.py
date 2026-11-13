"""Stealth v10.4 (issue 0128): how a Mark X story is built, by the owner's rules (0120 "What the owner decided").

  1. **The story's event type**, from its members' read-v3 readings (0127's `read3`): the most common news type
     (`folds.story_type`), else the most common type of the read members (a story of leaks is `leak_rumour`).
  2. **Leaks.** A leak is a member read as `leak_rumour`; a story's release is its earliest member of the story's news
     type that isn't one.
       - Inside a story: a leak before the release joins it when it is at most JOIN_HOURS before, or it is the only
         voice that leaked; two or more voices leaking it earlier than that are coverage of its own (by the rule its
         own story, linked "came true"; the decision rules don't split stories by type yet, so it is shown, not split).
       - Across stories (`came_true`): a leak story (its type `leak_rumour`) and a later release story (a news type,
         its release within CAME_TRUE_DAYS of the leak story's first post) are linked when Mark X's judged connection
         joins them (development, follows up, same event). A shared main subject (identity's roots, or one's subject
         the other's family) is built but off (SUBJECT_LINKS: 0 of 5 right on the lab's unseen rumours). A one-voice
         leak story at most JOIN_HOURS before the release joins it; any other stays its own story, linked both ways.
  3. **The original by code** (0120 "The original by code", the port in perspectives.Story): a member whose own page
     is the page most members link to, else the maker's own post, the maker's page, a link post carrying the maker's
     page; shown as the story's first post. No member is: the source page is shown, the earliest post first.
  4. **Published order** (PUBLISHED): a post's own date (a saved page's is the page's, 0063); the time it was put in
     front of the owner (surfaced_at, 0039) only for a post with no date.

**Nothing is stored:** a function of the readings, the members, the mentions and the connections Mark X keeps,
computed when a page is built, as the fold is (0127 §3). The decision rules, task inputs and perspectives' frozen
inputs are unchanged. Reads only; Mark IX's tables are read, never written.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Set

from insight_core.markx import event_types, folds

PUBLISHED = "COALESCE(p.published_at, p.surfaced_at, p.fetched_at)"
JOIN_HOURS = 24          # a leak this close before its release, with no coverage of its own, joins the release
CAME_TRUE_DAYS = 30      # a leak story is linked to a release at most this long after its first post
LEAK = folds.LEAK
NEWS_TYPES = folds.NEWS_TYPES
CONNECTED = ("development", "follows_up", "same_event")
# A shared main subject alone as the "came true" evidence. Off (measured 2026-11-07, 0128): on the lab's unseen rumour
# set it linked 0 of 5 right (run 1; runs 2-3: 0/2, 0/2; dev 0/1, 4/4, 0/0): a later post on the same subject is
# rarely the leak's confirmation, and the leak flag misses 4 rumours in 10. The lab's pairwise judge (read_v3e: F1
# 0.80) is the measured way; until then only Mark X's own judged connections link a leak story to its release.
SUBJECT_LINKS = False
ORIGINAL_ORDER = ("links", "maker", "maker-page", "maker-link")
NOT_FAMILY = ("org", "person")
CODE = "built-v1"


# ---- the rules (pure) -------------------------------------------------------------------------------

@dataclass(frozen=True)
class Post:
    id: str
    source: str
    at: datetime                       # published (PUBLISHED)
    event_type: Optional[str]          # None: no read-v3 reading yet
    origin: Optional[str] = None
    subjects: FrozenSet[str] = frozenset()   # the entity roots the post names as its subject


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
    own = len({p.source for p in early}) >= 2
    return [{"post": p.id, "hours": _hours(p.at, rel), "joins": not (own and p in early),
             "own_coverage": own and p in early} for p in leaks]


def main_subjects(posts: Sequence[Post]) -> Set[str]:
    """The entity roots named as subject by the most members (all of them on a tie); none named: empty."""
    c = Counter(r for p in posts for r in p.subjects)
    if not c:
        return set()
    top = max(c.values())
    return {r for r, n in c.items() if n == top}


def _related(a: Set[str], b: Set[str], family: Callable[[str], Iterable[str]]) -> bool:
    if a & b:
        return True
    return any(x in set(family(y)) for x in a for y in b) or any(y in set(family(x)) for x in a for y in b)


def voices(posts: Sequence[Post]) -> int:
    return len({p.source for p in posts})


def came_true(stories: Mapping[str, Sequence[Post]], *, connected: Iterable[FrozenSet[str]] = (),
              family: Callable[[str], Iterable[str]] = lambda root: (), join_hours: float = JOIN_HOURS,
              days: float = CAME_TRUE_DAYS, by_subject: bool = True) -> List[Dict[str, Any]]:
    """Every leak story linked to a later release story: {leak, release, hours (leak's first post to the release),
    joins (a one-voice leak hours before), via (connection | subject)}, ordered by release, then leak. `by_subject`:
    a shared main subject links on its own (the pages pass SUBJECT_LINKS, off: measured)."""
    connected = {frozenset(c) for c in connected}
    kinds = {s: event_type(ps) for s, ps in stories.items()}
    subj = {s: main_subjects(ps) for s, ps in stories.items()}
    firsts = {s: min(p.at for p in ps) for s, ps in stories.items() if ps}
    out = []
    for r in sorted(s for s, k in kinds.items() if k in NEWS_TYPES):
        rel = release_at(stories[r])
        if rel is None:
            continue
        for leak in sorted(s for s, k in kinds.items() if k == LEAK and s != r):
            t0 = firsts[leak]
            if not (t0 < rel <= t0 + timedelta(days=days)):
                continue
            via = ("connection" if frozenset((leak, r)) in connected else
                   "subject" if by_subject and subj[leak] and subj[r] and _related(subj[leak], subj[r], family)
                   else None)
            if via is None:
                continue
            hours = _hours(t0, rel)
            out.append({"leak": leak, "release": r, "hours": hours,
                        "joins": voices(stories[leak]) == 1 and hours <= join_hours, "via": via})
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
    """{story: [{id, source, at (published), event_type, origin}]} over each story's current members."""
    if not story_ids:
        return {}
    cur.execute(f"""SELECT sp.story_id::text, sp.post_id::text, p.source_id::text, {PUBLISHED}
                      FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id
                     WHERE sp.story_id = ANY(%s::uuid[]) AND sp.valid_to IS NULL AND sp.role = 'member'""",
                (list(story_ids),))
    rows = cur.fetchall()
    types = event_types.types_of(cur, [r[1] for r in rows])   # 0175: a post's type through the seam
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for sid, pid, src, at in rows:
        et, origin = types[pid]
        out[sid].append({"id": pid, "source": src, "at": at, "event_type": et, "origin": origin})
    return dict(out)


def _neighbours(cur: Any, lo: datetime, hi: datetime, have: Set[str], among: Optional[Iterable[str]] = None) -> List[str]:
    """The current, unmerged Mark X stories of 2+ members with a member published in [lo, hi] and a read-v3 reading
    of a leak or a news type: the stories a viewed one may be linked "came true" to. `among`: only these stories
    (v10.17: those a judged connection joins to a viewed one, when only a connection links, SUBJECT_LINKS off)."""
    among = None if among is None else sorted(set(among) - have)
    if among is not None and not among:
        return []
    cur.execute(f"""SELECT DISTINCT sp.story_id::text FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id
                      JOIN mx_stories s ON s.id = sp.story_id AND s.merged_into IS NULL
                     WHERE sp.valid_to IS NULL AND sp.role = 'member' AND {PUBLISHED} BETWEEN %(lo)s AND %(hi)s
                       {"AND sp.story_id = ANY(%(among)s::uuid[])" if among is not None else ""}
                       AND {event_types.typed_sql("sp.post_id", "%(types)s")}""",   # 0175: through the seam
                {"lo": lo, "hi": hi, "types": [LEAK, *NEWS_TYPES], "among": among})
    return sorted({r[0] for r in cur.fetchall()} - have)


def _subjects(cur: Any, posts: Sequence[str], book: Any) -> Dict[str, Set[str]]:
    if not posts:
        return {}
    cur.execute("""SELECT post_id::text, entity_id::text FROM mx_mentions_now
                    WHERE role = 'subject' AND entity_id IS NOT NULL AND post_id = ANY(%s::uuid[])""",
                (list(posts),))
    out: Dict[str, Set[str]] = defaultdict(set)
    for pid, eid in cur.fetchall():
        r = book.root(eid)
        e = book.ents.get(r)
        if r and (e is None or e.status != "not_entity"):
            out[pid].add(r)
    return out


def _family(book: Any) -> Callable[[str], List[str]]:
    """A root's family chain (its parents' roots, not an org or a person: the maker never counts as the family)."""
    def up(root: str) -> List[str]:
        out, seen = [], {root}
        e = book.ents.get(root)
        while e is not None and e.parent:
            r = book.root(e.parent)
            if r in seen:
                break
            seen.add(r)
            e = book.ents.get(r)
            if e is None or e.type in NOT_FAMILY:
                break
            out.append(r)
        return out
    return up


def _connected(cur: Any, story_ids: Sequence[str]) -> Set[FrozenSet[str]]:
    if not story_ids:
        return set()
    cur.execute("""SELECT a::text, b::text FROM mx_connections WHERE valid_to IS NULL AND a_kind = 'story'
                     AND b_kind = 'story' AND relation = ANY(%s) AND (a = ANY(%s::uuid[]) OR b = ANY(%s::uuid[]))""",
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
    return {sid: P.Story([m["id"] for m in ms if m["id"] in posts], posts, makers)
            for sid, ms in rows.items() if any(m["id"] in posts for m in ms)}


def build(cur: Any, story_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """{story: how it is built}: event type (and how many members are read), the original first or the source page,
    the published order, the leaks inside and the "came true" links both ways."""
    from insight_core.markx import identity
    ids = sorted({str(s) for s in story_ids if s})
    rows = _load(cur, ids)
    if not rows:
        return {}
    book = identity.lazy_book(cur)   # v10.17 (0186): what the stories ask of the book, not the whole book
    times = [m["at"] for ms in rows.values() for m in ms if m["at"]]
    # v10.17 (0186): a story is linked "came true" only through a judged connection while SUBJECT_LINKS is off, so
    # only the stories connected to a viewed one can be linked to it (was: every typed story of the window, ~60 days
    # of stories, their subjects and every leak x release pair among them, for the same links)
    among = None if SUBJECT_LINKS else {s for c in _connected(cur, ids) for s in c}
    near = _neighbours(cur, min(times) - timedelta(days=CAME_TRUE_DAYS), max(times) + timedelta(days=CAME_TRUE_DAYS),
                       set(rows), among) if times else []
    rows.update(_load(cur, near))
    subj = _subjects(cur, sorted({m["id"] for ms in rows.values() for m in ms}), book) if SUBJECT_LINKS else {}
    world = {sid: [Post(id=m["id"], source=m["source"], at=m["at"], event_type=m["event_type"], origin=m["origin"],
                        subjects=frozenset(subj.get(m["id"], ()))) for m in ms] for sid, ms in rows.items()}
    links = came_true(world, connected=_connected(cur, sorted(world)), family=_family(book), by_subject=SUBJECT_LINKS)
    firsts = {s: min(ps, key=lambda p: (p.at, p.id)).id for s, ps in world.items() if ps}
    titles = _titles(cur, sorted({x[k] for x in links for k in ("leak", "release")}), firsts)
    sts = stories_of(cur, ids, book=book)
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
        }
    return out


def line_roles(b: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """{post: its role in how the story is built}: the original, or a leak before the release."""
    out: Dict[str, Dict[str, Any]] = {}
    if b.get("original"):
        out[b["original"]["post"]] = {"role": "original", "how": b["original"]["how"]}
    for x in b.get("leaks") or ():
        out.setdefault(x["post"], {"role": "leak", "hours": x["hours"], "joins": x["joins"],
                                   "own_coverage": x["own_coverage"]})
    return out


def annotate(cur: Any, items: Sequence[Dict[str, Any]]) -> None:
    """The News page's rows (news.page): each row's `built` (its main story's), its lines in published order with the
    original first, and each line's `built` role. A line of another story keeps its place by time."""
    from insight_core.markx import news as mx_news
    mains = {r["id"]: r.get("main") or mx_news.main_story({"posts": [{"story": l.get("story"), "post_id": l["id"]}
                                                                      for l in r["posts"]]}) for r in items}
    got = build(cur, {s for s in mains.values() if s})
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
