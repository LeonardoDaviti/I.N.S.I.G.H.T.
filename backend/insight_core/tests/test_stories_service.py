import os
import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_posts import PostsRepository
from insight_core.db.repo_stories import StoriesRepository
from insight_core.services.stories_service import StoriesService


DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping database tests")
class StoriesStorageTests(unittest.TestCase):
    def setUp(self):
        self.source_handle = "https://stories-test.example.com/feed"
        self.repo_posts = PostsRepository(DATABASE_URL)
        self.repo_stories = StoriesRepository(DATABASE_URL)
        self.service = StoriesService(DATABASE_URL)
        self.story_title = "OpenAI ships a small model update"

        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM stories WHERE canonical_title = %s", (self.story_title,))
                cur.execute("DELETE FROM sources WHERE handle_or_url = %s", (self.source_handle,))
                conn.commit()

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

        self.post_payloads = [
            {
                "url": "https://stories-test.example.com/posts/1",
                "title": "OpenAI ships a small model update",
                "content": "OpenAI released a small model update.",
                "content_html": "<p>OpenAI released a small model update.</p>",
                "date": datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
                "external_id": "stories-test-1",
                "media_urls": [],
                "categories": [],
                "metadata": {},
            },
            {
                "url": "https://stories-test.example.com/posts/2",
                "title": "Commentary follows OpenAI release",
                "content": "Analysts discuss the update.",
                "content_html": "<p>Analysts discuss the update.</p>",
                "date": datetime(2026, 3, 21, 14, 0, tzinfo=timezone.utc),
                "external_id": "stories-test-2",
                "media_urls": [],
                "categories": [],
                "metadata": {},
            },
        ]

        self.post_ids = []
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                for payload in self.post_payloads:
                    post_id, _ = self.repo_posts.upsert_post(cur, payload, self.source_id)
                    self.post_ids.append(post_id)
                conn.commit()

        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                self.story_id = self.repo_stories.insert_story(
                    cur,
                    {
                        "canonical_title": self.story_title,
                        "canonical_summary": "A release story used to verify storage.",
                        "story_kind": "release",
                        "status": "active",
                        "anchor_post_id": self.post_ids[0],
                        "anchor_confidence": 0.91,
                        "first_seen_at": datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
                        "last_seen_at": datetime(2026, 3, 21, 14, 0, tzinfo=timezone.utc),
                        "created_by_method": "manual",
                        "resolution_version": "test-v1",
                        "metadata": {"seed": True},
                    },
                )
                self.repo_stories.upsert_story_post(
                    cur,
                    self.story_id,
                    self.post_ids[0],
                    role="anchor",
                    relevance_score=1.0,
                    anchor_score=1.0,
                    is_anchor_candidate=True,
                    evidence_weight=1.0,
                    added_by_method="manual",
                )
                self.repo_stories.upsert_story_post(
                    cur,
                    self.story_id,
                    self.post_ids[1],
                    role="commentary",
                    relevance_score=0.65,
                    anchor_score=0.12,
                    is_anchor_candidate=False,
                    evidence_weight=0.45,
                    added_by_method="manual",
                )
                self.update_id = self.repo_stories.insert_story_update(
                    cur,
                    {
                        "story_id": self.story_id,
                        "update_date": date(2026, 3, 21),
                        "title": "Release and commentary appear the same day",
                        "summary": "The release was observed and commentary followed later in the day.",
                        "importance_score": 0.88,
                        "created_by_method": "manual",
                        "metadata": {"seed": True},
                    },
                )
                self.repo_stories.upsert_story_update_post(cur, self.update_id, self.post_ids[0], role="anchor")
                self.repo_stories.upsert_story_update_post(cur, self.update_id, self.post_ids[1], role="context")
                conn.commit()

    def tearDown(self):
        story_id = getattr(self, "story_id", None)
        source_id = getattr(self, "source_id", None)
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                if story_id:
                    cur.execute("DELETE FROM stories WHERE id = %s", (story_id,))
                if source_id:
                    cur.execute("DELETE FROM sources WHERE id = %s", (source_id,))
                conn.commit()

    def test_repository_returns_story_detail(self):
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                story = self.repo_stories.get_story_by_id(cur, self.story_id)
                posts = self.repo_stories.get_story_posts(cur, self.story_id)
                updates = self.repo_stories.get_story_updates(cur, self.story_id)
                update_posts = self.repo_stories.get_story_update_posts(cur, self.update_id)
                by_post = self.repo_stories.get_stories_for_post(cur, self.post_ids[0])

        self.assertIsNotNone(story)
        self.assertEqual(story["id"], self.story_id)
        self.assertEqual(story["anchor_post_id"], self.post_ids[0])
        self.assertEqual(story["post_count"], 2)
        self.assertEqual(story["update_count"], 1)
        self.assertEqual(len(posts), 2)
        self.assertEqual(posts[0]["role"], "anchor")
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["post_count"], 2)
        self.assertEqual(len(update_posts), 2)
        self.assertEqual(by_post[0]["id"], self.story_id)
        self.assertEqual(by_post[0]["role"], "anchor")

    def test_service_returns_nested_story_payloads(self):
        detail = self.service.get_story_detail(self.story_id)
        timeline = self.service.get_story_timeline(self.story_id)
        post_story = self.service.get_post_story(self.post_ids[0])
        created = self.service.create_story(
            canonical_title="Service created story",
            canonical_summary="Created by the service wrapper.",
            story_kind="analysis",
            status="active",
            anchor_post_id=self.post_ids[0],
            anchor_confidence=0.75,
            first_seen_at=datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc),
            last_seen_at=datetime(2026, 3, 21, 14, 0, tzinfo=timezone.utc),
            created_by_method="manual",
            resolution_version="test-v1",
            metadata={"created_via": "service"},
            post_ids=[self.post_ids[0], self.post_ids[1]],
        )

        try:
            self.assertIsNotNone(detail)
            self.assertEqual(detail["id"], self.story_id)
            self.assertEqual(detail["post_count"], 2)
            self.assertIn("anchor", detail["posts_by_role"])
            self.assertEqual(len(detail["updates"]), 1)
            self.assertEqual(timeline["story"]["id"], self.story_id)
            self.assertEqual(len(timeline["timeline"]), 1)
            self.assertEqual(post_story["primary_story"]["id"], self.story_id)
            self.assertEqual(created["canonical_title"], "Service created story")
        finally:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM stories WHERE id = %s", (created["story_id"],))
                    conn.commit()


if __name__ == "__main__":
    unittest.main()
