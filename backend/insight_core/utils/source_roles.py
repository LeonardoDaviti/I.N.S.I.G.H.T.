"""Who a source is, by what its posts are about (issue 0132): shared by the voices (Part A, voices_service) and the
source analysis page (Part B, its role rule). Pure functions over plain data, and one loader (`load_reads`).

The role rule's step 3, **official**: the source itself is the subject, actor or venue of at least OFFICIAL_SHARE of
its read original posts (OFFICIAL_MIN_READ of them at least), matched by its name, its handle, its site's label or
an acronym of the name a post gives (a government institute's initials as its address writes them). Measured on the
server copy of 2026-11-05 (the lab's sources_v1): 12 sources official, all right by reading; 2 missed.

Step 4, **focused** (staff or beat): FOCUSED_SHARE of its read posts about one maker that is not itself.

Names are compared by `name_tokens`: the words of a name, a camel-cased handle split, at least 4 letters, no
generic word (GENERIC: words any name can hold, never a site's or a person's); and the name squashed when 5+ letters.
No list of known sites anywhere: only what the source and its posts say.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set

OFFICIAL_SHARE = 0.3        # measured (sources_v1): 12 official, all right
OFFICIAL_MIN_READ = 5       # read original posts, at least
FOCUSED_SHARE = 0.5         # measured: at 0.3 critics landed here too
SELF_ROLES = ("subject", "actor", "venue")

GENERIC = frozenset("""blog blogs news feed feeds rss atom xml www com org net io dev me ai ml the a of and for on in
to my research lab labs engineering tech channel daily weekly monthly notes thoughts official tv video videos media hq
inc github gist medium substack bearblog blogspot dreamwidth index main default posts post articles article resources
letter newsletter digest latest recent updates thread circuits from science data learning deep machine page pages
everything space world online home log web site real good things more just links""".split())
_SPLIT = re.compile(r"[^0-9A-Za-zА-Яа-яёЁ]+")
_CAMEL = re.compile(r"([a-z])([A-Z])")
_MAKER_TAIL = re.compile(r"\s+(ai|inc|labs?|llc|ltd|corp|corporation|research)$")


def name_tokens(*names: Optional[str]) -> Set[str]:
    """The words a name is known by: each word of 4+ letters (a camel-cased handle split, trailing digits off), no
    GENERIC word; and the whole name squashed (letters and digits only) when 5+ long."""
    out: Set[str] = set()
    for name in names:
        if not name:
            continue
        split = _CAMEL.sub(r"\1 \2", name)
        for token in _SPLIT.split(split.lower()):
            token = re.sub(r"\d+$", "", token)
            if len(token) >= 4 and token not in GENERIC:
                out.add(token)
        squashed = re.sub(r"[^0-9a-zа-яё]+", "", name.lower())
        if len(squashed) >= 5 and squashed not in GENERIC:
            out.add(squashed)
    return out


def acronym(name: Optional[str]) -> Optional[str]:
    """A name's initials (words of 3+ letters; a short word whole), for names of 2+ words: "Lab Safety Institute"
    -> "lsi"."""
    words = [w for w in re.split(r"[^a-z0-9]+", (name or "").lower()) if w and w not in ("of", "the", "and", "for")]
    return "".join(w if len(w) <= 2 else w[0] for w in words) if len(words) >= 2 else None


def maker_key(name: Optional[str]) -> str:
    """A maker's name as two sources share it: lower case, no punctuation, no company ending ("Lab AI Inc." -> "lab")."""
    text = re.sub(r"\s+", " ", re.sub(r"[,.]", " ", (name or "").strip().lower())).strip()
    previous = None
    while previous != text:
        previous, text = text, _MAKER_TAIL.sub("", text).strip()
    return text


@dataclass(frozen=True)
class Mention:
    """One entity a read post names (Mark X's mx_mentions): its name, its role, its maker."""

    name: str
    role: Optional[str] = None
    maker: Optional[str] = None
    type: Optional[str] = None


@dataclass(frozen=True)
class Official:
    """A source is official for `maker`: `share` of its `n` read original posts have itself as subject, actor or
    venue (`hits` of them). `line`: the rule's line that decided it; `posts`: up to 3 example posts."""

    maker: str
    share: float
    n: int
    hits: int
    line: str
    posts: tuple = ()


@dataclass(frozen=True)
class Focus:
    """The maker most of a source's read original posts are about (subject or actor), with its share."""

    maker: str
    share: float
    n: int


def is_self(mention: Mention, tokens: Set[str], squashed: Set[str]) -> bool:
    """A mention that names the source itself: by a name word, by the whole name squashed (a handle, a site label),
    or by its acronym (3+ letters) among the source's names."""
    for name in (mention.name, mention.maker):
        if not name:
            continue
        if name_tokens(name) & tokens:
            return True
        sq = re.sub(r"[^0-9a-z]+", "", name.lower())
        if len(sq) >= 3 and sq in squashed:
            return True
        short = acronym(name)
        if short and len(short) >= 3 and (short in tokens or short in squashed):
            return True
    return False


def self_names(names: Iterable[Optional[str]], handles: Iterable[Optional[str]] = ()) -> tuple:
    """(tokens, squashed): what a source is called, as is_self compares it. `names`: its display names; `handles`:
    its handles and site labels, squashed whole (a 3-letter label counts there)."""
    names = [n for n in names if n]
    handles = [h for h in handles if h]
    tokens = name_tokens(*names, *handles)
    squashed = {re.sub(r"[^0-9a-z]+", "", h.lower()) for h in handles} | {re.sub(r"[^0-9a-z]+", "", n.lower()) for n in names}
    return tokens, {s for s in squashed if len(s) >= 3}


def official(reads: Mapping[str, Sequence[Mention]], tokens: Set[str], squashed: Set[str]) -> Optional[Official]:
    """The role rule's step 3 for one source: `reads` its read original posts (post id -> its mentions; a read post
    with none is still read). Official when OFFICIAL_SHARE of OFFICIAL_MIN_READ+ name itself as subject, actor or
    venue; its maker is the self-mention's maker (else name) said most."""
    n = len(reads)
    if n < OFFICIAL_MIN_READ:
        return None
    hits, makers = [], Counter()
    for post_id in sorted(reads):
        selves = [m for m in reads[post_id] if m.role in SELF_ROLES and is_self(m, tokens, squashed)]
        if selves:
            hits.append(post_id)
            makers.update({maker_key(m.maker or m.name) for m in selves})
    share = len(hits) / n
    if share < OFFICIAL_SHARE or not makers:
        return None
    maker = sorted(makers.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return Official(maker=maker, share=round(share, 2), n=n, hits=len(hits),
                    line=f"{share:.0%} of {n} read own posts have the source itself as subject, actor or venue",
                    posts=tuple(hits[:3]))


def focus(reads: Mapping[str, Sequence[Mention]]) -> Optional[Focus]:
    """The maker its read original posts are most about (subject or actor; an org's or person's own name when it
    has no maker), with its share of them; None with no read post."""
    n = len(reads)
    if not n:
        return None
    counts: Counter = Counter()
    for mentions in reads.values():
        counts.update({maker_key(m.maker or (m.name if m.type in ("org", "person") else None))
                       for m in mentions if m.role in ("subject", "actor") and (m.maker or m.type in ("org", "person"))})
    counts.pop("", None)
    if not counts:
        return None
    maker, k = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    return Focus(maker=maker, share=round(k / n, 2), n=n)


def load_reads(cur: Any, own_posts: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, List[Mention]]]:
    """source id -> {read post id -> its mentions}: Mark X's readings (mx_readings) of each source's original posts
    (not a repost: no reposted_by, its own account's on X), with their mentions. Empty when Mark X has read nothing.
    `own_posts`: only these posts (the caller told reposts apart)."""
    wanted = None if own_posts is None else sorted(set(own_posts))
    cur.execute(
        """SELECT p.source_id::text, r.post_id::text FROM (SELECT DISTINCT post_id FROM mx_readings) r
           JOIN posts p ON p.id = r.post_id
           WHERE (%(ids)s::uuid[] IS NULL OR p.id = ANY(%(ids)s::uuid[]))
             AND COALESCE(cardinality(p.reposted_by), 0) = 0""",
        {"ids": wanted})
    out: Dict[str, Dict[str, List[Mention]]] = {}
    source_of: Dict[str, str] = {}
    for source_id, post_id in cur.fetchall():
        out.setdefault(source_id, {})[post_id] = []
        source_of[post_id] = source_id
    if not source_of:
        return out
    cur.execute("""SELECT DISTINCT post_id::text, name, role, maker, type FROM mx_mentions
                   WHERE post_id = ANY(%s::uuid[])""", (sorted(source_of),))
    for post_id, name, role, maker, type_ in cur.fetchall():
        out[source_of[post_id]][post_id].append(Mention(name=name, role=role, maker=maker, type=type_))
    return out


__all__ = ["OFFICIAL_SHARE", "OFFICIAL_MIN_READ", "FOCUSED_SHARE", "GENERIC", "Mention", "Official", "Focus", "name_tokens",
           "acronym", "maker_key", "is_self", "self_names", "official", "focus", "load_reads"]
