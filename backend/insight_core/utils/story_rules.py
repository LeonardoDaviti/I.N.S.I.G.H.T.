"""One story, many sources (issue 0050): the rules that join posts into stories, each post's
role, a story's voices, and Discover's suggestions. Pure functions over plain data: the story
job (services/stories_service.py) loads the posts and writes what these return.

Ported from the prototype (`plan/research/dedup-prototype/stories.py`, `rank.py`, `report.py`),
the reference the real code reproduces. The thresholds are here, in one place.

- A **voice** is one site for websites (its registrable domain), one channel or account for
  Telegram, X and YouTube, and on Reddit the person who posted: a story's voices count people.
  Joining by links, and telling a copy, go by where a post was said (`place`): the voice, but
  on Reddit the subreddit, so one person posting a link to two subreddits makes one story of
  one voice (a copy), as the prototype does. Posts of one place never join through links.
- Posts join when they share a text (the same content_hash, 120+ characters, within 30 days),
  a title (5+ words, within 7 days), an outside page linked by 2+ voices within 72 hours, or one
  cites a stored post of another voice within 72 hours. A post with 3+ anchors is a roundup: it
  joins only the story of its first and mentions the others. Home and profile pages join nothing.
- Two posts at one address (0049 keeps them apart when their titles differ) join (`address`).
- A story is a group of posts from 2+ sources, keyed by its first post.
- **A story is a tree (issue 0064):** each post gets a parent, the post (or the outside page) it
  came from, or none for the origin, by evidence in order of certainty, never one signal alone:
  1. `address`: a post at an address on its source's own site is that address's origin; the
     other posts at the address hang from it, and a link to the address is a link to it;
  2. `citation`: a post linking another post of the story, or a page outside INSIGHT 2+ of its
     posts link (not as a roundup's mentions), is its child, whatever the dates say; the more
     voices link a node, the more it is the parent (in-degree);
  3. `copy`: the same text or title, the earlier time the parent, when both times are trustworthy;
  4. `time`: the posts 1-3 leave unrelated hang from the origin, `time` when both times are
     trustworthy (a time of day, not a Saved page, not a page updated since) and 10+ minutes
     apart, the origin first; else `none` (no claim of order).
  The origin is the root linked by the most voices, a post at its own site first, then the
  earlier trustworthy time. One parent per post, no cycles. Mark X adds `meaning` and
  `attribution` to the reasons without changing the shape.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.utils.post_links import (PLATFORM_SITES, account_key, bare, host_of, is_article, is_home, site_of,
                                          titled_link_text)

SAME_TEXT_WITHIN = timedelta(days=30)
SAME_TEXT_MIN_CHARS = 120
SAME_TITLE_WITHIN = timedelta(days=7)
SAME_TITLE_MIN_WORDS = 5
SAME_ADDRESS_WITHIN = timedelta(days=30)   # two posts at one address (0064), as a shared text
LINK_WITHIN = timedelta(hours=72)
ROUNDUP_ANCHORS = 3
LINK_POST_MAX_WORDS = 60          # a Reddit or HN post with fewer words of its own is a share
SIGNATURE_SHARE = 0.25            # a link in 25% of a source's posts ...
SIGNATURE_MIN_POSTS = 4           # ... and in 4 of them at least is the source's signature
DISCOVER_MIN_VOICES = 3
DISCOVER_MIN_ARTICLES = 2
DISCOVER_ARTICLE_SHARE = 0.4
# The sites where INSIGHT follows one account, not the whole site: its source kinds (Reddit, X,
# Telegram, YouTube) and the feed finder's platform feeds (GitHub, Medium). Measured on the
# server's data, 2026-10-30: a test by "8+ first path segments" called 249 hosts platforms, split
# publishers by year or section (nytimes.com/2026) and hid blogs whose posts sit at the root.
DISCOVER_PLATFORMS = frozenset(set().union(*(PLATFORM_SITES[k] for k in ("reddit", "x", "telegram", "youtube")))
                               | {"github.com", "medium.com"})
# First path segments of a platform that name a kind of page, not an account.
NOT_ACCOUNT = frozenset({"status", "watch", "pull", "issues", "i", "p", "s", "search", "hashtag", "intent",
                         "share", "home", "explore", "wiki", "posts", "in"})
WORD = re.compile(r"\w+", re.U)

REASONS = ("address", "text", "title", "link", "citation")   # why a post is in its story; Mark X adds more
# Why a post hangs from its parent (issue 0064), most certain first. Mark X adds meaning, attribution.
PARENT_REASONS = ("address", "citation", "copy", "time", "none")
TIME_APART = timedelta(minutes=10)         # two trustworthy times closer than this make no order
PAGE_ORIGIN_MIN_POSTS = 2                  # an outside page 2+ of a story's posts link can be its origin
# Kinds whose posts' addresses are not their own pages: an HN item is the page it links, a Saved
# page is anyone's. Their posts never claim an address.
NOT_PUBLISHERS = ("hn", "saved")
HOME_SITE_SHARE = 0.5                      # a source whose address is elsewhere publishes on a site holding half its posts


@dataclass
class StoryPost:
    """What the rules read of one post."""

    id: str
    source_id: str
    kind: str                       # post_links.source_kind
    own_site: str                   # the site of its source
    t: datetime                     # published_at, else fetched_at
    title: Optional[str] = None
    content_hash: Optional[str] = None
    text_chars: int = 0             # len(content)
    words: Optional[int] = None     # words of its own (Reddit, HN): the share rule
    author: Optional[str] = None    # a Reddit post's author
    url: Optional[str] = None       # normalized
    links: List[Tuple[str, Optional[str]]] = field(default_factory=list)   # (target, stored post id)
    link_texts: Dict[str, str] = field(default_factory=dict)              # target -> the link's words
    updated: bool = False           # a watched page that changed since its date (0037)
    home_site: Optional[str] = None  # the site its source publishes on; None: its own site (not HN, Saved)

    @property
    def voice(self) -> str:
        if self.kind == "site":
            return "site:" + self.own_site
        if self.kind == "reddit" and self.author:
            return "reddit:" + self.author
        return "source:" + self.source_id

    @property
    def place(self) -> str:
        """Where it was said: its voice, but a subreddit (not its poster) on Reddit."""
        return "source:" + self.source_id if self.kind == "reddit" else self.voice

    @property
    def text_key(self) -> Optional[str]:
        return self.content_hash if self.content_hash and self.text_chars >= SAME_TEXT_MIN_CHARS else None

    @property
    def title_key(self) -> Optional[str]:
        return title_key(self.title)

    @property
    def trusted_time(self) -> bool:
        """Its time can order it (issue 0064): a time of day (not a date alone, 00:00:00), not a
        Saved page (the day you saved it), not a watched page updated since its date."""
        if self.kind == "saved" or self.updated:
            return False
        t = self.t.astimezone(timezone.utc) if self.t.tzinfo else self.t
        return (t.hour, t.minute, t.second, t.microsecond) != (0, 0, 0, 0)

    @property
    def on_own_site(self) -> bool:
        """It is at an address on the site its source publishes on: that address's own page."""
        home = self.home_site if self.home_site is not None else ("" if self.kind in NOT_PUBLISHERS else self.own_site)
        return bool(home and self.url and site_of(host_of(self.url)) == home)


def title_key(title: Optional[str]) -> Optional[str]:
    words = WORD.findall((title or "").lower())
    return " ".join(words) if len(words) >= SAME_TITLE_MIN_WORDS else None


class _UnionFind:
    def __init__(self) -> None:
        self.parent: Dict[str, str] = {}

    def find(self, x: str) -> str:
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        self.parent[self.find(a)] = self.find(b)


@dataclass
class Story:
    id: str                          # its first post
    first_at: datetime
    posts: List[StoryPost]           # first first
    voices: int
    roles: Dict[str, str]            # post id -> report | share
    reasons: Dict[str, List[str]]    # post id -> why it joined
    mentions: Set[str]               # roundups that mention it and are not in it
    # Its tree (issue 0064): post id -> (parent post, parent page, reason). The origin post has
    # (None, None, None); a post under the outside page origin has (None, origin_url, reason).
    parents: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = field(default_factory=dict)
    origin_url: Optional[str] = None       # the origin, when it is a page outside INSIGHT
    origin_title: Optional[str] = None     # its most common titled link words (0051's rule)
    origin_linked_by: int = 0              # how many of the story's posts are about it


def _order(post: StoryPost) -> Tuple[datetime, str]:
    return post.t, post.id


def anchors(post: StoryPost) -> List[Tuple[str, str]]:
    """What a post points at: ('post', id) for a stored post, ('url', address) for an outside page.
    Home and profile pages, and the post itself, are no anchor. A stored post is never a home
    page, however short its address (blog.cloudflare.com/yandex-outage is one segment)."""
    out: Dict[Tuple[str, str], None] = {}
    for url, stored_id in post.links:
        if stored_id == post.id or (not stored_id and is_home(url)):
            continue
        out[("post", stored_id) if stored_id else ("url", url)] = None
    return list(out)


def _time_key(post: StoryPost) -> Tuple[bool, datetime, str]:
    """Earlier trustworthy time first; a time that can't order comes after every one that can."""
    return not post.trusted_time, post.t, post.id


def address_origins(posts: Iterable[StoryPost]) -> Dict[str, str]:
    """Each address's own page among `posts`: address -> the post at it on its source's own site
    (two such: the earlier trustworthy time)."""
    out: Dict[str, StoryPost] = {}
    for p in posts:
        if p.on_own_site and (p.url not in out or _time_key(p) < _time_key(out[p.url])):
            out[p.url] = p
    return {url: p.id for url, p in out.items()}


def group(posts: Sequence[StoryPost]) -> List[Story]:
    """The stories among `posts` (2+ sources each), first post first, each a tree (issue 0064)."""
    posts = sorted(posts, key=_order)
    by_id = {p.id: p for p in posts}
    # A link to an address is a link to its own page when one is stored: the row a link resolves
    # to (the first seen at the address) may be another source's post of that page (HN's).
    origin_of = address_origins(posts)

    def resolved(post: StoryPost) -> List[Tuple[str, str]]:
        out: Dict[Tuple[str, str], None] = {}
        for what, target in anchors(post):
            cited = by_id.get(target) if what == "post" else None
            if cited is not None and cited.url:
                target = origin_of.get(cited.url, target)
            if (what, target) != ("post", post.id):
                out[(what, target)] = None
        return list(out)
    uf = _UnionFind()
    why: Dict[str, Set[str]] = defaultdict(set)
    mentioned: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for p in posts:
        uf.find(p.id)

    def chain(same: Iterable[List[StoryPost]], within: timedelta, reason: str) -> None:
        for run in same:
            for a, b in zip(run, run[1:]):
                if a.source_id != b.source_id and b.t - a.t <= within:
                    uf.union(a.id, b.id)
                    why[a.id].add(reason)
                    why[b.id].add(reason)

    by_text: Dict[str, List[StoryPost]] = defaultdict(list)
    by_title: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in posts:
        if p.text_key:
            by_text[p.text_key].append(p)
        if p.title_key:
            by_title[p.title_key].append(p)
    chain(by_text.values(), SAME_TEXT_WITHIN, "text")
    chain(by_title.values(), SAME_TITLE_WITHIN, "title")
    by_url: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in posts:
        if p.url:
            by_url[p.url].append(p)
    chain(by_url.values(), SAME_ADDRESS_WITHIN, "address")

    linkers: Dict[Tuple[str, str], List[StoryPost]] = defaultdict(list)
    every: Dict[str, List[Tuple[str, str]]] = {}     # every anchor of a post: its citations
    focused: Dict[str, List[Tuple[str, str]]] = {}   # what it is about: a roundup's first anchor only
    for p in posts:
        points = every[p.id] = resolved(p)
        if len(points) >= ROUNDUP_ANCHORS:
            for anchor in points[1:]:
                mentioned[anchor].add(p.id)
            points = points[:1]
        focused[p.id] = points
        for anchor in points:
            linkers[anchor].append(p)
    for (what, target), ps in linkers.items():
        if what == "post":
            cited = by_id.get(target)
            if cited is None:
                continue   # a stored post outside the posts recomputed
            for p in ps:
                if p.place != cited.place and abs(p.t - cited.t) <= LINK_WITHIN:
                    uf.union(p.id, cited.id)
                    why[p.id].add("citation")
                    why[cited.id].add("citation")
        else:
            near = [p for p in ps if p.t - ps[0].t <= LINK_WITHIN]   # ps is in time order
            if len({p.place for p in near}) >= 2:
                for p in near:
                    uf.union(p.id, "U:" + target)
                    why[p.id].add("link")

    members: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in posts:
        members[uf.find(p.id)].append(p)
    mentions_of: Dict[str, Set[str]] = defaultdict(set)
    for (what, target), ps in mentioned.items():
        node = target if what == "post" else "U:" + target
        if what == "post" and target not in by_id or what == "url" and node not in uf.parent:
            continue
        root = uf.find(node)
        mentions_of[root] |= {pid for pid in ps if uf.find(pid) != root}

    stories = []
    for root, group_posts in members.items():
        if len({p.source_id for p in group_posts}) < 2:
            continue
        first = group_posts[0]
        shape = tree(group_posts, every=every, focused=focused, origin_of=origin_of)
        stories.append(Story(
            id=first.id, first_at=first.t, posts=group_posts, voices=count_voices(group_posts),
            roles=roles(group_posts),
            reasons={p.id: [r for r in REASONS if r in why[p.id]] for p in group_posts},
            mentions=mentions_of.get(root, set()),
            parents=shape.parents, origin_url=shape.origin_url, origin_title=shape.origin_title,
            origin_linked_by=shape.origin_linked_by,
        ))
    return sorted(stories, key=lambda s: (s.first_at, s.id))


# ---- a story's tree (issue 0064) -------------------------------------------------------------


@dataclass
class Tree:
    parents: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]]
    origin_url: Optional[str] = None
    origin_title: Optional[str] = None
    origin_linked_by: int = 0


_RANK = {reason: i for i, reason in enumerate(PARENT_REASONS)}
_PAGE = "U:"   # a node that is a page outside INSIGHT: "U:" + its address
_NEVER = datetime.max.replace(tzinfo=timezone.utc)


def tree(posts: Sequence[StoryPost], *, every: Dict[str, List[Tuple[str, str]]],
         focused: Dict[str, List[Tuple[str, str]]], origin_of: Dict[str, str]) -> Tree:
    """Each post's parent in its story, by evidence in order of certainty (the module's notes).
    `posts`: one story's. `every` / `focused`: each post's anchors resolved to the address's own
    page (`group`): all of them, and those it is about (a roundup: its first only). `origin_of`:
    address -> its own page."""
    by_id = {p.id: p for p in posts}
    edges: List[Tuple[str, str, str]] = []          # (child, parent node, reason)
    about: Dict[str, Set[str]] = defaultdict(set)   # node -> the voices of the posts about it
    # 1. The address's own site: the other posts at an address hang from its own page.
    for p in posts:
        own = origin_of.get(p.url or "")
        if own and own != p.id and own in by_id and by_id[own].source_id != p.source_id:
            edges.append((p.id, own, "address"))
            about[own].add(p.voice)
    # 2. Citation: a post links another post of the story (any of its links: whatever the dates
    # say), or a page outside INSIGHT that 2+ of the story's posts are about (focused links).
    page_posts: Dict[str, List[str]] = defaultdict(list)
    for p in posts:
        for what, target in focused.get(p.id, []):
            if what == "url":
                page_posts[target].append(p.id)
    for p in posts:
        about_it = focused.get(p.id, [])
        for what, target in every.get(p.id, []):
            if what == "post" and target in by_id:
                edges.append((p.id, target, "citation"))
                if (what, target) in about_it:
                    about[target].add(p.voice)
            elif what == "url" and (what, target) in about_it and len(page_posts[target]) >= PAGE_ORIGIN_MIN_POSTS:
                edges.append((p.id, _PAGE + target, "citation"))
                about[_PAGE + target].add(p.voice)
    # 3. Copy: the same text or title from another source, the earlier trustworthy time the parent.
    for key in ("text_key", "title_key"):
        same: Dict[str, List[StoryPost]] = defaultdict(list)
        for p in posts:
            if getattr(p, key) and p.trusted_time:
                same[getattr(p, key)].append(p)
        for run in same.values():
            for a in run:
                for b in run:
                    if a.source_id != b.source_id and a.t < b.t:   # one time: no order
                        edges.append((b.id, a.id, "copy"))

    def node_key(node: str) -> Tuple:
        """Equally certain parents: a stored post before a page, then the earlier trustworthy time."""
        if node.startswith(_PAGE):
            return (1, True, _NEVER, node)
        return (0, *_time_key(by_id[node]))

    def origin_key(node: str) -> Tuple:
        """The origin: linked by the most voices (in-degree), a post at its own site first, then
        the earlier trustworthy time. A post's own out-links never count: a roundup is no origin."""
        own = 0 if not node.startswith(_PAGE) and by_id[node].on_own_site else 1
        return (-len(about[node]), own, *node_key(node))

    # The origin is chosen first, among every post and every page 2+ posts are about: the node
    # most voices are about is where the story starts, even when it links a page itself (Google's
    # Gemini post links a benchmark page two of its copies link too). Only the origin may be a page.
    pages = sorted(_PAGE + url for url, pids in page_posts.items() if len(pids) >= PAGE_ORIGIN_MIN_POSTS)
    origin = min([p.id for p in posts] + pages, key=origin_key)
    edges.sort(key=lambda e: (_RANK[e[2]], -len(about[e[1]]), node_key(e[1]), node_key(e[0])))
    # One parent per post, the first edge in order of certainty, never a cycle; the origin has none.
    parent: Dict[str, Tuple[str, str]] = {}
    for child, node, reason in edges:
        if child in parent or child == origin or (node.startswith(_PAGE) and node != origin):
            continue
        up = node
        while up in parent and up != child:
            up = parent[up][0]
        if up != child:
            parent[child] = (node, reason)
    # 4. Time, as a tiebreaker: what 1-3 leave unrelated hangs from the origin, in order only
    # when both times are trustworthy and 10+ minutes apart.
    first = by_id.get(origin)
    for p in posts:
        if p.id != origin and p.id not in parent:
            ordered = first is not None and first.trusted_time and p.trusted_time and p.t - first.t > TIME_APART
            parent[p.id] = (origin, "time" if ordered else "none")
    out: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {}
    for p in posts:
        node, reason = parent.get(p.id, (None, None))
        if node is None:
            out[p.id] = (None, None, None)
        elif node.startswith(_PAGE):
            out[p.id] = (None, node[len(_PAGE):], reason)
        else:
            out[p.id] = (node, None, reason)
    if first is not None:
        return Tree(out)
    url = origin[len(_PAGE):]
    texts = Counter(text for text in (by_id[pid].link_texts.get(url) for pid in page_posts[url])
                    if titled_link_text(text))
    title = min(texts.items(), key=lambda kv: (-kv[1], kv[0]))[0] if texts else None
    return Tree(out, url, title, len(set(page_posts[url])))


def roles(posts: Sequence[StoryPost]) -> Dict[str, str]:
    """report (its own writing) or share: a copy of an earlier post's text or title from another
    place, or a Reddit or HN post that is mostly a link. `posts` in time order."""
    first_text: Dict[str, str] = {}
    first_title: Dict[str, str] = {}
    out = {}
    for p in posts:
        text, title = p.text_key, p.title_key
        copy = (text and text in first_text and first_text[text] != p.place) or \
               (title and title in first_title and first_title[title] != p.place)
        link_post = p.kind in ("reddit", "hn") and (p.words or 0) < LINK_POST_MAX_WORDS
        out[p.id] = "share" if copy or link_post else "report"
        if text:
            first_text.setdefault(text, p.place)
        if title:
            first_title.setdefault(title, p.place)
    return out


def count_voices(posts: Sequence[StoryPost]) -> int:
    """How many voices a story has: posts of one voice, and copies of one text, are one."""
    uf = _UnionFind()
    keys: Dict[str, str] = {}
    for p in posts:
        uf.find(p.id)
        for key in (("text:" + p.text_key) if p.text_key else None, "voice:" + p.voice):
            if key is None:
                continue
            if key in keys:
                uf.union(p.id, keys[key])
            else:
                keys[key] = p.id
    return len({uf.find(p.id) for p in posts})


# ---- Discover --------------------------------------------------------------------------------


@dataclass
class Suggestion:
    key: str                         # a site (openai.com) or a platform account (x.com/karpathy)
    voices: List[str]                # the voices that link it
    articles: List[str]              # its article-like addresses linked
    links: int                       # every address of it linked
    addresses: Set[str] = field(default_factory=set)   # those addresses (0051 counts its classics)


def suggestions(links: Iterable[Tuple[str, str]], *, followed: Set[str], hidden: Set[str],
                followed_accounts: Set[str] = frozenset()) -> List[Suggestion]:
    """Sites and accounts 3+ of your voices link, in 2+ article-like pages that make 40%+ of their
    links, that you don't follow and did not hide. On a platform the unit is the account: it is
    followed, or hidden, only as that account (`followed_accounts`, post_links.account_key), so
    following one channel hides no other. Elsewhere it is the site (`followed`: sites; `hidden`:
    keys or sites). `links`: (voice, address) for every kept outside link. Most voices first."""
    links = list(links)
    found: Dict[str, Tuple[Set[str], Set[str], Set[str]]] = defaultdict(lambda: (set(), set(), set()))
    for voice, url in links:
        host, _, rest = bare(url).partition("/")
        if site_of(host) in DISCOVER_PLATFORMS:
            if rest.split("/")[0].lower() in NOT_ACCOUNT:
                continue
            key = account_key(url)
            if key in followed_accounts or key in hidden:
                continue
        else:
            key = host
            if site_of(host) in followed or key in hidden or site_of(host) in hidden:
                continue
        voices, articles, every = found[key]
        voices.add(voice)
        every.add(url)
        if is_article(url):
            articles.add(url)
    out = [
        Suggestion(key, sorted(voices), sorted(articles), len(every), set(every))
        for key, (voices, articles, every) in found.items()
        if len(voices) >= DISCOVER_MIN_VOICES and len(articles) >= DISCOVER_MIN_ARTICLES
        and len(articles) >= DISCOVER_ARTICLE_SHARE * len(every)
    ]
    return sorted(out, key=lambda s: (-len(s.voices), -len(s.articles), -s.links, s.key))


def source_site(hosts: Iterable[Tuple[str, int]]) -> str:
    """A source's own site: the most common site of its posts' hosts ((host, posts) pairs)."""
    sites: Counter = Counter()
    for host, n in hosts:
        sites[site_of(host)] += n
    return sites.most_common(1)[0][0] if sites else ""


__all__ = ["StoryPost", "Story", "Suggestion", "Tree", "group", "tree", "address_origins", "roles", "count_voices", "suggestions",
           "source_site", "title_key", "anchors"]
