"""Why a post is, or is not, in a track. Read only over stored rows: no model call, no task, no vector computed.

`why(cur, track, post)` -> {state, ...}:
  - judged (the newest stored verdict, as tracks.placed reads it): `in`, `joined` (passive, at or above the join
    band), `discover` (passive, below it: `position` of `of`, `shown`), `checking` / `checked_out` (the blind check),
    `off` (a passive source the owner switched off), `out`; each with Haiku's why, confidence, subtopic, origin,
    found_by, `version` (`current`, `waiting_again`) and `guide`;
  - `waiting` (asked, no answer), `invalid` (the task failed with no verdict: `error`);
  - `not_asked` with `reason`: not_a_topic, labelled, outside_window, not_planned (also a passive post an ALWAYS
    finder puts up: `found_by`, e.g. a page the owner saved), not_embedded, no_profile, history_pending, below_bar (`bar`).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from insight_core.markx import pairing, tasks, tracks

DATE = pairing.ordinary_date("p")


def _post(cur: Any, post_id: str, folder: str) -> Optional[Dict[str, Any]]:
    cur.execute(f"""SELECT p.id::text, p.source_id::text, {DATE},
                           EXISTS (SELECT 1 FROM mx_embeddings e WHERE e.post_id = p.id AND e.model = %s),
                           EXISTS (SELECT 1 FROM source_folders sf WHERE sf.folder_id = %s AND sf.source_id = p.source_id)
                      FROM posts p WHERE p.id = %s""", (tracks.MODEL, folder, post_id))
    row = cur.fetchone()
    return dict(zip(("id", "source_id", "at", "embedded", "active"), row)) if row else None


def _rows(cur: Any, folder: str, post_id: str):
    """The post's rows for the track, newest version first, with its task's status and last error, and the guide its
    verdict was answered under (a re-asked row's verdict may be an earlier task's)."""
    cur.execute("""SELECT i.version, i.verdict, i.confidence, i.subtopic, i.why, i.origin, i.found_by, i.answered_at,
                          k.status, k.last_error, vt.guide, vt.id IS DISTINCT FROM i.task_id AND i.verdict IS NOT NULL
                     FROM mx_track_items i JOIN mx_tasks k ON k.id = i.task_id
                     LEFT JOIN mx_calls c ON c.id = i.call_id LEFT JOIN mx_tasks vt ON vt.id = c.task_id
                    WHERE i.track_id = %s AND i.post_id = %s ORDER BY i.version DESC""", (folder, post_id))
    cols = ("version", "verdict", "confidence", "subtopic", "why", "origin", "found_by", "answered_at", "status",
            "error", "guide", "reasked")
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def _judged(cur: Any, t: Dict[str, Any], post: Dict[str, Any], row: Dict[str, Any], label: Optional[str],
            waiting_again: bool) -> Dict[str, Any]:
    got = tracks.placed(cur, t, shown=False)
    items, cal = got["items"], got["calibration"]
    me = next((it for it in items if it["post_id"] == post["id"]), None)
    place = me["place"] if me else "out"
    out: Dict[str, Any] = {
        "state": "in" if place == "track" else place, "label": label, "verdict": row["verdict"],
        "confidence": None if row["confidence"] is None else round(float(row["confidence"]), 3),
        "why": row["why"], "subtopic": row["subtopic"], "origin": "active" if post["active"] else "passive",
        "found_by": list(row["found_by"] or []), "version": row["version"], "current": row["version"] == t["version"],
        "waiting_again": waiting_again or bool(row.get("reasked") and row.get("status") in ("open", "leased")),
        "guide": row.get("guide"), "answered_at": _iso(row["answered_at"]), "shown": True,
        "join_edge": cal.get("join_edge"), "calibrated": cal["labels"] >= tracks.RANK_MIN_LABELS}
    if place == "discover" and me:
        key = tracks.discover_order(cal)   # the lane's own order
        mine = key(me)
        ahead = [it for it in items if it["place"] == "discover" and it is not me and key(it) < mine]
        of = sum(1 for it in items if it["place"] == "discover")
        out.update(position=len(ahead) + 1, of=of, shown=len(ahead) < tracks.DISCOVER_ITEMS, cut=tracks.DISCOVER_ITEMS)
    elif place in ("track", "joined"):
        out["section_items"] = tracks.SECTION_ITEMS
    return out


def find_post(cur: Any, ref: str) -> Optional[str]:
    """The post a reference names: its id, INSIGHT's own /posts/<id> address, or its address as stored (as written
    or normalized). None when none."""
    import re
    from insight_core.utils.url_normalization import normalize_url
    ref = (ref or "").strip()
    m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", ref, re.I)
    if m and (ref == m.group(1) or "/posts/" in ref):
        cur.execute("SELECT id::text FROM posts WHERE id = %s", (m.group(1),))
        row = cur.fetchone()
        if row:
            return row[0]
    if not ref:
        return None
    cur.execute(f"""SELECT id::text FROM posts WHERE url = %s OR normalized_url = %s
                    ORDER BY {pairing.ordinary_date('')} DESC LIMIT 1""", (ref, normalize_url(ref)))
    row = cur.fetchone()
    return row[0] if row else None


def why(cur: Any, folder_id: Any, post_id: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Where `post_id` stands in the track `folder_id` and why (see the module). KeyError: no such folder or post."""
    now = now or datetime.now(timezone.utc)
    folder, pid = str(folder_id), str(post_id)
    cur.execute("SELECT name FROM folders WHERE id = %s", (folder,))
    if cur.fetchone() is None:
        raise KeyError(folder_id)
    post = _post(cur, pid, folder)
    if post is None:
        raise KeyError(post_id)
    base = {"track": folder, "post": pid, "origin": "active" if post["active"] else "passive"}
    t = tracks.get(cur, folder)
    if not tracks.is_topic(t):
        return {**base, "state": "not_asked", "reason": "not_a_topic"}
    label = (tracks.labels(cur, folder).get(pid) or (None,))[0]
    rows = _rows(cur, folder, pid)
    answered = next((r for r in rows if r["verdict"] is not None), None)
    open_now = any(r["verdict"] is None and r["version"] == t["version"] for r in rows)
    if answered is not None:
        return {**base, **_judged(cur, t, post, answered, label, open_now and answered["version"] != t["version"])}
    if label is not None:
        return {**base, "state": "in" if label == "in" else "out", "label": label, "reason": "labelled"}
    if rows:
        if rows[0]["status"] == "failed":   # no verdict stored, never "out"
            return {**base, "state": "invalid", "version": rows[0]["version"], "error": rows[0]["error"]}
        return {**base, "state": "waiting", "version": rows[0]["version"]}
    out = {**base, "state": "not_asked", "at": _iso(post["at"])}
    if post["active"]:
        days = tasks.reading_window(cur)
        if days is not None and post["at"] is not None and post["at"] < now - timedelta(days=days):
            return {**out, "reason": "outside_window", "days": days}
        return {**out, "reason": "not_planned"}
    from insight_core.markx import finders
    tie = finders.tie(cur, t, now=now)   # the ALWAYS finders ask it whatever its vector and probe score
    always = (["source"] if post["source_id"] in tie["tied"] else []) + \
        (["linked"] if finders.linked_by(cur, pid, tie["linkers"]) >= finders.LINK_MIN else []) + \
        (["saved"] if finders.saved_by_owner(cur, pid) else [])
    if always:
        return {**out, "reason": "not_planned", "found_by": always}
    if not post["embedded"]:
        return {**out, "reason": "not_embedded"}
    last = (t.get("stats") or {}).get("last") or {}
    if not last:
        return {**out, "reason": "no_profile"}
    at = post["at"]
    if at is not None and at < t["version_at"] and t.get("history_done_at") is None and \
            (t.get("history_at") is None or (at, pid) < (t["history_at"], t["history_id"] or "")):
        # the history pass reads newest first from the description's start: a post before its cursor is still ahead
        return {**out, "reason": "history_pending"}
    return {**out, "reason": "below_bar", "bar": last.get("threshold")}
