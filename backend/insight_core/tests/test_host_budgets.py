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
        # The slower of the two measures: 40 per (400 s + 12 min), not per the 12 min waited.
        self.assertEqual(learned.window_s, 400 + 12 * 60)
        self.assertEqual(learned.line(), f"{HOST}: about 40 requests per 19 min, learned from 2 limits")

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


if __name__ == "__main__":
    unittest.main()
