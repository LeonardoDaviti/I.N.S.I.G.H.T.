"""The shared helpers (utils/json_safe, utils/env, strip_html): one copy each, and what each
caller relied on before they were collapsed."""
import os
import unittest
from datetime import date, datetime, timezone
from unittest import mock

from insight_core.utils.content_fingerprints import strip_html
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

    def test_keep_leaves_entities(self):
        self.assertEqual(strip_html(self.HTML), "Fish &amp; chips &lt;b&gt;bold&lt;/b&gt;")

    def test_decode_decodes_after_the_tags_go(self):
        self.assertEqual(strip_html(self.HTML, entities="decode"), "Fish & chips <b>bold</b>")

    def test_decode_first_also_drops_escaped_tags(self):
        self.assertEqual(strip_html(self.HTML, entities="decode_first"), "Fish & chips bold")

    def test_nothing_is_empty(self):
        self.assertEqual(strip_html(None), "")


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
