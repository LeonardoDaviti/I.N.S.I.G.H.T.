"""A track's suggested fields (Stealth v10.41, FIX 6; owner 2026-11-23: fields are the owner's decision).

The schema (markx/track_things.py) is proposed once from the track's words, before any post is read; what its posts
keep saying that no field holds shows only later. So, once a schema version has rows, INSIGHT asks Haiku which
fields the track's records miss: the schema planner's kind (`track_schema`), its second guide FIELDS_GUIDE
(track-fields-v1, schemas.GUIDE_VARIANTS: its own answer schema and check). The question shows the track's words, its
kinds and fields, a sample of its rows (the newest ROWS_SAMPLE) and of their posts (the newest POSTS_SAMPLE, title and
opening); one question a track and schema version (its input's first line names both).

The answer is never applied: it is a list of suggestions the track page shows ("Suggested fields", `suggestions`):
Add is the owner's schema edit (PUT .../schema, track_things.set_schema: a version of their own, its posts read again
under it); Dismiss (`dismiss`) keeps the field from being suggested again (mx_track_field_dismissals). A field the
schema has now (any version) is not suggested. Nothing here names a track, a kind or a field.

Behind entity_bands.json `tracks.briefs` (track_things.on), as the schema is.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set

from insight_core.markx import track_things as TT

FIELDS_GUIDE = "track-fields-v1"
FIELDS_MAX = 6          # fields one answer suggests at most
FIELDS_MIN_ROWS = 8     # rows read under the current schema version before its fields are asked about
ROWS_SAMPLE = 20        # rows of the owner's kinds a question shows (the newest)
PRACTICE_SAMPLE = 6     # practices it shows besides (the newest)
POSTS_SAMPLE = 10       # posts a question shows (the newest of those rows')
POST_CHARS = 400        # characters of a post's text a question shows
ROW_CHARS = 300

_HEAD = re.compile(r"^FIELDS: (\S+) v(\d+)$", re.M)
_KIND = re.compile(r"^- ([a-z][a-z0-9_]*) \(.*?\): (.*)$", re.M)


def head(track_id: str, version: int) -> str:
    return f"FIELDS: {track_id} v{version}"


def _field_line(f: Dict[str, Any]) -> str:
    extra = f.get("unit") or (", ".join(f.get("values") or []) if f["type"] == "enum" else "")
    return f"{f['name']} ({f['type']}{': ' + extra if extra else ''})"


def fields_input(track: Dict[str, Any], schema: Dict[str, Any], version: int, rows: Sequence[Dict[str, Any]],
                 posts: Sequence[Dict[str, Any]], total: Optional[int] = None) -> str:
    """The question (pure): the head line, the track's words, its kinds and fields, the rows (each a thing view:
    {kind, fields: {name: {shown}}}) and the posts ({title, text})."""
    lines = [head(track["folder_id"], version)] + TT.header(track) + ["", "KINDS:"]
    for k in schema["kinds"]:
        lines.append(f"- {k['kind']} ({k.get('about') or ''}): " + "; ".join(_field_line(f) for f in k["fields"]))
    lines += ["", f"ROWS ({len(rows)} of {total if total is not None else len(rows)}):"]
    for r in rows:
        vals = " | ".join(f"{n}: {v['shown']}" for n, v in r["fields"].items())
        lines.append(f"[{r['kind']}] {' '.join(vals.split())[:ROW_CHARS]}")
    lines += ["", f"POSTS ({len(posts)}):"]
    for i, p in enumerate(posts, 1):
        text = " ".join((p.get("text") or "").split())[:POST_CHARS]
        lines.append(f"[{i}] {' '.join((p.get('title') or '').split())} :: {text}")
    return "\n".join(lines)


def pick_rows(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The rows a question shows (given newest first): the owner's kinds' newest ROWS_SAMPLE (their fields are what
    may be added to), then the newest PRACTICE_SAMPLE practices (what the posts say beside them)."""
    own = [x for x in rows if x["kind"] != TT.PRACTICE_KIND][:ROWS_SAMPLE]
    return own + [x for x in rows if x["kind"] == TT.PRACTICE_KIND][:PRACTICE_SAMPLE]


def kinds_of(input: str) -> Dict[str, Set[str]]:
    """{kind: its field names} as a question showed them."""
    return {m.group(1): {x.split(" (")[0].strip() for x in m.group(2).split("; ") if x.strip()}
            for m in _KIND.finditer(input)}


def check(answer: Dict[str, Any], input: str) -> Optional[str]:
    """track-fields-v1's check (validate.GUIDE_CHECKS): each field of a kind shown, not one it has, named once, an
    enum with its values; at most FIELDS_MAX."""
    from insight_core.markx import schemas
    kinds = kinds_of(input)
    got = answer.get("fields") or []
    if len(got) > FIELDS_MAX:
        return f"at most {FIELDS_MAX} fields"
    seen: Set[tuple] = set()
    for f in got:
        if f["kind"] not in kinds or f["kind"] == TT.PRACTICE_KIND:
            return f"{f['kind']}: not a kind shown" if f["kind"] not in kinds else f"{f['kind']} is fixed"
        if f["name"] in kinds[f["kind"]]:
            return f"{f['kind']}.{f['name']}: the kind has it"
        if (f["kind"], f["name"]) in seen:
            return f"{f['kind']}.{f['name']} twice"
        seen.add((f["kind"], f["name"]))
        if f["type"] == "enum" and len(f.get("values") or []) < schemas.THING_ENUM[0]:
            return f"{f['kind']}.{f['name']}: an enum needs {schemas.THING_ENUM[0]}+ values"
    return None


def _sample(cur: Any, track: Dict[str, Any], version: int) -> Optional[str]:
    """The question for the track's current schema version, or None while fewer than FIELDS_MIN_ROWS rows were read
    under it."""
    from insight_core.markx import track_brief
    tid = track["folder_id"]
    s = TT.current_schema(cur, tid)
    rows = [x for x in TT.current(cur, tid) if x["schema_version"] == version]
    if s is None or len(rows) < FIELDS_MIN_ROWS:
        return None
    kinds = {k["kind"]: k for k in s["schema"]["kinds"]}
    shown = pick_rows([x for x in rows if x["kind"] in kinds])
    rs = TT.reports(cur, tid, [x["id"] for x in shown])
    post_ids = list(dict.fromkeys(r["post"] for x in shown for r in reversed(rs.get(x["id"], []))))[:POSTS_SAMPLE]
    posts = track_brief._posts(cur, tid, post_ids)
    views = [track_brief.thing_view(kinds[x["kind"]], x, rs.get(x["id"], []), posts) for x in shown]
    cur.execute("SELECT id::text, content FROM posts WHERE id = ANY(%s::uuid[])", (post_ids,))
    text = dict(cur.fetchall())
    return fields_input(track, s["schema"], version, views,
                        [{"title": posts[p]["title"], "text": text.get(p)} for p in post_ids if p in posts], len(rows))


def plan(cur: Any, **_kw: Any) -> int:
    """The schema planner's part: a fields question for each topic track whose current schema version has rows and
    was not asked about yet. How many were added."""
    from insight_core.markx import repo, schemas, tracks
    if not TT.on():
        return 0
    schemas.ensure_guides(cur)
    added = 0
    for t in tracks.described(cur):
        s = TT.current_schema(cur, t["folder_id"])
        if s is None:
            continue
        cur.execute("""SELECT 1 FROM mx_tasks WHERE kind = %s AND guide = %s AND a = %s::uuid AND input LIKE %s
                        LIMIT 1""", (TT.SCHEMA_KIND, FIELDS_GUIDE, t["folder_id"],
                                     head(t["folder_id"], s["version"]) + "\n%"))
        if cur.fetchone():
            continue
        q = _sample(cur, t, s["version"])
        if q is None:
            continue
        _task, new = repo.add_task(cur, kind=TT.SCHEMA_KIND, guide=FIELDS_GUIDE, subject_kind="track", input=q,
                                   a=t["folder_id"])
        added += new
    return added


def suggestions(cur: Any, folder_id: Any) -> Dict[str, Any]:
    """GET .../schema/suggestions: {on, asked_for (the schema version asked about), at, fields: [{kind, name, type,
    unit, values, about, why}]}: the newest answer's fields, less those the schema has now and those dismissed.
    KeyError: not a topic track."""
    from insight_core.markx import tracks
    t = tracks.get(cur, folder_id)
    if not tracks.is_topic(t):
        raise KeyError(folder_id)
    tid = t["folder_id"]
    empty = {"on": TT.on(), "asked_for": None, "at": None, "fields": []}
    if not TT.on():
        return empty
    cur.execute("""SELECT k.input, c.answer, c.created_at FROM mx_tasks k JOIN mx_calls c ON c.task_id = k.id AND c.valid
                    WHERE k.kind = %s AND k.guide = %s AND k.a = %s::uuid
                    ORDER BY c.created_at DESC LIMIT 1""", (TT.SCHEMA_KIND, FIELDS_GUIDE, tid))
    r = cur.fetchone()
    s = TT.current_schema(cur, tid)
    if r is None or s is None:
        return empty
    input, answer, at = r
    m = _HEAD.search(input)
    have = {k["kind"]: {f["name"] for f in k["fields"]} for k in s["schema"]["kinds"]}
    cur.execute("SELECT kind, field FROM mx_track_field_dismissals WHERE track_id = %s::uuid", (tid,))
    gone = set(cur.fetchall())
    keep = ("kind", "name", "type", "unit", "values", "about", "why")
    fields = [{k: f[k] for k in keep if f.get(k) is not None} for f in (answer or {}).get("fields") or []
              if f["kind"] in have and f["name"] not in have[f["kind"]] and (f["kind"], f["name"]) not in gone]
    return {"on": True, "asked_for": int(m.group(2)) if m else None, "at": at.isoformat(), "fields": fields}


def dismiss(cur: Any, folder_id: Any, kind: str, name: str) -> Dict[str, Any]:
    """The owner dismissed a suggested field: never suggested again for this track. The suggestions left."""
    from insight_core.markx import tracks
    t = tracks.get(cur, folder_id)
    if not tracks.is_topic(t):
        raise KeyError(folder_id)
    cur.execute("""INSERT INTO mx_track_field_dismissals (track_id, kind, field) VALUES (%s::uuid, %s, %s)
                   ON CONFLICT DO NOTHING""", (t["folder_id"], kind, name))
    return suggestions(cur, folder_id)
