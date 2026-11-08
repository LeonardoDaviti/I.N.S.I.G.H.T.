"""ent-v4.2 in Shadow (issue 0133, the handoff of 2026-11-08): the second question, its cue rule, the merge, and the
owner's labels on the new entities. The lab's code (plan/research/lab/markx/proto: entv42_run.cue, entv4_sets.CUES,
entv42_rule.shape / cite_fix / merge_cite / name_span / finish with the rule off, entv41_rule's text forms and
own_title), ported with its tests (tests/test_markx_ent_v42.py).

  - **The arm** (schemas.ENTITY_ARMS["ent-v4.2"]): the main question, guides/ent-v4.2.md at 6,000 characters with
    ENTITIES_V4_SCHEMA. **The citation rule is off** for it (markx/citations.py is never called): it was 66-73%
    right in the lab; it comes back with ent-v4.3's own-paper guard.
  - **The second question** (kind `cite`, guides/cite-v1.md): every document and cited organisation or person, and
    nothing else; at 6,000 characters plus the post's first 12 links; at most 30. Planned only while the switch is on
    ent-v4.2, only for posts the cue rule picks (`cue`, about 15% of posts) and that have an ent-v4.2 entities task.
  - **The merge** (`finish`): the post's own title dropped as a document (main and cite); the cite answer's
    author-year people and orgs made documents (`cite_fix`); then `merge_cite` adds what the main answer lacks,
    marked q2 (mx_mentions.rule = 'q2'). Whichever answer comes second does it: a main answer merges the post's
    answered cite answer at once; a cite answer after the main one appends its new entities to the ent-v4.2 set.
  - **Labels**: right / wrong on each new entity (a document, a `source`, a `recommended`, every q2 one), mx_labels
    item kind `mention` (migration 0087), and the running precision with its Wilson interval.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, List, Optional, Sequence

from insight_core.markx import repo, schemas, tasks

GUIDE = "ent-v4.2"
CITE_KIND, CITE_GUIDE = "cite", "cite-v1"
CITE_CHARS, CITE_LINKS = 6000, 12
CITE_MAX = 30
Q2 = "q2"                                  # mx_mentions.rule of an entity the second question added
LAB = "lab: 89–93% precise, finds about 62%; post hoc"
LEAVE_AT = (100, 0.85)                     # leaving Shadow: 100+ labelled new entities, lower bound >= 85%
LABEL_KIND = "mention"
ANSWERS = ("right", "wrong")


def fold(s: Optional[str]) -> str:
    """The lab's fold (ent2.fold): NFKC, casefold, ё as е, every dash as '-', one space."""
    s = unicodedata.normalize("NFKC", s or "").casefold().replace("ё", "е")
    s = re.sub(r"[‐-―−­-]", "-", s)
    return re.sub(r"\s+", " ", s)


# ---- the cue rule (entv42_run.cue) ------------------------------------------------------------------

CUES = re.compile(r"(?i)\b(report|study|studies|paper|survey|forecast|filing|S-1|10-K|10-Q|white ?paper|preprint|according to|"
                  r"estimates?|analysts?|data from|research(?:ers)? (?:from|at|by)|found that|poll|predicts?|projections?|"
                  r"model card|system card|prospectus|index|ranking)\b|"
                  r"(отч[её]т|исследовани|доклад|опрос|прогноз|по данным|согласно|по оценк|по мнению|препринт|аналитик|"
                  r"рейтинг|индекс|проспект|статья|стать[еи])")


def cues(text: str) -> set:
    return {m.group(0).lower()[:6] for m in CUES.finditer(text)}


# ent-v4.1's text forms (entv41_rule): author-year citations, arXiv ids, DOIs
YEAR = r"(?:1[89]\d\d|20[0-3]\d)[a-z]?"
SUR = r"(?:(?:van|von|de|der|da|di|du|le|la)\s)?[A-ZА-ЯЁ][a-zа-яё]+(?:[A-ZА-ЯЁ][a-zа-яё]+)?(?:[-'’][A-ZА-ЯЁa-zа-яё]+)*"
ETAL = r"(?:et\s?al\.?|и\s?др\.?)"
AND = r"(?:&amp;|&|and|и)"
NOTNAME = {fold(w) for w in (
    "January February March April May June July August September October November December Jan Feb Mar Apr Jun Jul "
    "Aug Sep Sept Oct Nov Dec Monday Tuesday Wednesday Thursday Friday Saturday Sunday In On Since Until From By Of "
    "The This That These Those Before After During Around About Circa Spring Summer Autumn Fall Winter Q1 Q2 Q3 Q4 "
    "Январь Февраль Март Апрель Май Июнь Июль Август Сентябрь Октябрь Ноябрь Декабрь В С До После Году Год").split()}
T1 = re.compile(rf"\b({SUR})\s{ETAL},?\s\(?({YEAR})\)?")
T2 = re.compile(rf"\b({SUR})\s{AND}\s({SUR}),?\s\(({YEAR})\)")
T3 = re.compile(rf"\b({SUR})\s\(({YEAR})\)")
PAREN = re.compile(r"\(([^()]{4,300})\)")
INPAREN = re.compile(rf"^\s*(?:see\s|e\.g\.,?\s|cf\.\s)?({SUR})(?:\s{ETAL}|\s{AND}\s({SUR}))?,?\s({YEAR})\s*$")
ARXIV = re.compile(r"(?i)\barxiv(?:\.org/(?:abs|pdf|html)/|:\s?)(\d{4}\.\d{4,5})(?:v\d+)?")
DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>()\[\]]+[^\s\"'<>()\[\].,;:])")


def author_year(text: str) -> bool:
    """Whether the text holds an author-year citation (T1-T3, and the parenthesis lists)."""
    if T1.search(text) or T2.search(text):
        return True
    if any(fold(m.group(1)) not in NOTNAME for m in T3.finditer(text)):
        return True
    for p in PAREN.finditer(text):
        for part in p.group(1).replace("&amp;", "&").split(";"):
            m = INPAREN.match(part)
            if m and fold(m.group(1)) not in NOTNAME:
                return True
    return False


def in_text(text: str) -> bool:
    """ent-v4.1's text forms in the first 6,000 characters: an author-year citation, an arXiv id, a DOI."""
    t = (text or "")[:CITE_CHARS]
    return author_year(t) or ARXIV.search(t) is not None or DOI.search(t) is not None


def _host_path(url: str):
    u = re.sub(r"(?i)^https?://", "", url or "")
    host, _, rest = u.partition("/")
    path, _, query = rest.partition("?")
    return host.lower(), "/" + path, query


PMC = re.compile(r"(?i)(?:^|/)(PMC\d{5,9})(?:/|$|\.)")
PMID = re.compile(r"/(\d{6,9})(?:/|$)")
PII_SEG = re.compile(r"(?i)/pii/([A-Z0-9()%\-]{10,30})")
PII_SHAPE = re.compile(r"(?i)/(S\d{4}-?\d{3}[\dX](?:\(|%28)?\d{2}(?:\)|%29)?\d{5}-?[\dX])(?:/|$)")
RFC = re.compile(r"(?i)\brfc[-_]?0*(\d{1,5})\b")
ECMA = re.compile(r"(?i)\becma-(\d{2,4})\b")
ISO = re.compile(r"(?i)/standards?/(\d{3,6})(?:\.html)?(?:/|$)")
SSRN = re.compile(r"(?i)\babstract(?:_id)?=(\d{5,9})")
OSF = re.compile(r"^/(?:preprints/[a-z]+/)?([a-z0-9]{5})(?:/|$)")
NATID = re.compile(r"/(s\d{5}-\d{3}-\d{4,5}-[\dxX])(?:/|$|\.)")
OREV = re.compile(r"(?i)^/(?:forum|pdf)$")
OREV_ID = re.compile(r"(?i)\bid=([A-Za-z0-9_\-]{8,})")
ACL = re.compile(r"/(\d{4}\.[a-z\-]+\.\d+|[A-Z]\d{2}-\d{4})(?:\.pdf)?/?$")


def shape(url: Optional[str]):
    """(shape, id) for a link to a document (entv42_rule.shape: the product's document_key, then PMC, PubMed, PII,
    RFC, ECMA, ISO, SSRN, OSF, a Springer Nature article id, OpenReview, ACL Anthology), else None. Used by the cue."""
    from insight_core.markx.candidates import document_key
    if not url:
        return None
    host, path, query = _host_path(url)
    k = document_key(url)
    if k and k.startswith("paper:"):
        pid = k.split(":", 2)[2]
        return ("arxiv" if re.match(r"\d{4}\.\d{4,5}$", pid) else "doi"), pid
    for name, rx, where in (("pmc", PMC, path), ("pubmed", PMID, path if "pubmed" in host else ""),
                            ("pii", PII_SEG, path), ("pii", PII_SHAPE, path), ("rfc", RFC, path), ("ecma", ECMA, path)):
        m = rx.search(where)
        if m:
            return name, m.group(1)
    m = ISO.search(path)
    if m and "iso" in host.split(".")[-2:][0]:
        return "iso", m.group(1)
    m = SSRN.search(path + "?" + query)
    if m and "ssrn" in host:
        return "ssrn", m.group(1)
    if host.endswith("osf.io"):
        m = OSF.match(path)
        if m:
            return "osf", m.group(1)
    m = NATID.search(path)
    if m:
        return "natid", m.group(1).lower()
    if OREV.match(path):
        m = OREV_ID.search(query)
        if m:
            return "orev", m.group(1)
    m = ACL.search(path)
    if m and "anthology" in host:
        return "acl", m.group(1)
    if k:
        return "page", k
    return None


def cue(p: tasks.Post) -> bool:
    """The second question's cue rule (the lab's population share 15.1%): a text of >= 800 characters with >= 2
    distinct citation cues, or an in-text citation (author-year, arXiv id, DOI) in the first 6,000 characters, or one
    of the first 12 links with a document shape."""
    t = (p.title or "") + " " + (p.text or "")
    if len(p.text or "") >= 800 and len(cues(t)) >= 2:
        return True
    if in_text(p.text):
        return True
    return any(shape(u) for u, _a in (p.links or [])[:CITE_LINKS])


# ---- the merge (entv42_rule.finish with the rule off) -------------------------------------------------------------

STOP = {"the", "a", "an", "of", "and", "in", "on", "for", "to", "with", "et", "al", "by", "is", "are", "from", "at"}


def _toks(s: Optional[str]) -> set:
    return {t for t in re.findall(r"\w+", fold(s)) if t not in STOP and len(t) > 1}


def own_title(e: Dict[str, Any], title: Optional[str]) -> bool:
    """A document that is the post's own title: its name or span carries >= 80% of the title's words."""
    if schemas.entity_type(e.get("type")) != "document":
        return False
    tt = _toks(title)
    if len(tt) < 2:
        return False
    et = _toks(e.get("name")) | _toks(e.get("span"))
    return len(tt & et) >= 0.8 * len(tt)


def _same_any(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Two entities name the same thing: the same folded name, span containment (> 6 chars), the same id, or >= 60%
    of the shorter name's words."""
    an, bn = fold(a.get("name")), fold(b.get("name"))
    if an and an == bn:
        return True
    as_, bs = fold(a.get("span")), fold(b.get("span"))
    if len(as_) > 6 and len(bs) > 6 and (as_ in bs or bs in as_):
        return True
    ida = re.search(r"(\d{4}\.\d{4,5}|10\.\d{4,9}/\S+|pmc\d+|pmid \d+|rfc \d+)", an + " " + as_)
    if ida and ida.group(1) in (bn + " " + bs):
        return True
    ta, tb = _toks(a.get("name")), _toks(b.get("name"))
    if ta and tb:
        short = min(len(ta), len(tb))
        if short >= 2 and len(ta & tb) >= max(2, 0.6 * short):
            return True
    return False


def _doc(e: Dict[str, Any]) -> bool:
    return schemas.entity_type(e.get("type")) == "document"


def compatible(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return _doc(a) == _doc(b)


ETAL_ANY = re.compile(r"(?i)\bet\.?\s?al\b|\bat al\.|\sи\s?др\b|\s(?:&|&amp;|and|и)\s[A-ZА-ЯЁ]")


def cite_fix(c: Dict[str, Any]) -> Dict[str, Any]:
    """An academic citation the cite answer typed as a person or org ("Varga et al.") is a document."""
    span, name = c.get("span") or "", c.get("name") or ""
    if c.get("type") in ("person", "org") and ETAL_ANY.search(span + " " + name) and \
            (re.search(r"et\.?\s?al|и\s?др", span + name) or re.search(r"\b(?:1[89]|20)\d\d\b", span)):
        y = re.search(r"\b((?:1[89]|20)\d\d)[a-z]?\b", span)
        nm = re.sub(r"\s*\(?\b(?:1[89]|20)\d\d[a-z]?\)?", "", name).strip()
        return {**c, "type": "document", "role": "source", "name": f"{nm} {y.group(1)}" if y else nm}
    return c


NOT_DOC = ("model", "product", "software", "dataset", "event", "law", "other", "place")


def name_span(span: str) -> bool:
    """A span that can name a document: a link or id, a quoted title, a citation, or words starting with a capital."""
    t = (span or "").strip().strip('"“”«»\'(')
    return bool(t) and (t[:1].isupper() or t[:1].isdigit() or
                        re.match(r"(?i)https?://|www\.|arxiv|doi|t\.me/|[a-z0-9.-]+\.[a-z]{2,}/", t) is not None)


def merge_cite(main: Sequence[Dict[str, Any]], cite: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The main answer first; then the cite answer's entities the main answer lacks (same type family), marked q2."""
    out = list(main)
    for c in map(cite_fix, cite):
        if c.get("type") == "document" and c.get("role") == "subject":
            continue      # the post's subject is the main answer's job
        if c.get("type") == "document" and not name_span(c.get("span") or ""):
            continue      # a span that describes, not names
        if c.get("type") == "document" and any(m.get("type") in NOT_DOC and _same_any(c, m) for m in main):
            continue      # the main answer typed this thing as a model, software, dataset, ...: not a document
        if not any(compatible(c, m) and _same_any(c, m) for m in out):
            out.append({**c, "q2": True})
    return out


def finish(main: Sequence[Dict[str, Any]], title: Optional[str],
           cite: Optional[Sequence[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """ent-v4.2's code step, the rule off: the post's own title dropped (main and cite), the cite answer's new
    entities added."""
    kept = [e for e in main if not own_title(e, title)]
    if cite:
        kept = merge_cite(kept, [e for e in cite if not own_title(e, title)])
    return kept


# ---- the task, its planner, and what its answer writes ---------------------------------------------------------

def cite_input(p: tasks.Post) -> str:
    return tasks.post_block(p, CITE_LINKS, CITE_CHARS)


def cite_task(cur: Any, post_id: Any, priority: int = 0):
    p, = tasks._posts(cur, [post_id])
    return tasks.add(cur, CITE_KIND, cite_input(p), a=p.id, priority=priority)


_not_cue: set = set()     # the posts the cue rule passed over, in this process (not read again each lease)


def plan(cur: Any, *, days: Any = tasks.SETTING, limit: int = tasks.PLAN_LIMIT, now: Any = None) -> int:
    """`cite` tasks for the cue posts of the reading window (or `days`) that have an ent-v4.2 entities task and no
    cite task, newest first, only while the switch is on ent-v4.2: how many were added."""
    if schemas.entities_arm(cur).guide != GUIDE:
        return 0
    if days is tasks.SETTING:
        days = tasks.reading_window(cur)
    added, after = 0, None
    for _page in range(tasks.SCAN_PAGES):
        cur.execute(
            """SELECT p.id, GREATEST(0, floor(extract(epoch FROM (COALESCE(%(now)s, now())
                                        - COALESCE(p.surfaced_at, p.published_at, p.fetched_at))) / 86400))::int,
                      COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                 FROM posts p
                WHERE (%(days)s::int IS NULL OR COALESCE(p.surfaced_at, p.published_at, p.fetched_at)
                                                 >= COALESCE(%(now)s, now()) - make_interval(days => %(days)s))
                  AND EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = 'entities' AND t.guide = %(main)s AND t.a = p.id)
                  AND NOT EXISTS (SELECT 1 FROM mx_tasks t WHERE t.kind = %(kind)s AND t.guide = %(guide)s AND t.a = p.id)
                  AND (%(at)s::timestamptz IS NULL
                       OR (COALESCE(p.surfaced_at, p.published_at, p.fetched_at), p.id) < (%(at)s::timestamptz, %(id)s::uuid))
                ORDER BY COALESCE(p.surfaced_at, p.published_at, p.fetched_at) DESC, p.id DESC
                LIMIT %(limit)s""",
            {"now": now, "days": days, "main": GUIDE, "kind": CITE_KIND, "guide": CITE_GUIDE, "limit": limit,
             "at": after[0] if after else None, "id": after[1] if after else None})
        rows = cur.fetchall()
        todo = [r for r in rows if str(r[0]) not in _not_cue]
        posts = tasks.load_posts(cur, [r[0] for r in todo])
        for pid, age, _at in todo:
            if added >= limit:
                break
            p = posts.get(str(pid))
            if p is None:
                continue
            if not cue(p):
                _not_cue.add(p.id)
                continue
            if tasks.add(cur, CITE_KIND, cite_input(p), a=p.id, priority=age)[1]:
                added += 1
        if added >= limit or len(rows) < limit:
            break
        after = (rows[-1][2], rows[-1][0])
    return added


def _lock(cur: Any, post_id: Any) -> None:
    """The main and the cite answer of one post are merged one at a time (whichever commits second sees the other)."""
    cur.execute("SELECT pg_advisory_xact_lock(hashtext('ent42:' || %s::text))", (str(post_id),))


def _title(cur: Any, post_id: Any) -> str:
    got = tasks.load_posts(cur, [post_id]).get(str(post_id))
    return got.title if got else ""


def _mention(e: Dict[str, Any]) -> Dict[str, Any]:
    return dict({f: e.get(f) for f in repo.MENTION_FIELDS}, name_key=tasks.name_key(e.get("name")),
                by_name=e.get("by") or None, rule=Q2 if e.get("q2") else e.get("rule"))


def _cite_answer(cur: Any, post_id: Any) -> Optional[List[Dict[str, Any]]]:
    """The post's answered cite question's entities (its newest task's first valid answer), or None."""
    cur.execute("""SELECT c.answer FROM mx_tasks t JOIN mx_calls c ON c.task_id = t.id AND c.valid
                    WHERE t.kind = %s AND t.guide = %s AND t.a = %s AND t.status = 'answered'
                    ORDER BY t.answered_at DESC, c.created_at, c.ctid LIMIT 1""", (CITE_KIND, CITE_GUIDE, post_id))
    row = cur.fetchone()
    return None if row is None else list((row[0] or {}).get("entities") or [])


def main_mentions(cur: Any, post_id: Any, entities: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """An ent-v4.2 entities answer's mentions: its own title dropped, the post's cite answer merged when it came
    first (tasks.record, `# 0133 v4.2`)."""
    _lock(cur, post_id)
    return [_mention(e) for e in finish(entities, _title(cur, post_id), _cite_answer(cur, post_id))]


def after_cite(cur: Any, task: Dict[str, Any], call_id: Any, answer: Dict[str, Any]) -> int:
    """A cite answer after the post's ent-v4.2 main answer: its new entities appended to that set, marked q2 (a cite
    answer before it waits: the main answer merges it). How many were added."""
    pid = task["a"]
    _lock(cur, pid)
    cur.execute("""SELECT 1 FROM mx_tasks WHERE kind = 'entities' AND guide = %s AND a = %s AND status = 'answered'
                   LIMIT 1""", (GUIDE, pid))
    if cur.fetchone() is None:
        return 0
    have = repo.mentions(cur, pid, GUIDE)
    title = _title(cur, pid)
    cite = [e for e in answer.get("entities") or [] if not own_title(e, title)]
    new = [e for e in merge_cite(have, cite)[len(have):]]
    if not new:
        return 0
    start = max((m["n"] for m in have), default=-1) + 1
    fields = repo.MENTION_FIELDS + repo.MENTION_FIELDS_0133
    cur.executemany(f"INSERT INTO mx_mentions (post_id, guide, n, call_id, {', '.join(fields)}) "
                    f"VALUES ({', '.join(['%s'] * (4 + len(fields)))}) ON CONFLICT DO NOTHING",
                    [(pid, GUIDE, start + k, call_id, *(_mention(e).get(f) for f in fields)) for k, e in enumerate(new)])
    return len(new)


# ---- the owner's labels on the new entities ----------------------------------------------------------------------

def is_new(m: Dict[str, Any]) -> bool:
    """A new entity of ent-v4: a document, a `source` or a `recommended`, or one the second question added."""
    return (schemas.entity_type(m.get("type")) == "document" or m.get("role") in ("source", "recommended")
            or m.get("rule") == Q2)


def _key(guide: str, n: Any) -> str:
    return f"{guide}:{int(n)}"


def labels_of(cur: Any, post_id: Any, labeller: str = "owner") -> Dict[str, str]:
    """{"guide:n": the newest answer} of a post's labelled mentions."""
    cur.execute("""SELECT DISTINCT ON (note) note, answer FROM mx_labels
                    WHERE item_kind = %s AND a = %s AND labeller = %s ORDER BY note, created_at DESC, ctid DESC""",
                (LABEL_KIND, post_id, labeller))
    return dict(cur.fetchall())


def label(cur: Any, *, post: Any, guide: str, n: int, answer: str, labeller: str = "owner") -> Dict[str, Any]:
    """The owner's right / wrong on one new entity of a post (mx_labels item kind `mention`: a the post, b the call
    the mention came from, note "guide:n"; the newest row counts). ValueError for another answer or an entity that
    isn't new; LookupError for no such mention."""
    if answer not in ANSWERS:
        raise ValueError(f"answer: one of {', '.join(ANSWERS)}")
    cur.execute("SELECT * FROM mx_mentions WHERE post_id = %s AND guide = %s AND n = %s", (post, guide, n))
    rows = repo._rows(cur)
    if not rows:
        raise LookupError(f"no mention {guide}:{n} of post {post}")
    if not is_new(rows[0]):
        raise ValueError("only a new entity (a document, a source, a recommended, a second-question one) is labelled")
    repo.add_label(cur, item_kind=LABEL_KIND, a=post, b=rows[0]["call_id"], answer=answer, split="test",
                   labeller=labeller, note=_key(guide, n))
    return {"post": str(post), "guide": guide, "n": int(n), "label": answer}


def precision(cur: Any, guide: str = GUIDE, labeller: str = "owner") -> Dict[str, Any]:
    """The running precision of `guide`'s new entities from the owner's labels (each mention's newest), all and
    the second question's alone, with Wilson 95% intervals; the lab's stated line; the bar for leaving Shadow."""
    from insight_core.markx.labels import wilson
    cur.execute("""WITH l AS (SELECT DISTINCT ON (a, note) a, note, answer FROM mx_labels
                               WHERE item_kind = %s AND labeller = %s AND split_part(note, ':', 1) = %s
                               ORDER BY a, note, created_at DESC, ctid DESC)
                   SELECT m.rule = %s, l.answer FROM l
                     JOIN mx_mentions m ON m.post_id = l.a AND m.guide = %s
                                       AND m.n = split_part(l.note, ':', 2)::int""",
                (LABEL_KIND, labeller, guide, Q2, guide))
    rows = [(bool(q2), ans) for q2, ans in cur.fetchall()]

    def stat(xs: List[str]) -> Dict[str, Any]:
        n, k = len(xs), sum(1 for a in xs if a == "right")
        lo, hi = wilson(k, n)
        return {"labelled": n, "right": k, "precision": (k / n) if n else None,
                "low": lo if n else None, "high": hi if n else None}

    out = stat([a for _q, a in rows])
    out["q2"] = stat([a for q, a in rows if q])
    out.update({"guide": guide, "lab": LAB, "leave_at": {"labelled": LEAVE_AT[0], "low": LEAVE_AT[1]}})
    return out
