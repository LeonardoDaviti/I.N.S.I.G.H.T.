"""nitter_rss: X/Twitter accounts through a Nitter instance's /<user>/rss feed (cursor paging).

An archive that continues below the stored tweets jumps by date: its first page is the
bridge's search RSS, /<user>/search/rss?f=tweets&q=&until=<day> (until is exclusive), and
later pages add the same min-id cursor as the feed's pager. Every page's checkpoint keeps
search_until, so a resume stays on the search (checked on the owner's bridge, 2026-10-16).

A tweet that is an X Article, which the bridge gives as its link alone, is read again by its status id
(kinds/x_articles.py, v10.13.10): on a live fetch and an archive alike, at most x_articles.MAX_PER_FETCH a
fetch (an archive: a page). One stored with its article is kept as stored, not looked up again (a preview: once
a day); one stored as the link alone is looked up again, and the saver writes its article over it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import parsing, x_articles
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    PolitenessProfile,
    RateLimit,
    Source,
    resume_counts,
    start_at,
)
from insight_core.utils.addresses import host_of

logger = logging.getLogger("insight.ingestion.nitter_rss")

# Which of these urls are stored with their X Article read, each as stored (blocking; run in a thread):
# PostsRepository.stored_x_articles.
StoredArticles = Callable[[Sequence[str]], Dict[str, Dict[str, Any]]]

# Your Nitter (issue 0137 B3), configured like the Telegram bridge: NITTER_HOSTS, a comma list of hosts or
# origins, the first used for an x.com address pasted in the Add-source dialog ("nitter.local" when unset,
# as before; set and empty: none). Every host listed is read as Nitter, beside the known ones.
KNOWN_NITTER_HOSTS = ("nitter.local", "nitter.net")
NITTER_BASE_URL = "https://nitter.local"
NITTER_ENV = "NITTER_HOSTS"


def configured_nitters(env: Mapping[str, str] = os.environ) -> Optional[List[str]]:
    """The Nitter origins NITTER_HOSTS lists ("https://nitter.example"); None when unset."""
    raw = env.get(NITTER_ENV)
    if raw is None:
        return None
    return [item if "://" in item else f"https://{item}" for item in (part.strip().rstrip("/") for part in raw.split(",")) if item]


def nitter_origin(env: Mapping[str, str] = os.environ) -> Optional[str]:
    """The Nitter an x.com address is read through: the first configured, NITTER_BASE_URL when unset,
    None when NITTER_HOSTS is set and empty."""
    nitters = configured_nitters(env)
    if nitters is None:
        return NITTER_BASE_URL
    return nitters[0] if nitters else None


# gates.HOST_FLOORS gives each a 10s floor.
NITTER_HOSTS = frozenset({*KNOWN_NITTER_HOSTS,
                          *((urllib.parse.urlparse(o).hostname or "").lower() for o in configured_nitters() or ())} - {""})

NITTER_PROFILE = PolitenessProfile(
    concurrency_pool="host-lock",
    page_delay_s=10,
    batch_size=10,
    batch_cooldown_s=30,
    live_pages_rate_limited=True,
)

# A status id in your Nitter's own links: any id, an old tweet's too (an address on any host is a
# tweet only with 15+ digits, url_normalization.TWEET_PATH, so other sites' /status/ pages aren't).
STATUS_RE = re.compile(r"/status/(?P<post_id>\d+)")


def extract_nitter_tweet_count(profile_html: str) -> Optional[int]:
    match = re.search(
        r'<li class="posts">.*?<span class="profile-stat-num">([\d,]+)</span>',
        profile_html,
        re.DOTALL,
    )
    if not match:
        return None
    return int(match.group(1).replace(",", ""))


def _status_id(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    match = STATUS_RE.search(value)
    return match.group("post_id") if match else None


def _username(source_url: str) -> str:
    segments = parsing.path_segments(source_url)
    if len(segments) < 2 or segments[1] != "rss":
        raise ValueError(f"Invalid Nitter RSS URL: {source_url}")
    return segments[0]


class NitterRssKind(BaseKind):
    name = "nitter_rss"
    chronological = True   # newest first: an archive back to a date stops past it (issue 0130 C)
    available_basis = "estimate"   # the profile counter (replies and reposts included)
    profile = NITTER_PROFILE

    def __init__(self, http: KindHttp, *, stored_articles: Optional[StoredArticles] = None,
                 env: Mapping[str, str] = os.environ,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.http = http
        self.stored_articles = stored_articles
        self.env = env
        self.clock = clock

    def matches(self, source: Source) -> bool:
        url = str(source.get("handle_or_url") or "")
        segments = parsing.path_segments(url)
        return host_of(url) in NITTER_HOSTS and len(segments) >= 2 and segments[1] == "rss"

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "nitter_cursor" and checkpoint.get(
            "cursor"
        ) is not None

    async def start_checkpoint(self, source: Source, stored) -> Optional[dict]:
        oldest = stored.get("oldest_published_at")
        if not isinstance(oldest, datetime):
            return None
        if oldest.tzinfo is not None:
            oldest = oldest.astimezone(timezone.utc)
        # until is exclusive: the day after the oldest stored tweet re-reads that whole day.
        return start_at(mode="nitter_cursor", cursor=None,
                        search_until=(oldest.date() + timedelta(days=1)).isoformat())

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        posts: List[Dict[str, Any]] = []
        async for page in self._pages(str(source["handle_or_url"]), limit, None, None, 0, 0,
                                      self.profile.rate_limit(), [x_articles.MAX_PER_FETCH]):
            posts.extend(page.posts)
        return posts[:limit]

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        collected, pages = resume_counts(checkpoint)
        cursor = (checkpoint or {}).get("cursor")
        search_until = (checkpoint or {}).get("search_until")
        async for page in self._pages(str(source["handle_or_url"]), target, cursor, search_until, collected, pages,
                                      None):
            yield page

    async def inspect(self, source: Source) -> Inspection:
        source_url = str(source["handle_or_url"])
        username = _username(source_url)
        origin = parsing.origin_from_source(source_url, NITTER_BASE_URL)
        profile_html, _ = await self.http.get_text(f"{origin}/{username}")
        rss_text, _ = await self.http.get_text(source_url)
        page_size = max(1, len(parsing.parse_feed_posts(rss_text, source_url)))
        return Inspection(extract_nitter_tweet_count(profile_html), page_size, None)

    async def _pages(self, source_url: str, target: int, cursor: Optional[str], search_until: Optional[str],
                     initial_collected: int, initial_pages: int, rate: Optional[RateLimit],
                     lookups: Optional[List[int]] = None):
        """Pages until target posts (counting initial_collected). With a rate (a live fetch) the
        pause between pages is slept here; an archive passes None, its loop paces the pages.
        lookups: the X Article lookups left for the whole fetch ([n], shared by its pages); None gives each
        page x_articles.MAX_PER_FETCH (an archive)."""
        seen_urls: set[str] = set()
        collected = initial_collected
        pages_fetched = initial_pages
        current_cursor = cursor

        while collected < target:
            page_posts, next_cursor = await self._fetch_page(source_url, current_cursor, search_until)
            if not page_posts:
                break

            pages_fetched += 1
            unique: List[Dict[str, Any]] = []
            for post in page_posts:
                if post["url"] in seen_urls:
                    continue
                seen_urls.add(post["url"])
                unique.append(post)
                collected += 1
                if collected >= target:
                    break
            unique = await self._with_articles(unique, lookups if lookups is not None else [x_articles.MAX_PER_FETCH])

            checkpoint = {
                "mode": "nitter_cursor",
                "cursor": next_cursor,
                "last_cursor": current_cursor,
                "pages_fetched": pages_fetched,
                "collected_posts": collected,
            }
            if search_until:
                checkpoint["search_until"] = search_until
            yield ArchivePage(unique, checkpoint)

            if collected >= target or not next_cursor or next_cursor == current_cursor:
                break
            current_cursor = next_cursor
            if rate is not None:
                await self.http.sleep(rate.delay_after(pages_fetched))

    async def _fetch_page(self, source_url: str, cursor: Optional[str],
                          search_until: Optional[str]) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        origin = parsing.origin_from_source(source_url, NITTER_BASE_URL)
        username = _username(source_url)
        params = {"f": "tweets", "q": "", "until": search_until} if search_until else {}
        if cursor:
            params["cursor"] = cursor
        path = f"{origin}/{username}/search/rss" if search_until else f"{origin}/{username}/rss"
        url = f"{path}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}" if params else path

        body, headers = await self.http.get_text(url)
        posts = parsing.parse_feed_posts(body, f"{origin}/{username}/rss")
        for post in posts:
            external_id = _status_id(post["url"]) or _status_id(post.get("guid", ""))
            if external_id:
                post["external_id"] = external_id
        return posts, headers.get("min-id")

    # ------------------------------------------------------------------ X Articles (v10.13.10)

    async def read_article_post(self, post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The tweet with its X Article (x_articles.with_article), or None when it is none or no route gave it."""
        status = x_articles.status_of(str(post.get("url") or ""))
        if status is None or not x_articles.is_article_post(post):
            return None
        article = await x_articles.read_article(self.http, *status, env=self.env)
        return x_articles.with_article(post, article, self.clock()) if article else None

    async def _with_articles(self, posts: List[Dict[str, Any]], lookups: List[int]) -> List[Dict[str, Any]]:
        """The page's tweets, each X Article read (lookups[0] at most, LOOKUP_DELAY_S apart). One stored with its
        article comes as stored (the saver writes it back as it is), unless a preview is due again."""
        found = [post for post in posts if x_articles.is_article_post(post) and x_articles.status_of(post["url"])]
        if not found or not x_articles.lookups_on(self.env):
            return posts
        stored: Dict[str, Dict[str, Any]] = {}
        if self.stored_articles is not None:
            try:
                stored = await asyncio.to_thread(self.stored_articles, [post["url"] for post in found])
            except Exception as exc:  # noqa: BLE001 - the tweets are still saved, their articles looked up
                logger.warning("X Article lookup of stored tweets failed: %s", exc)
        now = self.clock()
        read: Dict[str, Dict[str, Any]] = {}
        asked = 0
        for post in found:
            kept = stored.get(post["url"])
            if kept is not None and not x_articles.due_again(kept, now):
                read[post["url"]] = {**post, **kept}
                continue
            if lookups[0] <= 0:
                logger.info("X Articles: lookups used up for this fetch; %s waits for the next", post["url"])
                if kept is not None:
                    read[post["url"]] = {**post, **kept}
                continue
            if asked:
                await self.http.sleep(x_articles.LOOKUP_DELAY_S)
            lookups[0] -= 1
            asked += 1
            fresh = await self.read_article_post(post)
            if fresh is not None:
                read[post["url"]] = fresh
            elif kept is not None:
                read[post["url"]] = {**post, **kept}
        return [read.get(post["url"], post) for post in posts]
