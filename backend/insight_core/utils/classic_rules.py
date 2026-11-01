"""Classics (issue 0051): what your sources keep citing. Pure functions over plain data; the story
job (services/news_service.py) loads the links and writes what these return.

- **A classic** is a page linked by 2+ of your voices (not the page's own), with links 180+ days
  apart: a stored post or an outside page. Reference pages (a path segment like `docs`,
  `pricing`, `help`) and home pages are not classics.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from insight_core.utils.addresses import bare, publication_of, site_of
from insight_core.utils.post_links import is_reference, titled_link_text

CLASSIC_MIN_VOICES = 2   # the prototype's (plan/research/dedup-prototype), not measured
# Measured on the server's data, 2026-10-30 (0051): at 30 days most were news with legs (~15% real
# classics in a sample); at 180, 172 classics, ~80% real in a random 30.
CLASSIC_MIN_SPREAD = timedelta(days=180)
CLASSIC_CITED_AGAIN = timedelta(days=7)   # cited in the last 7 days: "cited again this week", first; not measured
BACKGROUND_SHOWN = 2


# ---- Classics -------------------------------------------------------------------------------


@dataclass
class Citation:
    """One kept link: who linked what, when."""

    voice: str
    name: str                        # the voice as you know it (a source's name, u/<author>)
    source_id: str
    t: datetime
    target: str                      # normalized address
    stored: Optional[str] = None     # the stored post it is, if any
    text: Optional[str] = None       # the link's words


@dataclass
class Classic:
    target: str
    post_id: Optional[str]
    voices: int
    first_at: datetime               # the stored post's date, else the first link
    last_at: datetime                # the last link
    title: Optional[str]
    citers: List[Dict[str, object]] = field(default_factory=list)   # each voice once, first citation first

    @property
    def days(self) -> int:
        return (self.last_at - self.first_at).days


_titled = titled_link_text   # moved to post_links (issue 0064: a story's outside origin is titled so too)


def classics(citations: Iterable[Citation], stored: Dict[str, Tuple[str, datetime, Optional[str]]]) -> List[Classic]:
    """The classics among `citations`, most voices first, then cited longest.
    `stored`: post id -> (its voice, its date, its title) for the stored posts linked."""
    by_target: Dict[str, List[Citation]] = defaultdict(list)
    for c in citations:
        if c.stored is not None and c.stored not in stored:
            continue
        by_target[c.target].append(c)
    out = []
    for target, cites in by_target.items():
        host = bare(target).split("/", 1)[0]
        own = {"site:" + publication_of(host), "site:" + site_of(host)}   # its own publication, or site's
        post = stored.get(cites[0].stored) if cites[0].stored else None
        if post is not None:
            own.add(post[0])
        elif is_reference(target):
            continue
        cites = sorted(cites, key=lambda c: (c.t, c.source_id))
        counted = [c for c in cites if c.voice not in own]
        voices = {c.voice for c in counted}
        if len(voices) < CLASSIC_MIN_VOICES:
            continue
        # The spread starts at the stored post's own date, else at the second voice's first link:
        # one voice's date alone can't make a classic (a page rewritten under an old date, like
        # Gwern's, dated a 2026 link 2023 on the server's data).
        firsts = sorted({c.voice: c.t for c in reversed(counted)}.values())
        first = post[1] if post is not None else firsts[1]
        last = cites[-1].t
        if last - first < CLASSIC_MIN_SPREAD:
            continue
        citers: Dict[str, Dict[str, object]] = {}
        for c in counted:
            entry = citers.setdefault(c.voice, {"voice": c.voice, "name": c.name, "at": c.t.isoformat(), "source_ids": []})
            if c.source_id not in entry["source_ids"]:   # type: ignore[operator]
                entry["source_ids"].append(c.source_id)   # type: ignore[union-attr]
        texts = Counter(c.text for c in cites if _titled(c.text))
        title = post[2] if post is not None else (texts.most_common(1)[0][0] if texts else None)
        out.append(Classic(target, cites[0].stored, len(voices), first, last, title, list(citers.values())))
    return sorted(out, key=lambda c: (-c.voices, -c.days, c.target))


def cited_again(classic_last_at: datetime, now: datetime) -> bool:
    return classic_last_at >= now - CLASSIC_CITED_AGAIN


def classic_order(classic_last_at: datetime, voices: int, days: int, target: str, now: datetime) -> Tuple:
    """Cited again this week first, then most voices, then cited longest. Age never counts against."""
    return (not cited_again(classic_last_at, now), -voices, -days, target)


__all__ = ["Citation", "Classic", "classics", "cited_again", "classic_order"]
