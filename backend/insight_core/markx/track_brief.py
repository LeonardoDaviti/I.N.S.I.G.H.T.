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

from insight_core.db.repo_post_parts import shown_title
from insight_core.markx import track_things as TT

DIGEST_KIND, BRIEF_GUIDE = "digest", "digest-v3"   # v10.29: v2 asked again under v3
BRIEF_MIN = 2                 # a period with fewer rows has no "what changed"
BRIEF_ROWS = 60               # rows a brief question shows at most (new ones first)
BRIEF_EVERY = timedelta(hours=12)
ISSUE_WEEKS = 12              # closed weeks the jobs process keeps issues for, back from this one
PAGE = "track_brief"
KEPT_LAG = timedelta(minutes=15)
LINE_CHARS = 160
PRACTICE_HEADER = "Practices and claims"
QUIET_ROWS = 5        # a section with this many rows or more hides its quiet columns (v10.29)
QUIET_FILLED = 0.2    # a column filled in fewer rows than this share is quiet
QUIET_SAME = 0.6      # a choice column whose one value fills more rows than this share is quiet (most rows alike)
EMPTY_CHOICES = ("other", "unknown", "none", "n/a")


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
    from insight_core.markx import schemas, tracks
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
            if was is not None and was[2] in ("open", "leased"):
                continue
            rows, rs = rows_between(cur, tid, *bounds(w))
            # the week in progress at most every BRIEF_EVERY, unless most rows its brief cites left it (0269)
            if was is not None and w == this and now - was[1] < BRIEF_EVERY and not _cites_left(cur, tid, w, rows):
                continue
            added += _ask(cur, t, kinds, w, _period(w), rows, rs)
    return added


def _ask(cur: Any, t: Dict[str, Any], kinds: Dict[str, Dict[str, Any]], week: date, period: str,
         rows: Sequence[Dict[str, Any]], rs: Dict[str, List[Dict[str, Any]]]) -> int:
    """One digest-v3 question over `rows` (BRIEF_MIN at least), kept with its week and rows: 1 when new."""
    from insight_core.markx import repo
    if len(rows) < BRIEF_MIN:
        return 0
    text, ids = brief_input(t, kinds, period, rows, rs)   # the same rows: the same task (one ask)
    task_id, new = repo.add_task(cur, kind=DIGEST_KIND, guide=BRIEF_GUIDE, subject_kind="track", input=text,
                                 a=t["folder_id"])
    cur.execute("""INSERT INTO mx_track_brief_asks (task_id, track_id, week, thing_ids)
                   VALUES (%s, %s, %s, %s::uuid[]) ON CONFLICT DO NOTHING""", (task_id, t["folder_id"], week, ids))
    return new


def plan_subject(cur: Any, t: Dict[str, Any], *, now: datetime, period: str) -> int:
    """0261: one "what changed" over every row of a subject that is not a week's (an entity: entity_brief), asked
    again when its rows change, at most every BRIEF_EVERY, none while one waits (the asks keyed by this week)."""
    from insight_core.markx import schemas
    schemas.ensure_guides(cur)
    cur.execute("""SELECT a.created_at, k.status FROM mx_track_brief_asks a JOIN mx_tasks k ON k.id = a.task_id
                    WHERE a.track_id = %s ORDER BY a.created_at DESC LIMIT 1""", (t["folder_id"],))
    was = cur.fetchone()
    if was is not None and (was[1] in ("open", "leased") or now - was[0] < BRIEF_EVERY):
        return 0
    return _ask(cur, t, TT._kinds(cur, t["folder_id"]), monday(now), period,
                *rows_between(cur, t["folder_id"], None, None))


def _answered(cur: Any, track_id: str, week: Optional[date]) -> Optional[Tuple[List[Dict[str, Any]], Any, date]]:
    """The newest valid brief of the week (None: of any week): ([{text, cites}], at, week), each cite its thing's
    current root (a cite of a thing dropped since stays, as its id)."""
    cur.execute("""SELECT a.thing_ids::text[], c.answer, c.created_at, a.week
                     FROM mx_track_brief_asks a JOIN mx_calls c ON c.task_id = a.task_id AND c.valid
                    WHERE a.track_id = %s AND (%s::date IS NULL OR a.week = %s::date)
                    ORDER BY c.created_at DESC LIMIT 1""", (track_id, week, week))
    r = cur.fetchone()
    if r is None:
        return None
    ids, answer, at, w = r
    root = TT.roots(cur, track_id)
    out = []
    for p in (answer or {}).get("points") or []:
        cites = [root.get(ids[n - 1], ids[n - 1]) for n in p.get("cites") or [] if isinstance(n, int) and 1 <= n <= len(ids)]
        if p.get("text"):
            out.append({"text": p["text"], "cites": list(dict.fromkeys(cites))})
    return out, at, w


def points(cur: Any, track_id: str, week: Optional[date] = None, *,
           within: Optional[Sequence[str]] = None) -> Optional[Dict[str, Any]]:
    """The newest valid brief of the week (None: of any week): {points: [{text, cites: [thing ids]}], at, week}, each
    cite its thing's current root; a point left with no cite is not shown. 0269 `within` (a week's issue: the rows
    its sections show): a point is shown only when every row it cites is one of them (the week's rows change when
    posts are dated again: a point about rows that left the week is not the week's)."""
    got = _answered(cur, track_id, week)
    if got is None:
        return None
    pts, at, w = got
    cur.execute("SELECT id::text FROM mx_track_things WHERE track_id = %s AND status = 'current'", (track_id,))
    live = {i for (i,) in cur.fetchall()}
    keep = None if within is None else set(within)
    out = []
    for p in pts:
        if keep is not None and not (p["cites"] and set(p["cites"]) <= keep):
            continue
        cites = [c for c in p["cites"] if c in live]
        if cites:
            out.append({"text": p["text"], "cites": cites})
    return {"points": out, "at": at, "week": w} if out else None


def _cites_left(cur: Any, track_id: str, week: date, rows: Sequence[Dict[str, Any]]) -> bool:
    """0269: whether most of the rows the week's newest brief cites are no longer its rows (posts dated again, things
    dropped): its points would be about another week, so it is asked again whatever BRIEF_EVERY says."""
    got = _answered(cur, track_id, week)
    cited = {c for p in (got[0] if got else []) for c in p["cites"]}
    if not cited:
        return False
    now_ids = {t["id"] for t in rows}
    return 2 * len(cited - now_ids) > len(cited)


# ---- shapes ----------------------------------------------------------------------------------------------------

def _posts(cur: Any, track_id: str, ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """{post: {id, title, url, at (its publication), why}} (the why: the track judge's newest line)."""
    if not ids:
        return {}
    cur.execute(f"""SELECT p.id::text, {shown_title()}, p.url, {TT.post_date()}, p.source_id::text,
                           (SELECT i.why FROM mx_track_items i WHERE i.track_id = %s AND i.post_id = p.id
                             AND i.verdict IS NOT NULL ORDER BY i.version DESC LIMIT 1)
                      FROM posts p WHERE p.id = ANY(%s::uuid[])""", (track_id, list(ids)))
    return {i: {"id": i, "title": (" ".join((ti or "").split()))[:LINE_CHARS] or None, "url": u,
                "at": _iso(at), "why": why, "source_id": src} for i, ti, u, at, src, why in cur.fetchall()}


def sources_of(rs: Sequence[Dict[str, Any]], posts: Dict[str, Dict[str, Any]]) -> int:
    """How many independent sources reported a thing (its reports' posts' sources; a post not loaded counts as its
    own): the brief's rank (v10.29, owner 2026-11-21: what several of your sources report comes first)."""
    return len({(posts.get(r["post"]) or {}).get("source_id") or r["post"] for r in rs})


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def _digits(s: str) -> set:
    import re
    return set(re.findall(r"\d+(?:[.,]\d+)?", s or ""))


def _says_nothing(f: Dict[str, Any], v: Any) -> bool:
    """A value that tells the reader nothing: a choice of "other" (or like it)."""
    return f.get("type") == "enum" and TT.fold(v) in EMPTY_CHOICES


def thing_view(kind: Dict[str, Any], t: Dict[str, Any], rs: Sequence[Dict[str, Any]],
               posts: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """A row: its fields in the schema's order (each value typed, in words, with its quote and the post it came
    from; 0257: the post's linked page it was quoted from, `page`), every post that reported it (newest first), its dates. Not shown (kept in the row, v10.29): a choice of
    "other", and a practice's evidence that only repeats its result's figures."""
    fields = {}
    for f in kind["fields"]:
        v = (t["fields"] or {}).get(f["name"])
        if v is not None and not _says_nothing(f, v["value"]):
            fields[f["name"]] = {"value": v["value"], "shown": TT.shown_value(f, v["value"]), "quote": v.get("quote"),
                                 "post": v.get("post"), **({"page": v["page"]} if v.get("page") else {})}
    if t["kind"] == TT.PRACTICE_KIND and "evidence" in fields and "result" in fields:
        ev = _digits(fields["evidence"]["shown"])
        if ev and ev <= _digits(fields["result"]["shown"]):
            del fields["evidence"]
    seen = list(dict.fromkeys(r["post"] for r in reversed(list(rs))))
    return {"id": t["id"], "kind": t["kind"], "fields": fields, "posts": [posts[p] for p in seen if p in posts],
            "sources": sources_of(rs, posts),
            "first_at": _iso(t["first_at"]), "last_at": _iso(t["last_at"]), "found_at": _iso(t["found_at"]),
            **({"new": t["new"]} if "new" in t else {})}


def _quiet(fields: Sequence[Dict[str, Any]], views: Sequence[Dict[str, Any]]) -> set:
    """The columns that tell a section's rows apart too little to show (v10.29, the reader's ease): with QUIET_ROWS+
    rows, a column (never the first: the name) filled in under QUIET_FILLED of them, or a choice whose one value
    fills over QUIET_SAME of them. The values stay in each row and in the tables."""
    from collections import Counter
    n = len(views)
    if n < QUIET_ROWS:
        return set()
    out = set()
    for f in fields[1:]:
        got = [v["fields"][f["name"]]["shown"] for v in views if f["name"] in v["fields"]]
        if len(got) < QUIET_FILLED * n:
            out.add(f["name"])
        elif f.get("type") == "enum" and got and Counter(got).most_common(1)[0][1] > QUIET_SAME * n:
            out.add(f["name"])
    return out


def _fold_practices(rows: Sequence[Dict[str, Any]], rs: Dict[str, List[Dict[str, Any]]]
                    ) -> Tuple[Dict[str, str], set]:
    """(practice -> the thing it is shown inside, the practices not shown) (v10.29). A practice every post of which
    also gave a thing of the track's own kinds is about that thing (a project's feature, a setup's finding): shown
    inside the newest such thing, not in its own list. A practice with only its `what` (no result, no evidence)
    says nothing to try or check: not shown here (kept, and in the tables)."""
    by_post: Dict[str, str] = {}
    for t in rows:                      # rows: newest first within a kind, so the first thing a post gave is kept
        if t["kind"] != TT.PRACTICE_KIND:
            for r in rs.get(t["id"], []):
                by_post.setdefault(r["post"], t["id"])
    host, quiet = {}, set()
    for t in rows:
        if t["kind"] != TT.PRACTICE_KIND:
            continue
        ps = {r["post"] for r in rs.get(t["id"], [])}
        if ps and all(p in by_post for p in ps):
            host[t["id"]] = by_post[sorted(ps, key=lambda p: (p not in by_post, p))[0]]
        elif not ({"result", "evidence"} & set(t["fields"] or {})):
            quiet.add(t["id"])
    return host, quiet


def _sections(kinds: Dict[str, Dict[str, Any]], rows: Sequence[Dict[str, Any]], rs: Dict[str, List[Dict[str, Any]]],
              posts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One section a kind that has rows (schema order, the practices last): its header and count written by code;
    its quiet columns left out (`_quiet`); the practices folded into their things or not shown (`_fold_practices`:
    the section's `inside` and `quiet` count them; each thing carries its folded practices)."""
    host, quiet = _fold_practices(rows, rs)
    views = {t["id"]: thing_view(kinds[t["kind"]], t, rs.get(t["id"], []), posts) for t in rows}
    inside: Dict[str, List[Dict[str, Any]]] = {}
    for p, h in host.items():
        inside.setdefault(h, []).append(views[p])
    out = []
    for k in sorted(kinds, key=lambda k: _order(kinds).get(k, 99)):
        its = [t for t in rows if t["kind"] == k]
        shown = [t for t in its if t["id"] not in host and t["id"] not in quiet]
        # ranked: more independent sources first, then the rows' own order (new first, newest post first)
        shown = [t for _, t in sorted(enumerate(shown), key=lambda x: (-sources_of(rs.get(x[1]["id"], []), posts), x[0]))]
        if not shown:
            continue
        d = kinds[k]
        things = [dict(views[t["id"]], **({"practices": inside[t["id"]]} if t["id"] in inside else {})) for t in shown]
        hide = _quiet(d["fields"], things)
        header = PRACTICE_HEADER if k == TT.PRACTICE_KIND else k.replace("_", " ").capitalize()
        out.append({"kind": k, "header": f"{header} ({len(shown)})", "about": d.get("about") or "",
                    "count": len(shown), "new": sum(1 for t in shown if t.get("new")),
                    "inside": sum(1 for t in its if t["id"] in host), "quiet": sum(1 for t in its if t["id"] in quiet),
                    "fields": [{"name": f["name"], "type": f["type"], **({"unit": f["unit"]} if f.get("unit") else {}),
                                **({"values": f["values"]} if f.get("values") else {})}
                               for f in d["fields"] if f["name"] not in hide],
                    "things": things})
    return out


def _hosts(sections: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """{folded practice: the thing it is shown inside}: a point citing it cites its thing."""
    return {p["id"]: t["id"] for s in sections for t in s["things"] for p in t.get("practices") or []}


def _also(cur: Any, track: Dict[str, Any], start: Optional[datetime], end: Optional[datetime], *,
          joined: bool = False, fresh: Optional[datetime] = None) -> List[str]:
    """The posts in the track published in [start, end) that gave no row (no report of any thing); `joined`: joined
    in [start, end) and published since `fresh` (v10.41: by the post's publication, as the things are: a feed that
    surfaces a 2015 post this week does not make it this week's), newest published first."""
    from insight_core.markx import track_subtopics
    items = track_subtopics.in_track(cur, track)
    ids = [it["post_id"] for it in items]
    if not ids:
        return []
    cur.execute(f"SELECT p.id::text, {TT.post_date()} FROM posts p WHERE p.id = ANY(%s::uuid[])", (ids,))
    pub = dict(cur.fetchall())

    def inside(t: Optional[datetime], lo: Optional[datetime], hi: Optional[datetime]) -> bool:
        return t is not None and (lo is None or t >= lo) and (hi is None or t < hi)
    if joined:
        ids = [it["post_id"] for it in items if inside(track_subtopics.joined_at(it), start, end)
               and inside(pub.get(it["post_id"]), fresh, None)]
    else:
        ids = [p for p in ids if inside(pub.get(p), start, end)]
    if not ids:
        return []
    cur.execute("""SELECT DISTINCT r.post_id::text FROM mx_track_thing_reports r JOIN mx_track_things t ON t.id = r.thing_id
                    WHERE t.track_id = %s AND r.post_id = ANY(%s::uuid[])""", (track["folder_id"], ids))
    gave = {p for (p,) in cur.fetchall()}
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted((p for p in dict.fromkeys(ids) if p not in gave), key=lambda p: (pub.get(p) or epoch, p), reverse=True)


def _point_views(got: Optional[Dict[str, Any]], shown: Sequence[str], host: Optional[Dict[str, str]] = None
                 ) -> List[Dict[str, Any]]:
    """The points, each cite as its row (its thing id and its number among the rows shown, for the superscripts)."""
    if not got:
        return []
    n = {t: i for i, t in enumerate(shown, 1)}
    host = host or {}
    return [{"text": p["text"], "cites": [{"thing": c, "n": n.get(c)}
                                          for c in dict.fromkeys(host.get(c, c) for c in p["cites"])]}
            for p in got["points"]]


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
    shown = [x["id"] for s in sections for x in s["things"]]
    got = points(cur, tid, week, within=shown + list(_hosts(sections)))   # 0269: only points about the week's rows
    body = {**base, "points": _point_views(got, shown, _hosts(sections)), "points_at": _iso(got["at"]) if got else None,
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
                             WHERE x.track_id = %(t)s::uuid AND {TT.post_date()} >= %(s)s AND {TT.post_date()} < %(e)s),
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

def fresh_from(since: datetime, now: datetime) -> datetime:
    """New since a look (v10.29; the quick look and the rail's count): a thing found since it whose first post is
    dated since it or in the week in progress. A thing read since the look from an older post (a new schema re-reading
    the track, a backlog) is not news: it is in its week's issue and the tables."""
    return min(since, bounds(monday(now))[0])


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
    fresh = fresh_from(since, now)
    rows = [dict(x, new=True) for x in TT.current(cur, tid)
            if x["found_at"] > since and x["kind"] in kinds and x["first_at"] is not None and x["first_at"] >= fresh]
    rs = TT.reports(cur, tid, [x["id"] for x in rows])
    also = _also(cur, t, since, None, joined=True, fresh=fresh)
    posts = _posts(cur, tid, sorted({r["post"] for x in rows for r in rs.get(x["id"], [])} | set(also)))
    order = _order(kinds)
    rows.sort(key=lambda x: (order.get(x["kind"], 99), -x["found_at"].timestamp(), x["id"]))
    sections = _sections(kinds, rows, rs, posts)
    got = points(cur, tid)
    new_ids = {x["id"] for x in rows}
    if got:   # the newest brief's points about a new thing; none new: this week's points still lead the look
        cited = [p for p in got["points"] if set(p["cites"]) & new_ids]
        got = dict(got, points=cited or ([] if rows or got["week"] != monday(now) else got["points"]))
    shown = [x["id"] for s in sections for x in s["things"]]
    pts = _point_views(got, shown, _hosts(sections)) if got and got["points"] else []
    return {**base, "sections": sections, "points": pts, "as_of": _iso(got["at"]) if pts else None,
            "stale": bool(pts) and any(x["found_at"] > got["at"] for x in rows),
            "also": [posts[p] for p in also if p in posts], "counts": {"things": len(rows), "also": len(also)},
            "nothing_new": not rows and not also and not pts, "last_issue": closed[0] if closed else None, "weeks": weeks}


SINCE_LINES = 3   # 0271: a track's top lines in "Since you looked"


def since_lines(cur: Any, folder_id: Any, since: datetime, *, now: Optional[datetime] = None,
                n: int = SINCE_LINES) -> Dict[str, Any]:
    """0271: a track in "Since you looked", read from its quick look since `since` (no second path): {id, name, since,
    new (things found since), also (posts joined since that gave no row), lines: the top `n`, the things most
    independent sources reported first, those first reported after the look before the rest (each {text: its name,
    kind, sources, post}), then the joined posts}.
    KeyError: not a topic track."""
    q = quick_look(cur, folder_id, since, now=now)
    # first reported after the look first (a thing re-read from an older post of the week is new to the track, not
    # to the reader), then by sources; stable
    things = sorted((t for s in q["sections"] for t in s["things"]),
                    key=lambda t: (not (t["first_at"] and datetime.fromisoformat(t["first_at"]) > since), -t["sources"]))
    lines: List[Dict[str, Any]] = []
    for t in things[:n]:
        name = next(iter(t["fields"].values()), None)
        post = t["posts"][0]["id"] if t["posts"] else (name or {}).get("post")
        lines.append({"text": name["shown"] if name else t["kind"].replace("_", " "), "kind": t["kind"],
                      "sources": t["sources"], "post": post})
    for p in q["also"][:max(0, n - len(lines))]:
        lines.append({"text": p["title"] or p["url"], "kind": None, "sources": 1, "post": p["id"]})
    return {"id": q["track"]["id"], "name": q["track"]["name"], "since": q["since"], "new": q["counts"]["things"],
            "also": q["counts"]["also"], "lines": lines}


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
