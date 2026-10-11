"""ReaderRepository: the feed keyset query, read state, bounded mark-through, unread counts.

Rollback pattern (spec §5 conventions): one transaction per test, rolled back in
tearDown, so it is safe on any database. Every assertion is scoped to the test's own
scratch rows - live posts must never leak into a count.
"""
from __future__ import annotations

import json
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

from insight_core.db.repo_reader import FeedCursor, FeedScope, ReaderRepository
from insight_core.tests._db import db_url, insert_scratch_source, requires_db


class FeedCursorTests(unittest.TestCase):
    def test_encode_decode_round_trip(self):
        cursor = FeedCursor(datetime(2026, 10, 9, 12, 30, 1, 123456, tzinfo=timezone.utc), str(uuid.uuid4()))
        self.assertEqual(FeedCursor.decode(cursor.encode()), cursor)

    def test_decode_rejects_garbage(self):
        for bad in ["", "not-base64!!", "Zm9v", FeedCursor(datetime.now(timezone.utc), "x").encode()]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    FeedCursor.decode(bad)


@requires_db
class ReaderRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.repo = ReaderRepository(unread_window_days=30)
        self.conn = psycopg.connect(db_url())
        self.cur = self.conn.cursor()
        self.now = datetime.now(timezone.utc)

    def tearDown(self):
        self.conn.rollback()
        self.cur.close()
        self.conn.close()

    # ---- scratch helpers -------------------------------------------------------------

    def _source(self, **kwargs) -> str:
        return insert_scratch_source(self.cur, **kwargs)

    def _post(self, source_id: str, sort_at: datetime, *, title: str | None = "A post",
              content: str = "Body text", metadata: dict | None = None,
              media_urls: list | None = None) -> str:
        self.cur.execute(
            """
            INSERT INTO posts (source_id, url, published_at, title, content, metadata, media_urls)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb) RETURNING id
            """,
            (source_id, f"https://test.invalid/mark-ix/post/{uuid.uuid4().hex}", sort_at, title,
             content, json.dumps(metadata or {}), json.dumps(media_urls or [])),
        )
        return str(self.cur.fetchone()[0])

    def _posts(self, source_id: str, n: int, *, start: datetime | None = None) -> list[str]:
        """n posts, newest first, one minute apart."""
        start = start or (self.now - timedelta(hours=1))
        return [self._post(source_id, start - timedelta(minutes=i)) for i in range(n)]

    def _folder(self, *source_ids: str) -> str:
        self.cur.execute("INSERT INTO folders (name) VALUES (%s) RETURNING id", (f"scratch {uuid.uuid4().hex}",))
        folder_id = str(self.cur.fetchone()[0])
        for sid in source_ids:
            self.cur.execute("INSERT INTO source_folders (source_id, folder_id) VALUES (%s, %s)", (sid, folder_id))
        return folder_id

    def _page(self, scope, **kwargs):
        kwargs.setdefault("filter", "all")
        kwargs.setdefault("cursor", None)
        return self.repo.feed(self.cur, scope, **kwargs)

    # ---- feed: keyset pagination -----------------------------------------------------

    def test_feed_keyset_pagination_30_30_10(self):
        source = self._source()
        ids = self._posts(source, 70)
        scope = FeedScope("source", source)

        seen, sizes, cursor = [], [], None
        while True:
            items, cursor = self._page(scope, cursor=cursor, limit=30)
            sizes.append(len(items))
            seen.extend(items)
            if cursor is None:
                break

        self.assertEqual(sizes, [30, 30, 10])
        self.assertEqual([i["id"] for i in seen], ids, "every post once, newest first")
        keys = [(i["sort_at"], i["id"]) for i in seen]
        self.assertTrue(all(a > b for a, b in zip(keys, keys[1:])), "strictly descending")

    def test_ties_on_sort_at_are_broken_by_id_without_skipping(self):
        source = self._source()
        same = self.now - timedelta(hours=2)
        ids = [self._post(source, same) for _ in range(5)]
        scope = FeedScope("source", source)

        seen, cursor = [], None
        while True:
            items, cursor = self._page(scope, cursor=cursor, limit=2)
            seen.extend(i["id"] for i in items)
            if cursor is None:
                break

        self.assertEqual(seen, sorted(ids, reverse=True))

    # ---- feed: scopes -------------------------------------------------------------

    def test_folder_scope_returns_only_member_sources(self):
        member, outsider = self._source(), self._source()
        member_ids = set(self._posts(member, 3))
        self._posts(outsider, 3)
        folder = self._folder(member)

        items, _ = self._page(FeedScope("folder", folder), limit=30)

        self.assertEqual({i["id"] for i in items}, member_ids)

    def test_all_scope_honours_in_main_digest(self):
        far_future = self.now + timedelta(days=365 * 100)  # outranks every live post
        hidden_source = self._source(in_main_digest=False)
        shown_source = self._source(in_main_digest=True)
        hidden = self._post(hidden_source, far_future)
        shown = self._post(shown_source, far_future - timedelta(seconds=1))

        items, _ = self._page(FeedScope("all"), limit=30)
        ids = [i["id"] for i in items]

        self.assertNotIn(hidden, ids)
        self.assertIn(shown, ids)

    # ---- feed: filters ------------------------------------------------------------

    def test_unread_filter_hides_read_posts(self):
        source = self._source()
        a, b, c = self._posts(source, 3)
        self.repo.set_read(self.cur, [b], True)

        items, _ = self._page(FeedScope("source", source), filter="unread")

        self.assertEqual([i["id"] for i in items], [a, c])

    def test_unread_filter_applies_the_window(self):
        source = self._source()
        recent = self._post(source, self.now - timedelta(days=1))
        self._post(source, self.now - timedelta(days=45))

        items, _ = self._page(FeedScope("source", source), filter="unread")

        self.assertEqual([i["id"] for i in items], [recent])

    def test_without_a_window_unread_is_all_time(self):
        repo = ReaderRepository(unread_window_days=None)
        source = self._source()
        recent = self._post(source, self.now - timedelta(days=1))
        old = self._post(source, self.now - timedelta(days=4000))   # an archived post from years ago
        folder = self._folder(source)

        items, _ = repo.feed(self.cur, FeedScope("source", source), filter="unread", cursor=None, limit=30)
        counts = repo.unread_counts(self.cur)

        self.assertEqual([i["id"] for i in items], [recent, old])
        self.assertEqual(counts["by_source"][source], 2)
        self.assertEqual(counts["by_folder"][folder], 2)

    def test_without_a_window_mark_through_reaches_old_posts(self):
        repo = ReaderRepository(unread_window_days=None)
        source = self._source()
        recent = self._post(source, self.now - timedelta(hours=1))
        old = self._post(source, self.now - timedelta(days=400))
        scope = FeedScope("source", source)
        loaded, _ = repo.feed(self.cur, scope, filter="all", cursor=None, limit=30)
        by_id = {i["id"]: i for i in loaded}

        marked = repo.mark_read_through(
            self.cur, scope, FeedCursor(by_id[old]["sort_at"], old),
            newest=FeedCursor(by_id[recent]["sort_at"], recent), now=self.now,
        )

        self.assertEqual(sorted(marked), sorted([recent, old]))

    def test_starred_filter_shows_starred_posts(self):
        source = self._source()
        a, b, c = self._posts(source, 3)
        self.repo.set_starred(self.cur, c, True)

        items, _ = self._page(FeedScope("source", source), filter="starred")

        self.assertEqual([i["id"] for i in items], [c])
        self.assertIsNotNone(items[0]["starred_at"])

    def test_since_bounds_the_feed(self):
        source = self._source()
        recent = self._post(source, self.now - timedelta(days=1))
        self._post(source, self.now - timedelta(days=10))

        items, _ = self._page(FeedScope("source", source), since=self.now - timedelta(days=3))

        self.assertEqual([i["id"] for i in items], [recent])

    # ---- read / star --------------------------------------------------------------

    def test_set_read_and_unread(self):
        source = self._source()
        (post,) = self._posts(source, 1)

        self.assertEqual(self.repo.set_read(self.cur, [post], True), 1)
        first = self._page(FeedScope("source", source))[0][0]["read_at"]
        self.assertIsNotNone(first)

        self.repo.set_read(self.cur, [post], True)
        self.assertEqual(self._page(FeedScope("source", source))[0][0]["read_at"], first,
                         "marking read again keeps the first read time")

        self.assertEqual(self.repo.set_read(self.cur, [post], False), 1)
        self.assertIsNone(self._page(FeedScope("source", source))[0][0]["read_at"])

    def test_set_starred_toggles(self):
        source = self._source()
        (post,) = self._posts(source, 1)

        self.repo.set_starred(self.cur, post, True)
        self.assertIsNotNone(self._page(FeedScope("source", source))[0][0]["starred_at"])
        self.repo.set_starred(self.cur, post, False)
        self.assertIsNone(self._page(FeedScope("source", source))[0][0]["starred_at"])

    # ---- mark read through ----------------------------------------------------------

    def test_mark_read_through_is_bounded_by_newest_through_and_window(self):
        source = self._source()
        newer = self._post(source, self.now - timedelta(minutes=5))   # arrived after render
        ids = self._posts(source, 15, start=self.now - timedelta(hours=1))
        ancient = self._post(source, self.now - timedelta(days=60))
        scope = FeedScope("source", source)

        loaded, _ = self._page(scope, limit=30)
        by_id = {i["id"]: i for i in loaded}
        cursor_of = lambda pid: FeedCursor(by_id[pid]["sort_at"], pid)  # noqa: E731

        marked = self.repo.mark_read_through(
            self.cur, scope, cursor_of(ids[9]), newest=cursor_of(ids[0]), now=self.now,
        )

        self.assertEqual(sorted(marked), sorted(ids[:10]))
        unread, _ = self._page(scope, filter="unread")
        unread_ids = {i["id"] for i in unread}
        self.assertIn(newer, unread_ids)
        self.assertTrue(set(ids[10:]) <= unread_ids)

        # Through the ancient post: only the in-window unread rows are written.
        marked = self.repo.mark_read_through(
            self.cur, scope, cursor_of(ancient), newest=cursor_of(ids[0]), now=self.now,
        )
        self.assertEqual(sorted(marked), sorted(ids[10:]))
        all_items, _ = self._page(scope)
        self.assertIsNone({i["id"]: i for i in all_items}[ancient]["read_at"])

    # ---- by source ----------------------------------------------------------------

    def test_feed_by_source_groups(self):
        busy, quiet = self._source(), self._source()
        self._posts(busy, 40, start=self.now - timedelta(hours=3))
        quiet_ids = self._posts(quiet, 2, start=self.now - timedelta(hours=1))
        folder = self._folder(busy, quiet)

        groups, cursor = self.repo.feed_by_source(self.cur, FeedScope("folder", folder), filter="all")

        self.assertIsNone(cursor)
        self.assertEqual([g["source_id"] for g in groups], [quiet, busy], "ordered by newest post")
        self.assertEqual([g["count"] for g in groups], [2, 40])
        self.assertEqual([i["id"] for i in groups[0]["items"]], quiet_ids)
        self.assertEqual(len(groups[1]["items"]), 3)
        self.assertEqual(groups[0]["newest_sort_at"], groups[0]["items"][0]["sort_at"])

    def test_feed_by_source_group_keyset(self):
        sources = [self._source() for _ in range(3)]
        for n, sid in enumerate(sources):
            self._posts(sid, 1, start=self.now - timedelta(hours=n + 1))
        folder = self._folder(*sources)
        scope = FeedScope("folder", folder)

        first, cursor = self.repo.feed_by_source(self.cur, scope, filter="all", groups=2)
        rest, end = self.repo.feed_by_source(self.cur, scope, filter="all", groups=2, group_cursor=cursor)

        self.assertEqual([g["source_id"] for g in first + rest], sources)
        self.assertIsNone(end)

    def test_feed_by_source_count_honours_the_filter(self):
        source = self._source()
        ids = self._posts(source, 4)
        self.repo.set_read(self.cur, ids[:3], True)

        groups, _ = self.repo.feed_by_source(self.cur, FeedScope("source", source), filter="unread")

        self.assertEqual(groups[0]["count"], 1)
        self.assertEqual([i["id"] for i in groups[0]["items"]], [ids[3]])

    def test_feed_by_source_since_bounds_counts_and_items(self):
        source, old_only = self._source(), self._source()
        recent = self._post(source, self.now - timedelta(days=1))
        self._post(source, self.now - timedelta(days=10))
        self._post(old_only, self.now - timedelta(days=10))
        folder = self._folder(source, old_only)

        groups, _ = self.repo.feed_by_source(self.cur, FeedScope("folder", folder), filter="all",
                                             since=self.now - timedelta(days=3))

        self.assertEqual([g["source_id"] for g in groups], [source], "a source with only old posts drops out")
        self.assertEqual(groups[0]["count"], 1)
        self.assertEqual([i["id"] for i in groups[0]["items"]], [recent])

    def test_feed_by_source_items_stay_per_source_across_a_page(self):
        sources = [self._source() for _ in range(3)]
        ids = {sid: self._posts(sid, 5, start=self.now - timedelta(hours=n + 1)) for n, sid in enumerate(sources)}
        folder = self._folder(*sources)

        groups, _ = self.repo.feed_by_source(self.cur, FeedScope("folder", folder), filter="all", per_source=2)

        for group in groups:
            self.assertEqual([i["id"] for i in group["items"]], ids[group["source_id"]][:2])
            self.assertEqual(group["count"], 5)

    # ---- item shape ---------------------------------------------------------------

    def test_item_shape(self):
        source = self._source(platform="youtube")
        content = "<p>Hello <b>world</b></p> " + ("word " * 400)
        empty_title = self._post(source, self.now - timedelta(hours=1), title="", content=content,
                                 metadata={"duration_seconds": 754}, media_urls=["https://img.invalid/a.jpg"])

        (item,), _ = self._page(FeedScope("source", source))

        self.assertEqual(item["id"], empty_title)
        self.assertTrue(item["excerpt"].startswith("Hello world word"))
        self.assertLessEqual(len(item["excerpt"]), 280)
        self.assertEqual(item["title"], item["excerpt"][:80])
        self.assertEqual(item["duration_seconds"], 754)
        self.assertIsNone(item["reading_minutes"], "no reading time for YouTube")
        self.assertEqual(item["media_thumb"], "https://img.invalid/a.jpg")
        self.assertEqual(item["platform"], "youtube")
        self.assertEqual(item["source_id"], source)
        for key in ("url", "source_display_name", "sort_at", "published_at", "read_at", "starred_at"):
            self.assertIn(key, item)

    def test_media_thumb_is_an_image(self):
        source = self._source(platform="youtube")
        video = self._post(source, self.now - timedelta(hours=1), media_urls=[
            "https://www.youtube.com/watch?v=rHCpgtc5nzs", "https://i.ytimg.com/vi/rHCpgtc5nzs/3.jpg"])
        clip = self._post(source, self.now - timedelta(hours=2), media_urls=[
            "https://tg.i-c-a.su/media/c/1/clip.mp4", "https://preview.redd.it/a.jpeg?width=640&amp;s=abc"])
        link = self._post(source, self.now - timedelta(hours=3), media_urls=["https://example.com/article"])

        items, _ = self._page(FeedScope("source", source))
        thumbs = {i["id"]: i["media_thumb"] for i in items}

        self.assertEqual(thumbs[video], "https://i.ytimg.com/vi/rHCpgtc5nzs/hqdefault.jpg")
        self.assertEqual(thumbs[clip], "https://preview.redd.it/a.jpeg?width=640&s=abc", "first image, unescaped")
        self.assertIsNone(thumbs[link], "a link is not a thumbnail")

    def test_reading_minutes_for_text_posts(self):
        source = self._source()
        self._post(source, self.now - timedelta(hours=1), content="x" * 2300)

        (item,), _ = self._page(FeedScope("source", source))

        self.assertEqual(item["reading_minutes"], 3)  # ceil(2300 / 1100)
        self.assertIsNone(item["duration_seconds"])

    # ---- unread counts ------------------------------------------------------------

    def test_unread_counts(self):
        source = self._source()
        ids = self._posts(source, 3)
        self._post(source, self.now - timedelta(days=31))
        self.repo.set_read(self.cur, [ids[0]], True)
        folder = self._folder(source)

        counts = self.repo.unread_counts(self.cur)

        self.assertEqual(counts["by_source"][source], 2)
        self.assertEqual(counts["by_folder"][folder], 2)
        self.assertIn("total", counts)


class UnreadWindowFromEnvTests(unittest.TestCase):
    def _with_env(self, value):
        import os
        from unittest import mock
        env = {} if value is None else {"INSIGHT_UNREAD_WINDOW_DAYS": value}
        with mock.patch.dict(os.environ, env, clear=False):
            if value is None:
                os.environ.pop("INSIGHT_UNREAD_WINDOW_DAYS", None)
            return ReaderRepository().unread_window_days

    def test_no_window_by_default(self):
        self.assertIsNone(self._with_env(None))
        self.assertIsNone(self._with_env("0"))
        self.assertIsNone(self._with_env("soon"))

    def test_a_positive_value_sets_the_window(self):
        self.assertEqual(self._with_env("30"), 30)


if __name__ == "__main__":
    unittest.main()
