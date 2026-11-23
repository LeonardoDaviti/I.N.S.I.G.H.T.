"""News read state (0238): a row is its lead and its lines; `news.unread` counts the row's unread posts;
`unread=true` lists only rows with an unread post; PUT /api/feed/read {news: true} marks every post of every listed
row read, keeping Later. Pure parts as functions, routes over ASGI with fakes, the count on the database."""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.services.news_service import NewsService, read_state, row_post_ids, unread_posts
from insight_core.tests._db import db_url, requires_db

A, B, C, D = (str(uuid.uuid4()) for _ in range(4))
READ = "2026-11-01T10:00:00+00:00"


def row(lead, lead_read, *lines):
    """A News row as `news_on` answers it: the lead, its lines [(id, read_at)] and its count."""
    item = {"id": lead, "read_at": lead_read, "story": {"posts": [{"id": i, "read_at": r} for i, r in lines]},
            "news": {}}
    item["news"]["unread"] = len(unread_posts(item))
    return item


class PureTests(unittest.TestCase):
    def test_a_row_is_read_when_every_post_is(self):
        self.assertEqual(row(A, READ, (B, READ)).get("news")["unread"], 0)
        self.assertEqual(row(A, None, (B, READ)).get("news")["unread"], 1)
        # A read row a new post joined: one unread (the reader shows "1 new").
        self.assertEqual(row(A, READ, (B, READ), (C, None)).get("news")["unread"], 1)

    def test_the_unread_view_and_the_counts(self):
        items = [row(A, READ, (B, READ)), row(C, READ, (D, None))]
        answer = read_state({"items": items})
        self.assertEqual((answer["rows"], answer["unread_rows"], len(answer["items"])), (2, 1, 2))
        only = read_state({"items": items}, unread=True)
        self.assertEqual([i["id"] for i in only["items"]], [C])
        self.assertEqual((only["rows"], only["unread_rows"]), (2, 1), "the counts are the scope's, not the view's")

    def test_every_post_of_every_row_once(self):
        items = [row(A, None, (B, None)), row(C, READ, (B, None), (D, None))]
        self.assertEqual(row_post_ids(items), [A, B, C, D])


class FakeReader:
    def __init__(self):
        self.calls = []

    def set_read(self, ids, read, keep_later=False):
        self.calls.append(("set_read", ids, read, keep_later))
        return {"success": True, "updated": len(ids), "ids": ids}


class FakeNews:
    def __init__(self, ids):
        self.ids, self.calls = ids, []

    def post_ids(self, scope, mark):
        self.calls.append((scope, mark))
        return self.ids

    def news(self, scope, **kwargs):
        self.calls.append((scope, kwargs))
        return {"success": True, "items": [], "next_cursor": None, "mark": "ix", "fallback": False, "note": None,
                "rows": 0, "unread_rows": 0}


class RouteTests(unittest.TestCase):
    def setUp(self):
        import main
        from insight_core.services import registry
        from insight_core.tests._asgi import call
        self.main, self.call = main, call
        self.reader, self.news = FakeReader(), FakeNews([A, B])
        previous = registry.use(SimpleNamespace(reader=self.reader, news=self.news))
        self.addCleanup(registry.use, previous)

    def put(self, body):
        return self.call(self.main.app, "PUT", "/api/feed/read", json_body=body)

    def test_mark_all_news_read(self):
        status, _, body = self.put({"scope": "all", "news": True})
        self.assertEqual((status, body["ids"]), (200, [A, B]))
        self.assertEqual(self.news.calls, [("all", "main")])
        self.assertEqual(self.reader.calls, [("set_read", [A, B], True, True)], "read only: Later is kept")

    def test_mark_all_news_read_of_a_track_and_the_older_view(self):
        folder = str(uuid.uuid4())
        self.put({"scope": f"folder:{folder}", "news": True, "mark": "ix"})
        self.assertEqual(self.news.calls, [(f"folder:{folder}", "ix")])

    def test_nothing_to_mark(self):
        self.news.ids = []
        status, _, body = self.put({"scope": "all", "news": True})
        self.assertEqual((status, body), (200, {"success": True, "updated": 0, "ids": []}))
        self.assertEqual(self.reader.calls, [])

    def test_refused(self):
        for body in ({"scope": "all", "news": True, "read": False}, {"scope": "all", "news": True, "ids": [A]},
                     {"scope": "nowhere", "news": True}, {"scope": "all", "news": True, "mark": "y"}):
            self.assertEqual(self.put(body)[0], 400, body)
        self.assertEqual(self.reader.calls, [])

    def test_the_unread_view_is_asked(self):
        status, _, _ = self.call(self.main.app, "GET", "/api/news", query={"scope": "all", "unread": "true"})
        self.assertEqual(status, 200)
        self.assertTrue(self.news.calls[0][1]["unread"])
        self.call(self.main.app, "GET", "/api/news", query={"scope": "all"})
        self.assertFalse(self.news.calls[1][1]["unread"])


@requires_db
class RowCountTests(unittest.TestCase):
    """`news.unread` on the database: a row's posts unread, from the per-post read state."""

    def setUp(self):
        from insight_core.services.stories_service import StoriesService
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc)
        self.mark = uuid.uuid4().hex[:8]
        self.news = NewsService(db_url(), clock=lambda: self.now)
        self.service = StoriesService(db_url(), clock=lambda: self.now, news=self.news)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    def test_a_row_read_then_a_new_post(self):
        from insight_core.db.repo_reader import ReaderRepository
        from insight_core.db.repo_stories import StoriesRepository
        from insight_core.tests._stories import insert_post, insert_source
        name = f"Quux{self.mark[:4]} 7"
        sources = [insert_source(self.cur, n, in_main_digest=True, followed_days=60) for n in ("One", "Two", "Three", "Four")]

        def post(source, site, hours):
            return str(insert_post(self.cur, source, f"https://{site}-{self.mark}.test/{uuid.uuid4().hex}",
                                   at=self.now - timedelta(hours=hours), title=f"{name} is out", content="Body",
                                   content_hash=uuid.uuid4().hex, host=f"{site}-{self.mark}.test"))

        def job():
            while StoriesRepository().fill_missing_links(self.cur):
                pass
            self.service.regroup(self.cur)

        def mine():
            [item] = [i for i in self.news.news_on(self.cur, "all")["items"] if self.mark in (i.get("url") or "")]
            return item

        first = [post(sources[0], "one", 10), post(sources[1], "two", 9), post(sources[2], "three", 8)]
        job()
        self.assertEqual(mine()["news"]["unread"], 3)
        ReaderRepository().set_read(self.cur, row_post_ids([mine()]), True)
        self.assertEqual(mine()["news"]["unread"], 0, "a row marked read: every post of it")
        late = post(sources[3], "four", 1)
        job()
        item = mine()
        self.assertEqual(item["news"]["unread"], 1, "the post that joined after is the one new")
        self.assertEqual([p["id"] for p in item["story"]["posts"] if not p["read_at"]], [late])
        self.assertIn(item["id"], first)


if __name__ == "__main__":
    unittest.main()
