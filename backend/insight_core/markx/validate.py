"""Mark X Shadow's checks on an answer before it is stored as valid (issue 0086 C's table).

    answer, error = check(kind, answer, input)

`error` is None for a valid answer, else one short English sentence saying the first thing wrong; the
worker sees it, and mx_tasks.last_error keeps it. `answer` is the answer as stored: unwrapped when the
model put it under one key named for it ({"reading": {..}}, {"card": {..}}, {"answer": {..}}).

Two layers:
  1. the kind's JSON schema (markx/schemas.py; the worker checks the same before it posts): the shape,
     the sets (kind, events, relation, entity type and role), the counts (at most 20 entities, 7 lines);
  2. what only the input can tell (0086 C): an entity's span and version occur in the post; a headline's
     or a briefing line's figures and versions occur in the members it was written from; a briefing line
     cites keys the day has; a card's odd members are members; a translation keeps the post's numbers and
     a length within 0.5-2x.

Text is compared folded (NFKC, case, every dash as '-', ё as е, runs of space as one), as the prototype's
checks did (0090: 415/415 spans and 50/51 versions passed them).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

from insight_core.markx import schemas

WRAPPERS = {"read": ("reading", "answer"), "card": ("card", "answer")}

# ---- folding ---------------------------------------------------------------------------------------

_DASHES = re.compile(r"[‐-―−⁃﹘﹣－]")
_SOFT = "­"
_SPACE = re.compile(r"\s+")
_SEP = re.compile(r"[\s\-_]+")


def fold(text: Optional[str]) -> str:
    """Text as the checks compare it: NFKC, casefolded, ё as е, every dash as '-', no soft hyphen, runs of
    space as one."""
    s = unicodedata.normalize("NFKC", text or "").replace(_SOFT, "").casefold().replace("ё", "е")
    return _SPACE.sub(" ", _DASHES.sub("-", s))


def occurs(span: str, text: str) -> bool:
    return fold(span).strip() in fold(text)


def version_occurs(version: str, text: str) -> bool:
    """A version is found when its folded characters, separators dropped, occur in the text's ("4.1" in
    "V4.1-Flash", "K3.1" in "Kimi K3.1")."""
    return _SEP.sub("", fold(version)) in _SEP.sub("", fold(text))


# Figures and versions as the prototype's auto-checks read them (bg.py: digits, figures_found, versions), with
# one change: a figure is digits, thousands groups ("1 000", "1,000") and a decimal part ("2,5", "4.1"), so
# two figures a comma and a space apart ("$20, 27B") stay two, and a figure never runs across a line.
_FIGURE = re.compile(r"\d+(?:[ \u00a0\u202f.,]\d{3}(?!\d))*(?:[.,]\d+)?")
_VERSION = re.compile(r"\b[A-Za-z]+[-_‐‑]?\d+(?:\.\d+)+[A-Za-z]?\b|\b[A-Z][\w]*[ ]\d+(?:\.\d+)+\b|\bv\d+(?:\.\d+)+\b")


def figures(text: Optional[str]) -> List[str]:
    """Each figure as its bare digits ('1 000' -> '1000', '2,5' -> '25', '$500bn' -> '500')."""
    out = []
    for m in _FIGURE.finditer(text or ""):
        d = re.sub(r"\D", "", m.group(0))
        if d:
            out.append(d)
    return out


def missing_figures(claim: Optional[str], evidence: Optional[str]) -> List[str]:
    """The claim's figures the evidence doesn't hold: a figure counts when it is one of the evidence's, or
    (three digits or more) occurs in the evidence's digits run together."""
    have = set(figures(evidence))
    bare = re.sub(r"\D", "", evidence or "")
    return [d for d in figures(claim) if d not in have and (len(d) < 3 or d not in bare)]


def versions(text: Optional[str]) -> List[str]:
    """Product versions as written ('GPT-5.6', 'K3.1', 'Opus 5.5', 'v0.7.0'), not bare figures."""
    return _VERSION.findall(text or "")


def words(text: Optional[str]) -> int:
    return len((text or "").split())


# ---- the schema subset (the worker's, scripts/markx-worker) ----------------------------------------

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def _is(value: Any, t: str) -> bool:
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES.get(t, object))


def schema_error(schema: Any, value: Any, path: str = "answer") -> Optional[str]:
    """The first way `value` breaks `schema`, or None."""
    if schema is None or schema is True:
        return None
    if schema is False:
        return f"{path}: not allowed"
    if not isinstance(schema, dict):
        return None
    t = schema.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_is(value, x) for x in ts):
            return f"{path}: not {'/'.join(ts)}"
    if "const" in schema and value != schema["const"]:
        return f"{path}: not {schema['const']!r}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: {value!r} is not one of {', '.join(map(str, schema['enum']))}"
    for key in ("anyOf", "oneOf"):
        if key in schema and all(schema_error(s, value, path) for s in schema[key]):
            errors = [schema_error(s, value, path) for s in schema[key]]
            return min(errors, key=len)
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            return f"{path}: empty" if schema.get("minLength") == 1 else f"{path}: shorter than {schema['minLength']}"
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            return f"{path}: longer than {schema['maxLength']}"
        if "pattern" in schema and not re.search(schema["pattern"], value):
            return f"{path}: {value!r} is not in the expected form"
    if _is(value, "number"):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path}: below {schema['minimum']}"
        if "maximum" in schema and value > schema["maximum"]:
            return f"{path}: above {schema['maximum']}"
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            return f"{path}: fewer than {schema['minItems']} items"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path}: {len(value)} items, more than {schema['maxItems']}"
        if isinstance(schema.get("items"), dict):
            for n, v in enumerate(value):
                err = schema_error(schema["items"], v, f"{path}[{n}]")
                if err:
                    return err
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                return f"{path}: {k} missing"
        props = schema.get("properties") or {}
        for k, v in value.items():
            if k in props:
                err = schema_error(props[k], v, f"{path}.{k}")
            elif "additionalProperties" in schema:
                err = schema_error(schema["additionalProperties"], v, f"{path}.{k}")
            else:
                err = None
            if err:
                return err
    return None


# ---- the checks per kind ---------------------------------------------------------------------------

def _read(a: Dict[str, Any], _input: str) -> Optional[str]:
    if (a["events"] == "none") != (a["main"] is None):
        return ("main must be null when events is none" if a["events"] == "none"
                else f"main is null but events is {a['events']}")
    if a["main"] is not None and words(a["main"].get("headline_en")) > schemas.READ_HEADLINE_WORDS:
        return f"main.headline_en has {words(a['main']['headline_en'])} words, more than {schemas.READ_HEADLINE_WORDS}"
    return None


def _entities(a: Dict[str, Any], input: str) -> Optional[str]:
    for n, e in enumerate(a["entities"]):
        if not occurs(e["span"], input):
            return f"entities[{n}].span {e['span']!r} does not occur in the post"
        version = e.get("version")
        if version not in (None, "") and not version_occurs(str(version), input):
            return f"entities[{n}].version {version!r} does not occur in the post"
    return None


def _story_headline(text: str, input: str, field: str) -> Optional[str]:
    if words(text) > schemas.STORY_HEADLINE_WORDS:
        return f"{field} has {words(text)} words, more than {schemas.STORY_HEADLINE_WORDS}"
    for v in versions(text):
        if not version_occurs(v, input):
            return f"{field}: the version {v!r} occurs in no member"
    miss = missing_figures(text, input)
    if miss:
        return f"{field}: the figure {miss[0]} occurs in no member"
    return None


_CARD_ID = re.compile(r"^- id (\S+) \[", re.M)


def _card(a: Dict[str, Any], input: str) -> Optional[str]:
    if words(a["headline_en"]) > schemas.STORY_HEADLINE_WORDS:
        return f"headline_en has {words(a['headline_en'])} words, more than {schemas.STORY_HEADLINE_WORDS}"
    ids = set(_CARD_ID.findall(input))
    for odd in a.get("odd") or []:
        if str(odd).strip() not in ids and not any(i.startswith(str(odd).strip()) or str(odd).startswith(i) for i in ids):
            return f"odd names {odd!r}, not a member"
    return None


def _headline(a: Dict[str, Any], input: str) -> Optional[str]:
    return _story_headline(a["headline_en"], input, "headline_en")


_KEY_LINE = re.compile(r"^\[(s\d+)\]", re.M)


def day_blocks(input: str) -> Dict[str, str]:
    """A briefing's input by story key: {"s1": its lines, ...} (a block runs from its "[sN]" line to the next)."""
    marks = list(_KEY_LINE.finditer(input))
    return {m.group(1): input[m.start(): marks[i + 1].start() if i + 1 < len(marks) else len(input)]
            for i, m in enumerate(marks)}


def _briefing(a: Dict[str, Any], input: str) -> Optional[str]:
    blocks = day_blocks(input)
    lo, hi = min(schemas.BRIEFING_LINES[0], len(blocks)), schemas.BRIEFING_LINES[1]
    n = len(a["lines"])
    if not lo <= n <= hi:
        return f"{n} lines; the day has {len(blocks)} stories, so {lo} to {hi}" if lo != hi else f"{n} lines, not {lo}"
    for i, line in enumerate(a["lines"]):
        cited = [str(k).strip("[] ") for k in line["stories"]]
        unknown = [k for k in cited if k not in blocks]
        if unknown:
            return f"lines[{i}] cites {unknown[0]!r}, not a story of the day"
        evidence = "\n".join(blocks[k] for k in cited)
        miss = missing_figures(line["text"], evidence)
        if miss:
            return f"lines[{i}]: the figure {miss[0]} occurs in none of its stories ({', '.join(cited)})"
    return None


_LABEL = re.compile(r"^(Title|Text): ?", re.M)


def _translate(a: Dict[str, Any], input: str) -> Optional[str]:
    source = _LABEL.sub("", input).strip()
    out = (a["title_en"] + "\n" + a["text_en"]).strip()
    miss = missing_figures(source, out)
    if miss:
        return f"the number {miss[0]} of the post is not in the translation"
    lo, hi = schemas.TRANSLATE_LENGTH
    ratio = len(out) / max(1, len(source))
    if not lo <= ratio <= hi:
        return f"the translation is {ratio:.2f}x the post's length, outside {lo}-{hi}x"
    return None


CHECKS = {"read": _read, "entities": _entities, "card": _card, "headline": _headline, "briefing": _briefing,
          "translate": _translate}


def unwrap(kind: str, answer: Any) -> Any:
    if isinstance(answer, dict) and len(answer) == 1:
        (key, inner), = answer.items()
        if key in WRAPPERS.get(kind, ("answer",)) and isinstance(inner, dict):
            return inner
    return answer


def check(kind: str, answer: Any, input: str) -> Tuple[Any, Optional[str]]:
    """(the answer as stored, None) when it is valid; (the answer, why not) otherwise."""
    spec = schemas.KINDS.get(kind)
    if spec is None:
        return answer, f"unknown task kind {kind!r}"
    answer = unwrap(kind, answer)
    if not isinstance(answer, dict):
        return answer, "answer: not an object"
    err = schema_error(spec.schema, answer)
    if err:
        return answer, err
    extra = CHECKS.get(kind)
    return answer, extra(answer, input) if extra else None
