"""bluesky: a Bluesky profile (https://bsky.app/profile/<handle or did>) read on the public AppView (issue 0137 B10).

Behind INSIGHT_BLUESKY (default off): off, the kind matches nothing and a bsky.app address goes to
generic_rss as before (a profile's own RSS link, when the finder sees one). On, the feed finder
answers "direct" for a profile address, as for every kind but generic_rss.

- The profile first (app.bsky.actor.getProfile): an account labelled `!no-unauthenticated` asks not to
  be shown to logged-out readers. INSIGHT reads logged out, so nothing is read: KindUnavailable says so.
- Its posts (app.bsky.feed.getAuthorFeed, filter posts_no_replies), newest first, paged by the API's
  cursor (the archive's checkpoint). A repost of someone else's post is skipped (its author is not the
  source's); a post quoting another keeps its own text.
- A post has no title on Bluesky: its text's first line, its spaces single, at most TITLE_MAX characters.
- Its address is https://bsky.app/profile/<handle>/post/<rkey>; external_id the rkey; its date the
  record's createdAt.
All its sources share one host key, so the host floor (gates.HOST_FLOORS) spaces them.
"""
from __future__ import annotations

import json
import os
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import parsing
from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    KindUnavailable,
    PolitenessProfile,
    RateLimit,
    Source,
    resume_counts,
)

SWITCH = "INSIGHT_BLUESKY"
API = "https://public.api.bsky.app/xrpc"
PROFILE_HOSTS = frozenset({"bsky.app", "www.bsky.app"})
BLUESKY_HOST_KEY = "platform:bluesky"
OPT_OUT_LABEL = "!no-unauthenticated"
OPTED_OUT = "the account asks not to be shown to logged-out readers"
PAGE_SIZE = 50          # the API's most per page is 100
TITLE_MAX = 120

BLUESKY_PROFILE = PolitenessProfile(concurrency_pool="host-lock", page_delay_s=1)


def enabled(env: Any = None) -> bool:
    """The switch, read when asked (default off)."""
    return str((env if env is not None else os.environ).get(SWITCH, "off")).strip().lower() in ("on", "1", "true", "yes")


def actor(url: str) -> Optional[str]:
    """The handle or did of a profile address (bsky.app/profile/<actor>), else None."""
    try:
        parsed = urllib.parse.urlparse(url if "://" in url else f"https://{url}")
    except ValueError:
        return None
    segments = [segment for segment in parsed.path.split("/") if segment]
    if (parsed.hostname or "").lower() not in PROFILE_HOSTS or len(segments) < 2 or segments[0] != "profile":
        return None
    return segments[1]


def title_from(text: str) -> str:
    """A post's title: its text's first non-empty line, its spaces single, capped at TITLE_MAX."""
    line = next((" ".join(part.split()) for part in (text or "").splitlines() if part.strip()), "")
    return line if len(line) <= TITLE_MAX else line[:TITLE_MAX - 1].rstrip() + "…"


def opted_out(profile: Dict[str, Any]) -> bool:
    return any(isinstance(label, dict) and label.get("val") == OPT_OUT_LABEL for label in profile.get("labels") or [])


def feed_posts(payload: Dict[str, Any], did: Optional[str], source_url: str) -> List[Dict[str, Any]]:
    """The author's own posts in one getAuthorFeed page (reposts of others skipped)."""
    posts: List[Dict[str, Any]] = []
    for row in payload.get("feed") or []:
        post = row.get("post") or {}
        author = post.get("author") or {}
        reason = (row.get("reason") or {}).get("$type", "")
        if "reasonRepost" in reason or (did and author.get("did") != did):
            continue
        record = post.get("record") or {}
        uri = str(post.get("uri") or "")
        rkey = uri.rsplit("/", 1)[-1] if uri else ""
        if not rkey:
            continue
        handle = author.get("handle") or author.get("did") or ""
        text = str(record.get("text") or "")
        media = [image.get("fullsize") for image in ((post.get("embed") or {}).get("images") or [])
                 if isinstance(image, dict) and image.get("fullsize")]
        posts.append({
            "platform": "bluesky",
            "source": source_url,
            "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
            "external_id": rkey,
            "title": title_from(text),
            "content": text,
            "content_html": None,
            "date": parsing.parse_datetime_value(record.get("createdAt") or post.get("indexedAt")),
            "media_urls": media,
            "categories": [],
            "metadata": {"at_uri": uri, **({"reply": True} if record.get("reply") else {})},
        })
    return posts


class BlueskyKind(BaseKind):
    name = "bluesky"
    chronological = True       # newest first
    available_basis = "exact"  # the profile's postsCount
    profile = BLUESKY_PROFILE

    def __init__(self, http: KindHttp) -> None:
        self.http = http

    def matches(self, source: Source) -> bool:
        return enabled() and actor(str(source.get("handle_or_url") or "")) is not None

    def host_key(self, source: Source) -> str:
        return BLUESKY_HOST_KEY

    def checkpoint_resumable(self, checkpoint: Any) -> bool:
        return isinstance(checkpoint, dict) and checkpoint.get("mode") == "bluesky_cursor" and bool(checkpoint.get("cursor"))

    async def _json(self, method: str, **params: Any) -> Dict[str, Any]:
        body, _ = await self.http.get_text(f"{API}/{method}?{urllib.parse.urlencode(params)}")
        return json.loads(body)

    async def _profile(self, source: Source) -> Dict[str, Any]:
        """The profile; KindUnavailable when the account opted out of logged-out readers."""
        name = actor(str(source["handle_or_url"]))
        if name is None:
            raise ValueError(f"Not a Bluesky profile address: {source['handle_or_url']}")
        profile = await self._json("app.bsky.actor.getProfile", actor=name)
        if opted_out(profile):
            raise KindUnavailable(OPTED_OUT)
        return profile

    async def _page(self, source: Source, did: str, cursor: Optional[str], limit: int) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        params: Dict[str, Any] = {"actor": did, "limit": max(1, min(100, limit)), "filter": "posts_no_replies"}
        if cursor:
            params["cursor"] = cursor
        payload = await self._json("app.bsky.feed.getAuthorFeed", **params)
        return feed_posts(payload, did, str(source["handle_or_url"])), payload.get("cursor")

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        profile = await self._profile(source)
        posts, _ = await self._page(source, profile.get("did") or actor(str(source["handle_or_url"])), None,
                                    min(PAGE_SIZE, max(1, limit)))
        return posts[:limit]

    async def inspect(self, source: Source) -> Inspection:
        profile = await self._profile(source)
        count = profile.get("postsCount")
        return Inspection(count if isinstance(count, int) else None, PAGE_SIZE, None)

    async def archive_pages(self, source: Source, target: int, checkpoint: Optional[dict], rate: RateLimit):
        profile = await self._profile(source)
        did = profile.get("did") or actor(str(source["handle_or_url"]))
        collected, pages = resume_counts(checkpoint)
        cursor = (checkpoint or {}).get("cursor")
        while collected < target:
            posts, next_cursor = await self._page(source, did, cursor, PAGE_SIZE)
            pages += 1
            posts = posts[:max(0, target - collected)]
            collected += len(posts)
            yield ArchivePage(posts, {"mode": "bluesky_cursor", "cursor": next_cursor, "last_cursor": cursor,
                                      "pages_fetched": pages, "collected_posts": collected})
            if not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
