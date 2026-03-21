"""Evidence foundation orchestration and debug helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional

import psycopg

from insight_core.db.repo_evidence import EvidenceRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.posts_service import PostsService
from insight_core.utils.artifact_extraction import extract_artifacts
from insight_core.utils.content_fingerprints import normalize_text, strip_html
from insight_core.utils.evidence import EVIDENCE_NORMALIZATION_VERSION, build_post_evidence_fields


class EvidenceFoundationService:
    """Orchestrate evidence enrichment, debug views, and backfills."""

    RELATION_METHOD = "evidence_foundation_v1"
    NEAR_DUPLICATE_WINDOW_DAYS = 7

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = EvidenceRepository(db_url)
        self.posts_service = PostsService(db_url)
        self.logger = get_component_logger("evidence_foundation_service")

    def build_post_evidence(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """Build normalized evidence fields without touching the database."""
        return build_post_evidence_fields(post)

    def get_post_evidence_debug(self, post_id: str) -> Dict[str, Any]:
        """Return the current evidence debug view for a single post."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_post_evidence_debug(cur, post_id)

    def rebuild_post_evidence(self, post_id: str, *, job_run_id: str | None = None) -> Dict[str, Any]:
        """Re-run evidence enrichment for a single stored post."""
        debug_view = self.get_post_evidence_debug(post_id)
        if not debug_view:
            raise ValueError(f"Post {post_id} not found")

        post = debug_view["post"]
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                result = self.process_post(
                    cur,
                    post_id,
                    post,
                    job_run_id=job_run_id,
                    allow_relations=True,
                )
            conn.commit()

        return result

    def rebuild_source_evidence(
        self,
        source_id: str,
        *,
        job_run_id: str | None = None,
        limit: int | None = None,
    ) -> Dict[str, Any]:
        """Re-run evidence enrichment for all posts belonging to one source."""
        posts = self.posts_service.get_posts_by_source(source_id)
        posts = list(reversed(posts))
        if limit is not None:
            posts = posts[: max(0, int(limit))]

        processed = 0
        artifacts = 0
        relations = 0
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                for post in posts:
                    result = self.process_post(
                        cur,
                        post["id"],
                        post,
                        job_run_id=job_run_id,
                        allow_relations=True,
                    )
                    processed += 1
                    artifacts += int(result.get("artifacts_linked", 0))
                    relations += int(result.get("relations_created", 0))
            conn.commit()

        return {
            "success": True,
            "source_id": source_id,
            "posts_processed": processed,
            "artifacts_linked": artifacts,
            "relations_created": relations,
        }

    def rebuild_date_evidence(
        self,
        target_date: date,
        *,
        job_run_id: str | None = None,
        limit: int | None = None,
    ) -> Dict[str, Any]:
        """Re-run evidence enrichment for all posts on one date."""
        posts = self.posts_service.get_posts_by_date(target_date)
        posts = list(reversed(posts))
        if limit is not None:
            posts = posts[: max(0, int(limit))]

        processed = 0
        artifacts = 0
        relations = 0
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                for post in posts:
                    result = self.process_post(
                        cur,
                        post["id"],
                        post,
                        job_run_id=job_run_id,
                        allow_relations=True,
                    )
                    processed += 1
                    artifacts += int(result.get("artifacts_linked", 0))
                    relations += int(result.get("relations_created", 0))
            conn.commit()

        return {
            "success": True,
            "date": target_date.isoformat(),
            "posts_processed": processed,
            "artifacts_linked": artifacts,
            "relations_created": relations,
        }

    def process_post(
        self,
        cur: psycopg.Cursor,
        post_id: str,
        post: Dict[str, Any],
        *,
        job_run_id: str | None = None,
        allow_relations: bool = True,
    ) -> Dict[str, Any]:
        """Persist evidence fields, artifacts, and conservative relations for one post."""
        evidence = self.build_post_evidence(post)
        evidence_updated = self.repo.update_post_evidence(cur, post_id, evidence)
        artifact_payloads = extract_artifacts(post)

        artifact_ids: List[str] = []
        artifact_links = 0
        for artifact in artifact_payloads:
            artifact_id = self.repo.upsert_artifact(cur, artifact)
            artifact_ids.append(artifact_id)
            if self.repo.link_post_artifact(
                cur,
                post_id,
                artifact_id,
                artifact.get("relation_type", "links_to"),
                artifact.get("confidence", 0.0),
                artifact.get("is_primary", False),
                metadata=artifact.get("metadata") or {},
            ):
                artifact_links += 1

        relations_created = 0
        if allow_relations:
            relations = self._detect_relations(
                cur,
                post_id,
                post,
                evidence,
                artifact_ids,
                job_run_id=job_run_id,
            )
            for relation in relations:
                stored = self.repo.upsert_post_relation(
                    cur,
                    relation["from_post_id"],
                    relation["to_post_id"],
                    relation["relation_type"],
                    relation["method"],
                    relation["confidence"],
                    job_run_id=job_run_id,
                    metadata=relation.get("metadata") or {},
                )
                if stored:
                    relations_created += 1

        return {
            "post_id": post_id,
            "evidence_updated": evidence_updated,
            "artifacts_linked": artifact_links,
            "artifact_count": len(artifact_ids),
            "relations_created": relations_created,
            "evidence_version": EVIDENCE_NORMALIZATION_VERSION,
        }

    def _detect_relations(
        self,
        cur: psycopg.Cursor,
        post_id: str,
        post: Dict[str, Any],
        evidence: Dict[str, Any],
        artifact_ids: List[str],
        *,
        job_run_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        candidates = self._collect_candidates(
            cur,
            post_id,
            post,
            evidence,
            artifact_ids,
        )
        if not candidates:
            return []

        relations: List[Dict[str, Any]] = []
        seen_pairs: set[tuple[str, str, str]] = set()

        for candidate in candidates.values():
            candidate_id = candidate["id"]
            if candidate_id == post_id:
                continue

            exact = self._detect_exact_duplicate(post_id, post, evidence, candidate)
            if exact:
                key = exact["dedupe_key"]
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    relations.append(exact["relation"])
                continue

            syndicated = self._detect_syndicated(post_id, post, evidence, candidate)
            if syndicated:
                key = (
                    syndicated["from_post_id"],
                    syndicated["to_post_id"],
                    syndicated["relation_type"],
                )
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    relations.append(syndicated)
                continue

            translation = self._detect_translation(cur, post_id, post, evidence, candidate, artifact_ids)
            if translation:
                key = (
                    translation["from_post_id"],
                    translation["to_post_id"],
                    translation["relation_type"],
                )
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    relations.append(translation)
                continue

            same_artifact = self._detect_same_artifact(cur, post_id, candidate, artifact_ids)
            if same_artifact:
                key = same_artifact["dedupe_key"]
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    relations.append(same_artifact["relation"])
                continue

            near_duplicate = self._detect_near_duplicate(post_id, post, evidence, candidate)
            if near_duplicate:
                key = near_duplicate["dedupe_key"]
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    relations.append(near_duplicate["relation"])

        return relations

    def _collect_candidates(
        self,
        cur: psycopg.Cursor,
        post_id: str,
        post: Dict[str, Any],
        evidence: Dict[str, Any],
        artifact_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        candidates: Dict[str, Dict[str, Any]] = {}
        normalized_url = evidence.get("normalized_url")
        url_host = evidence.get("url_host")
        published_at = self._as_datetime(post.get("published_at") or post.get("fetched_at"))
        since = published_at - timedelta(days=self.NEAR_DUPLICATE_WINDOW_DAYS) if published_at else datetime.now(timezone.utc) - timedelta(days=self.NEAR_DUPLICATE_WINDOW_DAYS)

        if normalized_url:
            for candidate in self.repo.get_posts_by_normalized_url(cur, normalized_url, exclude_post_id=post_id, limit=50):
                candidates[candidate["id"]] = candidate

        for artifact_id in artifact_ids:
            for candidate in self.repo.get_posts_by_artifact(cur, artifact_id, exclude_post_id=post_id, limit=50):
                candidates[candidate["id"]] = candidate

        if url_host:
            for candidate in self.repo.get_recent_posts_by_host(cur, url_host, since, exclude_post_id=post_id, limit=100):
                candidates[candidate["id"]] = candidate

        return candidates

    def _detect_exact_duplicate(
        self,
        post_id: str,
        post: Dict[str, Any],
        evidence: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if evidence.get("normalized_url") and evidence.get("normalized_url") == candidate.get("normalized_url"):
            if evidence.get("content_hash") and evidence.get("content_hash") == candidate.get("content_hash"):
                return self._build_symmetric_relation(
                    post_id,
                    candidate["id"],
                    "exact_duplicate",
                    "normalized_url+content_hash",
                    0.99,
                    {
                        "signals": {
                            "normalized_url": evidence.get("normalized_url"),
                            "content_hash": evidence.get("content_hash"),
                        }
                    },
                )
            if evidence.get("title_hash") and evidence.get("title_hash") == candidate.get("title_hash"):
                return self._build_symmetric_relation(
                    post_id,
                    candidate["id"],
                    "exact_duplicate",
                    "normalized_url+title_hash",
                    0.97,
                    {
                        "signals": {
                            "normalized_url": evidence.get("normalized_url"),
                            "title_hash": evidence.get("title_hash"),
                        }
                    },
                )
        return None

    def _detect_same_artifact(
        self,
        cur: psycopg.Cursor,
        post_id: str,
        candidate: Dict[str, Any],
        artifact_ids: List[str],
    ) -> Optional[Dict[str, Any]]:
        candidate_artifacts = self._candidate_artifact_ids(cur, candidate.get("id"))
        shared = sorted(set(artifact_ids).intersection(candidate_artifacts))
        if not shared:
            return None

        return {
            "dedupe_key": tuple(sorted([post_id, candidate["id"]])) + ("references_same_artifact",),
            "relation": self._build_symmetric_relation(
                post_id,
                candidate["id"],
                "references_same_artifact",
                "shared_artifact",
                0.86,
                {"artifact_ids": shared},
            ),
        }

    def _detect_syndicated(
        self,
        post_id: str,
        post: Dict[str, Any],
        evidence: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        current_time = self._as_datetime(post.get("published_at") or post.get("fetched_at"))
        candidate_time = self._as_datetime(candidate.get("published_at") or candidate.get("fetched_at"))
        if not current_time or not candidate_time or current_time <= candidate_time:
            return None

        content_hash = evidence.get("content_hash")
        if content_hash and content_hash == candidate.get("content_hash"):
            return {
                "from_post_id": post_id,
                "to_post_id": candidate["id"],
                "relation_type": "syndicated_from",
                "method": self.RELATION_METHOD,
                "confidence": 0.95,
                "metadata": {
                    "reason": "content_hash_match",
                    "published_at_delta_seconds": int((current_time - candidate_time).total_seconds()),
                },
            }

        same_artifact = self._shared_artifact_ids(cur, post_id, candidate["id"])
        if same_artifact and self._title_similarity(post, candidate) >= 0.84 and self._content_similarity(post, candidate) >= 0.72:
            return {
                "from_post_id": post_id,
                "to_post_id": candidate["id"],
                "relation_type": "syndicated_from",
                "method": self.RELATION_METHOD,
                "confidence": 0.82,
                "metadata": {
                    "reason": "shared_artifact_and_similarity",
                    "published_at_delta_seconds": int((current_time - candidate_time).total_seconds()),
                },
            }

        return None

    def _detect_translation(
        self,
        cur: psycopg.Cursor,
        post_id: str,
        post: Dict[str, Any],
        evidence: Dict[str, Any],
        candidate: Dict[str, Any],
        artifact_ids: List[str],
    ) -> Optional[Dict[str, Any]]:
        current_time = self._as_datetime(post.get("published_at") or post.get("fetched_at"))
        candidate_time = self._as_datetime(candidate.get("published_at") or candidate.get("fetched_at"))
        if not current_time or not candidate_time:
            return None

        shared_artifact = self._shared_artifact_ids(cur, post_id, candidate["id"])
        if not shared_artifact:
            return None

        current_language = evidence.get("language_code") or "und"
        candidate_language = candidate.get("language_code") or "und"
        if current_language == candidate_language or "und" in {current_language, candidate_language}:
            return None

        title_similarity = self._title_similarity(post, candidate)
        content_similarity = self._content_similarity(post, candidate)
        translation_marker = self._contains_translation_marker(post) or self._contains_translation_marker(candidate)

        if title_similarity >= 0.84 and (content_similarity >= 0.45 or translation_marker):
            # Direction: from the translated post to the source/original post.
            if current_time >= candidate_time:
                from_post_id, to_post_id = post_id, candidate["id"]
            else:
                from_post_id, to_post_id = candidate["id"], post_id
            return {
                "from_post_id": from_post_id,
                "to_post_id": to_post_id,
                "relation_type": "translation_of",
                "method": self.RELATION_METHOD,
                "confidence": 0.8 if translation_marker else 0.72,
                "metadata": {
                    "current_language": current_language,
                    "candidate_language": candidate_language,
                    "title_similarity": round(title_similarity, 3),
                    "content_similarity": round(content_similarity, 3),
                },
            }

        return None

    def _detect_near_duplicate(
        self,
        post_id: str,
        post: Dict[str, Any],
        evidence: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        current_time = self._as_datetime(post.get("published_at") or post.get("fetched_at"))
        candidate_time = self._as_datetime(candidate.get("published_at") or candidate.get("fetched_at"))
        if not current_time or not candidate_time:
            return None

        if abs((current_time - candidate_time).total_seconds()) > self.NEAR_DUPLICATE_WINDOW_DAYS * 86400:
            return None

        if evidence.get("url_host") and evidence.get("url_host") != candidate.get("url_host"):
            return None

        title_similarity = self._title_similarity(post, candidate)
        content_similarity = self._content_similarity(post, candidate)
        if title_similarity >= 0.94 and content_similarity >= 0.7:
            return {
                "dedupe_key": tuple(sorted([post_id, candidate["id"]])) + ("near_duplicate",),
                "relation": self._build_symmetric_relation(
                    post_id,
                    candidate["id"],
                    "near_duplicate",
                    self.RELATION_METHOD,
                    0.74,
                    {
                        "title_similarity": round(title_similarity, 3),
                        "content_similarity": round(content_similarity, 3),
                    },
                ),
            }

        return None

    def _shared_artifact_ids(self, cur: psycopg.Cursor, post_id: str, candidate_post_id: str) -> List[str]:
        # This helper is intentionally conservative and uses the persisted artifact edges.
        cur.execute(
            """
            SELECT artifact_id
            FROM post_artifacts
            WHERE post_id = %s
            INTERSECT
            SELECT artifact_id
            FROM post_artifacts
            WHERE post_id = %s
            """,
            (post_id, candidate_post_id),
        )
        return [str(row[0]) for row in cur.fetchall()]

    def _candidate_artifact_ids(self, cur: psycopg.Cursor, post_id: str) -> List[str]:
        cur.execute("SELECT artifact_id FROM post_artifacts WHERE post_id = %s", (post_id,))
        return [str(row[0]) for row in cur.fetchall()]

    def _build_symmetric_relation(
        self,
        post_a: str,
        post_b: str,
        relation_type: str,
        method: str,
        confidence: float,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        from_post_id, to_post_id = sorted([post_a, post_b])
        return {
            "from_post_id": from_post_id,
            "to_post_id": to_post_id,
            "relation_type": relation_type,
            "method": method,
            "confidence": confidence,
            "metadata": metadata,
            "dedupe_key": (from_post_id, to_post_id, relation_type),
        }

    def _title_similarity(self, left: Dict[str, Any], right: Dict[str, Any]) -> float:
        left_title = normalize_text(left.get("title")) or ""
        right_title = normalize_text(right.get("title")) or ""
        if not left_title or not right_title:
            return 0.0
        return SequenceMatcher(None, left_title, right_title).ratio()

    def _content_similarity(self, left: Dict[str, Any], right: Dict[str, Any]) -> float:
        left_content = self._compact_content(left)
        right_content = self._compact_content(right)
        if not left_content or not right_content:
            return 0.0
        return SequenceMatcher(None, left_content, right_content).ratio()

    def _compact_content(self, post: Dict[str, Any]) -> str:
        content = normalize_text(post.get("content")) or ""
        html_content = normalize_text(strip_html(post.get("content_html"))) or ""
        combined = " ".join(part for part in [content, html_content] if part)
        if len(combined) > 1200:
            combined = combined[:1200]
        return combined

    def _contains_translation_marker(self, post: Dict[str, Any]) -> bool:
        text = " ".join(
            part
            for part in [
                normalize_text(post.get("title")) or "",
                normalize_text(post.get("content")) or "",
            ]
            if part
        )
        if not text:
            return False
        markers = (
            "translated from",
            "translation",
            "перевод",
            "переведено",
            "traducción",
            "traduction",
            "übersetzung",
            "tradotto",
        )
        return any(marker in text for marker in markers)

    def _as_datetime(self, value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None
