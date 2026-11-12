"""Back in the news, in Shadow (issue 0136, building 0092): an old Mark IX story with a fresh development gets a row on
/markx's News again, with the owner's label buttons. Shadow: mx_* rows only (mx_back, mx_tasks, mx_labels); Mark IX is
only read, and the row never enters Mark IX's News.

  1. **The trigger** (no model; the lab's back_v2 `bk_cands.py`). An old story is a Mark IX story with 2+ sources. It
     can fire in a 72-hour window starting at least FIRST_DAYS after its first post and LAST_DAYS after its last one,
     once (the lab's: a story's earliest burst; on the server copy, letting a story fire again 7 days after its last
     return made 535 candidates of 197 stories in four months, mostly the same perennial stories, V above all;
     0163: a long-lived story, markx/later.py's, may fire again later.AGAIN after its last window). In that
     window 2+ distinct sources post, outside the story, about:
       E  its subject: the ent-v3 subject (current mention set) of 2+ of its posts (of 1 when only one post was read),
          of a specific type (not org, person or place), by exact name: another version is another name;
       L  one of its pages: its members' own addresses, pages 2+ members link, Mark IX's origin page; not home pages,
          profiles or subreddits, nor pages linked in HUB_WEEKS+ distinct weeks;
       V  its centre: cosine >= COS to the mean of its members' vectors. A V burst is a candidate only when the
          story has no E or L burst.
     The window starts at the earliest E or L burst (else the V burst). Its posts are every hit inside it, E and L
     hits first, then by date, at most MAX_POSTS; its triggers, each that has 2+ sources inside it. Stored once per
     story and window (mx_back).
  2. **The judge** (`back`, back-v1 = the lab's frozen back_v3c.md): a verdict per new post. The candidate's verdict
     is the first of development, retold, related, unrelated any post has (the lab's bk_judge.rel); asked RUNS times,
     the majority, "unknown" when no two agree. Planned by the decision run, capped at OPEN open or leased.
  3. **The row** (`page`): each candidate judged development, with the owner's label (development / retold /
     related / unrelated) and the running precision of those labels.

Dates are the reader's: COALESCE(surfaced_at, published_at, fetched_at) (the lab's).
"""
from __future__ import annotations

import functools
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import pairing

log = logging.getLogger(__name__)

KIND = "back"
FIRST_DAYS = 14               # the window starts this long after the story's first post or later ...
LAST_DAYS = 7                 # ... and this long after its last one
WINDOW = timedelta(hours=72)
MIN_SOURCES = 2
COS = 0.70
HUB_WEEKS = 6                 # a page linked in this many distinct ISO weeks is a hub (no L)
MAX_POSTS = 6
OLD_SHOWN = 4                 # the question shows the old story's earliest 4 posts ...
OLD_CHARS = 300               # ... at 300 characters, and each new post at 500 (the lab's render)
NEW_CHARS = 500
RUNS = 3
OPEN = 50                     # decide.Config.back_open
FIRST_SCAN_DAYS = 30          # the first run reads this far back; each next one, from its last run's clock less WINDOW
MARGIN = timedelta(hours=1)
SINCE_KEY = "back_since"
MODEL = "bge-m3"
SPECIFIC = ("model", "product", "software", "paper", "document", "dataset", "event", "law", "other")
LABELS = ("development", "retold", "related", "unrelated")
ANSWERS = LABELS + ("undo",)
UNKNOWN = "unknown"
_MAP = {"mixed": "development", "late_repeat": "retold", "different": "unrelated"}   # the lab's older words
MEASURED = {"precision": 0.87, "lo": 0.68, "hi": 0.96, "n": 23, "words": "measured 87% precise (68–96%), about 1 in 8 wrong"}
DATE = pairing.POST_DATE       # Pairing's post date (0166)
SOCIAL = pairing.SOCIAL


def _date(p: str = "p") -> str:
    return DATE.format(p=p)


# ---- pages (the lab's norm) -------------------------------------------------------------------------------

# a page's compared form: Pairing's page address (0166). v10.16: kept per address (a pure function of the string; the
# hubs read every link to the stories' hosts, the same addresses many times over, in back's stage and later's)
norm = functools.lru_cache(maxsize=1 << 17)(pairing.page_address)


def _week(t: datetime) -> Tuple[int, int]:
    return tuple(t.isocalendar()[:2])   # type: ignore[return-value]


# ---- what the trigger reads ---------------------------------------------------------------------------------

class _P:
    __slots__ = ("id", "src", "at", "url", "saved")

    def __init__(self, id: str, src: str, at: datetime, url: Optional[str], saved: bool) -> None:
        self.id, self.src, self.at, self.url, self.saved = id, src, at, url, saved


def _posts(cur: Any, where: str, params: Sequence[Any]) -> Dict[str, _P]:
    from insight_core.utils.post_links import source_kind
    cur.execute(f"""SELECT p.id::text, p.source_id::text, {_date()}, p.url, s.platform, s.handle_or_url
                      FROM posts p JOIN sources s ON s.id = p.source_id WHERE {where}""", params)
    return {pid: _P(pid, src, at, url, source_kind(pl, h) == "saved") for pid, src, at, url, pl, h in cur.fetchall()
            if at is not None}


def _links(cur: Any, ids: Sequence[str]) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = defaultdict(set)
    if ids:
        cur.execute("SELECT post_id::text, target_url FROM post_links WHERE NOT boilerplate AND post_id = ANY(%s::uuid[])",
                    (list(ids),))
        for pid, u in cur.fetchall():
            n = norm(u)
            if n:
                out[pid].add(n)
    return out


def _pages(p: _P, links: Dict[str, Set[str]]) -> Set[str]:
    own = norm(p.url)
    return set(links.get(p.id, ())) | ({own} if own else set())


def _subjects(cur: Any, ids: Sequence[str]) -> Tuple[Dict[str, Set[str]], Set[str]]:
    """({post: its specific subjects' name keys}, the posts with a current entities answer) of `ids`."""
    from insight_core.markx import schemas, tasks
    if not ids:
        return {}, set()
    cur.execute("""SELECT m.post_id::text, m.name_key, m.name FROM mx_mentions_now m
                    WHERE m.post_id = ANY(%s::uuid[]) AND m.guide = ANY(%s) AND m.role = 'subject' AND m.type = ANY(%s)""",
                (list(ids), schemas.mention_guides(), list(SPECIFIC)))
    out: Dict[str, Set[str]] = defaultdict(set)
    for pid, key, name in cur.fetchall():
        k = key or tasks.name_key(name)
        if k:
            out[pid].add(k)
    cur.execute("SELECT post_id::text FROM mx_mention_sets WHERE post_id = ANY(%s::uuid[])", (list(ids),))
    return out, {r[0] for r in cur.fetchall()}


class Story:
    def __init__(self, id: str, members: List[_P], origin: Optional[str]) -> None:
        self.id, self.origin = id, origin
        self.members = sorted(members, key=lambda p: (p.at, p.id))
        self.first, self.last = self.members[0].at, self.members[-1].at
        self.sources = {p.src for p in self.members}
        self.subjects: Set[str] = set()
        self.pages: Set[str] = set()
        self.again: Optional[datetime] = None   # 0163: a long-lived story fires again from here (its last window + 30 days)

    def t0(self) -> datetime:
        t = max(self.first + timedelta(days=FIRST_DAYS), self.last + timedelta(days=LAST_DAYS))
        return max(t, self.again) if self.again else t


def stories(cur: Any, now: datetime) -> Dict[str, Story]:
    """Mark IX's stories of 2+ sources that may fire by `now` and never did, with their subjects and pages (hubs not
    yet taken out)."""
    cur.execute(f"""SELECT sp.story_id::text, p.id::text, p.source_id::text, {_date()}, p.url, st.origin_url
                      FROM story_posts sp JOIN stories st ON st.id = sp.story_id JOIN posts p ON p.id = sp.post_id""")
    by: Dict[str, List[_P]] = defaultdict(list)
    origin: Dict[str, Optional[str]] = {}
    for sid, pid, src, at, url, o in cur.fetchall():
        if at is not None:
            by[sid].append(_P(pid, src, at, url, False))
            origin[sid] = o
    out = {sid: Story(sid, ms, origin.get(sid)) for sid, ms in by.items() if len({m.src for m in ms}) >= MIN_SOURCES}
    cur.execute("SELECT story::text, max(window_at) FROM mx_back GROUP BY story")
    fired = dict(cur.fetchall())
    again = sorted(sid for sid in fired if sid in out)
    if again:   # 0163: a long-lived story (later.py), still followed, may fire again AGAIN after its last window
        from insight_core.markx import later
        lived = set(later.long_lived(cur, story_ids=again)) - later.stopped(cur, again)
        for sid in lived:
            out[sid].again = fired[sid] + later.AGAIN
    out = {sid: s for sid, s in out.items() if s.t0() <= now and (sid not in fired or s.again is not None)}
    mids = sorted({m.id for s in out.values() for m in s.members})
    subj, read = _subjects(cur, mids)
    links = _links(cur, mids)
    for s in out.values():
        c: Counter = Counter()
        for m in s.members:
            c.update(subj.get(m.id, ()))
        need = 2 if sum(m.id in read for m in s.members) >= 2 else 1
        s.subjects = {k for k, n in c.items() if n >= need}
        count: Counter = Counter()
        for m in s.members:
            count.update(links.get(m.id, ()))
        own = {norm(m.url) for m in s.members} | {norm(s.origin)}
        s.pages = {n for n in own | {n for n, k in count.items() if k >= 2} if n}
    return out


def hubs(cur: Any, pages: Iterable[str]) -> Set[str]:
    """The pages of `pages` linked (or posted) in HUB_WEEKS or more distinct ISO weeks."""
    pages = set(pages)
    if not pages:
        return set()
    hosts = {p.split("/", 1)[0] for p in pages}
    variants = sorted({v for h in hosts for v in (h, "www." + h, "m." + h, "mobile." + h)}
                      | ({"twitter.com", "www.twitter.com", "mobile.twitter.com"} if "x.com" in hosts else set()))
    weeks: Dict[str, Set[Tuple[int, int]]] = defaultdict(set)
    cur.execute(f"""SELECT l.target_url, {_date()} FROM post_links l JOIN posts p ON p.id = l.post_id
                     WHERE l.target_site = ANY(%s)""", (variants,))
    rows = cur.fetchall()
    cur.execute(f"""SELECT p.url, {_date()} FROM posts p
                     WHERE lower(substring(p.url from '^[a-zA-Z]+://([^/:?#]+)')) = ANY(%s)""", (variants,))
    rows += cur.fetchall()
    for u, at in rows:
        n = norm(u)
        if n in pages and at is not None:
            weeks[n].add(_week(at))
    return {n for n, w in weeks.items() if len(w) >= HUB_WEEKS}


def near(cur: Any, story_list: Sequence[Story], post_ids: Sequence[str]) -> Dict[str, Set[str]]:
    """{story: the posts of `post_ids` at cosine >= COS to its centre}: the mean of its members' (unit) vectors, for a
    story with every member's vector or 2+ of them."""
    pairs = [(s.id, m.id) for s in story_list for m in s.members]
    if not pairs or not post_ids:
        return {}
    cur.execute("""WITH m AS (SELECT * FROM unnest(%s::uuid[], %s::uuid[]) AS k(story, post)),
                        c AS (SELECT m.story, avg(l2_normalize(e.v::vector)) AS v, count(e.post_id) AS n, count(*) AS total
                                FROM m LEFT JOIN mx_embeddings e ON e.post_id = m.post AND e.model = %s GROUP BY m.story),
                        r AS (SELECT e.post_id, e.v::vector AS v FROM mx_embeddings e
                               WHERE e.model = %s AND e.post_id = ANY(%s::uuid[]))
                   SELECT c.story::text, r.post_id::text FROM c CROSS JOIN r
                    WHERE (c.n = c.total OR c.n >= 2) AND c.v IS NOT NULL AND 1 - (r.v <=> c.v) >= %s""",
                ([a for a, _ in pairs], [b for _, b in pairs], MODEL, MODEL, list(post_ids), COS))
    out: Dict[str, Set[str]] = defaultdict(set)
    for sid, pid in cur.fetchall():
        out[sid].add(pid)
    return out


def burst(hits: Sequence[Tuple[datetime, str]], src: Dict[str, str]) -> Optional[datetime]:
    """The start of the first WINDOW of `hits` (sorted [(at, post)]) with MIN_SOURCES distinct sources, or None."""
    for a in range(len(hits)):
        end = hits[a][0] + WINDOW
        if len({src[i] for t, i in hits[a:] if t <= end}) >= MIN_SOURCES:
            return hits[a][0]
    return None


def candidate(story: Story, hits: Dict[str, Sequence[Tuple[datetime, str]]], src: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """The story's candidate from its hits {E|L|V: sorted [(at, post)]}: {window_at, trig, posts, post_trig}, or None."""
    found = {k: b for k in "ELV" if (b := burst(hits.get(k) or (), src)) is not None}
    if not found:
        return None
    prim = [b for k, b in found.items() if k in "EL"]
    start = min(prim) if prim else found["V"]
    by: Dict[str, Set[str]] = defaultdict(set)
    at: Dict[str, datetime] = {}
    for k in "ELV":
        for t, i in hits.get(k) or ():
            if start <= t <= start + WINDOW:
                by[i].add(k)
                at[i] = t
    trig = [k for k in "ELV" if len({src[i] for i in by if k in by[i]}) >= MIN_SOURCES]
    posts = sorted(by, key=lambda i: (-len(by[i] & {"E", "L"}), at[i], i))[:MAX_POSTS]
    return {"window_at": start, "trig": trig, "posts": posts, "post_trig": {i: sorted(by[i]) for i in posts}}


def find(cur: Any, *, now: datetime, since: datetime) -> List[Dict[str, Any]]:
    """The candidates the posts dated in [since, now] make: one per story at most, each {story, window_at, trig,
    posts, post_trig}. Nothing is written."""
    st = stories(cur, now)
    if not st:
        return []
    recent = {i: p for i, p in _posts(cur, f"{_date()} >= %s AND {_date()} <= %s", (since, now)).items() if not p.saved}
    if not recent:
        return []
    ids = sorted(recent)
    subj, _read = _subjects(cur, ids)
    links = _links(cur, ids)
    pages = {i: _pages(p, links) for i, p in recent.items()}
    hub = hubs(cur, set().union(*(s.pages for s in st.values())) & set().union(*pages.values()))
    first = min(s.t0() for s in st.values())   # v10.16: once (was once a post: 3.5M t0 calls, 3.5 s on the scale copy)
    vec = near(cur, list(st.values()), [i for i in ids if recent[i].at >= first])
    src = {i: p.src for i, p in recent.items()}
    out = []
    for s in st.values():
        t0, mem = s.t0(), {m.id for m in s.members}
        own = s.pages - hub
        hits: Dict[str, List[Tuple[datetime, str]]] = {"E": [], "L": [], "V": []}
        for i in ids:
            p = recent[i]
            if i in mem or p.at < t0:
                continue
            if s.subjects & subj.get(i, set()):
                hits["E"].append((p.at, i))
            if own & pages[i]:
                hits["L"].append((p.at, i))
            if i in vec.get(s.id, ()):
                hits["V"].append((p.at, i))
        for h in hits.values():
            h.sort()
        c = candidate(s, hits, src)
        if c:
            out.append({"story": s.id, "members": [m.id for m in s.members], "first_at": s.first, "last_at": s.last, **c})
    return out


def write(cur: Any, found: Sequence[Dict[str, Any]], *, run_id: Any = None) -> int:
    """The new candidates (once per story and window): how many were new."""
    import json
    added = 0
    for c in found:
        cur.execute("""INSERT INTO mx_back (story, members, first_at, last_at, window_at, trig, posts, post_trig, run_id)
                       VALUES (%s, %s::uuid[], %s, %s, %s, %s, %s::uuid[], %s::jsonb, %s)
                       ON CONFLICT (story, window_at) DO NOTHING""",
                    (c["story"], c["members"], c["first_at"], c["last_at"], c["window_at"], c["trig"], c["posts"],
                     json.dumps(c["post_trig"]), run_id))
        added += cur.rowcount
    return added


# ---- the judge's question ----------------------------------------------------------------------------------

def _line(p: Any, chars: int, k: Optional[int] = None) -> str:
    head = f"{k}. " if k is not None else "- "
    text = re.sub(r"\s+", " ", p.text or "").strip()
    return f"{head}[{p.source}, {p.kind}, {p.iso[:16]}] {(p.title or '')[:150]} — {text[:chars]}"


def render(members: Sequence[Any], new: Sequence[Any]) -> str:
    """The lab's item: the old story's earliest OLD_SHOWN posts, then the new posts numbered (tasks.Post each)."""
    lines = ["OLD STORY:"] + [_line(p, OLD_CHARS) for p in members[:OLD_SHOWN]]
    if len(members) > OLD_SHOWN:
        lines.append(f"(+{len(members) - OLD_SHOWN} more posts)")
    lines += ["", "NEW POSTS (one 72-hour window):"] + [_line(p, NEW_CHARS, k + 1) for k, p in enumerate(new[:MAX_POSTS])]
    return "\n".join(lines)


_NUMBERED = re.compile(r"^(\d+)\. \[", re.M)


def numbered(input: str) -> int:
    """How many new posts a back question numbers."""
    _, _, tail = (input or "").partition("NEW POSTS")
    return len(_NUMBERED.findall(tail))


def plan(cur: Any, *, open_cap: int = OPEN, now: Optional[datetime] = None, **_kw: Any) -> int:
    """A back task for each candidate with none, newest window first, while fewer than `open_cap` wait (open or
    leased). How many were added."""
    from insight_core.markx import tasks
    cur.execute("SELECT count(*) FROM mx_tasks WHERE kind = %s AND status IN ('open', 'leased')", (KIND,))
    room = open_cap - cur.fetchone()[0]
    if room <= 0:
        return 0
    cur.execute("""SELECT id::text, story::text, members::text[], posts::text[], window_at FROM mx_back
                    WHERE task_id IS NULL ORDER BY window_at DESC, id LIMIT %s""", (room,))
    picks = cur.fetchall()
    if not picks:
        return 0
    posts = tasks.load_posts(cur, {x for _, _, ms, ps, _ in picks for x in list(ms) + list(ps)})
    now = now or datetime.now(timezone.utc)
    added = 0
    for bid, story, ms, ps, at in picks:
        old = sorted((posts[m] for m in ms if m in posts), key=lambda p: (p.at, p.id))
        new = [posts[p] for p in ps if p in posts]
        if not old or not new:
            continue
        age = max(0, int((now - at).total_seconds() // 86400))
        got = planned(cur, lambda: tasks.add(cur, KIND, render(old, new), a=story, priority=age),
                      "UPDATE mx_back SET task_id = %s WHERE id = %s", bid)
        added += bool(got and got[1])
    return added


def planned(cur: Any, add: Any, link: str, row: str) -> Optional[Tuple[Any, bool]]:
    """v10.15: a row's task added (`add()`: (task id, new)) and the row pointed at it (`link`), in a savepoint. Inside a
    decision run (one REPEATABLE READ snapshot) another transaction may have asked the same question or planned the
    same row since the snapshot (a worker's lease plans back and later too, and leases and answers its tasks): Postgres
    then fails the insert or the update with a serialization failure, which here leaves the row for the next plan
    instead of failing the run. None when so."""
    from psycopg import errors as psycopg_errors
    try:
        with cur.connection.transaction():
            tid, new_task = add()
            cur.execute(link, (tid, row))
            return tid, new_task
    except psycopg_errors.SerializationFailure:
        log.info("Mark X back: a row another transaction planned since this one's snapshot is left for the next plan")
        return None


def after_answer(cur: Any, task: Dict[str, Any]) -> bool:
    """A back task's valid answer (tasks.record): asked again until it has RUNS valid answers. Whether it reopened."""
    cur.execute("SELECT count(*) FROM mx_calls WHERE task_id = %s AND valid", (task["id"],))
    if cur.fetchone()[0] >= RUNS:
        return False
    cur.execute("UPDATE mx_tasks SET status = 'open', lease_until = NULL, leased_by = NULL WHERE id = %s", (task["id"],))
    return cur.rowcount == 1


# ---- verdicts (the lab's bk_judge.rel and vote) -------------------------------------------------------------

def relation(answer: Optional[Dict[str, Any]]) -> Optional[str]:
    """One answer's relation: from its per-post verdicts, the first of development, retold, related, unrelated any
    post has; else its `relation`."""
    if answer is None:
        return None
    ps = answer.get("posts")
    if isinstance(ps, list) and ps:
        vs = {_MAP.get(str(p.get("verdict")), p.get("verdict")) for p in ps if isinstance(p, dict)}
        for r in LABELS:
            if r in vs:
                return r
    return _MAP.get(answer.get("relation"), answer.get("relation"))


def verdict(answers: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The first RUNS valid answers' verdict: {relation (the majority's, or unknown when no two agree), runs}; None
    until RUNS came."""
    runs = list(answers)[:RUNS]
    if len(runs) < RUNS:
        return None
    rels = [relation(a) for a in runs]
    top, n = Counter(rels).most_common(1)[0]
    return {"relation": top if n >= 2 else UNKNOWN, "runs": rels}


def _answers(cur: Any, task_ids: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    if task_ids:
        cur.execute("""SELECT task_id::text, answer FROM mx_calls WHERE valid AND task_id = ANY(%s::uuid[])
                        ORDER BY created_at, ctid""", (list(task_ids),))
        for tid, ans in cur.fetchall():
            out[tid].append(ans or {})
    return out


# ---- the decision run's stage ------------------------------------------------------------------------------

def stage(cur: Any, *, now: datetime, run_id: Any = None, open_cap: int = OPEN) -> Dict[str, Any]:
    """The decision run's part (in its connections stage): the candidates of the posts since the last run (less
    WINDOW), then the back questions planned. Its counts."""
    from insight_core.markx import repo
    t0 = time.monotonic()
    last = repo.get_setting(cur, SINCE_KEY, default=None)
    since = (datetime.fromisoformat(last) - WINDOW - MARGIN) if last else now - timedelta(days=FIRST_SCAN_DAYS)
    found = find(cur, now=now, since=since)
    out = {"since": since.isoformat(), "found": len(found), "added": write(cur, found, run_id=run_id),
           "planned": plan(cur, open_cap=open_cap, now=now)}
    repo.set_setting(cur, SINCE_KEY, now.isoformat())
    out["seconds"] = round(time.monotonic() - t0, 3)
    return out


# ---- the rows on /markx (Shadow) ------------------------------------------------------------------------------

def _labels(cur: Any, ids: Sequence[str]) -> Dict[str, Optional[str]]:
    if not ids:
        return {}
    cur.execute("""SELECT DISTINCT ON (a) a::text, answer FROM mx_labels
                    WHERE item_kind = 'back' AND labeller = 'owner' AND a = ANY(%s::uuid[])
                    ORDER BY a, created_at DESC, ctid DESC""", (list(ids),))
    return {a: (None if ans == "undo" else ans) for a, ans in cur.fetchall()}


def _shown_posts(cur: Any, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    ids = sorted(set(ids))
    if not ids:
        return {}
    cur.execute(f"""SELECT p.id::text, p.title, p.url, {_date()},
                           COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                                    s.handle_or_url)
                      FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ANY(%s::uuid[])""", (ids,))
    return {i: {"title": t or None, "url": u, "at": at, "source": src} for i, t, u, at, src in cur.fetchall()}


def _iso(t: Optional[datetime]) -> Optional[str]:
    return t.isoformat() if t else None


def page(cur: Any, *, limit: int = 100) -> Dict[str, Any]:
    """/markx's "Back in the news": {items [rows judged development, newest window first], counts, precision}. Each
    row {id, story, headline, first_at, window_at, days_later, trig, posts [{id, n, title, source, at, trig,
    verdict}], old_thing, what_new [the development runs' words], runs, label}."""
    cur.execute("""SELECT b.id::text, b.story::text, b.members::text[], b.first_at, b.window_at, b.trig,
                          b.posts::text[], b.post_trig, b.task_id::text
                     FROM mx_back b ORDER BY b.window_at DESC, b.id""")
    rows = cur.fetchall()
    answers = _answers(cur, [r[8] for r in rows if r[8]])
    counts = Counter(candidates=len(rows))
    shown = []
    for bid, story, ms, at0, wat, trig, ps, ptrig, tid in rows:
        got = answers.get(tid, []) if tid else []
        v = verdict(got)
        if v is None:
            counts["waiting"] += 1
            continue
        counts[v["relation"]] += 1
        if v["relation"] == "development":
            shown.append((bid, story, ms, at0, wat, trig, ps, ptrig or {}, got[:RUNS], v))
    shown = shown[:limit]
    posts = _shown_posts(cur, [x for r in shown for x in [r[1]] + list(r[2])[:1] + list(r[6])])
    marks = _labels(cur, [r[0] for r in shown])
    items = []
    for bid, story, ms, at0, wat, trig, ps, ptrig, runs, v in shown:
        head = posts.get(story) or (posts.get(ms[0]) if ms else None) or {}
        dev = [a for a in runs if relation(a) == "development"]
        lines = []
        for k, pid in enumerate(ps, 1):
            p = posts.get(pid) or {}
            per = [next((str(x.get("verdict")) for x in (a.get("posts") or []) if isinstance(x, dict) and x.get("n") == k), None)
                   for a in runs]
            top, n = Counter(x for x in per if x).most_common(1)[0] if any(per) else (None, 0)
            lines.append({"id": pid, "n": k, "title": p.get("title"), "source": p.get("source"), "at": _iso(p.get("at")),
                          "url": p.get("url"), "trig": ptrig.get(pid) or [],
                          "verdict": _MAP.get(top, top) if n >= 2 else None,
                          "about": next((x.get("about") for a in dev for x in (a.get("posts") or [])
                                         if isinstance(x, dict) and x.get("n") == k and x.get("about")), None)})
        items.append({"id": bid, "story": story, "headline": head.get("title"), "first_at": _iso(at0),
                      "window_at": _iso(wat), "days_later": (wat - at0).days, "trig": list(trig), "posts": lines,
                      "old_thing": next((a.get("old_thing") for a in dev if a.get("old_thing")), None),
                      "what_new": list(dict.fromkeys(str(a["what_new"]) for a in dev if a.get("what_new"))),
                      "runs": v["runs"], "label": marks.get(bid)})
    return {"items": items, "counts": dict(counts), "precision": precision(cur), "measured": MEASURED}


def precision(cur: Any) -> Dict[str, Any]:
    """The owner's labels on the rows shown: {labelled, development, precision (None before the first)}."""
    cur.execute("""SELECT DISTINCT ON (a) a::text, answer FROM mx_labels WHERE item_kind = 'back' AND labeller = 'owner'
                    ORDER BY a, created_at DESC, ctid DESC""")
    marks = [ans for _, ans in cur.fetchall() if ans != "undo"]
    dev = sum(a == "development" for a in marks)
    return {"labelled": len(marks), "development": dev, "precision": round(dev / len(marks), 4) if marks else None}


def label(cur: Any, *, row: str, answer: str, note: Optional[str] = None) -> Dict[str, Any]:
    """The owner's label on a row (one of LABELS, or undo). ValueError: another answer; KeyError: no such row."""
    from insight_core.markx import repo
    if answer not in ANSWERS:
        raise ValueError(f"answer: one of {', '.join(ANSWERS)}")
    cur.execute("SELECT story FROM mx_back WHERE id = %s", (row,))
    got = cur.fetchone()
    if got is None:
        raise KeyError(row)
    lid = repo.add_label(cur, item_kind="back", a=row, b=got[0], answer=answer, note=(note or "").strip() or None)
    return {"id": str(lid), "answer": answer, "label": None if answer == "undo" else answer, "precision": precision(cur)}
