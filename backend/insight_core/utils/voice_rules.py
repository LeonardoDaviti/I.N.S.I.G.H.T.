"""Voices (issue 0132 A, 0078): which sources look like one voice, each suggestion with its evidence. Pure functions
over plain data; services/voices_service.py loads the data (db/repo_voices.py) and keeps what the owner decides.

A suggestion is never applied without the owner. Two sources are suggested as one voice ("join") only by:
1. **the same address**: the same channel added twice (it also says "the same channel twice: disable one?");
2. **a standing link**: a links section or footer that links the other's profile in STANDING_SHARE of its posts, or
   STANDING_SHARE of its own posts linking the other when that is no hub (linked by over HUB_SHARE of sources), with
   some link back; a links section or footer link alone is enough in SECTION_SHARE of SECTION_MIN_POSTS+ posts (v10.6.1:
   fewer are citations), and so is any link (SOME_LINK) with a shared name;
3. **near-identical own posts** (5-word shingles, Jaccard COPY_JACCARD+, neither a repost) with a shared name;
4. **both official for the same maker** (the role rule's step 3, utils/source_roles.py; a hook another role rule
   can fill).
A shared name and nothing else is "possible", never a suggestion. **Platforms are never joined** (Reddit, Hacker
News, Saved, sites of MULTI_AUTHORS+ authors, aggregators): there the voice is the post's author.

Related voices (a company's staff, decision 1) are suggested from: one official and the other FOCUSED_SHARE+ about
the same maker; heavy reposting (RELATED_REPOSTS+ reposts of one's handle by the other). Each says "needs a bio"
until profiles exist (Part C).

Measured on the server copy of 2026-11-05 (the lab's sources_v1): 16 voices from 40 sources, all 16 right.
No list of known sites: platform address shapes only (utils/addresses.py's platforms).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import unquote, urlsplit

from insight_core.utils.addresses import PLATFORM_SITES, publication_of, site_of
from insight_core.utils.byline import RT_BY_TAG
from insight_core.utils.discover_rules import DISCOVER_PLATFORMS
from insight_core.utils.source_roles import FOCUSED_SHARE, Focus, Official, name_tokens

STANDING_SHARE = 0.3      # measured (sources_v1)
STANDING_MIN_POSTS = 2
STANDING_OWN_MIN = 3
SECTION_SHARE = 0.6        # v10.6.1: a profile or footer link alone joins only in most posts (a links section) ...
SECTION_MIN_POSTS = 5      # ... of at least 5 posts; 2 of 6 posts linking a site cite it (the owner, 2026-11-08)
SOME_LINK_SHARE = 0.05    # "some link": 2+ posts and 5%
SOME_LINK_MIN = 2
HUB_SHARE = 0.10          # a source linked by over 10% of sources (5 at least) is a hub
HUB_MIN = 5
COPY_JACCARD = 0.5        # 5-word shingles
COPY_SHINGLE = 5
COPY_MIN_WORDS = 15
SHARED_NAME_MAX_SOURCES = 6   # a name word held by at most 6 sources ...
SHARED_NAME_MIN = 5           # ... and 5+ letters long
NAME_SUFFIXES = frozenset({"ai", "hq", "dev", "io", "app", "labs", "blog", "news", "tv", "official", "team"})
MULTI_AUTHORS = 10
AGGREGATOR_MIN_POSTS = 10
AGGREGATOR_OWN_SHARE = 0.3
AGGREGATOR_MIN_KEYS = 10
RELATED_REPOSTS = 10
SAME_MAKER_SHARE = 0.3
CLOSE_MAKER_SHARE = 0.6       # both this much about one maker and linking each other: one voice
HOME_HOST_SHARE = 0.5         # a host holding half a source's posts is its own address
ALSO_WITHIN_HOURS = 72        # "Also on": one post on two channels of a voice within 72 hours

PLATFORM_KINDS = ("reddit", "hn", "saved")
_X = PLATFORM_SITES["x"]
_TG = PLATFORM_SITES["telegram"]
_YT = PLATFORM_SITES["youtube"]
_REDDIT = PLATFORM_SITES["reddit"]
_X_NOT_ACCOUNT = frozenset({"i", "intent", "search", "home", "hashtag", "share", "explore", "settings", "messages",
                            "rss", "pic", "status"})
_FEED_END = re.compile(r"\.(atom|rss|xml)$")
WORD = re.compile(r"\w+", re.U)
URL = re.compile(r"https?://[^\s<>\"')\]]+")


def address_key(url: Optional[str]) -> Tuple[Optional[str], bool]:
    """(key, is_profile): the owner an address belongs to, as a platform's address shape says it (x:<user>,
    tg:<channel>, yt:<handle>, ytc:<channel id>, r:<sub>, ru:<user>, <platform site>/<account>), else its site's
    publication (site:<host>); is_profile: the bare profile or home page, not a post."""
    try:
        parts = urlsplit(url if "//" in (url or "") else "//" + (url or ""))
        host = (parts.hostname or "").lower()
    except ValueError:
        return None, False
    host = host.removeprefix("www.").removeprefix("m.")
    segs = [unquote(s) for s in parts.path.split("/") if s]
    if not host:
        return None, False
    if host in _X or host.endswith(".twitter.com"):
        if not segs or segs[0].lower() in _X_NOT_ACCOUNT:
            return None, False
        return "x:" + segs[0].lower().lstrip("@"), len(segs) == 1 or (len(segs) == 2 and segs[1] == "rss")
    if host in _TG:
        rest = [s for s in segs if s not in ("s", "rss", "media")]
        return ("tg:" + rest[0].lower(), len(rest) == 1) if rest else (None, False)
    if host in _YT:
        if segs and segs[0].startswith("@"):
            return "yt:" + segs[0][1:].lower(), len(segs) <= 2
        if len(segs) >= 2 and segs[0] in ("c", "user"):
            return "yt:" + segs[1].lower(), True
        if len(segs) >= 2 and segs[0] == "channel":
            return "ytc:" + segs[1].lower(), True
        return None, False
    if host in _REDDIT or host.endswith(".reddit.com"):
        if len(segs) >= 2 and segs[0] == "r":
            return "r:" + segs[1].lower(), len(segs) == 2
        if len(segs) >= 2 and segs[0] in ("u", "user"):
            return "ru:" + segs[1].lower(), len(segs) == 2
        return None, False
    site = site_of(host)
    if site in DISCOVER_PLATFORMS:   # a platform whose first path segment is the account (github.com/<owner>)
        if not segs:
            return None, False
        return site + "/" + _FEED_END.sub("", segs[0].lower().lstrip("@")), len(segs) == 1
    return "site:" + publication_of(host), not segs


def account_address_key(account: Optional[str]) -> Optional[str]:
    """A source's followed account (repo_stories.source_account: t.me/<c>, x.com/<u>, youtube.com/channel/<id>,
    reddit.com/r/<s>) as an address_key."""
    if not account:
        return None
    return address_key("https://" + account)[0]


def site_label(host: str) -> str:
    """A site's own word: the subdomain on a hosting platform, else the label before its ending (co.uk-like kept)."""
    host = (host or "").lower().removeprefix("www.")
    labels = site_of(host).split(".")
    co_uk = len(labels) >= 3 and len(labels[-2]) <= 3 and len(labels[-1]) == 2
    if len(labels) >= 3:
        return labels[-3] if co_uk else labels[0]
    return labels[-2] if len(labels) >= 2 else host


def shingles(title: Optional[str], text: Optional[str]) -> Optional[Set[int]]:
    """A post's 5-word shingles (hashed), addresses and a retweet's "RT by @x:" aside; None under COPY_MIN_WORDS words."""
    joined = f"{title or ''} {text or ''}"
    joined = re.sub("^" + RT_BY_TAG + r"\s*", "", joined)   # Byline's tag, any space after it
    words = WORD.findall(URL.sub(" ", joined.lower()))
    if len(words) < COPY_MIN_WORDS:
        return None
    return {hash(" ".join(words[i:i + COPY_SHINGLE])) for i in range(len(words) - COPY_SHINGLE + 1)}


def jaccard(a: Set[int], b: Set[int]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


@dataclass
class Channel:
    """What the rules read of one source."""

    id: str
    kind: str                         # post_links.source_kind: site, x, telegram, youtube, reddit, hn, saved
    name: str
    handle: str                       # its account's name, or its site's host
    keys: Set[str] = field(default_factory=set)   # the addresses that are this source
    posts: int = 0
    own: int = 0                      # posts that are not reposts
    authors: int = 0                  # distinct named authors of its posts (a site of many authors is a platform)
    own_key_share: float = 1.0        # share of its posts at its own addresses (an aggregator's are elsewhere)
    other_keys: int = 0               # distinct other owners its posts are at
    channel_title: Optional[str] = None
    enabled: bool = True
    voice_id: Optional[str] = None    # its confirmed voice

    @property
    def tokens(self) -> Set[str]:
        """Its names' words (source_roles.name_tokens): its name, its handle or its site's label, its channel's title."""
        made = (self.name, self.handle, self.kind, self.channel_title)
        if getattr(self, "_tokens", (None,))[0] != made:
            self._tokens = (made, name_tokens(self.name, self.handle if self.kind != "site" else site_label(self.handle),
                                              self.channel_title))
        return self._tokens[1]


def platform_of(c: Channel) -> Optional[str]:
    """Why a source is a platform (never joined), or None: Reddit, Hacker News or Saved; MULTI_AUTHORS+ authors; an
    aggregator (most posts at other owners' addresses, many of them)."""
    if c.kind in PLATFORM_KINDS:
        return c.kind
    if c.authors >= MULTI_AUTHORS:
        return "many authors"
    if c.kind == "site" and c.posts >= AGGREGATOR_MIN_POSTS and c.own_key_share < AGGREGATOR_OWN_SHARE \
            and c.other_keys >= AGGREGATOR_MIN_KEYS:
        return "aggregator"
    return None


@dataclass
class PairCounts:
    """What A's posts say of B: posts linking B (own posts too), its header/footer links (boilerplate), bare profile
    links, reposts of B's tweets, near-identical own posts; with example posts."""

    link_posts: int = 0
    link_posts_own: int = 0
    bp_posts: int = 0
    profile_posts: int = 0
    reposts: int = 0
    copies_own: int = 0
    examples: Dict[str, List[str]] = field(default_factory=lambda: defaultdict(list))

    def example(self, what: str, post_id: str) -> None:
        if len(self.examples[what]) < 3:
            self.examples[what].append(post_id)


def shared_names(a: Channel, b: Channel, held_by: Mapping[str, int]) -> Set[str]:
    """The distinctive names two sources share: a word of SHARED_NAME_MIN+ letters held by at most
    SHARED_NAME_MAX_SOURCES sources, or one name the other's start plus a generic ending (lab / labai)."""
    ta, tb = a.tokens, b.tokens
    out = {t for t in ta & tb if held_by.get(t, 0) <= SHARED_NAME_MAX_SOURCES and len(t) >= SHARED_NAME_MIN}
    for t in ta:
        for u in tb:
            lo, hi = (t, u) if len(t) <= len(u) else (u, t)
            if t != u and len(lo) >= SHARED_NAME_MIN and hi.startswith(lo) and hi[len(lo):] in NAME_SUFFIXES \
                    and held_by.get(lo, 0) <= SHARED_NAME_MAX_SOURCES:
                out.add(lo)
    return out


def link_strength(a: Channel, b: Channel, e: Optional[PairCounts], hub: bool) -> Tuple[int, str, str]:
    """(2, line, what) for a standing link from A to B, (1, ...) for some link, (0, "", "") for none."""
    n = max(1, a.own)
    if not e:
        return 0, "", ""
    if e.profile_posts >= STANDING_MIN_POSTS and e.profile_posts / n >= STANDING_SHARE:
        return 2, f"{a.name} links {b.name}'s profile in {e.profile_posts}/{n} posts", "profile"
    if e.bp_posts >= STANDING_MIN_POSTS and e.bp_posts / n >= STANDING_SHARE and not hub:
        return 2, f"{a.name}'s header or footer links {b.name} in {e.bp_posts}/{n} posts", "footer"
    if e.link_posts_own >= STANDING_OWN_MIN and e.link_posts_own / n >= STANDING_SHARE and not hub:
        return 2, f"{a.name} links {b.name} in {e.link_posts_own}/{n} own posts", "links"
    if e.link_posts_own >= SOME_LINK_MIN and e.link_posts_own / n >= SOME_LINK_SHARE:
        return 1, f"{a.name} links {b.name} in {e.link_posts_own}/{n} own posts", "some"
    return 0, "", ""


@dataclass
class Verdict:
    a: str
    b: str
    verdict: str                      # same_channel | join | possible | related
    evidence: List[Dict[str, Any]]    # [{rule, line, posts}]
    names: List[str] = field(default_factory=list)


def judge(channels: Mapping[str, Channel], counts: Mapping[Tuple[str, str], PairCounts],
          officials: Mapping[str, Official], focus: Mapping[str, Focus]) -> List[Verdict]:
    """Every pair of sources with evidence, judged (the module's rules), first by ids."""
    held_by: Counter = Counter(t for c in channels.values() for t in c.tokens)
    indeg: Counter = Counter(b for (a, b), e in counts.items() if e.link_posts_own >= 1)
    hub_at = max(HUB_MIN, int(HUB_SHARE * len(channels)))
    platforms = {i: platform_of(c) for i, c in channels.items()}
    pairs: Set[Tuple[str, str]] = {tuple(sorted(k)) for k in counts if k[0] in channels and k[1] in channels}
    by_key: Dict[str, List[str]] = defaultdict(list)
    for i, c in channels.items():
        for k in c.keys:
            by_key[k].append(i)
    pairs |= {(a, b) for ids in by_key.values() for a in ids for b in ids if a < b}
    ids = sorted(channels)
    tokens = {i: channels[i].tokens for i in ids}
    by_token: Dict[str, List[str]] = defaultdict(list)
    for i in ids:
        for t in tokens[i]:
            by_token[t].append(i)
    for t, holders in by_token.items():
        if len(holders) <= SHARED_NAME_MAX_SOURCES:
            pairs |= {(a, b) for a in holders for b in holders if a < b}
    for i in ids:   # a name the start of another's (lab / labai)
        for t in tokens[i]:
            if len(t) < SHARED_NAME_MIN:
                continue
            for suffix in NAME_SUFFIXES:
                for j in by_token.get(t + suffix, ()):
                    if j != i:
                        pairs.add(tuple(sorted((i, j))))
    by_maker: Dict[str, List[str]] = defaultdict(list)
    for i, o in officials.items():
        if i in channels:
            by_maker[o.maker].append(i)
    pairs |= {(a, b) for ids_ in by_maker.values() for a in ids_ for b in ids_ if a < b}
    for i, f in focus.items():   # one official, the other focused on its maker: related
        if i in channels and f.share >= FOCUSED_SHARE:
            pairs |= {tuple(sorted((i, j))) for j in by_maker.get(f.maker, ()) if j != i}

    def section(e: Optional[PairCounts], c: Channel, strength: int, kind: str) -> bool:
        """A profile or footer link alone joins as a links section: in SECTION_SHARE of SECTION_MIN_POSTS+ posts."""
        if strength != 2 or kind not in ("profile", "footer") or not e:
            return False
        n, hits = max(1, c.own), (e.profile_posts if kind == "profile" else e.bp_posts)
        return n >= SECTION_MIN_POSTS and hits / n >= SECTION_SHARE

    out = []
    for a, b in sorted(pairs):
        ca, cb = channels[a], channels[b]
        ab, ba = counts.get((a, b)), counts.get((b, a))
        same = sorted(ca.keys & cb.keys)
        names = sorted(shared_names(ca, cb, held_by))
        pa, wa, ka = link_strength(ca, cb, ab, indeg[b] > hub_at)
        pb, wb, kb = link_strength(cb, ca, ba, indeg[a] > hub_at)
        copies = (ab.copies_own if ab else 0)
        reposts = (ab.reposts if ab else 0) + (ba.reposts if ba else 0)
        oa, ob = officials.get(a), officials.get(b)
        both_official = bool(oa and ob and oa.maker == ob.maker)
        fa, fb = focus.get(a), focus.get(b)
        evidence: List[Dict[str, Any]] = []

        def add(rule: str, line: str, posts: Iterable[str] = ()) -> None:
            evidence.append({"rule": rule, "line": line, "posts": list(posts)[:3]})
        if same:
            add("same_address", "the same address: " + ", ".join(same) + " (the same channel twice: disable one?)")
        if pa:
            add("standing_link" if pa == 2 else "some_link", wa, (ab.examples.get("profile") or ab.examples.get("bp")
                                                                   or ab.examples.get("own") or []) if ab else [])
        if pb:
            add("standing_link" if pb == 2 else "some_link", wb, (ba.examples.get("profile") or ba.examples.get("bp")
                                                                   or ba.examples.get("own") or []) if ba else [])
        if copies:
            add("copies", f"{copies} near-identical own posts", ab.examples.get("copies", []) if ab else [])
        if names:
            add("shared_name", "shared name " + "/".join(names))
        if both_official:
            add("both_official", f"both official for '{oa.maker}' ({oa.line}; {ob.line})", (*oa.posts[:2], *ob.posts[:1]))
        if reposts:
            add("reposts", f"{reposts} reposts between them", [*(ab.examples.get("reposts", []) if ab else []),
                                                                *(ba.examples.get("reposts", []) if ba else [])])
        one_official_focused = None
        for o, f, other in ((oa, fb, cb), (ob, fa, ca)):
            if o and f and f.maker == o.maker and f.share >= FOCUSED_SHARE and not (oa and ob):
                one_official_focused = f"{other.name}: {f.share:.0%} of {f.n} read posts about '{o.maker}', the other's own maker"
        if one_official_focused:
            add("official_and_focused", one_official_focused + " (needs a bio)")
        if same:
            verdict = "same_channel"
        elif platforms[a] or platforms[b]:
            continue   # platforms are never joined: their voice is the post's author
        elif (names and (pa or pb or copies)) or (pa == 2 and pb >= 1) or (pb == 2 and pa >= 1) \
                or section(ab, ca, pa, ka) or section(ba, cb, pb, kb) or both_official \
                or (fa and fb and fa.maker == fb.maker and fa.share >= CLOSE_MAKER_SHARE and fb.share >= CLOSE_MAKER_SHARE
                    and pa and pb):
            verdict = "join"
        elif one_official_focused or reposts >= RELATED_REPOSTS:
            verdict = "related"
            if reposts >= RELATED_REPOSTS and not one_official_focused:
                evidence[-1]["line"] += " (needs a bio)"
        elif names and not (pa or pb or copies or reposts):
            verdict = "possible"
        else:
            continue
        out.append(Verdict(a, b, verdict, evidence, names))
    return out


def groups(verdicts: Iterable[Verdict], *, joined: Mapping[str, Optional[str]] = {},
           rejected: Iterable[Tuple[str, str]] = ()) -> List[List[str]]:
    """The suggested voices: sources joined by same_channel and join verdicts (a pair the owner said is not the same
    never joins), each 2+ sources, at least one not yet in that voice; sorted members, by first member."""
    no = {tuple(sorted(p)) for p in rejected}
    parent: Dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for v in verdicts:
        if v.verdict in ("same_channel", "join") and (v.a, v.b) not in no:
            parent[find(v.a)] = find(v.b)
    by_root: Dict[str, List[str]] = defaultdict(list)
    for x in list(parent):
        by_root[find(x)].append(x)
    out = []
    for members in by_root.values():
        if len(members) < 2:
            continue
        voices = {joined.get(m) for m in members}
        if len(voices) == 1 and None not in voices:
            continue   # already one confirmed voice
        out.append(sorted(members))
    return sorted(out)


# ---- channel profiles (issue 0132 C2) ---------------------------------------------------------------------
# A profile (ingestion/profiles.py, kept by migration 0086) says who a channel is: its website field and the
# accounts it links. Not measured yet (the server has fetched none): the thresholds are the spec's words.
PROFILE_MAX_LINKED = 5          # a profile linking more followed sources is a directory: its links say no "who"
VERDICT_ORDER = {"possible": 0, "related": 1, "join": 2, "same_channel": 3}
_FORMER = re.compile(r"(?:\bex[-\s]?|\bformer(?:ly)?\s+(?:at\s+)?|\bprev(?:iously)?\.?\s+(?:at\s+)?"
                     r"|\balum(?:nus|ni)?\s+(?:of\s+)?)$", re.I)
_BIO_AT = re.compile(r"(?:\bworks?\s+(?:at|for)|\bworking\s+(?:at|for)|\bemployed\s+(?:at|by)"
                     r"|\b(?:engineer|researcher|scientist|editor|reporter|writer|developer|designer|manager|director"
                     r"|founder|co-?founder|ceo|cto|head|lead|staff|member|intern|fellow|advocate|evangelist|pm)\b"
                     r"[^.|\n@]{0,40}?(?:\bat\b|@))\s*@?([\w.-]{2,40})", re.I)
_BIO_HANDLE = re.compile(r"(?<![\w@./])@([A-Za-z0-9_]{2,32})\b")


def profile_links(profile: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """(address, where) a profile links: its website field first ("website field"), then the accounts and
    addresses its bio and page link ("linked account" on a platform, else "link")."""
    out: List[Tuple[str, str]] = []
    seen: Set[str] = set()
    site = profile.get("website")
    for url in ([site] if site else []) + list(profile.get("links") or []):
        if not url or url in seen:
            continue
        seen.add(url)
        key = address_key(url)[0] or ""
        where = "website field" if url == site else (
            "linked account" if ":" in key and not key.startswith("site:") else "link")
        out.append((url, where))
    return out


def _evidence_profile(source_id: str, profile: Mapping[str, Any]) -> Dict[str, Any]:
    return {"source": source_id, "url": profile.get("url"), "fetched_at": profile.get("fetched_at"),
            "kind": profile.get("kind")}


def bio_names(bio: Optional[str], other: Channel, held_by: Mapping[str, int]) -> Optional[str]:
    """The words of a bio that name `other` as where its writer works ("works at X", "engineer at @x", "@x" for an
    account of it), None when it doesn't; "ex-", "former" and "previously" are not working there."""
    if not bio:
        return None
    own_handles = {k.split(":", 1)[1] for k in other.keys if k.startswith(("x:", "tg:", "yt:"))}
    tokens = {t for t in other.tokens if held_by.get(t, 0) <= SHARED_NAME_MAX_SOURCES}

    def names(word: str) -> bool:
        w = word.lower().strip(".-_")
        return bool(w) and (w in own_handles or w in tokens or re.sub(r"[^0-9a-z]+", "", w) in tokens)

    def former(start: int) -> bool:
        return bool(_FORMER.search(bio[max(0, start - 20):start]))
    for m in _BIO_AT.finditer(bio):
        if names(m.group(1)) and not former(m.start()):
            return bio[max(0, m.start() - 10):m.end() + 10].strip()
    for m in _BIO_HANDLE.finditer(bio):
        if m.group(1).lower() in own_handles and not former(m.start()):
            return bio[max(0, m.start() - 20):m.end() + 10].strip()
    return None


def profile_verdicts(channels: Mapping[str, Channel], profiles: Mapping[str, Mapping[str, Any]],
                     counts: Mapping[Tuple[str, str], PairCounts], held_by: Mapping[str, int]) -> List[Verdict]:
    """What profiles say of pairs of followed sources:
    - **profile_link**: A's profile (its website field, a linked account, a link) is B's address: one voice with a
      link back (B's profile or B's posts link A) or a shared name, else related; a profile linking more than
      PROFILE_MAX_LINKED followed sources is a directory and says nothing. Platforms are never joined.
    - **profile_bio**: A's bio names B as where A works ("works at", "@company"): related (staff, not a beat writer).
    Each with the profile as its evidence."""
    key_to: Dict[str, Set[str]] = defaultdict(set)
    for sid, c in channels.items():
        for k in c.keys:
            key_to[k].add(sid)
    links: Dict[Tuple[str, str], Tuple[str, str]] = {}
    for a, prof in profiles.items():
        if a not in channels or platform_of(channels[a]):
            continue
        hits: Dict[str, Tuple[str, str]] = {}
        for url, where in profile_links(prof):
            for b in key_to.get(address_key(url)[0] or "", ()):
                if b != a and b not in hits:
                    hits[b] = (url, where)
        if len(hits) <= PROFILE_MAX_LINKED:
            for b, hit in hits.items():
                links[(a, b)] = hit
    out: Dict[Tuple[str, str], Verdict] = {}
    for (a, b), (url, where) in sorted(links.items()):
        ca, cb = channels[a], channels[b]
        if platform_of(cb):
            continue
        pair = tuple(sorted((a, b)))
        back_profile = (b, a) in links
        back_posts = bool(counts.get((b, a)) and counts[(b, a)].link_posts)
        names = sorted(shared_names(ca, cb, held_by))
        line = f"{ca.name}'s profile links {cb.name} ({where}: {url})"
        if back_profile:
            line += f"; {cb.name}'s profile links back"
        elif back_posts:
            line += f"; {cb.name}'s posts link back"
        if names:
            line += "; shared name " + "/".join(names)
        same = back_profile or back_posts or bool(names)
        if not same:
            line += " (no link back nor shared name: related)"
        ev = {"rule": "profile_link", "line": line, "posts": [], "profile": _evidence_profile(a, profiles[a])}
        verdict = "join" if same else "related"
        v = out.get(pair)
        if v is None:
            out[pair] = Verdict(pair[0], pair[1], verdict, [ev], names)
        else:
            v.evidence.append(ev)
            if VERDICT_ORDER[verdict] > VERDICT_ORDER[v.verdict]:
                v.verdict = verdict
    for a, prof in profiles.items():   # the bio naming where its writer works
        if a not in channels or platform_of(channels[a]) or not prof.get("bio"):
            continue
        for b, cb in channels.items():
            if b == a or platform_of(cb):
                continue
            said = bio_names(prof.get("bio"), cb, held_by)
            if not said:
                continue
            pair = tuple(sorted((a, b)))
            ev = {"rule": "profile_bio", "line": f"{channels[a].name}'s bio names {cb.name}: “{said}” "
                                                 "(staff, not a beat writer)", "posts": [],
                  "profile": _evidence_profile(a, prof)}
            v = out.get(pair)
            if v is None:
                out[pair] = Verdict(pair[0], pair[1], "related", [ev], [])
            else:
                v.evidence.append(ev)
    return [out[k] for k in sorted(out)]


def with_profiles(verdicts: Sequence[Verdict], extra: Sequence[Verdict], channels: Mapping[str, Channel],
                  profiles: Mapping[str, Mapping[str, Any]], held_by: Mapping[str, int]) -> List[Verdict]:
    """The rules' verdicts with the profiles' added: a pair's evidence joined, its verdict the stronger (same channel,
    join, related, possible). A related pair whose side has a bio not naming the other says so: a beat writer,
    not staff."""
    by: Dict[Tuple[str, str], Verdict] = {(v.a, v.b): Verdict(v.a, v.b, v.verdict, list(v.evidence), list(v.names))
                                          for v in verdicts}
    for e in extra:
        v = by.get((e.a, e.b))
        if v is None:
            by[(e.a, e.b)] = e
            continue
        v.evidence.extend(e.evidence)
        if VERDICT_ORDER[e.verdict] > VERDICT_ORDER[v.verdict]:
            v.verdict = e.verdict
    for v in by.values():
        if v.verdict != "related" or any(e["rule"] in ("profile_bio", "profile_link") for e in v.evidence):
            continue
        for x, y in ((v.a, v.b), (v.b, v.a)):
            prof = profiles.get(x)
            if prof and prof.get("bio") and x in channels and y in channels \
                    and not bio_names(prof["bio"], channels[y], held_by):
                v.evidence.append({"rule": "profile_bio", "line": f"{channels[x].name}'s bio does not name "
                                   f"{channels[y].name}: a beat writer, not staff", "posts": [],
                                   "profile": _evidence_profile(x, prof)})
    return [by[k] for k in sorted(by)]


def address_of_key(key: str) -> Optional[str]:
    """An address_key as the address the Add-source flow (the feed finder) starts from."""
    if key.startswith("site:"):
        return "https://" + key[5:]
    if ":" in key:
        kind, _, rest = key.partition(":")
        return {"x": f"https://x.com/{rest}", "tg": f"https://t.me/{rest}", "yt": f"https://www.youtube.com/@{rest}",
                "ytc": f"https://www.youtube.com/channel/{rest}"}.get(kind) if rest else None
    return f"https://{key}" if "/" in key else None


def _key_channel(key: str) -> Optional[Channel]:
    """A channel nobody follows, as the name rules read it: its account's name, or its site's label."""
    if key.startswith(("r:", "ru:")):
        return None   # Reddit's are everyone's
    if key.startswith("site:"):
        host = key[5:]
        return Channel(id="key:" + key, kind="site", name=site_label(host), handle=host)
    if ":" in key:
        kind, _, rest = key.partition(":")
        if kind not in ("x", "tg", "yt", "ytc"):
            return None
        return Channel(id="key:" + key, kind={"x": "x", "tg": "telegram"}.get(kind, "youtube"), name=rest, handle=rest)
    if "/" in key:
        return Channel(id="key:" + key, kind="site", name=key.split("/", 1)[1], handle=key.split("/", 1)[1])
    return None


def _is_account(key: str) -> bool:
    """A platform account (x:, tg:, yt:, ytc:, github.com/<owner>), not a site's home."""
    return not key.startswith("site:")


def platform_label(key: str) -> str:
    if key.startswith("site:"):
        return "site"
    if ":" in key:
        return {"x": "X", "tg": "Telegram", "yt": "YouTube", "ytc": "YouTube"}.get(key.split(":", 1)[0], "")
    return key.split("/", 1)[0]


def not_followed(channels: Mapping[str, Channel], profiles: Mapping[str, Mapping[str, Any]],
                 own_links: Mapping[Tuple[str, str], Tuple[int, List[str]]], discover: Sequence[Mapping[str, Any]],
                 held_by: Mapping[str, int]) -> Dict[str, List[Dict[str, Any]]]:
    """A source's other channels you don't follow (issue 0132 C2, the owner 2026-11-08), each with why; never added
    without the owner (the page's Add opens the feed finder):
    - **profile**: its profile's website field or linked accounts (a profile linking over PROFILE_MAX_LINKED
      addresses nobody follows is a directory: none);
    - **own_links**: its own posts link the channel's bare profile address with a shared name, or, an account, in a
      links section (STANDING_SHARE of 2+ own posts); never its own site's other hosts;
    - **discover**: a Discover candidate that shares its name, or that Discover itself calls this source's other
      channel ("also <source>'s"); one its own posts' links listed says Discover agrees.
    Platforms (Reddit, Hacker News, Saved, many authors, aggregators) list none; Reddit's addresses are never one.
    Returns source id -> [{key, url, label, platform, why [{rule, line, posts}]}], sorted by key."""
    followed = {k for c in channels.values() for k in c.keys}
    found: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    pseudo: Dict[str, Optional[Channel]] = {}

    def channel_of(key: str) -> Optional[Channel]:
        if key not in pseudo:
            pseudo[key] = _key_channel(key)
        return pseudo[key]

    def add(sid: str, key: str, rule: str, line: str, posts: Sequence[str] = ()) -> None:
        url = address_of_key(key)
        if channel_of(key) is None or url is None or key in followed or sid not in channels \
                or platform_of(channels[sid]):
            return
        if key.startswith("site:") and site_of(key[5:]) in {site_of(k[5:]) for k in channels[sid].keys
                                                             if k.startswith("site:")}:
            return   # its own site's other host (trust.<its site>): no other channel
        entry = found[sid].setdefault(key, {"key": key, "url": url, "label": key.split(":", 1)[-1],
                                            "platform": platform_label(key), "why": []})
        if not any(w["rule"] == rule for w in entry["why"]):
            entry["why"].append({"rule": rule, "line": line, "posts": list(posts)[:3]})

    for sid, prof in profiles.items():
        outside = [(url, where, address_key(url)[0]) for url, where in profile_links(prof)]
        outside = [(u, w, k) for u, w, k in outside if k and k not in followed]
        if len({k for _, _, k in outside}) > PROFILE_MAX_LINKED:
            continue
        for url, where, key in outside:
            add(sid, key, "profile", f"its profile links it ({where})")
    for (sid, key), (n, posts) in own_links.items():
        c, other = channels.get(sid), channel_of(key)
        if c is None or other is None or key in followed:
            continue
        own = max(1, c.own)
        # An account in a links section (STANDING_SHARE of 2+ own posts); a site's home only with a shared name: a
        # post linking a site's home cites it, and a video description's repeated sites are its sponsors (measured
        # on the server copy, 2026-11-08: a tool's site, a newspaper's, a channel's 18 sponsors in 18 of 18 videos).
        section = _is_account(key) and n >= STANDING_MIN_POSTS and n / own >= STANDING_SHARE
        if section or shared_names(c, other, held_by):
            add(sid, key, "own_links", f"its own posts link it ({n}/{own})", posts)
    by_token: Dict[str, List[str]] = defaultdict(list)
    for sid, c in channels.items():
        for t in c.tokens:
            by_token[t].append(sid)
    linked_by: Dict[str, List[Tuple[str, int, List[str]]]] = defaultdict(list)
    for (sid, k), (n, posts) in own_links.items():
        linked_by[k].append((sid, n, posts))
    for cand in discover:
        key = address_key(cand.get("url") or ("https://" + str(cand.get("key") or "")))[0]
        other = channel_of(key) if key else None
        if other is None:
            continue
        if cand.get("source_id"):
            add(str(cand["source_id"]), key, "discover", f"Discover: also {cand.get('of') or 'this source'}'s")
        for sid in sorted({s for t in other.tokens for s in by_token.get(t, ())}):
            names = shared_names(channels[sid], other, held_by)
            if names:
                add(sid, key, "discover", "Discover suggests it; it shares the name " + "/".join(sorted(names)))
        for sid, n, posts in linked_by.get(key, ()):   # its own posts' links listed it: Discover agrees
            if key in found.get(sid, {}):
                add(sid, key, "discover", f"Discover suggests it too; its own posts link it ({n})", posts)
    return {sid: one_per_site(entries) for sid, entries in sorted(found.items())}


def one_per_site(entries: Mapping[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One row per site (measured on the server copy, 2026-11-08: one voice's 12 tool subdomains were 12 rows): its
    root host's when listed, else its first host's, with the other hosts' reasons and how many there are."""
    by_site: Dict[str, List[str]] = defaultdict(list)
    out: List[Dict[str, Any]] = []
    for k in sorted(entries):
        if k.startswith("site:"):
            by_site[site_of(k[5:])].append(k)
        else:
            out.append(entries[k])
    for site, keys in by_site.items():
        main = "site:" + site if "site:" + site in keys else keys[0]
        row = {**entries[main], "why": list(entries[main]["why"])}
        for k in keys:
            if k != main:
                row["why"].extend(w for w in entries[k]["why"] if w["rule"] not in {x["rule"] for x in row["why"]})
        if len(keys) > 1:
            row["hosts"] = len(keys)
        out.append(row)
    return sorted(out, key=lambda e: e["key"])


__all__ = ["address_key", "account_address_key", "site_label", "shingles", "jaccard", "Channel", "PairCounts", "Verdict",
           "platform_of", "shared_names", "link_strength", "judge", "groups", "ALSO_WITHIN_HOURS", "HOME_HOST_SHARE",
           "profile_links", "profile_verdicts", "with_profiles", "bio_names", "not_followed", "address_of_key"]
