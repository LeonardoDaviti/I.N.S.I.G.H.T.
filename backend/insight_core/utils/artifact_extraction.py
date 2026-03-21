"""Artifact extraction helpers for evidence foundation phase 2."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .url_normalization import canonicalize_url, extract_url_host, normalize_url

URL_RE = re.compile(r"(?i)\bhttps?://[^\s<>\")']+|\bwww\.[^\s<>\")']+")

ARTIFACT_TYPES = {
    "paper",
    "release_note",
    "repo",
    "issue",
    "official_post",
    "video",
    "article",
    "other",
}


def extract_artifacts(post: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract explicit artifact references from a post."""
    artifacts: List[Dict[str, Any]] = []
    seen: set[str] = set()
    post_url = post.get("url") if isinstance(post, dict) else None
    post_title = (post.get("title") or "").strip() if isinstance(post, dict) else ""
    post_content = (post.get("content") or "").strip() if isinstance(post, dict) else ""
    post_html = (post.get("content_html") or "").strip() if isinstance(post, dict) else ""

    ordered_sources = [
        ("post_url", post_url, True),
        ("title", post_title, False),
        ("content", post_content, False),
        ("content_html", post_html, False),
    ]

    for source_name, value, primary in ordered_sources:
        if not isinstance(value, str) or not value.strip():
            continue
        urls = _extract_urls(value, source_name == "content_html")
        if source_name == "post_url" and value.strip():
            urls = [value.strip(), *urls]
        for url in urls:
            artifact = _artifact_from_url(
                url,
                post_title=post_title,
                post_platform=(post.get("platform") or "").lower() if isinstance(post, dict) else "",
                source_name=source_name,
                is_primary=primary and url == value.strip(),
            )
            if not artifact:
                continue
            key = artifact["normalized_url"]
            if key in seen:
                continue
            seen.add(key)
            artifacts.append(artifact)

    if artifacts:
        artifacts.sort(key=lambda item: (not item.get("is_primary", False), -float(item.get("confidence", 0))))
    return artifacts


def _extract_urls(value: str, html_mode: bool = False) -> List[str]:
    if not value:
        return []

    urls = set()
    for match in URL_RE.findall(value):
        cleaned = match.strip().rstrip(".,);]}>\"'")
        if cleaned.startswith("www."):
            cleaned = f"https://{cleaned}"
        urls.add(cleaned)

    if html_mode:
        for href in re.findall(r'(?i)\b(?:href|src)=["\']([^"\']+)["\']', value):
            cleaned = href.strip().rstrip(".,);]}>\"'")
            if cleaned.startswith("www."):
                cleaned = f"https://{cleaned}"
            urls.add(cleaned)

    return sorted(urls)


def _artifact_from_url(
    url: str,
    *,
    post_title: str,
    post_platform: str,
    source_name: str,
    is_primary: bool,
) -> Optional[Dict[str, Any]]:
    normalized = normalize_url(url)
    if not normalized:
        return None

    canonical = canonicalize_url(url) or normalized
    host = extract_url_host(url)
    artifact_type = _classify_artifact_type(url, host, post_platform)
    confidence = 0.95 if is_primary else 0.8
    if artifact_type in {"article", "official_post"}:
        confidence -= 0.02
    metadata = {
        "extracted_from": source_name,
        "post_platform": post_platform,
        "artifact_type_rule": "host_path",
        "extraction_version": "artifact-foundation-v1",
    }

    return {
        "artifact_type": artifact_type,
        "canonical_url": canonical,
        "normalized_url": normalized,
        "url_host": host,
        "display_title": post_title or None,
        "status": "active",
        "metadata": metadata,
        "confidence": round(confidence, 3),
        "relation_type": "announces" if is_primary else "links_to",
        "is_primary": is_primary,
        "source_url": url,
    }


def _classify_artifact_type(url: str, host: Optional[str], post_platform: str) -> str:
    host = (host or "").lower()
    parsed = urlparse(url if "://" in url else f"https://{url}")
    path = parsed.path or ""
    segments = [segment for segment in path.split("/") if segment]

    if host in {"youtube.com", "youtu.be"}:
        return "video"

    if host in {"arxiv.org", "doi.org", "openreview.net"}:
        return "paper"

    if host in {"github.com"}:
        if "issues" in segments or "pull" in segments:
            return "issue"
        if "releases" in segments:
            return "release_note"
        if len(segments) >= 2:
            return "repo"
        return "other"

    if host in {"t.me", "telegram.org"} or host.endswith("telegram.local") or "telegram" in host:
        return "official_post"

    if host.endswith("reddit.com"):
        return "official_post"

    if any(domain in host for domain in {"substack.com", "medium.com", "blog", "news"}):
        return "article"

    if post_platform == "youtube":
        return "video"
    if post_platform in {"telegram", "reddit"}:
        return "official_post"
    if post_platform == "rss":
        return "article"

    return "article" if path else "other"
