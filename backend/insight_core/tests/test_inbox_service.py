import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import psycopg

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.repo_posts import PostsRepository
from insight_core.services.analyst_actions_service import AnalystActionsService
from insight_core.services.inbox_service import InboxService
from insight_core.services.sources_service import SourcesService
from insight_core.services.stories_service import StoriesService


DATABASE_URL = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")


@unittest.skipIf(not DATABASE_URL, "No DATABASE_URL found, skipping database tests")
class InboxServiceTests(unittest.TestCase):
    def setUp(self):
        self.suffix = uuid4().hex[:8]
        self.actor_id = f"inbox-test-{self.suffix}"
        self.source_handle = f"https://inbox-test-{self.suffix}.example.com/feed"
        self.repo_posts = PostsRepository(DATABASE_URL)
        self.sources_service = SourcesService(DATABASE_URL)
        self.stories_service = StoriesService(DATABASE_URL)
        self.inbox_service = InboxService(DATABASE_URL, stories_service=self.stories_service)
        self.actions_service = AnalystActionsService(DATABASE_URL, stories_service=self.stories_service)

        self.now = datetime.now(timezone.utc).replace(microsecond=0)
        self.story_title = f"Inbox story {self.suffix}"
        self.story_followup_title = f"{self.story_title} update"
        self.fresh_post_title = f"Inbox fresh post {self.suffix}"
        self.old_post_title = f"Inbox old post {self.suffix}"

        self._cleanup_existing_rows()
        self._seed_source()
        self._seed_posts_and_story()

    def tearDown(self):
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM analyst_actions WHERE actor_id = %s OR created_by = %s", (self.actor_id, self.actor_id))
                cur.execute("DELETE FROM inbox_batches WHERE metadata->>'generated_by' = %s", (self.actor_id,))
                cur.execute("DELETE FROM stories WHERE canonical_title = %s", (self.story_title,))
                cur.execute(
                    "DELETE FROM posts WHERE title IN (%s, %s, %s, %s)",
                    (self.story_title, self.story_followup_title, self.fresh_post_title, self.old_post_title),
                )
                cur.execute("DELETE FROM sources WHERE handle_or_url = %s", (self.source_handle,))
                conn.commit()

    def _cleanup_existing_rows(self):
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM analyst_actions WHERE actor_id = %s OR created_by = %s", (self.actor_id, self.actor_id))
                cur.execute("DELETE FROM inbox_batches WHERE metadata->>'generated_by' = %s", (self.actor_id,))
                cur.execute("DELETE FROM stories WHERE canonical_title = %s", (self.story_title,))
                cur.execute(
                    "DELETE FROM posts WHERE title IN (%s, %s, %s, %s)",
                    (self.story_title, self.story_followup_title, self.fresh_post_title, self.old_post_title),
                )
                cur.execute("DELETE FROM sources WHERE handle_or_url = %s", (self.source_handle,))
                conn.commit()

    def _seed_source(self):
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

        self.sources_service.update_source_settings(
            self.source_id,
            {
                "display_name": "Inbox Test Source",
                "priority": 1,
                "fetch_delay_seconds": 1,
                "max_posts_per_fetch": 50,
            },
        )

    def _seed_posts_and_story(self):
        story_anchor = {
            "url": f"https://inbox-test-{self.suffix}.example.com/posts/story-anchor",
            "title": self.story_title,
            "content": "The story anchor article.",
            "content_html": "<p>The story anchor article.</p>",
            "date": self.now - timedelta(hours=2),
            "external_id": f"{self.suffix}-story-anchor",
            "media_urls": [],
            "categories": [],
            "metadata": {},
        }
        story_followup = {
            "url": f"https://inbox-test-{self.suffix}.example.com/posts/story-followup",
            "title": self.story_followup_title,
            "content": "A follow-up update on the story.",
            "content_html": "<p>A follow-up update on the story.</p>",
            "date": self.now - timedelta(hours=1),
            "external_id": f"{self.suffix}-story-followup",
            "media_urls": [],
            "categories": [],
            "metadata": {},
        }
        fresh_post = {
            "url": f"https://inbox-test-{self.suffix}.example.com/posts/fresh",
            "title": self.fresh_post_title,
            "content": "A fresh post that should remain in the queue.",
            "content_html": "<p>A fresh post that should remain in the queue.</p>",
            "date": self.now - timedelta(minutes=30),
            "external_id": f"{self.suffix}-fresh",
            "media_urls": [],
            "categories": [],
            "metadata": {},
        }
        old_post = {
            "url": f"https://inbox-test-{self.suffix}.example.com/posts/old",
            "title": self.old_post_title,
            "content": "An old post that should fall below the novelty threshold.",
            "content_html": "<p>An old post that should fall below the novelty threshold.</p>",
            "date": self.now - timedelta(days=10),
            "external_id": f"{self.suffix}-old",
            "media_urls": [],
            "categories": [],
            "metadata": {},
        }

        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                self.story_anchor_post_id, _ = self.repo_posts.upsert_post(cur, story_anchor, self.source_id)
                self.story_followup_post_id, _ = self.repo_posts.upsert_post(cur, story_followup, self.source_id)
                self.fresh_post_id, _ = self.repo_posts.upsert_post(cur, fresh_post, self.source_id)
                self.old_post_id, _ = self.repo_posts.upsert_post(cur, old_post, self.source_id)
                conn.commit()

        created = self.stories_service.create_story(
            canonical_title=self.story_title,
            canonical_summary="A story used to verify inbox ranking and dedupe.",
            story_kind="release",
            status="active",
            anchor_post_id=self.story_anchor_post_id,
            anchor_confidence=0.93,
            first_seen_at=self.now - timedelta(hours=2),
            last_seen_at=self.now - timedelta(hours=1),
            created_by_method="manual",
            resolution_version="test-v1",
            metadata={"seed": True},
            post_ids=[self.story_anchor_post_id],
        )
        self.story_id = created["story_id"]

        self.stories_service.create_story_update(
            self.story_id,
            self.now.date(),
            "Story update for inbox ranking",
            "A follow-up update ensures the story is both new and materially updated.",
            importance_score=0.91,
            created_by_method="manual",
            metadata={"seed": True},
            post_ids=[self.story_followup_post_id],
        )

    def _get_batch_item(self, batch_payload, target_type: str, target_id: str):
        for item in batch_payload["items"]:
            if item["target_type"] == target_type and str(item["target_id"]) == target_id:
                return item
        return None

    def test_rebuild_dedupes_story_signals_and_ranks_story_above_post(self):
        batch_payload = self.inbox_service.rebuild_inbox(
            generated_for_date=self.now.date(),
            scope_type="daily_queue",
            actor_id=self.actor_id,
            limit=100,
        )

        self.assertTrue(batch_payload["success"])
        story_item = self._get_batch_item(batch_payload, "story", self.story_id)
        fresh_item = self._get_batch_item(batch_payload, "post", self.fresh_post_id)
        old_item = self._get_batch_item(batch_payload, "post", self.old_post_id)

        self.assertIsNotNone(story_item)
        self.assertIsNotNone(fresh_item)
        self.assertIsNone(old_item)
        self.assertGreater(story_item["priority_score"], fresh_item["priority_score"])
        self.assertIn("New story", story_item["reason_summary"])
        self.assertIn("Material update", story_item["reason_summary"])
        signal_codes = {reason["code"] for reason in story_item["reasons"]}
        self.assertIn("new_story", signal_codes)
        self.assertIn("story_update", signal_codes)

    def test_accept_action_logs_audit_and_updates_item_status(self):
        batch_payload = self.inbox_service.rebuild_inbox(
            generated_for_date=self.now.date(),
            scope_type="daily_queue",
            actor_id=self.actor_id,
            limit=100,
        )
        fresh_item = self._get_batch_item(batch_payload, "post", self.fresh_post_id)
        self.assertIsNotNone(fresh_item)

        action_result = self.actions_service.record_action(
            fresh_item["id"],
            "accept",
            actor_id=self.actor_id,
            payload={"note": "kept for review"},
        )

        self.assertTrue(action_result["success"])
        self.assertEqual(action_result["action"]["action_type"], "accept")
        self.assertEqual(action_result["item"]["status"], "accepted")
        self.assertEqual(action_result["item"]["metadata"]["last_action_type"], "accept")

        actions = self.actions_service.list_actions(target_type="post", target_id=self.fresh_post_id)
        self.assertEqual(actions["total"], 1)
        self.assertEqual(actions["actions"][0]["action_type"], "accept")

    def test_block_source_disables_source_and_records_side_effect(self):
        batch_payload = self.inbox_service.rebuild_inbox(
            generated_for_date=self.now.date(),
            scope_type="daily_queue",
            actor_id=self.actor_id,
            limit=100,
        )
        fresh_item = self._get_batch_item(batch_payload, "post", self.fresh_post_id)
        self.assertIsNotNone(fresh_item)

        action_result = self.actions_service.record_action(
            fresh_item["id"],
            "block_source",
            actor_id=self.actor_id,
            payload={"reason": "noise"},
        )

        self.assertTrue(action_result["success"])
        self.assertGreaterEqual(len(action_result["side_effects"]), 1)
        self.assertEqual(action_result["item"]["status"], "blocked_source")
        self.assertEqual(action_result["item"]["metadata"]["blocked_source_id"], self.source_id)
        self.assertEqual(action_result["side_effects"][0]["type"], "source_blocked")

        source = self.sources_service.get_source_by_id(self.source_id)
        self.assertIsNotNone(source)
        self.assertFalse(source["enabled"])

    def test_list_items_supports_filters_for_queue_navigation(self):
        batch_payload = self.inbox_service.rebuild_inbox(
            generated_for_date=self.now.date(),
            scope_type="daily_queue",
            actor_id=self.actor_id,
            limit=100,
        )
        batch_id = batch_payload["batch"]["id"]

        story_items = self.inbox_service.list_items(
            batch_id=batch_id,
            status="pending",
            target_type="story",
            source_id=self.source_id,
            generated_for_date=self.now.date(),
            limit=20,
            offset=0,
        )
        post_items = self.inbox_service.list_items(
            batch_id=batch_id,
            status="pending",
            target_type="post",
            source_id=self.source_id,
            generated_for_date=self.now.date(),
            limit=20,
            offset=0,
        )

        self.assertTrue(story_items["success"])
        self.assertTrue(post_items["success"])
        self.assertEqual(story_items["total"], 1)
        self.assertGreaterEqual(post_items["total"], 1)
        self.assertTrue(all(item["target_type"] == "story" for item in story_items["items"]))
        self.assertTrue(all(item["target_type"] == "post" for item in post_items["items"]))
        self.assertTrue(all(item["batch_generated_for_date"] == self.now.date() for item in story_items["items"]))
        self.assertTrue(all(item["batch_generated_for_date"] == self.now.date() for item in post_items["items"]))
        self.assertTrue(all(item["metadata"]["candidate"]["source_id"] == self.source_id for item in story_items["items"]))
        self.assertTrue(all(item["metadata"]["candidate"]["source_id"] == self.source_id for item in post_items["items"]))


if __name__ == "__main__":
    unittest.main()
