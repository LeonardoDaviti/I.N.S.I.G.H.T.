"""A story's original, fetched when INSIGHT lacks it: a followed source fetched early when a story links its page
(0114), and a News story's original collected, one page, when "Collect originals" is on (0123). Pure rules; the
database and the requests are services/originals_service.py.

One budget for both: the extra requests stay under EXTRA_SHARE of the schedule's requests. A credit: every scheduled
source fetch adds EXTRA_SHARE of a request, an extra request spends one, and it never holds more than
EXTRA_CREDIT_CAP; early fetches go first, then collections by the story's voices.

An early fetch is wanted only for a story post's link to a followed source's own page, not stored, linked in the
last LINK_RECENT, not dated PAGE_OLD+ before the link, and a source not fetched in REFETCH_WITHIN, not in backoff,
and with no early fetch this interval. A News story's root (`stories.origin_url`) is collected only when no followed
source owns it, it isn't walled (an access token, a never-titled site, a blocked follow test) and it is an article;
a tweet is taken from the quote a member holds (no request), never fetched.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from insight_core.utils.addresses import host_of, is_tweet, site_of
from insight_core.utils.url_normalization import is_access_key, normalize_url

EXTRA_SHARE = 0.01                       # the owner's bar: extra requests < 1% of the schedule's
EXTRA_CREDIT_CAP = 3.0                   # the most extra requests the credit holds at once (measured: 0123)
REFETCH_WITHIN = timedelta(minutes=15)   # decided in plan/issues/0114
LINK_RECENT = timedelta(hours=72)        # decided in plan/issues/0114
PAGE_OLD = timedelta(days=7)             # older pages are never in a feed (measured: 0114)
COLLECT_WITHIN = timedelta(days=7)       # a News story's original is collected in its first week; not measured
WALLED_MIN_READS = 2                     # a site read this often, never titled, is walled (measured: 0113)
# A link post with no words of its own (a Reddit link post) has the page read (story_originals kind `linked`) so
# Mark X reads the post with the page's text and can join it to its story (0208). Its own words beyond its title:
# at most LINK_POST_OWN_CHARS; posted within LINK_POSTS_WITHIN.
LINK_POST_OWN_CHARS = 200
LINK_POSTS_WITHIN = timedelta(hours=72)
LINKED_PAGE_CHARS = 3000                 # the page's text Mark X reads with the post, at most

# A query key naming an access or gift token, or a value shaped as a signed token (a JWT): a page that needs one is
# walled, and the token is never stored. The vocabulary is url_normalization's.
TWITTER_EPOCH_MS = 1288834974657
ADDRESS_DATE = re.compile(r"/((?:19|20)\d\d)[/-](0[1-9]|1[0-2])(?:[/-]([0-3]\d))?(?=/|$|-|\.)")
# a month written by name in the address (/2008/Jul/7/, /2019/september/03/), a whole day only
ADDRESS_DATE_NAMED = re.compile(r"/((?:19|20)\d\d)/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*/([0-3]?\d)(?=/|$)",
                                re.IGNORECASE)


# Collect originals' switch: on by default. A stored false counts as your choice only when this default wrote it
# (the row carries COLLECT_CHOSEN): an older dialog wrote false on every save, so that false reads as the default.
COLLECT_DEFAULT = True
COLLECT_CHOSEN = ("collect_originals_default", "on")


def collect_setting(stored: Optional[Mapping]) -> bool:
    """Whether Collect originals is on, from the scheduler's stored settings (None: never saved)."""
    stored = stored or {}
    value = stored.get("collect_originals")
    if value is None or (value is False and stored.get(COLLECT_CHOSEN[0]) != COLLECT_CHOSEN[1]):
        return COLLECT_DEFAULT
    return bool(value)


# Look up unlinked originals: a title lookup (the arXiv API, Crossref) for a document entity no post
# links. Off unless you switch it on (its own key in the scheduler's settings).
LOOKUP_SETTING = "lookup_originals"
LOOKUP_DEFAULT = False


def lookup_setting(stored: Optional[Mapping]) -> bool:
    """Whether Look up unlinked originals is on, from the scheduler's stored settings: off unless set true."""
    value = (stored or {}).get(LOOKUP_SETTING)
    return LOOKUP_DEFAULT if value is None else bool(value)


# Store Classics: every Classic not stored collected once, under its own backfill allowance. On unless
# you switch it off.
CLASSICS_SETTING = "store_classics"
CLASSICS_DEFAULT = True


def classics_setting(stored: Optional[Mapping]) -> bool:
    """Whether Store Classics is on, from the scheduler's stored settings: on unless set false."""
    value = (stored or {}).get(CLASSICS_SETTING)
    return CLASSICS_DEFAULT if value is None else bool(value)


def access_keys(url: str) -> Tuple[str, ...]:
    """The query keys of `url` that carry an access or gift token."""
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    except ValueError:
        return ()
    return tuple(k for k, v in pairs if is_access_key(k, v))


def tokened(url: str) -> bool:
    return bool(access_keys(url))


def strip_access_tokens(url: str) -> str:
    """`url` without its access and gift tokens (never stored); the rest as written."""
    keys = set(access_keys(url))
    if not keys:
        return url
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k not in keys]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def tweet_time(url: str) -> Optional[datetime]:
    """When a tweet was written, by its id (X's ids carry their time)."""
    if not is_tweet(url):
        return None
    try:
        tweet_id = int(url.rstrip("/").rsplit("/", 1)[-1].split("?")[0].split("#")[0])
    except ValueError:
        return None
    return datetime.fromtimestamp(((tweet_id >> 22) + TWITTER_EPOCH_MS) / 1000, timezone.utc)


def page_date(url: str) -> Optional[datetime]:
    """The date an address states: a tweet's id, else /2026/10/21/ or /2026-10/ in its path, or a month by name
    with its day (/2008/Jul/7/)."""
    if is_tweet(url):
        return tweet_time(url)
    path = urlsplit(url).path
    named = ADDRESS_DATE_NAMED.search(path)
    if named and not ADDRESS_DATE.search(path):
        try:
            month = datetime.strptime(named.group(2)[:3].title(), "%b").month
            return datetime(int(named.group(1)), month, int(named.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return None
    match = ADDRESS_DATE.search(path)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3) or 1), tzinfo=timezone.utc)
    except ValueError:
        return None


def address_day(url: str) -> Optional[datetime]:
    """The day an address states, only when it names a whole day (/2026/10/21/, /2008/Jul/7/), never a month
    alone (/2026-10/ is no day): what dates a page that states none in its markup."""
    path = urlsplit(url).path
    if is_tweet(url) or ADDRESS_DATE_NAMED.search(path):
        return page_date(url)
    match = ADDRESS_DATE.search(path)
    return page_date(url) if match and match.group(3) else None


def address_month(url: str) -> Optional[datetime]:
    """The 1st of the month an address names when it names a month and no day (/2003/07/slug, /2026-10/),
    None otherwise (a day: address_day; a year alone: no guess)."""
    if is_tweet(url):
        return None
    path = urlsplit(url).path
    match = ADDRESS_DATE.search(path)
    if not match or match.group(3) or ADDRESS_DATE_NAMED.search(path):
        return None
    return datetime(int(match.group(1)), int(match.group(2)), 1, tzinfo=timezone.utc)


def address_hint(url: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
    """An older page's sort hint by its address alone, for the backlog's paths only: the address's whole day, else
    the 1st of its month (stored as a date alone), never a year alone, never a date more than a day ahead. Never
    above the date the page states: callers ask for it only when the page states none."""
    if not url:
        return None
    hint = address_day(url) or address_month(url)
    latest = (now or datetime.now(timezone.utc)) + timedelta(days=1)
    return hint if hint is not None and hint <= latest else None


# ---- early fetch: a followed source's page a story links -------------------------------------------------


def linked_wanted(url: str, linked_at: datetime, *, in_story: bool, last_fetch: Optional[datetime]) -> Optional[str]:
    """None when a link to a followed source's page not stored makes that source due now, else why not."""
    if not in_story:
        return "no story links it"
    dated = page_date(url)
    if dated is not None and dated < linked_at - PAGE_OLD:
        return "older than its feed"
    if dated is not None and last_fetch is not None and dated < last_fetch - timedelta(days=1):
        return "dated before the source's last fetch"
    return None


def early_fetch_blocked(now: datetime, *, last_attempt: Optional[datetime], failures: int,
                        retry_at: Optional[datetime], linked_fetched_at: Optional[datetime],
                        interval: Optional[timedelta]) -> Optional[str]:
    """Why a source can't be fetched early now (it waits for its schedule), else None."""
    if last_attempt is not None and now - last_attempt < REFETCH_WITHIN:
        return "fetched in the last 15 minutes"
    if failures > 0 and retry_at is not None and now < retry_at:
        return "in backoff"
    if linked_fetched_at is not None and interval is not None and now - linked_fetched_at < interval:
        return "one early fetch per interval"
    return None


# ---- the shared budget -------------------------------------------------------------------------------


def credit_after(credit: float, scheduled: int, cap: float = EXTRA_CREDIT_CAP) -> float:
    """The credit once `scheduled` more source fetches were made: EXTRA_SHARE of a request each, at most the cap
    (raised while an entity's original has waited on it over 72 hours)."""
    return min(cap, max(0.0, credit) + EXTRA_SHARE * max(0, scheduled))


def whole(credit: float) -> int:
    """The extra requests a credit allows now."""
    return max(0, math.floor(credit + 1e-9))


# ---- collect: a News story's original -------------------------------------------------------------------

FOLLOWED, WALLED, NO_ARTICLE, FROM_QUOTE, TWEET_UNHELD, PAGE = (
    "followed", "walled", "no_article", "from_quote", "tweet_unheld", "page")


@dataclass(frozen=True)
class SiteReads:
    """What the server read of one site (Discover's reads): pages read, pages titled, the
    follow test's label."""
    read: int = 0
    titled: int = 0
    follow: Optional[str] = None

    @property
    def walled(self) -> bool:
        return self.follow == "blocked" or (self.read >= WALLED_MIN_READS and self.titled == 0)


def site_reads_of(reads: Mapping) -> Dict[str, SiteReads]:
    """Each site's SiteReads from Discover's reads (system_settings discover_reads: {titles: {url: {title}},
    follow: {key: {label}}}): its pages read and titled, its follow test's label."""
    counts: Dict[str, List[int]] = {}
    for url, read in ((reads or {}).get("titles") or {}).items():
        site = site_of(host_of(normalize_url(url) or url))
        title = read.get("title") if isinstance(read, dict) else read
        n = counts.setdefault(site, [0, 0])
        n[0] += 1
        n[1] += 1 if title else 0
    out = {site: SiteReads(read=n[0], titled=n[1]) for site, n in counts.items()}
    for key, test in ((reads or {}).get("follow") or {}).items():
        if "/" in key or not isinstance(test, dict):
            continue   # a platform account's test says nothing of the platform's site
        site = site_of(key)
        base = out.get(site, SiteReads())
        out[site] = SiteReads(read=base.read, titled=base.titled, follow=test.get("label"))
    return out


def trigger_kind(url: str, *, owner: Optional[str], names_account: bool, reads: SiteReads,
                 linked_as: Iterable[str] = (), quoted: Optional[str] = None, article: bool = True) -> str:
    """What collecting a story's original would be: FOLLOWED (an early fetch of its source), WALLED, NO_ARTICLE,
    FROM_QUOTE (a tweet a member quotes: no request), TWEET_UNHELD (a tweet nobody quotes: not fetched), or
    PAGE (one request). `names_account`: the address is a platform's page of an account, or not on a
    platform (Discover's discover_address found a key); `article`: not a reference, document, app or
    archive address (the Pages rows' tests); `linked_as`: the addresses the members link it by."""
    if owner:
        return FOLLOWED
    if tokened(url) or any(tokened(link) for link in linked_as):
        return WALLED
    if not names_account or not article:
        return NO_ARTICLE
    if is_tweet(url):
        return FROM_QUOTE if (quoted or "").strip() else TWEET_UNHELD
    if reads.walled:
        return WALLED
    return PAGE


def collect_order(rows: Sequence[Tuple[str, int, datetime]]) -> list:
    """(key, voices, first_at) rows, the biggest stories first, then the newest."""
    return sorted(rows, key=lambda r: (-r[1], -r[2].timestamp(), r[0]))


__all__ = [
    "COLLECT_CHOSEN", "COLLECT_DEFAULT", "LOOKUP_DEFAULT", "LOOKUP_SETTING", "lookup_setting", "CLASSICS_DEFAULT", "CLASSICS_SETTING", "classics_setting", "EXTRA_SHARE", "FOLLOWED", "FROM_QUOTE", "NO_ARTICLE", "PAGE", "SiteReads", "TWEET_UNHELD", "WALLED",
    "access_keys", "collect_order", "collect_setting", "credit_after", "early_fetch_blocked", "linked_wanted", "page_date", "site_reads_of",
    "strip_access_tokens", "tokened", "trigger_kind", "tweet_time", "whole",
]
