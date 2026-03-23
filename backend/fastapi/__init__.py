"""
Minimal FastAPI-compatible API surface for local testing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, List


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def Query(default: Any = None, **kwargs) -> Any:
    del kwargs
    return default


class BackgroundTasks:
    def __init__(self) -> None:
        self.tasks: List[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []

    def add_task(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        self.tasks.append((func, args, kwargs))


@dataclass
class Route:
    method: str
    path: str
    handler: Callable[..., Any]


class FastAPI:
    def __init__(self, *args, **kwargs):
        self.routes: List[Route] = []

    def add_middleware(self, *args, **kwargs) -> None:
        return None

    def get(self, path: str):
        return self._register("GET", path)

    def post(self, path: str):
        return self._register("POST", path)

    def put(self, path: str):
        return self._register("PUT", path)

    def delete(self, path: str):
        return self._register("DELETE", path)

    def _register(self, method: str, path: str):
        def decorator(func: Callable[..., Any]):
            self.routes.append(Route(method=method, path=path, handler=func))
            return func

        return decorator
