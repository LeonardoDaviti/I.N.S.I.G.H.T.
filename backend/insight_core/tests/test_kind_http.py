"""KindHttp, the one HTTP client of every source kind: how its failures are classified."""
from __future__ import annotations

import asyncio
import http.client
import io
import socket
import sys
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import main
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


class SchemeTests(unittest.TestCase):
    def test_only_http_and_https_are_requested(self):
        with mock.patch.object(urllib.request, "urlopen") as urlopen:
            for call in (lambda h: h.get_text("file:///etc/hostname"), lambda h: h.get_start("ftp://x.example/", 10),
                         lambda h: h.post_json("gopher://x.example/", {})):
                with self.assertRaises(HttpError):
                    asyncio.run(call(KindHttp()))
        urlopen.assert_not_called()


class SlowDrip:
    """A local server that answers at once with a long body, then drips it a byte at a time.
    `closed_after` is the seconds from the request until the client closed the connection."""

    def __init__(self) -> None:
        self.server = socket.socket()
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.url = f"http://127.0.0.1:{self.server.getsockname()[1]}/"
        self.closed_after = None
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        conn, _ = self.server.accept()
        started = time.monotonic()
        conn.recv(65536)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: 1000000\r\n\r\n")
        try:
            while time.monotonic() - started < 10:
                conn.sendall(b"a")
                time.sleep(0.02)
        except OSError:
            self.closed_after = time.monotonic() - started
        finally:
            conn.close()
            self.server.close()


class DeadlineTests(unittest.TestCase):
    def test_get_start_stops_a_slow_drip_at_its_deadline_and_closes_the_connection(self):
        drip = SlowDrip()
        started = time.monotonic()
        with self.assertRaises(HttpError) as raised:
            asyncio.run(KindHttp(timeout=1).get_start(drip.url, 1_000_000))
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(raised.exception.timed_out)
        drip.thread.join(3)
        self.assertIsNotNone(drip.closed_after, "the connection was left open")
        self.assertLess(drip.closed_after, 2.5)

    def test_the_add_source_dialogs_client_runs_on_its_own_threads(self):
        names = []

        def urlopen(*_args, **_kwargs):
            names.append(threading.current_thread().name)
            return _Body(b"<html></html>")

        with mock.patch.object(urllib.request, "urlopen", urlopen):
            asyncio.run(main.FEED_FINDER_HTTP.get_start("https://x.example/", 10))
            asyncio.run(main.FEED_FINDER_HTTP.get_text("https://x.example/"))
        self.assertEqual(len(names), 2)
        self.assertTrue(all(name.startswith("add-source-http") for name in names), names)


class _Body(io.BytesIO):
    headers: dict = {}

    def geturl(self):
        return "https://x.example/"


if __name__ == "__main__":
    unittest.main()
