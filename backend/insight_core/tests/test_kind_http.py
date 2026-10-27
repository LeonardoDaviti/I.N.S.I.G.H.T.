"""KindHttp, the one HTTP client of every source kind: how its failures are classified."""
from __future__ import annotations

import asyncio
import http.client
import io
import sys
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion.http import HttpError, KindHttp


class _Truncated(io.BytesIO):
    """A response whose body ends early: read() raises IncompleteRead."""

    def read(self, *_args):
        raise http.client.IncompleteRead(b"par", 100)

    def geturl(self):
        return "https://x.example/"


class DroppedConnectionTests(unittest.TestCase):
    def test_a_dropped_connection_is_an_http_error(self):
        dropped = http.client.RemoteDisconnected("Remote end closed connection without response")
        for call in (lambda h: h.get_text("https://x.example/"), lambda h: h.get_start("https://x.example/", 10),
                     lambda h: h.post_json("https://x.example/", {})):
            with mock.patch.object(urllib.request, "urlopen", side_effect=dropped):
                with self.assertRaises(HttpError) as raised:
                    asyncio.run(call(KindHttp()))
            self.assertIsNone(raised.exception.status)
            self.assertFalse(raised.exception.timed_out)

    def test_a_truncated_body_and_a_reset_are_http_errors(self):
        with mock.patch.object(urllib.request, "urlopen", return_value=_Truncated()):
            with self.assertRaises(HttpError):
                asyncio.run(KindHttp().get_text("https://x.example/"))
        with mock.patch.object(urllib.request, "urlopen", side_effect=ConnectionResetError(104, "reset")):
            with self.assertRaises(HttpError):
                asyncio.run(KindHttp().get_start("https://x.example/", 10))


if __name__ == "__main__":
    unittest.main()
