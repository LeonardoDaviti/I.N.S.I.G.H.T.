"""0216: process monitoring. Each process's own memory and CPU (utils/peak, the heartbeats), each job's runs counted
in mx_jobs (migration 0151), and GET /metrics in Prometheus' text format (services/metrics.py)."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.services import metrics
from insight_core.tests._db import clear_tables, db_url, requires_test_db
from insight_core.utils import heartbeat, peak

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
SAMPLE = re.compile(r'^([a-z_:][a-z0-9_:]*)(\{([a-z_]+="(?:[^"\\]|\\.)*"(,[a-z_]+="(?:[^"\\]|\\.)*")*)?\})? (\S+)$')


def parse(text):
    """{(name, frozenset(labels)): value}, checking every line is a comment, or a sample in the text format."""
    out = {}
    types = {}
    for line in text.splitlines():
        if line.startswith("# TYPE "):
            _, _, name, kind = line.split(" ")
            types[name] = kind
            continue
        if line.startswith("# HELP "):
            continue
        m = SAMPLE.match(line)
        assert m, f"not a sample: {line!r}"
        labels = frozenset(re.findall(r'([a-z_]+)="((?:[^"\\]|\\.)*)"', m.group(3) or ""))
        out[(m.group(1), labels)] = float(m.group(5))
        assert m.group(1) in types, f"{m.group(1)} has no # TYPE"
    return out, types


def value(samples, name, **labels):
    return samples.get((name, frozenset((k, str(v)) for k, v in labels.items())))


class TheTextFormat(unittest.TestCase):
    def test_families_samples_and_escaping(self):
        page = metrics.Page()
        page("insight_job_runs_total").add(3, job="decide", result="ok")
        page("insight_job_runs_total").add(1, job='say "hi"\\\n', result="failed")
        page("insight_metrics_seconds").add(0.0123)
        page("insight_job_last_ok").add(None, job="labels")          # no value: no sample
        page("insight_job_last_duration_seconds").add("n/a", job="x")  # not a number: no sample
        text = metrics.render(page)
        self.assertEqual(text.count("# TYPE insight_job_runs_total counter"), 1)
        self.assertIn('insight_job_runs_total{job="decide",result="ok"} 3\n', text)
        self.assertIn('insight_job_runs_total{job="say \\"hi\\"\\\\\\n",result="failed"} 1\n', text)
        self.assertIn("insight_metrics_seconds 0.0123\n", text)
        self.assertNotIn("insight_job_last_ok", text, "a family with no sample is not written")
        self.assertNotIn("insight_job_last_duration_seconds", text)
        samples, types = parse(text)
        self.assertEqual(types["insight_metrics_seconds"], "gauge")
        self.assertEqual(len(samples), 3)

    def test_every_family_has_a_type_and_a_help(self):
        for name, (kind, text) in metrics.FAMILIES.items():
            self.assertIn(kind, ("gauge", "counter"), name)
            self.assertTrue(text, name)
            self.assertEqual(kind == "counter", name.endswith("_total"), f"{name}: counters end in _total")

    def test_numbers(self):
        self.assertEqual([metrics._number(v) for v in (2.0, 1e20, 0.5, float("nan"), float("inf"))],
                         ["2", "1e+20", "0.5", "NaN", "+Inf"])


class AProcessesOwnNumbers(unittest.TestCase):
    @unittest.skipUnless(os.path.exists("/proc/self/status"), "Linux's /proc")
    def test_own_and_of_read_the_same_process(self):
        own, of = peak.own(), peak.of(os.getpid())
        self.assertGreater(own["rss_mb"], 1)
        self.assertGreaterEqual(own["hwm_mb"], own["rss_mb"] - 1)
        self.assertAlmostEqual(of["rss_mb"], own["rss_mb"], delta=20)
        t = os.times()   # `of`: the process's whole life; `own`: since the last reset (another test's)
        self.assertAlmostEqual(of["cpu_s"], t.user + t.system, delta=1.0)
        self.assertLessEqual(own["cpu_s"], of["cpu_s"] + 0.05)
        self.assertEqual(peak.of(2**22 + 12345), {"rss_mb": None, "hwm_mb": None, "cpu_s": None}, "a process gone")

    def test_cpu_counts_from_the_last_reset(self):
        peak.reset("/nonexistent/clear_refs")
        self.assertLess(peak.cpu_s(), 0.05)
        end = time.process_time() + 0.2
        while time.process_time() < end:
            pass
        self.assertGreaterEqual(peak.cpu_s(), 0.15)

    def test_without_proc(self):
        self.assertIsNone(peak.rss_mb("/nonexistent/status"))


class _Folder(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        patcher = mock.patch.dict(os.environ, {"INSIGHT_LOG_DIR": self.dir.name})
        patcher.start()
        self.addCleanup(patcher.stop)


class TheBeatsCarryTheNumbers(_Folder):
    def test_a_beat_with_numbers_is_still_a_beat(self):
        t = NOW.timestamp()
        heartbeat.beat("scheduler", now=t - 30, stats={"rss_mb": 812.5, "hwm_mb": 1366.9, "cpu_s": 4021.3})
        self.assertEqual(round(heartbeat.ages(t)["scheduler"]), 30)
        self.assertEqual(heartbeat.stale(t), [])
        heartbeat.beat("markx", now=t - 5)
        self.assertEqual(heartbeat.processes(t), {
            "scheduler": {"age": 30.0, "rss_mb": 812.5, "hwm_mb": 1366.9, "cpu_s": 4021.3},
            "markx": {"age": 5.0}})

    def test_an_old_api_beat_is_removed(self):
        t = NOW.timestamp()
        heartbeat.beat("api-41", now=t - 10, stats={"rss_mb": 140.0})
        heartbeat.beat("api-7", now=t - heartbeat.API_GONE - 1, stats={"rss_mb": 300.0})
        self.assertEqual(set(heartbeat.processes(t)), {"api-41"})
        self.assertFalse(os.path.exists(os.path.join(heartbeat.folder(), "heartbeat-api-7")))

    def test_the_supervisor_beats_for_each_api_process(self):
        from insight_core.scripts import api_supervisor
        self.assertEqual(api_supervisor.beat_api_processes([os.getpid(), 2**22 + 12345]), 1, "a gone pid is skipped")
        p = heartbeat.processes()[f"api-{os.getpid()}"]
        self.assertGreater(p["rss_mb"], 1)
        self.assertIn("cpu_s", p)

    def test_the_processes_on_the_page(self):
        page = metrics.Page()
        metrics.processes(page, {"scheduler": {"age": 12.0, "rss_mb": 800.0, "hwm_mb": 1400.0, "cpu_s": 99.5},
                                 "markx": {"age": 40.0},
                                 "api-41": {"age": 20.0, "rss_mb": 150.0, "hwm_mb": 220.0, "cpu_s": 7.0},
                                 "api-9": {"age": metrics.API_FRESH + 1, "rss_mb": 150.0}},
                          own=(55, {"rss_mb": 130.0, "hwm_mb": 131.0, "cpu_s": 1.5}))
        samples, types = parse(metrics.render(page))
        self.assertEqual(value(samples, "insight_process_resident_bytes", process="scheduler"), 800.0 * 2**20)
        self.assertEqual(value(samples, "insight_process_peak_resident_bytes", process="scheduler"), 1400.0 * 2**20)
        self.assertEqual(value(samples, "insight_process_cpu_seconds_total", process="api", pid=41), 7.0)
        self.assertEqual(value(samples, "insight_process_resident_bytes", process="api", pid=55), 130.0 * 2**20)
        self.assertIsNone(value(samples, "insight_process_resident_bytes", process="api", pid=9), "an ended process")
        self.assertEqual(value(samples, "insight_heartbeat_age_seconds", loop="markx"), 40.0)
        self.assertEqual(types["insight_process_cpu_seconds_total"], "counter")


@requires_test_db
class _Db(_Folder):
    def setUp(self):
        super().setUp()
        import psycopg
        self.conn = psycopg.connect(db_url(), autocommit=True)
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        clear_tables(self.cur, "mx_jobs, mx_kept_pages")


class RunsAreCounted(_Db):
    def row(self, job):
        self.cur.execute("SELECT runs_ok, runs_failed, ok_at, recent, last FROM mx_jobs WHERE job = %s", (job,))
        return self.cur.fetchone()

    def test_ok_failed_skipped_and_the_ring(self):
        from insight_core.markx import jobs
        j = jobs.Jobs(db_url())
        j._finish("labels", {"ok": True, "seconds": 2.5, "peak_mb": 210.0})
        j._finish("labels", {"ok": False, "error": "boom", "seconds": 1.0})
        j._finish("labels", {"ok": False, "skipped": "another run holds the lock"})   # neither
        n_ok, n_failed, ok_at, recent, last = self.row("labels")
        self.assertEqual((n_ok, n_failed), (1, 1))
        self.assertIsNotNone(ok_at)
        self.assertEqual([r.get("ok") for r in recent], [False, False, True], "newest first")
        self.assertEqual({k: recent[2][k] for k in ("seconds", "peak_mb")}, {"seconds": 2.5, "peak_mb": 210.0})
        self.assertNotIn("cpu_s", last, "measured only in a job's own process")
        for _ in range(jobs.RECENT + 5):
            j._finish("labels", {"ok": True, "seconds": 0.1})
        n_ok, n_failed, _, recent, _ = self.row("labels")
        self.assertEqual((n_ok, n_failed, len(recent)), (jobs.RECENT + 6, 1, jobs.RECENT))

    def test_a_job_process_records_its_own_peak_and_cpu(self):
        from insight_core.markx import jobs
        peak.reset("/nonexistent/clear_refs")
        jobs.Jobs(db_url(), measure=True)._finish("news", {"ok": True, "seconds": 0.2})
        _, _, _, recent, last = self.row("news")
        self.assertIsInstance(last["cpu_s"], float)
        self.assertGreater(last["peak_mb"], 1)
        self.assertEqual(recent[0]["cpu_s"], last["cpu_s"])

    def test_a_dead_run_is_a_failed_run(self):
        from insight_core.markx import jobs
        self.cur.execute("""INSERT INTO mx_jobs (job, started_at, stage, stage_at)
                            VALUES ('decide', now() - interval '2 hours', 'graph', now() - interval '2 hours')""")
        runner = jobs.Runner(db_url(), spawn=False)
        states = runner._states()
        runner._reap("decide", states["decide"])
        n_ok, n_failed, ok_at, recent, _ = self.row("decide")
        self.assertEqual((n_ok, n_failed, ok_at), (0, 1, None))
        self.assertEqual((recent[0]["ok"], recent[0]["stage"]), (False, "graph"))


class ThePage(_Db):
    def setUp(self):
        super().setUp()
        run_id = uuid.uuid4()
        self.cur.execute("""INSERT INTO mx_jobs (job, started_at, finished_at, last, failures, runs_ok, runs_failed, ok_at,
                                                 wanted_at)
                            VALUES ('decide', now() - interval '50 minutes', now() - interval '48 minutes',
                                    %s::jsonb, 0, 7, 2, now() - interval '48 minutes', now() - interval '20 minutes')""",
                         (json.dumps({"ok": True, "seconds": 95.5, "peak_mb": 640.0, "cpu_s": 80.25,
                                      "stages": [["candidates", 3.0], ["load", 20.5]]}),))
        self.cur.execute("""INSERT INTO mx_jobs (job, started_at, stage, stage_at, last, failures)
                            VALUES ('labels', now() - interval '30 seconds', 'building', now() - interval '10 seconds',
                                    %s::jsonb, 3)""", (json.dumps({"ok": False, "error": "boom"}),))
        self.cur.execute("""INSERT INTO mx_kept_pages (page, key, run_id, stamp, body, bytes, built_at)
                            VALUES ('news', 'all', %s, 's', '\\x00', 1000, now() - interval '5 minutes')""", (run_id,))
        started = datetime.now(timezone.utc) + timedelta(days=3650)   # the newest run, whatever else the table holds
        self.cur.execute("""INSERT INTO job_runs (job_type, status, trigger, payload, started_at, finished_at)
                            VALUES ('ingestion_run', 'partial', 'scheduler', %s::jsonb, %s, %s) RETURNING id""",
                         (json.dumps({"duration_s": 212.4, "posts_fetched": 950, "posts_inserted": 61}), started,
                          started + timedelta(minutes=4)))
        job_id = self.cur.fetchone()[0]
        self.addCleanup(self.cur.execute, "DELETE FROM job_runs WHERE id = %s", (job_id,))

    def test_the_values(self):
        heartbeat.beat("scheduler", stats={"rss_mb": 900.0, "hwm_mb": 1400.0, "cpu_s": 10.0})
        t0 = time.monotonic()
        text = metrics.exposition(db_url(), own=(123, {"rss_mb": 140.0, "hwm_mb": 150.0, "cpu_s": 2.0}))
        elapsed = time.monotonic() - t0
        samples, types = parse(text)
        self.assertIsNone(value(samples, "insight_metrics_part_errors", part="jobs"), text)
        self.assertEqual(value(samples, "insight_process_resident_bytes", process="scheduler"), 900.0 * 2**20)
        self.assertEqual(value(samples, "insight_process_resident_bytes", process="api", pid=123), 140.0 * 2**20)
        self.assertEqual(value(samples, "insight_job_runs_total", insight_job="decide", result="ok"), 7)
        self.assertEqual(value(samples, "insight_job_runs_total", insight_job="decide", result="failed"), 2)
        self.assertEqual(value(samples, "insight_job_last_duration_seconds", insight_job="decide"), 95.5)
        self.assertEqual(value(samples, "insight_job_last_peak_resident_bytes", insight_job="decide"), 640.0 * 2**20)
        self.assertEqual(value(samples, "insight_job_last_cpu_seconds", insight_job="decide"), 80.25)
        self.assertAlmostEqual(value(samples, "insight_job_since_success_seconds", insight_job="decide"), 48 * 60, delta=30)
        self.assertAlmostEqual(value(samples, "insight_job_wanted_seconds", insight_job="decide"), 20 * 60, delta=30)
        self.assertEqual(value(samples, "insight_job_running", insight_job="decide"), 0)
        self.assertEqual(value(samples, "insight_decision_last_stage_seconds", stage="load"), 20.5)
        self.assertEqual(value(samples, "insight_job_running", insight_job="labels"), 1)
        self.assertEqual(value(samples, "insight_job_current_stage", insight_job="labels", stage="building"), 1)
        self.assertAlmostEqual(value(samples, "insight_job_stage_seconds", insight_job="labels"), 10, delta=30)
        self.assertEqual(value(samples, "insight_job_failures_in_a_row", insight_job="labels"), 3)
        self.assertEqual(value(samples, "insight_job_last_ok", insight_job="labels"), 0)
        self.assertIsNone(value(samples, "insight_job_since_success_seconds", insight_job="labels"), "never ended well")
        self.assertEqual(value(samples, "insight_decision_held"), 0)
        self.assertIn(value(samples, "insight_rebuild_in_progress"), (0, 0.5, 1))
        self.assertEqual(value(samples, "insight_kept_page_bytes", page="news"), 1000)
        self.assertAlmostEqual(value(samples, "insight_kept_page_age_seconds", page="news"), 300, delta=30)
        self.assertEqual(value(samples, "insight_ingestion_last_run_seconds"), 212.4)
        self.assertEqual(value(samples, "insight_ingestion_last_posts_fetched"), 950)
        self.assertEqual(value(samples, "insight_ingestion_last_posts_inserted"), 61)
        self.assertEqual(value(samples, "insight_ingestion_last_run_ok"), 0.5)
        self.assertIn(value(samples, "insight_db_statements_enabled"), (0, 1))
        self.assertIsNotNone(value(samples, "insight_worker_calls_total"))
        self.assertEqual(types["insight_job_runs_total"], "counter")
        self.assertFalse([k for k in samples if k[0] == "insight_metrics_part_errors"], text)
        self.assertLess(elapsed, 5.0, "a cheap read (measured on a real-data copy: DEPLOYMENT.md)")

    def test_a_part_that_fails_is_left_out_and_counted(self):
        def broken(page, cur, now):
            cur.execute("SELECT * FROM no_such_table_0216")
        with mock.patch.object(metrics, "PARTS", (("kept_pages", broken),) + tuple(
                p for p in metrics.PARTS if p[0] != "kept_pages")):
            samples, _ = parse(metrics.exposition(db_url(), procs={}))
        self.assertEqual(value(samples, "insight_metrics_part_errors", part="kept_pages"), 1)
        self.assertEqual(value(samples, "insight_job_runs_total", insight_job="decide", result="ok"), 7, "the rest is read")

    def test_the_route(self):
        import main
        from insight_core.tests._asgi import call
        with mock.patch.dict("os.environ", {"DATABASE_URL": db_url()}):
            status, headers, body = call(main.app, "GET", "/metrics")
        self.assertEqual(status, 200, body)
        self.assertTrue(headers["content-type"].startswith("text/plain; version=0.0.4"))
        samples, _ = parse(body.decode())
        self.assertGreater(value(samples, "insight_process_resident_bytes", process="api", pid=os.getpid()), 0)


if __name__ == "__main__":
    unittest.main()
