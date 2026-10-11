"""Call the FastAPI app over ASGI, the way a server would, without a network or httpx.

    status, headers, body = call(main.app, "GET", "/api/feed", query="limit=0")

The request goes through routing, validation and the error handler; the body is parsed
JSON (None when empty, bytes when not JSON). Background tasks run before this returns.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode


def call(app: Any, method: str, path: str, *, query: Optional[Dict[str, Any] | str] = None,
         json_body: Any = None) -> Tuple[int, Dict[str, str], Any]:
    return asyncio.run(_call(app, method, path, query, json_body))


async def _call(app, method, path, query, json_body):
    body = b"" if json_body is None else json.dumps(json_body).encode()
    query_string = query if isinstance(query, str) else urlencode(query or {})
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": query_string.encode(),
        "headers": [(b"host", b"test"), (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode())],
        "client": ("127.0.0.1", 1),
        "server": ("test", 80),
    }
    received = False
    finished = asyncio.Event()

    async def receive():
        nonlocal received
        if received:
            await finished.wait()
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    status, headers, chunks = 0, {}, []

    async def send(message):
        nonlocal status, headers
        if message["type"] == "http.response.start":
            status = message["status"]
            headers = {k.decode().lower(): v.decode() for k, v in message.get("headers", [])}
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                finished.set()

    await app(scope, receive, send)
    raw = b"".join(chunks)
    if not raw:
        return status, headers, None
    try:
        return status, headers, json.loads(raw)
    except ValueError:
        return status, headers, raw
