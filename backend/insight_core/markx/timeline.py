"""A thing's timeline (issue 0165 C-D): one dated line of what INSIGHT holds about an entity, read only from stored rows
(posts, mentions, merges, stories, back-in-the-news rows; nothing fetched).

`of_entity` (the entity page's Timeline block, shown when it has 2+ dated events), each event {at, kind, post, ...}:
  - `birth`: the oldest post about it (subject or actor) under any of its names, else the oldest naming it (as which
    name; `named_since` when an older post only names it);
  - `earlier_name` / `renamed`: each earlier name (a rename merge, markx/rename.py) at its last post, and the first post
    under the name it has now;
  - `release`: a post about it (role subject or actor) by its maker (a source that is the maker, or a site whose name
    is the maker's) or at one of its own addresses; a family's versions at their first post about them;
  - `first_outside` / `outside`: the posts by anyone else, the first one about it (or linking back) marked, the rest
    grouped by month (the month's first post about it; a month whose posts only name it is `named_only`, never among the
    top; how many posts and sources); a post linking back to one of its posts (0131's post edges) counts as an outside
    mention though it names it otherwise;
  - `story`: each Mark X or Mark IX story about it (a stop on its line, markx/stops.py), at its first post, with its
    `stop` (what happened to it there: launch, benchmark, ranking, weights...: the stored stop-v1 answer, `stop_by`
    "asked"; else its story type's, `stop_by` "type") and its `share` of the story's members; `in_story`: a story that
    only names it (an answer saying so, or no answer and too few of its members about it), never among the top;
  - `analysis`: a breakdown of it hung on the line: a post about it (subject or actor) by anyone but its maker, read
    as commentary, news_rank.ANALYSIS_CHARS+ characters of its own (News' Analysis rule), with `on` = the stop it
    belongs to (the stop whose story holds it, else the latest stop before it);
  - `back`: 0136's back in the news (judged development). (0163's `later` rows left the line with Later, 0203.)
Each post event inside a stop's story carries that story as `on`.
Each event has its importance (`rank`); the TOP most important (birth, renames, the first and last release, the first
outside mention, stories, then the rest) are `top` (shown by default); "all" shows every one, oldest first.

`before_post` (the post page's "before", D): the post's subjects' previous events, up to BEFORE (the birth, the last
release before it, the first outside mention), oldest first.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlsplit

from insight_core.markx import identity as I
from insight_core.markx import names as N
from insight_core.markx import pairing
from insight_core.utils import voice

TOP = 8
BEFORE = 3
MIN_EVENTS = 2
ABOUT = ("subject", "actor")
RANK = {"birth": 0, "renamed": 1, "earlier_name": 1, "release": 2, "first_outside": 3, "story": 4, "analysis": 5,
        "later": 5, "back": 5, "outside": 6, "in_story": 7}
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
    cur.execute(f"""SELECT m.post_id::text, m.guide, m.n, m.entity_id::text, m.role,
                          {pairing.post_date('p')}, p.source_id::text, p.url
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


def name_forms(book: I.Book, members: Iterable[str]) -> Set[str]:
    """The squashed forms a reading names the thing by: each name of its cluster, and a version's variant word of 4+
    letters ("Astra" for "Orbit 6 Astra"); forms under 3 characters left out (they are inside any text)."""
    out = set()
    for m in members:
        e = book.ents.get(m)
        if e is None:
            continue
        out.add(N.squash(N.key(e.name)))
        if e.variant and len(N.squash(N.key(e.variant))) >= 4:
            out.add(N.squash(N.key(e.variant)))
    return {f for f in out if len(f) >= 3}


def about_by_reading(kind: Optional[str], reading: Optional[Dict[str, Any]], headline: Optional[str],
                     forms: Set[str]) -> bool:
    """Whether a post whose role says it is about a thing is, by its reading (pure): never a round-up (it names
    everything), and its main event (object, actors, headline) names the thing by one of `forms`. No forms, or no main
    event written: yes."""
    reading = reading or {}
    if kind == "roundup" or reading.get("event_type") == "digest":
        return False
    if not forms:
        return True
    main = reading.get("main") if isinstance(reading.get("main"), dict) else {}
    text = " ".join([str(main.get("object") or ""), " ".join(map(str, main.get("actors") or [])),
                     str(main.get("headline_en") or ""), headline or ""])
    sq = N.squash(N.key(text))
    return not sq or any(f in sq for f in forms)   # a reading with no main event to tell by: kept


def named_only(cur: Any, book: I.Book, members: Iterable[str], rows: Dict[str, Dict[str, Any]]) -> Set[str]:
    """0220: the posts whose role says they are about the thing (subject or actor) but whose reading says they only
    name it (about_by_reading: a round-up; the extractor marked the thing subject of a post about another thing) lose
    that role here (`named`): never its birth, a release, its first outside mention or a month's lead, never counted
    in a story's share of it. A post with no reading keeps its role. Which ones, returned."""
    about = sorted(p for p, r in rows.items() if r["roles"] & set(ABOUT))
    if not about:
        return set()
    from insight_core.markx import reading5
    got = reading5.pick(cur, about, ("read-v3", "read-v2"))
    forms = name_forms(book, members)
    out = set()
    for p in about:
        r = got.get(p)
        if r and not about_by_reading(r.get("kind"), r.get("reading"), r.get("headline"), forms):
            rows[p]["roles"] = (rows[p]["roles"] - set(ABOUT)) | {"named"}
            out.add(p)
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
    from insight_core.markx import stops as ST
    if ST.config().get("by_reading"):   # 0220: a round-up, or a post about another thing, only names it (off: under its bar)
        named_only(cur, book, members, lines.rows)
    earlier = rename.earlier(cur, book, root)
    early = {m for x in earlier for m in x["members"]}
    from insight_core.markx import entity_facts
    fact = entity_facts.read(cur, [root]).get(root)   # 0184: the maker the facts give, else by identity
    maker = (book.root(fact.maker_id) if fact and fact.maker_id else None) or maker_of(book, root)
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
    about = [p for p in order if rows[p]["roles"] & set(ABOUT)]
    first = (about or order)[0]                      # 0165 v10.23: the oldest post about it, else naming it
    out.append(_event("birth", rows[first]["at"], first, name=name(sorted(rows[first]["as"])[0]),
                      **({"named_since": rows[order[0]]["at"]} if order[0] != first else {})))
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
        kids = sorted({book.root(x) for x in book.with_parent_in(root)   # v10.17 (0186): asked, not walked
                       if (e := book.ents[x]).level in I.VERSION_LEVELS and e.parent in members and book.root(x) != root})
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
        # 0165 v10.23: the first outside post about it (subject or actor) or linking back to its posts; a post that
        # only names it is counted in its month, never marked first
        firsts = [p for p in outside if rows[p]["roles"] & (set(ABOUT) | {"links"})]
        p0 = firsts[0] if firsts else None
        if p0 is not None:
            out.append(_event("first_outside", rows[p0]["at"], p0, linked="links" in rows[p0]["roles"]))
        months: Dict[str, List[str]] = defaultdict(list)
        for p in outside:
            if p not in (p0, first):            # the birth is its own line
                months[rows[p]["at"].astimezone(timezone.utc).strftime("%Y-%m")].append(p)
        for month, ps in sorted(months.items()):
            lead = next((p for p in ps if rows[p]["roles"] & set(ABOUT)), None)
            out.append(_event("outside", rows[lead or ps[0]]["at"], lead or ps[0], month=month, n=len(ps),
                              sources=voice.count((voice.Said(rows[p]["source"]) for p in ps), voice.Policy.MARKX),
                              **({} if lead else {"named_only": True, "rank": RANK["in_story"]})))
    if light:
        return _dedupe(out)
    stops = _stories(cur, book, root, stories or [], rows)
    out += stops
    out += _analysis(cur, rows, outside) if ST.config()["analysis"] else []   # 0165: off, under its bar
    out = _dedupe(out)
    _hang(out, stops)
    out += _back(cur, set(rows))
    return out


def _stories(cur: Any, book: I.Book, root: str, stories: List[Dict[str, Any]],
             rows: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The page's stories as `story` (a stop) or `in_story` events: the stored stop answer decides, else the thing's
    share of the members (stops.candidate) with the story type's stop. A story given without its members is a stop
    (the caller knows no better)."""
    from insight_core.markx import event_types, stops as ST
    dated = [s for s in stories if s.get("first_at")]
    members = {s["story"]: [str(p) for p in s.get("members") or []] for s in dated}
    at: Dict[str, datetime] = {p: r["at"] for p, r in rows.items()}
    ids = sorted({p for ps in members.values() for p in ps} - set(at))
    if ids:
        cur.execute(f"SELECT p.id::text, {pairing.post_date('p')} FROM posts p WHERE p.id = ANY(%s::uuid[])", (ids,))
        at.update({p: a for p, a in cur.fetchall() if a is not None})
    on = ST.config()
    answers = ST.of(cur, book, root, list(members))
    types = event_types.of_stories(cur, {s: ps for s, ps in members.items() if s not in answers and ps}) \
        if on["stop_types"] else {}
    out = []
    for s in dated:
        ps = members[s["story"]]
        sh = ST.share([(at[p], p) for p in ps if p in at],
                      [p for p in ps if p in rows and rows[p]["roles"] & set(ABOUT)])
        got = answers.get(s["story"])
        if got is not None:
            about, stop, by = got.about, got.stop, "asked"
        else:
            about, stop, by = (ST.candidate(sh) if ps else True), ST.coarse(types.get(s["story"])), "type"
        about = about or not on["stops"]                  # the split off: every story a stop, as before 0165's case 2
        stop = stop if on["stop_types"] else None         # the word off: kept in the answers, not shown
        out.append(_event("story" if about else "in_story", s["first_at"], None, story=s["story"], mark=s["mark"],
                          headline=s.get("headline"), voices=s.get("voices"), stop=stop, stop_by=by,
                          share=[sh.about, sh.members], members=ps))
    return out


def _analysis(cur: Any, rows: Dict[str, Dict[str, Any]], outside: List[str]) -> List[Dict[str, Any]]:
    """Breakdowns of the thing (News' Analysis rule, news_rank): its outside posts about it (subject or actor) read as
    commentary, with ANALYSIS_CHARS+ characters of their own and an origin that is not its maker."""
    from insight_core.markx import news_rank as NR
    cand = sorted(p for p in outside if rows[p]["roles"] & set(ABOUT))
    if not cand:
        return []
    pick = f"FROM mx_readings r WHERE r.post_id = p.id AND {NR._RANK} IS NOT NULL"
    cur.execute(f"""SELECT p.id::text, char_length(btrim(COALESCE(p.content, ''))) - CASE
                          WHEN COALESCE(p.title, '') <> '' AND btrim(COALESCE(p.content, '')) LIKE p.title || '%%'
                          THEN char_length(p.title) ELSE 0 END,
                          (SELECT r.kind {pick} ORDER BY {NR._RANK} LIMIT 1),
                          (SELECT r.reading->>'origin' {pick} AND r.reading ? 'origin' ORDER BY {NR._RANK} LIMIT 1)
                     FROM posts p WHERE p.id = ANY(%s::uuid[])""", (cand,))
    return [_event("analysis", rows[p]["at"], p) for p, own, kind, origin in cur.fetchall()
            if analysis(kind, own, origin)]


def analysis(kind: Optional[str], own_chars: Optional[int], origin: Optional[str]) -> bool:
    """A breakdown (pure): read as commentary, ANALYSIS_CHARS+ characters of its own, its origin not the maker."""
    from insight_core.markx import news_rank as NR
    return kind in NR.ANALYSIS_KINDS and (own_chars or 0) >= NR.ANALYSIS_CHARS and origin != "maker"


def _hang(evs: List[Dict[str, Any]], stops: List[Dict[str, Any]]) -> None:
    """Each post event inside a stop's story gets that story as `on` (the earliest such stop); an analysis outside
    every stop hangs on the latest stop before it. The stops' member lists are dropped (not shown)."""
    line = sorted((e for e in stops if e["kind"] == "story"), key=lambda e: (e["at"], e["story"]))
    of_post: Dict[str, str] = {}
    for e in line:
        for p in e.get("members") or []:
            of_post.setdefault(p, e["story"])
    for e in evs:
        p = e.get("post")
        if not p or e["kind"] in ("story", "in_story", "back"):
            continue
        if p in of_post:
            e["on"] = of_post[p]
        elif e["kind"] == "analysis" or "analysis" in (e.get("also") or []):
            before = [s for s in line if s["at"] <= e["at"]]
            if before:
                e["on"] = before[-1]["story"]
    for e in stops:
        e.pop("members", None)


ONE_A_POST = ("birth", "renamed", "earlier_name", "release", "first_outside", "analysis")


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
    cur.execute(f"""SELECT DISTINCT x.a::text, {pairing.post_date('p')}, p.source_id::text
                     FROM mx_connections x JOIN posts p ON p.id = x.a
                    WHERE x.valid_to IS NULL AND x.a_kind = 'post' AND x.b_kind = 'post'
                      AND x.b = ANY(%s::uuid[]) AND NOT x.a = ANY(%s::uuid[])""", (sorted(posts), sorted(posts)))
    return {pid: (at, src) for pid, at, src in cur.fetchall()}


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
    """The `n` most important events (a story, or a month of posts, that only names the thing never)."""
    order = sorted((i for i in range(len(evs)) if evs[i]["kind"] != "in_story" and not evs[i].get("named_only")),
                   key=lambda i: (evs[i]["rank"], evs[i]["at"]))
    return set(order[:n])


def _shown(cur: Any, evs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from insight_core.markx.news import _posts
    posts = _posts(cur, {e["post"] for e in evs if e.get("post")})
    out = []
    for e in evs:
        p = posts.get(e["post"]) if e.get("post") else None
        out.append({**{k: v for k, v in e.items() if k != "post"},
                    "post": {k: p.get(k) for k in ("id", "title", "source", "kind", "url", "byline")} if p else None})
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
    first outside mention before it) and its last STOPS_BEFORE stops before it (v10.23: the stories about it, as the
    entity page's line has them), oldest first: [{entity: {id, name}, items}]. `skip`: posts already listed."""
    from insight_core.markx import schemas
    cur.execute(f"""SELECT m.guide, m.n, m.entity_id::text, {pairing.post_date('p')}
                     FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                    WHERE m.post_id = %s AND m.guide = ANY(%s) AND m.role = 'subject' AND m.entity_id IS NOT NULL
                    ORDER BY m.n""", (post_id, schemas.mention_guides()))
    rows = cur.fetchall()
    if not rows:
        return []                                   # no subject linked: the book is not read
    book = book or I.lazy_book(cur)   # v10.17 (0186): what the post's subjects ask of the book
    skip = set(skip) | {post_id}
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for g, n, eid, at in rows:
        root = book.root(book.pins.get((post_id, g, n), eid))
        if root in seen or root not in book.ents or book.shown_type(root) in I.ORGISH:
            continue
        seen.add(root)
        evs = [e for e in events(cur, book, root, light=True) if e["at"] < at and e.get("post") not in skip]
        stops_before = _stops_before(cur, book, root, post_id, at)
        if not evs and not stops_before:
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
        got += stops_before
        got.sort(key=lambda e: (e["at"], e["rank"]))
        out.append({"entity": {"id": root, "name": book.label(root)}, "items": _shown(cur, got)})
        if len(out) >= 2:
            break
    return out


STOPS_BEFORE = 3


def _stops_before(cur: Any, book: I.Book, root: str, post_id: str, at: datetime,
                  limit: int = STOPS_BEFORE) -> List[Dict[str, Any]]:
    """D, the second case: the thing's stops before a post (its stored stop answers saying about; the stories the post
    is in left out), the newest `limit`, as `story` events at their first member's date. Nothing is asked here."""
    from insight_core.markx import stops as ST
    on = ST.config()
    if not on["stops"]:
        return []
    got = {s: x for s, x in ST.of(cur, book, root, None).items() if x.about}
    if not got:
        return []
    cur.execute(f"""SELECT sp.story_id::text, min({pairing.post_date('p')}), s.headline,
                           bool_or(sp.post_id = %s::uuid)
                      FROM mx_story_posts sp JOIN posts p ON p.id = sp.post_id JOIN mx_stories s ON s.id = sp.story_id
                     WHERE sp.valid_to IS NULL AND sp.role = 'member' AND sp.story_id = ANY(%s::uuid[])
                     GROUP BY sp.story_id, s.headline""", (post_id, sorted(got)))
    rows = [(sid, first, head) for sid, first, head, mine in cur.fetchall() if first is not None and first < at and not mine]
    rows.sort(key=lambda r: (r[1], r[0]))
    return [_event("story", first, None, story=sid, mark="x", headline=head,
                   stop=got[sid].stop if on["stop_types"] else None, stop_by="asked") for sid, first, head in rows[-limit:]]


# ---- 0220: the version line ---------------------------------------------------------------------------------------
# A family's versions on one line ("Orbit 2 -> Orbit 2.5 -> Orbit 3"), the order graph.next_version_edges joins posts by.
# Measured on the server's families (plan/issues/0220): what failed was a class each, kept off here:
#   - two lines told apart by a letter (DeepSeek-style R1 / V3, MiniMax-style M3 / H3) read as one: the letter is the
#     line (`line_key`); a number written without its letter joins the only lettered line that has it, unless the
#     family's unlettered numbers are a line of their own;
#   - another maker's thing filed under the family's name ("Zentra Orbit 5" under Vantor's Orbit): its stated maker;
#   - a version named once, or never the subject of a post (a typo, a guess at a future number): LINE_POSTS, LINE_ABOUT;
#   - a build or date number in a family numbered 1, 2, 3 (2512, 407): BUILD_FROM; a dot left out (46 for 4.6) is the
#     dotted version's stop;
#   - a one-letter family ("X-33", "X-45" under "x"): no line.
LINE_POSTS = 4        # posts naming a version (any role), at least (dev: 2 or 3 were guesses and slips, 0220)
LINE_ABOUT = 1        # posts whose subject or actor it is, at least
BUILD_FROM = 100      # a first number this big is a build or a date when the family's other numbers are small


@dataclass(frozen=True)
class Version:
    """One version entity of a family, as the line reads it."""
    id: str
    name: str
    key: Optional[Tuple[Any, ...]]   # its version tuple (names.vt: "K3.1" -> ('k', 3, 1); a leading v dropped)
    maker: Optional[str]             # its stated maker (same_maker compares)
    posts: int                       # posts naming it
    about: int                       # posts whose subject or actor it is
    first: Optional[datetime]        # its first post about it
    first_post: Optional[str]


@dataclass
class LineStop:
    key: Tuple[str, Tuple[int, ...]]
    versions: List[Version]          # the most named first
    first: Optional[datetime] = None
    first_post: Optional[str] = None
    posts: int = 0
    about: int = 0


def line_key(t: Any) -> Optional[Tuple[str, Tuple[int, ...]]]:
    """(its line's letter, its numbers) for a version tuple: ('k', (3, 1)) for K3.1, ('', (5,)) for 5.0; None unless the
    rest is numbers ("3.x", "Pro")."""
    if not t:
        return None
    t = tuple(t)
    prefix = ""
    if isinstance(t[0], str):
        prefix, t = t[0], t[1:]
    if not t or not all(isinstance(x, int) and not isinstance(x, bool) for x in t):
        return None
    while len(t) > 1 and t[-1] == 0:
        t = t[:-1]
    return prefix, t


def _lettered(k: Optional[Tuple[str, Tuple[int, ...]]], name: Optional[str]) -> Optional[Tuple[str, Tuple[int, ...]]]:
    """A version whose fields lost its letter ("Kite K2.6" read as version 2.6) takes the letter its name writes right
    before the number (never `v`: "V3" is 3, as names.vt reads it)."""
    if k is None or k[0]:
        return k
    num = r"\.".join(map(str, k[1]))
    m = re.search(rf"(?<![a-z0-9])([a-uw-z])[ -]?{num}(?![0-9]|\.[0-9])", unicodedata.normalize("NFKC", name or "").casefold())
    return (m.group(1), k[1]) if m else k


def _stop(key: Tuple[str, Tuple[int, ...]], vs: List[Version]) -> LineStop:
    vs = sorted(vs, key=lambda v: (-v.posts, -v.about, line_key(v.key) != key, v.name, v.id))   # as its line writes it
    # its date: the first post about it under a name that is on the line by itself (a stray one-post name filed under
    # the number never dates it: 0220 dev, 20 of 60 such names were another thing)
    dated = sorted((v.first, v.first_post or "") for n, v in enumerate(vs)
                   if v.first is not None and (n == 0 or v.posts >= LINE_POSTS))
    return LineStop(key, vs, dated[0][0] if dated else None, (dated[0][1] or None) if dated else None,
                    sum(v.posts for v in vs), sum(v.about for v in vs))


def _on_line(s: LineStop) -> bool:
    return s.posts >= LINE_POSTS and s.about >= LINE_ABOUT


def _line_maker(vs: List[Version], same_maker: Any) -> Optional[str]:
    """The maker most of the family's posts state for its versions (a family's own maker field is its first run's
    majority, and can be wrong)."""
    best, score = None, 0
    for m in sorted({v.maker for v in vs if v.maker}):
        n = sum(v.posts for v in vs if v.maker and same_maker(v.maker, m))
        if n > score:
            best, score = m, n
    return best


def version_lines(versions: Iterable[Version], *, family_name: Optional[str], family_maker: Optional[str],
                  same_maker: Any) -> List[List[LineStop]]:
    """A family's lines (pure): each its stops oldest version first, the longest line first; a line of one stop is no
    line. A version whose stated maker is not the one most of its family's posts state (else `family_maker`) is off.
    `same_maker(a, b)`: two stated makers name one maker."""
    if len(N.squash(N.key(family_name))) < 2:
        return []
    keyed = [(_lettered(line_key(v.key), v.name), v) for v in versions]
    keyed = [(k, v) for k, v in keyed if k is not None]
    maker = _line_maker([v for _, v in keyed], same_maker) or family_maker
    cand = [(k, v) for k, v in keyed if not (maker and v.maker and not same_maker(v.maker, maker))]
    if any(k[1][0] < BUILD_FROM for k, _ in cand):
        cand = [(k, v) for k, v in cand if k[1][0] < BUILD_FROM]
    groups: Dict[Tuple[str, Tuple[int, ...]], List[Version]] = defaultdict(list)
    for k, v in cand:
        groups[k].append(v)
    # a dot left out: a number whose digits are another stop's of the same line run together is that stop, when that
    # stop is the better named (the slip is the rarer spelling: "Orbit 46" for 4.6, never "Orbit 11" into a 1.1)
    for k in sorted(groups):
        if len(k[1]) == 1 and k[1][0] >= 10:
            hit = [o for o in groups if o[0] == k[0] and len(o[1]) > 1 and "".join(map(str, o[1])) == str(k[1][0])]
            if len(hit) == 1 and sum(v.posts for v in groups[hit[0]]) > sum(v.posts for v in groups[k]):
                groups[hit[0]] += groups.pop(k)
    # a number written without its letter: the only lettered line that has it, unless the unlettered numbers with no
    # lettered twin are a line of their own (two stops or more)
    letters = {k[0] for k in groups if k[0]}
    twin = {k: [p for p in sorted(letters) if (p, k[1]) in groups] for k in groups if k[0] == ""}
    own = [k for k, ps in twin.items() if len(ps) != 1 and _on_line(_stop(k, groups[k]))]
    if len(own) < 2:
        for k, ps in twin.items():
            if len(ps) == 1:
                groups[(ps[0], k[1])] += groups.pop(k)
    lines: Dict[str, List[LineStop]] = defaultdict(list)
    for k in sorted(groups, key=lambda k: (k[0], k[1])):
        s = _stop(k, groups[k])
        if _on_line(s):
            lines[k[0]].append(s)
    return sorted((ln for ln in lines.values() if len(ln) >= 2), key=lambda ln: (-len(ln), ln[0].key[0]))


def maker_word(m: Optional[str]) -> str:
    """A stated maker as one word: its key, a corporate word at its end dropped ("Zentra AI" -> "zentra")."""
    words = N.key(m).split()
    while len(words) > 1 and words[-1] in I.CORP_WORDS:
        words = words[:-1]
    return N.squash(" ".join(words))


def same_maker(a: Optional[str], b: Optional[str]) -> bool:
    return bool(maker_word(a)) and maker_word(a) == maker_word(b)


def version_counts(cur: Any, members: Dict[str, Iterable[str]]) -> Dict[str, Tuple[int, int, Optional[datetime], Optional[str]]]:
    """{version root: (posts naming it, posts about it (subject or actor), its first post about it, that post)} over
    its cluster's ids (`members`), counted by the database (one row an id; nothing per post comes back)."""
    from insight_core.markx import schemas
    of = {m: r for r, ms in members.items() for m in ms}
    if not of:
        return {}
    cur.execute(f"""SELECT m.entity_id::text, count(DISTINCT m.post_id),
                           count(DISTINCT m.post_id) FILTER (WHERE m.role IN ('subject', 'actor')),
                           (array_agg(m.post_id::text ORDER BY {pairing.post_date('p')}, m.post_id)
                              FILTER (WHERE m.role IN ('subject', 'actor') AND {pairing.post_date('p')} IS NOT NULL))[1],
                           min({pairing.post_date('p')}) FILTER (WHERE m.role IN ('subject', 'actor'))
                      FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                     WHERE m.guide = ANY(%s) AND m.entity_id = ANY(%s::uuid[]) GROUP BY m.entity_id""",
                (schemas.mention_guides(), sorted(of)))
    out: Dict[str, List[Any]] = {}
    for eid, n, about, post, first in cur.fetchall():
        r = out.setdefault(of[eid], [0, 0, None, None])
        r[0] += n
        r[1] += about
        if first is not None and (r[2] is None or first < r[2]):
            r[2], r[3] = first, post
    return {r: tuple(x) for r, x in out.items()}


def line_versions(rows: Iterable[Tuple[str, str, Any, Optional[str]]],
                  counts: Dict[str, Tuple[int, int, Optional[datetime], Optional[str]]]) -> List[Version]:
    """Versions from (root, name, version tuple, stated maker) rows and their `version_counts`."""
    return [Version(r, name, tuple(key) if key else None, maker, *(counts.get(r) or (0, 0, None, None)))
            for r, name, key, maker in rows]


def version_line(cur: Any, book: I.Book, root: str) -> Optional[Dict[str, Any]]:
    """The entity page's version line (0220): the lines of its family (the entity's own family, or itself when it is
    one), the one holding this entity first. {family {id, name}, lines: [[{id, name, version, first, posts, current}]]}
    (each stop by the name most posts use; the other names filed under its number are not shown: 0220 dev, a third of
    them were another thing); None when the family has no line."""
    e = book.ents[root]
    fam = root if e.level in ("family", "thing") else (book.root(e.parent) if e.parent and e.level in I.VERSION_LEVELS else None)
    if not fam or fam not in book.ents:
        return None
    kids = sorted({book.root(x) for x in book.with_parent_in(fam)})
    rows = [(k, book.label(k), book.ents[k].version_key, book.ents[k].maker) for k in kids
            if k in book.ents and book.ents[k].level == "version" and book.ents[k].status != "not_entity"
            and not (book.ents[k].variant or book.ents[k].size or book.ents[k].build)]
    if len(rows) < 2:
        return None
    counts = version_counts(cur, {k: book.cluster(k) for k, *_ in rows})
    fe = book.ents[fam]
    lines = version_lines(line_versions(rows, counts), family_name=book.label(fam), family_maker=fe.maker,
                          same_maker=same_maker)
    if not lines:
        return None
    mine = book.root(root)
    lines.sort(key=lambda ln: not any(v.id == mine for s in ln for v in s.versions))
    return {"family": {"id": fam, "name": book.label(fam)},
            "lines": [[{"id": s.versions[0].id, "name": s.versions[0].name, "version": book.ents[s.versions[0].id].version,
                        "first": s.first, "posts": s.posts, "current": any(v.id == mine for v in s.versions)}
                       for s in ln] for ln in lines]}


__all__ = ["LineStop", "Version", "before_post", "events", "line_key", "of_entity", "same_maker", "version_counts",
           "version_line", "version_lines"]
