"""The fields computed for every post on save: content hash, URLs, host and language."""

from __future__ import annotations

from typing import Any, Dict

from .content_fingerprints import hash_post_content, strip_html
from .language_detection import detect_language
from .url_normalization import canonicalize_url, extract_url_host, normalize_url


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
