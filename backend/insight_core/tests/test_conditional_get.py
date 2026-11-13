"""Conditional GETs for the polled answers (issue 0195, routers/conditional.py): a weak ETag and no-cache on a listed
path's 200, a 304 with no body when If-None-Match names it, anything else untouched. No database."""
from __future__ import annotations

import asyncio
import unittest
from typing import Any, Dict, List, Tuple

from insight_core.routers.conditional import POLLED, ConditionalGet, etag_of, matches


def app_answering(status: int, body: bytes, parts: int = 1):
    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                (b"access-control-allow-origin", b"x")]})
        step = max(1, len(body) // parts)
        pieces = [body[i:i + step] for i in range(0, len(body), step)] or [b""]
        for n, piece in enumerate(pieces):
            await send({"type": "http.response.body", "body": piece, "more_body": n < len(pieces) - 1})
    return app


def get(app, path: str, *, method: str = "GET", if_none_match: str | None = None) -> Tuple[int, Dict[str, str], bytes]:
    headers = [(b"host", b"t")] + ([(b"if-none-match", if_none_match.encode())] if if_none_match else [])
    scope = {"type": "http", "method": method, "path": path, "headers": headers}
    sent: List[Dict[str, Any]] = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    start = sent[0]
    return (start["status"], {k.decode(): v.decode() for k, v in start.get("headers", [])},
            b"".join(m.get("body", b"") for m in sent[1:]))


class ConditionalGets(unittest.TestCase):
    BODY = b'{"total": 3}'

    def test_a_polled_answer_carries_its_etag_and_an_unchanged_one_is_a_304(self):
        app = ConditionalGet(app_answering(200, self.BODY, parts=3))
        status, headers, body = get(app, "/api/feed/unread-counts")
        self.assertEqual((status, body, headers["etag"], headers["cache-control"]),
                         (200, self.BODY, etag_of(self.BODY), "no-cache"))
        self.assertEqual(headers["access-control-allow-origin"], "x")
        status, headers, body = get(app, "/api/feed/unread-counts", if_none_match=etag_of(self.BODY))
        self.assertEqual((status, body, headers["etag"]), (304, b"", etag_of(self.BODY)))
        self.assertNotIn("content-length", headers)
        self.assertEqual(headers["access-control-allow-origin"], "x")

    def test_a_changed_answer_is_sent_whole(self):
        app = ConditionalGet(app_answering(200, self.BODY))
        status, headers, body = get(app, "/api/operations/running", if_none_match=etag_of(b"{}"))
        self.assertEqual((status, body), (200, self.BODY))

    def test_other_paths_methods_and_errors_pass_untouched(self):
        for path, method, status in (("/api/feed", "GET", 200), ("/api/feed/unread-counts", "POST", 200),
                                     ("/api/sources/health", "GET", 500)):
            app = ConditionalGet(app_answering(status, self.BODY))
            got_status, headers, body = get(app, path, method=method, if_none_match=etag_of(self.BODY))
            self.assertEqual((got_status, body), (status, self.BODY), path)
            self.assertNotIn("etag", headers)

    def test_if_none_match_compares_weakly(self):
        tag = etag_of(self.BODY)
        self.assertTrue(matches(tag, tag))
        self.assertTrue(matches(tag[2:], tag))
        self.assertTrue(matches('"other", ' + tag, tag))
        self.assertTrue(matches("*", tag))
        self.assertFalse(matches('W/"other"', tag))

    def test_the_polled_paths_are_the_apps_routes(self):
        import main
        routes = set(main.app.openapi()["paths"])   # an included router's routes too (0198: Mark X News)
        self.assertTrue(set(POLLED) <= routes, set(POLLED) - routes)


if __name__ == "__main__":
    unittest.main()
