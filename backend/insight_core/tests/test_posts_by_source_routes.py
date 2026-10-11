"""GET /api/posts/source/{id}: real services on the scratch database, over ASGI."""
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.services import registry
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db


@requires_test_db
class PostsBySourceRouteTests(unittest.TestCase):
    def setUp(self):
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source_id = insert_scratch_source(cur)
            for i in range(3):
                cur.execute(
                    "INSERT INTO posts (source_id, url, published_at, title, content) VALUES (%s, %s, %s, %s, %s)",
                    (self.source_id, f"https://test.invalid/mark-ix/post/{uuid.uuid4().hex}",
                     start + timedelta(hours=i), f"Post {i}", "Body"),
                )

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)

    def test_a_page_of_posts_with_the_total(self):
        status, _, body = call(main.app, "GET", f"/api/posts/source/{self.source_id}",
                               query={"limit": 2, "offset": 1})

        self.assertEqual(status, 200)
        self.assertTrue(body["success"])
        self.assertEqual((body["source_id"], body["total"], body["returned"], body["offset"], body["limit"]),
                         (self.source_id, 3, 2, 1, 2))
        self.assertFalse(body["has_more"])
        self.assertEqual(len(body["posts"]), 2)

    def test_the_first_page_has_more(self):
        _, _, body = call(main.app, "GET", f"/api/posts/source/{self.source_id}", query={"limit": 1})
        self.assertEqual((body["returned"], body["offset"]), (1, 0))
        self.assertTrue(body["has_more"])

    def test_a_bad_source_id_keeps_the_envelope_without_driver_text(self):
        with self.assertLogs("main", "ERROR"):
            status, _, body = call(main.app, "GET", "/api/posts/source/not-a-uuid", query={"offset": 5})
        self.assertEqual(status, 200)
        self.assertEqual(body, {"success": False, "error": "Could not load the posts. Check the backend logs.",
                                "posts": [], "total": 0, "returned": 0, "offset": 5, "limit": None,
                                "has_more": False, "source_id": "not-a-uuid"})


if __name__ == "__main__":
    unittest.main()
