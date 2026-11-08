"""generic_rss: any RSS/Atom feed (the fallback kind). A new post whose feed gave only a
summary is expanded from its article page (ingestion/full_text.py), and a stored teaser whose
page read failed is read again on a later fetch (issue 0062). A live fetch asks for the feed
conditionally (issue 0044): an unchanged feed answers 304 and is no new posts.

The archive (issue 0108): the feed, and when the site's sitemap lists more posts under the feed's
section than the feed holds, each older one read from its page (page watch's reader: its body,
title and date; not a post without a date or og:type article), one per archive page so the host
gate spaces them, resumable by its checkpoint (mode "sitemap"). Nothing stored is removed."""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from insight_core.ingestion import full_text
from insight_core.ingestion.http import AddressMemory, HttpError, KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.db.repo_posts import BACKLOG_KEY
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    PolitenessProfile,
    SKIP_NO_POST,
    SKIP_STORED,
    SKIP_UNREADABLE,
    UNREADABLE,
    FetchedPosts,
    Source,
    checked_fetch,
    resume_counts,
    skipped_counts,
)
from insight_core.utils.addresses import host_of, publication_of
from insight_core.utils.json_safe import iso
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.ingestion.generic_rss")

GENERIC_RSS_PROFILE = PolitenessProfile(concurrency_pool="host-lock")
# The archive's checkpoint past the feed: an index into the site's sitemap posts (issue 0108).
SITEMAP_MODE = "sitemap"

# Which of these urls are already stored (blocking; run in a thread).
StoredUrls = Callable[[Sequence[str]], set]
# A source's stored teasers due another read of their page (blocking; run in a thread):
# PostsRepository.teasers_to_read_again.
TeasersDue = Callable[..., List[Dict[str, Any]]]


class GenericRssKind(BaseKind):
    name = "generic_rss"
    available_basis = "feed_window"
    conditional = True
    reads_posts = True   # read_post: one page of its site, as the site reader reads it (issue 0084 B)
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
        failure: Optional[str] = None
        if memory is None:
            feed_text, _ = await self.http.get_text(url)
        else:
            answer = await memory.get(self.http, url)
            feed_text = None if answer.not_modified else answer.text
        if feed_text is not None:
            # A feed with items none of which were read is an error, not "empty" (issue 0135); items
            # that would be stored as fewer posts than they are, a failure saying so (issue 0137 A1).
            parsed = parsing.parse_feed_posts(feed_text, url)
            failure = checked_fetch(parsed, parsing.feed_items(feed_text) if not parsed else len(parsed), {}).failure
            posts = await self._maybe_expand(source, parsed[:limit])
        result = FetchedPosts(await self._read_again(source, posts))
        result.failure = failure
        return result

    async def inspect(self, source: Source) -> Inspection:
        """The feed's posts, and the sitemap's when it lists more of the feed's section (issue 0108):
        then each older post is one archive page."""
        url = str(source["handle_or_url"])
        feed_text, _ = await self.http.get_text(url)
        posts = parsing.parse_feed_posts(feed_text, url)
        oldest = posts[-1]["date"] if posts else None
        site, prefix, listed = await self._sitemap_posts(posts)
        older = [loc for loc, _ in listed if normalize_url(loc) not in _addresses(posts)]
        return Inspection(
            available_posts=len(posts) + len(older),
            page_size=1 if older else max(1, len(posts)),
            first_post_date=iso(oldest),
            raw={"sitemap_posts": len(older), "sitemap_prefix": prefix} if older else {},
        )

    async def read_post(self, source: Source, url: str) -> Optional[Dict[str, Any]]:
        from insight_core.ingestion.kinds.page_watch import read_page_post   # page_watch imports this module

        return await read_page_post(self.http, source, url, adapter=self.name)

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        """An archive stopped in the sitemap's posts (issue 0108) continues there."""
        return (isinstance(checkpoint, dict) and checkpoint.get("mode") == SITEMAP_MODE
                and int(checkpoint.get("next_index") or 0) < int(checkpoint.get("total_candidates") or 0))

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: Any):
        """The feed's posts (one page), then the sitemap's older posts one page each (issue 0108),
        resumable from the checkpoint's next_index. A feed holding the whole sitemap is one page with
        no checkpoint, as a single fetch."""
        url = str(source["handle_or_url"])
        collected, pages_fetched = resume_counts(checkpoint)
        skipped = skipped_counts(checkpoint)
        if self.checkpoint_resumable(checkpoint):
            held: set = set()
            site, prefix, listed = await self._sitemap_posts([], site=checkpoint.get("site"), prefix=checkpoint.get("prefix"))
            start = int(checkpoint["next_index"])
        else:
            feed_text, _ = await self.http.get_text(url)
            feed = parsing.parse_feed_posts(feed_text, url)
            posts = await self._read_again(source, await self._maybe_expand(source, feed[:target]))
            held = _addresses(feed)
            site, prefix, listed = await self._sitemap_posts(feed)
            if not any(normalize_url(loc) not in held for loc, _ in listed):
                yield ArchivePage(posts, None)
                return
            collected, pages_fetched, start = collected + len(posts), pages_fetched + 1, 0
            yield ArchivePage(posts, self._checkpoint(site, prefix, 0, pages_fetched, collected, len(listed), skipped))
        stored = (await asyncio.to_thread(self.stored_urls, [loc for loc, _ in listed[start:]])
                  if self.stored_urls and listed[start:] else set())
        index = start
        while index < len(listed) and collected < target:
            loc, lastmod = listed[index]
            index += 1
            if loc in stored or normalize_url(loc) in held:
                skipped[SKIP_STORED] += 1
                continue
            post = await self._sitemap_post(source, loc, lastmod)
            if not isinstance(post, dict):
                skipped[SKIP_UNREADABLE if post == UNREADABLE else SKIP_NO_POST] += 1
                post = None
            collected += 1 if post else 0
            pages_fetched += 1
            yield ArchivePage([post] if post else [],
                              self._checkpoint(site, prefix, index, pages_fetched, collected, len(listed), skipped))

    @staticmethod
    def _checkpoint(site: str, prefix: str, next_index: int, pages_fetched: int, collected: int, total: int,
                    skipped: Optional[Dict[str, int]] = None) -> dict:
        return {"mode": SITEMAP_MODE, "site": site, "prefix": prefix, "next_index": next_index,
                "pages_fetched": pages_fetched, "collected_posts": collected, "total_candidates": total,
                "skipped": dict(skipped or {})}

    async def _sitemap_posts(self, posts: Sequence[Dict[str, Any]], *, site: Optional[str] = None,
                             prefix: Optional[str] = None) -> Tuple[str, str, List[Tuple[str, Optional[datetime]]]]:
        """(the site, the feed's section, the sitemap's posts under it): the feed's items' site and the
        path they share ("/posts/" for /posts/2021/03/a and /posts/2020/12/b; "/" for /a/ and /b/), and the
        sitemap's addresses there, newest lastmod first, once each. No posts when the sitemap lists no more
        of them than the feed holds, or cannot be read (issue 0108)."""
        from insight_core.ingestion.kinds.page_watch import ARCHIVE_SITEMAPS, sitemap_entries   # page_watch imports this module

        links = [p["url"] for p in posts if isinstance(p.get("url"), str) and p["url"].startswith("http")]
        if site is None or prefix is None:
            if not links:
                return "", "/", []
            site, prefix = parsing.origin_from_source(links[0], ""), feed_section(links)
        try:
            entries = await sitemap_entries(self.http, site + "/", prefix, posts_only=True, max_files=ARCHIVE_SITEMAPS)
        except Exception as exc:  # noqa: BLE001 - no sitemap: the feed is the archive
            logger.debug("Sitemap of %s not read: %s", site, exc)
            return site, prefix, []
        publication = publication_of(host_of(site))
        found: Dict[str, Tuple[str, Optional[datetime]]] = {}
        for order, (loc, lastmod) in enumerate(entries):
            path = urllib.parse.urlparse(loc).path or "/"
            key = normalize_url(loc)
            if (key and publication_of(host_of(loc)) == publication and path.startswith(prefix)
                    and path.rstrip("/") + "/" != prefix):
                found.setdefault(key, (loc, parsing.parse_datetime_value(lastmod)))
        if len(found) <= len(_addresses(links)) and links:
            return site, prefix, []
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        listed = sorted(found.values(), key=lambda entry: entry[1] or epoch, reverse=True)
        return site, prefix, listed

    async def _sitemap_post(self, source: Source, url: str, lastmod: Optional[datetime]) -> Any:
        """One older post from the sitemap, read from its page as page watch reads one; None when the
        page is no post, UNREADABLE when it cannot be read (a host limiting us stops the archive: it resumes)."""
        from insight_core.ingestion.kinds.page_watch import article_post, page_date

        try:
            page, _ = await self.http.get_text(url)
        except HttpError as exc:
            if exc.limiting:
                raise
            logger.info("Archive: %s could not be read (%s)", url, exc)
            return UNREADABLE
        except ValueError as exc:
            logger.info("Archive: %s could not be read (%s)", url, exc)
            return UNREADABLE
        date = page_date(page)
        if date is None and parsing.meta_content(page, "og:type").lower() != "article":
            return None
        post = article_post(page, str(source["handle_or_url"]), url, date or lastmod, adapter=self.name)
        if post is not None:
            post[BACKLOG_KEY] = True   # from the sitemap: never "new to you" (issue 0039)
        return post

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
        HTTP error, a timeout, a dropped connection) is the post with that try counted, and so is a
        page with nothing longer for a post with no body at all (issue 0108)."""
        try:
            article = await full_text.read_article(self.http, post["url"], full_text.body_text(post))
        except HttpError as exc:
            logger.debug("Full-text read failed for %s: %s", post["url"], exc)
            return full_text.with_page_try(post, self.clock(), failed=True)
        except Exception as exc:  # noqa: BLE001 - the summary is kept
            logger.debug("Full-text expansion skipped for %s: %s", post["url"], exc)
            return None
        if article is None:
            return full_text.with_page_try(post, self.clock(), failed=True) if full_text.empty_read_failed(post) else None
        return full_text.with_full_text(post, *article)

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
            # Nothing longer ends it, unless the post has no body at all (issue 0108).
            counted = full_text.with_page_try(stored, self.clock(),
                                              failed=article is None and full_text.empty_read_failed(stored))
            read_again[stored["url"]] = full_text.with_full_text(counted, *article) if article else counted
        if read_again:
            logger.info("%s: %s teasers read again, %s in full", source.get("handle_or_url"), len(read_again),
                        sum(1 for post in read_again.values() if post["metadata"].get(full_text.FULL_TEXT_FLAG)))
        # A teaser still in the feed is the read-again post, once.
        return [post for post in posts if post.get("url") not in read_again] + list(read_again.values())


def _addresses(posts_or_urls: Sequence[Any]) -> set:
    """The normalized addresses of posts (or of addresses)."""
    return {normalize_url(item["url"] if isinstance(item, dict) else item) for item in posts_or_urls} - {None}


def feed_section(links: Sequence[str]) -> str:
    """The path a feed's items share, their own last segment and a date's folders after it aside
    (issue 0108): "/posts/" for /posts/2021/03/a and /posts/2020/12/b (or /posts/2020/10/a alone),
    "/" for /a/ and /b/."""
    folders = [parsing.path_segments(link)[:-1] for link in links]
    shared: List[str] = []
    for parts in zip(*folders):
        if len(set(parts)) != 1:
            break
        shared.append(parts[0])
    while shared and shared[-1].isdigit():
        shared.pop()
    return "/" + "".join(f"{part}/" for part in shared)
