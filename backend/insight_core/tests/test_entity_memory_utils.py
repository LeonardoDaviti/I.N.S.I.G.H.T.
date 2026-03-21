import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.utils.entity_memory import build_post_memory_fields, extract_entity_mentions


class EntityMemoryUtilityTests(unittest.TestCase):
    def test_build_post_memory_fields_populates_original_and_pivot_text(self):
        fields = build_post_memory_fields(
            {
                "title": "Codex Memory Test Org announces a release",
                "content": "The release is available today.",
                "content_html": "<p>The release is available today.</p>",
            }
        )

        self.assertEqual(fields["title_original"], "Codex Memory Test Org announces a release")
        self.assertEqual(fields["body_original"], "The release is available today.")
        self.assertEqual(fields["title_pivot"], "codex memory test org announces a release")
        self.assertTrue(fields["summary_pivot"])

    def test_extract_entity_mentions_is_conservative(self):
        mentions = extract_entity_mentions(
            {
                "title": "Codex Memory Test Org launches with @codexmemorytest",
                "content": "Ada Memory Test and OpenAI are not the same as IDE.",
                "content_html": "<p>Ada Memory Test and OpenAI are not the same as IDE.</p>",
                "language_code": "en",
                "source": "https://example.com/feed",
            }
        )

        normalized = {item["normalized_mention"] for item in mentions}
        self.assertIn("codex memory test org", normalized)
        self.assertIn("codexmemorytest", normalized)
        self.assertIn("ada memory test", normalized)
        self.assertIn("openai", normalized)
        self.assertNotIn("the", normalized)
        self.assertNotIn("ide", normalized)


if __name__ == "__main__":
    unittest.main()
