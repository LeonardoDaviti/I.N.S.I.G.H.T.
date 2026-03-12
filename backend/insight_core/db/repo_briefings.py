"""
Repository for persisted briefing outputs.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, Optional

from psycopg import Cursor


class BriefingsRepository:
    """Database access layer for the briefings table."""

    def get_briefing(
        self,
        cur: Cursor,
        subject_type: str,
        subject_key: str,
        variant: str = "default",
    ) -> Optional[Dict[str, Any]]:
        query = """
            SELECT id, subject_type, subject_key, variant, render_format, title, content, payload, created_at, updated_at
            FROM briefings
            WHERE subject_type = %s AND subject_key = %s AND variant = %s
        """
        cur.execute(query, (subject_type, subject_key, variant))
        row = cur.fetchone()
        if not row:
            return None

        return {
            "id": str(row[0]),
            "subject_type": row[1],
            "subject_key": row[2],
            "variant": row[3],
            "render_format": row[4],
            "title": row[5],
            "content": row[6],
            "payload": row[7] or {},
            "created_at": row[8],
            "updated_at": row[9],
        }

    def upsert_briefing(
        self,
        cur: Cursor,
        *,
        subject_type: str,
        subject_key: str,
        variant: str,
        render_format: str,
        title: Optional[str],
        content: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        query = """
            INSERT INTO briefings (
                subject_type,
                subject_key,
                variant,
                render_format,
                title,
                content,
                payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (subject_type, subject_key, variant) DO UPDATE SET
                render_format = EXCLUDED.render_format,
                title = EXCLUDED.title,
                content = EXCLUDED.content,
                payload = EXCLUDED.payload,
                updated_at = now()
            RETURNING id, created_at, updated_at
        """
        cur.execute(
            query,
            (
                subject_type,
                subject_key,
                variant,
                render_format,
                title,
                content,
                json.dumps(payload or {}, default=self._json_default),
            ),
        )
        row = cur.fetchone()
        return {
            "id": str(row[0]),
            "subject_type": subject_type,
            "subject_key": subject_key,
            "variant": variant,
            "render_format": render_format,
            "title": title,
            "content": content,
            "payload": payload or {},
            "created_at": row[1],
            "updated_at": row[2],
        }

    def _json_default(self, value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value)} is not JSON serializable")
