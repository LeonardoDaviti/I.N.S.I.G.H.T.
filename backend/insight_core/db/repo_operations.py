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
