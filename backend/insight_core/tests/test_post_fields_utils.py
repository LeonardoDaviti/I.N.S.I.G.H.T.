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

    def test_one_post_has_one_normalized_url_however_the_link_is_written(self):
        """Issue 0049: a fragment, utm_ tags, http, www. and a trailing slash name the same post."""
        forms = [
            "https://simonwillison.net/2026/Aug/10/openclaw/#atom-everything",
            "https://simonwillison.net/2026/Aug/10/openclaw/",
            "https://simonwillison.net/2026/Aug/10/openclaw/?utm_source=rss",
            "http://www.simonwillison.net/2026/Aug/10/openclaw",
        ]
        self.assertEqual({normalize_url(form) for form in forms},
                         {"https://simonwillison.net/2026/Aug/10/openclaw"})

    def test_a_fragment_that_is_the_address_is_kept(self):
        self.assertEqual(normalize_url("https://app.test/#!/post/1"), "https://app.test/#!/post/1")
        self.assertEqual(normalize_url("https://app.test/#/post/2"), "https://app.test/#/post/2")
        self.assertNotEqual(normalize_url("https://app.test/#!/post/1"), normalize_url("https://app.test/#!/post/2"))

    def test_a_link_whose_port_is_not_a_number_is_not_an_address(self):
        """Found on the server's data: one post's link read "http://host:  some text", and the
        ValueError it raised stopped the whole story job."""
        self.assertIsNone(normalize_url("http://example.com:  Good morning, this is prose/"))
        self.assertIsNone(extract_url_host("http://example.com:abc/x"))
        self.assertEqual(normalize_url("https://example.com:8443/x"), "https://example.com:8443/x")

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
        self.assertEqual(display_title("", "  Release   notes\nMore text"), "Release notes")
        self.assertEqual(display_title(None, None), "")

    def test_a_title_cut_by_its_source_is_the_body_first_line(self):
        body = "Update the claude-api skill: a new default model, build-eval and hillclimb guides (#1930)\n\n* details"
        self.assertEqual(display_title("Update the claude-api skill: a new default model, …", body),
                         "Update the claude-api skill: a new default model, build-eval and hillclimb guides (#1930)")

    def test_a_title_cut_with_brackets_by_the_telegram_bridge_is_the_body_first_line(self):
        # tg.i-c-a.su cuts titles with " [...]" (turboproject, 2026-10-21).
        body = "🤖 Забавный диалог произошел у канцлера Германии Мерца с Хуангом насчет «суверенного ей».\n\nДальше текст."
        for cut in ("🤖 Забавный диалог произошел у канцлера Германии Мерца с Хуангом насчет «суверенного е [...]",
                    "🤖 Забавный диалог произошел у канцлера Германии Мерца с Хуангом насчет «суверенного е […]"):
            self.assertEqual(display_title(cut, body),
                             "🤖 Забавный диалог произошел у канцлера Германии Мерца с Хуангом насчет «суверенного ей».")

    def test_a_title_the_bridge_glued_from_two_lines_ends_where_the_first_line_did(self):
        """Server data, 2026-10-30: the Telegram bridge joins a post's lines with no space ("SpaceXДатацентр"),
        the stored body keeps it; 3,360 titles. The first line ends where the space is missing."""
        body = "Anthropic арендуют Colossus у SpaceX Датацентр Маска на 200+ тысяч видеокарт в итоге оказался не нужен"
        self.assertEqual(display_title("Anthropic арендуют Colossus у SpaceXДатацентр Маска на 200+ тысяч [...]", body),
                         "Anthropic арендуют Colossus у SpaceX")
        body = "Mistral выпустили Le Chaton Fat Le Chonk Mistral Large 4 это модель на триллион параметров"
        self.assertEqual(display_title("Mistral выпустили Le Chaton Fat Le ChonkMistral Large 4 это [...]", body),
                         "Mistral выпустили Le Chaton Fat Le Chonk")
        self.assertEqual(display_title("🌸Релизим Muse Glimmer 30B 🌸Впервые за [...]",
                                       "🌸 Релизим Muse Glimmer 30B 🌸 Впервые за долгое время"),
                         "🌸 Релизим Muse Glimmer 30B 🌸", "a leading emoji's space is not the line's end")
        self.assertEqual(display_title("A short note [...]", "A short note that goes on"), "A short note that goes on",
                         "a cut title with every space kept is the body's first line, as before")

    def test_a_placeholder_title_is_empty_so_the_text_says_what_the_post_is(self):
        """Issue 0069 (R5): placeholders told by shape, never by a list of phrases per site."""
        self.assertEqual(display_title("[Photo]", "А теперь наша любимая рубрика..."), "А теперь наша любимая рубрика...")
        self.assertEqual(display_title("[Video]", ""), "[Video]", "a post with no words keeps its placeholder")
        self.assertEqual(display_title("RT by @steipete: Image", "jason (@jxnlco) Post your best codex billboard"),
                         "jason (@jxnlco) Post your best codex billboard")
        self.assertEqual(display_title("R to @badlogicgames: Gif", ""), "Gif")
        self.assertEqual(display_title("R to @pankajkumar_dev: x.com/pankajkumar_dev/status…",
                                       "nitter.net/pankajkumar_dev/status… Pankaj Kumar (@pankajkumar_dev) Gemini 4 Carbon is out."),
                         "Pankaj Kumar (@pankajkumar_dev) Gemini 4 Carbon is out.", "a self-quote reads as the quoted words")
        self.assertEqual(display_title("https://lean-lang.org/eval/", "https://lean-lang.org/eval/ Lean Evaluating provers"),
                         "Lean Evaluating provers", "a shared link reads as its preview's words")
        self.assertEqual(display_title("https://github.com/sqlc-dev/sqlc is pretty sweet", ""),
                         "https://github.com/sqlc-dev/sqlc is pretty sweet", "an address inside a sentence stays")
        self.assertEqual(display_title("Video games I loved", "Body."), "Video games I loved")

    def test_a_reply_loses_nitters_prefix(self):
        self.assertEqual(display_title("R to @pankajkumar_dev: Gemini 4 Carbon*", "Gemini 4 Carbon*"), "Gemini 4 Carbon*")

    def test_a_short_unfinished_first_line_runs_on_to_the_sentence_end(self):
        tibo = ("RT by @badlogicgames: Day 25/\n\nWe are doubling all usage limits for all Pro 100/200/500 tiers and "
                "Business Premium, effective today.\n\nWe heard your kind feedback and won’t be reducing usage limits.")
        self.assertEqual(display_title(tibo, "Day 25/ We are doubling"),
                         "Day 25/ We are doubling all usage limits for all Pro 100/200/500 tiers and Business Premium, effective today.")
        self.assertEqual(display_title("Привет!\nКак дела у всех сегодня?", ""), "Привет!", "a finished line stands")
        self.assertEqual(display_title("Ghostty 1.4", "The release notes."), "Ghostty 1.4", "a one-line title stands")

    def test_a_whole_title_glued_from_two_lines_ends_where_the_first_line_did(self):
        """seeallochnaya/4011: the bridge glued two lines into a title it did not cut."""
        body = ("🤖 OpenAI удвоила лимиты во всех тарифах Pro – за $100, $200 и $500 Изменения уже действуют. "
                "Заодно отменили сокращение лимитов")
        self.assertEqual(display_title("🤖 OpenAI удвоила лимиты во всех тарифах Pro – за $100, $200 и $500Изменения уже действуют.", body),
                         "🤖 OpenAI удвоила лимиты во всех тарифах Pro – за $100, $200 и $500")
        # A space a tag left in the body is no line break.
        self.assertEqual(display_title("Huge thanks @_akhaliq! 🙌", "Huge thanks @_akhaliq ! 🙌"), "Huge thanks @_akhaliq! 🙌")
        self.assertEqual(display_title("Те, кто знают тест «Смит ест спагетти».", "Те , кто знают тест « Смит ест спагетти »."),
                         "Те, кто знают тест «Смит ест спагетти».")

    def test_plain_text_is_never_read_as_html(self):
        # Stored titles and bodies are plain text, already decoded: "<T>" is text, not a tag.
        self.assertEqual(display_title("Option<T> in Rust", ""), "Option<T> in Rust")
        self.assertEqual(display_title("", "Use <details> for spoilers\nmore"), "Use <details> for spoilers")
        self.assertEqual(display_title("That&#39;s it", ""), "That's it", "codes left by older saves")

    def test_a_long_cjk_line_is_cut_hard_at_117(self):
        self.assertEqual(display_title("字" * 300, ""), "字" * 117 + "…")


if __name__ == "__main__":
    unittest.main()
