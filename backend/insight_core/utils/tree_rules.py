"""A story's tree (issue 0064), and an outside origin's title (issue 0068): pure functions over the
posts of one story (story_rules groups them, then draws each one's tree here).

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
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Set, Tuple
from urllib.parse import unquote

from insight_core.utils.post_fields import display_title
from insight_core.utils.post_links import bare, titled_link_text

if TYPE_CHECKING:   # story_rules imports this module: it draws each story's tree
    from insight_core.utils.story_rules import StoryPost

# Why a post hangs from its parent (issue 0064; repost, thread, quote: 0066), most certain first.
# Mark X adds meaning, attribution.
PARENT_REASONS = ("address", "repost", "thread", "quote", "citation", "copy", "time", "none")
TIME_APART = timedelta(minutes=10)         # two trustworthy times closer than this make no order
PAGE_ORIGIN_MIN_POSTS = 2                  # an outside page 2+ of a story's posts link can be its origin

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
    from insight_core.utils.story_rules import _time_key   # story_rules imports this module

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
    if first is not None and first.kind == "saved":
        # A Saved page is no voice (issue 0070): when it is the origin it is shown as the page everyone
        # links, never as the first post; the Saved row is that page.
        under = {pid for pid, (node, _, _) in out.items() if node == first.id}
        for pid in under:
            out[pid] = (None, first.url, out[pid][2])
        out[first.id] = (None, first.url, "address")
        return Tree(out, first.url, first.title, len(under))
    if first is not None:
        return Tree(out)
    url = origin[len(_PAGE):]
    return Tree(out, url, origin_title(url, [by_id[pid] for pid in dict.fromkeys(page_posts[url])]),
                len(set(page_posts[url])))


def _origin_node(shape: Tree) -> Optional[str]:
    """A tree's origin as a node: its outside page ("U:" + address), else the post with no parent."""
    if shape.origin_url:
        return _PAGE + shape.origin_url
    return next((pid for pid, parent in shape.parents.items() if parent == (None, None, None)), None)


# An outside origin's title (issue 0068): an address's slug names its page with 3+ words of
# letters (claude-fable-5-mythos-5); words with digits (a version, an id) are kept but not counted.
# A leading id (5+ digits: help.openai.com's 20001626-api-credits-...) or date (2026-01-13-pocket-tts)
# is no word of it (issue 0070); a short number is ("16-charts-that-explain", "2025-ai-index-report").
SLUG_MIN_WORDS = 3
_SLUG = re.compile(r"[-_+]+")
_SLUG_ID = re.compile(r"^(?:\d{5,}|(?:19|20)\d\d[-_]\d\d(?:[-_]\d\d)?)(?:[-_+]|$)")
_TOKENS = re.compile(r"\w+", re.U)


def _slug_words(url: str) -> List[str]:
    """The words of an address's last path segment (its slug), its extension and a leading id aside."""
    _, _, rest = bare(url).partition("/")
    slug = unquote(re.split(r"[?#]", rest, maxsplit=1)[0].rstrip("/").rsplit("/", 1)[-1])
    return [w for w in _SLUG.split(_SLUG_ID.sub("", re.sub(r"\.[a-z]{2,5}$", "", slug, flags=re.I))) if w]


def origin_title(url: str, posts: Sequence[StoryPost]) -> Optional[str]:
    """An outside page's title (issue 0068), from evidence, nothing fetched: a story's outside origin,
    and Discover's articles (issue 0070). `posts`: those linking it. A page that is stored is no
    outside origin: it is the root, with its own title. Measured on the lab (30 roots checked by
    hand): link words that 2+ voices agree on are often a bare word ("Блогпост", "Веса", "Video"),
    and a slug loses a title's case and dots ("Introducing chatgpt images 2 5"), so each signal of
    other people's words needs another's support:
    1. the page's own words, as a post quotes them (post_links.quoted_words: a quoted tweet's text,
       a link preview's title), as the reader titles a post's text (display_title); those most
       posts quote (issue 0070);
    2. link words 2+ voices agree on (copies of one text are one voice) that read as a title
       (0051's rule, titled_link_text);
    3. else link words the address's slug confirms (the same words): the words, as written;
    4. else the title of a link post that is only this link: a Reddit or HN post with few words of
       its own (LINK_POST_MAX_WORDS, a share) and no other kept link is titled for it (issue 0070);
    5. else the slug made readable, when it holds SLUG_MIN_WORDS words of letters;
    6. else one voice's link words that read as a title;
    7. else None: the reader shows the address."""
    from insight_core.utils.story_rules import LINK_POST_MAX_WORDS, count_voices   # story_rules imports this module

    quoted = Counter(display_title(None, p.quoted_words[url]) for p in posts if p.quoted_words.get(url))
    shared = Counter(" ".join(p.title.split()) for p in posts if p.title and p.kind in ("reddit", "hn")
                     and (p.words or 0) < LINK_POST_MAX_WORDS and {target for target, _ in p.links} == {url})
    for found in (quoted, shared):
        found.pop("", None)
    if quoted:
        return min(quoted, key=lambda text: (-quoted[text], text))
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
    if shared:
        return min(shared, key=lambda text: (-shared[text], text))
    if sum(1 for w in words if re.fullmatch(r"[^\W\d_]+", w)) >= SLUG_MIN_WORDS:
        text = " ".join(words)
        return text[0].upper() + text[1:]
    titled = [key for key in by_use if titled_link_text(form[key])]
    return form[titled[0]] if titled else None


__all__ = ["Tree", "tree", "origin_title", "PARENT_REASONS"]
