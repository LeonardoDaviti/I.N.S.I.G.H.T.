"""Official channels' routes (issue 0196): an APIRouter, included by main.py in one line. Reads only, but Undo and the
owner's item filter; the decisions are markx/official.py's, made in the jobs process.

GET  /api/official                       the review view: {mode off|shadow|on, cap, added_today, counts {state: n},
                                         events {outcome: n}, rows [{id, key, kind x|telegram|youtube|section|releases,
                                         state candidate|would_add|added|undone|refused|covered, why, actor {id, name},
                                         follow, from (own_page|code_address|handle|web_search|web_announcement), owned,
                                         proof {via, address, items, dated, holds, linked}, judge {verdict, fits,
                                         original, reasons}, filter, source_id, hidden_items, events [{story, headline,
                                         voices, first_at}], decided_at, created_at}]}
POST /api/official/{id}/undo             {id, state: undone, source_id}: the source switched off (posts kept), the
                                         channel never added again by the module. 404: no such current row
GET  /api/sources/{id}/item-filter       {rule | null, by, hidden}
PUT  /api/sources/{id}/item-filter       {rule | null} -> {rule, hidden}: the owner's rule (utils/item_filter.check
                                         against the source's newest 30 posts), or none; the source's posts marked again
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["discover"])


def _db() -> str:
    from insight_core.services.registry import services
    return services().db_url


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise HTTPException(status_code=400, detail="Not an id") from None


@router.get("/api/official")
async def get_official():
    from insight_core.db import database
    from insight_core.markx import official

    def read() -> Dict[str, Any]:
        with database.connection(_db()) as conn, conn.cursor() as cur:
            return official.view(cur)
    return {"success": True, **await asyncio.to_thread(read)}


@router.post("/api/official/{channel_id}/undo")
async def undo_official(channel_id: str):
    from insight_core.db import database
    from insight_core.markx import official
    cid = _uuid(channel_id)

    def write() -> Dict[str, Any]:
        with database.transaction(_db()) as cur:
            return official.undo(cur, cid)
    try:
        got = await asyncio.to_thread(write)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such channel") from None
    return {"success": True, **got}


class ItemFilter(BaseModel):
    rule: Optional[Dict[str, Any]] = None


@router.get("/api/sources/{source_id}/item-filter")
async def get_item_filter(source_id: str):
    from insight_core.db import database
    from insight_core.utils import item_filter
    sid = _uuid(source_id)

    def read() -> Dict[str, Any]:
        with database.connection(_db()) as conn, conn.cursor() as cur:
            got = item_filter.current(cur, [sid]).get(sid)
            return {"rule": got["rule"] if got else None, "by": got["by"] if got else None,
                    "hidden": item_filter.hidden_count(cur, [sid]).get(sid, 0)}
    return {"success": True, **await asyncio.to_thread(read)}


@router.put("/api/sources/{source_id}/item-filter")
async def put_item_filter(source_id: str, body: ItemFilter):
    from insight_core.db import database
    from insight_core.utils import item_filter
    sid = _uuid(source_id)

    def write() -> Dict[str, Any]:
        with database.transaction(_db()) as cur:
            cur.execute("SELECT 1 FROM sources WHERE id = %s", (sid,))
            if cur.fetchone() is None:
                raise KeyError(sid)
            if body.rule is not None:
                cur.execute("SELECT id::text, title, url FROM posts WHERE source_id = %s ORDER BY fetched_at DESC "
                            "LIMIT 30", (sid,))
                items = [{"id": i, "title": t, "url": u} for i, t, u in cur.fetchall()]
                err = item_filter.check(body.rule, items)
                if err:
                    raise ValueError(err)
            item_filter.put(cur, sid, body.rule, by="owner")
            return {"rule": body.rule, "hidden": item_filter.hidden_count(cur, [sid]).get(sid, 0)}
    try:
        got = await asyncio.to_thread(write)
    except KeyError:
        raise HTTPException(status_code=404, detail="No such source") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"success": True, **got}
