"""telegram_rss: Telegram channels through an RSS bridge (tg.i-c-a.su, the self-hosted one).

The bridge answers "Too many requests" (FLOOD_WAIT) when paged quickly, so live pages are
rate limited too (live_pages_rate_limited) and a live fetch reads only the pages it needs
for `limit`. That JSON answer is raised as HttpError(status=429), so the caller slows down. The source URL's query (e.g. ?limit=50, the bridge's page size) is kept on
every page URL.

The bridge dates an edited post by its edit (issue 0135: posted 2 Sep, shown 20 Sep). A channel's
message numbers grow with the time each was posted, so a post dated after a newer-numbered post
carries an edit time: it takes the newest date it can have, the earliest date of the posts numbered
after it (message_order_dates), and keeps the bridge's in metadata.bridge_date. The MTProto path
(telegram_mtproto) reads Telegram's own message date, never the edit date.

A forwarded message's item carries the bridge's forward header as <source url="https://t.me/<channel>/<post>">
title</source> (issue 0178); it is kept as metadata.forwarded_from {username, name, post, url} (forwarded_from), the
MTProto adapter's shape, so Mark X's voice rule (voice.counted_source) can match the channel's account.

The bridge the Add-source dialog builds a channel's address on (issue 0135): TELEGRAM_RSS_HOSTS, a
comma list of hosts or origins, the first one used ("telegram.local" when unset; set and empty: none,
and the dialog says so). Every host listed is read as a bridge, beside the known ones.
"""
from __future__ import annotations

import json
import math
import os
import re
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from insight_core.ingestion.http import HttpError, KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    PolitenessProfile,
    RateLimit,
    Source,
    resume_counts,
    start_at,
)
from insight_core.utils.json_safe import iso

KNOWN_BRIDGE_HOSTS = ("telegram.local", "tg.i-c-a.su", "127.0.0.1")
DEFAULT_BRIDGE = "https://telegram.local"
BRIDGE_ENV = "TELEGRAM_RSS_HOSTS"


def configured_bridges(env: Mapping[str, str] = os.environ) -> Optional[List[str]]:
    """The bridges TELEGRAM_RSS_HOSTS lists, as origins ("https://tg.example"); None when unset."""
    raw = env.get(BRIDGE_ENV)
    if raw is None:
        return None
    origins = []
    for item in raw.split(","):
        item = item.strip().rstrip("/")
        if item:
            origins.append(item if "://" in item else f"https://{item}")
    return origins


def bridge_origin(env: Mapping[str, str] = os.environ) -> Optional[str]:
    """The bridge a channel's address is built on: the first configured, DEFAULT_BRIDGE when
    TELEGRAM_RSS_HOSTS is unset, None when it is set and empty (no bridge)."""
    bridges = configured_bridges(env)
    if bridges is None:
        return DEFAULT_BRIDGE
    return bridges[0] if bridges else None


# Hosts that serve the bridge's /rss/<channel> feeds. gates.HOST_FLOORS gives each a 5s floor.
TELEGRAM_RSS_HOSTS = frozenset({*KNOWN_BRIDGE_HOSTS,
                                *((urllib.parse.urlparse(o).hostname or "").lower() for o in configured_bridges() or ())} - {""})


def message_order_dates(posts: List[Dict[str, Any]], newer: Optional[datetime] = None) -> Optional[datetime]:
    """Dates the bridge gave as an edit time put back in message order (issue 0135), in place: a post
    dated after a post numbered after it takes the earliest date of those (`newer`: the earliest date
    of the posts numbered after this page's), its bridge date kept in metadata.bridge_date. Returns
    the earliest date of the page and the posts after it, for the next (older) page."""
    floor = newer
    for post in sorted(posts, key=lambda p: int(p.get("external_id") or 0), reverse=True):
        date = post.get("date")
        if not isinstance(date, datetime):
            continue
        if floor is not None and date > floor:
            post["metadata"] = {**(post.get("metadata") or {}), "bridge_date": iso(date), "date_from": "message_order"}
            post["date"] = floor
            continue
        floor = date
    return floor

TELEGRAM_RSS_PROFILE = PolitenessProfile(
    concurrency_pool="host-lock",
    page_delay_s=5,
    batch_size=10,
    batch_cooldown_s=30,
    live_pages_rate_limited=True,
)

CANONICAL_RE = re.compile(r"^https://t\.me/(?P<username>[^/]+)/(?P<post_id>\d+)$")
# The bridge's forward (issue 0178): <source url="https://t.me/<channel>/<post>">Channel title</source>, the
# channel's username when it has one, else its numeric id (a private channel: no account to match).
FORWARD_RE = re.compile(r"^https?://(?:t|telegram)\.me/(?:s/)?(?P<channel>[A-Za-z0-9_]+)/(?P<post>\d+)/?(?:[?#].*)?$")
USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")


def forwarded_from(origin: Optional[Mapping[str, Any]], own: str = "") -> Optional[Dict[str, Any]]:
    """A bridge item's forward header (its <source>, parsing.rss_source) as metadata.forwarded_from, the shape
    the MTProto adapter stores: {username, name, post, url} (username: the channel's, so Pairing's voice rule
    matches t.me/<username>, Mark IX's account form), {channel_id, name, post, url} for a channel known by id
    only. `name` is the channel's title, else "@username". None for no forward, one from the channel itself
    (`own`, its username), or a source that is no Telegram post."""
    if not origin:
        return None
    match = FORWARD_RE.match(str(origin.get("url") or "").strip())
    if not match:
        return None
    channel, title = match.group("channel"), " ".join(str(origin.get("title") or "").split())
    out: Dict[str, Any] = {"post": int(match.group("post")), "url": f"https://t.me/{channel}/{match.group('post')}"}
    if USERNAME_RE.match(channel):
        if own and channel.casefold() == own.lstrip("@").casefold():
            return None
        out["username"] = channel
        out["name"] = title or f"@{channel}"
    elif channel.isdigit():
        out["channel_id"] = int(channel)
        out["name"] = title or None
    else:
        return None
    return out


class TelegramRssKind(BaseKind):
    name = "telegram_rss"
    chronological = True   # newest first: an archive back to a date stops past it (issue 0130 C)
    available_basis = "upper_bound"   # the newest post number; deleted posts still count
    profile = TELEGRAM_RSS_PROFILE

    def __init__(self, http: KindHttp) -> None:
        self.http = http

    def matches(self, source: Source) -> bool:
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        segments = parsing.path_segments(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in TELEGRAM_RSS_HOSTS and len(segments) >= 2 and segments[0] == "rss"

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "telegram_page" and bool(
            checkpoint.get("next_page")
        )

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        collected: List[Dict[str, Any]] = []
        rate = self.profile.rate_limit()
        async for page in self._pages(str(source["handle_or_url"]), limit, start_page=1,
                                      initial_collected=0, initial_pages=0, rate=rate):
            collected.extend(page.posts)
        return collected[:limit]

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        initial_collected, initial_pages = resume_counts(checkpoint)
        start_page = int((checkpoint or {}).get("next_page") or 1)
        async for page in self._pages(str(source["handle_or_url"]), target, start_page=start_page,
                                      initial_collected=initial_collected, initial_pages=initial_pages,
                                      rate=None):
            yield page

    async def inspect(self, source: Source) -> Inspection:
        source_url = str(source["handle_or_url"])
        page_one = await self.fetch_page(source_url, 1)
        if not page_one:
            raise ValueError(f"No canonical Telegram posts found for {_username(source_url)}")

        highest_post_id = max(int(post["external_id"]) for post in page_one if post.get("external_id"))
        page_size = max(1, len(page_one))
        last_page_number = await self._find_last_page(source_url, highest_post_id, page_size)
        last_page = await self.fetch_page(source_url, last_page_number)
        oldest = last_page[-1]["date"] if last_page else None
        return Inspection(highest_post_id, page_size, iso(oldest))

    async def _pages(self, source_url: str, target: int, *, start_page: int, initial_collected: int,
                     initial_pages: int, rate: Optional[RateLimit]):
        """Pages from start_page until target posts (counting initial_collected) are reached. With a
        rate (a live fetch) the pause between pages is slept here; an archive passes None, its
        loop paces the pages."""
        seen_urls: set[str] = set()
        collected = initial_collected
        pages_fetched = initial_pages
        page = max(1, start_page)
        newer: Optional[datetime] = None   # the earliest date of the pages read so far (issue 0135)

        while collected < target:
            page_posts = await self.fetch_page(source_url, page)
            if not page_posts:
                break
            newer = message_order_dates(page_posts, newer)

            pages_fetched += 1
            unique: List[Dict[str, Any]] = []
            for post in page_posts:
                if post["url"] in seen_urls:
                    continue
                seen_urls.add(post["url"])
                unique.append(post)
                collected += 1
                if collected >= target:
                    break

            yield ArchivePage(unique, {
                "mode": "telegram_page",
                "next_page": page + 1,
                "last_page": page,
                "pages_fetched": pages_fetched,
                "collected_posts": collected,
            })
            page += 1
            if rate is not None and collected < target:
                await self.http.sleep(rate.delay_after(pages_fetched))

    async def start_checkpoint(self, source: Source, stored) -> Optional[dict]:
        # Pages are numbered from the newest, so page stored // page size is at or before the
        # oldest stored post. The raw page size, not the filtered count: that would skip posts.
        source_url = str(source["handle_or_url"])
        limit = urllib.parse.parse_qs(urllib.parse.urlparse(source_url).query).get("limit", [""])[0]
        page_size = int(limit) if limit.isdigit() else len(await self._feed_items(source_url, 1))
        return start_at(mode="telegram_page", next_page=max(1, int(stored["post_count"]) // max(1, page_size)))

    async def _feed_items(self, source_url: str, page: int) -> List[Dict[str, Any]]:
        """Every item of one page as the bridge lists it (sponsored and non-canonical ones too)."""
        body, _ = await self.http.get_text(page_url(source_url, page))

        if body.lstrip().startswith("{"):
            payload = json.loads(body)
            errors = payload.get("errors", payload)
            if "too many requests" in str(errors).lower():
                # The bridge answers its flood limit as a JSON body, not a 429 (issue 0016).
                raise HttpError(f"HTTP 429 from {page_url(source_url, page)}: {errors}", status=429)
            raise ValueError(errors)
        origin = parsing.origin_from_source(source_url, parsing.TELEGRAM_BASE_URL)
        return parsing.parse_feed_posts(body, f"{origin}/rss/{_username(source_url)}")

    async def fetch_page(self, source_url: str, page: int) -> List[Dict[str, Any]]:
        origin = parsing.origin_from_source(source_url, parsing.TELEGRAM_BASE_URL)
        canonical: List[Dict[str, Any]] = []
        for post in await self._feed_items(source_url, page):
            match = CANONICAL_RE.match(post["url"])
            if not match or post.get("title", "").startswith("[Sponsored]"):
                continue
            post["title"] = parsing.strip_telegram_media_tag(post.get("title", ""))
            post["external_id"] = match.group("post_id")
            post["url"] = f"https://t.me/{match.group('username')}/{match.group('post_id')}"
            post["content_html"] = parsing.normalize_telegram_resources(post.get("content_html", ""), origin)
            post["content"] = parsing.strip_html(post["content_html"])
            post["media_urls"] = [
                parsing.normalize_telegram_resources(media_url, origin) for media_url in post.get("media_urls", [])
            ]
            forward = forwarded_from(post.pop("origin_item", None), match.group("username"))
            if forward is not None:
                post["metadata"] = {**(post.get("metadata") or {}), "forwarded_from": forward}
            canonical.append(post)
        return canonical

    async def _find_last_page(self, source_url: str, highest_post_id: int, page_size: int) -> int:
        low = 1
        high = max(1, math.ceil(highest_post_id / max(page_size, 1)))

        while await self._page_has_posts(source_url, high):
            low = high
            high *= 2

        while low < high:
            mid = (low + high + 1) // 2
            if await self._page_has_posts(source_url, mid):
                low = mid
            else:
                high = mid - 1
        return low

    async def _page_has_posts(self, source_url: str, page: int) -> bool:
        return bool(await self.fetch_page(source_url, page))


def _username(source_url: str) -> str:
    segments = parsing.path_segments(source_url)
    if len(segments) < 2 or segments[0] != "rss":
        raise ValueError(f"Invalid Telegram RSS URL: {source_url}")
    return segments[1]


def page_url(source_url: str, page: int) -> str:
    """{origin}/rss/{channel}/{page}, keeping the source URL's query (?limit=N = page size)."""
    origin = parsing.origin_from_source(source_url, parsing.TELEGRAM_BASE_URL)
    query = urllib.parse.urlparse(source_url).query
    url = f"{origin}/rss/{_username(source_url)}/{page}"
    return f"{url}?{query}" if query else url
