"""
Post-level intelligence workspace: detail retrieval, notes, summaries, and chat.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.logs.core.logger_config import get_component_logger
from insight_core.processors.ai.gemini_processor import GeminiProcessor
from insight_core.services.explainability_service import ExplainabilityService
from insight_core.services.posts_service import PostsService
from insight_core.services.source_fetch_service import SourceFetchService


class PostDetailService:
    """Serve rich detail views for a single post."""

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.logger = get_component_logger("post_detail_service")
        self.processor = GeminiProcessor()
        self.posts_service = PostsService(db_url)
        self.source_fetch_service = SourceFetchService(db_url)
        self.explainability_service = ExplainabilityService(db_url)

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

        source_settings = row[32] or {}
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
            "created_at": row[28].isoformat() if row[28] else None,
            "updated_at": row[29].isoformat() if row[29] else None,
            "platform": row[30],
            "source": row[31],
            "source_display_name": source_settings.get("display_name") or row[31],
            "topics": row[33] or [],
        }

    def get_post_highlights(self, post_id: str) -> List[Dict[str, Any]]:
        return self.explainability_service.get_post_highlights(post_id)

    def get_post_reader_state(self, post_id: str) -> Dict[str, Any]:
        return self.explainability_service.get_post_reader_state(post_id)

    def get_post_summary_references(self, post_id: str) -> List[Dict[str, Any]]:
        references = self.explainability_service.get_artifact_references("post_summary", post_id)
        if references:
            return references

        post = self.get_post_by_id(post_id)
        if not post:
            return []

        highlights = self.get_post_highlights(post_id)
        if not highlights:
            return []

        return self._save_post_summary_references(post, highlights)

    def get_cached_summary(self, post_id: str) -> Optional[Dict[str, Any]]:
        return self._get_cached_summary(post_id)

    def record_post_open(self, post_id: str, *, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self.explainability_service.record_post_interaction(
            post_id,
            "opened",
            metadata or {},
        )

    def record_reading_session(
        self,
        post_id: str,
        *,
        duration_seconds: int,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            **(metadata or {}),
            "duration_seconds": max(0, int(duration_seconds)),
        }
        return self.explainability_service.record_post_interaction(
            post_id,
            "reading_session",
            payload,
        )

    def toggle_favorite(self, post_id: str, favorited: bool) -> Dict[str, Any]:
        interaction_type = "favorited" if favorited else "unfavorited"
        stored = self.explainability_service.record_post_interaction(post_id, interaction_type, {"favorited": favorited})
        state = self.get_post_reader_state(post_id)
        return {
            "post_id": post_id,
            "favorited": state.get("is_favorited", False),
            "interaction": stored,
            "reader_state": state,
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
                highlights = self.get_post_highlights(post_id)
                if not highlights:
                    highlights = self._generate_and_store_highlights(post, cached_summary_markdown=cached["summary_markdown"], force=False)
                summary_references = self._save_post_summary_references(post, highlights)
                return {
                    "post_id": post_id,
                    "summary_markdown": cached["summary_markdown"],
                    "model": cached["summary_model"],
                    "updated_at": cached["updated_at"],
                    "cached": True,
                    "categories": current_categories,
                    "estimated_tokens": self._count_tokens(cached["summary_markdown"]),
                    "one_sentence_takeaway": cached.get("one_sentence_takeaway"),
                    "highlights": highlights,
                    "references": summary_references,
                }

        summary_markdown, model, generated_tags, estimated_tokens = self._generate_summary(post)
        highlights = self._generate_and_store_highlights(post, cached_summary_markdown=summary_markdown, force=True)
        final_categories = current_categories or generated_tags
        if generated_tags and not current_categories:
            try:
                self.posts_service.update_post_categories(post_id, generated_tags)
                final_categories = generated_tags
            except Exception as exc:
                self.logger.warning("Failed to persist generated tags for %s: %s", post_id, exc)
        takeaway = self._takeaway_from_highlights(highlights) if highlights else None
        cached = self._save_summary_cache(post_id, summary_markdown, model, one_sentence_takeaway=takeaway)
        summary_references = self._save_post_summary_references(post, highlights)
        return {
            "post_id": post_id,
            "summary_markdown": summary_markdown,
            "model": cached["summary_model"],
            "updated_at": cached["updated_at"],
            "cached": False,
            "categories": final_categories,
            "estimated_tokens": estimated_tokens,
            "one_sentence_takeaway": takeaway,
            "highlights": highlights,
            "references": summary_references,
        }

    def chat_about_post(self, post_id: str, question: str) -> Dict[str, Any]:
        post = self.get_post_by_id(post_id)
        if not post:
            raise ValueError(f"Post {post_id} not found")

        notes = self.get_notes(post_id)
        cached_summary = self._get_cached_summary(post_id)
        highlights = self.get_post_highlights(post_id)
        reader_state = self.get_post_reader_state(post_id)
        post_context = {
            **post,
            "notes_markdown": notes.get("notes_markdown", ""),
            "cached_summary_markdown": (cached_summary or {}).get("summary_markdown", ""),
            "one_sentence_takeaway": (cached_summary or {}).get("one_sentence_takeaway", ""),
            "post_highlights": highlights,
            "reader_state": reader_state,
        }

        if self.processor.setup_processor():
            answer = self.processor.ask_single_post(post_context, question)
            if answer.get("success"):
                return {
                    "success": True,
                    "post_id": post_id,
                    "answer": answer["answer"],
                    "source": "gemini",
                    "estimated_tokens": answer.get("estimated_tokens"),
                    "context": self._build_context_stats(post_context),
                }

        return {
            "success": True,
            "post_id": post_id,
            "answer": self._fallback_answer(post, question),
            "source": "fallback",
            "estimated_tokens": self._count_tokens((post.get("content") or "")[:4000]),
            "context": self._build_context_stats(post_context),
        }

    def get_or_generate_highlights(self, post_id: str, *, refresh: bool = False) -> Dict[str, Any]:
        post = self.get_post_by_id(post_id)
        if not post:
            raise ValueError(f"Post {post_id} not found")

        existing = self.get_post_highlights(post_id)
        if existing and not refresh:
            cached_summary = self._get_cached_summary(post_id)
            return {
                "post_id": post_id,
                "highlights": existing,
                "one_sentence_takeaway": (cached_summary or {}).get("one_sentence_takeaway")
                or self._takeaway_from_highlights(existing),
                "cached": True,
                "model": (cached_summary or {}).get("summary_model"),
            }

        stored = self._generate_and_store_highlights(post, force=True)
        return {
            "post_id": post_id,
            "highlights": stored,
            "one_sentence_takeaway": self._takeaway_from_highlights(stored),
            "cached": False,
            "model": getattr(self.processor, "model_name", "gemini"),
        }

    async def fetch_reddit_comments(self, post_id: str, *, limit: int = 80, refresh: bool = False) -> Dict[str, Any]:
        post = self.get_post_by_id(post_id)
        if not post:
            raise ValueError(f"Post {post_id} not found")
        if post.get("platform") != "reddit":
            raise ValueError("Reddit comments are only available for reddit posts")

        metadata = dict(post.get("metadata") or {})
        discussion = dict(metadata.get("reddit_discussion") or {})
        cached_comments = discussion.get("comments") if isinstance(discussion.get("comments"), list) else []
        cached_limit = int(discussion.get("limit") or len(cached_comments) or 0)

        if not refresh and cached_comments and cached_limit >= limit:
            return {
                "post_id": post_id,
                "comments": cached_comments[:limit],
                "comment_count": min(len(cached_comments), limit),
                "cached": True,
                "fetched_at": discussion.get("fetched_at"),
            }

        comments = await self.source_fetch_service.fetch_reddit_comments_for_post(post["url"], limit=limit)
        updated_discussion = {
            **discussion,
            "comments": comments,
            "limit": limit,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata["reddit_discussion"] = updated_discussion
        self.posts_service.update_post_metadata(post_id, metadata)

        return {
            "post_id": post_id,
            "comments": comments,
            "comment_count": len(comments),
            "cached": False,
            "fetched_at": updated_discussion["fetched_at"],
        }

    async def get_or_generate_reddit_comments_briefing(
        self,
        post_id: str,
        *,
        limit: int = 80,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        post = self.get_post_by_id(post_id)
        if not post:
            raise ValueError(f"Post {post_id} not found")
        if post.get("platform") != "reddit":
            raise ValueError("Reddit comment briefing is only available for reddit posts")

        metadata = dict(post.get("metadata") or {})
        discussion = dict(metadata.get("reddit_discussion") or {})
        cached_briefing = discussion.get("briefing") if isinstance(discussion.get("briefing"), dict) else None
        cached_comments = discussion.get("comments") if isinstance(discussion.get("comments"), list) else []

        if not refresh and cached_briefing and cached_comments:
            return {
                "post_id": post_id,
                "summary_markdown": cached_briefing.get("summary_markdown", ""),
                "model": cached_briefing.get("model"),
                "signals": cached_briefing.get("signals") or [],
                "updated_at": cached_briefing.get("updated_at"),
                "comment_count": len(cached_comments),
                "cached": True,
                "estimated_tokens": cached_briefing.get("estimated_tokens", self.processor.count_tokens(cached_briefing.get("summary_markdown", ""))),
            }

        comments_payload = await self.fetch_reddit_comments(post_id, limit=limit, refresh=refresh)
        comments = comments_payload.get("comments") or []

        summary_markdown, model, signals, estimated_tokens = self._generate_reddit_comments_briefing(post, comments)
        updated_discussion = {
            **discussion,
            "comments": comments,
            "limit": limit,
            "fetched_at": comments_payload.get("fetched_at") or discussion.get("fetched_at"),
            "briefing": {
                "summary_markdown": summary_markdown,
                "model": model,
                "signals": signals,
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "comment_count": len(comments),
                "estimated_tokens": estimated_tokens,
            },
        }
        metadata["reddit_discussion"] = updated_discussion
        self.posts_service.update_post_metadata(post_id, metadata)

        return {
            "post_id": post_id,
            "summary_markdown": summary_markdown,
            "model": model,
            "signals": signals,
            "updated_at": updated_discussion["briefing"]["updated_at"],
            "comment_count": len(comments),
            "cached": False,
            "estimated_tokens": estimated_tokens,
        }

    def _get_cached_summary(self, post_id: str) -> Optional[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT summary_markdown, summary_model, one_sentence_takeaway, updated_at FROM post_ai_cache WHERE post_id = %s",
                    (post_id,),
                )
                row = cur.fetchone()

        if not row:
            return None
        return {
            "summary_markdown": row[0],
            "summary_model": row[1],
            "one_sentence_takeaway": row[2],
            "updated_at": row[3].isoformat() if row[3] else None,
        }

    def _save_summary_cache(
        self,
        post_id: str,
        summary_markdown: str,
        model: str,
        *,
        one_sentence_takeaway: str | None = None,
    ) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO post_ai_cache (post_id, summary_markdown, summary_model, one_sentence_takeaway, highlights_updated_at, updated_at)
                    VALUES (%s, %s, %s, %s, now(), now())
                    ON CONFLICT (post_id) DO UPDATE SET
                      summary_markdown = EXCLUDED.summary_markdown,
                      summary_model = EXCLUDED.summary_model,
                      one_sentence_takeaway = EXCLUDED.one_sentence_takeaway,
                      highlights_updated_at = EXCLUDED.highlights_updated_at,
                      updated_at = now()
                    RETURNING updated_at
                    """,
                    (post_id, summary_markdown, model, one_sentence_takeaway),
                )
                updated_at = cur.fetchone()[0]
            conn.commit()

        return {
            "summary_markdown": summary_markdown,
            "summary_model": model,
            "updated_at": updated_at.isoformat(),
            "one_sentence_takeaway": one_sentence_takeaway,
        }

    def _generate_and_store_highlights(
        self,
        post: Dict[str, Any],
        *,
        cached_summary_markdown: str | None = None,
        force: bool = False,
    ) -> List[Dict[str, Any]]:
        post_id = str(post["id"])
        existing = self.get_post_highlights(post_id)
        if existing and not force:
            return existing

        if cached_summary_markdown:
            post = {
                **post,
                "cached_summary_markdown": cached_summary_markdown,
            }

        if self.processor.setup_processor():
            try:
                result = self.processor.extract_post_highlights(post)
                if result.get("success"):
                    highlights = result.get("highlights") if isinstance(result.get("highlights"), list) else []
                    stored = self.explainability_service.save_post_highlights(
                        post_id,
                        highlights,
                        extractor_name="gemini",
                        extractor_version=str(result.get("model") or getattr(self.processor, "model_name", "gemini")),
                        language_code=post.get("language_code"),
                    )
                    return stored
            except Exception as exc:
                self.logger.warning("Highlight generation failed for %s: %s", post_id, exc)

        stored = self.explainability_service.save_post_highlights(
            post_id,
            self.processor._fallback_post_highlights(post),
            extractor_name="fallback",
            extractor_version="fallback",
            language_code=post.get("language_code"),
        )
        return stored

    def _save_post_summary_references(
        self,
        post: Dict[str, Any],
        highlights: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        post_id = str(post["id"])
        artifact_type = "post_summary"
        try:
            existing = self.explainability_service.get_artifact_references(artifact_type, post_id)
            if existing:
                return existing
        except Exception as exc:
            self.logger.warning("Failed to load summary references for %s: %s", post_id, exc)

        if not highlights:
            return []

        references: List[Dict[str, Any]] = []
        for index, highlight in enumerate(highlights[:3]):
            highlight_id = highlight.get("id")
            references.append(
                {
                    "artifact_type": artifact_type,
                    "artifact_id": post_id,
                    "post_id": post_id,
                    "highlight_id": highlight_id,
                    "reference_role": "primary" if index == 0 else "supporting",
                    "display_label": post.get("title") or post.get("source_display_name") or post.get("source") or "Post summary",
                    "order_index": index,
                }
            )

        try:
            self.explainability_service.save_artifact_references(artifact_type, post_id, references)
            return self.explainability_service.get_artifact_references(artifact_type, post_id)
        except Exception as exc:
            self.logger.warning("Failed to save summary references for %s: %s", post_id, exc)
            return []

    def _takeaway_from_highlights(self, highlights: List[Dict[str, Any]]) -> str | None:
        if not highlights:
            return None
        first = highlights[0]
        text = str(first.get("highlight_text") or first.get("text") or "").strip()
        if not text:
            return None
        return text if text.endswith((".", "!", "?")) else f"{text}."

    def _generate_reddit_comments_briefing(self, post: Dict[str, Any], comments: List[Dict[str, Any]]) -> tuple[str, str, List[str], int]:
        if self.processor.setup_processor():
            result = self.processor.summarize_reddit_comments(post, comments)
            if result.get("success"):
                summary = str(result.get("summary") or "").strip() or self._fallback_reddit_comments_briefing(post, comments)
                signals = self._normalize_tags(result.get("signals"))
                model = str(result.get("model") or getattr(self.processor, "model_name", "gemini"))
                return summary, model, signals, int(result.get("estimated_tokens") or self._count_tokens(summary))

        fallback = self._fallback_reddit_comments_briefing(post, comments)
        return fallback, "fallback", [], self._count_tokens(fallback)

    def _generate_summary(self, post: Dict[str, Any]) -> tuple[str, str, List[str], int]:
        if self.processor.setup_processor():
            result = self.processor.analyze_single_post(post)
            if result.get("success"):
                tags = self._normalize_tags(result.get("tags"))
                summary = str(result.get("summary") or "").strip() or self._fallback_summary(post, tags=tags)
                model = str(result.get("model") or getattr(self.processor, "model_name", "gemini"))
                return summary, model, tags, int(result.get("estimated_tokens") or self._count_tokens(summary))

        fallback_tags = self._fallback_tags(post)
        fallback_summary = self._fallback_summary(post, tags=fallback_tags)
        return fallback_summary, "fallback", fallback_tags, self._count_tokens(fallback_summary)

    def _build_context_stats(self, post: Dict[str, Any]) -> Dict[str, Any]:
        discussion = (post.get("metadata") or {}).get("reddit_discussion", {})
        comments = discussion.get("comments") if isinstance(discussion, dict) else []
        return {
            "content_chars": len(str(post.get("content") or "")),
            "notes_chars": len(str(post.get("notes_markdown") or "")),
            "summary_chars": len(str(post.get("cached_summary_markdown") or "")),
            "topics_loaded": len(post.get("topics") or []),
            "reddit_comments_loaded": len(comments or []),
            "highlights_loaded": len(post.get("post_highlights") or []),
            "reader_open_count": int((post.get("reader_state") or {}).get("open_count") or 0),
        }

    def _count_tokens(self, text: str) -> int:
        counter = getattr(self.processor, "count_tokens", None)
        if callable(counter):
            return int(counter(text))
        return max(1, len(str(text or "")) // 4)

    def _fallback_reddit_comments_briefing(self, post: Dict[str, Any], comments: List[Dict[str, Any]]) -> str:
        if not comments:
            return (
                "## Discussion Briefing\n"
                "No comments were fetched for this Reddit post yet."
            )

        ranked = sorted(
            comments,
            key=lambda comment: (int(comment.get("score") or 0), -int(comment.get("depth") or 0)),
            reverse=True,
        )
        highlights = ranked[:5]
        bullet_lines = []
        for comment in highlights:
            author = comment.get("author") or "unknown"
            score = comment.get("score") or 0
            body = " ".join(str(comment.get("body") or "").split())[:220].strip()
            bullet_lines.append(f"- **{author}** ({score}): {body}")

        return (
            f"## Discussion Briefing\n"
            f"Fetched **{len(comments)} comments** for **{post.get('title') or 'this post'}**.\n\n"
            f"## Strongest Signals\n"
            + "\n".join(bullet_lines)
        )

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
        discussion = (post.get("metadata") or {}).get("reddit_discussion", {})
        comments = discussion.get("comments") if isinstance(discussion, dict) else []
        comment_excerpt = ""
        if comments:
            preview = []
            for comment in comments[:3]:
                body = " ".join(str(comment.get("body") or "").split())[:180].strip()
                if not body:
                    continue
                preview.append(f"- {comment.get('author') or 'unknown'}: {body}")
            if preview:
                comment_excerpt = "\n\nFetched discussion:\n" + "\n".join(preview)
        return (
            f"I do not have an AI model available right now, so this is a deterministic answer.\n\n"
            f"Source: {post.get('source_display_name') or post.get('source')}\n"
            f"Title: {post.get('title') or 'Untitled post'}\n\n"
            f"Known content:\n{excerpt}"
            f"{comment_excerpt}"
        )
