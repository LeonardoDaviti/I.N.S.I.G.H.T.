"""Entity names: the name key (`key`, `squash`), handles, scripts and the version parser (`parse`, `vt`,
`fields_key`, `reordered`, `clean`, `setting`).

A size ("27B", "8x7B", "A3B", "E4B") or a build ("GGUF", "Q4_K_M", a date) is never a version; a size has no leading
zero ("GR00T" states none). A maker in front is dropped unless it is the family ("Acme V4 Pro" by Acme: family Acme).
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, Optional, Set, Tuple

DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−⁃﹘﹣－"), "-")
SIZE = re.compile(r"^((0|[1-9]\d*)(\.\d+)?[kmbt]|\d+x\d+(\.\d+)?[bt]|a\d+(\.\d+)?b|e\d+b)$")
BUILD = re.compile(r"^(gguf|ggml|awq|gptq|exl2|exl3|mlx|fp4|fp8|fp16|bf16|int4|int8|nvfp4|mxfp4|q\d(_[0-9a-z]+)*"
                   r"|iq\d(_[0-9a-z]+)*|\d{4}|\d{6,8})$")
VERSION = re.compile(r"^(v?\d+(\.\d+)*[a-z]{0,2}|[a-z]\d+(\.\d+)*[a-z]?)$")
VERSIONED = {"model", "product", "software", "project", "dataset", None}
HANDLE_SUFFIX = ("official", "ai", "hq", "labs", "lab", "inc", "dev", "org", "io", "team")
ROMAN = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10"}
YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
FIELDS = ("family", "version", "variant", "size", "build")
NONE = {f: None for f in FIELDS}


def base_key(name: Optional[str]) -> str:
    """The name key (mx_mentions.name_key): NFKC, dashes '-', casefold, ё as е, letter-digit glue split, separators
    one space. base_key("Nimbus3.8‑Flash") == base_key("nimbus 3.8 flash")."""
    s = unicodedata.normalize("NFKC", name or "").translate(DASHES).replace("­", "")
    s = s.casefold().replace("ё", "е")
    s = re.sub(r"(?<=[a-zа-я])(?=\d)", " ", s)
    return re.sub(r"[\s_\-/·,:;()\[\]\"'«»“”]+", " ", s).strip()


def key(name: Optional[str]) -> str:
    """The identity key: the name key with a leading '@' and a leading 'the ' dropped ("The Acme Times" = "Acme
    Times"; "@acme" = "acme")."""
    s = (name or "").strip()
    s = re.sub(r"^@+", "", s)
    s = re.sub(r"^the\s+", "", s, flags=re.I)
    return base_key(s)


SQUASH = r"[^0-9a-zа-яͰ-Ͽ一-鿿぀-ヿ가-힯+#]+"   # what squash drops
# squash(key) in Postgres, spelled exactly as migration 0127's indexes spell it: a query must match it to use them
SQUASH_SQL = "regexp_replace(key, '" + SQUASH + "', '', 'g')"


def squash(k: Optional[str]) -> str:
    return re.sub(SQUASH, "", k or "")


def is_handle(span: Optional[str]) -> bool:
    s = unicodedata.normalize("NFKC", span or "").strip()
    return bool(re.fullmatch(r"@?[A-Za-z0-9_]{3,}", s)) and (s.startswith("@") or "_" in s)


def handle_forms(span: Optional[str]) -> Dict[str, bool]:
    """{squashed form: whether it drops a word of the handle} ("@acme_ai" -> {"acmeai": False, "acme": True})."""
    s = re.sub(r"^@+", "", unicodedata.normalize("NFKC", span or "").strip()).casefold()
    base = squash(s)
    out = {base: False}
    for suf in HANDLE_SUFFIX:
        if base.endswith(suf) and len(base) - len(suf) >= 3:
            out.setdefault(base[: -len(suf)], True)
    return out


def scripts(s: Optional[str]) -> Set[str]:
    out = set()
    for ch in s or "":
        if not ch.isalpha():
            continue
        n = unicodedata.name(ch, "")
        out.add("latin" if "LATIN" in n else "cyrillic" if "CYRILLIC" in n else "greek" if "GREEK" in n
                else "cjk" if ("CJK" in n or "HIRAGANA" in n or "KATAKANA" in n or "HANGUL" in n) else "other")
    return out


def mixed_word(s: Optional[str]) -> bool:
    """A word mixing scripts ("Аnthropic" with a Cyrillic А): flagged, never trusted as an alias."""
    return any(len(scripts(w)) > 1 for w in (s or "").split())


def language(s: Optional[str]) -> Optional[str]:
    got = scripts(s)
    if not got:
        return None
    return "mixed" if len(got) > 1 else sorted(got)[0]


def tokens(name: Optional[str]):
    s = unicodedata.normalize("NFKC", name or "").translate(DASHES).replace("­", "").casefold()
    out = []
    for t in re.split(r"[\s_/]+", s):
        for u in t.split("-"):
            if not u:
                continue
            m = re.fullmatch(r"([a-z]{2,})(\d+(\.\d+)*[a-z]?)", u)   # nimbus3.8 -> nimbus, 3.8 ; zeta4o -> zeta, 4o
            # never a number with a leading zero ("gr00t"): letters for o written as zeros
            lead0 = m is not None and re.match(r"0\d", m.group(2)) is not None
            out += [m.group(1), m.group(2)] if m and not lead0 and not SIZE.match(u) and not BUILD.match(u) else [u]
    return out


def _parse0(name: str) -> Dict[str, Optional[str]]:
    toks = tokens(name)
    fam, ver, var, size, build = [], None, [], [], []
    for t in toks:
        if ver is None and fam and VERSION.match(t) and not SIZE.match(t):
            ver = t
            continue
        if SIZE.match(t) and (ver is not None or fam):
            size.append(t)
            continue
        if BUILD.match(t) and ver is not None:
            build.append(t)
            continue
        (var if ver is not None else fam).append(t)
    if ver is None and not size and not build:
        return dict(NONE)
    return {"family": " ".join(fam) or None, "version": ver, "variant": " ".join(var) or None,
            "size": "-".join(size) or None, "build": " ".join(build) or None}


def _starts_with_version(rest: str) -> bool:
    """What follows a maker is a bare version ("V4 Pro", "4.1"), not a model code of its own ("B300", "H200")."""
    first = tokens(rest)[:1]
    return bool(first) and bool(re.match(r"^v?\d+(\.\d+)*[a-z]{0,2}$", first[0])) and not SIZE.match(first[0]) \
        and not BUILD.match(first[0])


def parse(name: Optional[str], type_: Optional[str] = None, maker: Optional[str] = None) -> Dict[str, Optional[str]]:
    """family, version, variant, size, build (lowercase; None when absent). The maker in front is dropped ("Acme
    B300" by Acme parses as "B300") unless it is the family: what follows it is a bare version ("Acme V4 Pro")."""
    if type_ not in VERSIONED:
        return dict(NONE)
    s = unicodedata.normalize("NFKC", name or "").translate(DASHES)
    if maker:
        m = re.match(re.escape(unicodedata.normalize("NFKC", maker).strip()) + r"[\s\-_]+", s, flags=re.I)
        if m and len(s) > m.end() and not _starts_with_version(s[m.end():]):
            s = s[m.end():]
    s = re.sub(r"(\d)\.x\b", r"\1", s, flags=re.I)                       # "Kernel 6.x" -> "Kernel 6"
    toks = s.split()
    for i in range(1, len(toks)):                                           # "Saga VII" -> 7
        t = toks[i].casefold()
        if t in ROMAN and t not in ("v", "x") and toks[i - 1][:1].isupper():
            toks[i] = ROMAN[t]
    f = _parse0(" ".join(toks))
    if f["family"] and maker:
        mk = key(maker)
        fk = f["family"]
        if fk.startswith(mk + " ") and len(fk) > len(mk) + 1:
            f["family"] = fk[len(mk) + 1:]
    return clean(f, name)


RATIO = re.compile(r"^\s*\d+\s*:\s*\d+\s*$")                       # "5:1", "16:9": a ratio, never a version
MODEL_ID = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*?[-_](\d+)[-_](\d{1,2})$")   # "acme-nimbus-5-1": 5.1
# effort / settings words: a variant made of them is the version run another way, not a release. The plain ones
# always say a setting ("o9 low"); the others are tiers as often and count only in brackets ("(max)"). measured: 0259
SETTING_PLAIN = frozenset(("low", "high", "xhigh", "minimal"))
SETTING_WORDS = SETTING_PLAIN | frozenset(("max", "maximum", "medium", "mid", "min", "ultra", "ultracode", "default"))


def not_a_version(v: Any) -> bool:
    """A stated version that is no version: a ratio ("5:1")."""
    return v not in (None, "", "null") and bool(RATIO.match(str(v)))


def clean(fields: Optional[Dict[str, Any]], name: Optional[str] = None, versions: Optional[Set[Tuple]] = None) -> Dict[str, Any]:
    """The fields as a version reads them: a ratio is no version ("5:1"); a model id ("acme-nimbus-5-1") is version
    5.1 only when its family states it (`versions`), since an id's last two numbers are as often a shape. Anything
    else as given (the same dict)."""
    f = fields if fields is not None else {}
    v, var = f.get("version"), f.get("variant")
    if not_a_version(v):
        return {**f, "version": None}
    m = MODEL_ID.match(unicodedata.normalize("NFKC", name or "").strip()) if versions else None
    if m and str(v or "").strip() == m.group(1) and str(var or "").strip() == m.group(2) \
            and vt(f"{m.group(1)}.{m.group(2)}") in versions:
        return {**f, "version": f"{m.group(1)}.{m.group(2)}", "variant": None}
    return f


def setting(variant: Optional[str], name: Optional[str] = None, type_: Optional[str] = None) -> bool:
    """A model's variant that is a setting of its version: all settings words, and either only plain ones ("low",
    "xhigh") or written in brackets in the name ("Nimbus 5.2 (max)")."""
    if type_ not in ("model", None) or not variant:
        return False
    ws = key(variant).split()
    if not ws or not all(w in SETTING_WORDS for w in ws):
        return False
    if all(w in SETTING_PLAIN for w in ws):
        return True
    return any(key(b) == " ".join(ws) for b in re.findall(r"[(\[]([^()\[\]]+)[)\]]", name or ""))


_VNUM = re.compile(r"(\d+|[a-z]+)")


def vt(v: Any) -> Optional[Tuple]:
    if v in (None, "", "null"):
        return None
    s = unicodedata.normalize("NFKC", str(v)).casefold().strip()
    s = re.sub(r"^v(?=\d)", "", s)
    parts = _VNUM.findall(s)
    return tuple(int(p) if p.isdigit() else p for p in parts) or None


def vnorm(t: Optional[Tuple]) -> Optional[Tuple]:
    """A version tuple without its trailing zeros ("5.0" = "5"; "1.10" stays)."""
    if not t:
        return t
    t = tuple(t)
    while len(t) > 1 and t[-1] == 0:
        t = t[:-1]
    return t


def nk(v: Any) -> Optional[str]:
    if v in (None, "", "null"):
        return None
    return key(str(v)) or None


def fields_key(f: Optional[Dict[str, Any]], maker: Optional[str] = None) -> Tuple:
    f = f or {}
    fam = nk(f.get("family"))
    if fam and maker:
        mk = key(maker)
        if fam.startswith(mk + " "):
            fam = fam[len(mk) + 1:]
    return (fam, vt(f.get("version")), nk(f.get("variant")), squash(nk(f.get("size")) or "") or None,
            squash(nk(f.get("build")) or "") or None)


def version_part(fk: Optional[Tuple]) -> Tuple:
    """What decides 'another version': version tuple, variant, size, build (the family left out)."""
    return tuple(fk[1:]) if fk else (None, None, None, None)


def reordered(a: Optional[Tuple], b: Optional[Tuple], makers: Iterable[Optional[str]] = ()) -> bool:
    """Two parses of one name in another word order ("Claude Opus 4.5" / "Claude 4.5 Opus"): the same stated version,
    size and build, and the same family + variant words in any order; the maker's words left out only when both
    state the same maker. Never two different words ("Flash" / "Pro") or a version or size apart."""
    if not a or not b or a == b or a[1] is None or a[1] != b[1] or a[3:] != b[3:]:
        return False
    ms = [key(m) for m in makers]
    mw = set(ms[0].split()) if len(ms) == 2 and ms[0] and ms[0] == ms[1] else set()

    def words(fk: Tuple) -> list:
        return sorted(w for w in f"{fk[0] or ''} {fk[2] or ''}".split() if w not in mw)
    wa = words(a)
    return bool(wa) and wa == words(b)


def has_version(fk: Optional[Tuple]) -> bool:
    return any(x is not None for x in version_part(fk))


def ver_eq(a: Optional[Tuple], b: Optional[Tuple]) -> bool:
    """One version: equal, or equal once a leading letter prefix is dropped (K3.1 = 3.1)."""
    if a == b:
        return True
    if a is None or b is None:
        return False
    da = a[1:] if a and isinstance(a[0], str) else a
    db = b[1:] if b and isinstance(b[0], str) else b
    return da == db and bool(da)


def version_json(t: Optional[Tuple]) -> Optional[list]:
    return None if t is None else list(t)


def from_json(v: Any) -> Optional[Tuple]:
    return None if v is None else tuple(v)


def years(k: Optional[str]) -> Set[str]:
    return set(YEAR.findall(k or ""))


def word_contains(k: str, o: str) -> bool:
    """One key's words are a run of the other's words ("unity" is not inside "community")."""
    a, b = (k or "").split(), (o or "").split()
    if not a or not b:
        return False
    if len(a) > len(b):
        a, b = b, a
    return any(b[i:i + len(a)] == a for i in range(len(b) - len(a) + 1))


def grams(s: str) -> Set[str]:
    return {s[j:j + 3] for j in range(max(1, len(s) - 2))}


def jaccard(a: str, b: str) -> float:
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / max(1, len(ga | gb))
