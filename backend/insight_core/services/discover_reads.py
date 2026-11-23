"""What Discover reads of the web for its first page, at most once in CHECK_DAYS each (stored in `discover_reads`):
follow tests (`follow_read`), linked videos' channels (`read_video`) and untitled pages' titles (`page_title`).
One request at a time per host, FAN_OUT hosts at once. Entry: `keep` (jobs process); off with INSIGHT_DISCOVER_READS=0.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

from insight_core.db import database as db
from insight_core.db.repo_discover import DiscoverRepository
from insight_core.ingestion import where_linked
from insight_core.ingestion.gates import HostLimiter
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import page_watch, parsing
from insight_core.utils.addresses import ACCOUNT_NAMESPACES, PLATFORM_SITES, host_of, is_tweet, publication_of, site_of
from insight_core.utils.discover_rules import CHECK_DAYS, FIRST_PAGE, FOLLOWABLE, UNFOLLOWABLE

logger = logging.getLogger(__name__)

PAGE_BYTES = 512 * 1024      # the start of a page read for its title (its <head>)
FAN_OUT = 4
TITLE_CHARS = 300
BLOCKED = (401, 403)
LABELS = ("feed", "page", "headlines", "blocked", "other_feed")
# the follow test's rules version: a stored test made by other rules is due again
FOLLOW_TEST = 5
# older rules whose followable tests still stand: only their unfollowable ones are due again
FOLLOWABLE_STANDS = frozenset({4})
KIND_POSTS = 3
TRANSIENT_HOURS = 6      # a test failed for a passing reason (5xx, timeout, 429) is asked again after this (0172)
SECTIONS_TRIED = 2
VIDEOS_PER_PASS = 25     # not measured
OEMBED = "https://www.youtube.com/oembed?format=json&url={}"
_ACCOUNT = re.compile(r"^[\w.@-]+$")
_ADDRESS = re.compile(r"^\s*(?:https?://\S+|[\w-]+(?:\.[\w-]+)+/\S*)\s*$")


def enabled() -> bool:
    return os.getenv("INSIGHT_DISCOVER_READS", "1") != "0"


class Polite:
    """An http client that records refusals; with a limiter, one request at a time per host."""

    def __init__(self, http: Any, limiter: Optional[HostLimiter] = None) -> None:
        self.http = http
        self.limiter = limiter
        self.answered = 0
        self.refused: List[Optional[int]] = []
        self.troubled = 0

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
            if exc.their_trouble or exc.limiting:
                self.troubled += 1
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
    """The follow test's label; a feed is "feed" only if it holds a linked page (or none linked), else other_feed."""
    if found.get("status") == "direct":
        return "feed"
    feeds = found.get("feeds") or []
    if feeds:
        if not found.get("linked") or any(feed.get("holds") for feed in feeds):
            return "feed"
        if not any(page.get("items") for page in found.get("pages") or ()):
            return "other_feed"
    if any(page.get("items") for page in found.get("pages") or ()):
        return "page"
    if not polite.answered and polite.refused and all(status in BLOCKED for status in polite.refused):
        return "blocked"
    return "headlines"


def slot(url: str) -> str:
    """The limiter's key of an address: its host, www. aside."""
    return publication_of(host_of(url)) or "?"


def own_pages(key: str, linked: Sequence[str]) -> List[str]:
    """The linked pages that are a suggestion's own: under its path (a platform owner), else all its host's."""
    host, _, path = key.lower().partition("/")
    out = []
    for url in linked:
        rest = url.split("://", 1)[-1]
        url_host, _, url_path = rest.partition("/")
        if publication_of(url_host.lower()) != publication_of(host):
            continue
        if not path or url_path.lower() == path or url_path.lower().startswith(path.rstrip("/") + "/"):
            out.append(url)
    return out


def kind_source(key: str, registry: Any) -> Optional[Dict[str, str]]:
    """The source a platform account is followed as (X and Telegram through their bridges, a subreddit, a YouTube
    channel), as Add source writes it, when a specific kind of `registry` reads it (not generic_rss nor page_watch);
    else None."""
    host, _, rest = key.partition("/")
    segments = [s for s in rest.split("/") if s]
    site = site_of(host)
    if not segments or not all(_ACCOUNT.match(s) for s in segments):
        return None
    source: Optional[Dict[str, str]] = None
    if (site in PLATFORM_SITES["x"] or (site in PLATFORM_SITES["telegram"] and site != "telegram.org")) \
            and len(segments) == 1:
        # the same bridge the add path follows it through (0241); no bridge set: no kind reads it
        from insight_core.ingestion.feed_finder import bridge_feed
        got = bridge_feed(f"https://{host}/{segments[0]}")
        if got is None or not got[1]:
            return None
        source = {"platform": "rss", "handle_or_url": got[1] + ("?limit=50" if got[0] == "telegram" else "")}
    elif site in PLATFORM_SITES["reddit"] and len(segments) == 2 and segments[0] == "r":
        source = {"platform": "reddit", "handle_or_url": f"r/{segments[1]}"}
    elif site in PLATFORM_SITES["youtube"] and ((len(segments) == 1 and segments[0].startswith("@"))
                                                or (len(segments) == 2 and segments[0] in ACCOUNT_NAMESPACES)):
        source = {"platform": "youtube", "handle_or_url": "https://www.youtube.com/" + "/".join(segments)}
    if source is None:
        return None
    try:
        kind = registry.resolve(source)
    except LookupError:
        return None
    return source if kind.name not in ("generic_rss", "page_watch") else None


async def kind_read(registry: Any, source: Dict[str, str]) -> Dict[str, Any]:
    """A platform account's follow test by its kind's latest posts: {label: feed | blocked | headlines, transient?}."""
    try:
        posts = await registry.resolve(source).fetch_latest(source, KIND_POSTS)
    except HttpError as exc:
        if exc.status in BLOCKED:
            return {"label": "blocked"}
        return {"label": "headlines", **({"transient": True} if exc.their_trouble or exc.limiting else {})}
    except Exception as exc:  # noqa: BLE001 - a bridge that can't be asked: nothing to follow by it now, ask again soon
        logger.info("Discover: the follow test of %s failed (%s)", source["handle_or_url"], type(exc).__name__)
        return {"label": "headlines", "transient": True}
    return {"label": "feed" if posts else "headlines"}


async def kind_test(registry: Any, source: Dict[str, str]) -> str:
    return (await kind_read(registry, source))["label"]


_HREF = re.compile(r"""href\s*=\s*["']([^"'#\s]+)["']""", re.I)


def declared_accounts(page: str, base: str, registry: Any) -> List[str]:
    """The platform accounts a site's page links to ("follow us") that a source kind reads, the most linked first."""
    from collections import Counter
    from urllib.parse import urljoin

    from insight_core.utils.discover_rules import discover_address
    found: Counter = Counter()
    for href in _HREF.findall(page or ""):
        url = urljoin(base, html.unescape(href))
        if "://" not in url:
            continue
        key, _, platform = discover_address(url)
        rest = url.split("://", 1)[1].partition("/")[2].split("?", 1)[0].strip("/")
        if not (platform and key) or rest.count("/") > (1 if key.count("/") > 1 else 0):
            continue   # an account's own page only, never one of its posts
        if kind_source(key, registry) is not None:
            found[key] += 1
    return [key for key, _ in found.most_common()]


def _sections(key: str, linked: Sequence[str]) -> List[str]:
    """The sections a site's own linked pages sit in, as addresses, the most pages first, at most SECTIONS_TRIED."""
    from collections import Counter

    from insight_core.utils.post_links import NUMBERISH
    counts: Counter = Counter()
    hosts: Dict[str, str] = {}
    for url in own_pages(key, linked):
        host, _, path = url.split("://", 1)[-1].partition("/")
        segs = [s for s in path.split("?", 1)[0].split("/") if s]
        if len(segs) >= 2 and not NUMBERISH.match(segs[0]):
            counts[segs[0]] += 1
            hosts.setdefault(segs[0], host)
    return [f"https://{hosts[seg]}/{seg}/" for seg, _ in counts.most_common(SECTIONS_TRIED)]


async def follow_read(http: Any, registry: Any, url: str, linked: List[str],
                      limiter: Optional[HostLimiter] = None) -> Dict[str, Any]:
    """The follow test, as stored: {label, moved_to? (landed on another site), url? (a followable section of its own
    pages when the home page gives nothing), account? ({url, label}: a declared account that answers, when the site
    can't be followed), transient? (asked again after TRANSIENT_HOURS)}."""
    polite = Polite(http)
    key = url.split("://", 1)[-1]
    source = kind_source(key, registry)
    own = own_pages(key, linked)
    try:
        async with (limiter or HostLimiter()).slot(slot(source["handle_or_url"] if source else url)):
            if source is not None:
                return await kind_read(registry, source)
            found = await where_linked.follow(polite, registry, url, own)
            out: Dict[str, Any] = {"label": label(found, polite)}
            landed = publication_of(host_of(found.get("landed") or "")) or ""
            if landed and site_of(landed) != site_of(publication_of(host_of(url))):
                out["moved_to"] = landed
                return out
            if out["label"] == "headlines" and not polite.troubled:
                for section in _sections(key, linked):
                    tried = Polite(http)
                    again = label(await where_linked.follow(tried, registry, section, own), tried)
                    if again in FOLLOWABLE:
                        out = {"label": again, "url": section}
                        break
            if out["label"] in UNFOLLOWABLE:
                account = await _declared(http, registry, found.get("landed") or (url if "/" in key else url + "/"))
                if account:
                    out["account"] = account
    except Exception as exc:  # noqa: BLE001 - a site that can't be asked is labelled by what it answered
        logger.info("Discover: the follow test of %s failed (%s)", url, type(exc).__name__)
        out = {"label": label({}, polite)}
    if out["label"] == "headlines" and polite.troubled and not polite.answered:
        out["transient"] = True
    return out


async def _declared(http: Any, registry: Any, url: str) -> Optional[Dict[str, str]]:
    """The first account a site's home page declares that its kind can read now, as {url, label}."""
    try:
        body, here = await http.get_start(url, PAGE_BYTES)
    except Exception:  # noqa: BLE001 - an unread page declares nothing
        return None
    for key in declared_accounts(body.decode("utf-8", "replace"), here, registry)[:2]:
        source = kind_source(key, registry)
        if source and (await kind_read(registry, source))["label"] == "feed":
            host, _, name = key.partition("/")
            return {"url": "https://" + key, "label": "@" + name if site_of(host) in PLATFORM_SITES["x"] else key}
    return None


async def follow_test(http: Any, registry: Any, url: str, linked: List[str],
                      limiter: Optional[HostLimiter] = None) -> str:
    return (await follow_read(http, registry, url, linked, limiter))["label"]


def page_title(page: str, url: str) -> Optional[str]:
    """A page's own title, None when it has none or only its address or its site's name (a wall or script page)."""
    title = " ".join(html.unescape(page_watch.page_title(page, url) or "").split())
    site = " ".join(html.unescape(parsing.meta_content(page, "og:site_name") or "").split())
    if not title or title == url or _ADDRESS.match(title) or len(title) > TITLE_CHARS:
        return None
    if site and title.casefold() == site.casefold():
        return None
    return title


async def read_title(polite: Polite, url: str) -> Optional[str]:
    try:
        body, here = await polite.get_start(url, PAGE_BYTES)
    except Exception:  # noqa: BLE001 - an unread page keeps no title
        return None
    return page_title(body.decode("utf-8", "replace"), here)


def channel_key(author_url: str) -> Optional[str]:
    """The Discover key of the YouTube channel an oEmbed answer names, else None."""
    from insight_core.utils.discover_rules import discover_address
    from insight_core.utils.url_normalization import normalize_url
    url = normalize_url(author_url or "") or ""
    key, site, platform = discover_address(url) if url else (None, "", False)
    return key if key and platform and site in PLATFORM_SITES["youtube"] else None


async def read_video(polite: "Polite", url: str) -> Dict[str, Any]:
    """A video's channel as YouTube's oEmbed names it: {channel: key or None, transient?}."""
    from urllib.parse import quote
    try:
        body, _ = await polite.get_text(OEMBED.format(quote(url, safe="")))
        data = json.loads(body)
    except HttpError as exc:
        return {"channel": None, **({"transient": True} if exc.their_trouble or exc.limiting else {})}
    except Exception:  # noqa: BLE001 - an answer that is no JSON names no channel
        return {"channel": None}
    return {"channel": channel_key(str((data or {}).get("author_url") or "")) if isinstance(data, dict) else None}


def videos_due(linked: Sequence[Any], reads: Dict[str, Any], now: datetime, *,
               limit: int = VIDEOS_PER_PASS) -> List[str]:
    """The linked videos whose channel is read this pass: never read, or no channel and `due`; at most `limit`."""
    videos = reads.get("videos", {})
    out = []
    for url, _ in linked:
        read = videos.get(url)
        if read is None or (not read.get("channel") and due(read, now)):
            out.append(url)
            if len(out) >= limit:
                break
    return out


def due(read: Optional[Dict[str, Any]], now: datetime, *, test: bool = False) -> bool:
    """Never read, read CHECK_DAYS ago (TRANSIENT_HOURS if transient), or (`test`) made by older FOLLOW_TEST rules."""
    try:
        again = timedelta(hours=TRANSIENT_HOURS) if read and read.get("transient") else timedelta(days=CHECK_DAYS)
        older = test and read is not None and read.get("test") != FOLLOW_TEST and not (
            read.get("test") in FOLLOWABLE_STANDS and read.get("label") in FOLLOWABLE)
        return read is None or older or now - datetime.fromisoformat(read["at"]) >= again
    except (AttributeError, KeyError, TypeError, ValueError):
        return True


def to_read(answer: Dict[str, Any], *, first_page: int = FIRST_PAGE) -> List[Dict[str, Any]]:
    """The first page plus the top FIRST_PAGE by score (tested ones sort first; else an untested one never is)."""
    listed = answer["suggestions"]
    by_score = sorted(listed, key=lambda s: (-s.get("score", 0), s["key"]))[:first_page]
    page = listed[:first_page]
    keys = {s["key"] for s in page}
    return page + [s for s in by_score if s["key"] not in keys]


def work(page: List[Dict[str, Any]], reads: Dict[str, Any], now: datetime, *,
         archives: Sequence[Dict[str, Any]] = (), classics: Sequence[str] = (),
         listed: Sequence[Dict[str, Any]] = ()) -> Dict[str, List[str]]:
    """What the first page asks to read: {follow: the suggestions whose test is due, and every `listed` one with a
    stored test by older rules; titles: the untitled pages whose title is due (not tweets): articles, the stories they
    started, archive rows' lines and `classics`}."""
    follow, titles = reads.get("follow", {}), reads.get("titles", {})
    lines = [line for s in page for line in (*s.get("articles", ()), *s.get("origin_stories", ()))]
    lines += [line for a in archives for line in a.get("origin_stories", ())]
    untitled = {line["url"] for line in lines if not line["title"]} | set(classics)
    keys = [s["key"] for s in page if due(follow.get(s["key"]), now, test=True)]
    keys += [s["key"] for s in listed if s["key"] in follow and due(follow[s["key"]], now, test=True)]
    return {"follow": list(dict.fromkeys(keys)),
            "titles": sorted(url for url in untitled if not is_tweet(url) and due(titles.get(url), now))}


async def read_first_page(stories: Any, http: Any, registry: Any, *,
                          clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> Dict[str, int]:
    """Read what the first page lacks (`work`) and the videos due, store each dated answer, then rebuild the list."""
    answer = await asyncio.to_thread(stories.discover_kept)
    classics = await asyncio.to_thread(stories.untitled_classics)
    with db.connection(stories.db_url) as conn, conn.cursor() as cur:
        reads = DiscoverRepository.reads(cur)
        todo = work(to_read(answer), reads, clock(),
                    archives=answer.get("archives", ()), classics=classics, listed=answer["suggestions"][FIRST_PAGE:])
        todo["videos"] = videos_due(DiscoverRepository.linked_videos(cur), reads, clock())
    if not todo["follow"] and not todo["titles"] and not todo["videos"]:
        return {"follow": 0, "titles": 0}
    gate = asyncio.Semaphore(FAN_OUT)
    limiter = HostLimiter()
    polite = Polite(http, limiter)

    async def test(key: str):
        async with gate:
            linked = await asyncio.to_thread(stories.linked_articles, "https://" + key)
            return key, {**await follow_read(http, registry, "https://" + key, linked, limiter), "at": clock().isoformat(),
                         "test": FOLLOW_TEST}

    async def title(url: str):
        async with gate:
            return url, {"title": await read_title(polite, url), "at": clock().isoformat()}

    async def video(url: str):
        async with gate:
            return url, {**await read_video(polite, url), "at": clock().isoformat()}

    tested = dict(await asyncio.gather(*map(test, todo["follow"])))
    titled = dict(await asyncio.gather(*map(title, todo["titles"])))
    channeled = dict(await asyncio.gather(*map(video, todo["videos"])))
    with db.transaction(stories.db_url) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('insight.discover_reads'))")
        reads = DiscoverRepository.reads(cur)
        reads["follow"] = {**reads.get("follow", {}), **tested}
        reads["titles"] = {**reads.get("titles", {}), **titled}
        reads["videos"] = {**reads.get("videos", {}), **channeled}
        DiscoverRepository.keep_reads(cur, reads)
    found = {url: r["channel"] for url, r in channeled.items() if r.get("channel")}
    moved = await asyncio.to_thread(stories.map_videos, found) if found else 0
    logger.info("Discover: %d follow tests, %d page titles, %d videos read (%d to a channel, %d addresses moved)",
                len(tested), len(titled), len(channeled), len(found), moved)
    await asyncio.to_thread(stories.refresh)   # the served answer, made with the new reads
    return {"follow": len(tested), "titles": len(titled), **({"videos": len(channeled)} if channeled else {})}


def keep(db_url: str, *, stories: Any = None, http: Any = None, registry: Any = None,
         people: Optional[Callable[[str], Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The jobs process's build (0206): Discover's answer rebuilt when due, its people kept, then `read_first_page`."""
    from insight_core.services.stories_service import StoriesService
    stories = stories or StoriesService(db_url)
    out: Dict[str, Any] = {"built": [], "follow": 0, "titles": 0}
    if stories.served_due():
        stories.refresh()
        out["built"].append("answer")
    out["people"] = (people or keep_people)(db_url)
    if enabled():
        if http is None:
            from concurrent.futures import ThreadPoolExecutor
            from insight_core.ingestion.http import KindHttp
            http = KindHttp(timeout=5, executor=ThreadPoolExecutor(max_workers=8, thread_name_prefix="discover-http"))
        if registry is None:
            from insight_core.services.source_fetch_service import archive_service
            registry = archive_service(db_url).kinds
        out.update(asyncio.run(read_first_page(stories, http, registry)))
    return out


def keep_people(db_url: str) -> Dict[str, Any]:
    """Discover's people and makers rebuilt when due; a failure is logged and returned, never raised."""
    from insight_core.db import database
    from insight_core.markx import discover_people
    try:
        with database.transaction(db_url) as cur:
            if not discover_people.due(cur):
                return {"built": False}
            return discover_people.keep(cur)
    except Exception as exc:  # noqa: BLE001 - derived; the older list stays served
        logger.exception("Discover: keeping the people failed")
        return {"failed": str(exc)[:300]}


__all__ = ["read_first_page", "keep", "keep_people", "read_video", "videos_due", "channel_key", "VIDEOS_PER_PASS", "label", "follow_read", "kind_read", "declared_accounts", "TRANSIENT_HOURS", "own_pages", "page_title", "to_read", "work", "due", "kind_source", "kind_test", "Polite", "LABELS",
           "FOLLOW_TEST", "enabled"]
