"""GET /api/feed and PUT /api/feed/read: real services on the scratch database, over ASGI.

One test per listing filter (all, source, track, date, unread, cursor) against the one post
listing, and one for the read-state route (single, bulk, through). Rows are committed, so
the class only runs against a `_test` database; every assertion is scoped to its own rows.
"""
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

FOLDER_PREFIX = "mark-ix-test-folder-"


@requires_test_db
class FeedListingRouteTests(unittest.TestCase):
    def setUp(self):
        previous = registry.use(registry.build_services(db_url()))
        self.addCleanup(registry.use, previous)
        self.addCleanup(self._clean)
        self._clean()
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def _clean(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM folders WHERE name LIKE %s", (FOLDER_PREFIX + "%",))
            delete_scratch_sources(cur)

    # ---- scratch rows -------------------------------------------------------------

    def _source(self, *, in_main_digest: bool = False) -> str:
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            return insert_scratch_source(cur, in_main_digest=in_main_digest)

    def _posts(self, source_id: str, *stamps: datetime) -> list[str]:
        """One post per stamp; ids in the order given."""
        ids = []
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            for stamp in stamps:
                cur.execute(
                    "INSERT INTO posts (source_id, url, published_at, title, content) "
                    "VALUES (%s, %s, %s, 'A post', 'Body') RETURNING id",
                    (source_id, f"https://test.invalid/mark-ix/post/{uuid.uuid4().hex}", stamp),
                )
                ids.append(str(cur.fetchone()[0]))
        return ids

    def _folder(self, *source_ids: str) -> str:
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO folders (name) VALUES (%s) RETURNING id", (FOLDER_PREFIX + uuid.uuid4().hex,))
            folder_id = str(cur.fetchone()[0])
            for source_id in source_ids:
                cur.execute("INSERT INTO source_folders (folder_id, source_id) VALUES (%s, %s)", (folder_id, source_id))
        return folder_id

    def _hours_ago(self, *hours: int) -> list[datetime]:
        return [self.now - timedelta(hours=h) for h in hours]

    def feed(self, **query):
        status, _, body = call(main.app, "GET", "/api/feed", query={"limit": 100, **query})
        self.assertEqual(status, 200, body)
        return body

    def ids(self, **query) -> list[str]:
        return [item["id"] for item in self.feed(**query)["items"]]

    def read(self, **payload):
        status, _, body = call(main.app, "PUT", "/api/feed/read", json_body=payload)
        self.assertEqual(status, 200, body)
        return body

    # ---- one test per filter -------------------------------------------------------

    def test_all_shows_main_digest_sources_only(self):
        inside, outside = self._source(in_main_digest=True), self._source(in_main_digest=False)
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)   # newest of all, so on the first page
        (shown,) = self._posts(inside, future)
        (hidden,) = self._posts(outside, future + timedelta(minutes=1))

        ids = self.ids(scope="all")

        self.assertIn(shown, ids)
        self.assertNotIn(hidden, ids)

    def test_source_shows_that_source_newest_first(self):
        source, other = self._source(), self._source()
        older, newer = self._posts(source, *self._hours_ago(2, 1))
        self._posts(other, *self._hours_ago(1))

        self.assertEqual(self.ids(scope=f"source:{source}"), [newer, older])

    def test_track_shows_its_sources_posts(self):
        member, outsider = self._source(), self._source()
        (inside,) = self._posts(member, *self._hours_ago(1))
        self._posts(outsider, *self._hours_ago(1))
        track = self._folder(member)

        self.assertEqual(self.ids(scope=f"folder:{track}"), [inside])
        groups = self.feed(scope=f"folder:{track}", view="by_source")["groups"]
        self.assertEqual([(g["source_id"], g["count"]) for g in groups], [(member, 1)])

    def test_date_keeps_one_utc_day(self):
        source = self._source()
        day = datetime(2001, 2, 3, tzinfo=timezone.utc)
        before, first, last, after = self._posts(
            source, day - timedelta(seconds=1), day, day + timedelta(hours=23, minutes=59), day + timedelta(days=1),
        )

        self.assertEqual(self.ids(scope=f"source:{source}", date="2001-02-03"), [last, first])
        status, _, body = call(main.app, "GET", "/api/feed", query={"date": "3 Feb 2001"})
        self.assertEqual(status, 400, body)

    def test_unread_hides_read_posts(self):
        source = self._source()
        read, unread = self._posts(source, *self._hours_ago(2, 1))
        self.read(ids=[read], read=True)

        self.assertEqual(self.ids(scope=f"source:{source}", filter="unread"), [unread])

    def test_cursor_pages_without_overlap(self):
        source = self._source()
        oldest, middle, newest = self._posts(source, *self._hours_ago(3, 2, 1))

        first = self.feed(scope=f"source:{source}", limit=2)
        second = self.feed(scope=f"source:{source}", limit=2, cursor=first["next_cursor"])

        self.assertEqual([i["id"] for i in first["items"]], [newest, middle])
        self.assertEqual([i["id"] for i in second["items"]], [oldest])
        self.assertIsNone(second["next_cursor"])

    # ---- the read-state route --------------------------------------------------------

    def test_read_state_single_bulk_and_through(self):
        source = self._source()
        scope = f"source:{source}"
        p1, p2, p3, p4 = self._posts(source, *self._hours_ago(4, 3, 2, 1))

        # single
        self.assertEqual(self.read(ids=[p4], read=True), {"success": True, "updated": 1, "ids": [p4]})
        self.assertEqual(self.read(ids=[p4], read=True)["updated"], 0, "already read: nothing changes")
        self.assertEqual(self.ids(scope=scope, filter="unread"), [p3, p2, p1])

        # bulk
        self.assertEqual(self.read(ids=[p4, p3], read=False)["updated"], 1, "p3 was never read")
        self.assertEqual(self.ids(scope=scope, filter="unread"), [p4, p3, p2, p1])

        # through: from the newest on the page (p3) down to p2; p4 and p1 stay unread
        items = {item["id"]: item for item in self.feed(scope=scope)["items"]}
        cursor = lambda pid: main.FeedCursor(datetime.fromisoformat(items[pid]["sort_at"]), pid).encode()
        marked = self.read(scope=scope, through_cursor=cursor(p2), newest_cursor=cursor(p3))
        self.assertEqual((marked["updated"], sorted(marked["ids"])), (2, sorted([p2, p3])))
        self.assertEqual(self.ids(scope=scope, filter="unread"), [p4, p1])

        # its ids undo it
        self.read(ids=marked["ids"], read=False)
        self.assertEqual(self.ids(scope=scope, filter="unread"), [p4, p3, p2, p1])

    # ---- Later (issue 0022) ----------------------------------------------------------

    def later(self, **payload):
        status, _, body = call(main.app, "PUT", "/api/feed/later", json_body=payload)
        self.assertEqual(status, 200, body)
        return body

    def test_finishing_takes_a_post_out_of_later_and_opening_does_not(self):
        source = self._source()
        scope = f"source:{source}"
        p1, p2 = self._posts(source, *self._hours_ago(2, 1))
        self.assertEqual(self.later(ids=[p1], later=True), {"success": True, "updated": 1, "ids": [p1]})
        self.assertEqual(self.later(ids=[p1, p2], later=True)["ids"], [p2], "p1 is already in Later")
        self.assertEqual(self.ids(scope=scope, filter="later"), [p1, p2], "oldest saved first: p1 was saved first")
        self.assertEqual(self.ids(scope=scope, filter="unread"), [p2, p1], "a Later post stays in Unread")

        # opening is not finishing: the post page's open, and the feed's own read on open
        status, _, body = call(main.app, "POST", f"/api/posts/item/{p1}/opened", json_body={})
        self.assertEqual(status, 200, body)
        self.read(ids=[p1], read=True, keep_later=True)
        self.assertEqual(self.ids(scope=scope, filter="later"), [p1, p2])
        status, _, body = call(main.app, "GET", f"/api/posts/item/{p1}")
        self.assertIsNotNone(body["reader_state"]["later_at"])

        # mark read up to here is catching up, not finishing
        items = {item["id"]: item for item in self.feed(scope=scope)["items"]}
        cursor = lambda pid: main.FeedCursor(datetime.fromisoformat(items[pid]["sort_at"]), pid).encode()
        self.read(scope=scope, through_cursor=cursor(p1), newest_cursor=cursor(p2))
        self.assertEqual(self.ids(scope=scope, filter="later"), [p1, p2])

        # an explicit mark read is finishing (read already or not)
        self.read(ids=[p1], read=True)
        self.assertEqual(self.ids(scope=scope, filter="later"), [p2])
        # and marking unread again does not put it back
        self.read(ids=[p1], read=False)
        self.assertEqual(self.ids(scope=scope, filter="later"), [p2])

        # the hand toggle
        self.assertEqual(self.later(ids=[p2], later=False)["ids"], [p2])
        self.assertEqual(self.ids(scope=scope, filter="later"), [])

    def test_starred_is_kept(self):
        source = self._source()
        p1, p2 = self._posts(source, *self._hours_ago(2, 1))
        status, _, body = call(main.app, "POST", f"/api/posts/item/{p1}/favorite", json_body={"favorited": True})
        self.assertEqual(status, 200, body)
        self.assertEqual(self.ids(scope=f"source:{source}", filter="starred"), [p1])

    def test_unread_counts_say_what_later_costs(self):
        source = self._source()
        before = call(main.app, "GET", "/api/feed/unread-counts")[2]["later"]
        (post,) = self._posts(source, *self._hours_ago(1))
        self.later(ids=[post], later=True)

        after = call(main.app, "GET", "/api/feed/unread-counts")[2]["later"]

        self.assertEqual((after["count"] - before["count"], after["minutes"] - before["minutes"]), (1, 1))

    def test_a_whole_text_title_comes_back_cut_from_the_feed_and_the_post(self):
        source = self._source()
        tweet = "Our new model is out today and it is better at everything. " + "And more besides, " * 50
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO posts (source_id, url, title, content) VALUES (%s, %s, %s, %s) RETURNING id",
                (source, f"https://test.invalid/mark-ix/post/{uuid.uuid4().hex}", tweet, tweet),
            )
            post_id = str(cur.fetchone()[0])
        short = "Our new model is out today and it is better at everything."

        feed_title = next(item["title"] for item in self.feed(scope=f"source:{source}")["items"] if item["id"] == post_id)
        status, _, body = call(main.app, "GET", f"/api/posts/item/{post_id}")
        self.assertEqual(status, 200, body)
        self.assertEqual((feed_title, body["post"]["title"]), (short, short))
        self.assertEqual(body["post"]["content"], tweet, "the body is served in full")

    def test_read_state_rejects_a_mixed_or_empty_body(self):
        source = self._source()
        (post,) = self._posts(source, *self._hours_ago(1))
        for payload in ({}, {"ids": []}, {"ids": [post], "through_cursor": "x", "newest_cursor": "x"},
                        {"through_cursor": "x"}, {"read": False, "through_cursor": "x", "newest_cursor": "x"}):
            with self.subTest(payload=payload):
                status, _, body = call(main.app, "PUT", "/api/feed/read", json_body=payload)
                self.assertEqual(status, 400, body)


if __name__ == "__main__":
    unittest.main()
