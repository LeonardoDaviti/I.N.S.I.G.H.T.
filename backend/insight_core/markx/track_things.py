"""A track's things: the general track briefer's schema, things, reports and joins (issue 0245).

One briefer for every track: the track's name, description and excludes are its only track-specific input; every rule
is about types (text, number, money, link, enum), never a named track or field. This module owns a track's schema
(`plan_schemas`, `set_schema`: Haiku's kinds plus the general PRACTICE, one version a row), its things (one row a
thing however many posts report it), each post's reports (`plan_things`, `apply_things`: values with their quotes,
read in windows, plus the maker's own linked pages) and the joins of reports or rows into one thing. Every value is
checked against what its question showed (`salvage`, run by the worker too); a failed value is dropped with its
reason. Joins never use vector similarity: a strong identity (`same_identity`), the same named entity (`refresh`), or
Haiku's `same` (`plan_same`); a join is a status, never a delete (`repair` splits rows wrongly joined).
markx/track_brief.py reads them. Behind entity_bands.json `tracks.briefs` (`on`). Only mx_* tables are written.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

log = logging.getLogger(__name__)

SCHEMA_KIND, SCHEMA_GUIDE = "track_schema", "track-schema-v1"
THINGS_KIND, THINGS_GUIDE = "track_things", "track-things-v3"   # v3: a catalog is one row
SAME_KIND, SAME_GUIDE = "track_same", "track-same-v2"
PRACTICE_KIND = "practice_or_claim"
PRACTICE = {"kind": PRACTICE_KIND, "about": "a method, habit, finding or opinion a post states",
            "fields": [{"name": "what", "type": "text", "key": True, "about": "the method or claim, in a few words"},
                       {"name": "result", "type": "text", "key": False, "about": "what it gave or what is claimed"},
                       {"name": "evidence", "type": "text", "key": False, "about": "numbers, test or example given"},
                       {"name": "by", "type": "text", "key": False,
                        "about": "who measured, tested or found it, when the post names them (a company, a lab, a person)"}]}
TEXT_CAP = 120          # characters of a text value at most
WINDOW_CHARS = 3500     # characters of a post one question shows (round 2's window)
MAX_WINDOWS = 6         # windows a long post is read in at most
LINKS_MAX = 25
THINGS_OPEN = 60
SAME_OPEN = 240         # one 5-minute plan pass and some: the server answered ~40 a minute
SAME_PAIRS = 200        # same-thing pairs one track's plan considers at most (closest names first)
RARE_MIN, RARE_SHARE = 3, 0.02   # a word of at most this many of a kind's names (or this share) is rare
AGREE = 0.5             # two names agree when their shared words are this Dice share of their words at least
OWN = "[this post's own address]"
SWITCH = ("tracks", "briefs")
LINKED_SWITCH = "linked_docs"
LINKED_DOCS = 2         # the maker's pages a post's questions show at most, within MAX_WINDOWS
LINKED_POST_CHARS = 1500  # characters of the post a linked page's question shows with the page (its first)
LINKED_LEAD = 200       # characters of the page shown before the part a link's anchor names
PAGE_MARK = "\nLinked page on the post's own site: "


# ---- the switch ---------------------------------------------------------------------------------------------

def on() -> bool:
    """entity_bands.json `tracks.briefs`: the briefer plans, joins and builds (default off)."""
    from insight_core.markx import identity
    return bool((identity.bands().get(SWITCH[0]) or {}).get(SWITCH[1]))


def linked_on() -> bool:
    """entity_bands.json `tracks.linked_docs`: a post's questions also show the stored pages it links on its own site
    (default on; the post's own questions are unchanged)."""
    from insight_core.markx import identity
    return bool((identity.bands().get(SWITCH[0]) or {}).get(LINKED_SWITCH, True))


# ---- folding and typed values (pure: the worker runs these checks too) --------------------------------------

def fold(s: Any) -> str:
    from insight_core.markx import validate
    return validate.fold(str(s or "")).strip()


UI_FRAGMENTS = frozenset({"", "m", "top", "main", "content", "comments", "respond", "more"})


def norm_url(u: Any) -> str:
    """A URL as two are compared: folded, no scheme, no www., no trailing slash or punctuation; a fragment kept when
    it names an item of the page ("releases#2026111800"), dropped when it is page furniture ("#comments", ":~:")."""
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


def figures(quote: str, *, strict: bool = False) -> Set[float]:
    """Every value a figure of `quote` can be read as: its parts, its thousands grouping, its decimal, each times a
    multiplier written right after it ("16K", "1.2M"). `strict` (a typed number's check): a figure with a word
    multiplier after it or a letter glued to it is read only multiplied (a letter after a space may be a unit)."""
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
            only = strict and (mult.group(2) is not None or not mult.group(0)[:1].isspace())
            vals = {v * k for v in vals} if only else vals | {v * k for v in vals}
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
    """The unit as the quote writes it: whole, or every one of its words by its first three letters ("tokens/s" in
    "tok/s")."""
    u, q = fold(unit), fold(quote)
    if not u or u in q:
        return True
    words = re.findall(r"[^\W\d_]+", u)
    return bool(words) and all(w[:3] in q for w in words)


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
        figs = figures(quote, strict=True)
        num = float(value["number"])
        if not _same_number(abs(num), figs):   # a fall given as a negative number shows its digits
            return None, "number not in its quote"
        to = value.get("range_to")
        if to is not None:
            if not isinstance(to, (int, float)) or isinstance(to, bool) or not _same_number(abs(float(to)), figs):
                return None, "range_to not in its quote"
            if float(to) < num:
                return None, "range_to below number"
        out: Dict[str, Any] = {"number": num, "range_to": None if to is None else float(to)}
        if t == "money":
            cur_ = str(value.get("currency") or "").strip().upper()
            if not currency_shown(cur_, quote):
                return None, "currency not in its quote"
            out["currency"] = cur_
        unit = value.get("unit")   # money may say what it is per ("per million input tokens"), shown by its quote
        unit = unit.strip() if isinstance(unit, str) and unit.strip() else None
        if unit and not unit_shown(unit, quote):
            return None, "unit not in its quote"
        if t != "money" or unit:
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
    if not figures_read(value, quote):
        return None, "a figure not in its quote"
    return value, None


def figures_read(value: str, quote: str) -> bool:
    """Every figure a text value gives is a figure of its own quote (read in its quote, not taken from the post around
    it). Language-free: figures only."""
    have = figures(quote)
    return all(_same_number(float(x), have) for x in re.findall(r"\d+(?:\.\d+)?", value or ""))


_RAW_GITHUB = re.compile(r"^https?://raw\.githubusercontent\.com/([^/\s]+)/([^/\s]+)/([^/\s]+)(/[^\s]*)?$", re.I)
_GITHUB = re.compile(r"^(https?://(?:www\.)?github\.com/[^/\s]+/[^/\s#?]+?)(?:\.git)?(?:/raw(/[^\s]*))?/?$", re.I)


def reader_link(u: str) -> str:
    """A link as a reader opens it: a raw GitHub file as its page in the repo (blob), a clone address (.git) as the
    repo. The stored value is kept as the post gave it."""
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
        tail = (" ".join(x for x in (v.get("currency"), v.get("unit")) if x) if field.get("type") == "money"
                else (v.get("unit") or field.get("unit")))
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
    """(the linked page a question shows, or None; what it showed of the post itself)."""
    if PAGE_MARK not in shown:
        return None, shown
    of_post, _, rest = shown.partition(PAGE_MARK)
    return rest.split("\n", 1)[0].strip() or None, of_post


def salvage(answer: Dict[str, Any], input: str) -> Dict[str, Any]:
    """The things answer checked value by value: each kept value typed, each dropped one (and each thing whose name
    did not stand, of an unknown kind, or past THINGS_PER_ANSWER) under "dropped" with why; a value quoted only from
    the linked page names it (`page`). Idempotent: the worker salvages before it posts, the server again."""
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
                if page and fold(raw["quote"]) not in fold(of_post):   # quoted from the linked page only
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
                task_id: Any = None, subject: str = "track") -> int:
    """A schema version stored; `subject` 'entity' (by 'code'): the "track" is an entity's root (entity_brief)."""
    cur.execute("""INSERT INTO mx_track_schemas (track_id, version, schema, by, track_version, task_id, subject)
                   SELECT %s, COALESCE(max(version), 0) + 1, %s::jsonb, %s, %s, %s, %s FROM mx_track_schemas
                    WHERE track_id = %s RETURNING version""",
                (folder_id, json.dumps(schema), by, track_version, task_id, subject, folder_id))
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
    has no schema for that version yet: the version, or None. Only track-schema-v1's (track-fields-v1 only suggests
    fields; never applied)."""
    from insight_core.markx import tracks
    if task.get("guide", SCHEMA_GUIDE) != SCHEMA_GUIDE:
        return None
    t = tracks.get(cur, task["a"])
    if not tracks.is_topic(t) or schema_input(t) != task.get("input"):
        return None
    have = current_schema(cur, t["folder_id"])
    if have is not None and have["track_version"] >= t["version"]:
        return None
    return _put_schema(cur, t["folder_id"], with_practice(answer), by="haiku", track_version=t["version"],
                       task_id=task["id"])


def set_schema(cur: Any, folder_id: Any, kinds: Any) -> Dict[str, Any]:
    """The owner's schema (PUT .../schema {kinds}: PRACTICE is added by code, up to schemas.OWNER_FIELDS fields a
    kind) stored as a new version: the schema view. ValueError: not a valid schema; KeyError: not a topic track."""
    from insight_core.markx import schemas, tracks, validate
    t = tracks.get(cur, folder_id)
    if not tracks.is_topic(t):
        raise KeyError(folder_id)
    answer = {"kinds": [k for k in kinds or [] if not (isinstance(k, dict) and k.get("kind") == PRACTICE_KIND)]}
    err = validate.schema_error(schemas.OWNER_SCHEMA_SCHEMA, answer) or schema_error(answer)
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
    """`link` is a page of the post's maker: on the post's own registrable site, and on a site of accounts (a
    platform, a code host) under the same account (a release linking its own repo's docs, not another's)."""
    from insight_core.markx.rename import CODE_HOSTS
    from insight_core.utils.addresses import PLATFORM_SITES, account_key, host_of, site_of
    a, b = site_of(host_of(own)), site_of(host_of(link))
    if not a or a != b:
        return False
    if a in CODE_HOSTS or any(a in sites for sites in PLATFORM_SITES.values()):
        return account_key(own) == account_key(link)
    return True


def maker_pages(cur: Any, posts: Dict[str, Any], own: Dict[str, List[str]]) -> Dict[str, List[Tuple[str, Any]]]:
    """{post id: [(the link as the post gives it, the stored page)]}, LINKED_DOCS at most a post, in the post's
    order: the links (post_refs) that are its maker's (`maker_page`) and stored as a post, never the post itself.
    Read only; nothing is fetched here."""
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
    post (title, which window, text) and its links; then one question a maker's page of `pages` within MAX_WINDOWS
    (the post's first LINKED_POST_CHARS and links, then the page's window). The post's own questions are the same
    with or without pages."""
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
    """The posts already asked under this schema version, under any guide of the kind (a new guide asks new posts
    only)."""
    from insight_core.markx import schemas
    cur.execute("""SELECT DISTINCT a::text FROM mx_tasks WHERE kind = %s AND guide = ANY(%s) AND a = ANY(%s::uuid[])
                      AND b = %s AND input LIKE %s""",
                (THINGS_KIND, list(schemas.answer_guides(THINGS_KIND)), list(ids), track_id,
                 f"SCHEMA: {track_id} v{version}\n%"))
    return {r[0] for r in cur.fetchall()}


def plan_things(cur: Any, **_kw: Any) -> int:
    """`track_things` questions for each topic track with a schema: its posts in the track not yet asked under that
    schema's version, newest first, every window of each, THINGS_OPEN waiting at most a track: how many were added."""
    from insight_core.markx import schemas, track_subtopics, tracks
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
        added += ask_posts(cur, t, s, [it["post_id"] for it in items], room=room)
    return added


def ask_posts(cur: Any, track: Dict[str, Any], s: Dict[str, Any], ids: Sequence[str], *, room: int,
              again: bool = False) -> int:
    """The things questions of `ids` (in their order) not yet asked under schema `s`'s version, `room` posts at most,
        every window of each (and its maker's linked pages): how many were added. A question already answered is applied
        again (its reports, once). A track's posts and an entity's (entity_brief) are asked by this one path."""
    from insight_core.markx import repo, tasks
    done = _asked(cur, track["folder_id"], s["version"], ids) if ids and not again else set()   # again: repair
    todo = [i for i in ids if i not in done][:max(0, room)]
    posts = tasks.load_posts(cur, todo)
    own = _own(cur, todo)
    pages = maker_pages(cur, posts, own) if linked_on() else {}
    added = 0
    for pid in todo:
        if pid not in posts:
            continue
        for text in things_inputs(track, s["schema"], s["version"], posts[pid], own.get(pid, []), pages.get(pid, ())):
            task_id, new = repo.add_task(cur, kind=THINGS_KIND, guide=THINGS_GUIDE, subject_kind="post_track",
                                         input=text, a=pid, b=track["folder_id"])
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
    field, and `own` (the address of the post the thing is the one thing of) as a link too."""
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
    """A post's own address when the post gives one thing of the track's kinds (practices aside): the post is that
    thing's page. None when it gives several or none."""
    mine = [t for t in things if t.get("kind") in kinds and t.get("kind") != PRACTICE_KIND and t.get("fields")]
    if len(mine) != 1:
        return None
    got = _own(cur, [post]).get(post) or []
    return got[0] if got else None


def post_date(alias: str = "p") -> str:
    """A thing's post date as SQL: the post's publication (pairing.published_date), never the day a feed surfaced
    an old post."""
    from insight_core.markx import pairing
    return pairing.published_date(alias)


def _post_at(cur: Any, post_id: str) -> Optional[datetime]:
    cur.execute(f"SELECT {post_date()} FROM posts p WHERE p.id = %s", (post_id,))
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


def _joined(root: Dict[str, str], keep: str, gone: str) -> None:
    """`root` (a `roots` map read once by the caller) after `gone` joined `keep`: every thing whose root was `gone`."""
    for t, r in root.items():
        if r == gone:
            root[t] = keep
    root[gone] = keep


def _one_thing_posts(alias: str = "one") -> str:
    """SQL (params: track id, PRACTICE_KIND): a CTE of the track's posts that gave one thing of its kinds (practices
    aside), read once a statement: such a post's address is its thing's own page."""
    return f"""{alias} AS (SELECT r2.post_id FROM mx_track_thing_reports r2 JOIN mx_track_things t2 ON t2.id = r2.thing_id
                             WHERE t2.track_id = %s AND t2.kind <> %s GROUP BY r2.post_id
                            HAVING count(DISTINCT r2.thing_id) = 1)"""


def apply_things(cur: Any, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> int:
    """A things answer as reports: each thing joined to a current thing of its strong identity (`_match`; a practice:
    one of the same post's), else a new thing; each touched thing's fields merged again once. How many reports were
    added. A call already applied adds nothing. v10.44: the track's roots and each kind's reports are read once an
    answer (a thing of the answer is matched against its earlier things too)."""
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
    root = roots(cur, tid)
    seen: Dict[str, List[Tuple[str, str, Set[str], Dict[str, Set[str]]]]] = {}
    touched: List[str] = []
    n_added = 0
    for n, th in enumerate(answer.get("things") or []):
        kind = kinds.get(th.get("kind"))
        if kind is None or not th.get("fields"):
            continue
        mine_own = own if kind["kind"] != PRACTICE_KIND else None
        if kind["kind"] not in seen:
            seen[kind["kind"]] = _candidates(cur, tid, kind, post)
        thing = _match(kind, th["fields"], seen[kind["kind"]], root, own=mine_own)
        if thing is None:
            key = sorted(sigs(kind, th["fields"], mine_own))
            first = kind["fields"][0]["name"]
            cur.execute("""INSERT INTO mx_track_things (track_id, kind, key, schema_version, first_at, last_at)
                           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id::text""",
                        (tid, kind["kind"], key[0] if key else f"{first}={key_text(th['fields'][first]['value'])}",
                         version, at, at))
            thing = cur.fetchone()[0]
            root[thing] = thing
        cur.execute("""INSERT INTO mx_track_thing_reports (call_id, n, thing_id, post_id, task_id, schema_version, win,
                                                           field_values)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb) ON CONFLICT DO NOTHING""",
                    (call_id, n, thing, post, task["id"], version, win, json.dumps(th["fields"], ensure_ascii=False)))
        n_added += cur.rowcount
        seen[kind["kind"]].append(_candidate(kind, thing, th["fields"], mine_own))
        touched.append(thing)
    for thing in dict.fromkeys(root.get(t, t) for t in touched):
        remerge(cur, tid, thing, root=root)
    if n_added and task.get("guide") == THINGS_GUIDE:
        fold_catalog(cur, tid, post, call_id, kinds, root=root)
    return n_added


def fold_catalog(cur: Any, track_id: str, post: str, call_id: Any, kinds: Dict[str, Dict[str, Any]], *,
                 root: Optional[Dict[str, str]] = None) -> int:
    """A post asked again under track-things-v3 (`repair`) gave one row of a kind: the rows of that kind only this
    post's earlier answers gave join it (merged_by haiku). How many joins."""
    cur.execute("""SELECT t.kind, array_agg(DISTINCT r.thing_id::text) FROM mx_track_thing_reports r
                     JOIN mx_track_things t ON t.id = r.thing_id
                    WHERE r.call_id = %s AND t.track_id = %s GROUP BY 1""", (call_id, track_id))
    got = cur.fetchall()
    root = roots(cur, track_id) if root is None else root
    joined = 0
    for kind, things in got:
        heads = {root.get(t, t) for t in things}
        if kind == PRACTICE_KIND or kind not in kinds or len(heads) != 1:
            continue
        head, = heads
        cur.execute("""SELECT t.id::text FROM mx_track_things t
                        WHERE t.track_id = %s AND t.kind = %s AND t.status = 'current' AND t.id <> %s
                          AND EXISTS (SELECT 1 FROM mx_track_thing_reports r WHERE r.thing_id = t.id)
                          AND NOT EXISTS (SELECT 1 FROM mx_track_thing_reports r JOIN mx_tasks k ON k.id = r.task_id
                                           WHERE r.thing_id = t.id AND (r.post_id <> %s OR k.guide = %s))""",
                    (track_id, kind, head, post, THINGS_GUIDE))
        for (gone,) in cur.fetchall():
            joined += merge(cur, track_id, head, gone, "haiku", root=root)
    return joined


def name_of(kind: Dict[str, Any], values: Dict[str, Any]) -> str:
    """A report's (or a thing's) name as two are compared: its kind's first field, as a key text, a plural `s`
    folded."""
    first = kind["fields"][0]["name"]
    v = values.get(first)
    v = v.get("value") if isinstance(v, dict) and "value" in v else v
    if not isinstance(v, str):
        return ""
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w
                    for w in key_text(v).split())


def links_of(kind: Dict[str, Any], values: Dict[str, Any], own: Optional[str] = None) -> Set[str]:
    """A report's links (every link field, and `own`, the address of the post it is the one thing of), normalised;
    `own` also as "own:<address>" (the thing's own page: a link to it names the thing)."""
    out = {s for s in sigs(kind, values, own) if s.startswith("link:")}
    return out | ({f"own:{norm_url(own)}"} if own and norm_url(own) else set())


def name_words(name: str) -> Set[str]:
    """The words of a name two may share: 3+ characters, or holding a digit."""
    return {w for w in name.split() if len(w) >= 3 or any(c.isdigit() for c in w)}


def rare_words(names: Iterable[str]) -> Set[str]:
    """The words of a kind's names that few of its rows use (RARE_SHARE at most, RARE_MIN rows at least): a word most
    rows share ("model", "app") names no one of them. Any language."""
    df: Dict[str, int] = defaultdict(int)
    n = 0
    for name in names:
        n += 1
        for w in name_words(name):
            df[w] += 1
    cap = max(RARE_MIN, RARE_SHARE * n)
    return {w for w, c in df.items() if c <= cap}


def other_keys(kind: Dict[str, Any], values: Dict[str, Any]) -> Dict[str, Set[str]]:
    """A report's (or a row's) key text fields besides its name, as words ({field: name_words}); a field not given is
    left out. v10.44: a kind keyed on several fields (a model *and* the machine it ran on) is one thing only where
    they all agree."""
    out = {}
    for f in kind["fields"][1:]:
        if not f.get("key") or f.get("type") not in (None, "text"):
            continue
        v = values.get(f["name"])
        v = v.get("value") if isinstance(v, dict) and "value" in v else v
        if isinstance(v, str) and (w := name_words(key_text(v))):
            out[f["name"]] = w
    return out


def keys_agree(a: Optional[Dict[str, Set[str]]], b: Optional[Dict[str, Set[str]]]) -> bool:
    """Whether two reports' other key fields (`other_keys`) agree: each field both give names the same (one's words
    within the other's, or AGREE of their words shared: "5090 GPU" and "RTX 5090" agree, "RTX 3060 12GB" and "Machine
    with 23GB RAM" do not). A field one leaves out never disagrees."""
    for name in set(a or {}) & set(b or {}):
        x, y = a[name], b[name]
        if not (x <= y or y <= x or 2 * len(x & y) >= AGREE * (len(x) + len(y))):
            return False
    return True


def same_identity(a_name: str, a_links: Set[str], b_name: str, b_links: Set[str], rare: Set[str],
                  a_keys: Optional[Dict[str, Set[str]]] = None, b_keys: Optional[Dict[str, Set[str]]] = None) -> bool:
    """Two reports are one thing only on a strong identity: the same name, or a shared link and names that agree (a
    rare word in both and AGREE of their words shared: "Tiel-Coder" and "Tiel-Coder 35B-A3B" agree, "Test PC" and
    "Palit RTX 5060 Ti test stand" do not); a link to the other's own page needs the rare word only. A shared link
    alone, or any other key (the hardware), is not the thing's identity, and a disagreeing other key (`keys_agree`:
    one model on two machines) is two things whatever the name."""
    if not a_name or not b_name:
        return False
    if not keys_agree(a_keys, b_keys):
        return False
    if a_name == b_name:
        return True
    if not a_links & b_links:
        return False
    a, b = name_words(a_name), name_words(b_name)
    shared = a & b
    if not shared & rare:
        return False
    page = any(f"link:{x[4:]}" in b_links for x in a_links if x.startswith("own:")) or \
        any(f"link:{x[4:]}" in a_links for x in b_links if x.startswith("own:"))
    return page or 2 * len(shared) >= AGREE * (len(a) + len(b))


def _candidate(kind: Dict[str, Any], thing: str, values: Dict[str, Any], own: Optional[str] = None
               ) -> Tuple[str, str, Set[str], Dict[str, Set[str]]]:
    """A report as `_match` compares it: (its thing, name, links, other keys)."""
    return thing, name_of(kind, values), links_of(kind, values, own), other_keys(kind, values)


def _candidates(cur: Any, track_id: str, kind: Dict[str, Any], post: str
                ) -> List[Tuple[str, str, Set[str], Dict[str, Set[str]]]]:
    """The reports a report of `post` may join (`_candidate` each): of a practice, its own post's of the kind; else
    every report of the kind in the track, with its post's own address when that post gave this one thing only (of
    the track's kinds). One read."""
    if kind["kind"] == PRACTICE_KIND:
        cur.execute("""SELECT DISTINCT r.thing_id::text, r.field_values, NULL FROM mx_track_thing_reports r
                         JOIN mx_track_things t ON t.id = r.thing_id
                        WHERE t.track_id = %s AND t.kind = %s AND r.post_id = %s""", (track_id, kind["kind"], post))
    else:
        cur.execute(f"""WITH {_one_thing_posts()}
                        SELECT r.thing_id::text, r.field_values, CASE WHEN one.post_id IS NOT NULL THEN p.url END
                          FROM mx_track_thing_reports r JOIN mx_track_things t ON t.id = r.thing_id
                          JOIN posts p ON p.id = r.post_id LEFT JOIN one ON one.post_id = r.post_id
                         WHERE t.track_id = %s AND t.kind = %s""", (track_id, PRACTICE_KIND, track_id, kind["kind"]))
    return [_candidate(kind, thing, vals, url) for thing, vals, url in cur.fetchall()]


def _match(kind: Dict[str, Any], values: Dict[str, Any],
           cands: Sequence[Tuple[str, str, Set[str], Dict[str, Set[str]]]], root: Dict[str, str],
           own: Optional[str] = None) -> Optional[str]:
    """The current thing a report joins (its root): same kind and a strong identity with one of that thing's own
    reports (`same_identity`, so no chain through weak keys); a practice only among its own post's things (the same
    name). `cands`: `_candidates`; `root`: the track's `roots`."""
    mine = name_of(kind, values)
    if not mine or not cands:
        return None
    if kind["kind"] == PRACTICE_KIND:
        for thing, name, _l, _k in cands:
            if name == mine:
                return root.get(thing, thing)
        return None
    rare = rare_words([n for _t, n, _l, _k in cands] + [mine])
    links, keys = links_of(kind, values, own), other_keys(kind, values)
    for thing, name, theirs, their_keys in cands:
        if same_identity(mine, links, name, theirs, rare, keys, their_keys):
            return root.get(thing, thing)
    return None


def reports(cur: Any, track_id: str, thing_ids: Optional[Sequence[str]] = None, *,
            root: Optional[Dict[str, str]] = None) -> Dict[str, List[Dict[str, Any]]]:
    """{root thing: its reports and its merged things' [{post, at, call, values, version, found_at}]}, oldest post
    first; `thing_ids`: only these roots'; `root`: the track's `roots`, when the caller read them. A post hidden
    (posts.filtered_by: its source's item filter or a repair hid it) reports nothing: v10.44, it leaves every view
    of the track's things and every row's fields."""
    root = roots(cur, track_id) if root is None else root
    wanted = None if thing_ids is None else set(thing_ids)
    members = [t for t, r in root.items() if wanted is None or r in wanted]
    if not members:
        return {}
    cur.execute(f"""SELECT r.thing_id::text, r.post_id::text, {post_date()}, r.call_id::text, r.field_values,
                           r.schema_version, r.created_at
                      FROM mx_track_thing_reports r JOIN posts p ON p.id = r.post_id
                     WHERE r.thing_id = ANY(%s::uuid[]) AND p.filtered_by IS NULL
                     ORDER BY 3 NULLS FIRST, r.created_at, r.call_id, r.n""", (members,))
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for thing, post, at, call, vals, version, found in cur.fetchall():
        out[root[thing]].append({"post": post, "at": at, "call": call, "values": vals, "version": version,
                                 "found_at": found})
    return out


def reported(things: Sequence[Dict[str, Any]], rs: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """The things some shown post reports (`reports` reads no hidden post): the rows a view of the track shows."""
    return [t for t in things if rs.get(t["id"])]


def value_key(v: Any) -> str:
    """A value as two posts' values are compared (text folded as a key text, numbers and links as given)."""
    v = v.get("value") if isinstance(v, dict) and "value" in v else v
    if isinstance(v, str):
        return "link:" + norm_url(v) if re.match(r"^https?://", v) else key_text(v)
    return json.dumps(v, sort_keys=True)


def merged_fields(rs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """A thing's fields from its own reports (oldest post first): each field the value most of its posts give (a tie:
    the earliest post's; within one post its latest answer's), with that report's quote: value and quote always one
    post's."""
    order: Dict[str, int] = {}
    for r in rs:
        order.setdefault(r["post"], len(order))
    posts: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))
    best: Dict[Tuple[str, str], Tuple[int, int, Dict[str, Any], str]] = {}
    for i, r in enumerate(rs):
        for name, v in (r["values"] or {}).items():
            if not isinstance(v, dict):
                continue
            k = value_key(v)
            posts[name][k].add(r["post"])
            rank = (order[r["post"]], -i)
            if (name, k) not in best or rank < best[(name, k)][:2]:
                best[(name, k)] = (*rank, v, r["post"])
    fields: Dict[str, Any] = {}
    for name, by in posts.items():
        k = min(by, key=lambda k: (-len(by[k]), best[(name, k)][:2]))
        _o, _i, v, post = best[(name, k)]
        fields[name] = {"value": v.get("value"), "quote": v.get("quote"), "post": post,
                        **({"page": v["page"]} if v.get("page") else {})}
    return fields


def remerge(cur: Any, track_id: str, thing: str, *, root: Optional[Dict[str, str]] = None) -> None:
    """A thing's fields again from its reports (`merged_fields`), its first and last post dates (publication).
    `root`: the track's `roots`, when the caller read them."""
    rs = reports(cur, track_id, [thing], root=root).get(thing, [])
    if not rs:
        return
    fields = merged_fields(rs)
    ats = [r["at"] for r in rs if r["at"] is not None]
    cur.execute("""UPDATE mx_track_things SET fields = %s::jsonb, first_at = %s, last_at = %s, updated_at = now()
                    WHERE id = %s""",
                (json.dumps(fields, ensure_ascii=False), min(ats) if ats else None, max(ats) if ats else None, thing))


def merge(cur: Any, track_id: str, keep: str, gone: str, by: str, *, root: Optional[Dict[str, str]] = None) -> bool:
    """`gone` joined into `keep` (both current roots of the track, two of one kind): a status, its reports read as
    `keep`'s from then on. `root`: the track's `roots` read once by the caller, kept up to date here."""
    root = roots(cur, track_id) if root is None else root
    keep, gone = root.get(keep, keep), root.get(gone, gone)
    if keep == gone:
        return False
    cur.execute("""UPDATE mx_track_things g SET status = 'merged', merged_into = %s, merged_by = %s, updated_at = now()
                     FROM mx_track_things k
                    WHERE g.id = %s AND k.id = %s AND g.track_id = %s AND k.track_id = g.track_id AND k.kind = g.kind
                      AND g.status = 'current' AND k.status = 'current'""", (keep, by, gone, keep, track_id))
    if not cur.rowcount:
        return False
    _joined(root, keep, gone)
    remerge(cur, track_id, keep, root=root)
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
    """The entities a thing names: a mention of a reporting post whose name (or span) is the thing's own name (its
    first field); a practice: every mention whose span is inside one of its quotes."""
    out: Set[str] = set()
    for r in rs:
        vals = r["values"] or {}
        if kind["kind"] == PRACTICE_KIND:
            quotes = [f" {key_text(v.get('quote'))} " for v in vals.values() if isinstance(v, dict)]
            out |= {root for root, _nk, span in ments.get(r["post"], []) if span and any(f" {span} " in q for q in quotes)}
            continue
        first = kind["fields"][0]["name"]   # its name only (a shared hardware or maker is not the thing)
        keys = {key_text(vals[first].get("value"))} if isinstance((vals.get(first) or {}).get("value"), str) else set()
        keys.discard("")
        out |= {root for root, nk, span in ments.get(r["post"], []) if nk in keys or key_text(span) in keys}
    return out


def _kinds(cur: Any, track_id: str) -> Dict[str, Dict[str, Any]]:
    s = current_schema(cur, track_id)
    kinds = {k["kind"]: k for k in (s["schema"]["kinds"] if s else [])}
    kinds.setdefault(PRACTICE_KIND, PRACTICE)
    return kinds


def entity_join(cur: Any, track: Dict[str, Any]) -> int:
    """Two current things of one kind (not practices) naming the same entity, their other keys agreeing
    (`keys_agree`: one model on two machines stays two rows): the newer joined into the older. How many joins."""
    tid = track["folder_id"]
    kinds = _kinds(cur, tid)
    things = [t for t in current(cur, tid) if t["kind"] != PRACTICE_KIND and t["kind"] in kinds]
    if len(things) < 2:
        return 0
    root = roots(cur, tid)
    rs = reports(cur, tid, [t["id"] for t in things], root=root)
    ments = _mentions(cur, sorted({r["post"] for v in rs.values() for r in v}))
    keys = {t["id"]: other_keys(kinds[t["kind"]], t["fields"] or {}) for t in things}
    first: Dict[Tuple[str, str], List[str]] = defaultdict(list)
    joined = 0
    for t in sorted(things, key=lambda t: (t["found_at"], t["id"])):
        ents = sorted(named_entities(kinds[t["kind"]], rs.get(t["id"], []), ments))
        into = next((o for e in ents for o in first[(t["kind"], e)] if keys_agree(keys[o], keys[t["id"]])), None)
        if into is not None:
            joined += merge(cur, tid, into, t["id"], "entity", root=root)
            continue
        for e in ents:
            first[(t["kind"], e)].append(t["id"])
    return joined


def refresh(cur: Any) -> Dict[str, Any]:
    """The jobs process's pass (before the briefs are kept): the entity joins of each topic track. {track: joins};
    nothing while off."""
    from insight_core.markx import tracks
    if not on():
        return {}
    return {t["folder_id"]: n for t in tracks.described(cur) if (n := entity_join(cur, t))}


def same_input(track: Dict[str, Any], a: Dict[str, Any], b: Dict[str, Any],
               kind: Optional[Dict[str, Any]] = None, *, same_post: bool = False) -> str:
    """A same-thing question (track-same-v2): the track, the kind, rows A and B (each filled field), and whether one
    post gave both."""
    kind = kind or PRACTICE

    def line(tag: str, t: Dict[str, Any]) -> str:
        f = t["fields"] or {}
        return f"{tag}: " + " | ".join(f"{x['name']}: {shown_value(x, f[x['name']]['value'])}" for x in kind["fields"]
                                       if x["name"] in f)
    return "\n".join(header(track)[:2] + [f"KIND: {kind['kind']}: {kind.get('about') or ''}",
                                          "FROM: " + ("one post gave both" if same_post else "two posts"),
                                          "", line("A", a), line("B", b)])


def same_pairs(kind: Dict[str, Any], things: Sequence[Dict[str, Any]], rs: Dict[str, List[Dict[str, Any]]],
               ments: Dict[str, List[Tuple[str, str, str]]], *, only: Optional[Set[str]] = None,
               skip: Optional[Set[Tuple[str, str]]] = None) -> List[Tuple[str, str, bool]]:
    """The pairs of one kind's current rows worth a same-thing question, closest names first, SAME_PAIRS at most:
    [(a, b, one post gave both)]. Practices: their quotes name a shared entity. Other kinds: a shared entity, a shared
    link, or a shared rare word. A pair from one post is asked too (a post read in windows gives its thing twice).
    `only`: the pairs with one of these rows (against every row); `skip`: pairs (a < b) left out before the cap."""
    named = {t["id"]: named_entities(kind, rs.get(t["id"], []), ments) for t in things}
    posts = {t["id"]: {r["post"] for r in rs.get(t["id"], [])} for t in things}
    names = {t["id"]: name_of(kind, t["fields"] or {}) for t in things}
    links = {t["id"]: set().union(*[links_of(kind, r["values"] or {}) for r in rs.get(t["id"], [])] or [set()])
             for t in things}
    rare = rare_words(names.values())
    words = {t: name_words(n) & rare for t, n in names.items()}
    out = []
    ids = sorted(names)
    lead = ids if only is None else sorted(set(ids) & set(only))
    for x0 in lead:
        for y0 in ids:
            if y0 == x0 or (y0 < x0 and (only is None or y0 in only)):
                continue   # each pair once: (a, b) with a < b, a pair of two `only` rows from its smaller one
            x, y = min(x0, y0), max(x0, y0)
            if skip and (x, y) in skip:
                continue
            if kind["kind"] == PRACTICE_KIND:
                close = 1.0 if named[x] & named[y] else 0.0
            else:
                shared = words[x] & words[y]
                close = (len(shared) / max(1, len(words[x] | words[y])) + bool(named[x] & named[y])
                         + bool(links[x] & links[y] and shared))
            if close > 0:
                out.append((close, x, y, bool(posts[x] & posts[y])))
    out.sort(key=lambda c: (-c[0], c[1], c[2]))
    return [(x, y, one) for _c, x, y, one in out[:SAME_PAIRS]]


SAME_PASS = "markx:track_same_pass:"   # v10.42: system_settings key (+ track id): {"at"} of its last complete pass
SAME_OVERLAP = timedelta(minutes=10)   # a row changed by a transaction still open at a pass is paired at the next


def plan_same(cur: Any, **_kw: Any) -> int:
    """A `track_same` question for each pair `same_pairs` finds that was never asked (under any guide of the kind),
    SAME_OPEN waiting at most: how many were added. Incremental: only the rows new or changed (updated_at) since the
    track's last complete pass are paired, against every row; a track with none is not read."""
    from insight_core.db.repo_operations import SystemSettingsRepository as Settings
    from insight_core.markx import repo, schemas, tracks
    if not on():
        return 0
    schemas.ensure_guides(cur)
    cur.execute("SELECT count(*), now() FROM mx_tasks WHERE kind = %s AND status IN ('open', 'leased')", (SAME_KIND,))
    waiting, now = cur.fetchone()
    room = SAME_OPEN - waiting
    added = 0
    for t in tracks.described(cur):
        if room <= 0:
            break
        tid = str(t["folder_id"])
        got = Settings.get(cur, SAME_PASS + tid)
        since = (got[0] or {}).get("at") if got else None
        cur.execute("""SELECT id::text FROM mx_track_things WHERE track_id = %s AND status = 'current'
                          AND (%s::timestamptz IS NULL OR updated_at >= %s::timestamptz)""", (tid, since, since))
        changed = {r[0] for r in cur.fetchall()}
        if not changed:
            continue
        kinds = _kinds(cur, t["folder_id"])
        rows = [x for x in current(cur, t["folder_id"]) if x["kind"] in kinds]
        complete = True
        if len(rows) >= 2:
            rs = reports(cur, t["folder_id"], [x["id"] for x in rows])
            ments = _mentions(cur, sorted({r["post"] for v in rs.values() for r in v}))
            ids = [x["id"] for x in rows]
            cur.execute("""SELECT a::text, b::text FROM mx_tasks WHERE kind = %s AND guide = ANY(%s)
                              AND (a = ANY(%s::uuid[]) OR b = ANY(%s::uuid[]))""",
                        (SAME_KIND, list(schemas.answer_guides(SAME_KIND)), ids, ids))
            asked = {tuple(sorted(r)) for r in cur.fetchall()}
            by = {x["id"]: x for x in rows}
            for kname, kind in kinds.items():
                mine = [x for x in rows if x["kind"] == kname]
                if len(mine) < 2 or not changed & {x["id"] for x in mine}:
                    continue
                pairs = same_pairs(kind, mine, rs, ments, only=changed, skip=asked)
                complete = complete and len(pairs) < SAME_PAIRS
                for x, y, one in pairs:
                    if room <= 0:
                        complete = False
                        break
                    _tid, new = repo.add_task(cur, kind=SAME_KIND, guide=SAME_GUIDE, subject_kind="thing_thing",
                                              input=same_input(t, by[x], by[y], kind, same_post=one), a=x, b=y)
                    asked.add((x, y))
                    added += new
                    room -= new
        if complete:
            Settings.upsert(cur, SAME_PASS + tid, {"at": (now - SAME_OVERLAP).isoformat()})
    return added


def apply_same(cur: Any, task: Dict[str, Any], answer: Dict[str, Any]) -> bool:
    """A same-thing answer: `same` joins the newer row into the older (both still current, of one kind)."""
    if not answer.get("same"):
        return False
    cur.execute("SELECT id::text, track_id::text, created_at FROM mx_track_things WHERE id = ANY(%s::uuid[])",
                ([str(task["a"]), str(task["b"])],))
    rows = sorted(cur.fetchall(), key=lambda r: (r[2], r[0]))
    if len(rows) != 2 or rows[0][1] != rows[1][1]:
        return False
    return merge(cur, rows[0][1], rows[0][0], rows[1][0], "haiku")


# ---- repair: rows joined by a weak key split, catalogs asked again -----------------------------------------------

CATALOG_ROWS = 5   # rows of one kind that one post alone gave: the post is a catalog read one row an item


def _member_reports(cur: Any, track_id: str, things: Sequence[str], *, root: Optional[Dict[str, str]] = None
                    ) -> Dict[str, List[Dict[str, Any]]]:
    """{root: its reports and its members' [{call, n, thing (its own), post, at, values, url (the post's own address
    when that post gave one thing of the track's kinds)}]}, oldest post first. `root`: the track's `roots`."""
    root = roots(cur, track_id) if root is None else root
    wanted = set(things)
    members = [t for t, r in root.items() if r in wanted]
    if not members:
        return {}
    cur.execute(f"""WITH {_one_thing_posts()}
                    SELECT r.call_id::text, r.n, r.thing_id::text, r.post_id::text, {post_date()}, r.field_values,
                           CASE WHEN one.post_id IS NOT NULL THEN p.url END
                      FROM mx_track_thing_reports r JOIN posts p ON p.id = r.post_id
                      LEFT JOIN one ON one.post_id = r.post_id
                     WHERE r.thing_id = ANY(%s::uuid[])
                     ORDER BY 5 NULLS FIRST, r.created_at, r.call_id, r.n""", (track_id, PRACTICE_KIND, members))
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for call, n, thing, post, at, vals, url in cur.fetchall():
        out[root[thing]].append({"call": call, "n": n, "thing": thing, "post": post, "at": at, "values": vals,
                                 "url": url})
    return out


def regroup(kind: Dict[str, Any], rs: Sequence[Dict[str, Any]], rare: Set[str]) -> List[List[Dict[str, Any]]]:
    """A row's reports in the groups a strong identity makes (`same_identity` with a report already in the group;
    oldest first): one group is one thing."""
    groups: List[List[Tuple[str, Set[str], Dict[str, Set[str]], Dict[str, Any]]]] = []
    for r in rs:
        _t, name, links, keys = _candidate(kind, "", r["values"] or {}, r.get("url"))
        for g in groups:
            if any(same_identity(name, links, n, ls, rare, keys, ks) for n, ls, ks, _r in g):
                g.append((name, links, keys, r))
                break
        else:
            groups.append([(name, links, keys, r)])
    return [[r for _n, _l, _k, r in g] for g in groups]


def repair_plan(cur: Any, track_id: str) -> Dict[str, Any]:
    """What `repair` would do to a track (read only): {splits: [{thing, kind, name, posts, groups: [{name, posts,
    members (member things wholly in the group), moved (the group's other reports)}]}], catalogs: [{post, kind,
    rows}]}. The group holding a row's earliest report stays the row; every other group becomes a thing of its own."""
    kinds = _kinds(cur, track_id)
    by_kind: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in current(cur, track_id):
        if t["kind"] in kinds and t["kind"] != PRACTICE_KIND:
            by_kind[t["kind"]].append(t)
    splits = []
    root = roots(cur, track_id) if by_kind else {}
    for kname, rows in sorted(by_kind.items()):
        kind = kinds[kname]
        rs = _member_reports(cur, track_id, [t["id"] for t in rows], root=root)
        rare = rare_words(name_of(kind, r["values"] or {}) for v in rs.values() for r in v)
        for t in rows:
            mine = rs.get(t["id"], [])
            groups = regroup(kind, mine, rare)
            if len(groups) < 2:
                continue
            of: Dict[str, Set[int]] = defaultdict(set)
            for i, g in enumerate(groups):
                for r in g:
                    of[r["thing"]].add(i)
            out = []
            for i, g in enumerate(groups[1:], 1):
                whole = sorted({r["thing"] for r in g if r["thing"] != t["id"] and of[r["thing"]] == {i}})
                out.append({"name": name_of(kind, g[0]["values"] or {}), "posts": sorted({r["post"] for r in g}),
                            "members": whole,
                            "moved": [(r["call"], r["n"], r["thing"]) for r in g if r["thing"] not in whole]})
            splits.append({"thing": t["id"], "kind": kname, "name": name_of(kind, t["fields"] or {}),
                           "posts": len({r["post"] for r in mine}), "groups": out})
    cur.execute("""SELECT r.post_id::text, t.kind, count(DISTINCT t.id) FROM mx_track_things t
                     JOIN mx_track_thing_reports r ON r.thing_id = t.id
                    WHERE t.track_id = %s AND t.status = 'current' AND t.kind <> %s
                      AND NOT EXISTS (SELECT 1 FROM mx_track_thing_reports o WHERE o.thing_id = t.id
                                         AND o.post_id <> r.post_id)
                    GROUP BY 1, 2 HAVING count(DISTINCT t.id) >= %s ORDER BY 3 DESC, 1""",
                (track_id, PRACTICE_KIND, CATALOG_ROWS))
    catalogs = [{"post": p, "kind": k, "rows": n} for p, k, n in cur.fetchall()]
    return {"splits": splits, "catalogs": catalogs}


def repair(cur: Any, track_id: str, *, dry_run: bool = True, ask: bool = True) -> Dict[str, Any]:
    """A track's rows made one a thing again, never deleting. Each row whose reports are not one thing
    (`repair_plan`) is split: a member thing wholly in another group is current again (split_from), the group's other
    reports move to it or a new thing (moved_from); a split-off thing then joins an older current thing of its
    identity, and every touched row's fields are merged again. A catalog post (CATALOG_ROWS rows only it gave) is asked
    again under the current guide (`ask`; fold_catalog). `dry_run`: the plan only. The plan, with what was done."""
    plan = repair_plan(cur, track_id)
    if dry_run:
        return dict(plan, done=False)
    cur.execute("SELECT id::text, kind, schema_version FROM mx_track_things WHERE track_id = %s", (track_id,))
    meta = {i: (k, v) for i, k, v in cur.fetchall()}
    kinds = _kinds(cur, track_id)
    heads: List[str] = []
    for sp in plan["splits"]:
        for g in sp["groups"]:
            if g["members"]:
                head = g["members"][0]
                cur.execute("""UPDATE mx_track_things SET status = 'current', merged_into = NULL, merged_by = NULL,
                                      split_from = %s, updated_at = now() WHERE id = %s""", (sp["thing"], head))
                for m in g["members"][1:]:
                    cur.execute("UPDATE mx_track_things SET merged_into = %s, updated_at = now() WHERE id = %s",
                                (head, m))
            else:
                kind, version = meta[sp["thing"]]
                cur.execute("""INSERT INTO mx_track_things (track_id, kind, key, schema_version, split_from)
                               VALUES (%s, %s, %s, %s, %s) RETURNING id::text""",
                            (track_id, kind, f"{kinds[kind]['fields'][0]['name']}={g['name']}", version, sp["thing"]))
                head = cur.fetchone()[0]
            for call, n, thing in g["moved"]:
                cur.execute("""UPDATE mx_track_thing_reports SET thing_id = %s, moved_from = COALESCE(moved_from, %s)
                                WHERE call_id = %s AND n = %s""", (head, thing, call, n))
            heads.append(head)
    root = roots(cur, track_id)   # v10.44: read once after the splits, kept up to date by every merge below
    for t in dict.fromkeys([sp["thing"] for sp in plan["splits"]] + heads):
        remerge(cur, track_id, t, root=root)
    rejoined = 0
    epoch_max = datetime.max.replace(tzinfo=timezone.utc)
    of_kind: Dict[str, Any] = {}   # kind: its rows' reports as identities, read once (v10.44: not once a head)
    for h in heads:   # a split-off thing of an older current thing's identity joins it
        cur.execute("SELECT kind, status FROM mx_track_things WHERE id = %s", (h,))
        kname, status = cur.fetchone()
        if status != "current" or root.get(h, h) != h:
            continue
        kind = kinds[kname]
        if kname not in of_kind:
            rs = _member_reports(cur, track_id, [t["id"] for t in current(cur, track_id, kname)], root=root)
            rare = rare_words(name_of(kind, r["values"] or {}) for v in rs.values() for r in v)
            idents = {o: [_candidate(kind, o, r["values"] or {}, r["url"])[1:] for r in v] for o, v in rs.items()}
            firsts = {o: min((r["at"] for r in v if r["at"]), default=epoch_max) for o, v in rs.items()}
            index: Dict[str, Set[str]] = defaultdict(set)   # a name or a link: the rows one of whose reports has it
            for o, ids in idents.items():
                for name, links, _k in ids:
                    for x in [f"name:{name}"] + sorted(links):
                        index[x].add(o)
            of_kind[kname] = (rare, idents, firsts, index)
        rare, idents, firsts, index = of_kind[kname]
        mine = idents.get(h, [])
        first = firsts.get(h, epoch_max)
        near = {root.get(o, o) for name, links, _k in mine for x in [f"name:{name}"] + sorted(links)
                for o in index.get(x, ())} - {h}   # a strong identity needs the same name or a shared link
        for at, other in sorted((firsts[o], o) for o in near if o in idents):
            if at > first:
                break
            if any(same_identity(n, ls, n2, ls2, rare, ks, ks2) for n, ls, ks in mine for n2, ls2, ks2 in idents[other]):
                if merge(cur, track_id, other, h, "key", root=root):
                    rejoined += 1
                    idents[other] = idents[other] + idents.pop(h, [])
                    firsts[other] = min(firsts[other], firsts.pop(h, epoch_max))
                    for name, links, _k in mine:
                        for x in [f"name:{name}"] + sorted(links):
                            index[x].add(other)
                break
    asked = 0
    if ask and plan["catalogs"]:
        from insight_core.markx import tracks
        t = tracks.get(cur, track_id)
        s = current_schema(cur, track_id)
        if t is not None and s is not None:
            asked = ask_posts(cur, t, s, sorted({c["post"] for c in plan["catalogs"]}), room=len(plan["catalogs"]),
                              again=True)
    return dict(plan, done=True, rejoined=rejoined, asked=asked)


def after_answer(cur: Any, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> None:
    """tasks.record's part: a schema stored, a post's things reported, two practices joined."""
    if task["kind"] == SCHEMA_KIND:
        apply_schema(cur, task, answer)
    elif task["kind"] == THINGS_KIND:
        apply_things(cur, task, call_id, answer)
    elif task["kind"] == SAME_KIND:
        apply_same(cur, task, answer)
