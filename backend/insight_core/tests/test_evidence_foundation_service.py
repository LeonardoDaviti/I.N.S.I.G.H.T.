import sys
import unittest
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


if __name__ == "__main__":
    unittest.main()
