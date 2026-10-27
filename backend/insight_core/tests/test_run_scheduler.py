"""The scheduler tick (spec §A.4, §5.8): tick() called directly with fakes as arguments."""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion import FetchRequest, RunReport, SourceSelector, Trigger
from unittest import mock

from insight_core.scripts.run_scheduler import SchedulerState, daily_work, tick

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
CONFIG = {"interval_hours": 20, "ingest_tick_minutes": 60}


class FakeOps:
    def __init__(self, last_cycle_success: datetime | None = None):
        self.last_cycle_success = last_cycle_success
        self.started: list[tuple[str, dict]] = []
        self.finished: list[tuple[str, dict]] = []
        self.events: list[tuple[str, dict]] = []
        self.states: list[dict] = []
        self.discarded: list[str] = []

    def start_job(self, job_type, **kwargs):
        self.started.append((job_type, kwargs))
        return f"job-{len(self.started)}"

    def finish_job(self, job_id, **kwargs):
        self.finished.append((job_id, kwargs))

    def append_job_event(self, job_id, **kwargs):
        self.events.append((job_id, kwargs))

    def discard_job(self, job_id):
        self.discarded.append(job_id)

    def latest_successful_job_finished_at(self, job_type):
        assert job_type == "scheduler_cycle"
        return self.last_cycle_success

    def set_scheduler_state(self, state):
        self.states.append(state)

    def job_types(self) -> list[str]:
        return [job_type for job_type, _ in self.started]


class FakeIngest:
    def __init__(self, raises: Exception | None = None, status: str = "success"):
        self.raises = raises
        self.status = status
        self.requests: list[FetchRequest] = []

    async def __call__(self, request, *, progress=None):
        self.requests.append(request)
        if progress is not None:
            progress.event("decided", {})
        if self.raises:
            raise self.raises
        return RunReport(run_id="r1", trigger=request.trigger, selector=request.selector, force=request.force,
                         status=self.status, started_at=NOW, finished_at=NOW, sources_considered=3,
                         sources_fetched=1, decisions={"fetch_due": 1, "skip_not_due": 2}, posts_inserted=4,
                         sources_with_new=1)


class FakeDailyWork:
    def __init__(self, result=None):
        self.calls = 0
        self.result = result

    async def __call__(self, config):
        self.calls += 1
        return self.result


class TickTests(unittest.IsolatedAsyncioTestCase):
    async def _tick(self, state=None, ops=None, ingest=None, daily=None, now=NOW):
        self.ops = ops or FakeOps()
        self.ingest = ingest or FakeIngest()
        self.daily = daily or FakeDailyWork()
        return await tick(now, state or SchedulerState(), CONFIG, ingest=self.ingest,
                          daily_work=self.daily, ops=self.ops)

    async def test_every_tick_runs_a_scheduled_ingestion_over_all_sources(self):
        await self._tick(SchedulerState(last_daily_work_at=NOW - timedelta(hours=1)))
        self.assertEqual(self.ingest.requests, [FetchRequest(SourceSelector.all(), Trigger.SCHEDULER)])
        self.assertEqual(self.ops.job_types(), ["ingestion_run"])
        job_id, finished = self.ops.finished[0]
        self.assertEqual(finished["status"], "success")
        self.assertEqual(finished["message"], "4 new posts from 1 source")
        self.assertEqual(finished["payload"]["posts_inserted"], 4)
        self.assertEqual(self.ops.discarded, [])

    async def test_a_tick_with_nothing_due_leaves_no_job_but_still_records_the_tick(self):
        state = await self._tick(SchedulerState(last_daily_work_at=NOW - timedelta(hours=1)),
                                 ingest=FakeIngest(status="nothing_due"))
        self.assertEqual(self.ops.discarded, ["job-1"])
        self.assertEqual(self.ops.finished, [], "a no-network check is not a job worth listing")
        self.assertEqual(self.ops.states[-1]["last_tick_at"], NOW.isoformat(), "the Scheduler region still sees the tick")
        self.assertEqual(state.last_tick_at, NOW)

    async def test_daily_work_waits_for_the_interval(self):
        await self._tick(SchedulerState(last_daily_work_at=NOW - timedelta(hours=19)))
        self.assertEqual(self.daily.calls, 0)
        state = await self._tick(SchedulerState(last_daily_work_at=NOW - timedelta(hours=20)))
        self.assertEqual(self.daily.calls, 1)
        self.assertEqual(state.last_daily_work_at, NOW)
        self.assertEqual(self.ops.job_types(), ["ingestion_run", "scheduler_cycle"])

    async def test_first_tick_is_seeded_from_the_last_daily_cycle(self):
        state = await self._tick(ops=FakeOps(last_cycle_success=NOW - timedelta(hours=2)))
        self.assertEqual(self.daily.calls, 0, "a fresh deploy must not run the daily work again")
        self.assertEqual(state.last_daily_work_at, NOW - timedelta(hours=2))
        self.assertEqual(state.next_daily_work_at, NOW + timedelta(hours=18))

    async def test_first_tick_with_no_previous_cycle_runs_daily_work(self):
        await self._tick(ops=FakeOps(last_cycle_success=None))
        self.assertEqual(self.daily.calls, 1)

    async def test_an_ingestion_exception_still_finishes_the_job_as_failed(self):
        state = await self._tick(SchedulerState(last_daily_work_at=NOW), ingest=FakeIngest(RuntimeError("db down")))
        job_id, finished = self.ops.finished[0]
        self.assertEqual(finished["status"], "failed")
        self.assertIn("db down", finished["message"])
        self.assertEqual(state.next_tick_at, NOW + timedelta(minutes=60))

    async def test_state_is_returned_and_persisted(self):
        state = await self._tick(SchedulerState(last_daily_work_at=NOW - timedelta(hours=1)))
        self.assertEqual(state.last_tick_at, NOW)
        self.assertEqual(state.next_tick_at, NOW + timedelta(minutes=60))
        self.assertEqual(self.ops.states[-1], state.as_dict())
        self.assertEqual(self.ops.states[-1]["next_tick_at"], (NOW + timedelta(minutes=60)).isoformat())

    async def test_tick_minutes_have_a_floor(self):
        self.ops, self.ingest, self.daily = FakeOps(), FakeIngest(), FakeDailyWork()
        state = await tick(NOW, SchedulerState(last_daily_work_at=NOW), {"interval_hours": 20, "ingest_tick_minutes": 1},
                           ingest=self.ingest, daily_work=self.daily, ops=self.ops)
        self.assertEqual(state.next_tick_at, NOW + timedelta(minutes=15))

    def test_state_round_trips_through_its_dict(self):
        state = SchedulerState(NOW, NOW + timedelta(hours=1), NOW - timedelta(hours=3), NOW + timedelta(hours=17))
        self.assertEqual(SchedulerState.from_dict(state.as_dict()), state)
        self.assertEqual(SchedulerState.from_dict({"last_tick_at": "garbage"}), SchedulerState())


class PruneOps(FakeOps):
    def __init__(self):
        super().__init__()
        self.pruned = 0

    def prune_job_runs(self, retain_days):
        self.pruned += 1
        self.retain_days = retain_days
        return 0


class DailyWorkTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_upkeep_runs_and_starts_no_jobs(self):
        ops = PruneOps()
        with mock.patch("insight_core.ingestion.ports.DbFetchStateStore.refresh_cadence", return_value=3) as cadence, \
             mock.patch("insight_core.services.source_config_sync_service.SourceConfigSyncService.sync_json_to_db",
                        return_value={"success": True}) as sync:
            # An old stored config may still carry the retired briefing switches: ignored.
            await daily_work("postgresql://unused@localhost/none", ops,
                             {"generate_daily_briefing": True, "generate_topic_briefing": True})
        self.assertEqual(ops.pruned, 1)
        self.assertEqual(cadence.call_count, 1)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(ops.job_types(), [])

    async def test_a_malformed_retention_falls_back_to_30_days(self):
        ops = PruneOps()
        with mock.patch.dict("os.environ", {"INSIGHT_JOB_RUNS_RETAIN_DAYS": "a month"}), \
             mock.patch("insight_core.ingestion.ports.DbFetchStateStore.refresh_cadence", return_value=0), \
             mock.patch("insight_core.services.source_config_sync_service.SourceConfigSyncService.sync_json_to_db",
                        return_value={"success": True}):
            await daily_work("postgresql://unused@localhost/none", ops, {})
        self.assertEqual(ops.retain_days, 30)


if __name__ == "__main__":
    unittest.main()
