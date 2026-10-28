"""Source hygiene (issue 0046): the quiet and never-opened marks on the health row, Keep and
its 90-day return, and the Keep route.

The marks over a fake schedule view (test_source_health's helpers and FixedClock); Keep
end to end against a `_test` database (it commits); the route over a fake service.
"""
from __future__ import annotations

import sys
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.ingestion.schedule import Availability
from insight_core.services import registry as services_registry
from insight_core.services.operations_service import TIDY_KEEP_DAYS, OperationsService
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._ingestion_fakes import FixedClock
from insight_core.tests.test_source_health import NOW, make_service, state, view_row

DAY = timedelta(days=1)


def source(name: str, *, last_post_days: float | None = 40, gap_days: float | None = 1,
           posts: int = 30, opened: int = 1, added_days: float = 400, kept_days: float | None = None,
           failing: bool = False, enabled: bool = True, fetched: bool = True, **kw) -> dict:
    """A source that works, posts daily, was added long ago and was read, unless told otherwise."""
    if failing:
        fetch_state = state(name, last_outcome="error", last_error="HTTP 404", last_error_at=NOW - DAY,
                            last_success_at=NOW - 50 * DAY, consecutive_failures=4, next_retry_at=NOW + DAY)
    elif fetched:
        fetch_state = state(name, last_success_at=NOW - DAY, last_outcome="empty")
    else:
        fetch_state = None
    return {
        **view_row(name, enabled=enabled, post_count=posts, state=fetch_state,
                   gap=None if gap_days is None else gap_days * 86400, **kw),
        "last_post_at": None if last_post_days is None else NOW - last_post_days * DAY,
        "created_at": NOW - added_days * DAY,
        "opened_posts": opened,
        "tidy_kept_at": None if kept_days is None else NOW - kept_days * DAY,
    }


def rows(*sources: dict) -> dict:
    return {r["source_id"]: r for r in make_service(list(sources)).get_source_health()["rows"]}


def marks(row: dict) -> tuple:
    return row["quiet"], row["never_opened"]


class QuietTests(unittest.TestCase):
    def test_quiet_against_the_sources_own_cadence(self):
        got = rows(
            source("daily", last_post_days=40, gap_days=1),
            source("monthly", last_post_days=31, gap_days=30),      # one gap late: not quiet
            source("monthly-gone", last_post_days=100, gap_days=30),  # over 3 gaps: quiet
            source("fresh", last_post_days=10, gap_days=1),          # under 30 days: never quiet
            source("rare", last_post_days=40, gap_days=20),          # 40 days < 3 x 20
            source("unknown-gap", last_post_days=35, gap_days=None),  # no cadence: 30 days alone
        )
        self.assertTrue(got["daily"]["quiet"])
        self.assertFalse(got["monthly"]["quiet"])
        self.assertTrue(got["monthly-gone"]["quiet"])
        self.assertFalse(got["fresh"]["quiet"])
        self.assertFalse(got["rare"]["quiet"])
        self.assertTrue(got["unknown-gap"]["quiet"])

    def test_a_source_with_no_posts_counts_from_the_day_it_was_added(self):
        got = rows(source("empty-old", last_post_days=None, posts=0, added_days=60),
                   source("empty-new", last_post_days=None, posts=0, added_days=5))
        self.assertTrue(got["empty-old"]["quiet"])
        self.assertFalse(got["empty-new"]["quiet"])

    def test_quiet_needs_fetches_that_work(self):
        got = rows(source("never-fetched", fetched=False),
                   source("tube", platform="youtube"))           # unavailable: yt-dlp is off
        self.assertEqual(got["tube"]["status"], "unavailable")
        self.assertFalse(got["never-fetched"]["quiet"])
        self.assertFalse(got["tube"]["quiet"])


class NeverOpenedTests(unittest.TestCase):
    def test_twenty_posts_over_thirty_days_and_none_opened(self):
        got = rows(
            source("ignored", last_post_days=1, posts=214, opened=0, added_days=90),
            source("read-once", last_post_days=1, posts=214, opened=1, added_days=90),
            source("few", last_post_days=1, posts=19, opened=0, added_days=90),
            source("new", last_post_days=1, posts=214, opened=0, added_days=29),
        )
        self.assertEqual(marks(got["ignored"]), (False, True))
        self.assertEqual(marks(got["read-once"]), (False, False))
        self.assertEqual(marks(got["few"]), (False, False))
        self.assertEqual(marks(got["new"]), (False, False), "an archive brought 214 posts in a month: too soon")
        self.assertEqual(got["ignored"]["opened_posts"], 0)

    def test_both_marks_can_hold(self):
        got = rows(source("both", last_post_days=60, posts=40, opened=0))
        self.assertEqual(marks(got["both"]), (True, True))


class ExclusionTests(unittest.TestCase):
    def test_broken_disabled_and_saved_sources_get_neither_mark(self):
        got = rows(
            source("broken", last_post_days=60, opened=0, failing=True),
            source("off", last_post_days=60, opened=0, enabled=False),
            source("saved", last_post_days=60, opened=0, platform="saved"),
        )
        self.assertIn(got["broken"]["status"], ("error", "backoff"))
        for name in ("broken", "off", "saved"):
            with self.subTest(name):
                self.assertEqual(marks(got[name]), (False, False))


class KeepTests(unittest.TestCase):
    def test_keep_hides_the_marks_for_ninety_days_then_they_return_if_still_true(self):
        got = rows(
            source("kept", last_post_days=60, opened=0, kept_days=10),
            source("kept-long-ago", last_post_days=200, opened=0, kept_days=TIDY_KEEP_DAYS + 1),
            source("kept-and-fine-now", last_post_days=1, opened=3, kept_days=TIDY_KEEP_DAYS + 1),
        )
        self.assertEqual(marks(got["kept"]), (False, False))
        self.assertEqual(got["kept"]["tidy_kept_at"], (NOW - 10 * DAY).isoformat())
        self.assertEqual(marks(got["kept-long-ago"]), (True, True))
        self.assertEqual(marks(got["kept-and-fine-now"]), (False, False))


@requires_test_db
class KeepDbTests(unittest.TestCase):
    """OperationsService.keep_source end to end: it commits, so only on a `_test` database."""

    def setUp(self):
        self.url = db_url()
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur, enabled=True)
            cur.execute("UPDATE sources SET created_at = %s WHERE id = %s", (NOW - 100 * DAY, self.source_id))
            for i in range(25):
                cur.execute("INSERT INTO posts (source_id, url, published_at) VALUES (%s, %s, %s)",
                            (self.source_id, f"https://test.invalid/mark-ix/tidy/{self.source_id}/{i}",
                             NOW - (60 + i) * DAY))
            cur.execute("INSERT INTO source_fetch_state (source_id, last_success_at, last_outcome) "
                        "VALUES (%s, %s, 'empty')", (self.source_id, NOW - DAY))
            conn.commit()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def ops(self, now):
        return OperationsService(self.url, availability=lambda: Availability(ytdlp_enabled=False, telegram_credentials=False),
                                 clock=FixedClock(now))

    def test_keep_then_the_mark_returns_ninety_days_later(self):
        row = self.ops(NOW).get_source_health_row(self.source_id)
        self.assertEqual(marks(row), (True, True))
        kept = self.ops(NOW).keep_source(self.source_id)
        self.assertEqual(marks(kept), (False, False))
        self.assertEqual(kept["tidy_kept_at"], NOW.isoformat())
        self.assertEqual(marks(self.ops(NOW + 89 * DAY).get_source_health_row(self.source_id)), (False, False))
        self.assertEqual(marks(self.ops(NOW + 90 * DAY).get_source_health_row(self.source_id)), (True, True))
        with self.assertRaises(LookupError):
            self.ops(NOW).keep_source("00000000-0000-4000-8000-00000000dead")


class FakeOperations:
    def __init__(self):
        self.kept = []

    def keep_source(self, source_id):
        if source_id.endswith("dead"):
            raise LookupError(f"Source {source_id} not found")
        self.kept.append(source_id)
        return {"source_id": source_id, "quiet": False, "never_opened": False}


class KeepRouteTests(unittest.TestCase):
    def setUp(self):
        self.ops = FakeOperations()
        previous = services_registry.use(SimpleNamespace(operations=self.ops))
        self.addCleanup(services_registry.use, previous)

    def test_keep_returns_the_fresh_row_and_404_for_no_source(self):
        sid = "00000000-0000-4000-8000-000000000001"
        status, _, body = call(main.app, "POST", f"/api/sources/{sid}/tidy/keep")
        self.assertEqual((status, body["row"]["source_id"], self.ops.kept), (200, sid, [sid]))
        missing = "00000000-0000-4000-8000-00000000dead"
        status, _, body = call(main.app, "POST", f"/api/sources/{missing}/tidy/keep")
        self.assertEqual(status, 404, body)


if __name__ == "__main__":
    unittest.main()
