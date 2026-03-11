"""
DB-backed daily briefing generation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.processors.ai.gemini_processor import GeminiProcessor
from insight_core.services.posts_service import PostsService


class BriefingService:
    """Generate daily briefings from posts already stored in the database."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.posts_service = PostsService(db_url)
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

        if not self.processor.setup_processor():
            return {
                "success": False,
                "error": "AI processor setup failed: GEMINI_API_KEY missing or invalid.",
                "posts": posts,
                "date": date_str,
                "posts_processed": len(posts),
                "total_posts_fetched": len(posts),
            }

        await self.processor.connect()
        try:
            briefing = await self.processor.daily_briefing(posts)
        finally:
            await self.processor.disconnect()

        return {
            "success": True,
            "briefing": briefing,
            "posts": posts,
            "date": date_str,
            "posts_processed": len(posts),
            "total_posts_fetched": len(posts),
        }

    async def generate_daily_briefing_with_topics(
        self,
        date_str: str,
        include_unreferenced: bool = True,
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

        if not self.processor.setup_processor():
            return {
                "success": False,
                "error": "AI processor setup failed: GEMINI_API_KEY missing or invalid.",
                "topics": [],
                "posts": {},
                "date": date_str,
                "posts_processed": len(posts),
                "total_posts_fetched": len(posts),
            }

        await self.processor.connect()
        try:
            topic_result = await self.processor.topic_briefing_with_numeric_ids(posts)
        finally:
            await self.processor.disconnect()

        if "error" in topic_result:
            return {
                "success": False,
                "error": topic_result["error"],
                "topics": [],
                "posts": {},
                "date": date_str,
                "posts_processed": len(posts),
                "total_posts_fetched": len(posts),
            }

        indexed_posts = {
            str(index): {
                **post,
                "post_id": str(index),
            }
            for index, post in enumerate(posts, start=1)
        }

        referenced_ids = set()
        topics: List[Dict[str, Any]] = topic_result.get("topics", [])
        for topic in topics:
            valid_ids = [post_id for post_id in topic.get("post_ids", []) if post_id in indexed_posts]
            topic["post_ids"] = valid_ids
            referenced_ids.update(valid_ids)

        unreferenced_ids: List[str] = []
        if include_unreferenced:
            unreferenced_ids = [
                post_id
                for post_id in indexed_posts
                if post_id not in referenced_ids
            ]

        return {
            "success": True,
            "enhanced": True,
            "briefing": topic_result.get("daily_briefing", ""),
            "topics": topics,
            "unreferenced_posts": unreferenced_ids,
            "posts": indexed_posts,
            "date": date_str,
            "posts_processed": len(posts),
            "total_posts_fetched": len(posts),
        }
