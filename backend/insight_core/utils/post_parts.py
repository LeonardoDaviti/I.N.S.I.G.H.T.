"""The stored structure of a post (issue 0076: `post_parts`, written by utils/post_parser.py at save):
what the pages read, with no parser. A shown body is stored as cut points into its raw column (Body)."""
from __future__ import annotations

import html as html_lib
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Body:
    """A shown body as cut points into its raw column: `cut` the kept spans [a, b, ...] (None: the raw
    body as it is), read in the raw body with its HTML codes decoded (`decode_entities`), joined by a
    line break each (`cut_leaves_break`); `copy` the body itself where no cut says it."""
    cut: Optional[List[int]] = None
    decode_entities: bool = False
    cut_leaves_break: bool = False
    copy: Optional[str] = None


def shown(raw: Optional[str], body: Body) -> Optional[str]:
    """The shown body a `Body` stores, from its raw column."""
    if body.copy is not None:
        return body.copy
    if body.cut is None:
        return raw
    base = html_lib.unescape(raw or "") if body.decode_entities else raw or ""
    return ("\n" if body.cut_leaves_break else "").join(base[body.cut[i]:body.cut[i + 1]] for i in range(0, len(body.cut), 2))
