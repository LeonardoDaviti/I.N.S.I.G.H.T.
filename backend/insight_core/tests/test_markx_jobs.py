"""Mark X's jobs (markx/jobs.py): the candidates' debounce and the decisions' clock, moved out of candidates.py and
decide.py with no change (0112 Decided 10, step 1)."""
from __future__ import annotations

import unittest
from unittest import mock

from insight_core.markx import candidates as C
from insight_core.markx import decide as D
from insight_core.markx import jobs as J


class Debounce(unittest.TestCase):
    def test_posts_wait_for_one_run_and_a_failed_run_keeps_them(self):
        runs = []

        class Tx:
            def __enter__(self):
                return "cursor"

            def __exit__(self, *exc):
                return False

        pending = J.Pending(delay=None, transaction=Tx)
        original = C.run
        self.addCleanup(setattr, C, "run", original)
        C.run = lambda cur, ids, since=None: runs.append((cur, set(ids), since)) or {"embedding": len(ids)}
        pending.note(["p1", "p2"])
        pending.note(["p2", "p3"])
        self.assertEqual(runs, [])
        self.assertEqual(pending.flush(), {"embedding": 3})
        self.assertEqual(runs[0][1], {"p1", "p2", "p3"})
        self.assertIsNotNone(pending.last_run)

        def boom(cur, ids, since=None):
            raise RuntimeError("database gone")
        C.run = boom
        pending.note(["p4"])
        with self.assertLogs(J.log, "ERROR"):
            self.assertIsNone(pending.flush())
        self.assertEqual(pending.posts, {"p4"})

    def test_a_timer_runs_it_after_the_last_note(self):
        pending = J.Pending(delay=0.05, transaction=None)
        done = []
        pending.flush = lambda: done.append(set(pending.posts))
        pending.note(["p1"])
        pending.note(["p2"])
        pending.timer.join(2)
        self.assertEqual(done, [{"p1", "p2"}])


class Switch(unittest.TestCase):
    def test_off_nothing_runs(self):
        ran = []
        s = J.Scheduler(transaction=lambda: ran.append(1), debounce=0.01, every=0.01, enabled=lambda: False)
        s.note()
        self.assertFalse(s.start())
        self.assertIsNone(s.run_now())
        self.assertEqual(ran, [])

    def test_uploads_close_together_make_one_run_after_the_last(self):
        import contextlib
        import threading
        import time
        ran, done = [], threading.Event()

        @contextlib.contextmanager
        def transaction():
            yield "cur"

        def fake_run(cur):
            ran.append(cur)
            done.set()
            return {"stories": 0}
        with mock.patch.object(D, "run", fake_run):
            s = J.Scheduler(transaction=transaction, debounce=0.2, every=None, enabled=lambda: True)
            for _ in range(3):
                s.note()
                time.sleep(0.05)
            self.assertTrue(done.wait(2))
            time.sleep(0.3)
        self.assertEqual(ran, ["cur"])

    def test_the_first_run_follows_the_starts_story_job(self):
        """0112 A: the start's story job ends, then Mark X decides at once (it waited up to an hour for the clock)."""
        import contextlib
        ran = []

        @contextlib.contextmanager
        def transaction():
            yield "cur"
        with mock.patch.object(D, "run", lambda cur: ran.append(cur) or {"stories": 0}):
            J.Scheduler(transaction=transaction, debounce=None, every=None, enabled=lambda: False).after_stories()
            self.assertEqual(ran, [])
            with mock.patch("insight_core.markx.jobs.pending.flush") as flush:
                J.Scheduler(transaction=transaction, debounce=None, every=None, enabled=lambda: True).after_stories()
            flush.assert_called_once()
        self.assertEqual(ran, ["cur"])

    def test_the_api_start_runs_mark_x_after_the_story_job(self):
        import main
        order = []
        with mock.patch.object(main, "in_own_process", lambda job: order.append(job.__name__)), \
                mock.patch.object(J.scheduler, "after_stories", lambda: order.append("markx")):
            main.start_stories()
        self.assertEqual(order, ["recompute_stories", "markx"])

    def test_on_a_failed_run_never_raises(self):
        def broken():
            raise RuntimeError("no database")
        s = J.Scheduler(transaction=broken, debounce=None, every=None, enabled=lambda: True)
        self.assertIsNone(s.run_now())


if __name__ == "__main__":
    unittest.main()
