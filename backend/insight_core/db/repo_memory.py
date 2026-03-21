"""Repository for entity and event memory tables."""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import psycopg
from psycopg import Cursor


class MemoryRepository:
    """SQL access layer for entity memory tables."""

    def __init__(self, db_url: str):
        self.db_url = db_url

    def update_post_memory_fields(self, cur: Cursor, post_id: str, fields: Dict[str, Any]) -> bool:
        query = """
            UPDATE posts
            SET title_original = COALESCE(%s, title_original),
                body_original = COALESCE(%s, body_original),
                title_pivot = %s,
                summary_pivot = %s,
                title_pivot_version = %s,
                summary_pivot_version = %s,
                updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        cur.execute(
            query,
            (
                fields.get("title_original"),
                fields.get("body_original"),
                fields.get("title_pivot"),
                fields.get("summary_pivot"),
                fields.get("title_pivot_version"),
                fields.get("summary_pivot_version"),
                post_id,
            ),
        )
        return cur.fetchone() is not None

    def upsert_source_profile(self, cur: Cursor, source_id: str, profile: Dict[str, Any]) -> bool:
        query = """
            INSERT INTO source_profiles (
                source_id,
                language_code,
                publisher_type,
                country_code,
                is_primary_reporter,
                reliability_notes,
                updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (source_id) DO UPDATE SET
                language_code = COALESCE(EXCLUDED.language_code, source_profiles.language_code),
                publisher_type = COALESCE(EXCLUDED.publisher_type, source_profiles.publisher_type),
                country_code = COALESCE(EXCLUDED.country_code, source_profiles.country_code),
                is_primary_reporter = EXCLUDED.is_primary_reporter,
                reliability_notes = COALESCE(EXCLUDED.reliability_notes, source_profiles.reliability_notes),
                updated_at = now()
            RETURNING source_id
        """
        cur.execute(
            query,
            (
                source_id,
                profile.get("language_code"),
                profile.get("publisher_type"),
                profile.get("country_code"),
                bool(profile.get("is_primary_reporter", False)),
                profile.get("reliability_notes"),
            ),
        )
        return cur.fetchone() is not None

    def insert_entity_mention(self, cur: Cursor, mention: Dict[str, Any]) -> str:
        query = """
            INSERT INTO entity_mentions (
                post_id,
                mention_text,
                normalized_mention,
                language_code,
                entity_type_predicted,
                role,
                char_start,
                char_end,
                extractor_confidence,
                extractor_name,
                extractor_version,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (post_id, mention_text, normalized_mention, entity_type_predicted, role, char_start, char_end) DO UPDATE SET
                language_code = COALESCE(EXCLUDED.language_code, entity_mentions.language_code),
                extractor_confidence = GREATEST(entity_mentions.extractor_confidence, EXCLUDED.extractor_confidence),
                extractor_name = EXCLUDED.extractor_name,
                extractor_version = EXCLUDED.extractor_version,
                metadata = entity_mentions.metadata || EXCLUDED.metadata
            RETURNING id
        """
        cur.execute(
            query,
            (
                mention["post_id"],
                mention["mention_text"],
                mention["normalized_mention"],
                mention.get("language_code"),
                mention["entity_type_predicted"],
                mention.get("role"),
                mention.get("char_start"),
                mention.get("char_end"),
                float(mention.get("extractor_confidence", 0.0)),
                mention.get("extractor_name"),
                mention.get("extractor_version"),
                json.dumps(mention.get("metadata") or {}, default=self._json_default),
            ),
        )
        return str(cur.fetchone()[0])

    def get_exact_entity_candidates(self, cur: Cursor, entity_type: str, normalized_alias: str) -> List[Dict[str, Any]]:
        query = """
            SELECT
                e.id,
                e.entity_type,
                e.canonical_name,
                e.canonical_name_pivot,
                e.normalized_name,
                e.description,
                e.status,
                e.review_state,
                e.first_seen_at,
                e.last_seen_at,
                ea.alias,
                ea.normalized_alias,
                ea.alias_type,
                ea.language_code,
                ea.script
            FROM entity_aliases ea
            JOIN entities e ON e.id = ea.entity_id
            WHERE e.entity_type = %s
              AND ea.normalized_alias = %s
              AND e.status = 'active'
            ORDER BY
                CASE e.review_state
                    WHEN 'active' THEN 0
                    WHEN 'provisional' THEN 1
                    ELSE 2
                END,
                COALESCE(e.last_seen_at, e.first_seen_at) DESC,
                e.created_at ASC
        """
        cur.execute(query, (entity_type, normalized_alias))
        rows = cur.fetchall()
        return [self._entity_row_to_dict(row) for row in rows]

    def insert_entity(self, cur: Cursor, entity: Dict[str, Any]) -> str:
        query = """
            INSERT INTO entities (
                entity_type,
                canonical_name,
                canonical_name_pivot,
                normalized_name,
                description,
                status,
                review_state,
                first_seen_at,
                last_seen_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """
        cur.execute(
            query,
            (
                entity["entity_type"],
                entity["canonical_name"],
                entity.get("canonical_name_pivot"),
                entity["normalized_name"],
                entity.get("description"),
                entity.get("status", "active"),
                entity.get("review_state", "provisional"),
                entity.get("first_seen_at"),
                entity.get("last_seen_at"),
            ),
        )
        return str(cur.fetchone()[0])

    def touch_entity(self, cur: Cursor, entity_id: str, *, seen_at: datetime | None = None) -> bool:
        query = """
            UPDATE entities
            SET last_seen_at = COALESCE(GREATEST(last_seen_at, %s), %s),
                updated_at = now()
            WHERE id = %s
            RETURNING id
        """
        cur.execute(query, (seen_at, seen_at, entity_id))
        return cur.fetchone() is not None

    def upsert_entity_alias(self, cur: Cursor, alias: Dict[str, Any]) -> bool:
        query = """
            INSERT INTO entity_aliases (
                entity_id,
                alias,
                normalized_alias,
                language_code,
                script,
                alias_type,
                transliteration,
                source_hint
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (entity_id, normalized_alias) DO UPDATE SET
                alias = COALESCE(EXCLUDED.alias, entity_aliases.alias),
                language_code = COALESCE(EXCLUDED.language_code, entity_aliases.language_code),
                script = COALESCE(EXCLUDED.script, entity_aliases.script),
                alias_type = COALESCE(EXCLUDED.alias_type, entity_aliases.alias_type),
                transliteration = COALESCE(EXCLUDED.transliteration, entity_aliases.transliteration),
                source_hint = COALESCE(EXCLUDED.source_hint, entity_aliases.source_hint)
            RETURNING id
        """
        cur.execute(
            query,
            (
                alias["entity_id"],
                alias["alias"],
                alias["normalized_alias"],
                alias.get("language_code"),
                alias.get("script"),
                alias.get("alias_type", "extracted"),
                alias.get("transliteration"),
                alias.get("source_hint"),
            ),
        )
        return cur.fetchone() is not None

    def upsert_mention_candidate(self, cur: Cursor, candidate: Dict[str, Any]) -> bool:
        query = """
            INSERT INTO mention_entity_candidates (
                mention_id,
                entity_id,
                candidate_method,
                score,
                selected,
                resolver_version
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (mention_id, entity_id, candidate_method) DO UPDATE SET
                score = GREATEST(mention_entity_candidates.score, EXCLUDED.score),
                selected = mention_entity_candidates.selected OR EXCLUDED.selected,
                resolver_version = EXCLUDED.resolver_version
            RETURNING mention_id
        """
        cur.execute(
            query,
            (
                candidate["mention_id"],
                candidate["entity_id"],
                candidate["candidate_method"],
                float(candidate.get("score", 0.0)),
                bool(candidate.get("selected", False)),
                candidate["resolver_version"],
            ),
        )
        return cur.fetchone() is not None

    def upsert_post_entity(self, cur: Cursor, post_entity: Dict[str, Any]) -> bool:
        query = """
            INSERT INTO post_entities (
                post_id,
                entity_id,
                mention_id,
                resolution_status,
                confidence,
                role,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (post_id, entity_id, mention_id) DO UPDATE SET
                resolution_status = EXCLUDED.resolution_status,
                confidence = GREATEST(post_entities.confidence, EXCLUDED.confidence),
                role = COALESCE(EXCLUDED.role, post_entities.role),
                metadata = post_entities.metadata || EXCLUDED.metadata
            RETURNING post_id
        """
        cur.execute(
            query,
            (
                post_entity["post_id"],
                post_entity["entity_id"],
                post_entity["mention_id"],
                post_entity["resolution_status"],
                float(post_entity.get("confidence", 0.0)),
                post_entity.get("role"),
                json.dumps(post_entity.get("metadata") or {}, default=self._json_default),
            ),
        )
        return cur.fetchone() is not None

    def get_post_source_profile(self, cur: Cursor, source_id: str) -> Dict[str, Any]:
        cur.execute(
            """
            SELECT
                sp.source_id,
                sp.language_code,
                sp.publisher_type,
                sp.country_code,
                sp.is_primary_reporter,
                sp.reliability_notes,
                sp.created_at,
                sp.updated_at
            FROM source_profiles sp
            WHERE sp.source_id = %s
            """,
            (source_id,),
        )
        row = cur.fetchone()
        if not row:
            return {}

        return {
            "source_id": str(row[0]),
            "language_code": row[1],
            "publisher_type": row[2],
            "country_code": row[3],
            "is_primary_reporter": bool(row[4]),
            "reliability_notes": row[5],
            "created_at": row[6].isoformat() if row[6] else None,
            "updated_at": row[7].isoformat() if row[7] else None,
        }

    def get_post_mentions(self, cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        cur.execute(
            """
            SELECT
                em.id,
                em.post_id,
                em.mention_text,
                em.normalized_mention,
                em.language_code,
                em.entity_type_predicted,
                em.role,
                em.char_start,
                em.char_end,
                em.extractor_confidence,
                em.extractor_name,
                em.extractor_version,
                em.metadata,
                em.created_at
            FROM entity_mentions em
            WHERE em.post_id = %s
            ORDER BY em.created_at ASC, em.char_start ASC NULLS LAST
            """,
            (post_id,),
        )
        rows = cur.fetchall()
        mentions: List[Dict[str, Any]] = []
        for row in rows:
            mentions.append(
                {
                    "id": str(row[0]),
                    "post_id": str(row[1]),
                    "mention_text": row[2],
                    "normalized_mention": row[3],
                    "language_code": row[4],
                    "entity_type_predicted": row[5],
                    "role": row[6],
                    "char_start": row[7],
                    "char_end": row[8],
                    "extractor_confidence": float(row[9]) if row[9] is not None else 0.0,
                    "extractor_name": row[10],
                    "extractor_version": row[11],
                    "metadata": row[12] or {},
                    "created_at": row[13].isoformat() if row[13] else None,
                }
            )
        return mentions

    def get_post_entities(self, cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        cur.execute(
            """
            SELECT
                pe.post_id,
                pe.entity_id,
                pe.mention_id,
                pe.resolution_status,
                pe.confidence,
                pe.role,
                pe.metadata,
                pe.created_at,
                e.entity_type,
                e.canonical_name,
                e.canonical_name_pivot,
                e.normalized_name,
                e.description,
                e.status,
                e.review_state,
                e.first_seen_at,
                e.last_seen_at,
                em.mention_text,
                em.normalized_mention,
                em.entity_type_predicted
            FROM post_entities pe
            JOIN entities e ON e.id = pe.entity_id
            JOIN entity_mentions em ON em.id = pe.mention_id
            WHERE pe.post_id = %s
            ORDER BY pe.created_at ASC
            """,
            (post_id,),
        )
        rows = cur.fetchall()
        entities: List[Dict[str, Any]] = []
        for row in rows:
            entities.append(
                {
                    "post_id": str(row[0]),
                    "entity_id": str(row[1]),
                    "mention_id": str(row[2]),
                    "resolution_status": row[3],
                    "confidence": float(row[4]) if row[4] is not None else 0.0,
                    "role": row[5],
                    "metadata": row[6] or {},
                    "created_at": row[7].isoformat() if row[7] else None,
                    "entity": {
                        "id": str(row[1]),
                        "entity_type": row[8],
                        "canonical_name": row[9],
                        "canonical_name_pivot": row[10],
                        "normalized_name": row[11],
                        "description": row[12],
                        "status": row[13],
                        "review_state": row[14],
                        "first_seen_at": row[15].isoformat() if row[15] else None,
                        "last_seen_at": row[16].isoformat() if row[16] else None,
                    },
                    "mention": {
                        "id": str(row[2]),
                        "mention_text": row[17],
                        "normalized_mention": row[18],
                        "entity_type_predicted": row[19],
                    },
                }
            )
        return entities

    def get_post_mention_candidates(self, cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        cur.execute(
            """
            SELECT
                mec.mention_id,
                mec.entity_id,
                mec.candidate_method,
                mec.score,
                mec.selected,
                mec.resolver_version,
                mec.created_at,
                em.mention_text,
                em.normalized_mention,
                e.entity_type,
                e.canonical_name,
                e.normalized_name
            FROM mention_entity_candidates mec
            JOIN entity_mentions em ON em.id = mec.mention_id
            JOIN entities e ON e.id = mec.entity_id
            WHERE em.post_id = %s
            ORDER BY mec.created_at ASC
            """,
            (post_id,),
        )
        rows = cur.fetchall()
        candidates: List[Dict[str, Any]] = []
        for row in rows:
            candidates.append(
                {
                    "mention_id": str(row[0]),
                    "entity_id": str(row[1]),
                    "candidate_method": row[2],
                    "score": float(row[3]) if row[3] is not None else 0.0,
                    "selected": bool(row[4]),
                    "resolver_version": row[5],
                    "created_at": row[6].isoformat() if row[6] else None,
                    "mention_text": row[7],
                    "normalized_mention": row[8],
                    "entity_type": row[9],
                    "canonical_name": row[10],
                    "normalized_name": row[11],
                }
            )
        return candidates

    def get_post_memory_debug(self, cur: Cursor, post_id: str) -> Dict[str, Any]:
        post = self._get_post(cur, post_id)
        if not post:
            return {}

        source_profile = self.get_post_source_profile(cur, post["source_id"])
        mentions = self.get_post_mentions(cur, post_id)
        entities = self.get_post_entities(cur, post_id)
        candidates = self.get_post_mention_candidates(cur, post_id)

        candidates_by_mention: Dict[str, List[Dict[str, Any]]] = {}
        for candidate in candidates:
            candidates_by_mention.setdefault(candidate["mention_id"], []).append(candidate)

        for mention in mentions:
            mention["candidates"] = candidates_by_mention.get(mention["id"], [])

        return {
            "post": post,
            "source_profile": source_profile,
            "mentions": mentions,
            "entities": entities,
            "candidates": candidates,
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

    def _entity_row_to_dict(self, row) -> Dict[str, Any]:
        return {
            "id": str(row[0]),
            "entity_type": row[1],
            "canonical_name": row[2],
            "canonical_name_pivot": row[3],
            "normalized_name": row[4],
            "description": row[5],
            "status": row[6],
            "review_state": row[7],
            "first_seen_at": row[8].isoformat() if row[8] else None,
            "last_seen_at": row[9].isoformat() if row[9] else None,
            "alias": row[10],
            "normalized_alias": row[11],
            "alias_type": row[12],
            "language_code": row[13],
            "script": row[14],
        }

    def _json_default(self, value: Any) -> str:
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        raise TypeError(f"Object of type {type(value)} is not JSON serializable")
