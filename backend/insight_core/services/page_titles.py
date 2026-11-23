"""One title for a page you don't follow, the same for Discover and Classics; nothing here fetches.

1. the stored post's title; 2. else the evidence of the posts linking it or another path of it
(tree_rules.origin_title without the slug; a tweet only by its own quoted words); 3. else the page's own title as
read once (services/discover_reads.py), unless 2+ pages of its host share it (the site's name); 4. else none.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from typing import Any, Dict, Mapping, Optional, Sequence, Set, Tuple

from insight_core.db.repo_discover import DiscoverRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.utils.addresses import host_of, is_tweet, publication_of
from insight_core.utils.story_rules import StoryPost, one_page
from insight_core.utils.tree_rules import origin_title

LOAD_BATCH = 2000   # linking posts read at a time (`evidence`)


def evidence(cur: Any, sources: SourceFacts, urls: Sequence[str], *,
             aliases: Optional[Mapping[str, str]] = None) -> Dict[str, Optional[str]]:
    """Each address's title by the stored data (1 and 2). `aliases`: another path of a page -> the address
    that names it (story_rules.page_aliases' papers): its linkers' words count for that address."""
    from insight_core.services.stories_service import StoriesService   # it imports this module's users

    aliases = dict(aliases or {})
    urls = list(dict.fromkeys(urls))
    wanted = set(urls)
    every = sorted(wanted | {alias for alias, named in aliases.items() if named in wanted})
    if not every:
        return {}
    # linking posts read LOAD_BATCH at a time and kept only as these pages' evidence: bounds the job's peak (0231)
    linking: Dict[str, Dict[str, StoryPost]] = defaultdict(dict)
    ids = StoriesRepository.linking_posts(cur, every)
    for start in range(0, len(ids), LOAD_BATCH):
        for row in StoriesRepository.load_posts(cur, sources, ids[start:start + LOAD_BATCH]):
            post = _as_evidence(one_page(StoriesService._story_post(row, sources), aliases), wanted)
            for target, _ in post.links:
                if target in wanted:
                    linking[target][post.id] = post
    stored = DiscoverRepository.stored_titles(cur, urls)

    def title(url: str) -> Optional[str]:
        # in time order: a tie between link words goes to the first, and rows come in any order
        posts = sorted(linking[url].values(), key=lambda p: (p.t, p.id))
        if is_tweet(url):
            posts = [p for p in posts if p.quoted_words.get(url)]
        return stored.get(url) or origin_title(url, posts, slug=False)

    return {url: title(url) for url in urls}


def _as_evidence(post: StoryPost, wanted: Set[str]) -> StoryPost:
    """A linking post reduced to what origin_title reads for the `wanted` pages: their links, link words and quoted
    words, and only the first of its other links (so "this link alone" still means the same)."""
    links, other = [], None
    for target, stored_post in post.links:
        if target in wanted:
            links.append((target, stored_post))
        elif other is None:
            other = (target, stored_post)
    if other is None and len(links) == len(post.links):
        return post
    return replace(post, links=links + ([other] if other else []),
                   link_texts={t: w for t, w in post.link_texts.items() if t in wanted},
                   quoted_words={t: w for t, w in post.quoted_words.items() if t in wanted})


def shared_titles(reads: Mapping[str, Any]) -> Set[Tuple[str, str]]:
    """The read titles 2+ pages of one host (www. aside) share: (host, title), pages told apart by their last
    segment (_last_segment)."""
    pages: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for url, read_ in (reads or {}).items():
        title = (read_ or {}).get("title")
        if title:
            pages[(publication_of(host_of(url)), title.casefold())].add(_last_segment(url))
    return {key for key, slugs in pages.items() if len(slugs) >= 2}


_TRACKING = re.compile(r"^(?:_|utm_|mc_|fbclid$|gclid$)", re.I)


def _last_segment(url: str) -> str:
    """A page as told apart from another of its host: its last path segment and its query without tracking keys
    (/blog/x and /news/blog/x are one page; /blog?id=a and /blog?id=b are two)."""
    rest = url.split("://", 1)[-1].partition("/")[2].split("#", 1)[0]
    path, _, query = rest.partition("?")
    kept = sorted(q for q in query.split("&") if q and not _TRACKING.match(q))
    return path.rstrip("/").rsplit("/", 1)[-1].lower() + ("?" + "&".join(kept) if kept else "")


def read(reads: Mapping[str, Any], url: str, shared: Optional[Set[Tuple[str, str]]] = None) -> Optional[str]:
    """The page's own title as read (3), from `discover_reads`' titles; None when unread, it had none, or 2+
    pages of its host share it (`shared`: shared_titles of the same reads, computed once by the caller)."""
    title = ((reads or {}).get(url) or {}).get("title") or None
    if title and (publication_of(host_of(url)), title.casefold()) in (shared if shared is not None else shared_titles(reads)):
        return None
    return title


__all__ = ["evidence", "read", "shared_titles"]
