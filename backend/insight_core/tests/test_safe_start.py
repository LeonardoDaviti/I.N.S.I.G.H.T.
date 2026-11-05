"""A start that doesn't fail for something non-fatal, and a /health that reads (issue 0071)."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import psycopg

import main
from insight_core.services import registry as services_registry
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, requires_db

DOCKER = Path(__file__).resolve().parents[2] / "docker"


def run_start(script: str, *, sync_exit: int = 0, env: dict | None = None) -> tuple[subprocess.CompletedProcess, str]:
    """Run a start script with `python` and `uvicorn` stubbed: each call is one line in the log."""
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "calls"
        for name, code in (("python", f'case "$*" in *sync_sources_json*) exit {sync_exit};; esac'), ("uvicorn", "")):
            stub = Path(tmp) / name
            stub.write_text(f'#!/usr/bin/env bash\necho "{name} $*" >> "{log}"\n{code}\n')
            stub.chmod(0o755)
        result = subprocess.run(["bash", str(DOCKER / script)], capture_output=True, text=True, timeout=30,
                                env={**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}", **(env or {})})
        return result, log.read_text() if log.exists() else ""


class StartScriptTests(unittest.TestCase):
    def test_a_sources_json_that_fails_to_import_never_stops_the_start(self):
        for script, last in (("start-backend.sh", "uvicorn main:app"), ("start-ingestion.sh", "run_scheduler.py")):
            with self.subTest(script=script):
                result, calls = run_start(script, sync_exit=1)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("json-to-db --once", calls)
                self.assertIn(last, calls.splitlines()[-1])
                self.assertIn("starting anyway", result.stderr)


class TwoProcessesTests(unittest.TestCase):
    """0112 Decided 11: two API processes by default, under the supervisor that does the start's work once."""

    def test_the_api_starts_two_processes_under_the_supervisor(self):
        result, calls = run_start("start-backend.sh", env={"WEB_CONCURRENCY": "4"})
        self.assertEqual(result.returncode, 0, result.stderr)
        last = calls.splitlines()[-1]
        self.assertIn("-m insight_core.scripts.api_supervisor uvicorn main:app", last)
        self.assertTrue(last.endswith("--workers 2"), calls)

    def test_api_workers_sets_the_number(self):
        result, calls = run_start("start-backend.sh", env={"API_WORKERS": "1", "WEB_CONCURRENCY": "4"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(calls.splitlines()[-1].endswith("--workers 1"), calls)

    def test_a_number_that_isnt_one_is_refused_before_anything_runs(self):
        for bad in ("0", "two", "-1"):
            with self.subTest(bad=bad):
                result, calls = run_start("start-backend.sh", env={"API_WORKERS": bad})
                self.assertEqual(result.returncode, 1)
                self.assertIn("refused", result.stderr)
                self.assertEqual(calls, "", "nothing runs: no migration, no import, no server")


class PendingMigrationsTests(unittest.TestCase):
    @requires_db
    def test_update_lists_only_the_migrations_the_database_has_not_run(self):
        from insight_core.db import migrate
        with tempfile.TemporaryDirectory() as tmp, psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            ran = sorted(migrate.applied_versions(cur))[0]
            for name in (ran, "9999_later.sql"):
                (Path(tmp) / name).write_text("-- a migration\n")
            self.assertEqual([p.name for p in migrate.pending_migrations(cur, Path(tmp))], ["9999_later.sql"])


class HealthTests(unittest.TestCase):
    @requires_db
    def test_health_reads_the_database(self):
        previous = services_registry.use(SimpleNamespace(db_url=db_url()))
        self.addCleanup(services_registry.use, previous)
        status, _, body = call(main.app, "GET", "/health")
        self.assertEqual((status, body["status"], body["database"]), (200, "healthy", True))

    def test_health_is_503_when_the_database_does_not_answer(self):
        previous = services_registry.use(SimpleNamespace(db_url="postgresql://unused@localhost/none"))
        self.addCleanup(services_registry.use, previous)
        with mock.patch.object(main.database, "connection", side_effect=psycopg.OperationalError("down")):
            status, _, body = call(main.app, "GET", "/health")
        self.assertEqual((status, body["status"], body["database"]), (503, "unhealthy", False))


if __name__ == "__main__":
    unittest.main()
