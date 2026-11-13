"""The topic tracks' placements, kept (issue 0195, migration 0133).

tracks.placed places every judged post of a track (its newest verdict, the owner's labels, the active sources, the
calibration). The sidebar's counts placed every topic track per request, the source suggestions too, and a track's
page twice: 0.5-1.9 s on the server, and 100-230 MiB more in the API per request. The placements are kept here and
read; a track whose inputs changed since its last placement (mx_track_changes, written by triggers on its inputs) or
that was never placed is placed live, exactly as before, so a read is never stale. `refresh` (after each ingestion
run) places the changed tracks again. The planner is not touched: the placement is tracks.placed itself.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from psycopg import Cursor

REFRESH_LOCK = 0x7472_0195   # one refresh at a time; a second skips (the tracks stay placed live until the next)

_COLS = ("post_id", "place", "rank", "calibrated", "label", "active", "verdict", "confidence", "subtopic",
         "answered_at", "found_by")


def calibration(cur: Cursor, track_id: str) -> Optional[Dict[str, Any]]:
    """The track's kept calibration, or None when it is not kept or its inputs changed since (read it live)."""
    cur.execute("""SELECT s.calibration FROM mx_track_places_state s
                    WHERE s.track_id = %s AND NOT EXISTS (SELECT 1 FROM mx_track_changes c WHERE c.track_id = s.track_id)""",
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
    cur.execute("""SELECT DISTINCT ON (i.post_id) i.post_id::text, i.why, p.title, p.url,
                          COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                                   s.handle_or_url)
                     FROM mx_track_items i JOIN posts p ON p.id = i.post_id JOIN sources s ON s.id = p.source_id
                    WHERE i.track_id = %s AND i.verdict IS NOT NULL AND i.post_id = ANY(%s::uuid[])
                    ORDER BY i.post_id, i.version DESC""", (track["folder_id"], ids))
    got = {pid: (why, title, url, source) for pid, why, title, url, source in cur.fetchall()}
    for it in items:
        if it["post_id"] in got:
            it["why"], it["title"], it["url"], it["source"] = got[it["post_id"]]


def counts(cur: Cursor, track: Dict[str, Any], inside_places: Sequence[str]) -> Optional[Tuple[List[str], int]]:
    """(the posts placed in `inside_places`, the number placed in Discover) from what is kept, or None (live)."""
    if calibration(cur, track["folder_id"]) is None:
        return None
    cur.execute("""SELECT k.post_id::text, k.place FROM mx_track_places k JOIN posts p ON p.id = k.post_id
                    WHERE k.track_id = %s AND (k.place = ANY(%s) OR k.place = 'discover') ORDER BY k.post_id""",
                (track["folder_id"], list(inside_places)))
    rows = cur.fetchall()
    return [pid for pid, place in rows if place in inside_places], sum(1 for _p, place in rows if place == "discover")


def suggestible(cur: Cursor, track: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """The items tracks.suggestions counts (judged in or labelled in, not labelled out, from a passive source), each
    {source_id, source, at}, in placed()'s order; None: place it live."""
    if calibration(cur, track["folder_id"]) is None:
        return None
    from insight_core.markx import tracks
    cur.execute(f"""SELECT p.source_id::text,
                           COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                                    s.handle_or_url),
                           {tracks._date()}
                      FROM mx_track_places k JOIN posts p ON p.id = k.post_id JOIN sources s ON s.id = p.source_id
                     WHERE k.track_id = %s AND (k.verdict OR k.label = 'in') AND k.label IS DISTINCT FROM 'out'
                       AND NOT k.active
                     ORDER BY k.post_id""", (track["folder_id"],))
    return [{"source_id": sid, "source": name, "at": at} for sid, name, at in cur.fetchall()]


def refresh(cur: Cursor) -> Optional[int]:
    """Place again every topic track whose inputs changed or that was never placed; the tracks placed, or None when
    another refresh runs. The change rows taken are read before the placement, and only those are removed: a change
    committed meanwhile stays logged (the track is read live until the next refresh). The caller commits."""
    from insight_core.markx import tracks
    cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (REFRESH_LOCK,))
    if not cur.fetchone()[0]:
        return None
    topics = tracks.described(cur)
    cur.execute("DELETE FROM mx_track_places_state WHERE NOT (track_id = ANY(%s::uuid[]))",
                ([t["folder_id"] for t in topics],))
    cur.execute("DELETE FROM mx_track_places WHERE NOT (track_id = ANY(%s::uuid[]))", ([t["folder_id"] for t in topics],))
    cur.execute("SELECT track_id::text FROM mx_track_places_state")
    kept = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT id, track_id::text FROM mx_track_changes")
    taken: Dict[str, List[int]] = {}
    for cid, tid in cur.fetchall():
        taken.setdefault(tid, []).append(cid)
    placed_n = 0
    for t in topics:
        tid = t["folder_id"]
        if tid in kept and tid not in taken:
            continue
        got = tracks.placed(cur, t, shown=False)
        items = got["items"]
        cur.execute("DELETE FROM mx_track_places WHERE track_id = %s", (tid,))
        cur.execute("""INSERT INTO mx_track_places (track_id, post_id, place, rank, calibrated, label, active, verdict,
                                                    confidence, subtopic, answered_at, found_by)
                       SELECT %s::uuid, x.post_id, x.place, x.rank, x.calibrated, x.label, x.active, x.verdict,
                              x.confidence, i.subtopic, i.answered_at, i.found_by
                         FROM unnest(%s::uuid[], %s::text[], %s::float8[], %s::bool[], %s::text[], %s::bool[], %s::bool[],
                                     %s::real[]) AS x(post_id, place, rank, calibrated, label, active, verdict, confidence)
                         JOIN LATERAL (SELECT subtopic, answered_at, found_by FROM mx_track_items
                                        WHERE track_id = %s::uuid AND post_id = x.post_id AND verdict IS NOT NULL
                                        ORDER BY version DESC LIMIT 1) i ON true""",
                    (tid, [it["post_id"] for it in items], [it["place"] for it in items],
                     [float(it["rank"]) for it in items], [bool(it["calibrated"]) for it in items],
                     [it["label"] for it in items], [bool(it["active"]) for it in items],
                     [it["verdict"] for it in items], [it["confidence"] for it in items], tid))
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
