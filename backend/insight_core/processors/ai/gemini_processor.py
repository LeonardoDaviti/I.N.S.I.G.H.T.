"""
Gemini processor for daily briefings and topic modeling.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional


class GeminiProcessor:
    """Thin async wrapper around the Gemini text generation API."""

    def __init__(self):
        self.api_key: Optional[str] = None
        self.model = "gemini-2.0-flash"
        self.temperature = 0.1
        self.is_setup = False
        self.logger = logging.getLogger(__name__)

    def setup_processor(self) -> bool:
        """Configure Gemini using GEMINI_API_KEY."""
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            self.logger.error("GEMINI_API_KEY environment variable not set")
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
        """No-op kept for compatibility with existing call sites."""
        if not self.is_setup:
            raise RuntimeError("Gemini processor is not configured")

    async def disconnect(self) -> None:
        """No-op kept for compatibility with existing call sites."""
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
- Call out source names when useful
- Keep the whole briefing compact and high-signal
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
- Do not invent post IDs.
- Keep titles concrete and specific.

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

    def analyze_single_post(self, post: Dict[str, Any]) -> Dict[str, Any]:
        """Summarize a single post."""
        if not self.is_setup:
            return {"success": False, "error": "Processor not setup. Call setup_processor() first"}

        prompt = f"""
Summarize this post in 2-4 sentences of markdown.

Source: {post.get("source", "unknown")}
Title: {post.get("title", "")}
Content:
{post.get("content", "")[:3000]}
"""
        try:
            summary = self._generate_text_sync(prompt)
            return {"success": True, "summary": summary}
        except Exception as exc:
            return {"success": False, "error": f"Analysis failed: {exc}"}

    def ask_single_post(self, post: Dict[str, Any], question: str) -> Dict[str, Any]:
        """Answer a question about a single post."""
        if not self.is_setup:
            return {"success": False, "error": "Processor not setup. Call setup_processor() first"}

        prompt = f"""
Answer the user's question using only this post.
If the answer is not present, say that clearly.

Source: {post.get("source", "unknown")}
Title: {post.get("title", "")}
Content:
{post.get("content", "")[:3000]}

Question: {question}
"""
        try:
            answer = self._generate_text_sync(prompt)
            return {"success": True, "answer": answer}
        except Exception as exc:
            return {"success": False, "error": f"Question answering failed: {exc}"}

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

    async def _generate_text(self, prompt: str) -> str:
        return await asyncio.to_thread(self._generate_text_sync, prompt)

    def _generate_text_sync(self, prompt: str) -> str:
        if not self.is_setup or not self.api_key:
            raise RuntimeError("Gemini processor is not configured")

        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ]
                }
            ],
            "generationConfig": {
                "temperature": self.temperature,
            },
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                response_json = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Gemini HTTP {exc.code}: {error_body[:500]}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini request failed: {exc.reason}") from exc

        candidates = response_json.get("candidates", [])
        text_parts = []
        for candidate in candidates:
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if "text" in part:
                    text_parts.append(part["text"])

        text = "\n".join(text_parts).strip()
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return self._clean_markdown_response(text)

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
