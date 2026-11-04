"""Discover (issues 0050, 0065, 0067): the sites and accounts your sources keep linking, and where
your stories start. Pure functions over plain data; db/repo_discover.py counts the links in SQL by
these rules (`suggestions` is its reference) and services/stories_service.py ranks what it finds.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Set, Tuple

from insight_core.utils.addresses import PLATFORM_SITES, account_key, bare, publication_of, site_of, x_account
from insight_core.utils.post_links import LANGUAGE, NUMBERISH, is_article, section_of
from insight_core.utils.stamps import ADDRESSES, fingerprint
from insight_core.utils.story_rules import ROUNDUP_ANCHORS, StoryPost, anchors
from insight_core.utils.url_normalization import TWEET_PATH

DISCOVER_MIN_VOICES = 3        # the prototype's, not measured (the prototype: plan/research/dedup-prototype)
DISCOVER_MIN_ARTICLES = 2      # the prototype's, not measured
DISCOVER_ARTICLE_SHARE = 0.4   # the prototype's, not measured
# The sites where INSIGHT follows one account, not the whole site: its source kinds (Reddit, X,
# Telegram, YouTube) and the feed finder's platform feeds (GitHub, Medium). Measured on the
# server's data, 2026-10-30: a test by "8+ first path segments" called 249 hosts platforms, split
# publishers by year or section (nytimes.com/2026) and hid blogs whose posts sit at the root.
DISCOVER_PLATFORMS = frozenset(set().union(*(PLATFORM_SITES[k] for k in ("reddit", "x", "telegram", "youtube")))
                               | {"github.com", "medium.com"})
# First path segments of a platform that name a kind of page, not an account.
NOT_ACCOUNT = frozenset({"status", "watch", "pull", "issues", "i", "p", "s", "search", "hashtag", "intent",
                         "share", "home", "explore", "wiki", "posts", "in"})
# A post of a platform account is one of its articles (issue 0065). A tweet by its shape, on any host
# (x.com, a Nitter, xcancel.com, fxtwitter.com: the forms 0066 gives one address), is the account's;
# elsewhere on a platform, /<account>/<number> (a Telegram post, t.me/<channel>/<id>).
TWEET = TWEET_PATH
PLATFORM_POST = re.compile(r"^/[^/?#]+/\d+(?:[?#]|$)")
ORIGIN_MIN_VOICES = 2      # the stories whose origins Discover counts: 2+ voices, the ones 0064 counted; not measured

# ---- platforms from the data (issue 0080, measured on a copy of the lab: plan/research/0080-measure) ----
# A host is a platform when the pages your sources link there sit under many owners: OWNERS_MANY+
# owner segments, or OWNERS_MIN+ with none holding over OWNER_TOP_SHARE of the pages, and
# OWNER_VOICES+ owners each linked by 2+ voices. It found 10 of the lab's 1,313 hosts with 3+ voices
# (the 6 listed ones, a model hub, two social servers, a contributors' magazine); looser, it took
# publications by section. An owner is a path segment with pages beneath it, not a number, a date, a
# language, an id or a file; when one segment holds PREFIX_SHARE+ of the pages (/r/, /profile/), the
# owner is the next one, past a language too (/ru/companies/<owner>), down to the third segment
# (OWNER_DEPTH); never past two shared segments (a government site's /government/publications/<doc>).
OWNERS_MANY, OWNERS_MIN, OWNER_TOP_SHARE, OWNER_VOICES = 50, 15, 0.2, 2
PREFIX_SHARE = 0.7
OWNER_DEPTH = 3
NOT_OWNER = re.compile(r"^(v?\d[\d.\-_v]*|[a-z]{2}(-[a-z]{2,4})?|\d{4}-\d\d(-\d\d)?.*|[0-9a-f]{8,}|.*\.(html?|php|aspx?|pdf))$", re.I)
# Path segments of a data platform that name a kind of page, not an owner (hub.example/spaces/...).
NOT_OWNER_KINDS = frozenset({"spaces", "datasets", "collections", "papers", "models", "docs", "blog", "tags", "tag",
                             "topics", "topic", "search", "settings", "login", "about"}) | NOT_ACCOUNT
# A source's own names (SourceFacts.selves) shorter than this, or these words, name no one.
SELF_MIN = 3
NOT_SELF = frozenset({"www", "blog", "news", "feed", "feeds", "rss", "atom", "home", "index", "main", "posts"})

Platforms = Mapping[str, Tuple[str, ...]]   # a data platform's host -> the path its owners sit under


def path_segments(url: str) -> Tuple[str, ...]:
    """An address's path segments, lower case, its query and fragment aside."""
    _, _, rest = bare(url).partition("/")
    return tuple(seg for seg in re.split(r"[?#]", rest, maxsplit=1)[0].lower().split("/") if seg)


def _id_like(seg: str) -> bool:
    """An opaque id: 8+ letters and digits mixed, no word break (a forum's /posts/he3styo9vpk7m8zi4)."""
    return len(seg) >= 8 and bool(re.fullmatch(r"[a-z0-9]+", seg, re.I) and re.search(r"\d", seg)
                                   and re.search(r"[a-z]", seg, re.I))


def owner_segment(seg: str) -> bool:
    return not NOT_OWNER.match(seg) and not _id_like(seg)


def is_self_link(url: str, selves: Iterable[str]) -> bool:
    """A link from a source to its own page on a platform (issue 0080: a creator linking their page
    on a creators' platform): one of the first OWNER_DEPTH path segments is one of its names."""
    names = set(selves)
    return bool(names) and any(seg.lstrip("@~") in names for seg in path_segments(url)[:OWNER_DEPTH])


def platform_rows(links: Iterable[Tuple[str, str]]) -> List[Tuple[str, Tuple[str, ...], int, FrozenSet[str]]]:
    """(voice, address) links as the platform rule reads them, grouped as DiscoverRepository.platforms
    groups them in SQL: (host, its first OWNER_DEPTH segments and "*" when deeper ones follow, the
    addresses, their voices), for the hosts that aren't a listed platform, tweets aside. `links`: every
    kept link but Saved's and a self-link."""
    found: Dict[Tuple[str, Tuple[str, ...]], Tuple[Set[str], Set[str]]] = defaultdict(lambda: (set(), set()))
    for voice, url in links:
        host, _, rest = bare(url).partition("/")
        host = publication_of(host)
        if site_of(host) in DISCOVER_PLATFORMS or TWEET.match("/" + rest):
            continue
        segs = path_segments(url)
        urls, voices = found[(host, segs[:OWNER_DEPTH] + (("*",) if len(segs) > OWNER_DEPTH else ()))]
        urls.add(url)
        voices.add(voice)
    return [(host, segs, len(urls), frozenset(voices)) for (host, segs), (urls, voices) in found.items()]


def find_platforms(rows: Iterable[Tuple[str, Tuple[str, ...], int, Iterable[str]]], *,
                   min_voices: int = DISCOVER_MIN_VOICES) -> Dict[str, Tuple[str, ...]]:
    """The hosts that are platforms by the data (the rule above), each with the path its owners sit
    under. `rows`: platform_rows'."""
    by_host: Dict[str, List[Tuple[Tuple[str, ...], int, Set[str]]]] = defaultdict(list)
    for host, segs, urls, voices in rows:
        by_host[host].append((tuple(segs), int(urls), set(voices)))
    out: Dict[str, Tuple[str, ...]] = {}
    for host, paths in sorted(by_host.items()):
        if len(set().union(*(v for _, _, v in paths))) < min_voices:
            continue
        prefix: Tuple[str, ...] = ()
        stepped = False   # one step past a segment most pages share; a language one is skipped (section_of's)
        while len(prefix) < OWNER_DEPTH - 1:
            level = len(prefix)
            first: Counter = Counter()
            for segs, urls, _ in paths:
                if len(segs) > level:
                    first[segs[level]] += urls
            if not first:
                break
            top, n = first.most_common(1)[0]
            if n < PREFIX_SHARE * sum(urls for _, urls, _ in paths) or NUMBERISH.match(top) or top == "*":
                break
            if not LANGUAGE.match(top):
                if stepped:   # a second shared segment: a site's documents (/government/publications/<doc>), not owners
                    break
                stepped = True
            prefix += (top,)
            paths = [p for p in paths if p[0][:len(prefix)] == prefix]
        level = len(prefix)
        owners: Dict[str, Tuple[int, Set[str]]] = {}
        for segs, urls, voices in paths:
            if len(segs) > level + 1 and owner_segment(segs[level]):
                n, vs = owners.get(segs[level], (0, set()))
                owners[segs[level]] = (n + urls, vs | voices)
        if not owners:
            continue
        top_share = max(n for n, _ in owners.values()) / sum(n for n, _ in owners.values())
        multi = sum(1 for _, vs in owners.values() if len(vs) >= 2)
        if (len(owners) >= OWNERS_MANY or (len(owners) >= OWNERS_MIN and top_share <= OWNER_TOP_SHARE)) \
                and multi >= OWNER_VOICES:
            out[host] = prefix
    return out


def platform_key(url: str, prefix: Tuple[str, ...]) -> Optional[str]:
    """The owner an address on a data platform is under: host/<prefix>/<owner>; None for a page
    outside the prefix or one whose segment there names no owner (a kind of page, a number, an id)."""
    host = publication_of(bare(url).partition("/")[0])
    segs = path_segments(url)
    level = len(prefix)
    if segs[:level] != prefix or len(segs) <= level:
        return None
    owner = segs[level]
    if not owner_segment(owner) or owner.lstrip("@~") in NOT_OWNER_KINDS:
        return None
    return "/".join((host, *prefix, owner))


# ---- what a place is (issue 0080): references and paper sources are not sources to follow ----------
# Measured: a reference is told by its address's shape, not by its links (undated, re-linked pages are
# mostly ordinary blogs: 44 hits, none a reference; help and docs pages are linked in bursts like news).
# Government sites are no references: they publish dated press releases (they stay suggestions).
REFERENCE_HOST = re.compile(r"^(?:www\.)?(?:help|support|docs|developer)\.", re.I)
REFERENCE_PATH = frozenset({"docs", "help", "support"})
# A paper id (a preprint's yymm.nnnnn, a DOI's 10.nnnn prefix): a host whose pages hold them, and no
# owner, is a paper source; its papers stay in Classics and stories, and it is never a suggestion.
PAPER_ID = re.compile(r"^(?:\d{4}\.\d{4,5}(?:v\d+)?(?:\.pdf)?|10\.\d{4,9})$")
PLACE_SHARE = 0.6   # of a suggestion's shown pages (the measured share of reference paths)


def reference_address(url: str) -> bool:
    """A help, docs, support or developer page: a host so named, or a /docs, /help, /support path."""
    host = bare(url).partition("/")[0]
    segs = [s for s in path_segments(url)[:3] if not LANGUAGE.match(s)][:2]
    return bool(REFERENCE_HOST.match(host)) or any(s in REFERENCE_PATH for s in segs)


def paper_address(url: str) -> bool:
    return any(PAPER_ID.match(s) for s in path_segments(url)[:3])


def place_kind(key: str, urls: Iterable[str]) -> Optional[str]:
    """What a suggestion is when it is no source: "reference" (its host so named, or PLACE_SHARE of its
    shown pages reference_address), "paper" (PLACE_SHARE of them hold a paper id), else None."""
    urls = list(urls)
    if REFERENCE_HOST.match(key):
        return "reference"
    for kind, test in (("reference", reference_address), ("paper", paper_address)):
        if urls and sum(1 for u in urls if test(u)) >= PLACE_SHARE * len(urls):
            return kind
    return None


# ---- the order (issue 0080, measured on the lab and the server's answer) ------------------------------
RECENT_DAYS, LATELY_DAYS = 14, 60
FIRST_PAGE = 30   # Discover's first page; the rest behind "More"
CHECK_DAYS = 30   # a follow test, or a page's title, is read at most once in this many days


def score(*, origins: int, classics: int, opened: int, voices: int, days: Optional[float]) -> float:
    """3·ln(1+stories started) + 2·ln(1+classics) + 1.5·ln(1+posts you opened that link it) +
    ln(1+sources linking it) + 1 when one linked it in the last RECENT_DAYS days, 0.5 in LATELY_DAYS.
    Stories and classics carry it (recency is nearly flat and opens are sparse on the lab)."""
    recency = 0.0 if days is None else 1.0 if days <= RECENT_DAYS else 0.5 if days <= LATELY_DAYS else 0.0
    return (3 * math.log1p(origins) + 2 * math.log1p(classics) + 1.5 * math.log1p(opened)
            + math.log1p(voices) + recency)

# ---- Discover --------------------------------------------------------------------------------


@dataclass
class Suggestion:
    key: str                         # a site (openai.com) or a platform account (x.com/karpathy)
    voices: List[str]                # the voices that link it
    articles: List[str]              # its article-like addresses linked
    links: int                       # every address of it linked
    addresses: Set[str] = field(default_factory=set)   # those addresses (0051 counts its classics)
    roundups: Set[str] = field(default_factory=set)    # the voices that link it only in roundups (0067)

    @property
    def weight(self) -> float:
        """Its voices as Discover orders them (issue 0067): one linking it only in roundups counts half."""
        return len(self.voices) - len(self.roundups) / 2


def is_roundup(post: StoryPost) -> bool:
    """A post whose links have 3+ anchors: it lists news, so it joins only the story of its first
    (group) and weighs half in Discover's order (issue 0067)."""
    return len(anchors(post)) >= ROUNDUP_ANCHORS


def discover_address(url: str, platforms: Platforms = {}) -> Tuple[Optional[str], str, bool]:
    """What Discover reads of one address: (its key, its site, whether the site is a platform).
    On a platform the key is the account (account_key), none when the first path segment names a
    kind of page (NOT_ACCOUNT); a tweet, on any host, is its author's (x.com/<user>, TWEET); on a
    platform the data finds (`platforms`: find_platforms, issue 0080) its owner (platform_key);
    elsewhere it is the host. A function of the address and the platforms, so the database keeps it
    once per address (repo_discover, issue 0062)."""
    host, _, rest = bare(url).partition("/")
    tweet = TWEET.match("/" + rest)
    if tweet:
        user = tweet.group(1).lower()
        return (None if user in NOT_ACCOUNT else x_account(user)), "x.com", True
    site = site_of(host)
    if site in DISCOVER_PLATFORMS:
        return (None if re.split(r"[/?#]", rest)[0].lower() in NOT_ACCOUNT else account_key(url)), site, True
    if publication_of(host) in platforms:
        return platform_key(url, platforms[publication_of(host)]), site, True
    return host, site, False


def discover_article(url: str) -> bool:
    """What Discover counts as an article: an article-like address (post_links.is_article), or a
    post of a platform account (issue 0065: a tweet in any form, a Telegram post)."""
    host, _, rest = bare(url).partition("/")
    path = "/" + rest
    return is_article(url) or bool(TWEET.match(path)) or (
        site_of(host) in DISCOVER_PLATFORMS and bool(PLATFORM_POST.match(path)))


def discover_open(key: str, site: str, platform: bool, *, followed: Set[str], hidden: Set[str],
                  followed_accounts: Set[str]) -> bool:
    """A key you neither follow nor hid: on a platform as that account, elsewhere as its site."""
    if platform:
        return not (key in followed_accounts or key in hidden)
    return not (site in followed or key in hidden or site in hidden)


def suggestions(links: Iterable[Tuple[str, str, bool]], *, followed: Set[str], hidden: Set[str],
                followed_accounts: Set[str] = frozenset(), mirrors: Set[str] = frozenset(),
                platforms: Platforms = {}) -> List[Suggestion]:
    """Sites and accounts 3+ of your voices link, in 2+ article-like pages that make 40%+ of their
    links, that you don't follow and did not hide. On a platform the unit is the account: it is
    followed, or hidden, only as that account (`followed_accounts`, addresses.account_key), so
    following one channel hides no other. Elsewhere it is the site (`followed`: sites; `hidden`:
    keys or sites); a tweet mirror's other pages (`mirrors`: hosts where tweets are found, issue
    0067) are X's kinds of page, never a site. `links`: (voice, address, whether the linking post is
    a roundup) for every kept outside link, the voice None for a self-link (is_self_link) and Saved's;
    `platforms`: find_platforms'. Most voices first, a voice linking a key only in roundups counting
    half (Suggestion.weight), then all voices."""
    links = list(links)
    found: Dict[str, Tuple[Set[str], Set[str], Set[str], Set[str]]] = defaultdict(lambda: (set(), set(), set(), set()))
    for voice, url, roundup in links:
        key, site, platform = discover_address(url, platforms)
        if key is None or (not platform and key in mirrors) or not discover_open(
                key, site, platform, followed=followed, hidden=hidden, followed_accounts=followed_accounts):
            continue
        voices, articles, every, ordinary = found[key]
        every.add(url)
        if voice is not None:   # a self-link or Saved's: an address linked, by no voice
            voices.add(voice)
            if not roundup:
                ordinary.add(voice)
        if discover_article(url):
            articles.add(url)
    out = [
        Suggestion(key, sorted(voices), sorted(articles), len(every), set(every), voices - ordinary)
        for key, (voices, articles, every, ordinary) in found.items()
        if len(voices) >= DISCOVER_MIN_VOICES and len(articles) >= DISCOVER_MIN_ARTICLES
        and len(articles) >= DISCOVER_ARTICLE_SHARE * len(every)
    ]
    return sorted(out, key=lambda s: (-s.weight, -len(s.voices), -len(s.articles), -s.links, s.key))


# ---- Discover: where your stories start (issue 0065) --------------------------------------------


@dataclass
class Origin:
    """A story's root (0064) as Discover reads it."""
    story_id: str
    url: str                         # the outside page (stories.origin_url), else the origin post's address
    title: Optional[str]             # its link words, or the post's title; None: show the address
    source_id: Optional[str]         # the origin post's source; None: a page outside INSIGHT
    first_at: datetime
    voices: Dict[str, str] = field(default_factory=dict)   # the story's voices -> the source naming each
    own: bool = False                # an origin post on the site its source publishes on: held
    reddit_sources: Tuple[str, ...] = ()   # the Reddit sources of its voices that are a post's author (issue 0080)

    @property
    def stored(self) -> bool:
        return self.source_id is not None


@dataclass
class Origins:
    suggest: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # key -> its stories
    missing: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # source -> its stories
    unnamed: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # youtube.com/watch -> them
    references: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # docs.example.com -> them


def discover_place(url: str, platforms: Platforms = {}) -> Optional[str]:
    """Where an address is, as a source holds it: on a platform its account (None for a page that
    names none), elsewhere its host and section (anthropic.com/news; the host alone at the root)."""
    key, _, platform = discover_address(url, platforms)
    section = "" if platform else section_of(url)
    return f"{key}/{section}" if key and section else key


def origins(roots: Iterable[Origin], *, followed: Set[str], held: Dict[str, str],
            mirrors: Set[str] = frozenset(), platforms: Platforms = {}) -> Origins:
    """Where your stories start, each story once:
    - at its own source's site (Origin.own), or at a place one of your sources holds (`held`:
      discover_place -> that source): nothing to suggest; a story the
      source misses when its page is not stored (its archive may hold it, 0015);
    - at a help, docs or support page (reference_address, issue 0080): a reference, only listed;
    - on a site you don't follow, or an account no source holds: that site or account;
    - on a site you follow, elsewhere than the places your sources hold: never suggested (issue 0080),
      a story the site's source misses (the source holding the site's first place in `held`);
    - on a platform's page that names no account (youtube.com/watch?v=...), or a tweet mirror's page
      that is not a tweet (`mirrors`, issue 0067: nitter.net/i/article/...): only listed."""
    out = Origins()
    followers: Dict[str, str] = {}   # a followed site -> a source holding a place of it
    for place, source_id in sorted(held.items()):
        followers.setdefault(site_of(place.split("/", 1)[0]), source_id)
    for root in roots:
        key, site, platform = discover_address(root.url, platforms)
        place = discover_place(root.url, platforms)
        if root.own:
            continue
        if key is not None and place not in held and reference_address(root.url):
            out.references[key].append(root)
        elif key is None or (not platform and key in mirrors):
            if not root.stored:   # a stored one is its source's
                _, _, rest = bare(root.url).partition("/")
                out.unnamed[f"{site}/{re.split(r'[/?#]', rest)[0]}"].append(root)
        elif place in held:
            if not root.stored:
                out.missing[held[place]].append(root)
        elif platform or site not in followed:
            out.suggest[key].append(root)
        elif not root.stored and site in followers:
            out.missing[followers[site]].append(root)
    return out


def address_rules() -> str:
    """Which rules wrote a discover_addresses row (issue 0071): what they make of the sample's addresses
    (utils/stamps.py), so a change to discover_address, site_of, account_key or discover_article that
    shows there refills the rows, and a refactor that changes nothing keeps them."""
    return fingerprint([(url, discover_address(url), discover_article(url)) for url in ADDRESSES])


ADDRESS_RULES = address_rules()


def address_stamp(platforms: Platforms) -> str:
    """The rules a discover_addresses row is written by: ADDRESS_RULES, and the platforms the data
    finds (issue 0080), so a host that becomes one, or stops being one, refills the rows."""
    return ADDRESS_RULES if not platforms else fingerprint([ADDRESS_RULES, sorted((h, list(p)) for h, p in platforms.items())])

__all__ = ["Suggestion", "suggestions", "discover_address", "discover_article", "discover_open", "discover_place",
           "find_platforms", "platform_rows", "platform_key", "is_self_link", "place_kind", "reference_address",
           "paper_address", "score", "address_stamp",
           "Origin", "Origins", "origins", "is_roundup", "address_rules", "ADDRESS_RULES"]
