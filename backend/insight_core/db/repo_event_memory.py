"""Repository for typed event memory tables."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from psycopg import Cursor


class EventMemoryRepository:
    """SQL access layer for event memory tables."""

    def __init__(self, db_url: str):
        self.db_url = db_url

    def upsert_event(self, cur: Cursor, event: Dict[str, Any]) -> str:
        normalized_key = event.get("normalized_event_key") or None
        if normalized_key:
            cur.execute(
                "SELECT id FROM events WHERE normalized_event_key = %s LIMIT 1",
                (normalized_key,),
            )
            row = cur.fetchone()
            if row:
                event_id = str(row[0])
                cur.execute(
                    """
                    UPDATE events
                    SET event_type = COALESCE(%s, event_type),
                        title = COALESCE(%s, title),
                        status = COALESCE(%s, status),
                        confidence = GREATEST(confidence, %s),
                        occurred_at = COALESCE(occurred_at, %s),
                        first_seen_at = COALESCE(first_seen_at, %s),
                        last_seen_at = GREATEST(COALESCE(last_seen_at, %s), %s),
                        updated_at = now()
                    WHERE id = %s
                    RETURNING id
                    """,
                    (
                        event.get("event_type"),
                        event.get("title"),
                        event.get("status", "observed"),
                        float(event.get("confidence", 0.0)),
                        event.get("occurred_at"),
                        event.get("first_seen_at"),
                        event.get("last_seen_at"),
                        event.get("last_seen_at"),
                        event_id,
                    ),
                )
                return str(cur.fetchone()[0])

        query = """
            INSERT INTO events (
                event_type,
                title,
                normalized_event_key,
                status,
                confidence,
                occurred_at,
                first_seen_at,
                last_seen_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        cur.execute(
            query,
            (
                event["event_type"],
                event["title"],
                normalized_key,
                event.get("status", "observed"),
                float(event.get("confidence", 0.0)),
                event.get("occurred_at"),
                event.get("first_seen_at"),
                event.get("last_seen_at"),
            ),
        )
        return str(cur.fetchone()[0])

    def upsert_event_evidence(self, cur: Cursor, evidence: Dict[str, Any]) -> bool:
        query = """
            INSERT INTO event_evidence (
                event_id,
                post_id,
                stance,
                evidence_snippet,
                confidence,
                extractor_version
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id, post_id) DO UPDATE SET
                stance = EXCLUDED.stance,
                evidence_snippet = COALESCE(EXCLUDED.evidence_snippet, event_evidence.evidence_snippet),
                confidence = GREATEST(event_evidence.confidence, EXCLUDED.confidence),
                extractor_version = EXCLUDED.extractor_version
            RETURNING event_id
        """
        cur.execute(
            query,
            (
                evidence["event_id"],
                evidence["post_id"],
                evidence.get("stance", "mentions"),
                evidence.get("evidence_snippet"),
                float(evidence.get("confidence", 0.0)),
                evidence["extractor_version"],
            ),
        )
        return cur.fetchone() is not None

    def upsert_event_entity(self, cur: Cursor, event_entity: Dict[str, Any]) -> bool:
        query = """
            INSERT INTO event_entities (
                event_id,
                entity_id,
                role
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (event_id, entity_id, role) DO NOTHING
            RETURNING event_id
        """
        cur.execute(
            query,
            (
                event_entity["event_id"],
                event_entity["entity_id"],
                event_entity["role"],
            ),
        )
        return cur.fetchone() is not None

    def get_post_event_evidence(self, cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        cur.execute(
            """
            SELECT
                e.id,
                e.event_type,
                e.title,
                e.normalized_event_key,
                e.status,
                e.confidence AS event_confidence,
                e.occurred_at,
                e.first_seen_at,
                e.last_seen_at,
                ee.stance,
                ee.evidence_snippet,
                ee.confidence AS evidence_confidence,
                ee.extractor_version,
                ee.created_at
            FROM event_evidence ee
            JOIN events e ON e.id = ee.event_id
            WHERE ee.post_id = %s
            ORDER BY e.created_at ASC, ee.created_at ASC
            """,
            (post_id,),
        )
        rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "event_id": str(row[0]),
                    "event": {
                        "id": str(row[0]),
                        "event_type": row[1],
                        "title": row[2],
                        "normalized_event_key": row[3],
                        "status": row[4],
                        "confidence": float(row[5]) if row[5] is not None else 0.0,
                        "occurred_at": row[6].isoformat() if row[6] else None,
                        "first_seen_at": row[7].isoformat() if row[7] else None,
                        "last_seen_at": row[8].isoformat() if row[8] else None,
                    },
                    "stance": row[9],
                    "evidence_snippet": row[10],
                    "confidence": float(row[11]) if row[11] is not None else 0.0,
                    "extractor_version": row[12],
                    "created_at": row[13].isoformat() if row[13] else None,
                }
            )
        return results

    def get_post_event_entities(self, cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        cur.execute(
            """
            SELECT
                ee.event_id,
                ee.entity_id,
                ee.role,
                ee.created_at,
                e.event_type,
                e.title,
                e.normalized_event_key,
                en.entity_type,
                en.canonical_name,
                en.normalized_name,
                en.review_state
            FROM event_entities ee
            JOIN events e ON e.id = ee.event_id
            JOIN entities en ON en.id = ee.entity_id
            WHERE ee.event_id IN (
                SELECT DISTINCT event_id
                FROM event_evidence
                WHERE post_id = %s
            )
            ORDER BY ee.created_at ASC
            """,
            (post_id,),
        )
        rows = cur.fetchall()
        results: List[Dict[str, Any]] = []
        for row in rows:
            results.append(
                {
                    "event_id": str(row[0]),
                    "entity_id": str(row[1]),
                    "role": row[2],
                    "created_at": row[3].isoformat() if row[3] else None,
                    "event": {
                        "id": str(row[0]),
                        "event_type": row[4],
                        "title": row[5],
                        "normalized_event_key": row[6],
                    },
                    "entity": {
                        "id": str(row[1]),
                        "entity_type": row[7],
                        "canonical_name": row[8],
                        "normalized_name": row[9],
                        "review_state": row[10],
                    },
                }
            )
        return results

    def get_post_events_debug(self, cur: Cursor, post_id: str) -> Dict[str, Any]:
        post = self._get_post(cur, post_id)
        if not post:
            return {}

        evidence = self.get_post_event_evidence(cur, post_id)
        entities = self.get_post_event_entities(cur, post_id)

        evidence_by_event: Dict[str, List[Dict[str, Any]]] = {}
        for row in evidence:
            evidence_by_event.setdefault(row["event_id"], []).append(row)

        entities_by_event: Dict[str, List[Dict[str, Any]]] = {}
        for row in entities:
            entities_by_event.setdefault(row["event_id"], []).append(row)

        events: Dict[str, Dict[str, Any]] = {}
        for row in evidence:
            event = dict(row["event"])
            event["evidence"] = evidence_by_event.get(row["event_id"], [])
            event["entities"] = entities_by_event.get(row["event_id"], [])
            events[row["event_id"]] = event

        return {
            "post": post,
            "events": list(events.values()),
            "evidence": evidence,
            "entities": entities,
        }

    def _get_post(self, cur: Cursor, post_id: str) -> Dict[str, Any]:
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
                p.title_original,
                p.body_original,
                p.title_pivot,
                p.summary_pivot,
                p.title_pivot_version,
                p.summary_pivot_version,
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
            "title_original": row[22],
            "body_original": row[23],
            "title_pivot": row[24],
            "summary_pivot": row[25],
            "title_pivot_version": row[26],
            "summary_pivot_version": row[27],
            "platform": row[28],
            "source": row[29],
            "source_display_name": row[30],
        }

    def _json_default(self, value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value)} is not JSON serializable")
