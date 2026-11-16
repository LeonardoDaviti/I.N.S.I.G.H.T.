"""0215: GET /api/operations/db-statements, the database's top statements (pg_stat_statements), read only."""
from __future__ import annotations

import sys
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.services import operations_service as ops_module
from insight_core.services.operations_service import OperationsService
from insight_core.tests._db import db_url, requires_db

SINCE = datetime(2026, 11, 16, 9, tzinfo=timezone.utc)


class FakeCursor:
    """Answers top_statements' four reads in order."""

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
        cur = FakeCursor([(True, True), (50000.0, 9000), (SINCE,), rows])
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
            svc, patched = service(FakeCursor([answer]))
            with patched:
                out = svc.top_statements()
            self.assertEqual((out["enabled"], out["statements"]), (False, []))
            self.assertIn(why, out["reason"])


@requires_db
class OnTheDatabase(unittest.TestCase):
    def test_the_route_answers_on_any_postgres(self):
        """The test server may or may not load the library: either way an answer, never an error."""
        import main
        from insight_core.tests._asgi import call
        with mock.patch.dict("os.environ", {"DATABASE_URL": db_url()}):
            status, _, body = call(main.app, "GET", "/api/operations/db-statements")
        self.assertEqual(status, 200, body)
        if body["enabled"]:
            self.assertLessEqual(len(body["statements"]), OperationsService.STATEMENTS_SHOWN)
        else:
            self.assertIn("pg_stat_statements is off", body["reason"])


if __name__ == "__main__":
    unittest.main()
