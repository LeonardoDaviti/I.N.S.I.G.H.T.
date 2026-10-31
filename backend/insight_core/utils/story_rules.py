"""One story, many sources (issue 0050): the rules that join posts into stories, each post's
role, a story's voices, and Discover's suggestions. Pure functions over plain data: the story
job (services/stories_service.py) loads the posts and writes what these return.

Ported from the prototype (`plan/research/dedup-prototype/stories.py`, `rank.py`, `report.py`),
the reference the real code reproduces. The thresholds are here, in one place.

- A **voice** is one publication for websites (the host its source publishes at, issue 0069),
  one channel or account for Telegram, X and YouTube, and on Reddit the person who posted: a
  story's voices count people.
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
- **On X (issue 0066)** the platform says how tweets connect, and that is as certain as an address:
  - `repost`: a repost stored apart from its original (one address, 0049) hangs from it; a repost
    is a share, and never its address's own page;
  - `thread`: an author's reply to itself hangs from the post right before it in its source's
    timeline, when that is the author's own (not a repost, not a reply to another account) and
    within 24 hours. Its posts are one story, whatever the sources: a thread is one item;
  - `quote`: a quoting tweet hangs from the tweet it quotes; a stored one joins its story
    within 72 hours (as a citation), whatever the place.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import unquote

from insight_core.utils.post_links import (PLATFORM_SITES, SECTION_MIN, SECTION_SHARE, account_key, bare, host_of,
                                          is_article, is_home, is_tweet, section_of, site_of, titled_link_text)
from insight_core.utils.url_normalization import TWEET_PATH

# The version of the rules stories are grouped by (issue 0069). Bump it with a change to these rules,
# to post_links (site_of, a publication) or to how a source's voice is told (SourceFacts): the next
# story run then regroups every story, the frozen ones too. 1: issue 0069, a voice is its publication.
RULES_VERSION = 1
SAME_TEXT_WITHIN = timedelta(days=30)
SAME_TEXT_MIN_CHARS = 120
SAME_TITLE_WITHIN = timedelta(days=7)
SAME_TITLE_MIN_WORDS = 5
SAME_ADDRESS_WITHIN = timedelta(days=30)   # two posts at one address (0064), as a shared text
LINK_WITHIN = timedelta(hours=72)
THREAD_WITHIN = timedelta(hours=24)       # a reply to itself continues the author's post before it (0066)
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
# A post of a platform account is one of its articles (issue 0065). A tweet by its shape, on any host
# (x.com, a Nitter, xcancel.com, fxtwitter.com: the forms 0066 gives one address), is the account's;
# elsewhere on a platform, /<account>/<number> (a Telegram post, t.me/<channel>/<id>).
TWEET = TWEET_PATH
PLATFORM_POST = re.compile(r"^/[^/?#]+/\d+(?:[?#]|$)")
ORIGIN_MIN_VOICES = 2      # the stories whose origins Discover counts: 2+ voices, as 0064 measured them
WORD = re.compile(r"\w+", re.U)

REASONS = ("address", "text", "title", "link", "citation", "thread", "quote")   # why a post is in its story; Mark X adds more
# Why a post hangs from its parent (issue 0064; repost, thread, quote: 0066), most certain first.
# Mark X adds meaning, attribution.
PARENT_REASONS = ("address", "repost", "thread", "quote", "citation", "copy", "time", "none")
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
    own_site: str                   # its source's publication (SourceFacts.publication): a website's voice
    t: datetime                     # published_at, else fetched_at
    title: Optional[str] = None
    content_hash: Optional[str] = None
    text_chars: int = 0             # len(content)
    words: Optional[int] = None     # words of its own (Reddit, HN): the share rule
    author: Optional[str] = None    # a Reddit post's author; a tweet's account (issue 0066)
    url: Optional[str] = None       # normalized
    links: List[Tuple[str, Optional[str]]] = field(default_factory=list)   # (target, stored post id)
    link_texts: Dict[str, str] = field(default_factory=dict)              # target -> the link's words
    updated: bool = False           # a watched page that changed since its date (0037)
    home_site: Optional[str] = None  # the site its source publishes on; None: its own site (not HN, Saved)
    reposted: bool = False          # a tweet of another account its source reposted (issue 0066)
    reply_to: Optional[str] = None  # the account a tweet replies to
    quoted: Optional[str] = None    # the tweet it quotes (normalized)
    # Who else of your sources put this tweet before you (issue 0068): the sources that reposted it
    # (from posts.reposted_by), each a share voice in its story, and its author's own source when
    # the row is another source's repost, a report voice. Never the row's own source.
    reposters: Tuple[str, ...] = ()
    author_source: Optional[str] = None

    @property
    def other_sources(self) -> Tuple[str, ...]:
        return ((self.author_source,) if self.author_source else ()) + self.reposters

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
        """It is at an address on the site its source publishes on: that address's own page. A repost
        is another account's tweet: never its own page."""
        home = self.home_site if self.home_site is not None else ("" if self.kind in NOT_PUBLISHERS else site_of(self.own_site))
        return bool(home and self.url and not self.reposted and site_of(host_of(self.url)) == home)

    @property
    def own_tweet(self) -> bool:
        """A tweet its source's account wrote, and not as a reply to another account (issue 0066)."""
        return bool(self.kind == "x" and self.author and not self.reposted
                    and (self.reply_to is None or self.reply_to.lower() == self.author.lower()))


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
    origin_title: Optional[str] = None     # its title by evidence (origin_title, issue 0068)
    origin_linked_by: int = 0              # how many of the story's posts are about it


def _order(post: StoryPost) -> Tuple[datetime, int, str]:
    """Time order. Tweets of one second follow their ids, which X gives in the order they were
    written (issue 0066: a thread's replies often share a second)."""
    return post.t, int(post.url.rsplit("/", 1)[-1]) if is_tweet(post.url) else 0, post.id


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


def _time_key(post: StoryPost) -> Tuple[bool, datetime, int, str]:
    """Earlier trustworthy time first; a time that can't order comes after every one that can."""
    return (not post.trusted_time, *_order(post))


def address_origins(posts: Iterable[StoryPost]) -> Dict[str, str]:
    """Each address's own page among `posts`: address -> the post at it on its source's own site
    (two such: the earlier trustworthy time)."""
    out: Dict[str, StoryPost] = {}
    for p in posts:
        if p.on_own_site and (p.url not in out or _time_key(p) < _time_key(out[p.url])):
            out[p.url] = p
    return {url: p.id for url, p in out.items()}


def threads(posts: Iterable[StoryPost]) -> Dict[str, str]:
    """Each reply of an author to itself -> its parent (issue 0066): the post right before it in
    its source's timeline (reposts included), when that is the author's own tweet within 24 hours.
    A thread starts at the author's own post, never at a repost of another account."""
    timeline: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in sorted(posts, key=_order):
        if p.kind == "x":
            timeline[p.source_id].append(p)
    out: Dict[str, str] = {}
    for run in timeline.values():
        for before, p in zip(run, run[1:]):
            if p.own_tweet and p.reply_to and before.own_tweet and p.t - before.t <= THREAD_WITHIN:
                out[p.id] = before.id
    return out


def group(posts: Sequence[StoryPost]) -> List[Story]:
    """The stories among `posts` (2+ sources each), first post first, each a tree (issue 0064)."""
    posts = sorted(posts, key=_order)
    by_id = {p.id: p for p in posts}
    # A link to an address is a link to its own page when one is stored: the row a link resolves
    # to (the first seen at the address) may be another source's post of that page (HN's).
    origin_of = address_origins(posts)

    def resolve(what: str, target: str) -> Tuple[str, str]:
        cited = by_id.get(target) if what == "post" else None
        return what, origin_of.get(cited.url, target) if cited is not None and cited.url else target

    def resolved(post: StoryPost) -> List[Tuple[str, str]]:
        out: Dict[Tuple[str, str], None] = {}
        for what, target in anchors(post):
            anchor = resolve(what, target)
            if anchor != ("post", post.id):
                out[anchor] = None
        return list(out)

    def quote_of(post: StoryPost) -> Optional[Tuple[str, str]]:
        """The anchor of the tweet a tweet quotes (issue 0066), when it links it."""
        links = dict(post.links)
        if not post.quoted or post.quoted not in links:
            return None
        anchor = resolve("post", links[post.quoted]) if links[post.quoted] else ("url", post.quoted)
        return anchor if anchor != ("post", post.id) else None
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
    quotes: Dict[str, str] = {}   # a quoting tweet -> the stored tweet it quotes (issue 0066)
    for p in posts:
        every[p.id] = resolved(p)
        # A quote is what its tweet is about, never one of a roundup's listed links.
        quote = quote_of(p)
        points = [anchor for anchor in every[p.id] if anchor != quote]
        if len(points) >= ROUNDUP_ANCHORS:
            for anchor in points[1:]:
                mentioned[anchor].add(p.id)
            points = points[:1]
        focused[p.id] = points + ([quote] if quote else [])
        for anchor in focused[p.id]:
            linkers[anchor].append(p)
        if quote and quote[0] == "post" and quote[1] in by_id:
            quotes[p.id] = quote[1]
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
    # On X (issue 0066): a thread is one story, and a quote joins the stored tweet it quotes.
    replies = threads(posts)
    joins = [(child, parent, "thread") for child, parent in replies.items()]
    joins += [(child, parent, "quote") for child, parent in quotes.items()
              if abs(by_id[child].t - by_id[parent].t) <= LINK_WITHIN]
    for child, parent, reason in joins:
        uf.union(child, parent)
        why[child].add(reason)
        why[parent].add(reason)

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
        # 2+ sources (a reposter is one, issue 0068), or one account's thread or quote of itself (0066).
        if len({s for p in group_posts for s in (p.source_id, *p.other_sources)}) < 2 \
                and not any(why[p.id] & {"thread", "quote"} for p in group_posts):
            continue
        first = group_posts[0]
        shape = tree(group_posts, every=every, focused=focused, origin_of=origin_of, replies=replies, quotes=quotes)
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
         focused: Dict[str, List[Tuple[str, str]]], origin_of: Dict[str, str],
         replies: Optional[Dict[str, str]] = None, quotes: Optional[Dict[str, str]] = None) -> Tree:
    """Each post's parent in its story, by evidence in order of certainty (the module's notes).
    `posts`: one story's. `every` / `focused`: each post's anchors resolved to the address's own
    page (`group`): all of them, and those it is about (a roundup: its first only). `origin_of`:
    address -> its own page. `replies` / `quotes` (issue 0066): a thread's reply -> the post it
    continues, a quoting tweet -> the stored tweet it quotes."""
    by_id = {p.id: p for p in posts}
    edges: List[Tuple[str, str, str]] = []          # (child, parent node, reason)
    about: Dict[str, Set[str]] = defaultdict(set)   # node -> the voices of the posts about it
    # 1. The address's own site: the other posts at an address hang from its own page.
    for p in posts:
        own = origin_of.get(p.url or "")
        if own and own != p.id and own in by_id and by_id[own].source_id != p.source_id:
            edges.append((p.id, own, "repost" if p.reposted else "address"))
            about[own].add(p.voice)
    # On X (issue 0066): a reply continues the post before it; a quote is about the tweet it quotes.
    for child, parent in (replies or {}).items():
        if child in by_id and parent in by_id:
            edges.append((child, parent, "thread"))
    for child, parent in (quotes or {}).items():
        if child in by_id and parent in by_id:
            edges.append((child, parent, "quote"))
            about[parent].add(by_id[child].voice)
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
                edges.append((p.id, _PAGE + target, "quote" if target == p.quoted else "citation"))
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
            return (1, True, _NEVER, 0, node)
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
    return Tree(out, url, origin_title(url, [by_id[pid] for pid in dict.fromkeys(page_posts[url])]),
                len(set(page_posts[url])))


# An outside origin's title (issue 0068): an address's slug names its page with 3+ words of
# letters (claude-fable-5-mythos-5); words with digits (a version, an id) are kept but not counted.
SLUG_MIN_WORDS = 3
_SLUG = re.compile(r"[-_+]+")
_TOKENS = re.compile(r"\w+", re.U)


def _slug_words(url: str) -> List[str]:
    """The words of an address's last path segment (its slug), its extension aside."""
    _, _, rest = bare(url).partition("/")
    slug = unquote(re.split(r"[?#]", rest, maxsplit=1)[0].rstrip("/").rsplit("/", 1)[-1])
    return [w for w in _SLUG.split(re.sub(r"\.[a-z]{2,5}$", "", slug, flags=re.I)) if w]


def origin_title(url: str, posts: Sequence[StoryPost]) -> Optional[str]:
    """An outside origin's title (issue 0068), from evidence, never one signal, nothing fetched.
    `posts`: those linking it. A page that is stored is no outside origin: it is the root, with its
    own title. Measured on the lab (30 roots checked by hand): link words that 2+ voices agree on
    are often a bare word ("Блогпост", "Веса", "Video"), and a slug loses a title's case and dots
    ("Introducing chatgpt images 2 5"), so each signal needs another's support:
    1. link words 2+ voices agree on (copies of one text are one voice) that read as a title
       (0051's rule, titled_link_text);
    2. else link words the address's slug confirms (the same words): the words, as written;
    3. else the slug made readable, when it holds SLUG_MIN_WORDS words of letters;
    4. else one voice's link words that read as a title;
    5. else None: the reader shows the address."""
    said: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in posts:
        text = " ".join((p.link_texts.get(url) or "").split())
        if text and not re.match(r"https?://", text):
            said[text.casefold()].append(p)
    form = {key: Counter(" ".join(p.link_texts[url].split()) for p in ps).most_common(1)[0][0] for key, ps in said.items()}
    by_use = sorted(said, key=lambda key: (-count_voices(said[key]), -len(said[key]), key))
    agreed = [key for key in by_use if count_voices(said[key]) >= 2 and titled_link_text(form[key])]
    words = _slug_words(url)
    slug = _TOKENS.findall(" ".join(words).casefold())
    confirmed = [key for key in by_use if len(slug) >= 2 and _TOKENS.findall(key) == slug]
    if agreed or confirmed:
        return form[(agreed or confirmed)[0]]
    if sum(1 for w in words if re.fullmatch(r"[^\W\d_]+", w)) >= SLUG_MIN_WORDS:
        text = " ".join(words)
        return text[0].upper() + text[1:]
    titled = [key for key in by_use if titled_link_text(form[key])]
    return form[titled[0]] if titled else None


def roles(posts: Sequence[StoryPost]) -> Dict[str, str]:
    """report (its own writing) or share: a copy of an earlier post's text or title from another
    place, a Reddit or HN post that is mostly a link, or a repost. `posts` in time order."""
    first_text: Dict[str, str] = {}
    first_title: Dict[str, str] = {}
    out = {}
    for p in posts:
        text, title = p.text_key, p.title_key
        copy = (text and text in first_text and first_text[text] != p.place) or \
               (title and title in first_title and first_title[title] != p.place)
        link_post = p.kind in ("reddit", "hn") and (p.words or 0) < LINK_POST_MAX_WORDS
        out[p.id] = "share" if copy or link_post or p.reposted else "report"   # a repost is a share (0066)
        if text:
            first_text.setdefault(text, p.place)
        if title:
            first_title.setdefault(title, p.place)
    return out


def count_voices(posts: Sequence[StoryPost]) -> int:
    """How many voices a story has: posts of one voice, and copies of one text, are one. A source
    that reposted a tweet, or wrote the tweet another source holds, is a voice (issue 0068): one
    with its posts in the story, if it has some."""
    uf = _UnionFind()
    keys: Dict[str, str] = {}
    nodes = [(p.id, (("text:" + p.text_key) if p.text_key else None, "voice:" + p.voice)) for p in posts]
    nodes += [(f"{p.id}>{s}", (None, "voice:" + reposter_voice(s))) for p in posts for s in p.other_sources]
    for node, node_keys in nodes:
        uf.find(node)
        for key in node_keys:
            if key is None:
                continue
            if key in keys:
                uf.union(node, keys[key])
            else:
                keys[key] = node
    return len({uf.find(node) for node, _ in nodes})


def reposter_voice(source_id: str) -> str:
    """A reposting source's voice, as StoryPost.voice says an X account's (issue 0068)."""
    return "source:" + source_id


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


def discover_address(url: str) -> Tuple[Optional[str], str, bool]:
    """What Discover reads of one address: (its key, its site, whether the site is a platform).
    On a platform the key is the account (account_key), none when the first path segment names a
    kind of page (NOT_ACCOUNT); a tweet, on any host, is its author's (x.com/<user>, TWEET); elsewhere
    it is the host. A function of the address alone, so the database keeps it once per address
    (repo_discover, issue 0062)."""
    host, _, rest = bare(url).partition("/")
    tweet = TWEET.match("/" + rest)
    if tweet:
        user = tweet.group(1).lower()
        return (None if user in NOT_ACCOUNT else "x.com/" + user), "x.com", True
    site = site_of(host)
    if site in DISCOVER_PLATFORMS:
        return (None if re.split(r"[/?#]", rest)[0].lower() in NOT_ACCOUNT else account_key(url)), site, True
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
                followed_accounts: Set[str] = frozenset(), mirrors: Set[str] = frozenset()) -> List[Suggestion]:
    """Sites and accounts 3+ of your voices link, in 2+ article-like pages that make 40%+ of their
    links, that you don't follow and did not hide. On a platform the unit is the account: it is
    followed, or hidden, only as that account (`followed_accounts`, post_links.account_key), so
    following one channel hides no other. Elsewhere it is the site (`followed`: sites; `hidden`:
    keys or sites); a tweet mirror's other pages (`mirrors`: hosts where tweets are found, issue
    0067) are X's kinds of page, never a site. `links`: (voice, address, whether the linking post is
    a roundup) for every kept outside link. Most voices first, a voice linking a key only in
    roundups counting half (Suggestion.weight), then all voices."""
    links = list(links)
    found: Dict[str, Tuple[Set[str], Set[str], Set[str], Set[str]]] = defaultdict(lambda: (set(), set(), set(), set()))
    for voice, url, roundup in links:
        key, site, platform = discover_address(url)
        if key is None or (not platform and key in mirrors) or not discover_open(
                key, site, platform, followed=followed, hidden=hidden, followed_accounts=followed_accounts):
            continue
        voices, articles, every, ordinary = found[key]
        voices.add(voice)
        every.add(url)
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

    @property
    def stored(self) -> bool:
        return self.source_id is not None


@dataclass
class Origins:
    suggest: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # key -> its stories
    missing: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # source -> its stories
    unnamed: Dict[str, List[Origin]] = field(default_factory=lambda: defaultdict(list))   # youtube.com/watch -> them


def discover_place(url: str) -> Optional[str]:
    """Where an address is, as a source holds it: on a platform its account (None for a page that
    names none), elsewhere its host and section (anthropic.com/news; the host alone at the root)."""
    key, _, platform = discover_address(url)
    section = "" if platform else section_of(url)
    return f"{key}/{section}" if key and section else key


def origins(roots: Iterable[Origin], *, followed: Set[str], held: Dict[str, str],
            mirrors: Set[str] = frozenset()) -> Origins:
    """Where your stories start, each story once:
    - at its own source's site (Origin.own), or at a place one of your sources holds (`held`:
      discover_place -> that source): nothing to suggest; a story the
      source misses when its page is not stored (its archive may hold it, 0015);
    - on a site you don't follow, or an account no source holds: that site or account;
    - on a site you follow, in a section none of your sources holds: that section when SECTION_SHARE
      of the site's such stories start there (0060's rule: anthropic.com/news), else the site;
    - on a platform's page that names no account (youtube.com/watch?v=...), or a tweet mirror's page
      that is not a tweet (`mirrors`, issue 0067: nitter.net/i/article/...): only listed."""
    out = Origins()
    elsewhere: Dict[str, List[Origin]] = defaultdict(list)   # a followed site's host -> its unheld stories
    for root in roots:
        key, site, platform = discover_address(root.url)
        place = discover_place(root.url)
        if root.own:
            continue
        if key is None or (not platform and key in mirrors):
            if not root.stored:   # a stored one is its source's
                _, _, rest = bare(root.url).partition("/")
                out.unnamed[f"{site}/{re.split(r'[/?#]', rest)[0]}"].append(root)
        elif place in held:
            if not root.stored:
                out.missing[held[place]].append(root)
        elif platform or site not in followed:
            out.suggest[key].append(root)
        else:
            elsewhere[key].append(root)
    for host, found in elsewhere.items():
        section, n = Counter(section_of(root.url) for root in found).most_common(1)[0]
        if section and n >= max(SECTION_MIN, SECTION_SHARE * len(found)):
            out.suggest[f"{host}/{section}"] = [root for root in found if section_of(root.url) == section]
        else:
            out.suggest[host] = found
    return out


def source_site(hosts: Iterable[Tuple[str, int]], of: Callable[[str], str] = site_of) -> str:
    """A source's own site: the most common site of its posts' hosts ((host, posts) pairs); with
    `of=publication_of`, its publication (issue 0069)."""
    sites: Counter = Counter()
    for host, n in hosts:
        sites[of(host)] += n
    return sites.most_common(1)[0][0] if sites else ""


__all__ = ["StoryPost", "Story", "Suggestion", "Tree", "group", "tree", "threads", "address_origins", "roles", "count_voices", "suggestions",
           "discover_address", "discover_article", "discover_open", "discover_place", "Origin", "Origins", "origins",
           "source_site", "title_key", "anchors", "is_roundup"]
