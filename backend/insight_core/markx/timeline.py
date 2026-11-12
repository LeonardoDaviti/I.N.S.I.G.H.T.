"""A thing's timeline (issue 0165 C-D): one dated line of what INSIGHT holds about an entity, read only from stored rows
(posts, mentions, merges, stories, Later rows, back-in-the-news rows; nothing fetched).

`of_entity` (the entity page's Timeline block, shown when it has 2+ dated events), each event {at, kind, post, ...}:
  - `birth`: the oldest post naming it or any earlier name (as which name);
  - `earlier_name` / `renamed`: each earlier name (a rename merge, markx/rename.py) at its last post, and the first post
    under the name it has now;
  - `release`: a post about it (role subject or actor) by its maker (a source that is the maker, or a site whose name
    is the maker's) or at one of its own addresses; a family's versions at their first post about them;
  - `first_outside` / `outside`: the posts by anyone else, the first one marked, the rest grouped by month (the month's
    first post, how many posts and sources); a post linking back to one of its posts (0131's post edges) counts as an
    outside mention though it names it otherwise;
  - `story`: each Mark X or Mark IX story it is in, at its first post;
  - `later`: 0163's later developments (judged development); `back`: 0136's back in the news (judged development).
Each event has its importance (`rank`); the TOP most important (birth, renames, the first and last release, the first
outside mention, stories, then the rest) are `top` (shown by default); "all" shows every one, oldest first.

`before_post` (the post page's "before", D): the post's subjects' previous events, up to BEFORE (the birth, the last
release before it, the first outside mention), oldest first.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlsplit

from insight_core.markx import identity as I
from insight_core.markx import names as N

TOP = 8
BEFORE = 3
MIN_EVENTS = 2
ABOUT = ("subject", "actor")
RANK = {"birth": 0, "renamed": 1, "earlier_name": 1, "release": 2, "first_outside": 3, "story": 4, "later": 5,
        "back": 5, "outside": 6}
SECOND_LEVEL = ("co", "com", "org", "net", "ac", "gov", "edu")


def _site(url: Optional[str]) -> Optional[str]:
    """A URL's site name: its host's registrable label ("developer.acme.com" -> "acme"), else None."""
    try:
        host = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return None
    parts = [p for p in host.split(".") if p and p != "www"]
    if len(parts) < 2:
        return None
    label = parts[-2]
    if label in SECOND_LEVEL and len(parts) >= 3:
        label = parts[-3]
    return label


def _host(url: Optional[str]) -> Optional[str]:
    try:
        h = (urlsplit(url or "").hostname or "").lower()
    except ValueError:
        return None
    return h.removeprefix("www.") or None


def maker_of(book: I.Book, root: str) -> Optional[str]:
    """The maker cluster of a thing: its names' stated maker's cluster, else its org or person parent's."""
    for m in [root] + sorted(book.cluster(root)):
        e = book.ents[m]
        if e.maker:
            r = I.maker_root(book, e.maker)
            if r and r != root:
                return r
    for m in [root] + sorted(book.cluster(root)):
        e = book.ents[m]
        p = book.root(e.parent) if e.parent else None
        if p and p in book.ents and I.schemas_type(book.ents[p].type) in I.ORGISH:
            return p
        if p and p in book.ents and book.ents[m].level in I.VERSION_LEVELS:
            return maker_of(book, p) if p != root else None
    return None


def maker_names(book: I.Book, root: str, maker: Optional[str]) -> Set[str]:
    """The site names a maker's own sites go by: its names (and its stated maker strings) run together, a corporate
    word dropped ("Acme Corporation" -> "acme")."""
    keys: Set[str] = set()
    if maker and maker in book.ents:
        keys |= {book.ents[x].key for x in book.cluster(maker)}
    for m in book.cluster(root):
        if book.ents[m].maker:
            keys.add(N.key(book.ents[m].maker))
    out = set()
    for k in keys:
        words = k.split()
        while len(words) > 1 and words[-1] in I.CORP_WORDS:
            words = words[:-1]
        sq = N.squash(" ".join(words))
        if len(sq) >= 3:
            out.add(sq)
    return out


class Lines:
    """The posts naming a cluster: {post: (at, roles, source, url, written as)}."""

    def __init__(self) -> None:
        self.rows: Dict[str, Dict[str, Any]] = {}

    def add(self, pid: str, at: datetime, role: Optional[str], src: Optional[str], url: Optional[str],
            eid: Optional[str]) -> None:
        r = self.rows.setdefault(pid, {"at": at, "roles": set(), "source": src, "url": url, "as": set()})
        r["roles"].add(role or "mention")
        if eid:
            r["as"].add(eid)


def lines_of(cur: Any, book: I.Book, members: Iterable[str]) -> Lines:
    from insight_core.markx import schemas
    ids = sorted(set(members))
    out = Lines()
    if not ids:
        return out
    cur.execute("""SELECT m.post_id::text, m.guide, m.n, m.entity_id::text, m.role,
                          COALESCE(p.surfaced_at, p.published_at, p.fetched_at), p.source_id::text, p.url
                     FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                    WHERE m.guide = ANY(%s) AND (m.entity_id = ANY(%s::uuid[]) OR (m.post_id, m.guide, m.n) IN
                          (SELECT post_id, guide, n FROM mx_entity_pins WHERE undone_at IS NULL AND entity_id = ANY(%s::uuid[])))""",
                (schemas.mention_guides(), ids, ids))
    want = set(ids)
    for pid, g, n, eid, role, at, src, url in cur.fetchall():
        e = book.pins.get((pid, g, n), eid)
        if e in want and at is not None:
            out.add(pid, at, role, src, url, e)
    return out


def _maker_sources(cur: Any, book: I.Book, maker: Optional[str]) -> Set[str]:
    """The sources that are the maker (0144 B1: its voice, or the owner's yes)."""
    if not maker or maker not in book.ents:
        return set()
    from insight_core.markx import person_page as PP
    try:
        got = PP.by_sources(cur, book, maker, set(book.cluster(maker)))
    except Exception:   # noqa: BLE001 - a view never fails for want of it
        return set()
    return {s["id"] for s in got["by"]}


def _event(kind: str, at: datetime, post: Optional[str] = None, **kw: Any) -> Dict[str, Any]:
    return {"kind": kind, "at": at, "post": post, "rank": RANK[kind], **kw}


def events(cur: Any, book: I.Book, root: str, *, stories: Optional[List[Dict[str, Any]]] = None,
           light: bool = False) -> List[Dict[str, Any]]:
    """The cluster's dated events (unsorted, with their post ids; `of_entity` adds the posts' lines). `stories`: the
    entity page's story blocks ({story, mark, headline, voices, first_at}); `light`: only what the post page's
    "before" needs (birth, renames, releases, outside mentions)."""
    from insight_core.markx import rename
    members = set(book.cluster(root))
    lines = lines_of(cur, book, members)
    if not lines.rows:
        return []
    earlier = rename.earlier(cur, book, root)
    early = {m for x in earlier for m in x["members"]}
    maker = maker_of(book, root)
    sites = maker_names(book, root, maker)
    by_maker = _maker_sources(cur, book, maker)
    from insight_core.markx import entity_addresses as EA
    own_hosts = {_host(u) for kind, u, *_ in EA.current(cur, book, [root]).get(root, ())
                 if kind in ("release", "demo", "work")} - {None}

    def from_maker(r: Dict[str, Any]) -> bool:
        return r["source"] in by_maker or _site(r["url"]) in sites or _host(r["url"]) in own_hosts

    out: List[Dict[str, Any]] = []
    rows = lines.rows
    order = sorted(rows, key=lambda p: (rows[p]["at"], p))
    name = lambda e: book.ents[e].name if e in book.ents else None
    first = order[0]
    out.append(_event("birth", rows[first]["at"], first, name=name(sorted(rows[first]["as"])[0])))
    # earlier names: each at its last post, then the first post under the name it has now
    for x in earlier:
        mine = [p for p in order if rows[p]["as"] & set(x["members"])]
        if mine:
            out.append(_event("earlier_name", rows[mine[-1]]["at"], mine[-1], name=x["name"],
                              first=rows[mine[0]]["at"], posts=len(mine)))
    if earlier:
        now_posts = [p for p in order if rows[p]["as"] - early]
        if now_posts:
            out.append(_event("renamed", rows[now_posts[0]]["at"], now_posts[0], name=book.label(root)))
    # releases: about it, by its maker or at its own address
    rel = [p for p in order if rows[p]["roles"] & set(ABOUT) and from_maker(rows[p])]
    for k, p in enumerate(rel):
        out.append(_event("release", rows[p]["at"], p, name=name(sorted(rows[p]["as"])[0]),
                          rank=RANK["release"] if k in (0, len(rel) - 1) else RANK["outside"]))
    if book.ents[root].level in ("family", "thing"):
        kids = sorted({book.root(x) for x, e in book.ents.items() if e.level in I.VERSION_LEVELS and e.parent
                       and e.parent in members and book.root(x) != root})
        if kids:
            kl = lines_of(cur, book, {m for k in kids for m in book.cluster(k)})
            firsts: Dict[str, str] = {}
            for p in sorted(kl.rows, key=lambda q: (kl.rows[q]["at"], q)):
                if not kl.rows[p]["roles"] & set(ABOUT):
                    continue
                for e in kl.rows[p]["as"]:
                    firsts.setdefault(book.root(e), p)
            for k, p in sorted(firsts.items(), key=lambda kv: (kl.rows[kv[1]]["at"], kv[0])):
                if p not in rows:
                    out.append(_event("release", kl.rows[p]["at"], p, name=book.label(k), version=k))
    # outside mentions: the first marked, the rest by month; posts linking back to its posts count
    outside = [p for p in order if not from_maker(rows[p]) and p not in rel]
    linked = _linking_back(cur, set(rows))
    seen = set(rows)
    for p, (at, src) in sorted(linked.items(), key=lambda kv: (kv[1][0], kv[0])):
        if p not in seen and at is not None:
            rows[p] = {"at": at, "roles": {"links"}, "source": src, "url": None, "as": set()}
            outside.append(p)
    outside.sort(key=lambda p: (rows[p]["at"], p))
    if outside:
        p0 = outside[0]
        out.append(_event("first_outside", rows[p0]["at"], p0, linked="links" in rows[p0]["roles"]))
        months: Dict[str, List[str]] = defaultdict(list)
        for p in outside[1:]:
            months[rows[p]["at"].astimezone(timezone.utc).strftime("%Y-%m")].append(p)
        for month, ps in sorted(months.items()):
            out.append(_event("outside", rows[ps[0]]["at"], ps[0], month=month, n=len(ps),
                              sources=len({rows[p]["source"] for p in ps})))
    out = _dedupe(out)
    if light:
        return out
    for s in stories or []:
        if s.get("first_at"):
            out.append(_event("story", s["first_at"], None, story=s["story"], mark=s["mark"],
                              headline=s.get("headline"), voices=s.get("voices")))
    out += _later(cur, root)
    out += _back(cur, set(rows))
    return out


ONE_A_POST = ("birth", "renamed", "earlier_name", "release", "first_outside")


def _dedupe(evs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One line a post among the post events (the most important kept, the others named in its `also`): the birth
    post may be the maker's release or the first outside mention."""
    kept: Dict[str, Dict[str, Any]] = {}
    out = []
    for e in sorted(evs, key=lambda e: (e["rank"], e["at"])):
        p = e.get("post")
        if e["kind"] in ONE_A_POST and p:
            if p in kept:
                kept[p].setdefault("also", []).append(e["kind"])
                continue
            kept[p] = e
        out.append(e)
    return out


def _linking_back(cur: Any, posts: Set[str]) -> Dict[str, Tuple[datetime, str]]:
    """{post: (at, source)}: the posts with a current post edge back to one of `posts` (0131: the newer one links
    or refers back to the older)."""
    if not posts:
        return {}
    cur.execute("""SELECT DISTINCT x.a::text, COALESCE(p.surfaced_at, p.published_at, p.fetched_at), p.source_id::text
                     FROM mx_connections x JOIN posts p ON p.id = x.a
                    WHERE x.valid_to IS NULL AND x.a_kind = 'post' AND x.b_kind = 'post'
                      AND x.b = ANY(%s::uuid[]) AND NOT x.a = ANY(%s::uuid[])""", (sorted(posts), sorted(posts)))
    return {pid: (at, src) for pid, at, src in cur.fetchall()}


def _later(cur: Any, root: str) -> List[Dict[str, Any]]:
    from insight_core.markx import later
    try:
        got = later.of_entity(cur, root)
    except Exception:   # noqa: BLE001 - a view never fails for want of it
        return []
    out = []
    for it in got["items"]:
        if it.get("verdict") == "development" and it.get("at"):
            at = datetime.fromisoformat(it["at"]) if isinstance(it["at"], str) else it["at"]
            out.append(_event("later", at, it.get("post"), story=it.get("story"), headline=it.get("headline")))
    return out


def _back(cur: Any, posts: Set[str]) -> List[Dict[str, Any]]:
    """0136's rows judged development whose old story holds one of `posts`, at their window."""
    from insight_core.markx import back
    if not posts:
        return []
    from insight_core.markx import anchors   # 0180: the engine shown's rows
    cur.execute("""SELECT b.id::text, b.story::text, b.window_at, b.task_id::text, b.posts::text[] FROM mx_back b
                    WHERE b.engine = %s AND (b.members && %s::uuid[]
                          OR b.story IN (SELECT story_id FROM story_posts WHERE post_id = ANY(%s::uuid[])))""",
                (anchors.shown(cur), sorted(posts), sorted(posts)))
    rows = cur.fetchall()
    answers = back._answers(cur, [r[3] for r in rows if r[3]])
    out = []
    for bid, story, at, tid, ps in rows:
        v = back.verdict(answers.get(tid, [])) if tid else None
        if v and v["relation"] == "development":
            out.append(_event("back", at, (ps or [None])[0], story=story, back=bid))
    return out


def _top(evs: List[Dict[str, Any]], n: int = TOP) -> Set[int]:
    order = sorted(range(len(evs)), key=lambda i: (evs[i]["rank"], evs[i]["at"]))
    return set(order[:n])


def _shown(cur: Any, evs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from insight_core.markx.news import _posts
    posts = _posts(cur, {e["post"] for e in evs if e.get("post")})
    out = []
    for e in evs:
        p = posts.get(e["post"]) if e.get("post") else None
        out.append({**{k: v for k, v in e.items() if k != "post"},
                    "post": {k: p.get(k) for k in ("id", "title", "source", "kind", "url")} if p else None})
    return out


def of_entity(cur: Any, book: I.Book, root: str, *, stories: Optional[List[Dict[str, Any]]] = None,
              top: int = TOP) -> Optional[Dict[str, Any]]:
    """The entity page's Timeline: {items (oldest first, each with `top`), shown (how many are top), total, earlier
    (its earlier names)}; None when it has fewer than MIN_EVENTS dated events."""
    from insight_core.markx import rename
    evs = events(cur, book, root, stories=stories)
    if len(evs) < MIN_EVENTS:
        return None
    keep = _top(evs, top)
    for i, e in enumerate(evs):
        e["top"] = i in keep
    evs.sort(key=lambda e: (e["at"], e["rank"], e.get("post") or ""))
    earlier = [{"id": x["id"], "name": x["name"], "names": x["names"]} for x in rename.earlier(cur, book, root)]
    return {"items": _shown(cur, evs), "shown": len(keep), "total": len(evs), "earlier": earlier}


def before_post(cur: Any, post_id: str, *, book: Optional[I.Book] = None, limit: int = BEFORE,
                skip: Iterable[str] = ()) -> List[Dict[str, Any]]:
    """The post page's "before" from its subjects' timelines: for each thing the post is about (its subject mentions'
    entities, not an org or person), up to `limit` previous events (the birth, the last release before it, the
    first outside mention before it), oldest first: [{entity: {id, name}, items}]. `skip`: posts already listed."""
    from insight_core.markx import schemas
    cur.execute("""SELECT m.guide, m.n, m.entity_id::text, COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                     FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                    WHERE m.post_id = %s AND m.guide = ANY(%s) AND m.role = 'subject' AND m.entity_id IS NOT NULL
                    ORDER BY m.n""", (post_id, schemas.mention_guides()))
    rows = cur.fetchall()
    if not rows:
        return []                                   # no subject linked: the book is not read
    book = book or I.load_book(cur)
    skip = set(skip) | {post_id}
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for g, n, eid, at in rows:
        root = book.root(book.pins.get((post_id, g, n), eid))
        if root in seen or root not in book.ents or book.shown_type(root) in I.ORGISH:
            continue
        seen.add(root)
        evs = [e for e in events(cur, book, root, light=True) if e["at"] < at and e.get("post") not in skip]
        if not evs:
            continue
        pick: List[Dict[str, Any]] = []
        for kind in ("birth", "earlier_name", "renamed"):
            pick += [e for e in evs if e["kind"] == kind][:1]
        rel = [e for e in evs if e["kind"] == "release"]
        if rel:
            pick.append(max(rel, key=lambda e: e["at"]))
        pick += [e for e in evs if e["kind"] == "first_outside"][:1]
        got, posts = [], set()
        for e in sorted(pick, key=lambda e: (e["rank"], e["at"])):
            if e["post"] in posts:
                continue
            posts.add(e["post"])
            got.append(e)
            if len(got) >= limit:
                break
        got.sort(key=lambda e: (e["at"], e["rank"]))
        out.append({"entity": {"id": root, "name": book.label(root)}, "items": _shown(cur, got)})
        if len(out) >= 2:
            break
    return out


__all__ = ["before_post", "events", "of_entity"]
