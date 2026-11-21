"""An entity's brief (issues 0156 the knowledge page and 0245 the general briefer; built: 0261, Stealth v10.31): what
it is, how it works, and is it good (measured results and who measured them), every line cited, read on its page.

**One briefer, not a second one.** An entity is briefed as a track whose subject is the entity: its "track" is the
entity's root id, its description is the entity's own words (name, type, maker, other names: `subject`), and its
schema is the general one below (`SCHEMA`, the same for every entity; code writes it, Haiku never proposes it). From
there everything is track_things' and track_brief's: the questions (`track_things.ask_posts`: windows, links, the
maker's linked pages, kind `track_things`, guide track-things-v1), the checks (every value's quote in what the
question showed: `track_things.salvage`, the worker too), the reports, the joins by key, and "what changed"
(digest-v3, the digest kind) over every row so far. Nothing here names an entity or a type.

Stored where a track's things are (mx_track_schemas / mx_track_things / mx_track_thing_reports / mx_track_brief_asks,
`track_id` the entity's root): a schema row says whose it is (`subject` 'entity', `by` 'code': migration 0167). An
entity merged later keeps its rows under the root it was briefed as (keep everything); the page reads its root's.

**Which posts**: the posts whose current reading names the entity (through its merges and pins) as their subject or
actor (entity_views.ROLE_REPORT), newest first, MAX_POSTS at most. A post that only mentions it is not read for it.
**Which entities**: the ones the owner opens (kept_pages.most_opened, OPENED pages of the last 14 days) with
MIN_POSTS such posts or more; ASKS_A_DAY things questions a day across entities at most (bounded cost).

**The brief** (`view`): `what` (what_it_is rows: definition, its stage, its maker), `how` (how_it_works rows),
`results` (the practice_or_claim rows: what, result, evidence, and `who`: the sources of the posts that reported it,
from the posts, never from Haiku), each line with its cites (the posts, numbered for superscripts, each cite with the
quote it rests on), and `points` (digest-v3 over the rows), `as_of` (the newest report). Rows reported by more
sources come first. Behind entity_bands.json `entities.brief` (`on`): off, nothing is asked and the page has no brief.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from insight_core.markx import track_things as TT

SWITCH = ("entities", "brief")
SUBJECT = "entity"
SCHEMA_VERSION = 1      # the general schema's version (its track_version): a change here re-reads every post
MIN_POSTS = 3           # an entity is briefed with this many subject/actor posts or more
MAX_POSTS = 12          # posts read for an entity at most (newest first)
OPENED = 50             # the most opened entity pages considered (kept_pages.most_opened, 14 days)
ASKS_A_DAY = 150        # things questions a day across entities at most
PERIOD = "everything its posts say so far"
SHOWN = {"what": 3, "how": 6, "results": 8}
WHAT, HOW = "what_it_is", "how_it_works"
SCHEMA = {"kinds": [
    {"kind": WHAT, "about": "what the subject itself is: a definition line, its stage, who makes it",
     "fields": [{"name": "definition", "type": "text", "key": True,
                 "about": "what the subject is, in a few words (a kind of thing and what it is for)"},
                {"name": "stage", "type": "text", "key": False,
                 "about": "its stage as stated: experimental, preview, beta, released, retired, a version"},
                {"name": "maker", "type": "text", "key": False, "about": "who makes, runs or owns it"}]},
    {"kind": HOW, "about": "how the subject works or is used: its mechanism, how to enable, set up or use it, what "
                           "it needs",
     "fields": [{"name": "how", "type": "text", "key": True, "about": "one way it works or one step of using it"},
                {"name": "detail", "type": "text", "key": False,
                 "about": "a setting, command, flag, version or requirement given for it"}]},
]}


def on() -> bool:
    """entity_bands.json `entities.brief` (default off)."""
    from insight_core.markx import identity
    return bool((identity.bands().get(SWITCH[0]) or {}).get(SWITCH[1]))


def schema() -> Dict[str, Any]:
    """The general schema with the practice kind code always adds (its results)."""
    return TT.with_practice(SCHEMA)


def subject(name: str, type_: Optional[str], maker: Optional[str], aliases: Sequence[str], entity_id: str
            ) -> Dict[str, Any]:
    """The entity as a track: its root id, its name, a description from its own words, what is left out."""
    other = sorted({a for a in aliases if a and a.casefold() != (name or "").casefold()})[:6]
    words = ", ".join(x for x in (type_ if type_ and type_ != "other" else "",
                                  f"made by {maker}" if maker else "",
                                  ("also called " + "; ".join(other)) if other else "") if x)
    return {"folder_id": entity_id, "name": name,
            "description": f"{name}" + (f" ({words})" if words else "") + f": what {name} itself is, how it works or "
                           f"is used (how to enable or set it up), and the results measured or reported for it "
                           f"(numbers, tests, verdicts).",
            "excludes": f"anything not about {name} itself: other products, people or events the post names"}


def _subject(cur: Any, book: Any, root: str) -> Dict[str, Any]:
    from insight_core.markx import entity_views as EV
    v = EV._ent_view(book, root)
    return subject(v["name"], v["type"], v["maker"], [book.ents[m].name for m in EV._members(book, root)], root)


def report_posts(cur: Any, book: Any, root: str) -> List[str]:
    """The posts naming the entity (its merges and pins) as subject or actor, newest first, MAX_POSTS at most."""
    from insight_core.markx import entity_views as EV
    at: Dict[str, Any] = {}
    for pid, n, role, eid, when, _s, _r, g in EV._rows(cur, EV._guide(), None, EV._members(book, root)):
        if role in EV.ROLE_REPORT and book.root(book.pins.get((pid, g, n), eid)) == root and when is not None:
            at[pid] = max(at.get(pid, when), when)
    return sorted(at, key=lambda p: (at[p], p), reverse=True)[:MAX_POSTS]


def ensure_schema(cur: Any, root: str) -> Dict[str, Any]:
    """The entity's schema row (written by code once, again when SCHEMA_VERSION changes)."""
    s = TT.current_schema(cur, root)
    if s is None or s["track_version"] != SCHEMA_VERSION or s["schema"] != schema():
        TT._put_schema(cur, root, schema(), by="code", track_version=SCHEMA_VERSION, subject=SUBJECT)
        s = TT.current_schema(cur, root)
    return s


def candidates(cur: Any) -> List[str]:
    """The roots of the most opened entity pages (OPENED, 14 days), in that order, each once."""
    from insight_core.markx import entity_views as EV, kept_pages
    book = EV.I.lazy_book(cur)
    out: List[str] = []
    for key in kept_pages.most_opened(cur, "entity", OPENED):
        eid = key.partition("?replies=")[0]
        if EV.I._UUID.match(eid) and eid in book.ents:
            r = book.root(eid)
            if r not in out:
                out.append(r)
    return out


def asked_today(cur: Any, now: datetime) -> int:
    cur.execute("""SELECT count(*) FROM mx_tasks t WHERE t.kind = %s AND t.created_at >= %s
                      AND t.b IN (SELECT track_id FROM mx_track_schemas WHERE subject = %s)""",
                (TT.THINGS_KIND, now.replace(hour=0, minute=0, second=0, microsecond=0), SUBJECT))
    return cur.fetchone()[0]


def _worth(cur: Any, roots: Optional[Sequence[str]]):
    """(book, [(root, its report posts)]) of the entities worth a brief: `candidates` (or `roots`) with MIN_POSTS+."""
    from insight_core.markx import entity_views as EV
    book = EV.I.lazy_book(cur)
    out = []
    for root in (roots if roots is not None else candidates(cur)):
        if root in book.ents:
            posts = report_posts(cur, book, root)
            if len(posts) >= MIN_POSTS:
                out.append((root, posts))
    return book, out


def plan_things(cur: Any, *, now: Optional[datetime] = None, roots: Optional[Sequence[str]] = None, **_kw: Any) -> int:
    """The things questions (the track_things planner's part) of the entities worth a brief: their report posts not
    yet asked under the schema's version (track_things.ask_posts), within ASKS_A_DAY. How many were added."""
    from insight_core.markx import schemas
    if not on():
        return 0
    now = now or datetime.now(timezone.utc)
    schemas.ensure_guides(cur)
    book, worth = _worth(cur, roots)
    added = 0
    for root, posts in worth:
        room = ASKS_A_DAY - asked_today(cur, now)
        if room <= 0:
            break
        s = ensure_schema(cur, root)
        added += TT.ask_posts(cur, _subject(cur, book, root), s, posts, room=room)
    return added


def plan_points(cur: Any, *, now: Optional[datetime] = None, roots: Optional[Sequence[str]] = None, **_kw: Any) -> int:
    """The digest planner's part: a digest-v3 question over each briefed entity's rows when they changed
    (track_brief.plan_subject). How many were added."""
    from insight_core.markx import track_brief
    if not on():
        return 0
    now = now or datetime.now(timezone.utc)
    book, worth = _worth(cur, roots)
    added = 0
    for root, _posts in worth:
        if TT.current_schema(cur, root) is not None:
            added += track_brief.plan_subject(cur, _subject(cur, book, root), now=now, period=PERIOD)
    return added


# ---- the view ------------------------------------------------------------------------------------------------

def _posts(cur: Any, ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    from insight_core.markx import tracks
    if not ids:
        return {}
    cur.execute(f"""SELECT p.id::text, p.title, p.url, {tracks._date()}, p.source_id::text,
                           COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                                    s.handle_or_url)
                      FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ANY(%s::uuid[])""", (list(ids),))
    return {i: {"id": i, "title": " ".join((t or "").split())[:160] or None, "url": u,
                "at": at.isoformat() if at else None, "source_id": src, "source": name}
            for i, t, u, at, src, name in cur.fetchall()}


def _val(t: Dict[str, Any], name: str) -> Optional[str]:
    v = (t["fields"] or {}).get(name)
    return None if v is None or v.get("value") in (None, "") else str(v["value"])


def line_text(kind: str, t: Dict[str, Any]) -> str:
    """A row as one line of the brief, from its own fields only."""
    if kind == WHAT:
        extra = [x for x in (_val(t, "stage"), ("by " + _val(t, "maker")) if _val(t, "maker") else None) if x]
        return _val(t, "definition") + (f" ({'; '.join(extra)})" if extra else "")
    if kind == HOW:
        return _val(t, "how") + (f": {_val(t, 'detail')}" if _val(t, "detail") else "")
    out = _val(t, "what") or ""
    if _val(t, "result"):
        out += f": {_val(t, 'result')}"
    if _val(t, "evidence") and _val(t, "evidence") not in out:
        out += f" ({_val(t, 'evidence')})"
    return out


def view(cur: Any, root: str) -> Optional[Dict[str, Any]]:
    """The brief of an entity (its root), or None (off, or nothing found yet): {what, how, results, points, as_of,
    posts}. Each line {text, cites: [{n, post, quote}], sources} (results also `who`: its posts' sources); `posts`
    numbers the cited posts in order of first cite (the superscripts) with their title, address, source and date."""
    from insight_core.markx import track_brief as TB
    if not on():
        return None
    s = TT.current_schema(cur, root)
    if s is None:
        return None
    things = TT.current(cur, root)
    if not things:
        return None
    rs = TT.reports(cur, root, [t["id"] for t in things])
    posts = _posts(cur, sorted({r["post"] for v in rs.values() for r in v}))
    numbers: Dict[str, int] = {}

    def cite(t: Dict[str, Any]) -> List[Dict[str, Any]]:
        out, seen = [], set()
        for r in reversed(rs.get(t["id"], [])):   # newest first
            if r["post"] in seen or r["post"] not in posts:
                continue
            seen.add(r["post"])
            vals = r["values"] or {}
            first = next(iter(vals.values()), {}) if vals else {}
            out.append({"post": r["post"], "quotes": [v.get("quote") for v in vals.values() if v.get("quote")][:3],
                        "quote": first.get("quote")})
        return out

    by_kind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    for t in sorted(things, key=lambda t: (-TB.sources_of(rs.get(t["id"], []), posts),
                                           -(t["last_at"] or epoch).timestamp(), t["id"])):
        text = line_text(t["kind"], t).strip()
        if not text:
            continue
        cs = cite(t)
        if not cs:
            continue
        by_kind[t["kind"]].append({"thing": t["id"], "text": text, "cites": cs,
                                   "sources": TB.sources_of(rs.get(t["id"], []), posts)})
    sections = {"what": by_kind.get(WHAT, [])[:SHOWN["what"]], "how": by_kind.get(HOW, [])[:SHOWN["how"]],
                "results": by_kind.get(TT.PRACTICE_KIND, [])[:SHOWN["results"]]}
    for ln in sections["results"]:
        ln["who"] = sorted({posts[c["post"]]["source"] for c in ln["cites"] if posts[c["post"]].get("source")})
    shown_things = []
    for name in ("what", "how", "results"):
        for ln in sections[name]:
            shown_things.append(ln["thing"])
            for c in ln["cites"]:
                c["n"] = numbers.setdefault(c["post"], len(numbers) + 1)
    if not shown_things:
        return None
    got = TB.points(cur, root)
    line_of = {t: ln for name in ("what", "how", "results") for ln in sections[name] for t in [ln["thing"]]}
    points = []
    for p in (got or {}).get("points") or []:
        ns = sorted({c["n"] for t in p["cites"] if t in line_of for c in line_of[t]["cites"]})
        if ns:
            points.append({"text": p["text"], "cites": ns})
    found = [r["found_at"] for v in rs.values() for r in v if r.get("found_at")]
    return {**sections, "points": points,
            "as_of": max(found).isoformat() if found else None,
            "posts": [dict(posts[p], n=n) for p, n in sorted(numbers.items(), key=lambda x: x[1])]}


def stamp(cur: Any, root: str) -> List[Any]:
    """What the brief reads that changes it (the entity page's kept-page inputs): its reports and its brief asks."""
    cur.execute("""SELECT (SELECT json_build_array(count(*), max(r.created_at)) FROM mx_track_thing_reports r
                             JOIN mx_track_things t ON t.id = r.thing_id WHERE t.track_id = %s),
                          (SELECT json_build_array(count(*), max(c.created_at)) FROM mx_track_brief_asks a
                             JOIN mx_calls c ON c.task_id = a.task_id AND c.valid WHERE a.track_id = %s),
                          (SELECT json_build_array(count(*), max(updated_at)) FROM mx_track_things
                            WHERE track_id = %s)""", (root, root, root))
    return list(cur.fetchone()) + [on()]
