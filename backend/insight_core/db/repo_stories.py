"""Repository for story storage and read operations."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from psycopg import Cursor


class StoriesRepository:
    """SQL access layer for story tables."""

    ROLE_ORDER_CASE = """
        CASE sp.role
            WHEN 'anchor' THEN 0
            WHEN 'corroboration' THEN 1
            WHEN 'follow_up' THEN 2
            WHEN 'context' THEN 3
            WHEN 'commentary' THEN 4
            WHEN 'reaction' THEN 5
            WHEN 'contradiction' THEN 6
            WHEN 'duplicate' THEN 7
            ELSE 8
        END
    """

    UPDATE_ROLE_ORDER_CASE = """
        CASE COALESCE(sup.role, '')
            WHEN 'anchor' THEN 0
            WHEN 'corroboration' THEN 1
            WHEN 'follow_up' THEN 2
            WHEN 'context' THEN 3
            WHEN 'commentary' THEN 4
            WHEN 'reaction' THEN 5
            WHEN 'contradiction' THEN 6
            WHEN 'duplicate' THEN 7
            ELSE 8
        END
    """

    def __init__(self, db_url: str):
        self.db_url = db_url

    # ===============================
    # WRITE OPERATIONS
    # ===============================

    def insert_story(self, cur: Cursor, story: Dict[str, Any]) -> str:
        query = """
            INSERT INTO stories (
                canonical_title,
                canonical_summary,
                story_kind,
                status,
                anchor_post_id,
                anchor_confidence,
                first_seen_at,
                last_seen_at,
                created_by_method,
                resolution_version,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
        """
        cur.execute(
            query,
            (
                story["canonical_title"],
                story.get("canonical_summary"),
                story.get("story_kind", "other"),
                story.get("status", "active"),
                story.get("anchor_post_id"),
                float(story.get("anchor_confidence", 0.0)),
                story.get("first_seen_at"),
                story.get("last_seen_at"),
                story.get("created_by_method", "auto"),
                story.get("resolution_version"),
                json.dumps(story.get("metadata") or {}, default=self._json_default),
            ),
        )
        return str(cur.fetchone()[0])

    def update_story(self, cur: Cursor, story_id: str, **fields: Any) -> bool:
        mapping = {
            "canonical_title": "canonical_title",
            "canonical_summary": "canonical_summary",
            "story_kind": "story_kind",
            "status": "status",
            "anchor_post_id": "anchor_post_id",
            "anchor_confidence": "anchor_confidence",
            "first_seen_at": "first_seen_at",
            "last_seen_at": "last_seen_at",
            "created_by_method": "created_by_method",
            "resolution_version": "resolution_version",
            "metadata": "metadata",
        }

        set_clauses: List[str] = []
        params: List[Any] = []
        for field_name, column_name in mapping.items():
            if field_name not in fields:
                continue
            value = fields[field_name]
            if field_name == "metadata":
                value = json.dumps(value or {}, default=self._json_default)
                set_clauses.append(f"{column_name} = %s::jsonb")
            else:
                set_clauses.append(f"{column_name} = %s")
            params.append(value)

        if not set_clauses:
            return False

        query = f"""
            UPDATE stories
            SET {", ".join(set_clauses)},
                updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        params.append(story_id)
        cur.execute(query, params)
        return cur.fetchone() is not None

    def update_story_anchor(
        self,
        cur: Cursor,
        story_id: str,
        anchor_post_id: str | None,
        anchor_confidence: float = 0.0,
    ) -> bool:
        return self.update_story(
            cur,
            story_id,
            anchor_post_id=anchor_post_id,
            anchor_confidence=anchor_confidence,
        )

    def upsert_story_post(
        self,
        cur: Cursor,
        story_id: str,
        post_id: str,
        *,
        role: str,
        relevance_score: float = 0.0,
        anchor_score: float = 0.0,
        is_anchor_candidate: bool = False,
        evidence_weight: float = 0.0,
        added_by_method: str = "auto",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        query = """
            INSERT INTO story_posts (
                story_id,
                post_id,
                role,
                relevance_score,
                anchor_score,
                is_anchor_candidate,
                evidence_weight,
                added_by_method,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (story_id, post_id) DO UPDATE SET
                role = EXCLUDED.role,
                relevance_score = GREATEST(story_posts.relevance_score, EXCLUDED.relevance_score),
                anchor_score = GREATEST(story_posts.anchor_score, EXCLUDED.anchor_score),
                is_anchor_candidate = story_posts.is_anchor_candidate OR EXCLUDED.is_anchor_candidate,
                evidence_weight = GREATEST(story_posts.evidence_weight, EXCLUDED.evidence_weight),
                added_by_method = EXCLUDED.added_by_method,
                metadata = story_posts.metadata || EXCLUDED.metadata
            RETURNING story_id
        """
        cur.execute(
            query,
            (
                story_id,
                post_id,
                role,
                float(relevance_score or 0.0),
                float(anchor_score or 0.0),
                bool(is_anchor_candidate),
                float(evidence_weight or 0.0),
                added_by_method,
                json.dumps(metadata or {}, default=self._json_default),
            ),
        )
        return cur.fetchone() is not None

    def insert_story_update(self, cur: Cursor, update: Dict[str, Any]) -> str:
        query = """
            INSERT INTO story_updates (
                story_id,
                update_date,
                title,
                summary,
                importance_score,
                created_by_method,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
        """
        cur.execute(
            query,
            (
                update["story_id"],
                update["update_date"],
                update["title"],
                update["summary"],
                float(update.get("importance_score", 0.0)),
                update.get("created_by_method", "auto"),
                json.dumps(update.get("metadata") or {}, default=self._json_default),
            ),
        )
        return str(cur.fetchone()[0])

    def upsert_story_update_post(
        self,
        cur: Cursor,
        story_update_id: str,
        post_id: str,
        *,
        role: str | None = None,
    ) -> bool:
        query = """
            INSERT INTO story_update_posts (
                story_update_id,
                post_id,
                role
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (story_update_id, post_id) DO UPDATE SET
                role = EXCLUDED.role
            RETURNING story_update_id
        """
        cur.execute(query, (story_update_id, post_id, role))
        return cur.fetchone() is not None

    # ===============================
    # READ OPERATIONS
    # ===============================

    def get_story_by_id(self, cur: Cursor, story_id: str) -> Optional[Dict[str, Any]]:
        stories = self._fetch_story_cards(cur, story_id=story_id, limit=1)
        return stories[0] if stories else None

    def list_stories(
        self,
        cur: Cursor,
        *,
        status: str | None = None,
        story_kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        return self._fetch_story_cards(
            cur,
            status=status,
            story_kind=story_kind,
            limit=limit,
            offset=offset,
        )

    def get_stories_for_post(self, cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        query = f"""
            SELECT
                s.id,
                s.canonical_title,
                s.canonical_summary,
                s.story_kind,
                s.status,
                s.anchor_post_id,
                s.anchor_confidence,
                s.first_seen_at,
                s.last_seen_at,
                s.created_by_method,
                s.resolution_version,
                s.metadata,
                s.created_at,
                s.updated_at,
                COALESCE(sp_counts.post_count, 0) AS post_count,
                COALESCE(su_counts.update_count, 0) AS update_count,
                ap.id AS anchor_post_row_id,
                ap.url,
                ap.title,
                ap.published_at,
                ap.source_id,
                src.platform,
                src.handle_or_url,
                ap.normalized_url,
                ap.canonical_url,
                ap.url_host,
                sp.role,
                sp.relevance_score,
                sp.anchor_score,
                sp.is_anchor_candidate,
                sp.evidence_weight,
                sp.added_by_method,
                sp.added_at,
                sp.metadata AS story_post_metadata
            FROM story_posts sp
            JOIN stories s ON s.id = sp.story_id
            LEFT JOIN posts ap ON ap.id = s.anchor_post_id
            LEFT JOIN sources src ON src.id = ap.source_id
            LEFT JOIN (
                SELECT story_id, COUNT(*)::int AS post_count
                FROM story_posts
                GROUP BY story_id
            ) sp_counts ON sp_counts.story_id = s.id
            LEFT JOIN (
                SELECT story_id, COUNT(*)::int AS update_count
                FROM story_updates
                GROUP BY story_id
            ) su_counts ON su_counts.story_id = s.id
            WHERE sp.post_id = %s
            ORDER BY
                {self.ROLE_ORDER_CASE},
                sp.is_anchor_candidate DESC,
                sp.anchor_score DESC,
                sp.relevance_score DESC,
                COALESCE(s.last_seen_at, s.created_at) DESC,
                s.created_at DESC
        """
        cur.execute(query, (post_id,))
        return [self._story_card_from_post_row(row) for row in cur.fetchall()]

    def get_story_posts(self, cur: Cursor, story_id: str) -> List[Dict[str, Any]]:
        query = f"""
            SELECT
                sp.story_id,
                sp.post_id,
                sp.role,
                sp.relevance_score,
                sp.anchor_score,
                sp.is_anchor_candidate,
                sp.evidence_weight,
                sp.added_by_method,
                sp.added_at,
                sp.metadata,
                p.id,
                p.source_id,
                p.url,
                p.external_id,
                p.published_at,
                p.fetched_at,
                p.title,
                p.content,
                p.content_html,
                p.metadata AS post_metadata,
                p.media_urls,
                p.categories,
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
                p.title_original,
                p.body_original,
                p.title_pivot,
                p.summary_pivot,
                p.title_pivot_version,
                p.summary_pivot_version,
                s.platform,
                s.handle_or_url
            FROM story_posts sp
            JOIN posts p ON p.id = sp.post_id
            JOIN sources s ON s.id = p.source_id
            WHERE sp.story_id = %s
            ORDER BY
                {self.ROLE_ORDER_CASE},
                sp.is_anchor_candidate DESC,
                sp.anchor_score DESC,
                sp.relevance_score DESC,
                COALESCE(p.published_at, p.fetched_at) DESC,
                sp.added_at ASC
        """
        cur.execute(query, (story_id,))
        return [self._story_post_from_row(row) for row in cur.fetchall()]

    def get_story_updates(self, cur: Cursor, story_id: str) -> List[Dict[str, Any]]:
        query = """
            SELECT
                su.id,
                su.story_id,
                su.update_date,
                su.title,
                su.summary,
                su.importance_score,
                su.created_by_method,
                su.metadata,
                su.created_at,
                su.updated_at,
                COALESCE(post_counts.post_count, 0) AS post_count
            FROM story_updates su
            LEFT JOIN (
                SELECT story_update_id, COUNT(*)::int AS post_count
                FROM story_update_posts
                GROUP BY story_update_id
            ) post_counts ON post_counts.story_update_id = su.id
            WHERE su.story_id = %s
            ORDER BY su.update_date ASC, su.importance_score DESC, su.created_at ASC
        """
        cur.execute(query, (story_id,))
        return [self._story_update_from_row(row) for row in cur.fetchall()]

    def get_story_update_posts(self, cur: Cursor, story_update_id: str) -> List[Dict[str, Any]]:
        query = f"""
            SELECT
                sup.story_update_id,
                sup.post_id,
                sup.role,
                sup.created_at,
                p.id,
                p.source_id,
                p.url,
                p.external_id,
                p.published_at,
                p.fetched_at,
                p.title,
                p.content,
                p.content_html,
                p.metadata,
                p.media_urls,
                p.categories,
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
                p.title_original,
                p.body_original,
                p.title_pivot,
                p.summary_pivot,
                p.title_pivot_version,
                p.summary_pivot_version,
                s.platform,
                s.handle_or_url
            FROM story_update_posts sup
            JOIN posts p ON p.id = sup.post_id
            JOIN sources s ON s.id = p.source_id
            WHERE sup.story_update_id = %s
            ORDER BY
                {self.UPDATE_ROLE_ORDER_CASE},
                COALESCE(p.published_at, p.fetched_at) DESC,
                sup.created_at ASC
        """
        cur.execute(query, (story_update_id,))
        return [self._story_update_post_from_row(row) for row in cur.fetchall()]

    # ===============================
    # PUBLIC HELPERS
    # ===============================

    def get_story_detail(self, cur: Cursor, story_id: str) -> Optional[Dict[str, Any]]:
        story = self.get_story_by_id(cur, story_id)
        if not story:
            return None

        posts = self.get_story_posts(cur, story_id)
        updates = self.get_story_updates(cur, story_id)
        for update in updates:
            update["posts"] = self.get_story_update_posts(cur, update["id"])

        grouped_posts = self._group_posts_by_role(posts)
        story["posts"] = posts
        story["posts_by_role"] = grouped_posts
        story["updates"] = updates
        story["timeline"] = updates
        story["post_count"] = len(posts)
        story["update_count"] = len(updates)
        return story

    # ===============================
    # INTERNAL HELPERS
    # ===============================

    def _fetch_story_cards(
        self,
        cur: Cursor,
        *,
        story_id: str | None = None,
        status: str | None = None,
        story_kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        where_clauses: List[str] = []
        params: List[Any] = []

        if story_id is not None:
            where_clauses.append("s.id = %s")
            params.append(story_id)
        if status is not None:
            where_clauses.append("s.status = %s")
            params.append(status)
        if story_kind is not None:
            where_clauses.append("s.story_kind = %s")
            params.append(story_kind)

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = f"""
            SELECT
                s.id,
                s.canonical_title,
                s.canonical_summary,
                s.story_kind,
                s.status,
                s.anchor_post_id,
                s.anchor_confidence,
                s.first_seen_at,
                s.last_seen_at,
                s.created_by_method,
                s.resolution_version,
                s.metadata,
                s.created_at,
                s.updated_at,
                COALESCE(sp_counts.post_count, 0) AS post_count,
                COALESCE(su_counts.update_count, 0) AS update_count,
                ap.id AS anchor_post_row_id,
                ap.url,
                ap.title,
                ap.published_at,
                ap.source_id,
                src.platform,
                src.handle_or_url,
                ap.normalized_url,
                ap.canonical_url,
                ap.url_host
            FROM stories s
            LEFT JOIN posts ap ON ap.id = s.anchor_post_id
            LEFT JOIN sources src ON src.id = ap.source_id
            LEFT JOIN (
                SELECT story_id, COUNT(*)::int AS post_count
                FROM story_posts
                GROUP BY story_id
            ) sp_counts ON sp_counts.story_id = s.id
            LEFT JOIN (
                SELECT story_id, COUNT(*)::int AS update_count
                FROM story_updates
                GROUP BY story_id
            ) su_counts ON su_counts.story_id = s.id
            {where_sql}
            ORDER BY COALESCE(s.last_seen_at, s.created_at) DESC, s.created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([int(limit), int(offset)])
        cur.execute(query, params)
        return [self._story_card_from_row(row) for row in cur.fetchall()]

    def _story_card_from_row(self, row: tuple[Any, ...]) -> Dict[str, Any]:
        story = self._story_base_from_row(row)
        anchor_post_id = row[16]
        story["anchor_post"] = None
        if anchor_post_id:
            story["anchor_post"] = {
                "id": str(anchor_post_id),
                "url": row[17],
                "title": row[18],
                "published_at": row[19],
                "source_id": str(row[20]) if row[20] else None,
                "platform": row[21],
                "handle_or_url": row[22],
                "normalized_url": row[23],
                "canonical_url": row[24],
                "url_host": row[25],
            }
        return story

    def _story_card_from_post_row(self, row: tuple[Any, ...]) -> Dict[str, Any]:
        story = self._story_base_from_row(row)
        anchor_post_id = row[16]
        story["anchor_post"] = None
        if anchor_post_id:
            story["anchor_post"] = {
                "id": str(anchor_post_id),
                "url": row[17],
                "title": row[18],
                "published_at": row[19],
                "source_id": str(row[20]) if row[20] else None,
                "platform": row[21],
                "handle_or_url": row[22],
                "normalized_url": row[23],
                "canonical_url": row[24],
                "url_host": row[25],
            }
        story["role"] = row[26]
        story["relevance_score"] = float(row[27]) if row[27] is not None else 0.0
        story["anchor_score"] = float(row[28]) if row[28] is not None else 0.0
        story["is_anchor_candidate"] = bool(row[29])
        story["evidence_weight"] = float(row[30]) if row[30] is not None else 0.0
        story["added_by_method"] = row[31]
        story["added_at"] = row[32]
        story["story_post_metadata"] = row[33] or {}
        return story

    def _story_post_from_row(self, row: tuple[Any, ...]) -> Dict[str, Any]:
        story_post = {
            "story_id": str(row[0]),
            "post_id": str(row[1]),
            "role": row[2],
            "relevance_score": float(row[3]) if row[3] is not None else 0.0,
            "anchor_score": float(row[4]) if row[4] is not None else 0.0,
            "is_anchor_candidate": bool(row[5]),
            "evidence_weight": float(row[6]) if row[6] is not None else 0.0,
            "added_by_method": row[7],
            "added_at": row[8],
            "metadata": row[9] or {},
            "post": self._post_from_row(row[10:]),
        }
        return story_post

    def _story_update_from_row(self, row: tuple[Any, ...]) -> Dict[str, Any]:
        return {
            "id": str(row[0]),
            "story_id": str(row[1]),
            "update_date": row[2],
            "title": row[3],
            "summary": row[4],
            "importance_score": float(row[5]) if row[5] is not None else 0.0,
            "created_by_method": row[6],
            "metadata": row[7] or {},
            "created_at": row[8],
            "updated_at": row[9],
            "post_count": int(row[10]) if row[10] is not None else 0,
        }

    def _story_update_post_from_row(self, row: tuple[Any, ...]) -> Dict[str, Any]:
        return {
            "story_update_id": str(row[0]),
            "post_id": str(row[1]),
            "role": row[2],
            "created_at": row[3],
            "post": self._post_from_row(row[4:]),
        }

    def _story_base_from_row(self, row: tuple[Any, ...]) -> Dict[str, Any]:
        return {
            "id": str(row[0]),
            "canonical_title": row[1],
            "canonical_summary": row[2],
            "story_kind": row[3],
            "status": row[4],
            "anchor_post_id": str(row[5]) if row[5] else None,
            "anchor_confidence": float(row[6]) if row[6] is not None else 0.0,
            "first_seen_at": row[7],
            "last_seen_at": row[8],
            "created_by_method": row[9],
            "resolution_version": row[10],
            "metadata": row[11] or {},
            "created_at": row[12],
            "updated_at": row[13],
            "post_count": int(row[14]) if row[14] is not None else 0,
            "update_count": int(row[15]) if row[15] is not None else 0,
        }

    def _group_posts_by_role(self, posts: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for post in posts:
            grouped.setdefault(post.get("role") or "context", []).append(post)
        return grouped

    def _post_from_row(self, row: tuple[Any, ...]) -> Dict[str, Any]:
        return {
            "id": str(row[0]),
            "source_id": str(row[1]) if row[1] else None,
            "url": row[2],
            "external_id": row[3],
            "published_at": row[4],
            "fetched_at": row[5],
            "title": row[6],
            "content": row[7],
            "content_html": row[8],
            "metadata": row[9] or {},
            "media_urls": row[10] or [],
            "categories": row[11] or [],
            "lang": row[12],
            "language_code": row[13],
            "language_confidence": float(row[14]) if row[14] is not None else None,
            "normalized_url": row[15],
            "canonical_url": row[16],
            "url_host": row[17],
            "title_hash": row[18],
            "content_hash": row[19],
            "normalization_version": row[20],
            "enriched_at": row[21],
            "title_original": row[22],
            "body_original": row[23],
            "title_pivot": row[24],
            "summary_pivot": row[25],
            "title_pivot_version": row[26],
            "summary_pivot_version": row[27],
            "platform": row[28],
            "handle_or_url": row[29],
        }

    def _json_default(self, value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value)} is not JSON serializable")
