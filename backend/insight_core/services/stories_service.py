"""Story storage and read orchestration."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.db.repo_stories import StoriesRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.posts_service import PostsService


class StoriesService:
    """Thin service wrapper around story persistence."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = StoriesRepository(db_url)
        self.posts_service = PostsService(db_url)
        self.logger = get_component_logger("stories_service")

    # ===============================
    # WRITE OPERATIONS
    # ===============================

    def create_story(
        self,
        *,
        canonical_title: str,
        canonical_summary: str | None = None,
        story_kind: str = "other",
        status: str = "active",
        anchor_post_id: str | None = None,
        anchor_confidence: float = 0.0,
        first_seen_at: Any | None = None,
        last_seen_at: Any | None = None,
        created_by_method: str = "auto",
        resolution_version: str | None = None,
        metadata: Dict[str, Any] | None = None,
        post_ids: List[str] | None = None,
    ) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                story_id = self.repo.insert_story(
                    cur,
                    {
                        "canonical_title": canonical_title,
                        "canonical_summary": canonical_summary,
                        "story_kind": story_kind,
                        "status": status,
                        "anchor_post_id": anchor_post_id,
                        "anchor_confidence": anchor_confidence,
                        "first_seen_at": first_seen_at,
                        "last_seen_at": last_seen_at,
                        "created_by_method": created_by_method,
                        "resolution_version": resolution_version,
                        "metadata": metadata or {},
                    },
                )

                attached_post_ids: List[str] = []
                ordered_post_ids: List[str] = list(post_ids or [])
                if anchor_post_id and anchor_post_id not in ordered_post_ids:
                    ordered_post_ids.insert(0, anchor_post_id)

                for post_id in ordered_post_ids:
                    if post_id in attached_post_ids:
                        continue
                    if self.repo.upsert_story_post(
                        cur,
                        story_id,
                        post_id,
                        role="anchor" if post_id == anchor_post_id else "context",
                        relevance_score=1.0 if post_id == anchor_post_id else 0.5,
                        anchor_score=1.0 if post_id == anchor_post_id else 0.0,
                        is_anchor_candidate=post_id == anchor_post_id,
                        evidence_weight=1.0 if post_id == anchor_post_id else 0.5,
                        added_by_method=created_by_method,
                    ):
                        attached_post_ids.append(post_id)
                conn.commit()

        return {
            "story_id": story_id,
            "canonical_title": canonical_title,
            "post_ids": attached_post_ids,
        }

    def update_story(self, story_id: str, **fields: Any) -> bool:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                updated = self.repo.update_story(cur, story_id, **fields)
                if updated:
                    conn.commit()
                return updated

    def update_story_anchor(
        self,
        story_id: str,
        anchor_post_id: str | None,
        *,
        anchor_confidence: float = 0.0,
    ) -> bool:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                updated = self.repo.update_story_anchor(cur, story_id, anchor_post_id, anchor_confidence)
                if updated:
                    conn.commit()
                return updated

    def attach_post_to_story(
        self,
        story_id: str,
        post_id: str,
        *,
        role: str,
        relevance_score: float = 0.0,
        anchor_score: float = 0.0,
        is_anchor_candidate: bool = False,
        evidence_weight: float = 0.0,
        added_by_method: str = "auto",
        metadata: Dict[str, Any] | None = None,
    ) -> bool:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                attached = self.repo.upsert_story_post(
                    cur,
                    story_id,
                    post_id,
                    role=role,
                    relevance_score=relevance_score,
                    anchor_score=anchor_score,
                    is_anchor_candidate=is_anchor_candidate,
                    evidence_weight=evidence_weight,
                    added_by_method=added_by_method,
                    metadata=metadata,
                )
                if attached:
                    conn.commit()
                return attached

    def create_story_update(
        self,
        story_id: str,
        update_date: date,
        title: str,
        summary: str,
        *,
        importance_score: float = 0.0,
        created_by_method: str = "auto",
        metadata: Dict[str, Any] | None = None,
        post_ids: List[str] | None = None,
    ) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                update_id = self.repo.insert_story_update(
                    cur,
                    {
                        "story_id": story_id,
                        "update_date": update_date,
                        "title": title,
                        "summary": summary,
                        "importance_score": importance_score,
                        "created_by_method": created_by_method,
                        "metadata": metadata or {},
                    },
                )

                attached_post_ids: List[str] = []
                if post_ids:
                    for post_id in post_ids:
                        if self.repo.upsert_story_update_post(cur, update_id, post_id):
                            attached_post_ids.append(post_id)
                conn.commit()

        return {
            "story_update_id": update_id,
            "story_id": story_id,
            "post_ids": attached_post_ids,
        }

    def attach_post_to_story_update(self, story_update_id: str, post_id: str, *, role: str | None = None) -> bool:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                attached = self.repo.upsert_story_update_post(cur, story_update_id, post_id, role=role)
                if attached:
                    conn.commit()
                return attached

    # ===============================
    # READ OPERATIONS
    # ===============================

    def get_story(self, story_id: str) -> Optional[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_story_by_id(cur, story_id)

    def list_stories(
        self,
        *,
        status: str | None = None,
        story_kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_stories(
                    cur,
                    status=status,
                    story_kind=story_kind,
                    limit=limit,
                    offset=offset,
                )

    def get_story_detail(self, story_id: str) -> Optional[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_story_detail(cur, story_id)

    def get_story_timeline(self, story_id: str) -> Optional[Dict[str, Any]]:
        detail = self.get_story_detail(story_id)
        if not detail:
            return None
        return {
            "story_id": story_id,
            "story": {
                key: value
                for key, value in detail.items()
                if key not in {"posts", "posts_by_role", "updates", "timeline"}
            },
            "timeline": detail.get("timeline", []),
        }

    def get_stories_for_post(self, post_id: str) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_stories_for_post(cur, post_id)

    def get_post_story(self, post_id: str) -> Dict[str, Any]:
        stories = self.get_stories_for_post(post_id)
        return {
            "post_id": post_id,
            "stories": stories,
            "primary_story": stories[0] if stories else None,
        }
