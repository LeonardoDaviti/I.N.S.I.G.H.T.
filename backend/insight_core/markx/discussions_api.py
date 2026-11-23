"""Discussions' routes (issue 0280): the post page's Discussion section, the reader's want, News rows' counts.

GETs only read. The want is one insert and the jobs row's mark (discussions.want); the fetch is the jobs process's.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from insight_core.markx import discussions

router = APIRouter()
MAX_POSTS = 200


def _post(post_id: str) -> str:
    from insight_core.markx.api import _uuid
    found = _uuid(post_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such post")
    return str(found)


@router.get("/posts/{post_id}/discussion")
def mx_discussion(post_id: str):
    from insight_core.markx.api import transaction
    pid = _post(post_id)
    with transaction() as cur:
        return discussions.view(cur, pid)


@router.post("/posts/{post_id}/discussion/want")
def mx_discussion_want(post_id: str):
    """The reader opened the post: its thread is fetched by the next jobs pass (once; later fetches are scheduled)."""
    from insight_core.markx.api import transaction
    pid = _post(post_id)
    with transaction() as cur:
        return {"wanted": discussions.want(cur, pid)}


@router.get("/discussions")
def mx_discussion_counts(posts: str = Query("", max_length=MAX_POSTS * 40)):
    """{post id: {points, total, name}} for the given posts (comma-separated ids) with an answered thread."""
    from insight_core.markx.api import _uuid, transaction
    ids = [str(u) for u in (_uuid(p.strip()) for p in posts.split(",")[:MAX_POSTS]) if u is not None]
    with transaction() as cur:
        return discussions.counts(cur, ids)
