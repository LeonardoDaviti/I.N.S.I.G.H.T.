"""
Operational controls for scheduler config, job history, alerts, and source health.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

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
from insight_core.markx import pairing


# Human labels per job type. Any other type (old rows, reddit_comments_fetch) reads as its
# own name: "safe_ingest" -> "Safe ingest".
JOB_LABELS: Dict[str, str] = {
    "ingestion_run": "Ingestion run",
    "scheduler_cycle": "Daily work",
    "archive_source": "Archive",
    "api_restart": "API restart",   # issue 0117: the watchdog in insight-ingestion
}


# The job types INSIGHT still runs. Rows of any other type (retired analysis jobs, kept by
# 0027_drop_analysis.sql; old safe_ingest rows) stay in job_runs but leave the job list.
LIVE_JOB_TYPES = ("ingestion_run", "scheduler_cycle", "archive_source", "api_restart")


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
    """Each status's count, and `silent` (issue 0178): sources silent far beyond their rhythm, not a status."""
    return {**{key: 0 for key in HEALTH_SUMMARY_KEYS.values()}, "silent": 0}


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


def _kind_reading_notice(kind: Any, source: Dict[str, Any]) -> Optional[str]:
    """What a kind says about how this source's posts are read (Substack: paid posts as previews)."""
    notice = getattr(kind, "reading_notice", None)
    if not callable(notice):
        return None
    try:
        return notice(source)
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


# Source hygiene (issue 0046): two marks from data INSIGHT already has, never acted on alone.
QUIET_AFTER = timedelta(days=30)        # nothing new for at least this long...
QUIET_GAPS = 3                          # ...and for more than 3x the source's own mean gap
NEVER_OPENED_MIN_POSTS = 20             # at least this many posts...
NEVER_OPENED_MIN_AGE = timedelta(days=30)  # ...and added at least this long ago
TIDY_KEEP_DAYS = 90                     # Keep hides the marks this long; then they may return
NO_TIDY_MARKS = {"quiet": False, "never_opened": False}


def tidy_marks(source: Dict[str, Any], status: str, now: datetime) -> Dict[str, bool]:
    """Whether a source went quiet or was never opened (issue 0046).

    Quiet: its fetches work (it is on, available and not failing, and has fetched once), yet
    its newest post (or, with none, the day it was added) is older than QUIET_AFTER and than
    QUIET_GAPS times its mean gap between posts (unknown gap: QUIET_AFTER alone).
    Never opened: NEVER_OPENED_MIN_POSTS posts or more, added NEVER_OPENED_MIN_AGE ago or
    more, and none opened (opened_posts, repo_fetch_state.OPENED_POST_SQL: opened, read for
    a while, in Later, kept or part-read). Neither for a broken (failing) or disabled source,
    for saved pages, or within TIDY_KEEP_DAYS of the owner's Keep.
    """
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
        "reading_notice": ". ".join(filter(None, [reading_notice(source.get("page_reads")),
                                                  _kind_reading_notice(kind, source)])) or None,
        # Watch for changes (issue 0039): whether its kind can re-read its pages, and whether it does.
        "watchable": bool(getattr(kind, "watches", False)),
        "watch_changes": bool(getattr(kind, "watches", False) and settings.get("watch_changes")),
        "status": status,
        # Source hygiene (issue 0046): quiet / never opened, and the owner's last Keep.
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
        # Where its posts now live (issue 0108): {host, followed}; the owner chooses, nothing is switched off.
        "moved_to": source.get("moved_to"),
        **_doctor_fields(state, source.get("handle_or_url")),
        # Silent far beyond its own rhythm (issue 0178), and where the doctor found it went; None otherwise.
        "silent": silent_fields(source, state, status, now),
    }


def silent_fields(source: Dict[str, Any], state: Optional[FetchStateRow], status: str,
                  now: datetime) -> Optional[Dict[str, Any]]:
    """A source silent far beyond its own rhythm (issue 0178, source_doctor.silent_beyond_rhythm): {days,
    usual_gap_hours, last_post_at, looked_at, moved, replacement}, the doctor's look (looked_at None: not yet, or
    its kind has no address to move) when it was made since the source's newest post. None when it is not
    silent, is off, failing (the failure doctor speaks then) or the owner's saved pages, or the owner said it
    stopped and nothing came since."""
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
    """Dormant is what it waits (issue 0088): 10 failures in a row and a wait past the 24h cap. A 5xx
    or a timeout waits at most 12h however many failures, so it is never dormant."""
    if failures < BACKOFF_DORMANT_AFTER:
        return False
    if state is None or state.next_retry_at is None or state.last_error_at is None:
        return True
    return state.next_retry_at - state.last_error_at > BACKOFF_MAX


def _doctor_fields(state: Optional[FetchStateRow], address: Optional[str] = None) -> Dict[str, Any]:
    """The source doctor's finding (issue 0036): when it looked (None: it has not, in this
    failure streak, or the owner dismissed it, or the old address read again: a temporary
    error, nothing to replace, or the site answered a server error: no move, issue 0072) and the
    replacement it found ({kind: feed|page_watch, url, title, found, prefix, shared, latest};
    None: nothing found), and `server_error` {status, site} when it read a server error (issue 0072 D3;
    `site`, issue 0088: whose server, "example.org", "" when the address has no host)."""
    finding = (state.doctor_finding if state else None) or {}
    # A server error is no move (issue 0072 D3): the sheet says the server is failing, {status} (None: timed out).
    failing = {"status": finding.get("status"), "site": publication_of(host_of(address))} if state and state.doctor_checked_at and finding.get("server_error") else None
    if (state is None or state.doctor_checked_at is None or finding.get("dismissed")
            or finding.get("working_again") or finding.get("server_error")
            # A fetch that stored nothing (issue 0135): nothing was looked for; last_error says why.
            or finding.get("empty_fetch")):
        return {"doctor_looked_at": None, "replacement": None, "server_error": failing}
    replacement = finding.get("replacement")
    # An offer stored before 0072 was never checked against the source's items: not offered.
    if isinstance(replacement, dict) and "shared" not in replacement:
        replacement = None
    return {"doctor_looked_at": iso(state.doctor_checked_at), "replacement": replacement, "server_error": None}


def _health_sort_key(row: Dict[str, Any]) -> tuple:
    status = row["status"]
    rank = HEALTH_STATUS_ORDER.index(status) if status in HEALTH_STATUS_ORDER else len(HEALTH_STATUS_ORDER)
    # ISO-8601 UTC strings sort chronologically; no due time sorts last within a status.
    return (rank, -row["consecutive_failures"], row["next_due_at"] or "~", str(row["display_name"]).lower())


def summarize_health(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    """Each enabled source in its status's bucket. `errors` counts every failing source (issue 0137 A1):
    retrying now, and waiting to retry after failures (also counted in `backoff`), so "errors": 0 means
    no source is failing."""
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
            summary["silent"] += 1   # silent far beyond its rhythm (issue 0178), whatever its status
    return summary


def _ago(span: timedelta) -> str:
    """A span for a health reason: minutes under 2 hours, else hours."""
    seconds = span.total_seconds()
    return f"{seconds / 60:.0f} minutes" if seconds < 7200 else f"{seconds / 3600:.1f} hours"


def sources_failing(summary: Dict[str, int]) -> int:
    """Sources whose last fetches failed: retrying now or waiting (backoff), every one in `errors`."""
    return int(summary.get(HEALTH_SUMMARY_KEYS[HealthStatus.ERROR], 0))


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
        config = config or {}
        merged = self._normalize_scheduler_config({**existing, **config})
        # The switch as you set it now, else as it was; marked as this default's, so a false is your choice (0126).
        merged["collect_originals"] = (bool(config["collect_originals"]) if config.get("collect_originals") is not None
                                       else existing["collect_originals"])

        payload = {
            "interval_hours": merged["interval_hours"],
            "ingest_tick_minutes": merged["ingest_tick_minutes"],
            "collect_originals": merged["collect_originals"],
            COLLECT_CHOSEN[0]: COLLECT_CHOSEN[1],
            "lookup_originals": merged["lookup_originals"],   # issue 0138 C: off unless you switch it on
            "store_classics": merged["store_classics"],       # issue 0138 E1: on unless you switch it off
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

    def close_interrupted_jobs(self, trigger: str) -> int:
        """At a process's start (issue 0070): the jobs it runs (`trigger`: "manual" the API's,
        "scheduler" the scheduler's) still `running` were ended by its restart, so they become
        `interrupted`, with an event saying so, and the top bar stops saying "fetching". Returns how many."""
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

    # A job that waits (issue 0107: an archive waiting out a host's limit) is not finished: its
    # status is `waiting`, `waiting_until` in its payload says when it continues, and the process
    # that continues it claims it first.

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
        """waiting -> running, as this process's job (`trigger`); {id, source_id, payload}, or None
        when the job is not waiting (another process claimed it first)."""
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
        """At the scheduler's start: the archives it was continuing when it stopped wait again, due
        now, so they carry on by themselves (a deploy must not need a Resume). Returns how many."""
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

    # Tracked work (an archive, a fetch, a comment fetch) goes on when its job_runs row
    # cannot be written: these log the failure and return, instead of raising.

    def start_job_unless_running(self, job_type: str, *, source_id: str, trigger: str = "manual",
                                 message: Optional[str] = None, payload: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """start_job, unless a job of this type for this source is running: None then. The check and the insert run
        under one lock on (type, source), so two API processes (0112 Decided 11) can't both start one. A failure to
        write the row is logged and raised."""
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
        """The start times (epoch seconds) of this type's jobs in the last `seconds`, with payload.kind = `kind` when
        given (the API watchdog's restarts of the last hour, issue 0117)."""
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
        """Sources -> Ingestion -> overview's Background work (issue 0062): the story job's last run
        and whether it runs now, and how far search indexing and link reading are. Read only."""
        from insight_core.db.repo_background import background_work
        from insight_core.services.stories_service import LOCK_KEY, SETTINGS_KEY

        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            return {"success": True, **background_work(cur, stories_key=SETTINGS_KEY, stories_lock=LOCK_KEY)}

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

    # ------------------------------------------------------------------ the system's health (issue 0188)

    def system_health(self, now: Optional[datetime] = None, *, failing_sources: Optional[int] = None) -> Dict[str, Any]:
        """/api/status's `healthy`, from real checks (was a literal True). {healthy, reasons (what makes it
        unhealthy), warnings (shown, never unhealthy alone), checks (the numbers read)}:
          - ingestion: the newest successful ingestion run is older than the fetch interval plus two ticks (every
            source is due within the interval, so a run must have happened), or the scheduler's next tick is two
            ticks overdue (its loop stopped);
          - the scheduler's and Mark X's loops (utils/heartbeat.py, the logs volume): a heartbeat past its limit;
          - Mark X (when on): a job failing (markx/jobs.py: FAILING_AFTER failed runs in a row), or the newest
            finished decision run older than 2 x jobs.EVERY;
          - warnings: failing sources (a source failing is the site's trouble, not the system's), workers silent
            for more than WORKER_STALE_DAYS (markx/news.py).
        Each check that cannot be read is a reason of its own."""
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
        checks["markx"] = {"jobs": {job: {k: v.get(k) for k in ("failures", "failing", "retry_at", "finished_at")}
                                    | {"ok": (v.get("last") or {}).get("ok")} for job, v in view.items()},
                           "last_decision_run_at": iso(last_run)}
        for job, v in view.items():
            if v["failing"]:
                error = (v.get("last") or {}).get("error") or "no error recorded"
                reasons.append(f"Mark X's {job} job failed {v['failures']} times in a row ({str(error)[:120]})")
        if last_run is None or (now - last_run).total_seconds() > 2 * jobs.EVERY:
            reasons.append("no Mark X decision run has finished" if last_run is None
                           else f"the last Mark X decision run finished {_ago(now - last_run)} ago")
        if stale_workers:
            warnings.append(f"Mark X workers silent for over {markx_news.WORKER_STALE_DAYS} days: "
                            + ", ".join(stale_workers))

    def table_sizes(self, limit: int = 15) -> List[Dict[str, Any]]:
        """Issue 0188: the biggest tables with their indexes and TOAST (pg_total_relation_size), largest first;
        reported only: nothing is pruned (the owner keeps everything)."""
        with db.connection(self.db_url) as conn, conn.cursor() as cur:
            cur.execute("""SELECT c.relname, pg_total_relation_size(c.oid), c.reltuples::bigint
                             FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                            WHERE c.relkind IN ('r', 'p', 'm') AND n.nspname = current_schema()
                            ORDER BY 2 DESC LIMIT %s""", (limit,))
            return [{"table": name, "bytes": int(size), "rows_estimate": max(int(rows), 0)}
                    for name, size, rows in cur.fetchall()]

    def get_corpus_freshness(self) -> Dict[str, Any]:
        """Corpus-wide freshness: newest/oldest post, latest fetch, last-24h volume."""
        with db.connection(self.db_url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                      MAX({pairing.ix_date('')}) AS latest,
                      MIN({pairing.ix_date('')}) AS oldest,
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
            "host_limits": self.host_limits(),
        }

    def host_limits(self) -> List[Dict[str, Any]]:
        """Each host's budget as learned from the limits archives met (issue 0107), by host:
        [{host, requests, window_s, limits, archive_gap_s, line}]. An archive paces to it once
        learned from LEARN_AFTER limits. Never raises: health does not fail for it."""
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

    def source_stopped(self, source_id: str) -> Dict[str, Any]:
        """The owner says a silent source stopped (issue 0178): its silence is not shown again until it posts.
        Nothing is switched off or deleted. The fresh row; LookupError for no such source."""
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
        """Keep a source marked quiet or never opened (issue 0046): its marks hide for
        TIDY_KEEP_DAYS and come back only if still true then. The fresh row; LookupError
        for no such source."""
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
            # Issue 0123: a News story's original collected when INSIGHT lacks it. On unless you switched it off (0126).
            "collect_originals": collect_setting(config),
            # Issue 0138 C: a title lookup for a document entity no post links. Off unless you switch it on.
            "lookup_originals": lookup_setting(config),
            # Issue 0138 E1: every Classic not stored collected once, under its own allowance. On unless switched off.
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
