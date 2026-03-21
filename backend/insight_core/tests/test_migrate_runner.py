import os
import sys
import tempfile
import unittest
from pathlib import Path

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.migrate import apply_one


DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping migration tests")
class MigrationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.conn = psycopg.connect(DATABASE_URL)
        self.cur = self.conn.cursor()
        self.cur.execute("SELECT 1 FROM schema_migrations LIMIT 1")

        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False)
        self.tmp.write("SELECT 1;")
        self.tmp.flush()
        self.tmp.close()
        self.version = Path(self.tmp.name).name

    def tearDown(self):
        try:
            self.cur.execute("DELETE FROM schema_migrations WHERE version = %s", (self.version,))
            self.conn.commit()
        finally:
            self.conn.close()
            Path(self.tmp.name).unlink(missing_ok=True)

    def test_apply_one_is_idempotent_for_recording(self):
        first = apply_one(self.cur, Path(self.tmp.name), self.version)
        self.assertTrue(first)

        second = apply_one(self.cur, Path(self.tmp.name), self.version)
        self.assertFalse(second)

        self.cur.execute("SELECT count(*) FROM schema_migrations WHERE version = %s", (self.version,))
        self.assertEqual(self.cur.fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
