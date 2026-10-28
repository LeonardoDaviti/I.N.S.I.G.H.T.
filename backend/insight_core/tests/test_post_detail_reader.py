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
from insight_core.services.reader_service import ReaderService
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
        self.assertIsNone(state["later_at"])


@requires_test_db
class ReadingPositionTests(unittest.TestCase):
    """Continue where I stopped (issue 0030): the top block in view of a long post, kept with
    its read state until the post is finished (or marked read)."""

    def setUp(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source = insert_scratch_source(cur)
            cur.execute(
                "INSERT INTO posts (source_id, url, title, content) VALUES (%s, %s, 'T', 'Body') RETURNING id",
                (self.source, f"https://test.invalid/mark-ix/post/{uuid.uuid4().hex}"),
            )
            self.post_id = str(cur.fetchone()[0])
            conn.commit()
        self.service = PostDetailService(db_url())
        previous = registry.use(SimpleNamespace(post_detail=self.service, reader=ReaderService(db_url())))
        self.addCleanup(registry.use, previous)

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            conn.commit()

    def _position(self):
        state = self.service.get_post_reader_state(self.post_id)
        return state["resume_block"], state["resume_blocks"]

    def _feed_row(self):
        _, _, body = call(main.app, "GET", "/api/feed", query={"scope": f"source:{self.source}", "filter": "all"})
        (row,) = body["items"]
        return row["resume_block"], row["resume_blocks"]

    def test_an_untouched_post_has_no_position(self):
        self.assertEqual(self._position(), (None, None))
        self.assertEqual(self._feed_row(), (None, None))

    def test_the_position_is_stored_and_shown_on_the_post_and_its_feed_row(self):
        status, _, body = call(main.app, "PUT", f"/api/posts/item/{self.post_id}/position",
                               json_body={"block": 12, "blocks": 30})
        self.assertEqual((status, body["success"]), (200, True))
        self.assertEqual(self._position(), (12, 30))
        self.assertEqual(self._feed_row(), (12, 30))
        self.assertIsNone(self.service.get_post_reader_state(self.post_id)["read_at"], "a position is not a read")

        call(main.app, "PUT", f"/api/posts/item/{self.post_id}/position", json_body={"block": 20, "blocks": 30})
        self.assertEqual(self._position(), (20, 30), "the latest position wins")

    def test_finishing_clears_it(self):
        self.service.save_position(self.post_id, 12, 30)
        call(main.app, "PUT", f"/api/posts/item/{self.post_id}/position", json_body={"block": None})
        self.assertEqual(self._position(), (None, None))

    def test_marking_read_clears_it_but_opening_does_not(self):
        self.service.save_position(self.post_id, 12, 30)
        self.service.record_post_open(self.post_id)
        self.assertEqual(self._position(), (12, 30), "reopening a post keeps where you stopped")

        call(main.app, "PUT", "/api/feed/read", json_body={"ids": [self.post_id], "read": False})
        self.assertEqual(self._position(), (12, 30))
        call(main.app, "PUT", "/api/feed/read", json_body={"ids": [self.post_id], "read": True})
        self.assertEqual(self._position(), (None, None))

    def test_the_feed_marking_what_it_opens_keeps_it(self):
        # keep_later (issue 0022) is a read that is only an open: it finishes nothing.
        self.service.save_position(self.post_id, 12, 30)
        call(main.app, "PUT", "/api/feed/read", json_body={"ids": [self.post_id], "read": True, "keep_later": True})
        self.assertEqual(self._position(), (12, 30))

    def test_a_position_outside_the_post_is_a_400_and_an_unknown_post_a_404(self):
        for json_body in ({"block": 30, "blocks": 30}, {"block": -1, "blocks": 30}, {"block": 1, "blocks": 0},
                          {"block": 1}):
            with self.subTest(json_body=json_body), self.assertLogs("main", "WARNING"):
                status, _, _ = call(main.app, "PUT", f"/api/posts/item/{self.post_id}/position", json_body=json_body)
                self.assertEqual(status, 400)
        unknown = str(uuid.uuid4())
        with self.assertLogs("main", "WARNING"):
            status, _, _ = call(main.app, "PUT", f"/api/posts/item/{unknown}/position",
                                json_body={"block": 1, "blocks": 30})
        self.assertEqual(status, 404)


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
