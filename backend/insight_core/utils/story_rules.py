"""One story, many sources: the rules that join posts into stories (`grouping`), each post's role and a story's
voices. Pure functions over plain data; the story job (services/stories_service.py) loads the posts and writes what
these return. Each story is a tree (tree_rules.py); the thresholds are here, in one place.

Posts join by a shared text, title, address, an outside page linked by 2+ places, a citation of a stored post, and
on X by thread and quote. Joining by links goes by where a post was said (`place`: the voice, but the subreddit on
Reddit); posts of one place never join through links. A post with ROUNDUP_ANCHORS+ anchors is a roundup: it joins
only the story of its first and mentions the others (a told round-up, `StoryPost.roundup`, joins none).
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from insight_core.utils import titles, voice
from insight_core.utils.addresses import bare, host_of, is_tweet, paper_id, paper_page_order, site_of, tweet_author
from insight_core.utils.post_links import NUMBERISH, PLATFORM_KINDS, is_home, is_reference
from insight_core.utils.tree_rules import _PAGE, SLUG_MIN_WORDS, _origin_node, _slug_words, tree

# "The prototype's": plan/research/dedup-prototype's value, checked as a whole, never one value against another.
SAME_TEXT_WITHIN = timedelta(days=30)     # the prototype's, not measured
SAME_TEXT_MIN_CHARS = 120                 # the prototype's, not measured
SAME_TITLE_WITHIN = timedelta(days=7)     # the prototype's, not measured
SAME_TITLE_MIN_WORDS = 5                  # the prototype's, not measured
SAME_ADDRESS_WITHIN = SAME_TEXT_WITHIN    # two posts at one address (0064), as a shared text
LINK_WITHIN = timedelta(hours=72)         # the prototype's, not measured
THREAD_WITHIN = timedelta(hours=24)       # a reply to itself continues the author's own tweet; not measured
# A reply opening a quick run of replies THREAD_GAP or more after the tweet before it starts another thread (measured).
THREAD_GAP = timedelta(hours=1)
THREAD_BURST = timedelta(minutes=2)
ROUNDUP_ANCHORS = 3
LINK_POST_MAX_WORDS = 60          # a Reddit or HN post with fewer words of its own is a share; not measured
LINK_POST_KINDS = ("reddit", "hn")   # the kinds whose posts can be a link with a few words of its own
SIGNATURE_SHARE = 0.25            # a link in 25% of a source's posts ...
SIGNATURE_MIN_POSTS = 4           # ... and in 4 of them at least is the source's signature (the prototype's, not measured)
WORD = re.compile(r"\w+", re.U)

REASONS = ("address", "text", "title", "link", "citation", "thread", "quote")   # why a post is in its story; Mark X adds more
# Kinds whose posts' addresses are not their own pages (an HN item, a Saved page): they never claim an address.
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
    # the text's start its stored title said, when more than the title shown: copies of one post share it
    opening: Optional[str] = None
    content_hash: Optional[str] = None
    text_chars: int = 0             # len(content)
    words: Optional[int] = None     # words of its own (Reddit, HN): the share rule
    author: Optional[str] = None    # a Reddit post's author; a tweet's account
    url: Optional[str] = None       # normalized
    links: List[Tuple[str, Optional[str]]] = field(default_factory=list)   # (target, stored post id)
    link_texts: Dict[str, str] = field(default_factory=dict)              # target -> the link's words
    updated: bool = False           # a watched page that changed since its date
    home_site: Optional[str] = None  # the site its source publishes on; None: its own site (not HN, Saved)
    reposted: bool = False          # a tweet of another account its source reposted
    reply_to: Optional[str] = None  # the account a tweet replies to
    quoted: Optional[str] = None    # the tweet it quotes (normalized)
    quoted_words: Dict[str, str] = field(default_factory=dict)   # page -> its own words as quoted
    # the sources that reposted it (share voices), and its author's own source when the row is another source's
    # repost; never the row's own source
    reposters: Tuple[str, ...] = ()
    author_source: Optional[str] = None
    stored_at: Optional[datetime] = None   # when INSIGHT stored it (posts.created_at): what a story's id keeps to
    date_alone: Optional[bool] = None      # its time is a date alone; None: told by the time (`date_only`)
    undated: bool = False                  # the source gave no date: its time is when it was fetched
    # its page states only its month (published_precision "month"): its time is the 1st, the post any day of it
    month_alone: bool = False
    moved_to: Optional[str] = None         # where its page moved (a redirect stub's target), normalized
    # a round-up as Mark X tells it (markx/units.py): it joins no story by its links
    roundup: bool = False
    # its owner's voice when that is another (SourceFacts.owners), and each of `other_sources`': News counts by owner
    owner: Optional[str] = None
    other_owners: Tuple[Optional[str], ...] = ()
    # its Mark X reading says it reports an event (None: no reading); a non-report never leads (`lead_order`)
    report: Optional[bool] = None

    @property
    def other_sources(self) -> Tuple[str, ...]:
        return ((self.author_source,) if self.author_source else ()) + self.reposters

    @property
    def voice(self) -> str:
        """Its own voice (utils/voice.py), stored as story_posts.voice."""
        return voice.key(self.kind, self.source_id, self.own_site, self.author)

    @property
    def place(self) -> str:
        """Where it was said: its voice, but a subreddit (not its poster) on Reddit."""
        return voice.source_key(self.source_id) if self.kind == "reddit" else self.voice

    @property
    def link_post(self) -> bool:
        return self.kind in LINK_POST_KINDS and (self.words or 0) < LINK_POST_MAX_WORDS

    @property
    def text_key(self) -> Optional[str]:
        return text_key(self.content_hash, self.text_chars)

    @property
    def title_key(self) -> Optional[str]:
        return title_key(self.title)

    @property
    def title_keys(self) -> Tuple[str, ...]:
        keys_ = (self.title_key, title_key(self.opening) if self.opening else None)
        return tuple(dict.fromkeys(k for k in keys_ if k))

    @property
    def trusted_time(self) -> bool:
        """A time of day, not a Saved page, not a watched page updated since its date, not an undated post."""
        return not (self.kind == "saved" or self.updated or self.date_only or self.undated)

    @property
    def date_only(self) -> bool:
        return self.month_alone or (self.date_alone if self.date_alone is not None else date_alone(self.t))

    @property
    def last_t(self) -> datetime:
        """The latest its time can be: the 1st of the next month for a month alone, else its time."""
        if not self.month_alone:
            return self.t
        t = self.t.astimezone(timezone.utc) if self.t.tzinfo else self.t
        return t.replace(year=t.year + t.month // 12, month=t.month % 12 + 1, day=1)

    @property
    def on_own_site(self) -> bool:
        """It is at an address on the site its source publishes on (a repost never is)."""
        home = self.home_site if self.home_site is not None else ("" if self.kind in NOT_PUBLISHERS else site_of(self.own_site))
        return bool(home and self.url and not self.reposted and site_of(host_of(self.url)) == home)

    @property
    def own_tweet(self) -> bool:
        return bool(self.kind == "x" and self.author and not self.reposted
                    and (self.reply_to is None or self.reply_to.lower() == self.author.lower()))


def apart(a: StoryPost, b: StoryPost) -> timedelta:
    """How far apart two posts' times are: zero when they may be the same time (a month alone spans its month)."""
    return max(timedelta(0), max(a.t, b.t) - min(a.last_t, b.last_t))


def date_alone(t: datetime) -> bool:
    t = t.astimezone(timezone.utc) if t.tzinfo else t
    return (t.hour, t.minute, t.second, t.microsecond) == (0, 0, 0, 0)


def title_key(title: Optional[str]) -> Optional[str]:
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
    # its tree: post id -> (parent post, parent page, reason); the origin post has (None, None, None)
    parents: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = field(default_factory=dict)
    origin_url: Optional[str] = None       # the origin, when it is a page outside INSIGHT
    origin_title: Optional[str] = None     # its title by evidence (origin_title)
    origin_linked_by: int = 0              # how many of the story's posts are about it


def _order(post: StoryPost) -> Tuple[datetime, int, str]:
    """Time order; tweets of one second by their ids (X gives them in the order written)."""
    return post.t, int(post.url.rsplit("/", 1)[-1]) if is_tweet(post.url) else 0, post.id


def anchors(post: StoryPost) -> List[Tuple[str, str]]:
    """('post', id) for a stored post, ('url', address) for an outside page. Home and profile pages, and the post
    itself, are no anchor; a stored post is never a home page."""
    out: Dict[Tuple[str, str], None] = {}
    for url, stored_id in post.links:
        if stored_id == post.id or (not stored_id and is_home(url)):
            continue
        out[("post", stored_id) if stored_id else ("url", url)] = None
    return list(out)


def _time_key(post: StoryPost) -> Tuple[bool, datetime, int, str]:
    return (not post.trusted_time, *_order(post))


def address_origins(posts: Iterable[StoryPost]) -> Dict[str, str]:
    """address -> the post at it on its source's own site (two such: the earlier trustworthy time)."""
    out: Dict[str, StoryPost] = {}
    for p in posts:
        if p.on_own_site and (p.url not in out or _time_key(p) < _time_key(out[p.url])):
            out[p.url] = p
    return {url: p.id for url, p in out.items()}


@lru_cache(maxsize=1 << 15)   # read for each address of each post, in each group of a run
def _page_key(url: str) -> Optional[Tuple[str, str, Tuple[str, ...]]]:
    """(host, last segment, the path's numbers) naming a page whatever its section, when the last segment is a slug of
    SLUG_MIN_WORDS+ words and no reference page; a paper: (host, "paper " + its id, ())."""
    paper = paper_id(url)
    if paper:
        return host_of(url), "paper " + paper, ()
    words = _slug_words(url)
    if sum(1 for w in words if re.fullmatch(r"[^\W\d_]+", w)) < SLUG_MIN_WORDS or is_reference(url):
        return None
    _, _, rest = bare(url).partition("/")
    segments = [s for s in re.split(r"[?#]", rest, maxsplit=1)[0].split("/") if s]
    return host_of(url), segments[-1].lower(), tuple(s for s in segments[:-1] if NUMBERISH.match(s))


def page_aliases(posts: Sequence[StoryPost]) -> Dict[str, str]:
    """address -> the stored page's address, for another path of a website's own page (one host, the same slug:
    /engineering/<slug> is /research/<slug>), a paper's paths and versions, and a page that moved."""
    own: Dict[Tuple[str, str, Tuple[str, ...]], Set[str]] = defaultdict(set)
    for p in posts:
        if p.kind == "site" and p.on_own_site and _page_key(p.url):
            own[_page_key(p.url)].add(p.url)
    out: Dict[str, str] = {}
    papers: Dict[Tuple[str, str, Tuple[str, ...]], Set[str]] = defaultdict(set)
    for url in {u for p in posts for u in ((p.url,) if p.url else ()) + tuple(t for t, _ in p.links)}:
        pages = own.get(_page_key(url)) or set()
        if len(pages) == 1 and url not in pages:
            out[url] = next(iter(pages))
        elif not pages and paper_id(url):
            papers[_page_key(url)].add(url)
    out.update(paper_aliases(papers.values()))
    out.update({p.url: out.get(p.moved_to, p.moved_to) for p in posts if p.url and p.moved_to and p.moved_to != p.url})
    return out


def paper_aliases(papers: Iterable[Iterable[str]], stored: Iterable[str] = ()) -> Dict[str, str]:
    """Each address of a paper -> the one that names it: a `stored` one, else by addresses.paper_page_order."""
    out: Dict[str, str] = {}
    stored = set(stored)
    for addresses in papers:
        addresses = set(addresses)
        named = min(addresses & stored or addresses, key=paper_page_order)
        out.update({url: named for url in addresses if url != named})
    return out


def link_via(target: str) -> str:
    """Edge.via of a link join: "u:" + address, for a paper the key all its paths share ("g:")."""
    return (page_key(target) or "u:" + target) if paper_id(target) else "u:" + target


def one_page(post: StoryPost, aliases: Mapping[str, str]) -> StoryPost:
    """A post whose links to another path of a paper are links to its one page."""
    if not any(target in aliases for target, _ in post.links):
        return post
    links: Dict[str, Optional[str]] = {}
    for target, stored in post.links:
        named = aliases.get(target, target)
        if links.get(named) is None:
            links[named] = stored
    texts: Dict[str, str] = {}
    for target, text in post.link_texts.items():
        texts.setdefault(aliases.get(target, target), text)
    quoted = {aliases.get(target, target): words for target, words in post.quoted_words.items()}
    return replace(post, links=list(links.items()), link_texts=texts, quoted_words=quoted)


def own_quote(post: StoryPost) -> Optional[str]:
    if post.quoted and post.author and (tweet_author(post.quoted) or "").lower() == post.author.lower():
        return post.quoted
    return None


def threads(posts: Iterable[StoryPost]) -> Dict[str, str]:
    """Each reply of an author to itself -> its parent within THREAD_WITHIN: the stored tweet of its own it quotes,
    else the post right before it in its source's timeline unless it opens another thread. Never a repost."""
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
            elif i and run[i - 1].own_tweet and p.t - run[i - 1].t <= THREAD_WITHIN and not opens_thread(run, i):
                out[p.id] = run[i - 1].id
    return out


def opens_thread(run: Sequence[StoryPost], i: int) -> bool:
    """The reply `run[i]` begins another thread: its next reply follows within THREAD_BURST while the tweet before it
    is THREAD_GAP or more earlier. A lone late reply still continues the tweet before it."""
    p, nxt = run[i], run[i + 1] if i + 1 < len(run) else None
    return (p.t - run[i - 1].t >= THREAD_GAP and nxt is not None and nxt.own_tweet and bool(nxt.reply_to)
            and nxt.t - p.t <= THREAD_BURST)


@dataclass
class Edge:
    """One connection (stored in `post_edges`): `src` joins `dst` (a post id, or _PAGE + an address) by `kind` (a
    REASONS join, or `mention`); `via`: the key both hold (`keys`) when a key made it."""
    src: str
    dst: str
    kind: str
    via: Optional[str] = None


@dataclass
class Grouping:
    """`grouping`'s stories, edges, each node's root and each roundup's listed nodes: the incremental job reads the
    last three to tell which stories a new post changes."""
    stories: List[Story]
    edges: List[Edge]
    root: Dict[str, str]             # node (a post id, or _PAGE + an address) -> its group's root
    listed: Dict[str, List[str]]     # a roundup -> the nodes it lists after its first (a told round-up: all)


def group(posts: Sequence[StoryPost], *, replies: Optional[Dict[str, str]] = None) -> List[Story]:
    return grouping(posts, replies=replies).stories


def grouping(posts: Sequence[StoryPost], *, replies: Optional[Dict[str, str]] = None) -> Grouping:
    """`group`, with what it found on the way. `replies`: thread reply -> the post it continues (None: `threads`)."""
    # a link to an address is a link to its stored own page; another path of a page or a paper is that page too
    aliases = page_aliases(posts)
    papers = {url: named for url, named in aliases.items() if paper_id(url)}
    posts = sorted((one_page(p, papers) for p in posts) if papers else posts, key=_order)
    by_id = {p.id: p for p in posts}
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
        links = dict(post.links)
        if not post.quoted or post.quoted not in links:
            return None
        anchor = resolve("post", links[post.quoted]) if links[post.quoted] else ("url", post.quoted)
        return anchor if anchor != ("post", post.id) else None
    uf = _UnionFind()
    why: Dict[str, Set[str]] = defaultdict(set)
    # a roundup's anchors are distinct (`resolved`) and each post is read once: a list, not a set, an anchor (memory)
    mentioned: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    edges: List[Edge] = []
    page_nodes: Dict[str, str] = {}

    def page_node(target: str) -> str:
        """_PAGE + an address, one string however often it is a node (memory: round-ups list thousands)."""
        node = page_nodes.get(target)
        if node is None:
            node = page_nodes[target] = _PAGE + target
        return node
    for p in posts:
        uf.find(p.id)

    def join(src: str, dst: str, kind: str, via: Optional[str] = None) -> None:
        uf.union(src, dst)
        edges.append(Edge(src, dst, kind, via))

    def chain(same: Dict[str, List[StoryPost]], within: timedelta, reason: str, via: Callable[[str], str]) -> None:
        for key, run in same.items():
            for a, b in zip(run, run[1:]):
                if a.source_id != b.source_id and apart(a, b) <= within:
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
    quotes: Dict[str, str] = {}   # a quoting tweet -> the stored tweet it quotes
    listed: Dict[str, List[Tuple[str, str]]] = {}    # a roundup -> the anchors it mentions, in order
    for p in posts:
        every[p.id] = resolved(p)
        quote = quote_of(p)
        points = [anchor for anchor in every[p.id] if anchor != quote]
        if len(points) >= ROUNDUP_ANCHORS:
            # a told round-up (a newsletter issue) is about none of its links, not even its first
            lead = 0 if p.roundup else 1
            for anchor in points[lead:]:
                mentioned[anchor].append(p.id)
            listed[p.id] = points[lead:]
            points = points[:lead]
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
            if cited.kind == "saved":
                # a saved page is still the outside page its linkers link: their link join holds, and it joins them
                # whatever its own date (0113)
                near = [p for p in ps if apart(p, ps[0]) <= LINK_WITHIN]   # ps is in time order
                if len({p.place for p in near}) >= 2:
                    for p in near:
                        join(p.id, cited.id, "citation")
                        why[p.id].add("citation")
                        why[cited.id].add("citation")
                    ps = [p for p in ps if p not in near]
            for p in ps:
                if p.place != cited.place and apart(p, cited) <= LINK_WITHIN:
                    join(p.id, cited.id, "citation")
                    why[p.id].add("citation")
                    why[cited.id].add("citation")
        else:
            near = [p for p in ps if apart(p, ps[0]) <= LINK_WITHIN]   # ps is in time order
            if len({p.place for p in near}) >= 2:
                for p in near:
                    join(p.id, page_node(target), "link", link_via(target))
                    why[p.id].add("link")
    replies = threads(posts) if replies is None else {c: p for c, p in replies.items() if c in by_id and p in by_id}
    joins = [(child, parent, "thread", None) for child, parent in replies.items()]
    joins += [(child, parent, "quote", "u:" + by_id[child].quoted) for child, parent in quotes.items()
              if apart(by_id[child], by_id[parent]) <= LINK_WITHIN]
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
        """2+ sources (a reposter counts; a Saved page doesn't), or one account's thread or self-quote."""
        return len({s for p in group_posts if p.kind != "saved" for s in (p.source_id, *p.other_sources)}) >= 2 \
            or any(why[p.id] & {"thread", "quote"} for p in group_posts)

    members = grouped()
    # A platform post of 3+ links whose first joins no story joins the story it links twice or more, when that is the
    # only story it links and the link is its origin (0070). An article or a digest with links stays a roundup.
    story_of = {node: uf.find(node) for node in uf.parent if is_story(members[uf.find(node)])}
    pages: Dict[str, Set[Tuple[str, str]]] = defaultdict(set)   # a story -> what its posts are and link
    for root, group_posts in members.items():
        if is_story(group_posts):
            for p in group_posts:
                pages[root] |= {("post", p.id), *every[p.id]}
    origins: Dict[str, Optional[str]] = {}
    for pid, mentions in listed.items():
        if by_id[pid].kind not in PLATFORM_KINDS or by_id[pid].roundup or uf.find(pid) in pages:
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
        saved_page = by_id.get(node) if first[0] == "post" else None
        as_origin = {node} | ({_PAGE + saved_page.url} if saved_page and saved_page.kind == "saved" and saved_page.url else set())
        if origins[root] in as_origin and len(pages[root].intersection(mentions)) >= 2:
            join(pid, node, "citation" if first[0] == "post" else "link")
            why[pid].add("citation" if first[0] == "post" else "link")
            focused[pid] = [first] + focused[pid][1:]
    members = grouped()
    roots = {root for root, group_posts in members.items() if is_story(group_posts)}
    mentions_of: Dict[str, Set[str]] = defaultdict(set)
    for (what, target), ps in mentioned.items():
        node = target if what == "post" else page_node(target)
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
        # the id is the post stored first: a post that joins later, however early posted, never takes it
        times = story_times(group_posts)
        ordered = sorted(group_posts, key=lambda p: (times[p.id], not p.date_only, *_order(p)[1:]))
        stored = [p for p in ordered if p.stored_at is not None]
        stories.append(Story(
            id=min(stored, key=lambda p: (p.stored_at, p.id)).id if stored else ordered[0].id,
            first_at=story_start(ordered, times), posts=ordered,
            voices=voice.count(group_posts, voice.Policy.STORIES_IX),
            roles=roles(ordered),
            reasons={p.id: [r for r in REASONS if r in why[p.id]] for p in group_posts},
            mentions=mentions_of.get(root, set()),
            parents=shape.parents, origin_url=shape.origin_url, origin_title=shape.origin_title,
            origin_linked_by=shape.origin_linked_by,
        ))
    return Grouping(sorted(stories, key=lambda s: (s.first_at, s.id)), edges, {node: uf.find(node) for node in uf.parent},
                    {pid: [target if what == "post" else page_node(target) for what, target in points]
                     for pid, points in listed.items()})


def story_times(posts: Sequence[StoryPost]) -> Dict[str, datetime]:
    """Each post's time as its story counts it: a date alone counts as that day's earliest timed post of the story,
    a month alone (`month_alone`) as that month's, else its date. A story's start, its order and the News window
    read it."""
    earliest: Dict[object, datetime] = {}
    for p in posts:
        if p.trusted_time:
            day = p.t.astimezone(timezone.utc).date()
            earliest[day] = min(earliest.get(day, p.t), p.t)
            earliest[day.year, day.month] = min(earliest.get((day.year, day.month), p.t), p.t)

    def counted(p: StoryPost) -> datetime:
        day = p.t.astimezone(timezone.utc).date()
        return earliest.get((day.year, day.month) if p.month_alone else day, p.t) if p.date_only else p.t
    return {p.id: counted(p) for p in posts}


# A post of no voice dated more than BACKGROUND_BEFORE before its story's first voiced post is background: a member,
# never the story's start, first post or News date. A voiced post is never background (0263).
BACKGROUND_BEFORE = LINK_WITHIN


def background(posts: Sequence[Any], times: Mapping[str, datetime]) -> Set[str]:
    """The ids of `posts` (with `id` and `kind`) that are background to their story."""
    voiced = [times[p.id] for p in posts if p.kind not in voice.NOT_VOICE and p.id in times]
    if not voiced or not isinstance(min(voiced), datetime):   # the prototype's ISO strings: no date to measure
        return set()
    edge = min(voiced) - BACKGROUND_BEFORE
    return {p.id for p in posts if p.kind in voice.NOT_VOICE and p.id in times and times[p.id] < edge}


# A post that says nothing of its own, or is read as no report, leads only when no post reports the event.
_NO_WORDS = re.compile(r"https?://\S+|\b(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/\S*)?|@\w+|\bR to\b|\bRT by\b", re.I)


def says_nothing(post: Any) -> bool:
    """A saved page with no text, or a post whose title and opening are only links and handles."""
    if post.kind in voice.NOT_VOICE and not post.text_chars:
        return True
    own = " ".join(t for t in (post.title, post.opening) if t)
    return bool(own.strip()) and not re.search(r"[^\W\d_]", _NO_WORDS.sub(" ", own))


def lead_rank(post: Any) -> int:
    return 2 if says_nothing(post) else 1 if post.report is False else 0


def lead_order(posts: Sequence[Any], times: Mapping[str, datetime]) -> List[Any]:
    """`posts` lead first (never a background post, by `lead_rank`, then time, then id), the rest in time order."""
    bg = background(posts, times)
    ordered = sorted(posts, key=lambda p: (p.id in bg, times[p.id], not p.date_only, p.id))
    if not ordered:
        return ordered
    lead = min(ordered, key=lambda p: (p.id in bg, lead_rank(p), times[p.id], not p.date_only, p.id))
    return [lead] + [p for p in ordered if p is not lead]


def story_start(posts: Sequence[Any], times: Mapping[str, datetime]) -> Optional[datetime]:
    """Its earliest post that is not background; None with no post timed."""
    bg = background(posts, times)
    return min((times[p.id] for p in posts if p.id in times and p.id not in bg), default=None)


def page_key(url: str) -> Optional[str]:
    key = _page_key(url)
    return "g:" + "|".join((key[0], key[1], *key[2])) if key else None


def keys(post: StoryPost) -> Set[str]:
    """The keys a post joins or changes others by: "h:" text, "t:" title, "u:" its address, where it moved and its
    links (a home page only when stored), and their "g:" page keys. The incremental job regroups by them."""
    out = set()
    if post.text_key:
        out.add("h:" + post.text_key)
    out |= {"t:" + key for key in post.title_keys}
    own = [post.url] if post.url else []
    for url in own + ([post.moved_to] if post.moved_to else []) + [target for target, stored in post.links if stored or not is_home(target)]:
        out.add("u:" + url)
        if page_key(url):
            out.add(page_key(url))
    return out


def roles(posts: Sequence[StoryPost]) -> Dict[str, str]:
    """report or share (a copy of an earlier post's text or title from another place, a link post, or a repost);
    `posts` in time order."""
    first_text: Dict[str, str] = {}
    first_title: Dict[str, str] = {}
    out = {}
    for p in posts:
        text, titles_ = p.text_key, p.title_keys
        copy = (text and text in first_text and first_text[text] != p.place) or \
               any(title in first_title and first_title[title] != p.place for title in titles_)
        out[p.id] = "share" if copy or p.link_post or p.reposted else "report"
        if text:
            first_text.setdefault(text, p.place)
        for title in titles_:
            first_title.setdefault(title, p.place)
    return out


def text_key(content_hash: Optional[str], chars: int) -> Optional[str]:
    return content_hash if content_hash and chars >= SAME_TEXT_MIN_CHARS else None


def text_chars_sql(text: str) -> str:
    """SQL: a text column's length in characters, up to SAME_TEXT_MIN_CHARS. octet_length >= 4n implies n characters
    without decompressing the text, which length() does."""
    n = SAME_TEXT_MIN_CHARS
    return f"(CASE WHEN octet_length({text}) >= {4 * n} THEN {n} WHEN length({text}) > {n} THEN {n} ELSE length({text}) END)"


def named_voices(posts: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A story's voices as named, one item each (voice.count's): {id, name, place, with}, named by the first post's
    source (a Reddit author as u/<author>, `place` its subreddit), `with` its other sources; followed sources' voices
    first, then Reddit posters'. `posts` in naming order: {source_id, name, kind, voice, text_key, others}."""
    items = []
    for i, p in enumerate(posts):
        if p["kind"] == "saved":
            continue
        items.append(((i, -1), p["text_key"], p.get("owner") or p["voice"]))
        items += [((i, j), None, s.get("owner") or voice.source_key(s["id"])) for j, s in enumerate(p["others"])]
    followed, reddit = [], []
    for group in voice.groups(items):
        sources = [{"id": posts[i]["source_id"], "name": posts[i]["name"]} if j < 0 else
                   {k: v for k, v in posts[i]["others"][j].items() if k != "owner"} for i, j in group]
        # one owner's channels are one voice, named by a followed channel before a Reddit post
        k = next((k for k, (i, j) in enumerate(group) if not (j < 0 and posts[i]["kind"] == "reddit")), 0)
        group, sources = [group[k], *group[:k], *group[k + 1:]], [sources[k], *sources[:k], *sources[k + 1:]]
        (i, j), first = group[0], dict(sources[0])
        if j < 0 and voice.is_poster(posts[i]["voice"]):
            first.update(name="u/" + voice.poster(posts[i]["voice"]), place=posts[i]["name"])
        seen = {first["id"]}
        first["with"] = [s for s in sources if not (s["id"] in seen or seen.add(s["id"]))]
        (reddit if j < 0 and posts[i]["kind"] == "reddit" else followed).append(first)
    return followed + reddit


def source_site(hosts: Iterable[Tuple[str, int]], of: Callable[[str], str] = site_of) -> str:
    """The most common site of a source's posts' hosts; with `of=publication_of`, its publication."""
    sites: Counter = Counter()
    for host, n in hosts:
        sites[of(host)] += n
    return sites.most_common(1)[0][0] if sites else ""


__all__ = ["StoryPost", "Story", "Edge", "Grouping", "apart", "group", "grouping", "story_times", "background", "story_start", "keys", "page_key", "threads", "date_alone",
           "address_origins", "page_aliases", "paper_aliases", "link_via", "one_page", "roles", "named_voices", "text_key", "source_site", "title_key",
           "anchors"]
