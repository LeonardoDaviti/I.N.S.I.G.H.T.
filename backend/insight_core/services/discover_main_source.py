"""Discover's "main source missing" (issue 0170, INSIGHT v10.15 D): the events your sources covered whose actor's own
channel you don't hold, and the channel to follow.

Measured (plan/research/exp-2026-11-12/e5e7, E5): of company and person events with 2+ posts, 53-65% hold no post
from the actor's own channel; the event's own links point to the actor's main post in 59 of 76; following the
channel the finder or page watching found would have held it in ~47% (up to 68%).

**Which events.** A current Mark X story of 2+ voices (its members' sources) in the last WITHIN_DAYS whose story type
(markx/built.event_type over read-v3) is one an actor announces itself (ANNOUNCED): never a lawsuit, a regulator's
action or a filing (`policy_legal`), a scoop or a leak (`leak_rumour`), nor commentary, digests or tutorials, which
have no own announcement. A story with no read-v3 reading has no type and is never flagged. Its **actor** is the
story's maker by identity (perspectives.Story.maker), else the org or person half its members or more name as subject
or actor (read through the merges, entities not marked not_entity); and the readings must name it as the event's
(`named_actor`): the first of a reading's main actors once or more, among them in half the readings or more (a
reporter cited beside the actors, "..., an outlet reports", or an outlet the members only talk about, is not).

**Its own page.** A page the members carry that is the actor's: its owner (`owner`: an X account, a site's
registrable name, <name>.github.io's <name>) is one of the actor's names or the name of a thing the actor makes
(`owned_by`: <product>.ai, @<product>ai), or it is an address of the actor or of a thing it makes (0138's
mx_entity_addresses, release and work pages). A page counts as the event's own post when it is a member's own address
(held by an aggregator or a repost), 2+ members link it, it is a short link post's main link, it is the story's
source page (built's: the page members link when none of them is the original), or it is a post on X. Code hosts,
model hubs and platforms are nobody's channel, and neither are Discover's places that are no source (references and
docs, papers, records, apps, files) nor product, pricing and legal pages; a home page says who, not what.

**Its channel.** An X post: the account (x.com/<user>). A Telegram post: the channel. A site's page: its SECTION, the
first path segment of a page two or more deep (/blog/, /news/, /newsroom/; with a language segment before it,
/en/blog/), else the site's root; the finder starts there, never at the home page. One channel an event: its best
evidenced own page's (held, then the most linked, then a main link, then the source page).

**The verdicts.** The story holds a post of the actor's (its source's name names the actor, or the source is the
channel's account or a site source on the channel's site): nothing. Else, for each of its channels:
  - no source on it: `missing`, follow the channel;
  - an enabled source on it covers the page (an account; a page watch whose prefix the page is under; a feed that
    holds posts in the page's section, or holds nothing yet): nothing for the whole event, its source is followed (a
    page stored under an aggregator, or published before the follow, is ingestion's to fix);
  - only a disabled source covers it: `disabled`, surfaced;
  - enabled sources on the site, none covering it: `wrong_section`, a second section for the same site.
A disabled source whose name is the actor's (r/<actor>, "<Actor> blog") is surfaced as `disabled` too.

Measured before it was adopted (2026-11-12, a read-only run on the local census copy of Oct 5 - Nov 5, which has no
read-v3: every type let through): 141 stories of 2+ voices, 18 events flagged in 17 rows, 16 plausible by E5's rows
(a reporter as the actor, 1; a model card section, 1); the type gate removes the rest on the server.

**The test.** On opening Discover, at most TESTS_PER_RUN channels shown without a test in CHECK_DAYS are tested in the
background, as Discover's follow test (services/discover_reads.py): an account through its source kind; a section
through the feed finder on the section (where_linked.follow, the event's own pages as the linked articles: `holds`
says how many of them a feed or page keeps), then, when it found neither a feed nor a page to watch, page watching's
preview of the section with its prefix. Stored in system_settings `discover_main_source` with its date. Off with
INSIGHT_DISCOVER_READS=0. Nothing is ever added here: Follow opens Add source on the channel (the feed finder, then page
watching), as every add.

Reads Mark X's tables, never writes them; the list is made per open (cached CACHE_SECONDS while nothing changed).
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
import time
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.utils.addresses import PLATFORM_SITES, host_of, is_tweet, publication_of, site_of, tweet_author
from insight_core.utils.discover_rules import CHECK_DAYS, PLACE_TESTS
from insight_core.utils.entity_originals import CODE_SITES, MODEL_HUBS, RELEASE, WORK
from insight_core.utils.post_links import LANGUAGE, LEGAL, NUMBERISH, REFERENCE, source_kind
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger(__name__)

KEY = "discover_main_source"      # system_settings: {"tests": {channel key: {label, at, ...}}}
HIDE_PREFIX = "main:"             # a row's key in discover_hidden (Not interested), apart from Discover's own keys
WITHIN_DAYS = 30
MIN_VOICES = 2
ANNOUNCED = frozenset({"model_release", "product_release", "research_result", "business_event", "incident",
                       "public_statement", "promotion_event"})
ACTOR_TYPES = ("org", "person")
ACTOR_ROLES = ("subject", "actor")
ADDRESS_KINDS = (RELEASE, WORK)
SHOWN = 20                        # rows returned
POSTS_SHOWN = 5                   # an event's posts shown
TESTS_PER_RUN = 8
CACHE_SECONDS = 600
KINDS = ("missing", "wrong_section", "disabled")
# Hosts whose pages are a platform's, not an owner's (perspectives.PLATFORMS's, X and Telegram aside: their posts are
# an account's), and the paper, code and model hosts: nobody's channel.
_PLATFORM_SITES = frozenset().union(*PLATFORM_SITES.values()) | {"medium.com", "substack.com", "arxiv.org",
                                                                   "piped.video", "linkedin.com"}
_TELEGRAM_POST = re.compile(r"^[A-Za-z0-9_]{4,}$")


# ---- channels (pure) ----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Channel:
    key: str                  # x.com/<user>, t.me/<channel>, or <publication><prefix> (example.com/blog/)
    kind: str                 # account | site
    platform: str             # x | telegram | site
    url: str                  # what Follow opens Add source on: the account, or the section's page
    prefix: Optional[str] = None      # a site's section ("/blog/", "/" for the site's root)
    site: str = ""


def _full(url: str) -> Optional[str]:
    return normalize_url(url if "://" in url else "https://" + url)


def _path(url: str) -> str:
    return urllib.parse.urlparse(url).path.rstrip("/") + "/"


def segments(url: str) -> List[str]:
    return [s for s in urllib.parse.urlparse(url).path.split("/") if s]


def section_of(url: str) -> str:
    """A page's section prefix: "/<first segment>/" of a page two or more segments deep whose first segment is no date
    or number (/blog/<slug>, /newsroom/2026/10/<slug>), a language's with it (/en/blog/), else "/" (a page at the
    site's root, a site by date)."""
    segs = [s.lower() for s in segments(url)]
    lang = segs[:1] if segs and LANGUAGE.match(segs[0]) and len(segs) >= 3 else []
    rest = segs[len(lang):]
    if len(rest) >= 2 and not NUMBERISH.match(rest[0]):
        return "/" + "/".join([*lang, rest[0]]) + "/"
    return "/"


def channel_of(url: str) -> Optional[Channel]:
    """The channel a page of an actor's is published in, or None (a home page, a platform's page, a paper, code or a
    model hub)."""
    full = _full(url)
    if not full:
        return None
    if is_tweet(full):
        user = tweet_author(full)
        return Channel(f"x.com/{user.lower()}", "account", "x", f"https://x.com/{user}", site="x.com") if user else None
    host = host_of(full)
    site = site_of(host)
    segs = segments(full)
    if site in PLATFORM_SITES["telegram"] and site != "telegram.org":
        if len(segs) == 2 and segs[1].isdigit() and _TELEGRAM_POST.match(segs[0]):
            return Channel(f"t.me/{segs[0].lower()}", "account", "telegram", f"https://t.me/{segs[0]}", site="t.me")
        return None
    if (not segs or site in _PLATFORM_SITES or site in CODE_SITES or site in MODEL_HUBS or host.endswith(".hf.space")
            or any(test(full) for _, test in PLACE_TESTS) or REFERENCE.search(_path(full)) or LEGAL.search(_path(full))):
        return None   # no source (Discover's places: references, papers, records, apps, files; a product, pricing or legal page)
    prefix = section_of(full)
    pub = publication_of(host)
    parsed = urllib.parse.urlparse(full)
    page = f"{parsed.scheme}://{parsed.netloc}{prefix.rstrip('/')}" if prefix != "/" else f"{parsed.scheme}://{parsed.netloc}/"
    return Channel(pub + prefix, "site", "site", page, prefix, site)


# ---- sources (pure) -----------------------------------------------------------------------------------

@dataclass(frozen=True)
class Src:
    id: str
    name: str
    enabled: bool
    kind: str                         # post_links.source_kind: site, x, telegram, reddit, hn, saved, ...
    account: Optional[str] = None     # repo_stories.source_account
    host: str = ""                    # its address's host
    watch: Optional[str] = None       # a page watch's prefix (its listing page's path when unset); None: a feed
    sections: FrozenSet[Tuple[str, str]] = frozenset()   # (publication, section) of its stored posts


def page_section(url: str) -> Tuple[str, str]:
    full = _full(url) or url
    return publication_of(host_of(full)), section_of(full)


def on_channel(src: Src, ch: Channel) -> bool:
    """Whether a source is on the channel: its account, or a site source whose address is on the channel's site (a
    link blog's posts at other sites' addresses never make it theirs)."""
    if ch.kind == "account":
        return bool(src.account) and src.account == ch.key
    if src.kind != "site":                       # an aggregator (hn, saved) is never a site's channel
        return False
    return bool(src.host) and site_of(src.host) == ch.site


def covers(src: Src, ch: Channel, page: str) -> Optional[bool]:
    """Whether a source on the channel carries the page: an account always; a page watch when the page is under its
    prefix on its host; a feed when it holds posts in the page's section (None: it holds nothing yet, unknown)."""
    if ch.kind == "account":
        return True
    pub, section = page_section(page)
    if src.watch is not None:
        path = urllib.parse.urlparse(_full(page) or page).path
        if not path.endswith("/"):
            path += "/"
        return publication_of(src.host) == pub and path.startswith(src.watch)
    if not src.sections:
        return None
    return (pub, section) in src.sections


# ---- events (pure) ------------------------------------------------------------------------------------

@dataclass
class OwnPage:
    url: str                          # as a member carries it
    how: str                          # held | linked | main_link | source_page
    held_by: List[str] = field(default_factory=list)   # the members holding it as their own address


@dataclass
class Event:
    story: str
    headline: str
    event_type: str
    voices: int
    first_at: Optional[datetime]
    actor: str
    actor_name: str
    pages: List[OwnPage]
    member_sources: Set[str]
    actor_sources: Set[str]           # the sources whose name is the actor's
    posts: List[Dict[str, Any]]


def _verdict(ch: Channel, pages: Sequence[str], sources: Sequence[Src]) -> Tuple[Optional[str], Optional[Src]]:
    """(kind, the source it is about) of one channel of an event, or (None, None) when its source is followed."""
    on = [s for s in sources if on_channel(s, ch)]
    if not on:
        return "missing", None
    covering = [s for s in on if any(covers(s, ch, p) is not False for p in pages)]
    if any(s.enabled for s in covering):
        return None, None
    if covering:
        return "disabled", covering[0]
    enabled = [s for s in on if s.enabled]
    if enabled:
        return "wrong_section", enabled[0]
    return "missing", None


def judge(events: Sequence[Event], sources: Dict[str, Src]) -> List[Dict[str, Any]]:
    """The rows: one per (kind, channel), each with its events, the most events first, then the latest. Pure."""
    groups: Dict[Tuple[str, str], Dict[str, Any]] = {}
    srcs = list(sources.values())

    def add(kind: str, ch: Channel, src: Optional[Src], ev: Event, own: Optional[OwnPage]) -> None:
        g = groups.setdefault((kind, ch.key), {
            "key": HIDE_PREFIX + ch.key, "kind": kind,
            "channel": {"key": ch.key, "kind": ch.kind, "platform": ch.platform, "url": ch.url, "prefix": ch.prefix},
            "source": None, "actors": Counter(), "events": []})
        if src is not None and g["source"] is None:
            g["source"] = {"id": src.id, "name": src.name, "enabled": src.enabled, "watch": src.watch}
        g["actors"][(ev.actor, ev.actor_name)] += 1
        if any(e["story"] == ev.story for e in g["events"]):
            return
        g["events"].append({"story": ev.story, "headline": ev.headline, "event_type": ev.event_type,
                            "voices": ev.voices, "first_at": ev.first_at.isoformat() if ev.first_at else None,
                            "own_page": ({"url": own.url, "how": own.how, "held_by": own.held_by} if own else None),
                            "posts": ev.posts})

    for ev in events:
        if ev.member_sources & ev.actor_sources:
            continue                                         # the actor's own post is in the story
        members = [sources[s] for s in ev.member_sources if s in sources]
        channels: Dict[str, Tuple[Channel, List[OwnPage]]] = {}
        for own in ev.pages:
            ch = channel_of(own.url)
            if ch is not None:
                channels.setdefault(ch.key, (ch, []))[1].append(own)
        if any(on_channel(m, ch) for m in members for ch, _ in channels.values()):
            continue                                         # a member is from the actor's channel
        verdicts = [(ch, owns, *_verdict(ch, [o.url for o in owns], srcs)) for ch, owns in channels.values()]
        if any(kind is None for _, _, kind, _ in verdicts):
            continue                                         # its source is followed
        if verdicts:                                         # the main post's channel: the best evidenced
            ch, owns, kind, src = verdicts[0]
            add(kind, ch, src, ev, owns[0])
        for sid in sorted(ev.actor_sources):                 # a disabled source of the actor's own
            src = sources.get(sid)
            if src is None or src.enabled or any(s is not None and s.id == sid for _, _, _, s in verdicts):
                continue
            ch = Channel(f"source:{src.id}", "source", src.kind, "", None, "")
            add("disabled", ch, src, ev, ev.pages[0] if ev.pages else None)
    rows = []
    for g in groups.values():
        (actor, name), _ = g.pop("actors").most_common(1)[0]
        g["actor"] = {"id": actor, "name": name}
        g["events"].sort(key=lambda e: e["first_at"] or "", reverse=True)
        g["latest"] = g["events"][0]["first_at"] if g["events"] else None
        rows.append(g)
    rows.sort(key=lambda g: g["key"])
    rows.sort(key=lambda g: g["latest"] or "", reverse=True)      # stable: the latest first within a count
    rows.sort(key=lambda g: -len(g["events"]))
    return rows


def due(test: Optional[Dict[str, Any]], now: datetime) -> bool:
    try:
        return test is None or now - datetime.fromisoformat(test["at"]) >= timedelta(days=CHECK_DAYS)
    except (KeyError, TypeError, ValueError):
        return True


# ---- from the database (reads only) -------------------------------------------------------------------

def _sources(cur: Any) -> Dict[str, Src]:
    from insight_core.db.repo_stories import source_account
    from insight_core.ingestion.kinds.page_watch import normalise_prefix
    cur.execute("""SELECT id::text, platform, handle_or_url, enabled,
                          COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url),
                          settings ? 'page_watch', settings->'page_watch'->>'prefix'
                     FROM sources""")
    out = {}
    for sid, platform, handle, enabled, name, watched, prefix in cur.fetchall():
        kind = source_kind(platform, handle)
        watch = None
        if watched and kind == "site":
            path = urllib.parse.urlparse(handle if "://" in handle else "https://" + handle).path
            watch = normalise_prefix(prefix) if prefix else normalise_prefix(path)
        out[sid] = Src(sid, name, bool(enabled), kind, source_account(platform, handle), host_of(_full(handle) or ""),
                       watch)
    return out


def _with_sections(cur: Any, sources: Dict[str, Src], sites: Set[str]) -> Dict[str, Src]:
    """The site sources on these sites, with their stored posts' (publication, section) on the source's own site."""
    ids = [s.id for s in sources.values() if s.kind == "site" and site_of(s.host) in sites]
    if not ids:
        return sources
    cur.execute("SELECT DISTINCT source_id::text, url FROM posts WHERE source_id = ANY(%s::uuid[])", (ids,))
    got: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)
    for sid, url in cur.fetchall():
        sec = page_section(url) if url else None
        if sec and site_of(sec[0]) == site_of(sources[sid].host):
            got[sid].add(sec)
    out = dict(sources)
    for sid, secs in got.items():
        s = out[sid]
        out[sid] = Src(s.id, s.name, s.enabled, s.kind, s.account, s.host, s.watch, frozenset(secs))
    return out


def _stories(cur: Any, since: datetime) -> Dict[str, Dict[str, Any]]:
    from insight_core.markx import built, folds
    cur.execute(f"""SELECT sp.story_id::text, sp.post_id::text, p.source_id::text, {built.PUBLISHED}, s.headline,
                           s.first_at, r.reading->>'event_type', r.reading->>'origin'
                      FROM mx_story_posts sp JOIN mx_stories s ON s.id = sp.story_id AND s.merged_into IS NULL
                      JOIN posts p ON p.id = sp.post_id
                      LEFT JOIN mx_readings r ON r.post_id = sp.post_id AND r.guide = %s
                     WHERE sp.valid_to IS NULL AND sp.role = 'member' AND s.first_at >= %s""", (folds.GUIDE, since))
    out: Dict[str, Dict[str, Any]] = {}
    for sid, pid, src, at, headline, first_at, et, origin in cur.fetchall():
        s = out.setdefault(sid, {"headline": headline or "", "first_at": first_at, "posts": {}})
        if pid not in s["posts"] or et is not None:
            s["posts"][pid] = built.Post(id=pid, source=src, at=at, event_type=et, origin=origin)
    return out


def _actor(st: Any, book: Any) -> Optional[str]:
    """The story's maker by identity, else the org or person half its members or more name as subject or actor."""
    from insight_core.markx import schemas
    if st.maker:
        return st.maker
    c: Counter = Counter()
    for i in st.ids:
        roots = set()
        for m in st.mk.mentions.get(i, ()):
            if m.get("role") not in ACTOR_ROLES or schemas.entity_type(m.get("type")) not in ACTOR_TYPES:
                continue
            r = book.root(m.get("entity_id")) if m.get("entity_id") else None
            e = book.ents.get(r) if r else None
            if e is not None and e.status != "not_entity" and schemas.entity_type(e.type) in ACTOR_TYPES:
                roots.add(r)
        c.update(roots)
    if not c:
        return None
    ranked = c.most_common(2)
    (r, n) = ranked[0]
    if len(ranked) > 1 and ranked[1][1] == n:
        return None
    return r if n * 2 >= len(st.ids) else None


def owner(u: str) -> Optional[str]:
    """Who a page (perspectives.nurl's form) belongs to: perspectives.owner, but a site by its registrable name
    (site_of): a writer on a hosting platform (<name>.github.io) is <name>, a co.uk-like site its first label."""
    from insight_core.markx import perspectives as P
    host = u.split("/", 1)[0]
    site = site_of(host)
    if host in P.X_HOSTS or site in CODE_SITES or site in MODEL_HUBS or site in _PLATFORM_SITES:
        return P.owner(u)
    return site.split(".")[0] or None


def owned_by(mk: Any, o: Optional[str], actor: str) -> bool:
    """Whether an owner (a handle, a site's name) is the actor's: one of its names (Makers.is_maker), or the name of a
    thing the actor makes (<product>.ai, @<product>ai: the product's maker)."""
    from insight_core.markx import names as N
    if not o:
        return False
    if mk.is_maker(o, actor):
        return True
    for f in N.handle_forms(o):
        r = mk.of_name(f)
        if r and (r == actor or actor in mk.ancestors(r)):
            return True
    return False


def named_actor(actors: Sequence[Sequence[str]], is_actor: Callable[[str], bool]) -> bool:
    """Whether the readings name the actor as the event's: the first of its main actors in one reading or more, and
    among them in half the readings or more (`actors`: each read member's main.actors; a reporter cited beside the
    actors, or a subject the members only talk about, is not)."""
    named = [any(is_actor(x) for x in xs) for xs in actors]
    return any(xs and is_actor(xs[0]) for xs in actors) and sum(named) * 2 >= len(actors) > 0


def _own_pages(st: Any, actor: str, addresses: Set[str]) -> List[OwnPage]:
    """The event's own posts of the actor's, as its members carry them (the module's rule), held ones first."""
    from insight_core.markx import perspectives as P

    def own(u: str) -> bool:
        return u in addresses or owned_by(st.mk, owner(u), actor)

    raw: Dict[str, str] = {}
    held: Dict[str, List[str]] = defaultdict(list)
    linked: Dict[str, Set[str]] = defaultdict(set)
    main: Set[str] = set()
    for i in st.ids:
        m = st.by[i]
        for u in m.links:
            raw.setdefault(P.nurl(u), u)
        for u in (m.url, m.nurl):
            if u:
                raw.setdefault(P.nurl(u), u)
        for u in P.own_pages(m):
            if own(u):
                held[u].append(m.src_name)
        for u in set(P.links(m)):
            if own(u):
                linked[u].add(i)
        ml = st.main_link(i)
        if ml and own(ml):
            main.add(ml)
    out: List[OwnPage] = []
    seen: Set[str] = set()
    src_page = st.src_page if st.src_page and own(st.src_page) else None
    for u in [*held, *sorted(linked, key=lambda u: (-len(linked[u]), u)), *sorted(main), *([src_page] if src_page else [])]:
        if u in seen:
            continue
        how = ("held" if u in held else "linked" if len(linked.get(u, ())) >= 2 else "main_link" if u in main
               else "source_page" if u == src_page else "linked" if is_tweet(_full(u) or "") else None)
        if how is None:
            continue
        seen.add(u)
        out.append(OwnPage(raw.get(u, "https://" + u), how, held.get(u, [])))
    return out


def _named(cur: Any, mk: Any) -> Dict[str, Tuple[Set[str], Set[str]]]:
    """{source: (the entity roots its name names, with their ancestors; its name's handle forms)}: a source is an
    actor's own when the actor is among them (perspectives.Makers.author_is, read once for every source)."""
    from insight_core.markx import names as N
    cur.execute("SELECT id::text, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url) FROM sources")
    out = {}
    for sid, name in cur.fetchall():
        r = mk.of_name(name)
        roots = {r, *mk.ancestors(r)} if r else set()
        out[sid] = (roots, set(N.handle_forms(re.sub(r"\s+", "", (name or "").lower()))))
    return out


def events(cur: Any, now: datetime, *, within: int = WITHIN_DAYS) -> Tuple[List[Event], int]:
    """The events to judge (the module's rule) and how many stories of 2+ voices were checked."""
    from insight_core.markx import built, identity, schemas
    from insight_core.markx import entity_addresses as EA
    from insight_core.markx import perspectives as P
    stories = _stories(cur, now - timedelta(days=within))
    picked: Dict[str, Tuple[Dict[str, Any], str, int]] = {}
    checked = 0
    for sid, s in stories.items():
        posts = list(s["posts"].values())
        voices = built.voices(posts)
        if voices < MIN_VOICES:
            continue
        checked += 1
        et = built.event_type(posts)
        if et in ANNOUNCED:
            picked[sid] = (s, et, voices)
    if not picked:
        return [], checked
    book = identity.load_book(cur)
    sts = built.stories_of(cur, picked, book=book)
    actors: Dict[str, str] = {}
    for sid, st in sts.items():
        a = _actor(st, book)
        if a and a in book.ents and schemas.entity_type(book.ents[a].type) in ACTOR_TYPES:
            actors[sid] = a
    if actors:   # the readings' main actors decide (read-v3's where a post has one, else read-v2's)
        from insight_core.markx import names as N, tasks
        ids = sorted({i for sid in actors for i in sts[sid].ids})
        read = {**tasks.readings(cur, ids, "read-v2"), **tasks.readings(cur, ids, "read-v3")}
        for sid, a in list(actors.items()):
            st = sts[sid]

            def is_actor(name: str, a: str = a, st: Any = st) -> bool:
                r = book.by_key(N.key(name)) if N.key(name) else None
                return (r is not None and book.root(r) == a) or st.mk.is_maker(name, a)

            mains = [((read[i].get("main") or {}).get("actors") or []) for i in st.ids if i in read]
            if not named_actor([[x for x in xs if isinstance(x, str)] for xs in mains], is_actor):
                del actors[sid]
    if not actors:
        return [], checked
    # the actor's and its things' own addresses (0138), read through the merges
    things: Dict[str, Set[str]] = defaultdict(set)
    for sid, a in actors.items():
        st = sts[sid]
        for i in st.ids:
            for m in st.mk.mentions.get(i, ()):
                r = book.root(m.get("entity_id")) if m.get("entity_id") and m.get("role") in ACTOR_ROLES else None
                if r and r != a and a in st.mk.ancestors(r):
                    things[sid].add(r)
    roots = set(actors.values()) | {r for rs in things.values() for r in rs}
    found = EA.current(cur, book, roots)
    addr = {r: {P.nurl(u) for k, u, *_ in rows if k in ADDRESS_KINDS} for r, rows in found.items()}
    mk = next(iter(sts.values())).mk
    named = _named(cur, mk)
    out: List[Event] = []
    for sid, a in actors.items():
        st = sts[sid]
        s, et, voices = picked[sid]
        addresses = set(addr.get(a, ())) | {u for r in things[sid] for u in addr.get(r, ())}
        pages = _own_pages(st, a, addresses)
        forms = mk.forms(a)
        mine = {src for src, (roots, fs) in named.items() if a in roots or fs & forms}
        if not pages and not mine:
            continue
        posts = [{"id": i, "title": st.by[i].title, "source": st.by[i].src_name, "source_id": st.by[i].src,
                  "url": st.by[i].url, "at": P.pub(st.by[i]).isoformat()} for i in st.ids[:POSTS_SHOWN]]
        out.append(Event(story=sid, headline=s["headline"] or (posts[0]["title"] if posts else ""), event_type=et,
                         voices=voices, first_at=s["first_at"], actor=a, actor_name=book.label(a) or "",
                         pages=pages, member_sources={p.source for p in s["posts"].values()}, actor_sources=mine,
                         posts=posts))
    return out, checked


def scan(cur: Any, now: datetime, *, within: int = WITHIN_DAYS) -> Dict[str, Any]:
    """{rows (every one, hidden ones too), checked, events}: read only."""
    evs, checked = events(cur, now, within=within)
    sources = _sources(cur)
    sites = {ch.site for ev in evs for o in ev.pages if (ch := channel_of(o.url)) is not None and ch.kind == "site"}
    sources = _with_sections(cur, sources, sites)
    return {"rows": judge(evs, sources), "checked": checked, "events": len(evs)}


def tests(cur: Any) -> Dict[str, Any]:
    from insight_core.db.repo_operations import SystemSettingsRepository
    row = SystemSettingsRepository.get(cur, KEY)
    return ((row[0] if row else None) or {}).get("tests") or {}


def page(found: Dict[str, Any], tested: Dict[str, Any], hidden: Set[str], *, limit: int = SHOWN) -> Dict[str, Any]:
    """The answer: the rows not hidden, each with its channel's test, the first `limit`."""
    rows = [dict(r, test=tested.get(r["channel"]["key"])) for r in found["rows"] if r["key"].lower() not in hidden]
    return {"rows": rows[:limit], "total": len(rows), "checked": found["checked"], "events": found["events"],
            "within_days": WITHIN_DAYS}


# ---- the test (the web; background) -------------------------------------------------------------------

async def test_channel(http: Any, registry: Any, ch: Dict[str, Any], pages: Sequence[str], *, limiter: Any = None,
                       clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Dict[str, Any]:
    """A channel's follow test: {label (feed | page | other_feed | headlines | blocked), holds (of `pages`: the most a
    feed or page found keeps), feeds [{url, title, holds}], pages [{url, prefix, found, holds}], preview {prefix, found,
    items [{url, title}]} (page watching of the section, when the finder found neither), at}."""
    from insight_core.ingestion import where_linked
    from insight_core.ingestion.gates import HostLimiter
    from insight_core.ingestion.kinds import page_watch
    from insight_core.services import discover_reads as DR
    at = clock().isoformat()
    if ch["kind"] == "account":
        source = DR.kind_source(ch["key"], registry)
        label = await DR.kind_test(registry, source) if source else "headlines"
        return {"label": label, "at": at}
    polite = DR.Polite(http)
    out: Dict[str, Any] = {}
    async with (limiter or HostLimiter()).slot(DR.slot(ch["url"])):
        try:
            found = await where_linked.follow(polite, registry, ch["url"], list(pages))
        except Exception as exc:  # noqa: BLE001 - a site that can't be asked is labelled by what it answered
            logger.info("Discover main source: the finder on %s failed (%s)", ch["url"], type(exc).__name__)
            found = {}
        label = DR.label(found, polite)
        out["feeds"] = [{"url": f["url"], "title": f.get("title"), "holds": f.get("holds")}
                        for f in (found.get("feeds") or [])[:3]]
        out["pages"] = [{"url": p.get("url"), "prefix": p.get("prefix"), "found": p.get("found"), "holds": p.get("holds")}
                        for p in (found.get("pages") or [])[:3] if p.get("items")]
        if label not in ("feed", "page", "blocked"):
            try:
                prev = await page_watch.preview(polite, ch["url"], ch.get("prefix") if ch.get("prefix") != "/" else None)
            except Exception as exc:  # noqa: BLE001 - an unreadable section: nothing to watch
                logger.info("Discover main source: the preview of %s failed (%s)", ch["url"], type(exc).__name__)
                prev = None
            if prev is not None:
                items = [{"url": i["url"], "title": i.get("title")} for i in prev.get("items") or []][:3]
                out["preview"] = {"prefix": prev.get("prefix"), "found": prev.get("found"), "items": items}
                if prev.get("items"):
                    label = "page"
    held = [x.get("holds") for x in (*out["feeds"], *out["pages"]) if isinstance(x.get("holds"), int)]
    return {"label": label, "holds": max(held) if held else None, "of": len(pages), **out, "at": at}


def to_test(answer: Dict[str, Any], tested: Dict[str, Any], now: datetime, *, limit: int = TESTS_PER_RUN) -> List[Dict[str, Any]]:
    """The shown rows' channels to test: missing or wrong-section ones without a test in CHECK_DAYS, the first `limit`."""
    out, seen = [], set()
    for r in answer["rows"]:
        ch = r["channel"]
        if r["kind"] == "disabled" or ch["key"] in seen or not due(tested.get(ch["key"]), now):
            continue
        seen.add(ch["key"])
        out.append({**ch, "pages": [e["own_page"]["url"] for e in r["events"] if e.get("own_page")]})
    return out[:limit]


class MainSource:
    """The list per open (cached while nothing it reads changed, at most CACHE_SECONDS) and its background tests."""

    def __init__(self, db_url: str, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.db_url, self.clock = db_url, clock
        self._cache: Tuple[Any, float, Optional[Dict[str, Any]]] = (None, 0.0, None)
        self._lock = threading.Lock()
        self._running: Optional[asyncio.Task] = None

    def _stamp(self, cur: Any) -> Tuple:
        cur.execute("""SELECT (SELECT max(valid_from) FROM mx_story_posts), (SELECT max(valid_to) FROM mx_story_posts),
                              (SELECT count(*) FROM mx_readings WHERE guide = 'read-v3'),
                              (SELECT max(updated_at) FROM sources), (SELECT count(*) FROM sources)""")
        return tuple(cur.fetchone())

    def found(self) -> Dict[str, Any]:
        from insight_core.db import database as db
        with self._lock, db.connection(self.db_url) as conn, conn.cursor() as cur:
            stamp = self._stamp(cur)
            kept_stamp, kept_at, kept = self._cache
            if kept is not None and kept_stamp == stamp and time.monotonic() - kept_at < CACHE_SECONDS:
                return kept
            got = scan(cur, self.clock())
            conn.rollback()
            self._cache = (stamp, time.monotonic(), got)
            return got

    def answer(self, *, limit: int = SHOWN) -> Dict[str, Any]:
        from insight_core.db import database as db
        from insight_core.db.repo_stories import StoriesRepository
        found = self.found()
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            tested, hidden = tests(cur), StoriesRepository.hidden(cur)
        return page(found, tested, hidden, limit=limit)

    async def run_tests(self, http: Any, registry: Any) -> int:
        from insight_core.db import database as db
        from insight_core.ingestion.gates import HostLimiter
        answer = await asyncio.to_thread(self.answer)
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            tested = tests(cur)
        todo = to_test(answer, tested, self.clock())
        if not todo:
            return 0
        limiter = HostLimiter()
        got = await asyncio.gather(*(test_channel(http, registry, ch, ch["pages"], limiter=limiter, clock=self.clock)
                                     for ch in todo))
        from insight_core.db.repo_operations import SystemSettingsRepository
        with db.transaction(self.db_url) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext('insight.discover_main_source'))")
            row = SystemSettingsRepository.get(cur, KEY)
            value = (row[0] if row else None) or {}
            value["tests"] = {**(value.get("tests") or {}), **{ch["key"]: t for ch, t in zip(todo, got)}}
            SystemSettingsRepository.upsert(cur, KEY, value)
        logger.info("Discover main source: %d channels tested", len(todo))
        return len(todo)

    def start(self, http: Any, registry: Any) -> bool:
        """Test the shown channels in the background (one run at a time; off with INSIGHT_DISCOVER_READS=0)."""
        from insight_core.services import discover_reads
        if not discover_reads.enabled() or (self._running is not None and not self._running.done()):
            return False

        async def run() -> None:
            try:
                await self.run_tests(http, registry)
            except Exception:  # noqa: BLE001 - derived; the next open tries again
                logger.exception("Discover main source: the tests failed")

        self._running = asyncio.get_running_loop().create_task(run())
        return True


__all__ = ["ANNOUNCED", "Channel", "Event", "MainSource", "OwnPage", "Src", "channel_of", "covers", "due", "events",
           "judge", "on_channel", "page", "scan", "section_of", "test_channel", "to_test"]
