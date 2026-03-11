import unittest
from datetime import datetime, timezone

from backend.insight_core.db.repo_sources import SourcesRepository
from backend.insight_core.processors.ai.gemini_processor import GeminiProcessor


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


if __name__ == "__main__":
    unittest.main()
