"""
Minimal uvicorn-compatible runner for local endpoint testing.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Tuple, get_args, get_origin
from urllib.parse import parse_qs, urlparse

from fastapi import HTTPException
from pydantic import BaseModel


def run(app_ref: str | Any, host: str = "127.0.0.1", port: int = 8000, **kwargs):
    app = _resolve_app(app_ref)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

        def do_PUT(self):
            self._handle("PUT")

        def do_DELETE(self):
            self._handle("DELETE")

        def log_message(self, format: str, *args) -> None:
            return None

        def _handle(self, method: str):
            parsed = urlparse(self.path)
            route, path_params = _match_route(app.routes, method, parsed.path)

            if route is None:
                self._send_json(404, {"detail": "Not Found"})
                return

            try:
                body = self._read_json_body()
                query_params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
                kwargs = _build_handler_kwargs(route.handler, path_params, query_params, body)
                result = _call_handler(route.handler, kwargs)
                self._send_json(200, result)
            except HTTPException as exc:
                self._send_json(exc.status_code, {"detail": exc.detail})
            except Exception as exc:
                self._send_json(500, {"detail": str(exc)})

        def _read_json_body(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            if length <= 0:
                return None
            raw = self.rfile.read(length)
            if not raw:
                return None
            return json.loads(raw.decode("utf-8"))

        def _send_json(self, status_code: int, payload: Any):
            body = json.dumps(payload, default=_json_default).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _resolve_app(app_ref: str | Any):
    if not isinstance(app_ref, str):
        return app_ref
    module_name, attribute_name = app_ref.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, attribute_name)


def _match_route(routes, method: str, path: str):
    matches: List[Tuple[int, int, Any, Dict[str, str]]] = []

    for route in routes:
        if route.method != method:
            continue

        params = {}
        route_segments = [segment for segment in route.path.split("/") if segment]
        path_segments = [segment for segment in path.split("/") if segment]
        if len(route_segments) != len(path_segments):
            continue

        static_segments = 0
        for route_segment, path_segment in zip(route_segments, path_segments):
            if route_segment.startswith("{") and route_segment.endswith("}"):
                params[route_segment[1:-1]] = path_segment
            elif route_segment == path_segment:
                static_segments += 1
            else:
                break
        else:
            matches.append((len(params), -static_segments, route, params))

    if not matches:
        return None, {}

    matches.sort(key=lambda item: (item[0], item[1]))
    _, _, route, params = matches[0]
    return route, params


def _build_handler_kwargs(handler, path_params, query_params, body):
    kwargs = {}
    signature = inspect.signature(handler)

    for name, parameter in signature.parameters.items():
        annotation = parameter.annotation
        if name in path_params:
            kwargs[name] = _coerce(path_params[name], annotation)
            continue

        if name in query_params:
            kwargs[name] = _coerce(query_params[name], annotation)
            continue

        if annotation is inspect._empty:
            kwargs[name] = body
            continue

        if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
            kwargs[name] = annotation(**(body or {}))
            continue

        kwargs[name] = body

    return kwargs


def _call_handler(handler, kwargs):
    if inspect.iscoroutinefunction(handler):
        return asyncio.run(handler(**kwargs))
    return handler(**kwargs)


def _coerce(value: Any, annotation: Any):
    if annotation is inspect._empty or annotation is Any:
        return value

    origin = get_origin(annotation)
    if origin is None:
        if annotation is bool:
            return str(value).lower() in {"1", "true", "yes", "on"}
        if annotation is int:
            return int(value)
        if annotation is float:
            return float(value)
        return value

    if origin is list:
        inner = get_args(annotation)[0] if get_args(annotation) else Any
        return [_coerce(item, inner) for item in value]

    return value


def _json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump()
    raise TypeError(f"Object of type {type(value)} is not JSON serializable")
