"""Save any page (issue 0031): one web page, kept as an unread post of the built-in Saved source.

    result = await services().saved.save(http, "https://example.com/an/article", title="An article")
    result["status"]   # "saved" | "already"

A page already stored (its URL, or the one it redirects to, normalised) is not stored again:
"already", with that post.

Every save puts the post in Later at the save time (issue 0022, owner's decision), through
ReaderService.set_later, and a new saved post is dated by that time (its published_at, which
the feed sorts by), so it tops the feed and sorts by when it was saved, not by the article's own
date (kept as metadata.article_published_at). A page already stored keeps its date. Otherwise the page is read as page watch reads an article
(page_watch.article_post: the full-text reader, title, date, images). A page that cannot be
read as an article (built with JavaScript, blocked, an error) is still saved, with its title
(the page's, else the one the bookmarklet sent) and its address, and the answer says why
(readable false, reason). The Saved source is created by the first save and written to
sources.json at once: a source missing from that file is deleted at the next start.

Meanwhile the feed finder looks at the page: a feed that is not a source yet comes back as
feed {url, title}, so the save page can offer to follow it.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, Optional, Tuple

from insight_core.db import database as db
from insight_core.db.repo_posts import PostsRepository
from insight_core.ingestion.feed_finder import FeedFinding, find_feeds
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import parsing, saved
from insight_core.ingestion.kinds.page_watch import LISTING_MAX_BYTES, article_post, page_date, page_title
from insight_core.services.reader_service import ReaderService
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.saved")

ADAPTER = "saved"


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


def dated_by_save(post: Dict[str, Any], saved_at: datetime) -> Dict[str, Any]:
    """The post dated by when it was saved; the page's own date stays in its metadata."""
    metadata = dict(post.get("metadata") or {})
    if not metadata.get("unreadable") and isinstance(post.get("date"), datetime):
        metadata["article_published_at"] = post["date"].isoformat()
    return {**post, "date": saved_at, "metadata": metadata}


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

    async def save(self, http: KindHttp, url: str, title: Optional[str] = None) -> Dict[str, Any]:
        address = parsing.web_address(url, "An address is needed to save a page")
        if not _web_page(address):
            raise ValueError("Only an http or https page can be saved")
        saved_at = self.clock()
        stored = await asyncio.to_thread(self.stored_post, [address])
        if stored:
            return await self._already(stored, saved_at)
        (post, reason), finding = await asyncio.gather(
            self.read(http, address, (title or "").strip()), find_feeds(http, self.kinds, address))
        stored = post["url"] != address and await asyncio.to_thread(self.stored_post, [post["url"]])
        if stored:
            return await self._already(stored, saved_at)
        source_id = await asyncio.to_thread(self.saved_source_id)
        post_id = await asyncio.to_thread(self._insert, source_id, dated_by_save(post, saved_at))
        await asyncio.to_thread(self.reader.set_later, [post_id], True, saved_at)
        return {
            "success": True,
            "status": "saved",
            "post_id": post_id,
            "title": post["title"],
            "source_id": source_id,
            "readable": reason is None,
            "reason": reason,
            "feed": await asyncio.to_thread(self.unfollowed_feed, finding),
        }

    async def _already(self, stored: Dict[str, Any], saved_at: datetime) -> Dict[str, Any]:
        """A page already in INSIGHT: that post goes to Later (a post already there keeps its
        time), its date untouched."""
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
        post = article_post(page, saved.HANDLE, url, page_date(page), adapter=ADAPTER, platform=saved.PLATFORM) if page else None
        if post is not None:
            # A saved page's identity is its whole address: two sites' "/" are two posts.
            return {**post, "external_id": url}, None
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
            "date": datetime.now(timezone.utc),
            "media_urls": [image] if image else [],
            "categories": [],
            "metadata": {"adapter": ADAPTER, "unreadable": True},
        }, reason or "no article on the page"

    # ------------------------------------------------------------------ the database

    def stored_post(self, urls: Iterable[str]) -> Optional[Dict[str, Any]]:
        """{post_id, title} of a post stored under one of these addresses, else None."""
        urls = list(urls)
        normalized = [n for n in map(normalize_url, urls) if n]
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT id, title FROM posts WHERE url = ANY(%s) OR normalized_url = ANY(%s) LIMIT 1",
                        (urls, normalized))
            row = cur.fetchone()
        return {"post_id": str(row[0]), "title": row[1] or ""} if row else None

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

    def _insert(self, source_id: str, post: Dict[str, Any]) -> str:
        with db.transaction(self.db_url) as cur:
            post_id, _ = self.posts.upsert_post(cur, post, source_id)
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


__all__ = ["SavedService", "address_key"]
