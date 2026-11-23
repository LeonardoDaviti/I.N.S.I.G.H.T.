"""Discover's "main source missing" and people routes; both read pages the jobs process keeps, follow nothing.

GET /api/discover/main-source   {rows [{key "main:<channel>", kind, channel, actor, source, events, latest, test}],
                                total, checked, events, within_days, built_at} (services/discover_main_source.py)
GET /api/discover/people        {window_days, posts, authors, makers, built_at, refreshing} (markx/discover_people)
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["discover"])
_main: Optional[Any] = None


def main_source() -> Any:
    global _main
    if _main is None:
        from insight_core.services.discover_main_source import MainSource
        from insight_core.services.registry import services
        _main = MainSource(services().db_url)
    return _main


def use(main: Optional[Any] = None) -> None:
    """Tests: answer from this (None: build it again)."""
    global _main
    _main = main


@router.get("/api/discover/main-source")
def get_main_source(limit: int = Query(20, ge=1, le=100), test: bool = Query(True)):
    """The kept page (MainSource.served); `test` is accepted for older clients and ignored."""
    try:
        return main_source().served(limit=limit)
    except Exception as exc:  # noqa: BLE001 - Discover's own list stands without it
        raise HTTPException(status_code=500, detail=f"Could not read the main sources: {type(exc).__name__}") from None


@router.get("/api/discover/people")
def get_people(limit: int = Query(30, ge=1, le=100)):
    """Who is behind what your tracks and News care about: the kept list, with built_at and refreshing (0276)."""
    from insight_core.db import database as db
    from insight_core.markx import discover_people
    from insight_core.services.registry import services
    try:
        with db.transaction(services().db_url) as cur:
            return discover_people.served(cur, limit=limit)
    except Exception as exc:  # noqa: BLE001 - Discover's own list stands without it
        raise HTTPException(status_code=500, detail=f"Could not read the people: {type(exc).__name__}") from None
