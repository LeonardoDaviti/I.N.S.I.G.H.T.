"""Reader routes: /api/feed*, PUT /api/posts/item/{id}/read, over ASGI with a fake reader service."""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main
from insight_core.db.repo_reader import FeedCursor, FeedScope
from insight_core.services import registry
from insight_core.tests._asgi import call

SOURCE_ID = str(uuid.uuid4())
POST_ID = str(uuid.uuid4())
LEAK = "database is down | url=postgresql://insight:secret@postgres:5432/insight"


class FakeReader:
    def __init__(self):
        self.calls = []
        self.raise_on = None

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self.raise_on == name:
            raise RuntimeError(LEAK)

    def feed(self, scope, **kwargs):
        self._record("feed", scope, **kwargs)
        if kwargs["view"] == "by_source":
            return {"success": True, "groups": [], "next_cursor": None}
        return {"success": True, "items": [], "next_cursor": None}

    def unread_counts(self):
        self._record("unread_counts")
        return {"total": 3, "by_source": {SOURCE_ID: 3}, "by_folder": {}}

    def mark_read_through(self, scope, through, newest):
        self._record("mark_read_through", scope, through, newest)
        return {"success": True, "updated": 1, "ids": [POST_ID]}

    def set_read(self, ids, read):
        self._record("set_read", ids, read)
        return len(ids)


class FeedRouteTests(unittest.TestCase):
    def setUp(self):
        self.reader = FakeReader()
        previous = registry.use(SimpleNamespace(reader=self.reader))
        self.addCleanup(registry.use, previous)
        self.cursor = FeedCursor(datetime(2026, 10, 1, tzinfo=timezone.utc), POST_ID)

    def get_feed(self, **query):
        return call(main.app, "GET", "/api/feed", query=query)

    def assertBadRequest(self, answer):
        status, _headers, body = answer
        self.assertEqual(status, 400, body)
        self.assertIsInstance(body["detail"], str)
        return body

    # ---- GET /api/feed --------------------------------------------------------------

    def test_feed_parses_scope_filter_cursor(self):
        status, _, body = self.get_feed(scope=f"source:{SOURCE_ID}", filter="unread", view="stream",
                                        cursor=self.cursor.encode(), limit=30, days=7)

        self.assertEqual((status, body), (200, {"success": True, "items": [], "next_cursor": None}))
        name, (scope,), kwargs = self.reader.calls[0]
        self.assertEqual(name, "feed")
        self.assertEqual(scope, FeedScope("source", SOURCE_ID))
        self.assertEqual(kwargs, {"filter": "unread", "view": "stream", "cursor": self.cursor,
                                  "limit": 30, "days": 7})

    def test_feed_defaults(self):
        self.get_feed()
        _, (scope,), kwargs = self.reader.calls[0]
        self.assertEqual(scope, FeedScope("all"))
        self.assertEqual(kwargs["view"], "stream")
        self.assertIsNone(kwargs["cursor"])

    def test_feed_by_source_view(self):
        _, _, body = self.get_feed(scope="all", filter="all", view="by_source")
        self.assertIn("groups", body)

    def test_malformed_cursor_is_400(self):
        self.assertBadRequest(self.get_feed(cursor="garbage!!"))
        self.assertEqual(self.reader.calls, [])

    def test_invalid_scope_filter_view_limit_days_are_400(self):
        for query in (
            {"scope": "folder:not-a-uuid"},
            {"scope": "tag:x"},
            {"filter": "everything"},
            {"view": "grid"},
            {"limit": 0},
            {"limit": 101},
            {"days": 0},
        ):
            with self.subTest(**query):
                self.assertBadRequest(self.get_feed(**query))
        self.assertEqual(self.reader.calls, [])

    def test_feed_failure_is_500_with_clean_detail(self):
        self.reader.raise_on = "feed"
        with self.assertLogs("main", "ERROR"):
            status, _, body = self.get_feed()
        self.assertEqual(status, 500)
        self.assertEqual(body, {"detail": "Could not load the feed. Check the backend logs."})

    # ---- unread counts ------------------------------------------------------------

    def test_unread_counts(self):
        _, _, body = call(main.app, "GET", "/api/feed/unread-counts")
        self.assertEqual(body["by_source"], {SOURCE_ID: 3})

    # ---- mark read through ----------------------------------------------------------

    def test_mark_read_through(self):
        newest = FeedCursor(datetime(2026, 10, 2, tzinfo=timezone.utc), str(uuid.uuid4()))
        status, _, body = call(main.app, "POST", "/api/feed/mark-read", json_body={
            "scope": "all", "through_cursor": self.cursor.encode(), "newest_cursor": newest.encode()})

        self.assertEqual((status, body), (200, {"success": True, "updated": 1, "ids": [POST_ID]}))
        self.assertEqual(self.reader.calls[0][1], (FeedScope("all"), self.cursor, newest))

    def test_mark_read_through_rejects_bad_cursor(self):
        self.assertBadRequest(call(main.app, "POST", "/api/feed/mark-read", json_body={
            "scope": "all", "through_cursor": "bad", "newest_cursor": "bad"}))

    # ---- PUT /api/feed/read and /api/posts/item/{id}/read -----------------------------

    def test_set_posts_read_batch(self):
        status, _, body = call(main.app, "PUT", "/api/feed/read", json_body={"ids": [POST_ID], "read": False})
        self.assertEqual((status, body), (200, {"success": True, "updated": 1}))
        self.assertEqual(self.reader.calls[0][1], ([POST_ID], False))

    def test_set_posts_read_rejects_bad_ids(self):
        self.assertBadRequest(call(main.app, "PUT", "/api/feed/read", json_body={"ids": ["nope"], "read": True}))
        self.assertBadRequest(call(main.app, "PUT", "/api/feed/read",
                                   json_body={"ids": [POST_ID] * 501, "read": True}))

    def test_set_post_read(self):
        status, _, body = call(main.app, "PUT", f"/api/posts/item/{POST_ID}/read", json_body={"read": True})
        self.assertEqual((status, body), (200, {"success": True, "post_id": POST_ID, "updated": 1}))
        self.assertEqual(self.reader.calls[0][1], ([POST_ID], True))

    def test_set_post_read_rejects_bad_id(self):
        self.assertBadRequest(call(main.app, "PUT", "/api/posts/item/nope/read", json_body={"read": True}))


class ErrorHandlerTests(unittest.TestCase):
    """The one error handler: a service error becomes a safe answer in the route's shape."""

    def setUp(self):
        previous = registry.use(SimpleNamespace(reader=FakeReader(), folders=self))
        self.addCleanup(registry.use, previous)

    def list_folders(self):          # the folders service for GET /api/folders
        raise RuntimeError(LEAK)

    def get_folder(self, folder_id):  # ... and for GET /api/folders/{id}/posts
        raise ValueError(f"Folder {folder_id} is broken at {LEAK}")

    def test_a_service_error_is_a_safe_500_detail(self):
        services = registry.services()
        services.reader.raise_on = "unread_counts"
        with self.assertLogs("main", "ERROR") as logged:
            status, headers, body = call(main.app, "GET", "/api/feed/unread-counts")
        self.assertEqual(status, 500)
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(body, {"detail": "Could not load unread counts. Check the backend logs."})
        self.assertIn("postgresql://", "\n".join(logged.output), "the cause is in the log, not the body")

    def test_a_service_error_on_a_mark_viii_route_keeps_the_envelope(self):
        with self.assertLogs("main", "ERROR"):
            status, _, body = call(main.app, "GET", "/api/folders")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"success": False, "error": "Could not load the folders. Check the backend logs.",
                                "folders": []})

    def test_a_message_the_caller_can_act_on_passes_without_the_dsn(self):
        status, _, body = call(main.app, "GET", "/api/folders/f1/posts")
        self.assertEqual(status, 200)
        self.assertFalse(body["success"])
        self.assertTrue(body["error"].startswith("Folder f1 is broken at"))
        self.assertNotIn("secret", body["error"])
        self.assertNotIn("postgresql://", body["error"])
        self.assertEqual(body["posts"], [])


if __name__ == "__main__":
    unittest.main()


class ReaderServiceDaysTests(unittest.TestCase):
    """`days` reaches the repository for both views (spec §4: GET /api/feed days=)."""

    class FakeRepo:
        def __init__(self):
            self.calls = []

        def feed(self, cur, scope, **kwargs):
            self.calls.append(("feed", kwargs))
            return [], None

        def feed_by_source(self, cur, scope, **kwargs):
            self.calls.append(("feed_by_source", kwargs))
            return [], None

    def _feed(self, view, days):
        from contextlib import nullcontext
        from datetime import timedelta
        from unittest import mock

        from insight_core.services.reader_service import ReaderService

        now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        repo = self.FakeRepo()
        service = ReaderService("postgresql:///unused", repo=repo, clock=lambda: now)
        conn = mock.MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value = nullcontext(object())
        with mock.patch("insight_core.services.reader_service.psycopg.connect", return_value=conn):
            service.feed(FeedScope("all", None), filter="all", view=view, cursor=None, limit=30, days=days)
        return repo.calls[0], now - timedelta(days=days) if days else None

    def test_by_source_passes_since(self):
        (name, kwargs), expected = self._feed("by_source", 1)
        self.assertEqual(name, "feed_by_source")
        self.assertEqual(kwargs["since"], expected)

    def test_stream_passes_since(self):
        (name, kwargs), expected = self._feed("stream", 7)
        self.assertEqual(name, "feed")
        self.assertEqual(kwargs["since"], expected)

    def test_no_days_means_no_since(self):
        (_name, kwargs), _ = self._feed("by_source", None)
        self.assertIsNone(kwargs["since"])
