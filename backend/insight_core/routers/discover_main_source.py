"""Discover's "main source missing" route (issue 0170): an APIRouter, included by main.py in one line.

GET /api/discover/main-source   {rows [{key ("main:<channel key>", Not interested hides it through
                                POST /api/sources/suggested/hide), kind missing | wrong_section | disabled,
                                channel {key, kind account | site | source, platform, url, prefix}, actor {id, name},
                                source {id, name, enabled, watch} | null, events [{story, headline, event_type, voices,
                                first_at, own_page {url, how held | linked | main_link | source_page, held_by} | null,
                                posts [{id, title, source, source_id, url, at}]}], latest, test {label, holds, of,
                                feeds, pages, preview, at} | null}], total, checked, events, within_days}
                                (services/discover_main_source.py). Opening it tests the shown channels in the
                                background, at most once in 30 days each (off with INSIGHT_DISCOVER_READS=0). Nothing
                                is followed here: Follow opens Add source on the channel.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(tags=["discover"])
_main: Optional[Any] = None
_http: Optional[Any] = None


def main_source() -> Any:
    global _main
    if _main is None:
        from insight_core.services.discover_main_source import MainSource
        from insight_core.services.registry import services
        _main = MainSource(services().db_url)
    return _main


def http() -> Any:
    """The finder's client, as Add source's (main.FEED_FINDER_HTTP: a 5 s timeout)."""
    global _http
    if _http is None:
        from insight_core.ingestion.http import KindHttp
        _http = KindHttp(timeout=5, executor=ThreadPoolExecutor(max_workers=4, thread_name_prefix="discover-main-http"))
    return _http


def use(main: Optional[Any] = None, client: Optional[Any] = None) -> None:
    """Tests: answer from these (None: build them again)."""
    global _main, _http
    _main, _http = main, client


@router.get("/api/discover/main-source")
async def get_main_source(limit: int = Query(20, ge=1, le=100), test: bool = Query(True)):
    try:
        answer = await asyncio.to_thread(main_source().answer, limit=limit)
    except Exception as exc:  # noqa: BLE001 - Discover's own list stands without it
        raise HTTPException(status_code=500, detail=f"Could not read the main sources: {type(exc).__name__}") from None
    if test and answer["rows"]:
        from insight_core.services.registry import services
        main_source().start(http(), services().source_fetch.kinds)
    return {"success": True, **answer}
