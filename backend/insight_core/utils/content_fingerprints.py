"""Cheap deterministic content fingerprints: the post content hash, and strip_html (HTML to plain text)."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Literal


HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")
WHITESPACE_RE = re.compile(r"\s+")


def decode_entities(text: str) -> str:
    """HTML codes as characters ("That&#39;s" -> "That's"), twice for double-escaped text
    ("&amp;#39;"), which some feeds send."""
    for _ in range(2):
        decoded = html.unescape(text)
        if decoded == text:
            break
        text = decoded
    return text


def strip_html(value: str | None, *, entities: Literal["decode", "decode_first"] = "decode") -> str:
    """Plain text from HTML: every tag becomes a space, every run of whitespace one space.

    entities: "decode" decodes &amp; and friends once the tags are gone (decode_entities);
    "decode_first" decodes them once, before, so escaped tags (&lt;b&gt;) go too. The
    content hash uses "decode_first": what it returns is part of every stored hash.
    """
    if not value:
        return ""
    text = str(value)
    if entities == "decode_first":
        text = html.unescape(text)
    text = HTML_TAG_RE.sub(" ", text)
    if entities == "decode":
        text = decode_entities(text)
    return WHITESPACE_RE.sub(" ", text).strip()


def normalize_text(value: str | None) -> str:
    """Normalize text for deterministic fingerprinting."""
    if not value:
        return ""

    text = html.unescape(str(value))
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip().casefold()


def hash_post_content(title: str | None, content: str | None, content_html: str | None) -> str:
    """Hash a post's textual payload for update tracking and dedupe seeds."""
    parts = [
        normalize_text(title),
        normalize_text(content),
        normalize_text(strip_html(content_html, entities="decode_first")),
    ]
    payload = "\n".join(part for part in parts if part)
    if not payload:
        return ""
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
