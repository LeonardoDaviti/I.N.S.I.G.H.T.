"""Mark X News (issue 0086 E): Mark IX's own News code over Mark X's stories, into mx_news, each row tagged against
Mark IX's News; the day's briefing; and what the Mark X page reads.

**The rows** are made by `NewsService.rows` (the code Mark IX's story job writes news_stories with: the stories
begun in the last 30 days and the posts of no story, joined by the surging names) over Mark X's current stories,
with Mark IX's stored surges (news_surges, read only). Each row has Mark IX's shape (first post id, first_at,
voices, reports, shares, mentions, score) and its posts as news_posts rows (role, voice, name, position) plus the
Mark X story each came from. A run writes its rows only when they differ from the last rows written (keep
everything, without a copy an hour), so the page reads the newest run that wrote rows.

**The tags**, against Mark IX's current News rows (news_posts):
  - NEW: no post of the row is in a Mark IX row (a story that only gained an earlier post is CHANGED, not new);
  - MERGED: its posts are in two or more Mark IX rows;
  - SPLIT: its Mark IX row's posts are in two or more Mark X rows;
  - CHANGED: one Mark IX row, other posts;
  - SAME.

Only mx_* tables are written. Mark IX's are read, and its post_parts are never parsed here: a post with no parts
is left out of the rows rather than parsed (Mark IX's own job parses it, then the next run counts it).
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

TAGS = ("NEW", "MERGED", "SPLIT", "CHANGED", "SAME")
HAIKU_PER_MILLION = (0.10, 0.50)     # 0086 H: Haiku 5.5, $ per million tokens in and out (what the API would cost)


# ---- writing -------------------------------------------------------------------------------------------

def _ix_news(cur: Any, since: datetime) -> Tuple[Dict[str, str], Dict[str, Set[str]]]:
    """Mark IX's News rows of the window: {post: row id}, {row id: its posts}."""
    cur.execute("""SELECT np.post_id::text, np.news_id::text FROM news_posts np
                     JOIN news_stories ns ON ns.id = np.news_id WHERE ns.first_at >= %s""", (since,))
    of, rows = {}, defaultdict(set)
    for pid, nid in cur.fetchall():
        of[pid] = nid
        rows[nid].add(pid)
    return of, dict(rows)


def tag(posts: Sequence[str], x_of: Dict[str, str], row_id: str, ix_of: Dict[str, str],
        ix_rows: Dict[str, Set[str]]) -> str:
    """A Mark X row's tag against Mark IX's rows (above). `x_of`: post -> its Mark X row."""
    hit = {ix_of[p] for p in posts if p in ix_of}
    if not hit:
        return "NEW"
    if len(hit) >= 2:
        return "MERGED"
    (nid,) = hit
    if len({x_of.get(p) for p in ix_rows.get(nid, ()) if p in x_of}) >= 2:
        return "SPLIT"
    return "SAME" if set(posts) == ix_rows.get(nid, set()) else "CHANGED"


def _story_posts(cur: Any, ids: Iterable[str]) -> Dict[str, Any]:
    """Mark IX's StoryPosts of the posts that have their parts (none is parsed here)."""
    from insight_core.db.repo_stories import SourceFacts, StoriesRepository
    from insight_core.services.stories_service import StoriesService
    cur.execute("SELECT post_id::text FROM post_parts WHERE post_id = ANY(%s::uuid[])", (sorted(set(ids)),))
    parsed = [r[0] for r in cur.fetchall()]
    if not parsed:
        return {}
    sources = SourceFacts(cur)
    return {row["id"]: StoriesService._story_post(row, sources) for row in StoriesRepository.load_posts(cur, sources, parsed)}


def rows_of(cur: Any, stories: Dict[str, Tuple[List[str], Set[str]]], window: Iterable[str],
            since: datetime) -> List[Dict[str, Any]]:
    """Mark IX's News code over Mark X's stories ({Mark X story id: (members, mentions)}) and the window's other posts:
    the rows, each with its posts as news_posts rows and the Mark X story of each."""
    from insight_core.db.repo_news import NewsRepository
    from insight_core.services.news_service import NewsService
    from insight_core.utils.news_rules import longest
    from insight_core.utils.story_rules import Story
    every = set(window) | {p for ms, _ in stories.values() for p in ms}
    sp = _story_posts(cur, every)
    built = []
    story_of: Dict[str, str] = {}
    for sid, (members, mentions) in sorted(stories.items()):
        ps = sorted((sp[p] for p in members if p in sp), key=lambda p: (p.t, p.id))
        if len(ps) < 2:
            continue
        built.append(Story(id=sid, first_at=ps[0].t, posts=ps, voices=0, roles={}, reasons={}, mentions=set(mentions)))
        for p in ps:
            story_of.setdefault(p.id, sid)
    found = sorted(longest(NewsRepository.stored_surges(cur)), key=lambda s: (s.at, s.name))
    made = NewsService.rows(posts=list(sp.values()), stories=built, found=found, since=since)
    out = []
    for s in made:
        out.append({"id": s.id, "first_at": s.first_at, "voices": s.voices, "reports": s.reports, "shares": s.shares,
                    "mentions": s.mentions, "score": round(s.score, 2),
                    "posts": [{"post_id": p.id, "role": s.roles[p.id], "voice": p.voice, "name": s.names.get(p.id),
                               "position": n, "story": story_of.get(p.id)} for n, p in enumerate(s.posts)]})
    return out


def _signature(rows: Iterable[Dict[str, Any]]) -> Set[str]:
    return {json.dumps([str(r["id"]), r["first_at"].astimezone(timezone.utc).isoformat(), r["voices"], r["reports"],
                        r["shares"], r["mentions"], round(float(r["score"]), 2), r.get("tag"), [[p["post_id"], p["role"], p.get("story")] for p in r["posts"]]],
                       default=str) for r in rows}


def last_written(cur: Any) -> Optional[str]:
    """The newest run that wrote News rows."""
    cur.execute("""SELECT n.run_id::text FROM mx_news n JOIN mx_runs r ON r.id = n.run_id
                    GROUP BY n.run_id, r.started_at ORDER BY r.started_at DESC LIMIT 1""")
    row = cur.fetchone()
    return row[0] if row else None


def write(cur: Any, run_id: Any, *, out: Any, ids: Dict[str, str], world: Any, now: datetime) -> Dict[str, Any]:
    """A run's Mark X News: the rows, tagged, written when they differ from the last rows written."""
    from insight_core.markx import repo
    from insight_core.utils.news_rules import NEWS_KEEP
    since = now - NEWS_KEEP
    stories: Dict[str, Tuple[List[str], Set[str]]] = {}
    for s in out.stories(world.posts):
        key = s["story"]
        members = [p for p in out.about[key] if p in world.posts]
        mentions = {p for k, ms in out.mentions.items() if out.final.get(k, k) == key for p in ms}
        stories[ids[key]] = (members, mentions - set(members))
    rows = rows_of(cur, stories, [p for p, x in world.posts.items() if x.at >= since], since)
    ix_of, ix_rows = _ix_news(cur, since)
    x_of = {p["post_id"]: r["id"] for r in rows for p in r["posts"]}
    for r in rows:
        r["tag"] = tag([p["post_id"] for p in r["posts"]], x_of, r["id"], ix_of, ix_rows)
    tags = dict(Counter(r["tag"] for r in rows))
    last = last_written(cur)
    if last is not None and _signature(repo.news_rows(cur, last)) == _signature(rows):
        return {"rows": len(rows), "tags": tags, "written": False, "from": last}
    repo.add_news_rows(cur, run_id, rows)
    return {"rows": len(rows), "tags": tags, "written": True, "from": str(run_id)}


def briefing(cur: Any, *, ask: Any, now: datetime, hour: int, limit: int) -> Dict[str, Any]:
    """The day's briefing (F12), after `hour` server time: asked from the day's top Mark X News rows (most voices, then
    score), keyed s1..sN; stored with each line's Mark X stories once answered. The same rows ask the same question,
    so an answer's keys always name the stories it was asked about."""
    from insight_core.markx import repo, tasks
    local = now.astimezone()
    if local.hour < hour:
        return {"asked": False}
    day = local.date()
    run = last_written(cur)
    if run is None:
        return {"asked": False}
    start = datetime(day.year, day.month, day.day, tzinfo=local.tzinfo)
    rows = [r for r in repo.news_rows(cur, run) if start <= r["first_at"] < start + timedelta(days=1)]
    rows.sort(key=lambda r: (-r["voices"], -float(r["score"]), str(r["id"])))
    rows = rows[:limit]
    if len(rows) < 2:
        return {"asked": False, "rows": len(rows)}
    heads = headlines(cur, [r for r in rows])
    stories = [(heads[str(r["id"])]["text"], [p["post_id"] for p in r["posts"]]) for r in rows]
    posts = tasks.load_posts(cur, {p for _, ps in stories for p in ps})
    text = tasks.briefing_input(day, [(h, [posts[p] for p in ps if p in posts]) for h, ps in stories])
    got = ask.answer("briefing", text, day=day)
    if got is None:
        return {"asked": True, "answered": False}
    answer, call = got
    keys = {f"s{n}": str(r["posts"][0].get("story") or r["id"]) for n, r in enumerate(rows, 1)}
    lines = [{"text": line.get("text"), "keys": line.get("stories") or [],
              "stories": [keys[k] for k in (line.get("stories") or []) if k in keys],
              "rows": [str(rows[int(k[1:]) - 1]["id"]) for k in (line.get("stories") or [])
                       if k in keys]} for line in answer.get("lines") or []]
    repo.add_briefing(cur, day=day, call_id=call, lines=lines)
    return {"asked": True, "answered": True}


# ---- reading (the Mark X page) -----------------------------------------------------------------------

def _posts(cur: Any, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """The page's post lines: title (the one every page shows), source, platform, time."""
    from insight_core.utils.post_links import source_kind
    ids = sorted(set(ids))
    if not ids:
        return {}
    cur.execute("""SELECT p.id::text, COALESCE(pp.title, p.title), s.id::text,
                          COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), NULLIF(btrim(s.settings->>'name'), ''),
                                   s.handle_or_url),
                          s.platform, s.handle_or_url, COALESCE(p.surfaced_at, p.published_at, p.fetched_at), p.url
                     FROM posts p JOIN sources s ON s.id = p.source_id LEFT JOIN post_parts pp ON pp.post_id = p.id
                    WHERE p.id = ANY(%s::uuid[])""", (ids,))
    return {pid: {"id": pid, "title": title or "", "source_id": sid, "source": name or "", "kind": source_kind(platform, handle),
                  "at": at, "url": url} for pid, title, sid, name, platform, handle, at, url in cur.fetchall()}


def headlines(cur: Any, rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Each row's headline: its Mark X story's Haiku headline (F4), else its lead's title."""
    sids = sorted({p.get("story") for r in rows for p in (r["posts"] or [])[:1] if p.get("story")})
    heads: Dict[str, str] = {}
    if sids:
        cur.execute("SELECT id::text, headline FROM mx_stories WHERE id = ANY(%s::uuid[]) AND headline IS NOT NULL", (sids,))
        heads = dict(cur.fetchall())
    leads = _posts(cur, [str(r["id"]) for r in rows])
    out = {}
    for r in rows:
        sid = (r["posts"] or [{}])[0].get("story")
        if sid and heads.get(sid):
            out[str(r["id"])] = {"text": heads[sid], "from": "haiku"}
        else:
            out[str(r["id"])] = {"text": (leads.get(str(r["id"])) or {}).get("title") or "", "from": "lead title"}
    return out


def _why(cur: Any, post_ids: Sequence[str]) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """{(story, post): its current membership with the judge's relation and words} for these posts."""
    cur.execute("""SELECT sp.story_id::text, sp.post_id::text, sp.role, sp.reason, sp.p, c.answer
                     FROM mx_story_posts sp LEFT JOIN mx_calls c ON c.id = sp.call_id
                    WHERE sp.valid_to IS NULL AND sp.post_id = ANY(%s::uuid[])""", (list(post_ids),))
    out = {}
    for sid, pid, role, reason, p, answer in cur.fetchall():
        answer = answer or {}
        out[(sid, pid)] = {"role": role, "reason": reason, "p": p, "relation": answer.get("relation"),
                           "words": answer.get("reason")}
    return out


def _checks(cur: Any, post_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
    """The newest valid check answer of each post (why a removed member went)."""
    if not post_ids:
        return {}
    cur.execute("""SELECT DISTINCT ON (t.a) t.a::text, c.answer FROM mx_tasks t JOIN mx_calls c ON c.task_id = t.id AND c.valid
                    WHERE t.kind = 'check' AND t.a = ANY(%s::uuid[]) ORDER BY t.a, c.created_at DESC""", (list(post_ids),))
    from insight_core.markx.decide import Verdict
    out = {}
    for pid, answer in cur.fetchall():
        v = Verdict.of(answer or {})
        out[pid] = {"relation": v.relation, "p": round(v.p, 2), "words": v.reason}
    return out


def page(cur: Any, *, only_differences: bool = True, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The Mark X News beside Mark IX's: the newest written run's rows (only the differences, by default), each with its
    tag, headline, members (why each is there and what Mark IX did with it) and the Mark IX posts it left out; and the
    Mark IX rows no Mark X row holds."""
    from insight_core.markx import repo
    from insight_core.utils.news_rules import NEWS_DAYS
    now = now or datetime.now(timezone.utc)
    run = last_written(cur)
    if run is None:
        return {"run": None, "items": [], "gone": [], "counts": {}, "ix_rows": 0}
    since = now - timedelta(days=NEWS_DAYS)
    rows = [r for r in repo.news_rows(cur, run) if r["first_at"] >= since]
    ix_of, ix_rows = _ix_news(cur, since)
    cur.execute("SELECT id::text, voices, first_at FROM news_stories WHERE first_at >= %s", (since,))
    ix_meta = {nid: {"voices": v, "first_at": f} for nid, v, f in cur.fetchall()}
    counts = dict(Counter(r["tag"] for r in rows))
    x_of = {p["post_id"]: str(r["id"]) for r in rows for p in r["posts"]}
    shown = [r for r in rows if not only_differences or r["tag"] != "SAME"]
    every = {p["post_id"] for r in shown for p in r["posts"]} | {p for r in shown for nid in {ix_of.get(q["post_id"]) for q in r["posts"]}
                                                                if nid for p in ix_rows.get(nid, ())}
    gone_rows = [nid for nid, ps in ix_rows.items() if not any(p in x_of for p in ps)]
    every |= {p for nid in gone_rows for p in ix_rows[nid]}
    posts = _posts(cur, every | set(ix_rows))
    why = _why(cur, sorted(every))
    left = {p for r in shown for nid in {ix_of.get(q["post_id"]) for q in r["posts"]} if nid
            for p in ix_rows.get(nid, ()) if p not in {q["post_id"] for q in r["posts"]}}
    left |= {p for nid in gone_rows for p in ix_rows[nid]}
    checks = _checks(cur, sorted(left))
    heads = headlines(cur, shown)
    ix_titles = {nid: (posts.get(nid) or {}).get("title") for nid in ix_rows}

    def line(pid: str, story: Optional[str], row_ids: Set[str]) -> Dict[str, Any]:
        p = posts.get(pid) or {"id": pid}
        w = why.get((story, pid)) if story else None
        nid = ix_of.get(pid)
        ix = ({"row": nid, "title": ix_titles.get(nid), "same_row": nid in row_ids} if nid else None)
        return {**{k: p.get(k) for k in ("id", "title", "source", "kind", "at", "url")}, "why": w, "ix": ix}

    items = []
    for r in shown:
        mine = [p["post_id"] for p in r["posts"]]
        ix_hit = sorted({ix_of[p] for p in mine if p in ix_of})
        lines = [dict(line(p["post_id"], p.get("story"), set(ix_hit)), role=p["role"]) for p in r["posts"]]
        removed = []
        for nid in ix_hit:
            for pid in sorted(ix_rows.get(nid, ()), key=lambda q: str((posts.get(q) or {}).get("at") or "")):
                if pid in mine:
                    continue
                p = posts.get(pid) or {"id": pid}
                removed.append({**{k: p.get(k) for k in ("id", "title", "source", "kind", "at", "url")},
                                "check": checks.get(pid), "now_in": x_of.get(pid),
                                "mention": next((w for (s, q), w in why.items() if q == pid and w["role"] != "member"), None)})
        items.append({"id": str(r["id"]), "tag": r["tag"], "headline": heads[str(r["id"])], "first_at": r["first_at"],
                      "voices": r["voices"], "reports": r["reports"], "shares": r["shares"], "mentions": r["mentions"],
                      "score": float(r["score"]), "story": (r["posts"] or [{}])[0].get("story"), "posts": lines,
                      "removed": removed,
                      "ix": [{"id": nid, "title": ix_titles.get(nid), **(ix_meta.get(nid) or {})} for nid in ix_hit]})
    items.sort(key=lambda i: (i["first_at"] < now - timedelta(hours=48), -i["score"], -i["first_at"].timestamp(), i["id"]))
    gone = []
    for nid in sorted(gone_rows, key=lambda n: -(ix_meta.get(n) or {}).get("voices", 0)):
        gone.append({"id": nid, "title": ix_titles.get(nid), **(ix_meta.get(nid) or {}),
                     "posts": [{**{k: (posts.get(p) or {}).get(k) for k in ("id", "title", "source", "kind", "at")},
                                "check": checks.get(p),
                                "mention": next((w for (s, q), w in why.items() if q == p and w["role"] != "member"), None)}
                               for p in sorted(ix_rows[nid])]})
    cur.execute("SELECT started_at, finished_at, code_version, counts FROM mx_runs WHERE id = %s", (run,))
    started, finished, code, run_counts = cur.fetchone()
    return {"run": {"id": run, "started_at": started, "finished_at": finished, "code_version": code},
            "counts": {**counts, "rows": len(rows), "ix_rows": len(ix_rows), "gone": len(gone)}, "items": items, "gone": gone}


def post_panel(cur: Any, post_id: str) -> Dict[str, Any]:
    """The post page's Mark X panel: its reading, its entities and their roles, its Mark X stories (role, reason, the
    judge's words) and connections, each with its reason."""
    from insight_core.markx import repo
    cur.execute("SELECT guide, kind, events, lang, headline, reading FROM mx_readings WHERE post_id = %s ORDER BY guide DESC",
                (post_id,))
    r = cur.fetchone()
    reading = None if r is None else {"guide": r[0], "kind": r[1], "events": r[2], "lang": r[3], "headline": r[4],
                                      "main": (r[5] or {}).get("main"), "mentions": (r[5] or {}).get("mentions") or []}
    entities = [{k: m[k] for k in ("name", "type", "role", "maker", "family", "version", "variant", "span")}
                for m in repo.mentions(cur, post_id) if m["guide"] == "ent-v3"]
    stories = []
    for (sid, _pid), w in _why(cur, [post_id]).items():
        st = repo.get_story(cur, sid) or {}
        members = repo.current_members(cur, sid)
        stories.append({"id": sid, "headline": st.get("headline"), "first_at": st.get("first_at"), **w,
                        "posts": len([m for m in members if m["role"] == "member"])})
    conns = []
    things = [("post", post_id)] + [("story", s["id"]) for s in stories]
    for kind, thing in things:
        for c in repo.current_connections(cur, kind, thing):
            other_kind, other = (c["b_kind"], c["b"]) if (c["a_kind"], str(c["a"])) == (kind, thing) else (c["a_kind"], c["a"])
            conns.append({"relation": c["relation"], "p": c["p"], "rule": c["rule"], "from": kind,
                          "other_kind": other_kind, "other": str(other), "reason": (c["evidence"] or {}).get("reason")})
    other_stories = sorted({c["other"] for c in conns if c["other_kind"] == "story"})
    if other_stories:
        cur.execute("SELECT id::text, headline FROM mx_stories WHERE id = ANY(%s::uuid[])", (other_stories,))
        heads = dict(cur.fetchall())
        for c in conns:
            if c["other_kind"] == "story":
                c["title"] = heads.get(c["other"])
    other_posts = _posts(cur, [c["other"] for c in conns if c["other_kind"] == "post"])
    for c in conns:
        if c["other_kind"] == "post":
            c["title"] = (other_posts.get(c["other"]) or {}).get("title")
    return {"post_id": post_id, "reading": reading, "entities": entities, "stories": stories, "connections": conns,
            "read": reading is not None}


def entities(cur: Any, *, now: Optional[datetime] = None, limit: int = 30) -> Dict[str, Any]:
    """Today's and this week's main-subject entities (F7, ent-v3: role subject), each with its posts and voices."""
    now = now or datetime.now(timezone.utc)
    out = {}
    for name, days in (("today", 1), ("week", 7)):
        cur.execute("""SELECT m.name_key, lower(COALESCE(m.version, '')), (array_agg(m.name ORDER BY m.name))[1],
                              (array_agg(m.type))[1], count(DISTINCT m.post_id), count(DISTINCT p.source_id),
                              (array_agg(DISTINCT m.post_id::text))[1:5]
                         FROM mx_mentions m JOIN posts p ON p.id = m.post_id
                        WHERE m.guide = 'ent-v3' AND m.role = 'subject'
                          AND COALESCE(p.surfaced_at, p.published_at, p.fetched_at) >= %s
                        GROUP BY 1, 2 ORDER BY count(DISTINCT p.source_id) DESC, count(DISTINCT m.post_id) DESC, 1 LIMIT %s""",
                    (now - timedelta(days=days), limit))
        rows = cur.fetchall()
        posts = _posts(cur, {p for r in rows for p in (r[6] or [])})
        out[name] = [{"key": k, "version": v or None, "name": n, "type": t, "posts": np_, "voices": nv,
                      "examples": [{k2: (posts.get(p) or {}).get(k2) for k2 in ("id", "title", "source")} for p in (ps or [])]}
                     for k, v, n, t, np_, nv, ps in rows]
    return out


def briefings(cur: Any) -> Dict[str, Any]:
    """The newest day's briefings (newest first), with each line's Mark X stories and News rows."""
    cur.execute("SELECT max(day) FROM mx_briefings")
    day = cur.fetchone()[0]
    if day is None:
        return {"day": None, "briefings": []}
    from insight_core.markx import repo
    out = []
    for b in repo.briefings(cur, day):
        cur.execute("SELECT t.guide FROM mx_calls c JOIN mx_tasks t ON t.id = c.task_id WHERE c.id = %s", (b["call_id"],))
        guide = (cur.fetchone() or [None])[0]
        out.append({"created_at": b["created_at"], "guide": guide, "lines": b["lines"]})
    return {"day": day, "briefings": out}


def worker(cur: Any, contacts: Dict[str, datetime]) -> Dict[str, Any]:
    """The worker's side: the queue by kind, answers per day, tokens and their API cost, failures, last contacts, the
    last decision run."""
    from insight_core.markx import repo
    queue = repo.queue_counts(cur)
    cur.execute("""SELECT created_at::date, count(*), count(*) FILTER (WHERE valid), COALESCE(sum(tokens_in), 0),
                          COALESCE(sum(tokens_out), 0) FROM mx_calls GROUP BY 1 ORDER BY 1 DESC LIMIT 14""")
    days = [{"day": d, "calls": n, "valid": v, "tokens_in": int(ti), "tokens_out": int(to),
             "api_usd": round(int(ti) * HAIKU_PER_MILLION[0] / 1e6 + int(to) * HAIKU_PER_MILLION[1] / 1e6, 4)}
            for d, n, v, ti, to in cur.fetchall()]
    cur.execute("SELECT count(*), COALESCE(sum(tokens_in), 0), COALESCE(sum(tokens_out), 0), COALESCE(sum(cost_usd), 0) FROM mx_calls")
    n, ti, to, cost = cur.fetchone()
    cur.execute("""SELECT kind, last_error, count(*) FROM mx_tasks WHERE status = 'failed'
                    GROUP BY 1, 2 ORDER BY 3 DESC, 1 LIMIT 20""")
    failed = [{"kind": k, "error": e, "tasks": c} for k, e, c in cur.fetchall()]
    cur.execute("""SELECT t.kind, c.error, c.created_at FROM mx_calls c JOIN mx_tasks t ON t.id = c.task_id
                    WHERE NOT c.valid ORDER BY c.created_at DESC LIMIT 10""")
    invalid = [{"kind": k, "error": e, "at": at} for k, e, at in cur.fetchall()]
    cur.execute("SELECT leased_by, count(*), max(lease_until) FROM mx_tasks WHERE status = 'leased' GROUP BY 1")
    leased = {w: (k, until) for w, k, until in cur.fetchall()}
    workers = [{"worker": w, "last_contact": contacts.get(w), "leased": leased.get(w, (0, None))[0]}
               for w in sorted(set(contacts) | set(leased))]
    run = repo.last_run(cur)
    return {"queue": queue, "days": days,
            "tokens": {"calls": n, "tokens_in": int(ti), "tokens_out": int(to), "paid_usd": round(float(cost), 4),
                       "api_usd": round(int(ti) * HAIKU_PER_MILLION[0] / 1e6 + int(to) * HAIKU_PER_MILLION[1] / 1e6, 4)},
            "failed": failed, "invalid": invalid, "workers": workers,
            "last_run": None if run is None else {"id": str(run["id"]), "started_at": run["started_at"],
                                                  "finished_at": run["finished_at"], "code_version": run["code_version"],
                                                  "counts": run["counts"]}}
