"""The fields computed for every post on save (content hash, URLs, host and language), and the
title the reader shows."""

from __future__ import annotations

import re
from typing import Any, Dict

from .content_fingerprints import clean_text, hash_post_content, strip_html
from .language_detection import detect_language
from .url_normalization import canonicalize_url, extract_url_host, normalize_url

TITLE_MAX_CHARS = 120
TITLE_MIN_SENTENCE_CHARS = 20
SENTENCE_END_RE = re.compile(r"[.!?…](?=\s|$)")
TRAILING_ELLIPSIS_RE = re.compile(r"(?:…|\.\.\.)\s*$")


def display_title(title: str | None, content: str | None) -> str:
    """The title the feed and the post page show; the stored title is never changed.

    The text is the title, or the body when the title is empty or is the body's start cut with
    "…" (a tweet, a Telegram post, a GitHub commit). Only its first non-empty line counts. A
    line over 120 characters is cut at its first sentence end (after 20 characters at least),
    else at the last space within 117 characters, with "…". Title and body are stored plain
    text, so nothing in them is read as a tag.
    """
    stored = (title or "").strip()
    cut = TRAILING_ELLIPSIS_RE.sub("", stored).strip()
    from_body = not stored or (
        cut != stored and bool(cut) and clean_text(content).startswith(clean_text(cut))
    )
    text = content if from_body else stored
    line = next((plain for plain in (clean_text(raw) for raw in (text or "").splitlines()) if plain), "")
    if len(line) <= TITLE_MAX_CHARS:
        return line
    sentence = SENTENCE_END_RE.search(line, TITLE_MIN_SENTENCE_CHARS - 1)
    if sentence and sentence.end() <= TITLE_MAX_CHARS:
        return line[: sentence.end()]
    head = line[: TITLE_MAX_CHARS - 3]
    space = head.rfind(" ")
    return (head[:space] if space > 0 else head).rstrip() + "…"


def build_post_fields(post: Dict[str, Any]) -> Dict[str, Any]:
    """Build the normalised fields reading and deduplication rely on, for one post."""
    title = post.get("title") if isinstance(post, dict) else None
    content = post.get("content") if isinstance(post, dict) else None
    content_html = post.get("content_html") if isinstance(post, dict) else None
    url = post.get("url") if isinstance(post, dict) else None
    raw_lang = post.get("lang") if isinstance(post, dict) else None

    normalized_url = normalize_url(url)
    canonical_url = canonicalize_url(url)
    url_host = extract_url_host(url)
    language_input = "\n".join(
        part
        for part in [title or "", content or "", strip_html(content_html, entities="decode_first")]
        if part
    )
    detected = detect_language(language_input)

    return {
        "lang": raw_lang,
        "language_code": detected["language_code"],
        "language_confidence": float(detected["confidence"] or 0.0),
        "normalized_url": normalized_url,
        "canonical_url": canonical_url or normalized_url,
        "url_host": url_host,
        "content_hash": hash_post_content(title, content, content_html),
    }
