"""A track's things (issue 0245, the general track briefer; built: 0249, Stealth v10.27).

One briefer for every track: the track's name, description and excludes are its only track-specific input. Nothing
here names a track, a kind or a field; every rule is about types (text, number, money, link, enum).

This module owns a track's **schema** (its kinds of thing and their fields), its **things** (one row a thing, however
many posts report it), each post's **report** of a thing (the values with their quotes) and the **joins** of two
reports or two rows into one thing. markx/track_brief.py reads them for the weekly issue, the quick look and the tables.

**The schema** (`plan_schemas`, kind `track_schema`, guide track-schema-v1, one question a track and description):
Haiku proposes 1-3 kinds from the description, each with up to 8 typed fields; code always adds the general kind
PRACTICE ("practice or claim": what, result, evidence). Stored with the track, one row a version (mx_track_schemas);
a description change (the track's version) proposes again; the owner may replace it (`set_schema`, PUT .../schema),
a version of its own. A new schema version re-reads every post in the track (its questions name the version).

**The things** (`plan_things`, kind `track_things`, guide track-things-v1): asked only for the posts in the track
(judged in, joined, or the owner's ✓: track_subtopics.in_track), newest first. A long post is read in windows
(tasks.text_windows, WINDOW_CHARS each, MAX_WINDOWS at most; its links listed in each), merged per post (the reports
of one post join by any key, a practice by its exact `what`). The post's own address is never offered: its links
leave it out and its text shows it as OWN. Haiku answers each value as {value, quote}; numbers and money come typed
({number, unit, currency, range_to}). Code checks every value (`salvage`, before the answer is stored, the worker too):
  - the quote is in what the question showed (the window's text or its links);
  - number / money: the digits of `number` (and `range_to`) are a figure of the quote (thousands groups, a decimal
    comma or point, a K/M/B-like multiplier after it), the unit (when given) and the currency are shown by the quote;
  - link: an http(s) URL inside its own quote; enum: one of the field's values; text: at most TEXT_CAP characters;
  - a thing whose first field (its name; a practice's `what`) is not kept is not a thing.
A value that fails is dropped with its reason, kept on the call (the answer's "dropped"); the rest of the answer stays.

**The maker's linked pages** (0257, `maker_pages`, behind entity_bands.json `tracks.linked_docs`, default on): terse
release notes link the maker's own page that explains them. A post's questions are then followed by one question a
page (LINKED_DOCS at most, within MAX_WINDOWS): the post's first LINKED_POST_CHARS with its links, then the page's
address, title and WINDOW_CHARS of its text (from the words the link's anchor names). The pages are the post's links
(post_refs) on its own site (`maker_page`: its registrable domain; on a platform or code host its account) that INSIGHT
stores (a post at that address); nothing is fetched here. A quote may come from the page (the same checks: it is in
what the question showed); a value quoted only from it names it (`page`, kept in the report's values and the row).

**Joins** (never by vector similarity): a report joins a current thing of its kind that shares a key value (the
schema's key fields and every link field, normalised: a name, a link, a repo); a practice joins only within its own
post. In the jobs process (`refresh`), two things of one kind whose key value names the same entity (the posts'
current mentions, through identity's redirects and pins) become one; two practices whose quotes name a shared entity
are asked once (`plan_same`, kind `track_same`, guide track-same-v1, "same claim?"), and joined on `same`. A join is a
status (`merged`, `merged_into`, `merged_by`), never a delete; a thing's reports are its own and its merged things'.

Behind entity_bands.json `tracks.briefs` (`on`, default off until measured: 0249): while off nothing is planned or
built and the tables stay empty. Only mx_* tables are written.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

log = logging.getLogger(__name__)

SCHEMA_KIND, SCHEMA_GUIDE = "track_schema", "track-schema-v1"
THINGS_KIND, THINGS_GUIDE = "track_things", "track-things-v1"
SAME_KIND, SAME_GUIDE = "track_same", "track-same-v1"
PRACTICE_KIND = "practice_or_claim"
PRACTICE = {"kind": PRACTICE_KIND, "about": "a method, habit, finding or opinion a post states",
            "fields": [{"name": "what", "type": "text", "key": True, "about": "the method or claim, in a few words"},
                       {"name": "result", "type": "text", "key": False, "about": "what it gave or what is claimed"},
                       {"name": "evidence", "type": "text", "key": False, "about": "numbers, test or example given"}]}
TEXT_CAP = 120          # characters of a text value at most
WINDOW_CHARS = 3500     # characters of a post one question shows (round 2's window)
MAX_WINDOWS = 6         # windows a long post is read in at most
LINKS_MAX = 25          # links a question lists
THINGS_OPEN = 60        # things questions a track has waiting at most
SAME_OPEN = 30          # same-claim questions waiting at most, across tracks
OWN = "[this post's own address]"
SWITCH = ("tracks", "briefs")
LINKED_SWITCH = "linked_docs"   # entity_bands.json tracks.linked_docs (0257, default on)
LINKED_DOCS = 2         # the maker's pages a post's questions show at most (0257), within MAX_WINDOWS
LINKED_POST_CHARS = 1500  # characters of the post a linked page's question shows with the page (its first)
LINKED_LEAD = 200       # characters of the page shown before the part a link's anchor names
PAGE_MARK = "\nLinked page on the post's own site: "


# ---- the switch ---------------------------------------------------------------------------------------------

def on() -> bool:
    """entity_bands.json `tracks.briefs`: the briefer plans, joins and builds (default off)."""
    from insight_core.markx import identity
    return bool((identity.bands().get(SWITCH[0]) or {}).get(SWITCH[1]))


def linked_on() -> bool:
    """entity_bands.json `tracks.linked_docs` (0257): a post's questions also show the stored pages it links on its
    own site (default on: the post's own questions are unchanged, these are added)."""
    from insight_core.markx import identity
    return bool((identity.bands().get(SWITCH[0]) or {}).get(LINKED_SWITCH, True))


# ---- folding and typed values (pure: the worker runs these checks too) --------------------------------------

def fold(s: Any) -> str:
    from insight_core.markx import validate
    return validate.fold(str(s or "")).strip()


UI_FRAGMENTS = frozenset({"", "m", "top", "main", "content", "comments", "respond", "more"})


def norm_url(u: Any) -> str:
    """A URL as two are compared: folded, no scheme, no www., no trailing slash or punctuation; its fragment kept when
    it names an item of the page (v10.29: "releases#2026111800" is one release of a page listing many), dropped when
    it is the page's own furniture ("#m", "#comments", a text fragment ":~:")."""
    s = fold(u).rstrip(").,;'\"")
    s = re.sub(r"^https?://(www\.)?", "", s)
    page, _, frag = s.partition("#")
    page = page.rstrip("/")
    return f"{page}#{frag}" if frag not in UI_FRAGMENTS and not frag.startswith(":~:") else page


def key_text(v: Any) -> str:
    """A text key as two are compared (tasks.name_key: case, dashes, separators, letters glued to digits)."""
    from insight_core.markx.tasks import name_key
    return name_key(str(v or ""))


_FIG = re.compile(r"\d+(?:[ \u00a0\u202f'.,]\d+)*")
# a letter multiplier stands alone ("16K", not "5km"); a word one may go on ("thousands", "тысячи")
_MULT = re.compile(r"\s?(?:(k|к|m|м|mn|b|bn)(?![a-zа-яё])|(thousand|тыс|million|млн|billion|млрд))", re.I)
_MULTS = {"k": 1e3, "к": 1e3, "thousand": 1e3, "тыс": 1e3, "m": 1e6, "м": 1e6, "mn": 1e6, "million": 1e6, "млн": 1e6,
          "b": 1e9, "bn": 1e9, "billion": 1e9, "млрд": 1e9}


def figures(quote: str) -> Set[float]:
    """Every value a figure of `quote` can be read as: its parts, its thousands grouping ("1,500", "1 500"), its
    decimal ("24,5", "4.5"), each times a multiplier written right after it ("16K", "1.2M", "27B")."""
    out: Set[float] = set()
    for m in _FIG.finditer(quote or ""):
        tok = m.group(0)
        parts = re.split(r"[ \u00a0\u202f'.,]", tok)
        seps = re.findall(r"[ \u00a0\u202f'.,]", tok)
        vals = {float(p) for p in parts if p}
        if len(parts) > 1 and all(len(p) == 3 for p in parts[1:]):
            vals.add(float("".join(parts)))                       # a thousands grouping
        if len(parts) > 1 and seps[-1] in ".," and (len(parts) == 2 or all(len(p) == 3 for p in parts[1:-1])):
            vals.add(float("".join(parts[:-1]) + "." + parts[-1]))   # a decimal, its whole part maybe grouped
        mult = _MULT.match(quote, m.end())
        if mult:
            k = _MULTS[(mult.group(1) or mult.group(2)).lower()]
            vals |= {v * k for v in vals}
        out |= vals
    return out


def _same_number(a: float, vals: Iterable[float]) -> bool:
    return any(abs(a - v) <= 1e-9 * max(1.0, abs(a)) for v in vals)


# A currency as a quote shows it: its code, or a sign or word of it (dollar signs for every dollar). General: about
# currencies, never about a track.
_CURRENCY = {"USD": ("$", "dollar", "долл", "бакс"), "EUR": ("€", "euro", "евро"), "GBP": ("£", "pound", "фунт"),
             "RUB": ("₽", "руб", "рубл", "rouble", "ruble"), "JPY": ("¥", "yen", "円", "иен"),
             "CNY": ("¥", "rmb", "yuan", "元", "юан"), "INR": ("₹", "rupee", "рупи"), "KRW": ("₩", "won"),
             "UAH": ("₴", "грн", "гривн"), "CHF": ("franc",), "TRY": ("₺", "lira"), "BRL": ("r$", "real"),
             "PLN": ("zł", "złot", "zlot"), "CAD": ("$",), "AUD": ("$",), "NZD": ("$",), "HKD": ("$",),
             "SGD": ("$",), "MXN": ("$",), "KZT": ("₸", "тенге"), "BTC": ("₿", "bitcoin")}


def currency_shown(code: str, quote: str) -> bool:
    q = fold(quote)
    code = (code or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        return False
    return code.casefold() in q or any(fold(s) in q for s in _CURRENCY.get(code, ()))


def unit_shown(unit: str, quote: str) -> bool:
    """The unit as the quote writes it: whole, or its first word's first three letters ("tokens/s" in "tok/s")."""
    u, q = fold(unit), fold(quote)
    if not u or u in q:
        return True
    word = re.match(r"[^\W\d_]+", u)
    return bool(word) and word.group(0)[:3] in q


def check_value(field: Dict[str, Any], raw: Any, shown: str) -> Tuple[Any, Optional[str]]:
    """(the typed value, None) or (None, why it is dropped): one field's {value, quote} against what the question
    showed (`shown`, the window's text and links)."""
    if not isinstance(raw, dict) or "value" not in raw:
        return None, "not {value, quote}"
    value, quote = raw.get("value"), raw.get("quote")
    if not isinstance(quote, str) or not quote.strip():
        return None, "no quote"
    if fold(quote) not in fold(shown):
        return None, "quote not in the post"
    t = field.get("type")
    if t in ("number", "money"):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = {"number": value}
        if not isinstance(value, dict) or not isinstance(value.get("number"), (int, float)) \
                or isinstance(value.get("number"), bool):
            return None, f"{t} not typed"
        figs = figures(quote)
        num = float(value["number"])
        if not _same_number(num, figs):
            return None, "number not in its quote"
        to = value.get("range_to")
        if to is not None:
            if not isinstance(to, (int, float)) or isinstance(to, bool) or not _same_number(float(to), figs):
                return None, "range_to not in its quote"
            if float(to) < num:
                return None, "range_to below number"
        out: Dict[str, Any] = {"number": num, "range_to": None if to is None else float(to)}
        if t == "money":
            cur_ = str(value.get("currency") or "").strip().upper()
            if not currency_shown(cur_, quote):
                return None, "currency not in its quote"
            out["currency"] = cur_
        else:
            unit = value.get("unit")
            unit = unit.strip() if isinstance(unit, str) and unit.strip() else None
            if unit and not unit_shown(unit, quote):
                return None, "unit not in its quote"
            out["unit"] = unit
        return out, None
    if not isinstance(value, str) or not value.strip():
        return None, f"{t}: not a string"
    value = re.sub(r"\s+", " ", value).strip()
    if t == "link":
        if not re.match(r"^https?://\S+$", value):
            return None, "link: not an http(s) URL"
        if norm_url(value) not in norm_url(quote) and norm_url(value) not in fold(quote):
            return None, "link not in its quote"
        return value, None
    if t == "enum":
        allowed = {fold(v): v for v in field.get("values") or []}
        if fold(value) not in allowed:
            return None, "enum value not allowed"
        return allowed[fold(value)], None
    if len(value) > TEXT_CAP:
        return None, f"text over {TEXT_CAP} characters"
    return value, None


_RAW_GITHUB = re.compile(r"^https?://raw\.githubusercontent\.com/([^/\s]+)/([^/\s]+)/([^/\s]+)(/[^\s]*)?$", re.I)
_GITHUB = re.compile(r"^(https?://(?:www\.)?github\.com/[^/\s]+/[^/\s#?]+?)(?:\.git)?(?:/raw(/[^\s]*))?/?$", re.I)


def reader_link(u: str) -> str:
    """A link as a reader opens it (v10.29): a raw file on GitHub as its page in the repo (raw.githubusercontent.com
    /o/r/<ref>/<path> and github.com/o/r/raw/<ref>/<path> -> github.com/o/r/blob/<ref>/<path>), a clone address
    (.git) as the repo. The stored value is kept as the post gave it."""
    m = _RAW_GITHUB.match(u or "")
    if m:
        o, r, ref, path = m.groups()
        return f"https://github.com/{o}/{r}" + (f"/blob/{ref}{path}" if path and path != "/" else "")
    m = _GITHUB.match(u or "")
    if m:
        return m.group(1) + (f"/blob{m.group(2)}" if m.group(2) else "")
    return u


def shown_value(field: Dict[str, Any], v: Any) -> str:
    """A typed value in words ("14-15 tok/s", "1,500 USD"; a number with no unit of its own takes its field's unit;
    a link as a reader opens it)."""
    if isinstance(v, dict) and "number" in v:
        def n(x: float) -> str:
            return f"{x:,.0f}" if float(x).is_integer() else f"{x:,}"
        s = n(v["number"]) + (f"-{n(v['range_to'])}" if v.get("range_to") is not None else "")
        tail = v.get("currency") if field.get("type") == "money" else (v.get("unit") or field.get("unit"))
        return f"{s} {tail}" if tail else s
    if field.get("type") == "link" and isinstance(v, str):
        return reader_link(v)
    return str(v)


# ---- the question's input ------------------------------------------------------------------------------------

_HEAD = re.compile(r"^SCHEMA: (\S+) v(\d+)$", re.M)
_KINDS = re.compile(r"^KINDS: (.+)$", re.M)


def header(track: Dict[str, Any]) -> List[str]:
    return [f"TRACK: {track['name']}", f"Belongs: {track.get('description') or ''}",
            f"Excludes: {track.get('excludes') or '(none)'}"]


def parse_input(input: str) -> Tuple[Optional[str], Optional[int], Dict[str, Dict[str, Any]], str]:
    """(track id, schema version, {kind: its definition}, what the question showed of the post) of a things input."""
    m = _HEAD.search(input or "")
    k = _KINDS.search(input or "")
    kinds: Dict[str, Dict[str, Any]] = {}
    if k:
        try:
            kinds = {x["kind"]: x for x in json.loads(k.group(1)).get("kinds") or []}
        except (ValueError, TypeError, KeyError, AttributeError):
            kinds = {}
    shown = (input or "").split("\nPOST\n", 1)[1] if "\nPOST\n" in (input or "") else ""
    return (m.group(1) if m else None), (int(m.group(2)) if m else None), kinds, shown


def linked_page(shown: str) -> Tuple[Optional[str], str]:
    """(the linked page a question shows, 0257, or None; what it showed of the post itself)."""
    if PAGE_MARK not in shown:
        return None, shown
    of_post, _, rest = shown.partition(PAGE_MARK)
    return rest.split("\n", 1)[0].strip() or None, of_post


def salvage(answer: Dict[str, Any], input: str) -> Dict[str, Any]:
    """The things answer checked value by value: each kept value typed, each dropped one (and each thing whose name
    did not stand, of an unknown kind, or past THINGS_PER_ANSWER) under "dropped" with why; a value quoted only from
    the linked page a question shows (0257) names it (`page`). Idempotent (a kept value
    passes again: the worker salvages before it posts, the server again)."""
    from insight_core.markx import schemas, validate
    things = answer.get("things")
    if not isinstance(things, list):
        return answer
    _tid, _v, kinds, shown = parse_input(input)
    page, of_post = linked_page(shown)
    dropped = list(answer.get(validate.DROPPED) or [])
    before = len(dropped)
    kept = []
    for n, th in enumerate(things):
        if not isinstance(th, dict) or not isinstance(th.get("fields"), dict):
            dropped.append({"list": "things", "item": th, "why": f"things[{n}]: not {{kind, fields}}"})
            continue
        kind = kinds.get(th.get("kind"))
        if kind is None:
            dropped.append({"list": "things", "item": th, "why": f"things[{n}]: kind {th.get('kind')!r} not asked"})
            continue
        defs = {f["name"]: f for f in kind["fields"]}
        good: Dict[str, Any] = {}
        for name, raw in th["fields"].items():
            f = defs.get(name)
            typed, why = (None, "no such field") if f is None else check_value(f, raw, shown)
            if why:
                dropped.append({"list": "values", "item": {"kind": kind["kind"], "field": name, "value": raw},
                                "why": f"things[{n}].{name}: {why}"})
            else:
                good[name] = {"value": typed, "quote": raw["quote"]}
                if page and fold(raw["quote"]) not in fold(of_post):   # 0257: quoted from the linked page only
                    good[name]["page"] = page
        first = kind["fields"][0]["name"]
        if first not in good:
            dropped.append({"list": "things", "item": th, "why": f"things[{n}]: its {first} did not stand"})
            continue
        if len(kept) >= schemas.THINGS_PER_ANSWER:
            dropped.append({"list": "things", "item": th, "why": f"things[{n}]: past {schemas.THINGS_PER_ANSWER}"})
            continue
        kept.append({"kind": kind["kind"], "fields": good})
    out = dict(answer, things=kept)
    if len(dropped) > before:
        out[validate.DROPPED] = dropped
    return out


def schema_error(answer: Dict[str, Any]) -> Optional[str]:
    """A schema answer (or the owner's edit) past its JSON schema: kinds and fields named once, the first field a text
    key, an enum with its values, at most two key fields, no kind named as the general one."""
    from insight_core.markx import schemas
    seen: Set[str] = set()
    for k in answer.get("kinds") or []:
        if k["kind"] == PRACTICE_KIND:
            return f"{PRACTICE_KIND} is added by code"
        if k["kind"] in seen:
            return f"kind {k['kind']} twice"
        seen.add(k["kind"])
        names: Set[str] = set()
        for f in k["fields"]:
            if f["name"] in names:
                return f"{k['kind']}.{f['name']} twice"
            names.add(f["name"])
            if f["type"] == "enum" and len(f.get("values") or []) < schemas.THING_ENUM[0]:
                return f"{k['kind']}.{f['name']}: an enum needs {schemas.THING_ENUM[0]}+ values"
        first = k["fields"][0]
        if first["type"] != "text" or first.get("key") is False:
            return f"{k['kind']}: its first field is its name (text, key)"
        if sum(1 for f in k["fields"] if f.get("key")) > 2:
            return f"{k['kind']}: at most two key fields"
    return None


def with_practice(answer: Dict[str, Any]) -> Dict[str, Any]:
    """The stored schema: the kinds as given (the first field always a key) and PRACTICE last."""
    kinds = []
    for k in answer.get("kinds") or []:
        fields = [dict(f, key=bool(f.get("key")) or i == 0) for i, f in enumerate(k["fields"])]
        kinds.append({"kind": k["kind"], "about": k.get("about") or "", "fields": fields})
    return {"kinds": kinds + [PRACTICE]}


# ---- the schema (stored with the track) ----------------------------------------------------------------------

def current_schema(cur: Any, folder_id: Any) -> Optional[Dict[str, Any]]:
    """The track's newest schema: {version, schema, by, track_version, created_at}, or None."""
    cur.execute("""SELECT version, schema, by, track_version, created_at FROM mx_track_schemas WHERE track_id = %s
                    ORDER BY version DESC LIMIT 1""", (str(folder_id),))
    r = cur.fetchone()
    return None if r is None else dict(zip(("version", "schema", "by", "track_version", "created_at"), r))


def schema_at(cur: Any, folder_id: Any, version: int) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT schema FROM mx_track_schemas WHERE track_id = %s AND version = %s", (str(folder_id), version))
    r = cur.fetchone()
    return r[0] if r else None


def _put_schema(cur: Any, folder_id: str, schema: Dict[str, Any], *, by: str, track_version: int,
                task_id: Any = None) -> int:
    cur.execute("""INSERT INTO mx_track_schemas (track_id, version, schema, by, track_version, task_id)
                   SELECT %s, COALESCE(max(version), 0) + 1, %s::jsonb, %s, %s, %s FROM mx_track_schemas
                    WHERE track_id = %s RETURNING version""",
                (folder_id, json.dumps(schema), by, track_version, task_id, folder_id))
    return cur.fetchone()[0]


def schema_input(track: Dict[str, Any]) -> str:
    return "\n".join(header(track))


def plan_schemas(cur: Any, **_kw: Any) -> int:
    """A `track_schema` question for each topic track with no schema for its description's version (an answered one
    for the same words applied at once): how many were added."""
    from insight_core.markx import repo, schemas, tracks
    if not on():
        return 0
    schemas.ensure_guides(cur)
    added = 0
    for t in tracks.described(cur):
        have = current_schema(cur, t["folder_id"])
        if have is not None and have["track_version"] >= t["version"]:
            continue
        task_id, new = repo.add_task(cur, kind=SCHEMA_KIND, guide=SCHEMA_GUIDE, subject_kind="track",
                                     input=schema_input(t), a=t["folder_id"])
        added += new
        if not new:
            got = _valid_answer(cur, task_id)
            if got is not None:
                apply_schema(cur, repo.get_task(cur, task_id), got)
    return added


def _valid_answer(cur: Any, task_id: Any) -> Optional[Dict[str, Any]]:
    cur.execute("SELECT answer FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at DESC LIMIT 1", (task_id,))
    r = cur.fetchone()
    return r[0] if r else None


def apply_schema(cur: Any, task: Dict[str, Any], answer: Dict[str, Any]) -> Optional[int]:
    """A schema answer stored as the track's new version, when its description is still the one asked and the track
    has no schema for that version yet: the version, or None."""
    from insight_core.markx import tracks
    t = tracks.get(cur, task["a"])
    if not tracks.is_topic(t) or schema_input(t) != task.get("input"):
        return None
    have = current_schema(cur, t["folder_id"])
    if have is not None and have["track_version"] >= t["version"]:
        return None
    return _put_schema(cur, t["folder_id"], with_practice(answer), by="haiku", track_version=t["version"],
                       task_id=task["id"])


def set_schema(cur: Any, folder_id: Any, kinds: Any) -> Dict[str, Any]:
    """The owner's schema (PUT .../schema {kinds}: PRACTICE is added by code) stored as a new version: the schema view.
    ValueError: not a valid schema; KeyError: not a topic track."""
    from insight_core.markx import schemas, tracks, validate
    t = tracks.get(cur, folder_id)
    if not tracks.is_topic(t):
        raise KeyError(folder_id)
    answer = {"kinds": [k for k in kinds or [] if not (isinstance(k, dict) and k.get("kind") == PRACTICE_KIND)]}
    err = validate.schema_error(schemas.TRACK_SCHEMA_SCHEMA, answer) or schema_error(answer)
    if err:
        raise ValueError(err)
    _put_schema(cur, t["folder_id"], with_practice(answer), by="owner", track_version=t["version"])
    return schema_view(cur, folder_id)


def schema_view(cur: Any, folder_id: Any) -> Dict[str, Any]:
    """GET .../schema: {on, version, by, track_version, stale (proposed for an older description), schema}.
    KeyError: not a topic track."""
    from insight_core.markx import tracks
    t = tracks.get(cur, folder_id)
    if not tracks.is_topic(t):
        raise KeyError(folder_id)
    s = current_schema(cur, folder_id)
    if s is None:
        return {"on": on(), "version": None, "by": None, "track_version": None, "stale": False, "schema": None}
    return {"on": on(), "version": s["version"], "by": s["by"], "track_version": s["track_version"],
            "stale": s["track_version"] < t["version"], "at": s["created_at"].isoformat(), "schema": s["schema"]}


# ---- the things questions -----------------------------------------------------------------------------------

def _own(cur: Any, ids: Sequence[str]) -> Dict[str, List[str]]:
    cur.execute("SELECT id::text, url, normalized_url FROM posts WHERE id = ANY(%s::uuid[])", (list(ids),))
    return {i: [u for u in (a, b) if u] for i, a, b in cur.fetchall()}


def post_links(p: Any, own: Sequence[str]) -> List[str]:
    """The post's external links (its kept links, then URLs in its text), its own address never among them."""
    mine = {norm_url(u) for u in own}
    found = [u for u, _a in p.links] + re.findall(r"https?://[^\s<>\"')\]]+", p.text or "")
    out, seen = [], set()
    for u in found:
        u = u.rstrip(").,;")
        n = norm_url(u)
        if u.startswith("http") and n and n not in mine and n not in seen:
            seen.add(n)
            out.append(u)
    return out[:LINKS_MAX]


def _without_own(text: str, own: Sequence[str]) -> str:
    for u in sorted({x for x in own if x}, key=len, reverse=True):
        text = text.replace(u, OWN)
    return text


def maker_page(own: str, link: str) -> bool:
    """0257: `link` is a page of the post's maker: on the registrable site of the post's own address (addresses.site_of),
    and, on a site of accounts (a platform's, addresses.PLATFORM_SITES; a code host, rename.CODE_HOSTS), under the
    same account (addresses.account_key): a release on a code host linking its own repo's docs, not another's."""
    from insight_core.markx.rename import CODE_HOSTS
    from insight_core.utils.addresses import PLATFORM_SITES, account_key, host_of, site_of
    a, b = site_of(host_of(own)), site_of(host_of(link))
    if not a or a != b:
        return False
    if a in CODE_HOSTS or any(a in sites for sites in PLATFORM_SITES.values()):
        return account_key(own) == account_key(link)
    return True


def maker_pages(cur: Any, posts: Dict[str, Any], own: Dict[str, List[str]]) -> Dict[str, List[Tuple[str, Any]]]:
    """0257: {post id: [(the link as the post gives it, the stored page)]}, LINKED_DOCS at most a post, in the post's
    order: the pages a post links (post_refs: every link of its text, its own site's too, which post_links leaves out)
    that are its maker's (`maker_page`) and stored (a post at that address: posts.normalized_url, as Connected's
    Earlier reads them), never the post itself. Read only; nothing is fetched here."""
    from insight_core.markx import tasks
    ids = [i for i in posts if own.get(i)]
    if not ids:
        return {}
    cur.execute("""SELECT r.post_id::text, r.href, sp.id::text
                     FROM post_refs r
                     JOIN LATERAL (SELECT p.id FROM posts p WHERE p.normalized_url = r.target_address
                                      AND p.id <> r.post_id ORDER BY p.fetched_at DESC NULLS LAST, p.id LIMIT 1) sp ON true
                    WHERE r.post_id = ANY(%s::uuid[]) AND r.valid_to IS NULL AND NOT r.boilerplate
                    ORDER BY r.post_id, r.position""", (ids,))
    want: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for pid, href, page in cur.fetchall():
        mine = {norm_url(u) for u in own[pid]}
        got = want[pid]
        if (len(got) < LINKED_DOCS and norm_url(href) not in mine and maker_page(own[pid][0], href)
                and page not in {g for _h, g in got}):
            got.append((href, page))
    if not want:
        return {}
    loaded = tasks.load_posts(cur, {g for got in want.values() for _h, g in got}, linked=False)
    return {pid: [(h, loaded[g]) for h, g in got if g in loaded and loaded[g].text] for pid, got in want.items()}


def page_window(text: str, link: str) -> Tuple[int, int]:
    """The part of a linked page a question shows (WINDOW_CHARS): from LINKED_LEAD before the words its link's anchor
    names ("#network-toggle": "network toggle"), else from its start."""
    from urllib.parse import unquote, urlsplit
    try:
        frag = unquote(urlsplit(link).fragment)
    except ValueError:
        frag = ""
    words = [w for w in re.split(r"[\W_]+", frag) if w]
    start = 0
    if words and fold(frag) not in UI_FRAGMENTS and not frag.startswith(":~:"):
        m = re.search(r"\W+".join(re.escape(w) for w in words), text, re.I)
        start = max(0, m.start() - LINKED_LEAD) if m else 0
    return start, min(len(text), start + WINDOW_CHARS)


def things_inputs(track: Dict[str, Any], schema: Dict[str, Any], version: int, p: Any, own: Sequence[str],
                  pages: Sequence[Tuple[str, Any]] = ()) -> List[str]:
    """A post's things questions, one a window: the schema's version line, the track, its kinds (JSON, one line), the
    post (title, which window, text) and its links. 0257: then one question a page of `pages` (maker_pages), while the
    windows stay within MAX_WINDOWS: the post's first LINKED_POST_CHARS and links, then the page (its address, title
    and its window, page_window), so a value may be quoted from the maker's page. The post's own questions are the
    same with or without pages."""
    from insight_core.markx import tasks
    text = _without_own(p.text or "", own)
    windows = tasks.text_windows(text, WINDOW_CHARS, MAX_WINDOWS)
    links = post_links(p, own)
    head = ([f"SCHEMA: {track['folder_id']} v{version}"] + header(track)
            + ["KINDS: " + json.dumps(schema, ensure_ascii=False, separators=(",", ":")), "", "POST",
               f"Title: {_without_own(p.title or '', own)}"])
    link_lines = (["Links in the post:"] + links) if links else []
    out = []
    for w, (start, end) in enumerate(windows):
        lines = list(head)
        if len(windows) > 1:
            lines.append(f"Window: {w + 1} of {len(windows)} of the post's text (characters {start + 1:,}-{end:,} "
                         f"of {len(text):,})")
        lines.append("Text: " + ("[…] " if start else "") + text[start:end] + (" […]" if end < len(text) else ""))
        out.append("\n".join(lines + link_lines))
    pages = list(pages)[:max(0, min(LINKED_DOCS, MAX_WINDOWS - len(windows)))]
    for i, (link, page) in enumerate(pages):
        body = _without_own(page.text or "", own)
        start, end = page_window(body, link)
        n = len(windows) + len(pages)
        lines = list(head) + [
            f"Window: {len(windows) + i + 1} of {n} (the post with a page it links on its own site, its maker's)",
            "Text: " + text[:LINKED_POST_CHARS] + (" […]" if len(text) > LINKED_POST_CHARS else "")] + link_lines
        lines += [PAGE_MARK.strip("\n") + _without_own(link, own),
                  f"Page title: {_without_own(page.title or '', own)}",
                  "Page text: " + ("[…] " if start else "") + body[start:end] + (" […]" if end < len(body) else "")]
        out.append("\n".join(lines))
    return out


def _asked(cur: Any, track_id: str, version: int, ids: Sequence[str]) -> Set[str]:
    """The posts already asked under this schema version (their questions' first line names it)."""
    cur.execute("""SELECT DISTINCT a::text FROM mx_tasks WHERE kind = %s AND guide = %s AND a = ANY(%s::uuid[])
                      AND b = %s AND input LIKE %s""",
                (THINGS_KIND, THINGS_GUIDE, list(ids), track_id, f"SCHEMA: {track_id} v{version}\n%"))
    return {r[0] for r in cur.fetchall()}


def plan_things(cur: Any, **_kw: Any) -> int:
    """`track_things` questions for each topic track with a schema: its posts in the track not yet asked under that
    schema's version, newest first, every window of each, THINGS_OPEN waiting at most a track: how many were added."""
    from insight_core.markx import repo, schemas, tasks, track_subtopics, tracks
    if not on():
        return 0
    schemas.ensure_guides(cur)
    added = 0
    for t in tracks.described(cur):
        s = current_schema(cur, t["folder_id"])
        if s is None:
            continue
        cur.execute("""SELECT count(*) FROM mx_tasks WHERE kind = %s AND b = %s AND status IN ('open', 'leased')""",
                    (THINGS_KIND, t["folder_id"]))
        room = THINGS_OPEN - cur.fetchone()[0]
        if room <= 0:
            continue
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        items = sorted(track_subtopics.in_track(cur, t), key=lambda it: (it["at"] or epoch, it["post_id"]), reverse=True)
        ids = [it["post_id"] for it in items]
        done = _asked(cur, t["folder_id"], s["version"], ids) if ids else set()
        todo = [i for i in ids if i not in done][:room]
        posts = tasks.load_posts(cur, todo)
        own = _own(cur, todo)
        pages = maker_pages(cur, posts, own) if linked_on() else {}
        for pid in todo:
            if pid not in posts:
                continue
            for text in things_inputs(t, s["schema"], s["version"], posts[pid], own.get(pid, []), pages.get(pid, ())):
                task_id, new = repo.add_task(cur, kind=THINGS_KIND, guide=THINGS_GUIDE, subject_kind="post_track",
                                             input=text, a=pid, b=t["folder_id"])
                added += new
                if not new:
                    got = _valid_answer(cur, task_id)
                    if got is not None:
                        apply_things(cur, repo.get_task(cur, task_id), None, got)
    return added


# ---- things and reports --------------------------------------------------------------------------------------

def key_fields(kind: Dict[str, Any]) -> List[str]:
    """The fields two reports of one thing share: the key fields and every link field."""
    return [f["name"] for f in kind["fields"] if f.get("key") or f.get("type") == "link"]


def sigs(kind: Dict[str, Any], values: Dict[str, Any], own: Optional[str] = None) -> Set[str]:
    """A report's (or a thing's) key values, normalised: {"field=value"}; a link as "link:<address>" whatever its
    field (v10.29: an explainer's reference link meets the release's own link), and `own` (the address of the post
    the thing is the one thing of) as a link too."""
    types = {f["name"]: f.get("type") for f in kind["fields"]}
    out = set()
    for name in key_fields(kind):
        v = values.get(name)
        v = v.get("value") if isinstance(v, dict) and "value" in v else v
        if v is None:
            continue
        if types.get(name) == "link":
            n = norm_url(v)
            if n:
                out.add(f"link:{n}")
            continue
        n = key_text(v) if isinstance(v, str) else json.dumps(v)
        if n:
            out.add(f"{name}={n}")
    if own and norm_url(own):
        out.add(f"link:{norm_url(own)}")
    return out


def own_address(cur: Any, post: str, things: Sequence[Dict[str, Any]], kinds: Dict[str, Dict[str, Any]]
                ) -> Optional[str]:
    """v10.29: a post's own address when the post gives one thing of the track's kinds (not counting practices): the
    post is that thing's page (a release's notes, a project's page), so a link to it elsewhere is a link to the
    thing. None when it gives several or none (its address names no one of them)."""
    mine = [t for t in things if t.get("kind") in kinds and t.get("kind") != PRACTICE_KIND and t.get("fields")]
    if len(mine) != 1:
        return None
    got = _own(cur, [post]).get(post) or []
    return got[0] if got else None


def _post_at(cur: Any, post_id: str) -> Optional[datetime]:
    from insight_core.markx import tracks
    cur.execute(f"SELECT {tracks._date()} FROM posts p WHERE p.id = %s", (post_id,))
    r = cur.fetchone()
    return r[0] if r else None


def roots(cur: Any, track_id: str) -> Dict[str, str]:
    """{thing id: its current root} of every thing of the track (a merged thing's chain followed)."""
    cur.execute("SELECT id::text, merged_into::text FROM mx_track_things WHERE track_id = %s", (track_id,))
    into = dict(cur.fetchall())
    out = {}
    for t in into:
        r, seen = t, set()
        while into.get(r) and r not in seen:
            seen.add(r)
            r = into[r]
        out[t] = r
    return out


def apply_things(cur: Any, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> int:
    """A things answer as reports: each thing joined to a current thing of its kind that shares a key value (a
    practice: one of the same post's), else a new thing; its fields merged again. How many reports were added. A call
    already applied adds nothing."""
    tid, version, _k, _shown = parse_input(task.get("input") or "")
    post = str(task["a"])
    if tid is None or str(task.get("b")) != tid:
        return 0
    schema = schema_at(cur, tid, version)
    if schema is None:
        return 0
    if call_id is None:
        cur.execute("SELECT id FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at DESC LIMIT 1", (task["id"],))
        r = cur.fetchone()
        if r is None:
            return 0
        call_id = r[0]
    cur.execute("SELECT 1 FROM mx_track_thing_reports WHERE call_id = %s LIMIT 1", (call_id,))
    if cur.fetchone() is not None:
        return 0
    from insight_core.markx import tasks
    win = tasks.window_of(task.get("input") or "")
    kinds = {k["kind"]: k for k in schema["kinds"]}
    at = _post_at(cur, post)
    own = own_address(cur, post, answer.get("things") or [], kinds)
    n_added = 0
    for n, th in enumerate(answer.get("things") or []):
        kind = kinds.get(th.get("kind"))
        if kind is None or not th.get("fields"):
            continue
        mine_own = own if kind["kind"] != PRACTICE_KIND else None
        thing = _match(cur, tid, kind, th["fields"], post, own=mine_own)
        if thing is None:
            key = sorted(sigs(kind, th["fields"], mine_own))
            first = kind["fields"][0]["name"]
            cur.execute("""INSERT INTO mx_track_things (track_id, kind, key, schema_version, first_at, last_at)
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id::text""",
                        (tid, kind["kind"], key[0] if key else f"{first}={key_text(th['fields'][first]['value'])}",
                         version, at, at))
            thing = cur.fetchone()[0]
        cur.execute("""INSERT INTO mx_track_thing_reports (call_id, n, thing_id, post_id, task_id, schema_version, win,
                                                           field_values)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb) ON CONFLICT DO NOTHING""",
                    (call_id, n, thing, post, task["id"], version, win, json.dumps(th["fields"], ensure_ascii=False)))
        n_added += cur.rowcount
        remerge(cur, tid, thing)
    return n_added


def _match(cur: Any, track_id: str, kind: Dict[str, Any], values: Dict[str, Any], post: str,
           own: Optional[str] = None) -> Optional[str]:
    """The current thing a report joins (its root): same kind and a shared key value (a link: also the address of a
    post that gave only that thing, `own_address`); a practice only among the things its own post already reported
    (its exact `what`)."""
    mine = sigs(kind, values, own)
    if not mine:
        return None
    if kind["kind"] == PRACTICE_KIND:
        cur.execute("""SELECT DISTINCT r.thing_id::text, r.field_values FROM mx_track_thing_reports r
                         JOIN mx_track_things t ON t.id = r.thing_id
                        WHERE t.track_id = %s AND t.kind = %s AND r.post_id = %s""", (track_id, kind["kind"], post))
        rows = cur.fetchall()
    else:   # each report with its post's own address when that post gave this one thing only (of the track's kinds)
        cur.execute("""SELECT r.thing_id::text, r.field_values,
                              CASE WHEN (SELECT count(DISTINCT r2.thing_id) FROM mx_track_thing_reports r2
                                           JOIN mx_track_things t2 ON t2.id = r2.thing_id
                                          WHERE r2.post_id = r.post_id AND t2.track_id = t.track_id
                                            AND t2.kind <> %s) = 1 THEN p.url END
                         FROM mx_track_thing_reports r JOIN mx_track_things t ON t.id = r.thing_id
                         JOIN posts p ON p.id = r.post_id
                        WHERE t.track_id = %s AND t.kind = %s""", (PRACTICE_KIND, track_id, kind["kind"]))
        rows = cur.fetchall()
    root = roots(cur, track_id)
    for row in rows:
        thing, vals = row[0], row[1]
        theirs = row[2] if len(row) > 2 else None
        if mine & sigs(kind, vals, theirs):
            return root.get(thing, thing)
    return None


def reports(cur: Any, track_id: str, thing_ids: Optional[Sequence[str]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """{root thing: its reports and its merged things' [{post, at, call, values, version, found_at}]}, oldest post
    first; `thing_ids`: only these roots'."""
    from insight_core.markx import tracks
    root = roots(cur, track_id)
    wanted = None if thing_ids is None else set(thing_ids)
    members = [t for t, r in root.items() if wanted is None or r in wanted]
    if not members:
        return {}
    cur.execute(f"""SELECT r.thing_id::text, r.post_id::text, {tracks._date()}, r.call_id::text, r.field_values,
                           r.schema_version, r.created_at
                      FROM mx_track_thing_reports r JOIN posts p ON p.id = r.post_id
                     WHERE r.thing_id = ANY(%s::uuid[])
                     ORDER BY 3 NULLS FIRST, r.created_at, r.call_id, r.n""", (members,))
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for thing, post, at, call, vals, version, found in cur.fetchall():
        out[root[thing]].append({"post": post, "at": at, "call": call, "values": vals, "version": version,
                                 "found_at": found})
    return out


def remerge(cur: Any, track_id: str, thing: str) -> None:
    """A thing's fields again from its reports (each field the newest post's value, with that post and quote), its
    first and last post dates."""
    rs = reports(cur, track_id, [thing]).get(thing, [])
    if not rs:
        return
    fields: Dict[str, Any] = {}
    for r in rs:   # oldest first: a newer post's value replaces an older one's
        for name, v in (r["values"] or {}).items():
            fields[name] = {"value": v.get("value"), "quote": v.get("quote"), "post": r["post"],
                            **({"page": v["page"]} if v.get("page") else {})}
    ats = [r["at"] for r in rs if r["at"] is not None]
    cur.execute("""UPDATE mx_track_things SET fields = %s::jsonb, first_at = %s, last_at = %s, updated_at = now()
                    WHERE id = %s""",
                (json.dumps(fields, ensure_ascii=False), min(ats) if ats else None, max(ats) if ats else None, thing))


def merge(cur: Any, track_id: str, keep: str, gone: str, by: str) -> bool:
    """`gone` joined into `keep` (both current roots of the track, two of one kind): a status, its reports read as
    `keep`'s from then on."""
    root = roots(cur, track_id)
    keep, gone = root.get(keep, keep), root.get(gone, gone)
    if keep == gone:
        return False
    cur.execute("""UPDATE mx_track_things g SET status = 'merged', merged_into = %s, merged_by = %s, updated_at = now()
                     FROM mx_track_things k
                    WHERE g.id = %s AND k.id = %s AND g.track_id = %s AND k.track_id = g.track_id AND k.kind = g.kind
                      AND g.status = 'current' AND k.status = 'current'""", (keep, by, gone, keep, track_id))
    if not cur.rowcount:
        return False
    remerge(cur, track_id, keep)
    return True


def current(cur: Any, track_id: str, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    """The track's current things (of one kind): [{id, kind, key, fields, first_at, last_at, found_at, schema_version}],
    newest post first."""
    cur.execute("""SELECT id::text, kind, key, fields, first_at, last_at, created_at, schema_version FROM mx_track_things
                    WHERE track_id = %s AND status = 'current' AND (%s::text IS NULL OR kind = %s)
                    ORDER BY last_at DESC NULLS LAST, created_at DESC, id""", (str(track_id), kind, kind))
    return [dict(zip(("id", "kind", "key", "fields", "first_at", "last_at", "found_at", "schema_version"), r))
            for r in cur.fetchall()]


# ---- joins by entity, and same-claim questions (the jobs process; the planner) ------------------------------------

def _mentions(cur: Any, post_ids: Sequence[str]) -> Dict[str, List[Tuple[str, str, str]]]:
    """{post: [(entity root, name key, span as a key text)]} of the posts' current mentions (pins and redirects read)."""
    from insight_core.markx import happening
    if not post_ids:
        return {}
    cur.execute("""SELECT m.post_id::text, COALESCE(pin.entity_id, m.entity_id)::text, m.name_key, m.span
                     FROM mx_mentions_now m
                     LEFT JOIN mx_entity_pins pin ON pin.post_id = m.post_id AND pin.guide = m.guide AND pin.n = m.n
                                                 AND pin.undone_at IS NULL
                    WHERE m.post_id = ANY(%s::uuid[])""", (list(post_ids),))
    rows = [r for r in cur.fetchall() if r[1]]
    ids = happening._roots(cur, [r[1] for r in rows])
    out: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
    for post, eid, nk, span in rows:
        out[post].append((ids.root(eid), nk or "", key_text(span)))
    return out


def named_entities(kind: Dict[str, Any], rs: Sequence[Dict[str, Any]], ments: Dict[str, List[Tuple[str, str, str]]]
                   ) -> Set[str]:
    """The entities a thing names: a mention of a reporting post whose name (or span) is the thing's own key text; a
    practice: every mention whose span is inside one of its quotes."""
    out: Set[str] = set()
    for r in rs:
        vals = r["values"] or {}
        if kind["kind"] == PRACTICE_KIND:
            quotes = [f" {key_text(v.get('quote'))} " for v in vals.values() if isinstance(v, dict)]
            out |= {root for root, _nk, span in ments.get(r["post"], []) if span and any(f" {span} " in q for q in quotes)}
            continue
        keys = {key_text(vals[f].get("value")) for f in key_fields(kind)
                if f in vals and isinstance(vals[f].get("value"), str)}
        keys.discard("")
        out |= {root for root, nk, span in ments.get(r["post"], []) if nk in keys or key_text(span) in keys}
    return out


def _kinds(cur: Any, track_id: str) -> Dict[str, Dict[str, Any]]:
    s = current_schema(cur, track_id)
    kinds = {k["kind"]: k for k in (s["schema"]["kinds"] if s else [])}
    kinds.setdefault(PRACTICE_KIND, PRACTICE)
    return kinds


def entity_join(cur: Any, track: Dict[str, Any]) -> int:
    """Two current things of one kind (not practices) naming the same entity: the newer joined into the older. How
    many joins."""
    tid = track["folder_id"]
    kinds = _kinds(cur, tid)
    things = [t for t in current(cur, tid) if t["kind"] != PRACTICE_KIND and t["kind"] in kinds]
    if len(things) < 2:
        return 0
    rs = reports(cur, tid, [t["id"] for t in things])
    ments = _mentions(cur, sorted({r["post"] for v in rs.values() for r in v}))
    first: Dict[Tuple[str, str], str] = {}
    joined = 0
    for t in sorted(things, key=lambda t: (t["found_at"], t["id"])):
        for e in sorted(named_entities(kinds[t["kind"]], rs.get(t["id"], []), ments)):
            k = (t["kind"], e)
            if k in first and first[k] != t["id"]:
                joined += merge(cur, tid, first[k], t["id"], "entity")
                break
            first.setdefault(k, t["id"])
    return joined


def refresh(cur: Any) -> Dict[str, Any]:
    """The jobs process's pass (jobs.Jobs.tracks, before the briefs are kept): the entity joins of each topic track.
    {track: joins}; nothing while off."""
    from insight_core.markx import tracks
    if not on():
        return {}
    return {t["folder_id"]: n for t in tracks.described(cur) if (n := entity_join(cur, t))}


def same_input(track: Dict[str, Any], a: Dict[str, Any], b: Dict[str, Any]) -> str:
    def line(tag: str, t: Dict[str, Any]) -> str:
        f = t["fields"] or {}
        return f"{tag}: " + " | ".join(f"{n}: {f[n]['value']}" for n in ("what", "result", "evidence") if n in f)
    return "\n".join(header(track)[:2] + ["", line("A", a), line("B", b)])


def plan_same(cur: Any, **_kw: Any) -> int:
    """A `track_same` question for each pair of current practices of a track whose quotes name a shared entity and
    that were never asked (by the pair), SAME_OPEN waiting at most: how many were added."""
    from insight_core.markx import repo, schemas, tracks
    if not on():
        return 0
    schemas.ensure_guides(cur)
    cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = %s AND status IN ('open', 'leased')", (SAME_KIND,))
    room = SAME_OPEN - cur.fetchone()[0]
    added = 0
    for t in tracks.described(cur):
        if room <= 0:
            break
        ps = current(cur, t["folder_id"], PRACTICE_KIND)
        if len(ps) < 2:
            continue
        rs = reports(cur, t["folder_id"], [p["id"] for p in ps])
        ments = _mentions(cur, sorted({r["post"] for v in rs.values() for r in v}))
        named = {p["id"]: named_entities(PRACTICE, rs.get(p["id"], []), ments) for p in ps}
        posts = {p["id"]: {r["post"] for r in rs.get(p["id"], [])} for p in ps}
        cur.execute("""SELECT a::text, b::text FROM mx_tasks WHERE kind = %s AND guide = %s
                          AND (a = ANY(%s::uuid[]) OR b = ANY(%s::uuid[]))""",
                    (SAME_KIND, SAME_GUIDE, list(named), list(named)))
        asked = {tuple(sorted(r)) for r in cur.fetchall()}
        by = {p["id"]: p for p in ps}
        ids = sorted(named)
        for i, x in enumerate(ids):
            for y in ids[i + 1:]:
                if room <= 0 or (x, y) in asked or not (named[x] & named[y]) or posts[x] == posts[y]:
                    continue
                _tid, new = repo.add_task(cur, kind=SAME_KIND, guide=SAME_GUIDE, subject_kind="thing_thing",
                                          input=same_input(t, by[x], by[y]), a=x, b=y)
                asked.add((x, y))
                added += new
                room -= new
    return added


def apply_same(cur: Any, task: Dict[str, Any], answer: Dict[str, Any]) -> bool:
    """A same-claim answer: `same` joins the newer practice into the older (both still current)."""
    if not answer.get("same"):
        return False
    cur.execute("SELECT id::text, track_id::text, created_at FROM mx_track_things WHERE id = ANY(%s::uuid[])",
                ([str(task["a"]), str(task["b"])],))
    rows = sorted(cur.fetchall(), key=lambda r: (r[2], r[0]))
    if len(rows) != 2 or rows[0][1] != rows[1][1]:
        return False
    return merge(cur, rows[0][1], rows[0][0], rows[1][0], "haiku")


def after_answer(cur: Any, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> None:
    """tasks.record's part: a schema stored, a post's things reported, two practices joined."""
    if task["kind"] == SCHEMA_KIND:
        apply_schema(cur, task, answer)
    elif task["kind"] == THINGS_KIND:
        apply_things(cur, task, call_id, answer)
    elif task["kind"] == SAME_KIND:
        apply_same(cur, task, answer)
