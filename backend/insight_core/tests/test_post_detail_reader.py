"""PostDetailService writes the read-state projection (open -> read_at, favorite -> starred_at).

Scratch-source pattern: record_post_open opens and commits its own connection, so it can
only see a committed post. Committing class -> @requires_test_db.
"""
from __future__ import annotations

import sys
import time
import unittest
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.services.post_detail_service import PostDetailService
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db


@requires_test_db
class PostDetailReaderStateTests(unittest.TestCase):
    def setUp(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            source = insert_scratch_source(cur)
            cur.execute(
                "INSERT INTO posts (source_id, url, title, content) VALUES (%s, %s, 'T', 'Body') RETURNING id",
                (source, f"https://test.invalid/mark-ix/post/{uuid.uuid4().hex}"),
            )
            self.post_id = str(cur.fetchone()[0])
            conn.commit()
        self.service = PostDetailService(db_url())

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _projection(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT read_at, starred_at FROM post_reader_state WHERE post_id = %s", (self.post_id,))
            return cur.fetchone()

    def test_open_sets_read_at_once(self):
        self.service.record_post_open(self.post_id)
        first = self._projection()[0]
        self.assertIsNotNone(first)

        time.sleep(0.01)
        self.service.record_post_open(self.post_id)
        self.assertEqual(self._projection()[0], first, "a second open keeps the first read time")

        state = self.service.get_post_reader_state(self.post_id)
        self.assertEqual(state["read_at"], first)
        self.assertEqual(state["open_count"], 2, "the interaction log still records every open")

    def test_favorite_sets_and_clears_starred_at(self):
        result = self.service.toggle_favorite(self.post_id, True)
        self.assertTrue(result["favorited"])
        self.assertIsNotNone(self._projection()[1])
        self.assertTrue(self.service.get_post_reader_state(self.post_id)["is_favorited"])

        result = self.service.toggle_favorite(self.post_id, False)
        self.assertFalse(result["favorited"])
        self.assertIsNone(self._projection()[1])
        state = self.service.get_post_reader_state(self.post_id)
        self.assertFalse(state["is_favorited"])
        self.assertIsNone(state["read_at"], "starring is not reading")

    def test_reader_state_of_an_untouched_post(self):
        state = self.service.get_post_reader_state(self.post_id)
        self.assertFalse(state["is_favorited"])
        self.assertIsNone(state["read_at"])
        self.assertEqual(state["open_count"], 0)


if __name__ == "__main__":
    unittest.main()
