"""GET /api/version (issue 0020): the build the image was stamped with, over ASGI."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main
from insight_core.tests._asgi import call


class VersionRouteTests(unittest.TestCase):
    def test_a_stamped_build_reports_its_version_commit_and_date(self):
        stamp = {"INSIGHT_VERSION": "Mark IX v9.1", "INSIGHT_COMMIT": "b9fcc6e", "INSIGHT_COMMIT_DATE": "2026-10-27"}
        with mock.patch.dict(os.environ, stamp):
            status, _, body = call(main.app, "GET", "/api/version")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"version": "Mark IX v9.1", "commit": "b9fcc6e", "commit_date": "2026-10-27"})

    def test_an_unstamped_build_reports_nulls(self):
        unset = {"INSIGHT_VERSION": "", "INSIGHT_COMMIT": "", "INSIGHT_COMMIT_DATE": ""}
        with mock.patch.dict(os.environ, unset):
            status, _, body = call(main.app, "GET", "/api/version")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"version": None, "commit": None, "commit_date": None})


if __name__ == "__main__":
    unittest.main()
