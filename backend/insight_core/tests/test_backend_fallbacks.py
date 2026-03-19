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

        summary, model, tags = service._generate_summary({
            "title": "Test post",
            "content": "Some content",
            "source": "test-source",
        })

        self.assertEqual(summary, "## Summary\nUseful signal.")
        self.assertEqual(model, "gemini-test")
        self.assertEqual(tags, ["ai", "research"])

    def test_generate_summary_fallback_uses_generated_tags_in_markdown(self):
        service = PostDetailService("postgresql:///unused")

        class FakeProcessor:
            def setup_processor(self):
                return False

        service.processor = FakeProcessor()

        summary, model, tags = service._generate_summary({
            "title": "Nitter post",
            "content": "A short note about model training.",
            "source": "karpathy",
            "platform": "rss",
            "categories": [],
        })

        self.assertEqual(model, "fallback")
        self.assertEqual(tags, ["rss", "ai"])
        self.assertIn("The post is tagged with: rss, ai.", summary)


if __name__ == "__main__":
    unittest.main()
