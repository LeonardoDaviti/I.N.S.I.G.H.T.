"""Gemini and Langfuse read their keys from Connections, never from the environment (S6)."""
from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.credentials import MappingCredentials

ENV_KEYS = {"GEMINI_API_KEY": "env-gemini", "GOOGLE_API_KEY": "env-google",
            "LANGFUSE_PUBLIC_KEY": "pk-env", "LANGFUSE_SECRET_KEY": "sk-env"}


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


class LangfuseKeyTests(unittest.TestCase):
    def setUp(self):
        from insight_core.observability import langfuse_tracer

        self.tracer = langfuse_tracer
        self.addCleanup(self._reset)
        self._reset()
        self.built = []
        fake = types.ModuleType("langfuse")
        fake.Langfuse = lambda **kwargs: self.built.append(kwargs) or object()
        patcher = mock.patch.dict(sys.modules, {"langfuse": fake})
        patcher.start()
        self.addCleanup(patcher.stop)

    def _reset(self):
        self.tracer._client = None
        self.tracer._initialized = False

    def env(self):
        return mock.patch.dict(os.environ, {**ENV_KEYS, "LANGFUSE_ENABLED": "true",
                                            "LANGFUSE_BASE_URL": "https://cloud.langfuse.com"})

    def test_keys_come_from_the_store(self):
        creds = MappingCredentials({("langfuse", "public_key"): "pk-db", ("langfuse", "secret_key"): "sk-db"})
        with self.env():
            self.assertIsNotNone(self.tracer.get_client(credentials=creds))
        self.assertEqual((self.built[0]["public_key"], self.built[0]["secret_key"]), ("pk-db", "sk-db"))

    def test_env_keys_alone_leave_tracing_off(self):
        with self.env():
            self.assertIsNone(self.tracer.get_client(credentials=MappingCredentials()))
        self.assertEqual(self.built, [])


if __name__ == "__main__":
    unittest.main()
