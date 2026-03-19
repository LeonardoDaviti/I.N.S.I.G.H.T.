"""
Post-level intelligence workspace: detail retrieval, notes, summaries, and chat.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.processors.ai.gemini_processor import GeminiProcessor
from insight_core.services.posts_service import PostsService


class PostDetailService:
    """Serve rich detail views for a single post."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("post_detail_service")
        self.processor = GeminiProcessor()
        self.posts_service = PostsService(db_url)

    def get_post_by_id(self, post_id: str) -> Optional[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
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
                      p.created_at,
                      p.updated_at,
                      s.platform,
                      s.handle_or_url,
                      s.settings,
                      COALESCE(
                        (
                          SELECT json_agg(
                            json_build_object(
                              'id', t.id,
                              'title', t.title,
                              'date', t.date
                            )
                            ORDER BY t.date DESC, t.created_at DESC
                          )
                          FROM topic_posts tp
                          JOIN topics t ON t.id = tp.topic_id
                          WHERE tp.post_id = p.id
                        ),
                        '[]'::json
                      ) AS topics
                    FROM posts p
                    JOIN sources s ON s.id = p.source_id
                    WHERE p.id = %s
                    """,
                    (post_id,),
                )
                row = cur.fetchone()

        if not row:
            return None

        source_settings = row[16] or {}
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
            "created_at": row[12].isoformat() if row[12] else None,
            "updated_at": row[13].isoformat() if row[13] else None,
            "platform": row[14],
            "source": row[15],
            "source_display_name": source_settings.get("display_name") or row[15],
            "topics": row[17] or [],
        }

    def get_notes(self, post_id: str) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT notes_markdown, updated_at FROM post_notes WHERE post_id = %s",
                    (post_id,),
                )
                row = cur.fetchone()

        return {
            "post_id": post_id,
            "notes_markdown": row[0] if row else "",
            "updated_at": row[1].isoformat() if row and row[1] else None,
        }

    def save_notes(self, post_id: str, notes_markdown: str) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO post_notes (post_id, notes_markdown, updated_at)
                    VALUES (%s, %s, now())
                    ON CONFLICT (post_id) DO UPDATE SET
                      notes_markdown = EXCLUDED.notes_markdown,
                      updated_at = now()
                    RETURNING updated_at
                    """,
                    (post_id, notes_markdown),
                )
                updated_at = cur.fetchone()[0]
            conn.commit()

        return {
            "post_id": post_id,
            "notes_markdown": notes_markdown,
            "updated_at": updated_at.isoformat(),
        }

    def get_or_generate_summary(self, post_id: str, *, refresh: bool = False) -> Dict[str, Any]:
        post = self.get_post_by_id(post_id)
        if not post:
            raise ValueError(f"Post {post_id} not found")

        current_categories = post.get("categories") or []

        if not refresh and current_categories:
            cached = self._get_cached_summary(post_id)
            if cached:
                return {
                    "post_id": post_id,
                    "summary_markdown": cached["summary_markdown"],
                    "model": cached["summary_model"],
                    "updated_at": cached["updated_at"],
                    "cached": True,
                    "categories": current_categories,
                }

        summary_markdown, model, generated_tags = self._generate_summary(post)
        final_categories = current_categories or generated_tags
        if generated_tags and not current_categories:
            try:
                self.posts_service.update_post_categories(post_id, generated_tags)
                final_categories = generated_tags
            except Exception as exc:
                self.logger.warning("Failed to persist generated tags for %s: %s", post_id, exc)
        cached = self._save_summary_cache(post_id, summary_markdown, model)
        return {
            "post_id": post_id,
            "summary_markdown": summary_markdown,
            "model": cached["summary_model"],
            "updated_at": cached["updated_at"],
            "cached": False,
            "categories": final_categories,
        }

    def chat_about_post(self, post_id: str, question: str) -> Dict[str, Any]:
        post = self.get_post_by_id(post_id)
        if not post:
            raise ValueError(f"Post {post_id} not found")

        if self.processor.setup_processor():
            answer = self.processor.ask_single_post(post, question)
            if answer.get("success"):
                return {
                    "success": True,
                    "post_id": post_id,
                    "answer": answer["answer"],
                    "source": "gemini",
                }

        return {
            "success": True,
            "post_id": post_id,
            "answer": self._fallback_answer(post, question),
            "source": "fallback",
        }

    def _get_cached_summary(self, post_id: str) -> Optional[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT summary_markdown, summary_model, updated_at FROM post_ai_cache WHERE post_id = %s",
                    (post_id,),
                )
                row = cur.fetchone()

        if not row:
            return None
        return {
            "summary_markdown": row[0],
            "summary_model": row[1],
            "updated_at": row[2].isoformat() if row[2] else None,
        }

    def _save_summary_cache(self, post_id: str, summary_markdown: str, model: str) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO post_ai_cache (post_id, summary_markdown, summary_model, updated_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (post_id) DO UPDATE SET
                      summary_markdown = EXCLUDED.summary_markdown,
                      summary_model = EXCLUDED.summary_model,
                      updated_at = now()
                    RETURNING updated_at
                    """,
                    (post_id, summary_markdown, model),
                )
                updated_at = cur.fetchone()[0]
            conn.commit()

        return {
            "summary_markdown": summary_markdown,
            "summary_model": model,
            "updated_at": updated_at.isoformat(),
        }

    def _generate_summary(self, post: Dict[str, Any]) -> tuple[str, str, List[str]]:
        if self.processor.setup_processor():
            result = self.processor.analyze_single_post(post)
            if result.get("success"):
                tags = self._normalize_tags(result.get("tags"))
                summary = str(result.get("summary") or "").strip() or self._fallback_summary(post, tags=tags)
                model = str(result.get("model") or getattr(self.processor, "model_name", "gemini"))
                return summary, model, tags

        fallback_tags = self._fallback_tags(post)
        return self._fallback_summary(post, tags=fallback_tags), "fallback", fallback_tags

    def _fallback_summary(self, post: Dict[str, Any], tags: Optional[List[str]] = None) -> str:
        title = (post.get("title") or "Untitled post").strip()
        content = (post.get("content") or "").strip()
        excerpt = " ".join(content.split())[:900].strip()
        resolved_tags = ", ".join((tags or post.get("categories") or [])[:5]) or "No tags"
        return (
            f"## Executive Summary\n"
            f"**{title}** from **{post.get('source_display_name') or post.get('source')}**. "
            f"The post is tagged with: {resolved_tags}.\n\n"
            f"## Core Material\n"
            f"{excerpt or 'No textual content was stored for this post.'}"
        )

    def _normalize_tags(self, tags: Any) -> List[str]:
        if not isinstance(tags, list):
            return []
        normalized: List[str] = []
        for tag in tags:
            text = str(tag or "").strip().lower()
            if not text or text in normalized:
                continue
            normalized.append(text[:48])
        return normalized[:5]

    def _fallback_tags(self, post: Dict[str, Any]) -> List[str]:
        if post.get("categories"):
            return list(post["categories"])[:5]

        candidates = []
        source = str(post.get("platform") or "").strip().lower()
        if source:
            candidates.append(source)

        text = " ".join(
            part for part in [
                str(post.get("title") or ""),
                str(post.get("content") or ""),
            ] if part
        ).lower()

        keyword_map = {
            "ai": ["ai", "llm", "model", "models", "agent", "agents", "openai", "gemini", "claude"],
            "research": ["paper", "research", "study", "benchmark"],
            "video": ["video", "youtube", "watch"],
            "policy": ["policy", "law", "regulation", "government"],
            "coding": ["code", "coding", "programming", "dev", "developer"],
            "infrastructure": ["server", "infra", "deployment", "docker", "kubernetes"],
        }
        for tag, keywords in keyword_map.items():
            if any(keyword in text for keyword in keywords) and tag not in candidates:
                candidates.append(tag)
        return candidates[:5]

    def _fallback_answer(self, post: Dict[str, Any], question: str) -> str:
        del question
        excerpt = " ".join((post.get("content") or "").split())[:1200].strip()
        if not excerpt:
            excerpt = "This post has very little stored text, so the answer space is limited."
        return (
            f"I do not have an AI model available right now, so this is a deterministic answer.\n\n"
            f"Source: {post.get('source_display_name') or post.get('source')}\n"
            f"Title: {post.get('title') or 'Untitled post'}\n\n"
            f"Known content:\n{excerpt}"
        )
