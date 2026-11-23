"""youtube_channel: a channel read through yt-dlp (services/youtube_service.py).

yt-dlp is a blocking subprocess that can run for minutes, so every call goes through a worker thread
(blocking_io=True) or it would freeze the event loop, /health included. The profile carries the rest of the policy:
the ytdlp pool (YouTube's bot detection is per IP), requires="ytdlp" (INSIGHT_YTDLP_ENABLED=0: unavailable), a
168h cadence floor and at least 15 posts per fetch.
"""
from __future__ import annotations

import asyncio
import urllib.parse
from datetime import timedelta
from typing import Any, Dict, List, Optional

from insight_core.ingestion.kinds.base import (
    ArchivePage,
    BaseKind,
    Inspection,
    PolitenessProfile,
    ReadCheck,
    Source,
    gone_reason,
    start_at,
)

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

    async def test_read(self, source: Source) -> Optional[ReadCheck]:
        """The channel's newest video listed (one short yt-dlp call): a wrong handle is yt-dlp's 404."""
        try:
            await asyncio.to_thread(self.youtube.test_read_channel, str(source["handle_or_url"]))
            return None
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            reason = str(exc) or type(exc).__name__
            return ReadCheck(reason, gone=gone_reason(reason))

    async def inspect(self, source: Source) -> Inspection:
        data = dict(await asyncio.to_thread(self.youtube.inspect_channel, str(source["handle_or_url"])))
        data.pop("rate_limit", None)  # pacing comes from the profile, not the service
        return Inspection(
            available_posts=data.pop("available_posts", None),
            page_size=data.pop("page_size", None),
            first_post_date=data.pop("first_post_date", None),
            raw=data,
        )

    async def start_checkpoint(self, source: Source, stored) -> Optional[dict]:
        # The channel lists newest first: the stored videos are numbers 1..stored.
        start = max(1, int(stored["post_count"]) + 1 - self.youtube.DEFAULT_PAGE_SIZE)
        return start_at(mode="youtube_channel", playlist_start=start)

    async def archive_pages(self, source, target, checkpoint, rate):
        # single shot: one long yt-dlp listing from the checkpoint's video number to the channel's end (checkpoint
        # None), given the channel-scan time budget
        start = int((checkpoint or {}).get("playlist_start") or 1)
        result = await asyncio.to_thread(self.youtube.archive_channel_posts, str(source["handle_or_url"]), start)
        yield ArchivePage(list(result.get("posts") or []), None)
