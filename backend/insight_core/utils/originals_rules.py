"""A story's original, fetched when INSIGHT lacks it: a followed source fetched early when a story
links its page (issue 0114), and a News story's original collected, one page, when "Collect originals"
is on (issue 0123). Pure rules; the database and the requests are services/originals_service.py.

**One budget for both** (the owner's bar, 0114): the extra requests these make stay under 1% of the
requests the schedule makes. A credit: every source fetch the schedule makes adds EXTRA_SHARE of a
request, an extra request spends one, and it never holds more than EXTRA_CREDIT_CAP (a burst); 0114's
fetches go first, then 0123's by the story's voices, and what can't be asked now waits for the credit.
Replayed on the server's copy (2026-11-05, `plan/research/0123-measure.md`, the 8.7 days its per-source
fetch history covers): the two together were +1.14% of requests without it, +0.78% with it.

**0114, narrowed by the measure** (`plan/research/0114-measure.md`: as written +1.44%, 4 in 5 fetches
found nothing): a link is wanted only when
- a post of a story links it (a member or the story's root), not any post;
- it is a followed source's own page (0084 B's `OwnPages`: its post pages on its publication; on a
  platform its account's posts), the source followed when the link was seen, never a platform host;
- it isn't stored, and the linking post was published in the last 72 hours;
- the page isn't dated (by its address or a tweet's id) 7+ days before the link, nor a day before the
  source's last fetch: its feed can't hold it (it goes to "missing from the feed" with no fetch);
- the source wasn't fetched in the last 15 minutes, isn't in backoff, and had no early fetch in its
  scheduled interval (at most one per interval, not one per hour: 0114's measure saw 3 a day).

**0123's trigger** is the root of a News story's main story (`stories.origin_url`: the outside page its
posts link or quote first and most, 0064's tree), when no post is at it. It is collected only when:
- no followed source owns it (a followed source's page is 0114's: its source is fetched);
- it isn't walled (0081 is on hold): an address that carried an access or gift token, or a site whose
  every page the server read came back untitled, or whose follow test was "blocked";
- it is an article page: a platform page that names no account (a video's watch page) has none;
- a tweet is collected from the quote a member holds (its words as Nitter shows them, its date by its
  id): no request. A tweet no member quotes is not fetched (the save path reads x.com's app shell).
- a quote that names no address (only a name) is never fetched: there is nothing to fetch.
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

EXTRA_SHARE = 0.01                       # the owner's bar (0114): extra requests < 1% of the schedule's
EXTRA_CREDIT_CAP = 3.0                   # the most extra requests the credit holds at once: the replay's value
REFETCH_WITHIN = timedelta(minutes=15)   # 0114 decided 2
LINK_RECENT = timedelta(hours=72)        # 0114 decided 2
PAGE_OLD = timedelta(days=7)             # 0114's measure: older pages are never in a feed (8 of 8)
COLLECT_WITHIN = timedelta(days=7)       # a News story's original is collected in its first week; not measured
WALLED_MIN_READS = 2                     # a site read this often, never titled, is walled (0113's measure: 13-15 reads)

# A query key naming an access or gift token, or a value shaped as a signed token (a JWT): a page that needs one
# to be read is walled, and the token is never stored (0123). The vocabulary is url_normalization's (0126: every
# compared address drops it, and share marks too; a share mark opens no wall).
TWITTER_EPOCH_MS = 1288834974657
ADDRESS_DATE = re.compile(r"/((?:19|20)\d\d)[/-](0[1-9]|1[0-2])(?:[/-]([0-3]\d))?(?=/|$|-|\.)")


# Collect originals' switch (issue 0126 (4), the owner 2026-11-07: on by default). A stored false counts as your
# choice only when this default wrote it (the row carries COLLECT_CHOSEN): before, the dialog wrote false on every
# save, touched or not, so that false is no choice and reads as the default.
COLLECT_DEFAULT = True
COLLECT_CHOSEN = ("collect_originals_default", "on")


def collect_setting(stored: Optional[Mapping]) -> bool:
    """Whether Collect originals is on, from the scheduler's stored settings (None: never saved)."""
    stored = stored or {}
    value = stored.get("collect_originals")
    if value is None or (value is False and stored.get(COLLECT_CHOSEN[0]) != COLLECT_CHOSEN[1]):
        return COLLECT_DEFAULT
    return bool(value)


# Look up unlinked originals (issue 0138 C): a title lookup (the arXiv API, Crossref) for a document entity no post
# links. Off unless you switch it on (its own key in the scheduler's settings).
LOOKUP_SETTING = "lookup_originals"
LOOKUP_DEFAULT = False


def lookup_setting(stored: Optional[Mapping]) -> bool:
    """Whether Look up unlinked originals is on, from the scheduler's stored settings: off unless set true."""
    value = (stored or {}).get(LOOKUP_SETTING)
    return LOOKUP_DEFAULT if value is None else bool(value)


# Store Classics (issue 0138 E1): every Classic not stored collected once, under its own backfill allowance. On unless
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
    """`url` without its access and gift tokens (never stored, issue 0123); the rest as written."""
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
    """The date an address states: a tweet's id, else /2026/10/21/ or /2026-10/ in its path."""
    if is_tweet(url):
        return tweet_time(url)
    match = ADDRESS_DATE.search(urlsplit(url).path)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3) or 1), tzinfo=timezone.utc)
    except ValueError:
        return None


# ---- 0114: a followed source's page a story links -------------------------------------------------


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
    (0138 B5: raised while an entity's original has waited on it over 72 hours)."""
    return min(cap, max(0.0, credit) + EXTRA_SHARE * max(0, scheduled))


def whole(credit: float) -> int:
    """The extra requests a credit allows now."""
    return max(0, math.floor(credit + 1e-9))


# ---- 0123: a News story's original -------------------------------------------------------------------

FOLLOWED, WALLED, NO_ARTICLE, FROM_QUOTE, TWEET_UNHELD, PAGE = (
    "followed", "walled", "no_article", "from_quote", "tweet_unheld", "page")


@dataclass(frozen=True)
class SiteReads:
    """What the server read of one site (Discover's reads, issue 0080): pages read, pages titled, the
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
    """What collecting a story's original would be: FOLLOWED (0114 fetches its source), WALLED, NO_ARTICLE,
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
