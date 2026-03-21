import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.services.evidence_foundation_service import EvidenceFoundationService


class EvidenceFoundationServiceTests(unittest.TestCase):
    def test_build_post_evidence_uses_deterministic_utilities(self):
        service = EvidenceFoundationService("postgresql:///unused")
        evidence = service.build_post_evidence(
            {
                "url": "https://example.com/article",
                "title": "A Small Update",
                "content": "The system is working as expected.",
                "content_html": "<p>The system is working as expected.</p>",
            }
        )

        self.assertEqual(evidence["normalized_url"], "https://example.com/article")
        self.assertEqual(evidence["language_code"], "en")
        self.assertTrue(evidence["content_hash"])
        self.assertTrue(evidence["title_hash"])

    def test_detect_translation_uses_shared_artifact_signal(self):
        service = EvidenceFoundationService("postgresql:///unused")
        service._shared_artifact_ids = lambda *args, **kwargs: ["artifact-1"]

        post = {
            "published_at": datetime(2026, 3, 12, 10, 0, 0, tzinfo=timezone.utc),
            "title": "OpenAI ships a new release",
            "content": "OpenAI ships a new release",
            "content_html": "<p>OpenAI ships a new release</p>",
        }
        candidate = {
            "id": "candidate-post",
            "published_at": datetime(2026, 3, 12, 9, 0, 0, tzinfo=timezone.utc),
            "title": "OpenAI ships a new release",
            "content": "OpenAI ships a new release",
            "content_html": "<p>OpenAI ships a new release</p>",
            "language_code": "ru",
        }
        evidence = {"language_code": "en"}

        relation = service._detect_translation(None, "current-post", post, evidence, candidate, [])

        self.assertIsNotNone(relation)
        self.assertEqual(relation["relation_type"], "translation_of")
        self.assertEqual(relation["from_post_id"], "current-post")
        self.assertEqual(relation["to_post_id"], "candidate-post")


if __name__ == "__main__":
    unittest.main()
