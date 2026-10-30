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
- A story is a group of posts from 2+ sources, keyed by its first post.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.utils.post_links import account_key, bare, is_article, is_home, site_of

SAME_TEXT_WITHIN = timedelta(days=30)
SAME_TEXT_MIN_CHARS = 120
SAME_TITLE_WITHIN = timedelta(days=7)
SAME_TITLE_MIN_WORDS = 5
LINK_WITHIN = timedelta(hours=72)
ROUNDUP_ANCHORS = 3
LINK_POST_MAX_WORDS = 60          # a Reddit or HN post with fewer words of its own is a share
SIGNATURE_SHARE = 0.25            # a link in 25% of a source's posts ...
SIGNATURE_MIN_POSTS = 4           # ... and in 4 of them at least is the source's signature
DISCOVER_MIN_VOICES = 3
DISCOVER_MIN_ARTICLES = 2
DISCOVER_ARTICLE_SHARE = 0.4
PLATFORM_MIN_SEGMENTS = 8         # a host whose links reach 8+ first path segments, none half
# First path segments of a platform that name a kind of page, not an account.
NOT_ACCOUNT = frozenset({"status", "watch", "pull", "issues", "i", "p", "s", "search", "hashtag", "intent",
                         "share", "home", "explore", "wiki", "posts", "in"})
WORD = re.compile(r"\w+", re.U)

REASONS = ("text", "title", "link", "citation")   # why a post is in its story; Mark X adds more


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


def group(posts: Sequence[StoryPost]) -> List[Story]:
    """The stories among `posts` (2+ sources each), first post first."""
    posts = sorted(posts, key=_order)
    by_id = {p.id: p for p in posts}
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

    linkers: Dict[Tuple[str, str], List[StoryPost]] = defaultdict(list)
    for p in posts:
        points = anchors(p)
        if len(points) >= ROUNDUP_ANCHORS:
            for anchor in points[1:]:
                mentioned[anchor].add(p.id)
            points = points[:1]
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
        stories.append(Story(
            id=first.id, first_at=first.t, posts=group_posts, voices=count_voices(group_posts),
            roles=roles(group_posts),
            reasons={p.id: [r for r in REASONS if r in why[p.id]] for p in group_posts},
            mentions=mentions_of.get(root, set()),
        ))
    return sorted(stories, key=lambda s: (s.first_at, s.id))


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
    segments: Dict[str, Counter] = defaultdict(Counter)
    for _, url in links:
        host, _, rest = bare(url).partition("/")
        segments[host][rest.split("/")[0].lower()] += 1

    def platform(host: str) -> bool:
        seen = segments[host]
        return len(seen) >= PLATFORM_MIN_SEGMENTS and seen.most_common(1)[0][1] < 0.5 * sum(seen.values())

    platforms = {host for host in segments if platform(host)}
    found: Dict[str, Tuple[Set[str], Set[str], Set[str]]] = defaultdict(lambda: (set(), set(), set()))
    for voice, url in links:
        host, _, rest = bare(url).partition("/")
        if host in platforms:
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


__all__ = ["StoryPost", "Story", "Suggestion", "group", "roles", "count_voices", "suggestions",
           "source_site", "title_key", "anchors"]
