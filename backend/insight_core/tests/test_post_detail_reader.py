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

from types import SimpleNamespace

import main
from insight_core.services import registry
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.source_fetch_service import SourceFetchService
from insight_core.tests._asgi import call
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

    def test_detail_lists_clean_images_and_the_video(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE posts SET url = %s, media_urls = %s::jsonb WHERE id = %s",
                ("https://www.youtube.com/watch?v=rHCpgtc5nzs",
                 '["https://www.youtube.com/watch?v=rHCpgtc5nzs", "https://i.ytimg.com/vi/rHCpgtc5nzs/3.jpg",'
                 ' "https://tg.i-c-a.su/media/c/1/clip.mp4", "https://preview.redd.it/a.jpg?w=1&amp;s=x",'
                 ' "https://x.invalid/b.png"]',
                 self.post_id),
            )
            conn.commit()
        post = self.service.get_post_by_id(self.post_id)
        self.assertEqual(post["images"], [{"url": "https://preview.redd.it/a.jpg?w=1&s=x"},
                                          {"url": "https://x.invalid/b.png"}])
        self.assertEqual(post["video"], {"provider": "youtube", "id": "rHCpgtc5nzs"})

    def test_detail_without_media(self):
        post = self.service.get_post_by_id(self.post_id)
        self.assertEqual(post["images"], [])
        self.assertIsNone(post["video"])

    def test_reader_state_of_an_untouched_post(self):
        state = self.service.get_post_reader_state(self.post_id)
        self.assertFalse(state["is_favorited"])
        self.assertIsNone(state["read_at"])
        self.assertEqual(state["open_count"], 0)


@requires_test_db
class UnknownIdRouteTests(unittest.TestCase):
    """A well-formed id that names no row is a 404, not a ValueError 400 or an FK 500."""

    def setUp(self):
        previous = registry.use(SimpleNamespace(post_detail=PostDetailService(db_url()),
                                                source_fetch=SourceFetchService(db_url())))
        self.addCleanup(registry.use, previous)
        self.unknown = str(uuid.uuid4())

    def test_an_interaction_on_an_unknown_post_is_a_404(self):
        for path, json_body in (("opened", {}), ("reading-session", {"durationSeconds": 5}),
                                ("favorite", {"favorited": True})):
            with self.subTest(path=path), self.assertLogs("main", "WARNING"):
                status, _, body = call(main.app, "POST", f"/api/posts/item/{self.unknown}/{path}",
                                       json_body=json_body)
                self.assertEqual((status, body), (404, {"detail": f"Post {self.unknown} not found"}))

    def test_an_archive_of_an_unknown_source_is_a_404(self):
        with self.assertLogs("main", "WARNING"):
            status, _, body = call(main.app, "POST", f"/api/archive/{self.unknown}/plan", json_body={})
        self.assertEqual((status, body), (404, {"detail": f"Source {self.unknown} not found"}))
        status, _, body = call(main.app, "POST", f"/api/archive/{self.unknown}/run", json_body={"background": True})
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
