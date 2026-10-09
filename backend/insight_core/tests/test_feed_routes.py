"""Reader routes: /api/feed*, PUT /api/posts/item/{id}/read. FakeBridge, coroutines called directly."""
from __future__ import annotations

import asyncio
import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from fastapi import HTTPException

import main
from insight_core.db.repo_reader import FeedCursor, FeedScope

SOURCE_ID = str(uuid.uuid4())
POST_ID = str(uuid.uuid4())


class FakeBridge:
    def __init__(self):
        self.calls = []
        self.raise_on = None

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self.raise_on == name:
            raise RuntimeError("database is down | url=postgresql://secret")

    def get_feed(self, scope, **kwargs):
        self._record("get_feed", scope, **kwargs)
        if kwargs["view"] == "by_source":
            return {"success": True, "groups": [], "next_cursor": None}
        return {"success": True, "items": [], "next_cursor": None}

    def get_unread_counts(self):
        self._record("get_unread_counts")
        return {"total": 3, "by_source": {SOURCE_ID: 3}, "by_folder": {}}

    def mark_read_through(self, scope, through, newest):
        self._record("mark_read_through", scope, through, newest)
        return {"success": True, "updated": 1, "ids": [POST_ID]}

    def set_posts_read(self, ids, read):
        self._record("set_posts_read", ids, read)
        return {"success": True, "updated": len(ids)}

    def set_post_read(self, post_id, read):
        self._record("set_post_read", post_id, read)
        return {"success": True, "post_id": post_id, "updated": 1}


def run(coro):
    return asyncio.run(coro)


class FeedRouteTests(unittest.TestCase):
    def setUp(self):
        self.original_bridge = main.api_bridge
        self.bridge = FakeBridge()
        main.api_bridge = self.bridge
        self.cursor = FeedCursor(datetime(2026, 10, 1, tzinfo=timezone.utc), POST_ID)

    def tearDown(self):
        main.api_bridge = self.original_bridge

    def assertBadRequest(self, coro):
        with self.assertRaises(HTTPException) as ctx:
            run(coro)
        self.assertEqual(ctx.exception.status_code, 400)
        return ctx.exception

    # ---- GET /api/feed --------------------------------------------------------------

    def test_feed_parses_scope_filter_cursor(self):
        result = run(main.get_feed(scope=f"source:{SOURCE_ID}", filter="unread", view="stream",
                                   cursor=self.cursor.encode(), limit=30, days=7))

        self.assertEqual(result, {"success": True, "items": [], "next_cursor": None})
        name, (scope,), kwargs = self.bridge.calls[0]
        self.assertEqual(name, "get_feed")
        self.assertEqual(scope, FeedScope("source", SOURCE_ID))
        self.assertEqual(kwargs, {"filter": "unread", "view": "stream", "cursor": self.cursor,
                                  "limit": 30, "days": 7})

    def test_feed_defaults(self):
        run(main.get_feed())
        _, (scope,), kwargs = self.bridge.calls[0]
        self.assertEqual(scope, FeedScope("all"))
        self.assertEqual(kwargs["view"], "stream")
        self.assertIsNone(kwargs["cursor"])

    def test_feed_by_source_view(self):
        result = run(main.get_feed(scope="all", filter="all", view="by_source"))
        self.assertIn("groups", result)

    def test_malformed_cursor_is_400(self):
        self.assertBadRequest(main.get_feed(cursor="garbage!!"))
        self.assertEqual(self.bridge.calls, [])

    def test_invalid_scope_filter_view_limit_days_are_400(self):
        for kwargs in (
            {"scope": "folder:not-a-uuid"},
            {"scope": "tag:x"},
            {"filter": "everything"},
            {"view": "grid"},
            {"limit": 0},
            {"limit": 101},
            {"days": 0},
        ):
            with self.subTest(**kwargs):
                self.assertBadRequest(main.get_feed(**kwargs))
        self.assertEqual(self.bridge.calls, [])

    def test_feed_failure_is_500_with_clean_detail(self):
        self.bridge.raise_on = "get_feed"
        with self.assertRaises(HTTPException) as ctx:
            run(main.get_feed())
        self.assertEqual(ctx.exception.status_code, 500)
        self.assertNotIn("| url=", ctx.exception.detail)

    # ---- unread counts ------------------------------------------------------------

    def test_unread_counts(self):
        result = run(main.get_feed_unread_counts())
        self.assertEqual(result["by_source"], {SOURCE_ID: 3})

    # ---- mark read through ----------------------------------------------------------

    def test_mark_read_through(self):
        newest = FeedCursor(datetime(2026, 10, 2, tzinfo=timezone.utc), str(uuid.uuid4()))
        request = main.FeedMarkReadRequest(scope="all", through_cursor=self.cursor.encode(),
                                           newest_cursor=newest.encode())

        result = run(main.mark_feed_read(request))

        self.assertEqual(result, {"success": True, "updated": 1, "ids": [POST_ID]})
        self.assertEqual(self.bridge.calls[0][1], (FeedScope("all"), self.cursor, newest))

    def test_mark_read_through_rejects_bad_cursor(self):
        request = main.FeedMarkReadRequest(scope="all", through_cursor="bad", newest_cursor="bad")
        self.assertBadRequest(main.mark_feed_read(request))

    # ---- PUT /api/feed/read and /api/posts/item/{id}/read -----------------------------

    def test_set_posts_read_batch(self):
        result = run(main.set_feed_read(main.FeedReadRequest(ids=[POST_ID], read=False)))
        self.assertEqual(result, {"success": True, "updated": 1})
        self.assertEqual(self.bridge.calls[0][1], ([POST_ID], False))

    def test_set_posts_read_rejects_bad_ids(self):
        self.assertBadRequest(main.set_feed_read(main.FeedReadRequest(ids=["nope"], read=True)))
        self.assertBadRequest(main.set_feed_read(main.FeedReadRequest(ids=[POST_ID] * 501, read=True)))

    def test_set_post_read(self):
        result = run(main.set_post_read(POST_ID, main.PostReadRequest(read=True)))
        self.assertTrue(result["success"])
        self.assertEqual(self.bridge.calls[0][1], (POST_ID, True))

    def test_set_post_read_rejects_bad_id(self):
        self.assertBadRequest(main.set_post_read("nope", main.PostReadRequest(read=True)))


if __name__ == "__main__":
    unittest.main()
