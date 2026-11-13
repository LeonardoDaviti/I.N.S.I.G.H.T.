"""One page of a list the API ranks whole (issue 0195): News, Classics, the entity queue. The first page is the
list's top rows as they were before paging; the cursor is the next row's offset, as search's best-order cursor."""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple, TypeVar

T = TypeVar("T")


def offset_of(cursor: Optional[str]) -> int:
    """The offset a cursor names (None or "": the first page). ValueError (a 400) for anything else."""
    if cursor in (None, ""):
        return 0
    try:
        offset = int(str(cursor))
    except ValueError:
        raise ValueError("cursor must be an offset") from None
    if offset < 0:
        raise ValueError("cursor must not be negative")
    return offset


def page_of(items: Sequence[T], limit: int, cursor: Optional[str]) -> Tuple[List[T], Optional[str]]:
    """(the page of `limit` rows from `cursor`, the next page's cursor or None at the end)."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    start = offset_of(cursor)
    end = start + limit
    return list(items[start:end]), (str(end) if end < len(items) else None)
