"""The citation rule (issue 0133 part 3): the documents a post cites, found with no model, merged with the entities
answer's own. It runs when an entities answer under an arm with the rule (schemas.ENTITY_ARMS: ent-v4 and its
fallback, never ent-v3) is recorded, over the post's full stored text (not the task's cut) and its post_refs links.
Each hit is a mention: type `document`, role `source`, rule `citation`.

  - **In-text citations** ("Author et al. (YYYY)", "Author (YYYY)", "Author & Author (YYYY)", "Author and Author,
    YYYY"; English and Russian). FIRST SET: these patterns are the spec's listed shapes, written before the lab's
    frozen report (plan/research/lab/markx/proto/out/entv41_v1/REPORT.md); the report's patterns replace
    IN_TEXT (and PATTERNS_VERSION) when it passes. Nothing else here waits for it.
  - **Identifiers** (final): arXiv ids and links (arXiv:2401.01234, arxiv.org/abs|pdf|html/..., the arXiv DOI), DOIs.
  - **Links to documents** (final): every open, non-boilerplate post_refs link whose candidates.document_key is a
    document (a paper by its id; a record or a filing by 0109's address shapes).

Merged with the answer's mentions (`merge`): a hit and a model document naming the same thing (the same DOI or arXiv
id in its span or name, or the same name key) are one mention: the rule's span is kept, the model's role and name
win, and it carries rule 'citation' and the identifier (`ref`, which identity joins across posts). The rest of the
hits are mentions of their own after the model's, at most MAX_HITS.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

RULE = "citation"
TYPE, ROLE = "document", "source"
MAX_HITS = 60                  # a post's hits kept (the lab's reference lists held up to ~30 items a post)
PATTERNS_VERSION = "0133-first-set"   # replaced with the frozen report's patterns

_YEAR = r"(?:19|20)\d{2}[a-z]?"
_LAT = r"[A-Z][a-z]+(?:[-'][A-Z]?[a-z]+)?"
_CYR = r"[А-ЯЁ][а-яё]+(?:-[А-ЯЁ]?[а-яё]+)?"
_NAME = rf"(?:{_LAT}|{_CYR})"
_AND = r"(?:&|and|и)"
_ETAL = r"(?:et\s+al\.?|и\s+др\.?|и\s+соавт\.?)"

# FIRST SET (0133): the spec's shapes; the frozen lab report's patterns replace these. Order matters: a longer shape
# first, and a span a hit took is not read again.
IN_TEXT: Tuple[Tuple[str, "re.Pattern[str]"], ...] = (
    ("etal", re.compile(rf"\b(?P<a>{_NAME})\s+{_ETAL},?\s*\(?(?P<y>{_YEAR})\)?")),
    ("two_paren", re.compile(rf"\b(?P<a>{_NAME})\s+{_AND}\s+(?P<b>{_NAME}),?\s*\((?P<y>{_YEAR})\)")),
    ("two_comma", re.compile(rf"\b(?P<a>{_NAME})\s+{_AND}\s+(?P<b>{_NAME}),\s+(?P<y>{_YEAR})\b")),
    ("one_paren", re.compile(rf"\b(?P<a>{_NAME})\s+\((?P<y>{_YEAR})\)")),
)

ARXIV_ID = r"\d{4}\.\d{4,5}"
_ARXIV = re.compile(rf"(?:arxiv\.org/(?:abs|pdf|html)/|\barXiv:\s?|10\.48550/arxiv\.)(?P<id>{ARXIV_ID})(?:v\d+)?",
                    re.I)
_DOI = re.compile(r"\b(?P<doi>10\.\d{4,9}/[^\s\"'<>()\[\]{}]+)", re.I)
_DOI_END = re.compile(r"[.,;:]+$")


@dataclass(frozen=True)
class Hit:
    span: str              # the words or link the rule read
    name: str              # the mention's name
    ref: Optional[str]     # the identifier ("arXiv:<id>", "doi:<doi>", "page:<address>"); None for an in-text one
    how: str               # which shape found it (etal, two_paren, ..., arxiv, doi, link)

    def mention(self, name_key) -> Dict[str, Any]:
        return {"span": self.span, "name": self.name, "name_key": name_key(self.name), "type": TYPE, "role": ROLE,
                "rule": RULE, "ref": self.ref, "maker": None, "family": None, "version": None, "variant": None,
                "size": None, "build": None, "by_name": None}


_VERSION_END = re.compile(r"v\d+$")


def arxiv_ref(i: str) -> str:
    return "arXiv:" + _VERSION_END.sub("", i)


def doi_ref(d: str) -> str:
    d = _DOI_END.sub("", d).lower()
    m = re.match(rf"10\.48550/arxiv\.({ARXIV_ID})", d)
    return arxiv_ref(m.group(1)) if m else f"doi:{re.sub(r'(?<=\d)v\d+$', '', d)}"


def ids_in(text: str) -> List[str]:
    """The identifiers (arXiv ids, DOIs) a text names, as refs, in order."""
    out: List[str] = []
    for m in _ARXIV.finditer(text or ""):
        out.append(arxiv_ref(m.group("id")))
    for m in _DOI.finditer(text or ""):
        r = doi_ref(m.group("doi"))
        if r not in out:
            out.append(r)
    return out


def link_ref(url: str) -> Optional[str]:
    """The ref of a link to a document (candidates.document_key), else None."""
    from insight_core.markx.candidates import document_key
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    key = document_key(url)
    if key is None:
        return None
    if key.startswith("paper:"):
        pid = key.rsplit(":", 1)[1]
        if re.fullmatch(ARXIV_ID, pid):
            return arxiv_ref(pid)
        if pid.startswith("10."):
            return doi_ref(pid)
    return key


def in_text(text: str) -> List[Hit]:
    taken: List[Tuple[int, int]] = []
    out: List[Tuple[int, Hit]] = []
    for how, pat in IN_TEXT:
        for m in pat.finditer(text or ""):
            s, e = m.span()
            if any(s < te and ts < e for ts, te in taken):
                continue
            taken.append((s, e))
            a, y = m.group("a"), m.group("y")
            b = m.groupdict().get("b")
            if how == "etal":
                name = f"{a} et al. {y}"
            elif b:
                name = f"{a} and {b} {y}"
            else:
                name = f"{a} {y}"
            out.append((s, Hit(m.group(0), name, None, how)))
    return [h for _, h in sorted(out, key=lambda x: x[0])]


def find(text: str, links: Iterable[str] = ()) -> List[Hit]:
    """Every hit of a post: its identifiers, its document links, then its in-text citations (one hit a ref)."""
    hits: List[Hit] = []
    refs = set()
    for m in list(_ARXIV.finditer(text or "")) + list(_DOI.finditer(text or "")):
        r = arxiv_ref(m.group("id")) if "id" in m.groupdict() else doi_ref(m.group("doi"))
        if r not in refs:
            refs.add(r)
            hits.append(Hit(m.group(0), r, r, "arxiv" if r.startswith("arXiv:") else "doi"))
    for url in links:
        r = link_ref(url)
        if r and r not in refs:
            refs.add(r)
            hits.append(Hit(url, r[5:] if r.startswith("page:") else r, r, "link"))
    return hits + in_text(text)


def merge(mentions: Sequence[Dict[str, Any]], hits: Sequence[Hit], name_key) -> List[Dict[str, Any]]:
    """The answer's mentions with the rule's hits merged in (see the module's doc), in order: the model's first."""
    out = [dict(m) for m in mentions]
    docs = [m for m in out if m.get("type") in (TYPE, "paper")]
    ids = [set(ids_in(f"{m.get('span') or ''} {m.get('name') or ''}")) for m in docs]
    keys = [m.get("name_key") or name_key(m.get("name")) for m in docs]
    extra: List[Dict[str, Any]] = []
    for h in hits:
        hk = name_key(h.name)
        at = next((k for k, m in enumerate(docs) if (h.ref and h.ref in ids[k]) or (hk and hk == keys[k])), None)
        if at is not None:
            m = docs[at]
            if m.get("rule") != RULE:          # the first hit naming it: its span and its identifier
                m.update(rule=RULE, span=h.span, ref=h.ref or m.get("ref"))
            continue
        if len(extra) < MAX_HITS and all(x["name_key"] != hk for x in extra):
            extra.append(h.mention(name_key))
    return out + extra


def post_links(cur: Any, post_id: Any) -> List[str]:
    """The post's open, non-boilerplate post_refs addresses, in order (0125)."""
    cur.execute("""SELECT target_address FROM post_refs WHERE post_id = %s AND valid_to IS NULL AND NOT boilerplate
                    ORDER BY position""", (post_id,))
    return [r[0] for r in cur.fetchall()]


def for_post(cur: Any, post_id: Any, mentions: Sequence[Dict[str, Any]], name_key) -> List[Dict[str, Any]]:
    """The rule run on a stored post (its full text, its links) and merged with `mentions`."""
    from insight_core.markx import tasks
    p = tasks.load_posts(cur, [post_id]).get(str(post_id))
    text = "\n".join(x for x in ((p.title if p else ""), (p.text if p else "")) if x)
    links = post_links(cur, post_id) + [u for u, _ in (p.links if p else [])]   # post_refs, then the kept links
    return merge(mentions, find(text, links), name_key)
