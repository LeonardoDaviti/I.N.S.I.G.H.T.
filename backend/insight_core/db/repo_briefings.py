"""
Repository for persisted briefing outputs.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from psycopg import Cursor
from insight_core.utils.json_safe import json_default


class BriefingsRepository:
    """Database access layer for the briefings table."""

    def list_briefings(
        self,
        cur: Cursor,
        subject_type: str,
        subject_key_prefix: str,
        variant: str = "default",
        limit: int = 60,
    ) -> List[Dict[str, Any]]:
        """History for one subject, newest first - metadata only, no content.

        Expert briefings are keyed "<expert_id>:<end_date>", so this is what makes past
        runs browsable the way daily briefings already are. Deliberately does NOT project
        content or payload: a history list of 60 entries would otherwise pull 60 briefing
        bodies to render a date picker.
        """
        cur.execute(
            """
            SELECT id, subject_key, title,
                   COALESCE(updated_at, created_at) AS at,
                   length(content)                  AS content_length,
                   payload->>'generator'            AS generator,
                   payload->>'posts_processed'      AS posts_processed,
                   payload->>'start_date'           AS start_date,
                   payload->>'end_date'             AS end_date
            FROM briefings
            WHERE subject_type = %s
              AND (subject_key = %s OR subject_key LIKE %s)
              AND variant = %s
            ORDER BY COALESCE(updated_at, created_at) DESC
            LIMIT %s
            """,
            (subject_type, subject_key_prefix, f"{subject_key_prefix}:%", variant,
             max(1, min(int(limit), 200))),
        )
        return [
            {
                "id": str(r[0]),
                "subject_key": r[1],
                "title": r[2],
                "at": r[3].isoformat() if hasattr(r[3], "isoformat") else r[3],
                "content_length": r[4],
                "generator": r[5],
                "posts_processed": int(r[6]) if r[6] else None,
                "start_date": r[7],
                "end_date": r[8] or (r[1].split(":", 1)[1] if ":" in (r[1] or "") else None),
            }
            for r in cur.fetchall()
        ]

    def get_latest_briefing(
        self,
        cur: Cursor,
        subject_type: str,
        subject_key_prefix: str,
        variant: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """Most recent briefing whose subject_key starts with the given prefix.

        Expert briefings are keyed "<expert_id>:<end_date>" so each run is preserved.
        Rows written before that change are keyed with the bare expert_id, and the
        prefix match still finds them.
        """
        cur.execute(
            """
            SELECT id, subject_type, subject_key, variant, render_format, title, content,
                   payload, created_at, updated_at
            FROM briefings
            WHERE subject_type = %s
              AND (subject_key = %s OR subject_key LIKE %s)
              AND variant = %s
            ORDER BY COALESCE(updated_at, created_at) DESC
            LIMIT 1
            """,
            (subject_type, subject_key_prefix, f"{subject_key_prefix}:%", variant),
        )
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

    def get_latest_briefing_timestamp(
        self,
        cur: Cursor,
        subject_type: str,
        subject_key_prefix: str,
        variant: str = "default",
    ) -> Optional[datetime]:
        """Timestamp of the most recent briefing for a subject_key prefix."""
        cur.execute(
            """
            SELECT COALESCE(updated_at, created_at)
            FROM briefings
            WHERE subject_type = %s
              AND (subject_key = %s OR subject_key LIKE %s)
              AND variant = %s
            ORDER BY COALESCE(updated_at, created_at) DESC
            LIMIT 1
            """,
            (subject_type, subject_key_prefix, f"{subject_key_prefix}:%", variant),
        )
        row = cur.fetchone()
        return row[0] if row else None

    def get_briefing_timestamp(
        self,
        cur: Cursor,
        subject_type: str,
        subject_key: str,
        variant: str = "default",
    ) -> Optional[datetime]:
        """Just the last-updated timestamp - no content, no payload.

        get_briefing() projects content and payload, so callers that only want a
        timestamp were loading whole briefing bodies. /api/status does this once
        per expert on every poll.
        """
        cur.execute(
            """
            SELECT COALESCE(updated_at, created_at)
            FROM briefings
            WHERE subject_type = %s AND subject_key = %s AND variant = %s
            """,
            (subject_type, subject_key, variant),
        )
        row = cur.fetchone()
        return row[0] if row else None

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

    def _json_default(self, value: Any) -> Any:
        """Delegates to the shared encoder so all repos stay in step."""
        return json_default(value)
