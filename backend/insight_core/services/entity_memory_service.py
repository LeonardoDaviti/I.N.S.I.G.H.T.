"""Entity memory orchestration for mentions, provisional entities, and debug views."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

import psycopg

from insight_core.db.repo_memory import MemoryRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.posts_service import PostsService
from insight_core.services.sources_service import SourcesService
from insight_core.utils.entity_memory import (
    ENTITY_MEMORY_VERSION,
    build_post_memory_fields,
    detect_script,
    extract_entity_mentions,
    normalize_entity_name,
)


class EntityMemoryService:
    """Orchestrate deterministic entity-memory extraction and persistence."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = MemoryRepository(db_url)
        self.posts_service = PostsService(db_url)
        self.sources_service = SourcesService(db_url)
        self.logger = get_component_logger("entity_memory_service")

    def build_post_memory(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """Build deterministic post-memory fields and mention candidates."""
        return {
            "post_fields": build_post_memory_fields(post),
            "mentions": extract_entity_mentions(post),
        }

    def get_post_memory_debug(self, post_id: str) -> Dict[str, Any]:
        """Return the current entity-memory debug view for a single post."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_post_memory_debug(cur, post_id)

    def rebuild_post_memory(self, post_id: str, *, job_run_id: str | None = None) -> Dict[str, Any]:
        """Reprocess a single stored post."""
        debug_view = self.get_post_memory_debug(post_id)
        if not debug_view:
            raise ValueError(f"Post {post_id} not found")

        post = debug_view["post"]
        return self.process_post(post, source_id=post["source_id"], job_run_id=job_run_id)

    def rebuild_date_memory(
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
        """Persist entity-memory data for a batch of posts."""
        if not posts:
            return {
                "success": True,
                "posts_processed": 0,
                "mentions_created": 0,
                "entities_linked": 0,
                "source_profiles_updated": 0,
                "memory_version": ENTITY_MEMORY_VERSION,
            }

        processed = 0
        mentions_created = 0
        entities_linked = 0
        source_profiles_updated = 0
        source_cache: Dict[str, Dict[str, Any]] = {}

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                for post in posts:
                    source_id = self._extract_source_id(post)
                    if not source_id:
                        continue

                    if source_id not in source_cache:
                        source_cache[source_id] = self._build_source_profile(source_id)
                        if self.repo.upsert_source_profile(cur, source_id, source_cache[source_id]):
                            source_profiles_updated += 1

                    result = self._process_single_post(
                        cur,
                        post,
                        source_id=source_id,
                        source_profile=source_cache[source_id],
                        job_run_id=job_run_id,
                    )
                    processed += 1
                    mentions_created += int(result.get("mentions_created", 0))
                    entities_linked += int(result.get("entities_linked", 0))
            conn.commit()

        return {
            "success": True,
            "posts_processed": processed,
            "mentions_created": mentions_created,
            "entities_linked": entities_linked,
            "source_profiles_updated": source_profiles_updated,
            "memory_version": ENTITY_MEMORY_VERSION,
        }

    def process_post(
        self,
        post: Dict[str, Any],
        *,
        source_id: str | None = None,
        source_profile: Dict[str, Any] | None = None,
        job_run_id: str | None = None,
    ) -> Dict[str, Any]:
        """Persist entity-memory data for a single post."""
        post_id = post.get("id")
        if not post_id:
            raise ValueError("Post payload is missing an id")

        source_id = source_id or self._extract_source_id(post)
        if not source_id:
            raise ValueError(f"Post {post_id} is missing a source id")

        if source_profile is None:
            source_profile = self._build_source_profile(source_id)

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.upsert_source_profile(cur, source_id, source_profile)
                result = self._process_single_post(
                    cur,
                    post,
                    source_id=source_id,
                    source_profile=source_profile,
                    job_run_id=job_run_id,
                )
            conn.commit()

        return {
            "success": True,
            "post_id": post_id,
            "source_id": source_id,
            **result,
            "memory_version": ENTITY_MEMORY_VERSION,
        }

    def _process_single_post(
        self,
        cur: psycopg.Cursor,
        post: Dict[str, Any],
        *,
        source_id: str,
        source_profile: Dict[str, Any],
        job_run_id: str | None = None,
    ) -> Dict[str, Any]:
        post_id = str(post["id"])
        memory_fields = build_post_memory_fields(post)
        memory_updated = self.repo.update_post_memory_fields(cur, post_id, memory_fields)
        mentions = extract_entity_mentions(post)

        mentions_created = 0
        entities_linked = 0
        for mention in mentions:
            mention_payload = {
                **mention,
                "post_id": post_id,
                "metadata": {
                    **(mention.get("metadata") or {}),
                    "source_id": source_id,
                    "source_hint": self._source_hint(source_profile, post),
                },
            }
            mention_id = self.repo.insert_entity_mention(cur, mention_payload)
            mention_payload["id"] = mention_id
            mentions_created += 1

            resolution = self._resolve_mention(
                cur,
                mention_id,
                mention_payload,
                source_profile=source_profile,
            )
            if resolution["entity_id"]:
                entities_linked += 1
                self.repo.upsert_post_entity(
                    cur,
                    {
                        "post_id": post_id,
                        "entity_id": resolution["entity_id"],
                        "mention_id": mention_id,
                        "resolution_status": resolution["resolution_status"],
                        "confidence": resolution["confidence"],
                        "role": mention_payload.get("role"),
                        "metadata": {
                            "source_id": source_id,
                            "source_hint": self._source_hint(source_profile, post),
                            "resolved_method": resolution["candidate_method"],
                            "job_run_id": job_run_id,
                        },
                    },
                )

        return {
            "memory_updated": memory_updated,
            "mentions_created": mentions_created,
            "entities_linked": entities_linked,
        }

    def _resolve_mention(
        self,
        cur: psycopg.Cursor,
        mention_id: str,
        mention: Dict[str, Any],
        *,
        source_profile: Dict[str, Any],
    ) -> Dict[str, Any]:
        exact_candidates = self.repo.get_exact_entity_candidates(
            cur,
            mention["entity_type_predicted"],
            mention["normalized_mention"],
        )
        mention_text = mention["mention_text"]
        canonical_name = self._canonical_name_from_mention(mention_text)
        canonical_name_pivot = normalize_entity_name(canonical_name) or None
        source_hint = mention.get("metadata", {}).get("source_hint")

        if len(exact_candidates) == 1:
            entity = exact_candidates[0]
            entity_id = entity["id"]
            self.repo.touch_entity(cur, entity_id, seen_at=self._now())
            self.repo.upsert_entity_alias(
                cur,
                {
                    "entity_id": entity_id,
                    "alias": canonical_name,
                    "normalized_alias": mention["normalized_mention"],
                    "language_code": mention.get("language_code"),
                    "script": detect_script(canonical_name),
                    "alias_type": "extracted",
                    "source_hint": source_hint,
                },
            )
            self.repo.upsert_mention_candidate(
                cur,
                {
                    "mention_id": mention_id,
                    "entity_id": entity_id,
                    "candidate_method": "exact_alias",
                    "score": max(0.92, float(mention.get("extractor_confidence", 0.0))),
                    "selected": True,
                    "resolver_version": ENTITY_MEMORY_VERSION,
                },
            )
            return {
                "entity_id": entity_id,
                "resolution_status": "resolved",
                "confidence": max(0.92, float(mention.get("extractor_confidence", 0.0))),
                "candidate_method": "exact_alias",
            }

        if exact_candidates:
            entity_id = self.repo.insert_entity(
                cur,
                {
                    "entity_type": mention["entity_type_predicted"],
                    "canonical_name": canonical_name,
                    "canonical_name_pivot": canonical_name_pivot,
                    "normalized_name": mention["normalized_mention"],
                    "review_state": "needs_review",
                    "first_seen_at": self._now(),
                    "last_seen_at": self._now(),
                },
            )
            self.repo.upsert_entity_alias(
                cur,
                {
                    "entity_id": entity_id,
                    "alias": canonical_name,
                    "normalized_alias": mention["normalized_mention"],
                    "language_code": mention.get("language_code"),
                    "script": detect_script(canonical_name),
                    "alias_type": "canonical",
                    "source_hint": source_hint,
                },
            )
            for candidate in exact_candidates:
                self.repo.upsert_mention_candidate(
                    cur,
                    {
                        "mention_id": mention_id,
                        "entity_id": candidate["id"],
                        "candidate_method": "ambiguous_exact_alias",
                        "score": 0.5,
                        "selected": False,
                        "resolver_version": ENTITY_MEMORY_VERSION,
                    },
                )
            self.repo.upsert_mention_candidate(
                cur,
                {
                    "mention_id": mention_id,
                    "entity_id": entity_id,
                    "candidate_method": "provisional_create",
                    "score": 0.35,
                    "selected": True,
                    "resolver_version": ENTITY_MEMORY_VERSION,
                },
            )
            return {
                "entity_id": entity_id,
                "resolution_status": "needs_review",
                "confidence": 0.0,
                "candidate_method": "provisional_create",
            }

        entity_id = self.repo.insert_entity(
            cur,
            {
                "entity_type": mention["entity_type_predicted"],
                "canonical_name": canonical_name,
                "canonical_name_pivot": canonical_name_pivot,
                "normalized_name": mention["normalized_mention"],
                "review_state": "provisional",
                "first_seen_at": self._now(),
                "last_seen_at": self._now(),
            },
        )
        self.repo.upsert_entity_alias(
            cur,
            {
                "entity_id": entity_id,
                "alias": canonical_name,
                "normalized_alias": mention["normalized_mention"],
                "language_code": mention.get("language_code"),
                "script": detect_script(canonical_name),
                "alias_type": "canonical",
                "source_hint": source_hint,
            },
        )
        self.repo.upsert_mention_candidate(
            cur,
            {
                "mention_id": mention_id,
                "entity_id": entity_id,
                "candidate_method": "provisional_create",
                "score": max(0.55, float(mention.get("extractor_confidence", 0.0)) - 0.1),
                "selected": True,
                "resolver_version": ENTITY_MEMORY_VERSION,
            },
        )
        return {
            "entity_id": entity_id,
            "resolution_status": "provisional",
            "confidence": max(0.55, float(mention.get("extractor_confidence", 0.0)) - 0.1),
            "candidate_method": "provisional_create",
        }

    def _build_source_profile(self, source_id: str) -> Dict[str, Any]:
        source = self.sources_service.get_source_with_settings(source_id)
        settings = source.get("settings") or {}
        return {
            "language_code": settings.get("language_code"),
            "publisher_type": self._publisher_type_for_platform(source.get("platform")),
            "country_code": settings.get("country_code"),
            "is_primary_reporter": bool(settings.get("is_primary_reporter", False)),
            "reliability_notes": settings.get("reliability_notes"),
        }

    def _publisher_type_for_platform(self, platform: str | None) -> str | None:
        mapping = {
            "reddit": "community",
            "rss": "feed",
            "youtube": "video",
        }
        return mapping.get(platform or "", "feed")

    def _source_hint(self, source_profile: Dict[str, Any], post: Dict[str, Any]) -> str | None:
        hint = post.get("source_display_name") or post.get("source") or post.get("handle_or_url")
        if hint:
            return str(hint)
        publisher = source_profile.get("publisher_type")
        if publisher:
            return str(publisher)
        return None

    def _canonical_name_from_mention(self, mention_text: str) -> str:
        candidate = str(mention_text or "").strip()
        if candidate.startswith("@") or candidate.startswith("#"):
            candidate = candidate[1:]
        candidate = candidate.strip()
        return candidate or str(mention_text or "").strip()

    def _extract_source_id(self, post: Dict[str, Any]) -> str | None:
        source_id = post.get("source_id") or post.get("_source_id")
        return str(source_id) if source_id else None

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)
