import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.utils.artifact_extraction import extract_artifacts
from insight_core.utils.evidence import build_post_evidence_fields
from insight_core.utils.language_detection import detect_language
from insight_core.utils.url_normalization import extract_url_host, normalize_url


class EvidenceFoundationUtilityTests(unittest.TestCase):
    def test_url_normalization_strips_tracking_params_and_lowercases_host(self):
        normalized = normalize_url("https://Example.com/path/?utm_source=newsletter&b=2&a=1#frag")
        host = extract_url_host("https://Example.com/path/?utm_source=newsletter&b=2&a=1#frag")

        self.assertEqual(normalized, "https://example.com/path?a=1&b=2")
        self.assertEqual(host, "example.com")

    def test_youtube_normalization_collapses_short_links(self):
        normalized = normalize_url("https://youtu.be/dQw4w9WgXcQ?t=30")

        self.assertEqual(normalized, "https://youtube.com/watch?v=dQw4w9WgXcQ")

    def test_language_detection_handles_english_russian_and_georgian(self):
        english = detect_language("The system is working and the results are clear.")
        russian = detect_language("Это хороший пример текста для проверки языка.")
        georgian = detect_language("ეს არის კარგი მაგალითი ენის ამოცნობისთვის.")

        self.assertEqual(english["language_code"], "en")
        self.assertEqual(russian["language_code"], "ru")
        self.assertEqual(georgian["language_code"], "ka")
        self.assertGreater(english["confidence"], 0.5)
        self.assertGreater(russian["confidence"], 0.5)
        self.assertGreater(georgian["confidence"], 0.5)

    def test_artifact_extraction_identifies_primary_and_linked_artifacts(self):
        post = {
            "platform": "rss",
            "title": "Release notes for the new model",
            "content": "See the repo https://github.com/openai/openai-codex and the paper https://arxiv.org/abs/2401.00001",
            "content_html": "<p>See the repo <a href=\"https://github.com/openai/openai-codex\">repo</a></p>",
            "url": "https://example.com/release-notes",
        }

        artifacts = extract_artifacts(post)

        self.assertGreaterEqual(len(artifacts), 2)
        self.assertEqual(artifacts[0]["relation_type"], "announces")
        self.assertEqual(artifacts[0]["artifact_type"], "article")
        self.assertTrue(any(item["artifact_type"] == "repo" for item in artifacts))
        self.assertTrue(any(item["artifact_type"] == "paper" for item in artifacts))

    def test_post_evidence_builder_populates_expected_fields(self):
        evidence = build_post_evidence_fields(
            {
                "url": "https://Example.com/path/?utm_source=newsletter",
                "title": "The system is working",
                "content": "And the results are clear.",
                "content_html": "<p>And the results are clear.</p>",
            }
        )

        self.assertEqual(evidence["normalized_url"], "https://example.com/path")
        self.assertEqual(evidence["canonical_url"], "https://example.com/path")
        self.assertTrue(evidence["title_hash"])
        self.assertEqual(evidence["language_code"], "en")
        self.assertEqual(evidence["normalization_version"], "evidence-foundation-v1")
        self.assertIsNotNone(evidence["enriched_at"])


if __name__ == "__main__":
    unittest.main()
