"""Lightweight deterministic language detection for evidence enrichment."""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, Iterable, Tuple


TOKEN_RE = re.compile(r"[A-Za-z\u00C0-\u024F\u0400-\u04FF\u10A0-\u10FF']+")
SCRIPT_RE = {
    "ka": re.compile(r"[\u10A0-\u10FF]"),
    "ru": re.compile(r"[\u0400-\u04FF]"),
    "uk": re.compile(r"[\u0400-\u04FF]"),
}

STOPWORDS = {
    "en": {
        "the", "and", "to", "of", "in", "for", "on", "with", "is", "are", "this", "that",
        "it", "as", "be", "at", "by", "from", "or", "an", "was", "were", "not", "have", "has",
    },
    "es": {
        "el", "la", "de", "y", "en", "que", "los", "del", "se", "las", "por", "un", "para",
        "con", "no", "una", "es", "al", "lo", "como",
    },
    "fr": {
        "le", "la", "les", "de", "des", "et", "en", "du", "un", "une", "pour", "que", "est",
        "dans", "par", "sur", "pas", "plus", "au", "aux",
    },
    "de": {
        "der", "die", "das", "und", "ist", "in", "den", "von", "zu", "mit", "auf", "für",
        "ein", "eine", "nicht", "dem", "des", "als", "auch",
    },
    "it": {
        "il", "la", "di", "e", "in", "che", "per", "un", "una", "del", "della", "con",
        "non", "si", "le", "al", "come", "più", "da",
    },
    "pt": {
        "o", "a", "de", "e", "que", "do", "da", "em", "para", "com", "não", "uma", "os",
        "as", "por", "é", "se", "mais", "como",
    },
    "ru": {
        "и", "в", "не", "на", "что", "это", "как", "для", "по", "из", "с", "к", "или",
        "но", "я", "он", "она", "мы", "вы", "они",
    },
    "uk": {
        "і", "в", "не", "на", "що", "це", "як", "для", "по", "з", "та", "або", "але",
        "я", "він", "вона", "ми", "ви", "вони",
    },
}

GEORGIAN_STOPWORDS = {"და", "არის", "რომ", "ეს", "არ", "თუ", "ან", "მე", "შენ", "ის"}


def detect_language(text: str | None) -> Dict[str, object]:
    """Detect a language code and confidence using simple script/stopword heuristics."""
    normalized = _normalize_text(text)
    if not normalized:
        return {"language_code": "und", "confidence": 0.0, "signals": {"reason": "empty"}}

    tokens = TOKEN_RE.findall(normalized)
    if len(tokens) < 2 and len(normalized) < 8:
        return {"language_code": "und", "confidence": 0.15, "signals": {"reason": "too_short"}}

    script_counts = _script_counts(normalized)
    total_letters = sum(script_counts.values()) or len(normalized)

    georgian_ratio = script_counts["ka"] / total_letters if total_letters else 0.0
    cyrillic_ratio = script_counts["cyrillic"] / total_letters if total_letters else 0.0

    if georgian_ratio >= 0.12:
        confidence = min(0.99, 0.72 + georgian_ratio * 1.5)
        return {"language_code": "ka", "confidence": round(confidence, 3), "signals": {"script": "georgian"}}

    if cyrillic_ratio >= 0.12:
        scores = {
            "ru": _score_stopwords(tokens, STOPWORDS["ru"]),
            "uk": _score_stopwords(tokens, STOPWORDS["uk"]),
        }
        code = max(scores, key=scores.get)
        score = scores[code]
        confidence = 0.72 + min(0.22, score * 0.12) + min(0.06, cyrillic_ratio * 0.2)
        if score == 0:
            code = "ru"
            confidence = 0.76 + min(0.12, cyrillic_ratio * 0.15)
        return {
            "language_code": code,
            "confidence": round(min(0.99, confidence), 3),
            "signals": {"script": "cyrillic", "scores": scores},
        }

    scores = {code: _score_stopwords(tokens, stopwords) for code, stopwords in STOPWORDS.items() if code not in {"ru", "uk"}}
    code = max(scores, key=scores.get)
    score = scores[code]

    if score == 0:
        ascii_ratio = _ascii_letter_ratio(normalized)
        if ascii_ratio >= 0.8:
            return {"language_code": "en", "confidence": 0.55, "signals": {"script": "latin", "fallback": "ascii"}}
        return {"language_code": "und", "confidence": 0.2, "signals": {"script": "latin", "scores": scores}}

    confidence = 0.68 + min(0.28, score * 0.18)
    return {
        "language_code": code,
        "confidence": round(min(0.99, confidence), 3),
        "signals": {"script": "latin", "scores": scores},
    }


def _normalize_text(text: str | None) -> str:
    if not text:
        return ""
    value = str(text).casefold()
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^\w\u00C0-\u024F\u0400-\u04FF\u10A0-\u10FF']+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _score_stopwords(tokens: Iterable[str], stopwords: set[str]) -> int:
    score = 0
    for token in tokens:
        if token in stopwords:
            score += 1
    return score


def _ascii_letter_ratio(text: str) -> float:
    if not text:
        return 0.0
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return 0.0
    ascii_letters = sum(1 for char in letters if char.isascii())
    return ascii_letters / len(letters)


def _script_counts(text: str) -> Dict[str, int]:
    counts = Counter({"ka": 0, "cyrillic": 0})
    for char in text:
        if SCRIPT_RE["ka"].match(char):
            counts["ka"] += 1
        elif SCRIPT_RE["ru"].match(char):
            counts["cyrillic"] += 1
    return counts
