"""Discover: the sites and accounts your sources keep linking, and where your stories start.

Pure functions over plain data; db/repo_discover.py counts the links in SQL by these rules (`suggestions` is its
reference) and services/stories_service.py ranks what it finds.
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
from insight_core.utils.url_normalization import TWEET_PATH

DISCOVER_MIN_VOICES = 3        # the prototype's, not measured
DISCOVER_MIN_ARTICLES = 2      # the prototype's, not measured
DISCOVER_ARTICLE_SHARE = 0.4   # the prototype's, not measured
# The sites where INSIGHT follows one account, not the whole site (measured: plan/issues/0080).
DISCOVER_PLATFORMS = frozenset(set().union(*(PLATFORM_SITES[k] for k in ("reddit", "x", "telegram", "youtube", "bluesky")))
                               | {"github.com", "medium.com"})
# Of those, the ones a source kind reads an account of (services/discover_reads.kind_source).
KIND_PLATFORMS = frozenset(set().union(*(PLATFORM_SITES[k] for k in ("reddit", "x", "telegram", "youtube", "bluesky"))))
# First path segments of a platform that name a kind of page, not an account.
NOT_ACCOUNT = frozenset({"status", "watch", "pull", "issues", "i", "p", "s", "search", "hashtag", "intent",
                         "share", "home", "explore", "wiki", "posts", "in"})
# A platform account's post is one of its articles: a tweet on any host, elsewhere /<account>/<number>.
TWEET = TWEET_PATH
PLATFORM_POST = re.compile(r"^/[^/?#]+/\d+(?:[?#]|$)")
BSKY_POST = re.compile(r"^/profile/[^/?#]+/post/[a-z0-9]+(?:[/?#]|$)", re.I)
ORIGIN_MIN_VOICES = 2      # the stories whose origins Discover counts; not measured

# ---- platforms from the data (measured: plan/issues/0080) ----
# A host is a platform when the pages your sources link there sit under many owners (OWNERS_*). An owner is a path
# segment with pages beneath it (owner_segment); past a segment holding PREFIX_SHARE+ of the pages (/r/, /profile/)
# the owner is the next one, down to OWNER_DEPTH, never past two shared segments.
OWNERS_MANY, OWNERS_MIN, OWNER_TOP_SHARE, OWNER_VOICES = 50, 15, 0.2, 2
PREFIX_SHARE = 0.7
OWNER_DEPTH = 3
# A host whose pages mark their owner (/@<owner>, /~<owner>, /<owner>/posts/) is a platform of those owners when
# PLACE_SHARE of its pages are so marked under 2+ owners (0109).
OWNER_MARKS = ("@", "~")
MARKED_OWNERS = ("@",)   # the prefix of such a platform: only a page that marks its owner names one
OWNER_POSTS = frozenset({"posts", "post", "p"})
NOT_OWNER = re.compile(r"^(v?\d[\d.\-_v]*|[a-z]{2}|\d{4}-\d\d(-\d\d)?.*|[0-9a-f]{8,}|.*\.(html?|php|aspx?|pdf))$", re.I)
# Two letters name no owner (a store's /dp/); a language segment does neither (language_segment).
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
    _, _, rest = bare(url).partition("/")
    return tuple(seg for seg in re.split(r"[?#]", rest, maxsplit=1)[0].lower().split("/") if seg)


def _id_like(seg: str) -> bool:
    return len(seg) >= 8 and bool(re.fullmatch(r"[a-z0-9]+", seg, re.I) and re.search(r"\d", seg)
                                   and re.search(r"[a-z]", seg, re.I))


def language_segment(seg: str) -> bool:
    """en, ru-RU, es-419, zh-Hant: an ISO 639-1 language, with a region, a UN area or a script after it."""
    primary, _, sub = seg.lower().replace("_", "-").partition("-")
    return primary in ISO_639_1 and (not sub or (len(sub) == 2 and sub.isalpha()) or (len(sub) == 3 and sub.isdigit())
                                     or sub in SCRIPTS)


def owner_segment(seg: str, *, first: bool = False) -> bool:
    """Not a number, a date, an id or a file, and, as the whole first path part (`first`), not a language."""
    return not NOT_OWNER.match(seg) and not _id_like(seg) and not (first and language_segment(seg))


def is_self_link(url: str, selves: Iterable[str]) -> bool:
    """One of the first OWNER_DEPTH path segments is one of the source's names."""
    names = set(selves)
    return bool(names) and any(seg.lstrip("@~") in names for seg in path_segments(url)[:OWNER_DEPTH])


def platform_rows(links: Iterable[Tuple[str, str]]) -> List[Tuple[str, Tuple[str, ...], int, FrozenSet[str]]]:
    """(voice, address) links grouped as DiscoverRepository.platforms groups them in SQL: (host, its first
    OWNER_DEPTH segments and "*" when deeper ones follow, the addresses, their voices)."""
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
    """The hosts that are platforms by the data, each with the path its owners sit under."""
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
    if not segs:
        return None
    owner = segs[0].lstrip("".join(OWNER_MARKS))
    if not owner or owner.startswith("-") or not owner_segment(owner, first=True):
        return None
    if segs[0][:1] in OWNER_MARKS or (len(segs) >= 3 and segs[1] in OWNER_POSTS):
        return owner
    return None


def _marked_owners(paths: List[Tuple[Tuple[str, ...], int, Set[str]]]) -> Optional[Set[str]]:
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
    """host/<prefix>/<owner> of an address on a data platform; None outside the prefix or for no owner."""
    host = publication_of(bare(url).partition("/")[0])
    segs = path_segments(url)
    if tuple(prefix) == MARKED_OWNERS:   # owners only where a page marks them (/@x, /~x, /x/posts/)
        return f"{host}/{segs[0]}" if _marked_owner(segs) else None
    level = len(prefix)
    if segs[:level] != prefix or len(segs) <= level:
        return None
    owner = segs[level]
    if not owner_segment(owner, first=level == 0) or owner.lstrip("@~") in NOT_OWNER_KINDS:
        return None
    return "/".join((host, *prefix, owner))


# ---- what a place is: references and paper sources are not sources to follow (0080) ----------
# A reference is told by its address's shape, not by its links.
REFERENCE_HOST = re.compile(r"^(?:www\.)?(?:help|support|docs|developer)\.", re.I)
REFERENCE_PATH = frozenset({"docs", "help", "support"})
# A host of paper ids and no owner is a paper source: never a suggestion (its papers stay in stories and Classics).
PAPER_ID = re.compile(r"^(?:\d{4}\.\d{4,5}(?:v\d+)?(?:\.pdf)?|10\.\d{4,9})$")
PLACE_SHARE = 0.6   # of a suggestion's shown pages (measured: plan/issues/0080)


def reference_address(url: str) -> bool:
    host = bare(url).partition("/")[0]
    segs = [s for s in path_segments(url)[:3] if not LANGUAGE.match(s)][:2]
    return bool(REFERENCE_HOST.match(host)) or any(s in REFERENCE_PATH for s in segs)


# Shapes of what isn't a source (measured: plan/issues/0109): an archive's copy or a file, an app's shared page (an
# opaque id after a share-like segment; an id alone is no sign), a record or data page, a paper.
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
    path = _path(url)
    return bool(_EMBEDDED.search(path) or re.search(r"https?%3a%2f%2f", url, re.I) or _FILE.search(path))


def app_address(url: str) -> bool:
    segs = [s.lower() for s in _path(url).split("/") if s]
    return any(a in SHARE_PATH and bool(_UUID.search(b) or _HEX.search(b)) for a, b in zip(segs, segs[1:]))


def document_address(url: str) -> bool:
    segs = [s for s in path_segments(url)[:2] if not LANGUAGE.match(s)][:1]
    return any(s in DOCUMENT_PATH for s in segs)


def paper_address(url: str) -> bool:
    segs = path_segments(url)
    return (any(PAPER_ID.match(s) for s in segs[:3]) or paper_id(url) is not None
            or (len(segs) >= 2 and segs[0] in PAPER_PATH))


# What isn't a channel by its pages' shape (0172): an interactive page told by its query, a catalogue's entry.
LISTING_PATH = frozenset({"models", "model", "library", "leaderboard", "leaderboards", "providers", "rankings",
                          "compare", "playground", "spaces", "datasets"})


# A publication's own section, whose article a query may name (/blog?id=<post>).
PUBLICATION_PATH = frozenset({"blog", "blogs", "news", "posts", "post", "articles", "article", "research", "stories",
                              "story", "updates", "press", "newsroom", "insights", "journal", "notes"})


def query_address(url: str) -> bool:
    rest = bare(url).partition("/")[2]
    path, _, query = rest.partition("?")
    segs = [s.lower() for s in path.split("#", 1)[0].split("/") if s]
    return (bool(query.strip("&")) and len(segs) <= 1 and "=" in query
            and not (segs and segs[0] in PUBLICATION_PATH))


def listing_address(url: str) -> bool:
    segs = [s for s in path_segments(url) if not LANGUAGE.match(s)]
    return len(segs) >= 2 and segs[0] in LISTING_PATH


PLACE_TESTS = (("reference", reference_address), ("archive", archive_address), ("app", app_address),
               ("document", document_address), ("paper", paper_address), ("app", query_address),
               ("listing", listing_address))
# References and documents are a quiet line of references; the other kinds are no suggestion at all.
REFERENCE_KINDS = ("reference", "document")


def place_kind(key: str, urls: Iterable[str]) -> Optional[str]:
    """What a suggestion is when it is no source (PLACE_TESTS, PLACE_SHARE of its shown pages of that shape), else
    None. A platform's owner is only a reference, document, paper source or listing."""
    urls = list(urls)
    if REFERENCE_HOST.match(key):
        return "reference"
    tests = PLACE_TESTS if "/" not in key else tuple(t for t in PLACE_TESTS
                                                     if t[0] in ("reference", "document", "paper", "listing"))
    for kind, test in tests:
        if urls and sum(1 for u in urls if test(u)) >= PLACE_SHARE * len(urls):
            return kind
    return None


# ---- the order (measured: plan/issues/0080) ------------------------------
RECENT_DAYS, LATELY_DAYS = 14, 60
FIRST_PAGE = 30   # Discover's first page; the rest behind "More"
CHECK_DAYS = 30   # a follow test, or a page's title, is read at most once in this many days


GROWTH_DAYS = 30    # a source that first linked a key this recently is a new one
GROWTH_WEIGHT = 1.5  # NOT MEASURED YET; plan/issues/0235 says how to measure it


def growth(*, new: float, old: float) -> float:
    """The share of a key's linking sources new in GROWTH_DAYS, times ln(1+those new sources)."""
    total = new + old
    return 0.0 if new <= 0 or total <= 0 else (new / total) * math.log1p(new)


def score(*, origins: int, classics: int, opened: int, voices: float, days: Optional[float],
          grown: float = 0.0) -> float:
    recency = 0.0 if days is None else 1.0 if days <= RECENT_DAYS else 0.5 if days <= LATELY_DAYS else 0.0
    return (3 * math.log1p(origins) + 2 * math.log1p(classics) + 1.5 * math.log1p(opened)
            + math.log1p(voices) + recency + GROWTH_WEIGHT * grown)


# ---- a followed source's other channels (0109) -----
# A suggestion a followed source itself links, under one of that source's names, is that source's other channel.
# Matching names without the link is Mark X.
NAME_MIN = 4
NOT_NAME = NOT_SELF | {"https", "http"}
_NAME_WORDS = re.compile(r"[^a-z0-9]+")
_NAME_ADDRESS = re.compile(r"^\s*https?://", re.I)


def _site_word(site: str) -> str:
    return site.split(".", 1)[0]


# Top-level domains anyone registers under: never an owner's brand.
GENERIC_SUFFIXES = frozenset({"info", "name", "site", "online", "blog", "news", "tech", "club", "shop", "store", "live",
                              "life", "world", "today", "page", "work", "space", "website", "media", "press", "cloud",
                              "email", "link", "codes", "tools", "agency", "studio", "design", "network", "digital"})


def _brand_suffix(publication: str) -> Set[str]:
    """A brand's top-level label as its site's name (blog.<brand>, whose word "blog" names no one)."""
    if not publication:
        return set()
    site = site_of(publication)
    labels = site.split(".")
    if len(labels) != 2 or labels[0] not in NOT_NAME:
        return set()
    suffix = labels[1].lower()
    return {suffix} if len(suffix) >= NAME_MIN and suffix.isalpha() and suffix not in GENERIC_SUFFIXES else set()


def own_names(name: str, *, account: str = "", publication: str = "",
              shared_sites: Iterable[str] = frozenset()) -> Set[str]:
    """A source's names as a key may hold them. `shared_sites`: the sites of many writers."""
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
    """(its places' names, its whole name run together, its display name's words): a display-name word alone
    credits only an account (it credited unrelated sites, 0172)."""
    places = own_names("", account=account, publication=publication, shared_sites=shared_sites)
    places |= _brand_suffix(publication)
    whole: Set[str] = set()
    if name and not _NAME_ADDRESS.match(name):
        words = [w for w in _NAME_WORDS.split(name.lower()) if w and w not in NOT_NAME]
        if words:
            whole.add("".join(words))
    whole = {n for n in whole if len(n) >= NAME_MIN and n.isalnum() and not n.isdigit()}
    return places, whole, own_names(name, shared_sites=shared_sites) - places - whole


def other_channel(key: str, places: Iterable[str], whole: Iterable[str], words: Iterable[str] = ()) -> bool:
    """A key word is, starts or ends with one of the source's places' names, or is its whole name; an account on a
    KIND_PLATFORMS platform also by a display-name word. A site's word names its publisher, not the source."""
    held = owner_words(key)
    places = [n for n in places if n]
    if (any(w == n or w.startswith(n) or w.endswith(n) for w in held for n in places)
            or bool(held & set(whole))):
        return True
    if "/" not in key or site_of(key.split("/", 1)[0]) not in KIND_PLATFORMS:
        return False
    return any(w == n or w.startswith(n) or w.endswith(n) for w in held for n in words if n)


def owner_words(key: str) -> Set[str]:
    """An account's (or owner's) name and its parts, else the site's registrable word."""
    host, _, rest = key.partition("/")
    whole = rest.rsplit("/", 1)[-1].lstrip("@~").lower() if rest else _site_word(site_of(publication_of(host)))
    return {whole} | {part for part in re.split(r"[-_.]", whole) if part}


def same_owner(key: str, names: Iterable[str]) -> bool:
    names = [n for n in names if n]
    return any(w == n or w.startswith(n) or w.endswith(n) for w in owner_words(key) for n in names)


# ---- one owner's channels among the followed sources (News counts a voice by owner, 0111) ----------
# Two followed sources may be one owner: a name of one in the other's place and a link between them, or one place
# followed twice. A platform's word (code hosts, blog hosts) names no owner.
PLATFORM_WORDS = frozenset(_site_word(site) for site in DISCOVER_PLATFORMS)
Channel = Tuple[str, str, str, Optional[str], str]   # (source id, kind, name, account, publication)


def _place_words(kind: str, account: Optional[str], publication: str, shared_sites: Iterable[str]) -> Set[str]:
    if kind != "site":
        whole = account.rsplit("/", 1)[1].lstrip("@~").lower() if account and "/" in account else ""
    else:
        site = site_of(publication)
        whole = publication.split(".", 1)[0] if site in set(shared_sites) and publication != site else _site_word(site)
    words = {whole} | {part for part in re.split(r"[-_.]", whole) if part}
    return {w for w in words if w} - PLATFORM_WORDS


def owner_pairs(channels: Iterable[Channel], *, shared_sites: Iterable[str] = frozenset(),
                platforms: Iterable[str] = DISCOVER_PLATFORMS) -> Dict[Tuple[str, str], str]:
    """(a, b) with a < b -> "place" (one place followed twice) or "name" (a link decides)."""
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
    # found by bisecting the sorted words and their reversed letters' (avoids testing every pair)
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
    """Each followed source of an owner of 2+ channels -> its first source by id: the one-place pairs, and the
    named pairs one of which links the other (`linked`)."""
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


# ---- one card per owner domain (0109) ------------------------
# The hosts of one registrable domain are one owner's card, except a domain of many owners: a hosting platform's, one
# your followed sources publish on at 2+ hosts, or a federation by the data (measured: plan/issues/0109).
FEDERATION_HOSTS = 10
FEDERATION_POSTS = 4.0


def federation(*, hosts: int, posts: int) -> bool:
    return hosts >= FEDERATION_HOSTS and posts < FEDERATION_POSTS * hosts


# A company's directory of many owners' items (podcasts.<company>) is no place of the company's own.
CATALOG_LABELS = frozenset({"podcasts", "podcast", "music", "itunes", "apps", "play", "books", "store", "marketplace"})


def owner_domain(key: str, federations: Iterable[str] = frozenset()) -> Optional[str]:
    """A site suggestion's card domain: None for a platform's owner, a federation's host or a directory."""
    if "/" in key:
        return None
    site = site_of(key)
    host = key.removeprefix("www.")
    if host != site and host.split(".", 1)[0] in CATALOG_LABELS:
        return None
    return None if site in set(federations) else site


def announcing_place(s: Mapping) -> bool:
    """A card's place that is the company's announcing section, as discover_main_source.announcing reads it."""
    # imported here: that module imports this one
    from insight_core.services.discover_main_source import NEWSROOM, announcing
    url = s.get("url") or ""
    return announcing("https://" + s["key"]) == NEWSROOM or bool(url and announcing(url) == NEWSROOM)


def one_card_per_domain(found: Iterable[Mapping], *, federations: Iterable[str] = frozenset()) -> List[Dict]:
    """One card per owner domain (owner_domain), led by its announcing section when the best is not the site's own
    host, else by its best; counts summed, its score at least its best place's."""
    federations = set(federations)
    groups: Dict[str, List[Dict]] = defaultdict(list)
    out: List[Dict] = []
    for s in found:
        domain = owner_domain(s["key"], federations)
        if domain is None:
            out.append(dict(s))
        else:
            groups[domain].append(dict(s))
    for domain, members in groups.items():
        members.sort(key=lambda s: (-s["score"], -s["voices"], s["key"]))
        # the announcing section never leads over the site's own host (0248)
        if len(members) > 1 and members[0]["key"].removeprefix("www.") != domain:
            lead_at = next((i for i, s in enumerate(members) if announcing_place(s)), 0)
            members.insert(0, members.pop(lead_at))
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
        card["score"] = max(max(m["score"] for m in members), round(score(origins=card["origins"], classics=card["classics"], opened=card["opened"],
                                                       voices=len(names), days=days), 3))
        out.append(card)
    return out


# The follow test's labels (services/discover_reads.py): what can be followed, and what can't.
FOLLOWABLE = ("feed", "page")
UNFOLLOWABLE = ("headlines", "blocked", "other_feed")   # other_feed: a feed, but not of these pages


def _label(s: Mapping) -> Optional[str]:
    return (s.get("follow_test") or {}).get("label")


def section(s: Mapping) -> int:
    """0 tested followable, 1 tested and unfollowable as a feed, 2 untested."""
    label = _label(s)
    return 0 if label in FOLLOWABLE else 1 if label in UNFOLLOWABLE else 2


def not_channel(key: str, label: Optional[str]) -> bool:
    """A platform owner that is no channel: a model hub's, or one on a platform no source kind reads whose follow
    test found nothing."""
    from insight_core.utils.entity_originals import MODEL_HUBS   # entity_originals reads this module
    if "/" not in key:
        return False
    site = site_of(key.split("/", 1)[0])
    if site in MODEL_HUBS:
        return True
    return label in UNFOLLOWABLE and site not in KIND_PLATFORMS


def follow_url(url: str, platforms: Platforms = {}) -> Optional[str]:
    """What a page's "Follow" follows: on a platform its account; elsewhere its section, or the site's home."""
    key, _, platform = discover_address(url, platforms)
    if platform:
        return "https://" + key if key else None
    host = bare(url).partition("/")[0].lower()
    if not host:
        return None
    segs = path_segments(url)
    first = segs[0] if len(segs) >= 2 and not NUMBERISH.match(segs[0]) else ""
    return f"https://{host}/{first + '/' if first else ''}"


# The worker's judgement of a suggestion (source_judge), ahead of link volume within a section.
FIT_ORDER = {"follow": 0, "maybe": 1, None: 1, "skip": 2, "not_fit": 3}


def judged_follow(s: Mapping) -> bool:
    return s.get("fit") == "follow" and section(s) != 1


# The share of a row's linking sources you read (`reader_fit`), for rows the worker has not judged. Off by default
# (INSIGHT_DISCOVER_READER_FIT=1); READER_FIT_WEIGHT is NOT MEASURED (plan/issues/0239 says how).
READER_FIT_WEIGHT = 1.0


def reader_fit(linkers: Iterable[str], read: Iterable[str]) -> float:
    """Of `linkers`, the share you read (DiscoverRepository.read_sources); 0 when none. Pure."""
    linkers = set(linkers)
    return round(len(linkers & set(read)) / len(linkers), 3) if linkers else 0.0


def reader_fit_on() -> bool:
    import os
    return os.getenv("INSIGHT_DISCOVER_READER_FIT", "0") == "1"


def fit_score(s: Mapping, *, on: bool) -> float:
    """Its score; switched on, an unjudged one's score times 1 + READER_FIT_WEIGHT * its reader_fit."""
    if not on or s.get("fit") is not None:
        return s["score"]
    return s["score"] * (1 + READER_FIT_WEIGHT * float(s.get("reader_fit") or 0.0))


def order(found: Iterable[Mapping], *, reader: Optional[bool] = None) -> List[Mapping]:
    """Judged "follow" first, then by section, judgement, linked before unlinked, fit_score, key; the unfollowable
    section is marked `section: "unfollowable"`."""
    on = reader_fit_on() if reader is None else reader
    out = sorted(found, key=lambda s: (not judged_follow(s), section(s), FIT_ORDER.get(s.get("fit"), 1),
                                       not s.get("voices"), -fit_score(s, on=on), s["key"]))
    for s in out:
        if section(s) == 1:
            s["section"] = "unfollowable"   # type: ignore[index]
    return out

# ---- Discover --------------------------------------------------------------------------------


@dataclass
class Suggestion:
    key: str                         # a site (openai.com) or a platform account (x.com/nn_teacher)
    voices: List[str]                # the voices that link it
    articles: List[str]              # its article-like addresses linked
    links: int                       # every address of it linked
    addresses: Set[str] = field(default_factory=set)   # those addresses (its classics are counted by them)
    roundups: Set[str] = field(default_factory=set)    # the voices that link it only in roundups

    @property
    def weight(self) -> float:
        return len(self.voices) - len(self.roundups) / 2


def discover_address(url: str, platforms: Platforms = {},
                     channels: Mapping[str, str] = {}) -> Tuple[Optional[str], str, bool]:
    """(its key, its site, whether the site is a platform). On a platform the key is the account, none for a kind of
    page; a tweet is its author's; a video its read channel's (`channels`); on a data platform its owner; elsewhere
    the host. A function of the address and the platforms, so the database keeps it once per address."""
    if url in channels:
        return channels[url], "youtube.com", True
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
    """An article-like address, or a platform account's post."""
    host, _, rest = bare(url).partition("/")
    path = "/" + rest
    return is_article(url) or bool(TWEET.match(path)) or (
        site_of(host) in DISCOVER_PLATFORMS and bool(PLATFORM_POST.match(path) or BSKY_POST.match(path)))


def site_unit(host: str, publication_sites: Iterable[str] = frozenset()) -> str:
    """Its site, but on a site of publications its publication: following one newsletter hides no other."""
    host = publication_of(host.split("/", 1)[0])
    site = site_of(host)
    return host if site in set(publication_sites) else site


def discover_open(key: str, site: str, platform: bool, *, followed: Set[str], hidden: Set[str],
                  followed_accounts: Set[str], publication_sites: Iterable[str] = frozenset()) -> bool:
    """A key you neither follow nor hid: on a platform as that account, elsewhere as its site_unit."""
    if platform:
        return not (key in followed_accounts or key in hidden)
    return not (site_unit(key, publication_sites) in followed or key in hidden or site in hidden)


def suggestions(links: Iterable[Tuple[str, str, bool]], *, followed: Set[str], hidden: Set[str],
                followed_accounts: Set[str] = frozenset(), mirrors: Set[str] = frozenset(),
                platforms: Platforms = {}, mentioned: Set[str] = frozenset()) -> List[Suggestion]:
    """Sites and accounts 3+ of your voices link, in 2+ article-like pages that make 40%+ of their links, that you
    don't follow and did not hide; on a platform the unit is the account. A key a post @mentions (`mentioned`) needs
    only its voices. `links`: (voice or None for a self-link or Saved's, address, roundup?). Ordered by weight."""
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
        if len(voices) >= DISCOVER_MIN_VOICES and ((len(articles) >= DISCOVER_MIN_ARTICLES
                                                    and len(articles) >= DISCOVER_ARTICLE_SHARE * len(every))
                                                   or bool(every & set(mentioned)))
    ]
    return sorted(out, key=lambda s: (-s.weight, -len(s.voices), -len(s.articles), -s.links, s.key))


# ---- Discover: where your stories start --------------------------------------------


@dataclass
class Origin:
    story_id: str
    url: str                         # the outside page (stories.origin_url), else the origin post's address
    title: Optional[str]             # its link words, or the post's title; None: show the address
    source_id: Optional[str]         # the origin post's source; None: a page outside INSIGHT
    first_at: datetime
    voices: Dict[str, str] = field(default_factory=dict)   # the story's voices -> the source naming each
    own: bool = False                # an origin post on the site its source publishes on: held
    reddit_sources: Tuple[str, ...] = ()   # the Reddit sources of its voices that are a post's author
    at_post: bool = False            # a post is at its outside page's address: a page you saved

    @property
    def stored(self) -> bool:
        return self.source_id is not None or self.at_post


@dataclass
class Origins:
    suggest: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # key -> its stories
    missing: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # source -> its stories
    unnamed: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # youtube.com/watch -> them
    references: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # docs.example.com -> them


def discover_place(url: str, platforms: Platforms = {}, channels: Mapping[str, str] = {}) -> Optional[str]:
    """An account on a platform (None for none), elsewhere its host and section (anthropic.com/news)."""
    key, _, platform = discover_address(url, platforms, channels)
    section = "" if platform else section_of(url)
    return f"{key}/{section}" if key and section else key


def origins(roots: Iterable[Origin], *, followed: Set[str], held: Dict[str, str],
            mirrors: Set[str] = frozenset(), platforms: Platforms = {},
            publication_sites: Iterable[str] = frozenset(), channels: Mapping[str, str] = {}) -> Origins:
    """Where your stories start, each story once: at a held place nothing to suggest (a story the source misses when
    not stored); at a reference page a reference; at a site or account you don't follow a suggestion; elsewhere on a
    followed site never suggested (a missed story); on a page naming no account only listed."""
    out = Origins()
    pubs = frozenset(publication_sites)
    followers: Dict[str, str] = {}   # a followed site -> a source holding a place of it
    for place, source_id in sorted(held.items()):
        followers.setdefault(site_unit(place, pubs), source_id)
    for root in roots:
        key, site, platform = discover_address(root.url, platforms, channels)
        place = discover_place(root.url, platforms, channels)
        unit = site_unit(key or bare(root.url), pubs) if not platform else site
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
        elif platform or unit not in followed:
            out.suggest[key].append(root)
        elif not root.stored and unit in followers:
            out.missing[followers[unit]].append(root)
    return out


PAGES_WITHIN_DAYS = 30   # Discover's Pages: the stories of the last 30 days


def page_key_of(url: str) -> str:
    return "page:" + (bare(url) or url).lower()


def pages(started: Origins, *, since: datetime, hidden: Set[str]) -> List[Tuple[str, List[Origin], bool]]:
    """Discover's Pages: each unstored story root at a site or account you don't follow, or at a page naming none,
    as (address, its stories, names-no-account), by voices, stories, newest. Never an archive, an app's share link,
    a document, a reference page or a front page."""
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
    """The stamp of the rules behind discover_addresses rows: a rule change refills them, a refactor doesn't."""
    return fingerprint([(url, discover_address(url), discover_article(url)) for url in ADDRESSES] + platform_sample())


def platform_sample() -> List[Tuple[str, Tuple[Optional[str], str, bool]]]:
    platforms = {"hub.example": (), "forum.example": ("ru", "companies"), "social.example": MARKED_OWNERS}
    return [(url, discover_address(url, platforms)) for url in (
        "https://hub.example/ai-sage/a-model", "https://hub.example/en/a-model", "https://hub.example/an-owner/models",
        "https://forum.example/ru/companies/de/articles/1", "https://hub.example/@someone/posts/1",
        "https://social.example/@someone/1", "https://social.example/redirect/2/abc")]


ADDRESS_RULES = address_rules()


def address_stamp(platforms: Platforms) -> str:
    """ADDRESS_RULES with the platforms the data finds: a host that becomes or stops being one refills the rows."""
    return ADDRESS_RULES if not platforms else fingerprint([ADDRESS_RULES, sorted((h, list(p)) for h, p in platforms.items())])

__all__ = ["Suggestion", "suggestions", "discover_address", "discover_article", "discover_open", "discover_place",
           "find_platforms", "platform_rows", "platform_key", "is_self_link", "place_kind", "reference_address",
           "paper_address", "archive_address", "app_address", "document_address", "REFERENCE_KINDS", "score", "growth", "judged_follow", "order", "announcing_place", "site_unit", "reader_fit", "reader_fit_on", "fit_score", "READER_FIT_WEIGHT", "section", "language_segment", "platform_sample", "MARKED_OWNERS", "federation", "owner_domain", "one_card_per_domain", "own_names", "owner_words", "same_owner", "channel_names", "other_channel", "query_address", "listing_address", "not_channel", "follow_url", "KIND_PLATFORMS", "FOLLOWABLE", "UNFOLLOWABLE", "address_stamp",
           "Origin", "Origins", "origins", "address_rules", "ADDRESS_RULES"]
