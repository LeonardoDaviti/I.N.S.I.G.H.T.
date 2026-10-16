"""Full text for a post whose feed carried only a summary: read once from the article page.

Two callers. GenericRssKind expands a new post as it is fetched, and
scripts/repair_full_text re-reads the teasers stored before that. A body taken from the
page is marked metadata.full_content_fetched, and a later feed fetch never puts the
summary back over it (repo_posts._post_update_assignments).

On for every generic RSS source; `settings.fetch_full_content: false` turns it off for one.
"""
from __future__ import annotations

import urllib.parse
from typing import Any, Dict, Mapping, Optional, Tuple

from insight_core.db.repo_posts import FULL_TEXT_FLAG
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.utils.content_fingerprints import normalize_text

# A body shorter than this is probably a teaser.
SHORT_BODY_CHARS = 1400
# The page is the same article when the body's first OPENING_CHARS appear in the first
# quarter of the page text. A body under SAME_ARTICLE_MIN_CHARS is not checked.
OPENING_CHARS = 80
SAME_ARTICLE_MIN_CHARS = 200
# Seconds between two article pages of one site.
PAGE_DELAY_S = 2.0
# Links whose page is not an article: a repository, a paper's abstract page, a thread,
# a video, a chat message, a tweet.
NOT_ARTICLE_HOSTS = frozenset({
    "github.com", "arxiv.org", "reddit.com", "youtube.com", "youtu.be", "t.me", "x.com", "twitter.com",
})


def full_page_enabled(source: Mapping[str, Any]) -> bool:
    return (source.get("settings") or {}).get("fetch_full_content") is not False


def page_is_article(url: Any) -> bool:
    if not isinstance(url, str) or not url.startswith("http"):
        return False
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return not any(host == blocked or host.endswith(f".{blocked}") for blocked in NOT_ARTICLE_HOSTS)


def body_text(post: Mapping[str, Any]) -> str:
    return parsing.strip_html(post.get("content_html") or post.get("content") or "")


def is_teaser(post: Mapping[str, Any]) -> bool:
    return len(body_text(post)) < SHORT_BODY_CHARS


def _same_article(current_text: str, page_text: str) -> bool:
    current, page = normalize_text(current_text), normalize_text(page_text)
    if len(current) < SAME_ARTICLE_MIN_CHARS:
        return True
    return current[:OPENING_CHARS] in page[:len(page) // 4]


async def read_article(http: KindHttp, url: str, current_text: str) -> Optional[Tuple[str, str]]:
    """(html, text) of the article at url, or None when the page holds nothing longer, or is
    not clearly the same article (the feed body is the better version then).

    Raises what the request raises (ValueError for an HTTP or network error).
    """
    page, _ = await http.get_text(url)
    html = parsing.extract_article_html(page)
    text = parsing.strip_html(html)
    if len(text) <= max(len(current_text) + 250, 700) or not _same_article(current_text, text):
        return None
    return html, text


def with_full_text(post: Dict[str, Any], html: str, text: str) -> Dict[str, Any]:
    return {
        **post,
        "content_html": html,
        "content": text,
        "metadata": {**(post.get("metadata") or {}), FULL_TEXT_FLAG: True},
    }
