"""Fetch state: the persisted per-source scheduling memory (table source_fetch_state).

Replaces the Mark VIII settings.ops / settings.ingest_backoff JSONB blocks, which were
written by read-modify-write across two connections and so could clobber each other.
Every write here is a single UPSERT, and the failure counter is incremented in SQL.

Every method takes the caller's cursor and never commits: the caller owns the
transaction. Spec: plan/INSIGHT_mark_ix_plan.md §C.3.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence

from psycopg import Cursor

from insight_core.db.repo_posts import PAGE_READ_KEY
from insight_core.db.repo_sources import SourcesRepository
from insight_core.ingestion.types import FetchOutcome, OutcomeStatus, Trigger

if TYPE_CHECKING:
    from insight_core.ingestion.schedule import FetchDecision

# Tier boundaries in seconds, mirrored from ingestion/schedule.py (FAST_BELOW,
# MEDIUM_UP_TO). Kept as literals so this module does not import the schedule at load
# time; test_repo_fetch_state pins SQL tier == tier_for over the boundary cases.
FAST_BELOW_SECONDS = 12 * 3600
MEDIUM_UP_TO_SECONDS = 7 * 24 * 3600

MAX_ERROR_LENGTH = 2000
PAGE_READS_IN_HEALTH = 8    # the newest page-read posts source health sums (issue 0032)


@dataclass(frozen=True)
class FetchStateRow:
    """Mirrors source_fetch_state's columns."""

    source_id: str
    last_attempt_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None    # healthy OR empty: the fetch worked
    last_outcome: Optional[str] = None
    last_trigger: Optional[str] = None
    last_fetched_posts: Optional[int] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    consecutive_failures: int = 0
    next_retry_at: Optional[datetime] = None
    last_decision_kind: Optional[str] = None
    last_decision_at: Optional[datetime] = None
    next_due_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


_COLUMNS = [f.name for f in fields(FetchStateRow)]
_SELECT_COLUMNS = ", ".join(_COLUMNS)


def _row(values: Sequence[Any]) -> FetchStateRow:
    data = dict(zip(_COLUMNS, values))
    data["source_id"] = str(data["source_id"])
    data["consecutive_failures"] = int(data["consecutive_failures"] or 0)
    return FetchStateRow(**data)


def _value(enum_or_str: Any) -> Any:
    return getattr(enum_or_str, "value", enum_or_str)


def _error_text(error: Optional[str]) -> Optional[str]:
    if error is None:
        return None
    return error if len(error) <= MAX_ERROR_LENGTH else error[:MAX_ERROR_LENGTH] + "..."


# The cadence refresh. {source_filter} is either empty or "AND source_id = ANY(...)".
# Migration 0019 runs a literal copy of this once, so the UI is not blank after deploy.
#
# cadence_sample_size counts DISTINCT publication timestamps, not posts: a feed that stamps
# a whole batch with one time (4 live sources did on 2026-10-09) has a mean gap of 0, and
# the backlog guard would then poll it hourly. One distinct timestamp is no cadence signal,
# so such a source stays `unknown` (24h probation) instead.
_REFRESH_CADENCE_SQL = """
WITH ranked AS (
    SELECT source_id, published_at,
           row_number() OVER (PARTITION BY source_id ORDER BY published_at DESC) AS rn
    FROM posts
    WHERE published_at IS NOT NULL {post_filter}
), agg AS (
    SELECT source_id,
           count(DISTINCT published_at)::int AS samples,
           EXTRACT(EPOCH FROM (max(published_at) - min(published_at)))
               / NULLIF(count(*) - 1, 0) AS gap
    FROM ranked
    WHERE rn <= %(window)s
    GROUP BY source_id
), target AS (
    SELECT s2.id,
           COALESCE(a.samples, 0) AS samples,
           CASE WHEN COALESCE(a.samples, 0) >= %(min_samples)s THEN a.gap END AS gap
    FROM sources s2
    LEFT JOIN agg a ON a.source_id = s2.id
    WHERE TRUE {source_filter}
)
UPDATE sources s SET
    cadence_sample_size = t.samples,
    mean_gap_seconds = t.gap,
    cadence_tier = CASE
        WHEN t.gap IS NULL THEN 'unknown'
        WHEN t.gap < %(fast_below)s THEN 'fast'
        WHEN t.gap <= %(medium_up_to)s THEN 'medium'
        ELSE 'slow'
    END,
    cadence_computed_at = now()
FROM target t
WHERE s.id = t.id
"""


class FetchStateRepository:
    """Database access for source_fetch_state and the sources cadence columns."""

    def load(self, cur: Cursor, source_ids: Sequence[str]) -> Dict[str, FetchStateRow]:
        ids = [str(s) for s in source_ids]
        if not ids:
            return {}
        cur.execute(
            f"SELECT {_SELECT_COLUMNS} FROM source_fetch_state WHERE source_id = ANY(%s::uuid[])",
            (ids,),
        )
        return {row.source_id: row for row in (_row(r) for r in cur.fetchall())}

    def record_decisions(
        self, cur: Cursor, decisions: Sequence[tuple[str, "FetchDecision"]], now: datetime
    ) -> None:
        if not decisions:
            return
        cur.executemany(
            """
            INSERT INTO source_fetch_state (source_id, last_decision_kind, last_decision_at,
                                            next_due_at, updated_at)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_id) DO UPDATE SET
                last_decision_kind = EXCLUDED.last_decision_kind,
                last_decision_at = EXCLUDED.last_decision_at,
                next_due_at = EXCLUDED.next_due_at,
                updated_at = EXCLUDED.updated_at
            """,
            [
                (str(source_id), _value(decision.kind), now, decision.next_due_at, now)
                for source_id, decision in decisions
            ],
        )

    def record_outcome(
        self,
        cur: Cursor,
        outcome: FetchOutcome,
        *,
        trigger: Trigger | str,
        now: datetime,
        backoff: Callable[[int], timedelta],
    ) -> FetchStateRow:
        """One atomic UPSERT; the failure counter is computed in SQL, never read-modify-write.

        error: counter + 1, last_error/_at set, next_retry_at = now + backoff(new count).
        healthy/empty: counter reset, next_retry_at cleared, last_success_at = now.
        unavailable: only last_attempt_at, last_outcome and last_error (+ trigger) move.
        """
        status = OutcomeStatus(_value(outcome.status))
        params = {
            "sid": str(outcome.source_id),
            "now": now,
            "status": status.value,
            "trigger": _value(trigger),
            "fetched": outcome.fetched,
            "error": _error_text(outcome.error),
        }

        if status.is_success:
            cur.execute(
                f"""
                INSERT INTO source_fetch_state (source_id, last_attempt_at, last_success_at,
                    last_outcome, last_trigger, last_fetched_posts, consecutive_failures,
                    next_retry_at, updated_at)
                VALUES (%(sid)s, %(now)s, %(now)s, %(status)s, %(trigger)s, %(fetched)s, 0,
                        NULL, %(now)s)
                ON CONFLICT (source_id) DO UPDATE SET
                    last_attempt_at = EXCLUDED.last_attempt_at,
                    last_success_at = EXCLUDED.last_success_at,
                    last_outcome = EXCLUDED.last_outcome,
                    last_trigger = EXCLUDED.last_trigger,
                    last_fetched_posts = EXCLUDED.last_fetched_posts,
                    consecutive_failures = 0,
                    next_retry_at = NULL,
                    updated_at = EXCLUDED.updated_at
                RETURNING {_SELECT_COLUMNS}
                """,
                params,
            )
            return _row(cur.fetchone())

        if status == OutcomeStatus.UNAVAILABLE:
            cur.execute(
                f"""
                INSERT INTO source_fetch_state (source_id, last_attempt_at, last_outcome,
                    last_trigger, last_error, updated_at)
                VALUES (%(sid)s, %(now)s, %(status)s, %(trigger)s, %(error)s, %(now)s)
                ON CONFLICT (source_id) DO UPDATE SET
                    last_attempt_at = EXCLUDED.last_attempt_at,
                    last_outcome = EXCLUDED.last_outcome,
                    last_trigger = EXCLUDED.last_trigger,
                    last_error = EXCLUDED.last_error,
                    updated_at = EXCLUDED.updated_at
                RETURNING {_SELECT_COLUMNS}
                """,
                params,
            )
            return _row(cur.fetchone())

        # error
        cur.execute(
            """
            INSERT INTO source_fetch_state (source_id, last_attempt_at, last_outcome,
                last_trigger, last_error, last_error_at, consecutive_failures, updated_at)
            VALUES (%(sid)s, %(now)s, %(status)s, %(trigger)s, %(error)s, %(now)s, 1, %(now)s)
            ON CONFLICT (source_id) DO UPDATE SET
                last_attempt_at = EXCLUDED.last_attempt_at,
                last_outcome = EXCLUDED.last_outcome,
                last_trigger = EXCLUDED.last_trigger,
                last_error = EXCLUDED.last_error,
                last_error_at = EXCLUDED.last_error_at,
                consecutive_failures = source_fetch_state.consecutive_failures + 1,
                updated_at = EXCLUDED.updated_at
            RETURNING consecutive_failures
            """,
            params,
        )
        failures = int(cur.fetchone()[0])
        # The delay comes from the count the database returned, so two concurrent runs
        # cannot both write a delay computed from a stale count.
        cur.execute(
            f"""
            UPDATE source_fetch_state SET next_retry_at = %s
            WHERE source_id = %s
            RETURNING {_SELECT_COLUMNS}
            """,
            (now + backoff(failures), params["sid"]),
        )
        return _row(cur.fetchone())

    def record_outcomes(
        self,
        cur: Cursor,
        outcomes: Sequence[FetchOutcome],
        *,
        trigger: Trigger | str,
        now: datetime,
        backoff: Callable[[int], timedelta],
    ) -> List[FetchStateRow]:
        return [
            self.record_outcome(cur, outcome, trigger=trigger, now=now, backoff=backoff)
            for outcome in outcomes
        ]

    def refresh_cadence(
        self,
        cur: Cursor,
        *,
        window: int = 20,
        min_samples: int = 3,
        source_ids: Optional[Sequence[str]] = None,
    ) -> int:
        """Recompute mean gap, sample size and tier from the latest `window` dated posts.

        Sources with fewer than `min_samples` distinct publication timestamps get
        tier 'unknown' and a NULL mean gap. `source_ids` scopes the refresh (tests use it
        to touch only their scratch rows); None refreshes every source. Returns rows updated.
        """
        params: Dict[str, Any] = {
            "window": int(window),
            "min_samples": int(min_samples),
            "fast_below": FAST_BELOW_SECONDS,
            "medium_up_to": MEDIUM_UP_TO_SECONDS,
        }
        post_filter = source_filter = ""
        if source_ids is not None:
            params["ids"] = [str(s) for s in source_ids]
            post_filter = "AND source_id = ANY(%(ids)s::uuid[])"
            source_filter = "AND s2.id = ANY(%(ids)s::uuid[])"
        cur.execute(
            _REFRESH_CADENCE_SQL.format(post_filter=post_filter, source_filter=source_filter),
            params,
        )
        return cur.rowcount or 0

    def load_schedule_view(
        self, cur: Cursor, source_ids: Optional[Sequence[str]] = None
    ) -> List[Dict[str, Any]]:
        """Every source with its cadence columns, added date, post count, newest post, folders,
        its newest page reads (`page_reads`: the metadata.page_read of its PAGE_READS_IN_HEALTH
        newest page-read posts, newest first) and fetch state.

        For GET /api/sources/health: feed each row to cadence_stats(row, row["state"]).
        `settings` is merged with the platform defaults exactly as the runner's source
        catalog merges it, so max_posts_per_fetch (and with it the backlog guard) agrees.
        `source_ids` scopes the view (the cadence PUT returns one fresh row); None = all.
        """
        params: Dict[str, Any] = {}
        where = ""
        if source_ids is not None:
            params["ids"] = [str(s) for s in source_ids]
            if not params["ids"]:
                return []
            where = "WHERE s.id = ANY(%(ids)s::uuid[])"
        state_columns = ", ".join(f"st.{c}" for c in _COLUMNS)
        cur.execute(
            f"""
            SELECT s.id, s.platform, s.handle_or_url, s.enabled, s.in_main_digest, s.settings,
                   s.mean_gap_seconds, s.cadence_sample_size, s.cadence_tier,
                   s.cadence_computed_at, s.fetch_interval_hours_override, s.created_at,
                   (SELECT count(*) FROM posts p WHERE p.source_id = s.id) AS post_count,
                   (SELECT max(COALESCE(p.published_at, p.fetched_at)) FROM posts p
                     WHERE p.source_id = s.id) AS last_post_at,
                   COALESCE((
                       SELECT json_agg(json_build_object('id', f.id, 'name', f.name)
                                       ORDER BY f.name)
                       FROM source_folders sf JOIN folders f ON f.id = sf.folder_id
                       WHERE sf.source_id = s.id
                   ), '[]'::json) AS folders,
                   (SELECT COALESCE(json_agg(r.page_read ORDER BY r.fetched_at DESC), '[]'::json)
                      FROM (SELECT p.metadata -> '{PAGE_READ_KEY}' AS page_read, p.fetched_at
                              FROM posts p
                             WHERE p.source_id = s.id AND p.metadata ? '{PAGE_READ_KEY}'
                             ORDER BY p.fetched_at DESC LIMIT {PAGE_READS_IN_HEALTH}) r) AS page_reads,
                   {state_columns}
            FROM sources s
            LEFT JOIN source_fetch_state st ON st.source_id = s.id
            {where}
            ORDER BY s.platform, s.handle_or_url
            """,
            params,
        )
        defaults = SourcesRepository("")
        rows: List[Dict[str, Any]] = []
        for r in cur.fetchall():
            state_values = r[16:]
            rows.append(
                {
                    "id": str(r[0]),
                    "platform": r[1],
                    "handle_or_url": r[2],
                    "enabled": r[3],
                    "in_main_digest": r[4],
                    "settings": defaults.merge_with_defaults(r[1], r[5] or {}),
                    "mean_gap_seconds": r[6],
                    "cadence_sample_size": r[7],
                    "cadence_tier": r[8],
                    "cadence_computed_at": r[9],
                    "fetch_interval_hours_override": r[10],
                    "created_at": r[11],
                    "post_count": int(r[12] or 0),
                    "last_post_at": r[13],
                    "folders": [{"id": str(f["id"]), "name": f["name"]} for f in (r[14] or [])],
                    # How the newest page-read posts were read, newest first (issue 0032).
                    "page_reads": list(r[15] or []),
                    "state": _row(state_values) if state_values[0] is not None else None,
                }
            )
        return rows

    def set_cadence_override(self, cur: Cursor, source_id: str, hours: Optional[float]) -> bool:
        """Write sources.fetch_interval_hours_override (None clears it). False if no such source.

        Range validation is the route's job; the column's CHECK (> 0) is the last line.
        """
        cur.execute(
            "UPDATE sources SET fetch_interval_hours_override = %s, updated_at = now() WHERE id = %s",
            (None if hours is None else float(hours), str(source_id)),
        )
        return (cur.rowcount or 0) > 0
