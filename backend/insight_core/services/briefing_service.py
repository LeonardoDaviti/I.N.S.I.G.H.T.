"""
DB-backed daily briefing generation.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.processors.ai.gemini_processor import GeminiProcessor
from insight_core.services.briefings_store_service import BriefingsStoreService
from insight_core.services.posts_service import PostsService
from insight_core.services.topics_service import TopicsService


class BriefingService:
    """Generate daily briefings from posts already stored in the database."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.posts_service = PostsService(db_url)
        self.store_service = BriefingsStoreService(db_url)
        self.topics_service = TopicsService(db_url)
        self.processor = GeminiProcessor()
        self.logger = get_component_logger("briefing_service")

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
            },
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
            },
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
                }

        daily_briefings: List[Dict[str, Any]] = []
        for offset in range(7):
            current_date = week_start + timedelta(days=offset)
            current_key = current_date.isoformat()
            cached_daily = self.store_service.get_briefing("daily_briefing", current_key, "default")
            if cached_daily:
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
        }

    def _build_cached_topic_response(
        self,
        *,
        date_str: str,
        posts: List[Dict[str, Any]],
        cached_briefing: Dict[str, Any],
        include_unreferenced: bool,
    ) -> Dict[str, Any]:
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
        }

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
