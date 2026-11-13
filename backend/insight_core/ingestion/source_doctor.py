"""The source doctor (issue 0036): a broken source finds its replacement.

    await doctor.after_failure(source, kind, state, error, progress)

The runner calls it after every failed fetch, with the fetch state that failure wrote and
the exception the fetch raised. It looks when a source of a kind that reads a feed or a page
(generic_rss, page_watch; never one a kind or site adapter reads directly) has failed
FAILURES_BEFORE_LOOKING times in a row, or at once on a clear signal: HTTP 404/410 (gone) or
an answer that does not parse as a feed. At most once a day per source, and not again in a
streak whose finding the owner dismissed; a fetch that works clears the finding.

A server error (HTTP 5xx) or a timeout is no move (issue 0072): the site is there and failing.
That is recorded ("server error, not moved", with its HTTP status: the source sheet says the server
is failing and INSIGHT keeps retrying, issue 0072 D3); nothing is looked at and nothing is offered,
so an offer stored before is replaced (an aggregator's 502 was offered a feed tool's changelog).

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
A candidate at another address must hold the source's own items (issue 0072): one of its items
has the address or the title of one of the source's latest stored posts (`shared`). One that
holds none is never offered nor switched to, so a source with no stored post can be offered
only its own address read as a page. The finding carries the candidate's latest titles
(`latest`), which the source sheet shows before Switch.
Nothing is re-fetched: the next fetch reads the new address, posts match by URL, and an
archive brings the older ones.

A silent source (issue 0178): its fetches work, yet nothing new came for far longer than its own rhythm
(silent_beyond_rhythm: over max(SILENT_GAPS x its measured mean gap, SILENT_FLOOR); a source whose cadence
is not measured is never silent here: source hygiene's "quiet" mark covers it). A newsletter that moved
domains keeps answering at its old feed, so no failure ever wakes the doctor; after a fetch that worked and
brought nothing new, the runner shows it the source (after_success), at most once a LOOK_SILENT_EVERY. For a
kind whose address can move (SILENT_KINDS) it looks where the source went (where_it_went): where its address,
its home page and its newest posts' own pages now land (a redirect to another site is recorded, `moved`),
then the feed finder on each such landing and on its home page; a feed offered must publish after the
source's last post (it is alive) and, on the source's own site, stay within its section. The finding is kept
apart from the failure finding (source_fetch_state.silent_finding): Switch (the existing switch path) or
"It stopped" is the owner's; the doctor never switches a silent source by itself.
"""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from insight_core.db import database as db
from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow
from insight_core.ingestion.feed_finder import FEED_BYTES, feed_title, find_feeds
from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import KindRegistry, page_watch, substack
from insight_core.ingestion.kinds.base import EmptyFetch
from insight_core.ingestion.kinds.parsing import path_segments
from insight_core.utils.addresses import host_of, publication_of
from insight_core.utils.json_safe import iso
from insight_core.utils.titles import title_key
from insight_core.utils.url_normalization import normalize_url

logger = logging.getLogger("insight.ingestion.source_doctor")

DOCTOR_KINDS = ("generic_rss", "page_watch")   # the kinds whose address can move
FAILURES_BEFORE_LOOKING = 3
GONE_STATUSES = (404, 410)
LOOK_EVERY = timedelta(days=1)
STORED_ITEMS = 50          # the source's latest stored posts a candidate is compared with; not measured
LATEST_TITLES = 5          # the candidate's titles shown before Switch (page watching's preview has 5)

# Issue 0178: silent far beyond its own rhythm. Not measured: 5 gaps is a run of misses no rhythm has by
# chance often (a daily source silent 5 days), and the floor keeps a busy source's quiet fortnight from counting.
SILENT_GAPS = 5
SILENT_FLOOR = timedelta(days=14)
LOOK_SILENT_EVERY = timedelta(days=7)
SILENT_KINDS = ("generic_rss", "page_watch", "substack")   # the kinds whose address can move to another site
NEWEST_PROBED = 3          # the newest posts whose own pages are asked where they land
PROBE_BYTES = 4096         # a redirect is in the answer's address; the body is not needed

Replacement = Dict[str, Any]   # {kind: feed|page_watch, url, title, found, prefix, shared, latest}
Item = Tuple[str, str]         # a stored post's (url, title)
# The finding when the old address reads again: nothing to replace, nothing to suggest.
WORKING_AGAIN: Dict[str, Any] = {"replacement": None, "dismissed": False, "working_again": True,
                                 "note": "temporary error, working again"}
# The finding on a server error or a timeout: the site is there; nothing looked at, nothing offered.
# Recorded with the error's `status` (None for a timeout).
SERVER_ERROR: Dict[str, Any] = {"replacement": None, "dismissed": False, "server_error": True,
                                "note": "server error, not moved"}
# The finding on a fetch that worked and stored nothing (issue 0135, kinds.base.EmptyFetch): the address
# answers, so it is never "working again" and nothing replaces it; recorded with the fetch's reason (note).
EMPTY_FETCH: Dict[str, Any] = {"replacement": None, "dismissed": False, "empty_fetch": True}


class DoctorStore(Protocol):
    def record(self, source_id: str, *, checked_at: datetime, finding: Dict[str, Any]) -> None: ...

    def switch(self, source_id: str, url: str, page_watch: Optional[Dict[str, Any]]) -> Any: ...

    def items(self, source_id: str) -> List[Item]: ...


def failure_signal(error: Optional[BaseException]) -> Optional[str]:
    """"gone" (HTTP 404/410), "server_error" (HTTP 5xx or a timeout), "not_feed" (the answer
    does not parse as a feed), "empty" (it answered and nothing was stored, issue 0135), else None."""
    if isinstance(error, EmptyFetch):
        return "empty"
    if isinstance(error, HttpError) and error.status in GONE_STATUSES:
        return "gone"
    if isinstance(error, HttpError) and error.their_trouble:
        return "server_error"
    if isinstance(error, ET.ParseError):
        return "not_feed"
    return None


def should_look(kind_name: str, state: FetchStateRow, signal: Optional[str], now: datetime) -> bool:
    if kind_name not in DOCTOR_KINDS or (state.doctor_finding or {}).get("dismissed"):
        return False
    if state.doctor_checked_at is not None and now - state.doctor_checked_at < LOOK_EVERY:
        return False
    return signal is not None or state.consecutive_failures >= FAILURES_BEFORE_LOOKING


def short_address(url: str) -> str:
    """"https://www.arena.ai/blog/feed.xml" -> "arena.ai/blog/feed.xml"."""
    parsed = urllib.parse.urlparse(url)
    return (publication_of(host_of(url)) + parsed.path.rstrip("/") + (f"?{parsed.query}" if parsed.query else "")) or url


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
    if publication_of(host_of(candidate)) != publication_of(host_of(address)):
        return True
    scope = urllib.parse.urlparse(section(address)).path
    return (urllib.parse.urlparse(candidate).path or "/").startswith(scope)


def shared(stored: Sequence[Item], urls: Sequence[str], titles: Sequence[str]) -> int:
    """How many of a candidate's items are the source's own: the same address, or the same
    title (utils/titles.title_key), as one of its stored posts; the larger of the two counts."""
    addresses = {normalize_url(url) for url, _ in stored} - {None}
    keys = {title_key(title) for _, title in stored} - {""}
    return max(sum(normalize_url(url) in addresses for url in dict.fromkeys(urls)),
               sum(title_key(title) in keys for title in dict.fromkeys(titles)))


def _evidence(stored: Sequence[Item], urls: Sequence[str], titles: Sequence[str]) -> Dict[str, Any]:
    return {"shared": shared(stored, urls, titles), "latest": [title for title in titles if title][:LATEST_TITLES]}


def _page(url: str, preview: Mapping[str, Any], stored: Sequence[Item]) -> Replacement:
    items = preview["items"]
    return {"kind": "page_watch", "url": url, "title": short_address(url), "found": preview["found"],
            "prefix": preview["prefix"],
            **_evidence(stored, [item["url"] for item in items], [item["title"] or "" for item in items])}


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
                           follows_page: bool = False, stored: Sequence[Item] = ()) -> Optional[Replacement]:
    """A feed for the address's site (other than the address, within its section), else a page
    to follow, else None; at another address, only one holding the source's own items (`stored`,
    its latest posts). `follows_page`: the source already follows the address as a page."""
    # The finder on the address reads its first-segment section and home page itself; a
    # deeper section ("/a/b/") needs a search of its own.
    pages: List[str] = [address] + ([section(address)] if len(path_segments(section(address))) >= 2 else [])
    blog_pages: List[str] = []
    menu: List[str] = []
    for page in pages:
        finding = await find_feeds(http, registry, page)
        for feed in finding.feeds:
            if _same(feed.url, address) or not within_section(feed.url, address):
                continue
            evidence = _evidence(stored, feed.items, feed.titles)
            if evidence["shared"]:
                return {"kind": "feed", "url": feed.url, "title": feed.title or short_address(feed.url),
                        "found": None, "prefix": None, **evidence}
            logger.info("Source doctor: %s holds none of %s's items", feed.url, address)
        blog_pages += finding.pages
        menu += finding.menu
    # The section's page; for a source at the root that is the address itself: a site whose
    # address answers a page, not a feed (incompleteideas.net), is followed as that page.
    listing = section(address)
    # At the root, the whole site is the section: its own blog or news page with the most
    # articles comes before its home page (issue 0041), else a menu link that reads as an
    # article list (issue 0047), as for any source add.
    offered = await page_watch.offers(http, blog_pages, menu) if page_watch.is_home(listing) else []
    for offer in offered:
        if (candidate := _page(offer["url"], offer, stored))["shared"]:
            return candidate
    if follows_page and _same(listing, address):
        return None
    try:
        preview = await page_watch.preview(http, listing)
    except ValueError as exc:
        logger.info("Source doctor: %s cannot be followed (%s)", listing, exc)
        return None
    if not preview["items"]:
        return None
    candidate = _page(listing, preview, stored)
    # The address itself, read as a page, is the source itself: nothing to prove.
    return candidate if candidate["shared"] or _same(listing, address) else None


def silent_beyond_rhythm(last_post_at: Optional[datetime], mean_gap_seconds: Any, cadence_tier: Any,
                         now: datetime) -> Optional[timedelta]:
    """How long a source has been silent, when that is far beyond its own rhythm (issue 0178): over
    max(SILENT_GAPS x its mean gap, SILENT_FLOOR) since its newest post; None when it is not, has no post, or
    its cadence is not measured (no mean gap, or the "unknown" tier: too few posts to have a rhythm)."""
    tier = getattr(cadence_tier, "value", cadence_tier)
    if last_post_at is None or mean_gap_seconds is None or tier in (None, "", "unknown"):
        return None
    try:
        gap = timedelta(seconds=float(mean_gap_seconds))
    except (TypeError, ValueError):
        return None
    silence = now - last_post_at
    return silence if silence > max(gap * SILENT_GAPS, SILENT_FLOOR) else None


def home_of(url: str) -> str:
    """The site's home page: "https://news.example/rss.xml" -> "https://news.example/"."""
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(path="/", params="", query="", fragment=""))


def _elsewhere(url: str, landed: str) -> bool:
    """`landed` is on another site than `url` (www. and the subdomains of one publication are one site)."""
    return bool(landed) and publication_of(host_of(landed)) != publication_of(host_of(url))


async def where_it_went(http: KindHttp, registry: KindRegistry, address: str, *, last_post_at: Optional[datetime],
                        newest_posts: Sequence[str] = ()) -> Dict[str, Any]:
    """Where a silent source went (issue 0178): {moved: [{via, from, to}], replacement: {kind: feed, url, title,
    latest, newest, via} | None}. `moved`: its address, its home page or one of its newest posts' own pages
    (`newest_posts`, newest first) now landing on another site. The feed finder runs on each such landing, then
    on its home page; the first feed that is not the source's own address, publishes after `last_post_at` (it is
    alive) and, on the source's own site, stays within its section (within_section) is the replacement.
    Never raises for a site's failure."""
    probes: List[Tuple[str, str]] = [("address", address), ("home page", home_of(address))]
    probes += [("post", url) for url in list(dict.fromkeys(u for u in newest_posts if u))[:NEWEST_PROBED]]
    moved: List[Dict[str, str]] = []
    for via, url in probes:
        try:
            _, landed = await http.get_start(url, PROBE_BYTES)
        except Exception as exc:  # noqa: BLE001 - a page that does not answer says nothing of a move
            logger.info("Source doctor: %s (%s) did not answer: %s", url, via, str(exc)[:200])
            continue
        if _elsewhere(url, landed) and not any(_same(m["to"], landed) for m in moved):
            moved.append({"via": via, "from": url, "to": landed})
    looked: List[Tuple[str, str]] = []
    for move in moved:
        site = publication_of(host_of(move["to"]))
        if not any(publication_of(host_of(page)) == site for page, _ in looked):
            what = "its address" if move["via"] == "address" else f"its {move['via']}"
            looked.append((move["to"], f"{what} now lands at {short_address(move['to'])}"))
    looked.append((home_of(address), "its home page"))
    for page, via in looked:
        try:
            finding = await find_feeds(http, registry, page)
        except Exception as exc:  # noqa: BLE001 - nothing found there
            logger.info("Source doctor: the finder failed on %s: %s", page, str(exc)[:200])
            continue
        for feed in finding.feeds:
            if (_same(feed.url, address) or not within_section(feed.url, address) or not feed.readable
                    or feed.search or feed.newest is None
                    or (last_post_at is not None and feed.newest <= last_post_at)):
                continue
            return {"moved": moved, "replacement": {
                "kind": "feed", "url": feed.url, "title": feed.title or short_address(feed.url),
                "latest": [title for title in feed.titles if title][:LATEST_TITLES], "newest": iso(feed.newest),
                "via": via}}
    return {"moved": moved, "replacement": None}


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
        if signal == "empty" and state is not None:
            # Any kind (a channel whose every video was skipped too): its reason, nothing looked for.
            await asyncio.to_thread(self.store.record, str(source["id"]), checked_at=now,
                                    finding={**EMPTY_FETCH, "note": str(error)})
            logger.info("Source doctor: %s: %s", source.get("handle_or_url"), error)
            return
        if state is None or source.get("platform") != "rss" or not should_look(kind.name, state, signal, now):
            return
        if signal == "server_error":
            status = getattr(error, "status", None)
            await asyncio.to_thread(self.store.record, str(source["id"]), checked_at=now,
                                    finding={**SERVER_ERROR, "status": status})
            logger.info("Source doctor: %s: server error (%s), not moved; retrying", source.get("handle_or_url"),
                        f"HTTP {status}" if status else "timed out")
            return
        address = str(source["handle_or_url"])
        settings = source.get("settings") or {}
        name = str(settings.get("display_name") or address)
        followed = settings.get("page_watch") if isinstance(settings.get("page_watch"), dict) else None
        if followed is None and settings.get("substack") is not True and hasattr(self.store, "merge_settings"):
            # Issue 0167: a Substack publication on its own domain read as a plain feed: read by its kind from now.
            why = await substack.recognise(self.http, address)
            if why:
                await asyncio.to_thread(self.store.merge_settings, str(source["id"]), {"substack": True})
                await asyncio.to_thread(self.store.record, str(source["id"]), checked_at=now, finding={
                    "replacement": None, "dismissed": False, "recognised": "substack",
                    "note": f"a Substack publication on its own domain ({why}): read as one from its next fetch"})
                logger.info("Source doctor: %s is a Substack publication on its own domain (%s)", name, why)
                return
        if await reads_again(self.http, address, followed):
            # A temporary error (devblogs.microsoft.com's SSL on the server): nothing to replace.
            await asyncio.to_thread(self.store.record, str(source["id"]), checked_at=now, finding=WORKING_AGAIN)
            logger.info("Source doctor: %s: temporary error, working again (%s)", name, address)
            return
        stored = await asyncio.to_thread(self.store.items, str(source["id"]))
        replacement = await find_replacement(self.http, self.registry, address, follows_page=followed is not None,
                                             stored=stored)
        if (replacement and replacement["kind"] == "feed" and signal == "gone"
                and publication_of(host_of(replacement["url"])) == publication_of(host_of(address))):
            try:
                await asyncio.to_thread(self.store.switch, str(source["id"]), replacement["url"], None)
            except Exception as exc:  # noqa: BLE001 - already a source: suggest it
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


    async def after_success(self, source: Mapping[str, Any], kind: Any, state: Optional[FetchStateRow],
                            new_posts: int = 0) -> None:
        """After a fetch that worked (issue 0178): a source silent far beyond its rhythm has where it went looked
        for and recorded; one that posts again has its silence cleared. Never switches; never raises."""
        try:
            await self._after_success(source, kind, state, new_posts)
        except Exception:  # noqa: BLE001 - the doctor is never worth the run
            logger.exception("Source doctor (silence) failed for %s", source.get("handle_or_url"))

    async def _after_success(self, source: Mapping[str, Any], kind: Any, state: Optional[FetchStateRow],
                             new_posts: int) -> None:
        if not hasattr(self.store, "record_silence"):
            return
        source_id, now = str(source["id"]), self.clock()
        finding = (state.silent_finding if state else None) or None
        if new_posts:
            if finding:   # it posts again
                await asyncio.to_thread(self.store.record_silence, source_id, checked_at=now, finding=None)
            return
        if source.get("mean_gap_seconds") is None or source.get("cadence_tier") in (None, "", "unknown"):
            return
        if (state is not None and state.silent_checked_at is not None
                and now - state.silent_checked_at < LOOK_SILENT_EVERY):
            return
        last = await asyncio.to_thread(self.store.last_post_at, source_id)
        silence = silent_beyond_rhythm(last, source.get("mean_gap_seconds"), source.get("cadence_tier"), now)
        if silence is None:
            if finding:
                await asyncio.to_thread(self.store.record_silence, source_id, checked_at=now, finding=None)
            return
        if finding and finding.get("stopped") and finding.get("last_post_at") == iso(last):
            return   # the owner said it stopped, and nothing came since
        name = str((source.get("settings") or {}).get("display_name") or source.get("handle_or_url"))
        record: Dict[str, Any] = {
            "last_post_at": iso(last), "silent_days": round(silence.total_seconds() / 86400, 1),
            "usual_gap_days": round(float(source["mean_gap_seconds"]) / 86400, 2), "stopped": False,
            "moved": [], "replacement": None, "looked": False}
        if kind.name in SILENT_KINDS and source.get("platform") == "rss":
            newest = [url for url, _ in await asyncio.to_thread(self.store.items, source_id)]
            record.update(await where_it_went(self.http, self.registry, str(source["handle_or_url"]),
                                              last_post_at=last, newest_posts=newest), looked=True)
        await asyncio.to_thread(self.store.record_silence, source_id, checked_at=now, finding=record)
        replacement = record["replacement"]
        logger.warning("Source doctor: %s is silent for %s days (usually every %s days)%s", name,
                       record["silent_days"], record["usual_gap_days"],
                       f"; offering {replacement['url']} ({replacement['via']})" if replacement else
                       (f"; it moved to {record['moved'][0]['to']}" if record["moved"] else ""))


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

    def merge_settings(self, source_id: str, settings: Dict[str, Any]) -> None:
        """What the doctor learned the source is (issue 0167: {"substack": True}), into its settings."""
        from insight_core.db.repo_sources import SourcesRepository

        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                SourcesRepository(self.db_url).merge_source_settings(cur, source_id, settings)
            conn.commit()

    def record_silence(self, source_id: str, *, checked_at: datetime, finding: Optional[Dict[str, Any]]) -> None:
        """Where a silent source went (issue 0178); None clears it."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                FetchStateRepository().record_silence(cur, source_id, checked_at=checked_at, finding=finding)
            conn.commit()

    def last_post_at(self, source_id: str) -> Optional[datetime]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return FetchStateRepository().last_post_at(cur, source_id)

    def items(self, source_id: str) -> List[Item]:
        """The source's latest STORED_ITEMS posts, (url, title)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT url, coalesce(title, '') FROM posts WHERE source_id = %s"
                        " ORDER BY coalesce(published_at, fetched_at) DESC NULLS LAST LIMIT %s",
                        (source_id, STORED_ITEMS))
            return [(str(url or ""), str(title)) for url, title in cur.fetchall()]


__all__ = ["DbDoctorStore", "EMPTY_FETCH", "SERVER_ERROR", "SourceDoctor", "WORKING_AGAIN", "failure_signal", "find_replacement", "reads_again",
           "shared", "should_look", "silent_beyond_rhythm", "where_it_went", "within_section"]
