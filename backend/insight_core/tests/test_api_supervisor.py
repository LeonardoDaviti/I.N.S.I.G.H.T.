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


class OpenFiles(unittest.TestCase):
    """0124 (the v10.0.2 review's W4): after a 15-minute hang of both API processes, one came back holding 1,006
    sockets against the container's 1,024 open files (2,096 "Too many open files" in a second), and stayed so: then
    a fresh hang of the other process stalled 11 of 40 requests. The limit is raised, the queue bounded, and a
    process left at its limit is replaced."""

    def test_the_soft_limit_is_raised_to_the_hard_one_capped(self):
        got = []
        self.assertEqual(S.raise_open_files(get=lambda: (1024, 524288), set_=lambda soft, hard: got.append((soft, hard))),
                         65536)
        self.assertEqual(got, [(65536, 524288)])
        got.clear()
        self.assertEqual(S.raise_open_files(get=lambda: (1024, 4096), set_=lambda soft, hard: got.append((soft, hard))), 4096)
        self.assertEqual(got, [(4096, 4096)])
        got.clear()
        self.assertEqual(S.raise_open_files(get=lambda: (65536, 65536), set_=lambda soft, hard: got.append((soft, hard))),
                         65536)
        self.assertEqual(got, [])                      # already there: nothing to do

    def test_open_files_and_their_limit_are_read_from_proc(self):
        import resource
        self.assertGreater(S.open_files(os.getpid()), 2)
        self.assertEqual(S.open_files_limit(os.getpid()), resource.getrlimit(resource.RLIMIT_NOFILE)[0])
        self.assertIsNone(S.open_files(2 ** 22 + 7))   # no such process

    def guard(self, counts, limit=1024, looks=3):
        ended, now = [], [0.0]
        seq = {pid: list(cs) for pid, cs in counts.items()}
        g = S.OpenFilesGuard(processes=lambda: sorted(seq), count=lambda pid: seq[pid].pop(0) if seq[pid] else 10,
                             limit=lambda pid: limit, end=ended.append, looks=looks)
        return g, ended

    def test_a_process_held_at_its_limit_is_ended_once_uvicorn_starts_another(self):
        g, ended = self.guard({40: [1006, 1010, 1012, 1012], 41: [30, 30, 30, 30]})
        with self.assertLogs(S.logger, "ERROR") as logs:
            for _ in range(3):
                g.tick()
        self.assertEqual(ended, [40])
        self.assertIn("1012 of 1024 open files", "\n".join(logs.output))

    def test_a_burst_that_drains_is_left_alone(self):
        g, ended = self.guard({40: [1006, 1010, 200, 1010, 1010]})
        for _ in range(5):
            g.tick()
        self.assertEqual(ended, [])

    def test_compose_raises_the_limit_and_the_start_script_bounds_the_queue(self):
        from pathlib import Path
        start = (Path(S.BACKEND_DIR) / "docker" / "start-backend.sh").read_text()
        self.assertIn("--backlog", start)
        self.assertIn("--limit-concurrency", start)
        self.assertNotIn("replaces one that stops answering", start)   # uvicorn 0.54 doesn't (measured, 0124)
        compose = Path(S.BACKEND_DIR).parent / "docker-compose.yml"
        if not compose.exists():
            self.skipTest("docker-compose.yml is not in this image")
        text = compose.read_text()
        backend = text[text.index("  backend:"):text.index("  ingestion:")]
        self.assertIn("nofile", backend)


if __name__ == "__main__":
    unittest.main()
