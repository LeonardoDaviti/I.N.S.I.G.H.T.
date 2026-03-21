import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.utils.event_memory import build_post_event_fields, extract_event_candidates


class EventMemoryUtilityTests(unittest.TestCase):
    def test_build_post_event_fields_returns_candidates(self):
        fields = build_post_event_fields(
            {
                "title": "OpenAI launches a new model with Microsoft",
                "content": "The launch follows a new partnership announcement.",
                "content_html": "<p>The launch follows a new partnership announcement.</p>",
            }
        )

        self.assertIn("event_candidates", fields)
        self.assertTrue(fields["event_candidates"])

    def test_extract_event_candidates_is_conservative(self):
        candidates = extract_event_candidates(
            {
                "title": "OpenAI launches a new model with Microsoft",
                "content": "The launch follows a new partnership announcement.",
                "content_html": "<p>The launch follows a new partnership announcement.</p>",
                "language_code": "en",
            }
        )

        self.assertTrue(candidates)
        self.assertEqual(candidates[0]["event_type"], "release_launch")
        self.assertGreater(candidates[0]["confidence"], 0.0)


if __name__ == "__main__":
    unittest.main()
