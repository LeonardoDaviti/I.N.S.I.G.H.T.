"""Repository for evidence foundation tables and debug views."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import psycopg
from psycopg import Cursor


class EvidenceRepository:
    """SQL access layer for evidence enrichment and linkage tables."""

    def __init__(self, db_url: str):
        self.db_url = db_url

    def update_post_evidence(self, cur: Cursor, post_id: str, evidence: Dict[str, Any]) -> bool:
        query = """
            UPDATE posts
            SET lang = COALESCE(lang, %s),
                language_code = %s,
                language_confidence = %s,
                normalized_url = %s,
                canonical_url = %s,
                url_host = %s,
                title_hash = %s,
                content_hash = %s,
                normalization_version = %s,
                enriched_at = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        cur.execute(
            query,
            (
                evidence.get("lang"),
                evidence.get("language_code"),
                evidence.get("language_confidence"),
                evidence.get("normalized_url"),
                evidence.get("canonical_url"),
                evidence.get("url_host"),
                evidence.get("title_hash"),
                evidence.get("content_hash"),
                evidence.get("normalization_version"),
                evidence.get("enriched_at"),
                post_id,
            ),
        )
        return cur.fetchone() is not None

    def upsert_artifact(self, cur: Cursor, artifact: Dict[str, Any]) -> str:
        query = """
            INSERT INTO artifacts (
                artifact_type,
                canonical_url,
                normalized_url,
                url_host,
                display_title,
                status,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (normalized_url) DO UPDATE SET
                artifact_type = CASE
                    WHEN artifacts.artifact_type = 'other' THEN EXCLUDED.artifact_type
                    ELSE artifacts.artifact_type
                END,
                canonical_url = EXCLUDED.canonical_url,
                url_host = COALESCE(EXCLUDED.url_host, artifacts.url_host),
                display_title = COALESCE(EXCLUDED.display_title, artifacts.display_title),
                status = EXCLUDED.status,
                metadata = artifacts.metadata || EXCLUDED.metadata,
                updated_at = now()
            RETURNING id
        """
        cur.execute(
            query,
            (
                artifact.get("artifact_type", "other"),
                artifact["canonical_url"],
                artifact["normalized_url"],
                artifact.get("url_host"),
                artifact.get("display_title"),
                artifact.get("status", "active"),
                json.dumps(artifact.get("metadata") or {}, default=self._json_default),
            ),
        )
        return str(cur.fetchone()[0])

    def link_post_artifact(
        self,
        cur: Cursor,
        post_id: str,
        artifact_id: str,
        relation_type: str,
        confidence: float,
        is_primary: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        query = """
            INSERT INTO post_artifacts (
                post_id,
                artifact_id,
                relation_type,
                confidence,
                is_primary,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (post_id, artifact_id, relation_type) DO UPDATE SET
                confidence = GREATEST(post_artifacts.confidence, EXCLUDED.confidence),
                is_primary = post_artifacts.is_primary OR EXCLUDED.is_primary,
                metadata = post_artifacts.metadata || EXCLUDED.metadata
            RETURNING post_id
        """
        cur.execute(
            query,
            (
                post_id,
                artifact_id,
                relation_type,
                float(confidence or 0.0),
                bool(is_primary),
                json.dumps(metadata or {}, default=self._json_default),
            ),
        )
        return cur.fetchone() is not None

    def upsert_post_relation(
        self,
        cur: Cursor,
        from_post_id: str,
        to_post_id: str,
        relation_type: str,
        method: str,
        confidence: float,
        *,
        job_run_id: str | None = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        if from_post_id == to_post_id:
            return False

        query = """
            INSERT INTO post_relations (
                from_post_id,
                to_post_id,
                relation_type,
                method,
                confidence,
                job_run_id,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (from_post_id, to_post_id, relation_type) DO UPDATE SET
                method = EXCLUDED.method,
                confidence = GREATEST(post_relations.confidence, EXCLUDED.confidence),
                job_run_id = COALESCE(EXCLUDED.job_run_id, post_relations.job_run_id),
                metadata = post_relations.metadata || EXCLUDED.metadata
            RETURNING from_post_id
        """
        cur.execute(
            query,
            (
                from_post_id,
                to_post_id,
                relation_type,
                method,
                float(confidence or 0.0),
                job_run_id,
                json.dumps(metadata or {}, default=self._json_default),
            ),
        )
        return cur.fetchone() is not None

    def get_posts_by_normalized_url(
        self,
        cur: Cursor,
        normalized_url: str,
        *,
        exclude_post_id: str | None = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                p.id,
                p.source_id,
                p.url,
                p.title,
                p.content,
                p.content_html,
                p.published_at,
                p.fetched_at,
                p.language_code,
                p.normalized_url,
                p.canonical_url,
                p.url_host,
                p.title_hash,
                p.content_hash,
                s.platform,
                s.handle_or_url
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            WHERE p.normalized_url = %s
              AND (%s IS NULL OR p.id <> %s)
            ORDER BY COALESCE(p.published_at, p.fetched_at) DESC
            LIMIT %s
        """
        cur.execute(query, (normalized_url, exclude_post_id, exclude_post_id, limit))
        return [self._post_row_to_dict(row) for row in cur.fetchall()]

    def get_posts_by_artifact(
        self,
        cur: Cursor,
        artifact_id: str,
        *,
        exclude_post_id: str | None = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                p.id,
                p.source_id,
                p.url,
                p.title,
                p.content,
                p.content_html,
                p.published_at,
                p.fetched_at,
                p.language_code,
                p.normalized_url,
                p.canonical_url,
                p.url_host,
                p.title_hash,
                p.content_hash,
                s.platform,
                s.handle_or_url,
                pa.is_primary,
                pa.relation_type
            FROM post_artifacts pa
            JOIN posts p ON p.id = pa.post_id
            JOIN sources s ON s.id = p.source_id
            WHERE pa.artifact_id = %s
              AND (%s IS NULL OR p.id <> %s)
            ORDER BY pa.is_primary DESC, COALESCE(p.published_at, p.fetched_at) DESC
            LIMIT %s
        """
        cur.execute(query, (artifact_id, exclude_post_id, exclude_post_id, limit))
        return [self._post_row_to_dict(row) for row in cur.fetchall()]

    def get_recent_posts_by_host(
        self,
        cur: Cursor,
        url_host: str,
        since: datetime,
        *,
        exclude_post_id: str | None = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
                p.id,
                p.source_id,
                p.url,
                p.title,
                p.content,
                p.content_html,
                p.published_at,
                p.fetched_at,
                p.language_code,
                p.normalized_url,
                p.canonical_url,
                p.url_host,
                p.title_hash,
                p.content_hash,
                s.platform,
                s.handle_or_url
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            WHERE p.url_host = %s
              AND COALESCE(p.published_at, p.fetched_at) >= %s
              AND (%s IS NULL OR p.id <> %s)
            ORDER BY COALESCE(p.published_at, p.fetched_at) DESC
            LIMIT %s
        """
        cur.execute(query, (url_host, since, exclude_post_id, exclude_post_id, limit))
        return [self._post_row_to_dict(row) for row in cur.fetchall()]

    def get_post_artifacts(self, cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        query = """
            SELECT
                a.id,
                a.artifact_type,
                a.canonical_url,
                a.normalized_url,
                a.url_host,
                a.display_title,
                a.status,
                a.metadata AS artifact_metadata,
                pa.relation_type,
                pa.confidence,
                pa.is_primary,
                pa.metadata AS link_metadata,
                pa.created_at AS linked_at
            FROM post_artifacts pa
            JOIN artifacts a ON a.id = pa.artifact_id
            WHERE pa.post_id = %s
            ORDER BY pa.is_primary DESC, pa.created_at DESC, a.display_title
        """
        cur.execute(query, (post_id,))
        rows = cur.fetchall()
        artifacts = []
        for row in rows:
            artifacts.append(
                {
                    "id": str(row[0]),
                    "artifact_type": row[1],
                    "canonical_url": row[2],
                    "normalized_url": row[3],
                    "url_host": row[4],
                    "display_title": row[5],
                    "status": row[6],
                    "metadata": row[7] or {},
                    "relation_type": row[8],
                    "confidence": float(row[9]) if row[9] is not None else 0.0,
                    "is_primary": bool(row[10]),
                    "link_metadata": row[11] or {},
                    "created_at": row[12],
                }
            )
        return artifacts

    def get_post_relations(self, cur: Cursor, post_id: str) -> Dict[str, List[Dict[str, Any]]]:
        outgoing = self._get_relations(cur, post_id, direction="outgoing")
        incoming = self._get_relations(cur, post_id, direction="incoming")
        return {"outgoing": outgoing, "incoming": incoming}

    def get_post_evidence_debug(self, cur: Cursor, post_id: str) -> Dict[str, Any]:
        cur.execute(
            """
            SELECT
                p.id,
                p.source_id,
                p.url,
                p.external_id,
                p.published_at,
                p.fetched_at,
                p.title,
                p.content,
                p.content_html,
                p.media_urls,
                p.categories,
                p.metadata,
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
                p.created_at,
                p.updated_at,
                s.platform,
                s.handle_or_url,
                COALESCE(s.settings->>'display_name', s.handle_or_url) AS source_display_name
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            WHERE p.id = %s
            """,
            (post_id,),
        )
        row = cur.fetchone()
        if not row:
            return {}

        return {
            "post": {
                "id": str(row[0]),
                "source_id": str(row[1]),
                "url": row[2],
                "external_id": row[3],
                "published_at": row[4].isoformat() if row[4] else None,
                "fetched_at": row[5].isoformat() if row[5] else None,
                "title": row[6],
                "content": row[7],
                "content_html": row[8],
                "media_urls": row[9] or [],
                "categories": row[10] or [],
                "metadata": row[11] or {},
                "lang": row[12],
                "language_code": row[13],
                "language_confidence": float(row[14]) if row[14] is not None else None,
                "normalized_url": row[15],
                "canonical_url": row[16],
                "url_host": row[17],
                "title_hash": row[18],
                "content_hash": row[19],
                "normalization_version": row[20],
                "enriched_at": row[21].isoformat() if row[21] else None,
                "created_at": row[22].isoformat() if row[22] else None,
                "updated_at": row[23].isoformat() if row[23] else None,
                "platform": row[24],
                "source": row[25],
                "source_display_name": row[26],
            },
            "artifacts": self.get_post_artifacts(cur, post_id),
            "relations": self.get_post_relations(cur, post_id),
        }

    def _get_relations(self, cur: Cursor, post_id: str, *, direction: str) -> List[Dict[str, Any]]:
        if direction == "incoming":
            query = """
                SELECT
                    pr.from_post_id,
                    pr.to_post_id,
                    pr.relation_type,
                    pr.method,
                    pr.confidence,
                    pr.job_run_id,
                    pr.metadata,
                    pr.created_at,
                    p.url,
                    p.title,
                    p.language_code,
                    p.normalized_url,
                    p.url_host
                FROM post_relations pr
                JOIN posts p ON p.id = pr.from_post_id
                WHERE pr.to_post_id = %s
                ORDER BY pr.created_at DESC
            """
        else:
            query = """
                SELECT
                    pr.from_post_id,
                    pr.to_post_id,
                    pr.relation_type,
                    pr.method,
                    pr.confidence,
                    pr.job_run_id,
                    pr.metadata,
                    pr.created_at,
                    p.url,
                    p.title,
                    p.language_code,
                    p.normalized_url,
                    p.url_host
                FROM post_relations pr
                JOIN posts p ON p.id = pr.to_post_id
                WHERE pr.from_post_id = %s
                ORDER BY pr.created_at DESC
            """
        cur.execute(query, (post_id,))
        rows = cur.fetchall()
        relations = []
        for row in rows:
            relations.append(
                {
                    "from_post_id": str(row[0]),
                    "to_post_id": str(row[1]),
                    "relation_type": row[2],
                    "method": row[3],
                    "confidence": float(row[4]) if row[4] is not None else 0.0,
                    "job_run_id": str(row[5]) if row[5] else None,
                    "metadata": row[6] or {},
                    "created_at": row[7],
                    "other_post": {
                        "url": row[8],
                        "title": row[9],
                        "language_code": row[10],
                        "normalized_url": row[11],
                        "url_host": row[12],
                    },
                }
            )
        return relations

    def _post_row_to_dict(self, row) -> Dict[str, Any]:
        return {
            "id": str(row[0]),
            "source_id": str(row[1]),
            "url": row[2],
            "title": row[3],
            "content": row[4],
            "content_html": row[5],
            "published_at": row[6],
            "fetched_at": row[7],
            "language_code": row[8],
            "normalized_url": row[9],
            "canonical_url": row[10],
            "url_host": row[11],
            "title_hash": row[12],
            "content_hash": row[13],
            "platform": row[14],
            "handle_or_url": row[15],
            "relation_type": row[17] if len(row) > 17 else None,
            "is_primary": bool(row[16]) if len(row) > 16 else None,
        }

    def _json_default(self, value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value)} is not JSON serializable")
