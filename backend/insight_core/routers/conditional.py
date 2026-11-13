"""Conditional GETs for the answers every page polls (issue 0195).

The top bar's running jobs, the unread counts, the Ingestion overview and source health are asked again every few
seconds and mostly answer what they answered last time. Each such answer carries a weak ETag (a hash of its body) and
`Cache-Control: no-cache`, so the browser keeps it and asks again with If-None-Match; an unchanged answer is then a
304 with no body (the browser hands the kept body to the page as a 200). Only the listed paths, and only a 200: the
answer is held once, as the response already holds it, never kept between requests.
"""
from __future__ import annotations

import hashlib
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Tuple

Scope = Dict[str, Any]
Message = Dict[str, Any]

POLLED = ("/api/feed/unread-counts", "/api/operations/running", "/api/operations/overview", "/api/sources/health",
          "/api/markx/news")   # 0198: a kept page (1.7 MB): an unchanged one is a 304


def etag_of(body: bytes) -> str:
    return 'W/"' + hashlib.sha1(body).hexdigest() + '"'


def matches(if_none_match: str, etag: str) -> bool:
    """Whether an If-None-Match header names this ETag (weak comparison: W/ ignored), or is `*`."""
    tags = [t.strip() for t in if_none_match.split(",") if t.strip()]
    bare = etag[2:] if etag.startswith("W/") else etag
    return any(t == "*" or (t[2:] if t.startswith("W/") else t) == bare for t in tags)


class ConditionalGet:
    """Pure ASGI middleware: a weak ETag on the 200 answers of `paths`' GETs, a 304 when the request names it."""

    def __init__(self, app: Callable[..., Awaitable[None]], paths: Iterable[str] = POLLED) -> None:
        self.app = app
        self.paths = frozenset(paths)

    async def __call__(self, scope: Scope, receive: Callable[[], Awaitable[Message]],
                       send: Callable[[Message], Awaitable[None]]) -> None:
        if scope.get("type") != "http" or scope.get("method") != "GET" or scope.get("path") not in self.paths:
            await self.app(scope, receive, send)
            return
        asked = next((v.decode("latin-1") for k, v in scope.get("headers") or [] if k == b"if-none-match"), "")
        start: Dict[str, Any] = {}
        chunks: List[bytes] = []

        async def held(message: Message) -> None:
            if message["type"] == "http.response.start":
                if message.get("status") != 200:   # an error passes as it is
                    start["passthrough"] = True
                    await send(message)
                    return
                start.update(message)
                return
            if start.get("passthrough") or message["type"] != "http.response.body":
                await send(message)
                return
            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = b"".join(chunks)
            chunks.clear()
            etag = etag_of(body)
            headers: List[Tuple[bytes, bytes]] = [(k, v) for k, v in start.get("headers", [])
                                                  if k.lower() not in (b"etag", b"cache-control")]
            headers += [(b"etag", etag.encode("latin-1")), (b"cache-control", b"no-cache")]
            if asked and matches(asked, etag):
                kept = [(k, v) for k, v in headers if k.lower() not in (b"content-length", b"content-type")]
                await send({"type": "http.response.start", "status": 304, "headers": kept})
                await send({"type": "http.response.body", "body": b""})
                return
            await send({**start, "headers": headers})
            await send({"type": "http.response.body", "body": body})

        await self.app(scope, receive, held)
