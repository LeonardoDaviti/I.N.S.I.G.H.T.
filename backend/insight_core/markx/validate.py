"""Checks on a model's answer before it is stored as valid: `answer, error = check(kind, answer, input)`; `error`
is None or one short sentence the worker sees (mx_tasks.last_error keeps it). The kind's JSON schema first (the
worker checks it too), then what only the input can tell; text is compared folded (`fold`)."""
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
_QUOTES = str.maketrans({"’": "'", "‘": "'", "”": '"', "“": '"'})
_SPACE = re.compile(r"\s+")
_SEP = re.compile(r"[\s\-_]+")


def fold(text: Optional[str]) -> str:
    """Text as the checks compare it: NFKC, casefolded, ё as е, dashes as '-', quotes plain, spaces collapsed."""
    s = unicodedata.normalize("NFKC", text or "").replace(_SOFT, "").translate(_QUOTES).casefold().replace("ё", "е")
    return _SPACE.sub(" ", _DASHES.sub("-", s))


# the input folded once: an answer's checks ask it once per entity, and folding is most of a check's time (0243)
@lru_cache(maxsize=8)
def _folded(text: Optional[str]) -> str:
    return fold(text)


@lru_cache(maxsize=8)
def _bare(text: Optional[str]) -> str:
    return _SEP.sub("", fold(text))


def occurs(span: str, text: str) -> bool:
    return fold(span).strip() in _folded(text)


def version_occurs(version: str, text: str) -> bool:
    """Its folded characters, separators dropped, occur in the text's ("4.1" in "V4.1-Flash")."""
    return _SEP.sub("", fold(version)) in _bare(text)


# a figure: digits, thousands groups ("1 000", "1,000") and a decimal part ("2,5"); "$20, 27B" stays two figures
_FIGURE = re.compile(r"\d+(?:[ \u00a0\u202f.,]\d{3}(?!\d))*(?:[.,]\d+)?")
_VERSION = re.compile(r"\b[A-Za-z]+[-_‐‑]?\d+(?:\.\d+)+[A-Za-z]?\b|\b[A-Z][\w]*[ ]\d+(?:\.\d+)+\b|\bv\d+(?:\.\d+)+\b")


def figures(text: Optional[str]) -> List[str]:
    """Each figure as its bare digits, no leading zero ("1 000" -> "1000", "2,5" -> "25", "02" -> "2")."""
    out = []
    for m in _FIGURE.finditer(text or ""):
        d = re.sub(r"\D", "", m.group(0)).lstrip("0") or "0"
        if d:
            out.append(d)
    return out


def missing_figures(claim: Optional[str], evidence: Optional[str]) -> List[str]:
    """The claim's figures the evidence lacks (3+ digits also found in its digits run together)."""
    have = set(figures(evidence))
    bare = re.sub(r"\D", "", evidence or "")
    return [d for d in figures(claim) if d not in have and (len(d) < 3 or d not in bare)]


def versions(text: Optional[str]) -> List[str]:
    """Product versions as written ('GPT-5.6', 'K3.1', 'Opus 5.5', 'v0.7.0'), not bare figures."""
    return _VERSION.findall(text or "")


def words(text: Optional[str]) -> int:
    return len((text or "").split())


# ---- the schema subset (as scripts/markx-worker checks it) ---------------------------------------

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
    """What is wrong with one entities entry against its post (`_entities` and `salvage` use it)."""
    if e.get("role") == "recommended" and e.get("type") != "document":
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


def _cite(a: Dict[str, Any], input: str) -> Optional[str]:
    for n, e in enumerate(a["entities"]):
        err = _cite_error(e, input)
        if err:
            return f"entities[{n}].{err}"
    return None


# ---- salvage: each entry checked alone, a bad one kept under "dropped" -------------------------------------------
# {kind: {list key: the entry's check against the post (None: its schema alone)}}; the first list is the entities.
SALVAGE = {"entities": {"entities": _entity_error, "relations": None},
           "cite": {"entities": _cite_error},
           "reading": {"entities": _entity_error}}
SUBJECT_KINDS = ("entities", "reading")              # kinds whose answer must keep a subject it named
DROPPED = "dropped"


def salvage(kind: str, answer: Any, input: str, guide: Optional[str] = None) -> Any:
    """The answer with bad list entries dropped (kept under "dropped" with why) for a kind in SALVAGE; else as is."""
    if kind == "track_things" and isinstance(answer, dict):
        from insight_core.markx import track_things
        return track_things.salvage(answer, input or "")
    lists = SALVAGE.get(kind)
    if not lists or not isinstance(answer, dict):
        return answer
    if kind == "reading":   # a later window's reading is the first window's job
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
    """Why a salvaged answer is asked again: it kept none of its entities, or (SUBJECT_KINDS) no subject."""
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
    """A headline's version is found when its number occurs in the text as a number ("GPT-5.6"
    in "their 5.6 versions")."""
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
    # `odd` names members by the id the input shows; an answer that numbers them is kept as given (nothing reads
    # `odd`, and a number's base can't be told)
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
    """Every mention number appears once, in a sense or `unclear`; `related` links senses by 1-based position."""
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
    """A verdict needs its evidence (blank is none)."""
    return None if str(a.get("evidence") or "").strip() else "evidence: empty"


def _relate(a: Dict[str, Any], input: str) -> Optional[str]:
    """The reason is the edge's evidence: blank is none."""
    return None if str(a.get("reason") or "").strip() else "reason: empty"


# judge-read-v2 (0258): tasks.render_story + render_post; "Links: " and "Reading of the post: " are not the post's
JUDGE_POST_MARK = "\n\nPOST\nPlatform: "
JUDGE_POST_TAILS = ("\nReading of the post: ", "\nLinks: ")   # the render's last lines, in reverse order
JUDGE_QUOTE_MIN = 12   # folded characters: shorter names too little to be this post's (unless it is all of it)


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
    """`post_quote` is in this question's POST, `story_quote` in its STORY (an answer written for another
    question of the batch quotes words this one does not show); only `cant_tell` may leave the post quote empty."""
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
    """Whether an answer lacks the post quote its current guide checks: decide asks it again before using it."""
    spec = schemas.KINDS.get(kind)
    return (spec is not None and GUIDE_CHECKS.get(spec.guide or "") is _judge_read
            and isinstance(answer, dict) and "post_quote" not in answer)


_STANCE_BLOCK = re.compile(r"^\[(\d+)\] ", re.M)
STANCE_MIN_QUOTES = 2


def stance_posts(input: str) -> Dict[int, str]:
    """{number: text} of a stance question's numbered posts ("[3] ...")."""
    marks = list(_STANCE_BLOCK.finditer(input or ""))
    return {int(m.group(1)): input[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(input)]
            for i, m in enumerate(marks)}


def stance_grounded(answer: Any, input: str) -> List[Dict[str, Any]]:
    """The patterns a stance answer may show: quotes found exactly in the post they name, 2+ from 2
    posts; at most STANCE_PATTERNS."""
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
    """How many new posts a back question numbers (here: this module needs only the standard library)."""
    _, _, tail = (input or "").partition("NEW POSTS")
    return len(_BACK_NUMBERED.findall(tail))


def _back(a: Dict[str, Any], input: str) -> Optional[str]:
    """Each verdict names one of the question's new posts, once."""
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


# A track verdict judges ONE post (0252): its why must cite a word of the post's own text that is no word of the
# question, the guide or _FUNCTION_WORDS (5-letter stems); posts under CITE_MIN_WORDS Latin words are not checked.
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
    """A word's first 5 letters, a plural's -s off first ("tool" and "tools" one stem; "access" stays "acces")."""
    return (w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)[:5]


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


# The judge answers in English: a post written mostly in another script (Cyrillic, CJK, ...) shares no word with an
# answer that names it right, so its why is not checked (v10.44: 591 track-v3 tasks of Russian posts failed so). Its
# share of Latin words is counted on its title and text only, never its links (URLs are Latin in any language).
LATIN_SHARE_MIN = 0.5


_POST_LABEL = re.compile(r"^(?:Title|Text|Quotes the tweet): ", re.M)


def _latin_share(input: str) -> float:
    post = input.partition(POST_MARK)[2].split("\nLinks, in order:")[0]
    body = _POST_LABEL.sub("", "\n".join(line for line in post.splitlines()
                                         if not line.startswith(("Platform:", "Author:"))))
    words = [w for w in _CITE_WORD.findall(fold(body)) if len(w) >= 4 and not w.isdigit()]
    return sum(1 for w in words if _LATIN.search(w)) / len(words) if words else 1.0


def track_verdict_error(a: Dict[str, Any], input: Optional[str]) -> Optional[str]:
    """Why a `track` answer is no verdict of its post (None: it is one). See POST_MARK's note."""
    if float(a.get("confidence") or 0) <= 0:
        return "confidence: 0 judges nothing; say how sure you are of `in` (above 0)"
    if not input or POST_MARK not in input:
        return None
    if _latin_share(input) < LATIN_SHARE_MIN:
        return None
    own, asked = _post_words(input)
    own -= asked | _guide_words("track")
    if sum(1 for w in own if _LATIN.search(w)) < CITE_MIN_WORDS:
        return None
    if not (_cite_words(a.get("why") or "") & own):
        return "why: it names nothing of this post; say what the post is (its subject, in its words)"
    return None


def _track(a: Dict[str, Any], input: str) -> Optional[str]:
    """`why` is one line, at most TRACK_WHY_CHARS, and the answer is a verdict of its post."""
    return _one_line_why(a) or track_verdict_error(a, input)


# track-v3: `in` true needs `fits` true, a `matches` quote of `Belongs:` (the header's own words) and no `excluded`
_HEADER_PARTS = ("TRACK: ", "Belongs: ", "Not: ", "Sub-topics: ", "Marked in by the reader:", "Marked out by the reader:")


def header_part(input: Optional[str], name: str) -> Optional[str]:
    """The part of a track question's header starting with `name` ("Belongs: "), up to the next part; None if none."""
    head = "\n" + (input or "").partition(POST_MARK)[0]
    at = head.find("\n" + name)
    if at < 0:
        return None
    body = head[at + 1 + len(name):]
    ends = [i for i in (body.find("\n" + p) for p in _HEADER_PARTS) if i >= 0]
    return body[:min(ends)] if ends else body


# A quote of the header needs most of its words from the named part (QUOTE_SHARE_MIN of its words of 4+ letters,
# function words aside, by stem): the judge copies the reader's words but joins or rewords a few of them ("inference
# engines and tools for running local models" of "inference engines (llama.cpp, ...)"); an answer that names other
# things than the header's stays refused.
QUOTE_SHARE_MIN = 0.5


def _quotes(quote: Optional[str], part: Optional[str], field: str) -> Optional[str]:
    words = _cite_words(quote or "") - {_stem(w) for w in _FUNCTION_WORDS}
    if not words:
        return f"{field}: copy the words of the track's header it names (at least one word of 4+ letters)"
    if part is not None:
        missing = words - _cite_words(part)
        if len(missing) > len(words) * (1 - QUOTE_SHARE_MIN):
            return f"{field}: copy it from the track's header, its own words (not {sorted(missing)[:3]})"
    return None


def track_fit_error(a: Dict[str, Any], input: Optional[str]) -> Optional[str]:
    """Why a track-v3 answer's `in` disagrees with its stated fit (None: it agrees). See _HEADER_PARTS."""
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
    """The `_track` checks (the post named by `subject` or `why`), and `in` agrees with the stated fit."""
    named = {**a, "why": f"{a.get('why') or ''} {a.get('subject') or ''}"}
    return _one_line_why(a) or track_verdict_error(named, input) or track_fit_error(a, input)


def _subtopics(a: Dict[str, Any], input: str) -> Optional[str]:
    """Each key one of the question's groups, named once; names not repeated; a definition one line."""
    from insight_core.markx import track_subtopics
    if "names" not in a:   # a subtopics-v1 proposal: its schema alone
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
    """Every post of the question once, each in one of its sub-topics or none."""
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
    """Each point one line, citing only the question's posts [1..n]."""
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
    """Each point one line, citing only the question's rows, and every figure it gives in the rows it cites."""
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
    from insight_core.markx import track_things
    return track_things.schema_error(a)


def _track_fields(a: Dict[str, Any], input: str) -> Optional[str]:
    """Each field of a kind the question showed, not one it has (track_fields.check)."""
    from insight_core.markx import track_fields
    return track_fields.check(a, input)


def _track_same(a: Dict[str, Any], _input: str) -> Optional[str]:
    return "why: one line" if "\n" in a["why"].strip() else None


def _probes(a: Dict[str, Any], _input: str) -> Optional[str]:
    """The example posts are distinct, each at most PROBE_CHARS (x2)."""
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
    """Each source one address (no spaces, at most SCOUT_ADDRESS_CHARS), named once; `why` one line."""
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
    return _one_line_why(a)


def _websearch(a: Dict[str, Any], _input: str) -> Optional[str]:
    """Each candidate one http(s) address, named once, title and why one line; each query one line."""
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
    """Each reason one line, said once; each example an item the question shows, once; then the filter."""
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
    """A proposed item filter checked (utils/item_filter.check) against the items shown; `keep` names them."""
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
    """Every address one http(s) address, no spaces, named once; each why one line."""
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
                "more", "more news", "rest"}   # allowed for OTHER_ROWS rows or fewer only
OTHER_ROWS = 2


def _news_sections(a: Dict[str, Any], input: str) -> Optional[str]:
    """Every row shown in exactly one section; titles short, one line, unique; "Other" only for few rows."""
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
    """Every item shown answered exactly once; a headline one line, at most UNIT_HEADLINE_WORDS (+2) words."""
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
    """Every new row shown placed exactly once, into a shown section or "new"."""
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
# ---- ent-v5 `reading`: a long post's later window carries entities only; the first window needs a reading -------
_WINDOW_HEAD = re.compile(r"^Window: (\d+) of (\d+) ", re.M)


def later_window(input: Optional[str]) -> bool:
    """The input is a long post's window 2 or later."""
    m = _WINDOW_HEAD.search((input or "").split("\nText: ", 1)[0])
    return bool(m) and int(m.group(1)) > 1


def reading_window(answer: Dict[str, Any], input: Optional[str]) -> Dict[str, Any]:
    """A later window's answer with `reading` and `event` null (kept under "dropped"); others unchanged."""
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


def subtype_error(event_type: Optional[str], subtype: Optional[str]) -> Optional[str]:
    """v10.42: why a reading's subtype disagrees with its event type (schemas.SUBTYPE_TYPES), None when it agrees: a
    subtype only under its event types, and every type that has subtypes names one."""
    if subtype is None:
        if any(event_type in types for types in schemas.SUBTYPE_TYPES.values()):
            return f"subtype is null for a {event_type}"
        return None
    if event_type not in schemas.SUBTYPE_TYPES.get(subtype, ()):
        return f"subtype {subtype} is not one of a {event_type}'s"
    return None


def _reading6(a: Dict[str, Any], input: str) -> Optional[str]:
    """ent-v6: ent-v5's checks, then the subtype agrees with the event type."""
    err = _reading5(a, input)
    if err or later_window(input):
        return err
    r = a["reading"]
    return subtype_error(r.get("event_type"), r.get("subtype"))


CHECKS = {"read": _read, "entities": _entities, "card": _card, "headline": _headline, "briefing": _briefing,
          "translate": _translate, "collide": _collide, "read3": _read, "stance": _stance,
          "relate": _relate,
          "chain": _relate,
          "derive": _relate,
          "back": _back,
          "cite": _cite,
          "track": _track, "subtopics": _subtopics, "digest": _digest, "subtopic_place": _subtopic_place,
          "probes": _probes,
          "scout": _scout,
          "identity": _identity,
          "websearch": _websearch,
          "source_judge": _source_judge,
          "news_sections": _news_sections,
          "news_place": _news_place,
          "unit_types": _unit_types,
          "significance": _significance,
          "reading": _reading5,
          "track_schema": _track_schema, "track_same": _track_same,   # track_things: its salvage checks it
          "embed": lambda answer, input: _EMBEDDED, "embed_name": lambda answer, input: _EMBEDDED}


# a guide variant's own checks (schemas.GUIDE_VARIANTS), in place of its kind's
GUIDE_CHECKS = {"websearch-official-v1": _websearch_official,
                "ent-v6": _reading6,
                "digest-v2": _digest_rows,
                "digest-v3": _digest_rows,
                "collide-makers-v1": _collide_makers,
                "judge-read-v2": _judge_read,
                "track-fields-v1": lambda a, input: _track_fields(a, input),
                "track-v3": _track_v3,
                "track-check-v2": _track_v3}


def unwrap(kind: str, answer: Any) -> Any:
    if isinstance(answer, dict) and len(answer) == 1:
        (key, inner), = answer.items()
        if key in WRAPPERS.get(kind, ("answer",)) and isinstance(inner, dict):
            return inner
    return answer


def check(kind: str, answer: Any, input: str, guide: Optional[str] = None) -> Tuple[Any, Optional[str]]:
    """(the answer as stored, None) when valid, else (the answer, why not). `guide`: the task's (None: the kind's)."""
    spec = schemas.KINDS.get(kind)
    if spec is None:
        return answer, f"unknown task kind {kind!r}"
    answer = unwrap(kind, answer)
    if not isinstance(answer, dict):
        return answer, "answer: not an object"
    answer = salvage(kind, answer, input, guide)
    refused = salvage_refused(kind, answer)
    if refused:
        return answer, refused
    err = schema_error(schemas.schema_for(kind, guide), answer)
    if err:
        return answer, err
    extra = GUIDE_CHECKS.get(guide or spec.guide or "") or CHECKS.get(kind)
    return answer, extra(answer, input) if extra else None
