import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.utils.post_fields import (
    body_after_title, body_without_feed_lines, build_post_fields, display_title, hnrss_counts, quote_only, reading_text,
)
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
                         "Post your best codex billboard", "a quoted tweet's byline is no word (issue 0072)")
        self.assertEqual(display_title("R to @badlogicgames: Gif", ""), "Gif")
        self.assertEqual(display_title("R to @pankajkumar_dev: x.com/pankajkumar_dev/status…",
                                       "nitter.net/pankajkumar_dev/status… Pankaj Kumar (@pankajkumar_dev) Gemini 4 Carbon is out."),
                         "Gemini 4 Carbon is out.", "a self-quote reads as the quoted words, not who wrote them (0072)")
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


class TitlesLeftOpenTests(unittest.TestCase):
    # Issue 0070, B6: the titles 0069 B left open, each a class.
    def test_a_link_then_a_list_is_titled_by_the_link_and_a_list_mark_is_no_word(self):
        title = "RT by @badlogicgames: http://agentville.world\n\n> accessible for AI newcomers\n> voice chat for everything"
        self.assertEqual(display_title(title, "agentville.world > accessible for AI newcomers > voice chat"), "agentville.world")
        self.assertEqual(display_title("R to @predict_addict: • It penalizes underconfidence\n• and more", ""),
                         "It penalizes underconfidence")
        self.assertEqual(display_title("— модель станет доступна сегодня всем, кроме бесплатников.", ""),
                         "модель станет доступна сегодня всем, кроме бесплатников.")

    def test_a_title_ending_in_a_custom_emoji_keeps_it(self):
        title = "Релизы зарелижены, поэтому время показать папищекам, что я жива💀."
        body = "Релизы зарелижены, поэтому время показать папищекам, что я жива 💀 . Все подводят какие-то итоги года"
        self.assertEqual(display_title(title, body), title)
        # A glued line that starts with an emoji and has words is still a line of its own.
        self.assertEqual(display_title("🤖 OpenAI удвоила лимиты за $500🔥Изменения уже действуют.",
                                       "🤖 OpenAI удвоила лимиты за $500\n🔥Изменения уже действуют."),
                         "🤖 OpenAI удвоила лимиты за $500")

    def test_a_telegram_link_preview_is_titled_by_the_pages_title(self):
        html = ('<br/><a href="https://lnkd.in/p/x">https://lnkd.in/p/x</a><br/><br/><blockquote cite="https://lnkd.in/p/x">'
                '<cite><b>LinkedIn</b></cite></br><b>New Open-Source Glyph for Refusing Consent</b></br>I just learned that.</blockquote>')
        content = "https://lnkd.in/p/x LinkedIn New Open-Source Glyph for Refusing Consent I just learned that."
        self.assertEqual(display_title("[Media]", content), "LinkedIn New Open-Source Glyph for Refusing Consent I just learned that.")
        self.assertEqual(display_title("[Media]", content, html), "New Open-Source Glyph for Refusing Consent")
        tweet = html.replace("<b>New Open-Source Glyph for Refusing Consent</b>", "<b>Percy Liang (@percyliang)</b>")
        self.assertEqual(display_title("[Media]", content, tweet), "I just learned that.", "a tweet's preview: its words, not its author")

    def test_a_letters_abbreviation_is_no_sentence_end(self):
        title = ("SITUATION DETECTED: Major U.S. banks are detecting unauthorized AI agents operating inside customer accounts. "
                 "And more besides that goes on.")
        self.assertEqual(display_title(title, ""), "SITUATION DETECTED: Major U.S. banks are detecting unauthorized AI agents "
                                                   "operating inside customer accounts.")
        self.assertEqual(display_title("Hidden deep inside the catalogue of A. P. Kiselev. " + "x " * 80, ""),
                         "Hidden deep inside the catalogue of A. P. Kiselev.")
        self.assertEqual(display_title("A treasure of notes like this fills Kiselev's Algebra, Part I. " + "y " * 80, ""),
                         "A treasure of notes like this fills Kiselev's Algebra, Part I.", "\"I\" ends a sentence")


class TitleNotReadTwiceTests(unittest.TestCase):
    # Issue 0070: a title taken from the body isn't read twice; the body starts after it.
    def test_a_telegram_posts_first_line_leaves_its_body(self):
        content = "Свежий emergency выпуск подкаста Лекса Фридмана про AI и математику.\nТеренс Тао и другие."
        html = "<p><b>Свежий emergency выпуск подкаста Лекса Фридмана про AI и математику.</b><br/>Теренс Тао и другие.</p>"
        title, text, body = reading_text("Свежий emergency выпуск подкаста Лекса Фридмана про AI и математику. Теренс…", content, html)
        self.assertEqual(title, "Свежий emergency выпуск подкаста Лекса Фридмана про AI и математику.")
        self.assertEqual((text, body), ("Теренс Тао и другие.", "<p>Теренс Тао и другие.</p>"), "no empty bold, no break")

    def test_a_tweets_first_line_is_found_by_its_html_when_the_text_lost_its_breaks(self):
        html = '<p>Canada being &quot;at the forefront of AI&quot;</p>\n<a href="https://x.test/v"><br>Video<br></a>'
        title, text, body = reading_text('RT by @predict_addict: Canada being "at the forefront of AI"',
                                         'Canada being "at the forefront of AI" Video', html)
        self.assertEqual((title, text), ('Canada being "at the forefront of AI"', "Video"))
        self.assertEqual(body, '<a href="https://x.test/v"><br>Video<br></a>')

    def test_a_title_that_is_only_the_bodys_first_words_stays_in_it(self):
        self.assertEqual(reading_text("Notes", "Notes on X and Y", "<p>Notes on X and Y</p>")[1:],
                         ("Notes on X and Y", "<p>Notes on X and Y</p>"))
        self.assertEqual(body_after_title("Introducing Gemini 4", "Introducing Gemini 4, our model"), "Introducing Gemini 4, our model")

    def test_a_cut_title_a_whole_body_or_another_start_leave_the_body_alone(self):
        self.assertEqual(body_after_title("A long first line that goes on…", "A long first line that goes on and on.\nMore."),
                         "A long first line that goes on and on.\nMore.")
        self.assertEqual(body_after_title("All of it.", "All of it."), "All of it.")
        self.assertEqual(body_after_title("Other words.", "Different text.\nMore."), "Different text.\nMore.")

    def test_a_heading_that_repeats_the_title_goes(self):
        html = '<h1>Soft-deprecating re.match()</h1>\n<p>Python has a concept of soft deprecation.</p>'
        self.assertEqual(body_after_title("Soft-deprecating re.match()", html, html=True),
                         "<p>Python has a concept of soft deprecation.</p>")


class BridgeTitleTests(unittest.TestCase):
    """Issue 0072: a title the Telegram bridge cut ends where the post's headline ends."""

    def test_a_cut_title_ends_at_the_htmls_line_not_the_texts(self):
        html = ('<a href="https://media.test/1.jpg"><img src="https://media.test/1/thumb.jpeg"/></a><br/><br/>'
                '<b>Исследователи нашли способ тратить на 15% меньше вычислений без потери качества</b><br><br>'
                'На конференции, проходящей сейчас, представили метод.')
        text = "Исследователи нашли способ тратить на 15% меньше вычислений без потери качества На конференции, проходящей сейчас, представили метод."
        self.assertEqual(display_title("Исследователи нашли способ тратить на 15% меньше вычислений без [...]", text, html),
                         "Исследователи нашли способ тратить на 15% меньше вычислений без потери качества")

    def test_a_bold_words_space_is_no_line_end(self):
        text = "Классика: издание (американское кстати) утверждает , что недавно выпущенная модель была дистиллирована"
        self.assertEqual(display_title("Классика: издание (американское кстати) утверждает, что недавно вы [...]", text),
                         text, "not cut at 'утверждает': without the HTML the tag's space stays")
        html = 'Успех не просто <b>Kimi K3</b>, а новая архитектура.<br><br>Дальше.'
        self.assertEqual(display_title("Успех не просто Kimi K3, а новая [...]", "Успех не просто Kimi K3 , а новая архитектура. Дальше.", html),
                         "Успех не просто Kimi K3, а новая архитектура.")

    def test_a_cut_title_starts_the_text_whatever_its_spaces(self):
        html = "Meta* купила Moltbook – вирусную соцсеть для агентов<br><br>Помните, в конце января"
        self.assertEqual(display_title("Meta* купила Moltbook – вирусную соцсеть для агентовПомните, в конце янва [...]",
                                       "Meta * купила Moltbook – вирусную соцсеть для агентов Помните, в конце января", html),
                         "Meta* купила Moltbook – вирусную соцсеть для агентов")
        self.assertEqual(display_title("Расходы перешли в фазу &q [...]", 'Расходы перешли в фазу "роста" и дальше.'),
                         'Расходы перешли в фазу "роста" и дальше.', "a cut inside an HTML code")

    def test_a_title_ended_where_no_sentence_ends_is_cut_again(self):
        text = "Маск признал провал модели в программировании, т.к. она уступает конкурентам. Дальше текст."
        self.assertEqual(display_title("Маск признал провал модели в программировании, т.к.", text),
                         "Маск признал провал модели в программировании, т.к. она уступает конкурентам. Дальше текст.")
        self.assertEqual(display_title("Компания собирается выпускать модель (?", "Компания собирается выпускать модель (?) Дальше."),
                         "Компания собирается выпускать модель (?) Дальше.")
        self.assertEqual(display_title("Модель вышла.", "Модель вышла. Дальше."), "Модель вышла.", "a real end stands")


class QuoteCardTests(unittest.TestCase):
    """Issue 0072: Nitter's quote card says who is quoted and where, never the post's words."""
    ADDRESS = '<p><a href="https://nitter.net/ann/status/2115097309847630047?s=20">nitter.net/ann/status…</a></p>\n'
    CARD = ('<hr/>\n<blockquote>\n<b>Ann Lee (@ann)</b>\n<p>\n<p>Here is one more output of mine.<br>\n<br>\nThe speed is good, and I would put it above the model I used before this week for most of my daily work.</p>\n'
            '<img src="https://nitter.local/pic/a.jpg" />\n</p>\n<footer>\n— <cite><a href="https://nitter.local/ann/status/'
            '2115097309847630047#m">https://nitter.local/ann/status/2115097309847630047#m</a>\n</footer>\n</blockquote>')
    TEXT = ("nitter.net/ann/status… Ann Lee (@ann) Here is one more output of mine. The speed is good, and I would put it above the model I used before this week for most of my daily work. "
            "— https://nitter.local/ann/status/2115097309847630047#m")

    def test_a_quote_only_tweet_is_titled_and_read_by_the_quoted_words(self):
        title, text, html = reading_text("R to @ann: x.com/ann/status…", self.TEXT, self.ADDRESS + self.CARD)
        self.assertEqual(title, "Here is one more output of mine.")
        self.assertEqual(text, "The speed is good, and I would put it above the model I used before this week for most of my daily work.")
        self.assertNotIn("<footer>", html)
        self.assertNotIn("nitter.net/ann/status…", html)
        self.assertIn("<b>Ann Lee (@ann)</b>", html, "the card still says who it quotes")
        self.assertEqual(display_title("R to @ann: x.com/ann/status…", self.TEXT), "Here is one more output of mine.", "without the HTML too")

    def test_the_posts_own_words_end_where_the_quote_begins(self):
        title, text, _ = reading_text("Mogged...", "Mogged... " + self.TEXT.split(" ", 1)[1], "<p>Mogged...</p>\n" + self.CARD)
        self.assertEqual(title, "Mogged...", "not run on into the quote's byline")
        self.assertNotIn("(@ann)", text)

    def test_a_post_with_nothing_of_its_own_only_quotes(self):
        self.assertEqual(quote_only(self.ADDRESS + self.CARD), "https://x.com/ann/status/2115097309847630047")
        for own in ("<p>Its out guys.</p>\n", "<p>🫶</p>\n", '<p></p>\n<img src="https://nitter.local/pic/b.jpg" />\n'):
            self.assertIsNone(quote_only(own + self.CARD), own)
        self.assertIsNone(quote_only("<p>No quote here.</p>"))


class FeedLinesTests(unittest.TestCase):
    # Issue 0070: hnrss's four lines are a Hacker News row's counts, never its text.
    TEXT = ("Article URL: https://www.sec.gov/Archives/edgar/s1.htm Comments URL: https://news.ycombinator.com/item?id=50242939 "
            "Points: 1675 # Comments: 1628")
    HTML = ('<p>Article URL: <a href="https://www.sec.gov/s1.htm">https://www.sec.gov/s1.htm</a></p>\n'
            '<p>Comments URL: <a href="https://news.ycombinator.com/item?id=1">https://news.ycombinator.com/item?id=1</a></p>\n'
            '<p>Points: 1675</p>\n<p># Comments: 1628</p>\n')

    def test_hnrss_lines_are_counts_not_text(self):
        self.assertEqual(hnrss_counts(self.TEXT), {"points": 1675, "comments": 1628})
        self.assertEqual(hnrss_counts(self.HTML), {"points": 1675, "comments": 1628})
        self.assertEqual((body_without_feed_lines(self.TEXT), body_without_feed_lines(self.HTML)), ("", ""))

    def test_a_show_hn_keeps_its_own_words(self):
        html = "<p>Hey HN, I'm Christian.</p>\n<hr>\n" + self.HTML
        self.assertEqual(body_without_feed_lines(html), "<p>Hey HN, I'm Christian.</p>")
        self.assertEqual(body_without_feed_lines("Hey HN, I'm Christian. " + self.TEXT), "Hey HN, I'm Christian.")

    def test_another_body_is_left_alone(self):
        for body in ("Points: 3 of the plan", "<p>Article URL: none here</p>", None, ""):
            self.assertEqual(body_without_feed_lines(body), body)
            self.assertIsNone(hnrss_counts(body))


if __name__ == "__main__":
    unittest.main()
