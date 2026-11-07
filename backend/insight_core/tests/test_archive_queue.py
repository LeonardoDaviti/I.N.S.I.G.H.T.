"""Issue 0130: the archive queue (one Telegram, one Nitter archive at a time; Resume interrupted archives) and the
normalised-address repair (E1) with its invariant. Commits rows: a _test database only."""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg  # noqa: E402

from insight_core.checks.invariants import _address_unnormalized  # noqa: E402
from insight_core.scripts import repair_normalized_urls as repair  # noqa: E402
from insight_core.services.archive_jobs import ArchiveJobs, ArchiveQueue, exclusive, lane_of  # noqa: E402
from insight_core.services.operations_service import OperationsService  # noqa: E402
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db  # noqa: E402


class LaneTests(unittest.TestCase):
    def test_every_telegram_kind_shares_one_lane_and_nitter_its_own(self):
        self.assertEqual(lane_of("telegram_mtproto", "platform:telegram"), lane_of("telegram_rss", "tg.example"))
        self.assertEqual(lane_of("nitter_rss", "bridge.example"), "nitter")
        self.assertEqual(lane_of("generic_rss", "blog.example"), "host:blog.example")
        self.assertTrue(exclusive("telegram") and exclusive("nitter"))
        self.assertFalse(exclusive("host:blog.example"))


@requires_test_db
class ArchiveQueueTests(unittest.TestCase):
    def setUp(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            cur.execute("DELETE FROM job_runs WHERE job_type = 'archive_source'")
            self.sources = [insert_scratch_source(cur) for _ in range(4)]
            conn.commit()
        self.queue = ArchiveQueue(db_url())
        self.ops = OperationsService(db_url())

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM job_runs WHERE job_type = 'archive_source'")
            delete_scratch_sources(cur)
            conn.commit()

    def status(self, job_id):
        return self.ops.get_job(job_id)["status"]

    def test_a_telegram_archive_by_hand_while_another_runs_is_queued(self):
        a, b = self.sources[:2]
        first, status = self.queue.add(a, lane="telegram", payload={"resume": True}, queue=False)
        self.assertEqual(status, "running")
        second, status = self.queue.add(b, lane="telegram", payload={"resume": True, "until": "2025-11-01"}, queue=False)
        self.assertEqual((status, self.status(second)), ("queued", "queued"))
        self.assertEqual(self.queue.add(b, lane="telegram", payload={}, queue=False), (None, "queued"),
                         "a source never has two")
        self.assertEqual(self.queue.claim(trigger="scheduler"), [], "its lane is busy")
        self.ops.finish_job(first, status="success")
        claimed = self.queue.claim(trigger="scheduler")
        self.assertEqual([(c["id"], c["payload"]["until"]) for c in claimed], [(second, "2025-11-01")])
        self.assertEqual(self.status(second), "running")

    def test_the_queue_runs_one_per_lane_and_at_most_three_at_once(self):
        lanes = ["telegram", "telegram", "nitter", "host:a.example"]
        jobs = [self.queue.add(s, lane=lane, payload={})[0] for s, lane in zip(self.sources, lanes)]
        claimed = [c["id"] for c in self.queue.claim(trigger="scheduler", parallel=3)]
        self.assertEqual(claimed, [jobs[0], jobs[2], jobs[3]], "the second Telegram archive waits for the first")
        self.assertEqual(self.queue.claim(trigger="scheduler", parallel=3), [])

    def test_a_waiting_archive_holds_its_lane(self):
        a, b = self.sources[:2]
        first, _ = self.queue.add(a, lane="nitter", payload={}, queue=False)
        self.ops.wait_job(first, message="Waiting", payload={"waiting_until": "2026-11-07T20:00:00+00:00", "waits": 1})
        self.queue.add(b, lane="nitter", payload={})
        self.assertEqual(self.queue.claim(trigger="scheduler"), [])

    def test_a_restart_queues_again_what_the_scheduler_ran_from_the_queue(self):
        job, _ = self.queue.add(self.sources[0], lane="telegram", payload={"resume": False})
        self.queue.claim(trigger="scheduler")
        self.assertEqual(self.queue.requeue("scheduler"), 1)
        job_row = self.ops.get_job(job)
        self.assertEqual((job_row["status"], job_row["payload"]["resume"]), ("queued", True))

    def test_resume_interrupted_queues_each_interrupted_archive_once_with_its_horizon(self):
        a, b, c = self.sources[:3]
        for source, until in ((a, "2025-11-01"), (b, None)):
            job = self.ops.start_job("archive_source", source_id=source,
                                     payload={"resume": True, **({"until": until} if until else {})})
        self.ops.start_job("archive_source", source_id=c, payload={"linked": True})
        self.ops.close_interrupted_jobs("manual")
        archives = SimpleNamespace()   # no kinds: every source its own lane
        jobs = ArchiveJobs(self.ops, archives, trigger="manual")
        queued = jobs.resume_interrupted()
        self.assertEqual(sorted(row["source_id"] for row in queued), sorted([a, b]), "not a linked fetch")
        by_source = {row["source_id"]: self.ops.get_job(row["job_id"]) for row in queued}
        self.assertEqual(by_source[a]["payload"]["until"], "2025-11-01")
        self.assertEqual({row["status"] for row in queued}, {"queued"})
        self.assertEqual(jobs.resume_interrupted(), [], "queued now: nothing interrupted is last")
        del job

    def test_the_scheduler_runs_a_queued_archive_with_its_request(self):
        calls = []

        class Archives:
            async def archive_source(self, source_id, **kwargs):
                calls.append((source_id, kwargs))
                return {"success": True, "posts_fetched": 2, "message": "Archive completed with 2 posts"}

        jobs = ArchiveJobs(self.ops, Archives(), trigger="scheduler")
        job, _ = jobs.queue.add(self.sources[0], lane="telegram", payload={"resume": True, "until": "2025-11-01"})

        async def go():
            started = await jobs.start_queued()
            await jobs.idle()
            return started
        self.assertEqual(asyncio.run(go()), [job])
        self.assertEqual(calls[0][1]["until"], "2025-11-01")
        self.assertEqual(self.status(job), "success")


@requires_test_db
class NormalizedAddressRepairTests(unittest.TestCase):
    def setUp(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source = insert_scratch_source(cur)
            rows = [("https://Blog.Example/post/1/?utm_source=x", None), ("https://blog.example/post/2", "kept"),
                    ("not an address", None)]
            self.ids = []
            for url, normalized in rows:
                cur.execute("INSERT INTO posts (source_id, url, normalized_url) VALUES (%s, %s, %s) RETURNING id::text",
                            (self.source, url, normalized))
                self.ids.append(cur.fetchone()[0])
            conn.commit()

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def rows(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT id::text, normalized_url, canonical_url, url_host FROM posts WHERE id = ANY(%s::uuid[])",
                        (self.ids,))
            return {row[0]: row[1:] for row in cur.fetchall()}

    def invariant(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            ids, _of = _address_unnormalized(SimpleNamespace(cur=cur))
        return [i for i in ids if i in self.ids]

    def test_it_fills_by_todays_rule_only_where_empty_and_the_invariant_then_passes(self):
        self.assertEqual(self.invariant(), [self.ids[0]])
        result = repair.repair(db_url(), batch=1)
        self.assertGreaterEqual(result["filled"], 1)
        rows = self.rows()
        from insight_core.utils.url_normalization import canonicalize_url, extract_url_host, normalize_url
        url = "https://Blog.Example/post/1/?utm_source=x"
        self.assertEqual(rows[self.ids[0]], (normalize_url(url), canonicalize_url(url), extract_url_host(url)))
        self.assertEqual(rows[self.ids[1]][0], "kept", "a filled address is never changed")
        self.assertIsNone(rows[self.ids[2]][0], "no http(s) address: left as it is")
        self.assertEqual(self.invariant(), [])
        again = repair.repair(db_url())
        self.assertEqual(again["filled"], 0, "a second run (the next start) changes nothing")

    def test_a_dry_run_writes_nothing(self):
        self.assertGreaterEqual(repair.repair(db_url(), dry_run=True)["posts"], 1)
        self.assertIsNone(self.rows()[self.ids[0]][0])


if __name__ == "__main__":
    unittest.main()
