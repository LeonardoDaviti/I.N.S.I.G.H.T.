"""generic_rss: any RSS/Atom feed (the fallback kind). A new post whose feed gave only a
summary is expanded from its article page (ingestion/full_text.py), and a stored teaser whose
page read failed is read again on a later fetch (issue 0062). A live fetch asks for the feed
conditionally (issue 0044): an unchanged feed answers 304 and is no new posts."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from insight_core.ingestion import full_text
from insight_core.ingestion.http import AddressMemory, HttpError, KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import (
    BaseKind,
    Inspection,
    PolitenessProfile,
    SingleShotArchive,
    Source,
)
from insight_core.utils.json_safe import iso

logger = logging.getLogger("insight.ingestion.generic_rss")

GENERIC_RSS_PROFILE = PolitenessProfile(concurrency_pool="host-lock")

# Which of these urls are already stored (blocking; run in a thread).
StoredUrls = Callable[[Sequence[str]], set]
# A source's stored teasers due another read of their page (blocking; run in a thread):
# PostsRepository.teasers_to_read_again.
TeasersDue = Callable[..., List[Dict[str, Any]]]


class GenericRssKind(SingleShotArchive, BaseKind):
    name = "generic_rss"
    available_basis = "feed_window"
    conditional = True
    profile = GENERIC_RSS_PROFILE

    def __init__(self, http: KindHttp, *, stored_urls: Optional[StoredUrls] = None,
                 teasers_due: Optional[TeasersDue] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        self.http = http
        self.stored_urls = stored_urls
        self.teasers_due = teasers_due
        self.clock = clock

    def matches(self, source: Source) -> bool:
        return True  # the fallback

    async def fetch_latest(self, source: Source, limit: int, *,
                           memory: Optional[AddressMemory] = None) -> List[Dict[str, Any]]:
        """With memory (the runner's), the feed is asked conditionally: unchanged (304) is no new
        posts. Either way, the source's teasers due another read come after (issue 0062)."""
        url = str(source["handle_or_url"])
        posts: List[Dict[str, Any]] = []
        if memory is None:
            feed_text, _ = await self.http.get_text(url)
        else:
            answer = await memory.get(self.http, url)
            feed_text = None if answer.not_modified else answer.text
        if feed_text is not None:
            posts = await self._maybe_expand(source, parsing.parse_feed_posts(feed_text, url)[:limit])
        return await self._read_again(source, posts)

    async def inspect(self, source: Source) -> Inspection:
        url = str(source["handle_or_url"])
        feed_text, _ = await self.http.get_text(url)
        posts = parsing.parse_feed_posts(feed_text, url)
        oldest = posts[-1]["date"] if posts else None
        return Inspection(
            available_posts=len(posts),
            page_size=max(1, len(posts)),
            first_post_date=iso(oldest),
        )

    async def _maybe_expand(self, source: Source, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Read the article page of each new teaser post, one page at a time.

        A stored post is never re-read here: it was expanded when it was new, it is due another
        read (_read_again), or it is the repair script's job. When the lookup fails nothing is
        read, rather than every page. A read that failed is counted (full_text.with_page_try).
        """
        if not full_text.full_page_enabled(source):
            return posts
        teasers = [post for post in posts if full_text.page_is_article(post.get("url")) and full_text.is_teaser(post)]
        if not teasers:
            return posts
        try:
            stored = (await asyncio.to_thread(self.stored_urls, [post["url"] for post in teasers])
                      if self.stored_urls else set())
        except Exception as exc:  # noqa: BLE001 - the feed's own bodies are still saved
            logger.warning("Full-text lookup failed for %s: %s", source.get("handle_or_url"), exc)
            return posts
        expanded: Dict[str, Dict[str, Any]] = {}
        for index, post in enumerate(post for post in teasers if post["url"] not in stored):
            if index:
                await self.http.sleep(full_text.PAGE_DELAY_S)
            read = await self._read(post)
            if read is not None:
                expanded[post["url"]] = read
        return [expanded.get(post.get("url"), post) for post in posts]

    async def _read(self, post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """The post read from its page; None when the page holds nothing longer, or the read went
        wrong in a way no retry mends (the summary is kept). A failed request (an HttpError: an
        HTTP error, a timeout, a dropped connection) is the post with that try counted."""
        try:
            article = await full_text.read_article(self.http, post["url"], full_text.body_text(post))
        except HttpError as exc:
            logger.debug("Full-text read failed for %s: %s", post["url"], exc)
            return full_text.with_page_try(post, self.clock(), failed=True)
        except Exception as exc:  # noqa: BLE001 - the summary is kept
            logger.debug("Full-text expansion skipped for %s: %s", post["url"], exc)
            return None
        return full_text.with_full_text(post, *article) if article is not None else None

    async def _read_again(self, source: Source, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """The source's stored teasers whose page read failed, read again (issue 0062): a slice
        at a time, after the feed's own pages and PAGE_DELAY_S apart. Each comes back as a post
        the saver writes in place, with this try counted: its full text, or its stored teaser
        (still failed, or done when the page holds nothing longer). A host that is limiting us
        (a 429, a timeout) ends the slice after that try: the rest wait for the next fetch."""
        if self.teasers_due is None or not full_text.full_page_enabled(source) or not source.get("id"):
            return posts
        try:
            due = await asyncio.to_thread(
                self.teasers_due, str(source["id"]), now=self.clock(), max_tries=full_text.MAX_PAGE_TRIES,
                apart=full_text.RETRY_APART, limit=full_text.RETRY_SLICE)
        except Exception as exc:  # noqa: BLE001 - the fetch stands
            logger.warning("Teaser lookup failed for %s: %s", source.get("handle_or_url"), exc)
            return posts
        read_again: Dict[str, Dict[str, Any]] = {}
        for index, stored in enumerate(post for post in due if full_text.page_is_article(post.get("url"))):
            if index or posts:
                await self.http.sleep(full_text.PAGE_DELAY_S)
            try:
                article = await full_text.read_article(self.http, stored["url"], full_text.body_text(stored))
            except HttpError as exc:
                read_again[stored["url"]] = full_text.with_page_try(stored, self.clock(), failed=True)
                if exc.limiting:
                    logger.info("%s is limiting us (%s): %s teasers left for the next fetch",
                                stored["url"], str(exc)[:200], len(due) - index - 1)
                    break
                continue
            except Exception as exc:  # noqa: BLE001 - not a failed request: no more tries
                logger.debug("Full-text read again skipped for %s: %s", stored["url"], exc)
                article = None
            counted = full_text.with_page_try(stored, self.clock(), failed=False)
            read_again[stored["url"]] = full_text.with_full_text(counted, *article) if article else counted
        if read_again:
            logger.info("%s: %s teasers read again, %s in full", source.get("handle_or_url"), len(read_again),
                        sum(1 for post in read_again.values() if post["metadata"].get(full_text.FULL_TEXT_FLAG)))
        # A teaser still in the feed is the read-again post, once.
        return [post for post in posts if post.get("url") not in read_again] + list(read_again.values())
