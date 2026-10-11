"""Ingestion routes (spec §A.5, §5.8): coroutines called directly, a real BackgroundTasks.

Job tracking is the real OperationsService on the scratch database; the network is fake:
run_ingestion (main.run_ingestion) and the archive side of SourceFetchService.
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from fastapi import BackgroundTasks

import main
from insight_core.services import registry
from insight_core.services.operations_service import OperationsService
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db


class FakeReport:
    job_status = "success"

    def summary_line(self):
        return "1 due; 2 new posts"

    def to_payload(self):
        return {"status": "success", "posts_inserted": 2}


class FakeArchive:
    """The archive side of SourceFetchService: no network, a scripted answer."""

    def __init__(self):
        self.awaited: list[tuple[str, tuple, dict]] = []
        self.archive_result: dict = {"success": True, "posts_fetched": 3}
        self.support: dict = {"archivable": True, "unavailable": False, "reason": None}
        self.error: Exception | None = None

    def archive_support(self, source_id):
        return self.support

    async def archive_source(self, source_id, desired_posts=None, **kwargs):
        self.awaited.append(("archive_source", (source_id, desired_posts), kwargs))
        if self.error:
            raise self.error
        return self.archive_result

    async def plan_archive(self, source_id, desired_posts=None, **kwargs):
        if self.error:
            raise self.error
        return {"desired_posts": desired_posts}


class BrokenOperations(OperationsService):
    def start_job(self, *args, **kwargs):
        raise psycopg.OperationalError("connection refused")


def run(coro):
    return asyncio.run(coro)


def body(response) -> dict:
    return json.loads(response.body)


@requires_test_db
class IngestionRouteTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(db_url())
        with self.conn.cursor() as cur:
            cur.execute("SELECT now()")
            self.since = cur.fetchone()[0]   # job_runs rows from here on are this test's
            delete_scratch_sources(cur)
            self.s1 = insert_scratch_source(cur)
            self.s2 = insert_scratch_source(cur)
        self.conn.commit()
        self.ops = OperationsService(db_url())
        self.archive = FakeArchive()
        self.use_operations(self.ops)
        self.requests = []

        async def fake_run_ingestion(request, *, progress=None):
            self.requests.append(request)
            return FakeReport()

        patcher = mock.patch.object(main, "run_ingestion", fake_run_ingestion)
        patcher.start()
        self.addCleanup(patcher.stop)
        main._archiving_sources.clear()

    def use_operations(self, ops):
        previous = registry.use(SimpleNamespace(operations=ops, source_fetch=self.archive))
        self.addCleanup(registry.use, previous)

    def tearDown(self):
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM job_runs WHERE started_at >= %s", (self.since,))
            delete_scratch_sources(cur)
        self.conn.commit()
        self.conn.close()

    def job(self, job_id: str) -> dict:
        return self.ops.get_job(job_id)

    def _drain(self, tasks: BackgroundTasks) -> None:
        run(tasks())

    def test_run_cycle_starts_an_ingestion_job_and_returns_202(self):
        tasks = BackgroundTasks()
        response = run(main.run_ingestion_cycle(tasks, main.IngestionRunRequest(force=True)))
        self.assertEqual(response.status_code, 202)
        job_id = body(response)["job_id"]
        self.assertEqual(body(response)["job_type"], "ingestion_run")
        job = self.job(job_id)
        self.assertEqual((job["job_type"], job["status"]), ("ingestion_run", "running"))
        self.assertEqual(job["payload"]["selector"], {"kind": "all"})
        self.assertTrue(job["payload"]["force"])
        self.assertEqual(len(tasks.tasks), 1)
        self.assertEqual(self.requests, [], "the run happens in the background, not in the request")
        self._drain(tasks)
        self.assertEqual(self.requests[0].selector.as_dict(), {"kind": "all"})
        self.assertTrue(self.requests[0].force)
        job = self.job(job_id)
        self.assertEqual((job["status"], job["message"]), ("success", "1 due; 2 new posts"))

    def test_run_cycle_body_is_optional(self):
        tasks = BackgroundTasks()
        response = run(main.run_ingestion_cycle(tasks, None))
        self.assertEqual(response.status_code, 202)
        self.assertFalse(self.job(body(response)["job_id"])["payload"]["force"])

    def test_fetch_now_uses_a_forced_source_selector(self):
        tasks = BackgroundTasks()
        response = run(main.fetch_source_now(self.s1, main.LiveFetchRequest(limit=7), tasks))
        self.assertEqual(response.status_code, 202)
        job = self.job(body(response)["job_id"])
        self.assertEqual(job["payload"]["selector"], {"kind": "source", "id": self.s1})
        self.assertTrue(job["payload"]["force"])
        self.assertEqual(job["source_id"], self.s1)
        self._drain(tasks)
        self.assertEqual((self.requests[0].selector.as_dict(), self.requests[0].limit),
                         ({"kind": "source", "id": self.s1}, 7))

    def test_folder_ingest_uses_a_forced_folder_selector(self):
        tasks = BackgroundTasks()
        response = run(main.ingest_folder("f1", tasks, {"limit": 5}))
        self.assertEqual(response.status_code, 202)
        job = self.job(body(response)["job_id"])
        self.assertEqual(job["payload"]["selector"], {"kind": "folder", "id": "f1"})
        self.assertTrue(job["payload"]["force"])
        self._drain(tasks)
        self.assertEqual((self.requests[0].selector.as_dict(), self.requests[0].limit),
                         ({"kind": "folder", "id": "f1"}, 5))

    def test_job_tracking_failure_is_logged_503_and_nothing_runs(self):
        self.use_operations(BrokenOperations(db_url()))
        tasks = BackgroundTasks()
        with self.assertLogs("operations_service", "ERROR") as logged:
            response = run(main.run_ingestion_cycle(tasks, main.IngestionRunRequest()))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(body(response)["error"], "job tracking unavailable")
        self.assertEqual(len(tasks.tasks), 0)
        self.assertIn("Could not start a ingestion_run job", "\n".join(logged.output))

    def test_async_mode_is_gone_from_fetch_now(self):
        self.assertNotIn("asyncMode", main.LiveFetchRequest.model_fields)

    def test_legacy_ingest_routes_are_gone(self):
        self.assertFalse(hasattr(main, "ingest_posts"))
        self.assertFalse(hasattr(main, "safe_ingest_posts"))
        paths = [getattr(r, "path", None) for r in main.app.routes]
        self.assertNotIn("/api/ingest-posts", paths)
        self.assertNotIn("/api/safe-ingest-posts", paths)
        self.assertIn("/api/ingestion/run", paths)

    def test_archive_run_on_an_unavailable_kind_is_409(self):
        from insight_core.ingestion.kinds.base import KindUnavailable

        self.archive.error = KindUnavailable("yt-dlp disabled")
        response = run(main.run_archive(self.s1, main.ArchiveRequest(), BackgroundTasks()))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(body(response)["detail"], "yt-dlp disabled")
        response = run(main.plan_archive(self.s1, main.ArchiveRequest()))
        self.assertEqual(response.status_code, 409)

    def test_a_background_archive_starts_a_job_and_returns_202(self):
        tasks = BackgroundTasks()
        request = main.ArchiveRequest(desiredPosts=500, resume=False, background=True)
        response = run(main.run_archive(self.s1, request, tasks))
        self.assertEqual(response.status_code, 202)
        job_id = body(response)["job_id"]
        self.assertEqual(body(response)["job_type"], "archive_source")
        job = self.job(job_id)
        self.assertEqual(job["job_type"], "archive_source")
        self.assertEqual(job["source_id"], self.s1)
        self.assertEqual(job["payload"]["desired_posts"], 500)
        self.assertEqual(self.archive.awaited, [], "the archive runs in the background, not in the request")
        self._drain(tasks)
        self.assertEqual(len(self.archive.awaited), 1)
        name, args, kwargs = self.archive.awaited[0]
        self.assertEqual((name, args), ("archive_source", (self.s1, 500)))
        self.assertFalse(kwargs["resume"])
        job = self.job(job_id)
        self.assertEqual((job["status"], job["message"]), ("success", "Archived 3 posts"))

    def test_a_background_archive_on_a_source_that_cannot_archive_is_409_and_starts_nothing(self):
        self.archive.support = {"archivable": False, "unavailable": True, "reason": "yt-dlp disabled"}
        tasks = BackgroundTasks()
        response = run(main.run_archive(self.s1, main.ArchiveRequest(background=True), tasks))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(body(response)["error"], "yt-dlp disabled")
        self.assertIsNone(self.ops.latest_job_for_source("archive_source", self.s1))
        self.assertEqual(len(tasks.tasks), 0)

    def test_a_second_archive_of_the_same_source_is_409_while_the_first_runs(self):
        first, second = BackgroundTasks(), BackgroundTasks()
        self.assertEqual(run(main.run_archive(self.s1, main.ArchiveRequest(background=True), first)).status_code, 202)
        response = run(main.run_archive(self.s1, main.ArchiveRequest(background=True), second))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(body(response)["error"], "An archive of this source is already running")
        self.assertEqual(len(second.tasks), 0)
        other = BackgroundTasks()
        self.assertEqual(run(main.run_archive(self.s2, main.ArchiveRequest(background=True), other)).status_code, 202)
        self._drain(first)
        self._drain(other)
        again = BackgroundTasks()
        self.assertEqual(run(main.run_archive(self.s1, main.ArchiveRequest(background=True), again)).status_code, 202,
                         "the source is free once its archive finishes")

    def test_a_failed_archive_frees_its_source_and_fails_its_job(self):
        self.archive.error = RuntimeError("network down")
        tasks = BackgroundTasks()
        job_id = body(run(main.run_archive(self.s1, main.ArchiveRequest(background=True), tasks)))["job_id"]
        with self.assertLogs("main", "ERROR"):
            self._drain(tasks)
        self.assertEqual((self.job(job_id)["status"], self.job(job_id)["message"]), ("failed", "network down"))
        self.assertEqual(run(main.run_archive(self.s1, main.ArchiveRequest(background=True), BackgroundTasks())).status_code, 202)

    def test_a_background_archive_without_job_tracking_is_503(self):
        self.use_operations(BrokenOperations(db_url()))
        tasks = BackgroundTasks()
        with self.assertLogs("operations_service", "ERROR"):
            response = run(main.run_archive(self.s1, main.ArchiveRequest(background=True), tasks))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(len(tasks.tasks), 0)


if __name__ == "__main__":
    unittest.main()
