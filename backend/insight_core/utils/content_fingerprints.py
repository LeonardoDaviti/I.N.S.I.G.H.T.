"""Cheap deterministic content fingerprints for evidence processing."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Any, Dict, Optional


HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def strip_html(value: str | None) -> str:
    """Remove HTML tags and normalize entities to plain text."""
    if not value:
        return ""
    text = html.unescape(str(value))
    text = HTML_TAG_RE.sub(" ", text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def normalize_text(value: str | None) -> str:
    """Normalize text for deterministic fingerprinting."""
    if not value:
        return ""

    text = html.unescape(str(value))
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip().casefold()


def hash_text(value: str | None) -> str:
    """Hash normalized text with SHA-256."""
    normalized = normalize_text(value)
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def hash_post_content(title: str | None, content: str | None, content_html: str | None) -> str:
    """Hash a post's textual payload for update tracking and dedupe seeds."""
    parts = [
        normalize_text(title),
        normalize_text(content),
        normalize_text(strip_html(content_html)),
    ]
    payload = "\n".join(part for part in parts if part)
    if not payload:
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_post_fingerprints(
    title: str | None,
    content: str | None,
    content_html: str | None,
) -> Dict[str, str]:
    """Return deterministic title and content fingerprints."""
    return {
        "title_hash": hash_text(title),
        "content_hash": hash_post_content(title, content, content_html),
    }
