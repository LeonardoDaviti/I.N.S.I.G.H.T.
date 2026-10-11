"""youtube_channel: a channel read through yt-dlp (services/youtube_service.py).

yt-dlp is a subprocess that can run for minutes, and YouTubeService calls it with a
blocking communicate(). Awaited bare from an async def it freezes the event loop - /health
included, which flips the API container unhealthy - so every call goes through a worker
thread (blocking_io=True). That now covers the archive too, which used to run on the loop.

The profile carries the rest of yt-dlp's policy:
  - the ytdlp concurrency pool (2 at once, starts spaced 3s): YouTube's bot detection is
    per IP, and 22 channels fired together guarantee "Sign in to confirm you're not a bot"
  - requires="ytdlp": INSIGHT_YTDLP_ENABLED=0 makes every channel unavailable
  - a 168h cadence floor: channels publish ~10 videos a month
  - min 15 posts per fetch: over a week, anything past a stored limit of 5 would be dropped
"""
from __future__ import annotations

import asyncio
import urllib.parse
from datetime import timedelta
from typing import Any, Dict, List

from insight_core.ingestion.kinds.base import ArchivePage, BaseKind, Inspection, PolitenessProfile, Source

YOUTUBE_HOSTS = frozenset({"www.youtube.com", "youtube.com", "m.youtube.com"})

YOUTUBE_PROFILE = PolitenessProfile(
    concurrency_pool="ytdlp",
    page_delay_s=2,
    cadence_floor=timedelta(hours=168),
    min_posts_per_fetch=15,
    requires="ytdlp",
    blocking_io=True,
)


class YouTubeKind(BaseKind):
    name = "youtube_channel"
    available_basis = "exact"
    profile = YOUTUBE_PROFILE

    def __init__(self, youtube: Any) -> None:
        self.youtube = youtube   # YouTubeService (duck-typed so tests pass a stub)

    def matches(self, source: Source) -> bool:
        if source.get("platform") == "youtube":
            return True
        parsed = urllib.parse.urlparse(str(source.get("handle_or_url") or ""))
        return (parsed.hostname or "").lower() in YOUTUBE_HOSTS and parsed.path == "/feeds/videos.xml"

    async def fetch_latest(self, source: Source, limit: int) -> List[Dict[str, Any]]:
        return await asyncio.to_thread(self.youtube.fetch_live_posts, str(source["handle_or_url"]), limit)

    async def inspect(self, source: Source) -> Inspection:
        data = dict(await asyncio.to_thread(self.youtube.inspect_channel, str(source["handle_or_url"])))
        data.pop("rate_limit", None)  # pacing comes from the profile, not the service
        return Inspection(
            available_posts=data.pop("available_posts", None),
            page_size=data.pop("page_size", None),
            first_post_date=data.pop("first_post_date", None),
            raw=data,
        )

    async def archive_pages(self, source, target, checkpoint, rate):
        # Single shot: one yt-dlp listing of `target` videos, so checkpoint None (finished).
        result = await asyncio.to_thread(self.youtube.archive_channel_posts, str(source["handle_or_url"]), target)
        yield ArchivePage(list(result.get("posts") or []), None)
