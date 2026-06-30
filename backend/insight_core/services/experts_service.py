"""
Experts: briefing personas that run over one folder's sources.

An expert generates a topic briefing scoped to its folder, written in the
expert's own system prompt and focus.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.db.repo_experts import ExpertsRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.processors.ai.gemini_processor import GeminiProcessor
from insight_core.services.briefings_store_service import BriefingsStoreService
from insight_core.services.folders_service import FoldersService
from insight_core.services.posts_service import PostsService


class ExpertsService:
    """Manage experts and generate their folder-scoped briefings."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = ExpertsRepository(db_url)
        self.folders_service = FoldersService(db_url)
        self.posts_service = PostsService(db_url)
        self.store_service = BriefingsStoreService(db_url)
        self.processor = GeminiProcessor()
        self.logger = get_component_logger("experts_service")

    # ---- CRUD ----

    def list_experts(self) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_experts(cur)

    def list_scheduled_experts(self) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_scheduled_experts(cur)

    def get_expert(self, expert_id: str) -> Optional[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_expert(cur, expert_id)

    def create_expert(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                expert = self.repo.create_expert(cur, fields)
                conn.commit()
                return expert

    def update_expert(self, expert_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                expert = self.repo.update_expert(cur, expert_id, fields)
                conn.commit()
                if expert is None:
                    raise ValueError(f"Expert {expert_id} not found")
                return expert

    def delete_expert(self, expert_id: str) -> bool:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                deleted = self.repo.delete_expert(cur, expert_id)
                conn.commit()
                return deleted

    # ---- Briefing generation ----

    async def generate_expert_briefing(
        self, expert_id: str, as_of_date: str | None = None
    ) -> Dict[str, Any]:
        """Generate a folder-scoped topic briefing in the expert's persona."""
        expert = self.get_expert(expert_id)
        if not expert:
            return {"success": False, "error": f"Expert {expert_id} not found"}

        source_ids = self.folders_service.list_source_ids(expert["folder_id"])
        if not source_ids:
            return {"success": False, "error": "Expert's folder has no sources", "expert": expert}

        end_date = (
            datetime.strptime(as_of_date, "%Y-%m-%d").date()
            if as_of_date
            else datetime.now(timezone.utc).date()
        )
        lookback = int(expert.get("lookback_days") or 7)
        start_date = end_date - timedelta(days=lookback)

        posts = self.posts_service.get_posts_by_sources_and_range(source_ids, start_date, end_date)
        if not posts:
            return {
                "success": False,
                "error": f"No posts for this expert's sources between {start_date} and {end_date}",
                "expert": expert,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }

        setup_ok = self.processor.setup_processor()
        try:
            if not setup_ok:
                raise RuntimeError("Gemini processor setup failed")
            await self.processor.connect()
            result = await self.processor.expert_topic_briefing(
                posts,
                system_prompt=expert["system_prompt"],
                focus_instructions=expert.get("focus_instructions") or "",
            )
        except Exception as exc:
            self.logger.warning("Falling back to deterministic expert briefing for %s: %s", expert_id, exc)
            fallback = self.processor._fallback_topic_briefing(posts)
            result = {"summary": fallback.get("daily_briefing", ""), "topics": fallback.get("topics", [])}
        finally:
            try:
                await self.processor.disconnect()
            except Exception:
                pass

        summary = str(result.get("summary") or "")
        topics, posts_map = self._resolve_numeric_topics(posts, result.get("topics") or [])

        saved = self.store_service.save_briefing(
            subject_type="expert_briefing",
            subject_key=expert_id,
            variant=expert.get("output_variant") or "topics",
            render_format="markdown",
            title=f"{expert['name']} — {start_date} to {end_date}",
            content=summary,
            payload={
                "expert_id": expert_id,
                "expert_name": expert["name"],
                "folder_id": expert["folder_id"],
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "posts_processed": len(posts),
                "topics": topics,
            },
        )

        return {
            "success": True,
            "expert": expert,
            "briefing": summary,
            "format": "markdown",
            "saved_briefing_id": saved["id"],
            "topics": topics,
            "posts": posts_map,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "posts_processed": len(posts),
        }

    def get_latest_briefing(self, expert_id: str) -> Dict[str, Any]:
        """Fetch the most recent stored briefing for an expert."""
        expert = self.get_expert(expert_id)
        if not expert:
            return {"success": False, "error": f"Expert {expert_id} not found"}
        cached = self.store_service.get_briefing(
            "expert_briefing", expert_id, expert.get("output_variant") or "topics"
        )
        if not cached:
            return {"success": False, "error": "No briefing generated yet", "expert": expert}
        payload = cached.get("payload") or {}
        return {
            "success": True,
            "expert": expert,
            "briefing": cached.get("content", ""),
            "format": cached.get("render_format", "markdown"),
            "saved_briefing_id": cached.get("id"),
            "topics": payload.get("topics", []),
            "start_date": payload.get("start_date"),
            "end_date": payload.get("end_date"),
            "posts_processed": payload.get("posts_processed", 0),
        }

    def _resolve_numeric_topics(
        self, posts: List[Dict[str, Any]], raw_topics: List[Dict[str, Any]]
    ) -> tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
        """Map numeric (1-based) post ids from the model back to real post UUIDs."""
        index_to_post = {str(i): post for i, post in enumerate(posts, start=1)}
        topics: List[Dict[str, Any]] = []
        posts_map: Dict[str, Dict[str, Any]] = {}
        for raw in raw_topics:
            if not isinstance(raw, dict):
                continue
            real_ids: List[str] = []
            for numeric_id in raw.get("post_ids") or []:
                post = index_to_post.get(str(numeric_id))
                if not post:
                    continue
                post_id = str(post["id"])
                if post_id not in real_ids:
                    real_ids.append(post_id)
                posts_map[post_id] = post
            topics.append(
                {
                    "title": str(raw.get("title") or "Untitled topic"),
                    "summary": str(raw.get("summary") or ""),
                    "post_ids": real_ids,
                }
            )
        return topics, posts_map
