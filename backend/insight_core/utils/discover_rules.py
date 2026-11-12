"""Discover (issues 0050, 0065, 0067): the sites and accounts your sources keep linking, and where
your stories start. Pure functions over plain data; db/repo_discover.py counts the links in SQL by
these rules (`suggestions` is its reference) and services/stories_service.py ranks what it finds.
"""
from __future__ import annotations

import bisect
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Set, Tuple

from insight_core.utils.addresses import PLATFORM_SITES, account_key, bare, paper_id, publication_of, site_of, x_account
from insight_core.utils.post_links import LANGUAGE, NUMBERISH, is_article, is_home, section_of
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
# Of those, the ones a source kind reads an account of (services/discover_reads.kind_source), issue 0172.
KIND_PLATFORMS = frozenset(set().union(*(PLATFORM_SITES[k] for k in ("reddit", "x", "telegram", "youtube"))))
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
# Issue 0109 W4: a host whose pages mark their owner (/@<owner>/..., /~<owner>/..., /<owner>/posts/...) is a
# platform of those owners when PLACE_SHARE of its pages are so marked under 2+ owners, however few: a
# creators' platform (server and lab: 1 host, 3 owners). A section is never marked so.
OWNER_MARKS = ("@", "~")
MARKED_OWNERS = ("@",)   # the prefix of such a platform: only a page that marks its owner names one
OWNER_POSTS = frozenset({"posts", "post", "p"})
NOT_OWNER = re.compile(r"^(v?\d[\d.\-_v]*|[a-z]{2}|\d{4}-\d\d(-\d\d)?.*|[0-9a-f]{8,}|.*\.(html?|php|aspx?|pdf))$", re.I)
# Two letters name no owner (a store's /dp/ and /gp/ pages: 283 of the lab's links). A language segment (issue 0109
# W11: an organisation's handle, ai-sage, was read as one): the whole first path part, a language of ISO 639-1,
# and a region (ru-RU), a UN area (es-419) or a script (zh-Hant) after it.
ISO_639_1 = frozenset("""aa ab ae af ak am an ar as av ay az ba be bg bh bi bm bn bo br bs ca ce ch co cr cs cu cv cy da de
dv dz ee el en eo es et eu fa ff fi fj fo fr fy ga gd gl gn gu gv ha he hi ho hr ht hu hy hz ia id ie ig ii ik io is it
iu ja jv ka kg ki kj kk kl km kn ko kr ks ku kv kw ky la lb lg li ln lo lt lu lv mg mh mi mk ml mn mr ms mt my na nb nd
ne ng nl nn no nr nv ny oc oj om or os pa pi pl ps pt qu rm rn ro ru rw sa sc sd se sg si sk sl sm sn so sq sr ss st su
sv sw ta te tg th ti tk tl tn to tr ts tt tw ty ug uk ur uz ve vi vo wa wo xh yi yo za zh zu""".split())
SCRIPTS = frozenset({"hans", "hant", "latn", "cyrl", "arab", "deva", "jpan", "kore", "grek", "hebr", "thai"})
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


def language_segment(seg: str) -> bool:
    """A language tag (ISO_639_1, with a region, a UN area or a script after it): en, ru-RU, es-419, zh-Hant."""
    primary, _, sub = seg.lower().replace("_", "-").partition("-")
    return primary in ISO_639_1 and (not sub or (len(sub) == 2 and sub.isalpha()) or (len(sub) == 3 and sub.isdigit())
                                     or sub in SCRIPTS)


def owner_segment(seg: str, *, first: bool = False) -> bool:
    """A path segment that can name an owner: not a number, a date, an id or a file, and, as the whole first
    path part (`first`), not a language (issue 0109)."""
    return not NOT_OWNER.match(seg) and not _id_like(seg) and not (first and language_segment(seg))


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
        marked = _marked_owners(paths)
        if marked is not None:
            out[host] = MARKED_OWNERS
            continue
        level = len(prefix)
        owners: Dict[str, Tuple[int, Set[str]]] = {}
        for segs, urls, voices in paths:
            if len(segs) > level + 1 and owner_segment(segs[level], first=level == 0):
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


def _marked_owner(segs: Tuple[str, ...]) -> Optional[str]:
    """The owner a page marks as its own (/@<owner>, /~<owner>, /<owner>/posts/<x>), else None."""
    if not segs:
        return None
    owner = segs[0].lstrip("".join(OWNER_MARKS))
    if not owner or owner.startswith("-") or not owner_segment(owner, first=True):
        return None
    if segs[0][:1] in OWNER_MARKS or (len(segs) >= 3 and segs[1] in OWNER_POSTS):
        return owner
    return None


def _marked_owners(paths: List[Tuple[Tuple[str, ...], int, Set[str]]]) -> Optional[Set[str]]:
    """The owners of a host whose pages mark them (PLACE_SHARE of its pages, 2+ owners), else None."""
    total = sum(urls for _, urls, _ in paths)
    owners: Set[str] = set()
    marked = 0
    for segs, urls, _ in paths:
        owner = _marked_owner(segs)
        if owner:
            owners.add(owner)
            marked += urls
    return owners if total and marked >= PLACE_SHARE * total and len(owners) >= 2 else None


def platform_key(url: str, prefix: Tuple[str, ...]) -> Optional[str]:
    """The owner an address on a data platform is under: host/<prefix>/<owner>; None for a page
    outside the prefix or one whose segment there names no owner (a kind of page, a number, an id)."""
    host = publication_of(bare(url).partition("/")[0])
    segs = path_segments(url)
    if tuple(prefix) == MARKED_OWNERS:   # issue 0109: owners only where a page marks them (/@x, /~x, /x/posts/)
        return f"{host}/{segs[0]}" if _marked_owner(segs) else None
    level = len(prefix)
    if segs[:level] != prefix or len(segs) <= level:
        return None
    owner = segs[level]
    if not owner_segment(owner, first=level == 0) or owner.lstrip("@~") in NOT_OWNER_KINDS:
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


# Issue 0109 W4, shapes of what isn't a source, each measured on the server's 1,275 suggestions and the lab's
# 1,082 (their shown pages) before it was adopted (counts in 0109's Built):
# - an archive: a page holding another full address (/web/<date>/https:/<site>/...), or a file (an image, a
#   sound, a script): another site's page, or no article (server 3: two web archives, a CDN);
# - an app's shared pages: an opaque id (a uuid, 16+ hex) right after a share-like segment (/share/<id>,
#   /c/<id>, /chat/<id>, /notebook/<id>): a conversation, not a publication (server 4: three chat apps and a
#   notebook app). An id alone is no sign: a newspaper's articles are /content/<uuid>;
# - documents and data: a first segment (a language aside) that names a kind of record (DOCUMENT_PATH: a
#   register's /documents/, a court's /docket/, /statistics/, a leaderboard's /sota/): server 11, all right;
# - a paper: 0106's paper id (addresses.paper_id) or a /paper/ path (a proceedings' /paper/<year>/hash/<hex>).
_EMBEDDED = re.compile(r"/https?(?::|%3a)(?:/|%2f)", re.I)
_FILE = re.compile(r"\.(?:png|jpe?g|gif|webp|svg|avif|ico|bmp|tiff?|mp4|mp3|m4a|wav|ogg|webm|mov|woff2?|css|js)$", re.I)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HEX = re.compile(r"(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{16,}", re.I)
SHARE_PATH = frozenset({"share", "s", "c", "chat", "chats", "g", "conversation", "conversations", "notebook",
                        "app", "apps", "artifact", "artifacts"})
DOCUMENT_PATH = frozenset({"document", "documents", "docket", "dockets", "record", "records", "statistics",
                           "sota", "doc", "eli", "advisories", "opinion", "opinions", "legislation", "bill", "bills"})
PAPER_PATH = frozenset({"paper", "papers"})


def _path(url: str) -> str:
    _, _, rest = bare(url).partition("/")
    return "/" + re.split(r"[?#]", rest, maxsplit=1)[0]


def archive_address(url: str) -> bool:
    """Another site's page kept here (its full address in the path), or a file, not an article."""
    path = _path(url)
    return bool(_EMBEDDED.search(path) or re.search(r"https?%3a%2f%2f", url, re.I) or _FILE.search(path))


def app_address(url: str) -> bool:
    """An app's shared page: an opaque id right after a share-like segment."""
    segs = [s.lower() for s in _path(url).split("/") if s]
    return any(a in SHARE_PATH and bool(_UUID.search(b) or _HEX.search(b)) for a, b in zip(segs, segs[1:]))


def document_address(url: str) -> bool:
    """A record, a filing or a data page: its first segment (a language aside) names a kind of record."""
    segs = [s for s in path_segments(url)[:2] if not LANGUAGE.match(s)][:1]
    return any(s in DOCUMENT_PATH for s in segs)


def paper_address(url: str) -> bool:
    segs = path_segments(url)
    return (any(PAPER_ID.match(s) for s in segs[:3]) or paper_id(url) is not None
            or (len(segs) >= 2 and segs[0] in PAPER_PATH))


# Issue 0172 b3, what isn't a channel by its pages' shape (classes, never hosts):
# - an interactive page told by its query, not its path: a path of at most one segment whose query carries the
#   page (/forum?id=<x>, /?q=<x>, /compare?model=a): a forum's paper, a tool's state, never a publication's article;
# - a listing of models or packages: pages under a first segment naming a catalogue (LISTING_PATH: /models/<x>,
#   /library/<x>): a catalogue's entry, not an article.
LISTING_PATH = frozenset({"models", "model", "library", "leaderboard", "leaderboards", "providers", "rankings",
                          "compare", "playground", "spaces", "datasets"})


# A publication's own section, whose article a query may name (a blog drawn by its script, /blog?id=<post>): its
# site is a channel that can't be read as pages, never an interactive page (its account may be followed, b5).
PUBLICATION_PATH = frozenset({"blog", "blogs", "news", "posts", "post", "articles", "article", "research", "stories",
                              "story", "updates", "press", "newsroom", "insights", "journal", "notes"})


def query_address(url: str) -> bool:
    """An interactive page told by its query (above): one path segment at most (not a publication's section), a
    query that names the page."""
    rest = bare(url).partition("/")[2]
    path, _, query = rest.partition("?")
    segs = [s.lower() for s in path.split("#", 1)[0].split("/") if s]
    return (bool(query.strip("&")) and len(segs) <= 1 and "=" in query
            and not (segs and segs[0] in PUBLICATION_PATH))


def listing_address(url: str) -> bool:
    """A catalogue's entry (above): its first segment (a language aside) names a listing, an entry under it."""
    segs = [s for s in path_segments(url) if not LANGUAGE.match(s)]
    return len(segs) >= 2 and segs[0] in LISTING_PATH


PLACE_TESTS = (("reference", reference_address), ("archive", archive_address), ("app", app_address),
               ("document", document_address), ("paper", paper_address), ("app", query_address),
               ("listing", listing_address))
# What Discover does with each (issue 0109): references and documents are a quiet line of references; an
# archive, an app's pages and a paper source are no suggestion at all (papers stay in stories and Classics).
REFERENCE_KINDS = ("reference", "document")


def place_kind(key: str, urls: Iterable[str]) -> Optional[str]:
    """What a suggestion is when it is no source: "reference" (its host so named, or PLACE_SHARE of its
    shown pages reference_address), "archive", "app" (a share link or a page told by its query), "document",
    "paper" or "listing" (PLACE_SHARE of them of that shape, in that order), else None. A platform's owner (a
    key with a path) is only a reference, a paper source or a listing: the other shapes are read of a whole host."""
    urls = list(urls)
    if REFERENCE_HOST.match(key):
        return "reference"
    tests = PLACE_TESTS if "/" not in key else tuple(t for t in PLACE_TESTS
                                                     if t[0] in ("reference", "document", "paper", "listing"))
    for kind, test in tests:
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


# ---- a followed source's other channels (issue 0109 W3 A, measured on the server's saved answer) -----
# A suggestion a followed source itself links, under one of that source's names, is that source's other
# channel (its X account, a moved blog's old site, a lab's org page): 25 found on the server, 22 right by the
# review's judgement (2 wrong: a cloud company matched by a word of another source's name, a forge's blog by
# a third party's feed named after the forge). A name: its account's, its site's word (a writer's own label
# on a host of many writers), the words of its display name and those words run together; words of NAME_MIN+
# letters only (an id or a number names no one), none of NOT_NAME. A key holds a name when one of its words (an account's name and its parts, a
# site's registrable word) is it, starts with it or ends with it. Matching names without the link is Mark X.
NAME_MIN = 4
NOT_NAME = NOT_SELF | {"https", "http"}
_NAME_WORDS = re.compile(r"[^a-z0-9]+")
_NAME_ADDRESS = re.compile(r"^\s*https?://", re.I)


def _site_word(site: str) -> str:
    return site.split(".", 1)[0]


def own_names(name: str, *, account: str = "", publication: str = "",
              shared_sites: Iterable[str] = frozenset()) -> Set[str]:
    """A source's names as a key may hold them (above). `account`: its platform account (x.com/<name>);
    `publication`: a website's host; `shared_sites`: the sites of many writers (SourceFacts.shared_sites)."""
    names: Set[str] = set()
    if "/" in account:
        names.add(account.rsplit("/", 1)[1].lstrip("@~").lower())
    if publication:
        site = site_of(publication)
        names.add(publication.split(".", 1)[0] if site in set(shared_sites) and publication != site else _site_word(site))
    if name and not _NAME_ADDRESS.match(name):
        words = [w for w in _NAME_WORDS.split(name.lower()) if w]
        names.update(words)
        if len(words) > 1:
            names.add("".join(w for w in words if w not in NOT_NAME))
    return {n for n in names if len(n) >= NAME_MIN and n not in NOT_NAME and n.isalpha()}


def channel_names(name: str, *, account: str = "", publication: str = "",
                  shared_sites: Iterable[str] = frozenset()) -> Tuple[Set[str], Set[str], Set[str]]:
    """A followed source's names for crediting it a suggestion as its other channel (issue 0172 b2: a word
    shared by name credited a newspaper's science section to a source named "<x> Science Digest", a
    country's portal to a newsletter named "<country> Talk", a cloud company's blog to a source named "<x> Cloud
    <y>"): (its places' names: its account's and its site's word, its own addresses; its whole name: the display
    name's words run together; the words of its display name, own_names', which name only an account)."""
    places = own_names("", account=account, publication=publication, shared_sites=shared_sites)
    whole: Set[str] = set()
    if name and not _NAME_ADDRESS.match(name):
        words = [w for w in _NAME_WORDS.split(name.lower()) if w and w not in NOT_NAME]
        if words:
            whole.add("".join(words))
    whole = {n for n in whole if len(n) >= NAME_MIN and n.isalnum() and not n.isdigit()}
    return places, whole, own_names(name, shared_sites=shared_sites) - places - whole


def other_channel(key: str, places: Iterable[str], whole: Iterable[str], words: Iterable[str] = ()) -> bool:
    """Whether a suggestion is a followed source's other channel (channel_names): a word of its key is one of the
    source's places' names, starts or ends with one (its own address on another host or platform), or is its
    whole name; an account on a platform a source kind reads (KIND_PLATFORMS: an account's handle is chosen
    by its owner) also by a word of its display name. A site's or a section's word shared with a word of the
    name is no relation: a site names its publisher, not the source's."""
    held = owner_words(key)
    places = [n for n in places if n]
    if (any(w == n or w.startswith(n) or w.endswith(n) for w in held for n in places)
            or bool(held & set(whole))):
        return True
    if "/" not in key or site_of(key.split("/", 1)[0]) not in KIND_PLATFORMS:
        return False
    return any(w == n or w.startswith(n) or w.endswith(n) for w in held for n in words if n)


def owner_words(key: str) -> Set[str]:
    """The words a suggestion's key names its owner by: an account's (or owner's) name and its parts, else
    the site's registrable word (news.example.com: example)."""
    host, _, rest = key.partition("/")
    whole = rest.rsplit("/", 1)[-1].lstrip("@~").lower() if rest else _site_word(site_of(publication_of(host)))
    return {whole} | {part for part in re.split(r"[-_.]", whole) if part}


def same_owner(key: str, names: Iterable[str]) -> bool:
    """Whether a key holds one of a source's names (own_names): a word of it is the name, starts or ends with it."""
    names = [n for n in names if n]
    return any(w == n or w.startswith(n) or w.endswith(n) for w in owner_words(key) for n in names)


# ---- one owner's channels among the followed sources (issue 0111: News counts a voice by owner) ----------
# 0109's rule between two followed sources: a name of one in the other's own place (its account, or its site's
# word: a writer's own label on a host of many writers), either way, and a link from one to the other's posts or
# place; or one place followed twice. A platform's word (github, medium, youtube...) names no owner: a trending
# feed of a code host is no one's channel. Measured on the server's copy (2026-11-05): 21 of 23 linked pairs right,
# both wrong ones a code host's trending feed by its platform's word, which this leaves out.
PLATFORM_WORDS = frozenset(_site_word(site) for site in DISCOVER_PLATFORMS)
Channel = Tuple[str, str, str, Optional[str], str]   # (source id, kind, name, account, publication)


def _place_words(kind: str, account: Optional[str], publication: str, shared_sites: Iterable[str]) -> Set[str]:
    """The words a followed source's own place names its owner by (owner_words, for a source)."""
    if kind != "site":
        whole = account.rsplit("/", 1)[1].lstrip("@~").lower() if account and "/" in account else ""
    else:
        site = site_of(publication)
        whole = publication.split(".", 1)[0] if site in set(shared_sites) and publication != site else _site_word(site)
    words = {whole} | {part for part in re.split(r"[-_.]", whole) if part}
    return {w for w in words if w} - PLATFORM_WORDS


def owner_pairs(channels: Iterable[Channel], *, shared_sites: Iterable[str] = frozenset(),
                platforms: Iterable[str] = DISCOVER_PLATFORMS) -> Dict[Tuple[str, str], str]:
    """The pairs of followed sources that may be one owner: (a, b) with a < b -> "place" (one place followed
    twice) or "name" (a name of one in the other's place, either way; a link decides). A source at a
    platform's own host (a code host's trending feed) has no place of its own."""
    shared, platforms = frozenset(shared_sites), frozenset(platforms)
    info = {}
    for source_id, kind, name, account, publication in channels:
        place = (account or "") if kind != "site" else publication
        if kind == "site" and publication.removeprefix("www.") in platforms:
            place = ""
        named = own_names(name, account="" if kind == "site" else account or "",
                          publication=publication if kind == "site" else "", shared_sites=shared) - PLATFORM_WORDS
        info[source_id] = (place, named, _place_words(kind, account, publication, shared) if place else set())
    out: Dict[Tuple[str, str], str] = {}
    by_place: Dict[str, List[str]] = defaultdict(list)
    for source_id, (place, _, _) in info.items():
        if place:
            by_place[place].append(source_id)
    for members in by_place.values():
        for i, a in enumerate(sorted(members)):
            for b in sorted(members)[i + 1:]:
                out[(a, b)] = "place"
    # A word that is a name, starts with it or ends with it (same_owner), found by the words' sorted order and
    # their reversed letters' (256 sources: 62k pair tests otherwise).
    words = sorted((w, i) for i, (place, _, ws) in info.items() if place for w in ws)
    backwards = sorted((w[::-1], i) for w, i in words)

    def starting(found: List[Tuple[str, str]], prefix: str) -> Iterable[str]:
        k = bisect.bisect_left(found, (prefix, ""))
        while k < len(found) and found[k][0].startswith(prefix):
            yield found[k][1]
            k += 1
    for a, (place, named, _) in info.items():
        if not place:
            continue
        for n in named:
            for b in {*starting(words, n), *starting(backwards, n[::-1])} - {a}:
                pair = (min(a, b), max(a, b))
                out.setdefault(pair, "name")
    return out


def channel_owners(channels: Iterable[Channel], pairs: Mapping[Tuple[str, str], str],
                   linked: Iterable[Tuple[str, str]]) -> Dict[str, str]:
    """Each followed source of an owner of 2+ channels -> that owner (its first source by id): the pairs of one
    place, and the named pairs one of which links the other (`linked`: (linking source, linked source))."""
    linked = set(linked)
    parent = {source_id: source_id for source_id, *_ in channels}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for (a, b), why in sorted(pairs.items()):
        if a in parent and b in parent and (why == "place" or (a, b) in linked or (b, a) in linked):
            ra, rb = find(a), find(b)
            parent[max(ra, rb)] = min(ra, rb)
    groups: Dict[str, List[str]] = defaultdict(list)
    for source_id in parent:
        groups[find(source_id)].append(source_id)
    return {source_id: min(members) for members in groups.values() if len(members) > 1 for source_id in members}


# ---- one card per owner domain (issue 0109 W5: 23 owners in 54 cards on the server) ------------------------
# The hosts of one registrable domain (site_of) are one owner's, one card led by its best (the most score),
# its other hosts listed as its places; outside a domain of many owners: a hosting platform's (site_of
# already parts those listed as such), one your followed sources publish on at 2+ hosts
# (SourceFacts.shared_sites), and a federation by the data: FEDERATION_HOSTS+ hosts your sources link, at
# under FEDERATION_POSTS linking posts a host (measured on the lab's kept links: a blog host 51 hosts at 2.0,
# a newsletter host 556 at 2.3, three universities 31-47 at 1.6-3.6, the EU's 28 at 2.5, a tumblr-like host
# 20 at 2.9; one owner's: a search company 49 at 15.5, a software company 27 at 5.2, a phone maker 15 at 16,
# a portal 13 at 7.3, a browser maker 12 at 5.5). Linking voices shared between hosts were tried and told
# nothing apart (a blog host 17%, a news site 17%, a lab 0%).
FEDERATION_HOSTS = 10
FEDERATION_POSTS = 4.0


def federation(*, hosts: int, posts: int) -> bool:
    """A domain of many owners by its links: FEDERATION_HOSTS+ hosts at under FEDERATION_POSTS posts a host."""
    return hosts >= FEDERATION_HOSTS and posts < FEDERATION_POSTS * hosts


# A company's directory of many owners' shows, songs, apps or books (podcasts.<company>, apps.<company>) is no
# place of the company's own (issue 0111): measured on the server's copy, it takes podcasts. and itunes. out of
# one company's card of 4 hosts, and no host of the other 18 cards; the lab's podcasts. host of the same card.
CATALOG_LABELS = frozenset({"podcasts", "podcast", "music", "itunes", "apps", "play", "books", "store", "marketplace"})


def owner_domain(key: str, federations: Iterable[str] = frozenset()) -> Optional[str]:
    """The domain a site suggestion's card is one of: its registrable domain, None for a platform's owner (a
    key with a path), a host of a domain of many owners, or a directory of many owners' items (CATALOG_LABELS)."""
    if "/" in key:
        return None
    site = site_of(key)
    host = key.removeprefix("www.")
    if host != site and host.split(".", 1)[0] in CATALOG_LABELS:
        return None
    return None if site in set(federations) else site


def one_card_per_domain(found: Iterable[Mapping], *, federations: Iterable[str] = frozenset()) -> List[Dict]:
    """The suggestions with one owner domain's hosts as one card (owner_domain): led by the best (score, then
    voices, then key), `places` its hosts (the lead first, then by score), its voices, articles, classics,
    stories and opens together, its score at least its lead's (its stories and sources added up)."""
    federations = set(federations)
    groups: Dict[str, List[Dict]] = defaultdict(list)
    out: List[Dict] = []
    for s in found:
        domain = owner_domain(s["key"], federations)
        if domain is None:
            out.append(dict(s))
        else:
            groups[domain].append(dict(s))
    for members in groups.values():
        members.sort(key=lambda s: (-s["score"], -s["voices"], s["key"]))
        lead = members[0]
        if len(members) == 1:
            out.append(lead)
            continue
        names = list(dict.fromkeys(n for s in members for n in s.get("voice_names", ())))
        articles: Dict[str, Dict] = {}
        for s in members:
            for a in s.get("articles", ()):
                articles.setdefault(a["url"], a)
        stories: Dict[str, Dict] = {}
        for s in members:
            for o in s.get("origin_stories", ()):
                stories.setdefault(o["url"], o)
        card = {**lead, "places": [s["key"] for s in members], "voice_names": names, "voices": len(names),
                "articles": sorted(articles.values(), key=lambda a: -len(a.get("linked_by", ())))[:20]}
        for field_ in ("article_count", "link_count", "classics", "origins", "opened"):
            card[field_] = sum(int(s.get(field_) or 0) for s in members)
        if stories:
            card["origin_stories"] = sorted(stories.values(), key=lambda o: -o.get("voices", 0))[:3]
        days = min((s["days"] for s in members if s.get("days") is not None), default=None)
        card["score"] = max(lead["score"], round(score(origins=card["origins"], classics=card["classics"], opened=card["opened"],
                                                       voices=len(names), days=days), 3))
        out.append(card)
    return out


# The follow test's labels (services/discover_reads.py): what can be followed, and what can't (issue 0080).
FOLLOWABLE = ("feed", "page")
UNFOLLOWABLE = ("headlines", "blocked", "other_feed")   # other_feed: a feed, but not of these pages (issue 0109)


def _label(s: Mapping) -> Optional[str]:
    return (s.get("follow_test") or {}).get("label")


def section(s: Mapping) -> int:
    """Where a suggestion is listed (issue 0109): 0 tested followable, 1 tested and can't be followed as a
    feed (its own section), 2 untested."""
    label = _label(s)
    return 0 if label in FOLLOWABLE else 1 if label in UNFOLLOWABLE else 2


def not_channel(key: str, label: Optional[str]) -> bool:
    """Issue 0172 b3: an owner on a platform (a key with a path) that is no channel to follow: a model hub's owner
    (its pages are models, never posts), or one on a platform no source kind reads (KIND_PLATFORMS: X, Telegram,
    Reddit, YouTube) whose follow test found nothing to follow (a code host's organization without a feed, a
    network without a reader). A site, and an account a kind reads, are left to the follow test's sections."""
    from insight_core.utils.entity_originals import MODEL_HUBS   # entity_originals reads this module
    if "/" not in key:
        return False
    site = site_of(key.split("/", 1)[0])
    if site in MODEL_HUBS:
        return True
    return label in UNFOLLOWABLE and site not in KIND_PLATFORMS


def follow_url(url: str, platforms: Platforms = {}) -> Optional[str]:
    """What a page's "Follow" follows (issue 0172 c3: Pages followed the bare domain, a platform's home page for a
    tweet): on a platform its account (a tweet's author), None for a page naming none; elsewhere its section (its
    first path segment, discover_place's), the site's home when the page sits at its root or under a date."""
    key, _, platform = discover_address(url, platforms)
    if platform:
        return "https://" + key if key else None
    host = bare(url).partition("/")[0].lower()
    if not host:
        return None
    segs = path_segments(url)
    first = segs[0] if len(segs) >= 2 and not NUMBERISH.match(segs[0]) else ""
    return f"https://{host}/{first + '/' if first else ''}"


def order(found: Iterable[Mapping]) -> List[Mapping]:
    """Discover's order (issue 0109 W2: the server's top score had sunk to #1254 of 1,275, below every
    untested suggestion): those tested followable first, then the section of those that can't be followed
    as a feed, then the untested; each by score, ties by key, but one none of your sources links (Mark X's
    originals rows, issue 0172 b4) after every linked one of its section. Each of the section says so
    (`section: "unfollowable"`)."""
    out = sorted(found, key=lambda s: (section(s), not s.get("voices"), -s["score"], s["key"]))
    for s in out:
        if section(s) == 1:
            s["section"] = "unfollowable"   # type: ignore[index]
    return out

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
    at_post: bool = False            # a post is at its outside page's address: a page you saved (issue 0113)

    @property
    def stored(self) -> bool:
        """Its origin is in INSIGHT: an origin post, or a post at the outside page's address (0113's measure:
        a story whose origin you saved has origin_url and no origin post, and was counted as not stored)."""
        return self.source_id is not None or self.at_post


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


PAGES_WITHIN_DAYS = 30   # Discover's Pages (issue 0113): the stories of the last 30 days, as its measure counted


def page_key_of(url: str) -> str:
    """A Pages row's hide key (issue 0113): one page, never its site."""
    return "page:" + (bare(url) or url).lower()


def pages(started: Origins, *, since: datetime, hidden: Set[str]) -> List[Tuple[str, List[Origin], bool]]:
    """Discover's Pages (issue 0113): each story's root you can save as one post, (its address, its
    stories, whether it is a page naming no account: a video's watch page, only listed), the stories'
    voices first, then how many stories, then the newest. A root is a page when its story (2+ voices,
    started since `since`) starts at a site or account you don't follow (`suggest`) or at a platform's
    page that names none (`unnamed`), and no post is at its address (Origin.stored). Not an archive, an
    app's share link, a document host's or a reference page, or a site's front page."""
    found: Dict[str, List[Origin]] = defaultdict(list)
    unnamed: Set[str] = set()
    for group, named in ((started.suggest, True), (started.unnamed, False)):
        for stories in group.values():
            for root in stories:
                if root.stored or root.first_at < since or page_key_of(root.url) in hidden:
                    continue
                if (archive_address(root.url) or app_address(root.url) or document_address(root.url)
                        or reference_address(root.url) or is_home(root.url)):
                    continue
                found[root.url].append(root)
                if not named:
                    unnamed.add(root.url)

    def rank(item: Tuple[str, List[Origin]]) -> Tuple:
        url, roots = item
        voices = len({v for root in roots for v in root.voices})
        return (-voices, -len(roots), -max(r.first_at for r in roots).timestamp(), url)

    return [(url, roots, url in unnamed) for url, roots in sorted(found.items(), key=rank)]


def address_rules() -> str:
    """Which rules wrote a discover_addresses row (issue 0071): what they make of the sample's addresses
    (utils/stamps.py), so a change to discover_address, site_of, account_key or discover_article that
    shows there refills the rows, and a refactor that changes nothing keeps them."""
    return fingerprint([(url, discover_address(url), discover_article(url)) for url in ADDRESSES] + platform_sample())


def platform_sample() -> List[Tuple[str, Tuple[Optional[str], str, bool]]]:
    """What the rules make of a data platform's addresses (issue 0109: an owner's segment, a language before
    it), so a change to owner_segment or platform_key refills the rows as a change to discover_address does."""
    platforms = {"hub.example": (), "forum.example": ("ru", "companies"), "social.example": MARKED_OWNERS}
    return [(url, discover_address(url, platforms)) for url in (
        "https://hub.example/ai-sage/a-model", "https://hub.example/en/a-model", "https://hub.example/an-owner/models",
        "https://forum.example/ru/companies/de/articles/1", "https://hub.example/@someone/posts/1",
        "https://social.example/@someone/1", "https://social.example/redirect/2/abc")]


ADDRESS_RULES = address_rules()


def address_stamp(platforms: Platforms) -> str:
    """The rules a discover_addresses row is written by: ADDRESS_RULES, and the platforms the data
    finds (issue 0080), so a host that becomes one, or stops being one, refills the rows."""
    return ADDRESS_RULES if not platforms else fingerprint([ADDRESS_RULES, sorted((h, list(p)) for h, p in platforms.items())])

__all__ = ["Suggestion", "suggestions", "discover_address", "discover_article", "discover_open", "discover_place",
           "find_platforms", "platform_rows", "platform_key", "is_self_link", "place_kind", "reference_address",
           "paper_address", "archive_address", "app_address", "document_address", "REFERENCE_KINDS", "score", "order", "section", "language_segment", "platform_sample", "MARKED_OWNERS", "federation", "owner_domain", "one_card_per_domain", "own_names", "owner_words", "same_owner", "channel_names", "other_channel", "query_address", "listing_address", "not_channel", "follow_url", "KIND_PLATFORMS", "FOLLOWABLE", "UNFOLLOWABLE", "address_stamp",
           "Origin", "Origins", "origins", "is_roundup", "address_rules", "ADDRESS_RULES"]
