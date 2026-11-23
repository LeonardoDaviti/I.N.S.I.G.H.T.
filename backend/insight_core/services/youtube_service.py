"""
YouTube channel/video utilities built on top of yt-dlp.
"""
from __future__ import annotations

import html
import json
import math
import os
import re
import signal
import subprocess
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from insight_core.db import database as db
from insight_core.ingestion.kinds.base import checked_fetch

from insight_core.logs.core.logger_config import get_component_logger

# Why a video was skipped: the first of these found in yt-dlp's error, else "yt-dlp failed".
SKIP_REASONS = (
    ("confirm you", "the bot check"),         # "Sign in to confirm you're not a bot"
    ("timed out", "timed out"),
    ("private video", "private"),
    ("members", "members only"),
    ("live event", "not live yet"),
    ("premiere", "not live yet"),
    ("unavailable", "unavailable"),
)
ORIGINAL_SUFFIX = "-orig"   # yt-dlp's name for the untranslated automatic captions ("ru-orig")
TAG_RE = re.compile(r"<[^>]+>")
# WebVTT's marks, whatever the track's header says: a cue timing, an inline time or class tag, its header lines.
VTT_RE = re.compile(r"-->|<\d{2}:\d{2}:\d{2}\.\d{3}>|</c>|^(?:WEBVTT|Kind:\s|Language:\s)", re.MULTILINE)


def skip_reason(error: BaseException) -> str:
    """A skipped video's reason, short and countable: "the bot check", "timed out", ..."""
    text = str(error).lower()
    return next((reason for needle, reason in SKIP_REASONS if needle in text), "yt-dlp failed")


def base_language(code: Optional[str]) -> str:
    """"en-US" -> "en", "ru-orig" -> "ru", "zh-Hans" -> "zh"; "" for none."""
    return re.split(r"[-_]", str(code or "").strip().lower(), maxsplit=1)[0]


def original_language(details: Dict[str, Any]) -> str:
    """The video's own language: its `language`, else its default audio track's, else the untranslated
    automatic captions' ("ru-orig"); "" when none says."""
    for value in (details.get("language"), details.get("_audio_language")):
        if base_language(value):
            return base_language(value)
    for key in (details.get("automatic_captions") or {}):
        if str(key).endswith(ORIGINAL_SUFFIX):
            return base_language(key)
    return ""


def audio_language(formats: Sequence[Dict[str, Any]]) -> str:
    """The default audio track's language: the format yt-dlp ranks first by language_preference
    (the original track is highest), among those naming a language; "" when none does."""
    named = [f for f in formats or [] if isinstance(f, dict) and base_language(f.get("language"))
             and f.get("acodec") not in (None, "none")]
    if not named:
        return ""
    return base_language(max(named, key=lambda f: f.get("language_preference") or -1).get("language"))


def transcript_tracks(details: Dict[str, Any], preferred: Sequence[str]) -> List[Tuple[str, str]]:
    """The caption tracks to try, in order, as (bucket, language key): the video's own language (subtitles, then
    automatic, untranslated first), the preferred languages, then any other subtitles. Any other automatic track is
    YouTube's machine translation: tried only when the video's language is unknown."""
    subtitles = details.get("subtitles") or {}
    automatic = details.get("automatic_captions") or {}
    original = original_language(details)
    order: List[Tuple[str, str]] = []

    def add(bucket: str, key: str) -> None:
        if (bucket, key) not in order:
            order.append((bucket, key))

    def keys(bucket: Dict[str, Any], language: str) -> List[str]:
        return [key for key in bucket if base_language(key) == language]

    if original:
        for key in keys(subtitles, original):
            add("subtitles", key)
        for key in sorted(keys(automatic, original), key=lambda k: (not str(k).endswith(ORIGINAL_SUFFIX), k)):
            add("automatic_captions", key)
    for language in preferred:
        if language in subtitles:
            add("subtitles", language)
        if language in automatic and (not original or base_language(language) == original):
            add("automatic_captions", language)
    for key in subtitles:
        add("subtitles", key)
    if not original:
        for key in automatic:
            add("automatic_captions", key)
    return order


def plain_transcript(text: Optional[str]) -> str:
    """Any caption payload (XML srv1-3/ttml, json3, WebVTT, plain) as plain text, never markup."""
    payload = (text or "").strip()
    if not payload:
        return ""
    if payload.startswith("{"):
        try:
            return _json3_text(json.loads(payload))
        except (ValueError, AttributeError):
            pass
    if payload.startswith("<"):
        try:
            return _xml_text(payload)
        except ET.ParseError:
            pass
    if VTT_RE.search(payload):
        return _vtt_text(payload)
    return payload


def _json3_text(data: Dict[str, Any]) -> str:
    chunks = []
    for event in data.get("events", []) or []:
        segments = event.get("segs") or []
        text = "".join(segment.get("utf8", "") for segment in segments).strip()
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


def _vtt_text(payload: str) -> str:
    lines: List[str] = []
    for line in payload.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        if "-->" in stripped or stripped.isdigit():
            continue
        cleaned = " ".join(html.unescape(TAG_RE.sub("", stripped)).split())
        if cleaned and (not lines or lines[-1] != cleaned):
            lines.append(cleaned)
    return "\n".join(lines).strip()


def _xml_text(payload: str) -> str:
    """The words of a caption XML document: each <text> (srv1), <p> (srv3, ttml) as one line, its
    inner tags' text included; the text's own escaped markup ("&amp;#39;") decoded."""
    root = ET.fromstring(payload)
    cues = [node for node in root.iter() if str(node.tag).split("}")[-1] in ("text", "p")]
    texts = ["".join(node.itertext()) for node in cues] if cues else [node.text or "" for node in root.iter()]
    lines = [" ".join(html.unescape(TAG_RE.sub("", html.unescape(text))).split()) for text in texts]
    return "\n".join(line for line in lines if line).strip()


class YouTubeService:
    """Shared YouTube backend for fetching, archive, channel listing and watch progress."""

    DEFAULT_PAGE_SIZE = 15
    DEFAULT_LANGUAGES = ("en", "en-US", "en-GB", "ru", "ka")

    # yt-dlp's default retries with exponential sleeps can spend minutes on one bot-checked video:
    # fewer retries, and a hard timeout on every call.
    YTDLP_HARDENING_ARGS = ("--retries", "2", "--extractor-retries", "1", "--socket-timeout", "15")
    DEFAULT_YTDLP_TIMEOUT_SECONDS = 90
    # the test read before a channel is added (one listing of its newest video), while the reader waits
    TEST_READ_TIMEOUT_SECONDS = 45
    DEFAULT_YTDLP_PLAYLIST_TIMEOUT_SECONDS = 180
    # a full channel scan lists every video (available_posts, first_post_date), so it gets a larger budget
    # rather than a --playlist-end limit, which would silently change both numbers
    DEFAULT_YTDLP_CHANNEL_SCAN_TIMEOUT_SECONDS = 900
    # total time for one video's subtitles, across every format of every language
    DEFAULT_TRANSCRIPT_BUDGET_SECONDS = 90

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("youtube_service")
        self.preferred_languages = tuple(
            item.strip()
            for item in os.environ.get("YOUTUBE_PREFERRED_LANGUAGES", ",".join(self.DEFAULT_LANGUAGES)).split(",")
            if item.strip()
        ) or self.DEFAULT_LANGUAGES
        self.ytdlp_timeout_seconds = int(
            os.environ.get("YTDLP_TIMEOUT_SECONDS", str(self.DEFAULT_YTDLP_TIMEOUT_SECONDS))
        )
        self.ytdlp_playlist_timeout_seconds = int(
            os.environ.get(
                "YTDLP_PLAYLIST_TIMEOUT_SECONDS", str(self.DEFAULT_YTDLP_PLAYLIST_TIMEOUT_SECONDS)
            )
        )
        self.ytdlp_channel_scan_timeout_seconds = int(
            os.environ.get(
                "YTDLP_CHANNEL_SCAN_TIMEOUT_SECONDS",
                str(self.DEFAULT_YTDLP_CHANNEL_SCAN_TIMEOUT_SECONDS),
            )
        )
        self.transcript_budget_seconds = int(
            os.environ.get(
                "YOUTUBE_TRANSCRIPT_BUDGET_SECONDS", str(self.DEFAULT_TRANSCRIPT_BUDGET_SECONDS)
            )
        )

    def inspect_channel(self, source_handle: str) -> Dict[str, Any]:
        channel_ref = self._normalize_channel_ref(source_handle)
        try:
            entries = self._list_channel_entries(
                channel_ref["channel_url"], timeout=self.ytdlp_channel_scan_timeout_seconds
            )
        except Exception as exc:
            # the archive plan (the only caller) fails with this error; the log names what was lost
            self.logger.error(
                "Channel scan failed for %s - archive metadata (available_posts, "
                "first_post_date) will stay stale: %s",
                channel_ref["channel_url"],
                exc,
            )
            raise
        oldest_details = self._get_video_details(entries[-1]["id"]) if entries else None
        first_post_date = self._parse_upload_date(oldest_details.get("upload_date")) if oldest_details else None

        return {
            "available_posts": len(entries),
            "page_size": self.DEFAULT_PAGE_SIZE,
            "first_post_date": first_post_date.isoformat() if first_post_date else None,
            "channel": {
                "channel_url": channel_ref["channel_url"],
                "rss_url": channel_ref["rss_url"],
                "channel_id": channel_ref.get("channel_id"),
            },
        }

    def fetch_live_posts(self, source_handle: str, limit: int) -> List[Dict[str, Any]]:
        """The channel's latest videos; skips are counted by reason (kinds.base.checked_fetch)."""
        channel_ref = self._normalize_channel_ref(source_handle)
        entries = self._list_channel_entries(channel_ref["channel_url"], limit=limit)
        skipped: Counter = Counter()
        posts = self._hydrate_entries_to_posts(entries, source_handle, skipped=skipped)
        return checked_fetch(posts, len(entries), skipped, noun="videos")

    def test_read_channel(self, source_handle: str) -> None:
        """List the channel's newest video, nothing hydrated (the test read before adding); raises yt-dlp's error."""
        channel_ref = self._normalize_channel_ref(source_handle)
        self._list_channel_entries(channel_ref["channel_url"], limit=1, timeout=self.TEST_READ_TIMEOUT_SECONDS)

    def archive_channel_posts(self, source_handle: str, start: int = 1) -> Dict[str, Any]:
        """Every video from video number `start` to the channel's oldest, newest first."""
        channel_ref = self._normalize_channel_ref(source_handle)
        entries = self._list_channel_entries(channel_ref["channel_url"], start=start)
        posts = self._hydrate_entries_to_posts(entries, source_handle)
        return {
            "posts": posts,
            "pages_fetched": max(1, math.ceil(len(entries) / self.DEFAULT_PAGE_SIZE)) if entries else 0,
        }

    def get_watch_progress(self, video_id: str) -> Optional[Dict[str, Any]]:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT video_id, source_id, video_url, title, duration_seconds, progress_seconds,
                           progress_percent, notes_markdown, watch_sessions, completed,
                           last_watched_at, created_at, updated_at
                    FROM youtube_watch_progress
                    WHERE video_id = %s
                    """,
                    (video_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None

        return {
            "video_id": row[0],
            "source_id": str(row[1]) if row[1] else None,
            "video_url": row[2],
            "title": row[3],
            "duration_seconds": row[4],
            "progress_seconds": row[5],
            "progress_percent": float(row[6]) if row[6] is not None else None,
            "notes_markdown": row[7],
            "watch_sessions": row[8],
            "completed": row[9],
            "last_watched_at": row[10].isoformat() if row[10] else None,
            "created_at": row[11].isoformat() if row[11] else None,
            "updated_at": row[12].isoformat() if row[12] else None,
        }

    def save_watch_progress(
        self,
        *,
        video_id: str,
        video_url: str,
        title: str,
        duration_seconds: Optional[int],
        progress_seconds: int,
        source_id: Optional[str] = None,
        notes_markdown: Optional[str] = None,
        completed: Optional[bool] = None,
    ) -> Dict[str, Any]:
        duration = max(duration_seconds or 0, 0)
        progress = max(progress_seconds, 0)
        percent = round((progress / duration) * 100, 2) if duration else None
        completed = completed if completed is not None else (bool(duration) and progress >= duration)

        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO youtube_watch_progress (
                        video_id,
                        source_id,
                        video_url,
                        title,
                        duration_seconds,
                        progress_seconds,
                        progress_percent,
                        notes_markdown,
                        watch_sessions,
                        completed,
                        last_watched_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, now())
                    ON CONFLICT (video_id) DO UPDATE SET
                        source_id = COALESCE(EXCLUDED.source_id, youtube_watch_progress.source_id),
                        video_url = EXCLUDED.video_url,
                        title = EXCLUDED.title,
                        duration_seconds = EXCLUDED.duration_seconds,
                        progress_seconds = EXCLUDED.progress_seconds,
                        progress_percent = EXCLUDED.progress_percent,
                        notes_markdown = COALESCE(EXCLUDED.notes_markdown, youtube_watch_progress.notes_markdown),
                        watch_sessions = youtube_watch_progress.watch_sessions + 1,
                        completed = EXCLUDED.completed,
                        last_watched_at = now(),
                        updated_at = now()
                    """,
                    (
                        video_id,
                        source_id,
                        video_url,
                        title,
                        duration,
                        progress,
                        percent,
                        notes_markdown,
                        completed,
                    ),
                )
            conn.commit()

        return self.get_watch_progress(video_id) or {}

    def _normalize_channel_ref(self, source_handle: str) -> Dict[str, Any]:
        parsed = urllib.parse.urlparse(source_handle)
        if "youtube.com" in (parsed.netloc or "") and parsed.path == "/feeds/videos.xml":
            channel_id = urllib.parse.parse_qs(parsed.query).get("channel_id", [None])[-1]
            if not channel_id:
                raise ValueError(f"Invalid YouTube RSS URL: {source_handle}")
            return {
                "source_handle": source_handle,
                "channel_id": channel_id,
                "channel_url": f"https://www.youtube.com/channel/{channel_id}",
                "rss_url": source_handle,
            }

        if source_handle.startswith("UC") and len(source_handle) >= 20:
            channel_id = source_handle
            return {
                "source_handle": source_handle,
                "channel_id": channel_id,
                "channel_url": f"https://www.youtube.com/channel/{channel_id}",
                "rss_url": f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}",
            }

        if source_handle.startswith("@"):
            return {
                "source_handle": source_handle,
                "channel_id": None,
                "channel_url": f"https://www.youtube.com/{source_handle}",
                "rss_url": None,
            }

        if "youtube.com" in source_handle:
            channel_url = source_handle.rstrip("/")
            return {
                "source_handle": source_handle,
                "channel_id": None,
                "channel_url": channel_url,
                "rss_url": None,
            }

        return {
            "source_handle": source_handle,
            "channel_id": None,
            "channel_url": f"https://www.youtube.com/@{source_handle}",
            "rss_url": None,
        }

    def _list_channel_entries(
        self,
        channel_url: str,
        limit: Optional[int] = None,
        timeout: Optional[int] = None,
        start: int = 1,
    ) -> List[Dict[str, Any]]:
        args = [
            "--dump-single-json",
            "--flat-playlist",
            "--skip-download",
            "--no-warnings",
        ]
        if start > 1:
            args.extend(["--playlist-start", str(start)])
        if limit:
            # --playlist-end is a video number, not a count.
            args.extend(["--playlist-end", str(start + limit - 1)])

        if timeout is None:
            # no limit is a full channel scan: the page budget would break the largest channels
            timeout = (
                self.ytdlp_playlist_timeout_seconds
                if limit
                else self.ytdlp_channel_scan_timeout_seconds
            )

        info = self._run_ytdlp_json(
            args + [f"{channel_url.rstrip('/')}/videos"],
            timeout=timeout,
        )
        entries = info.get("entries") or []
        normalized = []
        for entry in entries:
            if not entry or not entry.get("id"):
                continue
            normalized.append(entry)
        return normalized

    def _build_video_post(self, video_ref: str, source_handle: str) -> Optional[Dict[str, Any]]:
        video_id = self._extract_video_id(video_ref)
        if not video_id:
            raise ValueError(f"Invalid YouTube video reference: {video_ref}")

        details = self._get_video_details(video_id)
        if not details:
            return None

        transcript, transcript_source = self._extract_transcript(details)
        # the stored text's language: the caption track's, else unset (detected later)
        transcript_language = base_language(transcript_source.split(":", 1)[1]) if transcript_source else ""
        description = details.get("description") or ""
        published_at = self._parse_upload_date(details.get("upload_date")) or datetime.now(timezone.utc)
        chapters = [
            {
                "title": chapter.get("title") or f"Chapter {index}",
                "start_seconds": int(chapter.get("start_time") or 0),
                "end_seconds": int(chapter.get("end_time") or 0),
            }
            for index, chapter in enumerate(details.get("chapters") or [], start=1)
        ]
        thumbnails = [item.get("url") for item in details.get("thumbnails") or [] if item.get("url")]
        video_url = details.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"

        content = transcript or description or details.get("title") or video_url
        metadata = {
            "kind": "youtube_video",
            "description": description,
            "channel_id": details.get("channel_id") or details.get("uploader_id"),
            "channel_title": details.get("channel") or details.get("uploader"),
            "duration_seconds": details.get("duration"),
            "view_count": details.get("view_count"),
            "like_count": details.get("like_count"),
            "chapters": chapters,
            "thumbnails": thumbnails,
            "transcript_source": transcript_source,
            "tags": details.get("tags") or [],
        }
        if original_language(details):
            metadata["video_language"] = original_language(details)

        return {
            **({"language_code": transcript_language} if transcript_language else {}),
            "platform": "youtube",
            "source": source_handle,
            "url": video_url,
            "external_id": video_id,
            "title": details.get("title") or video_id,
            "content": content,
            "content_html": f"<p>{self._escape_html(content)}</p>",
            "date": published_at,
            "media_urls": [video_url] + thumbnails[:1],
            "categories": [item for item in [details.get("channel"), details.get("playlist_title")] if item],
            "metadata": metadata,
        }

    def _hydrate_entries_to_posts(self, entries: List[Dict[str, Any]], source_handle: str, *,
                                  skipped: Optional[Counter] = None) -> List[Dict[str, Any]]:
        """The entries as posts; each one skipped counted in `skipped` by its reason (skip_reason)."""
        posts = []
        for entry in entries:
            try:
                post = self._build_video_post(entry["id"], source_handle)
            except Exception as exc:
                self.logger.warning("Skipping YouTube video %s: %s", entry.get("id"), exc)
                if skipped is not None:
                    skipped[skip_reason(exc)] += 1
                continue
            if post:
                posts.append(post)
            elif skipped is not None:
                skipped["no details"] += 1
        posts.sort(key=lambda item: item.get("date") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return posts

    # bulk keys of yt-dlp's per-video JSON nothing reads (`formats` is most of a 2-8MB dump); subtitles,
    # automatic_captions and thumbnails are read and must stay
    _YTDLP_DISCARD_KEYS = (
        "formats",
        "requested_formats",
        "heatmap",
    )

    def _get_video_details(self, video_id: str) -> Dict[str, Any]:
        details = self._run_ytdlp_json(
            [
                "--dump-single-json",
                "--skip-download",
                "--no-warnings",
                f"https://www.youtube.com/watch?v={video_id}",
            ]
        )
        # read before the formats are dropped
        details["_audio_language"] = audio_language(details.get("formats") or [])
        for key in self._YTDLP_DISCARD_KEYS:
            details.pop(key, None)
        return details

    def _run_ytdlp_json(self, args: List[str], timeout: Optional[int] = None) -> Dict[str, Any]:
        command = ["yt-dlp", *self.YTDLP_HARDENING_ARGS, *args]
        timeout = timeout or self.ytdlp_timeout_seconds
        started = time.monotonic()

        # a new session so the timeout kills the whole group: yt-dlp leaves grandchildren behind
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            self._kill_process_group(process)
            process.communicate()
            # a ValueError like a failure, so callers skip the video instead of losing the channel
            raise ValueError(f"yt-dlp timed out after {timeout}s: {command[-1]}")

        if process.returncode != 0:
            message = (stderr or stdout or "").strip()
            raise ValueError(f"yt-dlp failed ({process.returncode}): {message[:500]}")

        output = (stdout or "").strip()
        if not output:
            raise ValueError("yt-dlp returned empty output")

        self.logger.debug("yt-dlp finished in %.1fs: %s", time.monotonic() - started, command[-1])
        return json.loads(output)

    def _kill_process_group(self, process: subprocess.Popen) -> None:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            process.kill()

    def _extract_video_id(self, value: str) -> Optional[str]:
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
            return value

        parsed = urllib.parse.urlparse(value)
        if parsed.netloc == "youtu.be":
            return parsed.path.strip("/") or None

        if "youtube.com" in parsed.netloc:
            if parsed.path == "/watch":
                return urllib.parse.parse_qs(parsed.query).get("v", [None])[-1]
            if parsed.path.startswith("/shorts/"):
                return parsed.path.split("/", 2)[2]
            if parsed.path.startswith("/embed/"):
                return parsed.path.split("/", 2)[2]
        return None

    def _parse_upload_date(self, upload_date: Optional[str]) -> Optional[datetime]:
        if not upload_date:
            return None
        try:
            if len(upload_date) == 8:
                return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=timezone.utc)
            return datetime.fromisoformat(upload_date.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _extract_transcript(self, details: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
        deadline = time.monotonic() + self.transcript_budget_seconds   # one deadline for the whole video

        for bucket_name, language in transcript_tracks(details, self.preferred_languages):
            formats = (details.get(bucket_name) or {}).get(language) or []
            transcript = self._fetch_transcript_from_formats(formats, deadline)
            if transcript:
                return transcript, f"{bucket_name}:{language}"

        return None, None

    def _fetch_transcript_from_formats(
        self, formats: List[Dict[str, Any]], deadline: Optional[float] = None
    ) -> Optional[str]:
        prioritized = sorted(
            formats,
            key=lambda item: {"json3": 0, "vtt": 1, "ttml": 2}.get(item.get("ext"), 9),
        )
        for format_info in prioritized:
            subtitle_url = format_info.get("url")
            if not subtitle_url:
                continue
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                self.logger.debug("Transcript budget exhausted, stopping subtitle fetches")
                return None
            try:
                payload = self._fetch_text(subtitle_url, timeout=remaining)
                transcript = self._parse_subtitle_payload(payload, format_info.get("ext"))
            except Exception as exc:
                self.logger.debug("Subtitle fetch failed for %s: %s", subtitle_url, exc)
                continue
            if transcript:
                return transcript
        return None

    def _fetch_text(self, url: str, timeout: Optional[float] = None) -> str:
        effective_timeout = 60 if timeout is None else max(1.0, min(60.0, timeout))
        request = urllib.request.Request(url, headers={"User-Agent": "INSIGHT YouTube/1.0"})
        with urllib.request.urlopen(request, timeout=effective_timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    def _parse_subtitle_payload(self, payload: str, ext: Optional[str]) -> str:
        """Plain text from any caption format, told by its content, not its declared ext."""
        return plain_transcript(payload)

    def _escape_html(self, value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
