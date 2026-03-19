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
from datetime import datetime
from typing import Any, Dict, List, Optional


DEFAULT_MODEL = "gemini-3.0-flash"
DEFAULT_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.0-flash",
]


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
            lines.append(f"Source: {source}")
            if title:
                lines.append(f"Title: {title}")
            lines.append(f"Key: {identifier}")
            lines.append(f"Content: {content}")
            lines.append("")

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
