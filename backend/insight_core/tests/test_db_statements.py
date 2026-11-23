"""GET /api/operations/db-statements, the database's top statements (pg_stat_statements), read only (0215)."""
from __future__ import annotations

import sys
import unittest
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.services import operations_service as ops_module
from insight_core.services.operations_service import OperationsService
from insight_core.tests._db import db_url, requires_db

SINCE = datetime(2026, 11, 16, 9, tzinfo=timezone.utc)


INDEXES = [("mx_embeddings", "mx_embeddings_pkey", 812, 3 * 2 ** 20)]
MEMORY = ("1536MB", "4GB", "16MB", 970, 30, SINCE)
SEEN = [INDEXES, MEMORY]   # v10.22: the indexes and the buffer settings, read first


class FakeCursor:
    """Answers top_statements' reads in order."""

    def __init__(self, answers):
        self.answers, self.seen = list(answers), []

    def execute(self, sql, params=None):
        self.seen.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.answers.pop(0)

    def fetchall(self):
        return self.answers.pop(0)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def service(cur):
    svc = OperationsService.__new__(OperationsService)
    svc.db_url = "postgresql://unused"

    @contextmanager
    def connection(url):
        conn = mock.MagicMock()
        conn.cursor.return_value = cur
        yield conn
    return svc, mock.patch.object(ops_module.db, "connection", connection)


class TopStatements(unittest.TestCase):
    def test_the_top_statements_with_their_share(self):
        rows = [(11, "SELECT p.id FROM posts p\n   WHERE p.title LIKE ANY($1)", 120, 30000.0, 250.0, 9000, 5, 7, 0),
                (-12, "UPDATE mx_tasks SET answered_at = $1 WHERE id = $2", 4000, 10000.0, 2.5, 4000, 9, 0, 3)]
        cur = FakeCursor(SEEN + [(True, True), (50000.0, 9000), (SINCE,), rows])
        svc, patched = service(cur)
        with patched:
            out = svc.top_statements(limit=2)
        self.assertEqual((out["enabled"], out["total_ms"], out["calls"], out["since"]),
                         (True, 50000.0, 9000, SINCE.isoformat()))
        first, second = out["statements"]
        self.assertEqual(first, {"id": "11", "statement": "SELECT p.id FROM posts p WHERE p.title LIKE ANY($1)",
                                 "calls": 120, "total_ms": 30000.0, "mean_ms": 250.0, "rows": 9000, "blocks_hit": 5,
                                 "blocks_read": 7, "temp_blocks_written": 0, "share": 0.6})
        self.assertEqual((second["id"], second["share"]), ("-12", 0.2))
        self.assertEqual(cur.seen[-1][1], (OperationsService.STATEMENT_CHARS, 2))
        self.assertIn("ORDER BY total_exec_time DESC", cur.seen[-1][0])
        self.assertIn("current_database()", cur.seen[-1][0], "this database's statements only")

    def test_off_says_why(self):
        for answer, why in (((False, False), "not loaded"), ((True, False), "not loaded"), ((False, True), "0146")):
            svc, patched = service(FakeCursor(SEEN + [answer]))
            with patched:
                out = svc.top_statements()
            self.assertEqual((out["enabled"], out["statements"]), (False, []))
            self.assertIn(why, out["reason"])
            self.assertEqual(out["indexes"][0]["index"], "mx_embeddings_pkey", "the indexes either way")

    def test_each_index_with_its_scans_and_the_buffer_settings(self):
        """Whether an index earns its keep and the server's buffers, by a GET."""
        cur = FakeCursor(SEEN + [(False, False)])
        svc, patched = service(cur)
        with patched:
            out = svc.top_statements()
        self.assertEqual(out["indexes"], [{"table": "mx_embeddings", "index": "mx_embeddings_pkey", "scans": 812, "mb": 3.0}])
        self.assertEqual(out["memory"], {"shared_buffers": "1536MB", "effective_cache_size": "4GB", "work_mem": "16MB",
                                         "hit_ratio": 0.97, "blocks_hit": 970, "blocks_read": 30,
                                         "since": SINCE.isoformat()})
        self.assertEqual(cur.seen[0][1], (OperationsService.INDEX_MB_SHOWN * 2 ** 20,))


class SinceASnapshot(unittest.TestCase):
    def tearDown(self):
        ops_module._STATEMENT_BASES.clear()

    def test_the_top_statements_since_a_snapshot_by_their_time_since(self):
        """v10.42: ?snapshot=1 keeps the counts in the process; ?since=snapshot shows each statement's counts since,
        the top by that time: a statement hot before and idle since is not shown."""
        before = [(11, 100, 90000.0, 100, 10, 1, 0), (12, 10, 50.0, 10, 1, 0, 0)]
        cur = FakeCursor(SEEN + [(True,), before, (True, True), (90050.0, 110), (SINCE,), []])
        svc, patched = service(cur)
        with patched:
            svc.top_statements(snapshot=True, since=None)
        self.assertIn("snapshot", ops_module._STATEMENT_BASES)
        now = [(11, 100, 90000.0, 100, 10, 1, 0), (12, 30, 650.0, 40, 3, 2, 0), (13, 5, 100.0, 5, 0, 0, 1)]
        cur = FakeCursor(SEEN + [(True, True), now, [(12, "SELECT $1"), (13, "UPDATE x SET y = $1")]])
        svc, patched = service(cur)
        with patched:
            out = svc.top_statements(since="snapshot")
        self.assertEqual((out["enabled"], out["total_ms"], out["calls"]), (True, 700.0, 25))
        self.assertEqual([(x["id"], x["calls"], x["total_ms"], x["mean_ms"], x["statement"]) for x in out["statements"]],
                         [("12", 20, 600.0, 30.0, "SELECT $1"), ("13", 5, 100.0, 20.0, "UPDATE x SET y = $1")])
        self.assertEqual(out["since"], ops_module._STATEMENT_BASES["snapshot"][0])
        self.assertFalse(any("pg_stat_statements_reset" in sql for sql, _ in cur.seen), "read only: never a reset")

    def test_no_snapshot_says_so(self):
        svc, patched = service(FakeCursor(SEEN))
        with patched:
            out = svc.top_statements(since="start")
        self.assertEqual((out["enabled"], out["statements"]), (False, []))
        self.assertIn("snapshot=1", out["reason"])

    def test_a_snapshot_size(self):
        """5,000 statements (pg_stat_statements.max's default) kept: measured here, a few MB at most."""
        import tracemalloc
        rows = [(k, 10, 1.5, 10, 3, 1, 0) for k in range(5000)]
        tracemalloc.start()
        with mock.patch.object(ops_module, "statement_counts", wraps=ops_module.statement_counts):
            got = ops_module.statement_counts(FakeCursor([rows]))
        size, _peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        self.assertEqual(len(got), 5000)
        self.assertLess(size, 4 * 2 ** 20, size)


class RouteTimings(unittest.TestCase):
    def test_each_route_by_its_template(self):
        """v10.42: the count and time of each route, keyed by its template, never a path's values."""
        import main
        from insight_core.tests._asgi import call
        from insight_core.utils import route_timings
        route_timings._ROWS.clear()
        for _ in range(2):
            call(main.app, "GET", "/api/version")
        call(main.app, "GET", f"/api/operations/jobs/{uuid.uuid4()}")
        call(main.app, "GET", "/api/no-such-route")
        rows = {r["route"]: r for r in route_timings.snapshot()["routes"]}
        self.assertEqual(rows["GET /api/version"]["count"], 2)
        self.assertIn("GET /api/operations/jobs/{job_id}", rows)
        self.assertIn("GET (unmatched)", rows)
        self.assertTrue(all("-" not in k.split("/")[-1] or "{" in k for k in rows), "no uuid in a key")


@requires_db
class OnTheDatabase(unittest.TestCase):
    def test_every_statement_is_planned_for_its_values(self):
        """No generic plan for a prepared statement: an optional filter's index would be lost (0215)."""
        from insight_core.db import database
        with database.connection(db_url()) as conn:
            self.assertEqual(conn.execute("SHOW plan_cache_mode").fetchone()[0], "force_custom_plan")

    def test_the_route_answers_on_any_postgres(self):
        """The test server may or may not load the library: either way an answer, never an error."""
        import main
        from insight_core.tests._asgi import call
        with mock.patch.dict("os.environ", {"DATABASE_URL": db_url()}):
            status, _, body = call(main.app, "GET", "/api/operations/db-statements")
        self.assertEqual(status, 200, body)
        self.assertIn("shared_buffers", body["memory"])
        self.assertTrue(all({"table", "index", "scans", "mb"} <= set(i) for i in body["indexes"]))
        if body["enabled"]:
            self.assertLessEqual(len(body["statements"]), OperationsService.STATEMENTS_SHOWN)
        else:
            self.assertIn("pg_stat_statements is off", body["reason"])


if __name__ == "__main__":
    unittest.main()
