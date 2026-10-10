"""INSIGHT_ANALYSIS (spec reading-finish R3): one switch, default off, read into Settings."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.settings import Settings


class SettingsTests(unittest.TestCase):
    def test_analysis_is_off_by_default(self):
        self.assertFalse(Settings.from_env({}).analysis_enabled)

    def test_on_and_true_turn_analysis_on(self):
        for raw in ("on", "true", "1", "yes", " ON ", "True"):
            with self.subTest(raw=raw):
                self.assertTrue(Settings.from_env({"INSIGHT_ANALYSIS": raw}).analysis_enabled)

    def test_off_false_and_garbage_keep_analysis_off(self):
        for raw in ("off", "false", "0", "no", "", "maybe"):
            with self.subTest(raw=raw):
                self.assertFalse(Settings.from_env({"INSIGHT_ANALYSIS": raw}).analysis_enabled)


if __name__ == "__main__":
    unittest.main()
