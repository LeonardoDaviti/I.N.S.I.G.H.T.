"""Voices (issue 0132 A, 0078): which sources look like one voice, each suggestion with its evidence. Pure functions
over plain data; services/voices_service.py loads the data (db/repo_voices.py) and keeps what the owner decides.

A suggestion is never applied without the owner. Two sources are suggested as one voice ("join") only by:
1. **the same address**: the same channel added twice (it also says "the same channel twice: disable one?");
2. **a standing link**: a links section or footer that links the other's profile in STANDING_SHARE of its posts, or
   STANDING_SHARE of its own posts linking the other when that is no hub (linked by over HUB_SHARE of sources), with
   some link back; a links section or footer link alone is enough, and so is any link (SOME_LINK) with a shared name;
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
from insight_core.utils.discover_rules import DISCOVER_PLATFORMS
from insight_core.utils.source_roles import FOCUSED_SHARE, Focus, Official, name_tokens

STANDING_SHARE = 0.3      # measured (sources_v1)
STANDING_MIN_POSTS = 2
STANDING_OWN_MIN = 3
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
    joined = re.sub(r"^RT by @\w+:\s*", "", joined)
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
                or (pa == 2 and ka in ("profile", "footer")) or (pb == 2 and kb in ("profile", "footer")) or both_official \
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


__all__ = ["address_key", "account_address_key", "site_label", "shingles", "jaccard", "Channel", "PairCounts", "Verdict",
           "platform_of", "shared_names", "link_strength", "judge", "groups", "ALSO_WITHIN_HOURS", "HOME_HOST_SHARE"]
