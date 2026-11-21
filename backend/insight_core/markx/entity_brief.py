"""An entity's brief (issues 0156 the knowledge page and 0245 the general briefer; built: 0261, Stealth v10.31): what
it is, how it works, and is it good (measured results and who measured them), every line cited, read on its page.

**One briefer, not a second one.** An entity is briefed as a track whose subject is the entity: its "track" is the
entity's root id, its description is the entity's own words (name, type, maker, other names: `subject`), and its
schema is the general one below (`SCHEMA`, the same for every entity; code writes it, Haiku never proposes it). From
there everything is track_things' and track_brief's: the questions (`track_things.ask_posts`: windows, links, the
maker's linked pages, kind `track_things`, guide track-things-v2), the checks (every value's quote in what the
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
from typing import Any, Dict, List, Optional, Sequence, Tuple

from insight_core.markx import track_things as TT

SWITCH = ("entities", "brief")
SUBJECT = "entity"
SCHEMA_VERSION = 2      # the general schema's version (its track_version): a change here re-reads every post
                        # (0269: 2, what_it_is says whose definition it is: `subject`)
MIN_POSTS = 5           # an entity is briefed with this many subject/actor posts or more (0269: was 3)
SHOW_POSTS = 5          # 0269: a brief is shown only when this many of its posts were read (one post misled)
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
                {"name": "subject", "type": "text", "key": False,
                 "about": "the name of the thing this definition is about, exactly as the post writes it: the "
                          "subject's own name, or the name of another product, part or feature named with it"},
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


def own_sources(cur: Any, book: Any, root: str) -> set:
    """0269: the sources that are the entity or its maker (person_page.by_sources: via its voice, or the owner's yes):
    their posts are its own announcements, read first."""
    from insight_core.markx import entity_views as EV, person_page
    out = set()
    mk = EV._ent_view(book, root).get("maker_id")
    for r in dict.fromkeys(x for x in (root, book.root(mk) if mk else None) if x and x in book.ents):
        out |= {s["id"] for s in person_page.by_sources(cur, book, r, EV._members(book, r))["by"]}
    return out


def report_posts(cur: Any, book: Any, root: str) -> List[str]:
    """The posts naming the entity (its merges and pins) as subject or actor, MAX_POSTS at most: 0269, its own and its
    maker's posts first (`own_sources`), then the newest."""
    from insight_core.markx import entity_views as EV
    at: Dict[str, Any] = {}
    src: Dict[str, str] = {}
    for pid, n, role, eid, when, s, _r, g in EV._rows(cur, EV._guide(), None, EV._members(book, root)):
        if role in EV.ROLE_REPORT and book.root(book.pins.get((pid, g, n), eid)) == root and when is not None:
            at[pid] = max(at.get(pid, when), when)
            src[pid] = s
    own = own_sources(cur, book, root) if at else set()
    return sorted(at, key=lambda p: (src.get(p) in own, at[p], p), reverse=True)[:MAX_POSTS]


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


def line_parts(kind: str, t: Dict[str, Any], names: Sequence[str] = ()) -> Tuple[str, Optional[str]]:
    """A row as one line of the brief, from its own fields only: (its text, its note or None), shown apart, never
    glued into one string of labels (0269). what_it_is: the definition, its note the stage and maker; how_it_works: the
    step, its note the detail; a result: "what → result" ("what" left out when it is the entity's own name), its note
    the evidence only when it gives figures the line does not."""
    from insight_core.markx import track_brief as TB
    if kind == WHAT:
        note = " · ".join(x for x in (_val(t, "stage"), ("by " + _val(t, "maker")) if _val(t, "maker") else None) if x)
        return _val(t, "definition") or "", note or None
    if kind == HOW:
        how, detail = _val(t, "how") or "", _val(t, "detail")
        return how, detail if detail and TT.fold(detail) not in TT.fold(how) else None
    what, result, evidence = _val(t, "what"), _val(t, "result"), _val(t, "evidence")
    if what and TT.fold(what) in {TT.fold(n) for n in names}:
        what = None
    text = " → ".join(x for x in (what, result) if x)
    adds = evidence and TB._digits(evidence) - TB._digits(text)
    return text, evidence if adds else None


def line_text(kind: str, t: Dict[str, Any], names: Sequence[str] = ()) -> str:
    """The line's text and its note as one string (the tests' and the logs' reading of a line)."""
    text, note = line_parts(kind, t, names)
    return text + (f" ({note})" if note else "")


def own_what(t: Dict[str, Any], names: Sequence[str]) -> bool:
    """0269: a what_it_is row about the entity itself: its `subject` is one of the entity's names (a definition of
    "<Entity> Camera" from a post about it is that product's, not the entity's). A row without a subject (asked
    before schema 2) is not known to be the entity's."""
    subj = _val(t, "subject")
    return bool(subj) and TT.fold(subj) in {TT.fold(n) for n in names if n}


def _same(ln: Dict[str, Any]) -> Tuple[frozenset, frozenset]:
    """0269: what two lines of one meaning share, by a simple sound rule: the same figures and the same key words (the
    folded words of 4 letters or more). Anything less alike is left to the joins (track_things' keys)."""
    import re
    from insight_core.markx import track_brief as TB
    words = " ".join(x for x in (ln["text"], ln.get("note") or "") if x)
    return frozenset(TB._digits(words)), frozenset(w for w in re.findall(r"\w+", TT.fold(words)) if len(w) >= 4)


def read_posts(cur: Any, root: str) -> int:
    """0269: the posts the brief has read (a things question of the entity answered)."""
    cur.execute("SELECT count(DISTINCT a) FROM mx_tasks WHERE kind = %s AND b = %s AND status = 'answered'",
                (TT.THINGS_KIND, root))
    return cur.fetchone()[0]


def view(cur: Any, root: str, names: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
    """The brief of an entity (its root; `names`: its members' names), or None (off, nothing found yet, 0269: fewer
    than SHOW_POSTS posts read, or no what_it_is line about the entity itself): {what, how, results, points, as_of,
    posts}. Each line {text, note, cites: [{n, post, quote}], sources} (results also `who`: its posts' sources);
    lines of the same figures and key words are one (`_same`); `posts` numbers the cited posts in order of first cite
    (the superscripts) with their title, address, source and date."""
    from insight_core.markx import track_brief as TB
    if not on():
        return None
    s = TT.current_schema(cur, root)
    if s is None:
        return None
    things = TT.current(cur, root)
    if not things or read_posts(cur, root) < SHOW_POSTS:
        return None
    things = [t for t in things if t["kind"] != WHAT or own_what(t, names)]
    if not any(t["kind"] == WHAT for t in things):
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
    alike: Dict[Any, Dict[str, Any]] = {}
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    for t in sorted(things, key=lambda t: (-TB.sources_of(rs.get(t["id"], []), posts),
                                           -(t["last_at"] or epoch).timestamp(), t["id"])):
        text, note = line_parts(t["kind"], t, names)
        text = text.strip()
        if not text:
            continue
        cs = cite(t)
        if not cs:
            continue
        ln = {"thing": t["id"], "text": text, "note": note, "cites": cs,
              "sources": TB.sources_of(rs.get(t["id"], []), posts), "by": _val(t, "by")}
        key = (t["kind"], _same(ln))
        if key in alike:   # 0269: the same figures and key words: one line, every post it rests on cited
            first = alike[key]
            first["cites"] += [c for c in cs if c["post"] not in {x["post"] for x in first["cites"]}]
            first["also"].append(t["id"])
            continue
        alike[key] = ln
        ln["also"] = []
        by_kind[t["kind"]].append(ln)
    sections = {"what": by_kind.get(WHAT, [])[:SHOWN["what"]], "how": by_kind.get(HOW, [])[:SHOWN["how"]],
                "results": by_kind.get(TT.PRACTICE_KIND, [])[:SHOWN["results"]]}
    line_of: Dict[str, Dict[str, Any]] = {}
    for name in sections:
        for ln in sections[name]:
            for t in [ln["thing"], *ln.pop("also")]:
                line_of[t] = ln
            by = ln.pop("by")
            if name == "results":   # who measured it, when its quote names them; else the posts' sources
                ln["who"] = [by] if by else sorted({posts[c["post"]]["source"] for c in ln["cites"]
                                                    if posts[c["post"]].get("source")})
    shown_things = []
    for name in ("what", "how", "results"):
        for ln in sections[name]:
            shown_things.append(ln["thing"])
            for c in ln["cites"]:
                c["n"] = numbers.setdefault(c["post"], len(numbers) + 1)
    if not shown_things:
        return None
    got = TB.points(cur, root)
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
