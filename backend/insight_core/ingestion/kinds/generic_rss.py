"""generic_rss: any RSS/Atom feed (the fallback kind). A new post whose feed gave only a
summary is expanded from its article page (ingestion/full_text.py), and a stored teaser whose
page read failed is read again on a later fetch (issue 0062). A live fetch asks for the feed
conditionally (issue 0044): an unchanged feed answers 304 and is no new posts.

The archive (issues 0108, 0143): the feed, then the smart archiver's ladder (ingestion/archive_ladder.py): the
site's platform, and each strategy that finds more than the feed holds (the feed's paging, the platform's API, the
sitemap, the listing pages, the Web Archive's index when the source opts in), in order. A post found by its address
is read from its page (page watch's reader: its body, title and date; not a post without a date or og:type
article), one per archive page so the host gate spaces them; a feed or API page's posts as the feed's. Resumable by
its checkpoint (its mode the strategy's, its "ladder" the rest). Nothing stored is removed."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from insight_core.ingestion import archive_ladder, full_text
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
# The ladder's other strategies' checkpoints (issue 0143).
FEED_PAGES_MODE = "feed_pages"
API_MODE = "api"
LISTING_MODE = "listing"
WEB_ARCHIVE_MODE = "web_archive"
LADDER_MODES = frozenset({SITEMAP_MODE, FEED_PAGES_MODE, API_MODE, LISTING_MODE, WEB_ARCHIVE_MODE})
# The strategies whose posts are read one page each (page_size 1).
ADDRESS_STRATEGIES = frozenset({archive_ladder.SITEMAP, archive_ladder.LISTING, archive_ladder.WEB_ARCHIVE})
PLAN_TTL_S = 600        # a plan's ladder is reused by the archive that follows it this long
LADDER_ITEMS = 50       # the feed's item addresses a checkpoint keeps (the posts' shape, on a resume)
UNBOUNDED = 10 ** 9


class LearnedLadder:
    """The learned ladder's store (system_settings archive_learned, issue 0143): get() -> {platform: {strategy:
    posts}}, add(platform, strategy, posts). Blocking; the kind calls it in a thread."""

    def __init__(self, db_url: str) -> None:
        self.db_url = db_url

    def get(self) -> dict:
        from insight_core.db import database as db
        from insight_core.db.repo_operations import SystemSettingsRepository

        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            found = SystemSettingsRepository.get(cur, archive_ladder.LEARNED_KEY)
        return found[0] if found and isinstance(found[0], dict) else {}

    def add(self, platform: str, strategy: str, posts: int) -> None:
        from insight_core.db import database as db
        from insight_core.db.repo_operations import SystemSettingsRepository

        with db.transaction(self.db_url) as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (archive_ladder.LEARNED_KEY,))
            found = SystemSettingsRepository.get(cur, archive_ladder.LEARNED_KEY)
            current = found[0] if found and isinstance(found[0], dict) else {}
            SystemSettingsRepository.upsert(cur, archive_ladder.LEARNED_KEY,
                                            archive_ladder.learned_after(current, platform, strategy, posts))

# Which of these urls are already stored (blocking; run in a thread).
StoredUrls = Callable[[Sequence[str]], set]
# A source's stored teasers due another read of their page (blocking; run in a thread):
# PostsRepository.teasers_to_read_again.
TeasersDue = Callable[..., List[Dict[str, Any]]]


class GenericRssKind(BaseKind):
    name = "generic_rss"
    available_basis = "feed_window"
    chronological = True   # its archive goes newest first: back to a date stops past it (issues 0130 C, 0143)
    conditional = True
    reads_posts = True   # read_post: one page of its site, as the site reader reads it (issue 0084 B)
    profile = GENERIC_RSS_PROFILE

    def __init__(self, http: KindHttp, *, stored_urls: Optional[StoredUrls] = None,
                 teasers_due: Optional[TeasersDue] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 learned: Optional[Any] = None) -> None:
        self.http = http
        self.stored_urls = stored_urls
        self.teasers_due = teasers_due
        self.clock = clock
        self.learned = learned      # LearnedLadder (or a stand-in): None keeps the default order
        self._plans: Dict[str, Tuple[float, Any]] = {}   # source id -> (monotonic, its plan's LadderResult)

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

    # ------------------------------------------------------------------ the archive (issues 0108, 0143)

    async def _ladder(self, source: Source, feed: List[Dict[str, Any]], feed_text: str,
                      headers: Optional[Dict[str, str]] = None) -> "archive_ladder.LadderResult":
        """The site's platform and every strategy's probe (archive_ladder), kept PLAN_TTL_S for the archive
        that follows its plan."""
        learned = None
        if self.learned is not None:
            try:
                learned = await asyncio.to_thread(self.learned.get)
            except Exception as exc:  # noqa: BLE001 - the default order
                logger.warning("Archive: the learned ladder could not be read: %s", exc)
        result = await archive_ladder.Ladder(self, source, feed, feed_text, headers, learned=learned).run()
        if source.get("id"):
            self._plans[str(source["id"])] = (time.monotonic(), result)
        return result

    def _planned(self, source: Source) -> Optional["archive_ladder.LadderResult"]:
        kept = self._plans.pop(str(source.get("id") or ""), None)
        return kept[1] if kept and time.monotonic() - kept[0] < PLAN_TTL_S else None

    async def inspect(self, source: Source) -> Inspection:
        """The feed's posts and the ladder's look at the rest of the site (issue 0143): the platform, each
        strategy's outcome and the site's size (`smart`); the sitemap's older posts as before (issue 0108)."""
        url = str(source["handle_or_url"])
        feed_text, headers = await self.http.get_text(url)
        posts = parsing.parse_feed_posts(feed_text, url)
        oldest = posts[-1]["date"] if posts else None
        result = await self._ladder(source, posts, feed_text, headers)
        smart = result.smart()
        raw: Dict[str, Any] = {"smart": smart}
        sitemap = result.probes.get(archive_ladder.SITEMAP)
        if sitemap is not None and sitemap.more:
            raw.update(sitemap_posts=sitemap.new, sitemap_prefix=sitemap.state.get("prefix"))
        found = result.found
        # The site's size: the largest trustworthy estimate; unknown (None) when a strategy found more and none
        # can say how many; the feed's own count when nothing finds more.
        available = smart["estimate"] if (result.estimate or not found) else None
        by_address = bool(found) and found[0] in ADDRESS_STRATEGIES
        return Inspection(
            available_posts=available,
            page_size=1 if by_address else max(1, len(posts)),
            first_post_date=iso(oldest),
            raw=raw,
        )

    async def read_post(self, source: Source, url: str) -> Optional[Dict[str, Any]]:
        from insight_core.ingestion.kinds.page_watch import read_page_post   # page_watch imports this module

        return await read_page_post(self.http, source, url, adapter=self.name)

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        """An archive stopped in a strategy of the ladder (issue 0143), or in the sitemap's posts (issue 0108),
        continues there; one whose strategy ended continues with the next one it found more in."""
        if not isinstance(checkpoint, dict):
            return False
        ladder = checkpoint.get("ladder") if isinstance(checkpoint.get("ladder"), dict) else None
        if ladder is not None and ladder.get("order"):
            return checkpoint.get("mode") in LADDER_MODES
        if checkpoint.get("mode") == SITEMAP_MODE:
            return int(checkpoint.get("next_index") or 0) < int(checkpoint.get("total_candidates") or 0)
        return checkpoint.get("mode") in LADDER_MODES and not checkpoint.get("end")

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: Any):
        """The feed's posts (one page), then each strategy of the ladder that found more (issue 0143), in its
        order: the feed's next pages, the platform's API, the sitemap's older posts and the listing's (one
        page each, issue 0108), the Web Archive's (opt-in). Each skips what was seen or is stored, and the
        ladder stops once the seen addresses reach the site's estimate. Resumable from the checkpoint. A feed
        whose site holds nothing more is one page with no checkpoint, as a single fetch."""
        url = str(source["handle_or_url"])
        hint: Optional[list] = None   # the sitemap's posts the plan read (the first strategy's, when it is the sitemap)
        if self.checkpoint_resumable(checkpoint):
            assert checkpoint is not None
            held: set = set()
            if not isinstance(checkpoint.get("ladder"), dict):
                # An archive in the sitemap's posts from before the ladder (issue 0108): the sitemap alone.
                listed = (await self._sitemap_posts([], site=checkpoint.get("site"), prefix=checkpoint.get("prefix")))[2]
                async for page in self._sitemap_pages(source, checkpoint, listed, held, target):
                    yield page
                return
        else:
            feed_text, headers = await self.http.get_text(url)
            feed = parsing.parse_feed_posts(feed_text, url)
            posts = await self._read_again(source, await self._maybe_expand(source, feed[:target]))
            held = _addresses(feed)
            plan = self._planned(source) or await self._ladder(source, feed, feed_text, headers)
            found = plan.found
            if not found:
                yield ArchivePage(posts, None)
                return
            first = found[0]
            starts = {name: plan.probes[name].state for name in found}
            ladder = {"platform": plan.platform.platform, "order": found[1:], "estimate": plan.estimate,
                      "items": [p["url"] for p in feed if isinstance(p.get("url"), str)][:LADDER_ITEMS],
                      "starts": {name: _public(state) for name, state in starts.items()}, "worked": {}}
            checkpoint = self._start(first, starts[first], ladder, pages_fetched=1, collected=len(posts))
            hint = starts[first].get("_listed")
            yield ArchivePage(posts, checkpoint)
        while True:
            mode = checkpoint["mode"]
            last = checkpoint
            got = 0
            if not checkpoint.get("end"):
                async for page in self._strategy_pages(source, checkpoint, held, hint):
                    got += len(page.posts)
                    last = page.checkpoint or last
                    yield page
                if not last.get("end"):
                    # The strategy ended without saying so (no more pages): its checkpoint says it now.
                    last = {**last, "end": True}
                    yield ArchivePage([], last)
            ladder = dict(last.get("ladder") or {})
            worked = {**(ladder.get("worked") or {}), mode: int((ladder.get("worked") or {}).get(mode) or 0) + got}
            ladder["worked"] = worked
            await self._learn(ladder.get("platform"), mode, got)
            estimate = ladder.get("estimate")
            if isinstance(estimate, int) and estimate > 0 and len(held) >= archive_ladder.COVERED_SHARE * estimate:
                return
            order = list(ladder.get("order") or [])
            if not order:
                return
            following = order.pop(0)
            ladder["order"] = order
            checkpoint = self._start(following, (ladder.get("starts") or {}).get(following) or {}, ladder,
                                     pages_fetched=int(last.get("pages_fetched") or 0),
                                     collected=int(last.get("collected_posts") or 0), skipped=last.get("skipped"))
            hint = None

    async def _learn(self, platform: Optional[str], strategy: str, posts: int) -> None:
        """A strategy that gave posts is counted for its platform (system_settings archive_learned)."""
        if self.learned is None or not platform or posts <= 0:
            return
        try:
            await asyncio.to_thread(self.learned.add, platform, strategy, posts)
        except Exception as exc:  # noqa: BLE001 - learning never stops an archive
            logger.warning("Archive: could not record what worked for %s: %s", platform, exc)

    @staticmethod
    def _start(strategy: str, state: Dict[str, Any], ladder: Dict[str, Any], *, pages_fetched: int, collected: int,
               skipped: Optional[Dict[str, int]] = None) -> dict:
        """A strategy's first checkpoint: where its probe left off."""
        base = {"pages_fetched": pages_fetched, "collected_posts": collected, "skipped": dict(skipped or {}),
                "ladder": ladder}
        state = _public(state)
        if strategy == archive_ladder.SITEMAP:
            return {"mode": SITEMAP_MODE, "site": state.get("site", ""), "prefix": state.get("prefix", "/"),
                    "next_index": 0, "total_candidates": 0, **base}
        if strategy == archive_ladder.FEED_PAGES:
            return {"mode": FEED_PAGES_MODE, "next": state.get("next"), "page": int(state.get("page") or 2), **base}
        if strategy == archive_ladder.API:
            return {"mode": API_MODE, **{k: v for k, v in state.items()}, **base}
        if strategy == archive_ladder.LISTING:
            return {"mode": LISTING_MODE, "listing": state.get("listing"), "listing_page": 1, "urls": [],
                    "next_index": 0, **base}
        return {"mode": WEB_ARCHIVE_MODE, "urls": None, "next_index": 0, **base}

    def _strategy_pages(self, source: Source, checkpoint: dict, held: set, listed: Optional[list] = None):
        mode = checkpoint["mode"]
        if mode == SITEMAP_MODE:
            return self._sitemap_pages(source, checkpoint, listed, held, UNBOUNDED)
        if mode == FEED_PAGES_MODE:
            return self._feed_pages(source, checkpoint, held)
        if mode == API_MODE:
            return self._api_pages(source, checkpoint, held)
        if mode == LISTING_MODE:
            return self._listing_pages(source, checkpoint, held)
        return self._web_archive_pages(source, checkpoint, held)

    @staticmethod
    def _next(checkpoint: dict, **changes: Any) -> dict:
        return {**checkpoint, **changes}

    # ------------------------------------------------------------------ the strategies' pages

    async def _sitemap_pages(self, source: Source, checkpoint: dict, listed: Optional[list], held: set, target: int):
        """The sitemap's posts one page each from next_index (issue 0108); a stored one is not read again."""
        site, prefix = str(checkpoint.get("site") or ""), str(checkpoint.get("prefix") or "/")
        if listed is None:
            listed = (await self._sitemap_posts([], site=site or None, prefix=prefix if site else None))[2]
        collected, pages_fetched = resume_counts(checkpoint)
        skipped = skipped_counts(checkpoint)
        start = int(checkpoint.get("next_index") or 0)
        stored = (await asyncio.to_thread(self.stored_urls, [loc for loc, _ in listed[start:]])
                  if self.stored_urls and listed[start:] else set())
        index = start
        while index < len(listed) and collected < target:
            loc, lastmod = listed[index]
            index += 1
            key = normalize_url(loc)
            if loc in stored or key in held:
                skipped[SKIP_STORED] += 1
                held.add(key)
                continue
            held.add(key)
            post = await self._sitemap_post(source, loc, lastmod)
            if not isinstance(post, dict):
                skipped[SKIP_UNREADABLE if post == UNREADABLE else SKIP_NO_POST] += 1
                post = None
            collected += 1 if post else 0
            pages_fetched += 1
            page_checkpoint = {**self._checkpoint(site, prefix, index, pages_fetched, collected, len(listed), skipped),
                               **({"ladder": checkpoint["ladder"], "end": index >= len(listed)}
                                  if "ladder" in checkpoint else {})}
            yield ArchivePage([post] if post else [], page_checkpoint)

    async def _addressed(self, source: Source, checkpoint: dict, urls: List[Any], held: set):
        """Pages read one each from an address list (listing, Web Archive): the checkpoint's next_index on."""
        collected, pages_fetched = resume_counts(checkpoint)
        skipped = skipped_counts(checkpoint)
        index = int(checkpoint.get("next_index") or 0)
        rest = [entry[0] if isinstance(entry, (list, tuple)) else entry for entry in urls[index:]]
        stored = await asyncio.to_thread(self.stored_urls, rest) if self.stored_urls and rest else set()
        while index < len(urls):
            entry = urls[index]
            loc, stamp = (entry[0], entry[1]) if isinstance(entry, (list, tuple)) else (entry, None)
            index += 1
            key = normalize_url(loc)
            if loc in stored or key in held:
                skipped[SKIP_STORED] += 1
                held.add(key)
                continue
            held.add(key)
            post = await self._sitemap_post(source, loc, None, archived=stamp)
            if not isinstance(post, dict):
                skipped[SKIP_UNREADABLE if post == UNREADABLE else SKIP_NO_POST] += 1
                post = None
            if post is not None:
                post.setdefault("metadata", {})["archive_strategy"] = (
                    archive_ladder.WEB_ARCHIVE if checkpoint["mode"] == WEB_ARCHIVE_MODE else archive_ladder.LISTING)
            collected += 1 if post else 0
            pages_fetched += 1
            yield ArchivePage([post] if post else [], self._next(
                checkpoint, next_index=index, pages_fetched=pages_fetched, collected_posts=collected,
                skipped=dict(skipped), end=index >= len(urls)))

    async def _feed_pages(self, source: Source, checkpoint: dict, held: set):
        """The feed's next pages (RFC 5005's rel=next / prev-archive, the platform's page parameter), each one
        archive page of the feed's posts, until a page holds nothing new."""
        url = str(source["handle_or_url"])
        platform = archive_ladder.platform_named((checkpoint.get("ladder") or {}).get("platform"))
        collected, pages_fetched = resume_counts(checkpoint)
        page_url, number = checkpoint.get("next"), int(checkpoint.get("page") or 2)
        while page_url:
            try:
                text, _ = await self.http.get_text(page_url)
                feed = parsing.parse_feed_posts(text, url)
            except HttpError as exc:
                if exc.limiting:
                    raise
                feed, text = [], ""
            except Exception:  # noqa: BLE001 - a page that is no feed ends the paging
                feed, text = [], ""
            new = [post for post in feed if isinstance(post.get("url"), str) and normalize_url(post["url"]) not in held]
            held.update(_addresses(feed))
            following = None
            if new and number < archive_ladder.MAX_FEED_PAGES:
                following = (archive_ladder.feed_next(text, page_url)
                             or archive_ladder.feed_paged_url(url, platform, number + 1))
            posts = await self._maybe_expand(source, new)
            for post in posts:
                post[BACKLOG_KEY] = True
                post.setdefault("metadata", {})["archive_strategy"] = archive_ladder.FEED_PAGES
            collected += len(posts)
            pages_fetched += 1
            yield ArchivePage(posts, self._next(checkpoint, next=following, page=number + 1, pages_fetched=pages_fetched,
                                                collected_posts=collected, end=following is None))
            page_url, number = following, number + 1

    async def _api_pages(self, source: Source, checkpoint: dict, held: set):
        """The platform's archive API, a page at a time: WordPress REST, Blogger's JSON feed, the newsletter
        platform's archive (its own kind's paging, on the publication's domain)."""
        api = checkpoint.get("api")
        url = str(source["handle_or_url"])
        collected, pages_fetched = resume_counts(checkpoint)
        if api == "newsletter":
            async for page in self._newsletter_pages(source, checkpoint, held):
                yield page
            return
        while True:
            if api == "wordpress":
                number = int(checkpoint.get("page") or 1)
                request = archive_ladder.Ladder.wordpress_url(str(checkpoint.get("root")), number)
            else:
                number = int(checkpoint.get("start") or 1)
                request = archive_ladder.Ladder.blogger_url(parsing.origin_from_source(url, ""), number)
            try:
                text, headers = await self.http.get_text(request)
                data = json.loads(text)
            except HttpError as exc:
                if exc.limiting:
                    raise
                data, headers = None, {}      # WordPress answers a page past the last with HTTP 400
            except ValueError:
                data, headers = None, {}
            if api == "wordpress":
                items = data if isinstance(data, list) else []
                shaped = [archive_ladder.wordpress_post(item, url) for item in items if isinstance(item, dict)]
                pages = archive_ladder._int((headers or {}).get("x-wp-totalpages"))
                end = len(items) < archive_ladder.WP_PER_PAGE or (pages is not None and number >= pages)
                moved = {"page": number + 1}
            else:
                feed = (data or {}).get("feed") if isinstance(data, dict) else None
                items = (feed or {}).get("entry") or [] if isinstance(feed, dict) else []
                shaped = [archive_ladder.blogger_post(entry, url) for entry in items]
                end = len(items) < archive_ladder.BLOGGER_PER_PAGE
                moved = {"start": number + len(items)}
            new = [post for post in shaped if post and normalize_url(post["url"]) not in held]
            held.update(_addresses([post for post in shaped if post]))
            posts = await self._maybe_expand(source, new)
            collected += len(posts)
            pages_fetched += 1
            checkpoint = self._next(checkpoint, **moved, pages_fetched=pages_fetched, collected_posts=collected, end=end)
            yield ArchivePage(posts, checkpoint)
            if end:
                return

    async def _newsletter_pages(self, source: Source, checkpoint: dict, held: set):
        from insight_core.ingestion.kinds.substack import SubstackKind

        url = str(source["handle_or_url"])
        site = parsing.origin_from_source(url, "")
        # Never the owner's cookie: a publication on its own domain is read as anyone reads it.
        newsletter = SubstackKind(self.http, sid="", stored_urls=self.stored_urls)
        collected, pages_fetched = resume_counts(checkpoint)
        inner = checkpoint.get("inner") if isinstance(checkpoint.get("inner"), dict) else None
        rate = newsletter.profile.rate_limit()
        async for page in newsletter.archive_pages({**source, "handle_or_url": f"{site}/feed"}, UNBOUNDED, inner, rate):
            posts = []
            for post in page.posts:
                key = normalize_url(post.get("url"))
                if key in held:
                    continue
                held.add(key)
                post["source"] = url
                post[BACKLOG_KEY] = True
                post.setdefault("metadata", {})["archive_strategy"] = archive_ladder.API
                posts.append(post)
            collected += len(posts)
            pages_fetched += 1
            yield ArchivePage(posts, self._next(checkpoint, inner=page.checkpoint, pages_fetched=pages_fetched,
                                                collected_posts=collected))

    async def _listing_pages(self, source: Source, checkpoint: dict, held: set):
        """The blog's listing pages, one archive page each (their post links kept in the checkpoint, read by the
        shape the feed's items have), following rel=next or /page/N/; then each listed post one page each."""
        ladder = checkpoint.get("ladder") or {}
        shape = archive_ladder.post_shape(ladder.get("items") or [])
        urls: List[str] = list(checkpoint.get("urls") or [])
        walked = {normalize_url(url) for url in urls}
        listing, number = checkpoint.get("listing"), int(checkpoint.get("listing_page") or 1)
        pages_fetched = int(checkpoint.get("pages_fetched") or 0)
        while listing and shape is not None:
            try:
                page, _ = await self.http.get_text(listing)
            except HttpError as exc:
                if exc.limiting:
                    raise
                page = ""
            listed = [url for url in archive_ladder.page_links(page, listing)
                      if url.rstrip("/") != listing.rstrip("/") and shape.matches(url)]
            fresh = [url for url in dict.fromkeys(listed) if normalize_url(url) not in walked]
            walked.update(normalize_url(url) for url in fresh)
            urls.extend(url for url in fresh if normalize_url(url) not in held)
            urls = urls[:archive_ladder.MAX_LISTED]
            following = (archive_ladder.next_page(page, listing, number)
                         if fresh and number < archive_ladder.MAX_LISTING_PAGES and len(urls) < archive_ladder.MAX_LISTED
                         else None)
            pages_fetched += 1
            checkpoint = self._next(checkpoint, listing=following, listing_page=number + 1, urls=urls,
                                    pages_fetched=pages_fetched, end=False)
            yield ArchivePage([], checkpoint)
            listing, number = following, number + 1
        checkpoint = self._next(checkpoint, listing=None, end=not urls)
        if not urls:
            yield ArchivePage([], checkpoint)
            return
        async for page in self._addressed(source, checkpoint, urls, held):
            yield page

    async def _web_archive_pages(self, source: Source, checkpoint: dict, held: set):
        """The Web Archive's address index for the posts' section (opt-in, issue 0143): its list read once (one
        archive page), then each address read from the live site, or its archived copy when the live one is gone."""
        urls = checkpoint.get("urls")
        if urls is None:
            ladder = checkpoint.get("ladder") or {}
            probe = archive_ladder.Ladder(self, source, [{"url": url} for url in ladder.get("items") or []], "")
            try:
                urls = [[url, stamp] for url, stamp in await probe.cdx_entries()]
            except HttpError as exc:
                if exc.limiting:
                    raise
                urls = []
            except ValueError:
                urls = []
            urls = [entry for entry in urls if normalize_url(entry[0]) not in held][:archive_ladder.MAX_LISTED]
            checkpoint = self._next(checkpoint, urls=urls, pages_fetched=int(checkpoint.get("pages_fetched") or 0) + 1,
                                    end=not urls)
            yield ArchivePage([], checkpoint)
        if urls:
            async for page in self._addressed(source, checkpoint, urls, held):
                yield page

    @staticmethod
    def _checkpoint(site: str, prefix: str, next_index: int, pages_fetched: int, collected: int, total: int,
                    skipped: Optional[Dict[str, int]] = None) -> dict:
        return {"mode": SITEMAP_MODE, "site": site, "prefix": prefix, "next_index": next_index,
                "pages_fetched": pages_fetched, "collected_posts": collected, "total_candidates": total,
                "skipped": dict(skipped or {})}

    async def _sitemap_read(self, posts: Sequence[Dict[str, Any]], *, http: Any = None
                            ) -> Tuple[str, str, List[Tuple[str, Optional[datetime]]], int]:
        """(the site, the feed's section, the sitemap's posts under it, how many entries the sitemap has):
        the feed's items' site and the path they share ("/posts/" for /posts/2021/03/a and /posts/2020/12/b;
        "/" for /a/ and /b/), and the sitemap's addresses there, newest lastmod first, once each (issue 0108).
        No entries: no sitemap could be read."""
        from insight_core.ingestion.kinds.page_watch import ARCHIVE_SITEMAPS, sitemap_entries   # page_watch imports this module

        links = [p["url"] for p in posts if isinstance(p.get("url"), str) and p["url"].startswith("http")]
        if not links:
            return "", "/", [], 0
        site, prefix = parsing.origin_from_source(links[0], ""), feed_section(links)
        try:
            entries = await sitemap_entries(http or self.http, site + "/", prefix, posts_only=True, max_files=ARCHIVE_SITEMAPS)
        except Exception as exc:  # noqa: BLE001 - no sitemap: the feed is the archive
            logger.debug("Sitemap of %s not read: %s", site, exc)
            return site, prefix, [], 0
        return site, prefix, _under_section(entries, site, prefix), len(entries)

    async def _sitemap_posts(self, posts: Sequence[Dict[str, Any]], *, site: Optional[str] = None,
                             prefix: Optional[str] = None) -> Tuple[str, str, List[Tuple[str, Optional[datetime]]]]:
        """(the site, the feed's section, the sitemap's posts under it), as _sitemap_read; no posts when the
        sitemap lists no more of them than the feed holds, or cannot be read (issue 0108)."""
        from insight_core.ingestion.kinds.page_watch import ARCHIVE_SITEMAPS, sitemap_entries   # page_watch imports this module

        links = [p["url"] for p in posts if isinstance(p.get("url"), str) and p["url"].startswith("http")]
        if site is None or prefix is None:
            if not links:
                return "", "/", []
            site, prefix, listed, _ = await self._sitemap_read(posts)
        else:
            try:
                entries = await sitemap_entries(self.http, site + "/", prefix, posts_only=True, max_files=ARCHIVE_SITEMAPS)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Sitemap of %s not read: %s", site, exc)
                return site, prefix, []
            listed = _under_section(entries, site, prefix)
        if len(listed) <= len(_addresses(links)) and links:
            return site, prefix, []
        return site, prefix, listed


    async def _sitemap_post(self, source: Source, url: str, lastmod: Optional[datetime], *,
                            archived: Optional[str] = None) -> Any:
        """One older post from the sitemap (or a listing, or the Web Archive's index), read from its page as
        page watch reads one; None when the page is no post, UNREADABLE when it cannot be read (a host limiting
        us stops the archive: it resumes). `archived`: the Web Archive's capture of it, read when the live page
        is gone (404 / 410)."""
        from insight_core.ingestion.kinds.page_watch import article_post, page_date
        from insight_core.utils.originals_rules import address_day as address_date

        try:
            page, _ = await self.http.get_text(url)
        except HttpError as exc:
            if exc.limiting:
                raise
            if archived and exc.status in (404, 410):
                try:
                    page, _ = await self.http.get_text(f"{archive_ladder.WAYBACK_URL}/{archived}id_/{url}")
                except (HttpError, ValueError) as again:
                    if isinstance(again, HttpError) and again.limiting:
                        raise
                    return UNREADABLE
            else:
                logger.info("Archive: %s could not be read (%s)", url, exc)
                return UNREADABLE
        except ValueError as exc:
            logger.info("Archive: %s could not be read (%s)", url, exc)
            return UNREADABLE
        # v10.13.5: an archived page that states no date in its markup is dated by its address (/2008/Jul/7/)
        # before the sitemap's lastmod (a site's lastmod is often its last rebuild, not the post's day)
        date = page_date(page) or address_date(url)
        if date is None and parsing.meta_content(page, "og:type").lower() != "article":
            return None
        post = article_post(page, str(source["handle_or_url"]), url, date or lastmod, adapter=self.name)
        if post is not None:
            post[BACKLOG_KEY] = True   # from the sitemap: never "new to you" (issue 0039)
            if date is None and lastmod is None:
                # v10.13.6: an older page with no date anywhere stays undated (article_post dates a page "now", right
                # for a page watch's new page, wrong for an archive's 2008 page): the saver sorts it before the
                # source's oldest post (repo_posts' undated backlog), never at today's top
                post["date"] = None
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
            expanded[post["url"]] = await self._read(post, str(source.get("handle_or_url") or ""))
        return [expanded.get(post.get("url"), post) for post in posts]

    async def _read(self, post: Dict[str, Any], site: str) -> Dict[str, Any]:
        """The post read from its page, or its summary kept, with the read's outcome (issue 0140): why
        the page was not taken (nothing longer, not the same article, a script needed, the error). A
        failed request (an HttpError: an HTTP error, a timeout, a dropped connection) is counted as a
        try, and so is a page with nothing longer for a post with no body at all (issue 0108)."""
        now = self.clock()
        try:
            read = await full_text.read_page(self.http, post["url"], full_text.body_text(post),
                                             title=post.get("title"), site=site)
        except HttpError as exc:
            logger.info("Full-text read failed for %s: %s", post["url"], str(exc)[:200])
            return full_text.with_outcome(full_text.with_page_try(post, now, failed=True), full_text.error_outcome(exc), now)
        except Exception as exc:  # noqa: BLE001 - the summary is kept
            logger.warning("Full-text read of %s went wrong (%s): %s", post["url"], type(exc).__name__, str(exc)[:200])
            return full_text.with_outcome(post, full_text.error_outcome(exc), now)
        if read.article is None:
            kept = full_text.with_page_try(post, now, failed=True) if full_text.empty_read_failed(post) else post
            return full_text.with_outcome(kept, read.outcome, now)
        return full_text.with_outcome(full_text.with_full_text(post, *read.article), read.outcome, now)

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
            now = self.clock()
            try:
                read = await full_text.read_page(self.http, stored["url"], full_text.body_text(stored),
                                                 title=stored.get("title"), site=str(source.get("handle_or_url") or ""))
            except HttpError as exc:
                read_again[stored["url"]] = full_text.with_outcome(
                    full_text.with_page_try(stored, now, failed=True), full_text.error_outcome(exc), now)
                if exc.limiting:
                    logger.info("%s is limiting us (%s): %s teasers left for the next fetch",
                                stored["url"], str(exc)[:200], len(due) - index - 1)
                    break
                continue
            except Exception as exc:  # noqa: BLE001 - not a failed request: no more tries
                logger.warning("Full-text read again of %s went wrong (%s): %s", stored["url"], type(exc).__name__,
                               str(exc)[:200])
                read = full_text.PageRead(full_text.error_outcome(exc))
            article = read.article
            # Nothing longer ends it, unless the post has no body at all (issue 0108).
            counted = full_text.with_outcome(full_text.with_page_try(
                stored, now, failed=article is None and full_text.empty_read_failed(stored)), read.outcome, now)
            read_again[stored["url"]] = full_text.with_full_text(counted, *article) if article else counted
        if read_again:
            logger.info("%s: %s teasers read again, %s in full", source.get("handle_or_url"), len(read_again),
                        sum(1 for post in read_again.values() if post["metadata"].get(full_text.FULL_TEXT_FLAG)))
        # A teaser still in the feed is the read-again post, once.
        return [post for post in posts if post.get("url") not in read_again] + list(read_again.values())


def _public(state: Dict[str, Any]) -> Dict[str, Any]:
    """A probe's state without what is kept in memory only (its "_" keys): what a checkpoint stores."""
    return {key: value for key, value in (state or {}).items() if not key.startswith("_")}


def _under_section(entries: Sequence[Tuple[str, Optional[str]]], site: str, prefix: str
                   ) -> List[Tuple[str, Optional[datetime]]]:
    """The sitemap's addresses on the site under the feed's section, newest lastmod first, once each."""
    publication = publication_of(host_of(site))
    found: Dict[str, Tuple[str, Optional[datetime]]] = {}
    for loc, lastmod in entries:
        path = urllib.parse.urlparse(loc).path or "/"
        key = normalize_url(loc)
        if (key and publication_of(host_of(loc)) == publication and path.startswith(prefix)
                and path.rstrip("/") + "/" != prefix):
            found.setdefault(key, (loc, parsing.parse_datetime_value(lastmod)))
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(found.values(), key=lambda entry: entry[1] or epoch, reverse=True)


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
