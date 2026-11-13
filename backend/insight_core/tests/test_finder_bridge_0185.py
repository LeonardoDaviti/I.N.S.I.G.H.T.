"""Issue 0185 (2): the feed finder's "no bridge" says only that no bridge is configured. A configured bridge
whose feed gave nothing (timeout, empty, no feed) is asked once more, then says BRIDGE_SILENT; one that
answered an HTTP error keeps that error's reason. X's and Telegram's bridges alike."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from insight_core.ingestion.feed_finder import BRIDGE_SILENT, NO_BRIDGE  # noqa: E402
from insight_core.tests.test_new_spheres_0137 import blocked, finder, rss, toc  # noqa: E402

NITTER = {"NITTER_HOSTS": "nitter.example"}
TELEGRAM = {"TELEGRAM_RSS_HOSTS": "tg.example"}
X_FEED = "https://nitter.example/someone/rss"
TG_FEED = "https://tg.example/rss/achannel"


def flaky(answers):
    """A response answering each of answers in turn (a timeout, then a feed...)."""
    queue = list(answers)

    def answer(_url):
        return queue.pop(0) if len(queue) > 1 else queue[0]
    return answer


class BridgeReasonTests(unittest.TestCase):
    def test_no_bridge_only_when_none_is_configured(self):
        with mock.patch.dict("os.environ", {"NITTER_HOSTS": ""}):
            finding, http = finder({}, "https://x.com/someone")
        self.assertEqual((finding.status, finding.reason, http.requests), ("none", NO_BRIDGE, []))

    def test_a_silent_x_bridge_is_asked_twice_and_says_so(self):
        for answer in (TimeoutError(), rss("someone", ""), "<html><body>busy</body></html>"):
            with mock.patch.dict("os.environ", NITTER):
                finding, http = finder({X_FEED: answer}, "https://x.com/someone")
            self.assertEqual((finding.status, finding.reason), ("none", BRIDGE_SILENT), answer)
            self.assertEqual(http.requests, [X_FEED, X_FEED])

    def test_a_silent_telegram_bridge_says_so_too(self):
        with mock.patch.dict("os.environ", TELEGRAM):
            finding, http = finder({}, "https://t.me/achannel")
        self.assertEqual((finding.status, finding.reason, http.requests), ("none", BRIDGE_SILENT, [TG_FEED, TG_FEED]))

    def test_the_retry_finds_the_feed(self):
        with mock.patch.dict("os.environ", NITTER):
            finding, http = finder({X_FEED: flaky([TimeoutError(), toc("someone", "https://nitter.example/someone/status/1")])},
                                   "https://x.com/someone")
        self.assertEqual((finding.status, [f.url for f in finding.feeds]), ("found", [X_FEED]))
        self.assertEqual(len(http.requests), 2)

    def test_a_bridge_answering_a_client_error_keeps_that_reason_without_retry(self):
        with mock.patch.dict("os.environ", NITTER):
            finding, http = finder({X_FEED: blocked(X_FEED, 404)}, "https://x.com/someone")
        self.assertEqual((finding.reason, http.requests), ("gone", [X_FEED]))

    def test_a_server_error_is_retried_then_said(self):
        with mock.patch.dict("os.environ", TELEGRAM):
            finding, http = finder({TG_FEED: blocked(TG_FEED, 502)}, "https://t.me/achannel")
        self.assertEqual((finding.reason, http.requests), ("server error", [TG_FEED, TG_FEED]))


if __name__ == "__main__":
    unittest.main()
