"""How significant a News row's event is (issue 0208, Stealth v10.19): one question a row, asked of the worker.

News was ordered by loudness: a row's score is its voices and reports, so a big lab's minor launch covered by twenty
sources outranks a new method two expert sources take apart. This module owns the other half of the order: what kind
of event a row is and how big its effect is on the work of people in its field, whatever its coverage.

**The question** (kind `significance`, guide significance-v1, one row a question): the row's headline (`news.headlines`),
then what INSIGHT already measured about it (the existing signals first):
  - its kind of happening (`event_types.of_stories`, the event-type seam over its posts' readings);
  - its main subjects and their kind (`news_sections._entities`: the current entities of its posts);
  - its coverage: posts, sources and long posts (LONG_POST+ characters of their own), counted in buckets
    (`bucket`) so that a row gaining one more repeat does not make a new question;
  - the kinds of pages its posts link (a paper, code, a demo, a package, a model hub page: entity_originals'
    address kinds, no list of sites here);
then its members, up to MEMBERS, from its main story's posts (`core_of`: a stray post another story brought into the
row never speaks for it): the EARLIEST first posts, then the longest of the others (one a source first: a
breakdown is long), each with its platform, source, date, length, title and the start of its text (the longest one
LONG_CHARS, the others TEXT_CHARS). `question` is pure (the measurement builds the same text from the server's page).

**When** (`plan`, the decision run's stage after News, in the jobs process, never a lease): a row of News' window is
asked once, and again only when its posts changed since its last ask (`mx_news_significance_asks.members`) and its last
ask is REASK_GAP old: a row growing all day is asked a few times, not once a post. At most PLAN_MAX questions a run,
the newest rows first. A row asked and still waiting is not asked again.

**The answer** (`answers`): each row's newest answered ask (its task's first valid call), even when the row changed
since (it stands until the new one is answered). `score` turns it into one number in [0, 1]: the effect first (1..5),
then whether it can be used now, its adoption signals, an expert breakdown and its scope (SCORE_*: measured on the blind
labels, plan/issues/0208).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

KIND, GUIDE = "significance", "significance-v1"
MEMBERS = 6                 # members shown, at most
EARLIEST = 2                # the first posts always shown (who broke it)
TEXT_CHARS = 500            # a member's text shown
LONG_CHARS = 1500           # the longest member's (a breakdown is read further)
LONG_POST = 1000            # a post this long of its own words counts as a long post
TITLE_CHARS = 200
SUBJECTS = 3
REASK_GAP = timedelta(hours=6)    # a changed row is asked again at most this often
PLAN_MAX = 120                    # questions a run, at most (the newest rows first)
PRIORITY = 0

# The score (0208, `score`): the effect first, then the rest. Measured on the blind labels (plan/issues/0208).
SCORE_USABLE = {"now": 0.10, "soon": 0.05, "no": 0.0}
SCORE_LIBRARY = 0.10               # it landed inside a widely used library or tool
SCORE_OPEN = 0.05                  # open code, open weights, or a paper with its code
SCORE_BREAKDOWN = 0.05             # an expert took it apart
SCORE_SCOPE = {"field_wide": 0.05, "subfield": 0.0, "niche": -0.05}


@dataclass
class Member:
    id: str
    kind: str                   # the platform as the reader names it
    source: str
    at: datetime
    title: str
    text: str
    links: List[str] = field(default_factory=list)


def bucket(n: int) -> str:
    """A count as the question says it: exact to 5, then 6-9, 10-19, 20+ (a row gaining a repeat asks nothing new)."""
    if n <= 5:
        return str(n)
    return "6-9" if n < 10 else "10-19" if n < 20 else "20+"


def own_chars(m: Member) -> int:
    """The characters of a member's own words: its text, without its title repeated at its start."""
    text = m.text or ""
    if m.title and text.startswith(m.title):
        text = text[len(m.title):]
    return len(text.strip())


def chosen(members: Sequence[Member], core: Optional[Iterable[str]] = None) -> List[Member]:
    """The members a question shows, earliest first: the EARLIEST first posts, then the longest of the others, one a
    source before a second of the same source, up to MEMBERS. With `core` (the row's main story's posts, `core_of`),
    from those: a stray long post another story brought into the row never speaks for it (the measure's wrong row: a
    launch judged by the scandal its row had swallowed)."""
    if core is not None:
        inside = [m for m in members if m.id in set(core)]
        if len(inside) >= 2:
            members = inside
    order = sorted(members, key=lambda m: (m.at, m.id))
    picked = order[:EARLIEST]
    rest = sorted(order[EARLIEST:], key=lambda m: (-own_chars(m), m.at, m.id))
    seen = {m.source for m in picked}
    for second in (False, True):
        for m in rest:
            if len(picked) >= MEMBERS:
                break
            if m in picked or (not second and m.source in seen):
                continue
            picked.append(m)
            seen.add(m.source)
    return sorted(picked, key=lambda m: (m.at, m.id))


def link_kinds(members: Sequence[Member]) -> List[str]:
    """The kinds of pages the members link, in a fixed order: a paper, code, a demo, a package, a model hub page."""
    from insight_core.utils import entity_originals as E
    from insight_core.utils.addresses import host_of, site_of
    found = set()
    for m in members:
        for url in m.links:
            site = site_of(host_of(url))
            kind = E.address_kind(url)
            if kind == E.PAPER:
                found.add("paper")
            elif kind == E.CODE:
                found.add("code")
            elif kind == E.DEMO:
                found.add("demo")
            elif site in E.PACKAGE_SITES:
                found.add("package")
            elif site in E.MODEL_HUBS:
                found.add("model hub page")
    return [k for k in ("paper", "code", "demo", "package", "model hub page") if k in found]


def _squash(s: Optional[str], n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def core_of(row: Dict[str, Any]) -> Optional[set]:
    """The posts of a row's main story (news.main_story: the Mark X story holding most of its voices), or None when
    none of its posts is in a story."""
    from insight_core.markx import news
    main = news.main_story(row)
    if main is None:
        return None
    return {p["post_id"] for p in row.get("posts") or [] if str(p.get("story") or "") == main}


def question(headline: str, members: Sequence[Member], *, event_type: Optional[str] = None,
             subjects: Sequence[Tuple[str, Optional[str]]] = (), voices: int = 0,
             core: Optional[Iterable[str]] = None) -> str:
    """The input of one row's question (above). Pure: the same row reads the same text. `core`: its main story's
    posts, the members shown are taken from (`chosen`); the coverage line counts every post of the row."""
    shown = chosen(members, core)
    longest = max(shown, key=lambda m: (own_chars(m), m.id)) if shown else None
    long_posts = sum(1 for m in members if own_chars(m) >= LONG_POST)
    lines = [f"STORY: {_squash(headline, TITLE_CHARS) or '(no headline)'}"]
    if event_type:
        lines.append("KIND OF HAPPENING (measured): " + event_type.replace("_", " "))
    if subjects:
        lines.append("MAIN SUBJECTS: " + ", ".join(f"{n} ({t})" if t else n for n, t in list(subjects)[:SUBJECTS]))
    lines.append(f"COVERAGE: {bucket(len(members))} posts from {bucket(voices)} sources; "
                 f"{bucket(long_posts)} long posts ({LONG_POST:,}+ characters of their own)")
    kinds = link_kinds(members)
    if kinds:
        lines.append("LINKED PAGES: " + ", ".join(kinds))
    lines.append(f"POSTS ({len(shown)} of {bucket(len(members))}, earliest first):")
    for n, m in enumerate(shown, 1):
        chars = LONG_CHARS if m is longest else TEXT_CHARS
        lines.append(f"[{n}] {m.kind} · {m.source} · {m.at.astimezone(timezone.utc).date().isoformat()} · "
                     f"{own_chars(m):,} characters")
        lines.append(f"Title: {_squash(m.title, TITLE_CHARS)}")
        text = (m.text or "")[len(m.title):] if m.title and (m.text or "").startswith(m.title) else (m.text or "")
        if text.strip():
            lines.append(f"Text: {_squash(text, chars)}")
    return "\n".join(lines)


def score(answer: Optional[Dict[str, Any]]) -> Optional[float]:
    """One number in [0, 1] from an answer (None: none): the effect first ((effect - 1) / 4), then usable now, a
    widely used library, open code or weights, an expert breakdown and the scope (SCORE_*)."""
    if not answer:
        return None
    try:
        effect = int(answer.get("effect"))
    except (TypeError, ValueError):
        return None
    adoption = set(answer.get("adoption") or ())
    s = (min(max(effect, 1), 5) - 1) / 4
    s += SCORE_USABLE.get(answer.get("usable"), 0.0)
    s += SCORE_LIBRARY if "widely_used_library" in adoption else 0.0
    s += SCORE_OPEN if adoption & {"open_code", "open_weights", "paper_with_code"} else 0.0
    s += SCORE_BREAKDOWN if answer.get("coverage") == "expert_breakdown" else 0.0
    s += SCORE_SCOPE.get(answer.get("scope"), 0.0)
    return round(min(max(s, 0.0), 1.0), 4)


# ---- the database side -------------------------------------------------------------------------------------

def members_of(cur: Any, rows: Sequence[Dict[str, Any]]) -> Dict[str, List[Member]]:
    """{row id: its posts as Members}, from Mark X's own text of each (tasks.load_posts)."""
    from insight_core.markx import tasks
    ids = {p["post_id"] for r in rows for p in r.get("posts") or []}
    posts = tasks.load_posts(cur, sorted(ids))
    out: Dict[str, List[Member]] = {}
    for r in rows:
        ms = []
        for p in r.get("posts") or []:
            got = posts.get(p["post_id"])
            if got is not None:
                ms.append(Member(id=got.id, kind=got.kind, source=got.who, at=got.at, title=got.title, text=got.text,
                                 links=[u for u, _ in got.links]))
        out[str(r["id"])] = ms
    return out


def inputs(cur: Any, rows: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """{row id: its question} for these News rows (rows with no post Mark X can read are left out)."""
    from insight_core.markx import news, news_sections
    if not rows:
        return {}
    heads = news.headlines(cur, rows)
    types = news_sections._types(cur, rows)
    subjects = news_sections._entities(cur, rows)
    members = members_of(cur, rows)
    out = {}
    for r in rows:
        rid = str(r["id"])
        if members.get(rid):
            out[rid] = question(heads[rid]["text"], members[rid], event_type=types.get(rid),
                                subjects=subjects.get(rid) or (), voices=int(r.get("voices") or 0), core=core_of(r))
    return out


def last_asks(cur: Any, row_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """{row id: its newest ask {task_id, members, asked_at, status}}."""
    ids = sorted({str(r) for r in row_ids})
    if not ids:
        return {}
    cur.execute("""SELECT DISTINCT ON (a.row_id) a.row_id::text, a.task_id::text, a.members::text[], a.asked_at, t.status
                     FROM mx_news_significance_asks a JOIN mx_tasks t ON t.id = a.task_id
                    WHERE a.row_id = ANY(%s::uuid[]) ORDER BY a.row_id, a.asked_at DESC, a.task_id""", (ids,))
    return {r: {"task_id": t, "members": set(ms or ()), "asked_at": at, "status": st}
            for r, t, ms, at, st in cur.fetchall()}


def due(row: Dict[str, Any], last: Optional[Dict[str, Any]], now: datetime) -> Tuple[bool, str]:
    """Whether a row is asked now, and why (or why not)."""
    if last is None:
        return True, "never asked"
    posts = {p["post_id"] for p in row.get("posts") or []}
    if posts == last["members"]:
        return False, "its posts are as asked"
    if last["status"] in ("open", "leased"):
        return False, "one is waiting"
    if now - last["asked_at"] < REASK_GAP:
        return False, "asked less than the gap ago"
    return True, "its posts changed"


def plan(cur: Any, *, now: Optional[datetime] = None, limit: int = PLAN_MAX) -> Dict[str, int]:
    """The significance questions of the current News rows that are `due`, newest rows first, at most `limit`:
    {rows, asked (new tasks), again (a task that already existed for this input), waiting, unchanged}."""
    from insight_core.markx import news_sections, tasks
    now = now or datetime.now(timezone.utc)
    _run, rows = news_sections.current_rows(cur, now)
    out = {"rows": len(rows), "asked": 0, "again": 0, "waiting": 0, "unchanged": 0}
    if not rows:
        return out
    last = last_asks(cur, [str(r["id"]) for r in rows])
    want = []
    for r in sorted(rows, key=lambda r: (-r["first_at"].timestamp(), str(r["id"]))):
        ok, why = due(r, last.get(str(r["id"])), now)
        if ok:
            want.append(r)
        elif why == "one is waiting":
            out["waiting"] += 1
        else:
            out["unchanged"] += 1
    want = want[:limit]
    texts = inputs(cur, want)
    for r in want:
        rid = str(r["id"])
        if rid not in texts:
            continue
        tid, new = tasks.add(cur, KIND, texts[rid], a=rid, priority=PRIORITY)
        cur.execute("""INSERT INTO mx_news_significance_asks (task_id, row_id, members, asked_at)
                       VALUES (%s, %s, %s::uuid[], %s) ON CONFLICT (task_id) DO NOTHING""",
                    (tid, rid, sorted({p["post_id"] for p in r.get("posts") or []}), now))
        out["asked" if new else "again"] += 1
    return out


def answers(cur: Any, row_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """{row id: its newest answered ask's answer, with `asked_at`, `task_id` and `score`} (a row whose newer ask
    waits keeps its older answer)."""
    from insight_core.markx import repo
    ids = sorted({str(r) for r in row_ids})
    if not ids:
        return {}
    cur.execute("""SELECT DISTINCT ON (a.row_id) a.row_id::text, a.task_id::text, a.asked_at
                     FROM mx_news_significance_asks a JOIN mx_tasks t ON t.id = a.task_id
                    WHERE a.row_id = ANY(%s::uuid[]) AND t.status = 'answered'
                    ORDER BY a.row_id, a.asked_at DESC, a.task_id""", (ids,))
    asks = cur.fetchall()
    calls = repo.valid_calls(cur, [t for _, t, _ in asks])
    out = {}
    for rid, tid, at in asks:
        answer = (calls.get(tid) or {}).get("answer")
        if isinstance(answer, dict):
            out[rid] = {**answer, "asked_at": at, "task_id": tid, "score": score(answer)}
    return out


def stamp(cur: Any) -> List[Any]:
    """What `answers` reads, cheaply: the answered significance tasks' count and newest answer."""
    cur.execute("SELECT count(*), max(answered_at) FROM mx_tasks WHERE kind = %s AND status = 'answered'", (KIND,))
    return list(cur.fetchone())
