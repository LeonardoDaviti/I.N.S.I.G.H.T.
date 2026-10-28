"""Reader interactions (opens, reading sessions, favourites) and the reader state built from them."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from psycopg import Cursor
from insight_core.utils.json_safe import json_default


class PostInteractionsRepository:
    """SQL access for post_interactions and the per-post reader state."""

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
        cur.execute(query, (post_id, interaction_type, json.dumps(interaction_value or {}, default=json_default)))
        row = cur.fetchone()
        return {
            "id": str(row[0]),
            "post_id": post_id,
            "interaction_type": interaction_type,
            "interaction_value": interaction_value or {},
            "created_at": row[1],
        }

    def get_post_reader_state(self, cur: Cursor, post_id: str) -> Dict[str, Any]:
        """Interaction-log aggregates plus the read-state projection (read_at, starred_at, later_at).

        `is_favorited` comes from the projection (post_reader_state.starred_at), which the
        favorite endpoint writes; the interaction log stays the audit trail.
        """
        query = """
            SELECT
                COUNT(*) FILTER (WHERE i.interaction_type = 'opened') AS open_count,
                MIN(i.created_at) FILTER (WHERE i.interaction_type = 'opened') AS first_opened_at,
                MAX(i.created_at) FILTER (WHERE i.interaction_type = 'opened') AS last_opened_at,
                COALESCE(SUM(
                    CASE
                        WHEN i.interaction_type = 'reading_session'
                        THEN COALESCE((i.interaction_value->>'duration_seconds')::numeric, 0)
                        ELSE 0
                    END
                ), 0) AS total_read_seconds,
                (SELECT rs.read_at FROM post_reader_state rs WHERE rs.post_id = %s) AS read_at,
                (SELECT rs.starred_at FROM post_reader_state rs WHERE rs.post_id = %s) AS starred_at,
                (SELECT rs.later_at FROM post_reader_state rs WHERE rs.post_id = %s) AS later_at
            FROM post_interactions i
            WHERE i.post_id = %s
        """
        cur.execute(query, (post_id, post_id, post_id, post_id))
        row = cur.fetchone()
        if not row:
            return {
                "post_id": post_id,
                "is_favorited": False,
                "open_count": 0,
                "first_opened_at": None,
                "last_opened_at": None,
                "total_read_seconds": 0,
                "read_at": None,
                "starred_at": None,
                "later_at": None,
            }
        return {
            "post_id": post_id,
            "is_favorited": row[5] is not None,
            "open_count": int(row[0] or 0),
            "first_opened_at": row[1],
            "last_opened_at": row[2],
            "total_read_seconds": int(row[3] or 0),
            "read_at": row[4],
            "starred_at": row[5],
            "later_at": row[6],
        }
