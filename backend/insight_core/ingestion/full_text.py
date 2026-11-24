"""Full text for a post whose feed carried only a summary: read once from the article page.

Callers: GenericRssKind (a new post as it is fetched) and scripts/repair_full_text (stored teasers). A body from the
page is marked metadata.full_content_fetched and a later feed fetch never puts the summary back over it; an undated
post takes its page's date. On for every generic RSS source unless `settings.fetch_full_content: false`. A failed
read is retried on later fetches (MAX_PAGE_TRIES, RETRY_APART; metadata.page_tries). Every read records
metadata.page_read_outcome and metadata.full_text_rule (the repair re-reads once per rule version). A teaser is a
short body or one cut with a "read more" link (cut_marker); the page must be the same article (same_article); a page
with no longer article is tried by its embedded data (kinds/embedded_article.py), else NEEDS_SCRIPT.
"""
from __future__ import annotations

import html as html_lib
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from insight_core.db.repo_posts import (FULL_TEXT_FLAG, FULL_TEXT_RULE_KEY, MOVED_KEY, PAGE_OUTCOME_KEY, PAGE_READ_KEY,
                                        PAGE_TRIES_KEY)
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import embedded_article, parsing, paywall
from insight_core.utils.addresses import host_of, same_site
from insight_core.utils.content_fingerprints import normalize_text
from insight_core.utils.titles import title_key
from insight_core.utils.url_normalization import normalize_url

# A body shorter than this is probably a teaser. Not measured.
SHORT_BODY_CHARS = 1400
# Same article: the body's first OPENING_CHARS in the page text's first quarter; a body under
# SAME_ARTICLE_MIN_CHARS is not checked. Neither measured.
OPENING_CHARS = 80
SAME_ARTICLE_MIN_CHARS = 200
# The version of these rules (metadata.full_text_rule). Raise it when they change: the repair reads the posts left
# short again, once.
FULL_TEXT_RULE = 3
# A page read's outcome (metadata.page_read_outcome.outcome); else error:<class> or http:<status>.
FULL, NOTHING_LONGER, NOT_SAME_ARTICLE, NEEDS_SCRIPT = "full", "nothing_longer", "not_same_article", "needs_script"
# An X Article of which only the title and opening could be read (kinds/x_articles.py).
PREVIEW_ONLY = "preview_only"
# A page for paying readers (kinds/paywall.py): the post is marked metadata.paywalled, and the page's free part is
# taken only when longer than the feed's.
PAYWALLED = "paywalled"
PAYWALLED_KEY = "paywalled"
# The outcomes a later rule may change: the repair reads them again once per rule version.
READ_AGAIN_OUTCOMES = (NOTHING_LONGER, NOT_SAME_ARTICLE, NEEDS_SCRIPT)
# Same article: a title this short is no evidence ("Update"); SHINGLE_SHARE of the teaser's SHINGLE_WORDS-word
# runs on the page (at least SHINGLE_MIN runs). Measured on the 0140 fixtures only.
TITLE_MIN_CHARS = 12
SHINGLE_WORDS = 5
SHINGLE_SHARE = 0.6
SHINGLE_MIN = 3
# A "read more" link: at most CUT_WORDS of its own words (title aside) and CUT_TAIL_CHARS of body after it; a cut
# fragment (#more-123) or a more-link class is one too.
CUT_WORDS = 4
CUT_TAIL_CHARS = 40
CUT_FRAGMENT_RE = re.compile(r"(?i)^(?:\w*cut\w*|more(?:[-_]\d+)?|read[-_]?more|continue(?:[-_]reading)?|more[-_]link)$")
# A last link to the post's own page that is no cut: its comments, permalink, a footnote's return (measured).
NOT_CUT_WORDS_RE = re.compile(r"(?i)comment|коммент|discuss|обсу|repl(?:y|ies)|permalink|^\W*(?:link|return|source|#)\W*$|^\W*$")
CUT_CLASS_RE = re.compile(r"""(?i)\bclass\s*=\s*["'][^"']*\b(?:more-link|read-more|readmore|continue-reading)\b""")
# A page whose own text is shorter than this and that names another address is a redirect stub (measured: 0108);
# no article the reader keeps is this short.
STUB_PAGE_CHARS = 700
# Seconds between two article pages of one site.
PAGE_DELAY_S = 2.0
# A failed page read: at most MAX_PAGE_TRIES in all, RETRY_APART apart, RETRY_SLICE of a source's per fetch.
# Not measured.
MAX_PAGE_TRIES = 3
RETRY_APART = timedelta(days=1)
RETRY_SLICE = 20
# Links whose page is not an article: a repository, a paper's abstract page, a thread,
# a video, a chat message, a tweet.
NOT_ARTICLE_HOSTS = frozenset({
    "github.com", "arxiv.org", "reddit.com", "youtube.com", "youtu.be", "t.me", "x.com", "twitter.com",
})
# An episode's audio or video file (a podcast item's enclosure): never read as a page.
MEDIA_FILE_RE = re.compile(r"(?i)\.(?:mp3|m4a|m4b|aac|ogg|oga|opus|wav|flac|mp4|m4v|mov|webm|mkv)$")
SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|noscript)\b.*?</\1>")


def full_page_enabled(source: Mapping[str, Any]) -> bool:
    return (source.get("settings") or {}).get("fetch_full_content") is not False


def page_is_article(url: Any) -> bool:
    """Whether the address may be an article page to read. Never an episode's audio or video file, nor an item
    with no address of its own (parsing.ITEM_PARAM)."""
    if not isinstance(url, str) or not url.startswith("http"):
        return False
    if f"{parsing.ITEM_PARAM}=" in url or MEDIA_FILE_RE.search(url.split("?", 1)[0].split("#", 1)[0]):
        return False
    host = host_of(url)
    return not any(host == blocked or host.endswith(f".{blocked}") for blocked in NOT_ARTICLE_HOSTS)


def body_text(post: Mapping[str, Any]) -> str:
    return parsing.strip_html(post.get("content_html") or post.get("content") or "")


def is_teaser(post: Mapping[str, Any]) -> bool:
    """A short body, or one its feed cut with a "read more" link (cut_marker), whatever its length."""
    return len(body_text(post)) < SHORT_BODY_CHARS or cut_marker(post)


def cut_marker(post: Mapping[str, Any]) -> bool:
    """Whether the feed cut the post's body: a link to the post's own address that names a cut, or is the body's
    last link with a few words of its own (title aside) and next to nothing after it. A link whose words are only
    the title ("The post <title> appeared first on ...") is no cut."""
    html, url = post.get("content_html") or "", post.get("url")
    if not html or not isinstance(url, str) or not url.startswith("http"):
        return False
    own = normalize_url(url)
    links = list(parsing.LINK_RE.finditer(html))
    title = " ".join(parsing.strip_html(post.get("title") or "").split()).casefold()
    for index, link in enumerate(links):
        href = parsing.HREF_RE.search(link.group("attrs") or "")
        target = next((value for value in href.groups() if value), "") if href else ""
        if not target:
            continue
        try:
            absolute = urllib.parse.urljoin(url, html_lib.unescape(target.strip()))
        except ValueError:
            continue
        if normalize_url(absolute) != own:
            continue
        fragment = urllib.parse.urlparse(absolute).fragment
        if (fragment and CUT_FRAGMENT_RE.match(fragment)) or CUT_CLASS_RE.search(link.group("attrs") or ""):
            return True
        if fragment:   # a footnote's return (#fnref1), a heading's anchor, its comments (#comments): no cut
            continue
        words = " ".join(parsing.strip_html(link.group("text")).split()).casefold()
        own_words = (words.replace(title, " ") if title else words).split()
        after = parsing.strip_html(html[link.end():])
        if (index == len(links) - 1 and 0 < len(own_words) <= CUT_WORDS and len(after) <= CUT_TAIL_CHARS
                and not NOT_CUT_WORDS_RE.search(" ".join(own_words))):
            return True
    return False


def empty_read_failed(post: Mapping[str, Any]) -> bool:
    """Whether a page read that found nothing longer is a failed try: yes for a post with no body (read again
    later); a post with a body keeps it."""
    return not body_text(post).strip()


def _same_article(current_text: str, page_text: str) -> bool:
    """Today's opening rule: a body under SAME_ARTICLE_MIN_CHARS, or its first OPENING_CHARS in the first
    quarter of the page text."""
    current, page = normalize_text(current_text), normalize_text(page_text)
    if len(current) < SAME_ARTICLE_MIN_CHARS:
        return True
    return current[:OPENING_CHARS] in page[:len(page) // 4]


WORD_RE = re.compile(r"\w+")


def _shingles(text: str) -> set:
    words = WORD_RE.findall(normalize_text(text))
    return {tuple(words[i:i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)}


def shingle_share(current_text: str, page_text: str) -> Optional[float]:
    """The share of the teaser's runs of SHINGLE_WORDS words found anywhere in the page text; None for a
    teaser with fewer than SHINGLE_MIN runs."""
    teaser = _shingles(current_text)
    if len(teaser) < SHINGLE_MIN:
        return None
    return len(teaser & _shingles(page_text)) / len(teaser)


def on_own_site(url: Any, site: Optional[str]) -> bool:
    """Whether a post's address is on its source's own site (site: the source's address); a link post's is not."""
    return bool(site) and isinstance(url, str) and same_site(host_of(url), host_of(site))


def _titled(title: Optional[str], page_titles: Iterable[str]) -> bool:
    return len(title_key(parsing.strip_html(title or ""))) >= TITLE_MIN_CHARS and parsing.same_title(title, list(page_titles))


def same_article(current_text: str, text: str, page: str, *, url: str, title: Optional[str] = None,
                 site: Optional[str] = None) -> bool:
    """Whether the page read (article `text`, whole `page`) is the post's article: by the opening rule; or, for a
    post on its own site, by its title, the page naming the post's address, or SHINGLE_SHARE of word runs. A link
    post keeps the opening rule alone (a linked page's title and address are the linked article's)."""
    if _same_article(current_text, text):
        return True
    if not on_own_site(url, site):
        return False
    if _titled(title, parsing.page_title_keys(page)) or normalize_url(url) in parsing.page_addresses(page, url):
        return True
    share = shingle_share(current_text, parsing.strip_html(SCRIPT_STYLE_RE.sub(" ", page)))
    return share is not None and share >= SHINGLE_SHARE


@dataclass(frozen=True)
class PageRead:
    """A page read's outcome (FULL, NOTHING_LONGER, NOT_SAME_ARTICLE, NEEDS_SCRIPT) and, when FULL, the
    article: (html, text, how well the page was read, the date the page states, where the page moved), and that
    date's precision when the date can't tell it (page_watch.stated_precision: "month" for a month alone)."""
    outcome: str
    article: Optional[Tuple[str, str, Dict[str, Any], Optional[datetime], Optional[str]]] = None
    precision: Optional[str] = None


def error_outcome(exc: BaseException) -> str:
    """http:<status> for an HTTP answer, else error:<the exception's class> (a timeout, a dropped connection,
    a page the reader could not parse)."""
    if isinstance(exc, HttpError) and exc.status:
        return f"http:{exc.status}"
    return f"error:{type(exc).__name__}"


def with_outcome(post: Dict[str, Any], outcome: str, at: datetime) -> Dict[str, Any]:
    """The post with its page read's outcome and the rules' version; a page for paying readers marks it paywalled."""
    return {**post, "metadata": {**(post.get("metadata") or {}),
                                 PAGE_OUTCOME_KEY: {"outcome": outcome, "at": at.isoformat()},
                                 FULL_TEXT_RULE_KEY: FULL_TEXT_RULE,
                                 **({PAYWALLED_KEY: True} if outcome == PAYWALLED else {})}}


def outcome_of(metadata: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The outcome of a post's last page read, None when none was recorded."""
    found = (metadata or {}).get(PAGE_OUTCOME_KEY)
    return found.get("outcome") if isinstance(found, dict) else None


def _embedded(page: str, current_text: str, needed: int, *, url: str, title: Optional[str], site: Optional[str],
              page_is_post: bool) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """(html, text, fidelity) of the post's article from the page's embedded data, longer than `needed`: a
    candidate titled as the post (own site) or the same article by content; else the only long one when the page
    is the post's and its holder names no other title. None when none is."""
    candidates = [c for c in embedded_article.embedded_articles(page) if len(c.text) > needed]
    own = on_own_site(url, site)
    for candidate in candidates:
        titled = own and _titled(title, [title_key(candidate.title or "")])
        share = shingle_share(current_text, candidate.text)
        opening = (len(normalize_text(current_text)) >= SAME_ARTICLE_MIN_CHARS
                   and _same_article(current_text, candidate.text))
        # The only long one, with no title of another post on its holder.
        alone = page_is_post and len(candidates) == 1 and (not candidate.title or _titled(title, [title_key(candidate.title)]))
        if titled or opening or (share is not None and share >= SHINGLE_SHARE) or alone:
            html, fidelity = parsing.read_article_page(
                f"<html><body><article>{embedded_article.as_html(candidate)}</article></body></html>", base_url=url)
            text = parsing.strip_html(html)
            if len(text) > needed:
                return html, text, {**fidelity, "embedded": True}
    return None


async def read_page(http: KindHttp, url: str, current_text: str, *, title: Optional[str] = None,
                    site: Optional[str] = None) -> PageRead:
    """The article at url and why it was taken or not: FULL with (html, text, fidelity, the page's date, where it
    moved), else NOTHING_LONGER, NOT_SAME_ARTICLE or NEEDS_SCRIPT, each after trying the embedded data. A date after
    now is no date. A redirect stub (under STUB_PAGE_CHARS, naming another address) is followed one hop. `title` and
    `site` feed the same-article test. Raises what the requests raise (ValueError for an HTTP or network error).
    """
    from insight_core.ingestion.kinds.page_watch import page_dating, stated_precision   # page_watch imports generic_rss

    page, _ = await http.get_text(url)
    html, fidelity = parsing.read_article_page(page, base_url=url)
    text = parsing.strip_html(html)
    moved = parsing.moved_to(page, url) if len(text) < STUB_PAGE_CHARS else None
    here = url
    if moved:
        page, _ = await http.get_text(moved)
        html, fidelity = parsing.read_article_page(page, base_url=moved)
        text, here = parsing.strip_html(html), moved
    needed = max(len(current_text) + 250, 700)
    outcome = NOTHING_LONGER
    if len(text) > needed:
        outcome = FULL if same_article(current_text, text, page, url=url, title=title, site=site) else NOT_SAME_ARTICLE
    if outcome != FULL:
        page_is_post = on_own_site(url, site) and (
            normalize_url(url) in parsing.page_addresses(page, here) or _titled(title, parsing.page_title_keys(page)))
        embedded = _embedded(page, current_text, needed, url=here, title=title, site=site, page_is_post=page_is_post)
        if embedded:
            (html, text, fidelity), outcome = embedded, FULL
        elif not html and embedded_article.script_rendered(page):
            outcome = NEEDS_SCRIPT
    paid = paywall.marker(page) is not None
    if outcome != FULL:
        return PageRead(PAYWALLED if paid else outcome)
    date, how = page_dating(page, url)
    date = date if date and date <= datetime.now(timezone.utc) else None
    return PageRead(PAYWALLED if paid else FULL, (html, text, fidelity, date, moved),
                    stated_precision(how) if date is not None else None)


async def read_article(http: KindHttp, url: str, current_text: str, *, title: Optional[str] = None,
                       site: Optional[str] = None
                       ) -> Optional[Tuple[str, str, Dict[str, Any], Optional[datetime], Optional[str]]]:
    """read_page's article, or None when it took none (the feed body is kept)."""
    return (await read_page(http, url, current_text, title=title, site=site)).article


def with_full_text(post: Dict[str, Any], html: str, text: str,
                   fidelity: Optional[Dict[str, Any]] = None, date: Optional[datetime] = None,
                   moved: Optional[str] = None, *, precision: Optional[str] = None) -> Dict[str, Any]:
    """The post with its page's body, and the page's date when the feed gave it none, with `precision` (PageRead's:
    "month" for a month alone; else the saver tells it by the date). A page that moved: the post keeps its address;
    its canonical and metadata.moved_to (normalized) are where it moved."""
    return {
        **post,
        "content_html": html,
        "content": text,
        "date": post.get("date") or date,
        # an undated item dated by its page is no longer "seen"
        **({"date_precision": precision} if not post.get("date") and date else {}),
        **({"canonical_url": moved} if moved else {}),
        "metadata": {**(post.get("metadata") or {}), FULL_TEXT_FLAG: True,
                     **({PAGE_READ_KEY: fidelity} if fidelity else {}),
                     **({MOVED_KEY: normalize_url(moved)} if moved else {})},
    }


def tries(post: Mapping[str, Any]) -> int:
    """How many times the post's page was read, 0 when never counted."""
    return int(((post.get("metadata") or {}).get(PAGE_TRIES_KEY) or {}).get("count") or 0)


def with_page_try(post: Dict[str, Any], at: datetime, *, failed: bool) -> Dict[str, Any]:
    """The post with one more read of its page counted: when, and whether it failed."""
    counted = {"count": tries(post) + 1, "last_at": at.isoformat(), "failed": failed}
    return {**post, "metadata": {**(post.get("metadata") or {}), PAGE_TRIES_KEY: counted}}


def pages_losing_images(posts: Iterable[Mapping[str, Any]]) -> Tuple[int, int]:
    """(posts read from their page, those of them that lost most of their images)."""
    reads = [fidelity for post in posts if (fidelity := (post.get("metadata") or {}).get(PAGE_READ_KEY))]
    return len(reads), sum(1 for fidelity in reads if parsing.lost_most_images(fidelity))


# --------------------------------------------------------------------------- the reader's line

# Why a post is the summary only, as the post page says it after "Summary only ·".
TEASER_REASONS = {
    NOT_SAME_ARTICLE: "its page did not read as the same article",
    NEEDS_SCRIPT: "its page needs a script to show the article",
    NOTHING_LONGER: "its page held nothing longer",
    PAYWALLED: "for paid subscribers",
    PREVIEW_ONLY: "X gave only the article's opening",
}


def teaser_reason(metadata: Optional[Mapping[str, Any]], *, url: Any = None, title: Optional[str] = None,
                  content_html: Optional[str] = None) -> Optional[str]:
    """Why a post shows its feed's summary only, or None for a post read in full or never known short: its last
    page read took nothing, or found nothing longer though its feed cut the body. Otherwise nothing longer is whole."""
    meta = metadata or {}
    outcome = outcome_of(meta)
    if meta.get(PAYWALLED_KEY) is True:
        return TEASER_REASONS[PAYWALLED]   # a paid post's page (its kind's, or its page read's markers)
    if meta.get(FULL_TEXT_FLAG) or not outcome or outcome == FULL:
        return None
    if outcome == NOTHING_LONGER:
        cut = cut_marker({"url": url, "title": title, "content_html": content_html})
        return TEASER_REASONS[NOTHING_LONGER] if cut else None
    if outcome in TEASER_REASONS:
        return TEASER_REASONS[outcome]
    if outcome.startswith("http:"):
        return f"its page answered HTTP {outcome.split(':', 1)[1]}"
    return "its page could not be read"
