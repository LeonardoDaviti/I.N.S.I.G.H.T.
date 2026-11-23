"""A thing's stops: whether a story is about a thing (a stop on its timeline) or only names it, and what happened to
the thing in it (launch -> benchmark -> weights ...).

`share`/`candidate` (pure) pick candidate stories: the thing is subject or actor of CANDIDATE_SHARE of its members or
of its first post. `question` builds one `stop` item; `plan` (jobs process) asks each candidate pair once, at most
PLAN_MAX a pass; `of` reads the stored answers by any name of the thing's cluster (a later merge keeps them);
`coarse` gives the stop a story's event type implies when nothing is stored. Nothing is fetched.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from insight_core.markx import schemas

KIND, GUIDE = "stop", "stop-v1"
STOPS = tuple(schemas.STOP_KINDS)
ABOUT = ("subject", "actor")
CANDIDATE_SHARE = 0.25        # the thing is subject or actor of at least this share of the story's members
SHOWN = 6                     # the story's earliest posts the question shows
TITLE_CHARS = 200
PLAN_MAX = 300                # questions a pass, at most
WINDOW_DAYS = 30              # stories whose newest member is this recent are planned
PRIORITY = 0
# the stop a story's event type gives when nothing was asked
COARSE = {"model_release": "release", "product_release": "release", "research_result": "research",
          "business_event": "deal", "policy_legal": "incident", "incident": "incident",
          "public_statement": "statement", "promotion_event": "promotion", "leak_rumour": "teaser",
          "opinion_analysis": "analysis", "tutorial_explainer": "tutorial"}


def config() -> Dict[str, bool]:
    """entity_bands.json `timeline` switches: stops, stop_types, analysis, by_reading (timeline.named_only),
    version_line (timeline.version_line), outside_roles (timeline.OUTSIDE_ROLES)."""
    from insight_core.markx import identity as I
    got = I.bands().get("timeline") or {}
    return {"stops": bool(got.get("stops", True)), "stop_types": bool(got.get("stop_types", False)),
            "analysis": bool(got.get("analysis", False)), "by_reading": bool(got.get("by_reading", False)),
            "version_line": bool(got.get("version_line", False)),
            "outside_roles": bool(got.get("outside_roles", True))}


@dataclass(frozen=True)
class Share:
    members: int          # the story's members
    about: int            # of them, posts whose subject or actor is the thing
    first_about: bool     # its first post is about the thing


@dataclass(frozen=True)
class Stop:
    about: bool
    stop: str
    evidence: str
    task: str


@dataclass(frozen=True)
class Line:
    """One post shown in a question."""
    at: datetime
    source: str
    title: str
    role: Optional[str]   # how the post treats the thing: subject, actor, a mention, None (it does not name it)


def share(posts: Sequence[Tuple[datetime, str]], about: Iterable[str]) -> Share:
    """The thing's share of a story: `posts` its members (at, id), `about` the ids whose subject or actor it is."""
    ab = set(about)
    order = sorted(posts)
    return Share(len(order), sum(1 for _, p in order if p in ab), bool(order) and order[0][1] in ab)


def candidate(s: Share) -> bool:
    """Whether a story may be a stop on the thing's line (asked; never shown as one without an answer that says so)."""
    return s.members > 0 and (s.first_about or s.about >= max(1.0, CANDIDATE_SHARE * s.members))


def _clip(s: Optional[str], n: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def thing_line(thing: Mapping[str, Any]) -> str:
    """THING: "name" (type, by maker)."""
    return (f'THING: "{thing.get("name")}" ({thing.get("type") or "thing"}'
            + (f', by {thing["maker"]}' if thing.get("maker") else "") + ")")


def story_lines(headline: Optional[str], lines: Sequence[Line], label: str = "STORY", shown: int = SHOWN) -> List[str]:
    """A story as the stop and chain questions show it: headline, dates, post count, then its earliest `shown` posts
    (date, source, how the post treats the thing, title). Pure."""
    order = sorted(lines, key=lambda x: (x.at, x.source, x.title))
    span = (f"{order[0].at:%Y-%m-%d} to {order[-1].at:%Y-%m-%d}, {len(order)} posts" if order else "no posts")
    out = [f'{label}: "{_clip(headline, TITLE_CHARS) or "(no headline)"}" ({span})']
    for x in order[:shown]:
        out.append(f"- {x.at:%Y-%m-%d} · {_clip(x.source, 60)} · {x.role or 'does not name it'}: {_clip(x.title, TITLE_CHARS)}")
    return out


def question(thing: Mapping[str, Any], headline: Optional[str], lines: Sequence[Line]) -> str:
    """One stop item: THING (name, type, maker) and STORY (headline, dates, earliest SHOWN posts). Pure."""
    return "\n".join([thing_line(thing)] + story_lines(headline, lines))


def coarse(event_type: Optional[str]) -> Optional[str]:
    return COARSE.get(event_type or "")


def parse(answer: Optional[Mapping[str, Any]], task: str) -> Optional[Stop]:
    if not isinstance(answer, Mapping) or answer.get("stop") not in STOPS or not isinstance(answer.get("about"), bool):
        return None
    return Stop(bool(answer["about"]), str(answer["stop"]), str(answer.get("evidence") or ""), task)


# ---- the stored answers, the planner ---------------------------------------------------------------------------

def of(cur: Any, book: Any, root: str, story_ids: Optional[Iterable[str]]) -> Dict[str, Stop]:
    """{story: the newest valid answer about this thing (any name of its cluster) in it}; `story_ids` None: every
    story it was asked of (the b index)."""
    from insight_core.markx import repo
    members = sorted(book.cluster(root))
    if story_ids is None:
        cur.execute("""SELECT id::text, a::text FROM mx_tasks
                        WHERE kind = %s AND status = 'answered' AND b = ANY(%s::uuid[]) ORDER BY created_at""",
                    (KIND, members))
    else:
        sids = sorted({str(s) for s in story_ids if s})
        if not sids:
            return {}
        cur.execute("""SELECT id::text, a::text FROM mx_tasks
                        WHERE kind = %s AND status = 'answered' AND a = ANY(%s::uuid[]) AND b = ANY(%s::uuid[])
                        ORDER BY created_at""", (KIND, sids, members))
    rows = cur.fetchall()
    calls = repo.valid_calls(cur, [t for t, _ in rows])
    out: Dict[str, Stop] = {}
    for tid, sid in rows:
        got = parse((calls.get(tid) or {}).get("answer"), tid)
        if got is not None:
            out[sid] = got
    return out


def _thing(book: Any, root: str) -> Dict[str, Any]:
    from insight_core.markx import identity as I
    e = book.ents[root]
    maker = None
    for m in [root] + sorted(book.cluster(root)):
        if book.ents[m].maker:
            maker = book.ents[m].maker
            break
    if maker is None and e.parent and e.parent in book.ents and book.shown_type(book.root(e.parent)) in I.ORGISH:
        maker = book.label(book.root(e.parent))
    return {"name": book.label(root), "type": book.shown_type(root), "maker": maker}


def stories_shown(cur: Any, book: Any, sids: Sequence[str]
                  ) -> Tuple[Dict[str, List[Tuple[datetime, str, str, str]]], Dict[str, Dict[str, str]], Dict[str, Optional[str]]]:
    """What the stop and chain questions show of these stories: ({story: [(at, post, source, title)] of its current
    members}, {post: {root: its strongest role}}, {story: headline})."""
    from insight_core.markx.news import _posts
    cur.execute("""SELECT story_id::text, post_id::text FROM mx_story_posts
                    WHERE valid_to IS NULL AND role = 'member' AND story_id = ANY(%s::uuid[])""", (list(sids),))
    pairs = cur.fetchall()
    shown = _posts(cur, {p for _, p in pairs})
    posts: Dict[str, List[Tuple[datetime, str, str, str]]] = {}
    for sid, pid in pairs:
        x = shown.get(pid)
        if x and x.get("at") is not None:
            posts.setdefault(sid, []).append((x["at"], pid, x.get("source") or "", x.get("title") or ""))
    ids = sorted({p for ps in posts.values() for _, p, _, _ in ps})
    cur.execute("""SELECT post_id::text, guide, n, entity_id::text, role FROM mx_mentions_now
                    WHERE post_id = ANY(%s::uuid[]) AND guide = ANY(%s) AND entity_id IS NOT NULL""",
                (ids, schemas.mention_guides()))
    rows = cur.fetchall()
    book.ents.want({e for *_x, e, _r in rows})
    roles: Dict[str, Dict[str, str]] = {}            # post -> {root: its strongest role}
    for pid, g, n, eid, role in rows:
        eid = book.pins.get((pid, g, n), eid)
        if eid not in book.ents:
            continue
        r = book.root(eid)
        old = roles.setdefault(pid, {}).get(r)
        if old is None or (role in ABOUT and old not in ABOUT) or role == "subject":
            roles[pid][r] = role or "mention"
    cur.execute("SELECT id::text, headline FROM mx_stories WHERE id = ANY(%s::uuid[])", (list(sids),))
    heads = dict(cur.fetchall())
    return posts, roles, heads


def answered(cur: Any, *, stories: Optional[Iterable[str]] = None, since: Optional[datetime] = None
             ) -> List[Tuple[str, str, bool, datetime]]:
    """Every stored stop answer (the newest task's first valid call per (story, entity)): [(story, entity as asked,
    about, answered at)], filtered in SQL. `stories`: only these; `since`: only pairs answered since then."""
    where, params = ["t.kind = %s", "t.status = 'answered'"], [KIND]
    if stories is not None:
        where.append("t.a = ANY(%s::uuid[])")
        params.append(sorted({str(s) for s in stories}))
    cur.execute(f"""SELECT a, b, about, at FROM (
                      SELECT DISTINCT ON (t.a, t.b) t.a::text AS a, t.b::text AS b, c.answer->'about' AS about,
                             c.answer->>'stop' AS stop, c.created_at AS at
                        FROM mx_tasks t
                        JOIN LATERAL (SELECT answer, created_at FROM mx_calls
                                       WHERE task_id = t.id AND valid ORDER BY created_at, ctid LIMIT 1) c ON TRUE
                       WHERE {' AND '.join(where)}
                       ORDER BY t.a, t.b, t.created_at DESC, t.id DESC) x
                     WHERE jsonb_typeof(about) = 'boolean' AND stop = ANY(%s) AND (%s::timestamptz IS NULL OR at >= %s)""",
                params + [list(STOPS), since, since])
    return [(sid, eid, bool(about), at) for sid, eid, about, at in cur.fetchall()]


def plan(cur: Any, *, now: Optional[datetime] = None, limit: int = PLAN_MAX) -> Dict[str, int]:
    """Ask the candidate (thing, story) pairs of stories whose newest member is within WINDOW_DAYS and joined since
    the last pass (mx_settings `stops_planned`), or whose members were read since (pairs never asked only); each once,
    at most `limit` a pass, newest stories first. {stories, pairs, asked, again}."""
    from insight_core.markx import identity as I, repo, tasks
    now = now or datetime.now(timezone.utc)
    out = {"stories": 0, "pairs": 0, "asked": 0, "again": 0}
    if not config()["stops"]:
        return out                                     # nothing reads the answers
    mark = repo.get_setting(cur, "stops_planned", default=None) or {}
    since = mark.get("at")
    since = datetime.fromisoformat(since) if since else now - timedelta(days=WINDOW_DAYS)
    cur.execute("""SELECT story_id::text FROM mx_story_posts
                    WHERE valid_to IS NULL AND role = 'member'
                      AND story_id IN (SELECT story_id FROM mx_story_posts WHERE valid_to IS NULL AND valid_from >= %s)
                    GROUP BY story_id HAVING count(*) >= 2 ORDER BY max(valid_from) DESC, story_id""", (since,))
    sids = [r[0] for r in cur.fetchall()]
    # stories whose members' readings came since, membership unchanged: the pass that saw them join read no roles
    # yet and asked nothing; their pairs never asked are asked now
    cur.execute("""SELECT sp.story_id::text FROM mx_story_posts sp
                    WHERE sp.valid_to IS NULL AND sp.role = 'member'
                      AND sp.story_id IN (SELECT x.story_id FROM mx_story_posts x JOIN mx_mention_sets m ON m.post_id = x.post_id
                                           WHERE x.valid_to IS NULL AND x.role = 'member' AND m.at >= %s)
                    GROUP BY sp.story_id HAVING count(*) >= 2 AND max(sp.valid_from) >= %s
                    ORDER BY max(sp.valid_from) DESC, sp.story_id""", (since, now - timedelta(days=WINDOW_DAYS)))
    have = set(sids)
    read = [s for s, in cur.fetchall() if s not in have]
    sids += read
    asked: Set[Tuple[str, str]] = set()
    if read:
        cur.execute("SELECT a::text, b::text FROM mx_tasks WHERE kind = %s AND a = ANY(%s::uuid[])", (KIND, read))
        asked = set(cur.fetchall())
    read_only = set(read)
    out["stories"] = len(sids)
    if not sids:
        repo.set_setting(cur, "stops_planned", {"at": now.isoformat()})
        return out
    book = I.lazy_book(cur)
    posts, roles, heads = stories_shown(cur, book, sids)
    for sid in sids:
        ps = sorted(posts.get(sid, []))
        things = {r for _, p, _, _ in ps for r, role in (roles.get(p) or {}).items() if role in ABOUT}
        for r in sorted(things):
            if r not in book.ents or book.shown_type(r) not in I.PRODUCT_TYPES or book.ents[r].status == "not_entity":
                continue
            sh = share([(at, p) for at, p, _, _ in ps], [p for _, p, _, _ in ps if (roles.get(p) or {}).get(r) in ABOUT])
            if not candidate(sh) or (sid in read_only and (sid, r) in asked):
                continue
            out["pairs"] += 1
            if out["asked"] >= limit:
                continue
            text = question(_thing(book, r), heads.get(sid),
                            [Line(at, src, title, (roles.get(p) or {}).get(r)) for at, p, src, title in ps])
            _tid, new = tasks.add(cur, KIND, text, a=sid, b=r, priority=PRIORITY)
            out["asked" if new else "again"] += 1
    if out["asked"] < limit:
        repo.set_setting(cur, "stops_planned", {"at": now.isoformat()})
    return out


__all__ = ["CANDIDATE_SHARE", "KIND", "STOPS", "Line", "Share", "Stop", "candidate", "coarse", "of", "parse", "plan",
           "question", "share"]
