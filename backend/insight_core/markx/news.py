"""Mark X News: Mark IX's News code (`NewsService.rows`) over Mark X's stories into mx_news, each row tagged against
Mark IX's News (NEW, MERGED, SPLIT, CHANGED, SAME: `tag`); the day's briefing; and what the News page reads (`page`,
kept by `page_inputs`). A run writes its rows only when they differ from the last rows written. Only mx_* tables are
written; a post with no post_parts is left out rather than parsed here.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from insight_core.markx import pairing
from insight_core.utils import voice

HAIKU_PER_MILLION = (0.10, 0.50)     # Haiku $ per million tokens in and out


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


def _story_posts(cur: Any, ids: Iterable[str], sources: Any = None) -> Dict[str, Any]:
    """Mark IX's StoryPosts of the posts that have their parts (none is parsed here)."""
    from insight_core.db.repo_stories import SourceFacts, StoriesRepository
    from insight_core.services.stories_service import StoriesService
    cur.execute("SELECT post_id::text FROM post_parts WHERE post_id = ANY(%s::uuid[])", (sorted(set(ids)),))
    parsed = [r[0] for r in cur.fetchall()]
    if not parsed:
        return {}
    sources = SourceFacts(cur) if sources is None else sources
    said = reports(cur, parsed)
    return {row["id"]: replace(StoriesService._story_post(row, sources), report=said.get(row["id"]))
            for row in StoriesRepository.load_posts(cur, sources, parsed)}


def reports(cur: Any, ids: Iterable[str]) -> Dict[str, bool]:
    """{post: whether its preferred reading says it reports an event (kind report, not a leak)}: what leads a row."""
    from insight_core.markx import event_types, reading5
    ids = sorted({str(p) for p in ids if p})
    if not ids:
        return {}
    rank = reading5.rank_sql("guide")
    cur.execute(f"""SELECT DISTINCT ON (post_id) post_id::text, kind,
                           COALESCE(reading->>'event_type', reading->'reading'->>'event_type') FROM mx_readings
                     WHERE post_id = ANY(%s::uuid[]) AND {rank} IS NOT NULL ORDER BY post_id, {rank}""", (ids,))
    return {pid: kind == "report" and kind_type != event_types.LEAK for pid, kind, kind_type in cur.fetchall()}


# ---- what each post's StoryPost is made of, kept by the run's state (0177) -----------------------------------------
# Per post a digest of its text stamp and its links' resolution, plus the source facts and the surges: the posts whose
# digest or surge changed seed the rows made again (`_changed_rows`); changed source facts: a full pass.

def facts_digest(sources: Any) -> str:
    """The source facts as a StoryPost reads them (kind, publication, home site, account; accounts; owners)."""
    import hashlib
    data = [[i, sources.kind.get(i), sources.publication(i), sources.home_site(i), sources.account.get(i)]
            for i in sorted(sources.kind)]
    blob = json.dumps([data, sorted(sources.of_account.items()), sorted(sources.owners.items())], default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


def post_digests(cur: Any, memo: Any, ids: Iterable[str]) -> Dict[str, str]:
    """{post: a digest of its text stamp and of its kept links' resolution} of the posts of `ids` that exist."""
    import hashlib
    from insight_core.markx import incremental
    ids = sorted(set(ids))
    stamps = incremental.stamps_of(cur, memo, ids)
    cur.execute("""SELECT pl.post_id::text, string_agg(pl.target_url || ' ' || COALESCE(t.id::text, '-'), ' '
                                                       ORDER BY pl.position, pl.target_url)
                     FROM post_links pl LEFT JOIN LATERAL (SELECT tp.id FROM posts tp WHERE tp.normalized_url = pl.target_url
                                                           ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
                    WHERE NOT pl.boilerplate AND pl.post_id = ANY(%s::uuid[]) GROUP BY pl.post_id""", (ids,))
    links = dict(cur.fetchall())
    said = reports(cur, ids)   # a reading that comes or changes may change a row's lead
    return {i: hashlib.sha1(f"{stamps[i]}\x1f{links.get(i, '')}\x1f{said.get(i)}".encode()).hexdigest()[:16]
            for i in ids if i in stamps}


def surge_keys(found: Iterable[Any]) -> List[List[Any]]:
    return sorted([s.name, s.at.isoformat() if s.at else None, list(s.posts), s.usual] for s in found)


def changed_posts(last: Dict[str, Any], now: Dict[str, Any]) -> Set[str]:
    """The posts whose StoryPost inputs differ between two runs' digests, and the posts of a surge in one of them only."""
    a, b = last.get("posts") or {}, now.get("posts") or {}
    out = {p for p in set(a) | set(b) if a.get(p) != b.get(p)}
    was = {json.dumps(k) for k in last.get("surges") or []}
    new = {json.dumps(k) for k in now.get("surges") or []}
    for k in was ^ new:
        out |= set(json.loads(k)[2])
    return out


def window_posts(cur: Any, since: datetime) -> Set[str]:
    """The posts News reads for the window starting at `since`: from NEWS_EDGE before it, as Mark IX's code does
    (a row is in the window by its first post, so a row an earlier post begins is no row of it; 0111, 0124)."""
    from insight_core.utils.news_rules import NEWS_EDGE
    cur.execute(f"SELECT id::text FROM posts WHERE {pairing.ix_date('')} >= %s", (since - NEWS_EDGE,))
    return {r[0] for r in cur.fetchall()}


def release_keys(joins: Iterable[Sequence[str]], stories: Iterable[str]) -> Dict[str, str]:
    """{story: its one-release group's key (the group's lowest story id)} for the stories in a group with another of
    `stories`. Pure."""
    have = set(stories)
    out: Dict[str, str] = {}
    for g in joins:
        present = sorted({str(s) for s in g} & have)
        if len(present) >= 2:
            for s in present:
                out[s] = present[0]
    return out


def _window_stories(stories: Dict[str, Tuple[List[str], Set[str]]], sp: Dict[str, Any],
                    joins: Iterable[Sequence[str]], since: datetime) -> Set[str]:
    """The stories a one-release group joins in the window starting at `since`, each by its own start: a group's
    story begun before `since` stays out of the group, else it would carry the group's row (and its launch) out of
    the window."""
    grouped = {str(s) for g in joins for s in g} & set(stories)
    out = set(stories) - grouped
    for sid in grouped:
        own = _own_start(stories[sid][0], sp)
        if own is None or own >= since:
            out.add(sid)
    return out


def _own_start(members: Iterable[str], sp: Dict[str, Any]) -> Optional[datetime]:
    """A story's own start over its own posts, whatever group it is in: what the window reads it by and the run keeps
    as its `first`."""
    from insight_core.utils.story_rules import story_start, story_times
    ps = [sp[p] for p in members if p in sp]
    return story_start(ps, story_times(ps)) if ps else None


def rows_of(cur: Any, stories: Dict[str, Tuple[List[str], Set[str]]], since: datetime,
            only: Optional[Set[str]] = None, window: Optional[Set[str]] = None,
            first: Optional[Dict[str, Any]] = None, memo: Any = None, sources: Any = None,
            joins: Optional[Sequence[Sequence[str]]] = None) -> List[Dict[str, Any]]:
    """Mark IX's News code over Mark X's stories ({story id: (members, mentions)}) and the window's posts of no story:
    the rows, each with its posts as news_posts rows and the Mark X story of each. `only`: the rows of those posts
    only (a set closed under rows, stories, mentions and surges). `first` gets each story's own start. `joins`
    (graph.release_groups, read when None): each group's stories are one story to News's code, keyed by the lowest
    id, each post still naming its own."""
    from insight_core.services.news_service import NewsService
    from insight_core.utils.story_rules import Story, lead_order, story_start, story_times
    in_story = {p for ms, _ in stories.values() for p in ms}
    every = (window_posts(cur, since) if window is None else set(window)) | in_story
    if only is not None:
        every &= only
    sp = _story_posts(cur, every, sources)
    stored = sorted(sid for sid in stories if not sid.startswith(("one:", "new:")))   # a stored story's id only
    if joins is None:
        from insight_core.markx import graph
        joins = graph.release_groups(cur, stored)
    key_of = release_keys(joins, _window_stories(stories, sp, joins, since))
    parts: Dict[str, List[str]] = defaultdict(list)
    for sid in sorted(stories):
        parts[key_of.get(sid, sid)].append(sid)
    built = []
    made_of: Set[str] = set()
    for key, sids in sorted(parts.items()):
        seen: Set[str] = set()
        ps, mentions = [], set()
        for sid in sids:
            for p in stories[sid][0]:
                if p in sp and p not in seen:
                    seen.add(p)
                    ps.append(sp[p])
            mentions |= set(stories[sid][1])
        if not ps or (len(ps) < 2 and not key.startswith("one:")):
            continue
        times = story_times(ps)
        ps = lead_order(ps, times)    # never led by a background page nor a non-report (0263)
        start = story_start(ps, times)
        built.append(Story(id=key, first_at=start, posts=ps, voices=0, roles={}, reasons={},
                           mentions=mentions - seen))
        made_of |= set(sids)
        if first is not None:
            for sid in sids:
                own = _own_start(stories[sid][0], sp)
                if own is not None:
                    first[sid] = own
    story_of: Dict[str, str] = {}
    for sid, (members, _m) in sorted(stories.items()):   # each post names its own story (the lowest id of several)
        if sid in made_of and not sid.startswith("one:"):
            for p in members:
                if p in sp:
                    story_of.setdefault(p, sid)
    from insight_core.markx import incremental
    found = incremental.surges(cur, memo)
    from insight_core.markx import built as mx_built
    # two stories join by a surging name only when judged connected (the judge's or the chain's one-happening edges);
    # a pair inside one release group is no pair
    from insight_core.markx import graph
    judged = {frozenset(key_of.get(s, s) for s in pair)
              for pair in mx_built._connected(cur, stored) | graph.chain_connected(cur, stored)}
    judged = {pair for pair in judged if len(pair) == 2}
    made = NewsService.rows(posts=list(sp.values()), stories=built, found=found, since=since, judged=judged)
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
    """The newest run that wrote News rows (an EXISTS per run on mx_news' index, not a group-by over all rows: 0198)."""
    cur.execute("""SELECT r.id::text FROM mx_runs r WHERE EXISTS (SELECT 1 FROM mx_news n WHERE n.run_id = r.id)
                    ORDER BY r.started_at DESC, r.finished_at DESC NULLS LAST LIMIT 1""")
    row = cur.fetchone()
    return row[0] if row else None


def _changed_rows(cur: Any, stories: Dict[str, Tuple[List[str], Set[str]]], since: datetime,
                  last: Dict[str, Any], window: Set[str], memo: Any = None, extra: Iterable[str] = (),
                  sources: Any = None, joins: Sequence[Sequence[str]] = ()
                  ) -> Tuple[List[Dict[str, Any]], Set[str], Dict[str, Any]]:
    """The last run's rows, with only those its changed stories reach made again. Seeds: the posts of changed stories
    (now and before), posts that entered or left the window, stories whose start left it, release groups that came
    or went; closed over rows, stories, release groups and surges. Must agree with a full pass.
    Returns (rows, the group, firsts)."""
    from insight_core.markx import incremental
    stories = {sid: (frozenset(ms), frozenset(mentions)) for sid, (ms, mentions) in stories.items()}
    seeds: Set[str] = set(window ^ last["window"]) | set(extra)   # `extra`: the posts whose StoryPost changed
    now_joins = {tuple(sorted(g)) for g in joins}
    was_joins = {tuple(sorted(g)) for g in last.get("joins") or ()}
    partners: Dict[str, Set[str]] = defaultdict(set)
    for g in now_joins | was_joins:
        for sid in g:
            partners[sid] |= set(g)
    for g in now_joins ^ was_joins:
        for sid in g:
            for book in (stories, last["stories"]):
                if sid in book:
                    seeds |= set(book[sid][0]) | set(book[sid][1])
    for sid in set(stories) | set(last["stories"]):
        now_, was = stories.get(sid), last["stories"].get(sid)
        if now_ != was:
            for v in (now_, was):
                if v:
                    seeds |= set(v[0]) | set(v[1])
    for sid, at in last["first"].items():
        if at is not None and last["since"] <= at < since or since <= at < last["since"]:
            v = stories.get(sid) or last["stories"].get(sid)
            if v:
                seeds |= set(v[0]) | set(v[1])
    surges_of: Dict[str, List[Set[str]]] = defaultdict(list)
    for s in incremental.surges(cur, memo):
        for pid in s.posts:
            surges_of[pid].append(set(s.posts))
    rows_of_post: Dict[str, List[int]] = defaultdict(list)
    for n, r in enumerate(last["rows"]):
        for p in r["posts"]:
            rows_of_post[p["post_id"]].append(n)
    stories_of_post: Dict[str, Set[str]] = defaultdict(set)
    for book in (stories, last["stories"]):
        for sid, (ms, mentions) in book.items():
            for pid in (*ms, *mentions):
                stories_of_post[pid].add(sid)
    group, frontier = set(seeds), set(seeds)
    while frontier:
        more: Set[str] = set()
        for pid in frontier:
            for n in rows_of_post.get(pid, ()):
                more |= {p["post_id"] for p in last["rows"][n]["posts"]}
            for sid in {x for s in stories_of_post.get(pid, ()) for x in partners.get(s, {s})}:
                for book in (stories, last["stories"]):
                    if sid in book:
                        more |= set(book[sid][0]) | set(book[sid][1])
            for ps in surges_of.get(pid, ()):
                more |= ps
        frontier = more - group
        group |= frontier
    touching = {sid: (sorted(v[0]), set(v[1])) for sid, v in stories.items() if (v[0] | v[1]) & group}
    first = {sid: at for sid, at in last["first"].items() if sid in stories and sid not in touching}
    made = rows_of(cur, touching, since, only=group, window=window, first=first, memo=memo,
                   sources=sources, joins=[g for g in now_joins if set(g) & set(touching)]) if group else []
    kept = [r for r in last["rows"] if not any(p["post_id"] in group for p in r["posts"])]
    return sorted(kept + made, key=lambda r: (r["first_at"], str(r["id"]))), group, first


def main_story(row: Dict[str, Any]) -> Optional[str]:
    """The row's Mark X story holding most of its voices, then most posts, then the first; None when no post is in a
    story."""
    seen: Dict[str, List[Any]] = {}
    for n, p in enumerate(row.get("posts") or []):
        sid = p.get("story")
        if sid:
            got = seen.setdefault(str(sid), [set(), 0, n])
            got[0].add(p.get("voice") or p.get("post_id"))
            got[1] += 1
    if not seen:
        return None
    return min(seen, key=lambda s: (-len(seen[s][0]), -seen[s][1], seen[s][2]))


def row_headline_input(row: Dict[str, Any], posts: Dict[str, Any]) -> Optional[str]:
    """A row's own headline question (tasks.headline_input over its posts); the page finds the answer by this input."""
    from insight_core.markx import tasks
    ps = [posts[p["post_id"]] for p in row.get("posts") or [] if p["post_id"] in posts]
    return tasks.headline_input(ps) if ps else None


def _row_posts(cur: Any, rows: Sequence[Dict[str, Any]], known: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from insight_core.markx import tasks
    ids = {p["post_id"] for r in rows for p in r.get("posts") or []}
    known = known or {}
    have = {i: known[i] for i in ids if i in known}
    have.update(tasks.load_posts(cur, sorted(ids - set(have))))
    return have


def ask_row_headlines(cur: Any, rows: Sequence[Dict[str, Any]], ask: Any, *, headed: Set[str],
                      known: Optional[Dict[str, Any]] = None, memo: Any = None) -> Dict[str, int]:
    """A headline task for every News row whose main story is not in `headed` (the stories the run asks a headline
    for), so every row gets one. {"asked", "answered"}. With the run's state (`memo`, `known` its texts), each row's
    input is kept by its posts' stamps."""
    need = [r for r in rows if main_story(r) not in headed]
    if not need:
        return {"asked": 0, "answered": 0}
    if memo is not None and known is not None:
        return _ask_row_headlines_kept(cur, need, ask, memo, known)
    posts = _row_posts(cur, need, known)
    asked = answered = 0
    for r in need:
        text = row_headline_input(r, posts)
        if text is None:
            continue
        asked += 1
        if ask.answer("headline", text, a=r["posts"][0]["post_id"]) is not None:
            answered += 1
    return {"asked": asked, "answered": answered}


def _ask_row_headlines_kept(cur: Any, need: Sequence[Dict[str, Any]], ask: Any, memo: Any, texts: Any
                            ) -> Dict[str, int]:
    """ask_row_headlines' questions, each input kept by its posts' stamps (incremental.rendered)."""
    from insight_core.markx import incremental, tasks
    stamps = incremental.stamps_of(cur, memo, {p["post_id"] for r in need for p in r.get("posts") or []})
    asked = answered = 0
    for r in need:
        ids = [p["post_id"] for p in r.get("posts") or [] if p["post_id"] in stamps]
        if not ids:
            continue
        asked += 1
        text = incremental.rendered(memo, "row_headline", ids,
                                    lambda: tasks.headline_input([texts.load(ids)[i] for i in ids]), texts=texts)
        if ask.answer("headline", text, a=r["posts"][0]["post_id"]) is not None:
            answered += 1
    return {"asked": asked, "answered": answered}


def write(cur: Any, run_id: Any, *, out: Any, ids: Dict[str, str], world: Any, now: datetime,
          store: bool = True, ask: Any = None, headed: Optional[Set[str]] = None) -> Dict[str, Any]:
    """A run's Mark X News: the rows, tagged, written when they differ from the last rows written. With the run's
    memo (`world.memo`), only the rows its changed stories reach are made again. `store` False: nothing is written,
    the rows are returned. With `ask`, rows whose main story is not in `headed` are asked a headline of their own."""
    import copy
    from insight_core.markx import incremental, repo
    from insight_core.utils.news_rules import NEWS_KEEP
    since = now - NEWS_KEEP
    stories: Dict[str, Tuple[List[str], Set[str]]] = {}
    for s in out.stories(world.posts):
        key = s["story"]
        members = [p for p in out.about[key] if p in world.posts]
        # the roundups that mention it: Mark IX's (story_mentions, link evidence) and Mark X's demotions
        mentions = {p for k, ms in out.mentions.items() if out.final.get(k, k) == key for p in ms}
        mentions |= {p for k, ms in world.ix_mentions.items() if out.final.get(k, k) == key for p in ms}
        stories[ids[key]] = (members, mentions - set(members))
    for key in sorted(out.ix):   # a one-post Mark IX story Mark X left alone: its roundups still count
        ms = [p for p in out.about.get(key, {}) if p in world.posts]
        if len(ms) == 1 and world.ix_mentions.get(key):
            stories[f"one:{key}"] = (ms, set(world.ix_mentions[key]) - set(ms))
    memo = getattr(world, "memo", None)
    window = window_posts(cur, since)
    from insight_core.markx import graph   # the one-release groups ([] while chains.one_row is off)
    joins = graph.release_groups(cur, [sid for sid in stories if not sid.startswith(("one:", "new:"))])
    how, group = "full", None
    first: Dict[str, Any] = {}
    sources = inputs = last_inputs = None
    state = isinstance(memo, incremental.State)   # the kept state (an in-process memo has no stamps)
    if state:   # what the StoryPosts are made of, for the next run to compare
        from insight_core.db.repo_stories import SourceFacts
        sources = SourceFacts(cur)
        universe = window | {p for ms, _ in stories.values() for p in ms}
        inputs = {"facts": facts_digest(sources), "posts": post_digests(cur, memo, universe),
                  "surges": surge_keys(incremental.surges(cur, memo))}
        last_inputs = (memo.news or {}).get("inputs")
    if state and memo.news is not None and last_inputs is not None and last_inputs["facts"] == inputs["facts"]:
        rows, group, first = _changed_rows(cur, stories, since, memo.news, window, memo,
                                           extra=changed_posts(last_inputs, inputs), sources=sources, joins=joins)
        how = "incremental"
    elif (not state and memo is not None and memo.news is not None
          and not set(memo.report.get("ix_changed") or ()) & set(incremental.NEWS_TABLES)):
        rows, group, first = _changed_rows(cur, stories, since, memo.news, window, memo, joins=joins)   # in-process memo
        how = "incremental"
    else:
        rows = rows_of(cur, stories, since, window=window, first=first, memo=memo, sources=sources, joins=joins)
    ix_of, ix_rows = _ix_news(cur, since)
    x_of = {p["post_id"]: r["id"] for r in rows for p in r["posts"]}
    for r in rows:
        r["tag"] = tag([p["post_id"] for p in r["posts"]], x_of, r["id"], ix_of, ix_rows)
    tags = dict(Counter(r["tag"] for r in rows))
    if memo is not None:
        memo.news = {"since": since, "window": window, "first": first, "rows": copy.deepcopy(rows),
                     "stories": {sid: (frozenset(ms), frozenset(mentions)) for sid, (ms, mentions) in stories.items()},
                     "inputs": inputs, "code": incremental.news_stamp(),   # the code that made them
                     "joins": [list(g) for g in joins]}
    made = {"made": how, **({"group": len(group)} if group is not None else {})}
    if ask is not None:
        made["row_headlines"] = ask_row_headlines(cur, rows, ask, headed=set(headed or ()),
                                                  known=getattr(world, "text", None),
                                                  memo=memo if isinstance(memo, incremental.State) else None)
    if not store:
        return {"rows": len(rows), "tags": tags, "written": False, "made_rows": rows, **made}
    last = last_written(cur)
    if last is not None and _signature(repo.news_rows(cur, last)) == _signature(rows):
        return {"rows": len(rows), "tags": tags, "written": False, "from": last, **made}
    repo.add_news_rows(cur, run_id, rows)
    return {"rows": len(rows), "tags": tags, "written": True, "from": str(run_id), **made}


def briefing(cur: Any, *, ask: Any, now: datetime, hour: int, limit: int) -> Dict[str, Any]:
    """The day's briefing, after `hour` server time: asked from the day's top News rows (most voices, then score), keyed
    s1..sN; stored with each line's stories once answered. The same rows ask the same question."""
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
    """The page's post lines: title, source, kind, published time, url and byline."""
    from insight_core.utils import byline
    from insight_core.utils.post_links import source_kind
    ids = sorted(set(ids))
    if not ids:
        return {}
    cur.execute(f"""SELECT p.id::text, COALESCE(pp.title, p.title), s.id::text, {byline.SOURCE_NAME},
                           {pairing.published_date('p')}, p.url, {byline.COLUMNS}
                      FROM posts p JOIN sources s ON s.id = p.source_id LEFT JOIN post_parts pp ON pp.post_id = p.id
                     WHERE p.id = ANY(%s::uuid[])""", (ids,))
    rows = cur.fetchall()
    owns: Dict[Any, str] = {}
    sites = byline.site_owners(cur)   # a maker's page an aggregator carried is the maker's, via the aggregator
    return {pid: {"id": pid, "title": title or "", "source_id": sid, "source": name or "", "kind": source_kind(platform, handle),
                  "at": at, "url": url, "byline": byline.of_row(name, platform, handle, author, fwd, quoted, owns=owns,
                                                                 url=url, sites=sites)}
            for pid, title, sid, name, at, url, platform, handle, author, fwd, quoted in rows}


def launch_order(facts: Dict[str, Dict[str, Any]], weight: Optional[Dict[str, int]] = None) -> List[str]:
    """The stories a row's headline is taken from, in order (a release is named by its launch, never by a leak): those
    holding the maker's own post, then the others of a news type; leak stories never. In each: a release type first,
    then most of the row's voices (`weight`), then the newest. `facts`: {story: {maker, type, at}}. Pure."""
    from insight_core.markx import event_types
    floor = datetime.min.replace(tzinfo=timezone.utc)
    weight = weight or {}

    def ordered(sids: Iterable[str]) -> List[str]:
        return sorted(sids, key=lambda s: (facts[s].get("type") in event_types.RELEASES, weight.get(s, 0),
                                           facts[s].get("at") or floor, s), reverse=True)
    makers = [s for s, f in facts.items() if f.get("maker") and f.get("type") != event_types.LEAK]
    news_ = [s for s, f in facts.items() if s not in makers and f.get("type") in event_types.NEWS_TYPES]
    return ordered(makers) + ordered(news_)


def story_voices(row: Dict[str, Any]) -> Dict[str, int]:
    """{Mark X story: how many voices its posts are in the row} (main_story's count)."""
    seen: Dict[str, Set[str]] = defaultdict(set)
    for p in row.get("posts") or []:
        if p.get("story"):
            seen[str(p["story"])].add(p.get("voice") or p.get("post_id"))
    return {s: len(v) for s, v in seen.items()}


def _story_facts(cur: Any, story_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    """{story: {maker (its original is the maker's own post), post, type (event type), at (release)}} (built.build)."""
    from insight_core.markx import built
    got = built.build(cur, sorted(set(story_ids)))
    out = {}
    for sid, b in got.items():
        o = b.get("original") or {}
        out[sid] = {"maker": o.get("how") == "maker", "post": o.get("post") if o.get("how") == "maker" else None,
                    "type": b.get("event_type"), "at": b.get("release_at")}
    return out


def _row_stories(row: Dict[str, Any]) -> List[str]:
    return sorted({str(p["story"]) for p in row.get("posts") or [] if p.get("story")})


def headlines(cur: Any, rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Each row's headline: its main story's Haiku headline, else the row's own headline answer, else its lead's
    title. A one-release row is named by its launch (`launch_order`); a leak lead's title, in a row holding the
    maker's own post, gives way to that post's title."""
    from insight_core.markx import event_types, graph, repo, schemas
    mains = {str(r["id"]): main_story(r) for r in rows}
    groups = graph.release_groups(cur, {s for r in rows for s in _row_stories(r)})
    in_group = {s: n for n, g in enumerate(groups) for s in g}
    released = {str(r["id"]): ss for r in rows
                if len(ss := [s for s in _row_stories(r) if s in in_group]) >= 2
                and len({in_group[s] for s in ss}) < len(ss)}
    leads = _posts(cur, [str(r["id"]) for r in rows])
    facts = _story_facts(cur, {s for ss in released.values() for s in ss}) if released else {}
    sids = sorted({s for s in mains.values() if s} | set(facts))
    heads: Dict[str, str] = {}
    if sids:
        cur.execute("SELECT id::text, headline FROM mx_stories WHERE id = ANY(%s::uuid[]) AND headline IS NOT NULL", (sids,))
        heads = dict(cur.fetchall())
    by_id = {str(r["id"]): r for r in rows}
    for rid, ss in released.items():
        named = [s for s in launch_order({s: facts[s] for s in ss if s in facts}, story_voices(by_id[rid]))
                 if heads.get(s)]
        if named:
            mains[rid] = named[0]
    rest = [r for r in rows if not heads.get(mains[str(r["id"])] or "")]
    own: Dict[str, str] = {}
    if rest:
        posts = _row_posts(cur, rest)
        guide = schemas.KINDS["headline"].guide
        texts = {str(r["id"]): row_headline_input(r, posts) for r in rest}
        tasks_ = repo.tasks_for(cur, kind="headline", guide=guide, inputs={t for t in texts.values() if t})
        calls = repo.valid_calls(cur, [t["id"] for t in tasks_.values() if t["status"] == "answered"])
        for r in rest:
            text = texts[str(r["id"])]
            task = tasks_.get(text) if text else None
            call = calls.get(str(task["id"])) if task and task["status"] == "answered" else None
            words = ((call or {}).get("answer") or {}).get("headline_en") or ""
            if words.strip():
                own[str(r["id"])] = words.strip()
    untitled = [r for r in rows if not heads.get(mains[str(r["id"])] or "") and not own.get(str(r["id"]))]
    makers: Dict[str, str] = {}   # an untitled row led by a leak: the maker's own post in it, if any
    if untitled:
        types = event_types.types_of(cur, [str(r["id"]) for r in untitled])
        leaked = [r for r in untitled if types.get(str(r["id"]), (None, None))[0] == event_types.LEAK]
        more = _story_facts(cur, {s for r in leaked for s in _row_stories(r)} - set(facts)) if leaked else {}
        facts.update(more)
        for r in leaked:
            ids = {p["post_id"] for p in r["posts"]}
            mine = {s: facts[s] for s in _row_stories(r) if s in facts}
            order = launch_order(mine, story_voices(r))
            got = [facts[s]["post"] for s in order + sorted(set(mine) - set(order)) if facts[s].get("post") in ids]
            if got:
                makers[str(r["id"])] = got[0]
    titles = _posts(cur, sorted(set(makers.values()) - set(leads))) if makers else {}
    titles.update(leads)
    out = {}
    for r in rows:
        rid = str(r["id"])
        if heads.get(mains[rid] or ""):
            out[rid] = {"text": heads[mains[rid]], "from": "haiku"}
        elif own.get(rid):
            out[rid] = {"text": own[rid], "from": "haiku"}
        elif (titles.get(makers.get(rid) or "") or {}).get("title"):
            out[rid] = {"text": titles[makers[rid]]["title"], "from": "maker title"}
        else:
            out[rid] = {"text": (leads.get(rid) or {}).get("title") or "", "from": "lead title"}
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


def rank_key(row: Dict[str, Any], now: datetime) -> Tuple[Any, ...]:
    """News' order by coverage: the last 48 hours first, then the highest score, the newest, the id."""
    return (row["first_at"] < now - timedelta(hours=48), -float(row["score"]), -row["first_at"].timestamp(),
            str(row["id"]))


def ranked_key(row: Dict[str, Any], rank: Optional[Dict[str, Any]], now: datetime) -> Tuple[Any, ...]:
    """News ranked for the reader: the Notable lane first, then the last 48 hours, each by its kept rank score (an
    unranked row by its coverage), then `rank_key`'s order."""
    from insight_core.markx import news_rank
    score = rank["score"] if rank else news_rank.combine(None, news_rank.coverage(row["score"]))
    return (not (rank or {}).get("notable"), row["first_at"] < now - timedelta(hours=48), -float(score),
            *rank_key(row, now)[1:])


def page(cur: Any, *, only_differences: bool = True, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The Mark X News beside Mark IX's: the newest written run's rows (only the differences, by default), each with its
    tag, headline, members (why each is there and what Mark IX did with it) and the Mark IX posts it left out; and the
    Mark IX rows no Mark X row holds."""
    from insight_core.markx import repo
    from insight_core.utils.news_rules import NEWS_DAYS
    now = now or datetime.now(timezone.utc)
    run = last_written(cur)
    if run is None:
        return {"run": None, "items": [], "gone": [], "counts": {}, "ix_rows": 0, "sections": None}
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
    mention_of: Dict[str, Dict[str, Any]] = {}   # a post's first non-member membership
    for (_s, q), w in why.items():
        if w["role"] != "member":
            mention_of.setdefault(q, w)
    heads = headlines(cur, shown)
    ix_titles = {nid: (posts.get(nid) or {}).get("title") for nid in ix_rows}
    from insight_core.markx import labels
    flagged = labels.flags(cur, {(p["post_id"], p.get("story")) for r in shown for p in r["posts"] if p.get("story")})
    from insight_core.markx import entity_views
    surging = entity_views.surging_posts(cur, {p["post_id"] for r in shown for p in r["posts"]})

    def line(pid: str, story: Optional[str], row_ids: Set[str]) -> Dict[str, Any]:
        p = posts.get(pid) or {"id": pid}
        w = why.get((story, pid)) if story else None
        nid = ix_of.get(pid)
        ix = ({"row": nid, "title": ix_titles.get(nid), "same_row": nid in row_ids} if nid else None)
        return {**{k: p.get(k) for k in ("id", "title", "source", "kind", "at", "url", "byline")}, "why": w, "ix": ix}

    items = []
    for r in shown:
        mine = [p["post_id"] for p in r["posts"]]
        ix_hit = sorted({ix_of[p] for p in mine if p in ix_of})
        lines = [dict(line(p["post_id"], p.get("story"), set(ix_hit)), role=p["role"], name=p.get("name"),
                      story=p.get("story"), flag=flagged.get((p["post_id"], p.get("story")))) for p in r["posts"]]
        removed = []
        for nid in ix_hit:
            for pid in sorted(ix_rows.get(nid, ()), key=lambda q: str((posts.get(q) or {}).get("at") or "")):
                if pid in mine:
                    continue
                p = posts.get(pid) or {"id": pid}
                removed.append({**{k: p.get(k) for k in ("id", "title", "source", "kind", "at", "url", "byline")},
                                "check": checks.get(pid), "now_in": x_of.get(pid),
                                "mention": mention_of.get(pid)})
        items.append({"id": str(r["id"]), "tag": r["tag"], "headline": heads[str(r["id"])], "first_at": r["first_at"],
                      "voices": r["voices"], "reports": r["reports"], "shares": r["shares"], "mentions": r["mentions"],
                      "score": float(r["score"]), "story": (r["posts"] or [{}])[0].get("story"), "posts": lines,
                      "removed": removed,
                      "surging": list({s["id"]: s for p in mine for s in surging.get(p, [])}.values()),
                      "ix": [{"id": nid, "title": ix_titles.get(nid), **(ix_meta.get(nid) or {})} for nid in ix_hit]})
    from insight_core.markx import news_rank
    ranks = news_rank.read(cur, [i["id"] for i in items])
    order = news_rank.mode(cur)
    for i in items:
        i["rank"] = ranks.get(i["id"])
    items.sort(key=lambda i: ranked_key(i, i["rank"], now) if order != "coverage" else rank_key(i, now))
    from insight_core.markx import folds   # each line's fold, the header's count
    fold_count = folds.annotate(cur, items)
    from insight_core.markx import built   # how each row's story is built, its original first
    built.annotate(cur, items)
    from insight_core.markx import graph   # each row's Earlier and Later
    thread = graph.row_chains(cur, {i["id"]: _row_stories(i) for i in items})
    for i in items:
        i["chain"] = thread.get(i["id"])
    gone = []
    for nid in sorted(gone_rows, key=lambda n: -(ix_meta.get(n) or {}).get("voices", 0)):
        gone.append({"id": nid, "title": ix_titles.get(nid), **(ix_meta.get(nid) or {}),
                     "posts": [{**{k: (posts.get(p) or {}).get(k) for k in ("id", "title", "source", "kind", "at", "byline")},
                                "check": checks.get(p),
                                "mention": mention_of.get(p)}
                               for p in sorted(ix_rows[nid])]})
    cur.execute("SELECT started_at, finished_at, code_version, counts FROM mx_runs WHERE id = %s", (run,))
    started, finished, code, run_counts = cur.fetchone()
    from insight_core.markx import news_sections
    untitled = sum(1 for i in items if i["headline"]["from"] != "haiku")
    return {"run": {"id": run, "started_at": started, "finished_at": finished, "code_version": code},
            "counts": {**counts, "rows": len(rows), "ix_rows": len(ix_rows), "gone": len(gone), "untitled": untitled},
            "items": items, "gone": gone, "folds": fold_count, "sections": news_sections.view(cur, items),
            "order": order, "notable": [i["id"] for i in items if (i["rank"] or {}).get("notable")]}


# ---- the kept page (issue 0198) ------------------------------------------------------------------------------

VIEWS = {"differences": True, "all": False}   # the kept views: key -> only_differences
SHAPE = "3"   # the answer's shape, in the kept keys: bump it when a field the frontend reads changes
KEEP_RUNS = 3                                 # the newest runs whose kept views stay (a cache: pruned)
RECENT = timedelta(hours=48)                   # rank_key's "last 48 hours first"


def page_inputs(cur: Any, now: datetime) -> Tuple[Optional[str], Optional[str]]:
    """(the newest decision run's id, the stamp of what `page` reads at `now`), or (None, None) before any run; a few
    indexed reads. The stamp covers the newest run, the counts of the written run's rows in the window and its last
    48 hours (rows are fixed and both bounds only move forward), Mark IX's News of the window (hashed), the newest
    sectioning, the answered headline questions, the rank's inputs and the owner's marks. Other worker answers reach
    the page through the next decision run."""
    from insight_core.markx import kept_pages, repo
    from insight_core.utils.news_rules import NEWS_DAYS
    last = repo.last_run(cur)
    if last is None:
        return None, None
    written = last_written(cur)
    since = now - timedelta(days=NEWS_DAYS)
    cur.execute("""SELECT count(*) FILTER (WHERE first_at >= %s), count(*) FILTER (WHERE first_at >= %s)
                     FROM mx_news WHERE run_id = %s""", (since, now - RECENT, written))
    rows = list(cur.fetchone())
    cur.execute("""SELECT (SELECT md5(string_agg(id::text || ':' || voices || ':' || extract(epoch FROM first_at),
                                                 ',' ORDER BY id))
                             FROM news_stories WHERE first_at >= %(since)s),
                          (SELECT md5(string_agg(np.post_id::text || ':' || np.news_id::text, ',' ORDER BY np.post_id))
                             FROM news_posts np JOIN news_stories ns ON ns.id = np.news_id
                            WHERE ns.first_at >= %(since)s)""", {"since": since})
    ix = list(cur.fetchone())
    cur.execute("""SELECT s.call_id::text, s.at,
                          (SELECT json_build_array(count(*), max(p.at)) FROM mx_news_placements p
                            WHERE p.base_call = s.call_id)
                     FROM mx_news_sections s ORDER BY s.at DESC, s.call_id DESC LIMIT 1""")
    sections = list(cur.fetchone() or ())
    cur.execute("""SELECT EXISTS (SELECT 1 FROM mx_news_section_asks a JOIN mx_tasks t ON t.id = a.task_id
                                   WHERE t.status IN ('open', 'leased'))""")
    sections.append(bool(cur.fetchone()[0]))
    cur.execute("SELECT count(*), max(answered_at) FROM mx_tasks WHERE kind = 'headline' AND status = 'answered'")
    heads = list(cur.fetchone())
    from insight_core.markx import news_rank
    ranked = news_rank.stamp(cur, now) + [news_rank.mode(cur), news_rank.analysis_mode(cur)]
    return str(last["id"]), kept_pages.stamp("news", written, rows, ix, sections, heads, kept_pages.owner_marks(cur),
                                             ranked)


def _key(view: str) -> str:
    """A view's kept key, with the answer's SHAPE."""
    from insight_core.markx import kept_pages
    return kept_pages.shaped(view, SHAPE)


def _view_key(only_differences: bool) -> str:
    return _key("differences" if only_differences else "all")


def kept_page(cur: Any, *, only_differences: bool = True, now: Optional[datetime] = None) -> Optional[bytes]:
    """The page's kept answer: the bytes `page` would answer now (kept by any code, same inputs), else the newest view
    kept (the jobs process builds the next one; News is never built in a request); None only when no view of this
    shape was ever kept: the caller builds the page then."""
    from insight_core.markx import kept_pages
    key = _view_key(only_differences)
    run, st = page_inputs(cur, now or datetime.now(timezone.utc))
    got = kept_pages.get(cur, "news", key, run, st, any_code=True)
    if got is not None:
        return got
    newest = kept_pages.newest(cur, "news", key)
    return newest[0] if newest else None


def kept_missing(cur: Any, now: Optional[datetime] = None) -> bool:
    """Whether a view has no kept answer for its inputs now, by this code (the jobs process builds them then)."""
    from insight_core.markx import kept_pages
    run, st = page_inputs(cur, now or datetime.now(timezone.utc))
    return any(not kept_pages.has(cur, "news", _key(view), run, st) for view in VIEWS)


# what the News page's frontend doesn't read of `page`, left out of the answer the route sends (0215)
_ITEM_DROPPED = ("reports", "score")
_RANK_KEPT = ("notable", "significance", "fit", "why")
_RANK_WHY_KEPT = ("why", "effect", "analysis")
_BUILT_DROPPED = ("code", "read", "original", "source_page", "release_at", "leaks")
_LINE_DROPPED = ("url", "kind", "role")


def _line(p: Dict[str, Any]) -> Dict[str, Any]:
    """A line of a row (or a removed or gone post) as the page reads it."""
    out = {k: v for k, v in p.items() if k not in _LINE_DROPPED}
    if isinstance(out.get("ix"), dict):
        out["ix"] = {k: v for k, v in out["ix"].items() if k != "row"}
    if isinstance(out.get("fold"), dict):
        out["fold"] = {k: v for k, v in out["fold"].items() if k not in ("rule", "by", "count")}
    if isinstance(out.get("built"), dict):
        out["built"] = {k: v for k, v in out["built"].items() if k != "joins"}
    if isinstance(out.get("mention"), dict):
        out["mention"] = {"role": out["mention"].get("role")}
    return out


def reader_view(view: Dict[str, Any]) -> Dict[str, Any]:
    """`page` as GET /api/markx/news sends it: without what no page reads."""
    items = []
    for item in view.get("items") or []:
        item = {k: v for k, v in item.items() if k not in _ITEM_DROPPED}
        item["posts"] = [_line(p) for p in item.get("posts") or []]
        item["removed"] = [_line(p) for p in item.get("removed") or []]
        if isinstance(item.get("surging"), list):
            item["surging"] = [{"name": s.get("name")} if isinstance(s, dict) else s for s in item["surging"]]
        if isinstance(item.get("ix"), list):
            item["ix"] = [{"title": r.get("title")} if isinstance(r, dict) else r for r in item["ix"]]
        rank = item.get("rank")
        if isinstance(rank, dict):
            item["rank"] = {k: v for k, v in rank.items() if k in _RANK_KEPT}
            if isinstance(rank.get("why"), dict):
                item["rank"]["why"] = {k: v for k, v in rank["why"].items() if k in _RANK_WHY_KEPT}
        built = item.get("built")
        if isinstance(built, dict):
            built = {k: v for k, v in built.items() if k not in _BUILT_DROPPED}
            for key in ("came_true", "leaked_before"):
                if isinstance(built.get(key), list):
                    built[key] = [{k: v for k, v in e.items() if k not in ("via", "posts")} if isinstance(e, dict)
                                  else e for e in built[key]]
            item["built"] = built
        items.append(item)
    gone = [{**g, "posts": [_line(p) for p in g.get("posts") or []]} if isinstance(g, dict) else g
            for g in view.get("gone") or []]
    return {**view, "items": items, "gone": gone}


def keep_pages(cur: Any, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """In the jobs process, in one snapshot: each view not kept for its inputs built and kept as the bytes the route
    answers; the views of all but the newest KEEP_RUNS runs pruned."""
    import time
    from insight_core.markx import kept_pages
    now = now or datetime.now(timezone.utc)
    run, st = page_inputs(cur, now)
    if run is None:
        return {"run": None, "built": []}
    out: Dict[str, Any] = {"run": run, "built": [], "bytes": {}, "build_seconds": {}}
    ranked = False
    for view, only in VIEWS.items():
        key = _key(view)
        if kept_pages.has(cur, "news", key, run, st):
            continue
        if not ranked:   # ranks are page inputs: kept before the first view is built
            from insight_core.markx import news_rank
            t0 = time.monotonic()
            out["rank"] = {**news_rank.keep(cur, now=now), "seconds": round(time.monotonic() - t0, 2)}
            ranked = True
        t0 = time.monotonic()
        body = kept_pages.encode(reader_view(page(cur, only_differences=only, now=now)))
        seconds = round(time.monotonic() - t0, 2)
        kept_pages.put(cur, "news", key, run, st, body, seconds=seconds)
        out["built"].append(view)
        out["bytes"][view], out["build_seconds"][view] = len(body), seconds
    out["pruned"] = kept_pages.prune_runs(cur, "news", KEEP_RUNS)
    return out


def post_panel(cur: Any, post_id: str) -> Dict[str, Any]:
    """The post page's Mark X panel: its reading, its entities and their roles, its Mark X stories (role, reason, the
    judge's words) and connections, each with its reason."""
    from insight_core.markx import repo
    from insight_core.markx import reading5
    rank = reading5.rank_sql("guide")
    cur.execute(f"SELECT guide, kind, events, lang, headline, reading FROM mx_readings WHERE post_id = %s "
                f"AND {rank} IS NOT NULL ORDER BY {rank}", (post_id,))
    r = cur.fetchone()
    reading = None if r is None else {"guide": r[0], "kind": r[1], "events": r[2], "lang": r[3], "headline": r[4],
                                      "main": (r[5] or {}).get("main"), "mentions": (r[5] or {}).get("mentions") or []}
    from insight_core.markx import entity_views
    linked = entity_views.post_entities(cur, post_id)
    from insight_core.markx import schemas
    current = repo.current_guide(cur, post_id)   # the newest valid entities answer's guide
    from insight_core.markx import ent42   # q2 marks, new entities, the owner's labels
    mine = ent42.labels_of(cur, post_id)
    entities = [{**{k: m[k] for k in ("name", "maker", "family", "version", "variant", "span")},
                 "type": schemas.entity_type(m["type"]), "role": m["role"] or "mention", "rule": m.get("rule"),
                 "by": m.get("by_name"), "guide": m["guide"], "entity_id": linked.get(m["n"]),
                 "n": m["n"], "q2": m.get("rule") == ent42.Q2, "new": ent42.is_new(m),
                 "label": mine.get(f"{m['guide']}:{m['n']}")}
                for m in repo.mentions(cur, post_id) if m["guide"] == current]
    documents = [e for e in entities if e["type"] == "document" and e["role"] not in ("source", "recommended")]
    cited = {r: [e for e in entities if e["role"] == r] for r in ("source", "recommended")}
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
            if c["rule"] == "chain_stops":   # a story's chain is shown on its story page
                continue
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
            "read": reading is not None,
            "entities_guide": current, "documents": documents, "sources": cited["source"],
            "recommended": cited["recommended"]}


# related reading: the posts nearest a post by its stored vector, computed on request (a full scan, so a click of its
# own, never part of the post panel). Left out: the post, its stories' members, a source's post within a day of one
# already listed, a repeated title, and a source's posts past RELATED_PER_SOURCE.
RELATED_N = 10
RELATED_MIN = 0.62          # measured on the server copy's seeds (v10.36)
RELATED_SCAN = 1000         # the nearest rows read before the rules above thin them (one source can fill 200)
RELATED_PER_SOURCE = 2
RELATED_GUIDE_TYPES = ("tutorial_explainer",)   # what a reading calls a guide or explainer
# under RELATED_LOOSE items at the floor, the nearest under it fill the list up to RELATED_LOOSE, marked `loose`
RELATED_LOOSE = 3
# what a short report is about: the stored page of its subject document or, for a post of at most RELATED_ABOUT_WORDS
# words, a stored page it links, nearest the post at RELATED_ABOUT_MIN or more; the list is then seeded by the two
# vectors' mean and the page listed first, marked `about` (a short report's own vector is of the news, not the subject)
RELATED_ABOUT_WORDS = 200
RELATED_ABOUT_MIN = 0.55


def title_key(title: Optional[str]) -> str:
    """A title as its words (letters and digits, lower case), a leading bracketed tag ("[Project]") left out: two
    titles that differ only in case, punctuation or spacing are one."""
    import re
    t = re.sub(r"^\s*(?:\[[^\]]{0,40}\]\s*)+", "", title or "")
    return " ".join(re.findall(r"[^\W_]+", t.lower()))[:120]


def related_about(cur: Any, post_id: str, *, floor: float = RELATED_ABOUT_MIN) -> Optional[Tuple[str, float]]:
    """(the stored page the post is about, its cosine to the post) or None, by RELATED_ABOUT_WORDS's rule (no model
    call)."""
    from insight_core.markx import embed
    cur.execute("""WITH short AS (SELECT COALESCE((SELECT pp.words FROM post_parts pp WHERE pp.post_id = %(p)s), 0)
                                         <= %(words)s AS yes),
                        cand AS (
                        SELECT o.post_id FROM mx_mentions_now m
                          JOIN story_originals o ON o.kind = 'work' AND o.entity_id = m.entity_id AND o.post_id IS NOT NULL
                         WHERE m.post_id = %(p)s AND m.role = 'subject' AND m.type = 'document'
                        UNION
                        SELECT o.post_id FROM story_originals o, short
                         WHERE short.yes AND o.from_post_id = %(p)s AND o.kind IN ('linked', 'reference')
                           AND o.post_id IS NOT NULL
                        UNION
                        SELECT q.id FROM short, (SELECT l.target_url AS u FROM post_links l
                                                  WHERE l.post_id = %(p)s AND NOT l.boilerplate
                                                    AND l.kind IN ('link', 'reference')
                                                 UNION SELECT pp.link_target FROM post_parts pp
                                                  WHERE pp.post_id = %(p)s AND pp.link_target IS NOT NULL) k
                          JOIN posts q ON q.normalized_url = k.u
                         WHERE short.yes)
                   SELECT c.post_id::text, 1 - (e.v <=> s.v) AS cos FROM cand c
                     JOIN mx_embeddings e ON e.post_id = c.post_id AND e.model = %(m)s
                     JOIN mx_embeddings s ON s.post_id = %(p)s AND s.model = %(m)s
                    WHERE c.post_id <> %(p)s ORDER BY cos DESC, c.post_id LIMIT 1""",
                {"p": post_id, "m": embed.MODEL, "words": RELATED_ABOUT_WORDS})
    row = cur.fetchone()
    return (row[0], float(row[1])) if row is not None and row[1] >= floor else None


def related(cur: Any, post_id: str, *, n: int = RELATED_N, floor: float = RELATED_MIN,
            about: bool = True) -> Dict[str, Any]:
    """{post_id, vector, about, items: [_posts' line + cosine, guide, about, loose]}: the page the post is about first
    (`about` False: never), then the nearest to the seed; `guide` when the reading types it a tutorial or explainer;
    `loose` under the floor."""
    from insight_core.markx import embed, event_types
    date = pairing.published_date("p")
    cur.execute(f"""SELECT p.source_id::text, {date}, COALESCE(pp.title, p.title) FROM mx_embeddings e
                      JOIN posts p ON p.id = e.post_id LEFT JOIN post_parts pp ON pp.post_id = p.id
                     WHERE e.post_id = %s AND e.model = %s""", (post_id, embed.MODEL))
    seed = cur.fetchone()
    if seed is None:
        return {"post_id": post_id, "vector": False, "about": None, "items": []}
    page = related_about(cur, post_id) if about else None
    other = page[0] if page else post_id
    # the seed: the post's vector, or with the page it is about the two's mean (their sum: a cosine is scale-free)
    cur.execute(f"""WITH s AS MATERIALIZED (
                        SELECT (SELECT v FROM mx_embeddings WHERE post_id = %(p)s AND model = %(m)s)
                             + (SELECT v FROM mx_embeddings WHERE post_id = %(a)s AND model = %(m)s) AS v),
                         near AS MATERIALIZED (
                        SELECT e.post_id, 1 - (e.v <=> s.v) AS cos FROM mx_embeddings e, s
                         WHERE e.model = %(m)s AND e.post_id <> %(p)s AND e.post_id <> %(a)s
                         ORDER BY e.v <=> s.v LIMIT %(scan)s)
                    SELECT near.post_id::text, near.cos, p.source_id::text, {date}, COALESCE(pp.title, p.title)
                      FROM near JOIN posts p ON p.id = near.post_id LEFT JOIN post_parts pp ON pp.post_id = p.id
                     WHERE NOT EXISTS (SELECT 1 FROM mx_story_posts a JOIN mx_story_posts b ON b.story_id = a.story_id
                                        WHERE a.post_id = %(p)s AND a.valid_to IS NULL
                                          AND b.post_id = near.post_id AND b.valid_to IS NULL)
                     ORDER BY near.cos DESC, near.post_id""",
                {"p": post_id, "a": other, "m": embed.MODEL, "scan": RELATED_SCAN})
    rows = cur.fetchall()
    seed_source, seed_at, seed_title = seed
    titles = {title_key(seed_title)} - {""}
    if page:
        cur.execute("SELECT COALESCE(pp.title, p.title) FROM posts p LEFT JOIN post_parts pp ON pp.post_id = p.id"
                    " WHERE p.id = %s", (other,))
        titles |= {title_key((cur.fetchone() or [None])[0])} - {""}
    day = timedelta(days=1)
    times: Dict[str, List[Any]] = defaultdict(list)    # each source's listed posts' times (the seed's with them)
    times[seed_source].append(seed_at)
    listed: Counter = Counter()
    kept: List[Tuple[str, float]] = [page] if page else []
    for pid, cos, sid, at, title in rows:
        if cos < floor and len(kept) >= RELATED_LOOSE:   # the nearest first: all after are under the floor too
            break
        if listed[sid] >= RELATED_PER_SOURCE:
            continue
        if at is not None and any(t is not None and abs(at - t) < day for t in times[sid]):
            continue
        key = title_key(title)
        if key and key in titles:
            continue
        titles.add(key)
        times[sid].append(at)
        listed[sid] += 1
        kept.append((pid, float(cos)))
        if len(kept) >= n:
            break
    ids = [pid for pid, _ in kept]
    lines = _posts(cur, ids)
    typed = event_types.of_posts(cur, ids)
    # a reading with no closed type: its kind as the closed type it reads as
    kinds = [k for k, t in event_types.KIND_TYPES.items() if t in RELATED_GUIDE_TYPES]
    cur.execute("SELECT DISTINCT post_id::text FROM mx_readings WHERE post_id = ANY(%s::uuid[]) AND kind = ANY(%s)",
                (ids, kinds))
    by_kind = {r[0] for r in cur.fetchall()}
    items = []
    for pid, cos in kept:
        if pid in lines:
            t = typed[pid].type if pid in typed else None
            is_page = page is not None and pid == other
            items.append({**lines[pid], "cosine": round(cos, 3), "about": is_page, "loose": cos < floor and not is_page,
                          "guide": t in RELATED_GUIDE_TYPES if t else pid in by_kind})
    return {"post_id": post_id, "vector": True, "about": other if page else None, "items": items}


def entities(cur: Any, *, now: Optional[datetime] = None, limit: int = 30) -> Dict[str, Any]:
    """Today's and this week's main-subject entities, each with its posts and voices."""
    now = now or datetime.now(timezone.utc)
    out = {}
    for name, days in (("today", 1), ("week", 7)):
        cur.execute(f"""SELECT m.name_key, lower(COALESCE(m.version, '')), (array_agg(m.name ORDER BY m.name))[1],
                              (array_agg(m.type))[1], count(DISTINCT m.post_id), {voice.count_sql("p.source_id", "s.platform")},
                              (array_agg(DISTINCT m.post_id::text))[1:5], (array_agg(m.version ORDER BY m.version))[1]
                         FROM mx_mentions_now m JOIN posts p ON p.id = m.post_id JOIN sources s ON s.id = p.source_id
                        WHERE m.role = 'subject'
                          AND {pairing.post_date_within('p', '%(since)s')}
                        GROUP BY 1, 2 ORDER BY {voice.count_sql("p.source_id", "s.platform")} DESC,
                                 count(DISTINCT m.post_id) DESC, 1
                        LIMIT %(limit)s""",
                    {"since": now - timedelta(days=days), "limit": limit})
        rows = cur.fetchall()
        posts = _posts(cur, {p for r in rows for p in (r[6] or [])})
        out[name] = [{"key": k, "version": shown or v or None, "name": n, "type": t, "posts": np_, "voices": nv,
                      "examples": [{k2: (posts.get(p) or {}).get(k2) for k2 in ("id", "title", "source", "byline")} for p in (ps or [])]}
                     for k, v, n, t, np_, nv, ps, shown in rows]
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


WORKER_STALE_DAYS = 3     # a worker silent this long shows as stale


def workers_view(contacts: Dict[str, datetime], now: datetime,
                 leased: Optional[Dict[str, int]] = None) -> List[Dict[str, Any]]:
    """Each worker that called or holds leases: {worker, last_contact, leased, stale}."""
    leased = leased or {}
    limit = timedelta(days=WORKER_STALE_DAYS)
    return [{"worker": w, "last_contact": contacts.get(w), "leased": leased.get(w, 0),
             "stale": contacts.get(w) is None or now - contacts[w] > limit}
            for w in sorted(set(contacts) | set(leased))]


def worker(cur: Any, contacts: Dict[str, datetime]) -> Dict[str, Any]:
    """The worker's side: the queue by kind, answers per day, tokens and their API cost, failures, last contacts, the
    last decision run."""
    from insight_core.markx import repo
    queue = repo.queue_counts(cur)
    cur.execute("""SELECT created_at::date, count(*), count(*) FILTER (WHERE valid), COALESCE(sum(tokens_in), 0),
                          COALESCE(sum(tokens_out), 0) FROM mx_calls WHERE created_at >= COALESCE(%s, '-infinity'::timestamptz)
                    GROUP BY 1 ORDER BY 1 DESC LIMIT 14""", (repo.calls_days_floor(cur, 14),))
    days = [{"day": d, "calls": n, "valid": v, "tokens_in": int(ti), "tokens_out": int(to),
             "api_usd": round(int(ti) * HAIKU_PER_MILLION[0] / 1e6 + int(to) * HAIKU_PER_MILLION[1] / 1e6, 4)}
            for d, n, v, ti, to in cur.fetchall()]
    from insight_core.markx import kept_counts
    n, ti, to, cost = kept_counts.call_totals(cur)   # kept, not summed per request
    cur.execute("""SELECT kind, last_error, count(*) FROM mx_tasks WHERE status = 'failed'
                    GROUP BY 1, 2 ORDER BY 3 DESC, 1 LIMIT 20""")
    failed = [{"kind": k, "error": e, "tasks": c} for k, e, c in cur.fetchall()]
    cur.execute("""SELECT t.kind, c.error, c.created_at FROM mx_calls c JOIN mx_tasks t ON t.id = c.task_id
                    WHERE NOT c.valid AND t.status <> 'failed' ORDER BY c.created_at DESC LIMIT 10""")
    invalid = [{"kind": k, "error": e, "at": at} for k, e, at in cur.fetchall()]
    cur.execute("SELECT leased_by, count(*), max(lease_until) FROM mx_tasks WHERE status = 'leased' GROUP BY 1")
    leased = {w: (k, until) for w, k, until in cur.fetchall()}
    workers = workers_view(contacts, datetime.now(timezone.utc), leased={w: k for w, (k, _) in leased.items()})
    run = repo.last_run(cur)
    return {"queue": queue, "days": days,
            "tokens": {"calls": n, "tokens_in": int(ti), "tokens_out": int(to), "paid_usd": round(float(cost), 4),
                       "api_usd": round(int(ti) * HAIKU_PER_MILLION[0] / 1e6 + int(to) * HAIKU_PER_MILLION[1] / 1e6, 4)},
            "failed": failed, "invalid": invalid, "workers": workers,
            "last_run": None if run is None else {"id": str(run["id"]), "started_at": run["started_at"],
                                                  "finished_at": run["finished_at"], "code_version": run["code_version"],
                                                  "counts": run["counts"]}}
