"""Mark X's jobs (markx/jobs.py, 0112 Decided 10): the API only marks that work arrived; insight-ingestion's runner
runs the candidate finder and the decision run, one at a time, never in the API process.

These suites commit, so they run only on a _test database (see test_markx_api)."""
from __future__ import annotations

import os
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from unittest import mock

import psycopg

from insight_core.markx import api, decide, jobs
from insight_core.tests._db import db_url
from insight_core.tests.test_markx_api import _Api, call, reading

T0 = datetime(2026, 11, 5, 22, 0, tzinfo=timezone.utc)


def _states(**over):
    out = {j: {"job": j, "wanted_at": None, "started_at": None, "stage": None, "stage_at": None, "finished_at": None,
               "last": None} for j in jobs.JOBS}
    for job, fields in over.items():
        out[job].update(fields)
    return out


class Due(unittest.TestCase):
    def test_a_decision_run_waits_for_work_to_settle(self):
        recent = {"started_at": T0 - timedelta(minutes=10)}
        self.assertIsNone(jobs.due(_states(decide={**recent, "wanted_at": T0 - timedelta(seconds=20)}), T0))
        self.assertEqual(jobs.due(_states(decide={**recent, "wanted_at": T0 - timedelta(seconds=61)}), T0), "decide")

    def test_hourly_and_at_first(self):
        self.assertEqual(jobs.due(_states(), T0), "decide")                                     # never ran
        self.assertIsNone(jobs.due(_states(decide={"started_at": T0 - timedelta(minutes=59)}), T0))
        self.assertEqual(jobs.due(_states(decide={"started_at": T0 - timedelta(minutes=61)}), T0), "decide")

    def test_new_vectors_run_the_candidate_finder(self):
        recent = {"started_at": T0 - timedelta(minutes=10)}
        self.assertEqual(jobs.due(_states(decide=recent, candidates={"wanted_at": T0}), T0), "candidates")


class TheApiOnlyMarks(_Api):
    """No decision run, no candidate run and no Mark X thread in the API process: a request leaves a mark."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(decide, "run", side_effect=AssertionError("a decision run in the API"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def markx_threads(self):
        return [t.name for t in threading.enumerate() if "markx" in t.name.lower() or isinstance(t, threading.Timer)]

    def test_a_valid_answer_marks_a_decision_run_wanted(self):
        t = self.task("read")
        self.lease("read")
        self.assertIsNone(jobs.state(self.cur)["decide"]["wanted_at"])
        status, body = self.answer((t, reading()))
        self.assertEqual((status, body["valid"]), (200, 1), body)
        self.assertIsNotNone(jobs.state(self.cur)["decide"]["wanted_at"])
        self.cur.execute("SELECT count(*) FROM mx_runs")
        self.assertEqual(self.cur.fetchone()[0], 0)
        self.assertEqual(self.markx_threads(), [])

    def test_a_second_mark_keeps_the_first_time(self):
        with self.conn.transaction():
            jobs.want(self.cur, "decide")
        first = jobs.state(self.cur)["decide"]["wanted_at"]
        with self.conn.transaction():
            jobs.want(self.cur, "decide")
        self.assertEqual(jobs.state(self.cur)["decide"]["wanted_at"], first)

    def test_the_decide_route_asks_and_never_runs(self):
        status, body = call("POST", "/api/markx/decide")
        self.assertEqual(status, 200, body)
        self.assertTrue(body["wanted"])
        self.assertIsNotNone(body["jobs"]["decide"]["wanted_at"])
        self.cur.execute("SELECT count(*) FROM mx_runs")
        self.assertEqual(self.cur.fetchone()[0], 0)
        self.assertEqual(self.markx_threads(), [])

    def test_the_starts_story_job_asks_for_the_first_run(self):
        api.after_start_stories()
        self.assertIsNotNone(jobs.state(self.cur)["decide"]["wanted_at"])
        self.cur.execute("UPDATE mx_jobs SET wanted_at = NULL")
        os.environ["INSIGHT_MARKX"] = "off"
        api.after_start_stories()
        self.assertIsNone(jobs.state(self.cur)["decide"]["wanted_at"])

    def test_the_api_start_asks_mark_x_after_the_story_job(self):
        import main
        order = []
        with mock.patch.object(main, "in_own_process", lambda job: order.append(job.__name__)), \
                mock.patch.object(api, "after_start_stories", lambda: order.append("markx")):
            main.start_stories()
        self.assertEqual(order, ["recompute_stories", "markx"])

    def test_the_api_has_no_job_to_start(self):
        import main
        self.assertFalse(hasattr(api, "start_jobs"))
        self.assertFalse(hasattr(jobs, "scheduler") or hasattr(jobs, "pending"))
        self.assertNotIn("start_jobs", open(main.__file__, encoding="utf-8").read())


class TheRunner(_Api):
    """insight-ingestion's side, inline (spawn=False): the job due runs, its state is recorded, a failure retries."""

    def runner(self, **kw):
        return jobs.Runner(db_url(), spawn=False, **kw)

    def test_off_nothing_runs(self):
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertIsNone(self.runner().tick())
        self.assertFalse(self.runner().start())
        self.cur.execute("SELECT count(*) FROM mx_runs")
        self.assertEqual(self.cur.fetchone()[0], 0)

    def test_a_first_tick_finds_candidates_then_decides(self):
        pid = self.post()
        with self.conn.transaction():
            jobs.note_posts(self.cur, [pid])
        found = []
        with mock.patch("insight_core.markx.candidates.run", lambda cur, ids, since=None: found.append(set(ids)) or {}):
            self.assertEqual(self.runner().tick(), "decide")
        self.assertEqual(found, [{pid}])
        self.assertEqual(jobs.waiting_posts(self.cur), [])          # found: it waits no more
        s = jobs.state(self.cur)
        self.assertIsNone(s["decide"]["wanted_at"])
        self.assertIsNone(s["decide"]["stage"])
        self.assertTrue(s["decide"]["last"]["ok"], s["decide"]["last"])
        self.assertTrue(s["candidates"]["last"]["ok"])
        self.cur.execute("SELECT count(*) FROM mx_runs WHERE finished_at IS NOT NULL")
        self.assertEqual(self.cur.fetchone()[0], 1)
        self.assertIsNone(self.runner().tick())                      # nothing due: it ran a moment ago

    def test_vectors_alone_run_the_candidate_finder(self):
        self.runner().tick()                                        # the first decision run
        pid = self.post()
        with self.conn.transaction():
            jobs.note_posts(self.cur, [pid])
        with mock.patch("insight_core.markx.candidates.run", lambda cur, ids, since=None: {"embedding": len(ids)}):
            self.assertEqual(self.runner().tick(), "candidates")
        self.assertEqual(jobs.state(self.cur)["candidates"]["last"]["counts"], {"embedding": 1})
        self.assertEqual(jobs.waiting_posts(self.cur), [])

    def test_a_failed_candidates_run_keeps_its_posts_waiting(self):
        self.runner().tick()
        pid = self.post()
        with self.conn.transaction():
            jobs.note_posts(self.cur, [pid])

        def boom(cur, ids, since=None):
            raise RuntimeError("database gone")
        with mock.patch("insight_core.markx.candidates.run", boom), self.assertLogs(jobs.log, "ERROR"):
            self.assertEqual(self.runner().tick(), "candidates")
        self.assertEqual(jobs.waiting_posts(self.cur), [pid])
        s = jobs.state(self.cur)["candidates"]
        self.assertIsNotNone(s["wanted_at"])
        self.assertFalse(s["last"]["ok"])

    def test_the_mentions_window_follows_the_last_run(self):
        sinces = []
        with mock.patch("insight_core.markx.candidates.run", lambda cur, ids, since=None: sinces.append(since) or {}):
            jobs.Jobs(db_url()).candidates()
            jobs.Jobs(db_url()).candidates()
        first, second = sinces
        self.assertGreater(second, first + timedelta(hours=23))          # the first looks back a day, then the last run

    def test_a_failed_decision_run_is_retried(self):
        with mock.patch.object(decide, "run", side_effect=RuntimeError("boom")), self.assertLogs(jobs.log, "ERROR"):
            self.assertEqual(self.runner().tick(), "decide")
        s = jobs.state(self.cur)["decide"]
        self.assertFalse(s["last"]["ok"])
        self.assertIsNotNone(s["wanted_at"])
        self.assertIsNone(s["stage"])

    def test_one_run_at_a_time_across_processes(self):
        """Another process holds the decision lock: this run is skipped, and wanted again."""
        other = psycopg.connect(db_url())
        self.addCleanup(other.close)
        other.execute("SELECT pg_advisory_lock(%s)", (decide.LOCK_KEY,))
        self.addCleanup(other.execute, "SELECT pg_advisory_unlock(%s)", (decide.LOCK_KEY,))
        self.assertEqual(self.runner().tick(), "decide")
        s = jobs.state(self.cur)["decide"]
        self.assertEqual(s["last"]["skipped"], "another decision run holds the lock")
        self.assertIsNotNone(s["wanted_at"])

    def test_a_run_a_restart_ended_is_wanted_again(self):
        self.cur.execute("INSERT INTO mx_jobs (job, stage, stage_at, started_at) VALUES ('decide', 'decide', now(), now())")
        self.runner().recover()
        s = jobs.state(self.cur)["decide"]
        self.assertIsNone(s["stage"])
        self.assertIsNotNone(s["wanted_at"])

    def test_a_spawned_run_that_never_ends_is_killed(self):
        r = jobs.Runner(db_url(), spawn=True, hard_limit=0.5)
        with mock.patch.object(jobs, "_job_main", _sleep_forever), self.assertLogs(jobs.log, "ERROR"):
            r._in_own_process("decide")
        s = jobs.state(self.cur)["decide"]
        self.assertIn("killed", s["last"]["error"])
        self.assertIsNotNone(s["wanted_at"])

    def test_the_ingestion_scheduler_starts_the_runner(self):
        from insight_core.scripts import run_scheduler
        source = open(run_scheduler.__file__, encoding="utf-8").read()
        self.assertIn("from insight_core.markx.jobs import Runner", source)
        self.assertIn("markx_jobs.start()", source)


def _sleep_forever(db_url, job):   # module level: a spawned child imports it by name
    import time
    time.sleep(60)


if __name__ == "__main__":
    unittest.main()
