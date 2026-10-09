"""Ingestion routes (spec §A.5, §5.8): FakeBridge, coroutines called directly, a real BackgroundTasks."""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from fastapi import BackgroundTasks

import main


class FakeBridge:
    def __init__(self, job_id: str | None = "job-1"):
        self.job_id = job_id
        self.jobs: list[tuple[str, dict]] = []
        self.awaited: list[tuple[str, tuple, dict]] = []
        self.archive_result: dict = {"success": True}

    def _start_job_safe(self, job_type, **kwargs):
        self.jobs.append((job_type, kwargs))
        return self.job_id

    async def run_ingestion_cycle(self, force=False, *, job_id=None):
        self.awaited.append(("run_ingestion_cycle", (force,), {"job_id": job_id}))
        return {"status": "success"}

    async def fetch_source_now(self, source_id, limit=None, *, job_id=None):
        self.awaited.append(("fetch_source_now", (source_id, limit), {"job_id": job_id}))
        return {"status": "success"}

    async def ingest_folder_now(self, folder_id, limit=None, *, job_id=None):
        self.awaited.append(("ingest_folder_now", (folder_id, limit), {"job_id": job_id}))
        return {"status": "success"}

    async def run_archive(self, source_id, desired_posts=None, **kwargs):
        return self.archive_result

    async def get_archive_plan(self, source_id, desired_posts=None, **kwargs):
        return self.archive_result


def run(coro):
    return asyncio.run(coro)


def body(response) -> dict:
    return json.loads(response.body)


class IngestionRouteTests(unittest.TestCase):
    def setUp(self):
        self.original_bridge = main.api_bridge
        self.bridge = FakeBridge()
        main.api_bridge = self.bridge

    def tearDown(self):
        main.api_bridge = self.original_bridge

    def _drain(self, tasks: BackgroundTasks) -> None:
        run(tasks())

    def test_run_cycle_starts_an_ingestion_job_and_returns_202(self):
        tasks = BackgroundTasks()
        response = run(main.run_ingestion_cycle(tasks, main.IngestionRunRequest(force=True)))
        self.assertEqual(response.status_code, 202)
        self.assertEqual(body(response)["job_id"], "job-1")
        self.assertEqual(body(response)["job_type"], "ingestion_run")
        job_type, job = self.bridge.jobs[0]
        self.assertEqual(job_type, "ingestion_run")
        self.assertEqual(job["payload"]["selector"], {"kind": "all"})
        self.assertTrue(job["payload"]["force"])
        self.assertEqual(len(tasks.tasks), 1)
        self.assertEqual(self.bridge.awaited, [], "the run happens in the background, not in the request")
        self._drain(tasks)
        self.assertEqual(self.bridge.awaited, [("run_ingestion_cycle", (True,), {"job_id": "job-1"})])

    def test_run_cycle_body_is_optional(self):
        tasks = BackgroundTasks()
        response = run(main.run_ingestion_cycle(tasks, None))
        self.assertEqual(response.status_code, 202)
        self.assertFalse(self.bridge.jobs[0][1]["payload"]["force"])

    def test_fetch_now_uses_a_forced_source_selector(self):
        tasks = BackgroundTasks()
        response = run(main.fetch_source_now("s1", main.LiveFetchRequest(limit=7), tasks))
        self.assertEqual(response.status_code, 202)
        job_type, job = self.bridge.jobs[0]
        self.assertEqual(job["payload"]["selector"], {"kind": "source", "id": "s1"})
        self.assertTrue(job["payload"]["force"])
        self.assertEqual(job["source_id"], "s1")
        self._drain(tasks)
        self.assertEqual(self.bridge.awaited, [("fetch_source_now", ("s1", 7), {"job_id": "job-1"})])

    def test_folder_ingest_uses_a_forced_folder_selector(self):
        tasks = BackgroundTasks()
        response = run(main.ingest_folder("f1", tasks, {"limit": 5}))
        self.assertEqual(response.status_code, 202)
        job = self.bridge.jobs[0][1]
        self.assertEqual(job["payload"]["selector"], {"kind": "folder", "id": "f1"})
        self.assertTrue(job["payload"]["force"])
        self._drain(tasks)
        self.assertEqual(self.bridge.awaited, [("ingest_folder_now", ("f1", 5), {"job_id": "job-1"})])

    def test_job_tracking_failure_is_503_and_nothing_runs(self):
        self.bridge.job_id = None
        tasks = BackgroundTasks()
        response = run(main.run_ingestion_cycle(tasks, main.IngestionRunRequest()))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(body(response)["error"], "job tracking unavailable")
        self.assertEqual(len(tasks.tasks), 0)

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
        self.bridge.archive_result = {"success": False, "error": "yt-dlp disabled", "unavailable": True}
        response = run(main.run_archive("s1", main.ArchiveRequest()))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(body(response)["detail"], "yt-dlp disabled")
        response = run(main.plan_archive("s1", main.ArchiveRequest()))
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
