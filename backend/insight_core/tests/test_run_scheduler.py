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

from insight_core.scripts.run_scheduler import SchedulerState, daily_work, tick, tracked_job
from insight_core.settings import Settings

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
CONFIG = {"interval_hours": 20, "ingest_tick_minutes": 60}


class FakeOps:
    def __init__(self, last_cycle_success: datetime | None = None):
        self.last_cycle_success = last_cycle_success
        self.started: list[tuple[str, dict]] = []
        self.finished: list[tuple[str, dict]] = []
        self.events: list[tuple[str, dict]] = []
        self.states: list[dict] = []

    def start_job(self, job_type, **kwargs):
        self.started.append((job_type, kwargs))
        return f"job-{len(self.started)}"

    def finish_job(self, job_id, **kwargs):
        self.finished.append((job_id, kwargs))

    def append_job_event(self, job_id, **kwargs):
        self.events.append((job_id, kwargs))

    def latest_successful_job_finished_at(self, job_type):
        assert job_type == "scheduler_cycle"
        return self.last_cycle_success

    def set_scheduler_state(self, state):
        self.states.append(state)

    def job_types(self) -> list[str]:
        return [job_type for job_type, _ in self.started]


class FakeIngest:
    def __init__(self, raises: Exception | None = None):
        self.raises = raises
        self.requests: list[FetchRequest] = []

    async def __call__(self, request, *, progress=None):
        self.requests.append(request)
        if progress is not None:
            progress.event("decided", {})
        if self.raises:
            raise self.raises
        return RunReport(run_id="r1", trigger=request.trigger, selector=request.selector, force=request.force,
                         status="success", started_at=NOW, finished_at=NOW, sources_considered=3,
                         sources_fetched=1, decisions={"fetch_due": 1, "skip_not_due": 2}, posts_inserted=4)


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
        self.assertEqual(finished["message"], "1 due, 2 deferred, 0 failed; 4 new posts")
        self.assertEqual(finished["payload"]["posts_inserted"], 4)
        self.assertTrue(self.ops.events, "progress goes to the job")

    async def test_daily_work_waits_for_the_interval(self):
        await self._tick(SchedulerState(last_daily_work_at=NOW - timedelta(hours=19)))
        self.assertEqual(self.daily.calls, 0)
        state = await self._tick(SchedulerState(last_daily_work_at=NOW - timedelta(hours=20)))
        self.assertEqual(self.daily.calls, 1)
        self.assertEqual(state.last_daily_work_at, NOW)
        self.assertEqual(self.ops.job_types(), ["ingestion_run", "scheduler_cycle"])

    async def test_first_tick_is_seeded_from_the_last_daily_cycle(self):
        state = await self._tick(ops=FakeOps(last_cycle_success=NOW - timedelta(hours=2)))
        self.assertEqual(self.daily.calls, 0, "a fresh deploy must not produce an extra briefing")
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

    async def test_skipped_daily_steps_are_recorded_on_the_scheduler_cycle_job(self):
        skipped = {"skipped": ["experts", "daily_briefing", "topic_briefing"], "reason": "analysis off"}
        await self._tick(SchedulerState(last_daily_work_at=NOW - timedelta(hours=21)), daily=FakeDailyWork(skipped))
        _, cycle = self.ops.finished[-1]
        self.assertEqual(cycle["status"], "success")
        self.assertEqual(cycle["payload"]["daily_work"], skipped)
        self.assertIn("skipped", cycle["message"])

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
        return 0


class DailyWorkAnalysisOffTests(unittest.IsolatedAsyncioTestCase):
    """INSIGHT_ANALYSIS=off (reading-finish R3): upkeep runs; experts and briefings don't."""

    async def test_upkeep_runs_and_experts_and_briefings_are_skipped_without_gemini(self):
        ops = PruneOps()
        never = AssertionError
        with mock.patch("insight_core.ingestion.ports.DbFetchStateStore.refresh_cadence", return_value=3) as cadence, \
             mock.patch("insight_core.services.source_config_sync_service.SourceConfigSyncService.sync_json_to_db",
                        return_value={"success": True}) as sync, \
             mock.patch("insight_core.services.experts_service.ExpertsService.__init__", side_effect=never("experts")), \
             mock.patch("insight_core.services.briefing_service.BriefingService.__init__", side_effect=never("briefing")), \
             mock.patch("insight_core.processors.ai.gemini_processor.GeminiProcessor.__init__",
                        side_effect=never("GeminiProcessor built")):
            result = await daily_work("postgresql://unused@localhost/none", ops,
                                      {"generate_daily_briefing": True, "generate_topic_briefing": True},
                                      settings=Settings(analysis_enabled=False))
        self.assertEqual(ops.pruned, 1)
        self.assertEqual(cadence.call_count, 1)
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(ops.job_types(), [], "no expert or briefing jobs start")
        self.assertEqual(result, {"skipped": ["experts", "daily_briefing", "topic_briefing"], "reason": "analysis off"})


class TrackedJobTests(unittest.IsolatedAsyncioTestCase):
    """E5 for the daily-work jobs: a started job_runs row is finished in every case."""

    async def test_a_result_finishes_the_job_with_its_status(self):
        ops = FakeOps()

        async def work():
            return {"success": True, "posts_processed": 4}

        result = await tracked_job(ops, "daily_briefing", {"date": "2026-10-09"}, work)
        self.assertEqual(result, {"success": True, "posts_processed": 4})
        self.assertEqual(ops.job_types(), ["daily_briefing"])
        self.assertEqual(ops.started[0][1]["trigger"], "scheduler")
        job_id, finished = ops.finished[0]
        self.assertEqual(job_id, "job-1")
        self.assertEqual(finished["status"], "success")
        self.assertEqual(finished["message"], "Processed 4 posts")

    async def test_an_unsuccessful_result_is_failed_with_its_error(self):
        ops = FakeOps()

        async def work():
            return {"success": False, "error": "no posts"}

        await tracked_job(ops, "topic_briefing", {}, work)
        self.assertEqual(ops.finished[0][1]["status"], "failed")
        self.assertEqual(ops.finished[0][1]["message"], "no posts")

    async def test_an_exception_finishes_the_job_as_failed_and_propagates(self):
        ops = FakeOps()

        async def work():
            raise RuntimeError("db down")

        with self.assertRaises(RuntimeError):
            await tracked_job(ops, "daily_briefing", {}, work)
        self.assertEqual(len(ops.finished), 1)
        self.assertEqual(ops.finished[0][1]["status"], "failed")
        self.assertEqual(ops.finished[0][1]["message"], "db down")

    async def test_an_exception_can_be_contained(self):
        ops = FakeOps()

        async def work():
            raise RuntimeError("llm down")

        self.assertIsNone(await tracked_job(ops, "expert_briefing", {}, work, reraise=False))
        self.assertEqual(ops.finished[0][1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
