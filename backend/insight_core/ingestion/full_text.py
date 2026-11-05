"""Full text for a post whose feed carried only a summary: read once from the article page.

Two callers. GenericRssKind expands a new post as it is fetched, and
scripts/repair_full_text re-reads the teasers stored before that. A body taken from the
page is marked metadata.full_content_fetched, and a later feed fetch never puts the
summary back over it (repo_posts._post_update_assignments). A post its feed gave no date takes
the date its page states (page_watch.page_date, issue 0070), so it sorts at it.

On for every generic RSS source; `settings.fetch_full_content: false` turns it off for one.

A teaser whose page read failed (an HTTP error or a timeout, issue 0062) is read again on its
source's later fetches, inside the same host slot and PAGE_DELAY_S apart: at most MAX_PAGE_TRIES
reads in all, RETRY_APART between two. Each read is counted in metadata.page_tries
({count, last_at, failed}); a read that worked, or found nothing longer on the page, ends it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from insight_core.db.repo_posts import FULL_TEXT_FLAG, MOVED_KEY, PAGE_READ_KEY, PAGE_TRIES_KEY
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.utils.addresses import host_of
from insight_core.utils.content_fingerprints import normalize_text
from insight_core.utils.url_normalization import normalize_url

# A body shorter than this is probably a teaser. Not measured.
SHORT_BODY_CHARS = 1400
# The page is the same article when the body's first OPENING_CHARS appear in the first
# quarter of the page text. A body under SAME_ARTICLE_MIN_CHARS is not checked. Neither measured.
OPENING_CHARS = 80
SAME_ARTICLE_MIN_CHARS = 200
# A page whose own text is shorter than this and that names another address is a redirect stub
# (issue 0108: the measured stubs read "Redirecting... Click here if you are not redirected.", 50
# characters). No article the reader keeps is this short (read_article keeps only 700 and more).
STUB_PAGE_CHARS = 700
# Seconds between two article pages of one site.
PAGE_DELAY_S = 2.0
# A teaser whose page read failed: read at most MAX_PAGE_TRIES times in all, RETRY_APART apart,
# up to RETRY_SLICE of a source's at one fetch (issue 0062). Not measured.
MAX_PAGE_TRIES = 3
RETRY_APART = timedelta(days=1)
RETRY_SLICE = 20
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
    host = host_of(url)
    return not any(host == blocked or host.endswith(f".{blocked}") for blocked in NOT_ARTICLE_HOSTS)


def body_text(post: Mapping[str, Any]) -> str:
    return parsing.strip_html(post.get("content_html") or post.get("content") or "")


def is_teaser(post: Mapping[str, Any]) -> bool:
    return len(body_text(post)) < SHORT_BODY_CHARS


def empty_read_failed(post: Mapping[str, Any]) -> bool:
    """Whether a page read that found nothing longer is a failed try (issue 0108, decision 2): on a
    post with no body it is (its page may be read again later, 0062); a post with a body keeps it."""
    return not body_text(post).strip()


def _same_article(current_text: str, page_text: str) -> bool:
    current, page = normalize_text(current_text), normalize_text(page_text)
    if len(current) < SAME_ARTICLE_MIN_CHARS:
        return True
    return current[:OPENING_CHARS] in page[:len(page) // 4]


async def read_article(http: KindHttp, url: str, current_text: str
                       ) -> Optional[Tuple[str, str, Dict[str, Any], Optional[datetime], Optional[str]]]:
    """(html, text, how well the page was read, the date the page states, where the page moved) of
    the article at url, or None when the page holds nothing longer, or is not clearly the same
    article (the feed body is the better version then). A date after now (a clock off) is no date.

    A page whose own text is under STUB_PAGE_CHARS and that names another address (a meta refresh,
    else a canonical link: parsing.moved_to) is a redirect stub (issue 0108): the article is read at
    that address, one hop, and that address is where it moved (else None). A script alone is not
    followed.

    Raises what the requests raise (ValueError for an HTTP or network error).
    """
    from insight_core.ingestion.kinds.page_watch import page_date   # page_watch imports generic_rss, this module's caller

    page, _ = await http.get_text(url)
    html, fidelity = parsing.read_article_page(page, base_url=url)
    text = parsing.strip_html(html)
    moved = parsing.moved_to(page, url) if len(text) < STUB_PAGE_CHARS else None
    if moved:
        page, _ = await http.get_text(moved)
        html, fidelity = parsing.read_article_page(page, base_url=moved)
        text = parsing.strip_html(html)
    if len(text) <= max(len(current_text) + 250, 700) or not _same_article(current_text, text):
        return None
    date = page_date(page)
    return html, text, fidelity, date if date and date <= datetime.now(timezone.utc) else None, moved


def with_full_text(post: Dict[str, Any], html: str, text: str,
                   fidelity: Optional[Dict[str, Any]] = None, date: Optional[datetime] = None,
                   moved: Optional[str] = None) -> Dict[str, Any]:
    """The post with its page's body, and the page's date when the feed gave it none (issue 0070).
    A page that moved (issue 0108): the post keeps its address; its canonical is where it moved, and
    metadata.moved_to that address normalized (what the story job makes one page with it)."""
    return {
        **post,
        "content_html": html,
        "content": text,
        "date": post.get("date") or date,
        **({"canonical_url": moved} if moved else {}),
        "metadata": {**(post.get("metadata") or {}), FULL_TEXT_FLAG: True,
                     **({PAGE_READ_KEY: fidelity} if fidelity else {}),
                     **({MOVED_KEY: normalize_url(moved)} if moved else {})},
    }


def tries(post: Mapping[str, Any]) -> int:
    """How many times the post's page was read (issue 0062), 0 when never counted."""
    return int(((post.get("metadata") or {}).get(PAGE_TRIES_KEY) or {}).get("count") or 0)


def with_page_try(post: Dict[str, Any], at: datetime, *, failed: bool) -> Dict[str, Any]:
    """The post with one more read of its page counted: when, and whether it failed."""
    counted = {"count": tries(post) + 1, "last_at": at.isoformat(), "failed": failed}
    return {**post, "metadata": {**(post.get("metadata") or {}), PAGE_TRIES_KEY: counted}}


def pages_losing_images(posts: Iterable[Mapping[str, Any]]) -> Tuple[int, int]:
    """(posts read from their page, those of them that lost most of their images)."""
    reads = [fidelity for post in posts if (fidelity := (post.get("metadata") or {}).get(PAGE_READ_KEY))]
    return len(reads), sum(1 for fidelity in reads if parsing.lost_most_images(fidelity))
