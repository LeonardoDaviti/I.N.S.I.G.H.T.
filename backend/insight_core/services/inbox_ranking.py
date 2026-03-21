"""Deterministic ranking policy for analyst inbox items."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Iterable, List

INBOX_RANKING_VERSION = "inbox_v1"
STORY_SIGNAL_WINDOW_HOURS = 72
POST_SIGNAL_WINDOW_HOURS = 168
MIN_STORY_PRIORITY_SCORE = 30.0
MIN_POST_PRIORITY_SCORE = 25.0


def score_story_candidate(candidate: Dict[str, Any], now: datetime | None = None) -> Dict[str, Any] | None:
    """Score a story candidate with explicit reasons and transparent components."""
    signals = _unique_strings(candidate.get("signals") or [])
    if not signals:
        return None

    now = _normalize_datetime(now or datetime.now(timezone.utc))
    reference_time = _latest_datetime(
        candidate.get("last_seen_at"),
        candidate.get("latest_update_date"),
        candidate.get("first_seen_at"),
        candidate.get("created_at"),
    )

    novelty_score = _novelty_score(reference_time, now, STORY_SIGNAL_WINDOW_HOURS)
    post_count = int(candidate.get("post_count") or 0)
    update_count = int(candidate.get("update_count") or 0)
    latest_update_importance = float(candidate.get("latest_update_importance") or 0.0)
    anchor_confidence = float(candidate.get("anchor_confidence") or 0.0)
    source_priority_score = _normalize_priority(candidate.get("anchor_source_priority"))

    materiality_score = _clamp(
        0.40 * min(post_count / 4.0, 1.0)
        + 0.35 * min(update_count / 3.0, 1.0)
        + 0.25 * max(latest_update_importance, anchor_confidence),
        0.0,
        1.0,
    )
    evidence_score = _clamp(
        0.45 * min(post_count / 5.0, 1.0)
        + 0.25 * min(update_count / 4.0, 1.0)
        + 0.30 * anchor_confidence,
        0.0,
        1.0,
    )
    signal_bonus = min(0.25 * max(len(signals) - 1, 0), 0.35)
    priority_score = round(
        _clamp(
            100.0
            * (
                0.32 * novelty_score
                + 0.38 * materiality_score
                + 0.20 * evidence_score
                + 0.10 * source_priority_score
                + signal_bonus
            ),
            0.0,
            100.0,
        ),
        2,
    )

    reasons: List[Dict[str, Any]] = []
    if "new_story" in signals:
        reasons.append(
            _reason(
                "new_story",
                "New story",
                f"First seen {_time_ago(reference_time, now)}",
                0.45,
            )
        )
    if "story_update" in signals:
        reasons.append(
            _reason(
                "story_update",
                "Material update",
                _story_update_detail(candidate, now),
                0.40,
            )
        )

    if post_count:
        reasons.append(_reason("post_count", "Linked posts", f"{post_count} linked post(s)", 0.25))
    if update_count:
        reasons.append(_reason("update_count", "Story updates", f"{update_count} story update(s)", 0.25))
    if anchor_confidence:
        reasons.append(
            _reason(
                "anchor_confidence",
                "Anchor confidence",
                f"Anchor confidence {anchor_confidence:.2f}",
                0.20,
            )
        )
    if candidate.get("anchor_source_display_name"):
        reasons.append(
            _reason(
                "source_priority",
                "Source priority",
                f"{candidate.get('anchor_source_display_name')} priority {candidate.get('anchor_source_priority', 999)}",
                source_priority_score,
            )
        )

    reason_summary = _compose_story_summary(candidate, signals, post_count, update_count, latest_update_importance)
    metadata = _build_story_metadata(candidate, signals, now)

    return {
        "target_type": "story",
        "target_id": str(candidate["id"]),
        "priority_score": priority_score,
        "novelty_score": round(novelty_score, 4),
        "evidence_score": round(evidence_score, 4),
        "duplication_penalty": 0.0,
        "source_priority_score": round(source_priority_score, 4),
        "reason_summary": reason_summary,
        "reasons": reasons,
        "metadata": metadata,
        "signals": signals,
    }


def score_post_candidate(
    candidate: Dict[str, Any],
    now: datetime | None = None,
    *,
    stories_present: bool = False,
) -> Dict[str, Any] | None:
    """Score a post candidate with explicit reasons and transparent components."""
    if stories_present and int(candidate.get("story_link_count") or 0) > 0:
        return None

    now = _normalize_datetime(now or datetime.now(timezone.utc))
    reference_time = _latest_datetime(candidate.get("published_at"), candidate.get("fetched_at"), candidate.get("created_at"))

    novelty_score = _novelty_score(reference_time, now, POST_SIGNAL_WINDOW_HOURS)
    artifact_count = int(candidate.get("artifact_count") or 0)
    relation_count = int(candidate.get("relation_count") or 0)
    duplicate_relation_count = int(candidate.get("duplicate_relation_count") or 0)
    story_link_count = int(candidate.get("story_link_count") or 0)
    source_priority_score = _normalize_priority(candidate.get("source_priority"))
    language_confidence = float(candidate.get("language_confidence") or 0.0)

    evidence_score = _clamp(
        0.30
        + 0.30 * min(artifact_count / 3.0, 1.0)
        + 0.20 * min(relation_count / 5.0, 1.0)
        + 0.20 * min(language_confidence or 0.5, 1.0),
        0.0,
        1.0,
    )
    duplication_penalty = 1.0 if duplicate_relation_count > 0 else 0.0
    story_link_penalty = 0.0 if not stories_present else 1.0 if story_link_count > 0 else 0.0
    priority_score = round(
        max(
            0.0,
            100.0
            * (
                0.50 * novelty_score
                + 0.28 * evidence_score
                + 0.22 * source_priority_score
                - 0.55 * duplication_penalty
                - 0.20 * story_link_penalty
            ),
        ),
        2,
    )

    reasons: List[Dict[str, Any]] = []
    reasons.append(
        _reason(
            "recent_post",
            "Recent post",
            f"Published {_time_ago(reference_time, now)}",
            novelty_score,
        )
    )
    if candidate.get("source_display_name"):
        reasons.append(
            _reason(
                "source_priority",
                "Source priority",
                f"{candidate.get('source_display_name')} priority {candidate.get('source_priority', 999)}",
                source_priority_score,
            )
        )
    if artifact_count:
        reasons.append(_reason("artifacts", "Evidence artifacts", f"{artifact_count} linked artifact(s)", 0.35))
    if relation_count:
        reasons.append(_reason("relations", "Evidence relations", f"{relation_count} linked relation(s)", 0.25))
    if duplicate_relation_count:
        reasons.append(
            _reason(
                "duplicate_relations",
                "Duplicate penalty",
                f"{duplicate_relation_count} duplicate-like relation(s) detected",
                -0.55,
            )
        )
    if stories_present and story_link_count:
        reasons.append(_reason("story_link", "Story link", f"Already linked to {story_link_count} story(s)", -0.20))

    reason_summary = _compose_post_summary(candidate, novelty_score, artifact_count, relation_count, stories_present, story_link_count)
    metadata = _build_post_metadata(candidate, now)

    return {
        "target_type": "post",
        "target_id": str(candidate["id"]),
        "priority_score": priority_score,
        "novelty_score": round(novelty_score, 4),
        "evidence_score": round(evidence_score, 4),
        "duplication_penalty": round(duplication_penalty, 4),
        "source_priority_score": round(source_priority_score, 4),
        "reason_summary": reason_summary,
        "reasons": reasons,
        "metadata": metadata,
        "signals": ["recent_post"],
    }


def _build_story_metadata(candidate: Dict[str, Any], signals: List[str], now: datetime) -> Dict[str, Any]:
    return {
        "ranking_version": INBOX_RANKING_VERSION,
        "signal_codes": signals,
        "signal_count": len(signals),
        "evaluated_at": now.isoformat(),
        "candidate": {
            "story_kind": candidate.get("story_kind"),
            "post_count": int(candidate.get("post_count") or 0),
            "update_count": int(candidate.get("update_count") or 0),
            "latest_update_date": _iso(candidate.get("latest_update_date")),
            "latest_update_importance": float(candidate.get("latest_update_importance") or 0.0),
            "anchor_confidence": float(candidate.get("anchor_confidence") or 0.0),
            "anchor_source_id": candidate.get("anchor_source_id"),
            "anchor_source_display_name": candidate.get("anchor_source_display_name"),
            "anchor_source_priority": int(candidate.get("anchor_source_priority") or 999),
        },
    }


def _build_post_metadata(candidate: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    return {
        "ranking_version": INBOX_RANKING_VERSION,
        "evaluated_at": now.isoformat(),
        "candidate": {
            "source_id": candidate.get("source_id"),
            "source_display_name": candidate.get("source_display_name"),
            "source_priority": int(candidate.get("source_priority") or 999),
            "artifact_count": int(candidate.get("artifact_count") or 0),
            "relation_count": int(candidate.get("relation_count") or 0),
            "duplicate_relation_count": int(candidate.get("duplicate_relation_count") or 0),
            "story_link_count": int(candidate.get("story_link_count") or 0),
            "language_confidence": float(candidate.get("language_confidence") or 0.0),
            "published_at": _iso(candidate.get("published_at")),
            "fetched_at": _iso(candidate.get("fetched_at")),
        },
    }


def _compose_story_summary(candidate: Dict[str, Any], signals: List[str], post_count: int, update_count: int, latest_update_importance: Any) -> str:
    bits: List[str] = []
    if "new_story" in signals:
        bits.append("New story")
    if "story_update" in signals:
        bits.append("Material update")
    if post_count:
        bits.append(f"{post_count} linked post(s)")
    if update_count:
        bits.append(f"{update_count} update(s)")
    if latest_update_importance:
        bits.append(f"latest update importance {float(latest_update_importance):.2f}")
    if candidate.get("anchor_source_display_name"):
        bits.append(f"anchor source {candidate.get('anchor_source_display_name')}")
    return "; ".join(bits) if bits else "Story candidate"


def _compose_post_summary(
    candidate: Dict[str, Any],
    novelty_score: float,
    artifact_count: int,
    relation_count: int,
    stories_present: bool,
    story_link_count: int,
) -> str:
    bits = ["Recent post"]
    if candidate.get("source_display_name"):
        bits.append(f"from {candidate.get('source_display_name')}")
    if novelty_score >= 0.75:
        bits.append("very recent")
    if artifact_count:
        bits.append(f"{artifact_count} evidence artifact(s)")
    if relation_count:
        bits.append(f"{relation_count} linked relation(s)")
    if stories_present and story_link_count:
        bits.append(f"already tied to {story_link_count} story(s)")
    return "; ".join(bits)


def _story_update_detail(candidate: Dict[str, Any], now: datetime) -> str:
    latest_update_date = _normalize_datetime(candidate.get("latest_update_date"))
    if latest_update_date is not None:
        return f"Latest update {_time_ago(latest_update_date, now)}"
    update_count = int(candidate.get("update_count") or 0)
    return f"{update_count} update(s) on record"


def _reason(code: str, label: str, detail: str, weight: float) -> Dict[str, Any]:
    return {
        "code": code,
        "label": label,
        "detail": detail,
        "weight": round(float(weight), 4),
    }


def _novelty_score(reference_time: datetime | None, now: datetime, window_hours: int) -> float:
    if reference_time is None:
        return 0.5
    hours = max((_normalize_datetime(now) - _normalize_datetime(reference_time)).total_seconds() / 3600.0, 0.0)
    return _clamp(1.0 - (hours / float(window_hours)), 0.0, 1.0)


def _normalize_priority(priority: Any) -> float:
    try:
        priority_value = int(priority if priority is not None else 999)
    except (TypeError, ValueError):
        priority_value = 999
    priority_value = max(priority_value, 1)
    return _clamp(1.0 - ((priority_value - 1) / 999.0), 0.0, 1.0)


def _latest_datetime(*values: Any) -> datetime | None:
    datetimes = [value for value in (_normalize_datetime(v) for v in values) if value is not None]
    if not datetimes:
        return None
    return max(datetimes)


def _normalize_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    return None


def _time_ago(reference_time: datetime | None, now: datetime) -> str:
    if reference_time is None:
        return "recently"
    delta = max((_normalize_datetime(now) - _normalize_datetime(reference_time)).total_seconds(), 0.0)
    if delta < 3600:
        minutes = max(int(delta // 60), 1)
        return f"{minutes} minute(s) ago"
    hours = delta / 3600.0
    if hours < 24:
        return f"{hours:.1f} hour(s) ago"
    days = hours / 24.0
    return f"{days:.1f} day(s) ago"


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


def _unique_strings(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    ordered: List[str] = []
    for value in values:
        if not isinstance(value, str):
            continue
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
