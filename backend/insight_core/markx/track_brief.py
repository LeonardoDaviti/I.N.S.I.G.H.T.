"""A track's brief (issue 0245, the general track briefer; built: 0249, Stealth v10.27): the weekly issue, the quick
look and the tables, read from the things markx/track_things.py keeps.

**"What changed"** is 0207's `digest` kind deepened, not a second summariser: its second guide digest-v2 (`plan`, the
digest planner's part) is asked over a period's rows, numbered [1]..[n] (the things and practices with a report from
a post of the period, each "new" when first reported in it); 2-4 points about the things and practices only, never
authors or sources, each citing the rows it rests on (validate: only the question's rows, and every figure a point
gives is one of its rows'). A week's question is asked again only when its rows change (the same rows are the same
question: repo.add_task's one task), the week in progress at most every BRIEF_EVERY. Code writes the rest: the
sections (one a kind, in the schema's order, the practices last), their counts and headers, and the posts of the
period that gave no row ("also in the track").

**The weekly issue** (`issue`): a Monday-Sunday week (UTC), its things and points as of the week's end, kept as a page
per track and week (kept_pages, page PAGE, key "<track>:<monday>"), built in the jobs process (`keep_issues`, the
"tracks" job) for the closed weeks, ISSUE_WEEKS at most back; never deleted. A closed issue built again whose things
or points differ from the kept one says `updated` (keep everything: the reader sees a correction, not a silent edit).

**The quick look** (`quick_look`): the things found since the track's seen state (0207's mx_track_seen look, or a
given time; never looked: the week in progress), by kind with counts; the newest brief's points that cite one of them
(`as_of` its time, `stale` when a thing came after it); the posts joined since that gave no row. Read live (it depends
on the look): a few indexed reads.

**The tables** (`table`): every current thing of one kind, newest first, filtered by its own fields' values: number
and money `<field>.min` / `<field>.max` (and money `<field>.currency`), enum `<field>=a,b`, text `<field>=words`
(contained, folded), link `<field>=any`.

Behind entity_bands.json `tracks.briefs` (track_things.on): off, nothing is planned or kept and every read is empty.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from insight_core.markx import track_things as TT

DIGEST_KIND, BRIEF_GUIDE = "digest", "digest-v2"
BRIEF_MIN = 2                 # a period with fewer rows has no "what changed"
BRIEF_ROWS = 60               # rows a brief question shows at most (new ones first)
BRIEF_EVERY = timedelta(hours=12)
ISSUE_WEEKS = 12              # closed weeks the jobs process keeps issues for, back from this one
PAGE = "track_brief"
KEPT_LAG = timedelta(minutes=15)
LINE_CHARS = 160
PRACTICE_HEADER = "Practices and claims"


# ---- weeks -----------------------------------------------------------------------------------------------------

def monday(t: Any) -> date:
    d = t.astimezone(timezone.utc).date() if isinstance(t, datetime) else t
    return d - timedelta(days=d.weekday())


def bounds(week: date) -> Tuple[datetime, datetime]:
    start = datetime.combine(week, time.min, tzinfo=timezone.utc)
    return start, start + timedelta(days=7)


def parse_week(s: str) -> date:
    """A week as the API names it (any day of it, YYYY-MM-DD): its Monday. ValueError: not a date."""
    return monday(date.fromisoformat(s.strip()))


# ---- rows --------------------------------------------------------------------------------------------------------

def _order(kinds: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
    order = {k: i for i, k in enumerate(kinds) if k != TT.PRACTICE_KIND}
    order[TT.PRACTICE_KIND] = len(order)
    return order


def rows_between(cur: Any, track_id: str, start: Optional[datetime], end: Optional[datetime]
                 ) -> Tuple[List[Dict[str, Any]], Dict[str, List[Dict[str, Any]]]]:
    """(the current things with a report from a post dated in [start, end), each with `new` (its first report's post
    in the period) — kinds in schema order, new first, newest post first — and every thing's reports)."""
    kinds = TT._kinds(cur, track_id)
    things = [t for t in TT.current(cur, track_id) if t["kind"] in kinds]
    rs = TT.reports(cur, track_id, [t["id"] for t in things])

    def inside(at: Optional[datetime]) -> bool:
        return at is not None and (start is None or at >= start) and (end is None or at < end)
    out = []
    for t in things:
        if any(inside(r["at"]) for r in rs.get(t["id"], [])):
            out.append(dict(t, new=inside(t["first_at"])))
    order = _order(kinds)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    out.sort(key=lambda t: (order.get(t["kind"], 99), not t["new"], -(t["last_at"] or epoch).timestamp(), t["id"]))
    return out, rs


def row_line(kind: Dict[str, Any], t: Dict[str, Any], n_posts: int) -> str:
    """A row as a brief question shows it: its kind, new or not, its posts, then each filled field."""
    got = t["fields"] or {}
    vals = " · ".join(f"{f['name']}: {TT.shown_value(f, got[f['name']]['value'])}" for f in kind["fields"]
                      if f["name"] in got)
    tag = ", ".join(x for x in ("new" if t.get("new") else "", f"{n_posts} posts" if n_posts > 1 else "") if x)
    return f"{t['kind']}" + (f" ({tag})" if tag else "") + f": {vals}"


def brief_input(track: Dict[str, Any], kinds: Dict[str, Dict[str, Any]], period: str, rows: Sequence[Dict[str, Any]],
                rs: Dict[str, List[Dict[str, Any]]]) -> Tuple[str, List[str]]:
    """A digest-v2 question: the track, the period, the kinds, the rows [1]..[n] (new ones first, BRIEF_ROWS at most):
    (the question, the thing ids in its order)."""
    shown = sorted(rows, key=lambda t: not t["new"])[:BRIEF_ROWS]
    lines = TT.header(track)[:2] + [f"PERIOD: {period}", "", "KINDS:"]
    lines += [f"- {k}: {d.get('about') or ''}" for k, d in kinds.items()]
    lines += ["", "ROWS:"]
    for n, t in enumerate(shown, 1):
        lines.append(f"[{n}] " + row_line(kinds[t["kind"]], t, len({r["post"] for r in rs.get(t["id"], [])})))
    return "\n".join(lines), [t["id"] for t in shown]


def _period(week: date) -> str:
    return f"the week of {week.isoformat()} to {(week + timedelta(days=6)).isoformat()}"


def _weeks(cur: Any, track_id: str, now: datetime) -> List[date]:
    """The weeks from the track's first thing's to this one, ISSUE_WEEKS + 1 at most (oldest first)."""
    cur.execute("SELECT min(first_at) FROM mx_track_things WHERE track_id = %s AND status = 'current'", (track_id,))
    first = cur.fetchone()[0]
    if first is None:
        return []
    this = monday(now)
    w = max(monday(first), this - timedelta(weeks=ISSUE_WEEKS))
    out = []
    while w <= this:
        out.append(w)
        w += timedelta(weeks=1)
    return out


def plan(cur: Any, *, now: Optional[datetime] = None, **_kw: Any) -> int:
    """The digest planner's part (tasks.PLANNERS["digest"]): a digest-v2 question for each week of each topic track
    with BRIEF_MIN+ rows whose rows differ from its last question's (the week in progress at most every BRIEF_EVERY;
    none while one is waiting): how many were added."""
    from insight_core.markx import repo, schemas, tracks
    if not TT.on():
        return 0
    now = now or datetime.now(timezone.utc)
    schemas.ensure_guides(cur)
    added = 0
    for t in tracks.described(cur):
        tid = t["folder_id"]
        if TT.current_schema(cur, tid) is None:
            continue
        kinds = TT._kinds(cur, tid)
        cur.execute("""SELECT DISTINCT ON (a.week) a.week, a.thing_ids::text[], a.created_at, k.status
                         FROM mx_track_brief_asks a JOIN mx_tasks k ON k.id = a.task_id
                        WHERE a.track_id = %s ORDER BY a.week, a.created_at DESC""", (tid,))
        last = {w: (ids, at, st) for w, ids, at, st in cur.fetchall()}
        this = monday(now)
        for w in _weeks(cur, tid, now):
            was = last.get(w)
            if was is not None and (was[2] in ("open", "leased") or (w == this and now - was[1] < BRIEF_EVERY)):
                continue
            rows, rs = rows_between(cur, tid, *bounds(w))
            if len(rows) < BRIEF_MIN:
                continue
            text, ids = brief_input(t, kinds, _period(w), rows, rs)   # the same rows: the same task (one ask)
            task_id, new = repo.add_task(cur, kind=DIGEST_KIND, guide=BRIEF_GUIDE, subject_kind="track", input=text,
                                         a=tid)
            cur.execute("""INSERT INTO mx_track_brief_asks (task_id, track_id, week, thing_ids)
                           VALUES (%s, %s, %s, %s::uuid[]) ON CONFLICT DO NOTHING""", (task_id, tid, w, ids))
            added += new
    return added


def points(cur: Any, track_id: str, week: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """The newest valid brief of the week (None: of any week): {points: [{text, cites: [thing ids]}], at, week}, each
    cite its thing's current root; a point left with no cite is not shown."""
    cur.execute("""SELECT a.thing_ids::text[], c.answer, c.created_at, a.week
                     FROM mx_track_brief_asks a JOIN mx_calls c ON c.task_id = a.task_id AND c.valid
                    WHERE a.track_id = %s AND (%s::date IS NULL OR a.week = %s::date)
                    ORDER BY c.created_at DESC LIMIT 1""", (track_id, week, week))
    r = cur.fetchone()
    if r is None:
        return None
    ids, answer, at, w = r
    root = TT.roots(cur, track_id)
    cur.execute("SELECT id::text FROM mx_track_things WHERE track_id = %s AND status = 'current'", (track_id,))
    live = {i for (i,) in cur.fetchall()}
    out = []
    for p in (answer or {}).get("points") or []:
        cites = [root.get(ids[n - 1], ids[n - 1]) for n in p.get("cites") or [] if isinstance(n, int) and 1 <= n <= len(ids)]
        cites = [c for c in dict.fromkeys(cites) if c in live]
        if p.get("text") and cites:
            out.append({"text": p["text"], "cites": cites})
    return {"points": out, "at": at, "week": w} if out else None


# ---- shapes ----------------------------------------------------------------------------------------------------

def _posts(cur: Any, track_id: str, ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """{post: {id, title, url, at, why}} (the why: the track judge's newest line)."""
    from insight_core.markx import tracks
    if not ids:
        return {}
    cur.execute(f"""SELECT p.id::text, p.title, p.url, {tracks._date()},
                           (SELECT i.why FROM mx_track_items i WHERE i.track_id = %s AND i.post_id = p.id
                             AND i.verdict IS NOT NULL ORDER BY i.version DESC LIMIT 1)
                      FROM posts p WHERE p.id = ANY(%s::uuid[])""", (track_id, list(ids)))
    return {i: {"id": i, "title": (" ".join((ti or "").split()))[:LINE_CHARS] or None, "url": u,
                "at": _iso(at), "why": why} for i, ti, u, at, why in cur.fetchall()}


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def thing_view(kind: Dict[str, Any], t: Dict[str, Any], rs: Sequence[Dict[str, Any]],
               posts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """A row: its fields in the schema's order (each value typed, in words, with its quote and the post it came
    from), every post that reported it (newest first), its dates."""
    fields = {}
    for f in kind["fields"]:
        v = (t["fields"] or {}).get(f["name"])
        if v is not None:
            fields[f["name"]] = {"value": v["value"], "shown": TT.shown_value(f, v["value"]), "quote": v.get("quote"),
                                 "post": v.get("post")}
    seen = list(dict.fromkeys(r["post"] for r in reversed(list(rs))))
    return {"id": t["id"], "kind": t["kind"], "fields": fields, "posts": [posts[p] for p in seen if p in posts],
            "first_at": _iso(t["first_at"]), "last_at": _iso(t["last_at"]), "found_at": _iso(t["found_at"]),
            **({"new": t["new"]} if "new" in t else {})}


def _sections(kinds: Dict[str, Dict[str, Any]], rows: Sequence[Dict[str, Any]], rs: Dict[str, List[Dict[str, Any]]],
              posts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One section a kind that has rows (schema order, the practices last): its header and count written by code."""
    out = []
    for k in sorted(kinds, key=lambda k: _order(kinds).get(k, 99)):
        its = [t for t in rows if t["kind"] == k]
        if not its:
            continue
        d = kinds[k]
        header = PRACTICE_HEADER if k == TT.PRACTICE_KIND else k.replace("_", " ").capitalize()
        out.append({"kind": k, "header": f"{header} ({len(its)})", "about": d.get("about") or "", "count": len(its),
                    "new": sum(1 for t in its if t.get("new")),
                    "fields": [{"name": f["name"], "type": f["type"], **({"unit": f["unit"]} if f.get("unit") else {}),
                                **({"values": f["values"]} if f.get("values") else {})} for f in d["fields"]],
                    "things": [thing_view(d, t, rs.get(t["id"], []), posts) for t in its]})
    return out


def _also(cur: Any, track: Dict[str, Any], start: Optional[datetime], end: Optional[datetime], *,
          joined: bool = False) -> List[str]:
    """The posts in the track dated (`joined`: joined) in [start, end) that gave no row (no report of any thing)."""
    from insight_core.markx import track_subtopics
    items = track_subtopics.in_track(cur, track)

    def when(it: Dict[str, Any]) -> Optional[datetime]:
        return track_subtopics.joined_at(it) if joined else it.get("at")
    ids = [it["post_id"] for it in items if when(it) is not None and (start is None or when(it) >= start)
           and (end is None or when(it) < end)]
    if not ids:
        return []
    cur.execute("""SELECT DISTINCT r.post_id::text FROM mx_track_thing_reports r JOIN mx_track_things t ON t.id = r.thing_id
                    WHERE t.track_id = %s AND r.post_id = ANY(%s::uuid[])""", (track["folder_id"], ids))
    gave = {p for (p,) in cur.fetchall()}
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    at = {it["post_id"]: when(it) or epoch for it in items}
    return sorted((p for p in ids if p not in gave), key=lambda p: (at[p], p), reverse=True)


def _point_views(got: Optional[Dict[str, Any]], shown: Sequence[str]) -> List[Dict[str, Any]]:
    """The points, each cite as its row (its thing id and its number among the rows shown, for the superscripts)."""
    if not got:
        return []
    n = {t: i for i, t in enumerate(shown, 1)}
    return [{"text": p["text"], "cites": [{"thing": c, "n": n.get(c)} for c in p["cites"]]} for p in got["points"]]


def _track(cur: Any, folder_id: Any) -> Dict[str, Any]:
    from insight_core.markx import tracks
    t = tracks.get(cur, folder_id)
    if not tracks.is_topic(t):
        raise KeyError(folder_id)
    return t


# ---- the weekly issue ----------------------------------------------------------------------------------------

def _key(track_id: str, week: date) -> str:
    return f"{track_id}:{week.isoformat()}"


def issue(cur: Any, folder_id: Any, week: date, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The week's issue: {on, track, week {start, end, closed}, points, points_at, sections, also, counts, built_at,
    updated}. KeyError: not a topic track."""
    from insight_core.markx import kept_pages
    import json
    now = now or datetime.now(timezone.utc)
    t = _track(cur, folder_id)
    tid = t["folder_id"]
    start, end = bounds(week)
    base = {"on": TT.on(), "track": {"id": tid, "name": t["name"]},
            "week": {"start": week.isoformat(), "end": (week + timedelta(days=6)).isoformat(), "closed": now >= end}}
    if not TT.on():
        return {**base, "points": [], "points_at": None, "sections": [], "also": [],
                "counts": {"things": 0, "new": 0, "posts": 0, "also": 0}, "built_at": now.isoformat(), "updated": False}
    kinds = TT._kinds(cur, tid)
    rows, rs = rows_between(cur, tid, start, end)
    also = _also(cur, t, start, end)
    posts = _posts(cur, tid, sorted({r["post"] for x in rows for r in rs.get(x["id"], [])} | set(also)))
    sections = _sections(kinds, rows, rs, posts)
    got = points(cur, tid, week)
    shown = [x["id"] for s in sections for x in s["things"]]
    body = {**base, "points": _point_views(got, shown), "points_at": _iso(got["at"]) if got else None,
            "sections": sections, "also": [posts[p] for p in also if p in posts],
            "counts": {"things": len(rows), "new": sum(1 for x in rows if x["new"]),
                       "posts": len({r["post"] for x in rows for r in rs.get(x["id"], []) if r["at"] and start <= r["at"] < end}),
                       "also": len(also)},
            "built_at": now.isoformat(), "updated": False}
    old = kept_pages.newest(cur, PAGE, _key(tid, week))
    if old is not None:   # keep everything: a closed issue built again with other things or points says so
        prev = json.loads(old[0])
        if prev.get("week", {}).get("closed") and (prev.get("sections") != json.loads(kept_pages.encode(sections))
                                                   or prev.get("points") != json.loads(kept_pages.encode(body["points"]))):
            body["updated"] = True
        elif prev.get("updated"):
            body["updated"] = True
        body["first_built_at"] = prev.get("first_built_at") or prev.get("built_at")
    return body


def inputs(cur: Any, folder_id: Any, week: date, *, now: Optional[datetime] = None, loose: Optional[str] = None) -> Any:
    """What a week's issue reads (kept_pages' stamp): the track, its schema, whether the week is closed, the week's
    reports and the things they report (their state), the merges, the week's brief answers; the loose part: the
    track's placements (its "also" posts: tracks.page_inputs' loose part, or `loose` when read already)."""
    from insight_core.markx import kept_pages, tracks
    now = now or datetime.now(timezone.utc)
    tid = str(folder_id)
    start, end = bounds(week)
    cur.execute(f"""SELECT (SELECT json_build_array(f.name, t.description, t.version) FROM mx_tracks t
                              JOIN folders f ON f.id = t.folder_id WHERE t.folder_id = %(t)s::uuid),
                           (SELECT max(version) FROM mx_track_schemas WHERE track_id = %(t)s::uuid),
                           (SELECT json_build_array(count(*), max(r.created_at),
                                                    md5(string_agg(concat_ws(':', x.id, x.status, x.updated_at), ','
                                                                   ORDER BY x.id)))
                              FROM mx_track_thing_reports r JOIN mx_track_things x ON x.id = r.thing_id
                              JOIN posts p ON p.id = r.post_id
                             WHERE x.track_id = %(t)s::uuid AND {tracks._date()} >= %(s)s AND {tracks._date()} < %(e)s),
                           (SELECT md5(string_agg(concat_ws(':', id, status, merged_into, updated_at), ',' ORDER BY id))
                              FROM mx_track_things WHERE track_id = %(t)s::uuid AND status = 'merged'),
                           (SELECT json_build_array(count(*), max(c.created_at)) FROM mx_track_brief_asks a
                              JOIN mx_calls c ON c.task_id = a.task_id
                             WHERE a.track_id = %(t)s::uuid AND a.week = %(w)s)""",
                {"t": tid, "s": start, "e": end, "w": week})
    strict = [tid, week.isoformat(), TT.on(), now >= end, *cur.fetchone()]
    return kept_pages.Inputs(strict, tracks.page_inputs(cur, tid)[1] if loose is None else loose)


def kept_issue(cur: Any, folder_id: Any, week: date, *, now: Optional[datetime] = None) -> bytes:
    """GET .../brief?week=: the kept issue's bytes, else built (`issue`) and kept. KeyError: not a topic track."""
    from insight_core.markx import kept_pages
    now = now or datetime.now(timezone.utc)
    t = _track(cur, folder_id)
    return kept_pages.kept_or_build(cur, PAGE, _key(t["folder_id"], week),
                                    lambda: inputs(cur, t["folder_id"], week, now=now),
                                    lambda: issue(cur, t["folder_id"], week, now=now), until=now + KEPT_LAG, now=now)


def due(cur: Any, now: datetime) -> List[Tuple[str, date, str, Any]]:
    """The closed weeks (ISSUE_WEEKS back) of each topic track whose issue is not kept for its inputs: [(track,
    week, stamp, loose)]; none while off."""
    from insight_core.markx import kept_pages, tracks
    out: List[Tuple[str, date, str, Any]] = []
    if not TT.on():
        return out
    for t in tracks.described(cur):
        tid = t["folder_id"]
        weeks = [w for w in _weeks(cur, tid, now) if bounds(w)[1] <= now]
        if not weeks:
            continue
        loose = tracks.page_inputs(cur, tid)[1]
        for w in weeks:
            got = inputs(cur, tid, w, now=now, loose=loose)
            st = kept_pages.stamp(PAGE, _key(tid, w), got.strict)
            if not kept_pages.has(cur, PAGE, _key(tid, w), kept_pages.NO_RUN, st, loose=got.loose):
                out.append((tid, w, st, got.loose))
    return out


def missing(cur: Any, now: Optional[datetime] = None) -> bool:
    """The jobs process's look (its "tracks" view): an issue of a closed week is not kept for its inputs."""
    return bool(due(cur, now or datetime.now(timezone.utc)))


def keep_issues(cur: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """In the jobs process (jobs.Jobs.tracks): each `due` issue built and kept (a closed week's issue has no
    `until`: frozen until its inputs change; then built again, `updated` when its things or points differ).
    {built: [keys]}"""
    from insight_core.markx import kept_pages
    now = now or datetime.now(timezone.utc)
    out: Dict[str, Any] = {"built": []}
    for tid, w, st, loose in due(cur, now):
        kept_pages.put(cur, PAGE, _key(tid, w), kept_pages.NO_RUN, st, kept_pages.encode(issue(cur, tid, w, now=now)),
                       loose=loose)
        out["built"].append(_key(tid, w))
    return out


def issues(cur: Any, folder_id: Any, *, now: Optional[datetime] = None) -> List[str]:
    """The weeks a track has an issue for (Mondays, newest first): the issue strip."""
    now = now or datetime.now(timezone.utc)
    t = _track(cur, folder_id)
    return [w.isoformat() for w in reversed(_weeks(cur, t["folder_id"], now))] if TT.on() else []


# ---- the quick look --------------------------------------------------------------------------------------------

def quick_look(cur: Any, folder_id: Any, since: Optional[datetime] = None, *, now: Optional[datetime] = None
               ) -> Dict[str, Any]:
    """What is new since `since` (None: the week in progress): {on, track, since, sections (new things by kind),
    points (the newest brief's that cite a new thing; as_of, stale), also (posts joined since with no row), counts,
    nothing_new, last_issue, weeks (the issue strip: its Mondays, newest first)}. KeyError: not a topic track."""
    now = now or datetime.now(timezone.utc)
    t = _track(cur, folder_id)
    tid = t["folder_id"]
    since = since or bounds(monday(now))[0]
    base = {"on": TT.on(), "track": {"id": tid, "name": t["name"]}, "since": since.isoformat()}
    weeks = issues(cur, tid, now=now)
    closed = [w for w in weeks if bounds(date.fromisoformat(w))[1] <= now]
    if not TT.on():
        return {**base, "sections": [], "points": [], "as_of": None, "stale": False, "also": [],
                "counts": {"things": 0, "also": 0}, "nothing_new": True, "last_issue": None, "weeks": []}
    kinds = TT._kinds(cur, tid)
    rows = [dict(x, new=True) for x in TT.current(cur, tid) if x["found_at"] > since and x["kind"] in kinds]
    rs = TT.reports(cur, tid, [x["id"] for x in rows])
    also = _also(cur, t, since, None, joined=True)
    posts = _posts(cur, tid, sorted({r["post"] for x in rows for r in rs.get(x["id"], [])} | set(also)))
    order = _order(kinds)
    rows.sort(key=lambda x: (order.get(x["kind"], 99), -x["found_at"].timestamp(), x["id"]))
    sections = _sections(kinds, rows, rs, posts)
    got = points(cur, tid)
    new_ids = {x["id"] for x in rows}
    if got:
        got = dict(got, points=[p for p in got["points"] if set(p["cites"]) & new_ids])
    shown = [x["id"] for s in sections for x in s["things"]]
    pts = _point_views(got, shown) if got and got["points"] else []
    return {**base, "sections": sections, "points": pts, "as_of": _iso(got["at"]) if pts else None,
            "stale": bool(pts) and any(x["found_at"] > got["at"] for x in rows),
            "also": [posts[p] for p in also if p in posts], "counts": {"things": len(rows), "also": len(also)},
            "nothing_new": not rows and not also, "last_issue": closed[0] if closed else None, "weeks": weeks}


RAIL_QUIET = timedelta(days=30)   # a track not opened for this long shows no count in the rail (0245's UX)


def new_count(cur: Any, folder_id: Any, *, now: Optional[datetime] = None) -> int:
    """The rail's count (0245): the track's current things found since the reader's last look at it; 0 when it was
    never opened, or not for RAIL_QUIET, or the briefer is off. One indexed count."""
    from insight_core.markx import track_subtopics
    if not TT.on():
        return 0
    now = now or datetime.now(timezone.utc)
    look = track_subtopics.seen(cur, folder_id)["track"]
    if not look:
        return 0
    at = datetime.fromisoformat(look)
    if now - at > RAIL_QUIET:
        return 0
    kinds = list(TT._kinds(cur, str(folder_id)))
    cur.execute("""SELECT count(*) FROM mx_track_things WHERE track_id = %s AND status = 'current' AND created_at > %s
                      AND kind = ANY(%s)""", (str(folder_id), at, kinds))
    return int(cur.fetchone()[0])


# ---- the tables ------------------------------------------------------------------------------------------------

def _match(f: Dict[str, Any], v: Any, op: str, want: str) -> bool:
    t = f.get("type")
    if t in ("number", "money"):
        if not isinstance(v, dict) or "number" not in v:
            return False
        if op == "currency":
            return str(v.get("currency") or "").upper() == want.strip().upper()
        x = float(want)
        lo, hi = float(v["number"]), float(v.get("range_to") if v.get("range_to") is not None else v["number"])
        return lo >= x if op == "min" else hi <= x if op == "max" else lo <= x <= hi
    if t == "enum":
        return TT.fold(v) in {TT.fold(w) for w in want.split(",") if w.strip()}
    if t == "link":
        return bool(v)
    return TT.fold(want) in TT.fold(v)


def table(cur: Any, folder_id: Any, kind: str, filters: Dict[str, str], *, limit: int = 100, offset: int = 0
          ) -> Dict[str, Any]:
    """GET .../things?kind=&filters: every current thing of `kind`, newest first, filtered by its fields (see the
    module). ValueError: an unknown kind, field or operator, or a bad number; KeyError: not a topic track."""
    t = _track(cur, folder_id)
    tid = t["folder_id"]
    kinds = TT._kinds(cur, tid) if TT.on() else {}
    if not TT.on():
        return {"on": False, "track": {"id": tid, "name": t["name"]}, "kind": kind, "kinds": [], "fields": [],
                "filters": {}, "count": 0, "things": []}
    if kind not in kinds:
        raise ValueError(f"kind: one of {', '.join(kinds)}")
    d = kinds[kind]
    defs = {f["name"]: f for f in d["fields"]}
    tests = []
    for raw, want in filters.items():
        name, _, op = raw.partition(".")
        f = defs.get(name)
        if f is None:
            raise ValueError(f"no field {name!r} in {kind}")
        allowed = {"number": ("min", "max", "eq"), "money": ("min", "max", "eq", "currency")}.get(f["type"], ("",))
        if op not in allowed:
            raise ValueError(f"{raw}: {f['type']} filters are {', '.join(name + ('.' + a if a else '') for a in allowed)}")
        if f["type"] in ("number", "money") and op != "currency":
            try:
                float(want)
            except ValueError:
                raise ValueError(f"{raw}: not a number") from None
        tests.append((f, op or "eq", want))
    def passes(x: Dict[str, Any]) -> bool:
        for f, op, want in tests:
            got = (x["fields"] or {}).get(f["name"])
            if got is None or not _match(f, got["value"], op, want):
                return False
        return True
    kept = [x for x in TT.current(cur, tid, kind) if passes(x)]
    page = kept[offset:offset + limit]
    rs = TT.reports(cur, tid, [x["id"] for x in page])
    posts = _posts(cur, tid, sorted({r["post"] for x in page for r in rs.get(x["id"], [])}))
    return {"on": True, "track": {"id": tid, "name": t["name"]}, "kind": kind, "kinds": list(kinds),
            "about": d.get("about") or "", "fields": [{k: f[k] for k in ("name", "type", "unit", "values") if f.get(k)}
                                                     for f in d["fields"]],
            "filters": filters, "count": len(kept), "things": [thing_view(d, x, rs.get(x["id"], []), posts) for x in page]}
