"""
Operational controls for scheduler config, job history, alerts, and source health.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from insight_core.db import database as db

from insight_core.db.repo_fetch_state import FetchStateRepository, FetchStateRow
from insight_core.db.repo_operations import JobRunsRepository, SystemSettingsRepository
from insight_core.ingestion.kinds.parsing import lost_most_images
from insight_core.ingestion.schedule import (
    BACKOFF_DORMANT_AFTER,
    Availability,
    DecisionKind,
    FetchDecision,
    availability_from_env,
    cadence_stats,
    decide_fetch,
    unavailable_reason,
)
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.utils.env import env_float
from insight_core.utils.json_safe import iso, json_safe


# Human labels per job type. Any other type (old rows, reddit_comments_fetch) reads as its
# own name: "safe_ingest" -> "Safe ingest".
JOB_LABELS: Dict[str, str] = {
    "ingestion_run": "Ingestion run",
    "scheduler_cycle": "Daily work",
    "archive_source": "Archive",
}


# The job types INSIGHT still runs. Rows of any other type (retired analysis jobs, kept by
# 0027_drop_analysis.sql; old safe_ingest rows) stay in job_runs but leave the job list.
LIVE_JOB_TYPES = ("ingestion_run", "scheduler_cycle", "archive_source")


def job_label(job_type: Optional[str]) -> str:
    job_type = job_type or ""
    return JOB_LABELS.get(job_type) or job_type.replace("_", " ").capitalize()


INGEST_TICK_MINUTES_MIN = 15
INGEST_TICK_MINUTES_MAX = 24 * 60

# Source health (spec §F.4). Every source lands in exactly one status; the summary counts
# the enabled ones, so its buckets add up to the number of enabled sources.
class HealthStatus(str, Enum):
    """The one place the status set lives; declaration order is the sort order (worst first)."""

    ERROR = "error"
    BACKOFF = "backoff"
    UNAVAILABLE = "unavailable"
    DUE = "due"
    DEFERRED = "deferred"
    DISABLED = "disabled"


HEALTH_STATUS_ORDER = tuple(status.value for status in HealthStatus)
# Summary wire keys (API contract, spec §F.4): a disabled source is not counted.
HEALTH_SUMMARY_KEYS: Dict[HealthStatus, str] = {
    HealthStatus.DUE: "due_now",
    HealthStatus.DEFERRED: "deferred",
    HealthStatus.BACKOFF: "backoff",
    HealthStatus.UNAVAILABLE: "unavailable",
    HealthStatus.ERROR: "errors",
}
# "Failing" in the spec glossary: retrying now (error) or waiting to retry (backoff).
FAILING_STATUSES = (HealthStatus.ERROR, HealthStatus.BACKOFF)
OVERVIEW_HEALTH_ROWS = 8


def empty_health_summary() -> Dict[str, int]:
    return {key: 0 for key in HEALTH_SUMMARY_KEYS.values()}


EMPTY_SOURCE_HEALTH: Dict[str, Any] = {"summary": empty_health_summary(), "rows": []}
CADENCE_OVERRIDE_MIN_HOURS = 1.0
CADENCE_OVERRIDE_MAX_HOURS = 2160.0   # 90 days


def backlog_posts(available_posts: Any, stored_posts: Any) -> Optional[int]:
    """E1: max(available - stored, 0) when the available count is a known int, else None."""
    if isinstance(available_posts, bool) or not isinstance(available_posts, int):
        return None
    return max(available_posts - int(stored_posts or 0), 0)


def last_attempt_failed(state: Optional[FetchStateRow]) -> bool:
    """The newest attempt failed: last_outcome is 'error' and no success came after it."""
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
        return HealthStatus.BACKOFF.value      # failing, its retry is scheduled
    # Failing and its retry is due now. A failed last attempt counts even with no failure
    # count: Mark VIII rows backfilled by 0019 can be last_outcome='error' with 0 failures.
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


# A source's page reads (repo_fetch_state.PAGE_READS_IN_HEALTH newest) that lost most of their
# images, or opened with a very short block, before its row says so: conservative, so one
# odd page never warns, and a source whose dropped images were related cards (NVIDIA) never
# counts them (parsing.read_fidelity estimates from the article block only).
READING_NOTICE_MIN = 3
SHORT_OPENINGS_MIN = 4


def reading_notice(page_reads: Any) -> Optional[str]:
    """What source health says about how a source's pages are read (issue 0032), or None:
    "Pages from this source lose most of their images (5 of the last 8)" when at least
    READING_NOTICE_MIN of its newest page reads and at least half of them did, and the like
    for openings under SHORT_OPENING_CHARS (three quarters of them)."""
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


def health_row(source: Dict[str, Any], kind: Any, availability: Availability, now: datetime) -> Dict[str, Any]:
    """One SourceHealthRow: the schedule view row + decide_fetch(force=False)."""
    state: Optional[FetchStateRow] = source.get("state")
    stats = cadence_stats(source, state)
    decision = decide_fetch(stats, kind.profile, now, force=False, availability=availability)
    enabled = bool(source.get("enabled"))
    # B8: why this kind cannot be fetched at all (yt-dlp off, no Telegram session, ...),
    # kept even for a disabled source so the table says why enabling it would not help.
    unavailable = unavailable_reason(kind.profile, availability)
    if not enabled:
        # As the runner's defensive path: a disabled source is never picked by a cycle
        # (fetch-now still works on it).
        detail = "Source is disabled" + (f"; unavailable: {unavailable}" if unavailable else "")
        decision = replace(decision, kind=DecisionKind.SKIP_DISABLED, fetch=False,
                           next_due_at=None, detail=detail)
    settings = source.get("settings") or {}
    archive = settings.get("archive") or {}
    failures = stats.consecutive_failures
    stored = int(source.get("post_count") or 0)
    return {
        "source_id": source["id"],
        "display_name": settings.get("display_name") or source.get("handle_or_url"),
        "platform": source.get("platform"),
        "kind": kind.name,
        "enabled": enabled,
        "in_main_digest": bool(source.get("in_main_digest", True)),
        "folders": list(source.get("folders") or []),
        "stored_posts": stored,
        # When its newest post was published (fetched, if undated): the list's "last new post".
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
        # A kind that still fetches but would fetch more with a credential (Substack
        # without a session: teasers only) says so here; None otherwise.
        "credential_notice": _credential_notice(kind),
        # How its newest page-read posts were read (page watch, full text): None, or a note.
        "reading_notice": reading_notice(source.get("page_reads")),
        "status": health_status(enabled, decision, failures, state),
        "last_attempt_at": iso(state.last_attempt_at if state else None),
        "last_success_at": iso(state.last_success_at if state else None),
        "last_outcome": state.last_outcome if state else None,
        "last_fetched_posts": state.last_fetched_posts if state else None,
        "last_error": state.last_error if state else None,
        "last_error_at": iso(state.last_error_at if state else None),
        "consecutive_failures": failures,
        "next_retry_at": iso(stats.next_retry_at),
        "dormant": failures >= BACKOFF_DORMANT_AFTER,
        **_doctor_fields(state),
    }


def _doctor_fields(state: Optional[FetchStateRow]) -> Dict[str, Any]:
    """The source doctor's finding (issue 0036): when it looked (None: it has not, in this
    failure streak, or the owner dismissed it, or the old address read again: a temporary
    error, nothing to replace) and the replacement it found
    ({kind: feed|page_watch, url, title, found, prefix}; None: nothing found)."""
    finding = (state.doctor_finding if state else None) or {}
    if state is None or state.doctor_checked_at is None or finding.get("dismissed") or finding.get("working_again"):
        return {"doctor_looked_at": None, "replacement": None}
    return {"doctor_looked_at": iso(state.doctor_checked_at), "replacement": finding.get("replacement")}


def _health_sort_key(row: Dict[str, Any]) -> tuple:
    status = row["status"]
    rank = HEALTH_STATUS_ORDER.index(status) if status in HEALTH_STATUS_ORDER else len(HEALTH_STATUS_ORDER)
    # ISO-8601 UTC strings sort chronologically; no due time sorts last within a status.
    return (rank, -row["consecutive_failures"], row["next_due_at"] or "~", str(row["display_name"]).lower())


def summarize_health(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    summary = empty_health_summary()
    for row in rows:
        try:
            key = HEALTH_SUMMARY_KEYS.get(HealthStatus(row["status"]))
        except ValueError:
            key = None
        if key:
            summary[key] += 1
    return summary


def sources_failing(summary: Dict[str, int]) -> int:
    """Sources whose last fetches failed: retrying now (errors) or waiting (backoff)."""
    return sum(int(summary.get(HEALTH_SUMMARY_KEYS[status], 0)) for status in FAILING_STATUSES)


class OperationsService:
    """Manage operational configuration and runtime telemetry."""

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
        # Health seams: the kind registry (built lazily: the default one constructs
        # YouTubeService), the availability probe and the clock.
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
        merged = self._normalize_scheduler_config({**existing, **(config or {})})

        payload = {
            "interval_hours": merged["interval_hours"],
            "sync_sources_each_cycle": merged["sync_sources_each_cycle"],
            "ingest_tick_minutes": merged["ingest_tick_minutes"],
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
        """Close out a job run.

        Pass compact=True when the payload is a full result graph, so long lists and
        long strings are cut before they land in job_runs. Callers
        that poll the job for its result - see pollOperationJob in the frontend -
        must keep compact=False.
        """
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

    # Tracked work (an archive, a fetch, a comment fetch) goes on when its job_runs row
    # cannot be written: these log the failure and return, instead of raising.

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
        """Delete job history older than retain_days. Returns rows removed.

        Without this, job_runs grows forever and every list query gets slower and
        more memory-hungry. Called once per scheduler cycle.
        """
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
                      COALESCE(s.settings->>'display_name', s.handle_or_url),
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
                      COALESCE(s.settings->>'display_name', s.handle_or_url),
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

    def get_operations_overview(self) -> Dict[str, Any]:
        # The SQL projection above is what fixed the memory, not this limit, so keep
        # enough history for the alerts panel to still catch a stale failure.
        # The scheduler writes ~4-6 rows per cycle, so 50 covers ~8-10 cycles.
        jobs = self.list_recent_jobs(50)
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
            "source_health": {"summary": summary, "rows": health["rows"][:OVERVIEW_HEALTH_ROWS]},
            "alerts": alerts,
            "stats": {
                "recent_failures": len([job for job in jobs if job["status"] == "failed"]),
                "sources_in_error": sources_failing(summary),
                "sources_monitored": len(health["rows"]),
                **counts,
            },
        }

    def get_database_counts(self) -> Dict[str, int]:
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      (SELECT COUNT(*) FROM posts) AS total_posts,
                      (SELECT COUNT(*) FROM sources WHERE enabled = TRUE) AS enabled_sources
                    """
                )
                row = cur.fetchone()

        return {
            "total_posts": int(row[0] or 0),
            "enabled_sources": int(row[1] or 0),
        }

    def get_corpus_freshness(self) -> Dict[str, Any]:
        """Corpus-wide freshness: newest/oldest post, latest fetch, last-24h volume."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      MAX(COALESCE(published_at, fetched_at)) AS latest,
                      MIN(COALESCE(published_at, fetched_at)) AS oldest,
                      MAX(fetched_at) AS latest_fetch,
                      COUNT(*) FILTER (WHERE fetched_at >= now() - interval '24 hours') AS last_24h
                    FROM posts
                    """
                )
                row = cur.fetchone()

        return {
            "latest_post_at": iso(row[0]),
            "oldest_post_at": iso(row[1]),
            "latest_fetch_at": iso(row[2]),
            "posts_last_24h": int(row[3] or 0),
        }

    # ------------------------------------------------------------------ source health

    def get_source_health(self) -> Dict[str, Any]:
        """SourcesHealthResponse (spec §F.4): one schedule-aware row per source plus a summary.

        Every row is cadence_stats(source, state) -> decide_fetch(..., force=False) with the
        source's resolved kind and the process availability, exactly as the runner decides,
        so the table and the next run cannot disagree. Rows are sorted worst first.
        """
        now = self.clock()
        rows = self._health_rows(self._load_schedule_view(), now)
        return {
            "success": True,
            "generated_at": now.isoformat(),
            "rows": rows,
            "summary": summarize_health(rows),
        }

    def get_source_health_row(self, source_id: str) -> Optional[Dict[str, Any]]:
        rows = self._health_rows(self._load_schedule_view([source_id]), self.clock())
        return rows[0] if rows else None

    def set_cadence_override(self, source_id: str, hours: Optional[float]) -> Dict[str, Any]:
        """Write sources.fetch_interval_hours_override and return the source's fresh row.

        The range (None or [1, 2160]) is validated by the route. LookupError if no source.
        """
        if not self._write_cadence_override(source_id, hours):
            raise LookupError(f"Source {source_id} not found")
        row = self.get_source_health_row(source_id)
        if row is None:
            raise LookupError(f"Source {source_id} not found")
        return row

    def dismiss_replacement(self, source_id: str) -> Dict[str, Any]:
        """Hide the source doctor's finding until the next failure streak; the fresh row.
        LookupError when the source has no finding."""
        dismissed = False
        if self._valid_id(source_id):
            with db.connection(self.db_url) as conn, conn.cursor() as cur:
                dismissed = FetchStateRepository().dismiss_doctor(cur, source_id)
                conn.commit()
        row = self.get_source_health_row(source_id) if dismissed else None
        if row is None:
            raise LookupError(f"Source {source_id} has no replacement to dismiss")
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
                "sync_sources_each_cycle": os.getenv("INSIGHT_SYNC_SOURCES_EACH_CYCLE", "true").lower() == "true",
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
            "sync_sources_each_cycle": bool(config.get("sync_sources_each_cycle", True)),
            "ingest_tick_minutes": int(tick) if float(tick).is_integer() else tick,
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
