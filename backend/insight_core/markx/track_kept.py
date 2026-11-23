"""The topic tracks' placements, kept (mx_track_*), so readers don't place every track per request.

tracks.placed places every judged post of a track; its result is kept here and read, and a track never placed is
placed live. `refresh` (after each ingestion run, the planner and the jobs process's "tracks" view) places the changed
tracks again. The triggers on a track's inputs log whose change it is (mx_track_changes.owner):
  - the owner's own (a label, the folder's sources, a source switched on or off): the track is placed live until
    placed again (a read is never wrong for the owner's own action), and `refresh` places it at its next call;
  - the worker's and the ingestion's (a verdict answered, a post deleted or moved): readers read the kept placement,
    and `refresh` places it again once it is REFRESH_GAP old (a large track placed live on every read is too slow).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.db.repo_post_parts import shown_title

REFRESH_LOCK = 0x7472_0195   # one refresh at a time; a second skips (the tracks stay as they are until the next)
REFRESH_GAP = 300.0          # a track changed by the worker only is placed again at most every 5 minutes

_COLS = ("post_id", "place", "rank", "calibrated", "label", "active", "verdict", "confidence", "subtopic",
         "answered_at", "found_by")


def calibration(cur: Cursor, track_id: str) -> Optional[Dict[str, Any]]:
    """The track's kept calibration, or None when it is not kept or the owner changed its inputs since (read it live).
    A change of the worker's or the ingestion's alone reads the kept placement."""
    cur.execute("""SELECT s.calibration FROM mx_track_places_state s
                    WHERE s.track_id = %s
                      AND NOT EXISTS (SELECT 1 FROM mx_track_changes c WHERE c.track_id = s.track_id AND c.owner)""",
                (str(track_id),))
    row = cur.fetchone()
    return row[0] if row else None


def placed(cur: Cursor, track: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """tracks.placed(cur, track) from what is kept: {items, calibration} in the same order, each item with its post,
    place, rank, calibrated, label, active, verdict, confidence, subtopic, answered_at, found_by, source_id and `at`
    (not its title, address, source name or why: `fill` adds those to the items shown). None: place it live."""
    from insight_core.markx import tracks
    cal = calibration(cur, track["folder_id"])
    if cal is None:
        return None
    cur.execute(f"""SELECT {", ".join("k." + c for c in _COLS)}, p.source_id::text, {tracks._date()}
                      FROM mx_track_places k JOIN posts p ON p.id = k.post_id
                     WHERE k.track_id = %s ORDER BY k.post_id""", (track["folder_id"],))
    items = []
    for row in cur.fetchall():
        it = dict(zip(_COLS + ("source_id", "at"), row))
        it["post_id"] = str(it["post_id"])
        it["found_by"] = list(it["found_by"]) if it["found_by"] is not None else None
        items.append(it)
    return {"items": items, "calibration": cal}


def fill(cur: Cursor, track: Dict[str, Any], items: Sequence[Dict[str, Any]]) -> None:
    """Add to kept items what tracks._shown shows besides their place: title, url, source, why (the newest verdict's)."""
    ids = [it["post_id"] for it in items if "title" not in it]
    if not ids:
        return
    # The title every page shows (a title-less post's, a toot's, is its first line, never "")
    cur.execute(f"""SELECT DISTINCT ON (i.post_id) i.post_id::text, i.why, {shown_title()}, p.url,
                          COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                                   s.handle_or_url)
                     FROM mx_track_items i JOIN posts p ON p.id = i.post_id JOIN sources s ON s.id = p.source_id
                    WHERE i.track_id = %s AND i.verdict IS NOT NULL AND i.post_id = ANY(%s::uuid[])
                    ORDER BY i.post_id, i.version DESC""", (track["folder_id"], ids))
    got = {pid: (why, title, url, source) for pid, why, title, url, source in cur.fetchall()}
    for it in items:
        if it["post_id"] in got:
            it["why"], it["title"], it["url"], it["source"] = got[it["post_id"]]


def posts_in(cur: Cursor, track: Dict[str, Any], places: Sequence[str]) -> Optional[List[str]]:
    """The posts placed in `places` from what is kept (by post id), or None (place it live). The track's reading views
    read this (track_feed)."""
    if calibration(cur, track["folder_id"]) is None:
        return None
    cur.execute("""SELECT k.post_id::text FROM mx_track_places k JOIN posts p ON p.id = k.post_id
                    WHERE k.track_id = %s AND k.place = ANY(%s) ORDER BY k.post_id""",
                (track["folder_id"], list(places)))
    return [pid for (pid,) in cur.fetchall()]


def counts(cur: Cursor, track: Dict[str, Any], inside_places: Sequence[str]) -> Optional[Tuple[List[str], int]]:
    """(the posts placed in `inside_places`, the number placed in Discover) from what is kept, or None (live)."""
    inside = posts_in(cur, track, inside_places)
    if inside is None:
        return None
    # Discover counted where it is kept (only a number is sent)
    cur.execute("""SELECT count(*) FROM mx_track_places k JOIN posts p ON p.id = k.post_id
                    WHERE k.track_id = %s AND k.place = 'discover'""", (track["folder_id"],))
    return inside, cur.fetchone()[0]


def suggestible(cur: Cursor, track: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """The items tracks.suggestions counts (judged in or labelled in, not labelled out, from a passive source not
    switched off), each {source_id, source, at}, in placed()'s order; None: place it live."""
    if calibration(cur, track["folder_id"]) is None:
        return None
    from insight_core.db.repo_stories import suggestable_sql
    from insight_core.markx import tracks
    cur.execute(f"""SELECT p.source_id::text,
                           COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                                    s.handle_or_url),
                           {tracks._date()}
                      FROM mx_track_places k JOIN posts p ON p.id = k.post_id JOIN sources s ON s.id = p.source_id
                     WHERE k.track_id = %s AND (k.verdict OR k.label = 'in') AND k.label IS DISTINCT FROM 'out'
                       AND NOT k.active AND {suggestable_sql("p.source_id")}
                     ORDER BY k.post_id""", (track["folder_id"],))
    return [{"source_id": sid, "source": name, "at": at} for sid, name, at in cur.fetchall()]


def write_places(cur: Cursor, tid: str, items: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """Make the track's kept rows these placed items, writing only what differs: a row whose post is no longer placed is
    deleted, a new or changed one upserted, an unchanged one not written (a refresh changes a few rows of many). The
    same rows result. {deleted, written}."""
    # One statement, one snapshot: `y` the rows the placement makes (a post with a judged item), `gone` the kept rows
    # it no longer makes, `up` the new rows and the rows that differ (compared by a read; an ON CONFLICT ... WHERE
    # alone would still lock, and so write, every unchanged row).
    cur.execute("""WITH y AS MATERIALIZED (
                       SELECT x.post_id, x.place, x.rank, x.calibrated, x.label, x.active, x.verdict, x.confidence,
                              i.subtopic, i.answered_at, i.found_by
                         FROM unnest(%(posts)s::uuid[], %(place)s::text[], %(rank)s::float8[], %(calibrated)s::bool[],
                                     %(label)s::text[], %(active)s::bool[], %(verdict)s::bool[], %(confidence)s::real[])
                              AS x(post_id, place, rank, calibrated, label, active, verdict, confidence)
                         JOIN LATERAL (SELECT subtopic, answered_at, found_by FROM mx_track_items
                                        WHERE track_id = %(tid)s::uuid AND post_id = x.post_id AND verdict IS NOT NULL
                                        ORDER BY version DESC LIMIT 1) i ON true),
                   gone AS (DELETE FROM mx_track_places k
                             WHERE k.track_id = %(tid)s::uuid AND NOT EXISTS (SELECT 1 FROM y WHERE y.post_id = k.post_id)
                            RETURNING 1),
                   up AS (INSERT INTO mx_track_places (track_id, post_id, place, rank, calibrated, label, active, verdict,
                                                       confidence, subtopic, answered_at, found_by)
                          SELECT %(tid)s::uuid, y.post_id, y.place, y.rank, y.calibrated, y.label, y.active, y.verdict,
                                 y.confidence, y.subtopic, y.answered_at, y.found_by
                            FROM y LEFT JOIN mx_track_places o ON o.track_id = %(tid)s::uuid AND o.post_id = y.post_id
                           WHERE o.post_id IS NULL
                              OR (o.place, o.rank, o.calibrated, o.label, o.active, o.verdict, o.confidence, o.subtopic,
                                  o.answered_at, o.found_by)
                                 IS DISTINCT FROM
                                 (y.place, y.rank, y.calibrated, y.label, y.active, y.verdict, y.confidence, y.subtopic,
                                  y.answered_at, y.found_by)
                          ON CONFLICT (track_id, post_id) DO UPDATE
                             SET place = EXCLUDED.place, rank = EXCLUDED.rank, calibrated = EXCLUDED.calibrated,
                                 label = EXCLUDED.label, active = EXCLUDED.active, verdict = EXCLUDED.verdict,
                                 confidence = EXCLUDED.confidence, subtopic = EXCLUDED.subtopic,
                                 answered_at = EXCLUDED.answered_at, found_by = EXCLUDED.found_by
                          RETURNING 1)
                   SELECT (SELECT count(*) FROM gone), (SELECT count(*) FROM up)""",
                {"tid": tid, "posts": [it["post_id"] for it in items], "place": [it["place"] for it in items],
                 "rank": [float(it["rank"]) for it in items], "calibrated": [bool(it["calibrated"]) for it in items],
                 "label": [it["label"] for it in items], "active": [bool(it["active"]) for it in items],
                 "verdict": [it["verdict"] for it in items], "confidence": [it["confidence"] for it in items]})
    deleted, written = cur.fetchone()
    return {"deleted": int(deleted), "written": int(written)}


def due(cur: Cursor, *, gap: float = REFRESH_GAP) -> bool:
    """Whether `refresh` would place a kept track again now (the jobs process's "tracks" view looks): the owner changed
    its inputs, or the worker did and its placement is `gap` old. A few indexed reads."""
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_track_changes c JOIN mx_track_places_state s USING (track_id)
                                   WHERE c.owner OR s.placed_at <= now() - make_interval(secs => %s))""", (gap,))
    return bool(cur.fetchone()[0])


def refresh(cur: Cursor, *, gap: float = REFRESH_GAP) -> Optional[int]:
    """Place again every topic track that was never placed, whose inputs the owner changed, or whose inputs the worker
    or the ingestion changed and whose placement is `gap` seconds old or more; the tracks placed, or None when another
    refresh runs. Only the change rows read before the placement are removed: a change committed meanwhile stays logged.
    The caller commits."""
    from insight_core.markx import tracks
    cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (REFRESH_LOCK,))
    if not cur.fetchone()[0]:
        return None
    topics = tracks.described(cur)
    cur.execute("DELETE FROM mx_track_places_state WHERE NOT (track_id = ANY(%s::uuid[]))",
                ([t["folder_id"] for t in topics],))
    cur.execute("DELETE FROM mx_track_places WHERE NOT (track_id = ANY(%s::uuid[]))", ([t["folder_id"] for t in topics],))
    cur.execute("SELECT track_id::text, placed_at <= now() - make_interval(secs => %s) FROM mx_track_places_state",
                (gap,))
    kept = dict(cur.fetchall())   # {track: its placement is `gap` old}
    cur.execute("SELECT id, track_id::text, owner FROM mx_track_changes")
    taken: Dict[str, List[int]] = {}
    owners = set()
    for cid, tid, owner in cur.fetchall():
        taken.setdefault(tid, []).append(cid)
        if owner:
            owners.add(tid)
    placed_n = 0
    for t in topics:
        tid = t["folder_id"]
        if tid in kept and (tid not in taken or (tid not in owners and not kept[tid])):
            continue   # unchanged, or changed by the worker only and placed less than `gap` ago (its rows stay)
        got = tracks.placed(cur, t, shown=False)
        items = got["items"]
        write_places(cur, tid, items)
        cur.execute("""INSERT INTO mx_track_places_state (track_id, calibration, placed_at) VALUES (%s, %s::json, now())
                       ON CONFLICT (track_id) DO UPDATE SET calibration = EXCLUDED.calibration, placed_at = now()""",
                    (tid, json.dumps(got["calibration"])))
        if taken.get(tid):
            cur.execute("DELETE FROM mx_track_changes WHERE id = ANY(%s)", (taken[tid],))
        placed_n += 1
    # the log of tracks that are no topic (a plain folder's sources changed): nothing reads it
    others = [cid for tid, ids in taken.items() if tid not in {t["folder_id"] for t in topics} for cid in ids]
    if others:
        cur.execute("DELETE FROM mx_track_changes WHERE id = ANY(%s)", (others,))
    return placed_n
