"""Operations storage: system_settings key/value rows and job_runs lookups.

Every method takes the caller's cursor and never commits: the caller (OperationsService)
owns the connection and the transaction, as with FetchStateRepository.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional, Tuple

from psycopg import Cursor


class SystemSettingsRepository:
    """system_settings(key, value JSONB, updated_at)."""

    @staticmethod
    def get(cur: Cursor, key: str) -> Optional[Tuple[Any, Optional[datetime]]]:
        """(value, updated_at) for the key, or None when it was never written."""
        cur.execute("SELECT value, updated_at FROM system_settings WHERE key = %s", (key,))
        row = cur.fetchone()
        return (row[0], row[1]) if row else None

    @staticmethod
    def upsert(cur: Cursor, key: str, value: Any) -> datetime:
        """Insert or replace the key's value; returns the new updated_at."""
        cur.execute(
            """
            INSERT INTO system_settings (key, value, updated_at)
            VALUES (%s, %s::jsonb, now())
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
            RETURNING updated_at
            """,
            (key, json.dumps(value)),
        )
        return cur.fetchone()[0]


class JobRunsRepository:
    """Read-side lookups over job_runs."""

    @staticmethod
    def latest_success_finished_at(cur: Cursor, job_type: str) -> Optional[datetime]:
        """When the newest successful job of this type finished, or None."""
        cur.execute(
            """
            SELECT max(finished_at) FROM job_runs
            WHERE job_type = %s AND status = 'success' AND finished_at IS NOT NULL
            """,
            (job_type,),
        )
        row = cur.fetchone()
        return row[0] if row else None

    @staticmethod
    def latest_for_source(cur: Cursor, job_type: str, source_id: str) -> Optional[dict]:
        """The newest job of this type for one source, summarised (no event log), or None.

        The source sheet reads it to attach to a running archive and to show the last result.
        """
        cur.execute(
            """
            SELECT id, status, message, started_at, finished_at,
                   CASE WHEN jsonb_typeof(payload->'progress') = 'number'
                        THEN (payload->>'progress')::float END,
                   jsonb_strip_nulls(jsonb_build_object(
                     'posts_fetched',  payload->'posts_fetched',
                     'posts_inserted', payload->'posts_inserted',
                     'posts_updated',  payload->'posts_updated',
                     'pages_fetched',  payload->'pages_fetched',
                     'stored_posts',   payload->'stored_posts',
                     'error',          payload->'error',
                     'paused',         payload->'paused',
                     'paused_reason',  payload->'paused_reason'
                   ))
            FROM job_runs
            WHERE job_type = %s AND source_id = %s
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (job_type, source_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        return {
            "id": str(row[0]),
            "status": row[1],
            "message": row[2],
            "started_at": row[3].isoformat() if row[3] else None,
            "finished_at": row[4].isoformat() if row[4] else None,
            "progress": row[5],
            "result": row[6] or {},
        }
