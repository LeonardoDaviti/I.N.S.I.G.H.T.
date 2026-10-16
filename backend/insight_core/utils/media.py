"""Media URL helpers for the reader: clean stored URLs, pick images, derive YouTube thumbnails.

Pure functions, no I/O. Stored `posts.media_urls` mix images, video pages (YouTube watch
URLs, Telegram .mp4 clips) and the odd link, and older rows keep HTML entities (`&amp;`)
that break signed CDN URLs (external-preview.redd.it answers 403). Everything that shows
an image goes through here so the feed thumbnail and the post page agree.
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional

from .content_fingerprints import decode_entities

_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".svg")
_VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v", ".m3u8", ".mkv", ".avi", ".mp3", ".ogg", ".wav")
_IMAGE_HOSTS = {
    "i.redd.it", "preview.redd.it", "external-preview.redd.it", "i.ytimg.com",
    "static.simonwillison.net", "substackcdn.com", "substack-post-media.s3.amazonaws.com",
    "pbs.twimg.com", "i.imgur.com",
}
_IMAGE_HOST_SUFFIXES = (".wp.com", ".substackcdn.com")
_IMAGE_PREFIXES = ("tg.i-c-a.su/media/",)

_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                  "youtube-nocookie.com", "www.youtube-nocookie.com"}
_YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_PATH_PREFIXES = ("shorts", "embed", "live", "v")


def clean_url(value: Any) -> Optional[str]:
    """Strip and HTML-unescape a stored URL (decode_entities: `&amp;#038;` too). None if unusable."""
    if not isinstance(value, str):
        return None
    return decode_entities(value.strip()) or None


def _parts(url: str) -> Optional[urllib.parse.SplitResult]:
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts


def youtube_video_id(url: Any) -> Optional[str]:
    """The 11-char video id of a YouTube watch / youtu.be / shorts / embed / live URL."""
    url = clean_url(url)
    parts = _parts(url) if url else None
    if not parts:
        return None
    host = parts.hostname.lower()
    candidate: Optional[str] = None
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        segments = [s for s in parts.path.split("/") if s]
        if segments[:1] == ["watch"]:
            candidate = (urllib.parse.parse_qs(parts.query).get("v") or [None])[0]
        elif len(segments) >= 2 and segments[0] in _YOUTUBE_PATH_PREFIXES:
            candidate = segments[1]
    if candidate and _YOUTUBE_ID_RE.match(candidate):
        return candidate
    return None


def youtube_thumbnail(video_id: str) -> str:
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def is_image_url(url: Any) -> bool:
    """True for URLs that render in an <img>: image extension or a known image host."""
    url = clean_url(url)
    parts = _parts(url) if url else None
    if not parts:
        return False
    path = parts.path.lower()
    if path.endswith(_VIDEO_EXTENSIONS):
        return False
    if path.endswith(_IMAGE_EXTENSIONS):
        return True
    host = parts.hostname.lower()
    if host in _IMAGE_HOSTS or host.endswith(_IMAGE_HOST_SUFFIXES):
        return True
    host_path = host + parts.path
    return host_path.startswith(_IMAGE_PREFIXES)


def _as_list(media_urls: Any) -> List[Any]:
    return list(media_urls) if isinstance(media_urls, (list, tuple)) else []


def _video_id(media_urls: Iterable[Any], post_url: Any) -> Optional[str]:
    for candidate in [post_url, *media_urls]:
        video_id = youtube_video_id(candidate)
        if video_id:
            return video_id
    return None


def _images(media_urls: Iterable[Any], skip_video_id: Optional[str]) -> List[str]:
    images: List[str] = []
    for raw in media_urls:
        url = clean_url(raw)
        if not url or url in images or not is_image_url(url):
            continue
        if skip_video_id and f"/vi/{skip_video_id}/" in url:
            continue  # the video's own frame: the player (or its thumbnail) stands in for it
        images.append(url)
    return images


def post_media(media_urls: Any, post_url: Any = None) -> Dict[str, Any]:
    """`{"images": [{"url"}...], "video": {"provider", "id"} | None}` for the post page."""
    urls = _as_list(media_urls)
    video_id = _video_id(urls, post_url)
    return {
        "images": [{"url": url} for url in _images(urls, video_id)],
        "video": {"provider": "youtube", "id": video_id} if video_id else None,
    }


def feed_thumb(media_urls: Any, post_url: Any = None) -> Optional[str]:
    """One image for a feed row: the YouTube thumbnail of a video, else the first image."""
    urls = _as_list(media_urls)
    video_id = _video_id(urls, post_url)
    if video_id:
        return youtube_thumbnail(video_id)
    images = _images(urls, None)
    return images[0] if images else None
