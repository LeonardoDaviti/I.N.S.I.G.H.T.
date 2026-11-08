"""Series (issue 0134): a source's multi-part works ("Part 3 of 4") and its recurring numbered columns ("Issue #136"),
told apart, no model. A port of the lab's frozen rule (series_v1, measured on the 2026-11-05 server copy: membership
95.8%, series vs column 95.1%) with the spec's five fixes. Pure: the caller hands one source's posts and their
navigation links (services/series_service.py reads and stores them).

Edges between posts of ONE source, within WINDOW days:
  E1 numbered titles: both carry a numbered marker in label position (the title's start or end, or next to a
     separator), distinct numbers, similar stems (the title without the marker). Part-style ("part N", "часть N",
     "N/M", "pt. N", "Part two"), issue-style ("#N", "No. N", "выпуск N"), and runs of S_RUN+ "stem N:" titles.
  E2 navigation: a post links another of its source with navigation link words (NAV: previous / part N / начало /
     продолжение / "start of this series" ...).
  E3 shared navigation: posts of one source link the same page (stored or not) with navigation link words, its start.
Groups are the connected components; a group needs a marker, an E2 or an E3 edge (a weak "previous post" alone is no
group).

The five fixes (0134, from the lab's wrong and missed rows):
  1. no E4: an X self-reply joins nothing (it joined threads to series groups);
  2. on X a marker counts only at the start of the title (a promoted book's "Part II" is the subject's, not the post's);
  3. a post titled exactly with the group's stem, before its part 2, joins as part 1;
  4. WINDOW is 60 days (was 45);
  5. no cap on part numbers, and a number may carry a letter ("32a").

Kind, no model: a column when its markers are mostly issue-style and it runs long (max number >= COL_NUM, or
COL_SPAN+ days with COL_MIN+ members) or its issue-style stem recurs in two groups of the source; otherwise a series
(part-style, and the lab's rule-only default for the unclear ones: its Haiku call added nothing).

The lab's pairwise meaning check (BGE-M3 cosine for a looser stem) is not ported: Mark IX reads no Mark X vectors, so
a looser stem takes the lab's other sign, NEAR_DAYS, as the lab did for a post with no vector.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

VERSION = 2                   # a bump recomputes every source's series (series_service); 2: 0137's shapes
WINDOW = 60                   # fix 4: days between two parts (was 45)
K_WINDOW = 120                # issue-style numbers: days between two issues
K_STEP = 3                    # ... at most this many numbers apart
COL_NUM, COL_SPAN, COL_MIN = 10, 60, 3
STEM_J, STEM_HI = 0.5, 0.8    # stem overlap: needed, and enough alone
NEAR_DAYS = 3                 # a looser stem needs the posts this near
S_RUN = 3                     # "stem N:" titles count as a run of this many consecutive numbers
E3_MAX = 30                   # a page more posts link as their start is no series' start

SERIES, COLUMN = "series", "column"

ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
WORDN = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "первая": 1, "вторая": 2, "третья": 3, "четвертая": 4,
         "четвёртая": 4, "пятая": 5, "first": 1, "second": 2, "third": 3, "final": None}
# fix 5: any number of digits, and a letter after it ("32a")
NUMTOK = r"(\d+[a-zа-я]?|[IVX]{1,4}|one|two|three|four|five|первая|вторая|третья|четв[её]ртая|пятая)"
PART = re.compile(r"(?i)(?<![\w])(?:част[ьиеюя]|part|pt\.?|глава|chapter|серия|эпизод)\s*#?\s*" + NUMTOK + r"(?![\w])"
                  r"(?:\s*(?:/|of|из)\s*(\d{1,4}))?")
FRAC = re.compile(r"(?<![\w/.,:$€£])\(?(\d{1,2})\s?(?:/|of|из)\s?(\d{1,2})\)?(?![\w/.,:%])")
ISSUE = re.compile(r"(?i)(?:(?<![\w&])#\s?|№\s?|(?<![\w])(?:no\.|issue|выпуск|episode|ep\.?|vol\.?|week|неделя)\s?#?\s?)"
                   r"(\d{1,4})(?![\w,]|\.\d)")      # "#34." ends a sentence (0137); "#3.5" is no issue
SHORT = re.compile(r"^([A-Za-zА-Яа-яЁё][\w\-]{0,15}(?: [\w\-]{1,15}){0,2}) (\d{1,2})[:.]\s")   # "PPA 7: ..."
# 0137: "Name N Title" ("Newsletter 483 The jobs report"): a short stem at the title's start, a bare number, no colon.
# Only a run makes it a marker (N_RUN+ posts, numbers rising with the dates), never a pair; not a year, not a date.
NAMED = re.compile(r"^([A-Za-zА-Яа-яЁё][\w\-]{0,15}(?: [\w\-]{1,15}){0,2}) (\d{1,5})(?=\s|$)(?![\s]*[:./%,])")
MONTHS = re.compile(r"(?i)^\s*(?:(?:jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)\.?\b|january|february|march|april|may\b|"
                    r"june|july|august|september|october|november|december|(?:январ|феврал|март|апрел|июн|июл|август|"
                    r"сентябр|октябр|ноябр|декабр)\w*|ма[яй]\b)")
N_RUN, N_STEP = 3, 20         # a "Name N" run: this many posts, each at most this many numbers after the one before
# the stem of "#N" (0137; "week N", "No. N" keep the whole prefix) is the title segment next to it: a guest's name before it or after it is not part of the stem
# ("Musk v. Altman", "Dr. Who" are one segment: a full stop ends one after a word of 3+ letters)
SEGMENT = re.compile(r"(?<=\w{3})\.\s|[:!?]\s|\s-\s|[|—–]")
SEP = set(",:;()[]—–-|.!?«»\"'/")
# a bare "previous post" / "first post" is weak: a follow-up says it too; it makes no group alone
WEAK = re.compile(r"(?i)^\W*(?:предыдущ\w* пост|previous post|(?:the )?first post)\W*$")
PARTREF = re.compile(r"(?i)^\W*(?:part|част[ьи]|chapter) (?:\d{1,2}|one|two|three|i{1,3}|втор\w*)\W*$")
# navigation link words: the link's own words are ONLY a pointer to the start / the previous part of a work
NAV = re.compile(r"(?i)^\W*(?:↑\s*)?(?:начало(?: здесь| тут| треда| серии)?|предыдущ\w* (?:пост|част\w*|серия)|"
                 r"(?:перв\w*|предыдущ\w*|прошл\w*) част\w*|част[ьи] (?:\d{1,2}|перв\w*|втор\w*)|продолжение|"
                 r"previous (?:part|post|installment|chapter|episode)|(?:the )?first (?:part|post|installment|chapter)|"
                 r"part (?:\d{1,2}|one|two|three|i{1,3})|chapter \d{1,2}|continued(?: from)?|start(?:s)? here|"
                 r"(?:the )?(?:start|beginning) of (?:the|this) series)\W*$")
# A superset of NAV's words for the database to read only the posts that may hold such a link (series_service).
NAV_PREFILTER = (r">[^<[:alnum:]]{0,8}(начало|предыдущ|прошл|перв|част|продолжение|previous|first|part|chapter|"
                 r"continued|start|beginning|the )")


@dataclass(frozen=True)
class Post:
    id: str
    at: datetime
    title: Optional[str]
    head: str = ""                # the text's start, for a post with no title
    kind: str = "site"            # utils/post_links.source_kind: x, telegram, site ...


@dataclass(frozen=True)
class NavLink:
    """A link of `post` whose link words are navigation (NAV): its address, and the source's post it resolves to."""
    post: str
    address: str
    words: str
    target: Optional[str] = None


@dataclass(frozen=True)
class Marker:
    style: str                    # P part, F fraction, K issue, S "stem N:"
    number: int
    label: str                    # as written, a letter kept: "32a", "3"
    total: Optional[int]
    stem: str                     # normalized
    shown: str                    # the stem as written, for the line


@dataclass
class Group:
    members: List[str]                          # oldest first
    kind: str
    stem: str
    name: str                                   # the stem as written
    numbers: Dict[str, Optional[str]]           # post -> its number's label
    total: Optional[int]
    first_at: datetime
    last_at: datetime
    evidence: Dict[str, int] = field(default_factory=dict)

    def key(self) -> Tuple:
        return (self.kind, self.stem, tuple((m, self.numbers.get(m)) for m in self.members))


def clean_title(p: Post) -> str:
    t = p.title or (p.head or "")[:200]
    t = re.sub(r"\s*\[\.\.\.\]\s*$", "", t)
    t = re.sub(r"^(RT by @\w+:|R to @\w+:)\s*", "", t)
    return " ".join(t.split())[:200]


def norm(s: str) -> str:
    s = s.lower().replace("ё", "е")
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def _label_position(t: str, m: re.Match) -> bool:
    before, after = t[:m.start()].rstrip(), t[m.end():].lstrip()
    return (not before) or before[-1] in SEP or (not after) or after[0] in SEP


def _at_start(t: str, m: re.Match) -> bool:
    return not t[:m.start()].strip(" \t([{\"'«“#№")


def _num(s: str) -> Optional[Tuple[int, str]]:
    s = s.lower()
    digits = re.match(r"^(\d+)([a-zа-я]?)$", s)
    if digits:
        return int(digits.group(1)), s
    n = ROMAN.get(s) or WORDN.get(s)
    return (n, str(n)) if n else None


def marker(p: Post) -> Optional[Marker]:
    """The title's numbered marker, or None. On X (fix 2) only one at the title's start."""
    t = clean_title(p)
    x = p.kind == "x"
    for style, rx in (("P", PART), ("F", FRAC), ("K", ISSUE)):
        for m in rx.finditer(t):
            if not _label_position(t, m) or (x and not _at_start(t, m)):
                continue
            got = _num(m.group(1))
            if got is None:
                continue
            n, label = got
            total = int(m.group(2)) if (m.lastindex or 0) >= 2 and m.group(2) else None
            if style == "F" and (total is None or not (1 <= n <= total) or total < 2 or total > 20):
                continue
            if m.start() > 3:
                raw = t[:m.start()]
                if style == "K" and t[m.start()] in "#№":
                    raw = next((seg for seg in reversed(SEGMENT.split(raw)) if seg.strip(" ,;()[]#.")), raw)
            else:
                raw = re.split(r"[:|—–]|\s-\s|\(|\[", t[m.end():].strip(" ,:;-–—|()[]#"), maxsplit=1)[0]
            shown = raw.strip(" ,:;-–—|()[]#.")
            return Marker(style, n, label, total, norm(raw), shown)
    m = SHORT.match(t)
    if m:
        return Marker("S", int(m.group(2)), m.group(2), None, norm(m.group(1)), m.group(1))
    return None


def named_marker(p: Post) -> Optional[Marker]:
    """0137: a "Name N Title" title's marker, a candidate only: build() keeps it when its stem runs (N_RUN+, rising).
    Never on X: "Question 1", "Question 2" replies are a thread's tweets (fix 1), not a series."""
    if p.kind == "x":
        return None
    t = clean_title(p)
    m = NAMED.match(t)
    if m and not MONTHS.match(t[m.end():]) and not 1900 <= int(m.group(2)) <= 2100:
        return Marker("N", int(m.group(2)), m.group(2), None, norm(m.group(1)), m.group(1))
    return None


def stem_sim(a: str, b: str) -> float:
    if a == b and a:
        return 1.0
    ta, tb = set(a.split()), set(b.split())
    if {w for w in ta if w.isdigit()} != {w for w in tb if w.isdigit()}:
        return 0.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_navigation(words: Optional[str]) -> bool:
    return bool(words and NAV.search(words))


def _days(a: datetime, b: datetime) -> int:
    """Whole days between two dates, as the lab counted them."""
    return abs(b - a).days


def build(posts: Sequence[Post], links: Iterable[NavLink] = ()) -> List[Group]:
    """One source's series and columns, each oldest part first."""
    by_id = {p.id: p for p in posts}
    mk = {p.id: m for p in posts if (m := marker(p))}
    edges: Dict[str, Set[str]] = defaultdict(set)
    why: Dict[Tuple[str, str], Set[str]] = defaultdict(set)

    def join(a: str, b: str, tag: str) -> None:
        edges[a].add(b)
        edges[b].add(a)
        why[(min(a, b), max(a, b))].add(tag)

    # E1: part-style and fraction with each other, issue-style with issue-style
    fam = lambda s: s if s in ("K", "S") else "PF"
    ids = sorted((i for i in mk if mk[i].style not in ("S", "N")), key=lambda i: by_id[i].at)
    for x, a in enumerate(ids):
        for b in ids[x + 1:]:
            d = _days(by_id[a].at, by_id[b].at)
            if d > max(WINDOW, K_WINDOW):
                break
            ma, mb = mk[a], mk[b]
            if fam(ma.style) != fam(mb.style) or ma.label == mb.label:
                continue
            if ma.style == "K" and d <= K_WINDOW and abs(ma.number - mb.number) <= K_STEP and ma.stem and \
                    (ma.stem.split()[:2] == mb.stem.split()[:2] or stem_sim(ma.stem, mb.stem) >= STEM_J):
                join(a, b, "E1")
                continue
            if d > WINDOW:
                continue
            j = stem_sim(ma.stem, mb.stem)
            if j < STEM_J or (j < STEM_HI and d > NEAR_DAYS):
                continue
            join(a, b, "E1")
    # S: "<short stem> N:" titles, only as a run of S_RUN+ consecutive numbers within WINDOW
    runs: Dict[str, List[str]] = defaultdict(list)
    for i, m in mk.items():
        if m.style == "S":
            runs[m.stem].append(i)
    for _stem, members in runs.items():
        nums = sorted({mk[i].number for i in members})
        best, cur = [], [nums[0]]
        for n in nums[1:]:
            cur = cur + [n] if n == cur[-1] + 1 else [n]
            if len(cur) > len(best):
                best = cur
        if len(best) < len(cur):
            best = cur
        if len(best) >= S_RUN:
            mem = sorted((i for i in members if mk[i].number in best), key=lambda i: mk[i].number)
            ats = [by_id[i].at for i in mem]
            if _days(min(ats), max(ats)) <= WINDOW:
                for x in mem[1:]:
                    join(mem[0], x, "E1")
    # N (0137): "Name N Title" runs, N_RUN+ posts whose numbers rise with their dates, each within K_WINDOW days and
    # N_STEP numbers of the one before (a repost of a number is left out of the run, not breaking it)
    named: Dict[str, List[str]] = defaultdict(list)
    candidates = {p.id: m for p in posts if p.id not in mk and (m := named_marker(p))}
    for i, m in candidates.items():
        named[m.stem].append(i)

    def run(chain: List[str]) -> None:
        if len(chain) >= N_RUN:
            for x in chain:
                mk[x] = candidates[x]
            for x in chain[1:]:
                join(chain[0], x, "E1")

    for _stem, members in named.items():
        chain: List[str] = []
        for i in sorted(members, key=lambda i: (by_id[i].at, candidates[i].number)):
            last = chain[-1] if chain else None
            if last is not None and candidates[i].number == candidates[last].number:
                continue
            if last is None or (0 < candidates[i].number - candidates[last].number <= N_STEP
                                and _days(by_id[last].at, by_id[i].at) <= K_WINDOW):
                chain.append(i)
                continue
            run(chain)
            chain = [i]
        run(chain)
    # E2: a navigation link to another post of the source
    links = [l for l in links if l.post in by_id]
    for l in links:
        a, b = l.post, l.target
        if b is None or b not in by_id or a == b or _days(by_id[a].at, by_id[b].at) > WINDOW:
            continue
        if PARTREF.search(l.words) and a not in mk:
            continue   # a roundup linking "Part 2" is not itself a part
        join(a, b, "E2w" if WEAK.search(l.words) else "E2")
    # E3: the same page linked as their start
    by_page: Dict[str, Set[str]] = defaultdict(set)
    for l in links:
        by_page[l.address.split("?")[0].split("#")[0].rstrip("/")].add(l.post)
    for _page, ps in by_page.items():
        if not 2 <= len(ps) <= E3_MAX:
            continue
        ps_ = sorted(ps, key=lambda i: by_id[i].at)
        for x, a in enumerate(ps_):
            for b in ps_[x + 1:]:
                if _days(by_id[a].at, by_id[b].at) <= WINDOW:
                    join(a, b, "E3")
    # the components
    seen: Set[str] = set()
    comps: List[List[str]] = []
    for i in sorted(edges):
        if i in seen:
            continue
        comp, st = [], [i]
        seen.add(i)
        while st:
            x = st.pop()
            comp.append(x)
            for y in edges[x]:
                if y not in seen:
                    seen.add(y)
                    st.append(y)
        comps.append(sorted(comp, key=lambda i: (by_id[i].at, i)))
    groups: List[Group] = []
    issue_stems: List[Set[str]] = []
    for g in comps:
        ev = Counter(w for (a, b), ws in why.items() if a in g and b in g for w in ws)
        ms = [mk[i] for i in g if i in mk]
        if not (ms or ev.get("E2") or ev.get("E3")):
            continue   # a weak link alone
        styles = Counter(m.style for m in ms)
        k_major = styles.get("K", 0) + styles.get("N", 0) >= max(1, styles.get("P", 0) + styles.get("F", 0))
        groups.append(_group(g, by_id, mk, dict(ev), k_major))
        issue_stems.append({mk[i].stem for i in g if i in mk and mk[i].style in ("K", "N")})
    # an issue-style stem in two groups of the source is a column: it outlived the window
    recurs = Counter(s for stems in issue_stems for s in stems)
    for g, stems in zip(groups, issue_stems):
        if g.kind == SERIES and g.evidence.get("_k_major") and any(recurs[s] >= 2 for s in stems):
            g.kind = COLUMN
    for g in groups:
        g.evidence.pop("_k_major", None)
    _part_one(groups, posts, mk)
    return groups


def _group(g: List[str], by_id: Dict[str, Post], mk: Dict[str, Marker], ev: Dict[str, int], k_major: bool) -> Group:
    nums = [mk[i].number for i in g if i in mk]
    first, last = by_id[g[0]].at, by_id[g[-1]].at
    span = _days(first, last)
    column = k_major and ((nums and max(nums) >= COL_NUM) or (span >= COL_SPAN and len(g) >= COL_MIN))
    stems = Counter(mk[i].stem for i in g if i in mk and mk[i].stem)
    stem = stems.most_common(1)[0][0] if stems else norm(clean_title(by_id[g[0]]))
    name = next((mk[i].shown for i in g if i in mk and mk[i].stem == stem and mk[i].shown), None) \
        or clean_title(by_id[g[0]])[:120]
    totals = [mk[i].total for i in g if i in mk and mk[i].total]
    if k_major:
        ev["_k_major"] = 1
    return Group(members=list(g), kind=COLUMN if column else SERIES, stem=stem, name=name,
                 numbers={i: (mk[i].label if i in mk else None) for i in g}, total=max(totals) if totals else None,
                 first_at=first, last_at=last, evidence=ev)


def _part_one(groups: List[Group], posts: Sequence[Post], mk: Dict[str, Marker]) -> None:
    """Fix 3: a post titled exactly with a series' stem, unmarked, in no group, posted before its part 2 (and within
    WINDOW of it), joins it as part 1."""
    taken = {m for g in groups for m in g.members}
    at = {p.id: p.at for p in posts}
    by_title: Dict[str, List[Post]] = defaultdict(list)
    for p in posts:
        if p.id not in taken and p.id not in mk:
            by_title[norm(clean_title(p))].append(p)
    for g in groups:
        if g.kind != SERIES or not g.stem or any(n == "1" for n in g.numbers.values()):
            continue
        two = [m for m in g.members if g.numbers.get(m) == "2"]
        if not two:
            continue
        at2 = at[two[0]]
        found = [p for p in by_title.get(g.stem, []) if p.at <= at2 and _days(p.at, at2) <= WINDOW and p.id not in taken]
        if not found:
            continue
        p = max(found, key=lambda p: p.at)
        taken.add(p.id)
        g.members = sorted(g.members + [p.id], key=lambda i: (at[i], i))
        g.numbers[p.id] = "1"
        g.first_at = min(g.first_at, p.at)
        g.evidence["part_one"] = g.evidence.get("part_one", 0) + 1


def navigation(groups: Sequence[Group], links: Iterable[Tuple[str, str, Optional[str], Optional[str]]]) -> Set[Tuple[str, str]]:
    """Which same-source links are series navigation: (post, address) for each (post, address, target, words) whose
    target is a post of the source and both ends are in one group, or whose link words are navigation."""
    group_of: Dict[str, int] = {}
    for k, g in enumerate(groups):
        for m in g.members:
            group_of[m] = k
    out: Set[Tuple[str, str]] = set()
    for post, address, target, words in links:
        if target is None or target == post:
            continue
        if is_navigation(words) or (post in group_of and group_of.get(target) == group_of[post]):
            out.add((post, address))
    return out


def link_words(content_html: Optional[str], content: Optional[str], url: Optional[str]) -> List[Tuple[str, str, str]]:
    """The post's links as (normalized address, absolute url, link words), each address once, its first link's words:
    the addresses post_refs keeps (utils/post_refs.refs_of), so a row can be marked by its address."""
    from urllib.parse import urljoin
    from insight_core.utils.post_refs import _END, _MID, _OPEN, marked_text
    from insight_core.utils.url_normalization import normalize_url
    text, hrefs = marked_text(content_html, content)
    out, seen = [], set()
    for k, href in enumerate(hrefs):
        try:
            absolute = urljoin(url or "", href)
            if not absolute.lower().startswith(("http://", "https://")):
                continue
            address = normalize_url(absolute)
        except ValueError:
            continue
        if not address or address in seen:
            continue
        seen.add(address)
        m = re.search(_OPEN + str(k) + _MID + "(.*?)" + _END, text, re.S)
        out.append((address, absolute, " ".join(m.group(1).split()) if m else ""))
    return out
