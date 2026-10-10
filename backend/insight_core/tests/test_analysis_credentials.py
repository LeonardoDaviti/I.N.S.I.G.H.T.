"""The Gemini client reads its key from Connections, never from the environment (S6)."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.credentials import MappingCredentials

ENV_KEYS = {"GEMINI_API_KEY": "env-gemini", "GOOGLE_API_KEY": "env-google"}


class GeminiKeyTests(unittest.TestCase):
    def processor(self, values):
        from insight_core.processors.ai.gemini_processor import GeminiProcessor

        return GeminiProcessor(credentials=MappingCredentials(values))

    def test_the_key_comes_from_the_store(self):
        with mock.patch.dict(os.environ, ENV_KEYS):
            processor = self.processor({("gemini", "api_key"): "stored-key"})
            self.assertTrue(processor.setup_processor())
        self.assertEqual(processor.api_key, "stored-key")

    def test_an_env_key_alone_does_not_configure_gemini(self):
        with mock.patch.dict(os.environ, ENV_KEYS):
            processor = self.processor({})
            self.assertFalse(processor.setup_processor())
        self.assertIsNone(processor.api_key)

    def test_the_lazy_processor_uses_the_shared_store(self):
        from insight_core.processors.ai import lazy

        shared = MappingCredentials({("gemini", "api_key"): "shared-key"})
        with mock.patch("insight_core.ingestion.credentials.default_credentials", return_value=shared):
            processor = lazy._build_gemini_processor(object())
            self.assertTrue(processor.setup_processor())
        self.assertEqual(processor.api_key, "shared-key")


if __name__ == "__main__":
    unittest.main()
