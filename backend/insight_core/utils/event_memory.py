"""Deterministic helpers for typed event extraction and memory pivots."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from .content_fingerprints import normalize_text, strip_html
from .language_detection import detect_language

EVENT_MEMORY_VERSION = "event-memory-v1"
EVENT_EVENT_EXTRACTOR_NAME = "deterministic_event_extractor"
EVENT_EVENT_EXTRACTOR_VERSION = "event-events-v1"

EVENT_TYPE_ORDER = [
    "release_launch",
    "funding",
    "partnership",
    "acquisition",
    "leadership_change",
    "policy_regulation",
    "security_incident",
]

EVENT_LABELS = {
    "release_launch": "Launch / Release",
    "funding": "Funding",
    "partnership": "Partnership",
    "acquisition": "Acquisition",
    "leadership_change": "Leadership Change",
    "policy_regulation": "Policy / Regulation",
    "security_incident": "Security Incident",
}

EVENT_KEYWORDS: Dict[str, List[Tuple[str, float]]] = {
    "release_launch": [
        ("launch", 0.20),
        ("launched", 0.20),
        ("launches", 0.20),
        ("release", 0.16),
        ("released", 0.16),
        ("ships", 0.18),
        ("ship", 0.16),
        ("debut", 0.16),
        ("announce", 0.14),
        ("announced", 0.14),
    ],
    "funding": [
        ("funding", 0.24),
        ("raise", 0.22),
        ("raises", 0.22),
        ("raised", 0.22),
        ("investment", 0.20),
        ("invests", 0.18),
        ("invested", 0.18),
        ("series a", 0.22),
        ("series b", 0.22),
        ("series c", 0.22),
        ("seed round", 0.20),
    ],
    "partnership": [
        ("partnership", 0.24),
        ("partner", 0.20),
        ("partners", 0.20),
        ("collaboration", 0.18),
        ("collaborate", 0.18),
        ("agreement", 0.16),
        ("allianc", 0.16),
    ],
    "acquisition": [
        ("acquire", 0.24),
        ("acquires", 0.24),
        ("acquired", 0.24),
        ("acquisition", 0.24),
        ("buy", 0.18),
        ("bought", 0.18),
        ("merger", 0.18),
    ],
    "leadership_change": [
        ("appoint", 0.20),
        ("appointed", 0.20),
        ("joins as", 0.20),
        ("named", 0.16),
        ("resign", 0.22),
        ("resigned", 0.22),
        ("steps down", 0.22),
        ("promote", 0.18),
    ],
    "policy_regulation": [
        ("policy", 0.20),
        ("regulation", 0.22),
        ("regulator", 0.20),
        ("bill", 0.18),
        ("law", 0.18),
        ("ban", 0.18),
        ("rules", 0.16),
        ("legal", 0.16),
    ],
    "security_incident": [
        ("breach", 0.24),
        ("hack", 0.22),
        ("hacked", 0.22),
        ("vulnerability", 0.20),
        ("incident", 0.18),
        ("outage", 0.18),
        ("leak", 0.18),
        ("attack", 0.18),
        ("exploit", 0.18),
    ],
}

_FIRST_SENTENCE_RE = re.compile(r"^(.*?[\.\!\?])(?:\s+|$)", re.DOTALL)


def extract_event_candidates(post: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract conservative typed event candidates from a post."""
    title = _string_value(post.get("title"))
    content = _string_value(post.get("content"))
    content_html = _string_value(post.get("content_html"))
    body = strip_html(content_html) or content
    combined = "\n".join(part for part in [title, body] if part)
    if not combined.strip():
        return []

    detected_language = _string_value(post.get("language_code")) or detect_language(combined).get("language_code") or "und"
    now = datetime.now(timezone.utc)
    occurred_at = _coerce_datetime(post.get("published_at") or post.get("date") or post.get("fetched_at"))
    source_hint = _string_value(post.get("source_display_name")) or _string_value(post.get("source")) or _string_value(post.get("handle_or_url"))

    title_norm = normalize_text(title)
    body_norm = normalize_text(body)
    candidates: List[Dict[str, Any]] = []

    for event_type in EVENT_TYPE_ORDER:
        score, matches = _score_event_type(title_norm, body_norm, event_type)
        if score < 0.15:
            continue

        event_title = _build_event_title(title, body, event_type)
        normalized_event_key = normalize_text(f"{event_type} {event_title}") or normalize_text(event_type)
        evidence_snippet = _build_evidence_snippet(title, body)
        candidates.append(
            {
                "event_type": event_type,
                "title": event_title,
                "normalized_event_key": normalized_event_key or None,
                "status": "observed",
                "confidence": round(min(0.99, 0.45 + score), 3),
                "occurred_at": occurred_at,
                "first_seen_at": now,
                "last_seen_at": now,
                "evidence_snippet": evidence_snippet,
                "extractor_name": EVENT_EVENT_EXTRACTOR_NAME,
                "extractor_version": EVENT_EVENT_EXTRACTOR_VERSION,
                "metadata": {
                    "matches": matches,
                    "language_code": detected_language,
                    "source_hint": source_hint,
                    "source_title": title[:280] if title else None,
                },
            }
        )

    if not candidates:
        return []

    candidates.sort(key=lambda item: (-float(item["confidence"]), len(item["title"] or ""), item["event_type"]))
    return [candidates[0]]


def build_post_event_fields(post: Dict[str, Any]) -> Dict[str, Any]:
    """Build deterministic event memory fields for a post."""
    return {
        "event_candidates": extract_event_candidates(post),
    }


def humanize_event_type(event_type: str) -> str:
    return EVENT_LABELS.get(event_type, event_type.replace("_", " ").title())


def _score_event_type(title_norm: str, body_norm: str, event_type: str) -> Tuple[float, List[str]]:
    score = 0.0
    matches: List[str] = []
    for keyword, weight in EVENT_KEYWORDS[event_type]:
        matched = False
        if keyword in title_norm:
            score += weight
            matches.append(f"title:{keyword}")
            matched = True
        if keyword in body_norm:
            score += weight * 0.6
            matches.append(f"body:{keyword}")
            matched = True
        if matched and " " not in keyword and len(keyword) >= 5:
            score += 0.02
    if title_norm and matches:
        score += 0.04
    return score, matches


def _build_event_title(title: str, body: str, event_type: str) -> str:
    if title.strip():
        return title.strip()[:180]

    snippet = _build_evidence_snippet(title, body)
    if snippet:
        return snippet[:180]

    return humanize_event_type(event_type)


def _build_evidence_snippet(title: str, body: str) -> str:
    combined = "\n".join(part for part in [title, body] if part)
    combined = re.sub(r"\s+", " ", combined).strip()
    if not combined:
        return ""

    match = _FIRST_SENTENCE_RE.match(combined)
    if match:
        return match.group(1).strip()[:280]
    return combined[:280]


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _string_value(value: Any) -> str:
    return "" if value is None else str(value)
