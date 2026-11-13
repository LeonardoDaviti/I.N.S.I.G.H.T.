"""Why a post is, or is not, in a track (issue 0185 3). Read only, over stored rows: no model call, no task, no
vector computed. The track page shows only its top items; this says where any one post stands and why.

`why(cur, track, post)` -> {state, ...}:

  - **judged** (a verdict stored, the newest version's, as the page reads it: tracks.placed):
      `in`       in the track (an owner ✓, or Haiku's in from an active source); `shown` False when its section
                 shows only its newest tracks.SECTION_ITEMS;
      `joined`   Haiku's in from a passive source, at or above the join band (shown in the track, marked);
      `discover` Haiku's in from a passive source below the join band: in Discover at `position` of `of`, cut off
                 the page after tracks.DISCOVER_ITEMS (`shown`);
      `out`      Haiku's out (its why and confidence), or the owner's ✗;
    each with Haiku's `why`, `confidence`, `subtopic`, `origin`, `found_by`, the description `version` it was asked
    under (`current` False: an older description's verdict; `waiting_again` when the current one is asked and open).
  - `waiting`: asked, Haiku has not answered yet.
  - `not_asked`, with `reason`:
      `not_a_topic`      the track has no description: nothing is judged;
      `labelled`         the owner's label places it, nothing is asked;
      `outside_window`   its source is in the track, but the post is older than the reading window (`days`);
      `not_planned`      its source is in the track and the post in the window: the next plan asks it;
      `not_embedded`     a passive source's post with no vector yet: no finder can read it;
      `no_profile`       the track's finders are not ready (no example posts embedded yet);
      `history_pending`  older than the description, and the history pass has not reached it yet;
      `below_bar`        a passive source's post the finders did not put up (the last plan's bar, `bar`).
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
    cur.execute("""SELECT version, verdict, confidence, subtopic, why, origin, found_by, answered_at
                     FROM mx_track_items WHERE track_id = %s AND post_id = %s ORDER BY version DESC""", (folder, post_id))
    cols = ("version", "verdict", "confidence", "subtopic", "why", "origin", "found_by", "answered_at")
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
        "waiting_again": waiting_again, "answered_at": _iso(row["answered_at"]), "shown": True,
        "join_edge": cal.get("join_edge"), "calibrated": cal["labels"] >= tracks.RANK_MIN_LABELS}
    if place == "discover" and me:
        ahead = [it for it in items if it["place"] == "discover" and it is not me
                 and (it["rank"], it["confidence"] or 0) > (me["rank"], me["confidence"] or 0)]
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
        return {**base, "state": "waiting", "version": rows[0]["version"]}
    out = {**base, "state": "not_asked", "at": _iso(post["at"])}
    if post["active"]:
        days = tasks.reading_window(cur)
        if days is not None and post["at"] is not None and post["at"] < now - timedelta(days=days):
            return {**out, "reason": "outside_window", "days": days}
        return {**out, "reason": "not_planned"}
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
