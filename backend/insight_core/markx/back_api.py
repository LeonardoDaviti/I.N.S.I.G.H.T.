"""Routes for back in the news on /markx (the app's own; 404 when Mark X is off). Included into markx/api.py's router.

GET  /api/markx/back           {items, counts, precision, measured} (markx/back.page)
POST /api/markx/labels/back    {row, answer: development | retold | related | unrelated | undo} -> {id, answer, label,
                               precision}
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from insight_core.markx import back

router = APIRouter()


class BackLabelIn(BaseModel):
    row: Any = None
    answer: str
    note: Optional[str] = None


@router.get("/back")
def mx_back_page():
    from insight_core.markx.api import transaction
    with transaction() as cur:
        return back.page(cur)


@router.post("/labels/back")
def mx_label_back(body: BackLabelIn):
    from insight_core.markx.api import _uuid, transaction
    row = _uuid(body.row)
    if row is None:
        raise HTTPException(status_code=404, detail="No such row")
    with transaction() as cur:
        try:
            return back.label(cur, row=str(row), answer=body.answer, note=body.note)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except KeyError:
            raise HTTPException(status_code=404, detail="No such row")
