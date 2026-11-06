"""The API watchdog (services/api_watchdog.py, issue 0117): the judge in insight-ingestion, the door in the API
container, and the stack dump the API registers."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from insight_core.scripts import api_supervisor as S
from insight_core.services import api_watchdog as W


class FakeOps:
    def __init__(self, recent=()):
        self.jobs, self.events, self.recent = [], [], list(recent)

    def recent_job_times(self, job_type, seconds, kind=None):
        return list(self.recent)

    def start_job(self, job_type, **kw):
        self.jobs.append({"job_type": job_type, **kw})
        return f"job-{len(self.jobs)}"

    def finish_job(self, job_id, **kw):
        self.jobs[int(job_id.split("-")[1]) - 1]["finished"] = kw

    def append_job_event(self, job_id, **kw):
        self.events.append((job_id, kw))


class Judge(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.dir, "core"))
        with open(os.path.join(self.dir, W.APP_LOG), "w") as fh:
            fh.write("".join(f"line {n}\n" for n in range(80)))
        self.now = [1_000_000.0]
        self.answers = []
        self.ops = FakeOps()

    def dog(self, **kw):
        return W.Watchdog(self.ops, directory=self.dir, check=lambda: self.answers.pop(0) if self.answers else False,
                          clock=lambda: self.now[0], **kw)

    def step(self, dog, seconds=30):
        self.now[0] += seconds
        return dog.tick()

    def request(self):
        path = os.path.join(self.dir, W.REQUEST)
        return json.load(open(path)) if os.path.exists(path) else None

    def test_two_minutes_of_failures_ask_for_one_restart_then_it_waits(self):
        dog = self.dog()
        with self.assertLogs(W.logger, "WARNING"):
            self.assertEqual([self.step(dog) for _ in range(3)], ["failing"] * 3)
        self.assertIsNone(self.request())
        with self.assertLogs(W.logger, "ERROR"):
            self.assertEqual(self.step(dog), "restart")
        req = self.request()
        self.assertEqual(req["failing_seconds"], 90)
        self.assertEqual(req["job_id"], "job-1")
        job = self.ops.jobs[0]
        self.assertEqual((job["job_type"], job["trigger"], job["finished"]["status"]), ("api_restart", "watchdog", "failed"))
        self.assertIn("The API was restarted after", job["message"])
        self.assertEqual(job["payload"]["log_tail"], [f"line {n}" for n in range(30, 80)])   # the last 50 lines
        # five minutes of quiet: no judging, however it fails
        self.assertEqual([self.step(dog) for _ in range(9)], ["cooling"] * 9)
        self.assertEqual(len(self.ops.jobs), 1)

    def test_an_answer_resets_the_count(self):
        dog = self.dog()
        self.answers = [False, False, False, True, False, False, False]
        with self.assertLogs(W.logger, "WARNING"):
            outcomes = [self.step(dog) for _ in range(7)]
        self.assertEqual(outcomes, ["failing"] * 3 + ["ok"] + ["failing"] * 3)
        self.assertEqual(self.ops.jobs, [])

    def test_no_more_than_three_restarts_an_hour_then_it_says_so_once(self):
        dog = self.dog()
        outcomes = []
        with self.assertLogs(W.logger, "WARNING") as logs:
            for _ in range(60):          # 30 minutes of an API that never answers
                outcomes.append(self.step(dog))
        self.assertEqual(outcomes.count("restart"), 3)
        self.assertGreater(outcomes.count("gave_up"), 0)
        kinds = [j["payload"]["kind"] for j in self.ops.jobs]
        self.assertEqual(kinds, ["restart"] * 3 + ["gave_up"])
        self.assertIn("The API keeps failing", self.ops.jobs[-1]["message"])
        self.assertEqual(sum("keeps failing" in line for line in logs.output), 1)

    def test_keeps_failing_is_recorded_once_even_with_an_answer_between(self):
        """Measured on a copy: the API answered once between two hangs, and the give-up was recorded twice."""
        self.ops = FakeOps(recent=[self.now[0] - 600] * 3)
        dog = self.dog()
        self.answers = [False, False, False, False, True, False, False, False, False]
        with self.assertLogs(W.logger, "WARNING"):
            outcomes = [self.step(dog) for _ in range(9)]
        self.assertEqual(outcomes.count("gave_up"), 2)
        self.assertEqual([j["payload"]["kind"] for j in self.ops.jobs], ["gave_up"])

    def test_the_cap_survives_a_restart_of_ingestion(self):
        self.ops = FakeOps(recent=[self.now[0] - 600] * 3)
        dog = self.dog()
        with self.assertLogs(W.logger, "WARNING"):
            outcomes = [self.step(dog) for _ in range(4)]
        self.assertEqual(outcomes[-1], "gave_up")
        self.assertIsNone(self.request())

    def test_the_dump_goes_to_the_log_and_onto_its_restart(self):
        with open(os.path.join(self.dir, W.DONE), "w") as fh:
            json.dump({"request": {"job_id": "job-7"}, "stacks": 'File "main.py", line 1 in debug_spin'}, fh)
        dog = self.dog()
        self.answers = [True]
        with self.assertLogs(W.logger, "ERROR") as logs:
            self.step(dog)
        self.assertIn("debug_spin", "\n".join(logs.output))
        self.assertEqual(self.ops.events[0][0], "job-7")
        self.assertIn("debug_spin", self.ops.events[0][1]["fields"]["stacks"])
        self.assertFalse(os.path.exists(os.path.join(self.dir, W.DONE)))


class TimesForTheReader(unittest.TestCase):
    """0124 (the v10.0.2 review's W7): "The API was restarted at 10:53" (the container's UTC) sat over the page's
    "2:53:23 PM". The record says no clock time: the times are ISO UTC in its payload, and the page writes them in
    the reader's zone."""

    def setUp(self):
        Judge.setUp(self)

    dog, step = Judge.dog, Judge.step

    def test_a_restart_record_has_its_time_in_the_payload_not_in_the_message(self):
        dog = self.dog()
        with self.assertLogs(W.logger, "WARNING"):
            for _ in range(4):
                self.step(dog)
        job = self.ops.jobs[0]
        self.assertEqual(job["message"], "The API was restarted after 2 min of no answer")
        self.assertEqual(job["payload"]["at"], "1970-01-12T13:48:40+00:00")
        self.assertNotRegex(job["finished"]["message"], r"\d:\d\d")

    def test_a_give_up_record_has_until_in_the_payload(self):
        self.ops = FakeOps(recent=[self.now[0] - 600, self.now[0] - 500, self.now[0] - 400])
        dog = self.dog()
        with self.assertLogs(W.logger, "WARNING"):
            for _ in range(4):
                self.step(dog)
        job = self.ops.jobs[-1]
        self.assertEqual(job["payload"]["kind"], "gave_up")
        self.assertEqual(job["payload"]["restarts"], 3)
        self.assertEqual(job["payload"]["until"], W._iso(1_000_000 - 600 + 3600))
        self.assertNotRegex(job["message"], r"\d:\d\d")
        self.assertIn("no more for 48 min", job["message"])


class Door(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def test_a_request_is_honoured_once_with_the_stacks_saved_first(self):
        sent = []

        def kill(pid, signum):
            sent.append((pid, signum))
            with open(os.path.join(self.dir, W.STACKS), "a") as fh:
                fh.write(f"Thread 0x1 (most recent call first):\n  File \"main.py\", line 9 in debug_spin\n")
        door = W.RestartDoor(self.dir, processes=lambda: [11, 12], kill=kill, settle=0)
        self.assertIsNone(door.honour())
        W._write_json(os.path.join(self.dir, W.REQUEST), {"reason": "no answer", "job_id": "job-1"})
        with self.assertLogs(W.logger, "ERROR"):
            self.assertEqual(door.honour()["job_id"], "job-1")
        self.assertEqual(sent, [(11, signal.SIGUSR1), (12, signal.SIGUSR1)])
        done = json.load(open(os.path.join(self.dir, W.DONE)))
        self.assertEqual(done["request"]["job_id"], "job-1")
        self.assertIn("=== API process 11", done["stacks"])
        self.assertEqual(done["stacks"].count("debug_spin"), 2)
        self.assertIsNone(door.honour())                    # taken: once

    def test_the_children_of_a_process_are_read_from_proc(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        self.addCleanup(child.kill)
        self.assertIn(child.pid, W.children(os.getpid()))
        self.assertEqual(W.children(child.pid), [])

    def test_only_the_api_processes_get_the_signal(self):
        """uvicorn's spawned API processes, never another child (its resource tracker would end on SIGUSR1)."""
        api = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)  # spawn_main"])
        other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)  # resource_tracker"])
        self.addCleanup(api.kill)
        self.addCleanup(other.kill)
        got = W.api_processes(os.getpid())
        self.assertIn(api.pid, got)
        self.assertNotIn(other.pid, got)
        self.assertEqual(W.api_processes(api.pid), [api.pid])          # one process: uvicorn itself


class SupervisorRestart(unittest.TestCase):
    def test_asked_it_stops_uvicorn_and_exits_for_docker_to_restart(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(child.kill)
        s = S.Supervisor(["x"], popen=lambda c, env: child, spawn_work=lambda: None, close_jobs=lambda: 0)
        s.start()
        s.stop_for_restart(grace=5)
        self.assertEqual(s.wait(poll=0.05), S.RESTART_EXIT)


class TheStackDump(unittest.TestCase):
    def test_sigusr1_writes_every_threads_stack_while_python_is_stuck(self):
        """An API process busy in a loop that never yields: SIGUSR1 still names the loop's function."""
        with tempfile.TemporaryDirectory() as tmp:
            code = ("import os, sys, time; sys.path.insert(0, os.getcwd()); os.environ['INSIGHT_LOG_DIR'] = %r\n"
                    "import main\n"
                    "def stuck_in_a_loop():\n"
                    "    end = time.monotonic() + 20\n"
                    "    while time.monotonic() < end: pass\n"
                    "print('ready', flush=True); stuck_in_a_loop()\n") % tmp
            p = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True,
                                 cwd=str(Path(__file__).resolve().parents[2]))
            self.addCleanup(p.kill)
            self.assertEqual(p.stdout.readline().strip(), "ready")
            time.sleep(0.5)
            os.kill(p.pid, signal.SIGUSR1)
            time.sleep(1)
            text = open(os.path.join(tmp, W.STACKS)).read()
            self.assertIn("stuck_in_a_loop", text)
            self.assertEqual(p.poll(), None, "the process keeps running")


class TheSpinRoute(unittest.TestCase):
    def test_it_is_404_unless_switched_on(self):
        import main
        from insight_core.tests._asgi import call
        with mock.patch.dict(os.environ, {"INSIGHT_DEBUG_SPIN": "off"}):
            self.assertEqual(call(main.app, "POST", "/api/debug/spin", query={"seconds": 1})[0], 404)
        with mock.patch.dict(os.environ, {"INSIGHT_DEBUG_SPIN": "on"}):
            self.assertEqual(call(main.app, "POST", "/api/debug/spin", query={"seconds": 1})[0], 200)


class TheHealthcheck(unittest.TestCase):
    def test_compose_checks_api_version_every_30_s_and_4_failures_are_unhealthy(self):
        compose = (Path(__file__).resolve().parents[3] / "docker-compose.yml")
        if not compose.exists():
            self.skipTest("docker-compose.yml is not in this image")
        text = compose.read_text()
        backend = text[text.index("  backend:"):text.index("  ingestion:")]
        self.assertIn("http://localhost:8000/api/version", backend)
        self.assertIn("retries: 4", backend)
        ingestion = text[text.index("  ingestion:"):text.index("  frontend:")]
        self.assertIn("INSIGHT_API_WATCHDOG", ingestion)


if __name__ == "__main__":
    unittest.main()
