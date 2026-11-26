"""Reading usage: a reading session's active seconds and depth, the original opened ("opened_source"), the rows seen
in a list (post_seen, 0187) and GET /api/reading/summary. PostDetailService commits its own connections, so these
classes are @requires_test_db and clean up after themselves.
"""
from __future__ import annotations

import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg

import main
from insight_core.db.repo_reader import HISTORY_SQL
from insight_core.markx import personal
from insight_core.services.post_detail_service import PostDetailService
from insight_core.tests._asgi import call
from insight_core.tests._db import db_url, delete_scratch_sources, insert_scratch_source, requires_test_db


@requires_test_db
class ReadingUsageTests(unittest.TestCase):
    def setUp(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            delete_scratch_sources(cur)
            self.source = str(insert_scratch_source(cur))
            self.posts = []
            for n in range(3):
                cur.execute("INSERT INTO posts (source_id, url, title, content) VALUES (%s, %s, %s, 'Body') RETURNING id",
                            (self.source, f"https://test.invalid/reading/{uuid.uuid4().hex}", f"Post {n}"))
                self.posts.append(str(cur.fetchone()[0]))
            cur.execute("INSERT INTO folders (name) VALUES (%s) RETURNING id::text", (f"Reading track {uuid.uuid4().hex[:6]}",))
            self.track = cur.fetchone()[0]
            cur.execute("INSERT INTO mx_tracks (folder_id) VALUES (%s)", (self.track,))
            cur.execute("INSERT INTO mx_track_places (track_id, post_id, place, rank, calibrated, active) "
                        "VALUES (%s, %s, 'track', 1, true, true), (%s, %s, 'track', 1, true, true), "
                        "(%s, %s, 'out', 1, true, true)",
                        (self.track, self.posts[0], self.track, self.posts[1], self.track, self.posts[2]))
            cur.execute("INSERT INTO mx_stories (first_at, headline) VALUES (now(), 'A reading story') RETURNING id::text")
            self.story = cur.fetchone()[0]
            cur.execute("INSERT INTO mx_story_posts (story_id, post_id, role, reason) VALUES (%s, %s, 'member', 'test')",
                        (self.story, self.posts[0]))
            conn.commit()
        self.service = PostDetailService(db_url())

    def tearDown(self):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM mx_story_posts WHERE story_id = %s", (self.story,))
            cur.execute("DELETE FROM mx_stories WHERE id = %s", (self.story,))
            cur.execute("DELETE FROM mx_track_places WHERE track_id = %s", (self.track,))
            cur.execute("DELETE FROM mx_tracks WHERE folder_id = %s", (self.track,))
            cur.execute("DELETE FROM folders WHERE id = %s", (self.track,))
            delete_scratch_sources(cur)   # posts go, with their interactions and post_seen rows
            conn.commit()

    def _values(self, post_id, kind):
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT interaction_value FROM post_interactions WHERE post_id = %s AND interaction_type = %s "
                        "ORDER BY created_at", (post_id, kind))
            return [r[0] for r in cur.fetchall()]

    # ---- 1. active time and depth ----

    def test_session_stores_active_seconds_and_depth_clamped(self):
        status, _, body = call(main.app, "POST", f"/api/posts/item/{self.posts[0]}/reading-session",
                               json_body={"durationSeconds": 120, "activeSeconds": 300, "depth": 1.4,
                                          "metadata": {"title": "Post 0"}})
        self.assertEqual(status, 200, body)
        [value] = self._values(self.posts[0], "reading_session")
        self.assertEqual(value["duration_seconds"], 120)
        self.assertEqual(value["active_seconds"], 120, "active time is never more than the time open")
        self.assertEqual(value["depth"], 1.0)
        self.assertEqual(value["title"], "Post 0")

    def test_old_style_session_keeps_duration_alone(self):
        status, _, _ = call(main.app, "POST", f"/api/posts/item/{self.posts[0]}/reading-session",
                            json_body={"durationSeconds": 8})
        self.assertEqual(status, 200)
        self.assertEqual(self._values(self.posts[0], "reading_session"), [{"duration_seconds": 8}])
        self.assertEqual(self.service.get_post_reader_state(self.posts[0])["total_read_seconds"], 8)

    def test_long_read_counts_active_time_when_measured(self):
        # open 10 minutes, active 20 s: no long read; an old row of 10 minutes still is one
        self.service.record_reading_session(self.posts[0], duration_seconds=600, active_seconds=20)
        self.service.record_reading_session(self.posts[1], duration_seconds=600)
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            acts = personal._acts(cur, datetime.now(timezone.utc) - timedelta(hours=1))
        long_reads = {pid for pid, act, _ in acts if act == "long_read"}
        self.assertNotIn(self.posts[0], long_reads)
        self.assertIn(self.posts[1], long_reads)

    # ---- 2. the original opened ----

    def test_opened_source_is_recorded_and_counts_as_history(self):
        status, _, body = call(main.app, "POST", f"/api/posts/item/{self.posts[2]}/opened-source",
                               json_body={"url": "https://example.com/original"})
        self.assertEqual(status, 200, body)
        self.assertEqual(self._values(self.posts[2], "opened_source"), [{"url": "https://example.com/original"}])
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute(f"SELECT {HISTORY_SQL} FROM posts p WHERE p.id = %s", (self.posts[2],))
            self.assertTrue(cur.fetchone()[0], "History lists a post whose original was opened")
        state = self.service.get_post_reader_state(self.posts[2])
        self.assertEqual(state["open_count"], 0, "open_count still counts the post page's opens")
        self.assertIsNone(state["read_at"], "opening the original does not mark the post read")

    def test_opened_source_refuses_a_non_web_address_and_an_unknown_post(self):
        status, _, _ = call(main.app, "POST", f"/api/posts/item/{self.posts[0]}/opened-source",
                            json_body={"url": "javascript:alert(1)"})
        self.assertEqual(status, 400)
        status, _, _ = call(main.app, "POST", f"/api/posts/item/{uuid.uuid4()}/opened-source",
                            json_body={"url": "https://example.com/"})
        self.assertEqual(status, 404)

    # ---- 3. seen ----

    def test_seen_counts_one_row_per_post_surface_and_day(self):
        items = [{"post": self.posts[0], "surface": "feed"}, {"post": self.posts[0], "surface": "feed"},
                 {"post": self.posts[0], "surface": "news"}, {"post": self.posts[1], "surface": "track"},
                 {"post": str(uuid.uuid4()), "surface": "feed"}]   # a post not stored is skipped
        status, _, body = call(main.app, "POST", "/api/reading/seen", json_body={"items": items})
        self.assertEqual(status, 200, body)
        call(main.app, "POST", "/api/reading/seen", json_body={"items": items[:1]})
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("SELECT post_id::text, surface, count, day = (now() AT TIME ZONE 'UTC')::date, first_at <= last_at "
                        "FROM post_seen WHERE post_id = ANY(%s::uuid[]) ORDER BY surface", (self.posts,))
            rows = cur.fetchall()
        self.assertEqual(rows, [(self.posts[0], "feed", 3, True, True), (self.posts[0], "news", 1, True, True),
                                (self.posts[1], "track", 1, True, True)])

    def test_seen_refuses_an_unknown_surface_and_a_bad_id(self):
        status, _, _ = call(main.app, "POST", "/api/reading/seen",
                            json_body={"items": [{"post": self.posts[0], "surface": "sidebar"}]})
        self.assertEqual(status, 400)
        status, _, _ = call(main.app, "POST", "/api/reading/seen", json_body={"items": [{"post": "x", "surface": "feed"}]})
        self.assertEqual(status, 400)

    # ---- 5. the summary ----

    def test_summary_by_day_source_track_story_and_seen(self):
        self.service.record_post_open(self.posts[0])
        self.service.record_reading_session(self.posts[0], duration_seconds=300, active_seconds=90, depth=0.75)
        self.service.record_source_open(self.posts[0], "https://example.com/a")
        self.service.record_post_open(self.posts[2])
        self.service.record_reading_session(self.posts[2], duration_seconds=40)   # an old-style row
        self.service.record_seen([(self.posts[0], "feed"), (self.posts[1], "track"), (self.posts[1], "feed")])

        status, _, body = call(main.app, "GET", "/api/reading/summary", query={"days": "7"})
        self.assertEqual(status, 200, body)
        rows = {r["post_id"]: r for r in body["posts"] if r["post_id"] in self.posts}
        self.assertEqual(set(rows), {self.posts[0], self.posts[2]})
        first = rows[self.posts[0]]
        self.assertEqual((first["title"], first["active_seconds"], first["open_seconds"], first["depth"],
                          first["source_opened"]), ("Post 0", 90, 300, 0.75, True))
        self.assertEqual([t["id"] for t in first["tracks"]], [self.track])
        self.assertEqual(rows[self.posts[2]]["active_seconds"], None, "an old row has no active time")
        self.assertEqual(rows[self.posts[2]]["open_seconds"], 40)

        source = next(s for s in body["by_source"] if s["id"] == self.source)
        self.assertEqual((source["posts"], source["active_seconds"], source["originals_opened"]), (2, 90, 1))
        track = next(t for t in body["by_track"] if t["id"] == self.track)
        self.assertEqual(track["posts"], 1, "a post the track left out (place 'out') is not the track's")
        story = next(s for s in body["by_story"] if s["id"] == self.story)
        self.assertEqual((story["name"], story["posts"]), ("A reading story", 1))

        seen = next(s for s in body["seen_by_source"] if s["id"] == self.source)
        self.assertEqual((seen["seen"], seen["opened"]), (2, 1))
        seen_track = next(t for t in body["seen_by_track"] if t["id"] == self.track)
        self.assertEqual((seen_track["seen"], seen_track["opened"]), (2, 1))

    def test_summary_is_bounded_by_its_window(self):
        self.service.record_post_open(self.posts[0])
        with psycopg.connect(db_url()) as conn, conn.cursor() as cur:
            cur.execute("UPDATE post_interactions SET created_at = now() - interval '10 days' WHERE post_id = %s",
                        (self.posts[0],))
            cur.execute("INSERT INTO post_seen (day, post_id, surface) VALUES ((now() - interval '10 days')::date, %s, 'feed')",
                        (self.posts[1],))
            conn.commit()
        week = self.service.reading_summary(7)
        self.assertNotIn(self.posts[0], {r["post_id"] for r in week["posts"]})
        self.assertNotIn(self.source, {s["id"] for s in week["seen_by_source"]})
        month = self.service.reading_summary(30)
        self.assertIn(self.posts[0], {r["post_id"] for r in month["posts"]})
        self.assertIn(self.source, {s["id"] for s in month["seen_by_source"]})
        self.assertIn(self.posts[0], {r["post_id"] for r in self.service.reading_summary(None)["posts"]})
        status, _, _ = call(main.app, "GET", "/api/reading/summary", query={"days": "week"})
        self.assertEqual(status, 400)
        status, body_all = call(main.app, "GET", "/api/reading/summary", query={"days": "all"})[:2]
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
