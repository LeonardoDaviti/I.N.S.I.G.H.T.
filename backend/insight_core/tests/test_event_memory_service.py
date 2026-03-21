import os
import sys
import unittest
from pathlib import Path

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_posts import PostsRepository
from insight_core.services.event_memory_service import EventMemoryService


DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping database tests")
class EventMemoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.source_handle = "https://event-memory-test.example.com/feed"
        self.post_url = "https://event-memory-test.example.com/posts/1"
        self.repo = PostsRepository(DATABASE_URL)
        self.service = EventMemoryService(DATABASE_URL)

        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sources (platform, handle_or_url, enabled, settings)
                    VALUES ('rss', %s, TRUE, '{}'::jsonb)
                    RETURNING id
                    """,
                    (self.source_handle,),
                )
                self.source_id = str(cur.fetchone()[0])
                conn.commit()

        self.post_payload = {
            "url": self.post_url,
            "title": "OpenAI launches a new model with Microsoft",
            "content": "The launch follows a partnership announcement and a new release.",
            "content_html": "<p>The launch follows a partnership announcement and a new release.</p>",
            "date": None,
            "external_id": "event-memory-1",
            "media_urls": [],
            "categories": [],
            "metadata": {},
        }

        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                self.post_id, _ = self.repo.upsert_post(cur, self.post_payload, self.source_id)
                conn.commit()

    def tearDown(self):
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM events WHERE title LIKE %s", ("OpenAI launches a new model%",))
                cur.execute("DELETE FROM sources WHERE id = %s", (self.source_id,))
                conn.commit()

    def test_process_post_creates_event_memory(self):
        result = self.service.process_post(
            {**self.post_payload, "id": self.post_id, "_source_id": self.source_id},
            source_id=self.source_id,
        )

        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["events_created"], 1)
        self.assertGreaterEqual(result["event_evidence_created"], 1)

        debug = self.service.get_post_event_debug(self.post_id)
        self.assertEqual(debug["post"]["id"], self.post_id)
        self.assertGreaterEqual(len(debug["events"]), 1)
        self.assertEqual(debug["events"][0]["event_type"], "release_launch")


if __name__ == "__main__":
    unittest.main()
