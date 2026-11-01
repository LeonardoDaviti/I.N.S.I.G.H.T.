"""The shared helpers (utils/json_safe, utils/env, strip_html): one copy each, and what each
caller relied on before they were collapsed."""
import os
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from insight_core.utils.content_fingerprints import clean_text, strip_html
from insight_core.utils.env import env_float, env_int
from insight_core.utils.json_safe import iso, json_safe


class JsonSafeTests(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(iso(datetime(2026, 3, 19, 12, 30, tzinfo=timezone.utc)), "2026-03-19T12:30:00+00:00")
        self.assertEqual(iso(date(2026, 3, 19)), "2026-03-19")
        self.assertIsNone(iso(None))

    def test_json_safe_converts_nested_times_and_keeps_the_rest(self):
        payload = {
            "started_at": datetime(2026, 3, 19, 12, 30, tzinfo=timezone.utc),
            "nested": {"history": [{"at": datetime(2026, 3, 19, 13, 45, tzinfo=timezone.utc)}],
                       "pair": (date(2026, 3, 19), 2)},
            "count": 3, "name": "x", "none": None,
        }
        self.assertEqual(json_safe(payload), {
            "started_at": "2026-03-19T12:30:00+00:00",
            "nested": {"history": [{"at": "2026-03-19T13:45:00+00:00"}], "pair": ["2026-03-19", 2]},
            "count": 3, "name": "x", "none": None,
        })


class StripHtmlTests(unittest.TestCase):
    HTML = "<p>Fish &amp; chips</p>\n<p>&lt;b&gt;bold&lt;/b&gt;</p>"

    def test_entities_are_decoded_once_the_tags_go(self):
        self.assertEqual(strip_html(self.HTML), "Fish & chips <b>bold</b>")
        self.assertEqual(strip_html("<p>That&#39;s &quot;it&quot;</p>"), 'That\'s "it"')

    def test_double_escaped_text_is_decoded_too(self):
        # As stored on the preview: "the world&amp;#39;s number one".
        self.assertEqual(strip_html("the world&amp;#39;s number one"), "the world's number one")

    def test_decode_first_also_drops_escaped_tags(self):
        self.assertEqual(strip_html(self.HTML, entities="decode_first"), "Fish & chips bold")

    def test_tags_go_before_codes_are_decoded(self):
        # An escaped tag in HTML is text the author wrote: it survives as text.
        self.assertEqual(strip_html("<p>Use &lt;details&gt; here</p>"), "Use <details> here")

    def test_a_quoted_greater_than_sign_does_not_end_the_tag(self):
        # Issue 0072: a utility class's ">" left 'a]:hidden">' in front of the stored text.
        self.assertEqual(strip_html('<h1 class="max-md:[&amp;>a]:hidden"><span>A title</span></h1>'), "A title")
        self.assertEqual(strip_html("<a title='x > y' href=/p>Read</a>"), "Read")
        self.assertEqual(strip_html("<!-- it's a > note --><p>Hello, it's me</p>"), "Hello, it's me")

    def test_a_tag_that_cant_be_read_ends_at_its_first_bracket_as_before(self):
        self.assertEqual(strip_html("<a title=don't>here</a> and 'there'"), "here and 'there'")
        self.assertEqual(strip_html("1 < 2 and 3 > 2"), "1 2")

    def test_the_content_hash_keeps_its_rule(self):
        # decode_first is part of every stored hash: the first ">" still ends a tag there.
        self.assertEqual(strip_html('<h1 class="[&>a]">T</h1>', entities="decode_first"), 'a]">T')

    def test_nothing_is_empty(self):
        self.assertEqual(strip_html(None), "")
        self.assertEqual(clean_text(None), "")

    def test_clean_text_decodes_plain_text_and_never_strips_tags(self):
        self.assertEqual(clean_text("  Option<T>\n in &amp; out "), "Option<T> in & out")


class EnvTests(unittest.TestCase):
    def _with(self, value):
        env = {} if value is None else {"INSIGHT_TEST_KNOB": value}
        return mock.patch.dict(os.environ, env, clear=False)

    def test_a_number_is_read(self):
        with self._with("7"):
            self.assertEqual((env_int("INSIGHT_TEST_KNOB", 3), env_float("INSIGHT_TEST_KNOB", 3.0)), (7, 7.0))

    def test_unset_empty_or_garbage_is_the_default(self):
        os.environ.pop("INSIGHT_TEST_KNOB", None)
        for value in (None, "", "seven"):
            with self.subTest(value=value), self._with(value):
                self.assertEqual(env_int("INSIGHT_TEST_KNOB", 3), 3)
                self.assertEqual(env_float("INSIGHT_TEST_KNOB", 0.5), 0.5)

    def test_minimum_clamps_a_set_value(self):
        with self._with("-4"):
            self.assertEqual(env_int("INSIGHT_TEST_KNOB", 3, minimum=1), 1)
            self.assertEqual(env_float("INSIGHT_TEST_KNOB", 3.0, minimum=0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
