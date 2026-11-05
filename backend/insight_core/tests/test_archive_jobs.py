"""Issue 0107: an archive job that waits for a host's limit, and the scheduler that continues it."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg  # noqa: E402

from insight_core.services.archive_jobs import ArchiveJobs  # noqa: E402
from insight_core.services.operations_service import OperationsService  # noqa: E402
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db  # noqa: E402

NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)
UNTIL = (NOW + timedelta(minutes=5)).isoformat()


class FakeOps:
    """job_runs in memory, with the calls ArchiveJobs makes."""

    def __init__(self):
        self.jobs: dict = {}

    def try_start_job(self, job_type, *, trigger="manual", source_id=None, message=None, payload=None):
        job_id = f"job-{len(self.jobs) + 1}"
        self.jobs[job_id] = {"id": job_id, "job_type": job_type, "status": "running", "trigger": trigger,
                             "source_id": source_id, "message": message, "payload": dict(payload or {}), "events": []}
        return job_id

    def try_append_job_event(self, job_id, *, message, level="info", progress=None, payload=None):
        self.jobs[job_id]["events"].append(message)

    def try_finish_job(self, job_id, *, status, message=None, payload=None, compact=False):
        self.jobs[job_id].update(status=status, message=message)
        self.jobs[job_id]["payload"].update(payload or {})

    def wait_job(self, job_id, *, message, payload):
        self.jobs[job_id].update(status="waiting", message=message)
        self.jobs[job_id]["payload"].update(payload)

    def due_waiting_jobs(self, job_type, now):
        return [{"id": j["id"], "source_id": j["source_id"]} for j in self.jobs.values()
                if j["job_type"] == job_type and j["status"] == "waiting"
                and datetime.fromisoformat(j["payload"]["waiting_until"]) <= now]

    def latest_job_for_source(self, job_type, source_id):
        jobs = [j for j in self.jobs.values() if j["job_type"] == job_type and j["source_id"] == source_id]
        return {"id": jobs[-1]["id"], "status": jobs[-1]["status"]} if jobs else None

    def claim_waiting_job(self, job_id, *, trigger):
        job = self.jobs.get(job_id)
        if not job or job["status"] != "waiting":
            return None
        job.update(status="running", trigger=trigger)
        return {"id": job_id, "source_id": job["source_id"], "payload": dict(job["payload"])}


class FakeArchives:
    """archive_source / continue_archive, each playing the next scripted leg result."""

    def __init__(self, *legs):
        self.legs = list(legs)
        self.calls: list = []

    async def archive_source(self, source_id, *, progress_callback=None, resume=True, rate_limit_overrides=None):
        self.calls.append(("archive", source_id))
        progress_callback({"message": "Fetched page 1"})
        return self.legs.pop(0)

    async def continue_archive(self, source_id, previous, progress_callback=None):
        self.calls.append(("continue", source_id, previous.get("waits")))
        return self.legs.pop(0)


WAITING = {"success": True, "waiting": True, "waiting_until": UNTIL, "waiting_host": "bridge.example", "waits": 1,
           "posts_fetched": 40, "message": "Waiting for bridge.example's limit"}
DONE = {"success": True, "posts_fetched": 90, "message": None}


class ArchiveJobsTests(unittest.IsolatedAsyncioTestCase):
    def jobs(self, *legs, trigger="manual"):
        self.ops, self.archives = FakeOps(), FakeArchives(*legs)
        self.clock = [NOW]
        return ArchiveJobs(self.ops, self.archives, trigger=trigger, clock=lambda: self.clock[0])

    async def test_a_limited_archive_job_waits_instead_of_finishing(self):
        jobs = self.jobs(WAITING)
        await jobs.run("s1")
        job = self.ops.jobs["job-1"]
        self.assertEqual(job["status"], "waiting")
        self.assertEqual(job["message"], "Waiting for bridge.example's limit")
        self.assertEqual(job["payload"]["waiting_until"], UNTIL)

    async def test_the_scheduler_continues_it_at_its_time_on_the_same_job(self):
        jobs = self.jobs(WAITING, DONE)
        await jobs.run("s1")
        scheduler = ArchiveJobs(self.ops, self.archives, trigger="scheduler", clock=lambda: self.clock[0])
        self.assertEqual(await scheduler.continue_due(), [], "not before its time")
        self.clock[0] = NOW + timedelta(minutes=5)
        self.assertEqual(await scheduler.continue_due(), ["job-1"])
        await scheduler.idle()
        job = self.ops.jobs["job-1"]
        self.assertEqual((job["status"], job["trigger"]), ("success", "scheduler"))
        self.assertEqual(job["message"], "Archived 90 posts")
        self.assertEqual(self.archives.calls, [("archive", "s1"), ("continue", "s1", 1)])

    async def test_a_job_already_continued_is_not_continued_twice(self):
        jobs = self.jobs(WAITING, DONE)
        await jobs.run("s1")
        self.clock[0] = NOW + timedelta(minutes=5)
        self.assertEqual(await jobs.continue_job("job-1"), DONE)
        self.assertIsNone(await jobs.continue_job("job-1"), "a job only one process claims")

    async def test_resume_by_hand_continues_a_waiting_job_now(self):
        jobs = self.jobs(WAITING, DONE)
        await jobs.run("s1")
        job_id = jobs.waiting_job_for("s1")
        self.assertEqual(job_id, "job-1")
        self.assertEqual(await jobs.continue_job(job_id), DONE)
        self.assertEqual(self.ops.jobs["job-1"]["status"], "success")

    async def test_a_continuation_that_fails_fails_the_job(self):
        jobs = self.jobs(WAITING)
        await jobs.run("s1")

        async def boom(source_id, previous, progress_callback=None):
            raise RuntimeError("boom")
        self.archives.continue_archive = boom
        self.clock[0] = NOW + timedelta(minutes=5)
        with self.assertRaises(RuntimeError):
            await jobs.continue_job("job-1")
        self.assertEqual(self.ops.jobs["job-1"]["status"], "failed")


@requires_test_db
class WaitingJobsStoreTests(unittest.TestCase):
    """The job_runs side: a waiting job is not finished, is due at its time, and is claimed once."""

    def setUp(self):
        self.ops = OperationsService(db_url())
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur)
            conn.commit()
        self.job_id = self.ops.start_job("archive_source", trigger="manual", source_id=self.source_id)

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM job_runs WHERE id = %s", (self.job_id,))
            delete_scratch_sources(cur)
            conn.commit()

    def test_a_waiting_job_is_due_at_its_time_and_claimed_once(self):
        self.ops.wait_job(self.job_id, message="Waiting for bridge.example's limit", payload=WAITING)
        job = self.ops.get_job(self.job_id)
        self.assertEqual((job["status"], job["finished_at"]), ("waiting", None))
        self.assertEqual(self.ops.latest_job_for_source("archive_source", self.source_id)["result"]["waiting_until"],
                         UNTIL)
        self.assertNotIn(self.job_id, [j["id"] for j in self.ops.due_waiting_jobs("archive_source", NOW)])
        due = self.ops.due_waiting_jobs("archive_source", NOW + timedelta(minutes=5))
        self.assertIn({"id": self.job_id, "source_id": self.source_id}, due)
        claimed = self.ops.claim_waiting_job(self.job_id, trigger="scheduler")
        self.assertEqual((claimed["source_id"], claimed["payload"]["waits"]), (self.source_id, 1))
        self.assertIsNone(self.ops.claim_waiting_job(self.job_id, trigger="manual"))
        self.assertEqual(self.ops.get_job(self.job_id)["status"], "running")

    def test_a_restart_leaves_a_waiting_job_waiting_and_requeues_the_one_it_was_continuing(self):
        self.ops.wait_job(self.job_id, message="Waiting", payload=WAITING)
        self.ops.close_interrupted_jobs("manual")
        self.assertEqual(self.ops.get_job(self.job_id)["status"], "waiting")
        self.ops.claim_waiting_job(self.job_id, trigger="scheduler")
        self.assertEqual(self.ops.requeue_interrupted_archives("scheduler", NOW), 1)
        job = self.ops.get_job(self.job_id)
        self.assertEqual((job["status"], job["payload"]["waiting_until"]), ("waiting", NOW.isoformat()))


if __name__ == "__main__":
    unittest.main()
