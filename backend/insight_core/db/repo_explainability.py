"""Repository for explainability, artifact references, and reader interactions."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from psycopg import Cursor


class ExplainabilityRepository:
    """SQL access layer for post highlights, artifact references, and interactions."""

    def __init__(self, db_url: str):
        self.db_url = db_url

    def upsert_post_highlights(
        self,
        cur: Cursor,
        post_id: str,
        highlights: List[Dict[str, Any]],
        *,
        extractor_name: str,
        extractor_version: str,
        language_code: str | None = None,
    ) -> List[Dict[str, Any]]:
        cur.execute("DELETE FROM post_highlights WHERE post_id = %s", (post_id,))
        stored: List[Dict[str, Any]] = []
        for highlight in highlights:
            cur.execute(
                """
                INSERT INTO post_highlights (
                    post_id,
                    highlight_text,
                    highlight_kind,
                    start_char,
                    end_char,
                    language_code,
                    importance_score,
                    commentary,
                    extractor_name,
                    extractor_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    post_id,
                    highlight.get("highlight_text") or highlight.get("text") or "",
                    highlight.get("highlight_kind") or highlight.get("kind") or "evidence",
                    highlight.get("start_char"),
                    highlight.get("end_char"),
                    language_code or highlight.get("language_code"),
                    float(highlight.get("importance_score") or 0.0),
                    highlight.get("commentary"),
                    extractor_name,
                    extractor_version,
                ),
            )
            row = cur.fetchone()
            stored.append(
                {
                    "id": str(row[0]),
                    "post_id": post_id,
                    "highlight_text": highlight.get("highlight_text") or highlight.get("text") or "",
                    "highlight_kind": highlight.get("highlight_kind") or highlight.get("kind") or "evidence",
                    "start_char": highlight.get("start_char"),
                    "end_char": highlight.get("end_char"),
                    "language_code": language_code or highlight.get("language_code"),
                    "importance_score": float(highlight.get("importance_score") or 0.0),
                    "commentary": highlight.get("commentary"),
                    "extractor_name": extractor_name,
                    "extractor_version": extractor_version,
                    "created_at": row[1],
                }
            )
        return stored

    def get_post_highlights(self, cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        query = """
            SELECT
                id,
                post_id,
                highlight_text,
                highlight_kind,
                start_char,
                end_char,
                language_code,
                importance_score,
                commentary,
                extractor_name,
                extractor_version,
                created_at
            FROM post_highlights
            WHERE post_id = %s
            ORDER BY importance_score DESC, created_at ASC
        """
        cur.execute(query, (post_id,))
        rows = cur.fetchall()
        return [
            {
                "id": str(row[0]),
                "post_id": str(row[1]),
                "highlight_text": row[2],
                "highlight_kind": row[3],
                "start_char": row[4],
                "end_char": row[5],
                "language_code": row[6],
                "importance_score": float(row[7]) if row[7] is not None else 0.0,
                "commentary": row[8],
                "extractor_name": row[9],
                "extractor_version": row[10],
                "created_at": row[11],
            }
            for row in rows
        ]

    def upsert_artifact_post_references(
        self,
        cur: Cursor,
        artifact_type: str,
        artifact_id: str,
        references: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        cur.execute(
            "DELETE FROM artifact_post_references WHERE artifact_type = %s AND artifact_id = %s",
            (artifact_type, artifact_id),
        )

        stored: List[Dict[str, Any]] = []
        for index, reference in enumerate(references):
            post_id = reference.get("post_id")
            if not post_id:
                continue
            cur.execute(
                """
                INSERT INTO artifact_post_references (
                    artifact_type,
                    artifact_id,
                    post_id,
                    highlight_id,
                    reference_role,
                    display_label,
                    order_index
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id, created_at
                """,
                (
                    artifact_type,
                    artifact_id,
                    post_id,
                    reference.get("highlight_id"),
                    reference.get("reference_role") or "supporting",
                    reference.get("display_label"),
                    int(reference.get("order_index") or index),
                ),
            )
            row = cur.fetchone()
            stored.append(
                {
                    "id": str(row[0]),
                    "artifact_type": artifact_type,
                    "artifact_id": artifact_id,
                    "post_id": str(post_id),
                    "highlight_id": str(reference.get("highlight_id")) if reference.get("highlight_id") else None,
                    "reference_role": reference.get("reference_role") or "supporting",
                    "display_label": reference.get("display_label"),
                    "order_index": int(reference.get("order_index") or index),
                    "created_at": row[1],
                }
            )
        return stored

    def get_artifact_post_references(
        self,
        cur: Cursor,
        artifact_type: str,
        artifact_id: str,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                apr.id,
                apr.artifact_type,
                apr.artifact_id,
                apr.post_id,
                apr.highlight_id,
                apr.reference_role,
                apr.display_label,
                apr.order_index,
                apr.created_at,
                ph.highlight_text,
                ph.highlight_kind,
                ph.importance_score,
                ph.commentary
            FROM artifact_post_references apr
            LEFT JOIN post_highlights ph ON ph.id = apr.highlight_id
            WHERE apr.artifact_type = %s AND apr.artifact_id = %s
            ORDER BY apr.order_index ASC, apr.created_at ASC
        """
        cur.execute(query, (artifact_type, artifact_id))
        rows = cur.fetchall()
        return [
            {
                "id": str(row[0]),
                "artifact_type": row[1],
                "artifact_id": str(row[2]),
                "post_id": str(row[3]),
                "highlight_id": str(row[4]) if row[4] else None,
                "reference_role": row[5],
                "display_label": row[6],
                "order_index": int(row[7]) if row[7] is not None else 0,
                "created_at": row[8],
                "highlight": {
                    "highlight_text": row[9],
                    "highlight_kind": row[10],
                    "importance_score": float(row[11]) if row[11] is not None else 0.0,
                    "commentary": row[12],
                }
                if row[9]
                else None,
            }
            for row in rows
        ]

    def record_post_interaction(
        self,
        cur: Cursor,
        post_id: str,
        interaction_type: str,
        interaction_value: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        query = """
            INSERT INTO post_interactions (
                post_id,
                interaction_type,
                interaction_value
            )
            VALUES (%s, %s, %s::jsonb)
            RETURNING id, created_at
        """
        cur.execute(query, (post_id, interaction_type, json.dumps(interaction_value or {}, default=self._json_default)))
        row = cur.fetchone()
        return {
            "id": str(row[0]),
            "post_id": post_id,
            "interaction_type": interaction_type,
            "interaction_value": interaction_value or {},
            "created_at": row[1],
        }

    def get_post_interactions(self, cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        query = """
            SELECT id, post_id, interaction_type, interaction_value, created_at
            FROM post_interactions
            WHERE post_id = %s
            ORDER BY created_at ASC
        """
        cur.execute(query, (post_id,))
        rows = cur.fetchall()
        return [
            {
                "id": str(row[0]),
                "post_id": str(row[1]),
                "interaction_type": row[2],
                "interaction_value": row[3] or {},
                "created_at": row[4],
            }
            for row in rows
        ]

    def get_post_reader_state(self, cur: Cursor, post_id: str) -> Dict[str, Any]:
        query = """
            WITH interactions AS (
                SELECT interaction_type, interaction_value, created_at
                FROM post_interactions
                WHERE post_id = %s
            )
            SELECT
                COUNT(*) FILTER (WHERE interaction_type = 'opened') AS open_count,
                MIN(created_at) FILTER (WHERE interaction_type = 'opened') AS first_opened_at,
                MAX(created_at) FILTER (WHERE interaction_type = 'opened') AS last_opened_at,
                COALESCE(SUM(
                    CASE
                        WHEN interaction_type = 'reading_session'
                        THEN COALESCE((interaction_value->>'duration_seconds')::numeric, 0)
                        ELSE 0
                    END
                ), 0) AS total_read_seconds,
                COALESCE(
                    (
                        SELECT interaction_type = 'favorited'
                        FROM interactions
                        WHERE interaction_type IN ('favorited', 'unfavorited')
                        ORDER BY created_at DESC
                        LIMIT 1
                    ),
                    FALSE
                ) AS is_favorited
            FROM interactions
        """
        cur.execute(query, (post_id,))
        row = cur.fetchone()
        if not row:
            return {
                "post_id": post_id,
                "is_favorited": False,
                "open_count": 0,
                "first_opened_at": None,
                "last_opened_at": None,
                "total_read_seconds": 0,
            }
        return {
            "post_id": post_id,
            "is_favorited": bool(row[4]),
            "open_count": int(row[0] or 0),
            "first_opened_at": row[1],
            "last_opened_at": row[2],
            "total_read_seconds": int(row[3] or 0),
        }

    def _json_default(self, value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value)} is not JSON serializable")
