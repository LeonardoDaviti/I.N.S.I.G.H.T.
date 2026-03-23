"""
Gemini processor for daily briefings and topic modeling.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional


DEFAULT_MODEL = "gemini-3.0-flash"
DEFAULT_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash",
]
VERTICAL_TRACK_KINDS = {"project_thread", "recurring_theme", "one_off_update"}
VERTICAL_GENERIC_LEADS = {
    "a",
    "an",
    "analysis",
    "another",
    "briefing",
    "daily",
    "day",
    "follow",
    "followup",
    "follow-up",
    "latest",
    "log",
    "memo",
    "more",
    "new",
    "note",
    "notes",
    "post",
    "progress",
    "recap",
    "report",
    "roundup",
    "summary",
    "thread",
    "today",
    "update",
    "updates",
    "weekly",
    "yesterday",
}
VERTICAL_GENERIC_SUFFIXES = {
    "analysis",
    "commentary",
    "day",
    "draft",
    "entry",
    "followup",
    "follow-up",
    "log",
    "memo",
    "note",
    "notes",
    "post",
    "progress",
    "project",
    "recap",
    "report",
    "roundup",
    "summary",
    "thread",
    "today",
    "update",
    "updates",
    "version",
}


def _status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    if value is None:
        match = re.match(r"\s*([0-9]{3})\b", str(exc))
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _looks_like_missing_model(exc: Exception) -> bool:
    code = _status_code(exc)
    text = str(exc).lower()
    if code == 404:
        return True
    if "model" in text and ("not found" in text or "is not found for api version" in text):
        return True
    if code == 400 and "model" in text and ("not found" in text or "unknown" in text or "invalid" in text):
        return True
    return False


def _retry_delay_from_error(exc: Exception) -> float | None:
    text = str(exc)
    match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    match = re.search(r"retryDelay['\"]?\s*:\s*['\"]([0-9]+)s", text, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    return None


def _looks_like_quota_exhausted(exc: Exception) -> bool:
    text = str(exc).lower()
    if "resource_exhausted" in text:
        return True
    if "quota" in text and ("exceeded" in text or "limit" in text):
        return True
    if "daily limit" in text:
        return True
    return False


def _model_alias(model: str) -> str:
    aliases = {
        "gemini-3.0-flash": "gemini-3-flash-preview",
    }
    return aliases.get(model, model)


def _parse_csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


class GeminiProcessor:
    """Thin async wrapper around Gemini with Roberto-style model fallback handling."""

    def __init__(self):
        self.api_key: Optional[str] = None
        self.model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.model_name = self.model
        self.model_fallbacks = _parse_csv_env("GEMINI_MODEL_FALLBACKS") or list(DEFAULT_FALLBACK_MODELS)
        self.temperature = float(os.environ.get("GEMINI_TEMPERATURE", "0.1"))
        self.max_output_tokens = int(os.environ.get("GEMINI_MAX_OUTPUT_TOKENS", "4096"))
        self.retry_max_attempts = int(os.environ.get("GEMINI_RETRY_MAX_ATTEMPTS", "6"))
        self.retry_min_backoff_s = float(os.environ.get("GEMINI_RETRY_MIN_BACKOFF_S", "10"))
        self.retry_max_backoff_s = float(os.environ.get("GEMINI_RETRY_MAX_BACKOFF_S", "120"))
        self.single_post_context_chars = int(os.environ.get("GEMINI_SINGLE_POST_CONTEXT_CHARS", "120000"))
        self.single_post_notes_chars = int(os.environ.get("GEMINI_SINGLE_POST_NOTES_CHARS", "10000"))
        self.single_post_comments_chars = int(os.environ.get("GEMINI_SINGLE_POST_COMMENTS_CHARS", "40000"))
        self.is_setup = False
        self.logger = logging.getLogger(__name__)
        self._client: Any | None = None
        self._disabled_models: set[str] = set()
        self.llm: Any | None = None

    def setup_processor(self) -> bool:
        """Configure Gemini using GEMINI_API_KEY or GOOGLE_API_KEY."""
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            self.logger.error("GEMINI_API_KEY or GOOGLE_API_KEY environment variable not set")
            return False

        try:
            self.api_key = api_key
            self.is_setup = True
            return True
        except Exception as exc:
            self.logger.error("Failed to setup Gemini processor: %s", exc)
            self.is_setup = False
            return False

    async def connect(self) -> None:
        """Initialize the Gemini client lazily for compatibility with existing call sites."""
        if not self.is_setup:
            raise RuntimeError("Gemini processor is not configured")
        self.llm = self._client_instance()

    async def disconnect(self) -> None:
        """Release the cached client for compatibility with existing call sites."""
        self._client = None
        self.llm = None
        return None

    async def daily_briefing(self, posts: List[Dict[str, Any]]) -> str:
        """Generate a markdown daily briefing from stored posts."""
        prompt = f"""
You are preparing an intelligence daily briefing from collected source posts.

Write concise markdown with these sections:
- ## Executive Summary
- ## Main Developments
- ## Signals To Watch

Requirements:
- Use only the supplied posts
- Merge duplicate stories across sources instead of repeating them
- Separate original developments from downstream commentary when possible
- Prioritize what materially changes decisions, monitoring, or allocation of attention
- Call out source names when useful
- Write for a principal with very limited time: high signal, high consequence, no filler
- Do not mention missing data or your own process

POSTS:
{self._format_posts(posts, truncate_to=1600)}
"""
        try:
            return await self._generate_text(prompt)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic daily briefing: %s", exc)
            return self._fallback_daily_briefing(posts)

    async def daily_briefing_with_tokens(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compatibility wrapper for older test paths."""
        briefing = await self.daily_briefing(posts)
        return {
            "briefing": briefing,
            "token_usage": {
                "estimated_tokens": self.count_tokens(briefing),
            },
        }

    async def topic_briefing_with_numeric_ids(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Group posts into topics and cite them by numeric IDs."""
        numbered_posts = self._format_posts(posts, truncate_to=1400, numeric_ids=True)
        prompt = f"""
You are preparing a topic-based intelligence briefing from source posts.

Return ONLY valid JSON with this exact structure:
{{
  "daily_briefing": "short markdown summary",
  "topics": [
    {{
      "title": "topic title",
      "summary": "2-4 sentence markdown summary",
      "post_ids": ["1", "2"]
    }}
  ]
}}

Rules:
- Use only post IDs that exist in the input.
- Create as many topics as needed.
- Put related posts together, even across different sources.
- Include replies for Nitter when they belong to the same topic.
- Prefer the original source event over downstream commentary when titles collide.
- Treat commentary/reaction posts as part of the same story when they are clearly about the same underlying event.
- Do not invent post IDs.
- Keep titles concrete and specific.
- The daily briefing should read like an analyst memo, not a generic recap.

POSTS:
{numbered_posts}
"""

        try:
            response_text = await self._generate_text(prompt)
            return self._extract_json_from_response(response_text)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic topic briefing: %s", exc)
            return self._fallback_topic_briefing(posts)

    async def enhanced_daily_briefing_with_topics(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compatibility alias for older scripts."""
        return await self.topic_briefing_with_numeric_ids(posts)

    async def weekly_briefing(self, week_label: str, daily_briefings: List[Dict[str, Any]]) -> str:
        """Generate a weekly briefing from already-generated daily briefings."""
        prompt = f"""
You are preparing a weekly intelligence briefing by synthesizing daily briefings from the same week.

Write concise markdown with these sections:
- ## Executive Weekly Summary
- ## Major Developments
- ## Cross-Day Patterns
- ## Watchlist For Next Week

Requirements:
- Use only the supplied daily briefings.
- Merge repeated stories into one thread instead of restating them day by day.
- Emphasize what changed across the week.
- Distinguish primary developments from commentary, reactions, and follow-on validation.
- Keep it compact, specific, and high-signal.
- Write for a decision-maker who needs consequences, not narration.
- Do not mention missing data or your own process.

WEEK:
{week_label}

DAILY BRIEFINGS:
{self._format_daily_briefings(daily_briefings)}
"""
        try:
            return await self._generate_text(prompt)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic weekly briefing: %s", exc)
            return self._fallback_weekly_briefing(week_label, daily_briefings)

    async def weekly_topic_briefing(self, week_label: str, daily_topic_briefings: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate a weekly story/timeline view from daily topic briefings."""
        prompt = f"""
Return ONLY valid JSON with this exact structure:
{{
  "weekly_briefing": "markdown weekly topic synthesis",
  "topics": [
    {{
      "title": "story title",
      "summary": "2-5 sentence summary",
      "post_ids": ["post-uuid-1", "post-uuid-2"],
      "timeline": [
        {{
          "date": "YYYY-MM-DD",
          "summary": "what changed on this date",
          "source_topics": ["daily topic title"],
          "post_ids": ["post-uuid-1"]
        }}
      ]
    }}
  ]
}}

Rules:
- Use only post IDs that exist in the supplied daily topic briefings.
- Merge same-story developments across different days into one weekly topic.
- Focus on evolution over time: what started, what changed, what intensified, what faded.
- Distinguish the core event from commentary/reactions around it.
- Write the weekly_briefing like an executive intelligence memo for a principal with limited time.
- Do not output any text outside the JSON.

WEEK:
{week_label}

DAILY TOPIC BRIEFINGS:
{self._format_daily_topic_briefings(daily_topic_briefings)}
"""
        try:
            response_text = await self._generate_text(prompt)
            return self._extract_json_from_response(response_text)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic weekly topic briefing: %s", exc)
            return self._fallback_weekly_topic_briefing(week_label, daily_topic_briefings)

    async def source_vertical_briefing(
        self,
        posts: List[Dict[str, Any]],
        scope_label: str,
        start_date: str,
        end_date: str,
        *,
        source_profile: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """Generate a source-scoped vertical briefing across a date range."""
        prompt = f"""
Return ONLY valid JSON with this exact structure:
{{
  "vertical_briefing": "markdown source-scoped synthesis",
  "tracks": [
    {{
      "title": "track title",
      "summary": "2-5 sentence summary",
      "track_kind": "project_thread",
      "story_titles": ["story title"],
      "entity_hints": ["entity or recurring actor"],
      "post_ids": ["post-uuid-1", "post-uuid-2"],
      "timeline": [
        {{
          "date": "YYYY-MM-DD",
          "summary": "what changed on this date",
          "post_ids": ["post-uuid-1"]
        }}
      ]
    }}
  ]
}}

Rules:
- Use only the supplied posts and post IDs.
- Every supplied post UUID must appear in exactly one track. Do not leave orphan posts out of the output.
- Optimize for recurring threads inside one source, not for generic topic buckets.
- For ranges with more than 20 posts, usually produce 4-8 tracks. Do not collapse distinct threads into only 2-3 generic buckets.
- Keep related posts together only when they clearly belong to the same recurring thread.
- Prefer story links, shared event titles, entity overlap, and recurring category hints when those signals are present.
- Treat posts in the same evidence cluster as one underlying signal when judging prominence.
- Use track_kind values from this set: project_thread, recurring_theme, one_off_update.
- Put a post into one_off_update only if it is a material isolated update.
- Separate different narrative axes when the evidence supports it. Typical axes include:
  - product/tooling releases and workflow changes
  - institutional or policy shifts
  - operational failures, security incidents, or reliability warnings
  - research or science developments
  - cultural/media usage and adoption signals
- Preserve the source's actual obsessions and worldview. This is a live thread for one source, not a generic AI-news summary.
- Preserve exact post IDs and timeline evidence.
- Do not output any text outside the JSON.

SOURCE: {scope_label}
DATE RANGE: {start_date} to {end_date}
SOURCE PROFILE:
{self._format_vertical_source_profile(source_profile or {})}
POSTS:
{self._format_posts(posts, truncate_to=1200, include_uuid=True, include_dates=True)}
"""
        try:
            response_text = await self._generate_text(prompt)
            return self._extract_json_from_response(response_text)
        except Exception as exc:
            self.logger.warning("Falling back to deterministic source vertical briefing: %s", exc)
            return self._fallback_source_vertical_briefing(scope_label, start_date, end_date, posts)

    def analyze_single_post(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize a single post and suggest tags in one request."""
        if not self.is_setup:
            return {"success": False, "error": "Processor not setup. Call setup_processor() first"}

        post_body = self._single_post_body(post, max_chars=self.single_post_context_chars)
        prompt = f"""
Return ONLY valid JSON with this exact structure:
{{
  "summary": "markdown summary",
  "tags": ["tag one", "tag two", "tag three"]
}}

Rules:
- Keep tags short, concrete, and lowercase when possible.
- Use 0 to 5 tags.
- Make the summary materially useful for an operator, not generic.
- Structure the summary with these markdown sections:
  - ## Core Thesis
  - ## Key Signals
  - ## Why It Matters
  - ## Decision Relevance
- Stay grounded in the supplied post only.
- Do not include commentary outside the JSON.

Source: {post.get("source", "unknown")}
Platform: {post.get("platform", "unknown")}
URL: {post.get("url", "")}
Published at: {post.get("published_at", "")}
Title: {post.get("title", "")}
Content:
{post_body}
"""
        try:
            result = self._extract_json_from_response(self._generate_text_sync(prompt))
            tags = result.get("tags", [])
            if not isinstance(tags, list):
                tags = []
            cleaned_tags = []
            for tag in tags:
                text = str(tag).strip().lower()
                if not text or text in cleaned_tags:
                    continue
                cleaned_tags.append(text[:48])
            return {
                "success": True,
                "summary": str(result.get("summary", "")).strip(),
                "tags": cleaned_tags[:5],
                "model": self.model_name,
                "estimated_tokens": self.count_tokens(prompt) + self.count_tokens(str(result.get("summary", ""))),
            }
        except Exception as exc:
            return {"success": False, "error": f"Analysis failed: {exc}"}

    def extract_post_highlights(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """Extract evidence highlights and a one-sentence takeaway from a single post."""
        if not self.is_setup:
            return {"success": False, "error": "Processor not setup. Call setup_processor() first"}

        post_body = self._single_post_body(post, max_chars=self.single_post_context_chars)
        prompt = f"""
Return ONLY valid JSON with this exact structure:
{{
  "highlights": [
    {{
      "text": "exact snippet or close paraphrase from the post",
      "kind": "evidence",
      "importance_score": 0.0,
      "commentary": "short factual note explaining why it matters",
      "start_char": null,
      "end_char": null
    }}
  ],
  "one_sentence_takeaway": "one sentence that captures the main point"
}}

Rules:
- Produce 3 to 7 highlights.
- Use only the supplied post content.
- Prefer exact snippets when possible.
- Keep commentary short and factual.
- Focus on what an analyst should remember later.
- Do not expose internal reasoning.
- Do not mention missing data or your process.

Source: {post.get("source", "unknown")}
Platform: {post.get("platform", "unknown")}
URL: {post.get("url", "")}
Published at: {post.get("published_at", "")}
Title: {post.get("title", "")}
Categories: {", ".join(post.get("categories") or []) or "none"}
Content:
{post_body}
"""
        try:
            result = self._extract_json_from_response(self._generate_text_sync(prompt))
            highlights = result.get("highlights", [])
            if not isinstance(highlights, list):
                highlights = []
            normalized: List[Dict[str, Any]] = []
            for highlight in highlights[:7]:
                if not isinstance(highlight, dict):
                    continue
                text = str(highlight.get("text") or "").strip()
                if not text:
                    continue
                normalized.append(
                    {
                        "highlight_text": text[:1200],
                        "highlight_kind": str(highlight.get("kind") or "evidence").strip()[:64] or "evidence",
                        "start_char": highlight.get("start_char"),
                        "end_char": highlight.get("end_char"),
                        "importance_score": float(highlight.get("importance_score") or 0.0),
                        "commentary": str(highlight.get("commentary") or "").strip()[:500] or None,
                    }
                )
            takeaway = str(result.get("one_sentence_takeaway") or "").strip()
            if not takeaway:
                takeaway = self._fallback_post_takeaway(post)
            return {
                "success": True,
                "highlights": normalized or self._fallback_post_highlights(post),
                "one_sentence_takeaway": takeaway,
                "model": self.model_name,
                "estimated_tokens": self.count_tokens(prompt) + self.count_tokens(takeaway),
            }
        except Exception as exc:
            self.logger.warning("Falling back to deterministic post highlights: %s", exc)
            return {
                "success": True,
                "highlights": self._fallback_post_highlights(post),
                "one_sentence_takeaway": self._fallback_post_takeaway(post),
                "model": "fallback",
                "estimated_tokens": self.count_tokens(post_body),
            }

    def ask_single_post(self, post: Dict[str, Any], question: str) -> Dict[str, Any]:
        """Answer a question about a single post."""
        if not self.is_setup:
            return {"success": False, "error": "Processor not setup. Call setup_processor() first"}

        topics = [
            topic.get("title")
            for topic in (post.get("topics") or [])
            if isinstance(topic, dict) and topic.get("title")
        ]
        metadata = post.get("metadata") or {}
        discussion = metadata.get("reddit_discussion") if isinstance(metadata, dict) else {}
        comments = discussion.get("comments") if isinstance(discussion, dict) else []
        comments_text = "\n\n".join(
            f"- {comment.get('author') or 'unknown'} (score={comment.get('score', 0)}, depth={comment.get('depth', 0)}): {comment.get('body', '')}"
            for comment in (comments or [])[:40]
        )
        content = self._single_post_body(post, max_chars=self.single_post_context_chars)
        saved_summary = str(post.get("cached_summary_markdown", "") or "")[: self.single_post_notes_chars]
        saved_notes = str(post.get("notes_markdown", "") or "")[: self.single_post_notes_chars]

        prompt = f"""
Answer the user's question using only this post.
If the answer is not present, say that clearly.
Use the full supplied material, including fetched Reddit comments, when relevant.
Prefer precise answers over vague summaries.
Write as an analyst helping a high-context operator understand the post, not as a generic chatbot.

Source: {post.get("source", "unknown")}
URL: {post.get("url", "")}
Title: {post.get("title", "")}
Published at: {post.get("published_at", "")}
Tags: {", ".join(post.get("categories") or []) or "none"}
Connected topics: {", ".join(topics) or "none"}
Saved summary:
{saved_summary}
Saved notes:
{saved_notes}
Content:
{content}

Fetched Reddit comments:
{comments_text[: self.single_post_comments_chars] or "No fetched comments."}

Question: {question}
"""
        try:
            answer = self._generate_text_sync(prompt)
            return {
                "success": True,
                "answer": answer,
                "estimated_tokens": self.count_tokens(prompt) + self.count_tokens(answer),
            }
        except Exception as exc:
            return {"success": False, "error": f"Question answering failed: {exc}"}

    def summarize_reddit_comments(self, post: Dict[str, Any], comments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Summarize a Reddit discussion thread for a single stored post."""
        if not self.is_setup:
            return {"success": False, "error": "Processor not setup. Call setup_processor() first"}

        prompt = f"""
Return ONLY valid JSON with this exact structure:
{{
  "summary": "markdown discussion briefing",
  "signals": ["signal one", "signal two", "signal three"]
}}

Rules:
- Focus on the discussion, disagreement, consensus, and concrete recommendations.
- Use only the supplied comments.
- Keep it compact and high-signal.

Post title: {post.get("title", "")}
Post source: {post.get("source", "")}
Post content:
{self._single_post_body(post, max_chars=6000)}

Comments:
{chr(10).join(
    f"- {comment.get('author') or 'unknown'} (score={comment.get('score', 0)}, depth={comment.get('depth', 0)}): {str(comment.get('body') or '')[:600]}"
    for comment in comments[:60]
)[:12000]}
"""
        try:
            result = self._extract_json_from_response(self._generate_text_sync(prompt))
            return {
                "success": True,
                "summary": str(result.get("summary", "")).strip(),
                "signals": result.get("signals") if isinstance(result.get("signals"), list) else [],
                "model": self.model_name,
                "estimated_tokens": self.count_tokens(prompt) + self.count_tokens(str(result.get("summary", ""))),
            }
        except Exception as exc:
            return {"success": False, "error": f"Comments summary failed: {exc}"}

    def model_topics(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Assign database posts into topic buckets keyed by post UUID."""
        if not self.is_setup:
            return {
                "success": False,
                "error": "Processor not setup. Call setup_processor() first",
            }

        if not posts:
            return {
                "success": False,
                "error": "No posts provided for topic modeling",
            }

        prompt = f"""
Return ONLY valid JSON with this structure:
{{
  "topic_names": {{
    "0": "topic title"
  }},
  "assignments": {{
    "post_uuid": 0,
    "post_uuid_2": -1
  }}
}}

Rules:
- Use the supplied post IDs exactly.
- Use -1 for outliers.
- Every post must appear exactly once in assignments.
- Topic names must be specific and story-oriented.

POSTS:
{self._format_posts(posts, truncate_to=1000, include_uuid=True)}
"""

        try:
            response_text = self._generate_text_sync(prompt)
            result = self._extract_json_from_response(response_text)
            if "topic_names" not in result or "assignments" not in result:
                raise ValueError("Response missing topic_names or assignments")
            return {
                "success": True,
                "topic_names": result["topic_names"],
                "assignments": result["assignments"],
                "total_posts": len(posts),
                "total_topics": len(result["topic_names"]),
            }
        except Exception as exc:
            self.logger.error("Topic modeling failed: %s", exc)
            return {
                "success": False,
                "error": f"Topic modeling failed: {exc}",
            }

    def count_tokens(self, text: str) -> int:
        """Rough token estimate used for compatibility fields."""
        return max(1, len(text) // 4)

    def _single_post_body(self, post: Dict[str, Any], *, max_chars: int) -> str:
        content = str(post.get("content") or "").strip()
        html_content = str(post.get("content_html") or "").strip()

        if html_content and len(content) < len(html_content) // 4:
            stripped_html = re.sub(r"<[^>]+>", " ", html_content)
            stripped_html = re.sub(r"\s+", " ", stripped_html).strip()
            if len(stripped_html) > len(content):
                content = stripped_html

        if not content:
            content = "No stored content."

        return content[:max_chars]

    def _format_daily_briefings(self, daily_briefings: List[Dict[str, Any]]) -> str:
        blocks = []
        for item in daily_briefings:
            blocks.append(
                "\n".join(
                    [
                        f"Date: {item.get('date') or 'unknown'}",
                        f"Posts processed: {item.get('posts_processed') or 0}",
                        "Briefing:",
                        str(item.get("briefing") or "").strip(),
                    ]
                ).strip()
            )
        return "\n\n---\n\n".join(blocks)

    def _format_daily_topic_briefings(self, daily_topic_briefings: List[Dict[str, Any]]) -> str:
        blocks = []
        for item in daily_topic_briefings:
            topic_lines = []
            for topic in item.get("topics") or []:
                topic_lines.append(
                    "\n".join(
                        [
                            f"Topic: {topic.get('title') or 'Untitled topic'}",
                            f"Summary: {topic.get('summary') or ''}",
                            f"Post IDs: {', '.join(topic.get('post_ids') or [])}",
                        ]
                    ).strip()
                )
            blocks.append(
                "\n".join(
                    [
                        f"Date: {item.get('date') or 'unknown'}",
                        "Daily briefing:",
                        str(item.get("briefing") or "").strip(),
                        "Topics:",
                        "\n\n".join(topic_lines) if topic_lines else "No topics",
                    ]
                ).strip()
            )
        return "\n\n---\n\n".join(blocks)

    def _first_sentence(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if not text:
            return ""
        match = re.search(r"(.+?[.!?])(?:\s|$)", text)
        return (match.group(1) if match else text[:220]).strip()

    def _fallback_post_takeaway(self, post: Dict[str, Any]) -> str:
        title = (post.get("title") or "Untitled post").strip()
        content = " ".join((post.get("content") or "").split())
        if not content:
            return f"{title} contains too little stored text for a deeper takeaway."
        sentence = self._first_sentence(content)
        if not sentence:
            sentence = content[:180]
        return sentence if sentence.endswith((".", "!", "?")) else f"{sentence}."

    def _fallback_post_highlights(self, post: Dict[str, Any]) -> List[Dict[str, Any]]:
        content = " ".join((post.get("content") or "").split())
        if not content:
            return [
                {
                    "highlight_text": "No stored text was available for this post.",
                    "highlight_kind": "context",
                    "start_char": None,
                    "end_char": None,
                    "importance_score": 0.1,
                    "commentary": "Fallback highlight generated from missing content.",
                }
            ]

        sentences = re.split(r"(?<=[.!?])\s+", content)
        ranked = [sentence.strip() for sentence in sentences if sentence.strip()]
        if not ranked:
            ranked = [content[:220]]
        highlights: List[Dict[str, Any]] = []
        for index, sentence in enumerate(ranked[:5], start=1):
            highlights.append(
                {
                    "highlight_text": sentence[:600],
                    "highlight_kind": "evidence" if index == 1 else "context",
                    "start_char": None,
                    "end_char": None,
                    "importance_score": max(0.1, 1.0 - (index - 1) * 0.15),
                    "commentary": "Fallback highlight derived from the stored post content.",
                }
            )
        return highlights

    def _fallback_daily_briefing(self, posts: List[Dict[str, Any]]) -> str:
        ordered_posts = sorted(posts, key=self._post_sort_key, reverse=True)
        source_names = self._ordered_unique_sources(ordered_posts)
        executive = (
            f"- {len(ordered_posts)} posts collected across {len(source_names)} sources: "
            f"{', '.join(source_names[:3])}"
        )
        latest_post = ordered_posts[0] if ordered_posts else {}
        if latest_post:
            executive += f". Most recent activity came from {self._source_name(latest_post)}."

        development_lines = []
        for post in ordered_posts[:5]:
            development_lines.append(
                f"- {self._source_name(post)}: {self._post_brief(post)}"
            )

        signal_lines = []
        for post in ordered_posts[:3]:
            signal_lines.append(
                f"- Watch for follow-up from {self._source_name(post)} on {self._post_topic(post)}."
            )

        sections = [
            "## Executive Summary",
            executive,
            "",
            "## Main Developments",
            *(development_lines or ["- No developments available."]),
            "",
            "## Signals To Watch",
            *(signal_lines or ["- No watch items available."]),
        ]
        return "\n".join(sections)

    def _fallback_topic_briefing(self, posts: List[Dict[str, Any]]) -> Dict[str, Any]:
        grouped_posts: Dict[str, List[str]] = {}
        topic_titles: Dict[str, str] = {}

        for index, post in enumerate(posts, start=1):
            source_name = self._source_name(post)
            grouped_posts.setdefault(source_name, []).append(str(index))
            topic_titles.setdefault(source_name, f"Updates from {source_name}")

        topics = []
        for source_name, post_ids in grouped_posts.items():
            source_posts = [
                post for index, post in enumerate(posts, start=1)
                if str(index) in post_ids
            ]
            summary_parts = [self._post_brief(post) for post in source_posts[:3]]
            topics.append(
                {
                    "title": topic_titles[source_name],
                    "summary": " ".join(summary_parts),
                    "post_ids": post_ids,
                }
            )

        return {
            "daily_briefing": self._fallback_daily_briefing(posts),
            "topics": topics,
        }

    def _fallback_weekly_briefing(self, week_label: str, daily_briefings: List[Dict[str, Any]]) -> str:
        ordered = sorted(daily_briefings, key=lambda item: item.get("date") or "")
        developments = []
        watchlist = []
        for item in ordered[:7]:
            first_sentence = self._first_sentence(item.get("briefing") or "")
            label = item.get("date") or "unknown day"
            if first_sentence:
                developments.append(f"- **{label}**: {first_sentence}")
                watchlist.append(f"- Revisit the {label} thread for downstream changes.")

        sections = [
            "## Executive Weekly Summary",
            f"- {len(ordered)} daily briefings contributed to {week_label}.",
            "",
            "## Major Developments",
            *(developments or ["- No major developments were available."]),
            "",
            "## Cross-Day Patterns",
            "- Repeated stories across the week should be treated as durable signals rather than one-off noise.",
            "",
            "## Watchlist For Next Week",
            *(watchlist[:5] or ["- No watchlist items were generated."]),
        ]
        return "\n".join(sections)

    def _fallback_weekly_topic_briefing(self, week_label: str, daily_topic_briefings: List[Dict[str, Any]]) -> Dict[str, Any]:
        grouped: Dict[str, Dict[str, Any]] = {}
        for day in daily_topic_briefings:
            current_date = day.get("date") or "unknown"
            for topic in day.get("topics") or []:
                title = str(topic.get("title") or "Untitled Topic").strip()
                bucket = grouped.setdefault(
                    title,
                    {
                        "title": title,
                        "summary": str(topic.get("summary") or "").strip(),
                        "post_ids": [],
                        "timeline": [],
                    },
                )
                for post_id in topic.get("post_ids") or []:
                    post_key = str(post_id)
                    if post_key not in bucket["post_ids"]:
                        bucket["post_ids"].append(post_key)
                bucket["timeline"].append(
                    {
                        "date": current_date,
                        "summary": str(topic.get("summary") or "").strip() or f"{title} remained active on {current_date}.",
                        "source_topics": [title],
                        "post_ids": [str(post_id) for post_id in topic.get("post_ids") or []],
                    }
                )

        ordered_topics = list(grouped.values())
        weekly_lines = [
            "## Executive Weekly Topic Summary",
            f"- {len(ordered_topics)} weekly story threads were synthesized for {week_label}.",
            "",
            "## Story Evolution",
        ]
        for topic in ordered_topics[:6]:
            weekly_lines.append(f"- **{topic['title']}**: {topic['summary'] or 'This topic persisted across the week.'}")

        return {
            "weekly_briefing": "\n".join(weekly_lines),
            "topics": ordered_topics,
        }

    async def _generate_text(self, prompt: str) -> str:
        return await asyncio.to_thread(self._generate_text_sync, prompt)

    def _client_instance(self):
        if self._client is not None:
            return self._client

        from google import genai

        if self.api_key:
            self._client = genai.Client(api_key=self.api_key)
        else:
            self._client = genai.Client()
        self.llm = self._client
        return self._client

    def _candidate_models(self) -> list[str]:
        requested = [str(self.model).strip()] + [str(model).strip() for model in self.model_fallbacks]
        out: list[str] = []
        for model in requested:
            if not model:
                continue
            aliased = _model_alias(model)
            if aliased and aliased not in out:
                out.append(aliased)
        return out or ["gemini-flash-latest"]

    def _generate_text_sync(self, prompt: str) -> str:
        if not self.is_setup or not self.api_key:
            raise RuntimeError("Gemini processor is not configured")

        client = self._client_instance()
        try:
            from google.genai import types as genai_types

            config_obj: Any = genai_types.GenerateContentConfig(
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
            )
        except Exception:  # noqa: BLE001
            config_obj = {
                "temperature": self.temperature,
                "max_output_tokens": self.max_output_tokens,
            }

        models = [model for model in self._candidate_models() if model not in self._disabled_models]
        if not models:
            raise RuntimeError("No enabled Gemini models available for request")

        attempts = max(1, int(self.retry_max_attempts))
        min_backoff = max(1.0, float(self.retry_min_backoff_s))
        max_backoff = max(min_backoff, float(self.retry_max_backoff_s))
        last_retryable_exc: Exception | None = None

        for attempt in range(attempts):
            cycle_retry_delay: float | None = None
            for model in list(models):
                if model in self._disabled_models:
                    continue
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=config_obj,
                    )
                    text = self._response_text(response)
                    if not text:
                        raise RuntimeError(f"Gemini returned empty response for model {model}")
                    self.model_name = model
                    return self._clean_markdown_response(text)
                except Exception as exc:  # noqa: BLE001
                    if _looks_like_missing_model(exc):
                        self.logger.warning("Disabling unavailable Gemini model %s: %s", model, exc)
                        self._disabled_models.add(model)
                        continue

                    if isinstance(exc, RuntimeError):
                        text = str(exc).lower()
                        if "empty response" in text:
                            last_retryable_exc = exc
                            continue

                    status = _status_code(exc)
                    if status in {429, 500, 502, 503, 504}:
                        if status == 429 and _looks_like_quota_exhausted(exc):
                            self.logger.warning("Disabling quota-exhausted Gemini model %s: %s", model, exc)
                            self._disabled_models.add(model)
                            last_retryable_exc = exc
                            continue
                        last_retryable_exc = exc
                        retry_hint = _retry_delay_from_error(exc)
                        if retry_hint is not None:
                            cycle_retry_delay = max(cycle_retry_delay or 0.0, retry_hint)
                        continue
                    raise

            models = [model for model in self._candidate_models() if model not in self._disabled_models]
            if not models:
                raise RuntimeError("All configured Gemini models were rejected/unavailable")
            if last_retryable_exc is None:
                break
            if attempt >= attempts - 1:
                break
            default_delay = min(max_backoff, min_backoff * (2 ** attempt))
            wait_s = min(max_backoff, max(min_backoff, cycle_retry_delay or default_delay))
            self.logger.warning(
                "Gemini retry cycle %s/%s exhausted across models; sleeping %.1fs before retry.",
                attempt + 1,
                attempts,
                wait_s,
            )
            time.sleep(wait_s)

        if last_retryable_exc is not None:
            raise last_retryable_exc
        raise RuntimeError("Gemini request failed without retryable error details")

    def _response_text(self, response: Any) -> str:
        text = getattr(response, "text", None)
        if text:
            return str(text).strip()

        parsed = getattr(response, "parsed", None)
        if parsed is not None:
            if hasattr(parsed, "model_dump_json"):
                return parsed.model_dump_json()  # type: ignore[attr-defined]
            if hasattr(parsed, "model_dump"):
                return json.dumps(parsed.model_dump())  # type: ignore[attr-defined]
            if isinstance(parsed, (dict, list)):
                return json.dumps(parsed)
            return str(parsed).strip()

        candidates = getattr(response, "candidates", None)
        text_parts: list[str] = []
        if candidates:
            for candidate in candidates:
                content = getattr(candidate, "content", None)
                if content is None and isinstance(candidate, dict):
                    content = candidate.get("content", {})
                parts = getattr(content, "parts", None) if content is not None else None
                if parts is None and isinstance(content, dict):
                    parts = content.get("parts", [])
                for part in parts or []:
                    part_text = getattr(part, "text", None)
                    if part_text is None and isinstance(part, dict):
                        part_text = part.get("text")
                    if part_text:
                        text_parts.append(str(part_text))
        return "\n".join(text_parts).strip()

    def _extract_json_from_response(self, response_text: str) -> Dict[str, Any]:
        text = response_text.strip()
        if "```json" in text:
            text = text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in text:
            text = text.split("```", 1)[1].split("```", 1)[0].strip()
        return json.loads(text)

    def _clean_markdown_response(self, response_text: str) -> str:
        text = response_text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("\n", 1)[0] if "\n" in text else text[:-3]
        return text.strip()

    def _format_posts(
        self,
        posts: List[Dict[str, Any]],
        truncate_to: int,
        numeric_ids: bool = False,
        include_uuid: bool = False,
        include_dates: bool = False,
    ) -> str:
        lines: List[str] = []
        for index, post in enumerate(posts, start=1):
            source = post.get("source") or post.get("handle_or_url") or "unknown"
            title = (post.get("title") or "").strip()
            content = (post.get("content") or "").strip()[:truncate_to]
            identifier = str(index) if numeric_ids else post.get("id", str(index))

            header = f"Post {index}"
            if numeric_ids:
                header += f" (ID: {index})"
            if include_uuid:
                header += f" (UUID: {post.get('id')})"

            lines.append(header)
            if include_dates:
                posted_at = post.get("published_at") or post.get("date") or post.get("fetched_at") or "unknown"
                lines.append(f"Published at: {posted_at}")
            lines.append(f"Source: {source}")
            if title:
                lines.append(f"Title: {title}")
            story_titles = self._vertical_story_titles(post)
            if story_titles:
                lines.append(f"Story links: {', '.join(story_titles)}")
            event_titles = [str(item).strip() for item in (post.get("vertical_shared_event_titles") or post.get("vertical_event_titles") or []) if str(item).strip()]
            if event_titles:
                lines.append(f"Event hints: {', '.join(event_titles[:4])}")
            entity_names = self._vertical_entity_names(post)
            if entity_names:
                lines.append(f"Entities: {', '.join(entity_names)}")
            category_names = [str(item).strip() for item in (post.get("vertical_shared_category_names") or post.get("vertical_category_names") or []) if str(item).strip()]
            if category_names:
                lines.append(f"Categories: {', '.join(category_names[:4])}")
            track_hint = str(post.get("vertical_track_hint") or "").strip()
            if track_hint:
                lines.append(f"Track hint: {track_hint}")
            overlap_count = int(post.get("vertical_entity_overlap_count") or 0)
            if overlap_count > 0:
                lines.append(f"Entity overlap count: {overlap_count}")
            cluster_size = int(post.get("vertical_evidence_cluster_size") or 0)
            if cluster_size > 1:
                lines.append(f"Evidence cluster: {cluster_size} post(s) collapsed")
            lines.append(f"Key: {identifier}")
            lines.append(f"Content: {content}")
            lines.append("")

        return "\n".join(lines)

    def _format_vertical_source_profile(self, profile: Dict[str, Any]) -> str:
        if not profile:
            return "- no source profile available"

        lines = [
            f"- total posts: {int(profile.get('posts_total') or 0)}",
            f"- story-linked posts: {int(profile.get('story_linked_posts') or 0)}",
            f"- entity-overlap posts: {int(profile.get('entity_overlap_posts') or 0)}",
            f"- event-overlap posts: {int(profile.get('event_overlap_posts') or 0)}",
        ]
        for label, key, limit in (
            ("dominant story titles", "dominant_story_titles", 6),
            ("dominant entities", "dominant_entities", 8),
            ("dominant events", "dominant_events", 6),
            ("dominant categories", "dominant_categories", 8),
            ("dominant track hints", "dominant_track_hints", 8),
        ):
            values = [str(item).strip() for item in (profile.get(key) or []) if str(item).strip()]
            if values:
                lines.append(f"- {label}: {', '.join(values[:limit])}")
        return "\n".join(lines)

    def _source_name(self, post: Dict[str, Any]) -> str:
        return str(post.get("source") or post.get("handle_or_url") or "unknown").strip()

    def _ordered_unique_sources(self, posts: List[Dict[str, Any]]) -> List[str]:
        seen = set()
        sources = []
        for post in posts:
            source_name = self._source_name(post)
            if source_name in seen:
                continue
            seen.add(source_name)
            sources.append(source_name)
        return sources

    def _post_sort_key(self, post: Dict[str, Any]) -> str:
        for key in ("published_at", "date", "fetched_at"):
            value = post.get(key)
            if value is None:
                continue
            if isinstance(value, datetime):
                return value.isoformat()
            return str(value)
        return ""

    def _post_brief(self, post: Dict[str, Any]) -> str:
        title = (post.get("title") or "").strip()
        content = " ".join((post.get("content") or "").split())
        summary = title or content
        summary = summary[:220].rstrip()
        if not summary:
            return "Posted an update."
        return summary if summary.endswith((".", "!", "?")) else f"{summary}."

    def _post_topic(self, post: Dict[str, Any]) -> str:
        title = (post.get("title") or "").strip()
        if title:
            return title[:120]

        content = " ".join((post.get("content") or "").split())
        if not content:
            return "recent posts"

        words = content.split()
        return " ".join(words[:10]).strip()

    def _fallback_source_vertical_briefing(
        self,
        scope_label: str,
        start_date: str,
        end_date: str,
        posts: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        clusters = self._vertical_compress_posts(posts)
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for cluster in clusters:
            signature = self._vertical_cluster_signature(cluster)
            grouped.setdefault(signature, []).append(cluster)

        buckets = sorted(
            grouped.items(),
            key=lambda item: (
                -len(item[1]),
                -sum(cluster.get("raw_post_count", 0) for cluster in item[1]),
                self._post_sort_key((item[1][0] or {}).get("representative") or {}) if item[1] else "",
            ),
        )
        primary_buckets = buckets[:5]
        overflow_clusters = [cluster for _, bucket_clusters in buckets[5:] for cluster in bucket_clusters]
        if overflow_clusters:
            primary_buckets.append(("Other Updates", overflow_clusters))

        tracks: List[Dict[str, Any]] = []
        for index, (signature, bucket_clusters) in enumerate(primary_buckets, start=1):
            if not bucket_clusters:
                continue

            ordered_clusters = sorted(
                bucket_clusters,
                key=lambda cluster: self._post_sort_key(cluster.get("representative") or {}),
            )

            post_ids: List[str] = []
            for cluster in ordered_clusters:
                for post_id in cluster.get("post_ids") or []:
                    if post_id not in post_ids:
                        post_ids.append(post_id)
            if not post_ids:
                continue

            story_titles = self._merge_cluster_story_titles([cluster.get("posts") for cluster in ordered_clusters if cluster.get("posts")]) if False else []
            story_titles = self._collect_cluster_story_titles(ordered_clusters)
            entity_hints = self._collect_cluster_entity_hints(ordered_clusters)
            raw_post_count = sum(int(cluster.get("raw_post_count") or len(cluster.get("posts") or [])) for cluster in ordered_clusters)
            evidence_cluster_count = len(ordered_clusters)

            timeline = [
                self._vertical_cluster_timeline_entry(cluster)
                for cluster in ordered_clusters
            ]
            track_title = self._vertical_track_title(signature, ordered_clusters, index, signature == "Other Updates")
            track_kind = self._vertical_track_kind(
                ordered_clusters,
                track_title=track_title,
                story_titles=story_titles,
                entity_hints=entity_hints,
                is_overflow=signature == "Other Updates",
            )
            track_summary = self._vertical_track_summary(
                track_title,
                ordered_clusters,
                raw_post_count=raw_post_count,
                evidence_cluster_count=evidence_cluster_count,
                story_titles=story_titles,
                entity_hints=entity_hints,
            )
            tracks.append(
                {
                    "id": f"track-{index}",
                    "title": track_title,
                    "summary": track_summary,
                    "track_kind": track_kind,
                    "post_ids": post_ids,
                    "timeline": timeline,
                    "story_titles": story_titles,
                    "entity_hints": entity_hints,
                    "evidence_cluster_count": evidence_cluster_count,
                    "raw_post_count": raw_post_count,
                    "unique_post_count": len(post_ids),
                }
            )

        vertical_briefing = self._build_vertical_briefing_markdown(
            scope_label=scope_label,
            start_date=start_date,
            end_date=end_date,
            posts=posts,
            tracks=tracks,
        )

        return {
            "vertical_briefing": vertical_briefing,
            "tracks": tracks,
        }

    def _vertical_track_signature(self, post: Dict[str, Any]) -> str:
        story_title = str(post.get("vertical_primary_story_title") or "").strip()
        if story_title:
            return story_title

        track_hint = str(post.get("vertical_track_hint") or "").strip()
        if track_hint:
            return track_hint

        entity_names = self._vertical_entity_names(post)
        if entity_names:
            return " / ".join(entity_names[:2]).strip()

        text = self._normalize_vertical_text(post.get("title") or "") or self._normalize_vertical_text(post.get("content") or "")
        if not text:
            return "general"

        tokens = [
            token
            for token in re.findall(r"[a-z0-9][a-z0-9\-']+", text.lower())
            if token not in {"and", "or", "the", "a", "an", "to", "of", "for", "in", "on", "with", "from"}
        ]
        if not tokens:
            return "general"

        if tokens[0] in VERTICAL_GENERIC_LEADS and len(tokens) > 1:
            signature_tokens = tokens[1:3]
        elif len(tokens) > 1 and (tokens[1] in VERTICAL_GENERIC_SUFFIXES or re.fullmatch(r"v?\d+(?:\.\d+)?", tokens[1])):
            signature_tokens = tokens[:1]
        else:
            signature_tokens = tokens[:2]

        signature = " ".join(signature_tokens).strip()
        return signature or tokens[0]

    def _vertical_track_title(
        self,
        signature: str,
        posts: List[Dict[str, Any]],
        index: int,
        is_overflow: bool = False,
    ) -> str:
        if is_overflow:
            return "Other Updates"
        if not signature or signature == "general":
            first_item = posts[0] if posts else {}
            first_post = first_item.get("representative") if isinstance(first_item, dict) and "representative" in first_item else first_item
            fallback = self._post_topic(first_post)
            return fallback[:80] or f"Track {index}"
        if signature != signature.lower():
            return signature[:80]
        return signature.replace("-", " ").title()[:80]

    def _vertical_track_kind(
        self,
        clusters: List[Dict[str, Any]],
        *,
        track_title: str,
        story_titles: List[str],
        entity_hints: List[str],
        is_overflow: bool = False,
    ) -> str:
        if is_overflow:
            return "one_off_update"

        cluster_count = len(clusters)
        text = track_title.lower()
        project_hints = {
            "agent",
            "agents",
            "autoresearch",
            "build",
            "coding",
            "experiment",
            "framework",
            "launch",
            "model",
            "pipeline",
            "project",
            "research",
            "system",
            "tool",
            "workflow",
        }

        if cluster_count > 1 and (story_titles or any(hint in text for hint in project_hints)):
            return "project_thread"
        if cluster_count > 1 and entity_hints:
            return "recurring_theme"
        if cluster_count > 1:
            return "recurring_theme"
        return "one_off_update"

    def _vertical_track_summary(
        self,
        title: str,
        clusters: List[Dict[str, Any]],
        *,
        raw_post_count: int,
        evidence_cluster_count: int,
        story_titles: List[str],
        entity_hints: List[str],
    ) -> str:
        if not clusters:
            return "No posts available for this track."
        snippets: List[str] = []
        for cluster in clusters[:3]:
            snippet = self._vertical_cluster_brief(cluster)
            if snippet:
                snippets.append(snippet)

        summary = f"{title} spans {evidence_cluster_count} evidence cluster(s) and {raw_post_count} post(s)"
        if story_titles:
            summary += f"; story links: {', '.join(story_titles[:2])}"
        ordered_entity_hints = list(entity_hints)
        for preferred in [title, *(story_titles[:1] if story_titles else [])]:
            if not preferred:
                continue
            try:
                index = next(
                    idx
                    for idx, hint in enumerate(ordered_entity_hints)
                    if hint.lower() == str(preferred).lower()
                )
            except StopIteration:
                continue
            if index > 0:
                ordered_entity_hints.insert(0, ordered_entity_hints.pop(index))
            break
        if ordered_entity_hints:
            summary += f"; shared entities: {', '.join(ordered_entity_hints[:2])}"
        if snippets:
            summary += f": {'; '.join(snippets)}."
        else:
            summary += "."
        return summary

    def _build_vertical_briefing_markdown(
        self,
        *,
        scope_label: str,
        start_date: str,
        end_date: str,
        posts: List[Dict[str, Any]],
        tracks: List[Dict[str, Any]],
    ) -> str:
        recurring_tracks = [track for track in tracks if track.get("track_kind") != "one_off_update"]
        one_off_tracks = [track for track in tracks if track.get("track_kind") == "one_off_update"]
        top_track_titles = [track.get("title") for track in recurring_tracks[:3] if track.get("title")]

        lines: List[str] = [
            "## Executive Summary",
            (
                f"- {len(posts)} post(s) from {scope_label} between {start_date} and {end_date} "
                f"were organized into {len(tracks)} track(s)."
            ),
        ]
        if top_track_titles:
            lines.append(f"- Primary recurring threads: {', '.join(top_track_titles)}.")
        else:
            lines.append("- The source mostly expressed isolated updates in this range.")

        lines.extend(["", "## Recurring Tracks"])
        if recurring_tracks:
            for track in recurring_tracks:
                lines.extend(self._format_vertical_track_markdown(track))
        else:
            lines.append("- No strong recurring threads were identified.")

        if one_off_tracks:
            lines.extend(["", "## One-Off Updates"])
            for track in one_off_tracks:
                lines.extend(self._format_vertical_track_markdown(track, compact=True))

        lines.extend(["", "## Signal Watchlist"])
        if recurring_tracks:
            for track in recurring_tracks[:4]:
                title = track.get("title") or "Untitled track"
                lines.append(f"- Watch the {title} thread for follow-on shifts.")
        else:
            lines.append("- Watch for whether isolated updates start repeating as a broader thread.")

        return "\n".join(line for line in lines if line is not None).strip()

    def _format_vertical_track_markdown(self, track: Dict[str, Any], compact: bool = False) -> List[str]:
        title = track.get("title") or "Untitled track"
        summary = track.get("summary") or ""
        lines = [f"### {title}", summary or "No summary available."]
        story_titles = track.get("story_titles") or []
        if story_titles:
            lines.append(f"- Story links: {', '.join(str(item) for item in story_titles[:4])}")
        entity_hints = track.get("entity_hints") or []
        if entity_hints:
            lines.append(f"- Shared entities: {', '.join(str(item) for item in entity_hints[:4])}")
        if track.get("evidence_cluster_count") is not None:
            lines.append(f"- Evidence clusters: {track.get('evidence_cluster_count')}")
        if track.get("raw_post_count") is not None:
            lines.append(f"- Raw posts: {track.get('raw_post_count')}")
        if compact:
            if track.get("post_ids"):
                lines.append(f"- Evidence: {', '.join(track.get('post_ids')[:4])}")
            return lines

        for entry in track.get("timeline") or []:
            date_value = entry.get("date") or "unknown date"
            post_ids = entry.get("post_ids") or []
            evidence = f" ({', '.join(post_ids)})" if post_ids else ""
            lines.append(f"- **{date_value}**: {entry.get('summary') or ''}{evidence}")
        return lines

    def _vertical_cluster_brief(self, cluster: Dict[str, Any]) -> str:
        representative = cluster.get("representative") or {}
        snippet = self._post_brief(representative).rstrip(".")
        raw_post_count = int(cluster.get("raw_post_count") or len(cluster.get("posts") or []))
        if raw_post_count > 1:
            return f"{snippet} ({raw_post_count} posts collapsed)"
        return snippet

    def _collect_cluster_story_titles(self, clusters: List[Dict[str, Any]]) -> List[str]:
        posts = [post for cluster in clusters for post in cluster.get("posts") or []]
        return self._merge_cluster_story_titles(posts)

    def _collect_cluster_entity_hints(self, clusters: List[Dict[str, Any]]) -> List[str]:
        posts = [post for cluster in clusters for post in cluster.get("posts") or []]
        shared = self._merge_cluster_shared_entities(posts)
        return shared or self._merge_cluster_entity_names(posts)

    def _vertical_cluster_timeline_entry(self, cluster: Dict[str, Any]) -> Dict[str, Any]:
        representative = cluster.get("representative") or {}
        raw_post_count = int(cluster.get("raw_post_count") or len(cluster.get("posts") or []))
        summary = self._post_brief(representative)
        if raw_post_count > 1:
            summary = f"{summary.rstrip('.')} ({raw_post_count} posts collapsed)"
        return {
            "date": cluster.get("date") or self._vertical_post_date(representative),
            "summary": summary,
            "post_ids": list(cluster.get("post_ids") or []),
        }

    def _vertical_date_span(self, posts: List[Dict[str, Any]]) -> int:
        dates = [self._vertical_post_date(post) for post in posts if self._vertical_post_date(post)]
        if len(dates) < 2:
            return 0
        return self._date_distance_days(dates[0], dates[-1])

    def _vertical_post_date(self, post: Dict[str, Any]) -> str:
        value = post.get("published_at") or post.get("date") or post.get("fetched_at")
        if isinstance(value, datetime):
            return value.date().isoformat()
        if value is None:
            return ""
        text = str(value)
        if "T" in text:
            return text[:10]
        return text

    def _vertical_story_titles(self, post: Dict[str, Any]) -> List[str]:
        titles: List[str] = []
        seen: set[str] = set()
        for title in post.get("vertical_story_titles") or []:
            text = str(title).strip()
            if not text:
                continue
            normalized = text.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            titles.append(text)
        return titles[:4]

    def _vertical_entity_names(self, post: Dict[str, Any]) -> List[str]:
        names: List[str] = []
        seen: set[str] = set()
        for name in post.get("vertical_shared_entity_names") or []:
            text = str(name).strip()
            if not text:
                continue
            normalized = text.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            names.append(text)
        if names:
            return names[:4]

        for name in post.get("vertical_entity_names") or []:
            text = str(name).strip()
            if not text:
                continue
            normalized = text.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            names.append(text)
        return names[:4]

    def _vertical_cluster_key(self, post: Dict[str, Any]) -> str:
        key = str(post.get("vertical_evidence_cluster_key") or "").strip()
        if key:
            return key
        return str(post.get("id") or "")

    def _vertical_cluster_signature(self, cluster: Dict[str, Any]) -> str:
        story_titles = cluster.get("story_titles") or []
        if story_titles:
            return str(story_titles[0]).strip()

        shared_entities = cluster.get("shared_entity_names") or []
        if shared_entities:
            return " / ".join(str(name).strip() for name in shared_entities[:2] if str(name).strip())

        track_hint = str(cluster.get("track_hint") or "").strip()
        if track_hint:
            return track_hint

        representative = cluster.get("representative") or {}
        return self._post_topic(representative) or "general"

    def _vertical_compress_posts(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        clusters: Dict[str, Dict[str, Any]] = {}
        for post in sorted(posts, key=self._post_sort_key):
            cluster_key = self._vertical_cluster_key(post)
            cluster = clusters.setdefault(
                cluster_key,
                {
                    "key": cluster_key,
                    "posts": [],
                    "post_ids": [],
                },
            )
            cluster["posts"].append(post)
            post_id = str(post.get("id") or "")
            if post_id and post_id not in cluster["post_ids"]:
                cluster["post_ids"].append(post_id)

        compressed: List[Dict[str, Any]] = []
        for cluster_key, cluster in clusters.items():
            cluster_posts = sorted(cluster["posts"], key=self._post_sort_key)
            representative = cluster_posts[0] if cluster_posts else {}
            story_titles = self._vertical_story_titles(representative)
            if not story_titles:
                story_titles = self._merge_cluster_story_titles(cluster_posts)
            entity_names = self._vertical_entity_names(representative)
            if not entity_names:
                entity_names = self._merge_cluster_entity_names(cluster_posts)
            track_hint = (
                story_titles[0]
                if story_titles
                else " / ".join(entity_names[:2])
                if entity_names
                else self._post_topic(representative)
            )
            compressed.append(
                {
                    "key": cluster_key,
                    "posts": cluster_posts,
                    "representative": representative,
                    "post_ids": [str(post.get("id")) for post in cluster_posts if post.get("id")],
                    "story_titles": story_titles,
                    "entity_names": entity_names,
                    "shared_entity_names": self._merge_cluster_shared_entities(cluster_posts),
                    "track_hint": track_hint,
                    "raw_post_count": len(cluster_posts),
                    "date": self._vertical_post_date(representative),
                }
            )

        return compressed

    def _merge_cluster_story_titles(self, posts: List[Dict[str, Any]]) -> List[str]:
        counts: Counter[str] = Counter()
        display_by_key: Dict[str, str] = {}
        for post in posts:
            for title in post.get("vertical_story_titles") or []:
                text = str(title).strip()
                if not text:
                    continue
                key = text.lower()
                counts[key] += 1
                display_by_key.setdefault(key, text)
        ordered = [
            display_by_key[key]
            for key, _ in sorted(counts.items(), key=lambda item: (-item[1], display_by_key[item[0]].lower()))
        ]
        return ordered[:4]

    def _merge_cluster_entity_names(self, posts: List[Dict[str, Any]]) -> List[str]:
        counts: Counter[str] = Counter()
        display_by_key: Dict[str, str] = {}
        for post in posts:
            for name in post.get("vertical_entity_names") or []:
                text = str(name).strip()
                if not text:
                    continue
                key = text.lower()
                counts[key] += 1
                display_by_key.setdefault(key, text)
        ordered = [
            display_by_key[key]
            for key, _ in sorted(counts.items(), key=lambda item: (-item[1], display_by_key[item[0]].lower()))
        ]
        return ordered[:4]

    def _merge_cluster_shared_entities(self, posts: List[Dict[str, Any]]) -> List[str]:
        counts: Counter[str] = Counter()
        display_by_key: Dict[str, str] = {}
        for post in posts:
            for name in post.get("vertical_entity_names") or []:
                text = str(name).strip()
                if not text:
                    continue
                key = text.lower()
                counts[key] += 1
                display_by_key.setdefault(key, text)
        ordered = [
            display_by_key[key]
            for key, count in sorted(counts.items(), key=lambda item: (-item[1], display_by_key[item[0]].lower()))
            if count > 1
        ]
        return ordered[:4]

    def _date_distance_days(self, start: str, end: str) -> int:
        try:
            start_dt = datetime.fromisoformat(start[:10])
            end_dt = datetime.fromisoformat(end[:10])
        except ValueError:
            return 0
        return abs((end_dt - start_dt).days)

    def _normalize_vertical_text(self, value: str) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        return text
