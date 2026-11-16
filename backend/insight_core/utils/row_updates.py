"""Whether a News row the reader has seen has a meaningful update since (issue 0217 Part 2, Stealth v10.23). Pure.

`update(seen, new) -> Update`: `seen` are the row's posts the reader saw when they last opened it, `new` the posts it
gained since, each a `Line` (its voice, its stage, its kind of line, its numbers, whether it copies another post,
whether it corrects or denies). The update is meaningful when a new post brings any of:
  - **a new stage** of the happening: rumoured < announced (a teaser, a preview) < released (the launch);
  - **a new kind of line** of a release: availability on a platform or a price (a product release or pricing after the
    launch), benchmark or evaluation results (a research result);
  - **new numbers**: a number (a price, a score, a size) no seen post said (dates and years are not numbers here);
  - **a correction or a denial**;
  - **new independent sources**: `MIN_SOURCES` or more voices the row did not have, each with a post that is not a
    repost or a copy of a post already in the row, and that reports (a share or a reaction is no source).
Plain repetition (the same numbers, the same stage, more reposts) is not. `Update.what` names the first reason in that
order ("launch", "availability", "benchmarks", "new numbers", "correction", "new sources"), `sources` counts the new
independent voices (the "+N sources" the reader sees)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import FrozenSet, Iterable, List, Optional, Sequence, Tuple

STAGES = {"rumored": 0, "announced": 1, "released": 2}
STAGE_WORDS = {0: "rumour", 1: "announcement", 2: "launch"}
LINE_KINDS = {"product_release": "availability", "pricing": "availability", "research_result": "benchmarks"}
MIN_SOURCES = 2          # new independent voices that alone make an update (one new outlet is no news)
_MONTHS = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_DATE = re.compile(rf"^(?:{_MONTHS}\.?\s+\d{{1,2}}(?:,?\s*\d{{4}})?|\d{{1,2}}\s+{_MONTHS}(?:\s+\d{{4}})?|"
                   rf"(?:19|20)\d\d|\d{{4}}-\d\d(?:-\d\d)?|q[1-4](?:\s+\d{{4}})?|{_MONTHS}\s+\d{{4}})$", re.I)
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Line:
    id: str
    voice: str
    stage: Optional[str] = None            # rumored | announced | released | None
    kind: Optional[str] = None             # the closed event type of the post (event_types), None: unknown
    numbers: Tuple[str, ...] = ()          # the reading's main numbers as written
    copy_of: Optional[str] = None          # a post of the row it repeats (a repost, a near copy), None: its own
    report: bool = True                    # False: a share, a quote or a reply (no independent source)
    corrects: bool = False                 # a correction or a denial


@dataclass(frozen=True)
class Update:
    meaningful: bool
    what: Optional[str] = None
    reasons: Tuple[str, ...] = ()
    sources: int = 0
    lines: FrozenSet[str] = field(default_factory=frozenset)   # the new posts that carry it (marked for the reader)


def numbers(said: Iterable[str]) -> FrozenSet[str]:
    """The numbers a reading says, each as digits ("$1.50/M" -> "1.50"), dates and years left out."""
    out = set()
    for s in said:
        s = (s or "").strip()
        if not s or _DATE.match(s):
            continue
        for n in _NUM.findall(s):
            n = n.replace(",", ".")
            if re.fullmatch(r"(?:19|20)\d\d", n):
                continue
            out.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return frozenset(out)


def update(seen: Sequence[Line], new: Sequence[Line]) -> Update:
    seen_ids = {x.id for x in seen}
    new = sorted((x for x in new if x.id not in seen_ids), key=lambda x: x.id)
    if not new:
        return Update(False)
    reasons: List[str] = []
    carry = set()
    top = max((STAGES[x.stage] for x in seen if x.stage in STAGES), default=-1)
    staged = [x for x in new if x.stage in STAGES and STAGES[x.stage] > top]
    if staged:
        reasons.append(STAGE_WORDS[max(STAGES[x.stage] for x in staged)])
        carry |= {x.id for x in staged}
    had = {LINE_KINDS.get(x.kind) for x in seen}
    for x in new:
        line = LINE_KINDS.get(x.kind or "")
        if line and line not in had and x.copy_of is None:
            if line not in reasons:
                reasons.append(line)
            carry.add(x.id)
    known = set().union(*(numbers(x.numbers) for x in seen)) if seen else set()
    fresh = [x for x in new if x.copy_of is None and numbers(x.numbers) - known]
    if fresh:
        reasons.append("new numbers")
        carry |= {x.id for x in fresh}
    fixes = [x for x in new if x.corrects]
    if fixes:
        reasons.append("correction")
        carry |= {x.id for x in fixes}
    voices = {x.voice for x in seen}
    independent = {}
    for x in new:
        if x.voice not in voices and x.copy_of is None and x.report:
            independent.setdefault(x.voice, x.id)
    if len(independent) >= MIN_SOURCES:
        reasons.append("new sources")
        carry |= set(independent.values())
    return Update(bool(reasons), reasons[0] if reasons else None, tuple(reasons), len(independent), frozenset(carry))


__all__ = ["Line", "Update", "update", "numbers", "MIN_SOURCES"]
