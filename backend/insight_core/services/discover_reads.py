"""What Discover reads of the web, for its first page only (issue 0080: Discover tested nothing, and
75% of its lines had no title but one made from the address).

For each suggestion on the first page (StoriesService.discover, FIRST_PAGE), at most once in CHECK_DAYS:
- **the follow test**: the path every source add takes (where_linked.follow: the feed finder, then page
  watching), labelled "feed" (Feed found), "page" (Page watching: a page whose articles it reads),
  "blocked" (Blocks readers: every request it made was refused with 401 or 403) or "headlines"
  (Headlines only: anything else, a paywall or no feed and a page it can't read);
- **the titles** of its articles that have none (no stored post, no link words that read as a title):
  the page's own title, as page watching reads one (page_watch.page_title), from the start of the page.
  Tweets are never read: their line names the account.
Each answer is stored with its date (system_settings `discover_reads`, DiscoverRepository.reads), a failure
too, so nothing is asked again within CHECK_DAYS. Requests go one at a time per host, spaced by the
ingestion's per-host limiter (gates.HostLimiter), FAN_OUT hosts at once, with the Add source dialog's client.
Off with INSIGHT_DISCOVER_READS=0 (a machine that must not fetch).
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from insight_core.db import database as db
from insight_core.db.repo_discover import DiscoverRepository
from insight_core.ingestion import where_linked
from insight_core.ingestion.gates import HostLimiter
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import page_watch
from insight_core.utils.addresses import host_of, is_tweet, publication_of
from insight_core.utils.discover_rules import CHECK_DAYS, FIRST_PAGE

logger = logging.getLogger(__name__)

PAGE_BYTES = 512 * 1024      # the start of a page read for its title (its <head>)
FAN_OUT = 4                  # hosts read at once
TITLE_CHARS = 300
BLOCKED = (401, 403)
LABELS = ("feed", "page", "headlines", "blocked")
_ADDRESS = re.compile(r"^\s*(?:https?://\S+|[\w-]+(?:\.[\w-]+)+/\S*)\s*$")


def enabled() -> bool:
    return os.getenv("INSIGHT_DISCOVER_READS", "1") != "0"


class Polite:
    """An http client whose requests' refusals are recorded; with a limiter, one at a time per host
    (HostLimiter). A follow test holds its host's slot for the whole test instead: the finder's own
    requests run FAN_OUT at once, each within its timeout, as when a source is added."""

    def __init__(self, http: Any, limiter: Optional[HostLimiter] = None) -> None:
        self.http = http
        self.limiter = limiter
        self.answered = 0
        self.refused: List[Optional[int]] = []

    async def _call(self, name: str, url: str, *args: Any, **kwargs: Any) -> Any:
        if self.limiter is None:
            return await self._request(name, url, *args, **kwargs)
        async with self.limiter.slot(slot(url)):
            return await self._request(name, url, *args, **kwargs)

    async def _request(self, name: str, url: str, *args: Any, **kwargs: Any) -> Any:
        try:
            got = await getattr(self.http, name)(url, *args, **kwargs)
        except HttpError as exc:
            self.refused.append(exc.status)
            raise
        self.answered += 1
        return got

    async def get_start(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return await self._call("get_start", url, *args, **kwargs)

    async def get_text(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return await self._call("get_text", url, *args, **kwargs)

    async def get_conditional(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return await self._call("get_conditional", url, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.http, name)


def label(found: Dict[str, Any], polite: Polite) -> str:
    """The follow test's label of where_linked.follow's answer and the requests it made."""
    if found.get("status") == "direct" or found.get("feeds"):
        return "feed"
    if any(page.get("items") for page in found.get("pages") or ()):
        return "page"
    if not polite.answered and polite.refused and all(status in BLOCKED for status in polite.refused):
        return "blocked"
    return "headlines"


def slot(url: str) -> str:
    """The limiter's key of an address: its host, www. aside."""
    return publication_of(host_of(url)) or "?"


async def follow_test(http: Any, registry: Any, url: str, linked: List[str],
                      limiter: Optional[HostLimiter] = None) -> str:
    polite = Polite(http)
    try:
        async with (limiter or HostLimiter()).slot(slot(url)):
            found = await where_linked.follow(polite, registry, url, linked)
    except Exception as exc:  # noqa: BLE001 - a site that can't be asked is labelled by what it answered
        logger.info("Discover: the follow test of %s failed (%s)", url, type(exc).__name__)
        found = {}
    return label(found, polite)


def page_title(page: str, url: str) -> Optional[str]:
    """A page's own title (page_watch.page_title), None when it has none, or only its address."""
    title = " ".join(html.unescape(page_watch.page_title(page, url) or "").split())
    if not title or title == url or _ADDRESS.match(title) or len(title) > TITLE_CHARS:
        return None
    return title


async def read_title(polite: Polite, url: str) -> Optional[str]:
    try:
        body, here = await polite.get_start(url, PAGE_BYTES)
    except Exception:  # noqa: BLE001 - an unread page keeps no title
        return None
    return page_title(body.decode("utf-8", "replace"), here)


def due(read: Optional[Dict[str, Any]], now: datetime) -> bool:
    """Never read, or read CHECK_DAYS ago or more."""
    try:
        return read is None or now - datetime.fromisoformat(read["at"]) >= timedelta(days=CHECK_DAYS)
    except (KeyError, TypeError, ValueError):
        return True


def work(page: List[Dict[str, Any]], reads: Dict[str, Any], now: datetime) -> Dict[str, List[str]]:
    """What the first page asks to read: the suggestions whose follow test is due, the untitled articles
    (not tweets) whose title is."""
    follow, titles = reads.get("follow", {}), reads.get("titles", {})
    return {"follow": [s["key"] for s in page if due(follow.get(s["key"]), now)],
            "titles": sorted({a["url"] for s in page for a in s["articles"]
                              if not a["title"] and not is_tweet(a["url"]) and due(titles.get(a["url"]), now)})}


async def read_first_page(stories: Any, http: Any, registry: Any, *,
                          clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Dict[str, int]:
    """Read what the first page lacks (`work`), and store each answer with its date. Returns how many."""
    page = (await asyncio.to_thread(stories.discover, limit=FIRST_PAGE))["suggestions"]
    with db.connection(stories.db_url) as conn, conn.cursor() as cur:
        todo = work(page, DiscoverRepository.reads(cur), clock())
    if not todo["follow"] and not todo["titles"]:
        return {"follow": 0, "titles": 0}
    gate = asyncio.Semaphore(FAN_OUT)
    limiter = HostLimiter()
    polite = Polite(http, limiter)

    async def test(key: str):
        async with gate:
            linked = await asyncio.to_thread(stories.linked_articles, "https://" + key)
            return key, {"label": await follow_test(http, registry, "https://" + key, linked, limiter), "at": clock().isoformat()}

    async def title(url: str):
        async with gate:
            return url, {"title": await read_title(polite, url), "at": clock().isoformat()}

    tested = dict(await asyncio.gather(*map(test, todo["follow"])))
    titled = dict(await asyncio.gather(*map(title, todo["titles"])))
    with db.transaction(stories.db_url) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('insight.discover_reads'))")
        reads = DiscoverRepository.reads(cur)
        reads["follow"] = {**reads.get("follow", {}), **tested}
        reads["titles"] = {**reads.get("titles", {}), **titled}
        DiscoverRepository.keep_reads(cur, reads)
    logger.info("Discover: %d follow tests, %d page titles read", len(tested), len(titled))
    return {"follow": len(tested), "titles": len(titled)}


_running: Optional[asyncio.Task] = None


def start(stories: Any, http: Any, registry: Any) -> bool:
    """Start reading the first page in the background (one run at a time, when enabled). Never raises."""
    global _running
    if not enabled() or (_running is not None and not _running.done()):
        return False

    async def run() -> None:
        try:
            await read_first_page(stories, http, registry)
        except Exception:  # noqa: BLE001 - derived; the next open tries again
            logger.exception("Discover: reading the first page failed")

    _running = asyncio.get_running_loop().create_task(run())
    return True


__all__ = ["read_first_page", "start", "label", "page_title", "work", "due", "Polite", "LABELS", "enabled"]
