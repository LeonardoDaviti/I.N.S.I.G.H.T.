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
GET /api/discover/people        {window_days, posts, authors [...], makers [...]} (issue 0276, markx/discover_people):
                                the people and makers your tracks' in posts and News rows of 30 days quote, repost,
                                mention, link or name, each {key, kind author | maker, platform, name, posts, tracks,
                                news, how, why, evidence [{post_id, title, url, where, how, at}], follow {address, via,
                                feed, ready} | channels [...]}. Suggestions only: Follow opens Add source (the feed finder,
                                then page watching) on `follow.address`; a maker's channels are the official module's.
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


@router.get("/api/discover/people")
def get_people(limit: int = Query(30, ge=1, le=100), days: int = Query(30, ge=1, le=90)):
    """Issue 0276: who is behind what your tracks and News care about (read on the request: no fetch, no write)."""
    from insight_core.db import database as db
    from insight_core.markx import discover_people
    from insight_core.services.registry import services
    try:
        with db.connection(services().db_url) as conn, conn.cursor() as cur:
            return discover_people.suggestions(cur, limit=limit, days=days)
    except Exception as exc:  # noqa: BLE001 - Discover's own list stands without it
        raise HTTPException(status_code=500, detail=f"Could not read the people: {type(exc).__name__}") from None
