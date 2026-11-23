"""A thing's timeline: one dated line of what INSIGHT holds about an entity, read only from stored rows (posts,
mentions, merges, stories, back-in-the-news rows; nothing fetched).

`of_entity` (the entity page's Timeline block, 2+ dated events): events {at, kind, post, ...} of kinds `birth`,
`earlier_name` / `renamed`, `release` (by its maker or its stored original, else its first release report; a
family's versions by the same rule), `first_outside` / `outside` (posts by anyone else, grouped by month; a post
linking back counts), `story` / `in_story` (a stop on its line, markx/stops.py), `analysis` (a breakdown, News'
Analysis rule) and `back`. Birth, releases and the first outside mention are about the thing by their reading
(`about_by_reading`) and never a background page. Each post event inside a stop's story carries it as `on`; the TOP
most important events are `top`. `before_post`: the post page's "before" from its subjects' timelines. `version_line`:
the entity page's version line.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlsplit

from insight_core.markx import identity as I
from insight_core.markx import names as N
from insight_core.markx import pairing
from insight_core.utils import voice

TOP = 8
BEFORE = 3
MIN_EVENTS = 2
ABOUT = ("subject", "actor")
OUTSIDE_ROLES = ABOUT + ("compared",)   # the roles an outside event's post gives the thing (stops.config outside_roles)
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
            eid: Optional[str], kind: Optional[str] = None) -> None:
        r = self.rows.setdefault(pid, {"at": at, "roles": set(), "source": src, "url": url, "as": set(), "kind": kind})
        r["roles"].add(role or "mention")
        if eid:
            r["as"].add(eid)


def lines_of(cur: Any, book: I.Book, members: Iterable[str]) -> Lines:
    from insight_core.markx import schemas
    ids = sorted(set(members))
    out = Lines()
    if not ids:
        return out
    # the linked mentions by the entity index, the pinned ones apart (one OR is a full scan of mx_mentions)
    sql = f"""SELECT m.post_id::text, m.guide, m.n, m.entity_id::text, m.role,
                     {pairing.post_date('p')}, p.source_id::text, p.url,
                     (SELECT s.platform FROM sources s WHERE s.id = p.source_id)
                FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
               WHERE m.guide = ANY(%s)"""
    guides = schemas.mention_guides()
    cur.execute(f"""{sql} AND m.entity_id = ANY(%s::uuid[])
                    UNION ALL
                    {sql} AND (m.entity_id IS NULL OR m.entity_id <> ALL(%s::uuid[])) AND (m.post_id, m.guide, m.n) IN
                          (SELECT post_id, guide, n FROM mx_entity_pins WHERE undone_at IS NULL AND entity_id = ANY(%s::uuid[]))""",
                (guides, ids, guides, ids, ids))
    want = set(ids)
    for pid, g, n, eid, role, at, src, url, kind in cur.fetchall():
        e = book.pins.get((pid, g, n), eid)
        if e in want and at is not None:
            out.add(pid, at, role, src, url, e, kind)
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
    """The posts whose role says they are about the thing but whose reading says they only name it (a round-up; a post
    about another thing) lose that role here (`named`): never its birth, a release, its first outside mention or a
    month's lead, never counted in a story's share. A post with no reading keeps its role. Returns which ones."""
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


FIRST_CHUNK = 50      # outside posts read at a time while looking for the first one about the thing


def _first_about(cur: Any, book: I.Book, members: Iterable[str], rows: Dict[str, Dict[str, Any]],
                 order: List[str], roles: Tuple[str, ...] = ("subject",)) -> Optional[str]:
    """The first outside mention, of `order` (oldest first): a post linking back to its posts, or one whose main subject
    is the thing (`roles`, by its reading: about_by_reading). A post about another thing that names this one as a
    subject (a method shown on another maker's model) is never it. The readings are read a chunk at a time until one is
    found."""
    from insight_core.markx import reading5
    forms: Optional[Set[str]] = None
    cand = [p for p in order if "links" in rows[p]["roles"] or rows[p]["roles"] & set(roles)]
    for k in range(0, len(cand), FIRST_CHUNK):
        part = cand[k:k + FIRST_CHUNK]
        need = [p for p in part if "links" not in rows[p]["roles"]]
        got = reading5.pick(cur, need, ("read-v3", "read-v2")) if need else {}
        if forms is None:
            forms = name_forms(book, members)
        for p in part:
            r = got.get(p)
            if "links" in rows[p]["roles"] or not r or about_by_reading(r.get("kind"), r.get("reading"),
                                                                        r.get("headline"), forms):
                return p
    return None


def _maker_sources(cur: Any, book: I.Book, maker: Optional[str]) -> Set[str]:
    """The sources that are the maker (its voice, or the owner's yes)."""
    if not maker or maker not in book.ents:
        return set()
    from insight_core.markx import person_page as PP
    try:
        got = PP.by_sources(cur, book, maker, set(book.cluster(maker)))
    except Exception:   # noqa: BLE001 - a view never fails for want of it
        return set()
    return {s["id"] for s in got["by"]}


def _types(cur: Any, posts: Iterable[str]) -> Dict[str, Any]:
    """{post: event_types.EventType} of the posts with a reading (one query)."""
    from insight_core.markx import event_types
    return event_types.of_posts(cur, posts)


def is_release(t: Any) -> bool:
    """Whether a post's EventType says it is a release (pure): a release-typed reading (RELEASE_TYPES), else, with no
    closed type, a main action of the release group that released it ("launched", never "delayed"); never a leak."""
    if t is None or t.type == LEAK_TYPE:
        return False
    if t.type:
        return t.type in RELEASE_TYPES
    return t.group == "release" and t.stage == "released"


class _Kinded:
    __slots__ = ("id", "kind")

    def __init__(self, pid: str, kind: Optional[str]):
        self.id, self.kind = pid, kind


def _background(rows: Dict[str, Dict[str, Any]], posts: List[str]) -> Set[str]:
    """The posts of `posts` that are background to the thing (story_rules.background: a Saved page dated well before its
    first post of a voice): never its birth, a release or its first outside."""
    from insight_core.utils.story_rules import background
    return background([_Kinded(p, rows[p].get("kind")) for p in posts], {p: rows[p]["at"] for p in posts})


def _original_post(cur: Any, book: I.Book, root: str) -> Optional[str]:
    """The stored post of the thing's original (entity_views.original), None when it has none stored."""
    from insight_core.markx import entity_views as EV
    try:
        got = EV.original(cur, book, root).get("original") or {}
    except Exception:   # noqa: BLE001 - a view never fails for want of it
        return None
    return (got.get("post") or {}).get("id")


def maker_copy(row: Dict[str, Any], t: Any) -> bool:
    """A saved page (no voice) whose reading's origin is the maker: a copy of the maker's own post (pure). A voiced
    source's origin `maker` says only that its author made what it announces (a quant, an engine's support), never
    this thing: its maker is told by its source, site or address (`from_maker`)."""
    return row.get("kind") in voice.NOT_VOICE and t is not None and t.origin == "maker"


def releases(cur: Any, book: I.Book, members: Iterable[str], rows: Dict[str, Dict[str, Any]], about: List[str],
             types: Dict[str, Any], from_maker: Any, original_post: Optional[str],
             reports_too: bool = True) -> List[str]:
    """A thing's release posts, oldest first, of `about` (its posts about it, oldest first, background left out): each
    release-typed post (is_release) about it by its reading that is its maker's (`from_maker`, or a saved copy:
    `maker_copy`), and its stored original (`original_post`) when about it. With none (and `reports_too`: never a
    family's own line, its versions are what is released), its first release report: a release-typed post whose subject
    it is, not a saved page. A maker post that is no release and a post that only names it are never one."""
    from insight_core.markx import reading5
    # a maker post not read yet keeps its place (nothing to tell by, as about_by_reading keeps an unread post's role)
    cand = [p for p in about if (from_maker(rows[p]) and p not in types)
            or is_release(types.get(p)) and (from_maker(rows[p]) or maker_copy(rows[p], types[p]))]
    got = reading5.pick(cur, cand, ("read-v3", "read-v2")) if cand else {}
    forms = name_forms(book, members)

    def theirs(p: str) -> bool:
        r = got.get(p)
        if not r:
            return from_maker(rows[p])
        if not about_by_reading(r.get("kind"), r.get("reading"), r.get("headline"), forms):
            return False
        main = (r.get("reading") or {}).get("main")
        obj = N.squash(N.key(str(main.get("object") or ""))) if isinstance(main, dict) else ""
        return from_maker(rows[p]) or not forms or any(f in obj for f in forms)
    rel = [p for p in cand if theirs(p)]
    if original_post and original_post in about and original_post not in rel:
        rel = sorted(rel + [original_post], key=lambda p: (rows[p]["at"], p))
    if rel or not reports_too:
        return rel
    reports = [p for p in about if "subject" in rows[p]["roles"] and is_release(types.get(p))
               and rows[p].get("kind") not in voice.NOT_VOICE]
    got = _first_about(cur, book, members, rows, reports)
    return [got] if got else []


def _event(kind: str, at: datetime, post: Optional[str] = None, **kw: Any) -> Dict[str, Any]:
    return {"kind": kind, "at": at, "post": post, "rank": RANK[kind], **kw}


def events(cur: Any, book: I.Book, root: str, *, stories: Optional[List[Dict[str, Any]]] = None,
           light: bool = False, original_post: Any = ...) -> List[Dict[str, Any]]:
    """The cluster's dated events (unsorted, with their post ids; `of_entity` adds the posts' lines). `stories`: the
    entity page's story blocks ({story, mark, headline, voices, first_at}); `light`: only what the post page's
    "before" needs (birth, renames, releases, outside mentions); `original_post`: its stored original's post id (the
    entity page has it; read when not given)."""
    from insight_core.markx import rename
    members = set(book.cluster(root))
    lines = lines_of(cur, book, members)
    if not lines.rows:
        return []
    from insight_core.markx import stops as ST
    if ST.config().get("by_reading"):   # a round-up, or a post about another thing, only names it (off: under its bar)
        named_only(cur, book, members, lines.rows)
    earlier = rename.earlier(cur, book, root)
    early = {m for x in earlier for m in x["members"]}
    from insight_core.markx import entity_facts
    fact = entity_facts.read(cur, [root]).get(root)   # the maker the facts give, else by identity
    maker = (book.root(fact.maker_id) if fact and fact.maker_id else None) or maker_of(book, root)
    sites = maker_names(book, root, maker)
    by_maker = _maker_sources(cur, book, maker)
    from insight_core.markx import entity_addresses as EA
    from insight_core.utils.url_normalization import normalize_url
    # a post at one of its own addresses (the address itself, never any page of its host: a release address on
    # youtube.com would make every post there the maker's)
    own_urls = {normalize_url(u) or u for kind, u, *_ in EA.current(cur, book, [root]).get(root, ())
                if kind in ("release", "demo", "work") and u}

    def from_maker(r: Dict[str, Any]) -> bool:
        return (r["source"] in by_maker or _site(r["url"]) in sites
                or bool(r["url"]) and (normalize_url(r["url"]) or r["url"]) in own_urls)

    out: List[Dict[str, Any]] = []
    rows = lines.rows
    order = sorted(rows, key=lambda p: (rows[p]["at"], p))
    name = lambda e: book.ents[e].name if e in book.ents else None
    about = [p for p in order if rows[p]["roles"] & set(ABOUT)]
    types = _types(cur, about)
    bg = _background(rows, about)                    # an old Saved page neither dates nor starts it
    dated = [p for p in about if p not in bg]
    # the oldest post about it by its reading, else naming it; never a background page
    first = _first_about(cur, book, members, rows, dated, ABOUT) or (dated or about or order)[0]
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
    # releases (`releases`): a release-typed post about it by its maker, or its stored original
    orig = original_post if original_post is not ... else _original_post(cur, book, root)
    rel = releases(cur, book, members, rows, dated, types, from_maker, orig,
                   reports_too=book.ents[root].level != "family")   # a family is released by its versions
    for k, p in enumerate(rel):
        out.append(_event("release", rows[p]["at"], p, name=name(sorted(rows[p]["as"])[0]),
                          rank=RANK["release"] if k in (0, len(rel) - 1) else RANK["outside"]))
    if book.ents[root].level in ("family", "thing"):
        kids = sorted({book.root(x) for x in book.with_parent_in(root)   # asked, not walked
                       if (e := book.ents[x]).level in I.VERSION_LEVELS and e.parent in members and book.root(x) != root})
        if kids:
            kl = lines_of(cur, book, {m for k in kids for m in book.cluster(k)})
            k_about = sorted((p for p in kl.rows if kl.rows[p]["roles"] & set(ABOUT)),
                             key=lambda q: (kl.rows[q]["at"], q))
            k_types = _types(cur, k_about)
            k_bg = _background(kl.rows, k_about)
            firsts: Dict[str, str] = {}
            for k in kids:   # a version's release by the same rule (its first), never any post naming it
                mine = [p for p in k_about if p not in k_bg and k in {book.root(e) for e in kl.rows[p]["as"]}]
                got = releases(cur, book, set(book.cluster(k)), kl.rows, mine, k_types, from_maker, None)
                if got:
                    firsts[k] = got[0]
            for k, p in sorted(firsts.items(), key=lambda kv: (kl.rows[kv[1]]["at"], kv[0])):
                if p not in rows:
                    out.append(_event("release", kl.rows[p]["at"], p, name=book.label(k), version=k))
    # outside mentions: the first marked, the rest by month; posts linking back to its posts count. A saved copy of the
    # maker's own post is not outside
    outside = [p for p in order if not from_maker(rows[p]) and p not in rel
               and not (p in types and maker_copy(rows[p], types[p]))]
    about_roles = set(OUTSIDE_ROLES) if ST.config().get("outside_roles") else set(ABOUT)
    if ST.config().get("outside_roles"):
        # an outside event is a post about the thing (its subject, actor or compared), never one that only names it; the
        # posts linking back are added below
        outside = [p for p in outside if rows[p]["roles"] & set(OUTSIDE_ROLES)]
    linked = _linking_back(cur, set(rows))
    seen = set(rows)
    for p, (at, src) in sorted(linked.items(), key=lambda kv: (kv[1][0], kv[0])):
        if p not in seen and at is not None:
            rows[p] = {"at": at, "roles": {"links"}, "source": src, "url": None, "as": set(), "kind": None}
            outside.append(p)
    outside.sort(key=lambda p: (rows[p]["at"], p))
    if outside:
        # the first outside post about it or linking back to its posts; a post that only names it is counted in its
        # month, never marked first. Never before its birth (an archive's date), never a background page
        born = rows[first]["at"]
        firsts = [p for p in outside if rows[p]["roles"] & (set(ABOUT) | {"links"}) and p not in bg
                  and rows[p]["at"] >= born]
        p0 = _first_about(cur, book, members, rows, firsts)   # its main subject, never a post about another
        if p0 is not None:
            out.append(_event("first_outside", rows[p0]["at"], p0, linked="links" in rows[p0]["roles"]))
        months: Dict[str, List[str]] = defaultdict(list)
        for p in outside:
            if p not in (p0, first):            # the birth is its own line
                months[rows[p]["at"].astimezone(timezone.utc).strftime("%Y-%m")].append(p)
        for month, ps in sorted(months.items()):
            lead = next((p for p in ps if rows[p]["roles"] & about_roles), None)
            out.append(_event("outside", rows[lead or ps[0]]["at"], lead or ps[0], month=month, n=len(ps),
                              sources=voice.count((voice.Said(rows[p]["source"]) for p in ps), voice.Policy.MARKX),
                              **({} if lead else {"named_only": True, "rank": RANK["in_story"]})))
    if light:
        return _dedupe(out)
    stops = _stories(cur, book, root, stories or [], rows)
    out += stops
    out += _analysis(cur, rows, outside) if ST.config()["analysis"] else []   # off, under its bar
    out = _dedupe(out)
    _hang(out, stops)
    out += _back(cur, set(rows))
    return out


def _stories(cur: Any, book: I.Book, root: str, stories: List[Dict[str, Any]],
             rows: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The page's stories as `story` (a stop) or `in_story` events: the stored stop answer decides, else the thing's
    share of the members (stops.candidate) with the story type's stop. A story given without its members is a stop
    (the caller knows no better)."""
    dated = [s for s in stories if s.get("first_at")]
    members = {s["story"]: [str(p) for p in s.get("members") or []] for s in dated}
    at: Dict[str, datetime] = {p: r["at"] for p, r in rows.items()}
    ids = sorted({p for ps in members.values() for p in ps} - set(at))
    if ids:
        cur.execute(f"SELECT p.id::text, {pairing.post_date('p')} FROM posts p WHERE p.id = ANY(%s::uuid[])", (ids,))
        at.update({p: a for p, a in cur.fetchall() if a is not None})
    about_posts = {p for ps in members.values() for p in ps if p in rows and rows[p]["roles"] & set(ABOUT)}
    got = stops_of(cur, book, root, members, at, about_posts)
    out = []
    for s in dated:
        ps = members[s["story"]]
        about, stop, by, sh = got[s["story"]]
        out.append(_event("story" if about else "in_story", s["first_at"], None, story=s["story"], mark=s["mark"],
                          headline=s.get("headline"), voices=s.get("voices"), stop=stop, stop_by=by,
                          share=[sh.about, sh.members], members=ps))
    return out


def stops_of(cur: Any, book: I.Book, root: str, members: Dict[str, List[str]], at: Dict[str, datetime],
             about_posts: Set[str]) -> Dict[str, Tuple[bool, Optional[str], str, Any]]:
    """{story: (about the thing, its stop, "asked" or "type", its stops.Share)} of the stories (`members`: their posts;
    `at`: the posts' dates; `about_posts`: the posts whose subject or actor the thing is): the stored stop answer
    decides, else the thing's share of the members (stops.candidate); a story without members is about it. The
    timeline's stops and in_story, and the entity page's story order."""
    from insight_core.markx import event_types, stops as ST
    on = ST.config()
    answers = ST.of(cur, book, root, list(members))
    types = event_types.of_stories(cur, {s: ps for s, ps in members.items() if s not in answers and ps}) \
        if on["stop_types"] else {}
    out = {}
    for sid, ps in members.items():
        sh = ST.share([(at[p], p) for p in ps if p in at], [p for p in ps if p in about_posts])
        got = answers.get(sid)
        if got is not None:
            about, stop, by = got.about, got.stop, "asked"
        else:
            about, stop, by = (ST.candidate(sh) if ps else True), ST.coarse(types.get(sid)), "type"
        about = about or not on["stops"]                  # the split off: every story a stop
        stop = stop if on["stop_types"] else None         # the word off: kept in the answers, not shown
        out[sid] = (about, stop, by, sh)
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
    """{post: (at, source)}: the posts with a current post edge back to one of `posts` (the newer links or refers back
    to the older)."""
    if not posts:
        return {}
    cur.execute(f"""SELECT DISTINCT x.a::text, {pairing.post_date('p')}, p.source_id::text
                     FROM mx_connections x JOIN posts p ON p.id = x.a
                    WHERE x.valid_to IS NULL AND x.a_kind = 'post' AND x.b_kind = 'post'
                      AND x.b = ANY(%s::uuid[]) AND NOT x.a = ANY(%s::uuid[])""", (sorted(posts), sorted(posts)))
    return {pid: (at, src) for pid, at, src in cur.fetchall()}


def _back(cur: Any, posts: Set[str]) -> List[Dict[str, Any]]:
    """The back-in-the-news rows judged development whose old story holds one of `posts`, at their window."""
    from insight_core.markx import back
    if not posts:
        return []
    from insight_core.markx import anchors   # the engine shown's rows
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
              top: int = TOP, original_post: Any = ...) -> Optional[Dict[str, Any]]:
    """The entity page's Timeline: {items (oldest first, each with `top`), shown (how many are top), total, earlier
    (its earlier names)}; None when it has fewer than MIN_EVENTS dated events."""
    from insight_core.markx import rename
    evs = events(cur, book, root, stories=stories, original_post=original_post)
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
    entities, not an org or person), up to `limit` previous events (the birth, the last release before it, the first
    outside mention before it) and its last STOPS_BEFORE stops before it, oldest first: [{entity: {id, name}, items}].
    `skip`: posts already listed."""
    from insight_core.markx import schemas
    cur.execute(f"""SELECT m.guide, m.n, m.entity_id::text, {pairing.post_date('p')}
                     FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id
                    WHERE m.post_id = %s AND m.guide = ANY(%s) AND m.role = 'subject' AND m.entity_id IS NOT NULL
                    ORDER BY m.n""", (post_id, schemas.mention_guides()))
    rows = cur.fetchall()
    if not rows:
        return []                                   # no subject linked: the book is not read
    book = book or I.lazy_book(cur)   # what the post's subjects ask of the book
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
    """The thing's stops before a post (its stored stop answers saying about; the stories the post is in left out), the
    newest `limit`, as `story` events at their first member's date. Nothing is asked here."""
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


# ---- the version line ----------------------------------------------------------------------------------------------
# A family's versions on lines ("Orbit 2 -> Orbit 2.5 -> Orbit 3"; a product line each: "Orbit Coder 2 -> 3"), the
# order graph.next_version_edges joins posts by. The classes it handles (0220, 0234):
#   - lines told apart by a letter (R1 / V3): the letter is the line (`line_key`); a number written without its letter
#     joins the only lettered line that has it, unless the unlettered numbers are a line of their own;
#   - product lines inside a family (Max / Plus / Coder, or tiers Opus / Sonnet / Haiku): the version's line word
#     (`line_word`: its variant without a stage word) is a line of its own; a line word only one number has, that the
#     plain line also has, is that number's code name ("Orbit 10.12 Sierra" is 10.12), not a line;
#   - another maker's thing filed under the family's name: its stated maker;
#   - a rumoured version: a stop is real only when its maker announced it (never a leak) or, when the maker never
#     speaks for itself here, RELEASE_VOICES independent voices report its release. Once the maker speaks here, a
#     version it never announced is no stop, unless it is older than the maker's first post here;
#   - a stop's date: the maker's first announcement, else its first release report (never a sighting);
#   - year-named versions (95, 98 after 10): a line is ordered by its stops' release dates;
#   - a series or a phrase read as a version ("Orbit 40 Series", "Orbit 4 in Copilot"): `name_shape`;
#   - a build or date number in a family numbered 1, 2, 3: BUILD_FROM (a year, 1980-2039, is a name); a dot left out
#     (46 for 4.6) is the dotted version's stop;
#   - a one-letter family ("X-33" under "x"): no line.
LINE_ABOUT = 1        # posts whose subject or actor it is, at least
LINE_POSTS = 4        # posts naming a name before it may date its stop (a stray name filed under the number never)
RELEASE_VOICES = 2    # independent voices reporting its release, when its maker never speaks here
BUILD_FROM = 100      # a first number this big is a build or a date when the family's other numbers are small
YEARS = (1980, 2039)  # a four-digit first number in this range is a year-name (Windows 2000), never a build
RELEASE_TYPES = ("model_release", "product_release")   # the release-typed readings (schemas.EVENT_TYPES)
LEAK_TYPE = "leak_rumour"
# words that make a variant a stage of one version, not a product line (each generic: a release stage or a tuning)
STAGE_WORDS = frozenset({"preview", "exp", "experimental", "thinking", "instruct", "chat", "base", "beta", "alpha",
                         "latest", "it", "rc", "release", "stable", "early", "access", "update", "new"})
SERIES_WORDS = frozenset({"series", "serie", "family", "lineup", "generation", "gen", "models", "lineups"})
PHRASE_WORDS = frozenset({"in", "for", "on", "with", "vs", "versus", "and", "or", "via", "at", "to", "of", "by", "from",
                          "&", "+", "x"})


@dataclass(frozen=True)
class Version:
    id: str
    name: str
    key: Optional[Tuple[Any, ...]]   # its version tuple (names.vt: "K3.1" -> ('k', 3, 1); a leading v dropped)
    maker: Optional[str]
    posts: int
    about: int                       # posts whose subject or actor it is
    first: Optional[datetime]
    first_post: Optional[str]
    variant: Optional[str] = None
    maker_first: Optional[datetime] = None   # its maker's first post about it (origin maker, never a leak)
    maker_post: Optional[str] = None
    release_first: Optional[datetime] = None  # its first release report about it (release-typed, never a leak)
    release_post: Optional[str] = None
    voices: FrozenSet[str] = frozenset()      # the sources reporting its release (one voice each)


@dataclass
class LineStop:
    key: Tuple[str, Tuple[int, ...]]
    versions: List[Version]          # the most named first
    first: Optional[datetime] = None          # its release date (the maker's first post, else its first report)
    first_post: Optional[str] = None
    posts: int = 0
    about: int = 0
    word: str = ""                            # its product line's word ("" the plain line)
    by: Optional[str] = None                  # what dates it: "maker" or "voices"
    voices: int = 0


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


def line_word(variant: Optional[str]) -> str:
    """A version's product line from its variant (pure): its words without the stage words ("Pro Preview" -> "pro",
    "Instruct" -> ""); "" for the plain line."""
    words = [w for w in N.key(variant).split() if w not in STAGE_WORDS]
    return " ".join(words)


def name_shape(name: Optional[str], variant: Optional[str]) -> str:
    """'version', 'series' (a product generation: "Orbit 40 Series") or 'phrase' (a feature, a comparison, a version
    named with something else: "Orbit 4 in Copilot", "Orbit 4 vs Lumen 2") (pure)."""
    words = set(N.key(name).split()) | set(N.key(variant).split())
    if words & SERIES_WORDS:
        return "series"
    vw = N.key(variant).split()
    if set(vw) & PHRASE_WORDS or len([w for w in vw if w not in STAGE_WORDS]) > 2:
        return "phrase"
    return "version"


def _lettered(k: Optional[Tuple[str, Tuple[int, ...]]], name: Optional[str]) -> Optional[Tuple[str, Tuple[int, ...]]]:
    """A version whose fields lost its letter ("Kite K2.6" read as version 2.6) takes the letter its name writes right
    before the number (never `v`: "V3" is 3, as names.vt reads it)."""
    if k is None or k[0]:
        return k
    num = r"\.".join(map(str, k[1]))
    m = re.search(rf"(?<![a-z0-9])([a-uw-z])[ -]?{num}(?![0-9]|\.[0-9])", unicodedata.normalize("NFKC", name or "").casefold())
    return (m.group(1), k[1]) if m else k


def _stop(key: Tuple[str, Tuple[int, ...]], vs: List[Version], word: str = "") -> LineStop:
    vs = sorted(vs, key=lambda v: (line_word(v.variant) != word, -v.posts, -v.about, line_key(v.key) != key, v.name, v.id))
    # its date: the maker's first post about it, else its first release report; a stray name (fewer than LINE_POSTS
    # posts, not the stop's own name) never dates it (often another thing)
    own = [v for n, v in enumerate(vs) if n == 0 or v.posts >= LINE_POSTS]
    maker = sorted((v.maker_first, v.maker_post or "") for v in own if v.maker_first is not None)
    report = sorted((v.release_first, v.release_post or "") for v in own if v.release_first is not None)
    voices = len(frozenset().union(*(v.voices for v in own)))
    if maker:
        first, post, by = maker[0][0], maker[0][1] or None, "maker"
    elif report:
        first, post, by = report[0][0], report[0][1] or None, "voices"
    else:
        first, post, by = None, None, None
    return LineStop(key, vs, first, post, sum(v.posts for v in vs), sum(v.about for v in vs), word, by, voices)


def _maker_since(stops: Iterable[LineStop]) -> Optional[datetime]:
    """The maker's first post about any of the family's versions (None: it never speaks for itself here)."""
    got = [s.first for s in stops if s.by == "maker" and s.first is not None]
    return min(got) if got else None


def _released(s: LineStop, maker_since: Optional[datetime]) -> bool:
    """A real, released stop: about it at least LINE_ABOUT posts, and its maker announced it; or the maker does not
    speak here (or not yet when it came: its first report is older than the maker's first post here) and
    RELEASE_VOICES voices report its release."""
    if s.about < LINE_ABOUT or s.first is None:
        return False
    if s.by == "maker":
        return True
    if maker_since is not None and s.first >= maker_since:
        return False
    return s.voices >= RELEASE_VOICES


def _line_maker(vs: List[Version], same_maker: Any) -> Optional[str]:
    """The maker most of the family's posts state for its versions (a family's own maker field is its first run's
    majority, and can be wrong)."""
    best, score = None, 0
    for m in sorted({v.maker for v in vs if v.maker}):
        n = sum(v.posts for v in vs if v.maker and same_maker(v.maker, m))
        if n > score:
            best, score = m, n
    return best


def _build(k: Tuple[str, Tuple[int, ...]]) -> bool:
    return k[1][0] >= BUILD_FROM and not (len(k[1]) == 1 and YEARS[0] <= k[1][0] <= YEARS[1])


def version_lines(versions: Iterable[Version], *, family_name: Optional[str], family_maker: Optional[str],
                  same_maker: Any) -> List[List[LineStop]]:
    """A family's lines (pure): each its released stops in release order (ties by number), the longest line first; a
    line of one stop is no line. A version whose stated maker is not the one most of its family's posts state (else
    `family_maker`) is off; a series or a phrase is no version. `same_maker(a, b)`: two stated makers name one maker."""
    if len(N.squash(N.key(family_name))) < 2:
        return []
    keyed = [(_lettered(line_key(v.key), v.name), v) for v in versions if name_shape(v.name, v.variant) == "version"]
    keyed = [(k, v) for k, v in keyed if k is not None]
    maker = _line_maker([v for _, v in keyed], same_maker) or family_maker
    cand = [(k, v) for k, v in keyed if not (maker and v.maker and not same_maker(v.maker, maker))]
    if any(not _build(k) for k, _ in cand):
        cand = [(k, v) for k, v in cand if not _build(k)]
    groups: Dict[Tuple[str, str, Tuple[int, ...]], List[Version]] = defaultdict(list)
    for k, v in cand:
        groups[(line_word(v.variant), k[0], k[1])].append(v)
    # a line word one number ever has, that the plain line has too: that number's code name, not a line of its own
    words = defaultdict(set)
    for w, p, num in groups:
        words[(w, p)].add(num)
    for (w, p), nums in sorted(words.items()):
        if w and len(nums) == 1 and ("", p, next(iter(nums))) in groups:
            groups[("", p, next(iter(nums)))] += groups.pop((w, p, next(iter(nums))))
    # a dot left out: a number whose digits are another stop's of the same line run together is that stop, when that
    # stop is the better named (the slip is the rarer spelling: "Orbit 46" for 4.6, never "Orbit 11" into a 1.1)
    for g in sorted(groups):
        if g in groups and len(g[2]) == 1 and g[2][0] >= 10:
            hit = [o for o in groups if o[:2] == g[:2] and len(o[2]) > 1 and "".join(map(str, o[2])) == str(g[2][0])]
            if len(hit) == 1 and sum(v.posts for v in groups[hit[0]]) > sum(v.posts for v in groups[g]):
                groups[hit[0]] += groups.pop(g)
    # a number written without its letter: the only lettered line (of its word) that has it, unless the unlettered
    # numbers with no lettered twin are a line of their own (two stops or more)
    for w in sorted({g[0] for g in groups}):
        letters = {g[1] for g in groups if g[0] == w and g[1]}
        twin = {g: [p for p in sorted(letters) if (w, p, g[2]) in groups] for g in groups if g[0] == w and g[1] == ""}
        own = [g for g, ps in twin.items() if len(ps) != 1 and _stop((g[1], g[2]), groups[g], w).about >= LINE_ABOUT]
        if len(own) < 2:
            for g, ps in twin.items():
                if len(ps) == 1:
                    groups[(w, ps[0], g[2])] += groups.pop(g)
    stops = {g: _stop((g[1], g[2]), vs, g[0]) for g, vs in groups.items()}
    since = _maker_since(stops.values())
    lines: Dict[Tuple[str, str], List[LineStop]] = defaultdict(list)
    for g in sorted(stops):
        if _released(stops[g], since):
            lines[g[:2]].append(stops[g])
    out = [sorted(ln, key=lambda s: (s.first, s.key[1])) for ln in lines.values() if len(ln) >= 2]
    return sorted(out, key=lambda ln: (-len(ln), ln[0].word, ln[0].key[0]))


def maker_word(m: Optional[str]) -> str:
    """A stated maker as one word: its key, a corporate word at its end dropped ("Zentra AI" -> "zentra")."""
    words = N.key(m).split()
    while len(words) > 1 and words[-1] in I.CORP_WORDS:
        words = words[:-1]
    return N.squash(" ".join(words))


def same_maker(a: Optional[str], b: Optional[str]) -> bool:
    return bool(maker_word(a)) and maker_word(a) == maker_word(b)


Counts = Tuple[int, int, Optional[datetime], Optional[str], Optional[datetime], Optional[str], Optional[datetime],
               Optional[str], FrozenSet[str]]


def version_counts(cur: Any, members: Dict[str, Iterable[str]]) -> Dict[str, Counts]:
    """{version root: (posts naming it, posts about it (subject or actor), its first post about it, that post, its
    maker's first post about it (the post's reading says its origin is the maker; never a leak), that post, its first
    release report about it (a release-typed reading, never a leak), that post, the sources reporting its release)}
    over its cluster's ids (`members`), counted by the database (one row an id; nothing per post comes back). The
    reading of a post is the one event_types reads first (its type guides)."""
    from insight_core.markx import event_types, schemas
    of = {m: r for r, ms in members.items() for m in ms}
    if not of:
        return {}
    at = pairing.post_date('p')
    about = "m.role IN ('subject', 'actor')"
    maker = f"{about} AND rd.origin = 'maker' AND rd.typ IS DISTINCT FROM '{LEAK_TYPE}'"
    release = f"{about} AND rd.typ = ANY(%(rel)s) AND s.platform IS DISTINCT FROM 'saved'"
    cur.execute(f"""SELECT m.entity_id::text, count(DISTINCT m.post_id), count(DISTINCT m.post_id) FILTER (WHERE {about}),
                           (array_agg(m.post_id::text ORDER BY {at}, m.post_id) FILTER (WHERE {about} AND {at} IS NOT NULL))[1],
                           min({at}) FILTER (WHERE {about}),
                           (array_agg(m.post_id::text ORDER BY {at}, m.post_id) FILTER (WHERE {maker} AND {at} IS NOT NULL))[1],
                           min({at}) FILTER (WHERE {maker}),
                           (array_agg(m.post_id::text ORDER BY {at}, m.post_id) FILTER (WHERE {release} AND {at} IS NOT NULL))[1],
                           min({at}) FILTER (WHERE {release}),
                           array_agg(DISTINCT p.source_id::text) FILTER (WHERE {release})
                      FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id LEFT JOIN sources s ON s.id = p.source_id
                      LEFT JOIN LATERAL (SELECT r.reading->>'event_type' AS typ, r.reading->>'origin' AS origin
                                           FROM mx_readings r WHERE r.post_id = m.post_id AND r.guide = ANY(%(tg)s)
                                          ORDER BY array_position(%(tg)s, r.guide) LIMIT 1) rd ON m.role IN ('subject', 'actor')
                     WHERE m.guide = ANY(%(g)s) AND m.entity_id = ANY(%(ids)s::uuid[]) GROUP BY m.entity_id""",
                {"g": schemas.mention_guides(), "ids": sorted(of), "tg": event_types.type_guides(cur),
                 "rel": list(RELEASE_TYPES)})
    out: Dict[str, List[Any]] = {}
    for eid, n, ab, post, first, mpost, mfirst, rpost, rfirst, srcs in cur.fetchall():
        r = out.setdefault(of[eid], [0, 0, None, None, None, None, None, None, frozenset()])
        r[0] += n
        r[1] += ab
        for i, (when, pid) in ((2, (first, post)), (4, (mfirst, mpost)), (6, (rfirst, rpost))):
            if when is not None and (r[i] is None or when < r[i]):
                r[i], r[i + 1] = when, pid
        r[8] = r[8] | frozenset(srcs or ())
    return {r: tuple(x) for r, x in out.items()}


def line_versions(rows: Iterable[Tuple[Any, ...]], counts: Dict[str, Counts]) -> List[Version]:
    """Versions from (root, name, version tuple, stated maker[, variant]) rows and their `version_counts`."""
    out = []
    for row in rows:
        r, name, key, maker = row[:4]
        c = tuple(counts.get(r) or ()) + (0, 0, None, None, None, None, None, None, frozenset())[len(counts.get(r) or ()):]
        out.append(Version(r, name, tuple(key) if key else None, maker, c[0], c[1], c[2], c[3],
                           variant=row[4] if len(row) > 4 else None, maker_first=c[4], maker_post=c[5],
                           release_first=c[6], release_post=c[7], voices=frozenset(c[8])))
    return out


def version_line(cur: Any, book: I.Book, root: str) -> Optional[Dict[str, Any]]:
    """The entity page's version line: the lines of its family (the entity's own family, or itself when it is one), the
    one holding this entity first. {family {id, name}, lines: [[{id, name, version, first, by, posts, current}]], words:
    [each line's product line word, "" the plain line], grid} (each stop by the name most posts use; the other names
    filed under its number are not shown: often another thing); `grid`: when two product lines or more share two numbers
    or more, {tiers, rows: [{generation, cells: {tier: stop id}}]} in release order. None when the family has no
    line."""
    e = book.ents[root]
    fam = root if e.level in ("family", "thing") else (book.root(e.parent) if e.parent and e.level in I.VERSION_LEVELS else None)
    if not fam or fam not in book.ents:
        return None
    kids = sorted({book.root(x) for x in book.with_parent_in(fam)})
    rows = [(k, book.label(k), book.ents[k].version_key, book.ents[k].maker, book.ents[k].variant) for k in kids
            if k in book.ents and book.ents[k].level == "version" and book.ents[k].status != "not_entity"
            and not (book.ents[k].size or book.ents[k].build)]
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
                        "first": s.first, "by": s.by, "posts": s.posts,
                        "current": any(v.id == mine for v in s.versions)} for s in ln] for ln in lines],
            "words": [ln[0].word for ln in lines], "grid": grid(lines)}


def grid(lines: List[List[LineStop]]) -> Optional[Dict[str, Any]]:
    """Generation x tier (pure): the product lines (a word each) sharing two numbers or more, {tiers (the lines' words,
    the longest line first), rows: [{generation (its numbers dotted), cells {tier: the stop's first version id}}] in
    release order (a generation's first stop)}; None when fewer than two lines share two numbers."""
    tiers = [ln for ln in lines if ln[0].word]
    nums: Dict[Tuple[int, ...], Dict[str, LineStop]] = defaultdict(dict)
    for ln in tiers:
        for s in ln:
            nums[s.key[1]].setdefault(ln[0].word, s)
    shared = {k: v for k, v in nums.items() if len(v) >= 2}
    if len(shared) < 2:
        return None
    words = [ln[0].word for ln in tiers if any(ln[0].word in v for v in shared.values())]
    order = sorted(nums, key=lambda k: (min(s.first for s in nums[k].values()), k))
    return {"tiers": words, "rows": [{"generation": ".".join(map(str, k)),
                                      "cells": {w: s.versions[0].id for w, s in nums[k].items() if w in words}}
                                     for k in order if set(nums[k]) & set(words)]}


__all__ = ["LineStop", "Version", "before_post", "events", "grid", "line_key", "line_word", "name_shape", "of_entity",
           "same_maker", "version_counts", "version_line", "version_lines"]
