"""The real-data check's markx.api_during_run (0112 Decided 13): the API is measured while Mark X decides, and a
request over 1 s fails the merge. What counts is what the run adds: the same probes before and after the run are the
machine's own slowness (other checks share the database), and only the slow requests over that rate count."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from insight_core.checks import job_checks, report


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
