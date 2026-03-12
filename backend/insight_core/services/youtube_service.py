"""
YouTube channel/video utilities built on top of yt-dlp.
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.processors.ai.gemini_processor import GeminiProcessor


class YouTubeService:
    """Shared YouTube backend for archive, roadmap, evaluation, and progress tracking."""

    DEFAULT_PAGE_SIZE = 15
    DEFAULT_LANGUAGES = ("en", "en-US", "en-GB", "ru", "ka")
    STOPWORDS = {
        "the", "and", "for", "with", "from", "into", "about", "your", "this", "that",
        "what", "when", "how", "why", "are", "you", "our", "their", "will", "just",
        "part", "episode", "ep", "video", "new", "live", "podcast", "interview",
    }

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("youtube_service")
        self.processor = GeminiProcessor()
        self.preferred_languages = tuple(
            item.strip()
            for item in os.environ.get("YOUTUBE_PREFERRED_LANGUAGES", ",".join(self.DEFAULT_LANGUAGES)).split(",")
            if item.strip()
        ) or self.DEFAULT_LANGUAGES

    def inspect_channel(self, source_handle: str) -> Dict[str, Any]:
        channel_ref = self._normalize_channel_ref(source_handle)
        entries = self._list_channel_entries(channel_ref["channel_url"])
        oldest_details = self._get_video_details(entries[-1]["id"]) if entries else None
        first_post_date = self._parse_upload_date(oldest_details.get("upload_date")) if oldest_details else None

        return {
            "available_posts": len(entries),
            "page_size": self.DEFAULT_PAGE_SIZE,
            "first_post_date": first_post_date.isoformat() if first_post_date else None,
            "rate_limit": {
                "page_delay_seconds": 2,
            },
            "channel": {
                "channel_url": channel_ref["channel_url"],
                "rss_url": channel_ref["rss_url"],
                "channel_id": channel_ref.get("channel_id"),
            },
        }

    def fetch_live_posts(self, source_handle: str, limit: int) -> List[Dict[str, Any]]:
        channel_ref = self._normalize_channel_ref(source_handle)
        entries = self._list_channel_entries(channel_ref["channel_url"], limit=limit)
        return self._hydrate_entries_to_posts(entries, source_handle)

    def archive_channel_posts(self, source_handle: str, limit: int) -> Dict[str, Any]:
        channel_ref = self._normalize_channel_ref(source_handle)
        entries = self._list_channel_entries(channel_ref["channel_url"], limit=limit)
        posts = self._hydrate_entries_to_posts(entries, source_handle)
        return {
            "posts": posts,
            "pages_fetched": max(1, math.ceil(len(entries) / self.DEFAULT_PAGE_SIZE)) if entries else 0,
        }

    def list_channel_videos(self, source_handle: str, limit: Optional[int] = None) -> Dict[str, Any]:
        channel_ref = self._normalize_channel_ref(source_handle)
        entries = self._list_channel_entries(channel_ref["channel_url"], limit=limit)
        videos = [self._entry_to_video_dict(entry, source_handle) for entry in entries]
        return {
            "channel": channel_ref,
            "total_videos": len(videos),
            "videos": videos,
        }

    def build_channel_roadmap(self, source_handle: str, limit: Optional[int] = None) -> Dict[str, Any]:
        listing = self.list_channel_videos(source_handle, limit=limit)
        videos = listing["videos"]
        groups = self._group_videos(videos)
        roadmap_groups = []
        for index, group in enumerate(groups, start=1):
            ordered_videos = sorted(group["videos"], key=lambda item: item.get("published_at") or "")
            roadmap_groups.append(
                {
                    "group_id": str(index),
                    "title": group["title"],
                    "group_type": group["group_type"],
                    "recommended_order": [video["video_id"] for video in ordered_videos],
                    "videos": ordered_videos,
                    "video_count": len(ordered_videos),
                }
            )

        return {
            "channel": listing["channel"],
            "total_videos": len(videos),
            "groups": roadmap_groups,
        }

    def build_playlists(self, source_handle: str, limit: int = 20) -> Dict[str, Any]:
        listing = self.list_channel_videos(source_handle, limit=limit)
        groups = self._group_videos(listing["videos"], collapse_singletons=True)
        return {
            "channel": listing["channel"],
            "total_videos": len(listing["videos"]),
            "playlists": groups,
        }

    async def evaluate_video(self, source_handle: str, video_ref: str) -> Dict[str, Any]:
        post = self._build_video_post(video_ref, source_handle)
        if not post:
            raise ValueError(f"Unable to load video metadata for {video_ref}")

        fallback = self._fallback_video_evaluation(post)
        if not self.processor.setup_processor():
            self._persist_video_tldr(post, fallback)
            return fallback

        try:
            await self.processor.connect()
            prompt = f"""
Return ONLY valid JSON with this exact structure:
{{
  "summary_markdown": "2-3 minute read markdown summary",
  "chapters": [
    {{
      "title": "chapter title",
      "start_seconds": 0
    }}
  ],
  "depth": "low|medium|high",
  "novelty": "low|medium|high",
  "worth_watching": "summary_enough|watch_selected_sections|watch_full_video",
  "reasoning": "short explanation"
}}

Use only the supplied video transcript and metadata.

VIDEO:
Title: {post.get("title", "")}
Source: {post.get("source", "")}
Published: {post.get("date")}
Duration seconds: {post.get("metadata", {}).get("duration_seconds")}
Description:
{post.get("metadata", {}).get("description", "")[:4000]}

Transcript:
{post.get("content", "")[:20000]}
"""
            raw = await self.processor._generate_text(prompt)
            result = self.processor._extract_json_from_response(raw)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic video evaluation for %s: %s", video_ref, exc)
            result = fallback
        finally:
            try:
                await self.processor.disconnect()
            except Exception:
                pass

        self._persist_video_tldr(post, result)
        return result

    async def chat_with_video(self, source_handle: str, video_ref: str, question: str) -> Dict[str, Any]:
        post = self._build_video_post(video_ref, source_handle)
        if not post:
            raise ValueError(f"Unable to load video metadata for {video_ref}")

        if self.processor.setup_processor():
            answer = self.processor.ask_single_post(post, question)
            if answer.get("success"):
                return {
                    "success": True,
                    "video_id": post["external_id"],
                    "answer": answer["answer"],
                    "source": "gemini",
                }

        return {
            "success": True,
            "video_id": post["external_id"],
            "answer": self._fallback_video_answer(post, question),
            "source": "fallback",
        }

    def get_watch_progress(self, video_id: str) -> Optional[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
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

        with psycopg.connect(self.db_url) as conn:
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

    def _list_channel_entries(self, channel_url: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        args = [
            "--dump-single-json",
            "--flat-playlist",
            "--skip-download",
            "--no-warnings",
        ]
        if limit:
            args.extend(["--playlist-end", str(limit)])

        info = self._run_ytdlp_json(args + [f"{channel_url.rstrip('/')}/videos"])
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

        return {
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

    def _hydrate_entries_to_posts(self, entries: List[Dict[str, Any]], source_handle: str) -> List[Dict[str, Any]]:
        posts = []
        for entry in entries:
            try:
                post = self._build_video_post(entry["id"], source_handle)
            except Exception as exc:
                self.logger.warning("Skipping YouTube video %s: %s", entry.get("id"), exc)
                continue
            if post:
                posts.append(post)
        posts.sort(key=lambda item: item.get("date") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        return posts

    def _get_video_details(self, video_id: str) -> Dict[str, Any]:
        return self._run_ytdlp_json(
            [
                "--dump-single-json",
                "--skip-download",
                "--no-warnings",
                f"https://www.youtube.com/watch?v={video_id}",
            ]
        )

    def _run_ytdlp_json(self, args: List[str]) -> Dict[str, Any]:
        command = ["yt-dlp", *args]
        process = subprocess.run(command, capture_output=True, text=True, check=False)
        if process.returncode != 0:
            stderr = (process.stderr or process.stdout or "").strip()
            raise ValueError(f"yt-dlp failed ({process.returncode}): {stderr[:500]}")

        output = (process.stdout or "").strip()
        if not output:
            raise ValueError("yt-dlp returned empty output")

        return json.loads(output)

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
        for bucket_name in ("subtitles", "automatic_captions"):
            bucket = details.get(bucket_name) or {}
            for language in self.preferred_languages:
                formats = bucket.get(language) or []
                transcript = self._fetch_transcript_from_formats(formats)
                if transcript:
                    return transcript, f"{bucket_name}:{language}"

        for bucket_name in ("subtitles", "automatic_captions"):
            bucket = details.get(bucket_name) or {}
            for language, formats in bucket.items():
                transcript = self._fetch_transcript_from_formats(formats)
                if transcript:
                    return transcript, f"{bucket_name}:{language}"

        return None, None

    def _fetch_transcript_from_formats(self, formats: List[Dict[str, Any]]) -> Optional[str]:
        prioritized = sorted(
            formats,
            key=lambda item: {"json3": 0, "vtt": 1, "ttml": 2}.get(item.get("ext"), 9),
        )
        for format_info in prioritized:
            subtitle_url = format_info.get("url")
            if not subtitle_url:
                continue
            try:
                payload = self._fetch_text(subtitle_url)
                transcript = self._parse_subtitle_payload(payload, format_info.get("ext"))
            except Exception as exc:
                self.logger.debug("Subtitle fetch failed for %s: %s", subtitle_url, exc)
                continue
            if transcript:
                return transcript
        return None

    def _fetch_text(self, url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "INSIGHT YouTube/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")

    def _parse_subtitle_payload(self, payload: str, ext: Optional[str]) -> str:
        ext = (ext or "").lower()
        if ext == "json3":
            return self._parse_json3_transcript(payload)
        if ext == "vtt":
            return self._parse_vtt_transcript(payload)
        if ext in {"ttml", "srv3"}:
            return self._parse_xml_transcript(payload)
        return self._parse_vtt_transcript(payload)

    def _parse_json3_transcript(self, payload: str) -> str:
        data = json.loads(payload)
        chunks = []
        for event in data.get("events", []):
            segments = event.get("segs") or []
            text = "".join(segment.get("utf8", "") for segment in segments).strip()
            if text:
                chunks.append(text)
        return "\n".join(chunks).strip()

    def _parse_vtt_transcript(self, payload: str) -> str:
        lines = []
        for line in payload.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("WEBVTT"):
                continue
            if "-->" in stripped:
                continue
            if stripped.isdigit():
                continue
            lines.append(stripped)
        return "\n".join(lines).strip()

    def _parse_xml_transcript(self, payload: str) -> str:
        root = ET.fromstring(payload)
        texts = []
        for element in root.iter():
            text = (element.text or "").strip()
            if text:
                texts.append(text)
        return "\n".join(texts).strip()

    def _entry_to_video_dict(self, entry: Dict[str, Any], source_handle: str) -> Dict[str, Any]:
        video_id = entry["id"]
        published_at = self._parse_upload_date(entry.get("upload_date"))
        return {
            "video_id": video_id,
            "url": entry.get("url") or f"https://www.youtube.com/watch?v={video_id}",
            "title": entry.get("title") or video_id,
            "description": entry.get("description") or "",
            "published_at": published_at.isoformat() if published_at else None,
            "channel_title": entry.get("channel") or entry.get("uploader"),
            "channel_id": entry.get("channel_id") or entry.get("uploader_id"),
            "source_handle": source_handle,
        }

    def _group_videos(self, videos: List[Dict[str, Any]], collapse_singletons: bool = False) -> List[Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        singletons: List[Dict[str, Any]] = []

        for video in videos:
            key = self._topic_key(video["title"])
            if key == video["video_id"]:
                singletons.append(video)
                continue

            group = grouped.setdefault(
                key,
                {
                    "title": self._group_title_from_key(key, video["title"]),
                    "group_type": "topic_cluster",
                    "videos": [],
                },
            )
            group["videos"].append(video)

        if collapse_singletons and singletons:
            grouped["singletons"] = {
                "title": "General Watch Queue",
                "group_type": "general_queue",
                "videos": singletons,
            }
        else:
            for video in singletons:
                grouped[video["video_id"]] = {
                    "title": video["title"],
                    "group_type": "single_video",
                    "videos": [video],
                }

        groups = list(grouped.values())
        groups.sort(
            key=lambda item: min(
                (video.get("published_at") or "9999-12-31T00:00:00+00:00" for video in item["videos"]),
                default="9999-12-31T00:00:00+00:00",
            )
        )
        return groups

    def _topic_key(self, title: str) -> str:
        cleaned = re.sub(r"\s+", " ", title or "").strip()
        for separator in ("|", ":", " - ", " – ", " — "):
            if separator in cleaned:
                prefix = cleaned.split(separator, 1)[0].strip()
                if 2 <= len(prefix.split()) <= 8:
                    return prefix.lower()

        normalized = re.sub(r"\b(part|episode|ep|lesson|chapter)\s*\d+\b", "", cleaned, flags=re.IGNORECASE)
        tokens = re.findall(r"[A-Za-z0-9]+", normalized.lower())
        keywords = [token for token in tokens if token not in self.STOPWORDS]
        if len(keywords) >= 3:
            return " ".join(keywords[:3])
        return self._extract_video_id(cleaned) or cleaned

    def _group_title_from_key(self, key: str, original_title: str) -> str:
        if key == original_title:
            return original_title
        return " ".join(part.capitalize() for part in key.split())

    def _fallback_video_evaluation(self, post: Dict[str, Any]) -> Dict[str, Any]:
        metadata = post.get("metadata", {})
        chapters = metadata.get("chapters") or []
        duration = metadata.get("duration_seconds") or 0
        transcript = post.get("content", "")
        transcript_length = len(transcript.split())
        depth = "high" if transcript_length > 2200 or duration > 2400 else "medium" if transcript_length > 900 else "low"
        novelty = "high" if len(metadata.get("tags") or []) >= 6 else "medium" if transcript_length > 1200 else "low"
        worth = "watch_full_video" if depth == "high" else "watch_selected_sections" if chapters else "summary_enough"
        summary = self._summarize_text(transcript or metadata.get("description", ""), limit=1200)

        return {
            "summary_markdown": f"## TL;DR\n{summary}",
            "chapters": chapters[:12],
            "depth": depth,
            "novelty": novelty,
            "worth_watching": worth,
            "reasoning": "Derived from transcript coverage, duration, and chapter structure.",
        }

    def _persist_video_tldr(self, post: Dict[str, Any], result: Dict[str, Any]) -> None:
        from insight_core.services.briefings_store_service import BriefingsStoreService

        store = BriefingsStoreService(self.db_url)
        store.save_briefing(
            subject_type="youtube_video",
            subject_key=post["external_id"],
            variant="tldr",
            render_format="markdown",
            title=post.get("title"),
            content=result.get("summary_markdown", ""),
            payload=result,
        )

    def _fallback_video_answer(self, post: Dict[str, Any], question: str) -> str:
        transcript = post.get("content") or ""
        snippets = [line for line in transcript.splitlines() if line.strip()]
        if not snippets:
            return "No transcript or description is available for this video yet."
        if question:
            lowered = question.lower()
            for snippet in snippets:
                if any(token in snippet.lower() for token in re.findall(r"[a-z0-9]+", lowered)[:4]):
                    return snippet[:600]
        return snippets[0][:600]

    def _summarize_text(self, text: str, limit: int = 1200) -> str:
        normalized = " ".join(text.split())
        if not normalized:
            return "Transcript is not available yet."
        clipped = normalized[:limit].rstrip()
        return clipped if clipped.endswith((".", "!", "?")) else f"{clipped}."

    def _escape_html(self, value: str) -> str:
        return (
            value.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
