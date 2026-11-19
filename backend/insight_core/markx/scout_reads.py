"""A test read (issues 0148 §3, 0162 §4): one candidate source read the way the Add source path would follow it, its
newest items kept in a scratch area, and its health. Nothing is followed, nothing is stored as a post.

    reader = Reader(http, registry)
    got = await reader.read("https://example.org/blog/", limit=20)
    got.resolved   # {platform, handle_or_url, settings, via: kind | feed | page, title}, or None: can't read
    got.items      # [{url, title, text, published_at, lang, chars, transcript}], newest first
    got.reason     # "" when read; else why not (the finder's reason: blocked, gone, NOTHING: no feed and no dated list)
    health(got.items, now)   # {items, dated, median_chars, lang, per_week, newest_days, reads_well, reason, labels}

**How it reads (the add path, no other):** an account INSIGHT reads by a source kind (an X account through the bridge,
a Telegram channel, a subreddit, a YouTube channel: discover_reads.kind_source) through that kind; anything else through
where_linked.follow (the feed finder, then page watching): its first feed that is the page's own (not flagged as the
site's), else its first page to watch. A feed is parsed with the fetcher's own parser (parsing.parse_feed_posts); a
watched page's articles are read one by one as page watching reads them (page_watch.post_from), never dated "now":
an article with no date of its own stays undated, so an undated source shows as one.

**Scrape regardless of a feed** (issue 0240, owner 2026-11-19): this is the one test read of the scout, the daily judge,
a tap's judgement and the official channels (through source_judge), and Discover's follow test takes the same
where_linked.follow. When the finder finds no feed and no page, follow previews the pages that list the site's
announcements (page_watch.list_offers: the page itself, its section, its sitemap's news sections, /news, /newsroom,
/press, /blog) and offers the first dated one; only when that fails too is the source unreadable (NOTHING). A feed
whose items are undated or titles only is read from its items' own pages (`_from_pages`, at most DATE_PAGES): the date
each page states (page_watch.page_dating: markup, address, then body), the article text; so a titles-only feed dated
by its article pages is a dated stream. Still reading badly, the page offered beside it is read instead when better.

**Health** (0135's silent failures, 0149's classes, measured on the item list alone): no items; undated (fewer than half
the items carry a date); titles only (the median text under NO_TEXT_CHARS); stopped (the newest item older than
STOPPED_DAYS). Any of them: "can't read well: <why>", never suggested as working. Labels that don't stop a suggestion:
summaries only (median under SUMMARY_CHARS), its language when not English, no transcripts (videos without one).

The requests a read makes are counted (`requests`): every request through the read's own client, and one for a source
kind's read (its client is the kind's). The caller budgets them.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence

log = logging.getLogger(__name__)

ITEMS = 20                       # the newest items a test read keeps
KIND_ITEMS = {"youtube_channel": 8}   # a video's read is heavy (its details and transcript): fewer of them
TEXT_CHARS = 4000                # an item's text kept in the scratch area
NO_TEXT_CHARS = 40               # median text under this: titles only
SUMMARY_CHARS = 400              # median text under this: summaries only (a label)
STOPPED_DAYS = 120               # the newest item older than this: stopped
DATED_SHARE = 0.5                # fewer than this share dated: undated
PAGE_GAP_S = 1.0                 # between two article pages of one watched page
PAGE_SKIPS = 5                   # article pages that are no post, read at most besides the items
DATE_PAGES = 10                  # 0240: a feed's undated or titles-only items read from their own pages, at most
# Every way in failed (0240): the feed finder, page watching on the page, its section and the site's list pages.
NOTHING = "no feed, and no page that lists dated articles: the page, its section, its news, blog and press pages"


@dataclass
class ReadResult:
    resolved: Optional[Dict[str, Any]] = None
    items: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    requests: int = 0


class Counting:
    """An http client whose every request is counted (the caller's budget), one host at a time with a limiter."""

    def __init__(self, http: Any, limiter: Any = None) -> None:
        self.http, self.limiter, self.requests = http, limiter, 0

    async def _call(self, name: str, url: str, *args: Any, **kwargs: Any) -> Any:
        self.requests += 1
        if self.limiter is None:
            return await getattr(self.http, name)(url, *args, **kwargs)
        from insight_core.services.discover_reads import slot
        async with self.limiter.slot(slot(url)):
            return await getattr(self.http, name)(url, *args, **kwargs)

    async def get_start(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return await self._call("get_start", url, *args, **kwargs)

    async def get_text(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return await self._call("get_text", url, *args, **kwargs)

    async def get_json(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return await self._call("get_json", url, *args, **kwargs)

    async def get_conditional(self, url: str, *args: Any, **kwargs: Any) -> Any:
        return await self._call("get_conditional", url, *args, **kwargs)

    async def sleep(self, seconds: float) -> None:
        if seconds > 0:
            await asyncio.sleep(seconds)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.http, name)


def _iso(value: Any) -> Optional[str]:
    return value.astimezone(timezone.utc).isoformat() if isinstance(value, datetime) else None


def item_of(post: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A post draft (a kind's, the feed parser's, page watching's) as a scratch item; None without an address."""
    from insight_core.utils.language_detection import detect_language
    url = post.get("url") or post.get("guid")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    meta = post.get("metadata") or {}
    text = str(post.get("content") or meta.get("description") or "").strip()
    title = " ".join(str(post.get("title") or "").split())[:500]
    when = post.get("date")
    lang = post.get("language_code") or detect_language(f"{title}\n{text[:2000]}").get("language_code") or "und"
    video = meta.get("kind") == "youtube_video"
    return {"url": url, "title": title, "text": text[:TEXT_CHARS], "chars": len(text),
            "published_at": when if isinstance(when, datetime) else None, "lang": str(lang),
            "transcript": bool(meta.get("transcript_source")) if video else None}


def health(items: Sequence[Dict[str, Any]], now: Optional[datetime] = None) -> Dict[str, Any]:
    """What a test read's items say about the source (see the module docstring): {items, dated, median_chars, lang,
    per_week, newest_days, reads_well, reason, labels}."""
    now = now or datetime.now(timezone.utc)
    n = len(items)
    dates = sorted((i["published_at"] for i in items if isinstance(i.get("published_at"), datetime)), reverse=True)
    chars = [int(i.get("chars") or 0) for i in items]
    median = int(statistics.median(chars)) if chars else 0
    langs = Counter(str(i.get("lang") or "und") for i in items)
    lang = next((code for code, _ in langs.most_common() if code != "und"), "und")
    newest_days = max(0, int((now - dates[0]).total_seconds() // 86400)) if dates else None
    per_week = None
    if len(dates) >= 2:
        span = max((dates[0] - dates[-1]).total_seconds() / 86400.0, 1.0)
        per_week = round((len(dates) - 1) * 7.0 / span, 1)
    elif len(dates) == 1:
        per_week = 0.0
    reason = ""
    if not n:
        reason = "no items"
    elif len(dates) < DATED_SHARE * n:
        reason = f"undated: {n - len(dates)} of {n} items have no date"
    elif median < NO_TEXT_CHARS:
        reason = "titles only: its items carry no text"
    elif newest_days is not None and newest_days > STOPPED_DAYS:
        reason = f"stopped: the newest item is {newest_days} days old"
    labels: List[str] = []
    if n and not reason and median < SUMMARY_CHARS:
        labels.append("summaries only")
    if lang not in ("en", "und"):
        labels.append(f"in {lang}")
    videos = [i for i in items if i.get("transcript") is not None]
    if videos and sum(1 for i in videos if i["transcript"]) < len(videos) / 2:
        labels.append("no transcripts")
    return {"items": n, "dated": len(dates), "median_chars": median, "lang": lang, "per_week": per_week,
            "newest_days": newest_days, "reads_well": not reason, "reason": reason, "labels": labels}


def _better(a: Sequence[Dict[str, Any]], b: Sequence[Dict[str, Any]]) -> bool:
    """Whether items a read better than items b (0240): reads well first, then the more dated items."""
    ha, hb = health(a), health(b)
    return (ha["reads_well"], ha["dated"]) > (hb["reads_well"], hb["dated"])


def cadence_words(per_week: Optional[float]) -> str:
    """"3 a week", "2 a month", "less than one a month"."""
    if per_week is None:
        return ""
    if per_week >= 1:
        return f"{round(per_week):g} a week"
    month = per_week * 30 / 7
    return f"{round(month):g} a month" if month >= 1 else "less than one a month"


def _reason_of(error: BaseException) -> str:
    from insight_core.ingestion.feed_finder import REASON_BY_STATUS
    status = getattr(error, "status", None)
    if status in REASON_BY_STATUS:
        return REASON_BY_STATUS[status]
    if getattr(error, "timed_out", False):
        return "no answer in time"
    if isinstance(status, int) and status >= 500:
        return "server error"
    return "could not be read"


Read = Callable[..., Awaitable[ReadResult]]


class Reader:
    """Test reads on one http client and kind registry (the server's fetcher: the API's own client)."""

    def __init__(self, http: Any, registry: Any, *, limiter: Any = None, page_gap: float = PAGE_GAP_S) -> None:
        self.http, self.registry, self.limiter, self.page_gap = http, registry, limiter, page_gap

    async def read(self, address: str, *, linked: Sequence[str] = (), limit: int = ITEMS) -> ReadResult:
        from insight_core.services.discover_reads import kind_source
        client = Counting(self.http, self.limiter)
        try:
            source = kind_source(address.split("://", 1)[-1], self.registry)
            if source is not None:
                got = await self._kind(source, limit, via="kind")
            else:
                got = await self._follow(client, address, linked, limit)
        except Exception as exc:  # noqa: BLE001 - a candidate that can't be read says why; never raised
            log.info("Scout: %s could not be read (%s)", address, type(exc).__name__)
            got = ReadResult(reason=_reason_of(exc))
        got.requests += client.requests
        got.items = got.items[:limit]
        return got

    async def _kind(self, source: Dict[str, Any], limit: int, *, via: str, title: str = "") -> ReadResult:
        kind = self.registry.resolve(source)
        n = min(limit, KIND_ITEMS.get(kind.name, limit))
        posts = await kind.fetch_latest(source, n)
        items = [i for i in (item_of(p) for p in list(posts or [])) if i]
        resolved = {"platform": source["platform"], "handle_or_url": source["handle_or_url"],
                    "settings": dict(source.get("settings") or {}), "via": via, "title": title}
        return ReadResult(resolved=resolved, items=items, requests=1)

    async def _follow(self, client: Counting, address: str, linked: Sequence[str], limit: int) -> ReadResult:
        from insight_core.ingestion import where_linked
        from insight_core.ingestion.kinds import parsing
        found = await where_linked.follow(client, self.registry, address, list(linked))
        pages = [p for p in found.get("pages") or [] if p.get("items")]
        if found.get("status") == "direct":
            source = {"platform": "rss", "handle_or_url": address}
            got = await self._kind(source, limit, via="kind")
            await self._from_pages(client, got)
            return got
        feeds = list(found.get("feeds") or [])
        feeds.sort(key=lambda f: bool(f.get("not_this_page")))
        if feeds:
            feed = feeds[0]
            text, _ = await client.get_text(feed["url"])
            items = [i for i in (item_of(p) for p in parsing.parse_feed_posts(text, feed["url"])) if i][:limit]
            got = ReadResult(resolved={"platform": "rss", "handle_or_url": feed["url"], "settings": {}, "via": "feed",
                                       "title": feed.get("title") or ""}, items=items)
            await self._from_pages(client, got)
            if pages and not health(got.items)["reads_well"]:
                # The feed reads badly even from its pages (0240): the page offered beside it, when it reads better.
                other = await self._page(client, pages[0], limit)
                if _better(other.items, got.items):
                    return other
            return got
        if pages:
            return await self._page(client, pages[0], limit)
        from insight_core.ingestion.feed_finder import NONE_FOUND
        reason = found.get("refused") or found.get("reason") or NOTHING
        return ReadResult(reason=NOTHING if reason == NONE_FOUND else reason)

    async def _from_pages(self, client: Counting, got: ReadResult) -> None:
        """Issue 0240: a feed read whose items are undated or titles only (health) is read from its items' own pages,
        at most DATE_PAGES of them, the newest first: each undated item takes the date its page states
        (page_watch.page_dating: its markup, then its address's day, only then its byline or one written date; one
        the address contradicts is held), each titles-only item the page's article text. `got.resolved["from_pages"]`:
        how many items a page dated or filled. A page that can't be read is skipped."""
        from insight_core.ingestion.kinds import page_watch
        why = health(got.items)["reason"]
        if not got.items or not why.startswith(("undated", "titles only")):
            return
        thin = [i for i in got.items if i.get("published_at") is None or int(i.get("chars") or 0) < NO_TEXT_CHARS]
        filled = 0
        for n, item in enumerate(thin[:DATE_PAGES]):
            if n and self.page_gap:
                await asyncio.sleep(self.page_gap)
            try:
                page, _ = await client.get_text(item["url"])
            except Exception:  # noqa: BLE001 - one unreadable article page stays as the feed gave it
                continue
            changed = False
            if item.get("published_at") is None:
                date, _how = page_watch.page_dating(page, item["url"])
                if date is not None:
                    item["published_at"], changed = date, True
            if int(item.get("chars") or 0) < NO_TEXT_CHARS:
                post = page_watch.article_post(page, item["url"], item["url"], None, adapter=page_watch.PageWatchKind.adapter_type)
                text = str((post or {}).get("content") or "").strip()
                if len(text) >= NO_TEXT_CHARS:
                    item["text"], item["chars"], changed = text[:TEXT_CHARS], len(text), True
            filled += changed
        if filled and got.resolved is not None:
            got.resolved["from_pages"] = filled

    async def _page(self, client: Counting, offer: Dict[str, Any], limit: int) -> ReadResult:
        from insight_core.ingestion.kinds import page_watch
        url, prefix = offer["url"], offer.get("prefix") or ""
        found = await page_watch.discover(client, url, prefix or None)
        items: List[Dict[str, Any]] = []
        skips = 0
        for n, candidate in enumerate(found.candidates()):
            if len(items) >= limit or skips >= PAGE_SKIPS:
                break
            if n and self.page_gap:
                await asyncio.sleep(self.page_gap)
            try:
                page, _ = await client.get_text(candidate)
            except Exception:  # noqa: BLE001 - one unreadable article is a skip
                skips += 1
                continue
            post = page_watch.post_from(page, url, candidate, found.sitemap.get(candidate), new=False)
            item = item_of(post) if post else None
            if item is None:
                skips += 1
                continue
            items.append(item)
        resolved = {"platform": "rss", "handle_or_url": url, "settings": {"page_watch": {"prefix": prefix}},
                    "via": "page", "title": ""}
        return ReadResult(resolved=resolved, items=items)


__all__ = ["Counting", "ITEMS", "ReadResult", "Reader", "cadence_words", "health", "item_of"]
