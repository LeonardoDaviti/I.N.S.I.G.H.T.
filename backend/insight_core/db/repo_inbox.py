"""Repository for analyst inbox batches, items, actions, and candidate views."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from psycopg import Cursor


class InboxRepository:
    """SQL access layer for inbox batches, items, and actions."""

    DUPLICATE_RELATION_TYPES = (
        "exact_duplicate",
        "near_duplicate",
        "syndicated_from",
        "translation_of",
    )

    def __init__(self, db_url: str):
        self.db_url = db_url

    # ===============================
    # BATCH OPERATIONS
    # ===============================

    def create_batch(self, cur: Cursor, batch: Dict[str, Any]) -> str:
        query = """
            INSERT INTO inbox_batches (
                scope_type,
                scope_value,
                generated_for_date,
                status,
                item_count,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
        """
        cur.execute(
            query,
            (
                batch.get("scope_type", "daily_queue"),
                batch.get("scope_value"),
                batch.get("generated_for_date"),
                batch.get("status", "ready"),
                int(batch.get("item_count", 0) or 0),
                json.dumps(batch.get("metadata") or {}, default=self._json_default),
            ),
        )
        return str(cur.fetchone()[0])

    def update_batch(self, cur: Cursor, batch_id: str, **fields: Any) -> bool:
        mapping = {
            "scope_type": "scope_type",
            "scope_value": "scope_value",
            "generated_for_date": "generated_for_date",
            "status": "status",
            "item_count": "item_count",
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
            UPDATE inbox_batches
            SET {", ".join(set_clauses)},
                updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        params.append(batch_id)
        cur.execute(query, params)
        return cur.fetchone() is not None

    def supersede_batches(
        self,
        cur: Cursor,
        *,
        scope_type: str,
        generated_for_date: date | None,
        scope_value: str | None = None,
        keep_batch_id: str | None = None,
    ) -> int:
        clauses = ["scope_type = %s"]
        params: List[Any] = [scope_type]
        if generated_for_date is not None:
            clauses.append("generated_for_date = %s")
            params.append(generated_for_date)
        else:
            clauses.append("generated_for_date IS NULL")
        if scope_value is None:
            clauses.append("scope_value IS NULL")
        else:
            clauses.append("scope_value = %s")
            params.append(scope_value)
        if keep_batch_id is not None:
            clauses.append("id <> %s")
            params.append(keep_batch_id)

        query = f"""
            UPDATE inbox_batches
            SET status = 'superseded',
                updated_at = now()
            WHERE {' AND '.join(clauses)}
            RETURNING id
        """
        cur.execute(query, params)
        return len(cur.fetchall())

    def get_batch_by_id(self, cur: Cursor, batch_id: str) -> Optional[Dict[str, Any]]:
        query = """
            SELECT
              b.id,
              b.scope_type,
              b.scope_value,
              b.generated_for_date,
              b.status,
              b.item_count,
              b.metadata,
              b.created_at,
              b.updated_at,
              COALESCE((
                SELECT COUNT(*)
                FROM inbox_items i
                WHERE i.batch_id = b.id AND i.status = 'pending'
              ), 0) AS pending_count,
              COALESCE((
                SELECT COUNT(*)
                FROM inbox_items i
                WHERE i.batch_id = b.id AND i.status <> 'pending'
              ), 0) AS acted_count
            FROM inbox_batches b
            WHERE b.id = %s
        """
        cur.execute(query, (batch_id,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(
            row,
            [
                "id",
                "scope_type",
                "scope_value",
                "generated_for_date",
                "status",
                "item_count",
                "metadata",
                "created_at",
                "updated_at",
                "pending_count",
                "acted_count",
            ],
        )

    def get_latest_batch(
        self,
        cur: Cursor,
        *,
        scope_type: str | None = None,
        scope_value: str | None = None,
        generated_for_date: date | None = None,
    ) -> Optional[Dict[str, Any]]:
        where_clauses: List[str] = []
        params: List[Any] = []
        if scope_type is not None:
            where_clauses.append("b.scope_type = %s")
            params.append(scope_type)
        if scope_value is not None:
            where_clauses.append("b.scope_value = %s")
            params.append(scope_value)
        if generated_for_date is not None:
            where_clauses.append("b.generated_for_date = %s")
            params.append(generated_for_date)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        query = f"""
            SELECT
              b.id,
              b.scope_type,
              b.scope_value,
              b.generated_for_date,
              b.status,
              b.item_count,
              b.metadata,
              b.created_at,
              b.updated_at,
              COALESCE((
                SELECT COUNT(*)
                FROM inbox_items i
                WHERE i.batch_id = b.id AND i.status = 'pending'
              ), 0) AS pending_count,
              COALESCE((
                SELECT COUNT(*)
                FROM inbox_items i
                WHERE i.batch_id = b.id AND i.status <> 'pending'
              ), 0) AS acted_count
            FROM inbox_batches b
            {where_sql}
            ORDER BY b.created_at DESC, b.id DESC
            LIMIT 1
        """
        cur.execute(query, params)
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(
            row,
            [
                "id",
                "scope_type",
                "scope_value",
                "generated_for_date",
                "status",
                "item_count",
                "metadata",
                "created_at",
                "updated_at",
                "pending_count",
                "acted_count",
            ],
        )

    def list_batches(self, cur: Cursor, *, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        query = """
            SELECT
              b.id,
              b.scope_type,
              b.scope_value,
              b.generated_for_date,
              b.status,
              b.item_count,
              b.metadata,
              b.created_at,
              b.updated_at,
              COALESCE((
                SELECT COUNT(*)
                FROM inbox_items i
                WHERE i.batch_id = b.id AND i.status = 'pending'
              ), 0) AS pending_count,
              COALESCE((
                SELECT COUNT(*)
                FROM inbox_items i
                WHERE i.batch_id = b.id AND i.status <> 'pending'
              ), 0) AS acted_count
            FROM inbox_batches b
            ORDER BY b.created_at DESC, b.id DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(query, (int(limit), int(offset)))
        return self._rows_to_dicts(
            cur.fetchall(),
            [
                "id",
                "scope_type",
                "scope_value",
                "generated_for_date",
                "status",
                "item_count",
                "metadata",
                "created_at",
                "updated_at",
                "pending_count",
                "acted_count",
            ],
        )

    # ===============================
    # ITEM OPERATIONS
    # ===============================

    def insert_item(self, cur: Cursor, item: Dict[str, Any]) -> str:
        query = """
            INSERT INTO inbox_items (
                batch_id,
                target_type,
                target_id,
                status,
                priority_score,
                novelty_score,
                evidence_score,
                duplication_penalty,
                source_priority_score,
                reason_summary,
                reasons,
                surfaced_at,
                acted_at,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb)
            ON CONFLICT (batch_id, target_type, target_id) DO UPDATE SET
                status = EXCLUDED.status,
                priority_score = GREATEST(inbox_items.priority_score, EXCLUDED.priority_score),
                novelty_score = GREATEST(inbox_items.novelty_score, EXCLUDED.novelty_score),
                evidence_score = GREATEST(inbox_items.evidence_score, EXCLUDED.evidence_score),
                duplication_penalty = GREATEST(inbox_items.duplication_penalty, EXCLUDED.duplication_penalty),
                source_priority_score = GREATEST(inbox_items.source_priority_score, EXCLUDED.source_priority_score),
                reason_summary = CASE
                    WHEN inbox_items.reason_summary IS NULL OR inbox_items.reason_summary = ''
                    THEN EXCLUDED.reason_summary
                    WHEN EXCLUDED.reason_summary IS NULL OR EXCLUDED.reason_summary = ''
                    THEN inbox_items.reason_summary
                    WHEN inbox_items.reason_summary = EXCLUDED.reason_summary
                    THEN inbox_items.reason_summary
                    ELSE inbox_items.reason_summary || '; ' || EXCLUDED.reason_summary
                END,
                reasons = COALESCE(inbox_items.reasons, '[]'::jsonb) || COALESCE(EXCLUDED.reasons, '[]'::jsonb),
                surfaced_at = LEAST(inbox_items.surfaced_at, EXCLUDED.surfaced_at),
                metadata = inbox_items.metadata || EXCLUDED.metadata,
                updated_at = now()
            RETURNING id
        """
        cur.execute(
            query,
            (
                item["batch_id"],
                item["target_type"],
                item["target_id"],
                item.get("status", "pending"),
                float(item.get("priority_score", 0.0)),
                float(item.get("novelty_score", 0.0)),
                float(item.get("evidence_score", 0.0)),
                float(item.get("duplication_penalty", 0.0)),
                float(item.get("source_priority_score", 0.0)),
                item.get("reason_summary"),
                json.dumps(item.get("reasons") or [], default=self._json_default),
                item.get("surfaced_at") or datetime.now(),
                item.get("acted_at"),
                json.dumps(item.get("metadata") or {}, default=self._json_default),
            ),
        )
        return str(cur.fetchone()[0])

    def get_item_by_id(self, cur: Cursor, item_id: str) -> Optional[Dict[str, Any]]:
        query = self._item_query_base() + " WHERE i.id = %s"
        cur.execute(query, (item_id,))
        row = cur.fetchone()
        if not row:
            return None
        return self._row_to_dict(
            row,
            [
                "id",
                "batch_id",
                "batch_scope_type",
                "batch_scope_value",
                "batch_generated_for_date",
                "batch_status",
                "batch_item_count",
                "batch_metadata",
                "batch_created_at",
                "batch_updated_at",
                "target_type",
                "target_id",
                "status",
                "priority_score",
                "novelty_score",
                "evidence_score",
                "duplication_penalty",
                "source_priority_score",
                "reason_summary",
                "reasons",
                "surfaced_at",
                "acted_at",
                "metadata",
                "item_created_at",
                "item_updated_at",
                "target_preview",
            ],
        )

    def list_items(
        self,
        cur: Cursor,
        *,
        batch_id: str | None = None,
        status: str | None = None,
        target_type: str | None = None,
        source_id: str | None = None,
        generated_for_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        where_clauses: List[str] = []
        params: List[Any] = []
        if batch_id is not None:
            where_clauses.append("i.batch_id = %s")
            params.append(batch_id)
        if status is not None:
            where_clauses.append("i.status = %s")
            params.append(status)
        if target_type is not None:
            where_clauses.append("i.target_type = %s")
            params.append(target_type)
        if source_id is not None:
            where_clauses.append("COALESCE(p.source_id, asrc.id) = %s")
            params.append(source_id)
        if generated_for_date is not None:
            where_clauses.append("b.generated_for_date = %s")
            params.append(generated_for_date)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = self._item_query_base() + f" {where_sql} ORDER BY i.priority_score DESC, i.surfaced_at ASC, i.created_at ASC LIMIT %s OFFSET %s"
        params.extend([int(limit), int(offset)])
        cur.execute(query, params)
        return self._rows_to_dicts(
            cur.fetchall(),
            [
                "id",
                "batch_id",
                "batch_scope_type",
                "batch_scope_value",
                "batch_generated_for_date",
                "batch_status",
                "batch_item_count",
                "batch_metadata",
                "batch_created_at",
                "batch_updated_at",
                "target_type",
                "target_id",
                "status",
                "priority_score",
                "novelty_score",
                "evidence_score",
                "duplication_penalty",
                "source_priority_score",
                "reason_summary",
                "reasons",
                "surfaced_at",
                "acted_at",
                "metadata",
                "item_created_at",
                "item_updated_at",
                "target_preview",
            ],
        )

    def update_item_after_action(
        self,
        cur: Cursor,
        item_id: str,
        *,
        status: str,
        metadata_patch: Dict[str, Any] | None = None,
        acted_at: datetime | None = None,
    ) -> bool:
        query = """
            UPDATE inbox_items
            SET status = %s,
                acted_at = COALESCE(%s, acted_at),
                metadata = metadata || %s::jsonb,
                updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        cur.execute(
            query,
            (
                status,
                acted_at,
                json.dumps(metadata_patch or {}, default=self._json_default),
                item_id,
            ),
        )
        return cur.fetchone() is not None

    # ===============================
    # ACTION LOG
    # ===============================

    def insert_action(self, cur: Cursor, action: Dict[str, Any]) -> Dict[str, Any]:
        query = """
            INSERT INTO analyst_actions (
                inbox_item_id,
                target_type,
                target_id,
                action_type,
                actor_id,
                payload,
                created_by
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            RETURNING id, inbox_item_id, target_type, target_id, action_type, actor_id, created_by, payload, created_at
        """
        cur.execute(
            query,
            (
                action.get("inbox_item_id"),
                action["target_type"],
                action["target_id"],
                action["action_type"],
                action.get("actor_id"),
                json.dumps(action.get("payload") or {}, default=self._json_default),
                action.get("created_by") or action.get("actor_id"),
            ),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Failed to insert analyst action")
        return self._row_to_dict(
            row,
            [
                "id",
                "inbox_item_id",
                "target_type",
                "target_id",
                "action_type",
                "actor_id",
                "created_by",
                "payload",
                "created_at",
            ],
        )

    def get_actions_for_target(
        self,
        cur: Cursor,
        target_type: str,
        target_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = """
            SELECT
              aa.id,
              aa.inbox_item_id,
              aa.target_type,
              aa.target_id,
              aa.action_type,
              aa.actor_id,
              aa.created_by,
              aa.payload,
              aa.created_at
            FROM analyst_actions aa
            WHERE aa.target_type = %s
              AND aa.target_id = %s
            ORDER BY aa.created_at DESC
            LIMIT %s OFFSET %s
        """
        cur.execute(query, (target_type, target_id, int(limit), int(offset)))
        return self._rows_to_dicts(
            cur.fetchall(),
            [
                "id",
                "inbox_item_id",
                "target_type",
                "target_id",
                "action_type",
                "actor_id",
                "created_by",
                "payload",
                "created_at",
            ],
        )

    def list_actions(
        self,
        cur: Cursor,
        *,
        limit: int = 100,
        offset: int = 0,
        target_type: str | None = None,
        target_id: str | None = None,
        inbox_item_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        where_clauses: List[str] = []
        params: List[Any] = []
        if target_type is not None:
            where_clauses.append("aa.target_type = %s")
            params.append(target_type)
        if target_id is not None:
            where_clauses.append("aa.target_id = %s")
            params.append(target_id)
        if inbox_item_id is not None:
            where_clauses.append("aa.inbox_item_id = %s")
            params.append(inbox_item_id)
        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
        query = f"""
            SELECT
              aa.id,
              aa.inbox_item_id,
              aa.target_type,
              aa.target_id,
              aa.action_type,
              aa.actor_id,
              aa.created_by,
              aa.payload,
              aa.created_at,
              i.status AS item_status,
              i.batch_id,
              b.scope_type,
              b.scope_value,
              b.generated_for_date
            FROM analyst_actions aa
            LEFT JOIN inbox_items i ON i.id = aa.inbox_item_id
            LEFT JOIN inbox_batches b ON b.id = i.batch_id
            {where_sql}
            ORDER BY aa.created_at DESC
            LIMIT %s OFFSET %s
        """
        params.extend([int(limit), int(offset)])
        cur.execute(query, params)
        return self._rows_to_dicts(
            cur.fetchall(),
            [
                "id",
                "inbox_item_id",
                "target_type",
                "target_id",
                "action_type",
                "actor_id",
                "created_by",
                "payload",
                "created_at",
                "item_status",
                "batch_id",
                "scope_type",
                "scope_value",
                "generated_for_date",
            ],
        )

    # ===============================
    # CANDIDATE COLLECTION
    # ===============================

    def list_story_candidates(self, cur: Cursor, *, limit: int = 200) -> List[Dict[str, Any]]:
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
              su_latest.latest_update_date,
              su_latest.latest_update_importance,
              ap.id AS anchor_post_row_id,
              ap.url AS anchor_post_url,
              ap.title AS anchor_post_title,
              ap.published_at AS anchor_post_published_at,
              ap.source_id AS anchor_source_id,
              asrc.platform AS anchor_source_platform,
              asrc.handle_or_url AS anchor_source_handle_or_url,
              COALESCE(asrc.settings->>'display_name', asrc.handle_or_url) AS anchor_source_display_name,
              CASE
                WHEN COALESCE((asrc.settings->>'priority') ~ '^[0-9]+$', FALSE)
                THEN (asrc.settings->>'priority')::int
                ELSE 999
              END AS anchor_source_priority,
              COALESCE(asrc.enabled, TRUE) AS anchor_source_enabled
            FROM stories s
            LEFT JOIN LATERAL (
              SELECT COUNT(*)::int AS post_count
              FROM story_posts sp
              WHERE sp.story_id = s.id
            ) sp_counts ON TRUE
            LEFT JOIN LATERAL (
              SELECT COUNT(*)::int AS update_count
              FROM story_updates su
              WHERE su.story_id = s.id
            ) su_counts ON TRUE
            LEFT JOIN LATERAL (
              SELECT
                su.update_date AS latest_update_date,
                su.importance_score AS latest_update_importance
              FROM story_updates su
              WHERE su.story_id = s.id
              ORDER BY su.update_date DESC, su.importance_score DESC, su.created_at DESC
              LIMIT 1
            ) su_latest ON TRUE
            LEFT JOIN posts ap ON ap.id = s.anchor_post_id
            LEFT JOIN sources asrc ON asrc.id = ap.source_id
            WHERE s.status = 'active'
              AND (asrc.id IS NULL OR asrc.enabled = TRUE)
            ORDER BY COALESCE(s.last_seen_at, su_latest.latest_update_date, s.first_seen_at, s.created_at) DESC, s.created_at DESC
            LIMIT %s
        """
        cur.execute(query, (int(limit),))
        return self._rows_to_dicts(
            cur.fetchall(),
            [
                "id",
                "canonical_title",
                "canonical_summary",
                "story_kind",
                "status",
                "anchor_post_id",
                "anchor_confidence",
                "first_seen_at",
                "last_seen_at",
                "created_by_method",
                "resolution_version",
                "metadata",
                "created_at",
                "updated_at",
                "post_count",
                "update_count",
                "latest_update_date",
                "latest_update_importance",
                "anchor_post_row_id",
                "anchor_post_url",
                "anchor_post_title",
                "anchor_post_published_at",
                "anchor_source_id",
                "anchor_source_platform",
                "anchor_source_handle_or_url",
                "anchor_source_display_name",
                "anchor_source_priority",
                "anchor_source_enabled",
            ],
        )

    def list_post_candidates(
        self,
        cur: Cursor,
        *,
        since: datetime,
        limit: int = 250,
    ) -> List[Dict[str, Any]]:
        duplicate_types = ", ".join(f"'{value}'" for value in self.DUPLICATE_RELATION_TYPES)
        query = f"""
            SELECT
              p.id,
              p.title,
              p.content,
              p.published_at,
              p.fetched_at,
              p.source_id,
              p.metadata,
              p.categories,
              p.language_code,
              p.language_confidence,
              p.normalized_url,
              p.canonical_url,
              p.url_host,
              p.title_hash,
              p.content_hash,
              p.normalization_version,
              p.created_at,
              p.updated_at,
              s.platform,
              s.handle_or_url,
              COALESCE(s.settings->>'display_name', s.handle_or_url) AS source_display_name,
              CASE
                WHEN COALESCE((s.settings->>'priority') ~ '^[0-9]+$', FALSE)
                THEN (s.settings->>'priority')::int
                ELSE 999
              END AS source_priority,
              s.enabled AS source_enabled,
              COALESCE(art.artifact_count, 0) AS artifact_count,
              COALESCE(rel.relation_count, 0) AS relation_count,
              COALESCE(rel.duplicate_relation_count, 0) AS duplicate_relation_count,
              COALESCE(story_links.story_link_count, 0) AS story_link_count
            FROM posts p
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN LATERAL (
              SELECT COUNT(*)::int AS artifact_count
              FROM post_artifacts pa
              WHERE pa.post_id = p.id
            ) art ON TRUE
            LEFT JOIN LATERAL (
              SELECT
                COUNT(*)::int AS relation_count,
                COUNT(*) FILTER (WHERE relation_type IN ({duplicate_types}))::int AS duplicate_relation_count
              FROM (
                SELECT relation_type
                FROM post_relations
                WHERE from_post_id = p.id
                UNION ALL
                SELECT relation_type
                FROM post_relations
                WHERE to_post_id = p.id
              ) rels
            ) rel ON TRUE
            LEFT JOIN LATERAL (
              SELECT COUNT(*)::int AS story_link_count
              FROM story_posts sp
              WHERE sp.post_id = p.id
            ) story_links ON TRUE
            WHERE COALESCE(p.published_at, p.fetched_at) >= %s
              AND s.enabled = TRUE
            ORDER BY COALESCE(p.published_at, p.fetched_at) DESC, p.created_at DESC
            LIMIT %s
        """
        cur.execute(query, (since, int(limit)))
        return self._rows_to_dicts(
            cur.fetchall(),
            [
                "id",
                "title",
                "content",
                "published_at",
                "fetched_at",
                "source_id",
                "metadata",
                "categories",
                "language_code",
                "language_confidence",
                "normalized_url",
                "canonical_url",
                "url_host",
                "title_hash",
                "content_hash",
                "normalization_version",
                "created_at",
                "updated_at",
                "platform",
                "handle_or_url",
                "source_display_name",
                "source_priority",
                "source_enabled",
                "artifact_count",
                "relation_count",
                "duplicate_relation_count",
                "story_link_count",
            ],
        )

    # ===============================
    # INTERNAL HELPERS
    # ===============================

    def _item_query_base(self) -> str:
        return """
            SELECT
              i.id,
              i.batch_id,
              b.scope_type AS batch_scope_type,
              b.scope_value AS batch_scope_value,
              b.generated_for_date AS batch_generated_for_date,
              b.status AS batch_status,
              b.item_count AS batch_item_count,
              b.metadata AS batch_metadata,
              b.created_at AS batch_created_at,
              b.updated_at AS batch_updated_at,
              i.target_type,
              i.target_id,
              i.status,
              i.priority_score,
              i.novelty_score,
              i.evidence_score,
              i.duplication_penalty,
              i.source_priority_score,
              i.reason_summary,
              i.reasons,
              i.surfaced_at,
              i.acted_at,
              i.metadata,
              i.created_at AS item_created_at,
              i.updated_at AS item_updated_at,
              CASE
                WHEN i.target_type = 'post' THEN jsonb_build_object(
                  'id', p.id,
                  'title', p.title,
                  'url', p.url,
                  'published_at', p.published_at,
                  'fetched_at', p.fetched_at,
                  'source_id', p.source_id,
                  'source_display_name', COALESCE(ps.settings->>'display_name', ps.handle_or_url),
                  'platform', ps.platform,
                  'handle_or_url', ps.handle_or_url,
                  'normalized_url', p.normalized_url,
                  'canonical_url', p.canonical_url,
                  'url_host', p.url_host,
                  'language_code', p.language_code,
                  'language_confidence', p.language_confidence,
                  'artifact_count', COALESCE(art.artifact_count, 0),
                  'relation_count', COALESCE(rel.relation_count, 0),
                  'duplicate_relation_count', COALESCE(rel.duplicate_relation_count, 0),
                  'story_link_count', COALESCE(story_links.story_link_count, 0)
                )
                WHEN i.target_type = 'story' THEN jsonb_build_object(
                  'id', s.id,
                  'canonical_title', s.canonical_title,
                  'canonical_summary', s.canonical_summary,
                  'story_kind', s.story_kind,
                  'status', s.status,
                  'anchor_confidence', s.anchor_confidence,
                  'first_seen_at', s.first_seen_at,
                  'last_seen_at', s.last_seen_at,
                  'post_count', COALESCE(sp_counts.post_count, 0),
                  'update_count', COALESCE(su_counts.update_count, 0),
                  'latest_update_date', su_latest.latest_update_date,
                  'latest_update_importance', su_latest.latest_update_importance,
                  'anchor_post', CASE
                    WHEN ap.id IS NULL THEN NULL
                    ELSE jsonb_build_object(
                      'id', ap.id,
                      'title', ap.title,
                      'url', ap.url,
                      'published_at', ap.published_at,
                      'source_id', ap.source_id,
                      'source_display_name', COALESCE(asrc.settings->>'display_name', asrc.handle_or_url),
                      'platform', asrc.platform,
                      'handle_or_url', asrc.handle_or_url
                    )
                  END
                )
                ELSE NULL
              END AS target_preview
            FROM inbox_items i
            JOIN inbox_batches b ON b.id = i.batch_id
            LEFT JOIN posts p ON i.target_type = 'post' AND p.id = i.target_id
            LEFT JOIN sources ps ON ps.id = p.source_id
            LEFT JOIN LATERAL (
              SELECT COUNT(*)::int AS artifact_count
              FROM post_artifacts pa
              WHERE pa.post_id = p.id
            ) art ON TRUE
            LEFT JOIN LATERAL (
              SELECT
                COUNT(*)::int AS relation_count,
                COUNT(*) FILTER (WHERE relation_type IN ('exact_duplicate', 'near_duplicate', 'syndicated_from', 'translation_of'))::int AS duplicate_relation_count
              FROM (
                SELECT relation_type
                FROM post_relations
                WHERE from_post_id = p.id
                UNION ALL
                SELECT relation_type
                FROM post_relations
                WHERE to_post_id = p.id
              ) rels
            ) rel ON TRUE
            LEFT JOIN LATERAL (
              SELECT COUNT(*)::int AS story_link_count
              FROM story_posts sp
              WHERE sp.post_id = p.id
            ) story_links ON TRUE
            LEFT JOIN stories s ON i.target_type = 'story' AND s.id = i.target_id
            LEFT JOIN LATERAL (
              SELECT COUNT(*)::int AS post_count
              FROM story_posts sp
              WHERE sp.story_id = s.id
            ) sp_counts ON TRUE
            LEFT JOIN LATERAL (
              SELECT COUNT(*)::int AS update_count
              FROM story_updates su
              WHERE su.story_id = s.id
            ) su_counts ON TRUE
            LEFT JOIN LATERAL (
              SELECT
                su.update_date AS latest_update_date,
                su.importance_score AS latest_update_importance
              FROM story_updates su
              WHERE su.story_id = s.id
              ORDER BY su.update_date DESC, su.importance_score DESC, su.created_at DESC
              LIMIT 1
            ) su_latest ON TRUE
            LEFT JOIN posts ap ON ap.id = s.anchor_post_id
            LEFT JOIN sources asrc ON asrc.id = ap.source_id
        """

    def _rows_to_dicts(self, rows: List[tuple[Any, ...]], columns: List[str]) -> List[Dict[str, Any]]:
        return [self._row_to_dict(row, columns) for row in rows]

    def _row_to_dict(self, row: tuple[Any, ...], columns: List[str]) -> Dict[str, Any]:
        return {column: value for column, value in zip(columns, row)}

    def _json_default(self, value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value)} is not JSON serializable")
