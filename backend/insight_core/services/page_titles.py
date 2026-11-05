"""One title for a page you don't follow (issue 0106; 0080's decision 2, made one function): Discover's
article, origin and archive lines and Classics are titled the same way.

1. the stored post's title, as every place shows it (post_title);
2. else the evidence of every post linking it, or another path of it (a paper's PDF, issue 0106):
   tree_rules.origin_title without the slug (the page's own words as a post quotes them, link words 2+
   voices agree on, a link post's title, ...); a tweet only by its own words, as a post quotes them;
3. else the page's own title, read once (services/discover_reads.py, stored with its date in
   system_settings `discover_reads`): it fills only a page the stored data leaves untitled;
4. else none: Discover shows "site · section", Classics the address.
Nothing here fetches.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Mapping, Optional, Sequence

from insight_core.db.repo_discover import DiscoverRepository
from insight_core.db.repo_stories import SourceFacts, StoriesRepository
from insight_core.utils.addresses import is_tweet
from insight_core.utils.story_rules import StoryPost, one_page
from insight_core.utils.tree_rules import origin_title


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
    linking: Dict[str, Dict[str, StoryPost]] = defaultdict(dict)
    rows = StoriesRepository.load_posts(cur, sources, linking=every)
    # In time order, as a story's are (issue 0071: link words written two ways as often are a tie the
    # first one wins, and the database returns rows in any order).
    for row in sorted(rows, key=lambda row: (row["t"], row["id"])):
        post = one_page(StoriesService._story_post(row, sources), aliases)
        for target, _ in post.links:
            linking[target][post.id] = post
    stored = DiscoverRepository.stored_titles(cur, urls)

    def title(url: str) -> Optional[str]:
        posts = list(linking[url].values())
        if is_tweet(url):
            posts = [p for p in posts if p.quoted_words.get(url)]
        return stored.get(url) or origin_title(url, posts, slug=False)

    return {url: title(url) for url in urls}


def read(reads: Mapping[str, Any], url: str) -> Optional[str]:
    """The page's own title as read (3), from `discover_reads`' titles; None when unread or it had none."""
    return ((reads or {}).get(url) or {}).get("title") or None


__all__ = ["evidence", "read"]
