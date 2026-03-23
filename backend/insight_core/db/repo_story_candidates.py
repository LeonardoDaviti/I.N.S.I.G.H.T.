"""Repository for story timeline candidate links."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from psycopg import Cursor


class StoryCandidateRepository:
    """SQL access layer for story timeline candidate links."""

    def __init__(self, db_url: str):
        self.db_url = db_url

    def replace_candidates_for_post(
        self,
        cur: Cursor,
        source_post_id: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        cur.execute("DELETE FROM story_candidate_links WHERE source_post_id = %s", (source_post_id,))
        stored: List[Dict[str, Any]] = []
        for candidate in candidates:
            cur.execute(
                """
                INSERT INTO story_candidate_links (
                    source_post_id,
                    candidate_post_id,
                    candidate_story_id,
                    retrieval_method,
                    retrieval_score,
                    decision_status,
                    decision_reason,
                    metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                RETURNING id, created_at, updated_at
                """,
                (
                    source_post_id,
                    candidate["candidate_post_id"],
                    candidate.get("candidate_story_id"),
                    candidate["retrieval_method"],
                    float(candidate.get("retrieval_score") or 0.0),
                    candidate.get("decision_status") or "proposed",
                    candidate.get("decision_reason"),
                    json.dumps(candidate.get("metadata") or {}, default=self._json_default),
                ),
            )
            row = cur.fetchone()
            stored.append(
                {
                    "id": str(row[0]),
                    "source_post_id": source_post_id,
                    "candidate_post_id": str(candidate["candidate_post_id"]),
                    "candidate_story_id": str(candidate["candidate_story_id"]) if candidate.get("candidate_story_id") else None,
                    "retrieval_method": candidate["retrieval_method"],
                    "retrieval_score": float(candidate.get("retrieval_score") or 0.0),
                    "decision_status": candidate.get("decision_status") or "proposed",
                    "decision_reason": candidate.get("decision_reason"),
                    "metadata": candidate.get("metadata") or {},
                    "created_at": row[1],
                    "updated_at": row[2],
                }
            )
        return stored

    def get_candidates_for_post(
        self,
        cur: Cursor,
        source_post_id: str,
        *,
        statuses: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        where_status = ""
        params: List[Any] = [source_post_id]
        if statuses:
            where_status = "AND scl.decision_status = ANY(%s)"
            params.append(statuses)
        params.append(int(limit))
        query = f"""
            SELECT
                scl.id,
                scl.source_post_id,
                scl.candidate_post_id,
                scl.candidate_story_id,
                scl.retrieval_method,
                scl.retrieval_score,
                scl.decision_status,
                scl.decision_reason,
                scl.metadata,
                scl.created_at,
                scl.updated_at,
                p.id,
                p.source_id,
                p.url,
                p.external_id,
                p.published_at,
                p.fetched_at,
                p.title,
                p.content,
                p.content_html,
                p.metadata,
                p.media_urls,
                p.categories,
                p.lang,
                p.language_code,
                p.language_confidence,
                p.normalized_url,
                p.canonical_url,
                p.url_host,
                p.title_hash,
                p.content_hash,
                p.normalization_version,
                p.enriched_at,
                p.title_original,
                p.body_original,
                p.title_pivot,
                p.summary_pivot,
                p.title_pivot_version,
                p.summary_pivot_version,
                src.platform,
                src.handle_or_url,
                st.id,
                st.canonical_title,
                st.story_kind,
                st.status
            FROM story_candidate_links scl
            JOIN posts p ON p.id = scl.candidate_post_id
            JOIN sources src ON src.id = p.source_id
            LEFT JOIN stories st ON st.id = scl.candidate_story_id
            WHERE scl.source_post_id = %s
            {where_status}
            ORDER BY
                CASE scl.decision_status
                    WHEN 'accepted' THEN 0
                    WHEN 'proposed' THEN 1
                    WHEN 'needs_review' THEN 2
                    WHEN 'rejected' THEN 3
                    ELSE 4
                END,
                scl.retrieval_score DESC,
                COALESCE(p.published_at, p.fetched_at) ASC,
                scl.created_at ASC
            LIMIT %s
        """
        cur.execute(query, params)
        return [self._candidate_from_row(row) for row in cur.fetchall()]

    def get_candidate_by_id(self, cur: Cursor, candidate_id: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT
                id,
                source_post_id,
                candidate_post_id,
                candidate_story_id,
                retrieval_method,
                retrieval_score,
                decision_status,
                decision_reason,
                metadata,
                created_at,
                updated_at
            FROM story_candidate_links
            WHERE id = %s
        """
        cur.execute(query, (candidate_id,))
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "source_post_id": str(row[1]),
            "candidate_post_id": str(row[2]),
            "candidate_story_id": str(row[3]) if row[3] else None,
            "retrieval_method": row[4],
            "retrieval_score": float(row[5]) if row[5] is not None else 0.0,
            "decision_status": row[6],
            "decision_reason": row[7],
            "metadata": row[8] or {},
            "created_at": row[9],
            "updated_at": row[10],
        }

    def update_candidate_decision(
        self,
        cur: Cursor,
        candidate_id: str,
        *,
        decision_status: str,
        decision_reason: str | None = None,
        candidate_story_id: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        query = """
            UPDATE story_candidate_links
            SET
                decision_status = %s,
                decision_reason = COALESCE(%s, decision_reason),
                candidate_story_id = COALESCE(%s, candidate_story_id),
                metadata = CASE
                    WHEN %s::jsonb IS NULL THEN metadata
                    ELSE metadata || %s::jsonb
                END,
                updated_at = now()
            WHERE id = %s
            RETURNING id, source_post_id, candidate_post_id, candidate_story_id, retrieval_method,
                      retrieval_score, decision_status, decision_reason, metadata, created_at, updated_at
        """
        payload = json.dumps(metadata, default=self._json_default) if metadata is not None else None
        cur.execute(
            query,
            (decision_status, decision_reason, candidate_story_id, payload, payload, candidate_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "source_post_id": str(row[1]),
            "candidate_post_id": str(row[2]),
            "candidate_story_id": str(row[3]) if row[3] else None,
            "retrieval_method": row[4],
            "retrieval_score": float(row[5]) if row[5] is not None else 0.0,
            "decision_status": row[6],
            "decision_reason": row[7],
            "metadata": row[8] or {},
            "created_at": row[9],
            "updated_at": row[10],
        }

    def _candidate_from_row(self, row: tuple[Any, ...]) -> Dict[str, Any]:
        return {
            "id": str(row[0]),
            "source_post_id": str(row[1]),
            "candidate_post_id": str(row[2]),
            "candidate_story_id": str(row[3]) if row[3] else None,
            "retrieval_method": row[4],
            "retrieval_score": float(row[5]) if row[5] is not None else 0.0,
            "decision_status": row[6],
            "decision_reason": row[7],
            "metadata": row[8] or {},
            "created_at": row[9],
            "updated_at": row[10],
            "candidate_post": {
                "id": str(row[11]),
                "source_id": str(row[12]) if row[12] else None,
                "url": row[13],
                "external_id": row[14],
                "published_at": row[15],
                "fetched_at": row[16],
                "title": row[17],
                "content": row[18],
                "content_html": row[19],
                "metadata": row[20] or {},
                "media_urls": row[21] or [],
                "categories": row[22] or [],
                "lang": row[23],
                "language_code": row[24],
                "language_confidence": float(row[25]) if row[25] is not None else None,
                "normalized_url": row[26],
                "canonical_url": row[27],
                "url_host": row[28],
                "title_hash": row[29],
                "content_hash": row[30],
                "normalization_version": row[31],
                "enriched_at": row[32],
                "title_original": row[33],
                "body_original": row[34],
                "title_pivot": row[35],
                "summary_pivot": row[36],
                "title_pivot_version": row[37],
                "summary_pivot_version": row[38],
                "platform": row[39],
                "source": row[40],
                "source_display_name": row[40],
            },
            "candidate_story": {
                "id": str(row[41]),
                "canonical_title": row[42],
                "story_kind": row[43],
                "status": row[44],
            } if row[41] else None,
        }

    def _json_default(self, value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value)} is not JSON serializable")
