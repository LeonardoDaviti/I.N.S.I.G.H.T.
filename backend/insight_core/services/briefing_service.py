"""
DB-backed daily briefing generation.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
import re
from typing import Any, Dict, List

import psycopg

from insight_core.db.repo_evidence import EvidenceRepository
from insight_core.db.repo_event_memory import EventMemoryRepository
from insight_core.db.repo_memory import MemoryRepository
from insight_core.db.repo_stories import StoriesRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.processors.ai.gemini_processor import GeminiProcessor
from insight_core.services.explainability_service import ExplainabilityService
from insight_core.services.briefings_store_service import BriefingsStoreService
from insight_core.services.entity_memory_service import EntityMemoryService
from insight_core.services.event_memory_service import EventMemoryService
from insight_core.services.posts_service import PostsService
from insight_core.services.sources_service import SourcesService
from insight_core.services.topics_service import TopicsService
from insight_core.utils.entity_memory import is_meaningful_entity_name, normalize_entity_name


class BriefingService:
    """Generate daily briefings from posts already stored in the database."""

    VERTICAL_BRIEFING_VERSION = 4

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.posts_service = PostsService(db_url)
        self.sources_service = SourcesService(db_url)
        self.stories_repo = StoriesRepository(db_url)
        self.memory_repo = MemoryRepository(db_url)
        self.event_repo = EventMemoryRepository(db_url)
        self.evidence_repo = EvidenceRepository(db_url)
        self.entity_memory_service = EntityMemoryService(db_url)
        self.event_memory_service = EventMemoryService(db_url)
        self.store_service = BriefingsStoreService(db_url)
        self.topics_service = TopicsService(db_url)
        self.explainability_service = ExplainabilityService(db_url)
        self.processor = GeminiProcessor()
        self.logger = get_component_logger("briefing_service")

    def _briefing_artifact_type(self, subject_type: str, variant: str) -> str:
        if subject_type == "daily_briefing" and variant == "topics":
            return "topic_briefing"
        if subject_type == "weekly_briefing" and variant == "topics":
            return "weekly_topic_briefing"
        if subject_type == "vertical_briefing":
            return "vertical_briefing"
        return subject_type

    def _briefing_takeaway(self, briefing: str) -> str | None:
        text = str(briefing or "")
        if not text.strip():
            return None

        cleaned_lines: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("#"):
                continue
            if stripped.startswith(("-", "•", "*")):
                stripped = stripped.lstrip("-•* ").strip()
            if stripped:
                cleaned_lines.append(stripped)

        candidate = " ".join(cleaned_lines) or text
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if not candidate:
            return None

        match = re.search(r"(.+?[.!?])(?:\s|$)", candidate)
        sentence = (match.group(1) if match else candidate[:220]).strip()
        return sentence if sentence.endswith((".", "!", "?")) else f"{sentence}."

    def _pick_reference_highlight(self, post_id: str) -> Dict[str, Any] | None:
        try:
            highlights = self.explainability_service.get_post_highlights(post_id)
        except Exception as exc:
            self.logger.warning("Failed to load highlights for reference %s: %s", post_id, exc)
            return None

        if not highlights:
            return None
        return max(
            highlights,
            key=lambda item: float(item.get("importance_score") or 0.0),
        )

    def _build_artifact_references(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        posts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        references: List[Dict[str, Any]] = []
        seen_posts: set[str] = set()
        for index, post in enumerate(posts):
            post_id = str(post.get("id") or "").strip()
            if not post_id or post_id in seen_posts:
                continue
            seen_posts.add(post_id)
            highlight = self._pick_reference_highlight(post_id)
            label = (
                str(post.get("title") or post.get("source_display_name") or post.get("source") or f"Post {index + 1}").strip()
            )
            payload: Dict[str, Any] = {
                "artifact_type": artifact_type,
                "artifact_id": artifact_id,
                "post_id": post_id,
                "reference_role": "primary" if index == 0 else "supporting",
                "display_label": label[:220] or None,
                "order_index": index,
            }
            if highlight:
                payload["highlight_id"] = highlight.get("id")
            references.append(payload)
        return references

    def _save_artifact_references(
        self,
        *,
        artifact_type: str,
        artifact_id: str,
        posts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not posts:
            return []
        try:
            self.explainability_service.save_artifact_references(
                artifact_type,
                artifact_id,
                self._build_artifact_references(
                    artifact_type=artifact_type,
                    artifact_id=artifact_id,
                    posts=posts,
                ),
            )
            return self._hydrate_artifact_references(artifact_type, artifact_id)
        except Exception as exc:
            self.logger.warning("Failed to save artifact references for %s/%s: %s", artifact_type, artifact_id, exc)
            return []

    def _hydrate_artifact_references(self, artifact_type: str, artifact_id: str) -> List[Dict[str, Any]]:
        try:
            references = self.explainability_service.get_artifact_references(artifact_type, artifact_id)
        except Exception as exc:
            self.logger.warning("Failed to load artifact references for %s/%s: %s", artifact_type, artifact_id, exc)
            return []

        if not references:
            return []

        post_ids = [reference.get("post_id") for reference in references if reference.get("post_id")]
        posts_by_id = {
            str(post["id"]): post
            for post in self.posts_service.get_posts_by_ids([str(post_id) for post_id in post_ids])
            if post.get("id")
        }

        hydrated: List[Dict[str, Any]] = []
        for reference in references:
            post = posts_by_id.get(str(reference.get("post_id") or ""))
            hydrated.append(
                {
                    **reference,
                    "post": post,
                    "display_label": reference.get("display_label")
                    or (post.get("title") if post else None)
                    or (post.get("source_display_name") if post else None)
                    or (post.get("source") if post else None)
                    or "Referenced post",
                }
            )
        return hydrated

    async def generate_daily_briefing(self, date_str: str) -> Dict[str, Any]:
        """Generate a markdown daily briefing for a single day."""
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        posts = self.posts_service.get_posts_by_date(target_date)

        if not posts:
            return {
                "success": False,
                "error": f"No posts found for date {date_str}",
                "posts": [],
                "date": date_str,
                "posts_processed": 0,
                "total_posts_fetched": 0,
            }

        setup_ok = self.processor.setup_processor()

        try:
            if not setup_ok:
                raise RuntimeError("Gemini processor setup failed")
            await self.processor.connect()
            briefing = await self.processor.daily_briefing(posts)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic daily briefing for %s: %s", date_str, exc)
            briefing = self.processor._fallback_daily_briefing(posts)
        finally:
            try:
                await self.processor.disconnect()
            except Exception:
                pass

        estimated_tokens = self._count_tokens(briefing)

        saved = self.store_service.save_briefing(
            subject_type="daily_briefing",
            subject_key=date_str,
            variant="default",
            render_format="markdown",
            title=f"Daily Briefing {date_str}",
            content=briefing,
            payload={
                "posts_processed": len(posts),
                "source": "database",
                "estimated_tokens": estimated_tokens,
                "one_sentence_takeaway": self._briefing_takeaway(briefing),
            },
        )
        references = self._save_artifact_references(
            artifact_type=self._briefing_artifact_type("daily_briefing", "default"),
            artifact_id=saved["id"],
            posts=posts,
        )

        return {
            "success": True,
            "briefing": briefing,
            "format": "markdown",
            "saved_briefing_id": saved["id"],
            "posts": posts,
            "date": date_str,
            "posts_processed": len(posts),
            "total_posts_fetched": len(posts),
            "estimated_tokens": estimated_tokens,
            "one_sentence_takeaway": self._briefing_takeaway(briefing),
            "references": references,
        }

    async def generate_daily_briefing_with_topics(
        self,
        date_str: str,
        include_unreferenced: bool = True,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        """Generate a topic-based daily briefing using DB posts."""
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        posts = self.posts_service.get_posts_by_date(target_date)

        if not posts:
            return {
                "success": False,
                "error": f"No posts found for date {date_str}",
                "topics": [],
                "posts": {},
                "date": date_str,
                "posts_processed": 0,
                "total_posts_fetched": 0,
            }

        if not refresh:
            cached = self.store_service.get_briefing("daily_briefing", date_str, "topics")
            if cached:
                return self._build_cached_topic_response(
                    date_str=date_str,
                    posts=posts,
                    cached_briefing=cached,
                    include_unreferenced=include_unreferenced,
                )

        setup_ok = self.processor.setup_processor()

        try:
            if not setup_ok:
                raise RuntimeError("Gemini processor setup failed")
            await self.processor.connect()
            topic_result = await self.processor.topic_briefing_with_numeric_ids(posts)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic topic briefing for %s: %s", date_str, exc)
            topic_result = self.processor._fallback_topic_briefing(posts)
        finally:
            try:
                await self.processor.disconnect()
            except Exception:
                pass
        normalized = self._normalize_topic_result(
            posts=posts,
            topic_result=topic_result,
            include_unreferenced=include_unreferenced,
        )
        stored_topics = self._store_topic_briefing_topics(
            target_date=target_date,
            normalized_topics=normalized["topics"],
            unreferenced_post_ids=normalized["unreferenced_posts"],
            refresh=refresh,
        )
        normalized["topics"] = stored_topics

        saved = self.store_service.save_briefing(
            subject_type="daily_briefing",
            subject_key=date_str,
            variant="topics",
            render_format="markdown",
            title=f"Topic Briefing {date_str}",
            content=topic_result.get("daily_briefing", ""),
            payload={
                "topics": stored_topics,
                "unreferenced_posts": normalized["unreferenced_posts"],
                "posts_processed": len(posts),
                "source": "database",
                "estimated_tokens": self._count_tokens(topic_result.get("daily_briefing", "")),
                "one_sentence_takeaway": self._briefing_takeaway(topic_result.get("daily_briefing", "")),
            },
        )
        references = self._save_artifact_references(
            artifact_type=self._briefing_artifact_type("daily_briefing", "topics"),
            artifact_id=saved["id"],
            posts=posts,
        )

        return {
            "success": True,
            "enhanced": True,
            "briefing": topic_result.get("daily_briefing", ""),
            "format": "markdown",
            "saved_briefing_id": saved["id"],
            "topics": normalized["topics"],
            "unreferenced_posts": normalized["unreferenced_posts"],
            "posts": normalized["posts"],
            "date": date_str,
            "posts_processed": len(posts),
            "total_posts_fetched": len(posts),
            "cached": False,
            "estimated_tokens": self._count_tokens(topic_result.get("daily_briefing", "")),
            "one_sentence_takeaway": self._briefing_takeaway(topic_result.get("daily_briefing", "")),
            "references": references,
        }

    async def generate_weekly_briefing(self, date_str: str, refresh: bool = False) -> Dict[str, Any]:
        """Generate a weekly briefing by combining the week's daily briefings."""
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        week_start = target_date - timedelta(days=target_date.weekday())
        week_end = week_start + timedelta(days=6)
        subject_key = f"{week_start.isoformat()}__{week_end.isoformat()}"
        week_label = f"{week_start.isoformat()} to {week_end.isoformat()}"

        if not refresh:
            cached = self.store_service.get_briefing("weekly_briefing", subject_key, "default")
            if cached:
                payload = cached.get("payload") or {}
                references = self._hydrate_artifact_references("weekly_briefing", cached.get("id"))
                if not references:
                    weekly_posts: List[Dict[str, Any]] = []
                    try:
                        for offset in range(7):
                            current_date = week_start + timedelta(days=offset)
                            weekly_posts.extend(self.posts_service.get_posts_by_date(current_date))
                    except Exception as exc:
                        self.logger.warning("Failed to backfill weekly briefing references: %s", exc)
                    if weekly_posts:
                        references = self._save_artifact_references(
                            artifact_type="weekly_briefing",
                            artifact_id=cached.get("id"),
                            posts=weekly_posts,
                        )
                return {
                    "success": True,
                    "briefing": cached.get("content", ""),
                    "format": cached.get("render_format", "markdown"),
                    "saved_briefing_id": cached.get("id"),
                    "cached": True,
                    "date": date_str,
                    "week_start": week_start.isoformat(),
                    "week_end": week_end.isoformat(),
                    "subject_key": subject_key,
                    "daily_briefings_used": payload.get("daily_briefings_used", 0),
                    "days_covered": payload.get("days_covered", []),
                    "estimated_tokens": payload.get("estimated_tokens", self._count_tokens(cached.get("content", ""))),
                    "one_sentence_takeaway": payload.get("one_sentence_takeaway") or self._briefing_takeaway(cached.get("content", "")),
                    "references": references,
                }

        daily_briefings: List[Dict[str, Any]] = []
        weekly_posts: List[Dict[str, Any]] = []
        seen_post_ids: set[str] = set()

        def add_weekly_posts(candidate_posts: List[Dict[str, Any]]) -> None:
            for post in candidate_posts:
                post_id = str(post.get("id") or "").strip()
                if not post_id or post_id in seen_post_ids:
                    continue
                seen_post_ids.add(post_id)
                weekly_posts.append(post)

        for offset in range(7):
            current_date = week_start + timedelta(days=offset)
            current_key = current_date.isoformat()
            cached_daily = self.store_service.get_briefing("daily_briefing", current_key, "default")
            if cached_daily:
                add_weekly_posts(self.posts_service.get_posts_by_date(current_date))
                daily_briefings.append(
                    {
                        "date": current_key,
                        "briefing": cached_daily.get("content", ""),
                        "posts_processed": (cached_daily.get("payload") or {}).get("posts_processed", 0),
                    }
                )
                continue

            generated = await self.generate_daily_briefing(current_key)
            if generated.get("success"):
                add_weekly_posts(generated.get("posts") or [])
                daily_briefings.append(
                    {
                        "date": current_key,
                        "briefing": generated.get("briefing", ""),
                        "posts_processed": generated.get("posts_processed", 0),
                    }
                )

        if not daily_briefings:
            return {
                "success": False,
                "error": f"No daily briefings or posts found for week {week_label}",
                "date": date_str,
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "subject_key": subject_key,
            }

        setup_ok = self.processor.setup_processor()
        try:
            if not setup_ok:
                raise RuntimeError("Gemini processor setup failed")
            await self.processor.connect()
            briefing = await self.processor.weekly_briefing(week_label, daily_briefings)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic weekly briefing for %s: %s", week_label, exc)
            briefing = self.processor._fallback_weekly_briefing(week_label, daily_briefings)
        finally:
            try:
                await self.processor.disconnect()
            except Exception:
                pass

        estimated_tokens = self._count_tokens(briefing)
        payload = {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "days_covered": [item["date"] for item in daily_briefings],
            "daily_briefings_used": len(daily_briefings),
            "estimated_tokens": estimated_tokens,
            "one_sentence_takeaway": self._briefing_takeaway(briefing),
        }
        saved = self.store_service.save_briefing(
            subject_type="weekly_briefing",
            subject_key=subject_key,
            variant="default",
            render_format="markdown",
            title=f"Weekly Briefing {week_label}",
            content=briefing,
            payload=payload,
        )
        references = self._save_artifact_references(
            artifact_type="weekly_briefing",
            artifact_id=saved["id"],
            posts=weekly_posts,
        )

        return {
            "success": True,
            "briefing": briefing,
            "format": "markdown",
            "saved_briefing_id": saved["id"],
            "cached": False,
            "date": date_str,
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "subject_key": subject_key,
            "daily_briefings_used": len(daily_briefings),
            "days_covered": payload["days_covered"],
            "estimated_tokens": estimated_tokens,
            "one_sentence_takeaway": self._briefing_takeaway(briefing),
            "references": references,
        }

    async def generate_weekly_topic_briefing(self, date_str: str, refresh: bool = False) -> Dict[str, Any]:
        """Generate a weekly topic/timeline briefing from stored daily topic briefings."""
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        week_start = target_date - timedelta(days=target_date.weekday())
        week_end = week_start + timedelta(days=6)
        subject_key = f"{week_start.isoformat()}__{week_end.isoformat()}"
        week_label = f"{week_start.isoformat()} to {week_end.isoformat()}"

        if not refresh:
            cached = self.store_service.get_briefing("weekly_briefing", subject_key, "topics")
            if cached:
                return self._build_cached_weekly_topic_response(
                    cached_briefing=cached,
                    date_str=date_str,
                    week_start=week_start.isoformat(),
                    week_end=week_end.isoformat(),
                    subject_key=subject_key,
                )

        daily_topic_briefings: List[Dict[str, Any]] = []
        combined_posts: Dict[str, Dict[str, Any]] = {}
        for offset in range(7):
            current_date = (week_start + timedelta(days=offset)).isoformat()
            result = await self.generate_daily_briefing_with_topics(
                current_date,
                include_unreferenced=False,
                refresh=False,
            )
            if not result.get("success") or not (result.get("topics") or []):
                continue
            for post_id, post in (result.get("posts") or {}).items():
                combined_posts[post_id] = post
            daily_topic_briefings.append(
                {
                    "date": current_date,
                    "briefing": result.get("briefing", ""),
                    "topics": result.get("topics") or [],
                }
            )

        if not daily_topic_briefings:
            return {
                "success": False,
                "error": f"No topic briefings or posts found for week {week_label}",
                "date": date_str,
                "week_start": week_start.isoformat(),
                "week_end": week_end.isoformat(),
                "subject_key": subject_key,
            }

        setup_ok = self.processor.setup_processor()
        try:
            if not setup_ok:
                raise RuntimeError("Gemini processor setup failed")
            await self.processor.connect()
            topic_result = await self.processor.weekly_topic_briefing(week_label, daily_topic_briefings)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic weekly topic briefing for %s: %s", week_label, exc)
            topic_result = self.processor._fallback_weekly_topic_briefing(week_label, daily_topic_briefings)
        finally:
            try:
                await self.processor.disconnect()
            except Exception:
                pass

        normalized_topics = self._normalize_weekly_topic_result(
            topic_result=topic_result,
            posts_map=combined_posts,
        )
        estimated_tokens = self._count_tokens(topic_result.get("weekly_briefing", ""))
        payload = {
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "days_covered": [item["date"] for item in daily_topic_briefings],
            "daily_briefings_used": len(daily_topic_briefings),
            "estimated_tokens": estimated_tokens,
            "topics": normalized_topics,
            "one_sentence_takeaway": self._briefing_takeaway(topic_result.get("weekly_briefing", "")),
        }
        saved = self.store_service.save_briefing(
            subject_type="weekly_briefing",
            subject_key=subject_key,
            variant="topics",
            render_format="markdown",
            title=f"Weekly Topic Briefing {week_label}",
            content=topic_result.get("weekly_briefing", ""),
            payload=payload,
        )
        references = self._save_artifact_references(
            artifact_type=self._briefing_artifact_type("weekly_briefing", "topics"),
            artifact_id=saved["id"],
            posts=list(combined_posts.values()),
        )

        return {
            "success": True,
            "briefing": topic_result.get("weekly_briefing", ""),
            "format": "markdown",
            "saved_briefing_id": saved["id"],
            "cached": False,
            "date": date_str,
            "week_start": week_start.isoformat(),
            "week_end": week_end.isoformat(),
            "subject_key": subject_key,
            "daily_briefings_used": len(daily_topic_briefings),
            "days_covered": payload["days_covered"],
            "estimated_tokens": estimated_tokens,
            "topics": normalized_topics,
            "posts": combined_posts,
            "variant": "topics",
            "one_sentence_takeaway": self._briefing_takeaway(topic_result.get("weekly_briefing", "")),
            "references": references,
        }

    def _normalize_vertical_boundary(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.date().isoformat()
        if isinstance(value, date):
            return value.isoformat()
        text = str(value).strip()
        if not text:
            return None
        if "T" in text:
            return text.split("T", 1)[0]
        return text[:10]

    def _resolve_vertical_briefing_range(
        self,
        source_id: str,
        start_date: str | None,
        end_date: str | None,
    ) -> tuple[str | None, str | None]:
        if start_date and end_date:
            return start_date, end_date

        stats = self.posts_service.get_source_post_stats(source_id)
        post_count = int(stats.get("post_count") or 0)
        if post_count <= 0:
            return start_date, end_date

        latest_iso = self._normalize_vertical_boundary(stats.get("latest_published_at") or stats.get("latest_fetched_at"))
        oldest_iso = self._normalize_vertical_boundary(stats.get("oldest_published_at"))

        if not latest_iso:
            newest_posts = self.posts_service.get_posts_by_source(source_id, limit=1, offset=0)
            if newest_posts:
                latest_iso = self._normalize_vertical_boundary(
                    newest_posts[0].get("published_at") or newest_posts[0].get("fetched_at") or newest_posts[0].get("date")
                )

        if not oldest_iso:
            oldest_posts = self.posts_service.get_posts_by_source(source_id, limit=1, offset=max(0, post_count - 1))
            if oldest_posts:
                oldest_iso = self._normalize_vertical_boundary(
                    oldest_posts[0].get("published_at") or oldest_posts[0].get("fetched_at") or oldest_posts[0].get("date")
                )

        resolved_start = start_date or oldest_iso or latest_iso
        resolved_end = end_date or latest_iso or oldest_iso
        return resolved_start, resolved_end

    async def generate_source_vertical_briefing(
        self,
        source_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        """Generate a source-scoped vertical briefing across a date range."""
        start_date, end_date = self._resolve_vertical_briefing_range(source_id, start_date, end_date)
        if not start_date or not end_date:
            return {
                "success": False,
                "error": f"No stored posts found for source {source_id}",
                "vertical_briefing": "",
                "tracks": [],
                "posts": {},
                "source_id": source_id,
                "start_date": start_date,
                "end_date": end_date,
                "subject_key": self._vertical_subject_key(source_id, start_date or "none", end_date or "none"),
            }

        start = self._parse_date_str(start_date)
        end = self._parse_date_str(end_date)
        if end < start:
            return {
                "success": False,
                "error": "end_date must be on or after start_date",
                "vertical_briefing": "",
                "tracks": [],
                "posts": {},
                "source_id": source_id,
                "start_date": start_date,
                "end_date": end_date,
                "subject_key": self._vertical_subject_key(source_id, start_date, end_date),
            }

        subject_key = self._vertical_subject_key(source_id, start_date, end_date)
        if not refresh:
            cached = self.store_service.get_briefing("vertical_briefing", subject_key, "source")
            if cached and (cached.get("payload") or {}).get("briefing_version") == self.VERTICAL_BRIEFING_VERSION:
                return self._build_cached_vertical_briefing_response(
                    source_id=source_id,
                    start_date=start_date,
                    end_date=end_date,
                    subject_key=subject_key,
                    cached_briefing=cached,
                )

        source = self.sources_service.get_source_with_settings(source_id)
        source_label = (
            (source.get("settings") or {}).get("display_name")
            or source.get("handle_or_url")
            or source_id
        )
        posts = self.posts_service.get_posts_by_source_and_range(source_id, start, end)

        if not posts:
            return {
                "success": False,
                "error": f"No posts found for source {source_id} between {start_date} and {end_date}",
                "vertical_briefing": "",
                "tracks": [],
                "posts": {},
                "source_id": source_id,
                "source_label": source_label,
                "start_date": start_date,
                "end_date": end_date,
                "subject_key": subject_key,
            }

        self._ensure_vertical_supporting_memory(posts)
        posts = self._build_vertical_briefing_context(posts)
        source_profile = self._build_vertical_source_profile(posts)

        setup_ok = self.processor.setup_processor()
        try:
            if not setup_ok:
                raise RuntimeError("Gemini processor setup failed")
            await self.processor.connect()
            vertical_result = await self.processor.source_vertical_briefing(
                posts,
                source_label,
                start_date,
                end_date,
                source_profile=source_profile,
            )
        except Exception as exc:
            self.logger.warning(
                "Falling back to deterministic source vertical briefing for %s: %s",
                source_label,
                exc,
            )
            vertical_result = self.processor._fallback_source_vertical_briefing(
                source_label,
                start_date,
                end_date,
                posts,
            )
        finally:
            try:
                await self.processor.disconnect()
            except Exception:
                pass

        normalized = self._normalize_vertical_briefing_result(
            posts=posts,
            briefing_result=vertical_result,
            scope_label=source_label,
            start_date=start_date,
            end_date=end_date,
        )
        vertical_briefing = vertical_result.get("vertical_briefing", "")
        tracks = normalized["tracks"]
        posts_map = normalized["posts"]
        coverage = normalized["coverage"]
        if coverage.get("residual_backfill_used") or not str(vertical_briefing or "").strip():
            vertical_briefing = self.processor._build_vertical_briefing_markdown(
                scope_label=source_label,
                start_date=start_date,
                end_date=end_date,
                posts=posts,
                tracks=tracks,
            )
        estimated_tokens = self._count_tokens(vertical_briefing)
        unique_evidence_clusters = len(
            {
                str(post.get("vertical_evidence_cluster_key"))
                for post in posts
                if post.get("vertical_evidence_cluster_key")
            }
        )
        story_linked_posts = sum(1 for post in posts if post.get("vertical_story_titles"))
        entity_overlap_posts = sum(1 for post in posts if post.get("vertical_shared_entity_names"))
        event_overlap_posts = sum(1 for post in posts if post.get("vertical_shared_event_titles"))
        payload = {
            "briefing_version": self.VERTICAL_BRIEFING_VERSION,
            "scope_type": "source",
            "scope_id": source_id,
            "source_id": source_id,
            "source_label": source_label,
            "start_date": start_date,
            "end_date": end_date,
            "post_count": len(posts),
            "unique_evidence_clusters": unique_evidence_clusters,
            "story_linked_posts": story_linked_posts,
            "entity_overlap_posts": entity_overlap_posts,
            "event_overlap_posts": event_overlap_posts,
            "track_count": len(tracks),
            "estimated_tokens": estimated_tokens,
            "tracks": tracks,
            "coverage": coverage,
            "source_profile": source_profile,
            "signal_sources": ["stories", "entities", "events", "evidence"],
            "one_sentence_takeaway": self._briefing_takeaway(vertical_briefing),
        }
        saved = self.store_service.save_briefing(
            subject_type="vertical_briefing",
            subject_key=subject_key,
            variant="source",
            render_format="markdown",
            title=f"Vertical Briefing {source_label} {start_date} to {end_date}",
            content=vertical_briefing,
            payload=payload,
        )
        references = self._save_artifact_references(
            artifact_type="vertical_briefing",
            artifact_id=saved["id"],
            posts=posts,
        )

        return {
            "success": True,
            "briefing": vertical_briefing,
            "vertical_briefing": vertical_briefing,
            "format": "markdown",
            "saved_briefing_id": saved["id"],
            "cached": False,
            "scope_type": "source",
            "scope_id": source_id,
            "source_id": source_id,
            "source_label": source_label,
            "start_date": start_date,
            "end_date": end_date,
            "subject_key": subject_key,
            "posts_processed": len(posts),
            "total_posts_fetched": len(posts),
            "estimated_tokens": estimated_tokens,
            "tracks": tracks,
            "posts": posts_map,
            "variant": "source",
            "coverage": coverage,
            "source_profile": source_profile,
            "one_sentence_takeaway": self._briefing_takeaway(vertical_briefing),
            "references": references,
        }

    def _build_cached_topic_response(
        self,
        *,
        date_str: str,
        posts: List[Dict[str, Any]],
        cached_briefing: Dict[str, Any],
        include_unreferenced: bool,
    ) -> Dict[str, Any]:
        artifact_type = self._briefing_artifact_type("daily_briefing", "topics")
        normalized = self._normalize_topic_result(
            posts=posts,
            topic_result={
                "topics": (cached_briefing.get("payload") or {}).get("topics", []),
                "daily_briefing": cached_briefing.get("content", ""),
                "unreferenced_posts": (cached_briefing.get("payload") or {}).get("unreferenced_posts", []),
            },
            include_unreferenced=include_unreferenced,
        )

        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        if not self.topics_service.topics_exist_for_date(target_date):
            stored_topics = self._store_topic_briefing_topics(
                target_date=target_date,
                normalized_topics=normalized["topics"],
                unreferenced_post_ids=normalized["unreferenced_posts"],
                refresh=False,
            )
            normalized["topics"] = stored_topics
        else:
            normalized["topics"] = self._load_stored_topics(target_date)

        references = self._hydrate_artifact_references(artifact_type, cached_briefing.get("id"))
        if not references:
            references = self._save_artifact_references(
                artifact_type=artifact_type,
                artifact_id=cached_briefing.get("id"),
                posts=posts,
            )
        takeaway = (cached_briefing.get("payload") or {}).get("one_sentence_takeaway") or self._briefing_takeaway(
            cached_briefing.get("content", "")
        )

        return {
            "success": True,
            "enhanced": True,
            "briefing": cached_briefing.get("content", ""),
            "format": cached_briefing.get("render_format", "markdown"),
            "saved_briefing_id": cached_briefing.get("id"),
            "topics": normalized["topics"],
            "unreferenced_posts": normalized["unreferenced_posts"],
            "posts": normalized["posts"],
            "date": date_str,
            "posts_processed": len(posts),
            "total_posts_fetched": len(posts),
            "cached": True,
            "estimated_tokens": (cached_briefing.get("payload") or {}).get("estimated_tokens", self._count_tokens(cached_briefing.get("content", ""))),
            "one_sentence_takeaway": takeaway,
            "references": references,
        }

    def _build_cached_vertical_briefing_response(
        self,
        *,
        source_id: str,
        start_date: str,
        end_date: str,
        subject_key: str,
        cached_briefing: Dict[str, Any],
        ) -> Dict[str, Any]:
        payload = cached_briefing.get("payload") or {}
        tracks = payload.get("tracks") or []
        references = self._hydrate_artifact_references("vertical_briefing", cached_briefing.get("id"))
        post_ids: List[str] = []
        for track in tracks:
            if not isinstance(track, dict):
                continue
            for post_id in track.get("post_ids") or []:
                post_key = str(post_id)
                if post_key not in post_ids:
                    post_ids.append(post_key)
            for entry in track.get("timeline") or []:
                if not isinstance(entry, dict):
                    continue
                for post_id in entry.get("post_ids") or []:
                    post_key = str(post_id)
                    if post_key not in post_ids:
                        post_ids.append(post_key)

        posts = {
            post["id"]: post
            for post in self.posts_service.get_posts_by_ids(post_ids)
            if post.get("id")
        }
        return {
            "success": True,
            "briefing": cached_briefing.get("content", ""),
            "vertical_briefing": cached_briefing.get("content", ""),
            "format": cached_briefing.get("render_format", "markdown"),
            "saved_briefing_id": cached_briefing.get("id"),
            "cached": True,
            "scope_type": "source",
            "scope_id": source_id,
            "source_id": source_id,
            "source_label": payload.get("source_label") or source_id,
            "start_date": start_date,
            "end_date": end_date,
            "subject_key": subject_key,
            "posts_processed": payload.get("post_count", len(post_ids)),
            "total_posts_fetched": payload.get("post_count", len(post_ids)),
            "estimated_tokens": payload.get(
                "estimated_tokens",
                self._count_tokens(cached_briefing.get("content", "")),
            ),
            "tracks": tracks,
            "posts": posts,
            "variant": "source",
            "coverage": payload.get("coverage") or {},
            "source_profile": payload.get("source_profile") or {},
            "one_sentence_takeaway": payload.get("one_sentence_takeaway") or self._briefing_takeaway(cached_briefing.get("content", "")),
            "references": references,
        }

    def _normalize_vertical_briefing_result(
        self,
        *,
        posts: List[Dict[str, Any]],
        briefing_result: Dict[str, Any],
        scope_label: str,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        posts_map = {
            str(post["id"]): {
                **post,
                "post_id": str(post["id"]),
            }
            for post in posts
            if post.get("id")
        }

        normalized_tracks = self._normalize_vertical_tracks(
            posts_map=posts_map,
            raw_tracks=briefing_result.get("tracks") or [],
            start_index=1,
            existing_titles=None,
        )

        coverage = self._vertical_track_coverage(posts_map, normalized_tracks)
        residual_backfill_used = False
        if coverage["uncovered_post_ids"]:
            uncovered_posts = [
                posts_map[post_id]
                for post_id in coverage["uncovered_post_ids"]
                if post_id in posts_map
            ]
            residual_result = self.processor._fallback_source_vertical_briefing(
                scope_label,
                start_date,
                end_date,
                uncovered_posts,
            )
            residual_tracks = self._normalize_vertical_tracks(
                posts_map=posts_map,
                raw_tracks=residual_result.get("tracks") or [],
                start_index=len(normalized_tracks) + 1,
                existing_titles={str(track.get("title") or "").strip().lower() for track in normalized_tracks},
            )
            if residual_tracks:
                normalized_tracks.extend(residual_tracks)
                residual_backfill_used = True
                coverage = self._vertical_track_coverage(posts_map, normalized_tracks)

        if coverage["uncovered_post_ids"]:
            singleton_tracks = self._build_vertical_singleton_tracks(
                posts_map=posts_map,
                post_ids=coverage["uncovered_post_ids"],
                start_index=len(normalized_tracks) + 1,
            )
            if singleton_tracks:
                normalized_tracks.extend(singleton_tracks)
                residual_backfill_used = True
                coverage = self._vertical_track_coverage(posts_map, normalized_tracks)

        coverage["residual_backfill_used"] = residual_backfill_used

        return {
            "tracks": normalized_tracks,
            "posts": posts_map,
            "coverage": coverage,
        }

    def _normalize_vertical_tracks(
        self,
        *,
        posts_map: Dict[str, Dict[str, Any]],
        raw_tracks: List[Dict[str, Any]],
        start_index: int,
        existing_titles: set[str] | None,
    ) -> List[Dict[str, Any]]:
        normalized_tracks: List[Dict[str, Any]] = []
        seen_titles = set(existing_titles or set())

        for index, track in enumerate(raw_tracks, start=start_index):
            if not isinstance(track, dict):
                continue
            raw_post_ids = [str(post_id) for post_id in (track.get("post_ids") or [])]
            track_post_ids: List[str] = []
            for post_id in raw_post_ids:
                if post_id in posts_map and post_id not in track_post_ids:
                    track_post_ids.append(post_id)

            timeline_entries: List[Dict[str, Any]] = []
            for entry in track.get("timeline") or []:
                if not isinstance(entry, dict):
                    continue
                entry_post_ids: List[str] = []
                for post_id in entry.get("post_ids") or []:
                    post_key = str(post_id)
                    if post_key in posts_map and post_key not in entry_post_ids:
                        entry_post_ids.append(post_key)
                        if post_key not in track_post_ids:
                            track_post_ids.append(post_key)
                timeline_entries.append(
                    {
                        "date": entry.get("date"),
                        "summary": entry.get("summary"),
                        "post_ids": entry_post_ids,
                    }
                )

            if not track_post_ids:
                continue

            track_kind = str(track.get("track_kind") or "").strip()
            if track_kind not in {"project_thread", "recurring_theme", "one_off_update"}:
                track_kind = "recurring_theme" if len(track_post_ids) > 1 else "one_off_update"

            story_titles = [
                str(title).strip()
                for title in (track.get("story_titles") or [])
                if str(title).strip()
            ]
            entity_hints = [
                str(entity).strip()
                for entity in (track.get("entity_hints") or [])
                if str(entity).strip()
            ]
            evidence_cluster_count = int(track.get("evidence_cluster_count") or len(timeline_entries) or 1)
            raw_post_count = int(track.get("raw_post_count") or len(track_post_ids))
            unique_post_count = int(track.get("unique_post_count") or len(track_post_ids))
            title = track.get("title") or f"Track {index}"
            title_text = str(title).strip() or f"Track {index}"
            normalized_title = title_text.lower()
            if normalized_title in seen_titles:
                title_text = f"Additional: {title_text}"[:120]
                normalized_title = title_text.lower()
            seen_titles.add(normalized_title)

            normalized_tracks.append(
                {
                    "id": str(track.get("id") or f"track-{index}"),
                    "title": title_text,
                    "summary": track.get("summary") or "",
                    "track_kind": track_kind,
                    "post_ids": track_post_ids,
                    "timeline": timeline_entries,
                    "story_titles": story_titles,
                    "entity_hints": entity_hints,
                    "evidence_cluster_count": evidence_cluster_count,
                    "raw_post_count": raw_post_count,
                    "unique_post_count": unique_post_count,
                }
            )

        return normalized_tracks

    def _vertical_track_coverage(
        self,
        posts_map: Dict[str, Dict[str, Any]],
        tracks: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        covered_post_ids: List[str] = []
        for track in tracks:
            for post_id in track.get("post_ids") or []:
                post_key = str(post_id)
                if post_key in posts_map and post_key not in covered_post_ids:
                    covered_post_ids.append(post_key)

        uncovered_post_ids = [post_id for post_id in posts_map.keys() if post_id not in covered_post_ids]
        total_posts = len(posts_map)
        covered_posts = len(covered_post_ids)
        coverage_ratio = (covered_posts / total_posts) if total_posts else 1.0
        return {
            "total_posts": total_posts,
            "covered_posts": covered_posts,
            "coverage_ratio": round(coverage_ratio, 4),
            "covered_post_ids": covered_post_ids,
            "uncovered_post_ids": uncovered_post_ids,
        }

    def _build_vertical_singleton_tracks(
        self,
        *,
        posts_map: Dict[str, Dict[str, Any]],
        post_ids: List[str],
        start_index: int,
    ) -> List[Dict[str, Any]]:
        tracks: List[Dict[str, Any]] = []
        for offset, post_id in enumerate(post_ids):
            post = posts_map.get(post_id)
            if not post:
                continue
            title = self._vertical_fallback_track_hint(post) or post.get("title") or f"Track {start_index + offset}"
            summary = self.processor._post_brief(post)
            tracks.append(
                {
                    "id": f"track-{start_index + offset}",
                    "title": str(title)[:120],
                    "summary": summary,
                    "track_kind": "one_off_update",
                    "post_ids": [post_id],
                    "timeline": [
                        {
                            "date": self.processor._vertical_post_date(post),
                            "summary": summary,
                            "post_ids": [post_id],
                        }
                    ],
                    "story_titles": list(post.get("vertical_story_titles") or [])[:4],
                    "entity_hints": list(post.get("vertical_shared_entity_names") or post.get("vertical_entity_names") or [])[:4],
                    "evidence_cluster_count": 1,
                    "raw_post_count": 1,
                    "unique_post_count": 1,
                }
            )
        return tracks

    def _vertical_subject_key(self, source_id: str, start_date: str, end_date: str) -> str:
        return f"source:{source_id}:{start_date}:{end_date}"

    def _parse_date_str(self, value: str) -> date:
        return datetime.strptime(value, "%Y-%m-%d").date()

    def _build_vertical_briefing_context(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Annotate posts with story, entity, and evidence-dedupe signals."""
        if not posts:
            return posts

        try:
            story_links_by_post: Dict[str, List[Dict[str, Any]]] = {}
            entity_links_by_post: Dict[str, List[Dict[str, Any]]] = {}
            event_links_by_post: Dict[str, List[Dict[str, Any]]] = {}
            evidence_by_post: Dict[str, Dict[str, Any]] = {}
            entity_counts: Counter[str] = Counter()
            entity_display_by_key: Dict[str, str] = {}
            event_counts: Counter[str] = Counter()
            event_display_by_key: Dict[str, str] = {}
            category_counts: Counter[str] = Counter()
            category_display_by_key: Dict[str, str] = {}

            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    for post in posts:
                        post_id = str(post["id"])
                        story_links = self.stories_repo.get_stories_for_post(cur, post_id)
                        story_links_by_post[post_id] = story_links

                        entity_links = self.memory_repo.get_post_entities(cur, post_id)
                        entity_links_by_post[post_id] = entity_links
                        event_links = self.event_repo.get_post_event_evidence(cur, post_id)
                        event_links_by_post[post_id] = event_links

                        evidence_by_post[post_id] = self.evidence_repo.get_post_evidence_debug(cur, post_id)

                        seen_entity_keys: set[str] = set()
                        for entity_link in entity_links:
                            entity_key, entity_display = self._vertical_entity_signature(entity_link)
                            if not entity_key or entity_key in seen_entity_keys:
                                continue
                            seen_entity_keys.add(entity_key)
                            entity_counts[entity_key] += 1
                            entity_display_by_key.setdefault(entity_key, entity_display)

                        seen_event_keys: set[str] = set()
                        for event_key, event_display in self._vertical_event_pairs(event_links):
                            if event_key in seen_event_keys:
                                continue
                            seen_event_keys.add(event_key)
                            event_counts[event_key] += 1
                            event_display_by_key.setdefault(event_key, event_display)

                        seen_category_keys: set[str] = set()
                        for category_key, category_display in self._vertical_category_pairs(post):
                            if category_key in seen_category_keys:
                                continue
                            seen_category_keys.add(category_key)
                            category_counts[category_key] += 1
                            category_display_by_key.setdefault(category_key, category_display)

            cluster_map = self._vertical_evidence_clusters(posts, evidence_by_post)
            enriched_posts: List[Dict[str, Any]] = []
            for post in posts:
                post_id = str(post["id"])
                story_links = story_links_by_post.get(post_id, [])
                entity_links = entity_links_by_post.get(post_id, [])
                event_links = event_links_by_post.get(post_id, [])
                evidence = evidence_by_post.get(post_id) or {}
                cluster_info = cluster_map.get(post_id) or {"key": post_id, "size": 1, "members": [post_id]}

                story_titles = self._vertical_story_titles(story_links)
                entity_pairs = self._vertical_entity_pairs(entity_links)
                entity_pairs.sort(key=lambda item: (-entity_counts.get(item[0], 0), item[1].lower()))
                event_pairs = self._vertical_event_pairs(event_links)
                event_pairs.sort(key=lambda item: (-event_counts.get(item[0], 0), item[1].lower()))
                category_pairs = self._vertical_category_pairs(post)
                category_pairs.sort(key=lambda item: (-category_counts.get(item[0], 0), item[1].lower()))

                entity_names = [display for _, display in entity_pairs[:5]]
                shared_entity_names = [
                    entity_display_by_key[key]
                    for key, display in entity_pairs
                    if entity_counts.get(key, 0) > 1
                ][:4]
                event_names = [display for _, display in event_pairs[:5]]
                shared_event_titles = [
                    event_display_by_key[key]
                    for key, display in event_pairs
                    if event_counts.get(key, 0) > 1
                ][:4]
                category_names = [display for _, display in category_pairs[:5]]
                shared_category_names = [
                    category_display_by_key[key]
                    for key, display in category_pairs
                    if category_counts.get(key, 0) > 1
                ][:4]
                primary_story_title = story_titles[0] if story_titles else ""
                track_hint = (
                    primary_story_title
                    or " / ".join(shared_event_titles[:2])
                    or " / ".join(shared_entity_names[:2])
                    or " / ".join(shared_category_names[:2])
                    or " / ".join(event_names[:2])
                    or " / ".join(entity_names[:2])
                    or " / ".join(category_names[:2])
                    or self._vertical_fallback_track_hint(post)
                )

                enriched_posts.append(
                    {
                        **post,
                        "vertical_story_links": story_links,
                        "vertical_story_titles": story_titles,
                        "vertical_primary_story_title": primary_story_title,
                        "vertical_event_titles": event_names,
                        "vertical_shared_event_titles": shared_event_titles,
                        "vertical_entity_names": entity_names,
                        "vertical_shared_entity_names": shared_entity_names,
                        "vertical_category_names": category_names,
                        "vertical_shared_category_names": shared_category_names,
                        "vertical_entity_overlap_count": len(shared_entity_names),
                        "vertical_evidence_cluster_key": cluster_info["key"],
                        "vertical_evidence_cluster_size": cluster_info["size"],
                        "vertical_evidence_cluster_members": cluster_info["members"],
                        "vertical_evidence_weight": round(1.0 / cluster_info["size"], 3) if cluster_info["size"] else 1.0,
                        "vertical_track_hint": track_hint,
                    }
                )

            return enriched_posts
        except Exception as exc:
            self.logger.warning("Vertical briefing context enrichment failed: %s", exc)
            return posts

    def _vertical_evidence_clusters(
        self,
        posts: List[Dict[str, Any]],
        evidence_by_post: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        """Build conservative evidence-dedupe clusters for the supplied posts."""
        post_lookup = {str(post["id"]): post for post in posts if post.get("id")}
        if not post_lookup:
            return {}

        parent = {post_id: post_id for post_id in post_lookup}

        def find(value: str) -> str:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        def union(left: str, right: str) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root == right_root:
                return
            parent[right_root] = left_root

        shared_keys: Dict[str, List[str]] = defaultdict(list)
        safe_relation_types = {
            "exact_duplicate",
            "near_duplicate",
            "references_same_artifact",
            "syndicated_from",
            "translation_of",
        }

        for post_id, evidence in evidence_by_post.items():
            post_data = (evidence or {}).get("post") or {}
            for value in (
                post_data.get("normalized_url"),
                post_data.get("canonical_url"),
                post_data.get("content_hash"),
                post_data.get("title_hash"),
            ):
                if value:
                    shared_keys[f"value:{value}"].append(post_id)

            for artifact in (evidence or {}).get("artifacts") or []:
                artifact_id = artifact.get("id")
                if artifact_id:
                    shared_keys[f"artifact:{artifact_id}"].append(post_id)

            for direction in ("outgoing", "incoming"):
                for relation in ((evidence or {}).get("relations") or {}).get(direction, []):
                    if relation.get("relation_type") not in safe_relation_types:
                        continue
                    other_post_id = relation.get("to_post_id") if direction == "outgoing" else relation.get("from_post_id")
                    if other_post_id and other_post_id in parent:
                        union(post_id, other_post_id)

        for ids in shared_keys.values():
            if len(ids) < 2:
                continue
            first = ids[0]
            for other_id in ids[1:]:
                union(first, other_id)

        clusters: Dict[str, List[str]] = defaultdict(list)
        for post_id in post_lookup:
            clusters[find(post_id)].append(post_id)

        cluster_map: Dict[str, Dict[str, Any]] = {}
        for member_ids in clusters.values():
            member_ids.sort(key=lambda pid: self._vertical_post_sort_key(post_lookup.get(pid) or {}))
            canonical_id = member_ids[0]
            cluster_size = len(member_ids)
            for post_id in member_ids:
                cluster_map[post_id] = {
                    "key": canonical_id,
                    "members": member_ids,
                    "size": cluster_size,
                }
        return cluster_map

    def _vertical_post_sort_key(self, post: Dict[str, Any]) -> str:
        for key in ("published_at", "date", "fetched_at", "created_at"):
            value = post.get(key)
            if isinstance(value, datetime):
                return value.isoformat()
            if value:
                return str(value)
        return str(post.get("id") or "")

    def _vertical_fallback_track_hint(self, post: Dict[str, Any]) -> str:
        title = str(post.get("title") or "").strip()
        if title:
            return title
        content = " ".join(str(post.get("content") or "").split())
        if not content:
            return "recent update"
        return " ".join(content.split()[:8]).strip()

    def _vertical_entity_signature(self, entity_link: Dict[str, Any]) -> tuple[str, str]:
        confidence = float(entity_link.get("confidence") or 0.0)
        if confidence and confidence < 0.72:
            return "", ""
        entity = entity_link.get("entity") or {}
        mention = entity_link.get("mention") or {}
        display = (
            entity.get("canonical_name")
            or entity.get("normalized_name")
            or mention.get("mention_text")
            or entity_link.get("entity_id")
            or ""
        )
        display_text = str(display).strip()
        if not is_meaningful_entity_name(display_text):
            return "", ""
        normalized = normalize_entity_name(display_text) or display_text.lower()
        return normalized, display_text

    def _vertical_category_pairs(self, post: Dict[str, Any]) -> List[tuple[str, str]]:
        pairs: List[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_category in post.get("categories") or []:
            display = str(raw_category or "").strip()
            if not display:
                continue
            normalized = normalize_entity_name(display)
            if not normalized or normalized in seen:
                continue
            if normalized in {"rss", "reddit", "telegram", "youtube"}:
                continue
            if len(normalized) < 3:
                continue
            seen.add(normalized)
            pairs.append((normalized, display))
        return pairs

    def _vertical_event_pairs(self, event_links: List[Dict[str, Any]]) -> List[tuple[str, str]]:
        pairs: List[tuple[str, str]] = []
        seen: set[str] = set()
        for event_link in event_links:
            event = event_link.get("event") or {}
            title = str(event.get("title") or "").strip()
            event_type = str(event.get("event_type") or "").strip()
            display = title or event_type.replace("_", " ").title()
            normalized = re.sub(r"\s+", " ", display.lower()).strip()
            if not normalized or normalized in seen:
                continue
            if len(normalized) < 4:
                continue
            seen.add(normalized)
            pairs.append((normalized, display[:120]))
        return pairs

    def _build_vertical_source_profile(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        profile: Dict[str, Any] = {
            "posts_total": len(posts),
            "story_linked_posts": 0,
            "entity_overlap_posts": 0,
            "event_overlap_posts": 0,
            "dominant_story_titles": [],
            "dominant_entities": [],
            "dominant_events": [],
            "dominant_categories": [],
            "dominant_track_hints": [],
        }
        if not posts:
            return profile

        story_counts: Counter[str] = Counter()
        entity_counts: Counter[str] = Counter()
        event_counts: Counter[str] = Counter()
        category_counts: Counter[str] = Counter()
        track_hint_counts: Counter[str] = Counter()

        for post in posts:
            if post.get("vertical_story_titles"):
                profile["story_linked_posts"] += 1
            if post.get("vertical_shared_entity_names"):
                profile["entity_overlap_posts"] += 1
            if post.get("vertical_shared_event_titles"):
                profile["event_overlap_posts"] += 1

            for title in post.get("vertical_story_titles") or []:
                story_counts[str(title).strip()] += 1
            for entity in post.get("vertical_shared_entity_names") or post.get("vertical_entity_names") or []:
                entity_counts[str(entity).strip()] += 1
            for event_title in post.get("vertical_shared_event_titles") or post.get("vertical_event_titles") or []:
                event_counts[str(event_title).strip()] += 1
            for category in post.get("vertical_shared_category_names") or post.get("vertical_category_names") or []:
                category_counts[str(category).strip()] += 1

            track_hint = str(post.get("vertical_track_hint") or "").strip()
            if track_hint:
                track_hint_counts[track_hint] += 1

        profile["dominant_story_titles"] = [name for name, _ in story_counts.most_common(6)]
        profile["dominant_entities"] = [name for name, _ in entity_counts.most_common(8)]
        profile["dominant_events"] = [name for name, _ in event_counts.most_common(6)]
        profile["dominant_categories"] = [name for name, _ in category_counts.most_common(8)]
        profile["dominant_track_hints"] = [name for name, _ in track_hint_counts.most_common(8)]
        return profile

    def _ensure_vertical_supporting_memory(self, posts: List[Dict[str, Any]]) -> None:
        if not posts:
            return

        post_ids = [str(post.get("id") or "").strip() for post in posts if post.get("id")]
        if not post_ids:
            return

        total_posts = len(post_ids)
        try:
            with psycopg.connect(self.db_url) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT COUNT(DISTINCT post_id) FROM post_entities WHERE post_id = ANY(%s)",
                        (post_ids,),
                    )
                    entity_coverage = int(cur.fetchone()[0] or 0)
                    cur.execute(
                        "SELECT COUNT(DISTINCT post_id) FROM event_evidence WHERE post_id = ANY(%s)",
                        (post_ids,),
                    )
                    event_coverage = int(cur.fetchone()[0] or 0)

            if entity_coverage < max(1, int(total_posts * 0.7)):
                self.entity_memory_service.process_posts(posts)
            if event_coverage < max(1, int(total_posts * 0.4)):
                self.event_memory_service.process_posts(posts)
        except Exception as exc:
            self.logger.warning("Vertical memory backfill check failed: %s", exc)

    def _vertical_entity_pairs(self, entity_links: List[Dict[str, Any]]) -> List[tuple[str, str]]:
        pairs: List[tuple[str, str]] = []
        seen: set[str] = set()
        for entity_link in entity_links:
            entity_key, entity_display = self._vertical_entity_signature(entity_link)
            if not entity_key or entity_key in seen:
                continue
            seen.add(entity_key)
            pairs.append((entity_key, entity_display))
        return pairs

    def _vertical_story_titles(self, story_links: List[Dict[str, Any]]) -> List[str]:
        titles: List[str] = []
        seen: set[str] = set()
        for story in story_links:
            title = str(story.get("canonical_title") or "").strip()
            if not title:
                continue
            normalized = title.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            titles.append(title)
        return titles[:4]

    def _normalize_topic_result(
        self,
        *,
        posts: List[Dict[str, Any]],
        topic_result: Dict[str, Any],
        include_unreferenced: bool,
    ) -> Dict[str, Any]:
        posts_by_numeric = {str(index): post for index, post in enumerate(posts, start=1)}
        posts_by_id = {str(post["id"]): post for post in posts if post.get("id")}
        posts_map = {
            str(post["id"]): {
                **post,
                "post_id": str(post["id"]),
            }
            for post in posts
            if post.get("id")
        }

        topics: List[Dict[str, Any]] = []
        referenced_ids = set()
        for index, topic in enumerate(topic_result.get("topics", []), start=1):
            actual_ids: List[str] = []
            for raw_id in topic.get("post_ids", []) or []:
                post = posts_by_id.get(str(raw_id)) or posts_by_numeric.get(str(raw_id))
                if not post or not post.get("id"):
                    continue
                post_id = str(post["id"])
                if post_id in actual_ids:
                    continue
                actual_ids.append(post_id)
                referenced_ids.add(post_id)
            if not actual_ids:
                continue
            topics.append(
                {
                    "id": topic.get("id") or f"topic-{index}",
                    "title": topic.get("title") or f"Topic {index}",
                    "summary": topic.get("summary"),
                    "post_ids": actual_ids,
                    "is_outlier": bool(topic.get("is_outlier", False)),
                }
            )

        unreferenced_ids = [
            str(post["id"])
            for post in posts
            if post.get("id") and str(post["id"]) not in referenced_ids
        ]
        if not include_unreferenced:
            unreferenced_ids = []

        return {
            "topics": topics,
            "unreferenced_posts": unreferenced_ids,
            "posts": posts_map,
        }

    def _store_topic_briefing_topics(
        self,
        *,
        target_date,
        normalized_topics: List[Dict[str, Any]],
        unreferenced_post_ids: List[str],
        refresh: bool,
    ) -> List[Dict[str, Any]]:
        if refresh:
            self.topics_service.delete_topics_by_date(target_date)

        if self.topics_service.topics_exist_for_date(target_date):
            return self._load_stored_topics(target_date)

        stored_topics: List[Dict[str, Any]] = []
        for topic in normalized_topics:
            topic_id = self.topics_service.save_topic_with_posts(
                target_date=target_date,
                title=topic["title"],
                embedding=None,
                post_ids=topic["post_ids"],
                is_outlier=bool(topic.get("is_outlier", False)),
                summary=topic.get("summary"),
            )
            stored_topics.append(
                {
                    **topic,
                    "id": topic_id,
                }
            )

        if unreferenced_post_ids:
            outlier_topic_id = self.topics_service.save_topic_with_posts(
                target_date=target_date,
                title="Uncategorized Posts",
                embedding=None,
                post_ids=unreferenced_post_ids,
                is_outlier=True,
                summary="Posts that were not assigned to a named topic in the briefing.",
            )
            stored_topics.append(
                {
                    "id": outlier_topic_id,
                    "title": "Uncategorized Posts",
                    "summary": "Posts that were not assigned to a named topic in the briefing.",
                    "post_ids": list(unreferenced_post_ids),
                    "is_outlier": True,
                }
            )

        return stored_topics

    def _load_stored_topics(self, target_date) -> List[Dict[str, Any]]:
        stored = self.topics_service.get_topics_by_date(target_date)
        hydrated: List[Dict[str, Any]] = []
        for topic in stored:
            topic_posts = self.topics_service.get_posts_for_topic(topic["id"])
            hydrated.append(
                {
                    "id": topic["id"],
                    "title": topic["title"],
                    "summary": topic.get("summary"),
                    "post_ids": [post["id"] for post in topic_posts if post.get("id")],
                    "is_outlier": topic.get("is_outlier", False),
                }
            )
        return hydrated

    def _count_tokens(self, text: str) -> int:
        counter = getattr(self.processor, "count_tokens", None)
        if callable(counter):
            return int(counter(text))
        return max(1, len(str(text or "")) // 4)

    def _build_cached_weekly_topic_response(
        self,
        *,
        cached_briefing: Dict[str, Any],
        date_str: str,
        week_start: str,
        week_end: str,
        subject_key: str,
    ) -> Dict[str, Any]:
        payload = cached_briefing.get("payload") or {}
        normalized_topics = payload.get("topics") or []
        references = self._hydrate_artifact_references("weekly_topic_briefing", cached_briefing.get("id"))
        post_ids: List[str] = []
        for topic in normalized_topics:
            for post_id in topic.get("post_ids") or []:
                if post_id not in post_ids:
                    post_ids.append(post_id)
            for item in topic.get("timeline") or []:
                for post_id in item.get("post_ids") or []:
                    if post_id not in post_ids:
                        post_ids.append(post_id)

        posts = {
            post["id"]: post
            for post in self.posts_service.get_posts_by_ids(post_ids)
            if post.get("id")
        }
        return {
            "success": True,
            "briefing": cached_briefing.get("content", ""),
            "format": cached_briefing.get("render_format", "markdown"),
            "saved_briefing_id": cached_briefing.get("id"),
            "cached": True,
            "date": date_str,
            "week_start": week_start,
            "week_end": week_end,
            "subject_key": subject_key,
            "daily_briefings_used": payload.get("daily_briefings_used", 0),
            "days_covered": payload.get("days_covered", []),
            "estimated_tokens": payload.get("estimated_tokens", self._count_tokens(cached_briefing.get("content", ""))),
            "topics": normalized_topics,
            "posts": posts,
            "variant": "topics",
            "one_sentence_takeaway": payload.get("one_sentence_takeaway") or self._briefing_takeaway(cached_briefing.get("content", "")),
            "references": references,
        }

    def _normalize_weekly_topic_result(
        self,
        *,
        topic_result: Dict[str, Any],
        posts_map: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        normalized_topics: List[Dict[str, Any]] = []
        for index, topic in enumerate(topic_result.get("topics") or [], start=1):
            post_ids: List[str] = []
            for post_id in topic.get("post_ids") or []:
                post_key = str(post_id)
                if post_key in posts_map and post_key not in post_ids:
                    post_ids.append(post_key)

            timeline_entries: List[Dict[str, Any]] = []
            for entry in topic.get("timeline") or []:
                entry_post_ids: List[str] = []
                for post_id in entry.get("post_ids") or []:
                    post_key = str(post_id)
                    if post_key in posts_map and post_key not in entry_post_ids:
                        entry_post_ids.append(post_key)
                        if post_key not in post_ids:
                            post_ids.append(post_key)
                timeline_entries.append(
                    {
                        "date": entry.get("date"),
                        "summary": entry.get("summary"),
                        "source_topics": entry.get("source_topics") or [],
                        "post_ids": entry_post_ids,
                    }
                )

            normalized_topics.append(
                {
                    "id": topic.get("id") or f"weekly-topic-{index}",
                    "title": topic.get("title") or f"Weekly Topic {index}",
                    "summary": topic.get("summary"),
                    "post_ids": post_ids,
                    "timeline": timeline_entries,
                    "is_outlier": False,
                }
            )
        return normalized_topics
