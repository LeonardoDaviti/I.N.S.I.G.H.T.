"""The API container's supervisor (scripts/api_supervisor.py, issue 0112 Decided 11): with two API processes, the
start's work runs once per container, never once per process."""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import unittest
from unittest import mock

import main
from insight_core.scripts import api_supervisor as S


class FakeChild:
    def __init__(self, codes):
        self.codes = list(codes)
        self.signals = []

    def poll(self):
        return self.codes.pop(0) if self.codes else None

    def send_signal(self, signum):
        self.signals.append(signum)


class Supervisor(unittest.TestCase):
    def test_the_jobs_are_closed_before_uvicorn_and_the_start_work_runs_once(self):
        order, seen_env = [], {}

        def popen(command, env):
            order.append(("uvicorn", command))
            seen_env.update(env)
            return FakeChild([None, 0])
        s = S.Supervisor(["uvicorn", "main:app", "--workers", "2"], popen=popen,
                         spawn_work=lambda: order.append(("work",)), close_jobs=lambda: order.append(("close",)) or 0)
        s.start()
        self.assertEqual(order, [("close",), ("uvicorn", ["uvicorn", "main:app", "--workers", "2"]), ("work",)])
        self.assertEqual(seen_env[S.SUPERVISED], "1")
        self.assertEqual(s.wait(poll=0), 0)

    def test_a_stop_goes_to_uvicorn_and_its_code_is_the_exit(self):
        child = FakeChild([None, None, 3])
        s = S.Supervisor(["uvicorn"], popen=lambda c, env: child, spawn_work=lambda: None, close_jobs=lambda: 0)
        s.start()
        s.forward(signal.SIGTERM)
        self.assertEqual(child.signals, [signal.SIGTERM])
        self.assertEqual(s.wait(poll=0), 3)

    def test_a_failed_start_work_never_stops_the_api(self):
        def boom():
            raise RuntimeError("no fork")
        s = S.Supervisor(["uvicorn"], popen=lambda c, env: FakeChild([0]), spawn_work=boom, close_jobs=lambda: 0)
        with self.assertLogs(S.logger, "ERROR"):
            s.start()
        self.assertEqual(s.wait(poll=0), 0)

    def test_a_sigusr1_reaches_each_api_process(self):
        sent = []
        s = S.Supervisor(["uvicorn"], popen=lambda c, env: FakeChild([0]), spawn_work=lambda: None, close_jobs=lambda: 0)
        self.assertEqual(s.dump_stacks(lambda: [21, 22], kill=lambda pid, sig: sent.append((pid, sig))), [21, 22])
        self.assertEqual(sent, [(21, signal.SIGUSR1), (22, signal.SIGUSR1)])

    def test_the_start_work_is_the_search_refill_and_the_story_job(self):
        ran = []
        with mock.patch.object(main, "fill_search_vectors", lambda: ran.append("search")), \
                mock.patch.object(main, "start_stories", lambda: ran.append("stories")):
            S.start_work()
        self.assertEqual(sorted(ran), ["search", "stories"])


class TheLifespan(unittest.TestCase):
    """Each API process's start: the work only when it is the only one (no supervisor)."""

    def run_lifespan(self):
        async def go():
            async with main.lifespan(main.app):
                pass
        with mock.patch.object(main, "services"), mock.patch.object(main.database, "close_all"):
            asyncio.run(go())

    def test_under_the_supervisor_a_process_starts_nothing(self):
        with mock.patch.dict(os.environ, {S.SUPERVISED: "1"}), mock.patch.object(main, "start_once") as once:
            self.run_lifespan()
        once.assert_not_called()

    def test_alone_it_does_the_start_work(self):
        env = {k: v for k, v in os.environ.items() if k != S.SUPERVISED}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(main, "start_once") as once:
            self.run_lifespan()
        once.assert_called_once()


if __name__ == "__main__":
    unittest.main()
