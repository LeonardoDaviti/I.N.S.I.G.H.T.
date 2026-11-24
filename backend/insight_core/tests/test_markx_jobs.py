"""Mark X's jobs (markx/jobs.py): the API only marks that work arrived; insight-ingestion's runner runs the jobs, one
at a time, never in the API process. These suites commit, so they run only on a _test database."""
from __future__ import annotations

import os
import threading
import unittest
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
        recent = {"started_at": T0 - timedelta(minutes=16)}
        self.assertIsNone(jobs.due(_states(decide={**recent, "wanted_at": T0 - timedelta(seconds=20)}), T0))
        self.assertEqual(jobs.due(_states(decide={**recent, "wanted_at": T0 - timedelta(seconds=61)}), T0), "decide")

    def test_hourly_and_at_first(self):
        self.assertEqual(jobs.due(_states(), T0), "decide")                                     # never ran
        self.assertIsNone(jobs.due(_states(decide={"started_at": T0 - timedelta(minutes=59)}), T0))
        self.assertEqual(jobs.due(_states(decide={"started_at": T0 - timedelta(minutes=61)}), T0), "decide")

    def test_new_vectors_run_the_candidate_finder(self):
        recent = {"started_at": T0 - timedelta(minutes=10)}   # within RUN_GAP: the candidates run between two runs
        self.assertEqual(jobs.due(_states(decide=recent, candidates={"wanted_at": T0}), T0), "candidates")


class TheBackoff(unittest.TestCase):
    """A failing job waits GAP x 2^failures (at most 6 hours) before it is tried again; from FAILING_AFTER failures
    it shows as failing (0188)."""

    def failed(self, n, ended_ago):
        return {"started_at": T0 - timedelta(seconds=ended_ago + 30), "finished_at": T0 - timedelta(seconds=ended_ago),
                "last": {"ok": False, "error": "boom"}, "failures": n, "wanted_at": T0 - timedelta(hours=7)}

    def test_the_wait_doubles_up_to_six_hours(self):
        self.assertEqual(jobs.backoff({"failures": 0}), 0)
        self.assertEqual([jobs.backoff({"failures": n}) for n in (1, 2, 3, 4)], [600, 1200, 2400, 4800])
        self.assertEqual(jobs.backoff({"failures": 7}), jobs.MAX_BACKOFF)
        self.assertEqual(jobs.backoff({"failures": 10_000}), jobs.MAX_BACKOFF)   # no overflow

    def test_every_job_waits_out_its_backoff(self):
        self.assertIsNone(jobs.due(_states(decide=self.failed(2, 1199)), T0))
        self.assertEqual(jobs.due(_states(decide=self.failed(2, 1201)), T0), "decide")
        recent = {"started_at": T0 - timedelta(minutes=10)}
        self.assertIsNone(jobs.due(_states(decide=recent, candidates=self.failed(1, 599)), T0))
        self.assertEqual(jobs.due(_states(decide=recent, candidates=self.failed(1, 601)), T0), "candidates")
        self.assertNotEqual(jobs.due(_states(plan=self.failed(3, 60)), T0, plan_every=300), "plan")
        self.assertEqual(jobs.due(_states(plan=self.failed(3, 2401)), T0, plan_every=300), "plan")

    def test_a_killed_run_is_not_restarted_at_the_next_look(self):
        killed = {**self.failed(1, 30), "last": {"ok": False, "error": "killed after 900 s"}}
        self.assertIsNone(jobs.due(_states(decide=killed), T0))

    def test_failing_after_three_and_still_tried_at_the_longest_wait(self):
        self.assertFalse(jobs.failing({"failures": 2}))
        self.assertTrue(jobs.failing({"failures": 3}))
        self.assertIsNone(jobs.due(_states(decide=self.failed(50, 6 * 3600 - 1)), T0))
        self.assertEqual(jobs.due(_states(decide=self.failed(50, 6 * 3600 + 1)), T0), "decide")


class AWantedKeptView(unittest.TestCase):
    """A view kept only when wanted is built when missing and asked for, after a due decision run (0182, 0199)."""

    def test_due_when_missing_after_the_decision_run(self):
        recent = {"started_at": T0 - timedelta(minutes=10)}
        asked = {"wanted_at": T0 - timedelta(minutes=1)}                       # a page asked for it
        self.assertIsNone(jobs.due(_states(decide=recent), T0))
        self.assertIsNone(jobs.due(_states(decide=recent), T0, kept_missing={"main_source"}))    # nobody asked
        self.assertEqual(jobs.due(_states(decide=recent, main_source=asked), T0, kept_missing={"main_source"}), "main_source")
        self.assertEqual(jobs.due(_states(main_source=asked), T0, kept_missing={"main_source"}), "decide")     # a run first
        self.assertEqual(jobs.due(_states(decide=recent, candidates={"wanted_at": T0}, main_source=asked), T0,
                                  kept_missing={"main_source"}), "main_source")

    def test_a_failed_build_waits_for_its_backoff(self):
        recent = {"started_at": T0 - timedelta(minutes=10)}
        failed = {"started_at": T0 - timedelta(minutes=3), "finished_at": T0 - timedelta(minutes=2),
                  "last": {"ok": False, "error": "boom"}, "failures": 1, "wanted_at": T0 - timedelta(minutes=2)}
        self.assertIsNone(jobs.due(_states(decide=recent, main_source=failed), T0, kept_missing={"main_source"}))
        failed["finished_at"] = T0 - timedelta(minutes=11)                                    # GAP x 2 after its end
        self.assertEqual(jobs.due(_states(decide=recent, main_source=failed), T0, kept_missing={"main_source"}), "main_source")
        ok = {"started_at": T0 - timedelta(seconds=40), "last": {"ok": True}, "wanted_at": T0}  # a newer run's
        self.assertEqual(jobs.due(_states(decide=recent, main_source=ok), T0, kept_missing={"main_source"}), "main_source")
        running = {"started_at": T0 - timedelta(seconds=40), "stage": "building", "wanted_at": T0}
        self.assertIsNone(jobs.due(_states(decide=recent, main_source=running), T0, kept_missing={"main_source"}))


class TheRebuildHold(unittest.TestCase):
    """The rebuild's slices run from the jobs loop and hold no decision run; the story job's lock does (0209, 0215)."""

    IX = {"locked": False, "rebuild": "in progress", "done": 2000, "total": 157752}

    def test_the_hold(self):
        held, ahead = jobs.decision_hold(self.IX)
        self.assertIsNone(held)
        self.assertEqual(ahead, "a rule change's rebuild is in progress (2,000 of 157,752 posts regrouped): the "
                                "decision run goes ahead on the stories as stored")
        self.assertEqual(jobs.decision_hold(dict(self.IX, locked=True)),
                         ("Mark IX's story job is running", None))                           # a batch: seconds
        self.assertEqual(jobs.decision_hold({"locked": False, "rebuild": None}), (None, None))
        self.assertIn("is due:", jobs.decision_hold({"locked": False, "rebuild": "due"})[1])

    def test_the_rebuild_slice_after_the_decision_run(self):
        recent = {"started_at": T0 - timedelta(minutes=16), "wanted_at": T0 - timedelta(minutes=2)}
        self.assertEqual(jobs.due(_states(decide=recent), T0, rebuild=True), "decide")       # not held: first
        self.assertEqual(jobs.due(_states(decide=recent), T0, rebuild=True, busy="held"), "stories")
        ended = {"finished_at": T0 - timedelta(seconds=jobs.STORIES_GAP - 1)}
        self.assertIsNone(jobs.due(_states(decide=recent, stories=ended), T0, rebuild=True, busy="held"))
        self.assertEqual(jobs.due(_states(stories=ended), T0 + timedelta(seconds=2), rebuild=True, markx=False),
                         "stories")
        self.assertIsNone(jobs.due(_states(decide=recent), T0, busy="held"))                 # no rebuild: none

    def test_a_wanted_story_run_goes_before_the_decision_run(self):
        """Saved posts want the story job and the decision run; the story job groups them first (0218)."""
        due_run = {"started_at": T0 - timedelta(minutes=61), "wanted_at": T0 - timedelta(minutes=2)}
        wanted = {"wanted_at": T0 - timedelta(seconds=40), "finished_at": T0 - timedelta(hours=1)}
        self.assertEqual(jobs.due(_states(decide=due_run, stories=wanted), T0), "stories")
        self.assertEqual(jobs.due(_states(decide=due_run, stories=wanted), T0, rebuild=True), "stories")
        # then the decision run (the story run's start cleared its want)
        ran = {"started_at": T0 - timedelta(seconds=50), "finished_at": T0 - timedelta(seconds=5)}
        self.assertEqual(jobs.due(_states(decide=due_run, stories=ran), T0), "decide")
        # the plan still first (it never starves)
        self.assertEqual(jobs.due(_states(decide=due_run, stories=wanted), T0, plan_every=300), "plan")

    def test_a_rested_or_running_story_job_never_holds_the_decision_run(self):
        due_run = {"started_at": T0 - timedelta(minutes=61)}
        # a wanted run that yielded (or stepped aside for this run) rests STORIES_GAP: the decision run goes meanwhile
        for how in ("yielded", "skipped"):
            rested = {"wanted_at": T0 - timedelta(seconds=30), "finished_at": T0 - timedelta(seconds=30),
                      "last": {"ok": True, how: True}}
            self.assertEqual(jobs.due(_states(decide=due_run, stories=rested), T0), "decide")
        running = {"wanted_at": T0 - timedelta(seconds=30), "stage": "regrouping", "stage_at": T0}
        self.assertEqual(jobs.due(_states(decide=due_run, stories=running), T0), "decide")
        # a failed story run waits out its backoff; the decision run does not wait with it
        failed = {"wanted_at": T0 - timedelta(minutes=1), "finished_at": T0 - timedelta(seconds=10), "failures": 1,
                  "last": {"ok": False, "error": "boom"}}
        self.assertEqual(jobs.due(_states(decide=due_run, stories=failed), T0), "decide")
        # a rebuild's slice alone (not wanted) still follows the decision run
        self.assertEqual(jobs.due(_states(decide=due_run), T0, rebuild=True), "decide")

    def test_candidates_and_official_never_starve_behind_the_kept_views(self):
        """The unread counts can be due at every look."""
        ran = {"started_at": T0 - timedelta(minutes=10)}
        missing = ["unread"]
        self.assertEqual(jobs.due(_states(decide=ran), T0, kept_missing=missing, official_every=1800.0), "official")
        o = {"started_at": T0 - timedelta(seconds=1800 + jobs.STARVE_AFTER - 60)}
        self.assertEqual(jobs.due(_states(decide=ran, official=o), T0, kept_missing=missing, official_every=1800.0),
                         "unread")                                                            # due, not for long
        o = {"started_at": T0 - timedelta(seconds=1800 + jobs.STARVE_AFTER + 60)}
        self.assertEqual(jobs.due(_states(decide=ran, official=o), T0, kept_missing=missing, official_every=1800.0),
                         "official")
        c = {"wanted_at": T0 - timedelta(minutes=2)}
        self.assertEqual(jobs.due(_states(decide=ran, candidates=c), T0, kept_missing=missing), "unread")
        c = {"wanted_at": T0 - timedelta(seconds=jobs.STARVE_AFTER + 1)}
        self.assertEqual(jobs.due(_states(decide=ran, candidates=c), T0, kept_missing=missing), "candidates")


class TheOrderOfRuns(unittest.TestCase):
    """No decision run during Mark IX's first-start rebuild or before the candidate finder ends (0121)."""

    def test_no_decision_run_while_mark_ix_is_busy_it_waits_then_runs_once(self):
        wanted = {"started_at": T0 - timedelta(minutes=16), "wanted_at": T0 - timedelta(minutes=2)}
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

    def setUp(self):
        super().setUp()
        # the reader's kept views have tests of their own (test_kept_pages_wave_2)
        patcher = mock.patch.object(jobs, "KEPT_VIEWS", tuple(v for v in jobs.KEPT_VIEWS if v.markx))
        patcher.start()
        self.addCleanup(patcher.stop)
        # nor official channels (test_official_0196): its pass reads the web
        patcher = mock.patch.object(jobs.Runner, "official_every", lambda self: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        # nor the discussions pass (test_discussions_0280): it reads the web
        patcher = mock.patch.object(jobs.Runner, "discussions_every", lambda self: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def runner(self, **kw):
        return jobs.Runner(db_url(), spawn=False, **{"plan_every": None, **kw})   # the plan job apart

    def test_off_nothing_runs(self):
        """Mark X off: no Mark X job; the loop still runs for the reader's kept views (0206)."""
        os.environ["INSIGHT_MARKX"] = "off"
        self.assertIsNone(self.runner().tick())
        runner = self.runner()
        self.assertTrue(runner.start(poll=3600))
        runner.stop.set()
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

    def test_a_decision_run_goes_ahead_during_a_rule_change_rebuild(self):
        """The rebuild's slices and the decision runs take turns at the normal cadence (0215)."""
        from insight_core.services.stories_service import rules_stamp
        self.decide_row(started=20, wanted=19)
        self.stories_setting({"rules": "older rules", "rebuild": {"rules": rules_stamp(), "done": 0, "total": 49384}})
        self.assertEqual(jobs.mark_ix_busy(self.cur), "a rule change's rebuild is in progress")   # the source stats wait
        with self.assertLogs(jobs.log, "WARNING") as logs:
            self.assertEqual(self.runner().tick(), "decide")          # due: the rebuild doesn't hold it
        self.assertIn("goes ahead on the stories as stored", "\n".join(logs.output))
        with self.slices() as ran:
            self.assertEqual(self.runner().tick(), "stories")         # then the rebuild's slice
        self.assertEqual(len(ran), 1)
        self.stories_setting({"rules": "older rules"})                  # stored by other rules: one is due
        self.assertEqual(jobs.mark_ix_busy(self.cur), "a rule change's rebuild is due")
        self.stories_setting({"rules": rules_stamp()})
        self.assertIsNone(jobs.mark_ix_busy(self.cur))

    def decide_row(self, *, started, wanted=None, finished=None):
        """The decide job's row: started (wanted, finished) that many minutes ago."""
        def ago(m):
            return None if m is None else datetime.now(timezone.utc) - timedelta(minutes=m)
        self.cur.execute("INSERT INTO mx_jobs (job) VALUES ('decide') ON CONFLICT (job) DO NOTHING")
        self.cur.execute("""UPDATE mx_jobs SET started_at = %s, wanted_at = %s, finished_at = %s, stage = NULL,
                                   stage_at = NULL, failures = 0 WHERE job = 'decide'""",
                         (ago(started), ago(wanted), ago(finished)))

    def slices(self):
        """The rebuild's slice (stories_service.recompute_safely) recorded, not run."""
        from insight_core.services import stories_service
        ran = []
        patcher = mock.patch.object(stories_service.StoriesService, "recompute_safely",
                                    lambda svc, full=False: ran.append(1) or {"batches": 3, "yielded": True})

        class _Ctx:
            def __enter__(self_):
                patcher.start()
                return ran

            def __exit__(self_, *exc):
                patcher.stop()
        return _Ctx()

    def test_the_2026_11_14_deadlock_ends(self):
        """A rebuild in progress and a decision run long wanted: the story job steps aside for it, and the run works
        on the stories as stored, saying so in its record (0209, 0215)."""
        from insight_core.services.stories_service import DECISION_WAIT_S, StoriesService, rules_stamp
        self.stories_setting({"rules": "older rules",
                              "rebuild": {"rules": rules_stamp(), "phase": "keys", "done": 0, "total": 157752}})
        svc = StoriesService(db_url())
        self.decide_row(started=20, wanted=5)                          # wanted, not for ten minutes: the rebuild goes on
        self.assertFalse(svc._decision_waiting())
        self.decide_row(started=45 * 60 + 44, wanted=45 * 60 + 43, finished=45 * 60 + 47)
        self.assertTrue(svc._decision_waiting())                       # its turn
        self.assertTrue(jobs.decision_waits(self.cur, datetime.now(timezone.utc), DECISION_WAIT_S))
        with self.assertLogs(jobs.log, "WARNING") as logs:
            self.assertEqual(self.runner().tick(), "decide")
        self.assertIn("goes ahead on the stories as stored", "\n".join(logs.output))
        last = jobs.state(self.cur)["decide"]["last"]
        self.assertTrue(last["ok"], last)
        self.assertIn("goes ahead on the stories as stored", last["mark_ix"])
        self.assertFalse(svc._decision_waiting())                      # it ran: the story job goes on

    def test_the_rebuild_slices_run_here_with_mark_x_off_too(self):
        """The slices run from this loop STORIES_GAP after the last ended, with Mark X on or off (0209)."""
        from insight_core.services.stories_service import rules_stamp
        self.decide_row(started=5)
        self.stories_setting({"rules": "older rules",
                              "rebuild": {"rules": rules_stamp(), "phase": "stories", "done": 1000, "total": 49384}})
        with self.slices() as ran:
            self.assertEqual(self.runner().tick(), "stories")
            self.assertIsNone(self.runner().tick())                     # STORIES_GAP after the last
            self.cur.execute("UPDATE mx_jobs SET finished_at = now() - make_interval(secs => %s) WHERE job = 'stories'",
                             (jobs.STORIES_GAP + 1,))
            os.environ["INSIGHT_MARKX"] = "off"
            self.assertEqual(self.runner().tick(), "stories")
        self.assertEqual(len(ran), 2)
        last = jobs.state(self.cur)["stories"]["last"]
        self.assertEqual((last["ok"], last["batches"], last["yielded"]), (True, 3, True))
        self.assertEqual(last["rebuild"], {"rebuild": "in progress", "phase": "stories", "done": 1000, "total": 49384})
        self.assertTrue(jobs.readers("stories"))                       # not a Mark X run (markx.ix_unchanged)

    def test_a_wanted_story_job_runs_here_then_the_originals(self):
        """A fetch that saved posts wants the story job; this loop runs it, then the originals and scouts at most every
        ORIGINALS_GAP; a yielded run is wanted again STORIES_GAP after; an unwanted slice asks no originals (0216)."""
        from insight_core.services import stories_service
        from insight_core.services.stories_service import rules_stamp
        self.decide_row(started=5)
        self.stories_setting({"rules": rules_stamp()})
        out = {"batches": 1, "posts": 4}
        after = []
        with mock.patch.object(stories_service.StoriesService, "recompute_safely", lambda svc, full=False: dict(out)), \
                mock.patch.object(jobs.Jobs, "after_stories", lambda job: after.append(1) or {"ok": True}):
            self.assertIsNone(self.runner().tick(), "not wanted, no rebuild: nothing")
            self.assertTrue(jobs.want_stories(db_url()))
            self.assertEqual(self.runner().tick(), "stories")
            last = jobs.state(self.cur)["stories"]["last"]
            self.assertEqual((last["wanted"], last["posts"], len(after)), (True, 4, 1))
            self.assertIsNone(jobs.state(self.cur)["stories"]["wanted_at"], "taken")
            os.environ["INSIGHT_MARKX"] = "off"
            jobs.want_stories(db_url())
            out["yielded"] = True
            self.assertEqual(self.runner().tick(), "stories", "at once: its last run did not yield")
            self.assertEqual(len(after), 1, "the originals at most every ORIGINALS_GAP")
            self.assertIsNotNone(jobs.state(self.cur)["stories"]["wanted_at"], "yielded: wanted again")
            self.assertIsNone(self.runner().tick(), "past its rest: STORIES_GAP after")
            self.cur.execute("UPDATE mx_jobs SET finished_at = now() - make_interval(secs => %s), "
                             "last = last || jsonb_build_object('after_at', (now() - interval '1 hour')::text) "
                             "WHERE job = 'stories'", (jobs.STORIES_GAP + 1,))
            del out["yielded"]
            self.assertEqual(self.runner().tick(), "stories")
            self.assertEqual(len(after), 2, "the originals' gap is over")
            self.stories_setting({"rules": "older rules"})              # a rebuild due: its slices, not wanted
            self.cur.execute("UPDATE mx_jobs SET finished_at = now() - make_interval(secs => %s), "
                             "last = last || jsonb_build_object('after_at', (now() - interval '1 hour')::text) "
                             "WHERE job = 'stories'", (jobs.STORIES_GAP + 1,))
            self.assertEqual(self.runner().tick(), "stories")
            self.assertFalse(jobs.state(self.cur)["stories"]["last"]["wanted"])
            self.assertEqual(len(after), 2, "a slice nobody wanted asks no originals")

    def test_a_decision_run_waits_for_its_candidate_finder(self):
        """New vectors: the run finds their candidates first; when that fails, no decision runs on candidates that
        aren't there, and both are wanted again."""
        self.runner().tick()
        self.cur.execute("UPDATE mx_jobs SET started_at = now() - interval '16 minutes' WHERE job = 'decide'")
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
        self.cur.execute("""INSERT INTO mx_jobs (job, stage, stage_at, started_at, last)
                            VALUES ('decide', 'decide', now(), now(), '{"skip_next": "graph"}')""")
        self.runner().recover()
        s = jobs.state(self.cur)["decide"]
        self.assertIsNone(s["stage"])
        self.assertIsNotNone(s["wanted_at"])
        # its end recorded, not as a failure
        self.assertGreaterEqual(s["finished_at"], s["started_at"])
        self.assertEqual(s["last"], {"skip_next": "graph", "ok": False, "stage": "decide", "error": "ended by a restart"})
        self.assertEqual(s["failures"], 0)

    def test_every_job_has_its_row(self):
        """mx_jobs' check names every job, so every job can write its row (0209)."""
        for job in jobs.JOBS:
            with self.conn.transaction():
                self.cur.execute("INSERT INTO mx_jobs (job) VALUES (%s) ON CONFLICT (job) DO NOTHING", (job,))
        jobs.Jobs(db_url())._begin("official", "running")
        self.assertEqual(jobs.state(self.cur)["official"]["stage"], "running")

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
    """At most one run per RUN_GAP, a 120 s limit between stages, stage logs, the running state (0112)."""

    def test_uploads_streaming_in_start_at_most_one_run_per_fifteen_minutes(self):
        self.assertEqual(jobs.RUN_GAP, 900.0)
        recent = {"started_at": T0 - timedelta(minutes=14), "wanted_at": T0 - timedelta(minutes=3)}
        self.assertIsNone(jobs.due(_states(decide=recent), T0))                       # wanted, settled, but too soon
        later = {"started_at": T0 - timedelta(minutes=15, seconds=1), "wanted_at": T0 - timedelta(minutes=3)}
        self.assertEqual(jobs.due(_states(decide=later), T0), "decide")
        self.assertIsNone(jobs.due(_states(decide={"started_at": T0 - timedelta(minutes=6)}), T0),
                          "nothing wanted: the hourly run only")
        # a stream that keeps marking can't push the run back: the first mark's time stays
        streaming = {"started_at": T0 - timedelta(minutes=16), "wanted_at": T0 - timedelta(minutes=2)}
        self.assertEqual(jobs.due(_states(decide=streaming), T0), "decide")
        # the candidates still run between two decision runs
        self.assertEqual(jobs.due(_states(decide=recent, candidates={"wanted_at": T0}), T0), "candidates")

    def test_each_stage_is_logged_with_its_duration(self):
        with self.assertLogs(jobs.log, "INFO") as logs:
            out = jobs.Jobs(db_url()).decide()
        self.assertIn("run", out)
        text = "\n".join(logs.output)
        self.assertIn("Mark X decision run started", text)
        for name in ("candidates", "load", "questions and decisions", "write", "connections", "back", "headlines", "news", "entities", "graph", "surges", "perspectives_plan"):
            self.assertIn(f"Mark X decision run: {name} took", text, name)
        self.assertIn("Mark X decision run finished in", text)
        last = jobs.state(self.cur)["decide"]["last"]
        self.assertEqual([s for s, _ in last["stages"]], ["candidates", "load", "questions and decisions", "write", "connections",
                                                "back", "headlines", "news", "entities", "graph", "surges",
                                                "perspectives_plan"])   # graph after entities

    def test_a_run_over_the_limit_stops_between_stages_and_writes_nothing(self):
        self.cur.execute("SELECT count(*) FROM mx_runs")
        before = self.cur.fetchone()[0]
        clock = iter(range(0, 10_000, 50))                     # each look at the clock: 50 s later
        with mock.patch.object(jobs.time, "monotonic", lambda: next(clock)), self.assertLogs(jobs.log, "WARNING") as logs:
            self.assertIsNone(jobs.Jobs(db_url(), limit=120, catch_up=120).decide())
        self.assertIn("stopped before", "\n".join(logs.output))
        self.cur.execute("SELECT count(*) FROM mx_runs")
        self.assertEqual(self.cur.fetchone()[0], before)       # its one transaction rolled back: no mx_runs row
        s = jobs.state(self.cur)["decide"]
        self.assertFalse(s["last"]["ok"])
        self.assertTrue(s["last"]["error"].startswith("over 120 s"))
        self.assertIsNotNone(s["wanted_at"])                   # retried at the next look (after the 5-minute gap)
        self.assertIsNone(s["stage"])
        # the stage's whole name, and the retry as it happens
        self.assertEqual(s["last"]["stopped_before"], s["last"]["error"].split("stopped before ", 1)[1])
        self.assertIn(s["last"]["stopped_before"], ("load", "questions and decisions", "write", "connections", "graph", "back", "headlines", "news"))
        self.assertIn("it runs again after its backoff", "\n".join(logs.output))
        self.assertEqual(s["failures"], 1)                     # one failure in a row, the backoff counts it

    def test_the_entities_stages_own_budget_is_not_counted_in_the_limit(self):
        """A 100 s entities stage inside a 150 s run stays under the 120 s limit; the budget reaches the run (0128)."""
        clock = [0.0]
        seen = {}

        def run(cur, *, stage, entity_budget=None, **kw):
            seen["budget"] = entity_budget
            for name, secs in (("load", 10), ("questions and decisions", 10), ("write", 5), ("connections", 5),
                               ("headlines", 5), ("news", 5), ("entities", 100), ("surges", 5), ("perspectives_plan", 5)):
                stage(name)
                clock[0] += secs
            return {"run": "x", "stories": 0}
        with mock.patch.object(jobs.time, "monotonic", lambda: clock[0]), mock.patch.object(decide, "run", run):
            out = jobs.Jobs(db_url(), limit=120).decide()
        self.assertEqual(out, {"run": "x", "stories": 0})
        self.assertEqual(seen["budget"], jobs.ENTITY_BUDGET)
        last = jobs.state(self.cur)["decide"]["last"]
        self.assertTrue(last["ok"])
        self.assertIn(["entities", 100.0], last["stages"])
        # the same 100 s in any other stage stops the run
        clock[0] = 0.0

        def slow(cur, *, stage, **kw):
            for name, secs in (("load", 10), ("questions and decisions", 100), ("write", 5), ("connections", 5),
                               ("headlines", 5), ("news", 5), ("entities", 1)):
                stage(name)
                clock[0] += secs
            return {"run": "y"}
        with mock.patch.object(jobs.time, "monotonic", lambda: clock[0]), mock.patch.object(decide, "run", slow), \
                self.assertLogs(jobs.log, "WARNING"):
            self.assertIsNone(jobs.Jobs(db_url(), limit=120).decide())

    def test_a_full_run_and_the_run_after_a_stop_have_the_catch_up_limit(self):
        """A full run, and the run after one that stopped, have CATCH_UP_LIMIT; then LIMIT again, so a full run that
        overruns is not repeated for ever (0215)."""
        clock, kinds = [0.0], []

        def run(cur, *, stage, on_kind=None, **kw):
            on_kind(kinds.pop(0))
            for name, secs in (("load", 1), ("questions and decisions", 93), ("write", 1), ("connections", 10),
                               ("graph", 16), ("back", 10), ("news", 5)):
                stage(name)
                clock[0] += secs
            return {"run": "x", "stories": 0}
        with mock.patch.object(jobs.time, "monotonic", lambda: clock[0]), mock.patch.object(decide, "run", run), \
                mock.patch.object(jobs.Jobs, "candidates", lambda self: {}), self.assertLogs(jobs.log, "INFO") as logs:
            j = jobs.Jobs(db_url(), limit=120, catch_up=600)
            kinds[:] = ["full", "incremental", "incremental", "incremental"]
            self.assertEqual(j.decide(), {"run": "x", "stories": 0})                 # full: 136 s of its 600
            last = jobs.state(self.cur)["decide"]["last"]
            self.assertEqual((last["ok"], last["limit"]), (True, 600))
            self.assertIsNone(j.decide())                                             # incremental: 120 s again
            last = jobs.state(self.cur)["decide"]["last"]
            self.assertEqual((last["ok"], last["limit"], last["stopped_before"]), (False, 120, "back"))   # as the server
            self.assertEqual(j.decide(), {"run": "x", "stories": 0})                 # the run after: caught up
            self.assertEqual(jobs.state(self.cur)["decide"]["last"]["limit"], 600)
            self.assertIsNone(j.decide())                                             # then LIMIT once more
        text = "\n".join(logs.output)
        self.assertIn("a full run, 600 s at most", text)
        self.assertIn("the last one stopped over its limit; this one has 600 s", text)

    def test_the_limit_for_a_run(self):
        self.assertEqual(jobs.limit_for(None, {}), jobs.LIMIT)
        self.assertEqual(jobs.limit_for("incremental", {"ok": True}), jobs.LIMIT)
        self.assertEqual(jobs.limit_for("full", {}), jobs.CATCH_UP_LIMIT)
        self.assertEqual(jobs.limit_for(None, {"ok": False, "stopped_before": "back"}), jobs.CATCH_UP_LIMIT)
        self.assertEqual(jobs.limit_for("full", {}, limit=900, catch_up=600), 900)   # never below LIMIT

    def test_failures_count_in_a_row_and_a_good_run_clears_them(self):
        j = jobs.Jobs(db_url())
        for _ in range(3):
            j._finish("news", {"ok": False, "error": "boom"})
        view = jobs.view(self.cur)["news"]
        self.assertEqual(view["failures"], 3)
        self.assertTrue(view["failing"])
        self.assertIsNotNone(view["retry_at"])
        j._finish("decide", {"ok": False, "skipped": "another decision run holds the lock"})
        self.assertEqual(jobs.state(self.cur)["decide"]["failures"], 0)             # a skipped run is no failure
        j._finish("news", {"ok": True})
        view = jobs.view(self.cur)["news"]
        self.assertEqual((view["failures"], view["failing"], view["retry_at"]), (0, False, None))

    def test_over_the_limit_twice_in_the_same_stage_skips_it_once(self):
        """The next run defers the stage the last one ran over in, then tries it again (0188)."""
        clock, seen = [0.0], []

        def run(cur, *, stage, skip=(), **kw):
            seen.append(list(skip))
            for name, secs in (("load", 10), ("questions and decisions", 10), ("graph", 0 if "graph" in skip else 200),
                               ("back", 5)):
                stage(name)
                clock[0] += secs
            return {"run": "x", "stories": 0}
        with mock.patch.object(jobs.time, "monotonic", lambda: clock[0]), mock.patch.object(decide, "run", run), \
                mock.patch.object(jobs.Jobs, "candidates", lambda self: {}), self.assertLogs(jobs.log, "WARNING") as logs:
            j = jobs.Jobs(db_url(), limit=120, catch_up=120)   # past the catch-up limit too
            self.assertIsNone(j.decide())
            first = jobs.state(self.cur)["decide"]["last"]
            self.assertEqual((first["over_in"], first.get("skip_next")), ("graph", None))
            self.assertIsNone(j.decide())
            second = jobs.state(self.cur)["decide"]
            self.assertEqual(second["last"]["skip_next"], "graph")
            self.assertEqual(second["failures"], 2)
            self.assertEqual(j.decide(), {"run": "x", "stories": 0})
            third = jobs.state(self.cur)["decide"]
            self.assertEqual(third["last"]["skipped_stages"], ["graph"])
            self.assertEqual(third["failures"], 0)
            self.assertIsNone(j.decide())                                           # tried again the run after
        self.assertEqual(seen, [[], [], ["graph"], []])
        self.assertIn("the next run skips it", "\n".join(logs.output))

    def test_a_core_stage_is_never_skipped(self):
        clock = [0.0]

        def run(cur, *, stage, skip=(), **kw):
            self.assertEqual(list(skip), [])
            for name, secs in (("load", 10), ("questions and decisions", 200), ("write", 5)):
                stage(name)
                clock[0] += secs
        with mock.patch.object(jobs.time, "monotonic", lambda: clock[0]), mock.patch.object(decide, "run", run), \
                mock.patch.object(jobs.Jobs, "candidates", lambda self: {}), self.assertLogs(jobs.log, "WARNING"):
            j = jobs.Jobs(db_url(), limit=120, catch_up=120)
            for _ in range(3):
                self.assertIsNone(j.decide())
        last = jobs.state(self.cur)["decide"]["last"]
        self.assertEqual(last["over_in"], "questions and decisions")
        self.assertNotIn("skip_next", last)

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



class PlanningInTheBackground(_Api):
    """check, cite, track and relate are planned by the job "plan", never a lease."""

    def jobs_(self):
        return jobs.Jobs(db_url())

    def test_the_slow_kinds_are_planned_here(self):
        from insight_core.markx import tasks
        planners = {k: mock.Mock(return_value=n) for k, n in (("check", 7), ("cite", 2), ("track", 0), ("relate", 4), ("stop", 5), ("chain", 3), ("derive", 6),
                                                            ("digest", 1), ("track_things", 2), ("track_same", 3))}
        with mock.patch.object(tasks, "checks_in_background", lambda cur, now=None: True), \
                mock.patch.dict(tasks.PLANNERS, planners):
            got = self.jobs_().plan_background()
        self.assertEqual({k: v["added"] for k, v in got.items() if k not in ("track_places", "not_asked")},
                         {"check": 7, "cite": 2, "track": 0, "relate": 4, "stop": 5, "chain": 3, "derive": 6,
                          "digest": 1, "track_things": 2, "track_same": 3})
        self.assertIn("placed", got["track_places"])   # the track placements kept after the planners
        self.assertEqual(got["not_asked"], {})          # nothing open of a kind no feature reads

    def test_within_30_days_the_lease_plans_the_checks(self):
        from insight_core.markx import tasks
        planners = {k: mock.Mock(return_value=1) for k in tasks.BACKGROUND_PLANNED}
        with mock.patch.object(tasks, "checks_in_background", lambda cur, now=None: False), \
                mock.patch.dict(tasks.PLANNERS, planners):
            got = self.jobs_().plan_background()
        planners["check"].assert_not_called()
        self.assertEqual(got["check"], {"planned": "by the lane"})
        self.assertEqual(got["cite"]["added"], 1)

    def test_one_failure_never_stops_the_others(self):
        from insight_core.markx import tasks
        planners = {"check": mock.Mock(side_effect=RuntimeError("boom")), "cite": mock.Mock(return_value=3),
                    "track": mock.Mock(return_value=0), "relate": mock.Mock(return_value=0), "stop": mock.Mock(return_value=0),
                    "chain": mock.Mock(return_value=0), "derive": mock.Mock(return_value=0),
                    **{k: mock.Mock(return_value=0) for k in ("digest", "track_things", "track_same")}}
        with mock.patch.object(tasks, "checks_in_background", lambda cur, now=None: True), \
                mock.patch.dict(tasks.PLANNERS, planners):
            got = self.jobs_().plan_background()
        self.assertIn("boom", got["check"]["error"])
        self.assertEqual(got["cite"]["added"], 3)

    def test_the_plan_job_records_its_run(self):
        from insight_core.markx import tasks
        planners = {k: mock.Mock(return_value=1) for k in tasks.BACKGROUND_PLANNED}
        with mock.patch.object(tasks, "checks_in_background", lambda cur, now=None: True), \
                mock.patch.dict(tasks.PLANNERS, planners):
            self.jobs_().plan()
        last = jobs.state(self.cur)["plan"]["last"]
        self.assertTrue(last["ok"], last)
        self.assertEqual(last["kinds"]["cite"]["added"], 1)

    def test_keeping_the_track_placements_never_fails_the_plan(self):
        from insight_core.markx import tasks, track_kept
        planners = {k: mock.Mock(return_value=1) for k in tasks.BACKGROUND_PLANNED}
        with mock.patch.object(tasks, "checks_in_background", lambda cur, now=None: True), \
                mock.patch.dict(tasks.PLANNERS, planners), \
                mock.patch.object(track_kept, "refresh", mock.Mock(side_effect=RuntimeError("no places"))):
            self.jobs_().plan()
        last = jobs.state(self.cur)["plan"]["last"]
        self.assertTrue(last["ok"], last)
        self.assertIn("no places", last["kinds"]["track_places"]["failed"])
        self.assertEqual(last["kinds"]["track"]["added"], 1)

    def test_the_plan_job_is_due_every_5_minutes_before_a_decision_run(self):
        s = _states(plan={"started_at": T0 - timedelta(seconds=301)}, decide={"started_at": T0 - timedelta(hours=2)})
        self.assertEqual(jobs.due(s, T0, plan_every=300), "plan")
        s = _states(plan={"started_at": T0 - timedelta(seconds=10)}, decide={"started_at": T0 - timedelta(hours=2)})
        self.assertEqual(jobs.due(s, T0, plan_every=300), "decide")
        self.assertEqual(jobs.due(_states(), T0), "decide")              # without plan_every: as before
        s = _states(plan={"started_at": None}, candidates={"stage": "finding"})
        self.assertNotEqual(jobs.due(s, T0, plan_every=300), "plan")    # never beside the candidate finder


class AKilledEntitiesStage(_Api):
    """A run killed in the entities stage defers the full pass to the next night, so the runs between finish."""

    def kill_in(self, stage):
        with self.conn.transaction():
            self.cur.execute("INSERT INTO mx_jobs (job) VALUES ('decide') ON CONFLICT (job) DO NOTHING")
            self.cur.execute("UPDATE mx_jobs SET stage = %s, started_at = now() WHERE job = 'decide'", (stage,))
        alive = mock.Mock()
        alive.is_alive.return_value = True
        with mock.patch("multiprocessing.get_context") as ctx:
            ctx.return_value.Process.return_value = alive
            jobs.Runner(db_url(), hard_limit=0.01)._in_own_process("decide")
        alive.kill.assert_called_once()
        self.addCleanup(self._clear)

    def _clear(self):
        from insight_core.markx import entity_stage
        with self.conn.transaction():
            self.cur.execute("DELETE FROM mx_settings WHERE key = %s", (entity_stage.FULL_DEFERRED,))

    def test_killed_in_entities_the_full_pass_waits_for_the_next_night(self):
        from insight_core.markx import entity_stage
        self.kill_in("entities")
        last = jobs.state(self.cur)["decide"]["last"]
        self.assertEqual(last["stage"], "entities")
        with self.conn.transaction():
            self.assertIsNotNone(entity_stage.full_deferred(self.cur))
            self.assertFalse(entity_stage.full_due(self.cur, datetime.now(timezone.utc)))
            self.assertTrue(entity_stage.full_due(self.cur, datetime.now(timezone.utc) + timedelta(days=1)))

    def test_killed_elsewhere_nothing_is_deferred(self):
        from insight_core.markx import entity_stage
        self.kill_in("connections")
        self.assertEqual(jobs.state(self.cur)["decide"]["last"]["stage"], "connections")
        with self.conn.transaction():
            self.assertIsNone(entity_stage.full_deferred(self.cur))


class ADeadRun(_Api):
    """A crashed run is recorded like a killed one, and a stage nobody updates for longer than any run lives is
    cleared, so no job waits on a dead run."""

    def set_stage(self, job, stage, ago=0):
        with self.conn.transaction():
            self.cur.execute("INSERT INTO mx_jobs (job) VALUES (%s) ON CONFLICT (job) DO NOTHING", (job,))
            self.cur.execute("""UPDATE mx_jobs SET stage = %s, started_at = now() - make_interval(secs => %s),
                                       stage_at = now() - make_interval(secs => %s), wanted_at = NULL WHERE job = %s""",
                             (stage, ago, ago, job))

    def exit_with(self, code, job="decide"):
        ended = mock.Mock()
        ended.is_alive.return_value = False
        ended.exitcode = code
        with mock.patch("multiprocessing.get_context") as ctx, self.assertLogs(jobs.log, "ERROR"):
            ctx.return_value.Process.return_value = ended
            jobs.Runner(db_url())._in_own_process(job)

    def test_a_run_that_crashed_before_its_first_write_is_recorded(self):
        """A job whose process ended before it recorded its start is recorded as failed and waits its backoff (0209)."""
        self.cur.execute("DELETE FROM mx_jobs WHERE job = 'official'")
        self.exit_with(1, "official")
        s = jobs.state(self.cur)["official"]
        self.assertEqual((s["failures"], s["last"]["error"]), (1, "exited with code 1"))
        self.assertTrue(jobs.held(s, datetime.now(timezone.utc)))

    def test_a_run_with_no_stage_and_no_end_is_stale(self):
        """A run started after its last end with no stage, older than any run lives: stale (0209)."""
        unended = {"started_at": T0 - timedelta(hours=45), "finished_at": T0 - timedelta(hours=45, minutes=3)}
        ended = {"started_at": T0 - timedelta(hours=45), "finished_at": T0 - timedelta(hours=44)}
        young = {"started_at": T0 - timedelta(seconds=jobs.HARD_LIMIT)}
        self.assertEqual(jobs.stale(_states(decide=unended, candidates=ended, plan=young), T0), ["decide"])

    def test_the_runner_records_the_end_of_a_run_that_never_finished(self):
        self.cur.execute("INSERT INTO mx_jobs (job) VALUES ('decide') ON CONFLICT (job) DO NOTHING")
        self.cur.execute("""UPDATE mx_jobs SET started_at = now() - interval '45 hours',
                                   finished_at = now() - interval '45 hours 3 minutes', stage = NULL, wanted_at = NULL,
                                   failures = 0, last = '{"ok": true, "run": "r1"}' WHERE job = 'decide'""")
        seen = {}

        def due(states, now, **kw):
            seen.update(states)
            return None
        with mock.patch.object(jobs, "due", due), self.assertLogs(jobs.log, "ERROR"):
            jobs.Runner(db_url(), spawn=False, on=lambda: True).tick()
        s = jobs.state(self.cur)["decide"]
        self.assertGreater(s["finished_at"], s["started_at"])
        self.assertIsNotNone(s["wanted_at"])
        self.assertEqual((s["failures"], s["last"]["run"], s["last"]["ok"]), (0, "r1", False))
        self.assertIn("never finished", s["last"]["error"])
        self.assertEqual(seen["decide"]["finished_at"], s["finished_at"], "due() sees it ended")

    def test_a_crashed_run_is_recorded_like_a_killed_one(self):
        self.set_stage("decide", "connections")
        self.set_stage("candidates", "candidates")      # the finder the decision run was running inside it
        self.exit_with(-9)
        s = jobs.state(self.cur)
        self.assertEqual(s["decide"]["last"], {"ok": False, "error": "exited with code -9", "stage": "connections"})
        self.assertIsNone(s["decide"]["stage"])
        self.assertIsNotNone(s["decide"]["wanted_at"])
        self.assertIsNone(s["candidates"]["stage"])
        self.assertIsNotNone(s["candidates"]["wanted_at"])
        self.assertIn("inside the decide run", s["candidates"]["last"]["error"])
        self.assertEqual(jobs.due(s, datetime.now(timezone.utc) + timedelta(minutes=16)), "decide", "nothing waits")

    def test_a_run_that_recorded_its_end_keeps_its_record(self):
        jobs.Jobs(db_url())._finish("decide", {"ok": True, "seconds": 1.0})
        self.exit_with(1)
        self.assertEqual(jobs.state(self.cur)["decide"]["last"], {"ok": True, "seconds": 1.0})

    def test_stale_is_a_stage_older_than_any_run_can_live(self):
        old = {"stage": "candidates", "stage_at": T0 - timedelta(seconds=jobs.HARD_LIMIT + jobs.STALE_MARGIN + 1)}
        young = {"stage": "load", "stage_at": T0 - timedelta(seconds=jobs.HARD_LIMIT)}
        self.assertEqual(jobs.stale(_states(candidates=old, decide=young), T0), ["candidates"])
        self.assertEqual(jobs.stale(_states(), T0), [])

    def test_the_runner_clears_a_dead_runs_stage_and_wants_it_again(self):
        self.set_stage("candidates", "candidates", ago=jobs.HARD_LIMIT + jobs.STALE_MARGIN + 60)
        self.set_stage("decide", "load", ago=5)          # alive: left alone
        seen = {}

        def due(states, now, **kw):
            seen.update(states)
            return None
        with mock.patch.object(jobs, "due", due), self.assertLogs(jobs.log, "ERROR"):
            jobs.Runner(db_url(), spawn=False, on=lambda: True).tick()
        self.assertIsNone(seen["candidates"]["stage"], "due() sees it cleared")
        s = jobs.state(self.cur)
        self.assertIsNone(s["candidates"]["stage"])
        self.assertIsNotNone(s["candidates"]["wanted_at"])
        self.assertIn("no word from the run", s["candidates"]["last"]["error"])
        self.assertEqual(s["decide"]["stage"], "load")


if __name__ == "__main__":
    unittest.main()
