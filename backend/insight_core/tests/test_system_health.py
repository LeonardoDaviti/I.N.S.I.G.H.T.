"""/api/status's health (issue 0188): computed from real checks, with its reasons; the loops' heartbeats.

No database: the reads are stubbed; what is tested is the decision."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from insight_core.services import operations_service as ops_module
from insight_core.services.operations_service import OperationsService
from insight_core.utils import heartbeat

NOW = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)


class _Env(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = mock.patch.dict(os.environ, {"INSIGHT_LOG_DIR": self.dir.name, "INSIGHT_MARKX": "off"})
        patcher.start()
        self.addCleanup(patcher.stop)


class Heartbeats(_Env):
    def test_a_fresh_beat_is_healthy_a_stale_one_is_not(self):
        t = NOW.timestamp()
        heartbeat.beat("scheduler", now=t - 30)
        self.assertEqual(heartbeat.stale(t), [])
        self.assertEqual(round(heartbeat.ages(t)["scheduler"]), 30)
        heartbeat.beat("scheduler", now=t - 600)
        self.assertIn("scheduler loop's last heartbeat was 600 s ago", heartbeat.stale(t)[0])

    def test_no_scheduler_beat_fails_the_healthcheck_a_cleared_markx_one_does_not(self):
        t = NOW.timestamp()
        self.assertEqual(heartbeat.stale(t), ["no scheduler heartbeat"])
        heartbeat.beat("scheduler", now=t)
        heartbeat.beat("markx", now=t - 5000)
        self.assertEqual(len(heartbeat.stale(t)), 1)
        heartbeat.clear("markx")
        self.assertEqual(heartbeat.stale(t), [])

    def test_the_healthcheck_command(self):
        script = Path(heartbeat.__file__)
        run = lambda: subprocess.run([sys.executable, "-I", str(script)], env={**os.environ}, capture_output=True,  # noqa: E731
                                     text=True, timeout=30)
        self.assertEqual(run().returncode, 1)
        heartbeat.beat("scheduler")
        self.assertEqual(run().returncode, 0)


class Health(_Env):
    def service(self, *, last_ok, next_tick=None, interval=20, tick=60):
        svc = OperationsService.__new__(OperationsService)
        svc.get_scheduler_config = lambda: {"interval_hours": interval, "ingest_tick_minutes": tick}
        svc.latest_successful_job_finished_at = lambda job_type: last_ok
        svc.get_scheduler_state = lambda: {"next_tick_at": next_tick.isoformat() if next_tick else None}
        return svc

    def test_healthy_when_ingestion_ran_within_its_interval(self):
        heartbeat.beat("scheduler", now=NOW.timestamp())
        out = self.service(last_ok=NOW - timedelta(hours=3), next_tick=NOW + timedelta(minutes=20)).system_health(NOW)
        self.assertEqual((out["healthy"], out["reasons"]), (True, []))
        self.assertEqual(out["checks"]["ingestion"]["limit_hours"], 22.0)

    def test_an_old_ingestion_an_overdue_tick_and_a_stale_loop_are_reasons(self):
        heartbeat.beat("scheduler", now=NOW.timestamp() - 900)
        out = self.service(last_ok=NOW - timedelta(hours=23), next_tick=NOW - timedelta(hours=3)).system_health(NOW)
        self.assertFalse(out["healthy"])
        text = " | ".join(out["reasons"])
        self.assertIn("the last successful ingestion run finished 23.0 hours ago", text)
        self.assertIn("the scheduler's next tick is 3.0 hours overdue", text)
        self.assertIn("scheduler loop's last heartbeat", text)

    def test_never_ingested_and_an_unreadable_state_are_reasons(self):
        self.assertIn("no ingestion run has succeeded yet", self.service(last_ok=None).system_health(NOW)["reasons"])
        svc = self.service(last_ok=NOW)
        svc.get_scheduler_config = mock.Mock(side_effect=RuntimeError("down"))
        self.assertEqual(svc.system_health(NOW)["reasons"], ["could not read the ingestion state (RuntimeError)"])

    def test_failing_sources_are_a_warning_never_unhealthy_alone(self):
        out = self.service(last_ok=NOW).system_health(NOW, failing_sources=4)
        self.assertTrue(out["healthy"])
        self.assertEqual(out["warnings"], ["4 sources failing"])


class MarkXHealth(_Env):
    def run_health(self, view, last_run, contacts):
        os.environ["INSIGHT_MARKX"] = "on"
        svc = OperationsService.__new__(OperationsService)
        svc.db_url = "postgresql://unused"
        svc.get_scheduler_config = lambda: {"interval_hours": 20, "ingest_tick_minutes": 60}
        svc.latest_successful_job_finished_at = lambda job_type: NOW
        svc.get_scheduler_state = lambda: {}

        class Cur:
            def execute(self, *a):
                pass

            def fetchone(self):
                return (last_run,)

        @contextmanager
        def connection(url):
            conn = mock.MagicMock()
            conn.cursor.return_value.__enter__.return_value = Cur()
            yield conn
        from insight_core.markx import api as markx_api, jobs
        with mock.patch.object(ops_module.db, "connection", connection), \
                mock.patch.object(jobs, "view", lambda cur: view), \
                mock.patch.object(markx_api, "contacts", lambda cur: contacts):
            return svc.system_health(NOW)

    def job(self, **over):
        return {"failures": 0, "failing": False, "retry_at": None, "finished_at": None, "last": {"ok": True}, **over}

    def test_a_failing_job_an_old_decision_run_and_a_silent_worker(self):
        view = {"decide": self.job(failures=4, failing=True, last={"ok": False, "error": "over 120 s"}),
                "candidates": self.job()}
        out = self.run_health(view, NOW - timedelta(hours=3), {"desk": NOW - timedelta(days=5), "laptop": NOW})
        self.assertFalse(out["healthy"])
        self.assertEqual(out["reasons"], ["Mark X's decide job failed 4 times in a row (over 120 s)",
                                          "the last Mark X decision run finished 3.0 hours ago"])
        self.assertEqual(out["warnings"], ["Mark X workers silent for over 3 days: desk"])
        self.assertEqual(out["checks"]["markx"]["jobs"]["decide"]["failures"], 4)

    def test_mark_x_healthy(self):
        out = self.run_health({"decide": self.job()}, NOW - timedelta(minutes=40), {"laptop": NOW})
        self.assertEqual((out["healthy"], out["warnings"]), (True, []))


if __name__ == "__main__":
    unittest.main()
