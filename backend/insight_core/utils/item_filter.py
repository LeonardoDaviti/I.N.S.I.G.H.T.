"""A source's item filter (issue 0196, Stealth v10.18): which of a followed source's items are kept but hidden.

A release feed that also publishes its automatic builds (per-commit `b12361`, nightlies, `-alpha.N`) would flood the
feed: measured on 18 public release feeds, one engine's feed carried 16.3 items a day, 99% builds. The worker
proposes a rule when a channel is added (the `source_judge` question's `filter`, guide source-judge-v2); this module
checks it, keeps it and applies it, by code, to every new item. Any source may have one; the owner may set or clear it.

    rule = {"kind": "releases" | "builds" | "mixed", "hide": [{"field": "tag" | "title", "regex": "...", "why": "..."}]}

  - `tag` is a release's tag, read from its address (`.../releases/tag/<tag>`); `title` the item's title.
  - **Checks** (`check`): at most HIDE_MAX patterns, each compiles, is at most REGEX_CHARS long, holds no literal digit
    (a shape, `^b\\d+$`, never one version, `v1\\.2`), hides at least one item read, never one the answer keeps (its
    examples of real releases), and never a plain release (`v1.0.0`, `2.3.1`, `Release 1.0`: PLAIN). The spec's "at
    most 95% of the items read" is replaced by PLAIN: a releases Atom feed holds its newest 10 items only, and an
    engine's newest 10 are all builds, so a right rule hides all of them.
  - **Kept** in source_filters (one current row a source; a new rule supersedes the old one, keep everything).
  - **Applied** at store time (repo_posts.save_batch, ingestion's one save path: `mark`) and to a source's stored posts
    when its rule changes (`remark`). A hidden post is stored as any post with `posts.filtered_by` = the rule's row;
    the feeds and unread counts (repo_reader.NOT_STORY_ONLY) and Mark X's reading planners skip it. Nothing is deleted.
"""
from __future__ import annotations

import json
import re
import urllib.parse
from typing import Any, Dict, Iterable, List, Optional, Sequence

KINDS = ("releases", "builds", "mixed")
FIELDS = ("tag", "title")
HIDE_MAX = 4
REGEX_CHARS = 120
WHY_CHARS = 200
# Plain releases a rule may never hide (as a tag and as a title).
PLAIN = ("v1.0.0", "1.0.0", "v2.3", "2.3.1", "v10.2.0", "0.4.12", "Release 1.0", "v1.0", "Version 2.1.0")
_TAG = re.compile(r"/releases/tag/([^/?#]+)")
# A filter's SQL predicate for "shown": the posts no rule hid.
SHOWN_SQL = "p.filtered_by IS NULL"


def tag_of(url: Optional[str]) -> Optional[str]:
    """A release's tag from its address (github.com/<o>/<r>/releases/tag/<tag>, and code hosts of the same shape)."""
    m = _TAG.search(url or "")
    return urllib.parse.unquote(m.group(1)) if m else None


def _compiled(rule: Dict[str, Any]) -> List[tuple]:
    out = []
    for h in rule.get("hide") or []:
        try:
            out.append((h.get("field"), re.compile(h.get("regex") or "")))
        except re.error:
            continue
    return out


def hides(rule: Optional[Dict[str, Any]], title: Optional[str], url: Optional[str]) -> bool:
    """Whether the rule hides an item (its title, its address's tag)."""
    if not rule:
        return False
    tag = tag_of(url)
    title = (title or "").strip()
    for field, rx in _compiled(rule):
        value = tag if field == "tag" else title
        if value and rx.search(value):
            return True
    return False


def _literal_digit(regex: str) -> bool:
    """Whether a pattern holds a digit that is not part of a class or a count (\\d, [0-9], {2,4})."""
    s = re.sub(r"\\[dDwWsS]", "", regex)
    s = re.sub(r"\[[^\]]*\]", "", s)
    s = re.sub(r"\{\d+(,\d*)?\}", "", s)
    return bool(re.search(r"\d", s))


def check(rule: Any, items: Sequence[Dict[str, Any]], keep: Iterable[str] = ()) -> Optional[str]:
    """None when the rule may be kept; else why not. `items`: the items read ({id, title, url}); `keep`: the ids the
    answer says are real releases (never hidden)."""
    if not isinstance(rule, dict):
        return "the filter: not an object"
    if rule.get("kind") not in KINDS:
        return f"the filter's kind: one of {', '.join(KINDS)}"
    hide = rule.get("hide")
    if not isinstance(hide, list) or len(hide) > HIDE_MAX:
        return f"the filter's hide: a list of at most {HIDE_MAX}"
    if not hide:
        return None if rule["kind"] == "releases" else "a filter of builds hides something"
    for h in hide:
        if not isinstance(h, dict) or h.get("field") not in FIELDS:
            return f"a hide pattern's field: one of {', '.join(FIELDS)}"
        regex = h.get("regex")
        if not isinstance(regex, str) or not regex or len(regex) > REGEX_CHARS:
            return f"a hide pattern's regex: 1 to {REGEX_CHARS} characters"
        try:
            re.compile(regex)
        except re.error:
            return f"a hide pattern's regex does not compile: {regex}"
        if _literal_digit(regex):
            return f"a hide pattern names one version, not a shape: {regex}"
        if len((h.get("why") or "")) > WHY_CHARS or "\n" in (h.get("why") or ""):
            return f"a hide pattern's why: one line, at most {WHY_CHARS} characters"
    for plain in PLAIN:
        if hides(rule, plain, f"https://example.invalid/o/r/releases/tag/{urllib.parse.quote(plain)}"):
            return f"the filter would hide a plain release ({plain})"
    keep = set(keep)
    hidden = [i for i in items if hides(rule, i.get("title"), i.get("url"))]
    if not hidden:
        return "the filter hides none of the items read"
    kept_hidden = [i["id"] for i in hidden if i.get("id") in keep]
    if kept_hidden:
        return f"the filter hides an item the answer keeps ({', '.join(kept_hidden[:3])})"
    return None


def clean(rule: Dict[str, Any]) -> Dict[str, Any]:
    """The rule as kept: its kind and patterns, nothing else."""
    return {"kind": rule["kind"], "hide": [{"field": h["field"], "regex": h["regex"], "why": (h.get("why") or "")[:WHY_CHARS]}
                                           for h in rule.get("hide") or []]}


# ---- kept and applied -----------------------------------------------------------------------------------

def current(cur: Any, source_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """{source: {id, rule, by, created_at}} of the current filters of these sources (one query)."""
    ids = sorted({str(s) for s in source_ids if s})
    if not ids:
        return {}
    cur.execute("""SELECT source_id::text, id::text, rule, by, created_at FROM source_filters
                    WHERE superseded_at IS NULL AND source_id = ANY(%s::uuid[])""", (ids,))
    return {sid: {"id": fid, "rule": rule, "by": by, "created_at": at} for sid, fid, rule, by, at in cur.fetchall()}


def mark(cur: Any, post_ids: Sequence[str]) -> int:
    """At store time: the new posts their source's rule hides marked `filtered_by`. One query when no source of
    theirs has a filter. Returns how many were hidden."""
    ids = [str(p) for p in post_ids]
    if not ids:
        return 0
    cur.execute("""SELECT p.id::text, p.title, p.url, f.id::text, f.rule FROM posts p
                     JOIN source_filters f ON f.source_id = p.source_id AND f.superseded_at IS NULL
                    WHERE p.id = ANY(%s::uuid[])""", (ids,))
    hidden: Dict[str, List[str]] = {}
    for pid, title, url, fid, rule in cur.fetchall():
        if hides(rule, title, url):
            hidden.setdefault(fid, []).append(pid)
    for fid, pids in hidden.items():
        cur.execute("UPDATE posts SET filtered_by = %s WHERE id = ANY(%s::uuid[])", (fid, pids))
    return sum(len(p) for p in hidden.values())


def remark(cur: Any, source_id: str) -> int:
    """A source's stored posts marked again under its current rule (none: every post shown). Returns how many are
    hidden now."""
    got = current(cur, [source_id]).get(str(source_id))
    cur.execute("UPDATE posts SET filtered_by = NULL WHERE source_id = %s AND filtered_by IS NOT NULL", (source_id,))
    if got is None:
        return 0
    cur.execute("SELECT id::text, title, url FROM posts WHERE source_id = %s", (source_id,))
    pids = [pid for pid, title, url in cur.fetchall() if hides(got["rule"], title, url)]
    if pids:
        cur.execute("UPDATE posts SET filtered_by = %s WHERE id = ANY(%s::uuid[])", (got["id"], pids))
    return len(pids)


def put(cur: Any, source_id: str, rule: Optional[Dict[str, Any]], *, by: str, guide: Optional[str] = None,
        task_id: Optional[str] = None) -> Optional[str]:
    """The source's new rule (None: none), the old one superseded, its posts marked again. Returns the new row's id."""
    cur.execute("UPDATE source_filters SET superseded_at = now() WHERE source_id = %s AND superseded_at IS NULL",
                (source_id,))
    fid = None
    if rule is not None:
        cur.execute("""INSERT INTO source_filters (source_id, rule, by, guide, task_id) VALUES (%s, %s::jsonb, %s, %s, %s)
                       RETURNING id::text""", (source_id, json.dumps(clean(rule)), by, guide, task_id))
        fid = cur.fetchone()[0]
    remark(cur, source_id)
    return fid


def hidden_count(cur: Any, source_ids: Iterable[str]) -> Dict[str, int]:
    """{source: how many of its posts a rule hides} (the partial index on filtered_by)."""
    ids = sorted({str(s) for s in source_ids if s})
    if not ids:
        return {}
    cur.execute("""SELECT source_id::text, count(*) FROM posts WHERE source_id = ANY(%s::uuid[])
                     AND filtered_by IS NOT NULL GROUP BY 1""", (ids,))
    return dict(cur.fetchall())


__all__ = ["KINDS", "PLAIN", "SHOWN_SQL", "check", "clean", "current", "hidden_count", "hides", "mark", "put",
           "remark", "tag_of"]
