"""0173 (Stealth v10.15)'s routes: "Is this worth it?" for a candidate source (Shadow; the app's own; 404 when Mark X is
off, as every /api/markx path). Included into markx/api.py's router.

GET  /api/markx/source-judge?address=<address>     the latest judgement of the address ({judgement: null}: never asked)
POST /api/markx/source-judge {address, again?}     the owner's tap: the cached judgement (30 days), else a new one, its
                                                   test read and question in the background -> {judgement}
Nothing here writes a source: Follow is the Add source dialog's, as every add.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Set

from fastapi import APIRouter, BackgroundTasks, HTTPException

from insight_core.markx import source_judge

log = logging.getLogger(__name__)
router = APIRouter()
_reading: Set[str] = set()   # judgements this process is reading now (the database claim decides)


async def read_in_background(judgement_id: str) -> None:
    from insight_core.markx.api import db_url
    if judgement_id in _reading:
        return
    _reading.add(judgement_id)
    try:
        await source_judge.read_and_ask(db_url(), judgement_id)
    except Exception:  # noqa: BLE001 - the next ask reads it again
        log.exception("Source judge %s: the background read failed", judgement_id)
    finally:
        _reading.discard(judgement_id)


@router.get("/source-judge")
def mx_source_judge(address: str = ""):
    from insight_core.markx.api import transaction
    if not address.strip():
        raise HTTPException(status_code=400, detail="An address to judge, please")
    with transaction() as cur:
        return {"judgement": source_judge.page(cur, address)}


@router.post("/source-judge")
async def mx_source_judge_ask(body: Dict[str, Any], background: BackgroundTasks):
    from insight_core.markx.api import transaction
    address = str((body or {}).get("address") or "")
    again = bool((body or {}).get("again"))
    with transaction() as cur:
        try:
            got = source_judge.ask(cur, address, again=again)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if got["needs_read"]:
        background.add_task(read_in_background, got["id"])
    with transaction() as cur:
        return {"judgement": source_judge.page(cur, got["address"])}
