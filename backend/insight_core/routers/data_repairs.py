"""The data repairs' routes (services/data_repairs.py; Stealth v10.43): an APIRouter included by main.py. The API
only reads and asks; the jobs process runs every repair.

GET  /api/operations/repairs                 {repairs: [{name, title, about, version, ran_version, due, last_run,
                                             last_preview, requested, requested_at, running, running_since, undo}]}
                                             (last_run, last_preview: {at, version, dry_run, counts, sample [{label,
                                             url?, post_id?, source_id?, track_id?}], seconds, error?} or null)
POST /api/operations/repairs/{name}/run      the repair run again by the jobs process -> its row (requested: run)
POST /api/operations/repairs/{name}/preview  a dry run by the jobs process -> its row (requested: preview); the result
                                             lands in last_preview. 404: no such repair
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from insight_core.services import data_repairs

router = APIRouter(tags=["operations"])


def _db() -> str:
    from insight_core.services.registry import services
    return services().db_url


@router.get("/api/operations/repairs")
def list_repairs():
    from insight_core.db import database
    with database.transaction(_db()) as cur:
        return {"repairs": data_repairs.listing(cur)}


def _ask(name: str, mode: str):
    from insight_core.db import database
    with database.transaction(_db()) as cur:
        try:
            return data_repairs.request(cur, name, mode)
        except KeyError:
            raise HTTPException(status_code=404, detail="No such repair")


@router.post("/api/operations/repairs/{name}/run")
def run_repair(name: str):
    return _ask(name, "run")


@router.post("/api/operations/repairs/{name}/preview")
def preview_repair(name: str):
    return _ask(name, "preview")
