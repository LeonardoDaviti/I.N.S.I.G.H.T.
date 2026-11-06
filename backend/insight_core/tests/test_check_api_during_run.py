"""The real-data check's markx.api_during_run (0112 Decided 13): the API is measured while Mark X decides, and a
request over 1 s fails the merge. What counts is what the run adds: the same probes before and after the run are the
machine's own slowness (other checks share the database), and only the slow requests over that rate count."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest import mock

import psycopg

from insight_core.checks import job_checks, report
from insight_core.tests._db import db_url, requires_test_db


class TheCheck(unittest.TestCase):
    def test_the_number_of_api_processes_is_the_start_scripts(self):
        with tempfile.TemporaryDirectory() as app:
            os.makedirs(os.path.join(app, "docker"))
            script = os.path.join(app, "docker", "start-backend.sh")
            for text, n in (('WORKERS="${API_WORKERS:-2}"\nexec uvicorn main:app --workers "$WORKERS"', 2),
                            ("exec uvicorn main:app --host 0.0.0.0 --workers 1", 1), ("exec uvicorn main:app", 1)):
                with open(script, "w") as fh:
                    fh.write(text)
                self.assertEqual(job_checks._api_workers(app), n, text)
        self.assertEqual(job_checks._api_workers("/nowhere"), 1)

    def test_a_slow_answer_fails_the_check_whatever_main_does(self):
        self.assertIn("markx.api_during_run", report.MUST_BE_ZERO)
        with tempfile.TemporaryDirectory() as work:
            for side, count in (("base", 7), ("head", 2)):
                os.makedirs(os.path.join(work, side))
                with open(os.path.join(work, side, "jobs.json"), "w") as fh:
                    json.dump({"found": [{"name": "markx.api_during_run", "what": "slow", "count": count, "of": 100,
                                          "examples": [], "note": ""}]}, fh)
            _, problems = report.build(work)
        self.assertTrue(any("markx.api_during_run: 2" in p for p in problems), problems)


class DuringTheFirstStart(unittest.TestCase):
    """0121 Decided 8: the same gate during a deploy's first start after a rule change (the v10.0.1 review saw 2.0-5.8 s
    stalls of the whole API during the first start's rebuild), with the same baseline-relative count."""

    def test_the_gate_fails_above_zero_whatever_main_does_and_main_may_not_have_it(self):
        self.assertIn("markx.api_during_rebuild", report.MUST_BE_ZERO)
        self.assertIn("markx.api_during_rebuild", report.ZERO_EVEN_IF_FELL)
        for base, head, fails in (([], 1, True), ([], 0, False), ([5], 1, True)):
            with tempfile.TemporaryDirectory() as work:
                for side, found in (("base", [{"name": "markx.api_during_rebuild", "count": c, "of": 9, "what": "slow",
                                               "examples": [], "note": ""} for c in base]),
                                    ("head", [{"name": "markx.api_during_rebuild", "count": head, "of": 9, "what": "slow",
                                               "examples": [], "note": ""}])):
                    os.makedirs(os.path.join(work, side))
                    with open(os.path.join(work, side, "jobs.json"), "w") as fh:
                        json.dump({"found": found}, fh)
                _, problems = report.build(work)
            self.assertEqual(any("markx.api_during_rebuild" in p for p in problems), fails, (base, head, problems))

    def test_the_check_measures_the_first_start_last(self):
        order = []
        with mock.patch.object(job_checks, "scratch_only", lambda url: None), \
                mock.patch.object(job_checks, "rebuild_twice", lambda *a: order.append("rebuild") or []), \
                mock.patch.object(job_checks, "markx_unchanged", lambda *a: order.append("ix") or []), \
                mock.patch.object(job_checks, "incremental_identity", lambda *a: order.append("identity") or "i"), \
                mock.patch.object(job_checks, "api_during_run", lambda *a: order.append("run") or "r"), \
                mock.patch.object(job_checks, "api_during_rebuild", lambda *a: order.append("start") or "s"):
            found = job_checks.check("postgresql://x/y_test", None)
        self.assertEqual(order, ["rebuild", "ix", "identity", "run", "start"])
        self.assertEqual(found[-2:], ["r", "s"])

    @requires_test_db
    def test_the_copy_is_made_to_need_a_rebuild_and_the_versions_start_work_runs_as_its_container_runs_it(self):
        from insight_core.services.stories_service import SETTINGS_KEY
        url = db_url()
        with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM system_settings WHERE key = %s", (SETTINGS_KEY,))
            kept = cur.fetchone()
            cur.execute("INSERT INTO system_settings (key, value, updated_at) VALUES (%s, %s::jsonb, now()) "
                        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                        (SETTINGS_KEY, json.dumps({"rules": "this code's", "rebuild": {"done": 3}})))
        self.addCleanup(self._put, url, SETTINGS_KEY, kept[0] if kept else None)
        seen = {}

        def measured(db, name, what, log_name, work):
            seen.update(name=name, log=log_name, work=work)
            return "found"
        with mock.patch.object(job_checks, "_measured", measured):
            self.assertEqual(job_checks.api_during_rebuild(url, None), "found")
        self.assertEqual(seen["name"], "markx.api_during_rebuild")
        with psycopg.connect(url) as conn, conn.cursor() as cur:
            cur.execute("SELECT value FROM system_settings WHERE key = %s", (SETTINGS_KEY,))
            self.assertEqual(cur.fetchone()[0], {"rules": job_checks.FORCED_RULES})   # a rule change, no rebuild begun
        calls = []

        class Child:
            pid, returncode = 4242, 0

            def wait(self, timeout=None):
                return 0
        fake = type("Api", (), {"env": {"X": "1"}})()
        with mock.patch("subprocess.Popen", lambda args, **kw: calls.append((args, kw)) or Child()), \
                tempfile.TemporaryDirectory() as here, _cwd(here):
            note = seen["work"](fake)
        (args, kw), = calls
        self.assertIn("from insight_core.scripts.api_supervisor import start_work", args[-1])
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(kw["env"], {"X": "1"})
        self.assertEqual(note["start_work"], "finished")

    @staticmethod
    def _put(url, key, value):
        with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
            if value is None:
                cur.execute("DELETE FROM system_settings WHERE key = %s", (key,))
            else:
                cur.execute("UPDATE system_settings SET value = %s::jsonb WHERE key = %s", (json.dumps(value), key))


class _cwd:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.was = os.getcwd()
        os.chdir(self.path)

    def __exit__(self, *exc):
        os.chdir(self.was)


def rows(n: int, slow: int = 0, failed: int = 0):
    """n probe answers: `slow` of them over 1 s, `failed` of them failing (status -1 after the 10 s timeout)."""
    out = [{"path": "/api/version", "ms": 2, "status": 200} for _ in range(n - slow - failed)]
    out += [{"path": "/api/feed", "ms": 1500, "status": 200} for _ in range(slow)]
    out += [{"path": "/api/feed", "ms": 10010, "status": -1} for _ in range(failed)]
    return out


class WhatTheRunAdds(unittest.TestCase):
    def test_on_a_quiet_machine_every_slow_or_failing_request_counts(self):
        count, note = job_checks.added_by_run(rows(40), rows(30, slow=2, failed=1), rows(40))
        self.assertEqual(count, 3)
        self.assertEqual(note["expected"], 0)

    def test_a_machine_as_slow_before_and_after_as_during_the_run_counts_none(self):
        # the lab's 6 Nov check: other checks' story jobs made /api/feed slow, and /api/version waited behind it
        count, note = job_checks.added_by_run(rows(40, slow=20, failed=8), rows(38, slow=19, failed=8), rows(40, slow=20, failed=8))
        self.assertEqual(count, 0)
        self.assertAlmostEqual(note["baseline_rate"], 0.7)

    def test_a_run_that_slows_a_loaded_api_further_counts_what_it_adds(self):
        # 10% slow without the run, all 30 slow with it: 27 more than the machine's own rate
        count, note = job_checks.added_by_run(rows(40, slow=4), rows(30, slow=30), rows(40, slow=4))
        self.assertEqual(count, 27)
        self.assertEqual(note["expected"], 3)

    def test_the_expected_number_is_rounded_to_whole_requests(self):
        count, _ = job_checks.added_by_run(rows(40, slow=1), rows(30, slow=1), rows(40))   # 1/80 of 30 = 0.4: none expected
        self.assertEqual(count, 1)

    def test_no_baseline_is_a_quiet_machine(self):
        count, note = job_checks.added_by_run([], rows(10, slow=2), [])
        self.assertEqual((count, note["expected"]), (2, 0))


class AQuietMachineFirst(unittest.TestCase):
    """A window with most requests slow and no run says nothing of a run (lab, 6 Nov, two checks at once: 37 of 40
    slow before, 40 of 40 after): the run waits for a quiet window, and with none the invariant is not measured,
    which the report fails, never passes."""

    def test_a_window_is_quiet_when_at_most_one_in_ten_is_slow(self):
        self.assertTrue(job_checks.quiet(rows(40, slow=4)))
        self.assertFalse(job_checks.quiet(rows(40, slow=5)))
        self.assertFalse(job_checks.quiet(rows(40, failed=37)))
        self.assertFalse(job_checks.quiet([]))   # no answer at all is no quiet machine

    def test_not_measured_for_load_fails_the_report(self):
        with tempfile.TemporaryDirectory() as work:
            for side, count, note in (("base", 0, ""), ("head", -1, job_checks.LOADED_NOTE + " (37 of 40 slow)")):
                os.makedirs(os.path.join(work, side))
                with open(os.path.join(work, side, "jobs.json"), "w") as fh:
                    json.dump({"found": [{"name": "markx.api_during_run", "what": "slow", "count": count, "of": 0,
                                          "examples": [], "note": note}]}, fh)
            _, problems = report.build(work)
        self.assertTrue(any("markx.api_during_run" in p and "not measured" in p for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
