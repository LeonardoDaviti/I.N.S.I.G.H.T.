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

Every read leaves a reason (issue 0140): metadata.page_read_outcome {outcome, at} (FULL,
NOTHING_LONGER, NOT_SAME_ARTICLE, NEEDS_SCRIPT, or `error:<class>` / `http:<status>`) and
metadata.full_text_rule, the version of these rules it was read by (the repair reads a post again once
per version). A teaser is a short body, or one its feed cut with a "read more" link to the post's own
address (cut_marker), whatever its length. The page is the same article by today's opening rule; or,
for a post on its source's own site, when its title is the page's, the page says it is the post's
address, or SHINGLE_SHARE of the teaser's word runs are on the page (same_article). A page whose reader
finds no article longer than the teaser is read from its embedded data (JSON-LD articleBody,
__NEXT_DATA__, a framework's state: kinds/embedded_article.py); a page a script builds that holds none
ends NEEDS_SCRIPT (a headless read is not done: 0081).
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
# The page is the same article when the body's first OPENING_CHARS appear in the first
# quarter of the page text. A body under SAME_ARTICLE_MIN_CHARS is not checked. Neither measured.
OPENING_CHARS = 80
SAME_ARTICLE_MIN_CHARS = 200
# The version of the rules a page read is made by (metadata.full_text_rule): 1 before issue 0140 (none
# stored), 2 its same-article test, cut marker and embedded data. Raise it when they change: the repair
# reads the posts left short again, once.
FULL_TEXT_RULE = 3   # 3 (issue 0167): a page that says it is for paying readers ends PAYWALLED
# A page read's outcome (metadata.page_read_outcome.outcome); else error:<class> or http:<status>.
FULL, NOTHING_LONGER, NOT_SAME_ARTICLE, NEEDS_SCRIPT = "full", "nothing_longer", "not_same_article", "needs_script"
# An X Article of which only the title and opening could be read (kinds/x_articles.py, v10.13.10).
PREVIEW_ONLY = "preview_only"
# A page that says it is for paying readers (issue 0167: kinds/paywall.py's markers): the post is marked
# metadata.paywalled, and its page's free part is taken only when longer than the feed's.
PAYWALLED = "paywalled"
PAYWALLED_KEY = "paywalled"
# The outcomes a later rule may change: the repair reads them again once per rule version.
READ_AGAIN_OUTCOMES = (NOTHING_LONGER, NOT_SAME_ARTICLE, NEEDS_SCRIPT)
# The same article (issue 0140): a title this short is no evidence ("Update", "Notes"); the teaser's runs
# of SHINGLE_WORDS words, SHINGLE_SHARE of them on the page (at least SHINGLE_MIN runs). Measured on the
# fixtures of plan/issues/0140-built.md only.
TITLE_MIN_CHARS = 12
SHINGLE_WORDS = 5
SHINGLE_SHARE = 0.6
SHINGLE_MIN = 3
# A "read more" link's own words (its post's title aside): at most CUT_WORDS, and at most CUT_TAIL_CHARS of
# the body after it. A fragment naming a cut (#cut, #more, #more-123, #habracut) or a more-link class is one.
CUT_WORDS = 4
CUT_TAIL_CHARS = 40
CUT_FRAGMENT_RE = re.compile(r"(?i)^(?:\w*cut\w*|more(?:[-_]\d+)?|read[-_]?more|continue(?:[-_]reading)?|more[-_]link)$")
# A last link to the post's own page that is no cut: its comments, its permalink, a footnote's return
# (measured on the 2026-11-05 export: "Comments", "[comments]", "[link]", "[return]" end whole feed bodies).
NOT_CUT_WORDS_RE = re.compile(r"(?i)comment|коммент|discuss|обсу|repl(?:y|ies)|permalink|^\W*(?:link|return|source|#)\W*$|^\W*$")
CUT_CLASS_RE = re.compile(r"""(?i)\bclass\s*=\s*["'][^"']*\b(?:more-link|read-more|readmore|continue-reading)\b""")
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
# An episode's audio or video file (a podcast item's enclosure, issue 0137 B1): never read as a page.
MEDIA_FILE_RE = re.compile(r"(?i)\.(?:mp3|m4a|m4b|aac|ogg|oga|opus|wav|flac|mp4|m4v|mov|webm|mkv)$")
SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style|noscript)\b.*?</\1>")


def full_page_enabled(source: Mapping[str, Any]) -> bool:
    return (source.get("settings") or {}).get("fetch_full_content") is not False


def page_is_article(url: Any) -> bool:
    """Whether the address may be an article page to read. Never an episode's audio or video file, nor
    an item with no address of its own (its feed's, parsing.ITEM_PARAM: issue 0137 B1)."""
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
    """Whether the feed cut the post's body (issue 0140): a link to the post's own address that names a cut
    (a fragment like #cut or #more-123, a more-link class), or that is the body's last link, with a few words
    of its own (its post's title aside: "Continue reading <title>") and next to nothing after it. A link
    whose words are only the title ("The post <title> appeared first on ...") is no cut."""
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
    """Whether a page read that found nothing longer is a failed try (issue 0108, decision 2): on a
    post with no body it is (its page may be read again later, 0062); a post with a body keeps it."""
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
    """Whether a post's address is on its source's own site (site: the source's address). A link post's
    address is another site's page (a link blog, an aggregator): its page is what it links, not the post."""
    return bool(site) and isinstance(url, str) and same_site(host_of(url), host_of(site))


def _titled(title: Optional[str], page_titles: Iterable[str]) -> bool:
    return len(title_key(parsing.strip_html(title or ""))) >= TITLE_MIN_CHARS and parsing.same_title(title, list(page_titles))


def same_article(current_text: str, text: str, page: str, *, url: str, title: Optional[str] = None,
                 site: Optional[str] = None) -> bool:
    """Whether the page read (its article `text`, the whole `page`) is the post's article (issue 0140): by
    today's opening rule; or, for a post on its source's own site (on_own_site), when the post's title is
    one of the page's titles, the page names the post's address as its own (canonical, og:url), or
    SHINGLE_SHARE of the teaser's word runs are anywhere in the page's text. A link post keeps today's rule
    alone: a linked page's title and address are the linked article's, never the post's."""
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
    article: (html, text, how well the page was read, the date the page states, where the page moved)."""
    outcome: str
    article: Optional[Tuple[str, str, Dict[str, Any], Optional[datetime], Optional[str]]] = None


def error_outcome(exc: BaseException) -> str:
    """http:<status> for an HTTP answer, else error:<the exception's class> (a timeout, a dropped connection,
    a page the reader could not parse)."""
    if isinstance(exc, HttpError) and exc.status:
        return f"http:{exc.status}"
    return f"error:{type(exc).__name__}"


def with_outcome(post: Dict[str, Any], outcome: str, at: datetime) -> Dict[str, Any]:
    """The post with its page read's outcome and the rules' version it was read by (issue 0140); a page for paying
    readers marks it paywalled (issue 0167)."""
    return {**post, "metadata": {**(post.get("metadata") or {}),
                                 PAGE_OUTCOME_KEY: {"outcome": outcome, "at": at.isoformat()},
                                 FULL_TEXT_RULE_KEY: FULL_TEXT_RULE,
                                 **({PAYWALLED_KEY: True} if outcome == PAYWALLED else {})}}


def outcome_of(metadata: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The outcome of a post's last page read (issue 0140), None when none was recorded."""
    found = (metadata or {}).get(PAGE_OUTCOME_KEY)
    return found.get("outcome") if isinstance(found, dict) else None


def _embedded(page: str, current_text: str, needed: int, *, url: str, title: Optional[str], site: Optional[str],
              page_is_post: bool) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """(html, text, fidelity) of the post's article read from the page's embedded data, longer than `needed`:
    a candidate whose holder's title is the post's (a post on its source's own site), or whose text is the
    same article by the content rules (opening, word runs); else the only long one, when the page itself is
    the post's (its title or address) and its holder names no other title. None when none is."""
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
    """The article at url and why it was taken or not (issue 0140): FULL with (html, text, how well the
    page was read, the date the page states, where the page moved); NOTHING_LONGER when the page holds
    nothing longer than the feed body; NOT_SAME_ARTICLE when what it holds is not clearly the same article
    (same_article: the feed body is the better version then); NEEDS_SCRIPT when the reader found no article
    on a page a script builds and its embedded data holds none. Each but FULL tries the page's embedded
    data first. A date after now (a clock off) is no date.

    A page whose own text is under STUB_PAGE_CHARS and that names another address (a meta refresh,
    else a canonical link: parsing.moved_to) is a redirect stub (issue 0108): the article is read at
    that address, one hop, and that address is where it moved (else None). A script alone is not
    followed. The post's title and its source's address (`site`) feed the same-article test.

    Raises what the requests raise (ValueError for an HTTP or network error).
    """
    from insight_core.ingestion.kinds.page_watch import page_date   # page_watch imports generic_rss, this module's caller

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
    date = page_date(page, url)
    return PageRead(PAYWALLED if paid else FULL,
                    (html, text, fidelity, date if date and date <= datetime.now(timezone.utc) else None, moved))


async def read_article(http: KindHttp, url: str, current_text: str, *, title: Optional[str] = None,
                       site: Optional[str] = None
                       ) -> Optional[Tuple[str, str, Dict[str, Any], Optional[datetime], Optional[str]]]:
    """read_page's article, or None when it took none (the feed body is kept)."""
    return (await read_page(http, url, current_text, title=title, site=site)).article


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
        # An undated item dated by its page (issue 0137 B9) is no longer "seen": the saver tells it by its time.
        **({"date_precision": None} if not post.get("date") and date else {}),
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


# --------------------------------------------------------------------------- the reader's line (issue 0140)

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
    """Why a post shows its feed's summary only (issue 0140), or None for a post read in full or never
    known short: its last page read did not take the page (not the same article, a script needed, an
    error), or found nothing longer though its feed cut the body with a "read more" link. A post whose page
    held nothing longer is otherwise whole (a link post, a short note)."""
    meta = metadata or {}
    outcome = outcome_of(meta)
    if meta.get(PAYWALLED_KEY) is True:
        return TEASER_REASONS[PAYWALLED]   # issue 0167: a paid post's page (its kind's, or its page read's markers)
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
