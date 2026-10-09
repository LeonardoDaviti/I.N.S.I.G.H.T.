"""FetchStateRepository against the real database (rollback pattern, spec §5.2).

One transaction per test, rolled back in tearDown: the scratch sources, their posts and
their fetch state vanish, so this is safe on the live DB. Every assertion is scoped to the
test's own scratch rows.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_fetch_state import FetchStateRepository
from insight_core.ingestion.schedule import (
    DecisionKind,
    FetchDecision,
    tier_for,
)
from insight_core.ingestion.types import FetchOutcome, OutcomeStatus, Trigger
from insight_core.tests._db import db_url, insert_scratch_source, requires_db

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
H = timedelta(hours=1)


def no_backoff(_n: int) -> timedelta:
    return timedelta(hours=1)


def outcome(source_id: str, status: OutcomeStatus, *, fetched: int = 0,
            error: str | None = None) -> FetchOutcome:
    return FetchOutcome(source_id=source_id, status=status, fetched=fetched,
                        error=error, duration_s=0.1)


@requires_db
class FetchStateRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = FetchStateRepository()
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.source = insert_scratch_source(self.cur)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def record(self, status: OutcomeStatus, *, at: datetime = NOW, backoff=no_backoff, **kw):
        return self.repo.record_outcome(self.cur, outcome(self.source, status, **kw),
                                        trigger=Trigger.SCHEDULER, now=at, backoff=backoff)

    def add_posts(self, source_id: str, published: list[datetime]) -> None:
        for i, at in enumerate(published):
            self.cur.execute(
                "INSERT INTO posts (source_id, url, published_at) VALUES (%s, %s, %s)",
                (source_id, f"https://test.invalid/mark-ix/post/{source_id}/{i}", at),
            )

    # record_outcome ----------------------------------------------------------------

    def test_errors_count_up_and_a_success_resets(self):
        self.record(OutcomeStatus.ERROR, error="first")
        row = self.record(OutcomeStatus.ERROR, error="second", at=NOW + H)
        self.assertEqual(row.consecutive_failures, 2)
        self.assertEqual(row.last_error, "second")
        self.assertEqual(row.last_error_at, NOW + H)
        self.assertEqual(row.last_outcome, "error")
        self.assertIsNotNone(row.next_retry_at)
        self.assertIsNone(row.last_success_at)

        row = self.record(OutcomeStatus.EMPTY, at=NOW + 2 * H)
        self.assertEqual(row.consecutive_failures, 0)
        self.assertEqual(row.last_success_at, NOW + 2 * H)
        self.assertIsNone(row.next_retry_at)
        self.assertEqual(row.last_outcome, "empty")
        self.assertEqual(row.last_fetched_posts, 0)

    def test_healthy_records_the_post_count_and_trigger(self):
        row = self.record(OutcomeStatus.HEALTHY, fetched=7)
        self.assertEqual(row.last_fetched_posts, 7)
        self.assertEqual(row.last_trigger, "scheduler")
        self.assertEqual(row.last_attempt_at, NOW)

    def test_retry_deadline_comes_from_the_database_count(self):
        seen: list[int] = []

        def backoff(n: int) -> timedelta:
            seen.append(n)
            return timedelta(hours=n)

        self.record(OutcomeStatus.ERROR, error="x", backoff=backoff)
        row = self.record(OutcomeStatus.ERROR, error="x", backoff=backoff)
        self.assertEqual(seen, [1, 2])
        self.assertEqual(row.next_retry_at, NOW + 2 * H)

    def test_unavailable_leaves_the_counter_alone(self):
        self.record(OutcomeStatus.ERROR, error="boom")
        before = self.record(OutcomeStatus.ERROR, error="boom")
        row = self.record(OutcomeStatus.UNAVAILABLE, error="yt-dlp disabled", at=NOW + H)
        self.assertEqual(row.consecutive_failures, 2)
        self.assertEqual(row.next_retry_at, before.next_retry_at)
        self.assertEqual(row.last_error_at, before.last_error_at)
        self.assertEqual(row.last_outcome, "unavailable")
        self.assertEqual(row.last_error, "yt-dlp disabled")
        self.assertEqual(row.last_attempt_at, NOW + H)

    def test_record_outcomes_writes_several_rows_in_one_call(self):
        other = insert_scratch_source(self.cur)
        rows = self.repo.record_outcomes(
            self.cur,
            [outcome(self.source, OutcomeStatus.ERROR, error="a"),
             outcome(other, OutcomeStatus.HEALTHY, fetched=3),
             outcome(self.source, OutcomeStatus.ERROR, error="b")],
            trigger=Trigger.MANUAL, now=NOW, backoff=lambda n: timedelta(hours=n),
        )
        self.assertEqual(len(rows), 3)
        loaded = self.repo.load(self.cur, [self.source, other])
        self.assertEqual(loaded[self.source].consecutive_failures, 2)
        self.assertEqual(loaded[self.source].next_retry_at, NOW + 2 * H)
        self.assertEqual(loaded[other].last_fetched_posts, 3)
        self.assertEqual(loaded[other].last_trigger, "manual")

    # load / record_decisions ---------------------------------------------------------

    def test_load_returns_only_the_requested_ids(self):
        other = insert_scratch_source(self.cur)
        self.record(OutcomeStatus.HEALTHY, fetched=1)
        self.repo.record_outcome(self.cur, outcome(other, OutcomeStatus.EMPTY),
                                 trigger=Trigger.CLI, now=NOW, backoff=no_backoff)
        loaded = self.repo.load(self.cur, [self.source])
        self.assertEqual(set(loaded), {self.source})
        self.assertEqual(self.repo.load(self.cur, []), {})

    def test_record_decisions_keeps_the_outcome_fields(self):
        self.record(OutcomeStatus.HEALTHY, fetched=4)
        decision = FetchDecision(
            kind=DecisionKind.SKIP_NOT_DUE, fetch=False, post_limit=20, interval=24 * H,
            interval_basis="tier", next_due_at=NOW + 23 * H, next_retry_at=None, detail="x",
        )
        self.repo.record_decisions(self.cur, [(self.source, decision)], NOW + H)
        row = self.repo.load(self.cur, [self.source])[self.source]
        self.assertEqual(row.last_decision_kind, "skip_not_due")
        self.assertEqual(row.last_decision_at, NOW + H)
        self.assertEqual(row.next_due_at, NOW + 23 * H)
        self.assertEqual(row.last_fetched_posts, 4, "a decision must not wipe the outcome")

    # refresh_cadence -------------------------------------------------------------------

    def test_refresh_cadence_uses_the_latest_20_posts(self):
        # 25 posts 6h apart, plus 5 older ones 30 days apart that must fall outside the window.
        latest = [NOW - i * 6 * H for i in range(25)]
        self.add_posts(self.source, latest)
        sparse = insert_scratch_source(self.cur)
        self.add_posts(sparse, [NOW, NOW - 5 * H])

        updated = self.repo.refresh_cadence(self.cur, source_ids=[self.source, sparse])
        self.assertEqual(updated, 2)

        view = {r["id"]: r for r in self.repo.load_schedule_view(self.cur)}
        self.assertAlmostEqual(view[self.source]["mean_gap_seconds"], 6 * 3600, places=3)
        self.assertEqual(view[self.source]["cadence_sample_size"], 20)
        self.assertEqual(view[self.source]["cadence_tier"], "fast")
        self.assertIsNotNone(view[self.source]["cadence_computed_at"])

        self.assertEqual(view[sparse]["cadence_tier"], "unknown")
        self.assertIsNone(view[sparse]["mean_gap_seconds"])
        self.assertEqual(view[sparse]["cadence_sample_size"], 2)

    def test_one_shared_timestamp_is_no_cadence_signal(self):
        """A feed that stamps a whole batch with one time must not look infinitely fast."""
        self.add_posts(self.source, [NOW] * 10)
        self.repo.refresh_cadence(self.cur, source_ids=[self.source])
        row = next(r for r in self.repo.load_schedule_view(self.cur) if r["id"] == self.source)
        self.assertEqual(row["cadence_tier"], "unknown")
        self.assertIsNone(row["mean_gap_seconds"])

    def test_sql_tier_matches_tier_for_at_the_boundaries(self):
        gaps = [
            timedelta(hours=11, minutes=59),
            timedelta(hours=12),
            timedelta(days=7),
            timedelta(days=7, seconds=1),
            timedelta(days=30),
        ]
        sources = {}
        for gap in gaps:
            sid = insert_scratch_source(self.cur)
            self.add_posts(sid, [NOW, NOW - gap, NOW - 2 * gap])
            sources[sid] = gap
        self.repo.refresh_cadence(self.cur, source_ids=list(sources))
        view = {r["id"]: r for r in self.repo.load_schedule_view(self.cur)}
        for sid, gap in sources.items():
            with self.subTest(gap=gap):
                self.assertEqual(view[sid]["cadence_tier"], tier_for(gap, 3).value)

    # load_schedule_view ----------------------------------------------------------------

    def test_schedule_view_includes_override_cadence_and_state(self):
        self.cur.execute(
            "UPDATE sources SET fetch_interval_hours_override = 6, cadence_tier = 'medium', "
            "mean_gap_seconds = 86400, cadence_sample_size = 12 WHERE id = %s",
            (self.source,),
        )
        self.record(OutcomeStatus.HEALTHY, fetched=2)
        bare = insert_scratch_source(self.cur)

        view = {r["id"]: r for r in self.repo.load_schedule_view(self.cur)}
        row = view[self.source]
        self.assertEqual(row["fetch_interval_hours_override"], 6)
        self.assertEqual(row["cadence_tier"], "medium")
        self.assertEqual(row["mean_gap_seconds"], 86400)
        self.assertEqual(row["cadence_sample_size"], 12)
        self.assertEqual(row["post_count"], 0)
        self.assertEqual(row["folders"], [])
        self.assertEqual(row["state"].last_fetched_posts, 2)
        self.assertFalse(row["enabled"])
        self.assertIsNone(view[bare]["state"])

    def test_schedule_view_can_be_scoped_and_merges_platform_defaults(self):
        other = insert_scratch_source(self.cur)
        view = self.repo.load_schedule_view(self.cur, source_ids=[self.source])
        self.assertEqual([r["id"] for r in view], [self.source])
        self.assertNotIn(other, [r["id"] for r in view])
        # The same merged settings the runner's catalog hands to cadence_stats.
        self.assertIn("max_posts_per_fetch", view[0]["settings"])
        self.assertIn("archive", view[0]["settings"])
        self.assertEqual(self.repo.load_schedule_view(self.cur, source_ids=[]), [])

    # set_cadence_override --------------------------------------------------------------

    def test_set_cadence_override_writes_and_clears_the_column(self):
        self.assertTrue(self.repo.set_cadence_override(self.cur, self.source, 12.5))
        (row,) = self.repo.load_schedule_view(self.cur, source_ids=[self.source])
        self.assertEqual(row["fetch_interval_hours_override"], 12.5)

        self.assertTrue(self.repo.set_cadence_override(self.cur, self.source, None))
        (row,) = self.repo.load_schedule_view(self.cur, source_ids=[self.source])
        self.assertIsNone(row["fetch_interval_hours_override"])

        missing = "00000000-0000-4000-8000-000000000000"
        self.assertFalse(self.repo.set_cadence_override(self.cur, missing, 4))


if __name__ == "__main__":
    unittest.main()
