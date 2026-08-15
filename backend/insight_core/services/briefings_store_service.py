"""
Persistence service for markdown briefing outputs.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

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

    def list_briefings(
        self,
        subject_type: str,
        subject_key_prefix: str,
        variant: str = "default",
        limit: int = 60,
    ) -> List[Dict[str, Any]]:
        """Metadata-only history for a subject_key prefix, newest first."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.list_briefings(cur, subject_type, subject_key_prefix, variant, limit)

    def get_latest_briefing(
        self,
        subject_type: str,
        subject_key_prefix: str,
        variant: str = "default",
    ) -> Optional[Dict[str, Any]]:
        """Most recent briefing for a subject_key prefix (e.g. all runs of one expert)."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_latest_briefing(cur, subject_type, subject_key_prefix, variant)

    def get_latest_briefing_timestamp(
        self,
        subject_type: str,
        subject_key_prefix: str,
        variant: str = "default",
    ):
        """Timestamp of the most recent briefing for a subject_key prefix."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_latest_briefing_timestamp(cur, subject_type, subject_key_prefix, variant)

    def get_briefing_timestamp(
        self,
        subject_type: str,
        subject_key: str,
        variant: str = "default",
    ):
        """Timestamp only - avoids pulling the briefing body just to read a date."""
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_briefing_timestamp(cur, subject_type, subject_key, variant)

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
