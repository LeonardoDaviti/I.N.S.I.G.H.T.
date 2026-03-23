"""Explainability, artifact references, highlights, and reader interactions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import psycopg

from insight_core.db.repo_explainability import ExplainabilityRepository
from insight_core.logs.core.logger_config import get_component_logger


class ExplainabilityService:
    """Orchestrate explainability persistence and reads."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = ExplainabilityRepository(db_url)
        self.logger = get_component_logger("explainability_service")

    def save_post_highlights(
        self,
        post_id: str,
        highlights: List[Dict[str, Any]],
        *,
        extractor_name: str,
        extractor_version: str,
        language_code: str | None = None,
    ) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                stored = self.repo.upsert_post_highlights(
                    cur,
                    post_id,
                    highlights,
                    extractor_name=extractor_name,
                    extractor_version=extractor_version,
                    language_code=language_code,
                )
            conn.commit()
        return stored

    def get_post_highlights(self, post_id: str) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_post_highlights(cur, post_id)

    def save_artifact_references(
        self,
        artifact_type: str,
        artifact_id: str,
        references: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                stored = self.repo.upsert_artifact_post_references(cur, artifact_type, artifact_id, references)
            conn.commit()
        return stored

    def get_artifact_references(self, artifact_type: str, artifact_id: str) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_artifact_post_references(cur, artifact_type, artifact_id)

    def record_post_interaction(
        self,
        post_id: str,
        interaction_type: str,
        interaction_value: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                stored = self.repo.record_post_interaction(cur, post_id, interaction_type, interaction_value)
            conn.commit()
        return stored

    def get_post_interactions(self, post_id: str) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_post_interactions(cur, post_id)

    def get_post_reader_state(self, post_id: str) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_post_reader_state(cur, post_id)
