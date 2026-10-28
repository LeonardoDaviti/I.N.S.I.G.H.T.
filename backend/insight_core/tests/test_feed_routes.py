"""Reader routes: /api/feed*, over ASGI with a fake reader service: parsing, 400s, redaction.

What the listing and read-state routes return from a real database: test_feed_listing_routes."""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.db.repo_reader import FeedCursor, FeedQuery, FeedScope
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

    def list_posts(self, query):
        self._record("list_posts", query)
        if query.view == "by_source":
            return {"success": True, "groups": [], "next_cursor": None}
        return {"success": True, "items": [], "next_cursor": None}

    def unread_counts(self):
        self._record("unread_counts")
        return {"total": 3, "by_source": {SOURCE_ID: 3}, "by_folder": {}}

    def mark_read_through(self, scope, through, newest):
        self._record("mark_read_through", scope, through, newest)
        return {"success": True, "updated": 1, "ids": [POST_ID]}

    def set_read(self, ids, read, keep_later=False):
        self._record("set_read", ids, read, keep_later=keep_later)
        return {"success": True, "updated": len(ids), "ids": ids}

    def set_later(self, ids, later):
        self._record("set_later", ids, later)
        return {"success": True, "updated": len(ids), "ids": ids}


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
        name, (query,), _ = self.reader.calls[0]
        self.assertEqual(name, "list_posts")
        self.assertEqual(query, FeedQuery(scope=FeedScope("source", SOURCE_ID), filter="unread", view="stream",
                                          cursor=self.cursor, limit=30, days=7))

    def test_feed_defaults(self):
        self.get_feed()
        _, (query,), _ = self.reader.calls[0]
        self.assertEqual(query, FeedQuery())

    def test_feed_parses_a_date(self):
        self.get_feed(scope=f"folder:{SOURCE_ID}", date="2026-10-01")
        _, (query,), _ = self.reader.calls[0]
        self.assertEqual((query.scope, query.day.isoformat()), (FeedScope("folder", SOURCE_ID), "2026-10-01"))

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
            {"date": "2026-13-01"},
            {"date": "2026-10-01", "days": 1},
        ):
            with self.subTest(**query):
                self.assertBadRequest(self.get_feed(**query))
        self.assertEqual(self.reader.calls, [])

    def test_feed_failure_is_500_with_clean_detail(self):
        self.reader.raise_on = "list_posts"
        with self.assertLogs("main", "ERROR"):
            status, _, body = self.get_feed()
        self.assertEqual(status, 500)
        self.assertEqual(body, {"detail": "Could not load the feed. Check the backend logs."})

    # ---- unread counts ------------------------------------------------------------

    def test_unread_counts(self):
        _, _, body = call(main.app, "GET", "/api/feed/unread-counts")
        self.assertEqual(body["by_source"], {SOURCE_ID: 3})

    # ---- PUT /api/feed/read --------------------------------------------------------

    def test_read_through(self):
        newest = FeedCursor(datetime(2026, 10, 2, tzinfo=timezone.utc), str(uuid.uuid4()))
        status, _, body = call(main.app, "PUT", "/api/feed/read", json_body={
            "scope": "all", "through_cursor": self.cursor.encode(), "newest_cursor": newest.encode()})

        self.assertEqual((status, body), (200, {"success": True, "updated": 1, "ids": [POST_ID]}))
        self.assertEqual(self.reader.calls[0][:2], ("mark_read_through", (FeedScope("all"), self.cursor, newest)))

    def test_read_through_rejects_bad_cursor(self):
        self.assertBadRequest(call(main.app, "PUT", "/api/feed/read", json_body={
            "scope": "all", "through_cursor": "bad", "newest_cursor": "bad"}))

    def test_read_ids(self):
        status, _, body = call(main.app, "PUT", "/api/feed/read", json_body={"ids": [POST_ID], "read": False})
        self.assertEqual((status, body), (200, {"success": True, "updated": 1, "ids": [POST_ID]}))
        self.assertEqual(self.reader.calls[0][:2], ("set_read", ([POST_ID], False)))

    def test_read_ids_rejects_bad_ids(self):
        self.assertBadRequest(call(main.app, "PUT", "/api/feed/read", json_body={"ids": ["nope"], "read": True}))
        self.assertBadRequest(call(main.app, "PUT", "/api/feed/read",
                                   json_body={"ids": [POST_ID] * 501, "read": True}))
        self.assertEqual(self.reader.calls, [])

    def test_read_ids_can_keep_later(self):
        call(main.app, "PUT", "/api/feed/read", json_body={"ids": [POST_ID], "read": True, "keep_later": True})
        self.assertEqual(self.reader.calls[0], ("set_read", ([POST_ID], True), {"keep_later": True}))

    def test_feed_parses_the_later_filter(self):
        status, _, _ = self.get_feed(filter="later")
        self.assertEqual(status, 200)
        self.assertEqual(self.reader.calls[0][1][0].filter, "later")

    # ---- PUT /api/feed/later -------------------------------------------------------

    def test_later_ids(self):
        status, _, body = call(main.app, "PUT", "/api/feed/later", json_body={"ids": [POST_ID], "later": True})
        self.assertEqual((status, body), (200, {"success": True, "updated": 1, "ids": [POST_ID]}))
        self.assertEqual(self.reader.calls[0][:2], ("set_later", ([POST_ID], True)))

    def test_later_rejects_bad_ids(self):
        for payload in ({"ids": ["nope"], "later": True}, {"ids": [], "later": True}, {"later": True}):
            with self.subTest(payload=payload):
                self.assertBadRequest(call(main.app, "PUT", "/api/feed/later", json_body=payload))
        self.assertEqual(self.reader.calls, [])


class ErrorHandlerTests(unittest.TestCase):
    """The one error handler: a service error becomes a safe answer in the route's shape."""

    def setUp(self):
        previous = registry.use(SimpleNamespace(reader=FakeReader(), folders=self))
        self.addCleanup(registry.use, previous)

    def list_folders(self):                    # the folders service for GET /api/folders
        raise RuntimeError(LEAK)

    def update_folder(self, folder_id, fields):  # ... and for PUT /api/folders/{id}
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

    def test_every_route_names_what_failed(self):
        with self.assertLogs("main", "ERROR"):
            status, _, body = call(main.app, "GET", "/api/folders")
        self.assertEqual((status, body), (500, {"detail": "Could not load the folders. Check the backend logs."}))

    def test_an_id_the_database_cannot_read_is_a_404(self):
        def update_folder(folder_id, fields):
            raise AssertionError("a path id that is not a uuid never reaches the service")
        self.update_folder = update_folder
        status, _, body = call(main.app, "PUT", "/api/folders/not-a-uuid", json_body={"name": "x"})
        self.assertEqual((status, body), (404, {"detail": "Not found."}))

    def test_every_malformed_path_id_is_a_404(self):
        for method, path, json_body in (
            ("GET", "/api/posts/item/nope", None),
            ("POST", "/api/posts/item/nope/favorite", {"favorited": True}),
            ("DELETE", "/api/folders/nope", None),
            ("DELETE", "/api/folders/nope/sources/nope", None),
            ("DELETE", "/api/sources/nope", None),
            ("POST", "/api/sources/nope/fetch-now", {}),
            ("GET", "/api/operations/jobs/nope", None),
            ("GET", "/api/archive/nope/status", None),
            ("POST", "/api/archive/nope/plan", {}),
        ):
            with self.subTest(method=method, path=path), self.assertLogs("main", "WARNING"):
                status, _, body = call(main.app, method, path, json_body=json_body)
                self.assertEqual((status, body), (404, {"detail": "Not found."}))

    def test_a_value_the_database_cannot_read_is_a_logged_400(self):
        def update_folder(folder_id, fields):
            raise psycopg.errors.InvalidTextRepresentation('invalid input syntax for type uuid: "x"')
        self.update_folder = update_folder
        with self.assertLogs("main", "WARNING") as logged:
            status, _, body = call(main.app, "PUT", f"/api/folders/{SOURCE_ID}", json_body={"name": "x"})
        self.assertEqual((status, body), (400, {"detail": "Invalid value."}))
        self.assertIn("invalid input syntax", "\n".join(logged.output))

    def test_bad_stored_data_is_a_logged_500_not_a_400(self):
        import json
        for error in (json.JSONDecodeError("Expecting value", "", 0),
                      UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")):
            def update_folder(folder_id, fields, error=error):
                raise error
            self.update_folder = update_folder
            with self.subTest(error=type(error).__name__), self.assertLogs("main", "ERROR"):
                status, _, body = call(main.app, "PUT", f"/api/folders/{SOURCE_ID}", json_body={"name": "x"})
                self.assertEqual((status, body), (500, {"detail": "Could not update the folder. Check the backend logs."}))

    def test_a_message_the_caller_can_act_on_passes_without_the_dsn(self):
        with self.assertLogs("main", "WARNING") as logged:
            status, _, body = call(main.app, "PUT", f"/api/folders/{SOURCE_ID}", json_body={"name": "x"})
        self.assertEqual(status, 400)
        self.assertTrue(body["detail"].startswith(f"Folder {SOURCE_ID} is broken at"))
        self.assertNotIn("secret", body["detail"])
        self.assertNotIn("postgresql://", body["detail"])
        line = "\n".join(logged.output)
        self.assertIn(f"PUT /api/folders/{SOURCE_ID} answered 400: Folder {SOURCE_ID} is broken at", line)
        self.assertNotIn("secret", line)


class FeedQueryBoundsTests(unittest.TestCase):
    """`days` and `date` become the sort-key bounds the listing query applies."""

    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)

    def test_days_is_a_lower_bound(self):
        from datetime import timedelta
        self.assertEqual(FeedQuery(days=7).bounds(self.now), (self.now - timedelta(days=7), None))

    def test_a_date_is_one_utc_day(self):
        since, until = FeedQuery.parse(date="2026-10-01").bounds(self.now)
        self.assertEqual((since.isoformat(), until.isoformat()),
                         ("2026-10-01T00:00:00+00:00", "2026-10-02T00:00:00+00:00"))

    def test_no_bound_by_default(self):
        self.assertEqual(FeedQuery().bounds(self.now), (None, None))


if __name__ == "__main__":
    unittest.main()
