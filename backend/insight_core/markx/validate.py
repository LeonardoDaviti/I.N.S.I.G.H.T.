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

Text is compared folded (NFKC, case, every dash as '-', ё as е, typographic apostrophes and quotes as plain ones,
runs of space as one), as the prototype's
checks did (0090: 415/415 spans and 50/51 versions passed them).
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from insight_core.markx import schemas

WRAPPERS = {"read": ("reading", "answer"), "read3": ("reading", "answer"), "card": ("card", "answer")}

# ---- folding ---------------------------------------------------------------------------------------

_DASHES = re.compile(r"[‐-―−⁃﹘﹣－]")
_SOFT = "­"
_QUOTES = str.maketrans({"’": "'", "‘": "'", "”": '"', "“": '"'})   # typographic as plain (0121 Decided 6)
_SPACE = re.compile(r"\s+")
_SEP = re.compile(r"[\s\-_]+")


def fold(text: Optional[str]) -> str:
    """Text as the checks compare it: NFKC, casefolded, ё as е, every dash as '-', ’ ‘ as ' and ” “ as ", no soft
    hyphen, runs of space as one."""
    s = unicodedata.normalize("NFKC", text or "").replace(_SOFT, "").translate(_QUOTES).casefold().replace("ё", "е")
    return _SPACE.sub(" ", _DASHES.sub("-", s))


# The text side of occurs/version_occurs, folded once: one answer's checks ask its input once per entity (up to 20,
# and salvage again), and folding a long input is most of a check's time (0243: 90% of an entities check).
@lru_cache(maxsize=8)
def _folded(text: Optional[str]) -> str:
    return fold(text)


@lru_cache(maxsize=8)
def _bare(text: Optional[str]) -> str:
    return _SEP.sub("", fold(text))


def occurs(span: str, text: str) -> bool:
    return fold(span).strip() in _folded(text)


def version_occurs(version: str, text: str) -> bool:
    """A version is found when its folded characters, separators dropped, occur in the text's ("4.1" in
    "V4.1-Flash", "K3.1" in "Kimi K3.1")."""
    return _SEP.sub("", fold(version)) in _bare(text)


# Figures and versions as the prototype's auto-checks read them (bg.py: digits, figures_found, versions), with
# one change: a figure is digits, thousands groups ("1 000", "1,000") and a decimal part ("2,5", "4.1"), so
# two figures a comma and a space apart ("$20, 27B") stay two, and a figure never runs across a line.
_FIGURE = re.compile(r"\d+(?:[ \u00a0\u202f.,]\d{3}(?!\d))*(?:[.,]\d+)?")
_VERSION = re.compile(r"\b[A-Za-z]+[-_‐‑]?\d+(?:\.\d+)+[A-Za-z]?\b|\b[A-Z][\w]*[ ]\d+(?:\.\d+)+\b|\bv\d+(?:\.\d+)+\b")


def figures(text: Optional[str]) -> List[str]:
    """Each figure as its bare digits, no leading zero ("1 000" -> "1000", "2,5" -> "25", "$500bn" -> "500", "02" -> "2")."""
    out = []
    for m in _FIGURE.finditer(text or ""):
        d = re.sub(r"\D", "", m.group(0)).lstrip("0") or "0"   # "02" is 2
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
            # say what is wrong inside the branch of the value's own type ("main.actors: ..."), not "main: not null"
            errors = [schema_error(s, value, path) for s in schema[key]]
            typed = [e for s, e in zip(schema[key], errors)
                     if not (isinstance(s, dict) and "type" in s and schema_error({"type": s["type"]}, value, path))]
            return (typed or errors)[0]
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


def _entity_error(e: Dict[str, Any], input: str) -> Optional[str]:
    """What is wrong with one entities entry against its post (the server's rule: `_entities` and `salvage` use it)."""
    if e.get("role") == "recommended" and e.get("type") != "document":   # 0133: a recommended work is a document
        return f"role recommended on a {e.get('type')}: only a document is recommended"
    if not occurs(e["span"], input):
        return f"span {e['span']!r} does not occur in the post"
    version = e.get("version")
    if version not in (None, "") and not version_occurs(str(version), input):
        return f"version {version!r} does not occur in the post"
    return None


def _cite_error(e: Dict[str, Any], input: str) -> Optional[str]:
    """What is wrong with one cite entry against its post."""
    if e["type"] != "document" and e["role"] != "source":
        return f"role {e['role']} on a {e['type']}: an org or a person is a source only"
    if not occurs(e["span"], input):
        return f"span {e['span']!r} does not occur in the post"
    return None


def _entities(a: Dict[str, Any], input: str) -> Optional[str]:
    for n, e in enumerate(a["entities"]):
        err = _entity_error(e, input)
        if err:
            return f"entities[{n}].{err}"
    return None


def _cite(a: Dict[str, Any], input: str) -> Optional[str]:   # 0133 v4.2: the second question
    for n, e in enumerate(a["entities"]):
        err = _cite_error(e, input)
        if err:
            return f"entities[{n}].{err}"
    return None


# ---- v10.20 (entity waste): a list's bad entries dropped, the rest kept -------------------------------------------
# One entry with a span or a version not in the post, a value outside a set, or past the 20th refused the whole
# answer, which was asked again (up to three tries). Now each entry of an entity list is checked alone and only the
# bad ones are dropped; each dropped entry is kept in the stored answer under "dropped" ({list, item, why}), so
# nothing the model said is lost (keep everything). An answer whose every entity was dropped stays invalid (asked
# again, as before): an empty set from a non-empty answer is a wrong reading, not a post that names nothing.
# {kind: {list key: the entry's own check against the post (None: its schema alone)}}; the first list is the entities.
SALVAGE = {"entities": {"entities": _entity_error, "relations": None},
           "cite": {"entities": _cite_error},
           "reading": {"entities": _entity_error}}   # 0212: ent-v5's entities section, entry by entry as 0213's
SUBJECT_KINDS = ("entities", "reading")              # kinds whose answer must keep a subject it named
DROPPED = "dropped"


def salvage(kind: str, answer: Any, input: str, guide: Optional[str] = None) -> Any:
    """The answer with its bad list entries dropped (each kept under "dropped" with why), for a kind in SALVAGE. Any
    other answer, or a list that is not a list of objects, is left as it is (`check` refuses it as before)."""
    if kind == "track_things" and isinstance(answer, dict):   # 0245: value by value (track_things.salvage)
        from insight_core.markx import track_things
        return track_things.salvage(answer, input or "")
    lists = SALVAGE.get(kind)
    if not lists or not isinstance(answer, dict):
        return answer
    if kind == "reading":   # 0212: a later window's reading is the first window's job (kept under "dropped")
        answer = reading_window(answer, input)
    props = (schemas.schema_for(kind, guide) or {}).get("properties") or {}
    before = list(answer.get(DROPPED) or [])
    out, dropped = dict(answer), list(before)
    for key, rule in lists.items():
        items = answer.get(key)
        spec = props.get(key) or {}
        if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
            continue
        kept = []
        for n, item in enumerate(items):
            why = schema_error(spec.get("items"), item, f"{key}[{n}]")
            if why is None and rule is not None:
                try:
                    why = rule(item, input or "")
                except (KeyError, TypeError, AttributeError) as e:
                    why = f"unreadable ({e})"
                why = why and f"{key}[{n}].{why}"
            if why is None and "maxItems" in spec and len(kept) >= spec["maxItems"]:
                why = f"{key}[{n}]: past entry {spec['maxItems']}"
            if why is None:
                kept.append(item)
            else:
                dropped.append({"list": key, "item": item, "why": why})
        out[key] = kept
    if len(dropped) > len(before):
        out[DROPPED] = dropped
    return out


def salvage_refused(kind: str, answer: Dict[str, Any]) -> Optional[str]:
    """Why a salvaged answer is still asked again, or None: it kept none of the entities it gave (SALVAGE[kind]'s
    first list), or (entities) every subject it named was dropped: a post whose subject is a named thing never ends
    without it (ent-v4.2's rule), and on the lab's posts asked seven times a re-ask named a dropped entity validly 16
    times in 28."""
    key = next(iter(SALVAGE.get(kind) or {}), None)
    if key is None:
        return None
    gone = [d for d in answer.get(DROPPED) or [] if isinstance(d, dict) and d.get("list") == key]
    if not gone:
        return None
    kept = answer.get(key) or []
    if not kept:
        return "every entity was dropped: " + "; ".join(str(d.get("why")) for d in gone[:3])
    subjects = [d for d in gone if isinstance(d.get("item"), dict) and d["item"].get("role") == "subject"]
    if kind in SUBJECT_KINDS and subjects and not any(isinstance(e, dict) and e.get("role") == "subject" for e in kept):
        return "every subject was dropped: " + "; ".join(str(d.get("why")) for d in subjects[:3])
    return None


_VERSION_NUMBER = re.compile(r"\d+(?:\.\d+)+")


def version_number_occurs(version: str, text: str) -> bool:
    """A headline's version is found when its number occurs in the text as a number ("GPT-5.6" in "their 5.6
    versions"): the name around it may be the story's family, said once (measured on the recorded headlines)."""
    m = _VERSION_NUMBER.search(version)
    if not m:
        return version_occurs(version, text)
    return re.search(r"(?<![\d.])" + re.escape(m.group(0)) + r"(?!\d|\.\d)", text) is not None


def _story_headline(text: str, input: str, field: str, limit: int = schemas.STORY_HEADLINE_WORDS) -> Optional[str]:
    if words(text) > limit:
        return f"{field} has {words(text)} words, more than {limit}"
    for v in versions(text):
        if not version_number_occurs(v, input):
            return f"{field}: the version {v!r} occurs in no member"
    miss = missing_figures(text, input)
    if miss:
        return f"{field}: the figure {miss[0]} occurs in no member"
    return None


_CARD_ID = re.compile(r"^- id (\S+) \[", re.M)


def _card(a: Dict[str, Any], input: str) -> Optional[str]:
    if words(a["headline_en"]) > schemas.STORY_HEADLINE_WORDS:
        return f"headline_en has {words(a['headline_en'])} words, more than {schemas.STORY_HEADLINE_WORDS}"
    # `odd` names members by the 8-character id the input shows. An answer that numbers them instead (6 of the 43
    # recorded cards) is kept as given: no decision reads `odd` (the prototype's never did), and a number's base
    # (first member 0 or 1) can't be told, so it is not turned into an id.
    ids = set(_CARD_ID.findall(input))
    for odd in a.get("odd") or []:
        if isinstance(odd, str) and odd.strip() not in ids and not any(i.startswith(odd.strip()) for i in ids):
            return f"odd names {odd!r}, not a member"
    return None


def _headline(a: Dict[str, Any], input: str) -> Optional[str]:
    return _story_headline(a["headline_en"], input, "headline_en", schemas.HEADLINE_WORDS)


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
        # the day's own line ("DAY 2026-10-23: ...") is every story's: its year and date may be cited
        evidence = "\n".join([input.split("\n", 1)[0]] + [blocks[k] for k in cited])
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


_MENTION_LINE = re.compile(r"^(\d+)\. written ", re.M)


def collide_mentions(input: str) -> int:
    """How many numbered mentions a collision question shows."""
    return len(_MENTION_LINE.findall(input))


def _collide(a: Dict[str, Any], input: str) -> Optional[str]:
    """0119 A1 (the lab's valid_for): every mention number appears once, in one sense or in `unclear`; `related` links
    senses by their 1-based positions."""
    n = collide_mentions(input)
    seen: List[int] = []
    for s in a["senses"]:
        seen += [int(x) for x in s["m"]]
    seen += [int(x) for x in a.get("unclear") or []]
    if sorted(seen) != list(range(1, n + 1)):
        return f"the senses and unclear name mentions {sorted(seen)}, not each of 1-{n} once"
    for r in a.get("related") or []:
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in r[:2]):
            return f"related {r!r}: two sense positions"
        if not (1 <= r[0] <= len(a["senses"]) and 1 <= r[1] <= len(a["senses"])):
            return f"related {r!r} names a sense that isn't one (1-{len(a['senses'])})"
    return None


def _collide_makers(a: Dict[str, Any], input: str) -> Optional[str]:
    """0250 (collide-makers-v1): a verdict needs its evidence (a reason of spaces is none)."""
    return None if str(a.get("evidence") or "").strip() else "evidence: empty"


def _relate(a: Dict[str, Any], input: str) -> Optional[str]:
    """0131: the judge's reason is its evidence (three of them on an edge): a reason of spaces is none."""
    return None if str(a.get("reason") or "").strip() else "reason: empty"


# 0258 (judge-read-v2, join and pair): the answer quotes the POST it judged, and maybe the STORY. The question is
# tasks.render_story + "\n\n" + tasks.render_post: the STORY block, then "POST", the platform line, "Title: ", "Text: "
# (its lines), "Links: " and "Reading of the post: " (the model's reading, never the post's words).
JUDGE_POST_MARK = "\n\nPOST\nPlatform: "
JUDGE_POST_TAILS = ("\nReading of the post: ", "\nLinks: ")   # the render's last lines, in reverse order
JUDGE_QUOTE_MIN = 12   # folded characters: a shorter quote names too little to be this post's (unless it is all of it)


def judge_blocks(input: str) -> Tuple[str, str]:
    """(the STORY block, the POST's own words: its title and text) of a judge-read question."""
    story, mark, post = (input or "").partition(JUDGE_POST_MARK)
    if not mark:
        return story, ""
    for tail in JUDGE_POST_TAILS:
        head, found, _rest = post.rpartition(tail)
        if found:
            post = head
    _platform, _nl, own = post.partition("\n")
    return story, own


def _own_part(post: str) -> List[str]:
    """The post's title and text, each whole (folded): a quote that is all of a short one needs no length."""
    title, _, text = post.partition("\nText: ")
    return [fold(title.removeprefix("Title: ")).strip(), fold(text).strip()]


def _judge_read(a: Dict[str, Any], input: str) -> Optional[str]:
    """0258: `post_quote` is in this question's POST (its title or text), `story_quote` (when given) in its STORY: an
    answer written from another question of its batch quotes words this one does not show. Only `cant_tell` (a post
    with too little text) may leave the post quote empty."""
    story, post = judge_blocks(input)
    q = fold(a.get("post_quote") or "").strip()
    if not q:
        return None if a.get("relation") == "cant_tell" else "post_quote: empty (copy the post's own words)"
    if q not in fold(post):
        return "post_quote: not in this question's POST title or text"
    if len(q) < JUDGE_QUOTE_MIN and q not in _own_part(post):
        return f"post_quote: shorter than {JUDGE_QUOTE_MIN} characters"
    sq = fold(a.get("story_quote") or "").strip()
    if sq and sq not in fold(story):
        return "story_quote: not in this question's STORY"
    return None


def unquoted(kind: str, answer: Any) -> bool:
    """v10.34: whether an answer of `kind` lacks the post quote its kind's current guide checks (judge-read-v2's, by
    `_judge_read`): one made under an earlier guide (judge-read-v1) cannot be told from an answer written for another
    question of its batch (a reason that describes another post), so decide asks it again before it may change a
    story."""
    spec = schemas.KINDS.get(kind)
    return (spec is not None and GUIDE_CHECKS.get(spec.guide or "") is _judge_read
            and isinstance(answer, dict) and "post_quote" not in answer)


# 0132 B: a stance answer's quotes, checked against the question's numbered posts.
_STANCE_BLOCK = re.compile(r"^\[(\d+)\] ", re.M)
STANCE_MIN_QUOTES = 2


def stance_posts(input: str) -> Dict[int, str]:
    """{number: text} of a stance question's numbered posts ("[3] ...")."""
    marks = list(_STANCE_BLOCK.finditer(input or ""))
    return {int(m.group(1)): input[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(input)]
            for i, m in enumerate(marks)}


def stance_grounded(answer: Any, input: str) -> List[Dict[str, Any]]:
    """The patterns a stance answer may show: each quote found exactly (folded) in the post it names, and 2+ such
    quotes from 2 different posts; at most 4. Each {pattern, kind, strength, quotes [{post, quote}], dropped}."""
    posts = {n: fold(t) for n, t in stance_posts(input).items()}
    out: List[Dict[str, Any]] = []
    for pat in (answer or {}).get("patterns") or []:
        if not isinstance(pat, dict):
            continue
        quotes, dropped = [], 0
        for ev in pat.get("evidence") or []:
            q = ev.get("quote") if isinstance(ev, dict) else None
            n = ev.get("post") if isinstance(ev, dict) else None
            folded = fold(q).strip() if isinstance(q, str) else ""
            if isinstance(n, int) and folded and folded in posts.get(n, ""):
                quotes.append({"post": n, "quote": q.strip()})
            else:
                dropped += 1
        if len(quotes) >= STANCE_MIN_QUOTES and len({q["post"] for q in quotes}) >= 2:
            out.append({"pattern": pat.get("pattern"), "kind": pat.get("kind"), "strength": pat.get("strength"),
                        "quotes": quotes, "dropped": dropped})
    return out[:schemas.STANCE_PATTERNS]


def _stance(a: Dict[str, Any], input: str) -> Optional[str]:
    """Only a post number the question doesn't show is an error; an inexact quote is dropped at use."""
    n = len(stance_posts(input))
    for pat in a["patterns"]:
        for ev in pat["evidence"]:
            if not 1 <= ev["post"] <= n:
                return f"a quote names post {ev['post']}, not one of 1-{n}"
    return None


_BACK_NUMBERED = re.compile(r"^(\d+)\. \[", re.M)


def back_numbered(input: str) -> int:
    """How many new posts a back question numbers (back.numbered; here so this module needs only the standard library,
    0191: the worker imports it)."""
    _, _, tail = (input or "").partition("NEW POSTS")
    return len(_BACK_NUMBERED.findall(tail))


def _back(a: Dict[str, Any], input: str) -> Optional[str]:
    """0136: each verdict names one of the question's new posts, once."""
    n = back_numbered(input)
    seen = set()
    for p in a["posts"]:
        if not 1 <= p["n"] <= n:
            return f"a verdict names post {p['n']}, not one of 1-{n}"
        if p["n"] in seen:
            return f"post {p['n']} has two verdicts"
        seen.add(p["n"])
    return None


def _one_line_why(a: Dict[str, Any]) -> Optional[str]:
    """`why` is one line, at most TRACK_WHY_CHARS."""
    why = a["why"].strip()
    if not why:
        return "why: empty"
    if "\n" in why:
        return "why: one line"
    if len(why) > schemas.TRACK_WHY_CHARS:
        return f"why: at most {schemas.TRACK_WHY_CHARS} characters"
    return None


# 0252: a track verdict is a judgement of ONE post (the guide: `confidence` "how sure you are of your `in`", `why`
# "what the post is, and why ..."). An answer with confidence 0 judged nothing, and a why that names nothing of the post
# ("Not applicable to this track.") could be said of any post: neither is a verdict, and stored they read as "out".
# A word cites the post when the post's own text has it (its title, text, links, quote; never its platform or source
# line: the post's content, not its source) and it is none of the question's own words (the guide's, the track's
# header) nor a function word. Compared by a 5-letter stem, folded; a word of 4+ letters or with a digit. A post with
# fewer than CITE_MIN_WORDS Latin-script words of its own is not checked for a citation (an English why of a post in
# another script may name nothing in its letters).
POST_MARK = "\n\nPOST\n"
CITE_MIN_WORDS = 5
_CITE_WORD = re.compile(r"\w+")
_LATIN = re.compile(r"[a-z]")
_FUNCTION_WORDS = frozenset("""about above after again against also among another anything because been before being
below between both could does doing down during each either else even every from further have having here hers herself
himself into itself just like more most much must neither none nothing only other ours ourselves over same should some
such than that their theirs them themselves then there these they this those through under until upon very what when
where which while whom whose will with within without would your yours yourself https http html www""".split())


def _stem(w: str) -> str:
    return w[:5]


def _cite_words(text: str) -> set:
    return {_stem(w) for w in _CITE_WORD.findall(fold(text))
            if len(w) >= 4 or (len(w) >= 2 and any(c.isdigit() for c in w))}


@lru_cache(maxsize=4)
def _guide_words(kind: str) -> frozenset:
    """The words of every guide of `kind` (its own and its variants): an answer that repeats them cites no post."""
    out: set = set()
    for gid, k in schemas.guide_ids().items():
        if k == kind:
            out |= _cite_words(schemas.guide_body(gid))
    return frozenset(out | {_stem(w) for w in _FUNCTION_WORDS})


def _post_words(input: str) -> Tuple[set, set]:
    """(the post's own words, the question's other words) of a track question (tracks.track_input)."""
    head, _, post = input.partition(POST_MARK)
    own = "\n".join(line for line in post.splitlines()
                     if not line.startswith(("Platform:", "Author:")))
    return _cite_words(own), _cite_words(head)


def track_verdict_error(a: Dict[str, Any], input: Optional[str]) -> Optional[str]:
    """0252: why a `track` answer is no verdict of its post (None: it is one). See POST_MARK's note."""
    if float(a.get("confidence") or 0) <= 0:
        return "confidence: 0 judges nothing; say how sure you are of `in` (above 0)"
    if not input or POST_MARK not in input:
        return None
    own, asked = _post_words(input)
    own -= asked | _guide_words("track")
    if sum(1 for w in own if _LATIN.search(w)) < CITE_MIN_WORDS:
        return None
    if not (_cite_words(a.get("why") or "") & own):
        return "why: it names nothing of this post; say what the post is (its subject, in its words)"
    return None


def _track(a: Dict[str, Any], input: str) -> Optional[str]:
    """0145: `why` is one line, at most TRACK_WHY_CHARS; a post judged in may name its sub-topic. 0252: and the answer
    is a verdict of its post (track_verdict_error)."""
    return _one_line_why(a) or track_verdict_error(a, input)


# v10.41 (track-v3, track-check-v2): a verdict must agree with its own stated fit. Production (v10.38): 34 of Cool 3D
# Projects' top 100 Discover/joined posts were `in` at 0.85-0.9 with a why saying they don't fit ("nothing to do with
# printing"): the model wrote `in` first and its reason after, following the reader's examples. The answer now states
# the post's subject and whether `Belongs:` asks for it BEFORE `in`, and `in` is checked against those fields (never
# against the why's wording): `in` true needs `fits` true, a `matches` quote of `Belongs:` and no `excluded`; a
# quote must be the question's own words (its 5-letter stems all in that part of the header), so `fits` names what
# the reader asked for, not what the post resembles.
_HEADER_PARTS = ("TRACK: ", "Belongs: ", "Not: ", "Sub-topics: ", "Marked in by the reader:", "Marked out by the reader:")


def header_part(input: Optional[str], name: str) -> Optional[str]:
    """The part of a track question's header that starts with `name` ("Belongs: ", "Not: "), up to the next part; None
    when the question has none (tracks.header writes them)."""
    head = "\n" + (input or "").partition(POST_MARK)[0]
    at = head.find("\n" + name)
    if at < 0:
        return None
    body = head[at + 1 + len(name):]
    ends = [i for i in (body.find("\n" + p) for p in _HEADER_PARTS) if i >= 0]
    return body[:min(ends)] if ends else body


def _quotes(quote: Optional[str], part: Optional[str], field: str) -> Optional[str]:
    words = _cite_words(quote or "")
    if not words:
        return f"{field}: copy the words of the track's header it names (at least one word of 4+ letters)"
    if part is not None and not words <= _cite_words(part):
        return f"{field}: copy it from the track's header, its own words (not {sorted(words - _cite_words(part))[:3]})"
    return None


def track_fit_error(a: Dict[str, Any], input: Optional[str]) -> Optional[str]:
    """v10.41: why a track-v3 answer's `in` disagrees with its stated fit (None: it agrees). See _HEADER_PARTS's note."""
    fits, verdict = bool(a.get("fits")), bool(a.get("in"))
    if verdict and not fits:
        return "in: true, but fits is false; the verdict follows the fit you stated (in is false when it does not fit)"
    if verdict and a.get("excluded"):
        return "in: true, but excluded names `Not:`; anything under `Not:` is out"
    if fits:
        if not a.get("matches"):
            return "matches: fits is true, so copy the words of `Belongs:` the subject is an instance of"
        err = _quotes(a.get("matches"), header_part(input, "Belongs: "), "matches")
        if err:
            return err
    elif a.get("matches"):
        return "matches: null when fits is false"
    if a.get("excluded"):
        not_part = header_part(input, "Not: ")
        if input and POST_MARK in input and not_part is None:
            return "excluded: this track has no `Not:`; null"
        return _quotes(a.get("excluded"), not_part, "excluded")
    return None


def _track_v3(a: Dict[str, Any], input: str) -> Optional[str]:
    """v10.41: the track-v2 checks (`_track`; the post is named by its `subject` or its `why`: the subject is the
    answer's own statement of what the post is), and `in` agrees with the fit stated before it (track_fit_error)."""
    named = {**a, "why": f"{a.get('why') or ''} {a.get('subject') or ''}"}
    return _one_line_why(a) or track_verdict_error(named, input) or track_fit_error(a, input)


def _subtopics(a: Dict[str, Any], input: str) -> Optional[str]:
    """0207 (subtopics-v2): each key is one of the question's groups, named once; names are not repeated; a definition
    is one line."""
    from insight_core.markx import track_subtopics
    if "names" not in a:   # a 0145 proposal (subtopics-v1) its own schema checked: nothing applies it any more
        return None
    keys = set(track_subtopics.keys_of(input))
    seen: set = set()
    names: set = set()
    for s in a["names"]:
        if s["key"] not in keys:
            return f"names group {s['key']}, not one of the question's"
        if s["key"] in seen:
            return f"group {s['key']} named twice"
        seen.add(s["key"])
        key = track_subtopics.fold_key(s["name"])
        if not key:
            return "a sub-topic with no name"
        if key in names:
            return f"sub-topic {s['name']!r} twice"
        names.add(key)
        if "\n" in (s.get("definition") or "").strip() or len(s.get("definition") or "") > schemas.SUBTOPIC_DEFINITION_CHARS:
            return f"definition of {s['key']}: one line, at most {schemas.SUBTOPIC_DEFINITION_CHARS} characters"
    return None


def _subtopic_place(a: Dict[str, Any], input: str) -> Optional[str]:
    """0207 (subtopic-place-v1): every post of the question once, each in one of its sub-topics or none."""
    from insight_core.markx import track_subtopics
    subs, posts = track_subtopics.place_keys(input)
    seen = set()
    for p in a["placements"]:
        if p["post"] not in posts:
            return f"places {p['post']}, not one of the question's posts"
        if p["post"] in seen:
            return f"{p['post']} placed twice"
        seen.add(p["post"])
        if p["subtopic"] != "none" and p["subtopic"] not in subs:
            return f"{p['post']} in {p['subtopic']}, not one of the question's sub-topics"
    missing = [p for p in posts if p not in seen]
    return f"{len(missing)} posts not placed ({', '.join(missing[:3])})" if missing else None


def _digest(a: Dict[str, Any], input: str) -> Optional[str]:
    """0207 (digest-v1): each point cites only the question's posts [1..n], each point one line."""
    from insight_core.markx import track_subtopics
    n = track_subtopics.numbered(input)
    for k, p in enumerate(a["points"], 1):
        if "\n" in p["text"].strip():
            return f"point {k}: one line"
        for c in p["cites"]:
            if not 1 <= c <= n:
                return f"point {k} cites post {c}, not one of 1-{n}"
    return None


def _digest_rows(a: Dict[str, Any], input: str) -> Optional[str]:
    """0245 (digest-v2, a track brief): each point one line, citing only the question's rows [1..n], and every figure
    it gives is one of the rows it cites."""
    rows = {int(n): line for n, line in re.findall(r"^\[(\d{1,3})\] (.*)$", input or "", re.M)}
    for k, p in enumerate(a["points"], 1):
        if "\n" in p["text"].strip():
            return f"point {k}: one line"
        for c in p["cites"]:
            if c not in rows:
                return f"point {k} cites row {c}, not one of 1-{len(rows)}"
        have = set(figures(" ".join(rows[c] for c in p["cites"])))
        missing = [f for f in figures(p["text"]) if f not in have]
        if missing:
            return f"point {k}: {missing[0]} is in none of the rows it cites"
    return None


def _track_schema(a: Dict[str, Any], _input: str) -> Optional[str]:
    """0245 (track-schema-v1): kinds and fields named once, each kind's first field its name (a text key)."""
    from insight_core.markx import track_things
    return track_things.schema_error(a)


def _track_fields(a: Dict[str, Any], input: str) -> Optional[str]:
    """v10.41 (track-fields-v1): each field of a kind the question showed, not one it has (track_fields.check)."""
    from insight_core.markx import track_fields
    return track_fields.check(a, input)


def _track_same(a: Dict[str, Any], _input: str) -> Optional[str]:
    """0245 (track-same-v1, v2): the reason is one line."""
    return "why: one line" if "\n" in a["why"].strip() else None


def _probes(a: Dict[str, Any], _input: str) -> Optional[str]:
    """0147: the example posts are distinct; each at most PROBE_CHARS (a longer one is a guide not followed)."""
    seen: set = set()
    for p in list(a["probes"]) + list(a.get("near_misses") or []):
        t = " ".join(p.split()).casefold()
        if not t:
            return "an empty example post"
        if len(t) > schemas.PROBE_CHARS * 2:
            return f"an example post over {schemas.PROBE_CHARS * 2} characters"
        if t in seen:
            return "an example post twice"
        seen.add(t)
    return None


def _scout(a: Dict[str, Any], _input: str) -> Optional[str]:
    """0148: each named source has one line of address (no spaces, at most SCOUT_ADDRESS_CHARS) and is named once;
    `why` is one line."""
    seen: set = set()
    for s in a["sources"]:
        address = (s.get("address") or "").strip()
        if not address or any(c.isspace() for c in address):
            return "a source's address: one address, no spaces"
        if len(address) > schemas.SCOUT_ADDRESS_CHARS:
            return f"a source's address over {schemas.SCOUT_ADDRESS_CHARS} characters"
        key = address.lower().split("://", 1)[-1].removeprefix("www.").rstrip("/")
        if key in seen:
            return "a source named twice"
        seen.add(key)
        why = (s.get("why") or "").strip()
        if "\n" in why or len(why) > schemas.SCOUT_WHY_CHARS:
            return f"a source's why: one line, at most {schemas.SCOUT_WHY_CHARS} characters"
    return None


def _identity(a: Dict[str, Any], input: str) -> Optional[str]:
    """0162: `why` is one line, at most TRACK_WHY_CHARS (the evidence, not an essay)."""
    return _one_line_why(a)


def _websearch(a: Dict[str, Any], _input: str) -> Optional[str]:
    """0171: each candidate one web address (http or https, no spaces, at most WEBSEARCH_URL_CHARS), named once; its
    title and why one line each; each query one line. Whether a candidate is an identity is research's to judge (its
    rules or the `identity` question), never this answer's."""
    seen: set = set()
    for c in a["candidates"]:
        url = (c.get("url") or "").strip()
        if not url.lower().startswith(("http://", "https://")) or any(ch.isspace() for ch in url):
            return "a candidate's url: one http(s) address, no spaces"
        if len(url) > schemas.WEBSEARCH_URL_CHARS:
            return f"a candidate's url over {schemas.WEBSEARCH_URL_CHARS} characters"
        key = url.lower().split("://", 1)[-1].removeprefix("www.").rstrip("/")
        if key in seen:
            return "a candidate named twice"
        seen.add(key)
        for field, most in (("title", schemas.WEBSEARCH_TITLE_CHARS), ("why", schemas.WEBSEARCH_WHY_CHARS)):
            text = (c.get(field) or "").strip()
            if field == "why" and not text:
                return "a candidate's why: empty"
            if "\n" in text or len(text) > most:
                return f"a candidate's {field}: one line, at most {most} characters"
    for q in a["queries"]:
        if "\n" in q.strip() or len(q) > schemas.WEBSEARCH_QUERY_CHARS:
            return f"a query: one line, at most {schemas.WEBSEARCH_QUERY_CHARS} characters"
    return None


_ITEM_ID = re.compile(r"^\[(i\d{1,2})\] ", re.M)


def _source_judge(a: Dict[str, Any], input: str) -> Optional[str]:
    """0173: each reason one line, said once; each example an item the question shows ("[i<n>] ..."), named once."""
    seen: set = set()
    for r in a["reasons"]:
        text = r.strip()
        if not text or "\n" in text:
            return "a reason: one line, not empty"
        if fold(text) in seen:
            return "a reason said twice"
        seen.add(fold(text))
    shown = set(_ITEM_ID.findall(input or ""))
    named: set = set()
    for e in a["examples"]:
        if e not in shown:
            return f"an example names an item the question does not show: {e}"
        if e in named:
            return "an example named twice"
        named.add(e)
    return _item_filter(a.get("filter"), input)


_ITEM_LINE = re.compile(r"^\[(i\d{1,2})\] [^\n]*?· (.*?)(?: tag=(\S+))?$", re.M)


def _item_filter(rule: Any, input: str) -> Optional[str]:
    """0196: a proposed item filter (source-judge-v2's `filter`) checked against the items the question shows
    (utils/item_filter.check: compiles, a shape not one version, never a plain release, hides one item read and none
    of those it keeps); its `keep` names items the question shows."""
    if rule is None:
        return None
    from insight_core.utils import item_filter
    items = [{"id": i, "title": t.strip(), "url": f"https://example.invalid/o/r/releases/tag/{tag}" if tag else None}
             for i, t, tag in _ITEM_LINE.findall(input or "")]
    shown = {i["id"] for i in items}
    for k in rule.get("keep") or []:
        if k not in shown:
            return f"the filter keeps an item the question does not show: {k}"
    if not (rule.get("hide") or []):
        return None
    err = item_filter.check(rule, items, keep=rule.get("keep") or [])
    return f"the filter: {err}" if err else None


def _websearch_official(a: Dict[str, Any], _input: str) -> Optional[str]:
    """0196 (websearch-official-v1): every address one http(s) address, no spaces, named once; each why one line."""
    seen: set = set()
    urls = [c.get("url") for c in a.get("channels") or []]
    if a.get("announcement"):
        urls.append(a["announcement"].get("url"))
    if (a.get("actor") or {}).get("site"):
        urls.append(a["actor"]["site"])
    for url in urls:
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")) or any(ch.isspace() for ch in url):
            return "an address: one http(s) address, no spaces"
    for c in a.get("channels") or []:
        key = c["url"].lower().split("://", 1)[-1].removeprefix("www.").rstrip("/")
        if key in seen:
            return "a channel named twice"
        seen.add(key)
        if "\n" in (c.get("why") or ""):
            return "a channel's why: one line"
    if a.get("official") and not a.get("actor"):
        return "official without an actor"
    return None


_ROW_KEY = re.compile(r"^\[(r\d{1,4})\] ", re.M)
VAGUE_TITLES = {"other", "others", "other news", "misc", "miscellaneous", "various", "everything else", "the rest",
                "more", "more news", "rest"}   # 0174: allowed for OTHER_ROWS rows or fewer only
OTHER_ROWS = 2


def _news_sections(a: Dict[str, Any], input: str) -> Optional[str]:
    """0174: every row the question shows (its "[r<n>] ..." lines) in exactly one section, no other key; titles of at
    most NEWS_SECTION_TITLE_WORDS words, one line, none twice; "Other" (and its like) for OTHER_ROWS rows or fewer."""
    shown = _ROW_KEY.findall(input or "")
    keys = set(shown)
    seen: Dict[str, str] = {}
    titles: set = set()
    for n, s in enumerate(a["sections"]):
        title = s["title"].strip()
        if not title or "\n" in title:
            return f"sections[{n}]: a title is one line, not empty"
        if len(title.split()) > schemas.NEWS_SECTION_TITLE_WORDS:
            return f"sections[{n}]: the title {title!r} has more than {schemas.NEWS_SECTION_TITLE_WORDS} words"
        if fold(title) in titles:
            return f"the title {title!r} is used twice"
        titles.add(fold(title))
        if fold(title).strip(" .") in VAGUE_TITLES and len(s["row_ids"]) > OTHER_ROWS:
            return f"sections[{n}]: {title!r} holds {len(s['row_ids'])} rows (at most {OTHER_ROWS}): give them a real section"
        for k in s["row_ids"]:
            if k not in keys:
                return f"sections[{n}] names {k}, not a row of the question"
            if k in seen:
                return f"{k} is in two sections ({seen[k]!r} and {title!r})"
            seen[k] = title
    missing = [k for k in shown if k not in seen]
    if missing:
        more = f" and {len(missing) - 3} more" if len(missing) > 3 else ""
        return f"{', '.join(missing[:3])}{more} in no section: every row in exactly one"
    return None


_UNIT_KEY = re.compile(r"^\[(u\d{1,3})\] ", re.M)


def _unit_types(a: Dict[str, Any], input: str) -> Optional[str]:
    """0181: every item the question shows (its "[u<n>] ..." lines) answered exactly once, no other key; a headline
    of one line and at most UNIT_HEADLINE_WORDS words (+2, as headlines have)."""
    shown = _UNIT_KEY.findall(input or "")
    keys = set(shown)
    seen: set = set()
    for n, u in enumerate(a["units"]):
        k = u["key"]
        if k not in keys:
            return f"units[{n}] names {k}, not an item of the question"
        if k in seen:
            return f"{k} is answered twice"
        seen.add(k)
        head = u["headline"].strip()
        if not head or "\n" in head:
            return f"{k}: a headline is one line, not empty"
        if len(head.split()) > schemas.UNIT_HEADLINE_WORDS + 2:
            return f"{k}: the headline has more than {schemas.UNIT_HEADLINE_WORDS} words"
    missing = [k for k in shown if k not in seen]
    if missing:
        return f"{', '.join(missing[:3])} not answered: every item once"
    return None


_SECTION_KEY = re.compile(r"^\[(s\d{1,2})\] ", re.M)


def _news_place(a: Dict[str, Any], input: str) -> Optional[str]:
    """0197: every new row the question shows (its "[r<n>] ..." lines) placed exactly once, into a section it shows (its
    "[s<n>] ..." lines) or "new"; no other key."""
    rows, sections = set(_ROW_KEY.findall(input or "")), set(_SECTION_KEY.findall(input or ""))
    seen: set = set()
    for n, p in enumerate(a["placements"]):
        k, s = p["row_id"], p["section"]
        if k not in rows:
            return f"placements[{n}] names {k}, not a new row of the question"
        if k in seen:
            return f"{k} is placed twice"
        seen.add(k)
        if s != "new" and s not in sections:
            return f"placements[{n}]: {s} is not a section of the question (one of them, or \"new\")"
    missing = sorted(rows - seen, key=lambda k: int(k[1:]))
    if missing:
        more = f" and {len(missing) - 3} more" if len(missing) > 3 else ""
        return f"{', '.join(missing[:3])}{more} not placed: every new row exactly once"
    return None


_SHOWN_POST = re.compile(r"^\[(\d+)\] ", re.M)


def _significance(a: Dict[str, Any], input: str) -> Optional[str]:
    """0208: the breakdowns named are posts the question shows (its "[n] ..." lines), each once."""
    shown = {int(n) for n in _SHOWN_POST.findall(input or "")}
    named = list(a.get("breakdowns") or [])
    wrong = sorted({n for n in named if n not in shown})
    if wrong:
        return f"breakdowns name {', '.join(map(str, wrong))}, not a post shown"
    if len(named) != len(set(named)):
        return "a breakdown is named twice"
    return None


_SHOWN_POST = re.compile(r"^\[(\d+)\] ", re.M)


def _significance(a: Dict[str, Any], input: str) -> Optional[str]:
    """0208: the breakdowns named are posts the question shows (its "[n] ..." lines), each once."""
    shown = {int(n) for n in _SHOWN_POST.findall(input or "")}
    named = list(a.get("breakdowns") or [])
    wrong = sorted({n for n in named if n not in shown})
    if wrong:
        return f"breakdowns name {', '.join(map(str, wrong))}, not a post shown"
    if len(named) != len(set(named)):
        return "a breakdown is named twice"
    return None


_EMBEDDED ="an embed task is answered at POST /api/markx/embeddings, not here"
# ---- 0212 (v10.21): ent-v5, one reading of a post (kind `reading`) --------------------------------------------------
# Its entities are checked entry by entry (SALVAGE, 0213); its reading as read-v2's and read-v3's are (`_read`: `event`
# null iff `events` is none, the headline's length). A long post's later window (0176's input line "Window: k of n")
# carries entities only: its `reading` and `event` are set null here (what the model wrote there is kept under
# "dropped"), and a first window without a reading is refused (asked again, as `read` is).
_WINDOW_HEAD = re.compile(r"^Window: (\d+) of (\d+) ", re.M)


def later_window(input: Optional[str]) -> bool:
    """The input is a long post's window 2 or later (tasks.window_input's head line)."""
    m = _WINDOW_HEAD.search((input or "").split("\nText: ", 1)[0])
    return bool(m) and int(m.group(1)) > 1


def reading_window(answer: Dict[str, Any], input: Optional[str]) -> Dict[str, Any]:
    """A later window's answer with `reading` and `event` null (anything written there kept under "dropped"); any
    other answer unchanged."""
    if not later_window(input):
        return answer
    out = dict(answer, reading=None, event=None)
    for key in ("reading", "event"):
        if answer.get(key) is not None:
            out[DROPPED] = list(out.get(DROPPED) or []) + [{"list": key, "item": answer[key],
                                                            "why": f"{key} on a later window: the first window's job"}]
    return out


def _reading5(a: Dict[str, Any], input: str) -> Optional[str]:
    if later_window(input):
        return None
    r = a.get("reading")
    if r is None:
        return "reading is null on the post's first window"
    return _read({"events": r.get("events"), "main": a.get("event")}, input)


CHECKS = {"read": _read, "entities": _entities, "card": _card, "headline": _headline, "briefing": _briefing,
          "translate": _translate, "collide": _collide, "read3": _read, "stance": _stance,
          "relate": _relate,   # 0131
          "chain": _relate,    # 0219: a story chain's reason is its evidence too
          "derive": _relate,   # 0234: a based_on check's reason too
          "back": _back,       # 0136
          "cite": _cite,       # 0133 v4.2
          "track": _track, "subtopics": _subtopics, "digest": _digest, "subtopic_place": _subtopic_place,   # 0145, 0207
          "probes": _probes,                          # 0147
          "scout": _scout,                            # 0148
          "identity": _identity,                      # 0162
          "websearch": _websearch,                    # 0171
          "source_judge": _source_judge,              # 0173
          "news_sections": _news_sections,            # 0174
          "news_place": _news_place,                  # 0197
          "unit_types": _unit_types,                  # 0181
          "significance": _significance,              # 0208
          "reading": _reading5,                       # 0212
          "track_schema": _track_schema, "track_same": _track_same,   # 0245 (track_things: its salvage checks it)
          "embed": lambda answer, input: _EMBEDDED, "embed_name": lambda answer, input: _EMBEDDED}


# 0196: a guide variant's own checks (schemas.GUIDE_VARIANTS), in place of its kind's.
GUIDE_CHECKS = {"websearch-official-v1": _websearch_official,
                "digest-v2": _digest_rows,   # 0245: a track brief's points cite its rows
                "digest-v3": _digest_rows,   # v10.29: digest-v2's points, stating facts
                "collide-makers-v1": _collide_makers,   # 0250: two maker groups of one bare name
                "judge-read-v2": _judge_read,           # 0258: join's and pair's quotes are their own question's
                "track-fields-v1": lambda a, input: _track_fields(a, input),   # v10.41: fields a track misses
                "track-v3": _track_v3,                  # v10.41: a track verdict agrees with its stated fit
                "track-check-v2": _track_v3}            # ... the blind check's too


def unwrap(kind: str, answer: Any) -> Any:
    if isinstance(answer, dict) and len(answer) == 1:
        (key, inner), = answer.items()
        if key in WRAPPERS.get(kind, ("answer",)) and isinstance(inner, dict):
            return inner
    return answer


def check(kind: str, answer: Any, input: str, guide: Optional[str] = None) -> Tuple[Any, Optional[str]]:
    """(the answer as stored, None) when it is valid; (the answer, why not) otherwise. `guide`: the task's (0133: an
    entities arm's own schema; None: the kind's)."""
    spec = schemas.KINDS.get(kind)
    if spec is None:
        return answer, f"unknown task kind {kind!r}"
    answer = unwrap(kind, answer)
    if not isinstance(answer, dict):
        return answer, "answer: not an object"
    answer = salvage(kind, answer, input, guide)   # v10.20: an entity list's bad entries dropped, kept as "dropped"
    refused = salvage_refused(kind, answer)
    if refused:
        return answer, refused
    err = schema_error(schemas.schema_for(kind, guide), answer)
    if err:
        return answer, err
    extra = GUIDE_CHECKS.get(guide or spec.guide or "") or CHECKS.get(kind)   # no guide: the kind's (0258)
    return answer, extra(answer, input) if extra else None
