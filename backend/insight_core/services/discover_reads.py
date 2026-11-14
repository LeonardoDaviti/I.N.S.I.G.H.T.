"""What Discover reads of the web, for its first page only (issue 0080: Discover tested nothing, and
75% of its lines had no title but one made from the address).

For each suggestion on the first page (StoriesService.discover, FIRST_PAGE), at most once in CHECK_DAYS:
- **the follow test**: the path every source add takes (where_linked.follow: the feed finder, then page
  watching), labelled "feed" (Feed found), "page" (Page watching: a page whose articles it reads),
  "blocked" (Blocks readers: every request it made was refused with 401 or 403) or "headlines"
  (Headlines only: anything else, a paywall or no feed and a page it can't read). A platform account
  INSIGHT follows by a source kind (an X account through the Nitter bridge, a Telegram channel, a
  subreddit, a YouTube channel: `kind_source`, issue 0109) is tested through that kind instead: one
  read of the address the kind reads, "feed" when it answers with posts. A test made by older rules
  (FOLLOW_TEST) is made again wherever its suggestion is listed;
- **the titles** of the pages it lists that have none (no stored post, no evidence: services/page_titles.py),
  its articles' and the stories they started, and the archive rows' lines (issue 0106); and Classics'
  untitled pages: the page's own title, as page watching reads one (page_watch.page_title), from the
  start of the page. Tweets are never read: their line names the account.
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
from typing import Any, Callable, Dict, List, Optional, Sequence

from insight_core.db import database as db
from insight_core.db.repo_discover import DiscoverRepository
from insight_core.ingestion import where_linked
from insight_core.ingestion.gates import HostLimiter
from insight_core.ingestion.http import HttpError
from insight_core.ingestion.kinds import page_watch, parsing
from insight_core.ingestion.kinds.nitter_rss import NITTER_BASE_URL
from insight_core.ingestion.kinds.parsing import TELEGRAM_BASE_URL
from insight_core.utils.addresses import ACCOUNT_NAMESPACES, PLATFORM_SITES, host_of, is_tweet, publication_of, site_of
from insight_core.utils.discover_rules import CHECK_DAYS, FIRST_PAGE, FOLLOWABLE, UNFOLLOWABLE

logger = logging.getLogger(__name__)

PAGE_BYTES = 512 * 1024      # the start of a page read for its title (its <head>)
FAN_OUT = 4                  # hosts read at once
TITLE_CHARS = 300
BLOCKED = (401, 403)
LABELS = ("feed", "page", "headlines", "blocked", "other_feed")
# The rules a follow test is made by (issue 0109: platform accounts through their kind): a stored test
# by other rules is due again.
FOLLOW_TEST = 4   # 2: platform accounts through their kind; 3: "feed" only for a feed of the linked pages;
#                   4 (issue 0172): where it landed (moved_to), its own pages' sections, its declared account, transient
KIND_POSTS = 3           # the posts a platform account's kind is asked for
# Issue 0172 b6: a test that failed for a passing reason (a bridge's error, a timeout, a 5xx, a 429) is asked again
# after this, not after CHECK_DAYS (a bridge's hiccup had labelled an X account "headlines" for 30 days).
TRANSIENT_HOURS = 6
SECTIONS_TRIED = 2       # b7: the sections of a site's own linked pages its test tries when its home page gives none
_ACCOUNT = re.compile(r"^[\w.@-]+$")
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
        self.troubled = 0   # refusals for a passing reason: a 5xx, a timeout, a 429 (issue 0172 b6)

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
    """The follow test's label of where_linked.follow's answer and the requests it made. A feed is "feed" only
    when it holds one of the linked pages, or when none were linked (issue 0109 W9: a hub's owners were
    "Feed found" by the hub's own blog feed); else "other_feed": a feed, but not of these pages."""
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
    """The linked pages that are a suggestion's own (issue 0109): on a platform's owner (hub.example/owner),
    those under its path; on a site, all its host's (www. aside, case aside in the path)."""
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
    """The source a platform account is followed as (issue 0109 W1): the address its source kind reads, as
    the Add source templates write it (x.com/<user> -> the Nitter bridge's /<user>/rss; t.me/<channel> ->
    the Telegram bridge's /rss/<channel>; reddit.com/r/<sub> -> r/<sub>; youtube.com/@<channel> -> the
    channel), when a kind of `registry` reads it (KindRegistry.resolve: not the generic feed reader nor
    page watching). None for a site, an owner on a platform no kind reads (a code or model hub's) or a
    kind of page."""
    host, _, rest = key.partition("/")
    segments = [s for s in rest.split("/") if s]
    site = site_of(host)
    if not segments or not all(_ACCOUNT.match(s) for s in segments):
        return None
    source: Optional[Dict[str, str]] = None
    if site in PLATFORM_SITES["x"] and len(segments) == 1:
        source = {"platform": "rss", "handle_or_url": f"{NITTER_BASE_URL}/{segments[0].lstrip('@')}/rss"}
    elif site in PLATFORM_SITES["telegram"] and site != "telegram.org" and len(segments) == 1:
        source = {"platform": "rss", "handle_or_url": f"{TELEGRAM_BASE_URL}/rss/{segments[0]}?limit=50"}
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
    """A platform account's follow test (issue 0109): its kind's latest posts, as a fetch run reads them.
    {label: "feed" when there are some, "blocked" when the read was refused with 401 or 403, else "headlines";
    transient: true when it failed for a passing reason (issue 0172 b6: the bridge's error, a timeout, a 5xx)}."""
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
    """The platform accounts a site's page links to (its "follow us" links, issue 0172 b5), that a source kind
    reads (kind_source), the most linked first: x.com/<name>, t.me/<name>, youtube.com/@<name>, reddit.com/r/<name>.
    A post (a tweet's status), a share or intent page names no account."""
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
    """The sections a site's own linked pages sit in (their first path segment, not a date or a number), the most
    pages first, at most SECTIONS_TRIED, as addresses (issue 0172 b7)."""
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
    """The follow test (module doc), as stored: {label, moved_to? (the site it landed on, when another: issue 0172
    b1), url? (the section of its own pages that can be followed when its home page gives nothing: b7), account?
    ({url, label}: the account it declares, a kind reads and that answers, when it can't be followed itself: b5),
    transient? (failed for a passing reason: asked again within TRANSIENT_HOURS, b6)}."""
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
    """The first account a site's home page declares that its kind can read now (issue 0172 b5), as {url, label}."""
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
    """A page's own title (page_watch.page_title), None when it has none, only its address, or only its site's
    name (issue 0109 W7: a wall or a script page answers with its site's <title>, its og:site_name)."""
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


def due(read: Optional[Dict[str, Any]], now: datetime, *, test: bool = False) -> bool:
    """Never read, or read CHECK_DAYS ago or more (TRANSIENT_HOURS for one that failed for a passing reason, issue
    0172 b6); a follow test (`test`), also one by older rules (FOLLOW_TEST)."""
    try:
        again = timedelta(hours=TRANSIENT_HOURS) if read and read.get("transient") else timedelta(days=CHECK_DAYS)
        return (read is None or (test and read.get("test") != FOLLOW_TEST)
                or now - datetime.fromisoformat(read["at"]) >= again)
    except (AttributeError, KeyError, TypeError, ValueError):
        return True


def to_read(answer: Dict[str, Any], *, first_page: int = FIRST_PAGE) -> List[Dict[str, Any]]:
    """The suggestions whose lines and tests are read (issue 0109): the first page, and the first page's count
    by score alone wherever they are listed (the tested come first, so an untested one with more stories
    would otherwise wait behind them, never tested)."""
    listed = answer["suggestions"]
    by_score = sorted(listed, key=lambda s: (-s.get("score", 0), s["key"]))[:first_page]
    page = listed[:first_page]
    keys = {s["key"] for s in page}
    return page + [s for s in by_score if s["key"] not in keys]


def work(page: List[Dict[str, Any]], reads: Dict[str, Any], now: datetime, *,
         archives: Sequence[Dict[str, Any]] = (), classics: Sequence[str] = (),
         listed: Sequence[Dict[str, Any]] = ()) -> Dict[str, List[str]]:
    """What the first page asks to read: the suggestions whose follow test is due, and every `listed` one
    whose stored test was made by older rules (issue 0109: the X accounts the finder called headlines had
    sunk out of the first page); the pages whose title is due and that have none (not tweets): its
    suggestions' articles and the stories they started, the archive rows' lines (issue 0106: one title per
    page, whichever line shows it) and the untitled `classics`."""
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
    """Read what the first page lacks (`work`), and Classics' untitled pages (issue 0106), and store each
    answer with its date; then make and keep Discover's list once (issue 0080 cold open: the answers change
    its inputs, so the next open, in any process, reads it instead of making it). Returns how many."""
    answer = await asyncio.to_thread(stories.discover)
    classics = await asyncio.to_thread(stories.untitled_classics)
    with db.connection(stories.db_url) as conn, conn.cursor() as cur:
        todo = work(to_read(answer), DiscoverRepository.reads(cur), clock(),
                    archives=answer.get("archives", ()), classics=classics, listed=answer["suggestions"][FIRST_PAGE:])
    if not todo["follow"] and not todo["titles"]:
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

    tested = dict(await asyncio.gather(*map(test, todo["follow"])))
    titled = dict(await asyncio.gather(*map(title, todo["titles"])))
    with db.transaction(stories.db_url) as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('insight.discover_reads'))")
        reads = DiscoverRepository.reads(cur)
        reads["follow"] = {**reads.get("follow", {}), **tested}
        reads["titles"] = {**reads.get("titles", {}), **titled}
        DiscoverRepository.keep_reads(cur, reads)
    logger.info("Discover: %d follow tests, %d page titles read", len(tested), len(titled))
    await asyncio.to_thread(stories.refresh)   # the answer served, made with the answers (issue 0172 c1)
    return {"follow": len(tested), "titles": len(titled)}


def keep(db_url: str, *, stories: Any = None, http: Any = None, registry: Any = None) -> Dict[str, Any]:
    """Issue 0206, the jobs process (markx/jobs.py, the view "discover", wanted by an open: services/stories_service.
    discover_served): Discover's answer made again when it is due (StoriesService.refresh), then what its first page
    lacks read over the web (`read_first_page`, which makes it again when it read anything; off with
    INSIGHT_DISCOVER_READS=0). Was: in the API process, in the background of an open (255-300 s on the server, with
    the API's memory)."""
    from insight_core.services.stories_service import StoriesService
    stories = stories or StoriesService(db_url)
    out: Dict[str, Any] = {"built": [], "follow": 0, "titles": 0}
    if stories.served_due():
        stories.refresh()
        out["built"].append("answer")
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


__all__ = ["read_first_page", "keep", "label", "follow_read", "kind_read", "declared_accounts", "TRANSIENT_HOURS", "own_pages", "page_title", "to_read", "work", "due", "kind_source", "kind_test", "Polite", "LABELS",
           "FOLLOW_TEST", "enabled"]
