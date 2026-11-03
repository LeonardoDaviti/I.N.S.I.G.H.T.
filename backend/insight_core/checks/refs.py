"""A case names its posts by reference (case.schema.json, `ref`): an address, or a source and words of
its title for a post whose address the case doesn't hold. A reference resolves to the stored posts it
names, first seen first (the order 0049's "first seen" uses)."""
from __future__ import annotations

from typing import Any, Dict, List, Union

from insight_core.checks import compat

Ref = Union[str, Dict[str, Any]]


class RefError(Exception):
    """A reference names no stored post (the copy doesn't hold it, or the case is wrong)."""


def describe(ref: Ref) -> str:
    if isinstance(ref, str):
        return ref
    return " ".join(f"{k}={v!r}" for k, v in ref.items())


def resolve(cur: Any, ref: Ref, cache: Dict[str, List[str]] | None = None) -> List[str]:
    """The ids of the stored posts `ref` names, first seen first; RefError when none.

    - "https://…": the post at that address (its url, else its normalized address);
    - {"url": …, "source": …}: the same, from that source only (two sources store one address);
    - {"source": …, "title": …}: that source's post whose title (as the feed shows it) or stored title
      holds the words; `source` matches the source's handle or address, or its display name.
    """
    key = describe(ref)
    if cache is not None and key in cache:
        return cache[key]
    spec = {"url": ref} if isinstance(ref, str) else dict(ref)
    where, params = [], []
    if spec.get("url"):
        where.append("(p.url = %s OR p.normalized_url = %s)")
        params += [spec["url"], compat.normalize(spec["url"])]
    if spec.get("source"):
        where.append("(s.handle_or_url ILIKE %s OR s.settings->>'display_name' ILIKE %s)")
        params += [f"%{spec['source']}%", f"%{spec['source']}%"]
    if not where:
        raise RefError(f"a reference needs a url or a source: {key}")
    text_chars, html_chars = compat.title_window()
    cur.execute(
        f"""SELECT p.id, p.title, left(p.content, {text_chars}), left(p.content_html, {html_chars})
            FROM posts p JOIN sources s ON s.id = p.source_id
            WHERE {' AND '.join(where)}
            ORDER BY p.fetched_at, p.created_at, p.id""",
        params,
    )
    rows = cur.fetchall()
    words = spec.get("title")
    if words:
        title = compat.title_function()
        rows = [r for r in rows if words in (r[1] or "") or words in title(r[1], r[2], r[3])]
    ids = [str(r[0]) for r in rows]
    if not ids:
        raise RefError(f"no stored post: {key}")
    if cache is not None:
        cache[key] = ids
    return ids


def one(cur: Any, ref: Ref, cache: Dict[str, List[str]] | None = None) -> str:
    """The first post seen that `ref` names."""
    return resolve(cur, ref, cache)[0]
