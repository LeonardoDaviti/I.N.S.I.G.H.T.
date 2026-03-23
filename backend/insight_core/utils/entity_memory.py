"""Deterministic helpers for entity memory extraction and post pivots."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List

from .content_fingerprints import normalize_text, strip_html
from .language_detection import detect_language

ENTITY_MEMORY_VERSION = "entity-memory-v1"
ENTITY_MENTION_EXTRACTOR_NAME = "deterministic_entity_extractor"
ENTITY_MENTION_EXTRACTOR_VERSION = "entity-mentions-v1"
ENTITY_PIVOT_VERSION = "entity-pivot-v1"

HANDLE_RE = re.compile(r"(?<!\w)@([A-Za-z0-9_]{2,32})\b")
HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_]{1,64})\b")
MULTIWORD_ENTITY_RE = re.compile(
    r"\b(?:"
    r"(?:[A-Z][a-z]+(?:[A-Z][a-zA-Z]+)?|[A-Z][A-Za-z0-9]{3,}|[A-Z]{4,})"
    r"(?:\s+(?:[A-Z][a-z]+(?:[A-Z][a-zA-Z]+)?|[A-Z][A-Za-z0-9]{3,}|[A-Z]{4,})){1,3}"
    r")\b"
)
SINGLE_ENTITY_RE = re.compile(
    r"\b(?:[A-Z][a-z]+(?:[A-Z][a-zA-Z]+)?|[A-Z][A-Za-z0-9]{3,}|[A-Z]{4,})\b"
)

COMMON_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have",
    "he", "her", "his", "i", "if", "in", "into", "is", "it", "its", "just", "more", "most",
    "new", "not", "of", "on", "or", "our", "out", "over", "she", "so", "than", "that",
    "the", "their", "them", "there", "these", "this", "those", "they", "to", "too", "under", "up",
    "very", "was", "we", "were", "what", "when", "where", "which", "who", "with", "you",
    "your", "today", "tomorrow", "yesterday", "first", "last", "big", "small", "great",
    "good", "bad", "latest", "only", "more", "less", "very", "much", "many",
}

NON_ENTITY_TERMS = {
    "answer",
    "answers",
    "article",
    "articles",
    "beat",
    "beats",
    "blog",
    "blogs",
    "comment",
    "comments",
    "discussion",
    "discussions",
    "example",
    "examples",
    "feed",
    "feeds",
    "headline",
    "headlines",
    "here",
    "note",
    "notes",
    "page",
    "pages",
    "post",
    "posts",
    "question",
    "questions",
    "section",
    "sections",
    "signal",
    "signals",
    "story",
    "stories",
    "tag",
    "tags",
    "thread",
    "threads",
    "update",
    "updates",
}

TECH_ACRONYM_BLOCKLIST = {
    "ai", "api", "cpu", "css", "db", "gpu", "gui", "html", "http", "https", "ide", "json",
    "ml", "ram", "sdk", "seo", "ssh", "sql", "ui", "url", "xml",
}

ORG_HINTS = {
    "agency",
    "association",
    "board",
    "commission",
    "company",
    "corp",
    "corporation",
    "council",
    "department",
    "foundation",
    "group",
    "inc",
    "institute",
    "lab",
    "labs",
    "limited",
    "llc",
    "ltd",
    "ministry",
    "network",
    "org",
    "office",
    "organization",
    "research",
    "school",
    "studio",
    "systems",
    "team",
    "technologies",
    "technology",
    "university",
}

PERSON_TITLES = {
    "dr",
    "mr",
    "mrs",
    "ms",
    "prof",
    "professor",
}

FIRST_SENTENCE_RE = re.compile(r"^(.*?[\.\!\?])(?:\s+|$)", re.DOTALL)


def build_post_memory_fields(post: Dict[str, Any]) -> Dict[str, Any]:
    """Build deterministic post memory fields for phase-0 storage."""
    title = _string_value(post.get("title"))
    content = _string_value(post.get("content"))
    content_html = _string_value(post.get("content_html"))
    summary_source = _derive_summary_source(content, content_html)
    return {
        "title_original": title or None,
        "body_original": content or None,
        "title_pivot": normalize_text(title) or None,
        "summary_pivot": normalize_text(summary_source) or None,
        "title_pivot_version": ENTITY_PIVOT_VERSION,
        "summary_pivot_version": ENTITY_PIVOT_VERSION,
    }


def extract_entity_mentions(post: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract conservative mention candidates from a post."""
    title = _string_value(post.get("title"))
    content = _string_value(post.get("content"))
    content_html = _string_value(post.get("content_html"))
    body = strip_html(content_html) or content
    detected_language = _string_value(post.get("language_code")) or detect_language("\n".join(
        part for part in [title, body] if part
    )).get("language_code") or "und"
    source_hint = _string_value(post.get("source")) or _string_value(post.get("handle_or_url")) or _string_value(post.get("platform"))

    candidates: List[Dict[str, Any]] = []
    candidates.extend(_extract_from_text(title, "title", detected_language, source_hint))
    candidates.extend(_extract_from_text(body, "body", detected_language, source_hint))

    return _dedupe_mentions(candidates)


def normalize_entity_name(value: str | None) -> str:
    """Normalize entity names for exact-match comparison."""
    if not value:
        return ""

    text = unicodedata.normalize("NFKC", str(value))
    text = text.replace("@", " ").replace("#", " ")
    text = text.replace("’", "'")
    text = re.sub(r"[^\w\u00C0-\u024F\u0400-\u04FF\u10A0-\u10FF]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def is_meaningful_entity_name(value: str | None) -> bool:
    """Return whether a candidate mention looks like a real entity label."""
    normalized = normalize_entity_name(value)
    if not normalized:
        return False

    tokens = [token for token in normalized.split() if token]
    if not tokens:
        return False

    if normalized in COMMON_STOPWORDS or normalized in NON_ENTITY_TERMS:
        return False

    if normalized in TECH_ACRONYM_BLOCKLIST and normalized != "ai":
        return False

    if all(token in COMMON_STOPWORDS or token in NON_ENTITY_TERMS for token in tokens):
        return False

    return True


def guess_entity_type(mention_text: str, *, role: str | None = None) -> str:
    """Conservatively guess the entity type for a mention."""
    normalized = normalize_entity_name(mention_text)
    if not normalized:
        return "unknown"

    if mention_text.startswith("@"):
        return "unknown"

    tokens = normalized.split()
    if not tokens:
        return "unknown"

    if any(token in ORG_HINTS for token in tokens):
        return "organization"

    if any(token in PERSON_TITLES for token in tokens):
        return "person"

    if len(tokens) >= 2:
        if all(_looks_like_name_token(token) for token in tokens):
            return "person"
        return "organization"

    token = tokens[0]
    if _looks_like_organization_token(mention_text, token):
        return "organization"

    if len(token) >= 5 and is_meaningful_entity_name(mention_text):
        if role == "title" or mention_text[:1].isupper():
            return "organization"

    if role == "title" and len(token) >= 4 and token not in COMMON_STOPWORDS:
        return "organization"

    return "unknown"


def detect_script(value: str | None) -> str:
    """Detect the dominant script for a mention."""
    if not value:
        return "unknown"

    has_latin = False
    has_cyrillic = False
    has_georgian = False
    for char in str(value):
        codepoint = ord(char)
        if 0x10A0 <= codepoint <= 0x10FF:
            has_georgian = True
        elif 0x0400 <= codepoint <= 0x04FF:
            has_cyrillic = True
        elif char.isalpha() and char.isascii():
            has_latin = True

    scripts = [flag for flag, active in [("latin", has_latin), ("cyrillic", has_cyrillic), ("georgian", has_georgian)] if active]
    if not scripts:
        return "unknown"
    if len(scripts) > 1:
        return "mixed"
    return scripts[0]


def _extract_from_text(text: str, role: str, language_code: str, source_hint: str | None) -> List[Dict[str, Any]]:
    if not text:
        return []

    candidates: List[Dict[str, Any]] = []
    for match in HANDLE_RE.finditer(text):
        mention_text = f"@{match.group(1)}"
        candidates.append(_build_candidate(
            mention_text,
            role,
            match.start(),
            match.end(),
            language_code,
            source_hint,
            "handle",
            0.96,
        ))

    for match in HASHTAG_RE.finditer(text):
        mention_text = f"#{match.group(1)}"
        normalized = normalize_entity_name(mention_text)
        if not normalized or normalized in COMMON_STOPWORDS:
            continue
        candidates.append(_build_candidate(
            mention_text,
            role,
            match.start(),
            match.end(),
            language_code,
            source_hint,
            "hashtag",
            0.66 if len(normalized) > 3 else 0.55,
        ))

    for match in MULTIWORD_ENTITY_RE.finditer(text):
        mention_text = match.group(0).strip()
        if _should_skip_mention(mention_text):
            continue
        candidates.append(_build_candidate(
            mention_text,
            role,
            match.start(),
            match.end(),
            language_code,
            source_hint,
            "multiword",
            0.88,
        ))

    for match in SINGLE_ENTITY_RE.finditer(text):
        mention_text = match.group(0).strip()
        if _should_skip_mention(mention_text):
            continue
        if _should_skip_single_entity_match(mention_text, role=role, text=text):
            continue
        candidates.append(_build_candidate(
            mention_text,
            role,
            match.start(),
            match.end(),
            language_code,
            source_hint,
            "single",
            0.76 if _looks_like_name_token(mention_text.casefold()) else 0.7,
        ))

    return candidates


def _build_candidate(
    mention_text: str,
    role: str,
    start: int,
    end: int,
    language_code: str,
    source_hint: str | None,
    pattern: str,
    confidence: float,
) -> Dict[str, Any]:
    normalized = normalize_entity_name(mention_text)
    return {
        "mention_text": mention_text,
        "normalized_mention": normalized,
        "language_code": language_code or "und",
        "entity_type_predicted": guess_entity_type(mention_text, role=role),
        "role": role,
        "char_start": start,
        "char_end": end,
        "extractor_confidence": round(float(confidence), 3),
        "extractor_name": ENTITY_MENTION_EXTRACTOR_NAME,
        "extractor_version": ENTITY_MENTION_EXTRACTOR_VERSION,
        "metadata": {
            "pattern": pattern,
            "source_field": role,
            "source_hint": source_hint,
            "pivot": normalize_text(mention_text) or None,
            "script": detect_script(mention_text),
        },
    }


def _dedupe_mentions(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    by_field: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        by_field.setdefault(candidate["role"], []).append(candidate)

    for role, role_candidates in by_field.items():
        accepted: List[Dict[str, Any]] = []
        ordered = sorted(
            role_candidates,
            key=lambda item: (
                -float(item["extractor_confidence"]),
                -(item["char_end"] - item["char_start"]),
                item["char_start"],
                item["char_end"],
                item["mention_text"].casefold(),
            ),
        )
        for candidate in ordered:
            if any(_spans_overlap(candidate["char_start"], candidate["char_end"], existing["char_start"], existing["char_end"]) for existing in accepted):
                continue
            accepted.append(candidate)
        deduped.extend(sorted(accepted, key=lambda item: (item["char_start"], item["char_end"])))

    return deduped


def _spans_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a < end_b and start_b < end_a


def _should_skip_mention(mention_text: str) -> bool:
    normalized = normalize_entity_name(mention_text)
    if not normalized:
        return True

    if not is_meaningful_entity_name(mention_text):
        return True

    if len(normalized) < 4 and normalized not in {"ai"}:
        return True

    return False


def _should_skip_single_entity_match(mention_text: str, *, role: str, text: str) -> bool:
    normalized = normalize_entity_name(mention_text)
    if not normalized:
        return True

    if role == "title":
        return False

    if _has_internal_capitalization(mention_text):
        return False

    if mention_text.isascii() and mention_text.isupper() and len(mention_text) >= 4:
        return False

    if _count_entity_occurrences(text, normalized) >= 2:
        return False

    return True


def _looks_like_name_token(token: str) -> bool:
    if not token:
        return False
    if token in COMMON_STOPWORDS:
        return False
    if token in PERSON_TITLES:
        return True
    if token in ORG_HINTS:
        return True
    if token.isascii() and token.isupper() and len(token) >= 4:
        return True
    if _has_internal_capitalization(token):
        return True
    if token[:1].isupper() and token[1:].islower() and len(token) >= 4:
        return True
    return False


def _looks_like_organization_token(mention_text: str, token: str) -> bool:
    if token in ORG_HINTS:
        return True
    if token.isascii() and token.isupper() and len(token) >= 4:
        return True
    if _has_internal_capitalization(mention_text):
        return True
    return False


def _has_internal_capitalization(value: str) -> bool:
    return any(char.isupper() for char in value[1:]) and any(char.islower() for char in value)


def _derive_summary_source(content: str, content_html: str) -> str:
    text = strip_html(content_html) or content or ""
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ""

    match = FIRST_SENTENCE_RE.match(text)
    if match:
        return match.group(1).strip()
    return text[:280].strip()


def _string_value(value: Any) -> str:
    return "" if value is None else str(value)


def _count_entity_occurrences(text: str, normalized: str) -> int:
    normalized_text = normalize_entity_name(text)
    if not normalized_text or not normalized:
        return 0
    pattern = re.compile(rf"(?<!\w){re.escape(normalized)}(?!\w)")
    return len(pattern.findall(normalized_text))
