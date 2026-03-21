import os
import sys
import unittest
from pathlib import Path

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_posts import PostsRepository
from insight_core.services.entity_memory_service import EntityMemoryService


DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping database tests")
class EntityMemoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.source_handle = "https://memory-test.example.com/feed"
        self.post_url = "https://memory-test.example.com/posts/1"
        self.repo = PostsRepository(DATABASE_URL)
        self.service = EntityMemoryService(DATABASE_URL)

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
            "title": "Codex Memory Test Org launches with @codexmemorytest",
            "content": "Ada Memory Test and OpenAI are included in the launch announcement.",
            "content_html": "<p>Ada Memory Test and OpenAI are included in the launch announcement.</p>",
            "date": None,
            "external_id": "memory-test-1",
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
                cur.execute("DELETE FROM sources WHERE id = %s", (self.source_id,))
                cur.execute(
                    "DELETE FROM entities WHERE normalized_name LIKE %s OR canonical_name LIKE %s",
                    ("codex memory test%", "Codex Memory Test%"),
                )
                cur.execute(
                    "DELETE FROM entities WHERE normalized_name LIKE %s OR canonical_name LIKE %s",
                    ("ada memory test%", "Ada Memory Test%"),
                )
                conn.commit()

    def test_process_post_creates_mentions_and_entities(self):
        result = self.service.process_post(
            {**self.post_payload, "id": self.post_id, "_source_id": self.source_id},
            source_id=self.source_id,
        )

        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["mentions_created"], 2)
        self.assertGreaterEqual(result["entities_linked"], 2)

        debug = self.service.get_post_memory_debug(self.post_id)
        self.assertEqual(debug["post"]["id"], self.post_id)
        self.assertGreaterEqual(len(debug["mentions"]), 2)
        self.assertGreaterEqual(len(debug["entities"]), 2)

        normalized_mentions = {item["normalized_mention"] for item in debug["mentions"]}
        self.assertIn("codex memory test org", normalized_mentions)
        self.assertIn("codexmemorytest", normalized_mentions)
        self.assertIn("ada memory test", normalized_mentions)


if __name__ == "__main__":
    unittest.main()
