"""High-level post evidence field builder."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from .content_fingerprints import build_post_fingerprints, strip_html
from .language_detection import detect_language
from .url_normalization import canonicalize_url, extract_url_host, normalize_url

EVIDENCE_NORMALIZATION_VERSION = "evidence-foundation-v1"


def build_post_evidence_fields(post: Dict[str, Any]) -> Dict[str, Any]:
    """Build normalized evidence fields for a single post."""
    title = post.get("title") if isinstance(post, dict) else None
    content = post.get("content") if isinstance(post, dict) else None
    content_html = post.get("content_html") if isinstance(post, dict) else None
    url = post.get("url") if isinstance(post, dict) else None
    raw_lang = post.get("lang") if isinstance(post, dict) else None

    fingerprints = build_post_fingerprints(title, content, content_html)
    normalized_url = normalize_url(url)
    canonical_url = canonicalize_url(url)
    url_host = extract_url_host(url)
    language_input = "\n".join(
        part
        for part in [title or "", content or "", strip_html(content_html)]
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
        "title_hash": fingerprints["title_hash"],
        "content_hash": fingerprints["content_hash"],
        "normalization_version": EVIDENCE_NORMALIZATION_VERSION,
        "enriched_at": datetime.now(timezone.utc),
        "language_signals": detected.get("signals", {}),
    }
