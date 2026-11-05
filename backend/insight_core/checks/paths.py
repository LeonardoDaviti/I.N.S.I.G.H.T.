"""Reading a field out of what a service answered, and testing it (case.schema.json, `path` and the ops).

A path is dotted keys and list indexes: `story.voices`, `story.posts[0].title`, `items[*].id` (every
element), `len(story.posts)`. A missing key reads None, so "is_null" can test that a field is absent."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

_STEP = re.compile(r"([^.\[\]]+)|\[(\*|-?\d+)\]")
_EACH = object()


def plain(value: Any) -> Any:
    """JSON-shaped: datetimes as ISO text, tuples as lists (so cases compare what the API would send)."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [plain(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def get(value: Any, path: Optional[str]) -> Any:
    if not path:
        return value
    if path.startswith("len(") and path.endswith(")"):
        inner = get(value, path[4:-1])
        return len(inner) if inner is not None else 0
    steps: List[Any] = []
    for key, index in _STEP.findall(path):
        steps.append(key if key else (_EACH if index == "*" else int(index)))
    return _walk(value, steps)


def _walk(value: Any, steps: List[Any]) -> Any:
    for i, step in enumerate(steps):
        if value is None:
            return None
        if step is _EACH:
            return [_walk(v, steps[i + 1:]) for v in (value or [])]
        if isinstance(step, int):
            value = value[step] if isinstance(value, list) and -len(value) <= step < len(value) else None
        else:
            value = value.get(step) if isinstance(value, dict) else None
    return value


def _flat(value: Any) -> List[Any]:
    out: List[Any] = []
    for v in value if isinstance(value, list) else [value]:
        out.extend(_flat(v) if isinstance(v, list) else [v])
    return out


def _holds(value: Any, needle: Any) -> bool:
    """A text holds a substring; a list holds an element equal to it, or a text element holding it."""
    if isinstance(value, str):
        return isinstance(needle, str) and needle in value
    if isinstance(value, list):
        return any(v == needle or (isinstance(v, str) and isinstance(needle, str) and needle in v) for v in _flat(value))
    return value == needle


def _count(value: Any, needle: Any) -> int:
    if isinstance(value, str):
        return value.count(needle)
    if isinstance(value, list):
        return sum(1 for v in _flat(value) if v == needle or (isinstance(v, str) and isinstance(needle, str) and needle in v))
    return int(value == needle)


def _ids(value: Any) -> set:
    """Every text anywhere in the value (keys too): the ids a page's answer holds."""
    out: set = set()
    if isinstance(value, dict):
        for k, v in value.items():
            out.add(k)
            out |= _ids(v)
    elif isinstance(value, list):
        for v in value:
            out |= _ids(v)
    elif isinstance(value, str):
        out.add(value)
    return out


def _rank(value: Any) -> Optional[int]:
    rank = value.get("rank") if isinstance(value, dict) else value
    return rank if isinstance(rank, int) and not isinstance(rank, bool) else None


def _many(x: Any) -> List[Any]:
    return x if isinstance(x, list) else [x]


# op -> (value, the case's operand) -> ok. "has_post"/"lacks_post" are resolved to ids before they get here.
OPS: Dict[str, Callable[[Any, Any], bool]] = {
    "equals": lambda v, x: v == x,
    "not_equals": lambda v, x: v != x,
    "contains": lambda v, x: all(_holds(v, n) for n in _many(x)),
    "not_contains": lambda v, x: not any(_holds(v, n) for n in _many(x)),
    "starts_with": lambda v, x: isinstance(v, str) and v.startswith(x),
    "matches": lambda v, x: isinstance(v, str) and re.search(x, v) is not None,
    "not_matches": lambda v, x: not (isinstance(v, str) and re.search(x, v) is not None),
    "at_least": lambda v, x: v is not None and v >= x,
    "at_most": lambda v, x: v is not None and v <= x,
    # A suggestion's place in Discover's list (the discover surface's `rank`, 1 first), read off the
    # suggestion itself or the path's value: one not listed has none (issue 0109).
    "rank_at_most": lambda v, x: _rank(v) is not None and _rank(v) <= x,
    "is_null": lambda v, x: (v is None or v == [] or v == "") == bool(x),
    # x: one list of ids per post the case names; a post is there when any of its ids is, anywhere in the value.
    "has_post": lambda v, x: all(_ids(v) & set(ids) for ids in x),
    "lacks_post": lambda v, x: not any(_ids(v) & set(ids) for ids in x),
}
COUNT_OP = "count"   # {"count": {"of": needle, "equals"|"at_least"|"at_most": n}}


def test(value: Any, op: str, operand: Any) -> Tuple[bool, str]:
    if op == COUNT_OP:
        n = _count(value, operand["of"])
        checks = [(k, operand[k]) for k in ("equals", "at_least", "at_most") if k in operand]
        return all(OPS[k](n, x) for k, x in checks), f"{operand['of']!r} found {n} times"
    return OPS[op](value, operand), ""


def shown(value: Any, limit: int = 160) -> str:
    text = repr(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"
