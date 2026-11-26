"""Track scout: a track finds sources in a sphere INSIGHT doesn't read yet.

A run finds candidate sources for a track's sphere, test-reads each through the add path (the feed finder, then page
watching) into a scratch area (mx_scout_items), has the track's judge rate what it read, and shows the owner "<source>
(<platform>): 14 of its last 20 posts fit · 3 a week · reads well" with Follow active / passive / Not this one.
Nothing is followed without the owner's tap; nothing read is a post.

**When** (`start`): the owner's tap, and weekly (`due_weekly`, insight-ingestion's hook): every described track once
a week, starving ones (fewer than WEEKLY_MIN items in) first, one weekly run open at a time.

**Candidates, five finders** (no request but the two questions): 1. `maker`: a person the track's in and ✓ posts name (Mark X's entities)
whose own account or site the same post links or @mentions (its handle or site is the name: `own_address`), even from
one post; 2. `match`: the link targets (and @mentions) of those posts, by Discover's address key; never one you
follow, never a link that is no source's (`source_link`: no public host, an action or share link, an app's page, a
paper), never a reference, app, archive, document or paper place, never a key answered "Not this one"; 3. `shape`:
platform-class addresses built from the track's words and names (Hacker News' search feed, accounts; no site is named
here); 4. `haiku`: one `scout` task, each source test-read like the others, never trusted as is; 5. `web`: one
`websearch` task (guide websearch-sphere-v1, asked of the worker: Claude Code's web search, Haiku) for new projects,
tools, makers and sites of the track's sphere this week or month, each result's own address keyed and tested like
match's (`web_candidates`), its task id in the run's stats.web_task_id. A platform the server
can never read (SERVER_BLOCKED: Reddit, read through the reader's browser, 0262) is no candidate of these finders.

**The test read** (scout_reads.Reader): at most MAX_READS candidates a run, by each finder's share (READ_SHARE), up to
20 newest items each; the share of a finder whose question is still open (haiku's, web's) is held for its answer, the rest
refilled by the others only once it is answered. An X account is read and followed as the add path does
(discover_reads.kind_source: feed_finder.bridge_feed's Nitter feed). One that reads badly (scout_reads.health) is never
suggested. **The judge**: each item a `track` task (subject 'scout_item'), at most MAX_JUDGEMENTS a run; precision =
in / judged. **Suggested** (`suggestions`): read well, MIN_JUDGED+ judged, precision FLOOR+, ranked by precision then
cadence. Following adds the source as POST /api/sources does and records its provenance (mx_source_provenance).

`advance` is called by the API after the tap and by insight-ingestion's hook (`tick`), each claiming the run
(busy_until) so two never read at once. `tick` also settles every open run with nothing to read (its questions
answered: done), and `settle` closes a track run still open STALL after it started (its questions unanswered: done,
stats.closed says so), so the one open weekly run never holds the other tracks' weekly runs. With
INSIGHT_DISCOVER_READS=0 nothing is read. Only mx_* tables are written, except the owner's own Follow.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.markx import pairing, repo, schemas, scout_reads, tasks

log = logging.getLogger(__name__)

KIND = "scout"
JUDGE = "track"
MAX_READS = 40
MAX_JUDGEMENTS = 800
MAX_REQUESTS = 800                # the test reads' request budget a run (the finder alone may ask ~10 a candidate)
ITEMS = scout_reads.ITEMS
READ_SHARE = {"maker": 8, "match": 10, "haiku": 8, "web": 8, "shape": 6}   # not measured; MAX_READS in all
FINDER_ORDER = ("maker", "match", "haiku", "web", "shape")
ASKED = ("haiku", "web")          # the finders whose candidates come with a question's answer (held while it is open)
WEB_KIND, WEB_GUIDE = "websearch", "websearch-sphere-v1"   # the worker's web search (Claude Code's, Haiku)
SERVER_BLOCKED = frozenset({"reddit"})   # platforms every server read is refused (0262: the reader's browser reads them)
STALL = timedelta(days=2)         # a track run still open this long after it started is closed (not measured)
WEEKLY_MIN = 5
WEEK = timedelta(days=7)
FLOOR = 0.30
MIN_JUDGED = 5
BEST_ITEMS = 10
MATCH_POSTS = 200                 # the newest in / ✓ posts whose links finder 1 reads
MATCH_MAX = 60                    # candidates finder 1 keeps (most linked first)
MAKER_MAX = 40                    # candidates the maker finder keeps (most posts, then the newest, first)
MAKER_MIN = 4                     # a squashed name shorter than this is no one's handle
MAKER_ROLES = frozenset({"actor", "subject", "mention"})   # a person quoted as a `source` made nothing here
SHAPE_NAMES = 3
CLAIM = timedelta(minutes=20)
JUDGE_PRIORITY = 0
TEXT_CHARS = 1200

# The Hacker News class's search feed (the feed service INSIGHT reads HN through: utils/post_links names it "hn").
HN_SEARCH = "https://hnrss.org/newest?q={q}"
REDDIT_SEARCH = "https://www.reddit.com/search.rss?q={q}&sort=new"
STOPWORDS = frozenset("""a an the and or of for to in on at by with from about into over under as is are be been being
it its this that these those my our your their his her them they we you i me not no nor but so than then too very can
will just also any all some such each every more most other new good cool best great nice things thing stuff posts post
like what which who whom whose when where why how only own same few lot lots want wants really much many way ways
make makes made using use used people get gets got one two""".split())
_WORD = re.compile(r"[a-z0-9][a-z0-9+#.\-]*[a-z0-9+#]|[a-z0-9]")
_SQUASH = re.compile(r"[^a-z0-9]+")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: Any) -> Optional[str]:
    return t.astimezone(timezone.utc).isoformat() if isinstance(t, datetime) else None


def squash(text: str) -> str:
    return _SQUASH.sub("", (text or "").casefold())


# ---- addresses ------------------------------------------------------------------------------------------

def normal_address(platform: str, address: str) -> Optional[str]:
    """A candidate's address as a full https address: a handle under its platform class ("r/x", "@h", "x"), a bare
    host ("example.org/blog"); None for something that is no address (a search page asked for is kept: it is one)."""
    a = (address or "").strip().strip("<>\"'")
    if not a or any(c.isspace() for c in a):
        return None
    if a.startswith(("http://", "https://")):
        return a
    platform = (platform or "").lower()
    handle = a.lstrip("@")
    if platform == "reddit":
        m = re.match(r"^/?(?:r/)?([A-Za-z0-9_]{2,40})/?$", a)
        if m:
            return f"https://www.reddit.com/r/{m.group(1)}"
    elif platform == "youtube" and re.match(r"^@?[\w.\-]{2,60}$", a) and "." not in handle:
        return f"https://www.youtube.com/@{handle}"
    elif platform == "telegram" and re.match(r"^@?[A-Za-z0-9_]{4,40}$", a):
        return f"https://t.me/{handle}"
    elif platform == "x" and re.match(r"^@?[A-Za-z0-9_]{1,30}$", a):
        return f"https://x.com/{handle}"
    if "." in a.split("/", 1)[0]:
        return "https://" + a
    return None


def key_of(address: str, platforms: Optional[Dict[str, Tuple[str, ...]]] = None) -> Tuple[Optional[str], str, bool]:
    """(Discover's key, its site, on a platform) of an address; a code host's or model hub's thing is keyed by its
    owner (the account that makes it); a search feed by its whole address (it is its own source)."""
    from insight_core.ingestion.feed_finder import is_search_feed
    from insight_core.utils.discover_rules import discover_address
    from insight_core.utils.entity_originals import platform_thing
    from insight_core.utils.addresses import host_of, site_of
    if is_search_feed("", address):
        return address.split("://", 1)[-1].lower(), site_of(host_of(address)), True
    thing = platform_thing(address)
    if thing and thing[1]:
        host = host_of(address)
        host = host[4:] if host.startswith("www.") else host
        return f"{host}/{thing[1].lower()}", site_of(host), True
    key, site, platform = discover_address(address, platforms or {})
    return (key[4:] if key and key.startswith("www.") else key), site, platform


def address_of_key(key: str) -> str:
    return key if key.startswith(("http://", "https://")) else "https://" + key


# ---- the track's posts -------------------------------------------------------------------------------------

def in_posts(cur: Cursor, folder_id: str, *, limit: int = MATCH_POSTS, since: Optional[datetime] = None) -> List[str]:
    """The track's posts judged in or labelled ✓ (not ✗), newest first. Haiku's in from a source the owner switched off
    is none (it feeds no suggestion); the owner's ✓ is the owner's."""
    from insight_core.db.repo_stories import suggestable_sql
    from insight_core.markx import tracks
    labels = tracks.labels(cur, folder_id)
    cur.execute(f"""SELECT DISTINCT ON (i.post_id) i.post_id::text, {tracks._date('p')}
                      FROM mx_track_items i JOIN posts p ON p.id = i.post_id
                     WHERE i.track_id = %s AND i.verdict AND {suggestable_sql("p.source_id")}
                     ORDER BY i.post_id""", (folder_id,))
    rows = {pid: at for pid, at in cur.fetchall() if labels.get(pid, ("",))[0] != "out"}
    ok = [p for p, (a, _) in labels.items() if a == "in"]
    if ok:
        cur.execute(f"SELECT p.id::text, {tracks._date('p')} FROM posts p WHERE p.id = ANY(%s::uuid[])", (ok,))
        rows.update(dict(cur.fetchall()))
    got = [(at, pid) for pid, at in rows.items() if since is None or (at and at >= since)]
    got.sort(key=lambda x: (x[0] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return [pid for _, pid in got[:limit]]


def best_items(cur: Cursor, folder_id: str, n: int = BEST_ITEMS) -> List[tasks.Post]:
    """The track's best items for the scout question: ✓ first, then `in` by confidence, newest first."""
    from insight_core.markx import tracks
    labels = tracks.labels(cur, folder_id)
    cur.execute("""SELECT DISTINCT ON (post_id) post_id::text, confidence FROM mx_track_items
                    WHERE track_id = %s AND verdict ORDER BY post_id, confidence DESC NULLS LAST""", (folder_id,))
    conf = {pid: c or 0.0 for pid, c in cur.fetchall() if labels.get(pid, ("",))[0] != "out"}
    for pid, (a, _) in labels.items():
        if a == "in":
            conf[pid] = 2.0
    posts = tasks.load_posts(cur, list(conf))
    order = sorted(posts.values(), key=lambda p: (-conf.get(p.id, 0), -p.at.timestamp()))
    return order[:n]


# ---- finder 1: the matches' links ----------------------------------------------------------------------------

def _platforms(cur: Cursor) -> Dict[str, Tuple[str, ...]]:
    from insight_core.db.repo_discover import DiscoverRepository
    kept = DiscoverRepository.kept(cur, found=False) or {}   # platforms only (0283)
    return {host: tuple(prefix) for host, prefix in (kept.get("platforms") or {}).items()}


class Followed:
    """What you follow, as finder keys are compared with it: the sites (a site's key), the platform accounts, and
    every source's address without its scheme (a code host owner's activity feed, <host>/<owner>.atom, is that owner)."""

    def __init__(self, sites: Iterable[str] = (), accounts: Iterable[str] = (), handles: Iterable[str] = ()) -> None:
        self.sites, self.accounts = set(sites), set(accounts)
        self.handles = [h.lower().split("://", 1)[-1].removeprefix("www.") for h in handles if h]

    def __contains__(self, item: Tuple[str, str, bool]) -> bool:
        key, site, platform = item
        k = key.lower().removeprefix("www.")
        if any(h == k or h.startswith((k + "/", k + ".", k + "?")) for h in self.handles):
            return True
        if platform:
            return k in self.accounts
        return bool(site) and site in self.sites or k in self.sites


def _followed(cur: Cursor) -> Followed:
    from insight_core.db.repo_discover import light_facts
    facts = light_facts(cur)
    cur.execute("SELECT handle_or_url FROM sources")
    return Followed(facts.followed(), facts.followed_accounts(), [h for (h,) in cur.fetchall()])


def is_followed(key: str, site: str, platform: bool, followed: Followed) -> bool:
    return (key, site, platform) in followed


def source_link(url: str) -> bool:
    """Whether a link can be a source's at all, by the address's nature alone (Discover's place tests, per link): a
    public host (not localhost, a dotless name or an IP), not an action or share link carrying another address
    (a submit or share page: archive_address), not an app's shared page, not an interactive page told by its query,
    not a paper. A site whose links pass is still tested as a place (place_kind) by its caller."""
    import ipaddress
    from insight_core.utils.addresses import host_of
    from insight_core.utils.discover_rules import app_address, archive_address, paper_address, query_address
    host = host_of(url).rstrip(".")
    if "." not in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not (archive_address(url) or app_address(url) or query_address(url) or paper_address(url))


def _post_links(cur: Cursor, posts: Sequence[str]) -> Tuple[List[Tuple[str, str]], Dict[str, str]]:
    """(post, link target) of the posts' own links and @mentions, and each post's source address."""
    cur.execute("""SELECT l.post_id::text, l.target_url FROM post_links l
                    WHERE l.post_id = ANY(%s::uuid[])
                      AND ((NOT l.boilerplate AND l.kind = 'link') OR l.kind = 'mention')""", (list(posts),))
    rows = cur.fetchall()
    cur.execute("SELECT p.id::text, s.handle_or_url FROM posts p JOIN sources s ON s.id = p.source_id "
                "WHERE p.id = ANY(%s::uuid[])", (list(posts),))
    return rows, dict(cur.fetchall())


def _own_link(own: Optional[str], key: str) -> bool:
    return (own or "").split("://", 1)[-1].lower().removeprefix("www.").startswith(key)


def match_candidates(cur: Cursor, folder_id: str, *, skip: Iterable[str] = (),
                     posts: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Finder 1: the link targets of the track's in and ✓ posts, by address key, the most posts first, then the
    most recently linked (`posts` newest first: in_posts)."""
    from insight_core.utils.discover_rules import place_kind
    posts = in_posts(cur, folder_id) if posts is None else list(posts)
    if not posts:
        return []
    order = {pid: n for n, pid in enumerate(posts)}
    rows, own = _post_links(cur, posts)
    platforms = _platforms(cur)
    followed = _followed(cur)
    skip = set(skip)
    by_key: Dict[str, Dict[str, Any]] = {}
    for pid, url in rows:
        if not source_link(url):
            continue
        key, site, platform = key_of(url, platforms)
        if not key or key in skip or is_followed(key, site, platform, followed):
            continue
        if _own_link(own.get(pid), key):
            continue                                   # a source's link to itself
        got = by_key.setdefault(key, {"key": key, "site": site, "platform": platform, "posts": set(), "urls": []})
        got["posts"].add(pid)
        if url not in got["urls"]:
            got["urls"].append(url)
    kept = {key: got for key, got in by_key.items() if not place_kind(key, got["urls"][:20])}
    # a post's attention is shared by the places it links: one linking a single place points at it, one footer of
    # ten social links points at none of them much
    places: Counter = Counter(p for got in kept.values() for p in got["posts"])
    out = []
    for key, got in kept.items():
        n = len(got["posts"])
        out.append({"finder": "match", "platform": _platform_word(key, got["platform"]), "address": address_of_key(key),
                    "key": key, "name": None, "why": f"linked by {n} of the track's posts",
                    "evidence": {"posts": n, "linked": got["urls"][:20],
                                 "weight": round(sum(1 / places[p] for p in got["posts"]), 3),
                                 "newest": min(order.get(p, len(order)) for p in got["posts"])}})
    out.sort(key=lambda c: (-c["evidence"]["posts"], -c["evidence"]["weight"], c["evidence"]["newest"], c["key"]))
    return out[:MATCH_MAX]


# ---- finder 0: the makers of the finds --------------------------------------------------------------------------

def name_handle(name: str) -> str:
    """A person's name as a handle or a site's name would write it: its letters and digits, lower case
    ("Jakub Antalik" -> "jakubantalik"); "" for a name in another script."""
    return squash(name)


def own_address(name: str, url: str, platforms: Optional[Dict[str, Tuple[str, ...]]] = None
                ) -> Optional[Tuple[str, str, bool]]:
    """(key, site, on a platform) when `url` is the person `name`'s own: a person's account (Discover's
    discover_people.person_key: x.com/jakubantalik, github.com/jakubantalik, never a wiki page or a raw file) whose
    handle is the name, or a site whose own name is (jakubantalik.com); else None. The name and the address must
    agree whole (MAKER_MIN+ letters): a name alone is never an address."""
    from insight_core.markx.discover_people import person_key
    from insight_core.utils.addresses import host_of, site_of
    want = name_handle(name)
    if len(want) < MAKER_MIN or not source_link(url):
        return None
    key, site, platform = key_of(url, platforms or {})
    if not key:
        return None
    if platform or "/" in key:
        person = person_key(url, platforms or {})
        if person is None:
            return None
        handle = person[0].rsplit("/", 1)[-1].lstrip("@~")
        return (person[0], site, True) if squash(handle) == want else None
    label = site_of(host_of(url)).split(".", 1)[0]
    return (key, site, False) if squash(label) == want else None


def maker_candidates(cur: Cursor, folder_id: str, *, skip: Iterable[str] = (),
                     posts: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """Finder 0: the people the track's in and ✓ posts name (Mark X's entities of type person, as actor, subject or
    mention) whose own account or site the same post links or @mentions (own_address), even from one post; the most
    posts first, then the newest."""
    posts = in_posts(cur, folder_id) if posts is None else list(posts)
    if not posts:
        return []
    order = {pid: n for n, pid in enumerate(posts)}
    cur.execute("""SELECT DISTINCT post_id::text, name, role FROM mx_mentions_now
                    WHERE post_id = ANY(%s::uuid[]) AND type = 'person' AND name IS NOT NULL""", (posts,))
    people: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for pid, name, role in cur.fetchall():
        if role in MAKER_ROLES and len(name_handle(name)) >= MAKER_MIN:
            people[pid].append((name, role))
    if not people:
        return []
    rows, own = _post_links(cur, list(people))
    platforms = _platforms(cur)
    followed = _followed(cur)
    skip = set(skip)
    by_key: Dict[str, Dict[str, Any]] = {}
    for pid, url in rows:
        for name, role in people.get(pid, ()):
            got = own_address(name, url, platforms)
            if not got:
                continue
            key, site, platform = got
            if key in skip or is_followed(key, site, platform, followed) or _own_link(own.get(pid), key):
                continue
            c = by_key.setdefault(key, {"key": key, "platform": platform, "name": name, "posts": set(), "made": set(),
                                        "urls": []})
            c["posts"].add(pid)
            if role == "actor":
                c["made"].add(pid)
            if url not in c["urls"]:
                c["urls"].append(url)
    out = []
    for key, c in by_key.items():
        n, made = len(c["posts"]), len(c["made"])
        why = (f"made something {made} of the track's posts {'is' if made == 1 else 'are'} about" if made
               else f"named in {n} of the track's posts, which link{'s' if n == 1 else ''} their own account")
        out.append({"finder": "maker", "platform": _platform_word(key, c["platform"]), "address": address_of_key(key),
                    "key": key, "name": c["name"], "why": why,
                    "evidence": {"posts": n, "made": made, "person": c["name"], "linked": c["urls"][:20],
                                 "newest": min(order.get(p, len(order)) for p in c["posts"])}})
    out.sort(key=lambda c: (-c["evidence"]["made"], -c["evidence"]["posts"], c["evidence"]["newest"], c["key"]))
    return out[:MAKER_MAX]


def _platform_word(key: str, platform: bool) -> str:
    from insight_core.utils.addresses import PLATFORM_SITES, site_of
    site = site_of(key.split("/", 1)[0])
    for word, sites in PLATFORM_SITES.items():
        if site in sites:
            return word
    from insight_core.utils.entity_originals import CODE_SITES, MODEL_HUBS, PACKAGE_SITES
    if site in CODE_SITES:
        return "code"
    if site in MODEL_HUBS or site in PACKAGE_SITES:
        return "hub"
    return "site" if not platform else "account"


# ---- finder 2: platform shapes -------------------------------------------------------------------------------

def words_of(text: str) -> List[str]:
    return [w for w in _WORD.findall((text or "").casefold()) if w not in STOPWORDS and len(w) >= 2 and not w.isdigit()]


_CLAUSE = re.compile(r"[.,:;!?()\[\]{}\"“”«»—–/]|\s-\s|\band\b|\bor\b")


def description_terms(track: Dict[str, Any], n: int = 6) -> List[str]:
    """The description's nouns, roughly: its two-word phrases first, each two words written side by side in one clause
    (no stop word between: "weekend hacks", never "interesting build" out of "interesting things people build"), then
    its words that are no stop word."""
    excluded = set(words_of(track.get("excludes") or ""))
    pairs: List[str] = []
    for text in (track.get("name") or "", track.get("description") or ""):
        for clause in _CLAUSE.split(text.casefold()):
            tokens = _WORD.findall(clause)
            for a, b in zip(tokens, tokens[1:]):
                if all(w not in STOPWORDS and w not in excluded and len(w) >= 2 and not w.isdigit() for w in (a, b)):
                    pairs.append(f"{a} {b}")
    words = words_of(f"{track.get('name') or ''}. {track.get('description') or ''}")
    single = [w for w in words if w not in excluded and len(w) >= 3]
    return list(dict.fromkeys([*pairs[:2], *single]))[:n]


def track_terms(cur: Cursor, track: Dict[str, Any], pos: Sequence[str]) -> List[str]:
    """The learned terms when 2+ items are in (finders' lexicon over the in items), else the description's words."""
    if len(pos) >= 2:
        try:
            from insight_core.markx import finders
            learned = finders.learn(cur, track, list(pos)[:50]).get("words") or []
            if learned:
                return list(dict.fromkeys([*description_terms(track, 2), *learned]))[:8]
        except Exception:  # noqa: BLE001 - the description's words instead
            log.exception("Scout: the learned terms of %s could not be read", track.get("folder_id"))
    return description_terms(track)


def item_names(cur: Cursor, posts: Sequence[str], n: int = SHAPE_NAMES) -> List[str]:
    """The names most in-items make their subject or actor (Mark X's mentions), 2+ items each."""
    if not posts:
        return []
    cur.execute("""SELECT name, count(DISTINCT post_id) FROM mx_mentions_now
                    WHERE post_id = ANY(%s::uuid[]) AND role IN ('subject', 'actor') AND name IS NOT NULL
                    GROUP BY name ORDER BY 2 DESC, name LIMIT 20""", (list(posts),))
    return [name for name, c in cur.fetchall() if c >= 2 and len(squash(name)) >= 3][:n]


def shape_candidates(terms: Sequence[str], names: Sequence[str], *, x_bridge: Optional[str]) -> List[Dict[str, Any]]:
    """Finder 2: the platform classes' addresses for the track's phrases (Hacker News' search feed) and names (a video
    channel, an X account through the bridge). No Reddit (SERVER_BLOCKED) and no X search: the bridge's kind reads an
    account's feed only (nitter_rss reads /search/rss as an account named "search", its query dropped)."""
    out: List[Dict[str, Any]] = []

    def add(platform: str, address: str, why: str) -> None:
        out.append({"finder": "shape", "platform": platform, "address": address, "name": None, "why": why,
                    "evidence": {}})
    phrases = list(dict.fromkeys(t for t in terms if t))[:2]
    for phrase in phrases:
        add("hn", HN_SEARCH.format(q=urllib.parse.quote(phrase)), f"Hacker News' search feed for “{phrase}”")
    for name in names[:SHAPE_NAMES]:
        handle = squash(name)
        add("youtube", f"https://www.youtube.com/@{handle}", f"a video channel named for “{name}”")
        if x_bridge:
            add("x", f"https://x.com/{handle}", f"an X account named for “{name}”")
    return out


def _x_bridge() -> Optional[str]:
    from insight_core.ingestion.kinds.nitter_rss import nitter_origin
    try:
        return nitter_origin() or None
    except Exception:  # noqa: BLE001 - no bridge configured
        return None


# ---- finder 3: the scout question ------------------------------------------------------------------------------

PLATFORMS_LINE = ("sites and blogs (a feed, or a page INSIGHT watches), YouTube channels, Telegram channels, "
                  "X accounts (through a bridge), Hacker News, code hosts' and model hubs' accounts, paper categories, "
                  "podcasts and newsletters")


def scout_input(cur: Cursor, track: Dict[str, Any], best: Sequence[tasks.Post], followed_names: Sequence[str]) -> str:
    lines = [f"TRACK: {track['name']}", f"Belongs: {track['description']}"]
    if track.get("excludes"):
        lines.append(f"Not: {track['excludes']}")
    lines.append(f"Platforms the reader's INSIGHT reads: {PLATFORMS_LINE}.")
    if followed_names:
        lines.append("Already followed for this track (do not name): " + "; ".join(followed_names[:30]))
    if best:
        lines.append("Best posts so far:")
        for p in best:
            t = re.sub(r"\s+", " ", p.title or p.text or "").strip()[:140]
            lines.append(f"- {t} ({p.source})")
    return "\n".join(lines)


def ask(cur: Cursor, track: Dict[str, Any], run_id: str) -> Tuple[Any, bool]:
    """The run's one `scout` task (a = the folder): (its id, whether new). The same question is one task."""
    from insight_core.markx import tracks
    schemas.ensure_guides(cur)
    names = [s["name"] for s in tracks.active_sources(cur, track["folder_id"])]
    question = scout_input(cur, track, best_items(cur, track["folder_id"]), names)
    task_id, new = repo.add_task(cur, kind=KIND, guide=schemas.KINDS[KIND].guide, subject_kind="track", input=question,
                                 a=track["folder_id"], priority=-1)
    cur.execute("UPDATE mx_scout_runs SET scout_task_id = %s WHERE id = %s", (task_id, run_id))
    return task_id, new


def haiku_candidates(answer: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for s in answer.get("sources") or []:
        address = normal_address(s.get("platform") or "", s.get("address") or "")
        if not address:
            continue
        out.append({"finder": "haiku", "platform": s.get("platform") or "site", "address": address,
                    "name": (s.get("name") or None), "why": (s.get("why") or "").strip()[:300] or None,
                    "evidence": {"asked": s.get("address")}})
    return out


def after_answer(cur: Cursor, task: Dict[str, Any], answer: Dict[str, Any]) -> int:
    """tasks.record's part for a `scout` answer: its sources become candidates of every open run asking it (a run
    closed meanwhile takes none: nothing would read them)."""
    cur.execute("""SELECT id::text, track_id::text FROM mx_scout_runs
                    WHERE scout_task_id = %s AND status IN ('running', 'waiting')""", (task["id"],))
    added = 0
    for run_id, track_id in cur.fetchall():
        added += add_candidates(cur, run_id, haiku_candidates(answer), track_id=track_id)
        cur.execute("UPDATE mx_scout_runs SET status = 'running' WHERE id = %s AND status = 'waiting'", (run_id,))
    return added


# ---- finder 5: the web, by the worker's search ---------------------------------------------------------------------

WEB_SEARCHES = schemas.WEBSEARCH_QUERIES


def web_input(cur: Cursor, track: Dict[str, Any], now: datetime) -> str:
    """The `websearch` question (guide websearch-sphere-v1): the track's sphere (name, description, excludes), the
    week it asks about (a new week is a new question), the places followed for it, the searches allowed."""
    from insight_core.markx import tracks
    monday = (now.astimezone(timezone.utc) - timedelta(days=now.astimezone(timezone.utc).weekday())).date()
    lines = [f"Track: {track['name']}", f"Belongs: {track['description']}"]
    if track.get("excludes"):
        lines.append(f"Not: {track['excludes']}")
    lines.append(f"Week of: {monday.isoformat()} (new this week or this month)")
    names = [s["name"] for s in tracks.active_sources(cur, track["folder_id"])]
    if names:
        lines.append("Already followed (leave out): " + "; ".join(names[:30]))
    lines.append(f"Searches allowed: at most {WEB_SEARCHES}")
    return "\n".join(lines)


def web_ask(cur: Cursor, track: Dict[str, Any], run_id: str, now: datetime) -> Tuple[Any, bool]:
    """The run's one web search, asked of the worker (a = the folder; its id kept in the run's stats.web_task_id):
    (its id, whether new). The same week's question is one task."""
    schemas.ensure_guides(cur)
    task_id, new = repo.add_task(cur, kind=WEB_KIND, guide=WEB_GUIDE, subject_kind="track",
                                 input=web_input(cur, track, now), a=track["folder_id"], priority=-1)
    _stats(cur, run_id, web_task_id=str(task_id))
    return task_id, new


def web_candidates(answer: Dict[str, Any], platforms: Optional[Dict[str, Tuple[str, ...]]] = None
                   ) -> List[Dict[str, Any]]:
    """The web search's results as candidates, keyed like the others (key_of), never a link that is no source's
    (source_link) nor a place that is none (place_kind). A front page is what the search was asked for (the maker's
    or project's own address): it is kept unless its host is a reference's (docs., help., app. ...)."""
    from insight_core.utils.discover_rules import REFERENCE_HOST, REFERENCE_PAGE_HOST, path_segments, place_kind
    out, seen = [], set()
    for c in (answer.get("candidates") or [])[:schemas.WEBSEARCH_MAX]:
        url = (c.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or not source_link(url):
            continue
        key, _, platform = key_of(url, platforms or {})
        if not key or key in seen:
            continue
        kind = place_kind(key, [url])
        front = not path_segments(url)
        if kind and not (front and kind == "reference" and not REFERENCE_HOST.match(key)
                         and not REFERENCE_PAGE_HOST.match(key)):
            continue
        seen.add(key)
        out.append({"finder": "web", "platform": _platform_word(key, platform), "address": address_of_key(key),
                    "key": key, "name": (c.get("title") or "").strip()[:120] or None,
                    "why": (c.get("why") or "").strip()[:300] or None,
                    "evidence": {"url": url, "title": (c.get("title") or "").strip()[:300] or None}})
    return out


def after_websearch(cur: Cursor, task: Dict[str, Any], answer: Dict[str, Any]) -> int:
    """tasks.record's part for a websearch-sphere-v1 answer: its results become candidates of every open run asking
    it, which may read them now (a run closed meanwhile takes none)."""
    cur.execute("""SELECT id::text, track_id::text FROM mx_scout_runs
                    WHERE stats->>'web_task_id' = %s AND status IN ('running', 'waiting')""", (str(task["id"]),))
    added = 0
    for run_id, track_id in cur.fetchall():
        added += add_candidates(cur, run_id, web_candidates(answer, _platforms(cur)), track_id=track_id)
        cur.execute("UPDATE mx_scout_runs SET status = 'running' WHERE id = %s AND status = 'waiting'", (run_id,))
    return added


# ---- candidates and runs ------------------------------------------------------------------------------------

def answered_not(cur: Cursor, track_id: Optional[str]) -> set:
    """The keys the owner answered "Not this one" for this track, or followed already (any run of it)."""
    if not track_id:
        return set()
    cur.execute("""SELECT DISTINCT c.key FROM mx_scout_candidates c JOIN mx_scout_runs r ON r.id = c.run_id
                    WHERE r.track_id = %s AND c.answer IS NOT NULL""", (track_id,))
    return {k for (k,) in cur.fetchall()}


def add_candidates(cur: Cursor, run_id: str, cands: Sequence[Dict[str, Any]], *, track_id: Optional[str] = None,
                   followed: Optional[Followed] = None) -> int:
    """Candidates into a run, once a key (a key another finder named first keeps its finder), never one you follow
    or answered for this track: how many were new."""
    platforms = _platforms(cur)
    followed = followed if followed is not None else _followed(cur)
    skip = answered_not(cur, track_id)
    cur.execute("SELECT count(*) FROM mx_scout_candidates WHERE run_id = %s", (run_id,))
    rank = cur.fetchone()[0]
    added = 0
    for c in cands:
        if c.get("key"):
            key, (_, site, platform) = c["key"], key_of(c["address"], platforms)
        else:
            key, site, platform = key_of(c["address"], platforms)
        if not key or key in skip or is_followed(key, site, platform, followed):
            continue
        if c["finder"] in FINDER_ORDER and _platform_word(key, platform) in SERVER_BLOCKED:
            continue
        cur.execute("""INSERT INTO mx_scout_candidates (run_id, finder, platform, address, key, name, why, evidence, rank)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s) ON CONFLICT (run_id, key) DO NOTHING""",
                    (run_id, c["finder"], c.get("platform") or "site", c["address"], key, c.get("name"), c.get("why"),
                     json.dumps(c.get("evidence") or {}), rank))
        if cur.rowcount:
            added += 1
            rank += 1
    return added


def start(cur: Cursor, folder_id: str, *, trigger: str = "tap", now: Optional[datetime] = None) -> Dict[str, Any]:
    """A scout run for a described track: finders 1 and 2 now (no request), the `scout` question asked. KeyError: no
    track; ValueError: not a topic (no description)."""
    from insight_core.markx import tracks
    track = tracks.get(cur, folder_id)
    if track is None:
        raise KeyError(folder_id)
    if not tracks.is_topic(track):
        raise ValueError("Describe the track first: the scout looks for what its description asks for")
    cur.execute("""INSERT INTO mx_scout_runs (track_id, version, trigger, started_at) VALUES (%s, %s, %s, %s)
                   RETURNING id::text""", (track["folder_id"], track["version"], trigger, now or _now()))
    run_id = cur.fetchone()[0]
    skip = answered_not(cur, track["folder_id"])
    followed = _followed(cur)
    pos = in_posts(cur, track["folder_id"])
    makers = maker_candidates(cur, track["folder_id"], skip=skip, posts=pos)
    match = match_candidates(cur, track["folder_id"], skip=skip, posts=pos)
    shapes = shape_candidates(track_terms(cur, track, pos), item_names(cur, pos), x_bridge=_x_bridge())
    counts = {"maker": add_candidates(cur, run_id, makers, track_id=track["folder_id"], followed=followed),
              "match": add_candidates(cur, run_id, match, track_id=track["folder_id"], followed=followed),
              "shape": add_candidates(cur, run_id, shapes, track_id=track["folder_id"], followed=followed)}
    task_id, new = ask(cur, track, run_id)
    if not new:   # the same question answered before: its sources at once (no second call)
        got = tracks._answered_verdict(cur, task_id)
        if got:
            counts["haiku"] = add_candidates(cur, run_id, haiku_candidates(got[1]), track_id=track["folder_id"],
                                             followed=followed)
    web_id, new = web_ask(cur, track, run_id, now or _now())
    if not new:   # this week's search answered before (another run of the track): its results at once
        got = tracks._answered_verdict(cur, web_id)
        if got:
            counts["web"] = add_candidates(cur, run_id, web_candidates(got[1], _platforms(cur)),
                                           track_id=track["folder_id"], followed=followed)
    _stats(cur, run_id, candidates=counts)
    log.info("Scout run %s for track %s (%s): candidates %s", run_id, folder_id, trigger, counts)
    return {"id": run_id, "candidates": counts}


def _stats(cur: Cursor, run_id: str, **more: Any) -> None:
    cur.execute("UPDATE mx_scout_runs SET stats = stats || %s::jsonb WHERE id = %s", (json.dumps(more, default=str), run_id))


def due_weekly(cur: Cursor, now: Optional[datetime] = None) -> List[str]:
    """The described tracks with no scout in the last WEEK, those with fewer than WEEKLY_MIN items in or ✓ in 7 days
    (starving) first, then the longest unscouted."""
    from insight_core.markx import tracks
    now = now or _now()
    out = []
    for t in tracks.described(cur):
        if t.get("parent_id"):   # v10.42: a sub-track's posts are its parent's; it finds no sources
            continue
        cur.execute("SELECT max(started_at) FROM mx_scout_runs WHERE track_id = %s", (t["folder_id"],))
        last = cur.fetchone()[0]
        if last is not None and last > now - WEEK:
            continue
        starving = len(in_posts(cur, t["folder_id"], limit=WEEKLY_MIN, since=now - WEEK)) < WEEKLY_MIN
        out.append((not starving, last or datetime.min.replace(tzinfo=timezone.utc), t["folder_id"]))
    return [folder_id for *_, folder_id in sorted(out)]


def weekly_open(cur: Cursor, now: datetime) -> bool:
    """Whether a weekly run started in the last WEEK is still open (running or waiting): the next track's waits for it
    (an older one never holds the others)."""
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_scout_runs WHERE trigger = 'weekly' AND status IN ('running', 'waiting')
                                     AND started_at > %s)""", (now - WEEK,))
    return bool(cur.fetchone()[0])


def claim(cur: Cursor, run_id: str, now: datetime) -> bool:
    cur.execute("""UPDATE mx_scout_runs SET busy_until = %s WHERE id = %s AND status IN ('running', 'waiting')
                     AND (busy_until IS NULL OR busy_until < %s)""", (now + CLAIM, run_id, now))
    return cur.rowcount == 1


def asking(cur: Cursor, run_id: str) -> set:
    """The finders whose question is still open (ASKED): haiku while the `scout` task is, web while the web search is."""
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.id = r.scout_task_id AND t.status IN ('open', 'leased')),
                          EXISTS (SELECT 1 FROM mx_tasks t WHERE t.id::text = r.stats->>'web_task_id'
                                     AND t.status IN ('open', 'leased'))
                     FROM mx_scout_runs r WHERE r.id = %s""", (run_id,))
    row = cur.fetchone() or (False, False)
    return {f for f, open_ in zip(ASKED, row) if open_}


def to_read(cur: Cursor, run_id: str) -> List[Dict[str, Any]]:
    """The run's candidates to read next, within what is left of MAX_READS: each finder's share first, in its rank,
    then the rest refilled in finder order, but never into the share held for a finder whose question is still open
    (its candidates are not in yet: `asking`)."""
    cur.execute("SELECT reads, requests FROM mx_scout_runs WHERE id = %s", (run_id,))
    reads, requests = cur.fetchone()
    left = MAX_READS - reads
    if left <= 0 or requests >= MAX_REQUESTS:
        return []
    cur.execute("SELECT finder, count(*) FROM mx_scout_candidates WHERE run_id = %s AND state <> 'new' GROUP BY 1",
                (run_id,))
    done = dict(cur.fetchall())
    cur.execute("""SELECT id::text, finder, platform, address, key, name, evidence FROM mx_scout_candidates
                    WHERE run_id = %s AND state = 'new' ORDER BY rank""", (run_id,))
    rows = [dict(zip(("id", "finder", "platform", "address", "key", "name", "evidence"), r)) for r in cur.fetchall()]
    picked: List[Dict[str, Any]] = []
    for finder in FINDER_ORDER:
        share = max(0, READ_SHARE.get(finder, 0) - done.get(finder, 0))
        picked += [r for r in rows if r["finder"] == finder][:share]
    picked = picked[:left]
    chosen = {r["id"] for r in picked}
    held = sum(max(0, READ_SHARE.get(f, 0) - done.get(f, 0)) for f in asking(cur, run_id))
    rest = sorted((r for r in rows if r["id"] not in chosen), key=lambda r: FINDER_ORDER.index(r["finder"])
                  if r["finder"] in FINDER_ORDER else 9)
    return picked + rest[:max(0, left - len(picked) - held)]


def store_read(cur: Cursor, cand: Dict[str, Any], got: scout_reads.ReadResult, now: datetime) -> Dict[str, Any]:
    """A test read's outcome on its candidate, its items into the scratch area."""
    h = scout_reads.health(got.items, now) if got.resolved else None
    state = "read" if got.resolved else "unreadable"
    reason = got.reason if not got.resolved else (h["reason"] if h and not h["reads_well"] else None)
    cur.execute("""UPDATE mx_scout_candidates SET state = %s, resolved = %s::jsonb, reason = %s, health = %s::jsonb,
                          requests = %s, read_at = %s WHERE id = %s""",
                (state, json.dumps(got.resolved) if got.resolved else None, reason,
                 json.dumps(h, default=str) if h else None, got.requests, now, cand["id"]))
    for it in got.items:
        cur.execute("""INSERT INTO mx_scout_items (candidate_id, url, title, text, published_at, lang, chars, transcript)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (candidate_id, url) DO NOTHING""",
                    (cand["id"], it["url"], it["title"], it["text"], it["published_at"], it["lang"], it["chars"],
                     it["transcript"]))
    cur.execute("UPDATE mx_scout_runs SET reads = reads + 1, requests = requests + %s WHERE id = %s",
                (got.requests, cand["run_id"]))
    return {"state": state, "reason": reason, "items": len(got.items)}


def judge_items(cur: Cursor, run_id: str, track: Dict[str, Any], head: Optional[str] = None) -> int:
    """The track judge's questions on the run's read items that have none, within MAX_JUDGEMENTS: how many were
    asked (an identical question answered before fills its verdict at once)."""
    from insight_core.markx import tracks
    from insight_core.utils.post_links import source_kind
    cur.execute("SELECT judgements FROM mx_scout_runs WHERE id = %s", (run_id,))
    left = MAX_JUDGEMENTS - cur.fetchone()[0]
    if left <= 0:
        return 0
    cur.execute("""SELECT i.id::text, i.url, i.title, i.text, i.published_at, c.name, c.key, c.resolved
                     FROM mx_scout_items i JOIN mx_scout_candidates c ON c.id = i.candidate_id
                    WHERE c.run_id = %s AND i.task_id IS NULL AND c.state = 'read'
                      AND COALESCE((c.health->>'reads_well')::boolean, false)
                    ORDER BY c.rank, i.published_at DESC NULLS LAST LIMIT %s""", (run_id, left))
    rows = cur.fetchall()
    if not rows:
        return 0
    schemas.ensure_guides(cur)
    head = head if head is not None else tracks.header(cur, track)
    asked = 0
    for iid, url, title, text, at, name, key, resolved in rows:
        r = resolved or {}
        p = tasks.Post(id=iid, kind=source_kind(r.get("platform"), r.get("handle_or_url")), source=name or key,
                       source_id="", at=at or _now(), title=re.sub(r"\s+", " ", title or "").strip(),
                       text=(text or "")[:TEXT_CHARS], links=[(url, None)])
        task_id, new = repo.add_task(cur, kind=JUDGE, guide=schemas.KINDS[JUDGE].guide, subject_kind="scout_item",
                                     input=tracks.track_input(head, p), a=iid, b=track["folder_id"],
                                     priority=JUDGE_PRIORITY)
        cur.execute("UPDATE mx_scout_items SET task_id = %s WHERE id = %s", (task_id, iid))
        asked += 1
        if not new:
            got = tracks._answered_verdict(cur, task_id)
            if got:
                after_judge(cur, {"id": task_id}, got[1])
    cur.execute("UPDATE mx_scout_runs SET judgements = judgements + %s WHERE id = %s", (asked, run_id))
    return asked


def after_judge(cur: Cursor, task: Dict[str, Any], answer: Dict[str, Any]) -> int:
    """A track verdict copied to the scratch items asking it."""
    cur.execute("""UPDATE mx_scout_items SET verdict = %s, confidence = %s, why = %s
                    WHERE task_id = %s AND verdict IS NULL""",
                (bool(answer.get("in")), float(answer.get("confidence") or 0),
                 (answer.get("why") or "")[:schemas.TRACK_WHY_CHARS] or None, task["id"]))
    return cur.rowcount


def settle(cur: Cursor, run_id: str, now: datetime) -> str:
    """The run's status from what is left: running (candidates to read within the budget), waiting (the scout
    question, the web search or judgements unanswered), done."""
    if to_read(cur, run_id):
        status = "running"
    else:
        cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_scout_items i JOIN mx_scout_candidates c ON c.id = i.candidate_id
                                        JOIN mx_tasks t ON t.id = i.task_id
                                       WHERE c.run_id = %(r)s AND t.status IN ('open', 'leased'))""", {"r": run_id})
        status = "waiting" if cur.fetchone()[0] or asking(cur, run_id) else "done"
    if status != "done":
        cur.execute("SELECT trigger, started_at FROM mx_scout_runs WHERE id = %s", (run_id,))
        trigger, started = cur.fetchone()
        if trigger != "research" and started is not None and started < now - STALL:
            # its questions or reads never came: closed, so the next weekly run of another track can start
            _stats(cur, run_id, closed=f"stalled: still {status} {STALL.days} days after it started")
            status = "done"
    cur.execute("""UPDATE mx_scout_runs SET status = %s, busy_until = NULL,
                          finished_at = CASE WHEN %s = 'done' THEN COALESCE(finished_at, %s) ELSE NULL END
                    WHERE id = %s""", (status, status, now, run_id))
    return status


def reads_allowed() -> bool:
    from insight_core.services.discover_reads import enabled
    return enabled()


def default_reader() -> scout_reads.Reader:
    """The server's fetcher: the Add source dialog's short-timeout client and the API's kinds, one host at a time."""
    from insight_core.ingestion.gates import HostLimiter
    from insight_core.ingestion.http import KindHttp
    from insight_core.services.registry import services
    return scout_reads.Reader(KindHttp(timeout=8), services().source_fetch.kinds, limiter=HostLimiter())


async def advance(db_url: str, run_id: str, *, reader: Optional[Any] = None, now: Optional[Callable[[], datetime]] = None,
                  on_read: Optional[Callable[[Any, Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Advance one run as far as it can go now: read its candidates (within the budget), ask the judge about what
    was read, settle its status. Claimed first (another advancing it: nothing done). Never raises for a site's
    failure. `on_read(cur, candidate)`: a research run's hook after each read."""
    from insight_core.db import database
    from insight_core.markx import tracks
    clock = now or _now
    with database.transaction(db_url) as cur:
        if not claim(cur, run_id, clock()):
            return {"run": run_id, "claimed": False}
        cur.execute("SELECT track_id::text FROM mx_scout_runs WHERE id = %s", (run_id,))
        track_id = cur.fetchone()[0]
    read = 0
    try:
        if reads_allowed():
            reader = reader or default_reader()
            while True:
                with database.transaction(db_url) as cur:
                    cands = to_read(cur, run_id)   # empty once MAX_READS or MAX_REQUESTS is spent
                if not cands:
                    break
                cand = dict(cands[0], run_id=run_id)
                linked = list((cand.get("evidence") or {}).get("linked") or [])
                got = await reader.read(cand["address"], linked=linked)
                with database.transaction(db_url) as cur:
                    store_read(cur, cand, got, clock())
                    if on_read is not None:
                        on_read(cur, cand)
                read += 1
    finally:
        with database.transaction(db_url) as cur:
            asked = 0
            track = tracks.get(cur, track_id) if track_id else None
            if track is not None and tracks.is_topic(track):
                asked = judge_items(cur, run_id, track)
            status = settle(cur, run_id, clock())
            cur.execute("SELECT reads, requests, judgements FROM mx_scout_runs WHERE id = %s", (run_id,))
            reads, requests, judgements = cur.fetchone()
            _stats(cur, run_id, spent={"reads": reads, "requests": requests, "judgements": judgements})
    log.info("Scout run %s: %d read now, %d judgements asked, %s (spent: %d reads, %d requests, %d judgements)",
             run_id, read, asked, status, reads, requests, judgements)
    return {"run": run_id, "claimed": True, "read": read, "asked": asked, "status": status}


def open_runs(cur: Cursor, *, trigger: Optional[str] = None) -> List[str]:
    cur.execute("""SELECT id::text FROM mx_scout_runs WHERE status IN ('running', 'waiting')
                     AND (%s::text IS NULL OR trigger = %s) ORDER BY started_at""", (trigger, trigger))
    return [r for (r,) in cur.fetchall()]


def _track_run(cur: Cursor, run_id: str) -> bool:
    """A track's run (a research run is advanced and settled by research.tick)."""
    cur.execute("SELECT trigger <> 'research' FROM mx_scout_runs WHERE id = %s", (run_id,))
    row = cur.fetchone()
    return bool(row and row[0])


def needs_advance(cur: Cursor, run_id: str) -> bool:
    """A run with candidates to read, or read items not yet asked about (a judge question to plan)."""
    if to_read(cur, run_id):
        return True
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_scout_items i JOIN mx_scout_candidates c ON c.id = i.candidate_id
                                   WHERE c.run_id = %s AND i.task_id IS NULL AND c.state = 'read'
                                     AND COALESCE((c.health->>'reads_well')::boolean, false))""", (run_id,))
    return bool(cur.fetchone()[0])


async def tick(db_url: str, *, reader: Optional[Any] = None, now: Optional[Callable[[], datetime]] = None
               ) -> Dict[str, Any]:
    """insight-ingestion's hook: every open track run with nothing to read settled (done once its questions are
    answered, closed once stalled), the weekly scouts started, then every open track run with work advanced (a
    research run is advanced by research.tick). Never raises."""
    from insight_core.db import database
    from insight_core.markx.api import enabled
    if not enabled():
        return {}
    clock = now or _now
    out: Dict[str, Any] = {"settled": {}, "started": [], "advanced": []}
    try:
        with database.transaction(db_url) as cur:
            # an open run with nothing to read waits on its questions only: settled here (done once they are
            # answered, or closed as stalled), as nothing else would settle it (advance is for runs with work)
            for run_id in open_runs(cur):
                if not needs_advance(cur, run_id) and _track_run(cur, run_id) and claim(cur, run_id, clock()):
                    out["settled"][run_id] = settle(cur, run_id, clock())
        with database.transaction(db_url) as cur:
            due = [] if weekly_open(cur, clock()) else due_weekly(cur, clock())   # one weekly run at a time
            for folder_id in due[:1]:
                out["started"].append(start(cur, folder_id, trigger="weekly", now=clock())["id"])
        with database.transaction(db_url) as cur:
            runs = [r for r in open_runs(cur) if _track_run(cur, r) and needs_advance(cur, r)]
        for run_id in runs:
            out["advanced"].append(await advance(db_url, run_id, reader=reader, now=now))
    except Exception:  # noqa: BLE001 - the scheduler's run stands
        log.exception("Scout: the tick failed")
    return out


# ---- what the owner sees ----------------------------------------------------------------------------------------

def _candidate_rows(cur: Cursor, where: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    cur.execute(f"""SELECT c.id::text, c.run_id::text, c.finder, c.platform, c.address, c.key, c.name, c.why, c.state,
                           c.resolved, c.reason, c.health, c.answer, c.source_id::text, c.read_at, r.track_id::text,
                           (SELECT count(*) FROM mx_scout_items i WHERE i.candidate_id = c.id),
                           (SELECT count(*) FROM mx_scout_items i WHERE i.candidate_id = c.id AND i.verdict IS NOT NULL),
                           (SELECT count(*) FROM mx_scout_items i WHERE i.candidate_id = c.id AND i.verdict),
                           r.started_at
                      FROM mx_scout_candidates c JOIN mx_scout_runs r ON r.id = c.run_id
                     WHERE {where}""", params)
    cols = ("id", "run_id", "finder", "platform", "address", "key", "name", "why", "state", "resolved", "reason",
            "health", "answer", "source_id", "read_at", "track_id", "items", "judged", "fits", "run_at")
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def row_view(c: Dict[str, Any]) -> Dict[str, Any]:
    h = c.get("health") or {}
    precision = (c["fits"] / c["judged"]) if c.get("judged") else None
    if c["state"] == "new":
        place = "unread"
    elif c["state"] != "read":
        place = "unreadable"
    elif not h.get("reads_well"):
        place = "reads_badly"
    elif c["judged"] < min(MIN_JUDGED, max(c["items"], 1)):
        place = "judging"
    elif precision is not None and precision >= FLOOR and c["judged"] >= min(MIN_JUDGED, c["items"]):
        place = "suggested"
    else:
        place = "below_floor"
    resolved = c.get("resolved") or {}
    return {"id": c["id"], "run_id": c["run_id"], "track": c.get("track_id"), "finder": c["finder"],
            "platform": c["platform"], "address": c["address"], "key": c["key"], "name": c.get("name") or c["key"],
            "why": c.get("why"), "place": place, "reason": c.get("reason"), "items": c["items"], "judged": c["judged"],
            "fits": c["fits"], "precision": round(precision, 3) if precision is not None else None,
            "per_week": h.get("per_week"), "cadence": scout_reads.cadence_words(h.get("per_week")),
            "labels": h.get("labels") or [], "reads_well": bool(h.get("reads_well")),
            "follows_as": resolved.get("via"), "follow_address": resolved.get("handle_or_url"),
            "answer": c.get("answer"), "source_id": c.get("source_id")}


def _latest_per_key(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The newest run's row of each key (a key read again by a later scout replaces the older read)."""
    rows = sorted(rows, key=lambda c: (c["run_at"], c["read_at"] or c["run_at"]), reverse=True)
    seen, out = set(), []
    for c in rows:
        if c["key"] in seen:
            continue
        seen.add(c["key"])
        out.append(c)
    return out


def suggestions(cur: Cursor, folder_id: Optional[str] = None) -> Dict[str, Any]:
    """{suggested: [...ranked], reads_badly: [...], unreadable: [...], judging: [...], unread: n}: the latest read of each candidate key of
    the track's scouts (or every track's), not answered yet."""
    where, params = "r.track_id IS NOT NULL AND r.trigger <> 'research'", []
    if folder_id is not None:
        where += " AND r.track_id = %s"
        params.append(folder_id)
    answered = set()
    cur.execute(f"""SELECT r.track_id::text, c.key FROM mx_scout_candidates c JOIN mx_scout_runs r ON r.id = c.run_id
                     WHERE {where} AND c.answer IS NOT NULL""", params)
    answered = set(cur.fetchall())
    rows = [row_view(c) for c in _by_track_latest(_candidate_rows(cur, where + " AND c.answer IS NULL", params))
            if (c["track_id"], c["key"]) not in answered]
    sug = sorted((r for r in rows if r["place"] == "suggested"),
                 key=lambda r: (-(r["precision"] or 0), -(r["per_week"] or 0), r["name"]))
    return {"suggested": sug,
            "reads_badly": [r for r in rows if r["place"] == "reads_badly"],
            "unreadable": [r for r in rows if r["place"] == "unreadable"],
            "judging": [r for r in rows if r["place"] == "judging"],
            "unread": sum(1 for r in rows if r["place"] == "unread")}


def _by_track_latest(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in rows:
        groups[c["track_id"]].append(c)
    return [c for g in groups.values() for c in _latest_per_key(g)]


def followed(cur: Cursor, folder_id: str) -> List[Dict[str, Any]]:
    """The sources a scout of this track brought, each with its precision in the track since it was followed."""
    cur.execute("""SELECT DISTINCT ON (p.source_id) p.source_id::text, p.as_active, p.created_at,
                          COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url)
                     FROM mx_source_provenance p JOIN sources s ON s.id = p.source_id
                    WHERE p.track_id = %s AND p.kind = 'scout' ORDER BY p.source_id, p.created_at""", (folder_id,))
    out = []
    for sid, active, at, name in cur.fetchall():
        cur.execute(f"""SELECT count(*) FILTER (WHERE i.verdict IS NOT NULL), count(*) FILTER (WHERE i.verdict)
                          FROM mx_track_items i JOIN posts p ON p.id = i.post_id
                         WHERE i.track_id = %s AND p.source_id = %s AND {pairing.ordinary_date('p')} >= %s""",
                    (folder_id, sid, at))
        judged, fits = cur.fetchone()
        out.append({"source_id": sid, "name": name, "as": "active" if active else "passive", "since": _iso(at),
                    "judged": judged, "fits": fits, "precision": round(fits / judged, 3) if judged else None})
    return out


def runs(cur: Cursor, folder_id: str, limit: int = 5) -> List[Dict[str, Any]]:
    cur.execute("""SELECT r.id::text, r.trigger, r.status, r.reads, r.requests, r.judgements, r.stats, r.started_at,
                          r.finished_at, t.status
                     FROM mx_scout_runs r LEFT JOIN mx_tasks t ON t.id = r.scout_task_id
                    WHERE r.track_id = %s ORDER BY r.started_at DESC LIMIT %s""", (folder_id, limit))
    out = []
    for rid, trig, status, reads, requests, judgements, stats, started, finished, ask_status in cur.fetchall():
        cur.execute("""SELECT finder, count(*), count(*) FILTER (WHERE state = 'read'),
                              count(*) FILTER (WHERE COALESCE((health->>'reads_well')::boolean, false))
                         FROM mx_scout_candidates WHERE run_id = %s GROUP BY finder""", (rid,))
        finders = {f: {"candidates": n, "read": r, "read_well": w} for f, n, r, w in cur.fetchall()}
        out.append({"id": rid, "trigger": trig, "status": status, "reads": reads, "requests": requests,
                    "judgements": judgements, "asked": ask_status, "finders": finders,
                    "started_at": _iso(started), "finished_at": _iso(finished)})
    return out


def page(cur: Cursor, folder_id: str) -> Dict[str, Any]:
    """The Topic view's "Sources for this track" block."""
    return {**suggestions(cur, folder_id), "followed": followed(cur, folder_id), "runs": runs(cur, folder_id),
            "floor": FLOOR, "budget": {"reads": MAX_READS, "judgements": MAX_JUDGEMENTS, "requests": MAX_REQUESTS}}


# ---- what the scout brought ------------------------------------------------------------------------------------

COVER_DAYS = 14                   # another source's post this near (either side) covers a scout source's post
VALUE_EXAMPLES = 5


def _kept(cur: Cursor, track_id: str, post_ids: Sequence[str]) -> set:
    """The posts the track kept: the owner's ✓, else the judge's in (the owner's ✗ wins), as in_posts reads them."""
    from insight_core.markx import tracks
    if not post_ids:
        return set()
    labels = tracks.labels(cur, track_id)
    cur.execute("SELECT DISTINCT post_id::text FROM mx_track_items WHERE track_id = %s AND verdict "
                "AND post_id = ANY(%s::uuid[])", (track_id, list(post_ids)))
    judged = {p for (p,) in cur.fetchall()}
    return {p for p in post_ids if labels.get(p, ("",))[0] == "in" or (p in judged and labels.get(p, ("",))[0] != "out")}


def _thing_mates(cur: Cursor, track_id: str) -> Callable[[str], set]:
    """post -> the posts reporting the same thing of the track (track_things' identity: a thing's current root)."""
    from insight_core.markx import track_things
    root = track_things.roots(cur, track_id)
    if not root:
        return lambda _p: set()
    cur.execute("""SELECT r.post_id::text, r.thing_id::text FROM mx_track_thing_reports r
                     JOIN mx_track_things t ON t.id = r.thing_id WHERE t.track_id = %s""", (track_id,))
    by_post: Dict[str, set] = defaultdict(set)
    by_root: Dict[str, set] = defaultdict(set)
    for pid, thing in cur.fetchall():
        r = root.get(thing, thing)
        by_post[pid].add(r)
        by_root[r].add(pid)
    return lambda p: {q for r in by_post.get(p, ()) for q in by_root[r]} - {p}


def home_or_profile(url: str) -> bool:
    """A site's root (page_watch.is_home) or a person's account page itself (discover_people.person_key's key with
    nothing after it): two posts linking it share who, not what."""
    from insight_core.ingestion.kinds import page_watch
    from insight_core.markx.discover_people import person_key
    try:
        if page_watch.is_home(url):
            return True
    except ValueError:
        return True
    got = person_key(url)
    return bool(got) and url.split("://", 1)[-1].lower().removeprefix("www.").strip("/") == got[0]


def covering(cur: Cursor, post: Dict[str, Any], things: Callable[[str], set]) -> set:
    """The posts that cover the same thing as `post` (any source), each by an existing module's test: the same story
    (StoriesRepository.story_mates), the post's own address (at_addresses) or a link to it (linking_posts), a kept
    link to the same page that is no home nor profile (`home_or_profile`: it says who, not what), the same thing of
    the track (track_things' roots)."""
    from insight_core.db.repo_stories import StoriesRepository as R
    pid = post["id"]
    out = R.story_mates(cur, [pid])
    urls = [u for u in {post.get("url"), post.get("normalized_url")} if u]
    if urls:
        out |= R.at_addresses(cur, urls) | set(R.linking_posts(cur, urls))
    cur.execute("SELECT DISTINCT target_url FROM post_links WHERE post_id = %s AND NOT boilerplate AND kind = 'link'",
                (pid,))
    targets = [u for (u,) in cur.fetchall() if u and not home_or_profile(u)]
    if targets:
        out |= set(R.linking_posts(cur, targets))
    out |= things(pid)
    return out - {pid}


def _median(xs: Sequence[float]) -> Optional[float]:
    import statistics
    return round(statistics.median(xs), 1) if xs else None


def value(cur: Cursor, track_id: Optional[str] = None, days: Optional[int] = 30,
          now: Optional[datetime] = None) -> Dict[str, Any]:
    """What the sources followed from a scout's (or research's) suggestion brought each track since they were
    followed (within the last `days`): `posts`, `in` (the track kept), `unique` (in, and no post of a source the
    scouts did not bring covers it within COVER_DAYS: `covering`), `covered`, `first` (covered, the scout's source
    first), `lead_hours` (the median hours it came before the first other source's covering post, over `first`),
    `examples` (unique ones). The follow date is mx_source_provenance.created_at (the source's created_at when
    absent). Totals per track and overall. Read only."""
    from insight_core.markx import tracks
    now = now or _now()
    cur.execute(f"""SELECT DISTINCT ON (v.source_id, v.track_id) v.source_id::text, v.track_id::text, v.kind,
                           COALESCE(v.created_at, s.created_at),
                           COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url)
                      FROM mx_source_provenance v JOIN sources s ON s.id = v.source_id
                     WHERE v.track_id IS NOT NULL AND (%s::uuid IS NULL OR v.track_id = %s::uuid)
                     ORDER BY v.source_id, v.track_id, v.created_at""", (track_id, track_id))
    follows = cur.fetchall()
    cur.execute("SELECT DISTINCT source_id::text FROM mx_source_provenance")
    brought = [r for (r,) in cur.fetchall()]
    window = timedelta(days=COVER_DAYS)
    date = pairing.ordinary_date("p")
    sources, by_track = [], defaultdict(list)
    thing_mates: Dict[str, Callable[[str], set]] = {}
    for sid, tid, kind, followed_at, name in follows:
        since = max(followed_at, now - timedelta(days=days)) if days else followed_at
        cur.execute(f"""SELECT p.id::text, p.title, p.url, p.normalized_url, {date} FROM posts p
                         WHERE p.source_id = %s AND {date} >= %s ORDER BY {date}""", (sid, since))
        posts = [dict(zip(("id", "title", "url", "normalized_url", "at"), r)) for r in cur.fetchall()]
        kept = _kept(cur, tid, [p["id"] for p in posts])
        if tid not in thing_mates:
            thing_mates[tid] = _thing_mates(cur, tid)
        unique, leads, covered, first = [], [], 0, 0
        for p in posts:
            if p["id"] not in kept:
                continue
            mates = covering(cur, p, thing_mates[tid])
            earliest = None
            if mates and p["at"] is not None:
                cur.execute(f"""SELECT min({date}) FROM posts p WHERE p.id = ANY(%s::uuid[])
                                   AND p.source_id <> ALL(%s::uuid[]) AND {date} BETWEEN %s AND %s""",
                            (list(mates), brought, p["at"] - window, p["at"] + window))
                earliest = cur.fetchone()[0]
            if earliest is None:
                unique.append(p)
                continue
            covered += 1
            if earliest > p["at"]:
                first += 1
                leads.append((earliest - p["at"]).total_seconds() / 3600)
        row = {"source_id": sid, "name": name, "track": tid, "via": kind, "followed_at": _iso(followed_at),
               "since": _iso(since), "posts": len(posts), "in": len(kept), "unique": len(unique), "covered": covered,
               "first": first, "lead_hours": _median(leads),
               "examples": [{"title": p["title"], "url": p["url"]} for p in unique[-VALUE_EXAMPLES:][::-1]]}
        sources.append(row)
        by_track[tid].append((row, leads))

    def total(rows: Sequence[Tuple[Dict[str, Any], List[float]]]) -> Dict[str, Any]:
        out = {k: sum(r[k] for r, _ in rows) for k in ("posts", "in", "unique", "covered", "first")}
        out["sources"] = len(rows)
        out["lead_hours"] = _median([h for _, ls in rows for h in ls])
        return out
    names = {t["folder_id"]: t["name"] for t in tracks.described(cur)}
    return {"days": days, "cover_days": COVER_DAYS, "followed_at": "mx_source_provenance.created_at",
            "sources": sources,
            "tracks": [dict(total(rows), track=tid, name=names.get(tid, "")) for tid, rows in by_track.items()],
            "total": total([x for rows in by_track.values() for x in rows])}


# ---- the owner's answers ---------------------------------------------------------------------------------------

AddSource = Callable[[str, str, Dict[str, Any]], str]


def default_add_source(platform: str, handle: str, settings: Dict[str, Any]) -> str:
    """POST /api/sources' own path (SourcesService.add_with_settings, then the sources.json export): the source's id.
    A source already there is that source."""
    from insight_core.services.registry import services
    try:
        created = services().sources.add_with_settings(platform, handle, settings=settings, enabled=True)
    except ValueError:
        from insight_core.db import database
        with database.transaction(services().db_url) as cur:
            cur.execute("SELECT id::text FROM sources WHERE handle_or_url = %s", (handle,))
            row = cur.fetchone()
        if row is None:
            raise
        return row[0]
    try:
        services().source_config_sync.sync_db_to_json()
    except Exception:  # noqa: BLE001 - the database is the truth
        log.exception("Could not export sources.json")
    return str(created["source_id"])


def candidate(cur: Cursor, candidate_id: str) -> Optional[Dict[str, Any]]:
    got = _candidate_rows(cur, "c.id = %s", (candidate_id,))
    return got[0] if got else None


def follow(cur: Cursor, candidate_id: str, as_: str, *, add_source: Optional[AddSource] = None,
           folder_id: Optional[str] = None, kind: str = "scout") -> Dict[str, Any]:
    """The owner's Follow as active / passive: the address the add path resolved at the test read added as a source
    (active: into the track's folder), its provenance kept. KeyError: no candidate; ValueError: it can't be read."""
    from insight_core.db.repo_folders import FoldersRepository
    if as_ not in ("active", "passive"):
        raise ValueError("as: active or passive")
    c = candidate(cur, candidate_id)
    if c is None:
        raise KeyError(candidate_id)
    r = c.get("resolved") or {}
    if c["state"] != "read" or not r.get("handle_or_url"):
        raise ValueError("This one could not be read: there is nothing to follow")
    settings: Dict[str, Any] = dict(r.get("settings") or {})
    name = (c.get("name") or r.get("title") or "").strip()
    if name:
        settings.setdefault("display_name", name[:120])
    source_id = (add_source or default_add_source)(r.get("platform") or "rss", r["handle_or_url"], settings)
    folder = folder_id or c.get("track_id")
    if as_ == "active" and folder:
        FoldersRepository("").add_source_to_folder(cur, folder, source_id)
    cur.execute("""UPDATE mx_scout_candidates SET answer = %s, answered_at = now(), source_id = %s WHERE id = %s""",
                (as_, source_id, candidate_id))
    cur.execute("""INSERT INTO mx_source_provenance (source_id, kind, run_id, candidate_id, track_id, as_active)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (source_id, kind, c["run_id"], candidate_id, folder, as_ == "active"))
    return {"source_id": source_id, "as": as_}


def not_this(cur: Cursor, candidate_id: str) -> Dict[str, Any]:
    cur.execute("UPDATE mx_scout_candidates SET answer = 'not', answered_at = now() WHERE id = %s", (candidate_id,))
    if not cur.rowcount:
        raise KeyError(candidate_id)
    return {"answer": "not"}


__all__ = ["add_candidates", "advance", "after_answer", "after_judge", "due_weekly", "weekly_open", "follow", "haiku_candidates",
           "judge_items", "maker_candidates", "match_candidates", "not_this", "own_address", "page", "shape_candidates",
           "source_link", "start", "suggestions", "tick", "after_websearch", "value", "web_candidates"]


def with_scouts(hook: Optional[Callable[[], Awaitable[Any]]], db_url: str) -> Callable[[], Awaitable[Any]]:
    """insight-ingestion's after-the-story-job hook (markx/jobs.Jobs.after_stories), then the scouts' tick (the weekly
    scouts, the open runs advanced) and the research runs'. Each guarded: none fails the others or the run."""
    async def run() -> Any:
        out = None
        if hook is not None:
            out = await hook()
        try:
            await tick(db_url)
            from insight_core.markx import research
            await research.tick(db_url)
        except Exception:  # noqa: BLE001 - the scheduler's run stands
            log.exception("Scout and research ticks failed")
        return out
    return run
