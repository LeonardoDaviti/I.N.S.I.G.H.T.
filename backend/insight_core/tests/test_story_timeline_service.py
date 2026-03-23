import unittest

from backend.insight_core.services.story_timeline_service import StoryTimelineService


class StoryTimelineServiceTests(unittest.TestCase):
    def test_score_candidate_accepts_strong_same_url_signal(self):
        service = StoryTimelineService("postgresql:///unused")
        source_post = {
            "id": "post-1",
            "title": "DeepSeek OCR release",
            "content": "DeepSeek released the OCR paper with benchmark details.",
            "published_at": "2026-03-21T12:00:00+00:00",
            "canonical_url": "https://example.com/deepseek-ocr",
            "normalized_url": "https://example.com/deepseek-ocr",
            "content_hash": "hash-a",
            "title_hash": "title-a",
            "url_host": "example.com",
            "categories": ["ai", "research"],
        }
        candidate = {
            "id": "post-2",
            "title": "Reaction to DeepSeek OCR release",
            "content": "People discuss the same DeepSeek OCR release.",
            "published_at": "2026-03-22T12:00:00+00:00",
            "canonical_url": "https://example.com/deepseek-ocr",
            "normalized_url": "https://example.com/deepseek-ocr",
            "content_hash": "hash-b",
            "title_hash": "title-b",
            "url_host": "example.com",
            "categories": ["ai"],
            "candidate_story_id": None,
        }

        result = service._score_candidate(source_post, candidate, primary_story_id="story-1")

        self.assertIsNotNone(result)
        self.assertEqual(result["decision_status"], "accepted")
        self.assertEqual(result["candidate_story_id"], "story-1")
        self.assertEqual(result["retrieval_method"], "same_normalized_url")
        self.assertGreaterEqual(result["retrieval_score"], 0.98)

    def test_score_candidate_filters_weak_topical_cousin(self):
        service = StoryTimelineService("postgresql:///unused")
        source_post = {
            "id": "post-1",
            "title": "OpenAI ships new policy memo",
            "content": "Policy memo about safety review.",
            "published_at": "2026-03-21T12:00:00+00:00",
            "canonical_url": "https://example.com/policy-memo",
            "normalized_url": "https://example.com/policy-memo",
            "url_host": "example.com",
            "categories": ["policy"],
        }
        candidate = {
            "id": "post-2",
            "title": "General AI industry roundup",
            "content": "A broad recap of many companies.",
            "published_at": "2026-03-29T12:00:00+00:00",
            "canonical_url": "https://another.example.com/roundup",
            "normalized_url": "https://another.example.com/roundup",
            "url_host": "another.example.com",
            "categories": ["news"],
            "candidate_story_id": None,
        }

        result = service._score_candidate(source_post, candidate, primary_story_id=None)

        self.assertIsNone(result)

    def test_build_timeline_view_splits_earlier_current_and_later_updates(self):
        service = StoryTimelineService("postgresql:///unused")
        story_detail = {
            "id": "story-1",
            "timeline": [
                {
                    "id": "update-1",
                    "update_date": "2026-03-20",
                    "title": "Initial release",
                    "summary": "The story starts.",
                    "posts": [{"post_id": "post-a", "post": {"title": "Initial release post"}}],
                },
                {
                    "id": "update-2",
                    "update_date": "2026-03-21",
                    "title": "Current update",
                    "summary": "The current post lands here.",
                    "posts": [{"post_id": "post-current", "post": {"title": "Current post"}}],
                },
                {
                    "id": "update-3",
                    "update_date": "2026-03-23",
                    "title": "Follow-up",
                    "summary": "The story continues.",
                    "posts": [{"post_id": "post-c", "post": {"title": "Follow-up post"}}],
                },
            ],
        }

        result = service._build_timeline_view(story_detail, "post-current")

        self.assertEqual(result["current_update"]["id"], "update-2")
        self.assertEqual([item["id"] for item in result["earlier_updates"]], ["update-1"])
        self.assertEqual([item["id"] for item in result["later_updates"]], ["update-3"])
        self.assertEqual(result["total_updates"], 3)


if __name__ == "__main__":
    unittest.main()
