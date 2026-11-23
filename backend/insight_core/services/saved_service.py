"""Save any page: one web page kept as an unread post of the built-in Saved source (`save`), plus the
collected originals of News stories (`collect`, `collect_for_source`, `collect_quote`).

A page already stored (its URL or its redirect, normalised) is "already" and goes to Later. A new save goes to
Later, is dated by the page (else by the first stored post linking it, else the save time) and sorts at the save
time (surfaced_at). An unreadable page is still saved with its title and address, and the answer says why. A page
of a followed source is stored under that source; with `fetch`, the save first starts that source's fetch
("fetching") and the caller saves again with after_fetch. Only a click fetches: nothing here runs by itself.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

from insight_core.db import database as db
from insight_core.db.repo_linked import page_source
from insight_core.db.repo_posts import PostsRepository
from insight_core.ingestion.feed_finder import FeedFinding, find_feeds
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import parsing, saved
from insight_core.ingestion.kinds.page_watch import LISTING_MAX_BYTES, article_post, page_date, page_title
from insight_core.services.reader_service import ReaderService
from insight_core.utils.originals_rules import address_hint, strip_access_tokens
from insight_core.utils.post_fields import COLLECTED_KEY, SAVED_KEY, STORY_ONLY_KEY
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.saved")

ADAPTER = "saved"
# A source tried this recently is not fetched again for a save (0114).
REFETCH_WITHIN = timedelta(minutes=15)
# A fetch job still "running" after this long is no fetch to wait for (a process that died).
RUNNING_WITHIN = timedelta(hours=1)
FETCH_JOB = "ingestion_run"
_NAME = "COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url)"
# Since when a linking post p shows its links (first_linked): its date, or its page's later change
# (metadata.modified) when that is more than a day after publication (a same-day edit is the same piece; 0248).
# Migration 0156 repairs with the same expression.
LINKED_SINCE = ("(CASE WHEN p.metadata->>'modified' ~ '^\\d{4}-\\d\\d-\\d\\dT'"
                " AND (p.published_at IS NULL OR (p.metadata->>'modified')::timestamptz > p.published_at + interval '1 day')"
                " THEN (p.metadata->>'modified')::timestamptz ELSE p.published_at END)")

# The API's fetch of one source for a save: its job id, or None when none started.
StartFetch = Callable[[str], Awaitable[Optional[str]]]


def address_key(url: str) -> str:
    """An address compared without its scheme, www, trailing slash or tracking query."""
    return (normalize_url(url) or url.strip()).split("://", 1)[-1]


def _reason(exc: Exception) -> str:
    """Why a page could not be read, in a few words: the status, never the site's answer."""
    if isinstance(exc, HttpError):
        return f"HTTP {exc.status}" if exc.status else "no answer in time" if exc.timed_out else "no connection"
    return "no connection"


def _web_page(address: str) -> bool:
    """An http(s) address with a host and a valid port ("javascript:x" typed bare is neither)."""
    parsed = urllib.parse.urlparse(address)
    try:
        parsed.port
    except ValueError:
        return False
    return parsed.scheme.lower() in ("http", "https") and bool(parsed.hostname)


def dated_by_page(post: Dict[str, Any], saved_at: datetime) -> Tuple[Dict[str, Any], Optional[datetime]]:
    """(post, sorts_at): no date, or one after the save, becomes the save time (sorts_at None); an earlier
    date is kept and the post sorts at the save time."""
    stated = post.get("date")
    if not isinstance(stated, datetime) or stated >= saved_at:
        return {**post, "date": saved_at}, None
    return post, saved_at


class SavedService:
    def __init__(self, db_url: str, *, sources: Any, source_config_sync: Any, kinds: Any,
                 reader: ReaderService | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.db_url = db_url
        self.sources = sources
        self.source_config_sync = source_config_sync
        self.kinds = kinds
        self.posts = PostsRepository(db_url)
        self.reader = reader or ReaderService(db_url)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    async def save(self, http: KindHttp, url: str, title: Optional[str] = None, *,
                   fetch: Optional[StartFetch] = None, after_fetch: bool = False) -> Dict[str, Any]:
        address = parsing.web_address(url, "An address is needed to save a page")
        if not _web_page(address):
            raise ValueError("Only an http or https page can be saved")
        saved_at = self.clock()
        stored = await asyncio.to_thread(self.stored_post, [address])
        if stored:
            return await self._already(stored, saved_at)
        owner = await asyncio.to_thread(self.page_source, address)
        if owner and fetch is not None and not after_fetch:
            job_id = await self._fetch_first(owner["id"], saved_at, fetch)
            if job_id:
                return {"success": True, "status": "fetching", "job_id": job_id, "source": owner,
                        "title": (title or "").strip() or address}
        (post, reason), finding = await asyncio.gather(
            self.read(http, address, (title or "").strip()), find_feeds(http, self.kinds, address))
        stored = post["url"] != address and await asyncio.to_thread(self.stored_post, [post["url"]])
        if stored:
            return await self._already(stored, saved_at)
        if post.get("date") is None:   # no later than the first post linking it, so its story's window is its
            # links', never the save's (0113); none: the save time (dated_by_page)
            post = {**post, "date": await asyncio.to_thread(self.first_linked, [address, post["url"]], saved_at)}
        if owner:
            source_id = owner["id"]
            post = {**post, "metadata": {**post.get("metadata", {}), SAVED_KEY: saved_at.isoformat()}}
        else:
            source_id = await asyncio.to_thread(self.saved_source_id)
        post_id = await asyncio.to_thread(self._insert, source_id, *dated_by_page(post, saved_at))
        await asyncio.to_thread(self.reader.set_later, [post_id], True, saved_at)
        return {
            "success": True,
            "status": "saved",
            "post_id": post_id,
            "title": post["title"],
            "source_id": source_id,
            # a followed source's {id, name}, else null (Saved)
            "source": owner,
            "readable": reason is None,
            "reason": reason,
            "feed": await asyncio.to_thread(self.unfollowed_feed, finding),
        }

    # ------------------------------------------------------------------ collected originals

    async def collect(self, http: KindHttp, url: str, title: Optional[str] = None, *,
                      collected_as: Optional[str] = None) -> Dict[str, Any]:
        """A News story's original no followed source owns, read once (one request) and stored as a story_only
        Saved post (shown only in its story and post page), never in Later, without access tokens in its address.
        Returns "collected", "unreadable" (not stored), "already" or "followed". `collected_as`: "classic" or
        "work", kept in metadata."""
        address = strip_access_tokens(parsing.web_address(url, "An address is needed"))
        if not _web_page(address):
            raise ValueError("Only an http or https page can be collected")
        now = self.clock()
        stored = await asyncio.to_thread(self.stored_post, [address])
        if stored:
            return {"status": "already", **stored}
        if await asyncio.to_thread(self.page_source, address):
            return {"status": "followed"}
        post, reason = await self.read(http, address, (title or "").strip())
        if reason is not None:
            return {"status": "unreadable", "reason": reason, "requests": 1}
        landed = strip_access_tokens(post["url"])
        stored = landed != address and await asyncio.to_thread(self.stored_post, [landed])
        if stored:
            return {"status": "already", "requests": 1, **stored}
        post = {**post, "url": landed, "external_id": landed, "guid": landed,
                "metadata": {**post.get("metadata", {}), COLLECTED_KEY: now.isoformat(), STORY_ONLY_KEY: True,
                             **({"collected_as": collected_as} if collected_as else {})}}
        post["date"] = await self._older_date(post, address, landed, now)
        source_id = await asyncio.to_thread(self.saved_source_id)
        post_id = await asyncio.to_thread(self._insert, source_id, post)
        return {"status": "collected", "post_id": post_id, "title": post["title"], "requests": 1}

    async def collect_for_source(self, http: KindHttp, url: str, source_id: str) -> Dict[str, Any]:
        """A followed source's page its feed never carried, read once and stored as that source's post (not in
        Later, `metadata.missed_by_feed` the time), dated as `_older_date`. Stored already: "already"."""
        address = strip_access_tokens(parsing.web_address(url, "An address is needed"))
        if not _web_page(address):
            raise ValueError("Only an http or https page can be collected")
        now = self.clock()
        stored = await asyncio.to_thread(self.stored_post, [address])
        if stored:
            return {"status": "already", **stored}
        post, reason = await self.read(http, address, "")
        if reason is not None:
            return {"status": "unreadable", "reason": reason, "requests": 1}
        landed = strip_access_tokens(post["url"])
        stored = landed != address and await asyncio.to_thread(self.stored_post, [landed])
        if stored:
            return {"status": "already", "requests": 1, **stored}
        post = {**post, "url": landed, "external_id": landed, "guid": landed,
                "metadata": {**post.get("metadata", {}), "missed_by_feed": now.isoformat()}}
        post["date"] = await self._older_date(post, address, landed, now)
        post_id = await asyncio.to_thread(self._insert, source_id, post)
        return {"status": "collected", "post_id": post_id, "title": post["title"], "requests": 1}

    def collect_quote(self, url: str, words: str, *, title: Optional[str], at: datetime) -> Dict[str, Any]:
        """A tweet a member quotes, stored from the quote's words and time, as `collect` stores a page; no request."""
        address = normalize_url(url) or url
        stored = self.stored_post([address])
        if stored:
            return {"status": "already", **stored}
        text = (words or "").strip()
        post = {"platform": saved.PLATFORM, "source": saved.HANDLE, "url": address, "external_id": address,
                "guid": address, "title": (title or "").strip() or text[:120], "content": text,
                "content_html": None, "date": at, "media_urls": [], "categories": [],
                "metadata": {"adapter": ADAPTER, COLLECTED_KEY: self.clock().isoformat(), "from_quote": True,
                             STORY_ONLY_KEY: True}}
        post_id = self._insert(self.saved_source_id(), post)
        return {"status": "collected", "post_id": post_id, "title": post["title"], "requests": 0}

    async def _older_date(self, post: Dict[str, Any], address: str, landed: str, now: datetime) -> Optional[datetime]:
        """A collected page's date, never "now": the date it states, else its address's day or month, else the
        first stored post linking it, else None (undated: sorted before its source's oldest post)."""
        stated = post.get("date")
        if isinstance(stated, datetime) and stated < now:
            return stated
        return (address_hint(landed, now) or address_hint(address, now)
                or await asyncio.to_thread(self.first_linked, [address, landed], now))

    async def _fetch_first(self, source_id: str, now: datetime, fetch: StartFetch) -> Optional[str]:
        """The fetch job a save of this source's page waits for: one running, else one started now; None
        when the source was tried in the last REFETCH_WITHIN, is in backoff, or no job could start."""
        running, fetchable = await asyncio.to_thread(self.fetch_plan, source_id, now)
        if running or not fetchable:
            return running
        try:
            return await fetch(source_id) or await asyncio.to_thread(self.running_fetch, source_id, now)
        except Exception:  # noqa: BLE001 - no fetch: the page is saved as the source's at once
            logger.exception("Save a page: the fetch of source %s could not start", source_id)
            return None

    async def _already(self, stored: Dict[str, Any], saved_at: datetime) -> Dict[str, Any]:
        """A page already stored: to Later (keeping an earlier Later time), date untouched, no longer story_only."""
        await asyncio.to_thread(self.posts.drop_story_only, stored["post_id"])
        await asyncio.to_thread(self.reader.set_later, [stored["post_id"]], True, saved_at)
        return {"success": True, "status": "already", **stored}

    async def read(self, http: KindHttp, address: str, title: str) -> Tuple[Dict[str, Any], Optional[str]]:
        """(the post the page is, None) or, when it cannot be read as an article, (a post of its
        title and address, why)."""
        page, landed, reason = "", address, None
        try:
            body, landed = await http.get_start(address, LISTING_MAX_BYTES)
            page = body.decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - an unreadable page is still saved
            logger.info("Save a page: %s could not be read (%s)", address, str(exc)[:300])
            reason = _reason(exc)
        url = landed or address
        stated = page_date(page, url) if page else None
        post = article_post(page, saved.HANDLE, url, stated, adapter=ADAPTER, platform=saved.PLATFORM) if page else None
        if post is not None:
            # identity is the whole address: two sites' "/" are two posts
            return {**post, "external_id": url, "date": stated}, None
        named = page_title(page, url) if page else url
        image = parsing.normalize_media_url(parsing.meta_content(page, "og:image")) if page else None
        return {
            "platform": saved.PLATFORM,
            "source": saved.HANDLE,
            "url": url,
            "external_id": url,
            "guid": url,
            "title": named if named != url else (title or url),
            "content": "",
            "content_html": None,
            "date": None,
            "media_urls": [image] if image else [],
            "categories": [],
            "metadata": {"adapter": ADAPTER, "unreadable": True},
        }, reason or "no article on the page"

    # ------------------------------------------------------------------ the database

    def stored_post(self, urls: Iterable[str]) -> Optional[Dict[str, Any]]:
        """{post_id, title, source_id, source} of a post stored under one of these addresses, else None.
        source: {id, name} of a followed source's post, null for the Saved source's."""
        urls = list(urls)
        normalized = [n for n in map(normalize_url, urls) if n]
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            # normalized_url is not unique (0049): an exact url first, else the first seen
            cur.execute(f"SELECT p.id, p.title, s.id, s.platform, {_NAME} FROM posts p JOIN sources s ON s.id = p.source_id "
                        "WHERE p.url = ANY(%s) OR p.normalized_url = ANY(%s) "
                        "ORDER BY p.url = ANY(%s) DESC, p.fetched_at, p.created_at, p.id LIMIT 1",
                        (urls, normalized, urls))
            row = cur.fetchone()
        if not row:
            return None
        source = None if row[3] == saved.PLATFORM else {"id": str(row[2]), "name": row[4]}
        return {"post_id": str(row[0]), "title": row[1] or "", "source_id": str(row[2]), "source": source}

    def page_source(self, address: str) -> Optional[Dict[str, str]]:
        """{id, name} of the followed source whose post page this address is, else None."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            source_id = page_source(cur, address)
            if not source_id:
                return None
            cur.execute(f"SELECT {_NAME} FROM sources s WHERE s.id = %s::uuid", (source_id,))
            row = cur.fetchone()
        return {"id": source_id, "name": row[0]} if row else None

    def fetch_plan(self, source_id: str, now: datetime) -> Tuple[Optional[str], bool]:
        """(this source's running fetch job or None, whether a new fetch may start): not within REFETCH_WITHIN
        of its last attempt nor during its backoff, as the schedule would."""
        running = self.running_fetch(source_id, now)
        if running:
            return running, False
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT last_attempt_at, consecutive_failures, next_retry_at FROM source_fetch_state "
                        "WHERE source_id = %s::uuid", (source_id,))
            row = cur.fetchone()
        if row is None:
            return None, True
        last_attempt_at, failures, retry_at = row
        if last_attempt_at is not None and now - last_attempt_at < REFETCH_WITHIN:
            return None, False
        if (failures or 0) > 0 and retry_at is not None and now < retry_at:
            return None, False
        return None, True

    def running_fetch(self, source_id: str, now: datetime) -> Optional[str]:
        """The id of this source's fetch job running now (started in the last RUNNING_WITHIN), else None."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM job_runs WHERE job_type = %s AND source_id = %s::uuid AND status = 'running' "
                        "AND started_at > %s ORDER BY started_at DESC LIMIT 1", (FETCH_JOB, source_id, now - RUNNING_WITHIN))
            row = cur.fetchone()
        return str(row[0]) if row else None

    def first_linked(self, urls: List[str], saved_at: datetime) -> Optional[datetime]:
        """When the first dated post linking one of these addresses showed the link (LINKED_SINCE), never later
        than the save; None when no dated post links it."""
        normalized = sorted({n for n in map(normalize_url, urls) if n})
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute(f"SELECT min({LINKED_SINCE}) FROM post_links pl JOIN posts p ON p.id = pl.post_id "
                        "WHERE pl.target_url = ANY(%s)", (normalized,))
            (first,) = cur.fetchone()
        return min(first, saved_at) if first is not None else None

    def saved_source_id(self) -> str:
        """The Saved source's id, created (and written to sources.json) the first time."""
        found = self._find_saved_source()
        if found:
            return found
        try:
            created = self.sources.add_source(saved.PLATFORM, saved.HANDLE)["source_id"]
        except ValueError:  # another save created it meanwhile
            created = self._find_saved_source()
            if not created:
                raise
            return created
        try:
            self.source_config_sync.sync_db_to_json()
        except Exception:  # noqa: BLE001 - the save stands; the log says sources.json is behind
            logger.exception("Could not export sources.json after creating the Saved source")
        return str(created)

    def _find_saved_source(self) -> Optional[str]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM sources WHERE platform = %s AND handle_or_url = %s",
                        (saved.PLATFORM, saved.HANDLE))
            row = cur.fetchone()
        return str(row[0]) if row else None

    def _insert(self, source_id: str, post: Dict[str, Any], sorts_at: Optional[datetime] = None) -> str:
        """The new post's id; sorts_at, when given, is its surfaced_at."""
        with db.transaction(self.db_url) as cur:
            post_id, inserted = self.posts.upsert_post(cur, post, source_id)
            if sorts_at is not None:
                cur.execute("UPDATE posts SET surfaced_at = %s WHERE id = %s::uuid", (sorts_at, post_id))
            elif inserted and not isinstance(post.get("date"), datetime):
                # an undated older page sorts before its source's oldest post, as an archive's does
                PostsRepository.place_undated_backlog(cur, [str(post_id)])
        return str(post_id)

    def unfollowed_feed(self, finding: FeedFinding) -> Optional[Dict[str, str]]:
        """The first feed the finder found that is not a source yet, else None."""
        if finding.status not in ("feed", "found") or not finding.feeds:
            return None
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT handle_or_url FROM sources")
            followed = {address_key(str(row[0])) for row in cur.fetchall()}
        feed = next((feed for feed in finding.feeds if address_key(feed.url) not in followed), None)
        return {"url": feed.url, "title": feed.title} if feed else None


__all__ = ["REFETCH_WITHIN", "SavedService", "address_key"]
