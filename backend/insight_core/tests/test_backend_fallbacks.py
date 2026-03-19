import unittest
from datetime import datetime, timezone

from backend.insight_core.db.repo_sources import SourcesRepository
from backend.insight_core.processors.ai.gemini_processor import GeminiProcessor
from backend.insight_core.services.briefing_service import BriefingService
from backend.insight_core.services.post_detail_service import PostDetailService


class GeminiProcessorFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_briefing_falls_back_when_generation_fails(self):
        processor = GeminiProcessor()
        processor.is_setup = True
        processor.api_key = "test"

        async def fail_generate(prompt):
            raise RuntimeError("quota exceeded")

        processor._generate_text = fail_generate
        posts = [
            {
                "source": "https://nitter.local/karpathy/rss",
                "title": "AI agents are rewriting IDE expectations",
                "content": "The basic unit of work is shifting toward agent teams.",
                "date": "2026-03-11T20:22:27+04:00",
            }
        ]

        briefing = await processor.daily_briefing(posts)

        self.assertIn("## Executive Summary", briefing)
        self.assertIn("## Main Developments", briefing)
        self.assertIn("## Signals To Watch", briefing)
        self.assertIn("karpathy", briefing)

    async def test_topic_briefing_falls_back_when_generation_fails(self):
        processor = GeminiProcessor()
        processor.is_setup = True
        processor.api_key = "test"

        async def fail_generate(prompt):
            raise RuntimeError("quota exceeded")

        processor._generate_text = fail_generate
        posts = [
            {
                "source": "https://telegram.local/rss/denissexy",
                "title": "OpenClaw thread support shipped",
                "content": "Telegram bots can now segment agent work into forum topics.",
                "date": "2026-03-09T00:54:48+04:00",
            },
            {
                "source": "https://telegram.local/rss/denissexy",
                "title": "China drafts subsidies for OpenClaw deployments",
                "content": "Local policy support is moving up the stack toward agents.",
                "date": "2026-03-09T15:35:40+04:00",
            },
        ]

        result = await processor.topic_briefing_with_numeric_ids(posts)

        self.assertIn("daily_briefing", result)
        self.assertEqual(len(result["topics"]), 1)
        self.assertEqual(result["topics"][0]["post_ids"], ["1", "2"])

    async def test_weekly_briefing_falls_back_when_generation_fails(self):
        processor = GeminiProcessor()
        processor.is_setup = True
        processor.api_key = "test"

        async def fail_generate(prompt):
            raise RuntimeError("quota exceeded")

        processor._generate_text = fail_generate

        result = await processor.weekly_briefing(
            "2026-03-16 to 2026-03-22",
            [
                {
                    "date": "2026-03-17",
                    "briefing": "## Executive Summary\nLocal model updates accelerated.",
                    "posts_processed": 12,
                },
                {
                    "date": "2026-03-18",
                    "briefing": "## Executive Summary\nOpen-source tooling matured further.",
                    "posts_processed": 8,
                },
            ],
        )

        self.assertIn("## Executive Weekly Summary", result)
        self.assertIn("## Major Developments", result)
        self.assertIn("2026-03-17", result)

    async def test_weekly_topic_briefing_falls_back_when_generation_fails(self):
        processor = GeminiProcessor()
        processor.is_setup = True
        processor.api_key = "test"

        async def fail_generate(prompt):
            raise RuntimeError("quota exceeded")

        processor._generate_text = fail_generate

        result = await processor.weekly_topic_briefing(
            "2026-03-16 to 2026-03-22",
            [
                {
                    "date": "2026-03-17",
                    "briefing": "## Daily Topic Briefing",
                    "topics": [
                        {
                            "title": "RLVR",
                            "summary": "RLVR was a recurring theme.",
                            "post_ids": ["post-1", "post-2"],
                        }
                    ],
                }
            ],
        )

        self.assertIn("weekly_briefing", result)
        self.assertEqual(result["topics"][0]["title"], "RLVR")


class SourcesRepositoryJsonSafeTests(unittest.TestCase):
    def test_make_json_safe_converts_nested_datetimes(self):
        repo = SourcesRepository("postgresql:///unused")
        payload = {
            "archive": {
                "last_archived_at": datetime(2026, 3, 11, 22, 23, 14, tzinfo=timezone.utc),
                "history": [
                    {"at": datetime(2026, 3, 11, 22, 26, 13, tzinfo=timezone.utc)},
                ],
            }
        }

        result = repo._make_json_safe(payload)

        self.assertEqual(result["archive"]["last_archived_at"], "2026-03-11T22:23:14+00:00")
        self.assertEqual(result["archive"]["history"][0]["at"], "2026-03-11T22:26:13+00:00")


class BriefingServiceFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_daily_briefing_falls_back_when_connect_fails(self):
        service = BriefingService("postgresql:///unused")

        class FakePostsService:
            def get_posts_by_date(self, target_date):
                return [
                    {
                        "id": "1",
                        "source": "https://nitter.local/karpathy/rss",
                        "title": "Agent update",
                        "content": "Agents are getting more capable.",
                        "date": "2026-03-12T00:00:00+00:00",
                    }
                ]

        class FakeStoreService:
            def save_briefing(self, **kwargs):
                return {"id": "briefing-1"}

        class FakeProcessor:
            def setup_processor(self):
                return True

            async def connect(self):
                raise RuntimeError("missing google.genai")

            async def disconnect(self):
                return None

            def _fallback_daily_briefing(self, posts):
                return "## Executive Summary\nFallback"

        service.posts_service = FakePostsService()
        service.store_service = FakeStoreService()
        service.processor = FakeProcessor()

        result = await service.generate_daily_briefing("2026-03-12")

        self.assertTrue(result["success"])
        self.assertEqual(result["briefing"], "## Executive Summary\nFallback")
        self.assertEqual(result["format"], "markdown")
        self.assertEqual(result["saved_briefing_id"], "briefing-1")

    async def test_generate_daily_briefing_falls_back_when_setup_fails(self):
        service = BriefingService("postgresql:///unused")

        class FakePostsService:
            def get_posts_by_date(self, target_date):
                return [
                    {
                        "id": "1",
                        "source": "r/LocalLLaMA",
                        "title": "Local model update",
                        "content": "New local model benchmark results arrived.",
                        "date": "2026-03-12T00:00:00+00:00",
                    }
                ]

        class FakeStoreService:
            def save_briefing(self, **kwargs):
                return {"id": "briefing-2"}

        class FakeProcessor:
            def setup_processor(self):
                return False

            async def disconnect(self):
                return None

            def _fallback_daily_briefing(self, posts):
                return "## Executive Summary\nNo key fallback"

        service.posts_service = FakePostsService()
        service.store_service = FakeStoreService()
        service.processor = FakeProcessor()

        result = await service.generate_daily_briefing("2026-03-12")

        self.assertTrue(result["success"])
        self.assertEqual(result["briefing"], "## Executive Summary\nNo key fallback")
        self.assertEqual(result["saved_briefing_id"], "briefing-2")

    async def test_generate_topic_briefing_uses_cached_payload_without_regenerating(self):
        service = BriefingService("postgresql:///unused")

        class FakePostsService:
            def get_posts_by_date(self, target_date):
                return [
                    {
                        "id": "post-1",
                        "source": "https://karpathy.bearblog.dev/feed/",
                        "title": "Cached topic source",
                        "content": "RLVR is gaining momentum.",
                        "date": "2026-03-12T00:00:00+00:00",
                    }
                ]

        class FakeStoreService:
            def get_briefing(self, subject_type, subject_key, variant="default"):
                return {
                    "id": "briefing-topics-1",
                    "render_format": "markdown",
                    "content": "## Cached Topic Briefing",
                    "payload": {
                        "topics": [
                            {"id": "topic-1", "title": "RLVR", "summary": "cached", "post_ids": ["post-1"]},
                        ],
                        "unreferenced_posts": [],
                    },
                }

        class FakeTopicsService:
            def topics_exist_for_date(self, target_date):
                return True

            def get_topics_by_date(self, target_date):
                return [
                    {"id": "topic-1", "title": "RLVR", "summary": "cached", "is_outlier": False},
                ]

            def get_posts_for_topic(self, topic_id):
                return [{"id": "post-1"}]

        class FakeProcessor:
            def setup_processor(self):
                raise AssertionError("Processor should not be called when cached topic briefing exists")

        service.posts_service = FakePostsService()
        service.store_service = FakeStoreService()
        service.topics_service = FakeTopicsService()
        service.processor = FakeProcessor()

        result = await service.generate_daily_briefing_with_topics("2026-03-12")

        self.assertTrue(result["success"])
        self.assertTrue(result["cached"])
        self.assertEqual(result["briefing"], "## Cached Topic Briefing")
        self.assertEqual(result["topics"][0]["post_ids"], ["post-1"])

    async def test_generate_weekly_briefing_uses_cached_payload_without_regenerating(self):
        service = BriefingService("postgresql:///unused")

        class FakeStoreService:
            def get_briefing(self, subject_type, subject_key, variant="default"):
                if subject_type == "weekly_briefing":
                    return {
                        "id": "weekly-1",
                        "render_format": "markdown",
                        "content": "## Executive Weekly Summary\nCached weekly view",
                        "payload": {
                            "days_covered": ["2026-03-16", "2026-03-17"],
                            "daily_briefings_used": 2,
                            "estimated_tokens": 123,
                        },
                    }
                raise AssertionError("Daily briefing lookup should not happen when weekly cache exists")

        service.store_service = FakeStoreService()

        result = await service.generate_weekly_briefing("2026-03-18")

        self.assertTrue(result["success"])
        self.assertTrue(result["cached"])
        self.assertEqual(result["briefing"], "## Executive Weekly Summary\nCached weekly view")
        self.assertEqual(result["daily_briefings_used"], 2)

    async def test_generate_weekly_topic_briefing_uses_cached_payload_without_regenerating(self):
        service = BriefingService("postgresql:///unused")

        class FakeStoreService:
            def get_briefing(self, subject_type, subject_key, variant="default"):
                if subject_type == "weekly_briefing" and variant == "topics":
                    return {
                        "id": "weekly-topics-1",
                        "render_format": "markdown",
                        "content": "## Weekly Topic Briefing",
                        "payload": {
                            "days_covered": ["2026-03-16", "2026-03-17"],
                            "daily_briefings_used": 2,
                            "estimated_tokens": 111,
                            "topics": [
                                {
                                    "id": "weekly-topic-1",
                                    "title": "RLVR",
                                    "summary": "Weekly RLVR thread",
                                    "post_ids": ["post-1"],
                                    "timeline": [
                                        {"date": "2026-03-16", "summary": "Start", "post_ids": ["post-1"]},
                                    ],
                                }
                            ],
                        },
                    }
                return None

        class FakePostsService:
            def get_posts_by_ids(self, post_ids):
                return [
                    {
                        "id": "post-1",
                        "source": "https://karpathy.bearblog.dev/feed/",
                        "title": "RLVR weekly anchor",
                        "content": "RLVR matured.",
                        "platform": "rss",
                    }
                ]

        class FakeProcessor:
            def setup_processor(self):
                raise AssertionError("Processor should not be called when cached weekly topic briefing exists")

        service.store_service = FakeStoreService()
        service.posts_service = FakePostsService()
        service.processor = FakeProcessor()

        result = await service.generate_weekly_topic_briefing("2026-03-18")

        self.assertTrue(result["success"])
        self.assertTrue(result["cached"])
        self.assertEqual(result["variant"], "topics")
        self.assertEqual(result["topics"][0]["title"], "RLVR")


class PostDetailServiceTests(unittest.TestCase):
    def test_generate_summary_uses_model_from_processor_result(self):
        service = PostDetailService("postgresql:///unused")

        class FakeProcessor:
            def setup_processor(self):
                return True

            def analyze_single_post(self, post):
                return {
                    "success": True,
                    "summary": "## Summary\nUseful signal.",
                    "tags": ["ai", "research"],
                    "model": "gemini-test",
                }

        service.processor = FakeProcessor()

        summary, model, tags, estimated_tokens = service._generate_summary({
            "title": "Test post",
            "content": "Some content",
            "source": "test-source",
        })

        self.assertEqual(summary, "## Summary\nUseful signal.")
        self.assertEqual(model, "gemini-test")
        self.assertEqual(tags, ["ai", "research"])
        self.assertGreater(estimated_tokens, 0)

    def test_generate_summary_fallback_uses_generated_tags_in_markdown(self):
        service = PostDetailService("postgresql:///unused")

        class FakeProcessor:
            def setup_processor(self):
                return False

        service.processor = FakeProcessor()

        summary, model, tags, estimated_tokens = service._generate_summary({
            "title": "Nitter post",
            "content": "A short note about model training.",
            "source": "karpathy",
            "platform": "rss",
            "categories": [],
        })

        self.assertEqual(model, "fallback")
        self.assertEqual(tags, ["rss", "ai"])
        self.assertIn("The post is tagged with: rss, ai.", summary)
        self.assertGreater(estimated_tokens, 0)

    def test_generate_reddit_comments_briefing_uses_model_from_processor_result(self):
        service = PostDetailService("postgresql:///unused")

        class FakeProcessor:
            def setup_processor(self):
                return True

            def summarize_reddit_comments(self, post, comments):
                return {
                    "success": True,
                    "summary": "## Discussion Briefing\nConsensus emerged.",
                    "signals": ["consensus", "recommendations"],
                    "model": "gemini-comments",
                }

        service.processor = FakeProcessor()

        summary, model, signals, estimated_tokens = service._generate_reddit_comments_briefing(
            {"title": "Reddit thread", "source": "r/test"},
            [{"author": "a", "body": "Useful", "score": 10, "depth": 0}],
        )

        self.assertEqual(summary, "## Discussion Briefing\nConsensus emerged.")
        self.assertEqual(model, "gemini-comments")
        self.assertEqual(signals, ["consensus", "recommendations"])
        self.assertGreater(estimated_tokens, 0)


class PostDetailDiscussionTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_reddit_comments_uses_cached_metadata_without_refetch(self):
        service = PostDetailService("postgresql:///unused")
        service.get_post_by_id = lambda post_id: {
            "id": post_id,
            "platform": "reddit",
            "url": "https://reddit.com/r/test/comments/abc/thread/",
            "metadata": {
                "reddit_discussion": {
                    "limit": 80,
                    "fetched_at": "2026-03-19T12:00:00+00:00",
                    "comments": [{"id": "c1", "body": "cached"}],
                }
            },
        }

        class FakeFetchService:
            async def fetch_reddit_comments_for_post(self, post_url, limit=80):
                raise AssertionError("Should not refetch when cached discussion exists")

        service.source_fetch_service = FakeFetchService()

        result = await service.fetch_reddit_comments("post-1", limit=40, refresh=False)

        self.assertTrue(result["cached"])
        self.assertEqual(result["comment_count"], 1)
        self.assertEqual(result["comments"][0]["body"], "cached")


if __name__ == "__main__":
    unittest.main()
