"""The real-data check's markx.api_during_run (0112 Decided 13): the API is measured while Mark X decides, and a
request over 1 s fails the merge."""
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


if __name__ == "__main__":
    unittest.main()
