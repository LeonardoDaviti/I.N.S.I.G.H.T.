"""The smart archiver's routes (issue 0143): an APIRouter, included by main.py in one line. The app's own.

GET  /api/sources/{source_id}/discoveries   what the source discovered (db/repo_source_discoveries): {sites [{key,
                                            site, platform, state open|followed|hidden, voices, articles, addresses,
                                            first_linked, followed_source}], followed_from_here [{id, name, added_at,
                                            key}], originals [{kind, url, outcome, post_id, story_id, asked_at, title}],
                                            entities [{id, name, type, post_id, at, post_title}], counts,
                                            discover_counted}
PUT  /api/archive/{source_id}/web-archive   {on} -> {on}: the ladder's last resort, the Web Archive's address index,
                                            for this source (settings.archive.web_archive; off by default)

A bad id is 400 {"detail"}, an unknown source 404.
"""
from __future__ import annotations

import functools
import uuid
from typing import Any, Callable, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["archive"])
_reader: Optional[Callable[[str], Dict[str, Any]]] = None
_settings: Optional[Any] = None


def reader() -> Callable[[str], Dict[str, Any]]:
    """source id -> its discoveries (blocking), on the app's database."""
    global _reader
    if _reader is None:
        from insight_core.db import database as db
        from insight_core.db.repo_source_discoveries import source_discoveries
        from insight_core.services.registry import services

        db_url = services().db_url

        def read(source_id: str) -> Dict[str, Any]:
            with db.connection(db_url) as conn, conn.cursor() as cur:
                return source_discoveries(cur, source_id)

        _reader = read
    return _reader


def settings() -> Any:
    """The sources service (merge_source_settings, get_source_by_id)."""
    global _settings
    if _settings is None:
        from insight_core.services.registry import services
        _settings = services().sources
    return _settings


def use(read: Optional[Callable[[str], Dict[str, Any]]] = None, sources: Optional[Any] = None) -> None:
    """Tests: answer from these (None: build them again)."""
    global _reader, _settings
    _reader, _settings = read, sources


def answered(fn: Callable) -> Callable:
    """A ValueError is 400, a LookupError 404, each {"detail"}."""
    @functools.wraps(fn)
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
    return run


def _id(value: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise ValueError("source id must be a uuid") from None


class WebArchiveRequest(BaseModel):
    on: bool


@router.get("/api/sources/{source_id}/discoveries")
@answered
def discoveries(source_id: str):
    return reader()(_id(source_id))


@router.put("/api/archive/{source_id}/web-archive")
@answered
def web_archive(source_id: str, request: WebArchiveRequest):
    sources = settings()
    source_id = _id(source_id)
    if not sources.get_source_by_id(source_id):
        raise LookupError(f"Source {source_id} not found")
    sources.merge_source_settings(source_id, {"archive": {"web_archive": bool(request.on)}})
    return {"on": bool(request.on)}
