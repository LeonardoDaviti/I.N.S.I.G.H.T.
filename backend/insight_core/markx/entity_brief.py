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

import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from insight_core.markx import track_things as TT

SWITCH = ("entities", "brief")
SUBJECT = "entity"
SCHEMA_VERSION = 2      # the general schema's version (its track_version): a change here re-reads every post
                        # (0269: 2, what_it_is says whose definition it is: `subject`)
NUMBERS_VERSION = 3     # 0272: the schema's version with the measure kind (entities.numbers on): its posts read again
MIN_POSTS = 5           # an entity is briefed with this many subject/actor posts or more (0269: was 3)
SHOW_POSTS = 5          # 0269: a brief is shown only when this many of its posts were read (one post misled)
MAX_POSTS = 12          # posts read for an entity at most (newest first)
OPENED = 50             # the most opened entity pages considered (kept_pages.most_opened, 14 days)
ASKS_A_DAY = 150        # things questions a day across entities at most
PERIOD = "everything its posts say so far"
SHOWN = {"what": 3, "how": 6, "results": 8}
WHAT, HOW, MEASURE = "what_it_is", "how_it_works", "measure"
NUMBERS_SWITCH = ("entities", "numbers")   # 0272: the numbers over time on the page (the rows are asked either way)
NUMBERS_SHOWN = 12      # measures shown at most (the most reported first)
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
MEASURE_KIND = {"kind": MEASURE, "about": "one figure the post states of the subject itself: a score on a benchmark, a price, a "
                               "speed, a size, a count, a share, revenue; one thing per figure (when it is also a "
                               "result, give that result too)",
     "fields": [{"name": "measure", "type": "text", "key": True,
                 "about": "what is measured, named so the same measure reads the same in every post: the benchmark or "
                          "quantity alone, without the figure or the subject's name, with the period it covers when "
                          "it is a flow (\"SWE-bench Verified score\", \"price per million input tokens\", "
                          "\"memory bandwidth\", \"share price\", \"quarterly revenue\", \"annual revenue\")"},
                {"name": "value", "type": "number", "key": False,
                 "about": "the figure when it is not money, with its unit as the quote writes it (%, tok/s, GB, ...); "
                          "a fall, drop or loss as a negative number"},
                {"name": "amount", "type": "money", "key": False,
                 "about": "the figure when it is money; its `unit` what the money is per, as the quote writes it "
                          "(per month, per million input tokens, per PH/s per day), or null"},
                {"name": "setting", "type": "text", "key": False,
                 "about": "what the figure is of, when the post says: a version or variant, a mode, the game, task "
                          "or test it was measured on, a test setting"},
                {"name": "as_of", "type": "text", "key": False,
                 "about": "the date or period the figure is for, when the post states one (\"Q3 2025\", \"March\")"}]}


def on() -> bool:
    """entity_bands.json `entities.brief` (default off)."""
    from insight_core.markx import identity
    return bool((identity.bands().get(SWITCH[0]) or {}).get(SWITCH[1]))


def numbers_on() -> bool:
    """entity_bands.json `entities.numbers` (0272, default off): the page shows the numbers over time."""
    from insight_core.markx import identity
    return bool((identity.bands().get(NUMBERS_SWITCH[0]) or {}).get(NUMBERS_SWITCH[1]))


def schema() -> Dict[str, Any]:
    """The general schema with the practice kind code always adds (its results); 0272: with the measure kind while
    entities.numbers is on (off: the schema the brief was measured with, unchanged)."""
    return TT.with_practice({"kinds": SCHEMA["kinds"] + ([MEASURE_KIND] if numbers_on() else [])})


def schema_version() -> int:
    return NUMBERS_VERSION if numbers_on() else SCHEMA_VERSION


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
    if s is None or s["track_version"] != schema_version() or s["schema"] != schema():
        TT._put_schema(cur, root, schema(), by="code", track_version=schema_version(), subject=SUBJECT)
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
    added = plan_senses(cur, book, worth)   # 0274: the sense question of each, before its things
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


def read_posts(cur: Any, root: str, posts: Optional[Sequence[str]] = None) -> int:
    """0269: the posts the brief has read (a things question of the entity answered); 0274: of `posts` only."""
    if posts is None:
        cur.execute("SELECT count(DISTINCT a) FROM mx_tasks WHERE kind = %s AND b = %s AND status = 'answered'",
                    (TT.THINGS_KIND, root))
    else:
        cur.execute("""SELECT count(DISTINCT a) FROM mx_tasks WHERE kind = %s AND b = %s AND status = 'answered'
                          AND a = ANY(%s::uuid[])""", (TT.THINGS_KIND, root, list(posts)))
    return cur.fetchone()[0]


# ---- 0272: numbers over time ---------------------------------------------------------------------------------

_PERCENT = {"%", "percent", "per cent", "pct", "процент", "процентов", "процента"}


def unit_key(unit: Any) -> str:
    """A unit as two series are compared: folded, no spaces or trailing dots; every way of writing percent is '%'."""
    u = re.sub(r"\s+", " ", TT.fold(unit or "")).strip(" .")
    return "%" if u in _PERCENT else u.replace(" ", "")


def _day(at: Any) -> Optional[str]:
    return at.date().isoformat() if isinstance(at, datetime) else (str(at)[:10] if at else None)


def series(reported: Sequence[Dict[str, Any]], *, min_posts: int = 2) -> List[Dict[str, Any]]:
    """The numbers over time of an entity from its measure reports ([{post, at, values}]: values as stored, each
    {value, quote}): one series per measure name (key_text), unit (a money figure's currency and what it is per) and
    setting (the game, task or variant it is of: a different setting is a different measure), each value with its
    date (the post's; `as_of` when the post states the period), post, quote and setting; a post's same figure once.
    Only series with `min_posts` posts or more. Two values of one series, date and setting from different posts that
    differ are a dispute (0097): both kept, both marked, never averaged. Most reported series first."""
    fields = {f["name"]: f for f in MEASURE_KIND["fields"]}
    groups: Dict[Any, Dict[str, Any]] = {}
    for r in reported:
        vals = r.get("values") or {}
        name = (vals.get("measure") or {}).get("value")
        fig, field = None, None
        for f in ("value", "amount"):
            if isinstance((vals.get(f) or {}).get("value"), dict):
                fig, field = vals[f], fields[f]
                break
        if not isinstance(name, str) or not name.strip() or fig is None:
            continue
        v = fig["value"]
        money = field["name"] == "amount"
        unit = ("money:" + " ".join(x for x in (v.get("currency", ""), v.get("unit")) if x)) if money \
            else "unit:" + unit_key(v.get("unit"))
        setting = (vals.get("setting") or {}).get("value")
        key = (TT.key_text(name), (v.get("currency", "") if money else "") + "|" + unit_key(v.get("unit")),
               TT.key_text(setting))
        g = groups.setdefault(key, {"names": defaultdict(int), "points": [], "seen": set(), "unit": unit,
                                    "setting": setting})
        g["names"][name.strip()] += 1
        as_of = (vals.get("as_of") or {}).get("value")
        mark = (r["post"], v["number"], v.get("range_to"), TT.key_text(setting))
        if mark in g["seen"]:
            continue
        g["seen"].add(mark)
        g["points"].append({"at": _day(r.get("at")), "as_of": as_of, "value": v["number"], "range_to": v.get("range_to"),
                            "shown": TT.shown_value(field, v), "setting": setting, "post": r["post"],
                            "quote": fig.get("quote"), "dispute": False})
    out = []
    for _k, g in groups.items():
        unit = g["unit"]
        pts = g["points"]
        if len({p["post"] for p in pts}) < min_posts or len(pts) < 2:
            continue
        pts.sort(key=lambda p: (p["at"] or "", p["post"]))
        when: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
        for p in pts:
            when[TT.key_text(p["as_of"]) or p["at"]].append(p)
        disputes = 0
        for same in when.values():
            if len({p["post"] for p in same}) > 1 and len({(p["value"], p["range_to"]) for p in same}) > 1:
                disputes += 1
                for p in same:
                    p["dispute"] = True
        name = sorted(g["names"].items(), key=lambda x: (-x[1], x[0]))[0][0]
        out.append({"measure": name, "unit": unit.partition(":")[2] or None, "money": unit.startswith("money:"),
                    "setting": g["setting"],
                    "points": pts, "posts": len({p["post"] for p in pts}), "disputes": disputes})
    out.sort(key=lambda s: (-s["posts"], -len(s["points"]), s["measure"]))
    return out



def _cite(rs: Sequence[Dict[str, Any]], posts: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """A line's cites: its reports' posts, newest first, each with the quotes it rests on."""
    out, seen = [], set()
    for r in reversed(list(rs)):   # newest first
        if r["post"] in seen or r["post"] not in posts:
            continue
        seen.add(r["post"])
        vals = r["values"] or {}
        first = next(iter(vals.values()), {}) if vals else {}
        out.append({"post": r["post"], "quotes": [v.get("quote") for v in vals.values() if v.get("quote")][:3],
                    "quote": first.get("quote")})
    return out


def _fields(rs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """0274: a thing's fields from these reports only (track_things.merged_fields: one rule for both)."""
    from insight_core.markx import track_things
    return track_things.merged_fields(rs)


def _sections(things: Sequence[Dict[str, Any]], rs: Dict[str, List[Dict[str, Any]]], posts: Dict[str, Dict[str, Any]],
              names: Sequence[str], only: Optional[Set[str]] = None
              ) -> Optional[Tuple[Dict[str, List[Dict[str, Any]]], Dict[str, Dict[str, Any]]]]:
    """({what, how, results}, {thing: its line}) of these things, or None (no what_it_is line about the entity itself,
    0269). `only` (0274): a sense's posts: each thing read from those posts' reports alone (its fields too)."""
    from insight_core.markx import track_brief as TB
    rows = []
    for t in things:
        mine = [r for r in rs.get(t["id"], []) if only is None or r["post"] in only]
        if mine:
            rows.append((t if only is None else dict(t, fields=_fields(mine)), mine))
    rows = [(t, mine) for t, mine in rows if t["kind"] != WHAT or own_what(t, names)]
    if not any(t["kind"] == WHAT for t, _m in rows):
        return None
    by_kind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    alike: Dict[Any, Dict[str, Any]] = {}
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    for t, mine in sorted(rows, key=lambda x: (-TB.sources_of(x[1], posts),
                                               -(x[0]["last_at"] or epoch).timestamp(), x[0]["id"])):
        if t["kind"] == MEASURE:   # 0272: a measure is a value of the numbers over time, never a line
            continue
        text, note = line_parts(t["kind"], t, names)
        text = text.strip()
        if not text:
            continue
        cs = _cite(mine, posts)
        if not cs:
            continue
        ln = {"thing": t["id"], "text": text, "note": note, "cites": cs,
              "sources": TB.sources_of(mine, posts), "by": _val(t, "by")}
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
    return sections, line_of


def view(cur: Any, root: str, names: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
    """The brief of an entity (its root; `names`: its members' names), or None (off, nothing found yet, 0269: fewer
    than SHOW_POSTS posts read, or no what_it_is line about the entity itself): {what, how, results, points, as_of,
    numbers, posts[, senses]}. Each line {text, note, cites: [{n, post, quote}], sources} (results also `who`: its posts'
    sources); lines of the same figures and key words are one (`_same`); `posts` numbers the cited posts in order of
    first cite (the superscripts) with their title, address, source and date. 0274: when the entity's posts hold 2+
    senses (`senses`), the three lists are empty and `senses` holds one brief a sense ({label, kind, maker,
    post_count, what, how, results}), each by 0269's rules over its own posts (SHOW_POSTS of them read, a what line
    about the sense itself by its names and the names its posts wrote); a sense short of them is listed, no lines."""
    from insight_core.markx import track_brief as TB
    if not on():
        return None
    s = TT.current_schema(cur, root)
    if s is None:
        return None
    things = TT.current(cur, root)
    if not things or read_posts(cur, root) < SHOW_POSTS:
        return None
    rs = TT.reports(cur, root, [t["id"] for t in things])
    posts = _posts(cur, sorted({r["post"] for v in rs.values() for r in v}))
    sense = senses(cur, root)
    out_senses: List[Dict[str, Any]] = []
    if sense is None:
        got = _sections(things, rs, posts, names)
        if got is None:
            return None
        sections, line_of = got
        parts = [sections]
    else:   # 0274: one brief a sense, each from its own posts' reports only
        sections, line_of, parts = {"what": [], "how": [], "results": []}, {}, []
        for x in sense:
            got = (_sections(things, rs, posts, list(names) + x["names"], set(x["posts"]))
                   if read_posts(cur, root, x["posts"]) >= SHOW_POSTS else None)
            part = got[0] if got else {"what": [], "how": [], "results": []}
            if got:
                line_of.update(got[1])
                parts.append(part)
            out_senses.append({"label": x["label"], "kind": x["kind"], "maker": x["maker"],
                               "post_count": len(x["posts"]), **part, "numbers": []})
    numbers: Dict[str, int] = {}
    shown_things = []
    for part in parts:
        for name in ("what", "how", "results"):
            for ln in part[name]:
                shown_things.append(ln["thing"])
                for c in ln["cites"]:
                    c["n"] = numbers.setdefault(c["post"], len(numbers) + 1)
    numbers_shown: List[Dict[str, Any]] = []
    if numbers_on():   # 0272: each recurring measure's values over time (0274: a sense's from its own posts)
        for part, only in ([(sections, None)] if sense is None else
                           [(p, set(x["posts"])) for p, x in zip(out_senses, sense)]):
            got_series = series([dict(r) for t in things if t["kind"] == MEASURE for r in rs.get(t["id"], [])
                                 if r["post"] in posts and (only is None or r["post"] in only)])
            part["numbers"] = []
            for sr in got_series[:NUMBERS_SHOWN]:
                for pt in sr["points"]:
                    pt["n"] = numbers.setdefault(pt["post"], len(numbers) + 1)
                part["numbers"].append(sr)
            numbers_shown += part["numbers"]
    if not shown_things and not numbers_shown:
        return None
    got = TB.points(cur, root)
    points = []
    for p in (got or {}).get("points") or []:
        ns = sorted({c["n"] for t in p["cites"] if t in line_of for c in line_of[t]["cites"]})
        if ns:
            points.append({"text": p["text"], "cites": ns})
    found = [r["found_at"] for v in rs.values() for r in v if r.get("found_at")]
    return {**{k: sections[k] for k in ("what", "how", "results")}, "points": points,
            "numbers": sections.get("numbers", []), **({"senses": out_senses} if out_senses else {}),
            "as_of": max(found).isoformat() if found else None,
            "posts": [dict(posts[p], n=n) for p, n in sorted(numbers.items(), key=lambda x: x[1])]}


# ---- 0274: the senses of an entity's posts (a brief a sense) ---------------------------------------------------
#
# One entity can hold several things of one name (merged by a name rule before any sense was known, or a key whose
# senses were never split). Where identity already made sense entities (0184 entity_facts: a split's entities, their
# mentions pinned), each sense is its own entity with its own brief and the page links the others (`senses` of
# entity_facts.read): nothing here. Else the brief asks identity's own sense question, the collide kind under its
# guide collide-v2 (0184: one sense one exact thing, what each is, its kind and the maker a post states), over the
# brief's report posts (one mention a post, the shown sample's format: identity.collide_input), a=b=the root (b set:
# identity's collision reads, which read b IS NULL, never take it as theirs). Settled when SENSE_RUNS runs group the
# mentions alike (asked again up to SENSE_ASKS runs); a settled answer with 2+ named senses (generic and unclear
# mentions are in none) gives the brief one part a sense.

SENSE_SWITCH = ("entities", "brief_senses")
SENSE_GUIDE = "collide-v2"
SENSE_RUNS = 2
SENSE_ASKS = 3


def senses_on() -> bool:
    """entity_bands.json `entities.brief_senses` (default off)."""
    from insight_core.markx import identity
    return bool((identity.bands().get(SENSE_SWITCH[0]) or {}).get(SENSE_SWITCH[1]))


def _mentions(cur: Any, book: Any, root: str, posts: Sequence[str]) -> List[Tuple[str, str, Any, Any, Any]]:
    """One mention of the entity a post (post, span, type, maker, at), in the posts' order: its first subject/actor
    mention, else its first."""
    from insight_core.markx import entity_views as EV
    if not posts:
        return []
    members = EV._members(book, root)
    cur.execute("""SELECT m.post_id::text, m.n, m.span, m.type, m.maker, m.role, m.entity_id::text, m.guide
                     FROM mx_mentions_now m
                    WHERE m.guide = ANY(%s) AND m.post_id = ANY(%s::uuid[]) AND m.entity_id IS NOT NULL
                    ORDER BY m.post_id, m.n""", (EV._guide(), list(posts)))
    best: Dict[str, Tuple] = {}
    for pid, n, span, typ, maker, role, eid, g in cur.fetchall():
        if book.root(book.pins.get((pid, g, n), eid)) != root or (eid not in members and (pid, g, n) not in book.pins):
            continue
        rank = 0 if role in EV.ROLE_REPORT else 1
        if pid not in best or rank < best[pid][0]:
            best[pid] = (rank, span, typ, maker)
    return [(p, best[p][1], best[p][2], best[p][3], None) for p in posts if p in best]


def sense_input(cur: Any, book: Any, root: str, posts: Sequence[str]) -> Optional[str]:
    """The sense question's input over the brief's posts (the known senses, then one numbered mention a post), or
    None (under two posts)."""
    from insight_core.markx import entity_facts, identity as I, tasks
    loaded = tasks.load_posts(cur, list(posts))
    pick = [m for m in _mentions(cur, book, root, posts) if m[0] in loaded]
    if len(pick) < 2:
        return None
    return entity_facts.known_block(cur, root) + I.collide_input(book.ents[root], len(posts), pick, loaded)


def _partners(ans: Dict[str, Any]) -> Dict[int, Tuple[frozenset, Dict[str, Any]]]:
    """{mention: (the mentions of its sense, that sense)} of one run (unclear mentions in none)."""
    out = {}
    for s in ans.get("senses") or []:
        ms = frozenset(int(x) for x in s.get("m") or [] if str(x).isdigit())
        for x in ms:
            out[x] = (ms, s)
    return out


def settled(calls: Sequence[Tuple[str, Dict[str, Any]]]) -> Optional[Dict[str, Any]]:
    """The settled senses of the first SENSE_ASKS runs, {senses: [...], unclear: [...]}, else None (under SENSE_RUNS
    runs). The two-run agreement read per mention: a mention is settled when SENSE_RUNS runs put it with the same
    mentions; while some are not, the fewest mentions are left out (unclear) for the rest to settle (one run's
    stray mention never unsettles the others). Each settled group keeps the first run's what, kind and maker."""
    runs = [_partners(a) for _c, a in list(calls)[:SENSE_ASKS]]
    if len(runs) < SENSE_RUNS:
        return None
    nodes = sorted(set().union(*runs))

    def unsettled(drop: Set[int]) -> List[int]:
        out = []
        for x in nodes:
            if x in drop:
                continue
            sets = Counter(r[x][0] - drop for r in runs if x in r)
            if not sets or sets.most_common(1)[0][1] < SENSE_RUNS:
                out.append(x)
        return out
    drop: Set[int] = set()
    bad = unsettled(drop)
    while bad:   # leave out the one mention whose absence settles the most others (ties: the lowest number)
        x = min(bad, key=lambda b: (len(unsettled(drop | {b})), b))
        drop.add(x)
        bad = unsettled(drop)
    groups: Dict[frozenset, Dict[str, Any]] = {}
    for x in nodes:
        if x in drop:
            continue
        g = Counter(r[x][0] - drop for r in runs if x in r).most_common(1)[0][0]
        if g not in groups:
            first = next(r[x][1] for r in runs if x in r and r[x][0] - drop == g)
            groups[g] = dict(first, m=sorted(g))
    return {"senses": sorted(groups.values(), key=lambda s: s["m"]), "unclear": sorted(drop)}


def _task(cur: Any, root: str) -> Optional[Tuple[str, str, str]]:
    cur.execute("""SELECT id::text, status, input FROM mx_tasks WHERE kind = 'collide' AND guide = %s AND a = %s
                      AND b = %s ORDER BY created_at DESC, id LIMIT 1""", (SENSE_GUIDE, root, root))
    row = cur.fetchone()
    return tuple(row) if row else None


def senses(cur: Any, root: str) -> Optional[List[Dict[str, Any]]]:
    """The senses of the entity's brief posts, from the newest settled sense question: [{label, kind, maker, posts}]
    (2+ named senses, the largest first), else None (off; identity's sense entities hold them; one sense; unsettled)."""
    from insight_core.markx import entity_facts, entity_views as EV, identity as I
    if not senses_on():
        return None
    f = entity_facts.read(cur, [root], senses=True).get(root)
    if f is not None and f.senses:
        return None   # identity's sense entities: each its own entity, brief and page
    t = _task(cur, root)
    if t is None:
        return None
    ans = settled(I.valid_answers(cur, [t[0]]).get(t[0]) or [])
    if ans is None:
        return None
    book = I.lazy_book(cur)
    found = I.match_pick(cur, EV._guide(), root, t[2] or "", members=EV._members(book, root))
    spans = {r["n"]: r["span"] for r in I._sample_rows(t[2] or "")}   # how each mention wrote the name
    out = []
    for s in ans.get("senses") or []:
        if s.get("generic"):
            continue
        ps = sorted({pid for x in s.get("m") or [] if str(x).isdigit() for pid, _n in found.get(int(x), [])})
        if ps:
            out.append({"label": s.get("what") or None, "kind": s.get("kind"), "maker": s.get("maker") or None,
                        "posts": ps, "names": sorted({spans[int(x)] for x in s.get("m") or []
                                                      if str(x).isdigit() and int(x) in spans})})
    if len(out) < 2:
        return None
    return sorted(out, key=lambda s: (-len(s["posts"]), s["posts"][0]))


def plan_senses(cur: Any, book: Any, worth: Sequence[Tuple[str, List[str]]]) -> int:
    """The sense question of each entity worth a brief whose posts changed since it was asked (a new input), asked
    again while unsettled (up to SENSE_ASKS runs). How many were added or reopened."""
    from insight_core.markx import identity as I, repo, schemas
    if not senses_on():
        return 0
    n = 0
    for root, posts in worth:
        text = sense_input(cur, book, root, posts)
        if text is None:
            continue
        tid, new = repo.add_task(cur, kind="collide", guide=SENSE_GUIDE, subject_kind=schemas.KINDS["collide"].subject,
                                 input=text, a=root, b=root)
        if new:
            n += 1
            continue
        calls = I.valid_answers(cur, [str(tid)]).get(str(tid)) or []
        got = settled(calls)
        if calls and len(calls) < SENSE_ASKS and (got is None or got["unclear"]):   # 2 runs disagree: a third
            cur.execute("""UPDATE mx_tasks SET status = 'open', lease_until = NULL, leased_by = NULL
                            WHERE id = %s AND status = 'answered'""", (tid,))
            n += cur.rowcount
    return n



def stamp(cur: Any, root: str) -> List[Any]:
    """What the brief reads that changes it (the entity page's kept-page inputs): its reports and its brief asks."""
    cur.execute("""SELECT (SELECT json_build_array(count(*), max(r.created_at)) FROM mx_track_thing_reports r
                             JOIN mx_track_things t ON t.id = r.thing_id WHERE t.track_id = %s),
                          (SELECT json_build_array(count(*), max(c.created_at)) FROM mx_track_brief_asks a
                             JOIN mx_calls c ON c.task_id = a.task_id AND c.valid WHERE a.track_id = %s),
                          (SELECT json_build_array(count(*), max(updated_at)) FROM mx_track_things
                            WHERE track_id = %s),
                          (SELECT json_build_array(count(*), max(c.created_at)) FROM mx_tasks t
                             JOIN mx_calls c ON c.task_id = t.id AND c.valid
                            WHERE t.kind = 'collide' AND t.guide = %s AND t.a = %s AND t.b = %s)""",
                (root, root, root, SENSE_GUIDE, root, root))
    return list(cur.fetchone()) + [on(), numbers_on(), senses_on()]   # 0274: the sense answers
