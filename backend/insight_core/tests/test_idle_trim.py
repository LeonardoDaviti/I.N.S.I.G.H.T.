"""Freed memory back to the OS when an API process is idle (issue 0202, utils/idle_trim.py)."""
from __future__ import annotations

import asyncio
import threading
import unittest

import main
from insight_core.utils import idle_trim as T


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class Trimmer(unittest.TestCase):
    def make(self, rss=(100.0,)):
        self.clock, self.trims, self.rss = Clock(), [], list(rss)
        self.order = []
        t = T.Trimmer(trim=lambda: (self.trims.append(self.clock.t), self.order.append("trim")),
                      rss=lambda: self.rss[0], clock=self.clock, quiet=1.0, grow_mb=8.0,
                      collect=lambda: self.order.append("collect"))
        t._thread = object()        # the tests take the thread's steps themselves
        return t

    def test_it_trims_only_after_a_quiet_spell_with_no_request_in_flight(self):
        t = self.make()
        t.began()
        self.rss[0] = 150.0
        self.assertFalse(t.step())                  # a request in flight
        t.ended()
        self.assertEqual(t.wait_left(), 1.0)
        self.assertFalse(t.step())                  # idle, not yet for long enough
        self.clock.t += 1.0
        self.assertTrue(t.step())
        self.assertEqual(self.trims, [101.0])
        self.assertEqual(self.order, ["collect", "trim"])   # the cycles holding psycopg results first

    def test_a_request_starting_in_the_spell_waits_for_its_end(self):
        t = self.make()
        t.began(); t.ended()
        self.rss[0] = 150.0
        self.clock.t += 0.5
        t.began()
        self.clock.t += 0.6
        self.assertIsNone(t.wait_left())
        self.assertFalse(t.step())
        t.ended()
        self.clock.t += 0.9
        self.assertFalse(t.step())
        self.clock.t += 0.1
        self.assertTrue(t.step())

    def test_a_process_that_did_not_grow_is_not_trimmed(self):
        t = self.make()
        t.began(); t.ended()
        self.clock.t += 2
        self.rss[0] = 107.0                         # under 8 MB more than at the start
        self.assertFalse(t.step())
        self.rss[0] = 108.0
        self.assertTrue(t.step())
        self.assertEqual(t.after_trim, 108.0)       # RSS read after the trim: the next one counts from there
        self.assertFalse(t.step())
        self.rss[0] = 90.0                          # shrank by itself: the growth counts from the lowest seen
        self.assertFalse(t.step())
        self.assertEqual(t.after_trim, 90.0)
        self.rss[0] = 98.0
        self.assertTrue(t.step())

    def test_overlapping_requests_count_as_one_busy_spell(self):
        t = self.make()
        t.began(); t.began(); t.ended()
        self.assertEqual(t.inflight, 1)
        self.assertIsNone(t.wait_left())
        t.ended()
        self.assertEqual(t.inflight, 0)

    def test_without_malloc_trim_nothing_happens(self):
        t = T.Trimmer(trim=None)
        t.began(); t.ended()
        self.assertFalse(t.step())
        self.assertIsNone(t._thread)                # and no thread is started


class TheThread(unittest.TestCase):
    def test_the_thread_trims_once_the_process_is_idle(self):
        rss = [100.0]
        trimmed = threading.Event()
        t = T.Trimmer(trim=trimmed.set, rss=lambda: rss[0], quiet=0.05, grow_mb=1.0)
        t.began()
        rss[0] = 200.0
        t.ended()
        self.assertTrue(trimmed.wait(10), "the idle trim never ran")
        self.assertEqual(t.trims, 1)


class TheMiddleware(unittest.TestCase):
    def test_every_request_is_counted_in_flight_until_its_last_byte(self):
        seen = []

        class Spy(T.Trimmer):
            def began(self):
                seen.append("began")
                super().began()

            def ended(self):
                seen.append("ended")
                super().ended()

        trimmer = Spy(trim=lambda: None, rss=lambda: 0.0, quiet=3600)
        trimmer._thread = object()

        async def app(scope, receive, send):
            seen.append(("inflight", trimmer.inflight))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"x"})

        async def send(message):
            pass

        mw = T.IdleTrim(app, trimmer=trimmer)
        asyncio.run(mw({"type": "http", "method": "GET", "path": "/x"}, None, send))
        self.assertEqual(seen, ["began", ("inflight", 1), "ended"])
        self.assertEqual(trimmer.inflight, 0)
        asyncio.run(mw({"type": "lifespan"}, None, send))          # not a request: not counted
        self.assertEqual(seen[-1], ("inflight", 0))

    def test_the_app_has_it_outermost(self):
        self.assertIs(main.app.user_middleware[0].cls, T.IdleTrim)

    def test_the_start_is_frozen_out_of_the_gc(self):
        import gc
        T.freeze_start()
        try:
            self.assertGreater(gc.get_freeze_count(), 0)
        finally:
            gc.unfreeze()

    def test_glibc_has_malloc_trim_here(self):
        self.assertIsNotNone(T.libc_trim())        # the image is Debian (glibc): the trim is real
        self.assertIsNotNone(T.rss_mb())


if __name__ == "__main__":
    unittest.main()
