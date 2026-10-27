"""The ingestion runner over its real DB ports (spec §A.2, B4 acceptance).

The fetch itself is a FakeKind (no network); the catalog, fetch state store, save batch and
run lock are the real Postgres adapters. Scratch-source pattern: commits, so every class is
@requires_test_db.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.ingestion.kinds import KindRegistry
from insight_core.ingestion.ports import (
    RUN_LOCK_KEY,
    DbFetchStateStore,
    DbPostSaver,
    DbSourceCatalog,
    JobProgressSink,
    PgAdvisoryRunLock,
)
from insight_core.ingestion.runner import IngestionRunner
from insight_core.ingestion.schedule import Availability
from insight_core.ingestion.types import FetchRequest, SourceSelector, Trigger
from insight_core.services.operations_service import OperationsService
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db
from insight_core.tests._ingestion_fakes import RecordingInspectionRefresher, SpyFetchGates
from insight_core.tests._kind_fakes import FakeKind


@requires_test_db
class IngestionRunnerDbTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.url = db_url()
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur, settings_json='{"display_name": "Scratch feed"}')
            cur.execute("SELECT handle_or_url FROM sources WHERE id = %s", (self.source_id,))
            self.handle = cur.fetchone()[0]
            conn.commit()

    def tearDown(self):
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _runner(self, kind):
        return IngestionRunner(
            catalog=DbSourceCatalog(self.url),
            state=DbFetchStateStore(self.url),
            saver=DbPostSaver(self.url),
            inspections=RecordingInspectionRefresher(),
            registry=KindRegistry([kind]),
            gates=SpyFetchGates(),
            run_lock=PgAdvisoryRunLock(self.url),
            availability=lambda: Availability(ytdlp_enabled=True, telegram_credentials=False),
            clock=lambda: datetime.now(timezone.utc),
            rand=lambda: 1.0,
        )

    async def test_forced_fetch_now_saves_posts_and_records_a_manual_outcome(self):
        kind = FakeKind("fake_rss", behaviour=lambda s, n: [
            {"url": f"{s['handle_or_url']}/post/{i}", "title": f"t{i}", "content": "c", "date": None}
            for i in range(3)
        ])
        # The scratch source is disabled: fetch-now reaches it anyway.
        request = FetchRequest(SourceSelector.source(self.source_id), Trigger.MANUAL, force=True)
        report = await self._runner(kind).run(request)

        self.assertEqual(report.status, "success")
        self.assertEqual(report.decisions, {"fetch_forced": 1})
        self.assertEqual(report.posts_inserted, 3)
        self.assertEqual(report.inserted_by_source[0].display_name, "Scratch feed")
        with psycopg.connect(self.url) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT last_trigger, last_outcome, last_fetched_posts, last_decision_kind "
                "FROM source_fetch_state WHERE source_id = %s",
                (self.source_id,),
            )
            self.assertEqual(cur.fetchone(), ("manual", "healthy", 3, "fetch_forced"))
            cur.execute("SELECT count(*) FROM posts WHERE source_id = %s", (self.source_id,))
            self.assertEqual(cur.fetchone()[0], 3)

    async def test_a_running_job_lists_its_sources_done_and_new_posts(self):
        kind = FakeKind("fake_rss", behaviour=lambda s, n: [
            {"url": f"{s['handle_or_url']}/post/{i}", "title": f"t{i}", "content": "c", "date": None}
            for i in range(2)
        ])
        ops = OperationsService(self.url)
        job_id = ops.start_job("ingestion_run", trigger="manual", source_id=self.source_id)
        try:
            request = FetchRequest(SourceSelector.source(self.source_id), Trigger.MANUAL, force=True)
            await self._runner(kind).run(request, progress=JobProgressSink(ops, job_id))
            job = next(j for j in ops.list_recent_jobs(200) if j["id"] == job_id)
            self.assertEqual(job["payload"]["sources"], {"done": 1, "total": 1})
            self.assertEqual(job["payload"]["new_posts"], 2)
            messages = [e["message"] for e in ops.get_job(job_id)["payload"]["events"]]
            self.assertTrue(any(m.endswith(": 2 new of 2 · 1 of 1 source") for m in messages), messages)
        finally:
            with psycopg.connect(self.url) as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM job_runs WHERE id = %s", (job_id,))
                conn.commit()

    def test_a_discarded_job_is_gone(self):
        ops = OperationsService(self.url)
        job_id = ops.start_job("ingestion_run", trigger="scheduler")
        ops.discard_job(job_id)
        self.assertIsNone(ops.get_job(job_id))

    def test_retired_analysis_jobs_leave_the_job_list(self):
        # Issue 0027: rows of retired job types (analysis, kept by 0027_drop_analysis) are not
        # what ingestion did; the list and the overview show only the jobs INSIGHT still runs.
        ops = OperationsService(self.url)
        retired = ops.start_job("analyst_inbox_rebuild", trigger="scheduler")
        live = ops.start_job("ingestion_run", trigger="scheduler")
        try:
            ids = [j["id"] for j in ops.list_recent_jobs(200)]
            self.assertIn(live, ids)
            self.assertNotIn(retired, ids)
        finally:
            ops.discard_job(retired)
            ops.discard_job(live)

    async def test_a_held_run_lock_skips_a_full_run(self):
        kind = FakeKind("fake_rss")
        with psycopg.connect(self.url, autocommit=True) as holder, holder.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(hashtext(%s))", (RUN_LOCK_KEY,))
            try:
                report = await self._runner(kind).run(FetchRequest(SourceSelector.all(), Trigger.SCHEDULER))
            finally:
                cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (RUN_LOCK_KEY,))
        self.assertEqual(report.status, "skipped_busy")
        self.assertEqual(kind.fetch_calls, [])

    def test_catalog_selectors(self):
        catalog = DbSourceCatalog(self.url)
        self.assertEqual([s["id"] for s in catalog.load(SourceSelector.source(self.source_id))], [self.source_id])
        source = catalog.load(SourceSelector.source(self.source_id))[0]
        self.assertEqual(source["handle_or_url"], self.handle)
        self.assertEqual(source["post_count"], 0)
        self.assertIn("max_posts_per_fetch", source["settings"], "settings come merged with defaults")
        self.assertNotIn(self.source_id, [s["id"] for s in catalog.load(SourceSelector.all())],
                         "all returns enabled sources only")
        self.assertEqual(catalog.load(SourceSelector.source("not-a-uuid")), [])


if __name__ == "__main__":
    unittest.main()
