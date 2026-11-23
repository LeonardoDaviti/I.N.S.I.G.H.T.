"""Each API route's count and time, in this process (v10.42): which routes keep the API busy.

`RouteTimings` (pure ASGI middleware) times every HTTP request from its start to its response's last body and adds it
to its route's row, keyed by the method and the route's template (`/api/markx/tracks/{track_id}`, never a value of the
path; "(unmatched)" for a path no route has). Kept in memory, one row a template (a few hundred at most), since the
process started: `snapshot()` reads them (GET /api/operations/db-statements' `api_routes`). Each API process keeps its
own (the API runs two).
"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List

_LOCK = threading.Lock()
_ROWS: Dict[str, List[float]] = {}   # "GET /api/x/{id}" -> [count, total ms, max ms, errors (5xx)]
_STARTED = time.time()


def add(key: str, ms: float, error: bool) -> None:
    with _LOCK:
        row = _ROWS.setdefault(key, [0, 0.0, 0.0, 0])
        row[0] += 1
        row[1] += ms
        row[2] = max(row[2], ms)
        row[3] += int(error)


def snapshot(limit: int = 40) -> Dict[str, Any]:
    """{since, routes: [{route, count, total_ms, mean_ms, max_ms, errors}]}: the `limit` routes of most total time."""
    with _LOCK:
        rows = sorted(_ROWS.items(), key=lambda kv: (-kv[1][1], kv[0]))
    return {"since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(_STARTED)),
            "routes": [{"route": k, "count": int(n), "total_ms": round(t, 1), "mean_ms": round(t / n, 1) if n else 0.0,
                        "max_ms": round(m, 1), "errors": int(e)} for k, (n, t, m, e) in rows[:limit]]}


def _template(scope: Dict[str, Any]) -> str:
    route = scope.get("route")
    return getattr(route, "path_format", None) or getattr(route, "path", None) or "(unmatched)"


class RouteTimings:
    """The middleware: added outside the routing, so a route's own middleware and the handler are timed."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        status = [0]

        async def sent(message: Any) -> None:
            if message.get("type") == "http.response.start":
                status[0] = int(message.get("status") or 0)
            await send(message)

        try:
            await self.app(scope, receive, sent)
        except Exception:
            status[0] = 500
            raise
        finally:
            add(f"{scope.get('method', '?')} {_template(scope)}", (time.perf_counter() - t0) * 1000, status[0] >= 500)
