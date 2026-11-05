"""Issue 0107: each host's budget, learned from the limits an archive meets.

A measure is the requests that went through from one recovery (an archive's start, or the first
success after a limit) to the next limit, over the time from that recovery to the next one.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.host_budgets import (  # noqa: E402
    HostBudgets,
    LearnedBudget,
    MemoryHostBudgetStore,
)
from insight_core.ingestion.ports import DbHostBudgetStore  # noqa: E402
from insight_core.services.operations_service import OperationsService  # noqa: E402
from insight_core.tests._db import db_url, requires_test_db  # noqa: E402

import psycopg  # noqa: E402

HOST = "bridge.example"
T0 = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class HostBudgetsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clock = Clock()
        self.store = MemoryHostBudgetStore()
        self.budgets = HostBudgets(self.store, clock=self.clock)

    async def window(self, requests: int, *, then_wait_min: float, spend_s: float = 10):
        """`requests` successes `spend_s` apart, a limit, then `then_wait_min` minutes of waiting."""
        for _ in range(requests):
            await self.budgets.succeeded(HOST)
            self.clock.advance(seconds=spend_s)
        await self.budgets.limited(HOST)
        self.clock.advance(minutes=then_wait_min)

    async def test_nothing_is_learned_before_two_limits_are_measured(self):
        await self.budgets.archive_started(HOST)
        await self.window(40, then_wait_min=10)
        self.assertIsNone(self.budgets.learned(HOST))
        learned = await self.budgets.succeeded(HOST)       # the recovery measures the first limit
        self.assertEqual(learned.limits, 1)
        self.assertIsNone(self.budgets.learned(HOST), "one limit is not enough to pace by")

    async def test_two_limits_give_the_requests_per_window_from_recovery_to_recovery(self):
        await self.budgets.archive_started(HOST)
        await self.window(40, then_wait_min=10)             # 400 s spent, 10 min waited
        await self.window(40, then_wait_min=12)             # the recovery is request 1 of these 40
        learned = await self.budgets.succeeded(HOST)
        self.assertEqual(learned, self.budgets.learned(HOST))
        self.assertEqual(learned.limits, 2)
        self.assertEqual(learned.requests, 40)
        # From recovery to recovery, not the minutes waited: 40 per 400 s + 10 min and per 400 s + 12 min. Both
        # refused at 400 s, so one window under 400 s + 10 min: the narrower (issue 0107's follow-up).
        self.assertEqual(learned.window_s, 400 + 10 * 60)
        self.assertEqual(learned.line(), f"{HOST}: about 40 requests per 17 min, learned from 2 limits")

    async def test_an_archive_paces_to_80_percent_of_the_budget(self):
        budget = LearnedBudget(HOST, requests=40, window_s=900, limits=2)
        self.assertAlmostEqual(budget.archive_gap_s(), 900 / 32)

    async def test_the_second_limit_in_a_row_is_the_same_limit(self):
        await self.budgets.archive_started(HOST)
        await self.window(40, then_wait_min=1)
        await self.budgets.limited(HOST)                    # the retry: still the same window
        self.clock.advance(minutes=9)
        learned = await self.budgets.succeeded(HOST)
        self.assertEqual((learned.requests, learned.window_s), (40, 400 + 10 * 60))

    async def test_live_requests_in_the_process_count_against_the_budget(self):
        await self.budgets.archive_started(HOST)
        for _ in range(30):
            await self.budgets.succeeded(HOST)
        for _ in range(5):
            self.budgets.counted(HOST)                       # an hourly fetch of the same host
        await self.budgets.limited(HOST)
        self.clock.advance(minutes=15)
        learned = await self.budgets.succeeded(HOST)
        self.assertEqual(learned.requests, 35)

    async def test_live_requests_alone_measure_nothing(self):
        """An hourly fetch is not a busy window: its requests only count while an archive runs."""
        for _ in range(5):
            self.budgets.counted(HOST)
        self.assertEqual(self.store.load_all(), {})

    async def test_the_measures_survive_the_process_and_a_new_process_continues_after_a_wait(self):
        await self.budgets.archive_started(HOST)
        await self.window(40, then_wait_min=10)
        self.budgets.archive_stopped(HOST)                   # the archive waits; another process continues it
        other = HostBudgets(self.store, clock=self.clock)
        await other.archive_started(HOST)
        self.assertIsNotNone(await other.succeeded(HOST), "the recovery measures the limit the first process met")
        await self.window_on(other, 40, then_wait_min=10)
        await other.succeeded(HOST)
        self.assertEqual(HostBudgets(self.store, clock=self.clock).learned_all()[0].limits, 2)

    async def window_on(self, budgets, requests, *, then_wait_min):
        for _ in range(requests - 1):
            await budgets.succeeded(HOST)
            self.clock.advance(seconds=10)
        await budgets.limited(HOST)
        self.clock.advance(minutes=then_wait_min)

    async def test_a_limit_with_nothing_counted_is_no_measure(self):
        """The window was spent before the archive began: no request went through, so no budget."""
        await self.budgets.archive_started(HOST)
        await self.budgets.limited(HOST)
        self.clock.advance(minutes=10)
        self.assertIsNone(await self.budgets.succeeded(HOST))

    async def test_old_measures_are_forgotten(self):
        await self.budgets.archive_started(HOST)
        await self.window(40, then_wait_min=10)
        await self.window(40, then_wait_min=10)
        await self.budgets.succeeded(HOST)
        self.assertIsNotNone(self.budgets.learned(HOST))
        self.clock.advance(days=8)
        self.assertIsNone(self.budgets.learned(HOST), "a week later the host may allow more (more sessions)")

    async def test_the_lowest_rate_wins(self):
        await self.budgets.archive_started(HOST)
        await self.window(40, then_wait_min=10)             # 40 per 400 s + 10 min
        await self.window(20, then_wait_min=20)             # 20 per 200 s + 20 min
        learned = await self.budgets.succeeded(HOST)
        self.assertEqual((learned.requests, learned.window_s), (20, 200 + 20 * 60))


class AWindowMeasuredOnceTests(unittest.IsolatedAsyncioTestCase):
    """Issue 0107's follow-up: once one window is measured for a host, a limit is measured from the start of
    the window it hit (its budget's requests back), and the wait aims at that window's refill, 5 min past
    the latest refusal at most, instead of 5, 10, 20, 40 min."""

    def setUp(self):
        self.clock = Clock()
        self.budgets = HostBudgets(MemoryHostBudgetStore(), clock=self.clock)

    async def requests(self, n: int, apart_s: float):
        for _ in range(n):
            await self.budgets.succeeded(HOST)
            self.clock.advance(seconds=apart_s)

    async def first_window(self):
        """40 requests 12 s apart from the archive's start, a limit at 480 s, refused again at 14 min, then the
        recovery at 15 min: 40 per 15 min, refused at 14 min."""
        await self.budgets.archive_started(HOST)
        await self.requests(40, 12)
        await self.budgets.limited(HOST)
        self.clock.now = T0 + timedelta(minutes=14)
        await self.budgets.limited(HOST)
        self.clock.now = T0 + timedelta(minutes=15)

    async def test_an_unmeasured_host_has_no_refill_to_aim_at(self):
        await self.budgets.archive_started(HOST)
        await self.requests(40, 12)
        await self.budgets.limited(HOST)
        self.assertIsNone(self.budgets.refill_wait(HOST), "the 5, 10, 20, 40 min ladder")

    async def test_a_stretch_over_several_windows_is_measured_from_the_window_it_hit(self):
        await self.first_window()
        measured = await self.budgets.succeeded(HOST)
        self.assertEqual((measured.requests, measured.window_s), (40, 900))
        self.clock.advance(seconds=25)
        await self.requests(60, 25)                      # slower than the host allows: windows pass unseen
        await self.requests(40, 12)                      # then a window spent
        start = self.clock.now - timedelta(seconds=40 * 12)   # the 40th request back
        await self.budgets.limited(HOST)
        self.clock.advance(minutes=1)
        await self.budgets.limited(HOST)                 # the retry
        wait = self.budgets.refill_wait(HOST)
        self.assertEqual(self.clock.now + timedelta(seconds=wait), start + timedelta(minutes=15),
                         "its refill: the window's start and the window measured (refusals seen until 14 min)")
        self.clock.now = start + timedelta(minutes=15)
        second = await self.budgets.succeeded(HOST)
        self.assertEqual((second.requests, second.window_s), (40, 900), "not the stretch's 101 requests per its 40 min")
        self.assertEqual(self.budgets.learned(HOST).archive_gap_s(), 900 / 32)

    async def test_a_wide_first_bracket_is_probed_5_min_past_its_latest_refusal(self):
        # Refused at 26 min, recovered at 46 min (the ladder's 20 min wait): the window is 26 to 46 min.
        await self.budgets.archive_started(HOST)
        await self.requests(40, 12)
        await self.budgets.limited(HOST)
        self.clock.now = T0 + timedelta(minutes=26)
        await self.budgets.limited(HOST)
        self.clock.now = T0 + timedelta(minutes=46)
        await self.budgets.succeeded(HOST)
        start = self.clock.now
        await self.requests(39, 12)
        await self.budgets.limited(HOST)
        aim = self.clock.now + timedelta(seconds=self.budgets.refill_wait(HOST))
        self.assertEqual(aim, start + timedelta(minutes=31), "the latest refusal (26 min) and 5")
        self.clock.now = aim
        await self.budgets.limited(HOST)                 # refused again: 5 more
        self.assertEqual(self.clock.now + timedelta(seconds=self.budgets.refill_wait(HOST)), start + timedelta(minutes=36))
        self.clock.now = start + timedelta(minutes=36)
        await self.budgets.succeeded(HOST)
        learned = self.budgets.learned(HOST)
        self.assertEqual((learned.requests, learned.window_s), (40, 36 * 60),
                         "the window is under 36 min (31 refused): the narrower bracket, not 46 min")

    async def test_a_refusal_past_the_measured_window_falls_back_to_the_ladder(self):
        await self.first_window()
        await self.budgets.succeeded(HOST)
        start = self.clock.now
        await self.requests(39, 12)
        await self.budgets.limited(HOST)
        self.clock.now = start + timedelta(minutes=15)
        await self.budgets.limited(HOST)                 # the host allows less now
        self.assertIsNone(self.budgets.refill_wait(HOST))

    async def test_brackets_that_disagree_keep_the_slowest_measure(self):
        # A host that became stricter: refused at 25 min of a window once measured as 15 min.
        await self.first_window()
        await self.budgets.succeeded(HOST)
        start = self.clock.now
        await self.requests(39, 12)
        await self.budgets.limited(HOST)
        self.clock.now = start + timedelta(minutes=25)
        await self.budgets.limited(HOST)
        self.clock.now = start + timedelta(minutes=30)
        await self.budgets.succeeded(HOST)
        learned = self.budgets.learned(HOST)
        self.assertEqual((learned.requests, learned.window_s), (40, 30 * 60))


@requires_test_db
class HostLimitsInHealthTests(unittest.TestCase):
    """Health shows each learned budget: "<host>: about N requests per M min, learned from K limits"."""

    HOST = "budget-0107.test"

    def setUp(self):
        self.store = DbHostBudgetStore(db_url())

    def tearDown(self):
        with psycopg.connect(db_url()) as conn:
            conn.execute("DELETE FROM system_settings WHERE key = %s", (DbHostBudgetStore.PREFIX + self.HOST,))

    def test_the_health_answer_lists_the_learned_budgets(self):
        at = datetime.now(timezone.utc).isoformat()
        self.store.save(self.HOST, {"measures": [{"requests": 40, "window_s": 960, "at": at},
                                                 {"requests": 42, "window_s": 1000, "at": at}]})
        limits = OperationsService(db_url()).get_source_health()["host_limits"]
        mine = [row for row in limits if row["host"] == self.HOST]
        self.assertEqual(mine[0]["line"], f"{self.HOST}: about 40 requests per 16 min, learned from 2 limits")
        self.assertEqual((mine[0]["requests"], mine[0]["limits"], mine[0]["archive_gap_s"]), (40, 2, 30.0))


if __name__ == "__main__":
    unittest.main()
