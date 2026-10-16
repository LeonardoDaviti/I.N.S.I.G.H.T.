import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.utils.post_fields import build_post_fields, display_title
from insight_core.utils.language_detection import detect_language
from insight_core.utils.url_normalization import extract_url_host, normalize_url


class PostFieldsUtilityTests(unittest.TestCase):
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

    def test_post_fields_builder_populates_expected_fields(self):
        fields = build_post_fields(
            {
                "url": "https://Example.com/path/?utm_source=newsletter",
                "title": "The system is working",
                "content": "And the results are clear.",
                "content_html": "<p>And the results are clear.</p>",
            }
        )

        self.assertEqual(fields["normalized_url"], "https://example.com/path")
        self.assertEqual(fields["canonical_url"], "https://example.com/path")
        self.assertTrue(fields["content_hash"])
        self.assertEqual(fields["language_code"], "en")


class DisplayTitleTests(unittest.TestCase):
    def test_a_tweet_with_a_bullet_list_is_its_first_line(self):
        tweet = "Three things we shipped today:\n\n- faster search\n- dark mode\n- " + "more " * 60
        self.assertEqual(display_title(tweet, tweet), "Three things we shipped today:")

    def test_a_long_sentence_is_cut_at_a_word_with_an_ellipsis(self):
        line = "word " * 40
        title = display_title(line, "")
        self.assertTrue(title.endswith("word…"), title)
        self.assertLessEqual(len(title), 120)

    def test_a_first_sentence_within_the_limit_is_the_title(self):
        line = "OpenAI ships a new model today. " + "It is faster and cheaper than the last one, and more. " * 3
        self.assertEqual(display_title(line, line), "OpenAI ships a new model today.")

    def test_a_normal_blog_title_is_unchanged(self):
        self.assertEqual(display_title("2026 in LLMs (so far)", "On Friday I gave the closing keynote."),
                         "2026 in LLMs (so far)")

    def test_an_empty_title_is_the_start_of_the_body(self):
        self.assertEqual(display_title("", "<p>Release notes</p>\nMore text"), "Release notes")
        self.assertEqual(display_title(None, None), "")

    def test_a_title_cut_by_its_source_is_the_body_first_line(self):
        body = "Update the claude-api skill: a new default model, build-eval and hillclimb guides (#1930)\n\n* details"
        self.assertEqual(display_title("Update the claude-api skill: a new default model, …", body),
                         "Update the claude-api skill: a new default model, build-eval and hillclimb guides (#1930)")

    def test_a_long_cjk_line_is_cut_hard_at_117(self):
        self.assertEqual(display_title("字" * 300, ""), "字" * 117 + "…")


if __name__ == "__main__":
    unittest.main()
