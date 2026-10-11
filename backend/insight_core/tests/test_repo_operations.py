"""SystemSettingsRepository and JobRunsRepository against the real database (rollback pattern).

One transaction per test, rolled back in tearDown, with scratch keys and job types, so this
is safe on any database.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_operations import JobRunsRepository, SystemSettingsRepository
from insight_core.tests._db import db_url, insert_scratch_source, requires_db

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


@requires_db
class OperationsRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.key = f"scratch_{uuid.uuid4().hex}"

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_system_settings_get_missing_is_none(self):
        self.assertIsNone(SystemSettingsRepository.get(self.cur, self.key))

    def test_system_settings_upsert_then_get(self):
        first = SystemSettingsRepository.upsert(self.cur, self.key, {"a": 1})
        self.assertIsNotNone(first)
        SystemSettingsRepository.upsert(self.cur, self.key, {"a": 2, "b": "x"})
        value, updated_at = SystemSettingsRepository.get(self.cur, self.key)
        self.assertEqual(value, {"a": 2, "b": "x"})
        self.assertIsNotNone(updated_at)

    def test_latest_success_finished_at(self):
        job_type = self.key
        self.assertIsNone(JobRunsRepository.latest_success_finished_at(self.cur, job_type))
        for status, finished in (("success", NOW - timedelta(hours=3)), ("success", NOW - timedelta(hours=1)),
                                 ("failed", NOW), ("running", None)):
            self.cur.execute(
                "INSERT INTO job_runs (job_type, status, trigger, finished_at) VALUES (%s, %s, 'test', %s)",
                (job_type, status, finished),
            )
        self.assertEqual(JobRunsRepository.latest_success_finished_at(self.cur, job_type), NOW - timedelta(hours=1))

    def test_latest_for_source_is_the_newest_job_of_that_type_for_that_source(self):
        source_id = insert_scratch_source(self.cur)
        other_id = insert_scratch_source(self.cur)
        self.assertIsNone(JobRunsRepository.latest_for_source(self.cur, "archive_source", source_id))
        rows = [
            (source_id, "archive_source", "failed", NOW - timedelta(hours=3), "boom", '{"progress": 10}'),
            (source_id, "archive_source", "running", NOW - timedelta(hours=1), "Archive", '{"progress": 42.5}'),
            (source_id, "ingestion_run", "success", NOW, "fetched", "{}"),
            (other_id, "archive_source", "success", NOW, "other", "{}"),
        ]
        for sid, job_type, status, started, message, payload in rows:
            self.cur.execute(
                "INSERT INTO job_runs (job_type, status, trigger, source_id, started_at, message, payload)"
                " VALUES (%s, %s, 'test', %s, %s, %s, %s::jsonb)",
                (job_type, status, sid, started, message, payload),
            )
        job = JobRunsRepository.latest_for_source(self.cur, "archive_source", source_id)
        self.assertEqual(job["status"], "running")
        self.assertEqual(job["message"], "Archive")
        self.assertEqual(job["progress"], 42.5)
        self.assertEqual(job["started_at"], (NOW - timedelta(hours=1)).isoformat())
        self.assertIsNone(job["finished_at"])
        self.assertIsInstance(job["id"], str)


if __name__ == "__main__":
    unittest.main()
