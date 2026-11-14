"""Discover's "main source missing" route (issue 0170): an APIRouter, included by main.py in one line.

GET /api/discover/main-source   {rows [{key ("main:<channel key>", Not interested hides it through
                                POST /api/sources/suggested/hide), kind missing | wrong_section | disabled,
                                channel {key, kind account | site | source, platform, url, prefix}, actor {id, name},
                                source {id, name, enabled, watch} | null, events [{story, headline, event_type, voices,
                                first_at, own_page {url, how held | linked | main_link | source_page, held_by} | null,
                                posts [{id, title, source, source_id, url, at}]}], latest, test {label, holds, of,
                                feeds, pages, preview, at} | null}], total, checked, events, within_days}
                                (services/discover_main_source.py), built_at. Issue 0206: kept, made by the jobs
                                process, which tests the shown channels at most once in 30 days each (off with
                                INSIGHT_DISCOVER_READS=0). Nothing is followed here: Follow opens Add source on the
                                channel.
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
    """Issue 0206: the kept page (MainSource.served), made and tested by the jobs process; `test` is kept for older
    clients (the tests run there whenever it makes the list)."""
    try:
        return main_source().served(limit=limit)
    except Exception as exc:  # noqa: BLE001 - Discover's own list stands without it
        raise HTTPException(status_code=500, detail=f"Could not read the main sources: {type(exc).__name__}") from None
