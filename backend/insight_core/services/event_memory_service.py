"""Event memory orchestration for typed event extraction and debug views."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.db.repo_event_memory import EventMemoryRepository
from insight_core.db.repo_memory import MemoryRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.posts_service import PostsService
from insight_core.utils.event_memory import EVENT_MEMORY_VERSION, build_post_event_fields, extract_event_candidates


class EventMemoryService:
    """Orchestrate deterministic event extraction and persistence."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = EventMemoryRepository(db_url)
        self.entity_repo = MemoryRepository(db_url)
        self.posts_service = PostsService(db_url)
        self.logger = get_component_logger("event_memory_service")

    def build_post_events(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """Build deterministic event-memory fields without touching the database."""
        return build_post_event_fields(post)

    def get_post_event_debug(self, post_id: str) -> Dict[str, Any]:
        """Return the current event-memory debug view for a single post."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_post_events_debug(cur, post_id)

    def rebuild_post_events(self, post_id: str, *, job_run_id: str | None = None) -> Dict[str, Any]:
        """Reprocess a single stored post."""
        debug_view = self.get_post_event_debug(post_id)
        if not debug_view:
            raise ValueError(f"Post {post_id} not found")

        post = debug_view["post"]
        return self.process_post(post, source_id=post["source_id"], job_run_id=job_run_id)

    def rebuild_date_events(
        self,
        target_date: date,
        *,
        job_run_id: str | None = None,
        limit: int | None = None,
    ) -> Dict[str, Any]:
        """Reprocess all posts for one date."""
        posts = self.posts_service.get_posts_by_date(target_date)
        posts = list(reversed(posts))
        if limit is not None:
            posts = posts[: max(0, int(limit))]
        return self.process_posts(posts, job_run_id=job_run_id)

    def process_posts(
        self,
        posts: List[Dict[str, Any]],
        *,
        job_run_id: str | None = None,
    ) -> Dict[str, Any]:
        """Persist event-memory data for a batch of posts."""
        if not posts:
            return {
                "success": True,
                "posts_processed": 0,
                "events_created": 0,
                "event_evidence_created": 0,
                "event_entities_linked": 0,
                "memory_version": EVENT_MEMORY_VERSION,
            }

        processed = 0
        events_created = 0
        event_evidence_created = 0
        event_entities_linked = 0

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                for post in posts:
                    source_id = self._extract_source_id(post)
                    if not source_id:
                        continue

                    result = self._process_single_post(
                        cur,
                        post,
                        source_id=source_id,
                        job_run_id=job_run_id,
                    )
                    processed += 1
                    events_created += int(result.get("events_created", 0))
                    event_evidence_created += int(result.get("event_evidence_created", 0))
                    event_entities_linked += int(result.get("event_entities_linked", 0))
            conn.commit()

        return {
            "success": True,
            "posts_processed": processed,
            "events_created": events_created,
            "event_evidence_created": event_evidence_created,
            "event_entities_linked": event_entities_linked,
            "memory_version": EVENT_MEMORY_VERSION,
        }

    def process_post(
        self,
        post: Dict[str, Any],
        *,
        source_id: str | None = None,
        job_run_id: str | None = None,
    ) -> Dict[str, Any]:
        """Persist event-memory data for a single post."""
        post_id = post.get("id")
        if not post_id:
            raise ValueError("Post payload is missing an id")

        source_id = source_id or self._extract_source_id(post)
        if not source_id:
            raise ValueError(f"Post {post_id} is missing a source id")

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                result = self._process_single_post(
                    cur,
                    post,
                    source_id=source_id,
                    job_run_id=job_run_id,
                )
            conn.commit()

        return {
            "success": True,
            "post_id": post_id,
            "source_id": source_id,
            **result,
            "memory_version": EVENT_MEMORY_VERSION,
        }

    def _process_single_post(
        self,
        cur: psycopg.Cursor,
        post: Dict[str, Any],
        *,
        source_id: str,
        job_run_id: str | None = None,
    ) -> Dict[str, Any]:
        post_id = str(post["id"])
        event_fields = build_post_event_fields(post)
        event_candidates = event_fields.get("event_candidates") or extract_event_candidates(post)

        post_entities = self.entity_repo.get_post_entities(cur, post_id)
        events_created = 0
        event_evidence_created = 0
        event_entities_linked = 0

        for candidate in event_candidates:
            event_id = self.repo.upsert_event(cur, candidate)
            events_created += 1

            stance = "supports" if float(candidate.get("confidence", 0.0)) >= 0.75 else "mentions"
            if self.repo.upsert_event_evidence(
                cur,
                {
                    "event_id": event_id,
                    "post_id": post_id,
                    "stance": stance,
                    "evidence_snippet": candidate.get("evidence_snippet"),
                    "confidence": candidate.get("confidence", 0.0),
                    "extractor_version": candidate.get("extractor_version"),
                },
            ):
                event_evidence_created += 1

            for entity_link in self._select_event_entities(candidate["event_type"], post_entities):
                if self.repo.upsert_event_entity(
                    cur,
                    {
                        "event_id": event_id,
                        "entity_id": entity_link["entity_id"],
                        "role": entity_link["role"],
                    },
                ):
                    event_entities_linked += 1

        return {
            "events_created": events_created,
            "event_evidence_created": event_evidence_created,
            "event_entities_linked": event_entities_linked,
        }

    def _select_event_entities(self, event_type: str, post_entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not post_entities:
            return []

        role_map = {
            "release_launch": ["actor"],
            "funding": ["issuer", "target"],
            "partnership": ["actor", "partner"],
            "acquisition": ["acquirer", "acquired"],
            "leadership_change": ["actor", "target"],
            "policy_regulation": ["actor", "target"],
            "security_incident": ["affected", "actor"],
        }
        roles = role_map.get(event_type, ["actor", "target"])

        selected: List[Dict[str, Any]] = []
        seen_entity_ids: set[str] = set()
        for idx, entity in enumerate(post_entities):
            entity_id = entity.get("entity_id")
            if not entity_id or entity_id in seen_entity_ids:
                continue
            role = roles[min(idx, len(roles) - 1)]
            selected.append({"entity_id": entity_id, "role": role})
            seen_entity_ids.add(entity_id)
            if len(selected) >= len(roles):
                break
        return selected

    def _extract_source_id(self, post: Dict[str, Any]) -> str | None:
        source_id = post.get("source_id") or post.get("_source_id")
        return str(source_id) if source_id else None

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
