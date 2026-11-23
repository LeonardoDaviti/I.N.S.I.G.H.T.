"""Operational controls: scheduler config, job history, alerts, system health and source health."""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from insight_core.db import database as db

from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow
from insight_core.db.repo_operations import JobRunsRepository, SystemSettingsRepository
from insight_core.ingestion.kinds.parsing import lost_most_images
from insight_core.ingestion.kinds.saved import PLATFORM as SAVED_PLATFORM
from insight_core.ingestion.schedule import (
    BACKOFF_DORMANT_AFTER,
    BACKOFF_MAX,
    Availability,
    DecisionKind,
    FetchDecision,
    availability_from_env,
    cadence_stats,
    decide_fetch,
    unavailable_reason,
)
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.utils.addresses import host_of, publication_of
from insight_core.utils.env import env_float
from insight_core.utils.json_safe import iso, json_safe
from insight_core.utils.originals_rules import COLLECT_CHOSEN, classics_setting, collect_setting, lookup_setting


# Human labels per job type; any other type reads as its own name ("safe_ingest" -> "Safe ingest").
JOB_LABELS: Dict[str, str] = {
    "ingestion_run": "Ingestion run",
    "scheduler_cycle": "Daily work",
    "archive_source": "Archive",
    "api_restart": "API restart",
}


# The job types INSIGHT still runs; rows of other (retired) types stay in job_runs but leave the job list.
LIVE_JOB_TYPES = ("ingestion_run", "scheduler_cycle", "archive_source", "api_restart")


def job_label(job_type: Optional[str]) -> str:
    job_type = job_type or ""
    return JOB_LABELS.get(job_type) or job_type.replace("_", " ").capitalize()


INGEST_TICK_MINUTES_MIN = 15
INGEST_TICK_MINUTES_MAX = 24 * 60

# Source health: every source lands in exactly one status; the summary's buckets add up to the enabled sources.
class HealthStatus(str, Enum):
    """The one place the status set lives; declaration order is the sort order (worst first)."""

    ERROR = "error"
    BACKOFF = "backoff"
    UNAVAILABLE = "unavailable"
    DUE = "due"
    DEFERRED = "deferred"
    DISABLED = "disabled"


HEALTH_STATUS_ORDER = tuple(status.value for status in HealthStatus)
# Summary wire keys (API contract): a disabled source is not counted.
HEALTH_SUMMARY_KEYS: Dict[HealthStatus, str] = {
    HealthStatus.DUE: "due_now",
    HealthStatus.DEFERRED: "deferred",
    HealthStatus.BACKOFF: "backoff",
    HealthStatus.UNAVAILABLE: "unavailable",
    HealthStatus.ERROR: "errors",
}
OVERVIEW_HEALTH_ROWS = 8
OVERVIEW_JOBS = 50


def empty_health_summary() -> Dict[str, int]:
    """Each status's count, plus `silent` (0178) and `stalled` (0242), which are not statuses."""
    return {**{key: 0 for key in HEALTH_SUMMARY_KEYS.values()}, "silent": 0, "stalled": 0}


# Stalled: last success (else added) older than max(STALLED_FLOOR, STALLED_INTERVALS x interval), or STALLED_FAILURES
# failures in a row (not measured; the floor spares a frequent source one bad night).
STALLED_FLOOR = timedelta(days=3)
STALLED_INTERVALS = 5
STALLED_FAILURES = 5


def stalled_fields(source: Dict[str, Any], state: Optional[FetchStateRow], interval: timedelta, failures: int,
                   enabled: bool, now: datetime, stored: int = 0) -> Optional[Dict[str, Any]]:
    """{since, days, failures, posts, reason} for a stalled source; None when off, the saved pages, or working."""
    if not enabled or source.get("platform") == SAVED_PLATFORM:
        return None
    last = state.last_success_at if state else None
    since = last or source.get("created_at")
    old = since is not None and now - since > max(STALLED_FLOOR, interval * STALLED_INTERVALS)
    if not old and failures < STALLED_FAILURES:
        return None
    return {"since": iso(last), "days": int((now - since).total_seconds() // 86400) if since is not None else None,
            "failures": failures, "posts": stored,
            "reason": state.last_error if state is not None and last_attempt_failed(state) else None}


CADENCE_OVERRIDE_MIN_HOURS = 1.0
CADENCE_OVERRIDE_MAX_HOURS = 2160.0   # 90 days


def backlog_posts(available_posts: Any, stored_posts: Any) -> Optional[int]:
    if isinstance(available_posts, bool) or not isinstance(available_posts, int):
        return None
    return max(available_posts - int(stored_posts or 0), 0)


def last_attempt_failed(state: Optional[FetchStateRow]) -> bool:
    if state is None or state.last_outcome != "error":
        return False
    if state.last_success_at is None or state.last_error_at is None:
        return True
    return state.last_error_at >= state.last_success_at


def health_status(enabled: bool, decision: FetchDecision, consecutive_failures: int,
                  state: Optional[FetchStateRow] = None) -> str:
    if not enabled:
        return HealthStatus.DISABLED.value
    if decision.kind == DecisionKind.SKIP_UNAVAILABLE:
        return HealthStatus.UNAVAILABLE.value
    if decision.kind == DecisionKind.SKIP_BACKOFF:
        return HealthStatus.BACKOFF.value
    # Failing and due now; a failed last attempt counts even with 0 failures (backfilled rows).
    if consecutive_failures > 0 or last_attempt_failed(state):
        return HealthStatus.ERROR.value
    return HealthStatus.DUE.value if decision.fetch else HealthStatus.DEFERRED.value


def _credential_notice(kind: Any) -> Optional[str]:
    notice = getattr(kind, "credential_notice", None)
    if not callable(notice):
        return None
    try:
        return notice()
    except Exception:  # noqa: BLE001 - a notice never breaks the health table
        return None


def _kind_reading_notice(kind: Any, source: Dict[str, Any]) -> Optional[str]:
    """What a kind says about how this source's posts are read (Substack: paid posts as previews)."""
    notice = getattr(kind, "reading_notice", None)
    if not callable(notice):
        return None
    try:
        return notice(source)
    except Exception:  # noqa: BLE001 - a notice never breaks the health table
        return None


# How many newest page reads must lose images / open short before the row says so (one odd page never warns).
READING_NOTICE_MIN = 3
SHORT_OPENINGS_MIN = 4


def reading_notice(page_reads: Any) -> Optional[str]:
    """A note when most of a source's newest page reads lost their images or opened very short, else None."""
    reads = [read for read in (page_reads or []) if isinstance(read, dict)]
    lost = sum(1 for read in reads if lost_most_images(read))
    short = sum(1 for read in reads if read.get("short_opening"))
    notes = []
    if lost >= READING_NOTICE_MIN and lost * 2 >= len(reads):
        notes.append(f"Pages from this source lose most of their images ({lost} of the last {len(reads)})")
    if short >= SHORT_OPENINGS_MIN and short * 4 >= len(reads) * 3:
        notes.append(f"Pages from this source often open with a very short block, maybe a menu left in "
                     f"({short} of the last {len(reads)})")
    return ". ".join(notes) or None


# Source hygiene (0046): two marks, never acted on alone.
QUIET_AFTER = timedelta(days=30)
QUIET_GAPS = 3
NEVER_OPENED_MIN_POSTS = 20
NEVER_OPENED_MIN_AGE = timedelta(days=30)
TIDY_KEEP_DAYS = 90                     # Keep hides the marks this long; then they may return
NO_TIDY_MARKS = {"quiet": False, "never_opened": False}


def tidy_marks(source: Dict[str, Any], status: str, now: datetime) -> Dict[str, bool]:
    """Whether a working source went quiet (vs QUIET_AFTER and QUIET_GAPS x its mean gap) or was never opened;
    neither for a failing or disabled source, saved pages, or within TIDY_KEEP_DAYS of the owner's Keep."""
    state: Optional[FetchStateRow] = source.get("state")
    if (status in (HealthStatus.ERROR.value, HealthStatus.BACKOFF.value, HealthStatus.DISABLED.value)
            or source.get("platform") == SAVED_PLATFORM):
        return dict(NO_TIDY_MARKS)
    kept_at = source.get("tidy_kept_at")
    if kept_at is not None and now - kept_at < timedelta(days=TIDY_KEEP_DAYS):
        return dict(NO_TIDY_MARKS)
    created_at = source.get("created_at")
    newest = source.get("last_post_at") or created_at
    quiet = False
    if (status != HealthStatus.UNAVAILABLE.value and state is not None
            and state.last_success_at is not None and newest is not None):
        gap = source.get("mean_gap_seconds")
        silence = now - newest
        quiet = silence >= QUIET_AFTER and (gap is None or silence.total_seconds() > QUIET_GAPS * float(gap))
    never_opened = (
        int(source.get("post_count") or 0) >= NEVER_OPENED_MIN_POSTS
        and created_at is not None and now - created_at >= NEVER_OPENED_MIN_AGE
        and int(source.get("opened_posts") or 0) == 0
    )
    return {"quiet": quiet, "never_opened": never_opened}


def health_row(source: Dict[str, Any], kind: Any, availability: Availability, now: datetime) -> Dict[str, Any]:
    """One SourceHealthRow: the schedule view row + decide_fetch(force=False)."""
    state: Optional[FetchStateRow] = source.get("state")
    stats = cadence_stats(source, state)
    decision = decide_fetch(stats, kind.profile, now, force=False, availability=availability)
    enabled = bool(source.get("enabled"))
    # Why this kind cannot be fetched at all; kept for a disabled source too, so enabling it is no mystery.
    unavailable = unavailable_reason(kind.profile, availability)
    if not enabled:
        # As the runner: a disabled source is never picked by a cycle (fetch-now still works).
        detail = "Source is disabled" + (f"; unavailable: {unavailable}" if unavailable else "")
        decision = replace(decision, kind=DecisionKind.SKIP_DISABLED, fetch=False,
                           next_due_at=None, detail=detail)
    settings = source.get("settings") or {}
    archive = settings.get("archive") or {}
    failures = stats.consecutive_failures
    stored = int(source.get("post_count") or 0)
    status = health_status(enabled, decision, failures, state)
    return {
        "source_id": source["id"],
        "display_name": settings.get("display_name") or source.get("handle_or_url"),
        "platform": source.get("platform"),
        "kind": kind.name,
        "enabled": enabled,
        "in_main_digest": bool(source.get("in_main_digest", True)),
        "folders": list(source.get("folders") or []),
        "stored_posts": stored,
        "last_post_at": iso(source.get("last_post_at")),
        "created_at": iso(source.get("created_at")),
        "backlog_posts": backlog_posts(archive.get("available_posts"), stored),
        "tier": stats.tier.value,
        "mean_gap_hours": stats.mean_gap.total_seconds() / 3600 if stats.mean_gap is not None else None,
        "interval_hours": decision.interval.total_seconds() / 3600,
        "interval_basis": decision.interval_basis,
        "override_hours": stats.override_hours,
        "next_due_at": iso(decision.next_due_at),
        "would_fetch_now": decision.fetch,
        "decision": decision.kind.value,
        "decision_detail": decision.detail,
        "unavailable_reason": unavailable,
        "credential_notice": _credential_notice(kind),
        "reading_notice": ". ".join(filter(None, [reading_notice(source.get("page_reads")),
                                                  _kind_reading_notice(kind, source)])) or None,
        "watchable": bool(getattr(kind, "watches", False)),
        "watch_changes": bool(getattr(kind, "watches", False) and settings.get("watch_changes")),
        "status": status,
        **tidy_marks(source, status, now),
        "opened_posts": int(source.get("opened_posts") or 0),
        "tidy_kept_at": iso(source.get("tidy_kept_at")),
        "last_attempt_at": iso(state.last_attempt_at if state else None),
        "last_success_at": iso(state.last_success_at if state else None),
        "last_outcome": state.last_outcome if state else None,
        "last_fetched_posts": state.last_fetched_posts if state else None,
        "last_error": state.last_error if state else None,
        "last_error_at": iso(state.last_error_at if state else None),
        "consecutive_failures": failures,
        "next_retry_at": iso(stats.next_retry_at),
        "dormant": _dormant(failures, state),
        "moved_to": source.get("moved_to"),
        **_doctor_fields(state, source.get("handle_or_url")),
        "silent": silent_fields(source, state, status, now),
        "stalled": stalled_fields(source, state, decision.interval, failures, enabled, now, stored),
    }


def silent_fields(source: Dict[str, Any], state: Optional[FetchStateRow], status: str,
                  now: datetime) -> Optional[Dict[str, Any]]:
    """A source silent far beyond its rhythm, with the doctor's look if made since its newest post; None when not
    silent, off, failing, the saved pages, or the owner said it stopped and nothing came since."""
    from insight_core.ingestion.source_doctor import silent_beyond_rhythm

    if (status in (HealthStatus.ERROR.value, HealthStatus.BACKOFF.value, HealthStatus.DISABLED.value)
            or source.get("platform") == SAVED_PLATFORM):
        return None
    last = source.get("last_post_at")
    silence = silent_beyond_rhythm(last, source.get("mean_gap_seconds"), source.get("cadence_tier"), now)
    if silence is None:
        return None
    finding = (state.silent_finding if state else None) or {}
    current = bool(finding) and _same_instant(finding.get("last_post_at"), last)
    if current and finding.get("stopped"):
        return None
    looked = current and finding.get("looked")
    return {
        "days": int(silence.total_seconds() // 86400),
        "usual_gap_hours": float(source["mean_gap_seconds"]) / 3600,
        "last_post_at": iso(last),
        "looked_at": iso(state.silent_checked_at) if looked and state else None,
        "moved": list(finding.get("moved") or []) if looked else [],
        "replacement": finding.get("replacement") if looked else None,
    }


def _same_instant(stored: Any, value: Optional[datetime]) -> bool:
    if not stored or value is None:
        return False
    try:
        return datetime.fromisoformat(str(stored)) == value
    except ValueError:
        return False


def _dormant(failures: int, state: Optional[FetchStateRow]) -> bool:
    """Dormant (0088): 10 failures in a row and a wait past the 24h cap; a 5xx or timeout is never dormant."""
    if failures < BACKOFF_DORMANT_AFTER:
        return False
    if state is None or state.next_retry_at is None or state.last_error_at is None:
        return True
    return state.next_retry_at - state.last_error_at > BACKOFF_MAX


def _doctor_fields(state: Optional[FetchStateRow], address: Optional[str] = None) -> Dict[str, Any]:
    """The source doctor's finding: when it looked, the replacement it found (None: nothing), and `server_error`
    {status, site} when the site answered a server error (no move)."""
    finding = (state.doctor_finding if state else None) or {}
    # A server error is no move: the sheet says the server is failing ({status} None: timed out).
    failing = {"status": finding.get("status"), "site": publication_of(host_of(address))} if state and state.doctor_checked_at and finding.get("server_error") else None
    if (state is None or state.doctor_checked_at is None or finding.get("dismissed")
            or finding.get("working_again") or finding.get("server_error")
            # A fetch that stored nothing: nothing was looked for; last_error says why.
            or finding.get("empty_fetch")):
        return {"doctor_looked_at": None, "replacement": None, "server_error": failing, "dead": None}
    if finding.get("dead"):
        # A dead host: switch it off or replace it; nothing was looked for.
        return {"doctor_looked_at": None, "replacement": None, "server_error": None,
                "dead": {"host": finding.get("host"), "since": finding.get("since"), "reason": finding.get("reason"),
                         "checked_at": iso(state.doctor_checked_at)}}
    replacement = finding.get("replacement")
    # An old offer never checked against the source's items is not offered.
    if isinstance(replacement, dict) and "shared" not in replacement:
        replacement = None
    return {"doctor_looked_at": iso(state.doctor_checked_at), "replacement": replacement, "server_error": None,
            "dead": None}


def _health_sort_key(row: Dict[str, Any]) -> tuple:
    status = row["status"]
    rank = HEALTH_STATUS_ORDER.index(status) if status in HEALTH_STATUS_ORDER else len(HEALTH_STATUS_ORDER)
    # ISO-8601 UTC strings sort chronologically; no due time sorts last within a status.
    return (rank, -row["consecutive_failures"], row["next_due_at"] or "~", str(row["display_name"]).lower())


def summarize_health(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Each enabled source in its status's bucket; `errors` counts every failing source, backoff ones too."""
    summary = empty_health_summary()
    for row in rows:
        try:
            status = HealthStatus(row["status"])
        except ValueError:
            continue
        if key := HEALTH_SUMMARY_KEYS.get(status):
            summary[key] += 1
        if status == HealthStatus.BACKOFF:
            summary[HEALTH_SUMMARY_KEYS[HealthStatus.ERROR]] += 1
        if row.get("silent"):
            summary["silent"] += 1
        if row.get("stalled"):
            summary["stalled"] += 1
    return summary


def _ago(span: timedelta) -> str:
    seconds = span.total_seconds()
    return f"{seconds / 60:.0f} minutes" if seconds < 7200 else f"{seconds / 3600:.1f} hours"


def sources_failing(summary: Dict[str, int]) -> int:
    """Sources whose last fetches failed: retrying now or waiting (backoff), every one in `errors`."""
    return int(summary.get(HEALTH_SUMMARY_KEYS[HealthStatus.ERROR], 0))


class OperationsService:

    SETTINGS_KEY_SCHEDULER = "scheduler_config"
    SETTINGS_KEY_SCHEDULER_STATE = "scheduler_state"

    def __init__(
        self,
        db_url: str,
        *,
        kinds: Any = None,
        availability: Optional[Callable[[], Availability]] = None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.db_url = db_url
        self.logger = get_component_logger("operations_service")
        # Health seams; the kind registry is built lazily (the default one constructs YouTubeService).
        self._kinds = kinds
        self.availability = availability or availability_from_env
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def get_scheduler_config(self) -> Dict[str, Any]:
        defaults = self._default_scheduler_config()
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            row = SystemSettingsRepository.get(cur, self.SETTINGS_KEY_SCHEDULER)

        if not row:
            return defaults

        stored, updated_at = row
        merged = {
            **defaults,
            **(stored or {}),
            "updated_at": updated_at.isoformat() if updated_at else defaults.get("updated_at"),
        }
        return self._normalize_scheduler_config(merged)

    def update_scheduler_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.get_scheduler_config()
        config = config or {}
        merged = self._normalize_scheduler_config({**existing, **config})
        # Marked as this default's, so a stored false is the owner's choice (0126).
        merged["collect_originals"] = (bool(config["collect_originals"]) if config.get("collect_originals") is not None
                                       else existing["collect_originals"])

        payload = {
            "interval_hours": merged["interval_hours"],
            "ingest_tick_minutes": merged["ingest_tick_minutes"],
            "collect_originals": merged["collect_originals"],
            COLLECT_CHOSEN[0]: COLLECT_CHOSEN[1],
            "lookup_originals": merged["lookup_originals"],
            "store_classics": merged["store_classics"],
        }

        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                updated_at = SystemSettingsRepository.upsert(cur, self.SETTINGS_KEY_SCHEDULER, payload)
            conn.commit()

        merged["updated_at"] = updated_at.isoformat()
        return merged

    # ------------------------------------------------------------------ scheduler state

    def get_scheduler_state(self) -> Dict[str, Any]:
        """{last_tick_at, next_tick_at, last_daily_work_at, next_daily_work_at} as ISO strings (or {})."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            row = SystemSettingsRepository.get(cur, self.SETTINGS_KEY_SCHEDULER_STATE)
        return dict(row[0] or {}) if row else {}

    def set_scheduler_state(self, state: Dict[str, Any]) -> None:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                SystemSettingsRepository.upsert(cur, self.SETTINGS_KEY_SCHEDULER_STATE,
                                                json_safe(state or {}))
            conn.commit()

    def latest_successful_job_finished_at(self, job_type: str) -> Optional[datetime]:
        """When the newest successful job of this type finished (seeds the daily-work gate)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return JobRunsRepository.latest_success_finished_at(cur, job_type)

    def latest_job_for_source(self, job_type: str, source_id: str) -> Optional[Dict[str, Any]]:
        """The newest job of this type for one source, summarised (the source sheet's archive)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return JobRunsRepository.latest_for_source(cur, job_type, source_id)

    def start_job(
        self,
        job_type: str,
        *,
        trigger: str = "manual",
        source_id: Optional[str] = None,
        message: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO job_runs (job_type, status, trigger, source_id, message, payload)
                    VALUES (%s, 'running', %s, %s, %s, %s::jsonb)
                    RETURNING id
                    """,
                    (job_type, trigger, source_id, message, json.dumps(self._prepare_payload(payload or {}, compact=False))),
                )
                job_id = str(cur.fetchone()[0])
            conn.commit()
        return job_id

    def finish_job(
        self,
        job_id: str,
        *,
        status: str,
        message: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        compact: bool = False,
    ) -> None:
        """Close out a job run. compact=True cuts long lists/strings of a full result graph; callers that poll
        the job for its result (the frontend's pollOperationJob) must keep compact=False."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM job_runs WHERE id = %s FOR UPDATE", (job_id,))
                row = cur.fetchone()
                current_payload = row[0] if row else {}
                events = list((current_payload or {}).get("events") or [])
                if message or status:
                    events.append(
                        {
                            "at": now_iso,
                            "level": "error" if status == "failed" else "success",
                            "message": message or f"Job {status}",
                            "status": status,
                        }
                    )
                next_payload = {
                    **(current_payload or {}),
                    **self._prepare_payload(payload or {}, compact=compact),
                }
                if events:
                    next_payload["events"] = events[-200:]
                cur.execute(
                    """
                    UPDATE job_runs
                    SET status = %s,
                        message = COALESCE(%s, message),
                        payload = %s::jsonb,
                        finished_at = %s
                    WHERE id = %s
                    """,
                    (
                        status,
                        message,
                        json.dumps(self._prepare_payload(next_payload, compact=False)),
                        now_iso,
                        job_id,
                    ),
                )
            conn.commit()

    def close_interrupted_jobs(self, trigger: str) -> int:
        """At a process's start: its `trigger`'s jobs still `running` become `interrupted`. Returns how many."""
        event = {"level": "error", "message": "Interrupted by a restart", "status": "interrupted"}
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE job_runs
                    SET status = 'interrupted', finished_at = now(),
                        payload = jsonb_set(payload, '{events}', COALESCE(payload->'events', '[]'::jsonb)
                                            || jsonb_build_array(%s::jsonb || jsonb_build_object('at', now())))
                    WHERE status = 'running' AND trigger = %s
                    """,
                    (json.dumps(event), trigger),
                )
                closed = cur.rowcount or 0
            conn.commit()
        return closed

    # A waiting job is not finished: `waiting_until` says when it continues; the continuing process claims it first.

    def wait_job(self, job_id: str, *, message: str, payload: Dict[str, Any]) -> None:
        """Mark a running job waiting, its payload merged with the leg's result (finished_at stays empty)."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM job_runs WHERE id = %s FOR UPDATE", (job_id,))
                row = cur.fetchone()
                if not row:
                    return
                next_payload = {**(row[0] or {}), **self._prepare_payload(payload, compact=False)}
                next_payload["events"] = (row[0] or {}).get("events") or []
                cur.execute(
                    "UPDATE job_runs SET status = 'waiting', message = %s, payload = %s::jsonb, finished_at = NULL "
                    "WHERE id = %s",
                    (message, json.dumps(next_payload), job_id),
                )
            conn.commit()

    def due_waiting_jobs(self, job_type: str, now: datetime) -> List[Dict[str, Any]]:
        """The waiting jobs of this type whose waiting_until has come, soonest first: [{id, source_id}]."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, source_id::text FROM job_runs
                WHERE job_type = %s AND status = 'waiting' AND (payload->>'waiting_until')::timestamptz <= %s
                ORDER BY (payload->>'waiting_until')::timestamptz
                """,
                (job_type, now),
            )
            return [{"id": row[0], "source_id": row[1]} for row in cur.fetchall()]

    def claim_waiting_job(self, job_id: str, *, trigger: str) -> Optional[Dict[str, Any]]:
        """waiting -> running, as this process's job; None when another process claimed it first."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE job_runs SET status = 'running', trigger = %s WHERE id = %s AND status = 'waiting' "
                    "RETURNING id::text, source_id::text, payload",
                    (trigger, job_id),
                )
                row = cur.fetchone()
            conn.commit()
        return {"id": row[0], "source_id": row[1], "payload": row[2] or {}} if row else None

    def requeue_interrupted_archives(self, trigger: str, now: datetime) -> int:
        """At the scheduler's start: archives it was continuing are due again, so a deploy needs no Resume."""
        event = {"level": "warning", "message": "Interrupted by a restart; continues shortly", "status": "waiting"}
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE job_runs
                    SET status = 'waiting',
                        payload = jsonb_set(payload || jsonb_build_object('waiting_until', %s::text), '{events}',
                                            COALESCE(payload->'events', '[]'::jsonb)
                                            || jsonb_build_array(%s::jsonb || jsonb_build_object('at', now())))
                    WHERE status = 'running' AND trigger = %s AND job_type = 'archive_source'
                      AND payload ? 'waits'
                    """,
                    (now.isoformat(), json.dumps(event), trigger),
                )
                requeued = cur.rowcount or 0
            conn.commit()
        return requeued

    def discard_job(self, job_id: str) -> None:
        """Delete a job that turned out not worth listing (a scheduler tick with nothing due)."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM job_runs WHERE id = %s", (job_id,))
            conn.commit()

    def append_job_event(
        self,
        job_id: str,
        *,
        message: str,
        level: str = "info",
        progress: float | None = None,
        payload: Optional[Dict[str, Any]] = None,
        fields: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append an event; `progress` and `fields` (live counters) also set top-level payload keys."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT payload FROM job_runs WHERE id = %s FOR UPDATE", (job_id,))
                row = cur.fetchone()
                if not row:
                    return
                current_payload = row[0] or {}
                events = list(current_payload.get("events") or [])
                event: Dict[str, Any] = {
                    "at": now_iso,
                    "level": level,
                    "message": message,
                }
                if progress is not None:
                    event["progress"] = round(float(progress), 2)
                if payload:
                    event["data"] = self._prepare_payload(payload, compact=False)
                events.append(event)
                next_payload = {
                    **current_payload,
                    **(fields or {}),
                    "events": events[-200:],
                }
                if progress is not None:
                    next_payload["progress"] = round(float(progress), 2)
                cur.execute(
                    "UPDATE job_runs SET payload = %s::jsonb WHERE id = %s",
                    (json.dumps(self._prepare_payload(next_payload, compact=False)), job_id),
                )
            conn.commit()

    # Tracked work goes on when its job_runs row cannot be written: these log and return instead of raising.

    def start_job_unless_running(self, job_type: str, *, source_id: str, trigger: str = "manual",
                                 message: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """start_job, unless a job of this type for this source is running (None then). Check and insert run under
        one lock on (type, source), so two API processes can't both start one. A write failure is logged and raised."""
        key = f"job_runs:{job_type}:{source_id}"
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtext(%s))", (key,))
            try:
                cur.execute("SELECT 1 FROM job_runs WHERE job_type = %s AND source_id = %s AND status = 'running' LIMIT 1",
                            (job_type, source_id))
                if cur.fetchone() is not None:
                    return None
                try:
                    return self.start_job(job_type, trigger=trigger, source_id=source_id, message=message,
                                          payload=payload)
                except Exception:
                    self.logger.exception("Could not start a %s job", job_type)
                    raise
            finally:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (key,))

    def recent_job_times(self, job_type: str, seconds: float, *, kind: Optional[str] = None) -> List[float]:
        """Start times (epoch seconds) of this type's jobs in the last `seconds`, optionally of payload.kind `kind`."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("""SELECT extract(epoch FROM started_at) FROM job_runs
                            WHERE job_type = %s AND started_at > now() - make_interval(secs => %s)
                              AND (%s::text IS NULL OR payload->>'kind' = %s) ORDER BY started_at""",
                        (job_type, seconds, kind, kind))
            return [float(r[0]) for r in cur.fetchall()]

    def try_start_job(self, job_type: str, **kwargs: Any) -> Optional[str]:
        """start_job, or None (logged) when the row cannot be written."""
        try:
            return self.start_job(job_type, **kwargs)
        except Exception:
            self.logger.exception("Could not start a %s job", job_type)
            return None

    def try_append_job_event(self, job_id: Optional[str], **kwargs: Any) -> None:
        if not job_id:
            return
        try:
            self.append_job_event(job_id, **kwargs)
        except Exception:
            self.logger.exception("Could not record an event on job %s", job_id)

    def try_finish_job(self, job_id: Optional[str], **kwargs: Any) -> None:
        if not job_id:
            return
        try:
            self.finish_job(job_id, **kwargs)
        except Exception:
            self.logger.exception("Could not finish job %s", job_id)

    def prune_job_runs(self, retain_days: int = 30) -> int:
        """Delete job history older than retain_days (operational log). Returns rows removed."""
        retain_days = max(1, int(retain_days))
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM job_runs WHERE started_at < now() - make_interval(days => %s)",
                    (retain_days,),
                )
                removed = cur.rowcount or 0
            conn.commit()
        return removed

    def list_recent_jobs(self, limit: int = 80) -> List[Dict[str, Any]]:
        limit = max(1, min(int(limit), 200))
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      jr.id,
                      jr.job_type,
                      jr.status,
                      jr.trigger,
                      jr.source_id,
                      COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url),
                      s.platform,
                      jr.message,
                      -- Only project the handful of payload keys the list view reads.
                      -- Selecting jr.payload wholesale decoded ~148MB of jsonb per call
                      -- (200 rows) into Python objects; the freed pages never returned
                      -- to the OS. Full payloads are still served by get_job().
                      jsonb_strip_nulls(jsonb_build_object(
                        'progress',          jr.payload->'progress',
                        'error',             jr.payload->'error',
                        'sources',           jr.payload->'sources',
                        'new_posts',         jr.payload->'new_posts'
                      )),
                      jr.started_at,
                      jr.finished_at,
                      CASE
                        WHEN jsonb_typeof(jr.payload->'progress') = 'number'
                        THEN (jr.payload->>'progress')::float
                        ELSE 0
                      END,
                      CASE
                        WHEN jsonb_typeof(jr.payload->'events') = 'array'
                        THEN jsonb_array_length(jr.payload->'events')
                        ELSE 0
                      END
                    FROM job_runs jr
                    LEFT JOIN sources s ON s.id = jr.source_id
                    WHERE jr.job_type = ANY(%s)
                    ORDER BY jr.started_at DESC
                    LIMIT %s
                    """,
                    (list(LIVE_JOB_TYPES), limit),
                )
                rows = cur.fetchall()

        jobs: List[Dict[str, Any]] = []
        for row in rows:
            jobs.append(
                {
                    "id": str(row[0]),
                    "job_type": row[1],
                    "job_label": job_label(row[1]),
                    "status": row[2],
                    "trigger": row[3],
                    "source_id": str(row[4]) if row[4] else None,
                    "source_display_name": row[5],
                    "source_platform": row[6],
                    "message": row[7],
                    "payload": row[8] or {},
                    "progress": float(row[11] or 0),
                    "event_count": int(row[12] or 0),
                    "started_at": row[9].isoformat() if row[9] else None,
                    "finished_at": row[10].isoformat() if row[10] else None,
                }
            )
        return jobs

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      jr.id,
                      jr.job_type,
                      jr.status,
                      jr.trigger,
                      jr.source_id,
                      COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url),
                      s.platform,
                      jr.message,
                      jr.payload,
                      jr.started_at,
                      jr.finished_at
                    FROM job_runs jr
                    LEFT JOIN sources s ON s.id = jr.source_id
                    WHERE jr.id = %s
                    """,
                    (job_id,),
                )
                row = cur.fetchone()

        if not row:
            return None

        payload = row[8] or {}
        return {
            "id": str(row[0]),
            "job_type": row[1],
            "job_label": job_label(row[1]),
            "status": row[2],
            "trigger": row[3],
            "source_id": str(row[4]) if row[4] else None,
            "source_display_name": row[5],
            "source_platform": row[6],
            "message": row[7],
            "payload": payload,
            "progress": float(payload.get("progress", 0) or 0),
            "event_count": len(payload.get("events", []) or []),
            "started_at": row[9].isoformat() if row[9] else None,
            "finished_at": row[10].isoformat() if row[10] else None,
        }

    def background_work(self) -> Dict[str, Any]:
        """The overview's Background work: the story job, search indexing and link reading. Read only."""
        from insight_core.db.repo_background import background_work
        from insight_core.services.stories_service import LOCK_KEY, SETTINGS_KEY

        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return {"success": True, **background_work(cur, stories_key=SETTINGS_KEY, stories_lock=LOCK_KEY)}

    def running(self) -> Dict[str, Any]:
        """What runs now, for the top bar's sign: the overview's recent jobs, without source health."""
        return {"success": True, "jobs": self.list_recent_jobs(OVERVIEW_JOBS)}

    def get_operations_overview(self) -> Dict[str, Any]:
        # enough history (~8-10 scheduler cycles) for the alerts panel to catch a stale failure
        jobs = self.list_recent_jobs(OVERVIEW_JOBS)
        health = self.get_source_health()
        summary = health["summary"]
        counts = self.get_database_counts()
        alerts = [
            {
                "id": job["id"],
                "severity": "high",
                "title": job["job_type"],
                "label": job.get("job_label") or job_label(job["job_type"]),
                "message": job.get("message") or "Job failed",
                "started_at": job["started_at"],
                "source_id": job.get("source_id"),
            }
            for job in jobs
            if job["status"] == "failed"
        ][:8]

        return {
            "success": True,
            "scheduler": self.get_scheduler_config(),
            "jobs": jobs,
            "source_health": {"summary": summary, "rows": health["rows"][:OVERVIEW_HEALTH_ROWS],
                              "host_limits": health.get("host_limits") or []},
            "alerts": alerts,
            "stats": {
                "recent_failures": len([job for job in jobs if job["status"] == "failed"]),
                "sources_in_error": sources_failing(summary),
                "sources_monitored": len(health["rows"]),
                **counts,
            },
        }

    def get_database_counts(self) -> Dict[str, int]:
        """{total_posts, enabled_sources}: posts summed over each source's kept statistics, not a count of posts."""
        from insight_core.db import repo_post_stats

        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                total = repo_post_stats.corpus(cur)["total_posts"]
                cur.execute("SELECT COUNT(*) FROM sources WHERE enabled = TRUE")
                enabled = cur.fetchone()[0]

        return {
            "total_posts": int(total or 0),
            "enabled_sources": int(enabled or 0),
        }

    # ------------------------------------------------------------------ the system's health

    def system_health(self, now: Optional[datetime] = None, *, failing_sources: Optional[int] = None) -> Dict[str, Any]:
        """/api/status's `healthy`: {healthy, reasons, warnings (never unhealthy alone), checks}. Reasons: ingestion
        or the scheduler tick overdue, a heartbeat past its limit, a failing Mark X job or stale decision run, and any
        check that cannot be read; warnings: failing sources, silent workers."""
        from insight_core.utils import heartbeat
        now = now or datetime.now(timezone.utc)
        reasons: List[str] = []
        warnings: List[str] = []
        checks: Dict[str, Any] = {}
        try:
            config = self.get_scheduler_config()
            interval = timedelta(hours=float(config.get("interval_hours") or 20))
            tick = timedelta(minutes=float(config.get("ingest_tick_minutes") or 60))
            last_ok = self.latest_successful_job_finished_at("ingestion_run")
            state = self.get_scheduler_state() or {}
            next_tick = state.get("next_tick_at")
            next_tick = datetime.fromisoformat(next_tick) if isinstance(next_tick, str) else next_tick
            checks["ingestion"] = {"last_success_at": iso(last_ok), "next_tick_at": iso(next_tick),
                                   "limit_hours": round((interval + 2 * tick).total_seconds() / 3600, 2)}
            if last_ok is None:
                reasons.append("no ingestion run has succeeded yet")
            elif now - last_ok > interval + 2 * tick:
                reasons.append(f"the last successful ingestion run finished {_ago(now - last_ok)} ago")
            if next_tick is not None and now - next_tick > 2 * tick:
                reasons.append(f"the scheduler's next tick is {_ago(now - next_tick)} overdue")
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"could not read the ingestion state ({type(exc).__name__})")
        ages = heartbeat.ages(now.timestamp())
        checks["heartbeats"] = {k: None if v is None else round(v) for k, v in ages.items()}
        checks["processes"] = {name: {k: (round(v) if k == "age" else v) for k, v in p.items()}
                               for name, p in heartbeat.processes(now.timestamp()).items() if len(p) > 1}
        reasons.extend(heartbeat.stale(now.timestamp(), required=()))
        try:
            self._markx_health(now, reasons, warnings, checks)
        except Exception as exc:  # noqa: BLE001
            reasons.append(f"could not read Mark X's jobs ({type(exc).__name__})")
        if failing_sources:
            warnings.append(f"{failing_sources} sources failing")
        return {"healthy": not reasons, "reasons": reasons, "warnings": warnings, "checks": checks}

    def _markx_health(self, now: datetime, reasons: List[str], warnings: List[str], checks: Dict[str, Any]) -> None:
        from insight_core.markx import api as markx_api, jobs, news as markx_news
        if not markx_api.enabled():
            checks["markx"] = None
            return
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            view = jobs.view(cur)
            cur.execute("SELECT max(finished_at) FROM mx_runs")
            last_run = cur.fetchone()[0]
            stale_workers = [w["worker"] for w in markx_news.workers_view(markx_api.contacts(cur), now) if w["stale"]]
            ix = jobs.mark_ix(cur)
            held = jobs.decision_hold(ix)[0]
        checks["markx"] = {"jobs": {job: {k: v.get(k) for k in ("failures", "failing", "retry_at", "finished_at")}
                                    | {"ok": (v.get("last") or {}).get("ok")} for job, v in view.items()},
                           "last_decision_run_at": iso(last_run), "decision_held": held,
                           "mark_ix_rebuild": {k: ix.get(k) for k in ("rebuild", "phase", "done", "total", "started_at")}
                           if ix.get("rebuild") else None}
        for job, v in view.items():
            if v["failing"]:
                error = (v.get("last") or {}).get("error") or "no error recorded"
                reasons.append(f"Mark X's {job} job failed {v['failures']} times in a row ({str(error)[:120]})")
        if last_run is None or (now - last_run).total_seconds() > 2 * jobs.EVERY:
            # why a decision run doesn't start, when Mark IX holds it
            reasons.append(("no Mark X decision run has finished" if last_run is None
                            else f"the last Mark X decision run finished {_ago(now - last_run)} ago")
                           + (f"; held: {held}" if held else ""))
        if ix.get("rebuild") == "in progress" and ix.get("started_at"):
            try:
                begun = datetime.fromisoformat(ix["started_at"])
            except (TypeError, ValueError):
                begun = None
            if begun is not None and (now - begun).total_seconds() > 2 * jobs.EVERY:
                warnings.append(f"Mark IX's rule-change rebuild began {_ago(now - begun)} ago: "
                                f"{int(ix.get('done') or 0):,} of {int(ix.get('total') or 0):,} posts regrouped "
                                f"({ix.get('phase')} phase)")
        if stale_workers:
            warnings.append(f"Mark X workers silent for over {markx_news.WORKER_STALE_DAYS} days: "
                            + ", ".join(stale_workers))

    def table_sizes(self, limit: int = 15) -> List[Dict[str, Any]]:
        """The biggest tables with their indexes and TOAST, largest first. Read only: nothing is pruned."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("""SELECT c.relname, pg_total_relation_size(c.oid), c.reltuples::bigint
                             FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE c.relkind IN ('r', 'p', 'm') AND n.nspname = current_schema()
                            ORDER BY 2 DESC LIMIT %s""", (limit,))
            return [{"table": name, "bytes": int(size), "rows_estimate": max(int(rows), 0)}
                    for name, size, rows in cur.fetchall()]

    STATEMENTS_SHOWN = 20
    STATEMENT_CHARS = 2000

    def top_statements(self, limit: int = STATEMENTS_SHOWN, *, since: Optional[str] = None,
                       snapshot: bool = False) -> Dict[str, Any]:
        """What insight-db spends its time on (`top_statements`), plus `indexes` and `memory`. Read only. `since`
        "start" or "snapshot": since this process's start or its last `snapshot` (kept in the process, no reset)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            seen = self._indexes_and_memory(cur)
            if snapshot:
                statement_base(cur, "snapshot")
            base = None
            if since is not None:
                base = _STATEMENT_BASES.get(since)
                if base is None:
                    return {"enabled": False, "statements": [], **seen,
                            "reason": f"no {since!r} snapshot in this API process (pid {os.getpid()}): "
                                      "take one with ?snapshot=1"}
            out = top_statements(cur, limit, chars=self.STATEMENT_CHARS, base=base)
            return {**out, **seen, "process": os.getpid(), "snapshots": {k: v[0] for k, v in _STATEMENT_BASES.items()}}

    INDEX_MB_SHOWN = 1

    def _indexes_and_memory(self, cur: Any) -> Dict[str, Any]:
        """`indexes` of INDEX_MB_SHOWN MB or more with their scans, and `memory` (buffer settings, hit ratio)."""
        cur.execute("""SELECT i.relname, i.indexrelname, i.idx_scan, pg_relation_size(i.indexrelid)
                         FROM pg_stat_user_indexes i
                        WHERE pg_relation_size(i.indexrelid) >= %s
                        ORDER BY pg_relation_size(i.indexrelid) DESC, i.indexrelname""", (self.INDEX_MB_SHOWN * 2 ** 20,))
        indexes = [{"table": t, "index": name, "scans": int(n or 0), "mb": round(size / 2 ** 20, 1)}
                   for t, name, n, size in cur.fetchall()]
        cur.execute("""SELECT current_setting('shared_buffers'), current_setting('effective_cache_size'),
                              current_setting('work_mem'), blks_hit, blks_read, stats_reset
                         FROM pg_stat_database WHERE datname = current_database()""")
        sb, ecs, wm, hit, read, reset = cur.fetchone()
        hit, read = int(hit or 0), int(read or 0)
        return {"indexes": indexes,
                "memory": {"shared_buffers": sb, "effective_cache_size": ecs, "work_mem": wm,
                           "hit_ratio": round(hit / (hit + read), 4) if hit + read else None,
                           "blocks_hit": hit, "blocks_read": read, "since": iso(reset)}}

    def get_corpus_freshness(self) -> Dict[str, Any]:
        """Corpus-wide freshness: newest/oldest post, latest fetch (from kept statistics), last-24h volume."""
        from insight_core.db import repo_post_stats

        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                corpus = repo_post_stats.corpus(cur)
                cur.execute("SELECT COUNT(*) FROM posts WHERE fetched_at >= now() - interval '24 hours'")
                last_24h = cur.fetchone()[0]

        return {
            "latest_post_at": iso(corpus["latest_at"]),
            "oldest_post_at": iso(corpus["oldest_at"]),
            "latest_fetch_at": iso(corpus["latest_fetch_at"]),
            "posts_last_24h": int(last_24h or 0),
        }

    # ------------------------------------------------------------------ source health

    def get_source_health(self) -> Dict[str, Any]:
        """SourcesHealthResponse: one row per source (worst first) plus a summary. Each row decides exactly as the
        runner does (decide_fetch, force=False), so the table and the next run cannot disagree."""
        now = self.clock()
        rows = self._health_rows(self._load_schedule_view(), now)
        return {
            "success": True,
            "generated_at": now.isoformat(),
            "rows": rows,
            "summary": summarize_health(rows),
            "host_limits": self.host_limits(),
        }

    def host_limits(self) -> List[Dict[str, Any]]:
        """Each host's learned budget: [{host, requests, window_s, limits, archive_gap_s, line}]. Never raises."""
        from insight_core.ingestion.host_budgets import HostBudgets
        from insight_core.ingestion.ports import DbHostBudgetStore

        try:
            return [budget.as_dict() for budget in HostBudgets(DbHostBudgetStore(self.db_url), clock=self.clock).learned_all()]
        except Exception:  # noqa: BLE001
            self.logger.exception("Could not read the learned host budgets")
            return []

    def get_source_health_row(self, source_id: str) -> Optional[Dict[str, Any]]:
        rows = self._health_rows(self._load_schedule_view([source_id]), self.clock())
        return rows[0] if rows else None

    def set_cadence_override(self, source_id: str, hours: Optional[float]) -> Dict[str, Any]:
        """Write sources.fetch_interval_hours_override; the fresh row. LookupError if no source."""
        if not self._write_cadence_override(source_id, hours):
            raise LookupError(f"Source {source_id} not found")
        row = self.get_source_health_row(source_id)
        if row is None:
            raise LookupError(f"Source {source_id} not found")
        return row

    def dismiss_replacement(self, source_id: str) -> Dict[str, Any]:
        """Hide the source doctor's finding until the next failure streak; the fresh row (LookupError: none)."""
        dismissed = False
        if self._valid_id(source_id):
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                dismissed = FetchStateRepository().dismiss_doctor(cur, source_id)
                conn.commit()
        row = self.get_source_health_row(source_id) if dismissed else None
        if row is None:
            raise LookupError(f"Source {source_id} has no replacement to dismiss")
        return row

    def source_stopped(self, source_id: str) -> Dict[str, Any]:
        """The owner says a silent source stopped: its silence is hidden until it posts; nothing is switched off.
        The fresh row; LookupError if no source."""
        marked = False
        if self._valid_id(source_id):
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                repo = FetchStateRepository()
                marked = repo.mark_stopped(cur, source_id, last_post_at=repo.last_post_at(cur, source_id),
                                           at=self.clock())
                conn.commit()
        row = self.get_source_health_row(source_id) if marked else None
        if row is None:
            raise LookupError(f"Source {source_id} not found")
        return row

    def keep_source(self, source_id: str) -> Dict[str, Any]:
        """Keep a source marked quiet or never opened: its marks hide for TIDY_KEEP_DAYS; the fresh row.
        LookupError if no source."""
        kept = False
        if self._valid_id(source_id):
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                kept = FetchStateRepository().keep_source(cur, source_id, self.clock())
                conn.commit()
        row = self.get_source_health_row(source_id) if kept else None
        if row is None:
            raise LookupError(f"Source {source_id} not found")
        return row

    @staticmethod
    def _valid_id(source_id: str) -> bool:
        try:
            uuid.UUID(str(source_id))
            return True
        except (TypeError, ValueError):
            return False

    def _health_rows(self, view: List[Dict[str, Any]], now: datetime) -> List[Dict[str, Any]]:
        availability = self.availability()
        kinds = self.kinds
        rows = [health_row(source, kinds.resolve(source), availability, now) for source in view]
        rows.sort(key=_health_sort_key)
        return rows

    @property
    def kinds(self) -> Any:
        if self._kinds is None:
            from insight_core.ingestion.http import KindHttp
            from insight_core.ingestion.kinds import KindRegistry
            from insight_core.services.youtube_service import YouTubeService

            self._kinds = KindRegistry.default(KindHttp(), YouTubeService(self.db_url), db_url=self.db_url)
        return self._kinds

    def _load_schedule_view(self, source_ids: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return FetchStateRepository().load_schedule_view(cur, source_ids)

    def _write_cadence_override(self, source_id: str, hours: Optional[float]) -> bool:
        if not self._valid_id(source_id):
            return False
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            written = FetchStateRepository().set_cadence_override(cur, source_id, hours)
            conn.commit()
            return written

    def _default_scheduler_config(self) -> Dict[str, Any]:
        return self._normalize_scheduler_config(
            {
                "interval_hours": env_float("INSIGHT_INGEST_INTERVAL_HOURS", 20),
                "ingest_tick_minutes": env_float("INSIGHT_INGEST_TICK_MINUTES", 60),
                "updated_at": None,
            }
        )

    def _normalize_scheduler_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        interval_hours = float(config.get("interval_hours", 20))
        interval_hours = max(0.25, min(interval_hours, 168))
        try:
            tick = float(config.get("ingest_tick_minutes", 60))
        except (TypeError, ValueError):
            tick = 60.0
        tick = max(INGEST_TICK_MINUTES_MIN, min(tick, INGEST_TICK_MINUTES_MAX))
        return {
            "interval_hours": interval_hours,
            "ingest_tick_minutes": int(tick) if float(tick).is_integer() else tick,
            "collect_originals": collect_setting(config),
            "lookup_originals": lookup_setting(config),
            "store_classics": classics_setting(config),
            "updated_at": config.get("updated_at"),
        }

    def _prepare_payload(self, payload: Dict[str, Any], *, compact: bool = False) -> Dict[str, Any]:
        prepared = json_safe(payload)
        if compact:
            return self._compact_payload(prepared)
        return prepared

    def _compact_payload(self, value: Any, *, parent_key: str | None = None) -> Any:
        if isinstance(value, dict):
            compacted: Dict[str, Any] = {}
            for key, item in value.items():
                if key == "posts":
                    if isinstance(item, dict):
                        compacted[key] = {
                            "count": len(item),
                            "sample_ids": list(item.keys())[:5],
                        }
                    elif isinstance(item, list):
                        compacted[key] = {"count": len(item)}
                    else:
                        compacted[key] = self._compact_payload(item, parent_key=key)
                    continue
                compacted[key] = self._compact_payload(item, parent_key=key)
            return compacted

        if isinstance(value, list):
            if parent_key == "events":
                return [self._compact_payload(item, parent_key=parent_key) for item in value[-200:]]

            if len(value) > 20:
                preview = [self._compact_payload(item, parent_key=parent_key) for item in value[:10]]
                preview.append({"truncated_items": len(value) - 10})
                return preview
            return [self._compact_payload(item, parent_key=parent_key) for item in value]

        if isinstance(value, str):
            limit = 1200 if parent_key not in {"content", "content_html"} else 600
            if len(value) > limit:
                return value[:limit] + "... [truncated]"
            return value

        return value


def top_statements(cur: Any, limit: int, *, chars: int = OperationsService.STATEMENT_CHARS,
                   base: Optional[Tuple[str, Dict[str, Tuple[float, ...]]]] = None) -> Dict[str, Any]:
    """pg_stat_statements' statements of this database by total time since `since`, normalized ($n: no values shown),
    cut at `chars`, with `share` of all time. Read only; {"enabled": False, "reason"} without the extension. `base`
    (at, `statement_counts`): the counts since then, the top by that time."""
    cur.execute("""SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'),
                          'pg_stat_statements' = ANY(string_to_array(
                              replace(current_setting('shared_preload_libraries'), ' ', ''), ','))""")
    installed, loaded = cur.fetchone()
    if not (installed and loaded):
        why = ("its library is not loaded at the server's start (shared_preload_libraries)" if not loaded
               else "its view is not created in this database (migration 0146)")
        return {"enabled": False, "reason": f"pg_stat_statements is off: {why}", "statements": []}
    if base is not None:
        return _statements_since(cur, limit, chars, base)
    cur.execute("""SELECT sum(total_exec_time), sum(calls) FROM pg_stat_statements
                    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())""")
    total_ms, calls = cur.fetchone()
    cur.execute("SELECT stats_reset FROM pg_stat_statements_info")
    since = cur.fetchone()[0]
    cur.execute("""SELECT queryid, left(query, %s), calls, total_exec_time, mean_exec_time, rows,
                          shared_blks_hit, shared_blks_read, temp_blks_written
                     FROM pg_stat_statements
                    WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
                    ORDER BY total_exec_time DESC LIMIT %s""", (chars, limit))
    rows = cur.fetchall()
    total_ms = float(total_ms or 0)
    return {"enabled": True, "since": iso(since), "total_ms": round(total_ms, 1), "calls": int(calls or 0),
            "statements": [{"id": str(qid), "statement": " ".join(text.split()), "calls": int(n),
                            "total_ms": round(float(t), 1), "mean_ms": round(float(m), 2), "rows": int(r),
                            "blocks_hit": int(hit), "blocks_read": int(read), "temp_blocks_written": int(temp),
                            "share": round(float(t) / total_ms, 4) if total_ms else None}
                           for qid, text, n, t, m, r, hit, read, temp in rows]}


# v10.42: {name: (at, statement_counts)}: "start" (the API process's start, main.py's lifespan) and "snapshot" (a
# GET's ?snapshot=1). In this process only (the API runs two: each its own); one entry a statement Postgres keeps
# (pg_stat_statements.max, 5,000 by default): 1.7 MB a snapshot at 5,000 (measured, tracemalloc), two a process.
_STATEMENT_BASES: Dict[str, Tuple[str, Dict[str, Tuple[float, ...]]]] = {}
_THIS_DB = "dbid = (SELECT oid FROM pg_database WHERE datname = current_database())"


def statement_counts(cur: Any) -> Dict[str, Tuple[float, ...]]:
    """{queryid: (calls, total ms, rows, blocks hit, blocks read, temp blocks written)} of this database, now."""
    cur.execute(f"""SELECT queryid, sum(calls), sum(total_exec_time), sum(rows), sum(shared_blks_hit),
                           sum(shared_blks_read), sum(temp_blks_written)
                      FROM pg_stat_statements WHERE {_THIS_DB} GROUP BY queryid""")
    return {str(q): tuple(float(x or 0) for x in rest) for q, *rest in cur.fetchall()}


def statement_base(cur: Any, name: str) -> Optional[str]:
    """Keep the counts now as `name` (when pg_stat_statements is on): its time, or None."""
    cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements')")
    if not cur.fetchone()[0]:
        return None
    at = datetime.now(timezone.utc).isoformat()
    _STATEMENT_BASES[name] = (at, statement_counts(cur))
    return at


def _statements_since(cur: Any, limit: int, chars: int, base: Tuple[str, Dict[str, Tuple[float, ...]]]
                      ) -> Dict[str, Any]:
    """top_statements' answer for the counts since `base`."""
    at, before = base
    zero = (0.0,) * 6
    deltas = {q: tuple(a - b for a, b in zip(now, before.get(q, zero))) for q, now in statement_counts(cur).items()}
    deltas = {q: d for q, d in deltas.items() if d[0] > 0}
    total_ms = sum(d[1] for d in deltas.values())
    top = sorted(deltas.items(), key=lambda kv: (-kv[1][1], kv[0]))[:limit]
    texts: Dict[str, str] = {}
    if top:
        cur.execute(f"""SELECT DISTINCT ON (queryid) queryid, left(query, %s) FROM pg_stat_statements
                         WHERE {_THIS_DB} AND queryid = ANY(%s::bigint[])""", (chars, [int(q) for q, _ in top]))
        texts = {str(q): t for q, t in cur.fetchall()}
    return {"enabled": True, "since": at, "total_ms": round(total_ms, 1),
            "calls": int(sum(d[0] for d in deltas.values())),
            "statements": [{"id": q, "statement": " ".join((texts.get(q) or "").split()), "calls": int(n),
                            "total_ms": round(t, 1), "mean_ms": round(t / n, 2), "rows": int(r),
                            "blocks_hit": int(hit), "blocks_read": int(read), "temp_blocks_written": int(temp),
                            "share": round(t / total_ms, 4) if total_ms else None}
                           for q, (n, t, r, hit, read, temp) in top]}
