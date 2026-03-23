import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_posts import PostsRepository
from insight_core.services.briefing_service import BriefingService


DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping database tests")
class VerticalBriefingServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        self.source_handle = f"https://vertical-test-{self.suffix}.example.com/feed"
        self.source_display_name = f"Vertical Briefing Source {self.suffix}"
        self.repo_posts = PostsRepository(DATABASE_URL)
        self.service = BriefingService(DATABASE_URL)
        self.service.processor.setup_processor = lambda: False

        self.start_date = "2026-03-01"
        self.end_date = "2026-03-31"
        self.start_day = datetime(2026, 3, 1, tzinfo=timezone.utc)
        self.subject_key = None

        self.side_title = f"Vertical side note {self.suffix}"
        self.outlier_title = f"Vertical outlier {self.suffix}"
        self._cleanup_existing_rows()
        self._seed_source_and_posts()

    def tearDown(self):
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM briefings WHERE payload->>'source_label' = %s", (self.source_display_name,))
                cur.execute("DELETE FROM posts WHERE title IN (%s, %s, %s, %s, %s, %s)", self.seed_titles)
                cur.execute("DELETE FROM sources WHERE handle_or_url = %s", (self.source_handle,))
                conn.commit()

    def _cleanup_existing_rows(self):
        self.seed_titles = (
            f"Autoresearch {self.suffix} alpha",
            f"Autoresearch {self.suffix} beta",
            f"Agentic engineering {self.suffix} alpha",
            f"Agentic engineering {self.suffix} beta",
            self.side_title,
            self.outlier_title,
        )
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM briefings WHERE payload->>'source_label' = %s", (self.source_display_name,))
                cur.execute("DELETE FROM posts WHERE title IN (%s, %s, %s, %s, %s, %s)", self.seed_titles)
                cur.execute("DELETE FROM sources WHERE handle_or_url = %s", (self.source_handle,))
                conn.commit()

    def _seed_source_and_posts(self):
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO sources (platform, handle_or_url, enabled, settings)
                    VALUES ('rss', %s, TRUE, '{}'::jsonb)
                    RETURNING id
                    """,
                    (self.source_handle,),
                )
                self.source_id = str(cur.fetchone()[0])
                conn.commit()

        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                self.repo_posts.upsert_post(
                    cur,
                    {
                        "url": f"https://vertical-test-{self.suffix}.example.com/posts/autoresearch-1",
                        "title": self.seed_titles[0],
                        "content": "Autoresearch keeps pushing on the same project thread.",
                        "content_html": "<p>Autoresearch keeps pushing on the same project thread.</p>",
                        "date": datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc),
                        "external_id": f"{self.suffix}-auto-1",
                        "media_urls": [],
                        "categories": [],
                        "metadata": {},
                    },
                    self.source_id,
                )
                self.repo_posts.upsert_post(
                    cur,
                    {
                        "url": f"https://vertical-test-{self.suffix}.example.com/posts/autoresearch-2",
                        "title": self.seed_titles[1],
                        "content": "Autoresearch adds a follow-up update on the same thread.",
                        "content_html": "<p>Autoresearch adds a follow-up update on the same thread.</p>",
                        "date": datetime(2026, 3, 14, 12, 0, tzinfo=timezone.utc),
                        "external_id": f"{self.suffix}-auto-2",
                        "media_urls": [],
                        "categories": [],
                        "metadata": {},
                    },
                    self.source_id,
                )
                self.repo_posts.upsert_post(
                    cur,
                    {
                        "url": f"https://vertical-test-{self.suffix}.example.com/posts/agentic-1",
                        "title": self.seed_titles[2],
                        "content": "Agentic engineering work returns to the same build process.",
                        "content_html": "<p>Agentic engineering work returns to the same build process.</p>",
                        "date": datetime(2026, 3, 7, 12, 0, tzinfo=timezone.utc),
                        "external_id": f"{self.suffix}-agent-1",
                        "media_urls": [],
                        "categories": [],
                        "metadata": {},
                    },
                    self.source_id,
                )
                self.repo_posts.upsert_post(
                    cur,
                    {
                        "url": f"https://vertical-test-{self.suffix}.example.com/posts/agentic-2",
                        "title": self.seed_titles[3],
                        "content": "A second agentic engineering update lands later in the month.",
                        "content_html": "<p>A second agentic engineering update lands later in the month.</p>",
                        "date": datetime(2026, 3, 20, 12, 0, tzinfo=timezone.utc),
                        "external_id": f"{self.suffix}-agent-2",
                        "media_urls": [],
                        "categories": [],
                        "metadata": {},
                    },
                    self.source_id,
                )
                self.repo_posts.upsert_post(
                    cur,
                    {
                        "url": f"https://vertical-test-{self.suffix}.example.com/posts/side-note",
                        "title": self.side_title,
                        "content": "A single off-thread note that should remain isolated.",
                        "content_html": "<p>A single off-thread note that should remain isolated.</p>",
                        "date": datetime(2026, 3, 25, 12, 0, tzinfo=timezone.utc),
                        "external_id": f"{self.suffix}-side-note",
                        "media_urls": [],
                        "categories": [],
                        "metadata": {},
                    },
                    self.source_id,
                )
                self.repo_posts.upsert_post(
                    cur,
                    {
                        "url": f"https://vertical-test-{self.suffix}.example.com/posts/outlier",
                        "title": self.outlier_title,
                        "content": "This post falls outside the requested date range.",
                        "content_html": "<p>This post falls outside the requested date range.</p>",
                        "date": datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc),
                        "external_id": f"{self.suffix}-outlier",
                        "media_urls": [],
                        "categories": [],
                        "metadata": {},
                    },
                    self.source_id,
                )
                conn.commit()

        self.service.sources_service.update_source_settings(
            self.source_id,
            {
                "display_name": self.source_display_name,
                "priority": 1,
                "fetch_delay_seconds": 1,
                "max_posts_per_fetch": 50,
            },
        )
        self.subject_key = f"source:{self.source_id}:{self.start_date}:{self.end_date}"

    def test_posts_by_source_and_range_filters_to_requested_window(self):
        posts = self.service.posts_service.get_posts_by_source_and_range(
            self.source_id,
            datetime(2026, 3, 1, tzinfo=timezone.utc).date(),
            datetime(2026, 3, 31, tzinfo=timezone.utc).date(),
        )

        self.assertEqual(len(posts), 5)
        self.assertTrue(all(post["source_id"] == self.source_id for post in posts))
        self.assertEqual([post["title"] for post in posts][:2], [self.seed_titles[0], self.seed_titles[2]])
        self.assertIn(self.side_title, [post["title"] for post in posts])
        self.assertNotIn(self.outlier_title, [post["title"] for post in posts])

    async def test_generate_source_vertical_briefing_uses_fallback_and_cache(self):
        result = await self.service.generate_source_vertical_briefing(
            self.source_id,
            self.start_date,
            self.end_date,
            refresh=False,
        )

        self.assertTrue(result["success"])
        self.assertFalse(result["cached"])
        self.assertEqual(result["subject_key"], self.subject_key)
        self.assertEqual(result["posts_processed"], 5)
        self.assertEqual(result["total_posts_fetched"], 5)
        self.assertGreaterEqual(len(result["tracks"]), 3)
        self.assertIn(self.source_display_name, result["vertical_briefing"])

        track_titles = [track["title"] for track in result["tracks"]]
        self.assertTrue(any("Autoresearch" in title for title in track_titles))
        self.assertTrue(any("Agentic" in title for title in track_titles))
        self.assertTrue(any(track["track_kind"] == "one_off_update" for track in result["tracks"]))

        all_post_ids = {
            post_id
            for track in result["tracks"]
            for post_id in track["post_ids"]
        }
        self.assertEqual(len(all_post_ids), 5)

        cached = await self.service.generate_source_vertical_briefing(
            self.source_id,
            self.start_date,
            self.end_date,
            refresh=False,
        )

        self.assertTrue(cached["success"])
        self.assertTrue(cached["cached"])
        self.assertEqual(cached["saved_briefing_id"], result["saved_briefing_id"])
        self.assertEqual(cached["subject_key"], self.subject_key)

    async def test_generate_source_vertical_briefing_without_dates_uses_full_stored_range(self):
        result = await self.service.generate_source_vertical_briefing(
            self.source_id,
            None,
            None,
            refresh=True,
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["start_date"], "2026-03-03")
        self.assertEqual(result["end_date"], "2026-04-02")
        self.assertEqual(result["posts_processed"], 6)
        self.assertIn(self.outlier_title, [post.get("title") for post in result["posts"].values()])


if __name__ == "__main__":
    unittest.main()
