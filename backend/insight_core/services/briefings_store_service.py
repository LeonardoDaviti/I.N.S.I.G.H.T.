"""
Persistence service for markdown briefing outputs.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import psycopg

from insight_core.db.repo_briefings import BriefingsRepository


class BriefingsStoreService:
    """Read/write wrapper for persisted briefings."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = BriefingsRepository()

    def get_briefing(
        self,
        subject_type: str,
        subject_key: str,
        variant: str = "default",
    ) -> Optional[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_briefing(cur, subject_type, subject_key, variant)

    def save_briefing(
        self,
        *,
        subject_type: str,
        subject_key: str,
        content: str,
        variant: str = "default",
        render_format: str = "markdown",
        title: str | None = None,
        payload: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                saved = self.repo.upsert_briefing(
                    cur,
                    subject_type=subject_type,
                    subject_key=subject_key,
                    variant=variant,
                    render_format=render_format,
                    title=title,
                    content=content,
                    payload=payload,
                )
            conn.commit()
            return saved
