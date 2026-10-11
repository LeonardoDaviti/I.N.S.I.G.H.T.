"""scripts/import_env_secrets: a one-off copy of old .env secrets into Connections (S6)."""
from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.scripts.import_env_secrets import import_env_secrets, main

HASH = "0123456789abcdef0123456789abcdef"
FULL_ENV = {
    "TELEGRAM_API_ID": "123456",
    "TELEGRAM_API_HASH": HASH,
    "SUBSTACK_SID": "s%3AcookieValue.abcd",
}


class FakeStore:
    def __init__(self, existing=None):
        self.values = dict(existing or {})

    def has(self, provider, key):
        return (provider, key) in self.values

    def put(self, provider, key, value):
        self.values[(provider, key)] = value


class ImportEnvSecretsTests(unittest.TestCase):
    def test_every_secret_is_copied_into_its_connection(self):
        store = FakeStore()
        stored, skipped = import_env_secrets(FULL_ENV, store)
        self.assertEqual(store.values, {
            ("telegram", "api_id"): "123456",
            ("telegram", "api_hash"): HASH,
            ("substack", "sid"): "s%3AcookieValue.abcd",
        })
        self.assertEqual(sorted(stored), sorted(FULL_ENV))
        self.assertEqual(skipped, [])

    def test_empty_values_and_placeholders_are_skipped(self):
        env = {
            "TELEGRAM_API_ID": "your_api_id",
            "TELEGRAM_API_HASH": "your_api_hash",
            "SUBSTACK_SID": "  ",
        }
        store = FakeStore()
        stored, skipped = import_env_secrets(env, store)
        self.assertEqual(store.values, {})
        self.assertEqual(stored, [])
        self.assertEqual({name for name, _reason in skipped},
                         {"TELEGRAM_API_ID", "TELEGRAM_API_HASH", "SUBSTACK_SID"})

    def test_changeme_is_a_placeholder_in_any_case(self):
        store = FakeStore()
        _, skipped = import_env_secrets({"SUBSTACK_SID": "ChangeMe"}, store)
        self.assertEqual((store.values, skipped), ({}, [("SUBSTACK_SID", "placeholder")]))

    def test_a_non_integer_telegram_api_id_is_skipped(self):
        store = FakeStore()
        stored, skipped = import_env_secrets({"TELEGRAM_API_ID": "12ab"}, store)
        self.assertEqual((store.values, stored), ({}, []))
        self.assertEqual([name for name, _ in skipped], ["TELEGRAM_API_ID"])

    def test_an_already_stored_value_is_never_overwritten(self):
        store = FakeStore({("substack", "sid"): "kept"})
        stored, skipped = import_env_secrets({"SUBSTACK_SID": "newer-cookie"}, store)
        self.assertEqual(store.values[("substack", "sid")], "kept")
        self.assertEqual(stored, [])
        self.assertEqual(skipped, [("SUBSTACK_SID", "already stored")])

    def test_main_prints_names_and_never_values(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(env=FULL_ENV, store=FakeStore())
        text = out.getvalue()
        self.assertEqual(code, 0)
        for name in FULL_ENV:
            self.assertIn(name, text)
        for value in FULL_ENV.values():
            self.assertNotIn(value, text)


if __name__ == "__main__":
    unittest.main()
