"""The source doctor (issue 0036): a broken source finds its replacement.

    await doctor.after_failure(source, kind, state, error, progress)

The runner calls it after every failed fetch, with the fetch state that failure wrote and
the exception the fetch raised. It looks when a source of a kind that reads a feed or a page
(generic_rss, page_watch; never one a kind or site adapter reads directly) has failed
FAILURES_BEFORE_LOOKING times in a row, or at once on a clear signal: HTTP 404/410 (gone) or
an answer that does not parse as a feed. At most once a day per source, and not again in a
streak whose finding the owner dismissed; a fetch that works clears the finding.

First it reads the old address itself: when it reads again (a feed that parses; a followed
page that still lists articles), the error was temporary. That is recorded ("temporary error,
working again": no replacement, nothing to suggest) and nothing else is looked at.

Otherwise it looks the way every source add does: the feed finder (issue 0026) on the source's
address (which reads its section and home page too) and on a deeper section ("/a/b/rss" ->
"/a/b/"); no feed: page watching (issue 0028) previews the section (for a source at the site's
root, the site's own blog or news page with the most articles first, issue 0041). A feed on the source's site
must stay within its section (the address less its last segment: "/oldnewthing/" for
"/oldnewthing/feed"), so the home page's feed of every blog on the site is never taken for one
of them; a source at the site's root ("/rss") takes any feed of the site. Then:
  - a feed on the same site (www. ignored) while the old address is gone: switch the source
    to it (store.switch keeps its id, name, tracks, read state and posts, clears its failures
    and keeps sources.json in step) and say so in the job: "Arena: feed moved, now following
    arena.ai/blog/feed.xml";
  - anything else found (another site, a page to follow, a feed that is flaky, not gone): the
    finding is stored as a suggestion, for the Sources list and sheet to offer;
  - nothing: the finding says so ("Broken: no replacement found").
Nothing is re-fetched: the next fetch reads the new address, posts match by URL, and an
archive brings the older ones.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol

from insight_core.db import database as db
from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow
from insight_core.ingestion.feed_finder import FEED_BYTES, feed_title, find_feeds
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import KindRegistry, page_watch
from insight_core.ingestion.kinds.parsing import path_segments

logger = logging.getLogger("insight.ingestion.source_doctor")

DOCTOR_KINDS = ("generic_rss", "page_watch")   # the kinds whose address can move
FAILURES_BEFORE_LOOKING = 3
GONE_STATUSES = (404, 410)
LOOK_EVERY = timedelta(days=1)

Replacement = Dict[str, Any]   # {kind: feed|page_watch, url, title, found, prefix}
# The finding when the old address reads again: nothing to replace, nothing to suggest.
WORKING_AGAIN: Dict[str, Any] = {"replacement": None, "dismissed": False, "working_again": True,
                                 "note": "temporary error, working again"}


class DoctorStore(Protocol):
    def record(self, source_id: str, *, checked_at: datetime, finding: Dict[str, Any]) -> None: ...

    def switch(self, source_id: str, url: str, page_watch: Optional[Dict[str, Any]]) -> Any: ...


def failure_signal(error: Optional[BaseException]) -> Optional[str]:
    """"gone" (HTTP 404/410), "not_feed" (the answer does not parse as a feed), else None."""
    if isinstance(error, HttpError) and error.status in GONE_STATUSES:
        return "gone"
    if isinstance(error, ET.ParseError):
        return "not_feed"
    return None


def should_look(kind_name: str, state: FetchStateRow, signal: Optional[str], now: datetime) -> bool:
    if kind_name not in DOCTOR_KINDS or (state.doctor_finding or {}).get("dismissed"):
        return False
    if state.doctor_checked_at is not None and now - state.doctor_checked_at < LOOK_EVERY:
        return False
    return signal is not None or state.consecutive_failures >= FAILURES_BEFORE_LOOKING


def site(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.")


def short_address(url: str) -> str:
    """"https://www.arena.ai/blog/feed.xml" -> "arena.ai/blog/feed.xml"."""
    parsed = urllib.parse.urlparse(url)
    return (site(url) + parsed.path.rstrip("/") + (f"?{parsed.query}" if parsed.query else "")) or url


def section(url: str) -> str:
    """The address with its last path segment removed: "/blog/rss/" -> "/blog/", "/feed" -> "/"."""
    parsed = urllib.parse.urlparse(url)
    parent = path_segments(url)[:-1]
    return urllib.parse.urlunparse(parsed._replace(path="/" + "".join(f"{s}/" for s in parent),
                                                   params="", query="", fragment=""))


def _same(a: str, b: str) -> bool:
    return short_address(a) == short_address(b)


def within_section(candidate: str, address: str) -> bool:
    """A feed on the source's site stays within its section ("/oldnewthing/" for
    "/oldnewthing/feed"); for a source at the root ("/rss") that is the whole site. A feed on
    another site is never switched to (only suggested), so it is not judged here."""
    if site(candidate) != site(address):
        return True
    scope = urllib.parse.urlparse(section(address)).path
    return (urllib.parse.urlparse(candidate).path or "/").startswith(scope)


async def reads_again(http: KindHttp, address: str, page_watch_settings: Optional[Mapping[str, Any]]) -> bool:
    """The old address reads now: a feed that parses, or a followed page that lists articles."""
    try:
        if page_watch_settings is not None:
            preview = await page_watch.preview(http, address, page_watch_settings.get("prefix"))
            return bool(preview["items"])
        body, _ = await http.get_start(address, FEED_BYTES)
        return feed_title(body) is not None
    except Exception as exc:  # noqa: BLE001 - still failing: look for a replacement
        logger.info("Source doctor: %s still fails (%s)", address, str(exc)[:200])
        return False


async def find_replacement(http: KindHttp, registry: KindRegistry, address: str, *,
                           follows_page: bool = False) -> Optional[Replacement]:
    """A feed for the address's site (other than the address, within its section), else a page
    to follow, else None. `follows_page`: the source already follows the address as a page."""
    # The finder on the address reads its first-segment section and home page itself; a
    # deeper section ("/a/b/") needs a search of its own.
    pages: List[str] = [address] + ([section(address)] if len(path_segments(section(address))) >= 2 else [])
    blog_pages: List[str] = []
    menu: List[str] = []
    for page in pages:
        finding = await find_feeds(http, registry, page)
        feed = next((f for f in finding.feeds if not _same(f.url, address) and within_section(f.url, address)), None)
        if feed:
            return {"kind": "feed", "url": feed.url, "title": feed.title or short_address(feed.url),
                    "found": None, "prefix": None}
        blog_pages += finding.pages
        menu += finding.menu
    # The section's page; for a source at the root that is the address itself: a site whose
    # address answers a page, not a feed (incompleteideas.net), is followed as that page.
    listing = section(address)
    # At the root, the whole site is the section: its own blog or news page with the most
    # articles comes before its home page (issue 0041), else a menu link that reads as an
    # article list (issue 0047), as for any source add.
    offered = await page_watch.offers(http, blog_pages, menu) if page_watch.is_home(listing) else []
    if offered:
        best = offered[0]
        return {"kind": "page_watch", "url": best["url"], "title": short_address(best["url"]),
                "found": best["found"], "prefix": best["prefix"]}
    if follows_page and _same(listing, address):
        return None
    try:
        preview = await page_watch.preview(http, listing)
    except ValueError as exc:
        logger.info("Source doctor: %s cannot be followed (%s)", listing, exc)
        return None
    if not preview["items"]:
        return None
    return {"kind": "page_watch", "url": listing, "title": short_address(listing),
            "found": preview["found"], "prefix": preview["prefix"]}


class SourceDoctor:
    def __init__(self, *, http: KindHttp, registry: KindRegistry, store: DoctorStore,
                 clock: Callable[[], datetime]) -> None:
        self.http = http
        self.registry = registry
        self.store = store
        self.clock = clock

    async def after_failure(self, source: Mapping[str, Any], kind: Any, state: Optional[FetchStateRow],
                            error: Optional[BaseException], progress: Any = None) -> None:
        """Look for a failing source's replacement when it is time, and act on what is found.
        Never raises: a source that cannot be helped is just left failing."""
        try:
            await self._after_failure(source, kind, state, error, progress)
        except Exception:  # noqa: BLE001 - the doctor is never worth the run
            logger.exception("Source doctor failed for %s", source.get("handle_or_url"))

    async def _after_failure(self, source: Mapping[str, Any], kind: Any, state: Optional[FetchStateRow],
                             error: Optional[BaseException], progress: Any) -> None:
        signal, now = failure_signal(error), self.clock()
        if state is None or source.get("platform") != "rss" or not should_look(kind.name, state, signal, now):
            return
        address = str(source["handle_or_url"])
        settings = source.get("settings") or {}
        name = str(settings.get("display_name") or address)
        followed = settings.get("page_watch") if isinstance(settings.get("page_watch"), dict) else None
        if await reads_again(self.http, address, followed):
            # A temporary error (devblogs.microsoft.com's SSL on the server): nothing to replace.
            await asyncio.to_thread(self.store.record, str(source["id"]), checked_at=now, finding=WORKING_AGAIN)
            logger.info("Source doctor: %s: temporary error, working again (%s)", name, address)
            return
        replacement = await find_replacement(self.http, self.registry, address, follows_page=followed is not None)
        if (replacement and replacement["kind"] == "feed" and signal == "gone"
                and site(replacement["url"]) == site(address)):
            try:
                await asyncio.to_thread(self.store.switch, str(source["id"]), replacement["url"], None)
            except Exception as exc:  # noqa: BLE001 - already a source, sources.json unwritable: suggest it
                logger.warning("Source doctor: could not switch %s to %s (%s)", name, replacement["url"], exc)
            else:
                line = f"{name}: feed moved, now following {short_address(replacement['url'])}"
                logger.warning("Source doctor: %s (was %s)", line, address)
                if progress is not None:
                    await asyncio.to_thread(progress.event, "doctor", {
                        "source_id": str(source["id"]), "display_name": name, "line": line,
                        "from": address, "to": replacement["url"]})
                return
        await asyncio.to_thread(self.store.record, str(source["id"]), checked_at=now,
                                finding={"replacement": replacement, "dismissed": False})
        logger.info("Source doctor: %s is broken (%s); %s", name, signal or f"{state.consecutive_failures} failures",
                    f"suggesting {replacement['kind']} {replacement['url']}" if replacement else "no replacement found")


class DbDoctorStore:
    """The finding in source_fetch_state; the switch is the caller's (it keeps sources.json in step)."""

    def __init__(self, db_url: str, switch: Callable[[str, str, Optional[Dict[str, Any]]], Any]) -> None:
        self.db_url = db_url
        self._switch = switch

    def record(self, source_id: str, *, checked_at: datetime, finding: Dict[str, Any]) -> None:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                FetchStateRepository().record_doctor(cur, source_id, checked_at=checked_at, finding=finding)
            conn.commit()

    def switch(self, source_id: str, url: str, page_watch: Optional[Dict[str, Any]]) -> Any:
        return self._switch(source_id, url, page_watch)


__all__ = ["DbDoctorStore", "SourceDoctor", "WORKING_AGAIN", "failure_signal", "find_replacement", "reads_again",
           "should_look", "within_section"]
