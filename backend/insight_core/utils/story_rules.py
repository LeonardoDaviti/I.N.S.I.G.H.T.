"""One story, many sources (issue 0050): the rules that join posts into stories, each post's
role and a story's voices. Pure functions over plain data: the story job (services/stories_service.py)
loads the posts and writes what these return. Each story is a tree (tree_rules.py, issue 0064);
Discover's rules are discover_rules.py (issue 0071 split them out of this file).

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
- **On X (issue 0066)** the platform says how tweets connect, and that is as certain as an address:
  - `repost`: a repost stored apart from its original (one address, 0049) hangs from it; a repost
    is a share, and never its address's own page;
  - `thread`: an author's reply to itself hangs from the tweet of its own it quotes, stored from the
    24 hours before (issue 0103), else from the post right before it in its source's timeline, when that is the author's own
    (not a repost, not a reply to another account); within 24 hours. Its posts are one story, whatever
    the sources: a thread is one item;
  - `quote`: a quoting tweet hangs from the tweet it quotes; a stored one joins its story
    within 72 hours (as a citation), whatever the place.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.utils import titles
from insight_core.utils.addresses import bare, host_of, is_tweet, site_of, tweet_author
from insight_core.utils.post_links import NUMBERISH, PLATFORM_KINDS, is_home, is_reference
from insight_core.utils.tree_rules import _PAGE, SLUG_MIN_WORDS, _origin_node, _slug_words, tree

# Each tuned value says whether it was measured (issue 0071). "The prototype's": the value of
# plan/research/dedup-prototype, whose rules were checked as a whole (0050: 24 stories, none wrong),
# never one value against another.
SAME_TEXT_WITHIN = timedelta(days=30)     # the prototype's, not measured
SAME_TEXT_MIN_CHARS = 120                 # the prototype's, not measured
SAME_TITLE_WITHIN = timedelta(days=7)     # the prototype's, not measured
SAME_TITLE_MIN_WORDS = 5                  # the prototype's, not measured
SAME_ADDRESS_WITHIN = SAME_TEXT_WITHIN    # two posts at one address (0064), as a shared text
LINK_WITHIN = timedelta(hours=72)         # the prototype's, not measured
THREAD_WITHIN = timedelta(hours=24)       # a reply to itself continues the author's own tweet it quotes, else the one before it (0066, 0103); not measured
# A post with 3+ anchors is a roundup: the prototype's value. Measured, the rule: its first link's
# join is right 34 of 40 times on the lab (0050); no other count compared.
ROUNDUP_ANCHORS = 3
LINK_POST_MAX_WORDS = 60          # a Reddit or HN post with fewer words of its own is a share; the prototype's, not measured
LINK_POST_KINDS = ("reddit", "hn")   # the kinds whose posts can be a link with a few words of its own
SIGNATURE_SHARE = 0.25            # a link in 25% of a source's posts ...
SIGNATURE_MIN_POSTS = 4           # ... and in 4 of them at least is the source's signature (the prototype's, not measured)
WORD = re.compile(r"\w+", re.U)

REASONS = ("address", "text", "title", "link", "citation", "thread", "quote")   # why a post is in its story; Mark X adds more
# Kinds whose posts' addresses are not their own pages: an HN item is the page it links, a Saved
# page is anyone's. Their posts never claim an address.
NOT_PUBLISHERS = ("hn", "saved")
HOME_SITE_SHARE = 0.5   # a source whose address is elsewhere publishes on a site holding half its posts; not measured


@dataclass
class StoryPost:
    """What the rules read of one post."""

    id: str
    source_id: str
    kind: str                       # post_links.source_kind
    own_site: str                   # its source's publication (SourceFacts.publication): a website's voice
    t: datetime                     # published_at, else fetched_at
    title: Optional[str] = None
    # The text's start its stored title said, when that is more than the title shown (issue 0076: a bridge's
    # title is its post's first ~85 characters, two lines glued): copies of one post share it.
    opening: Optional[str] = None
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
    quoted_words: Dict[str, str] = field(default_factory=dict)   # page -> its own words as quoted (0070)
    # Who else of your sources put this tweet before you (issue 0068): the sources that reposted it
    # (from posts.reposted_by), each a share voice in its story, and its author's own source when
    # the row is another source's repost, a report voice. Never the row's own source.
    reposters: Tuple[str, ...] = ()
    author_source: Optional[str] = None
    stored_at: Optional[datetime] = None   # when INSIGHT stored it (posts.created_at): what a story's id keeps to (0072)
    date_alone: Optional[bool] = None      # its time is a date alone; None: told by the time (`date_only`)
    undated: bool = False                  # the source gave no date: its time is when it was fetched (0076)

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
    def link_post(self) -> bool:
        """A Reddit or HN post that is mostly a link (fewer than LINK_POST_MAX_WORDS words of its own)."""
        return self.kind in LINK_POST_KINDS and (self.words or 0) < LINK_POST_MAX_WORDS

    @property
    def text_key(self) -> Optional[str]:
        return text_key(self.content_hash, self.text_chars)

    @property
    def title_key(self) -> Optional[str]:
        return title_key(self.title)

    @property
    def title_keys(self) -> Tuple[str, ...]:
        """What it joins by as a title (SAME_TITLE_WITHIN): its title's key, and its opening's (issue 0076)."""
        keys_ = (self.title_key, title_key(self.opening) if self.opening else None)
        return tuple(dict.fromkeys(k for k in keys_ if k))

    @property
    def trusted_time(self) -> bool:
        """Its time can order it (issue 0064): a time of day (not a date alone, 00:00:00), not a
        Saved page (the day you saved it), not a watched page updated since its date, not a post its
        source gave no date (issue 0076: its fetch's time, or a made-up backlog time)."""
        return not (self.kind == "saved" or self.updated or self.date_only or self.undated)

    @property
    def date_only(self) -> bool:
        """Its time is a date alone: when that day it was posted is unknown (issue 0072 D). As the post
        was read (`date_alone`), else told by its time, 00:00:00 UTC."""
        return self.date_alone if self.date_alone is not None else date_alone(self.t)

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


def date_alone(t: datetime) -> bool:
    """A time that is a date alone, as feeds without a time of day are stored: 00:00:00 UTC."""
    t = t.astimezone(timezone.utc) if t.tzinfo else t
    return (t.hour, t.minute, t.second, t.microsecond) == (0, 0, 0, 0)


def title_key(title: Optional[str]) -> Optional[str]:
    """A title as two posts share it: the words of its comparable form (utils/titles.py: styled letters
    as plain, issue 0070; entities decoded, issue 0071)."""
    words = WORD.findall(titles.title_key(title))
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


@lru_cache(maxsize=1 << 15)   # read for each address of each post, in each group of a run
def _page_key(url: str) -> Optional[Tuple[str, str, Tuple[str, ...]]]:
    """What names a page on its host whatever its section (issue 0070): (host, its last segment, its
    path's numbers and dates), when the last segment is a slug of SLUG_MIN_WORDS+ words of letters
    (not an id), and the page is no reference page (a /docs/ or /collections/ page is another one)."""
    words = _slug_words(url)
    if sum(1 for w in words if re.fullmatch(r"[^\W\d_]+", w)) < SLUG_MIN_WORDS or is_reference(url):
        return None
    _, _, rest = bare(url).partition("/")
    segments = [s for s in re.split(r"[?#]", rest, maxsplit=1)[0].split("/") if s]
    return host_of(url), segments[-1].lower(), tuple(s for s in segments[:-1] if NUMBERISH.match(s))


def page_aliases(posts: Sequence[StoryPost]) -> Dict[str, str]:
    """Another path of a website's own page (issue 0070): address -> the stored page's address, for
    the posts' and their links' addresses on one host with its last segment, a slug (_page_key):
    anthropic.com/engineering/redesigning-source-control is anthropic.com/research/redesigning-source-control,
    darioamodei.com/machines-of-loving-grace is darioamodei.com/essay/machines-of-loving-grace, and a
    language before it (openai.com/ru-RU/index/...) is skipped with the section. A slug two stored
    pages share (a weekly series' "this-week-in-..." under its dates) names neither."""
    own: Dict[Tuple[str, str, Tuple[str, ...]], Set[str]] = defaultdict(set)
    for p in posts:
        if p.kind == "site" and p.on_own_site and _page_key(p.url):
            own[_page_key(p.url)].add(p.url)
    out: Dict[str, str] = {}
    for url in {u for p in posts for u in ((p.url,) if p.url else ()) + tuple(t for t, _ in p.links)}:
        pages = own.get(_page_key(url)) or set()
        if len(pages) == 1 and url not in pages:
            out[url] = next(iter(pages))
    return out


def own_quote(post: StoryPost) -> Optional[str]:
    """The tweet of its own account a tweet quotes (issue 0103): what a reply of the author to itself
    continues, when its source holds it from the 24 hours before."""
    if post.quoted and post.author and (tweet_author(post.quoted) or "").lower() == post.author.lower():
        return post.quoted
    return None


def threads(posts: Iterable[StoryPost]) -> Dict[str, str]:
    """Each reply of an author to itself -> its parent (issue 0066), its author's own tweet within 24
    hours. A thread starts at the author's own post, never at a repost of another account.
    - A reply that quotes a tweet of its own account continues that tweet (issue 0103), when its source
      holds it from the 24 hours before: the account's previous tweet may be about something else
      (a self-quote of the 15:19 tweet at 16:39 is no reply to the 16:22 thread on another model).
    - Otherwise (that tweet isn't stored, or is older: "a related tweet from earlier", a reference
      within the thread before it) the post right before it in its source's timeline (reposts included).
      Measured on the lab (0103): the 2 of 44 stored self-quotes past 24 hours both continue the
      tweet right before them."""
    timeline: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in sorted(posts, key=_order):
        if p.kind == "x":
            timeline[p.source_id].append(p)
    out: Dict[str, str] = {}
    for run in timeline.values():
        own_row: Dict[str, StoryPost] = {}   # address -> the source's first own row of it
        for p in run:
            if p.own_tweet and p.url:
                own_row.setdefault(p.url, p)
        for i, p in enumerate(run):
            if not (p.own_tweet and p.reply_to):
                continue
            quoted = own_row.get(own_quote(p) or "")
            if quoted is not None and _order(quoted) < _order(p) and p.t - quoted.t <= THREAD_WITHIN:
                out[p.id] = quoted.id
            elif i and run[i - 1].own_tweet and p.t - run[i - 1].t <= THREAD_WITHIN:
                out[p.id] = run[i - 1].id
    return out


@dataclass
class Edge:
    """One connection the rules found (issue 0072 A, stored in `post_edges`): `src` joins `dst` (a post's
    id, or _PAGE + an outside page's address) by `kind`, a REASONS join, or `mention` (a roundup lists
    it and is not in its story). `via`: the key both hold (`keys`) when a key made it."""
    src: str
    dst: str
    kind: str
    via: Optional[str] = None


@dataclass
class Grouping:
    """What `grouping` finds among some posts: their stories, every connection, each node's group (its
    root) and each roundup's listed nodes. The incremental job (issue 0072 A) reads the last three to
    tell which stories a new post can change."""
    stories: List[Story]
    edges: List[Edge]
    root: Dict[str, str]             # node (a post id, or _PAGE + an address) -> its group's root
    listed: Dict[str, List[str]]     # a roundup -> the nodes it lists after its first


def group(posts: Sequence[StoryPost], *, replies: Optional[Dict[str, str]] = None) -> List[Story]:
    """The stories among `posts` (2+ sources each), first post first, each a tree (issue 0064)."""
    return grouping(posts, replies=replies).stories


def grouping(posts: Sequence[StoryPost], *, replies: Optional[Dict[str, str]] = None) -> Grouping:
    """`group`, with what it found on the way. `replies`: each thread reply -> the post it continues,
    when known (the stored thread edges; `threads(posts)` when None)."""
    posts = sorted(posts, key=_order)
    by_id = {p.id: p for p in posts}
    # A link to an address is a link to its own page when one is stored: the row a link resolves
    # to (the first seen at the address) may be another source's post of that page (HN's). Another
    # path of a website's page is that page too (issue 0070, page_aliases).
    aliases = page_aliases(posts)
    origin_of = address_origins(posts)
    origin_of.update({alias: origin_of[url] for alias, url in aliases.items() if url in origin_of})

    def resolve(what: str, target: str) -> Tuple[str, str]:
        if what == "url":
            return ("post", origin_of[target]) if target in origin_of else (what, target)
        cited = by_id.get(target)
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
    edges: List[Edge] = []
    for p in posts:
        uf.find(p.id)

    def join(src: str, dst: str, kind: str, via: Optional[str] = None) -> None:
        uf.union(src, dst)
        edges.append(Edge(src, dst, kind, via))

    def chain(same: Dict[str, List[StoryPost]], within: timedelta, reason: str, via: Callable[[str], str]) -> None:
        for key, run in same.items():
            for a, b in zip(run, run[1:]):
                if a.source_id != b.source_id and b.t - a.t <= within:
                    join(b.id, a.id, reason, via(key))
                    why[a.id].add(reason)
                    why[b.id].add(reason)

    by_text: Dict[str, List[StoryPost]] = defaultdict(list)
    by_title: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in posts:
        if p.text_key:
            by_text[p.text_key].append(p)
        for key in p.title_keys:
            by_title[key].append(p)
    chain(by_text, SAME_TEXT_WITHIN, "text", lambda key: "h:" + key)
    chain(by_title, SAME_TITLE_WITHIN, "title", lambda key: "t:" + key)
    by_url: Dict[str, List[StoryPost]] = defaultdict(list)
    for p in posts:
        if p.url:
            by_url[aliases.get(p.url, p.url)].append(p)
    chain(by_url, SAME_ADDRESS_WITHIN, "address", lambda url: page_key(url) or "u:" + url)

    linkers: Dict[Tuple[str, str], List[StoryPost]] = defaultdict(list)
    every: Dict[str, List[Tuple[str, str]]] = {}     # every anchor of a post: its citations
    focused: Dict[str, List[Tuple[str, str]]] = {}   # what it is about: a roundup's first anchor only
    quotes: Dict[str, str] = {}   # a quoting tweet -> the stored tweet it quotes (issue 0066)
    listed: Dict[str, List[Tuple[str, str]]] = {}    # a roundup -> the anchors it mentions, in order
    for p in posts:
        every[p.id] = resolved(p)
        # A quote is what its tweet is about, never one of a roundup's listed links.
        quote = quote_of(p)
        points = [anchor for anchor in every[p.id] if anchor != quote]
        if len(points) >= ROUNDUP_ANCHORS:
            for anchor in points[1:]:
                mentioned[anchor].add(p.id)
            listed[p.id] = points[1:]
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
                    join(p.id, cited.id, "citation")
                    why[p.id].add("citation")
                    why[cited.id].add("citation")
        else:
            near = [p for p in ps if p.t - ps[0].t <= LINK_WITHIN]   # ps is in time order
            if len({p.place for p in near}) >= 2:
                for p in near:
                    join(p.id, _PAGE + target, "link", "u:" + target)
                    why[p.id].add("link")
    # On X (issue 0066): a thread is one story, and a quote joins the stored tweet it quotes.
    replies = threads(posts) if replies is None else {c: p for c, p in replies.items() if c in by_id and p in by_id}
    joins = [(child, parent, "thread", None) for child, parent in replies.items()]
    joins += [(child, parent, "quote", "u:" + by_id[child].quoted) for child, parent in quotes.items()
              if abs(by_id[child].t - by_id[parent].t) <= LINK_WITHIN]
    for child, parent, reason, via in joins:
        join(child, parent, reason, via)
        why[child].add(reason)
        why[parent].add(reason)

    def grouped() -> Dict[str, List[StoryPost]]:
        out: Dict[str, List[StoryPost]] = defaultdict(list)
        for p in posts:
            out[uf.find(p.id)].append(p)
        return out

    def is_story(group_posts: Sequence[StoryPost]) -> bool:
        """2+ sources (a reposter is one, issue 0068; a Saved page none, 0070), or one account's thread
        or quote of itself (0066)."""
        return len({s for p in group_posts if p.kind != "saved" for s in (p.source_id, *p.other_sources)}) >= 2 \
            or any(why[p.id] & {"thread", "quote"} for p in group_posts)

    members = grouped()
    # A post with links about one story (issue 0070): a platform's post (PLATFORM_KINDS) with 3+ links,
    # whose first link joins no story, is a member of the story its first link into a story is the
    # origin of, when it links that story twice or more (the origin and a page or post of the
    # story's) and links no other story. r/LocalLLaMA's "mistralai/Mistral-Large-4-1T-A52B · Hugging
    # Face" lists GGUFs, then Mistral's announcement (the origin) and the model page akhaliq links.
    # An article or a digest with links stays a roundup: measured on the lab, websites' were mostly
    # essays and digests building on the story (Mark X tells those apart by meaning).
    story_of = {node: uf.find(node) for node in uf.parent if is_story(members[uf.find(node)])}
    pages: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)   # a story -> what its posts are and link
    for root, group_posts in members.items():
        if is_story(group_posts):
            for p in group_posts:
                pages[root] |= {("post", p.id), *every[p.id]}
    origins: Dict[str, Optional[str]] = {}
    for pid, mentions in listed.items():
        if by_id[pid].kind not in PLATFORM_KINDS or uf.find(pid) in pages:
            continue
        roots = {story_of.get(target if what == "post" else _PAGE + target) for what, target in mentions} - {None}
        if len(roots) != 1:
            continue
        [root] = roots
        first = next((what, target) for what, target in mentions
                     if story_of.get(target if what == "post" else _PAGE + target) == root)
        if root not in origins:
            origins[root] = _origin_node(tree(members[root], every=every, focused=focused, origin_of=origin_of,
                                              replies=replies, quotes=quotes))
        node = first[1] if first[0] == "post" else _PAGE + first[1]
        if origins[root] == node and len(pages[root].intersection(mentions)) >= 2:
            join(pid, node, "citation" if first[0] == "post" else "link")
            why[pid].add("citation" if first[0] == "post" else "link")
            focused[pid] = [first] + focused[pid][1:]
    members = grouped()
    roots = {root for root, group_posts in members.items() if is_story(group_posts)}
    mentions_of: Dict[str, Set[str]] = defaultdict(set)
    for (what, target), ps in mentioned.items():
        node = target if what == "post" else _PAGE + target
        if what == "post" and target not in by_id or what == "url" and node not in uf.parent:
            continue
        root = uf.find(node)
        for pid in sorted(ps):
            if uf.find(pid) != root:
                mentions_of[root].add(pid)
                if root in roots:
                    edges.append(Edge(pid, node, "mention"))

    stories = []
    for root, group_posts in members.items():
        if root not in roots:
            continue
        shape = tree(group_posts, every=every, focused=focused, origin_of=origin_of, replies=replies, quotes=quotes)
        # A date alone counts as that day's earliest timed post (issue 0072 D); the id is the post
        # stored first, so a post that joins later, however early it was posted, keeps it (0072 A).
        times = story_times(group_posts)
        ordered = sorted(group_posts, key=lambda p: (times[p.id], not p.date_only, *_order(p)[1:]))
        stored = [p for p in ordered if p.stored_at is not None]
        stories.append(Story(
            id=min(stored, key=lambda p: (p.stored_at, p.id)).id if stored else ordered[0].id,
            first_at=times[ordered[0].id], posts=ordered, voices=count_voices(group_posts),
            roles=roles(ordered),
            reasons={p.id: [r for r in REASONS if r in why[p.id]] for p in group_posts},
            mentions=mentions_of.get(root, set()),
            parents=shape.parents, origin_url=shape.origin_url, origin_title=shape.origin_title,
            origin_linked_by=shape.origin_linked_by,
        ))
    return Grouping(sorted(stories, key=lambda s: (s.first_at, s.id)), edges, {node: uf.find(node) for node in uf.parent},
                    {pid: [target if what == "post" else _PAGE + target for what, target in points]
                     for pid, points in listed.items()})


def story_times(posts: Sequence[StoryPost]) -> Dict[str, datetime]:
    """Each post's time as its story counts it (issue 0072 D): a date alone (`date_only`) counts as that
    day's earliest timed post among the story's (`trusted_time`), never its 00:00 (at that time it comes
    first: it is as early as that post, and is said first); with none that day, its date. A story's start, its order ("first") and the News window read it."""
    earliest: Dict[object, datetime] = {}
    for p in posts:
        if p.trusted_time:
            day = p.t.astimezone(timezone.utc).date()
            earliest[day] = min(earliest.get(day, p.t), p.t)
    return {p.id: earliest.get(p.t.astimezone(timezone.utc).date(), p.t) if p.date_only else p.t for p in posts}


def page_key(url: str) -> Optional[str]:
    """`_page_key` as a key (`keys`): "g:" + host, slug and the path's numbers."""
    key = _page_key(url)
    return "g:" + "|".join((key[0], key[1], *key[2])) if key else None


def keys(post: StoryPost) -> Set[str]:
    """What a post can join or change another by (issue 0072 A): its text ("h:"), its title ("t:"), its
    address and the pages it links ("u:"; a home page only when a post is stored at it: no anchor
    else), and each one's page key ("g:", another path of one page). The incremental job regroups
    the posts that hold a key a new or changed post holds."""
    out = set()
    if post.text_key:
        out.add("h:" + post.text_key)
    out |= {"t:" + key for key in post.title_keys}
    for url in ([post.url] if post.url else []) + [target for target, stored in post.links if stored or not is_home(target)]:
        out.add("u:" + url)
        if page_key(url):
            out.add(page_key(url))
    return out


def roles(posts: Sequence[StoryPost]) -> Dict[str, str]:
    """report (its own writing) or share: a copy of an earlier post's text or title from another
    place, a Reddit or HN post that is mostly a link, or a repost. `posts` in time order."""
    first_text: Dict[str, str] = {}
    first_title: Dict[str, str] = {}
    out = {}
    for p in posts:
        text, titles_ = p.text_key, p.title_keys
        copy = (text and text in first_text and first_text[text] != p.place) or \
               any(title in first_title and first_title[title] != p.place for title in titles_)
        out[p.id] = "share" if copy or p.link_post or p.reposted else "report"   # a repost is a share (0066)
        if text:
            first_text.setdefault(text, p.place)
        for title in titles_:
            first_title.setdefault(title, p.place)
    return out


def text_key(content_hash: Optional[str], chars: int) -> Optional[str]:
    """What copies of one text share: its hash, when it is long enough to tell (SAME_TEXT_MIN_CHARS)."""
    return content_hash if content_hash and chars >= SAME_TEXT_MIN_CHARS else None


def voice_groups(items: Iterable[Tuple[Any, Optional[str], str]]) -> List[List[Any]]:
    """The voices among `items` ((key, text key, voice) each: a post, or a source that wrote or
    reposted the tweet a post holds, issue 0068): items of one voice, and copies of one text, are one
    voice. Each voice is its items' keys in the order given, the voices in the order of their first."""
    uf = _UnionFind()
    keys: Dict[str, Any] = {}
    order = []
    for node, text, voice in items:
        order.append(node)
        uf.find(node)
        for key in (("text:" + text) if text else None, "voice:" + voice):
            if key is None:
                continue
            if key in keys:
                uf.union(node, keys[key])
            else:
                keys[key] = node
    groups: Dict[Any, List[Any]] = {}
    for node in order:
        groups.setdefault(uf.find(node), []).append(node)
    return list(groups.values())


def count_voices(posts: Sequence[StoryPost]) -> int:
    """How many voices a story has: posts of one voice, and copies of one text, are one. A source
    that reposted a tweet, or wrote the tweet another source holds, is a voice (issue 0068): one
    with its posts in the story, if it has some. A page you saved is no voice (issue 0070)."""
    posts = [p for p in posts if p.kind != "saved"]
    return len(voice_groups([*((p.id, p.text_key, p.voice) for p in posts),
                             *((f"{p.id}>{s}", None, reposter_voice(s)) for p in posts for s in p.other_sources)]))


def named_voices(posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A story's voices as you know them (issue 0082), the ones count_voices counts, one item each, so
    a count reads as its names and "+N". `posts` in the order to name them, each {source_id, name (its
    source's), kind, voice (StoryPost.voice), text_key, others: [{id, name}] (its other_sources)}; a
    page you saved is none. Each voice is {id, name, place, with}: named by its first post's source,
    a Reddit author as u/<author> with `place` its subreddit, a publication's copies once; `with` the
    voice's other sources (a copy's, a reposter's), each once."""
    items = []
    for i, p in enumerate(posts):
        if p["kind"] == "saved":
            continue
        items.append(((i, -1), p["text_key"], p["voice"]))
        items += [((i, j), None, reposter_voice(s["id"])) for j, s in enumerate(p["others"])]
    out = []
    for group in voice_groups(items):
        sources = [{"id": posts[i]["source_id"], "name": posts[i]["name"]} if j < 0 else posts[i]["others"][j]
                   for i, j in group]
        (i, j), first = group[0], dict(sources[0])
        if j < 0 and posts[i]["voice"].startswith("reddit:"):
            first.update(name="u/" + posts[i]["voice"].split(":", 1)[1], place=posts[i]["name"])
        seen = {first["id"]}
        first["with"] = [s for s in sources if not (s["id"] in seen or seen.add(s["id"]))]
        out.append(first)
    return out


def reposter_voice(source_id: str) -> str:
    """A reposting source's voice, as StoryPost.voice says an X account's (issue 0068)."""
    return "source:" + source_id


def source_site(hosts: Iterable[Tuple[str, int]], of: Callable[[str], str] = site_of) -> str:
    """A source's own site: the most common site of its posts' hosts ((host, posts) pairs); with
    `of=publication_of`, its publication (issue 0069)."""
    sites: Counter = Counter()
    for host, n in hosts:
        sites[of(host)] += n
    return sites.most_common(1)[0][0] if sites else ""


__all__ = ["StoryPost", "Story", "Edge", "Grouping", "group", "grouping", "story_times", "keys", "page_key", "threads", "date_alone",
           "address_origins", "page_aliases", "roles", "count_voices", "voice_groups", "named_voices", "text_key", "reposter_voice", "source_site", "title_key",
           "anchors"]
