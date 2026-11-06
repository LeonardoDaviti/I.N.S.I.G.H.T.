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


class TheOrderOfRuns(unittest.TestCase):
    """0121 Decided 3 (the v10.0.1 review's W6): a decision run ran during Mark IX's first-start rebuild, at 0 of
    49,384 posts, and queued 159 checks against stories about to change; one started 29 s before the candidate finder
    it depended on had finished."""

    def test_no_decision_run_while_mark_ix_is_busy_it_waits_then_runs_once(self):
        wanted = {"started_at": T0 - timedelta(minutes=10), "wanted_at": T0 - timedelta(minutes=2)}
        self.assertIsNone(jobs.due(_states(decide=wanted), T0, busy="Mark IX's story job is running"))
        self.assertIsNone(jobs.due(_states(), T0, busy="a rule change's rebuild is in progress"))   # nor the first
        self.assertEqual(jobs.due(_states(decide=wanted, candidates={"wanted_at": T0}), T0, busy="rebuild"),
                         "candidates")                                                           # the finder may run
        self.assertEqual(jobs.due(_states(decide=wanted), T0), "decide")

    def test_no_decision_run_while_the_candidate_finder_runs(self):
        wanted = {"started_at": T0 - timedelta(minutes=10), "wanted_at": T0 - timedelta(minutes=2)}
        running = {"stage": "candidates", "started_at": T0 - timedelta(seconds=20)}
        self.assertIsNone(jobs.due(_states(decide=wanted, candidates=running), T0))


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

    def stories_setting(self, value):
        self.cur.execute("SELECT value FROM system_settings WHERE key = 'stories'")
        row = self.cur.fetchone()
        self.addCleanup(self._put_stories, row[0] if row else None)
        self._put_stories(value)

    def _put_stories(self, value):
        import json
        if value is None:
            self.cur.execute("DELETE FROM system_settings WHERE key = 'stories'")
        else:
            self.cur.execute("INSERT INTO system_settings (key, value, updated_at) VALUES ('stories', %s::jsonb, now()) "
                             "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (json.dumps(value),))

    def test_no_decision_run_while_mark_ix_s_story_job_holds_its_lock(self):
        from insight_core.services.stories_service import LOCK_KEY
        other = psycopg.connect(db_url())
        self.addCleanup(other.close)
        other.execute("BEGIN")
        other.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))   # as the story job takes it
        self.assertEqual(jobs.mark_ix_busy(self.cur), "Mark IX's story job is running")
        with self.assertLogs(jobs.log, "INFO") as logs:
            self.assertIsNone(self.runner().tick())
        self.assertIn("waits for Mark IX", "\n".join(logs.output))
        self.cur.execute("SELECT count(*) FROM mx_runs")
        self.assertEqual(self.cur.fetchone()[0], 0)
        other.execute("ROLLBACK")
        self.assertIsNone(jobs.mark_ix_busy(self.cur))
        self.assertEqual(self.runner().tick(), "decide")                 # then it runs, once
        self.assertIsNone(self.runner().tick())

    def test_no_decision_run_during_a_rule_change_rebuild(self):
        from insight_core.services.stories_service import rules_stamp
        self.stories_setting({"rules": "older rules", "rebuild": {"rules": rules_stamp(), "done": 0, "total": 49384}})
        self.assertEqual(jobs.mark_ix_busy(self.cur), "a rule change's rebuild is in progress")
        self.assertIsNone(self.runner().tick())
        self.stories_setting({"rules": "older rules"})                  # stored by other rules: one is due
        self.assertEqual(jobs.mark_ix_busy(self.cur), "a rule change's rebuild is due")
        self.stories_setting({"rules": rules_stamp()})
        self.assertIsNone(jobs.mark_ix_busy(self.cur))
        self.assertEqual(self.runner().tick(), "decide")

    def test_a_decision_run_waits_for_its_candidate_finder(self):
        """New vectors: the run finds their candidates first; when that fails, no decision runs on candidates that
        aren't there, and both are wanted again."""
        self.runner().tick()
        self.cur.execute("UPDATE mx_jobs SET started_at = now() - interval '10 minutes' WHERE job = 'decide'")
        pid = self.post()
        with self.conn.transaction():
            jobs.note_posts(self.cur, [pid])
            jobs.want(self.cur, "decide")
        self.cur.execute("UPDATE mx_jobs SET wanted_at = now() - interval '2 minutes' WHERE job = 'decide'")
        self.cur.execute("SELECT count(*) FROM mx_runs")
        runs = self.cur.fetchone()[0]

        def boom(cur, ids, since=None):
            raise RuntimeError("database gone")
        with mock.patch("insight_core.markx.candidates.run", boom), self.assertLogs(jobs.log, "ERROR"):
            self.assertEqual(self.runner().tick(), "decide")
        self.cur.execute("SELECT count(*) FROM mx_runs")
        self.assertEqual(self.cur.fetchone()[0], runs)                  # no decision run without its candidates
        s = jobs.state(self.cur)
        self.assertFalse(s["decide"]["last"]["ok"])
        self.assertIn("candidate finder", s["decide"]["last"]["error"])
        self.assertIsNotNone(s["decide"]["wanted_at"])
        self.assertEqual(jobs.waiting_posts(self.cur), [pid])

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


class TheLimitAndTheStages(_Api):
    """0112 Decided 12: at most one run per 5 minutes, a 120 s limit between stages, stage logs, the running state."""

    def test_uploads_streaming_in_start_at_most_one_run_per_five_minutes(self):
        recent = {"started_at": T0 - timedelta(minutes=4), "wanted_at": T0 - timedelta(minutes=3)}
        self.assertIsNone(jobs.due(_states(decide=recent), T0))                       # wanted, settled, but too soon
        later = {"started_at": T0 - timedelta(minutes=5, seconds=1), "wanted_at": T0 - timedelta(minutes=3)}
        self.assertEqual(jobs.due(_states(decide=later), T0), "decide")
        # a stream that keeps marking can't push the run back: the first mark's time stays
        streaming = {"started_at": T0 - timedelta(minutes=6), "wanted_at": T0 - timedelta(minutes=2)}
        self.assertEqual(jobs.due(_states(decide=streaming), T0), "decide")
        # the candidates still run between two decision runs
        self.assertEqual(jobs.due(_states(decide=recent, candidates={"wanted_at": T0}), T0), "candidates")

    def test_each_stage_is_logged_with_its_duration(self):
        with self.assertLogs(jobs.log, "INFO") as logs:
            out = jobs.Jobs(db_url()).decide()
        self.assertIn("run", out)
        text = "\n".join(logs.output)
        self.assertIn("Mark X decision run started", text)
        for name in ("candidates", "load", "questions and decisions", "write", "connections", "headlines", "news"):
            self.assertIn(f"Mark X decision run: {name} took", text, name)
        self.assertIn("Mark X decision run finished in", text)
        last = jobs.state(self.cur)["decide"]["last"]
        self.assertEqual([s for s, _ in last["stages"]], ["candidates", "load", "questions and decisions", "write", "connections",
                                                "headlines", "news"])

    def test_a_run_over_the_limit_stops_between_stages_and_writes_nothing(self):
        self.cur.execute("SELECT count(*) FROM mx_runs")
        before = self.cur.fetchone()[0]
        clock = iter(range(0, 10_000, 50))                     # each look at the clock: 50 s later
        with mock.patch.object(jobs.time, "monotonic", lambda: next(clock)), self.assertLogs(jobs.log, "WARNING") as logs:
            self.assertIsNone(jobs.Jobs(db_url(), limit=120).decide())
        self.assertIn("stopped before", "\n".join(logs.output))
        self.cur.execute("SELECT count(*) FROM mx_runs")
        self.assertEqual(self.cur.fetchone()[0], before)       # its one transaction rolled back: no mx_runs row
        s = jobs.state(self.cur)["decide"]
        self.assertFalse(s["last"]["ok"])
        self.assertTrue(s["last"]["error"].startswith("over 120 s"))
        self.assertIsNotNone(s["wanted_at"])                   # retried at the next look (after the 5-minute gap)
        self.assertIsNone(s["stage"])

    def test_the_status_shows_a_running_run_with_its_start_and_stage(self):
        seen = {}

        def think(*a, **kw):
            seen["status"] = call("GET", "/api/markx/status", token=self.token)[1]["jobs"]["decide"]
            seen["overview"] = call("GET", "/api/markx/overview")[1]["worker"]["jobs"]["decide"]
            return real_think(*a, **kw)
        real_think = decide.think
        with mock.patch.object(decide, "think", think):
            jobs.Jobs(db_url()).decide()
        for where in ("status", "overview"):
            self.assertTrue(seen[where]["running"], where)
            self.assertEqual(seen[where]["stage"], "questions and decisions")
            self.assertIsNotNone(seen[where]["started_at"])
        done = call("GET", "/api/markx/status", token=self.token)[1]["jobs"]["decide"]
        self.assertFalse(done["running"])
        self.assertTrue(done["last"]["ok"])


def _sleep_forever(db_url, job):   # module level: a spawned child imports it by name
    import time
    time.sleep(60)


if __name__ == "__main__":
    unittest.main()
