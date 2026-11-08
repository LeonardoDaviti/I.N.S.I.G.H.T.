"""0132 B (Stealth v10.6): the source analysis page's numbers, computed by one stats job and stored in source_stats.

    rows = compute(load(cur, now))         # every card's signal, per source and per voice
    write(cur, rows, now)                  # one row per subject and signal (migration 0081)
    list_view(cur), subject_view(cur, id)  # what /markx/sources and /markx/sources/<id> show: rows only

**No single score** (the owner's decision 5): each signal is its own number with its formula, its n and its evidence,
and the list sorts by any column. A composite ranked English sites first and Russian Telegram channels last, because
nobody links t.me posts (the lab's report, 2026-11-08).

**Subjects.** Every source (but saved pages) has its rows; a voice (0132 A's `voices`, `sources.voice_id`) has rows
over all its channels' posts, once that table exists (until then: per source only). Who "another voice" is: a
source's voice when it has one, else the source itself, so a voice's own channels never count as each other's
citers, followers or co-reporters.

**Windows.** Posts, shares, links and News: the last WINDOW_DAYS (90) days. First to report and story roots: every
stored story (they need 10 stories). Reading kinds and the role: every read post (Mark X reads few; Part C1 reads more).

**The signals** (SIGNALS: card, formula, the threshold below which the page says "too few to tell", and what n counts)
are the lab's (plan/research/lab/markx/proto/sv1_signals.py, sv1_table.py), measured for stability between periods
(Spearman 0.56-0.92). The role rule is markx/source_role.py.

**The job** (`Runner`, started by insight-ingestion's scheduler only while Mark X is on): nightly (between 02:00 and
06:00 UTC, once a day; and at most 36 hours apart) and after a regroup (Mark IX's story job finished a full run or a
rule change's rebuild since the last stats run), never while Mark IX's story job holds its lock or rebuilds. Each run
in a child process of its own (its memory goes back to the OS), HARD_LIMIT seconds at most; its time, rows and peak
memory are kept in mx_settings `source_stats_job`.

Only source_stats (and the job's state in mx_settings) is written; every other table is read.
"""
from __future__ import annotations

import json
import logging
import multiprocessing
import re
import statistics
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from insight_core.markx import source_role as R

log = logging.getLogger(__name__)

WINDOW_DAYS = 90
NEW_SOURCE_DAYS = 30
EVIDENCE = 10                 # evidence items kept per signal
COPY_JACCARD = 0.5            # near-identical posts: 5-word shingles
COPY_MIN_WORDS = 15
COPY_SAMPLE = 4               # one shingle in 4 is indexed (the estimate's error is small at 15+ words)
COPY_MAX_POSTS = 40           # a shingle in more posts than this is boilerplate
LINK_POST_CHARS = 400
MEDIA_ONLY_TEXT, MEDIA_ONLY_TITLE = 40, 15
STANCE_MIN_CHARS = 250
STANCE_POSTS = 15
PLATFORM_YEARS = {"x": 2006, "youtube": 2005, "telegram": 2013, "reddit": 2005, "hn": 2007, "site": 1991}
ACCOUNT_SITES = frozenset({"x.com", "twitter.com", "t.me", "telegram.me", "youtube.com", "reddit.com", "github.com",
                           "medium.com"})
NOT_SUBJECTS = ("saved",)
JOB_KEY = "source_stats_job"

CITED_BIAS = ("Only your own sources count, and nobody links Telegram posts: a channel others don't link scores 0 "
              "whatever its standing.")


@dataclass(frozen=True)
class Signal:
    card: str
    formula: str
    min: int = 0              # "too few to tell" below this n (0: always shown)
    counts: str = "posts"     # what n counts


SIGNALS: Dict[str, Signal] = {
    "channels": Signal("channels", "its channels, and the same channel added twice", 0, "channels"),
    "role": Signal("who", "the role rule, in order: platform, curator by links, official, staff or beat, reposter, "
                          "curator, commentator, reporter, independent", 5, "read posts"),
    "own_share": Signal("own", "1 - reposts / posts, last 90 days (meaningful on X)", 10),
    "forwards": Signal("own", "its posts that are later near-copies of another source's post (undeclared forwards), "
                              "last 90 days", 10),
    "root_share": Signal("own", "its story posts with no parent / its story posts", 10, "stories"),
    "perspectives": Signal("own", "Mark X perspectives of its posts: original / new facts / opinion / same", 20,
                           "labels"),
    "first_to_report": Signal("first", "stories with 2+ voices where it was the earliest voice / its stories with "
                                       "2+ voices", 10, "stories"),
    "solo_share": Signal("covered", "its posts in no story with 2+ voices / its posts, last 90 days: nobody else in "
                                    "your sources covered this", 10),
    "news_yield": Signal("news", "its posts in News / its posts in the News window", 10, "posts in the News window"),
    "cited_by": Signal("cited", "distinct other voices linking its posts or addresses, last 90 days; own channels "
                                "excluded", 0, "citing posts"),
    "kinds": Signal("posts", "Mark X reading kinds of its read original posts", 10, "read posts"),
    "languages": Signal("posts", "languages of its posts, last 90 days", 10),
    "media_only": Signal("posts", "posts with under 40 characters of text and a title under 15 / posts, last 90 days",
                         10),
    "per_week": Signal("rhythm", "posts in the last 90 days / weeks (since it was added, when later)", 0),
    "age": Signal("rhythm", "its first stored post and the date it was added", 0),
    "audience": Signal("audience", "median YouTube views per video, as fetched", 5, "videos"),
    "followers": Signal("audience", "subscribers or followers its profile shows, as last fetched (a voice: its "
                                    "channels' together)", 0, "profiles"),
    "reputation": Signal("reputation", "inside your sources only: cited by, Classics, first to report", 0),
    "stance": Signal("stance", "Haiku over 15 random own posts of 250+ characters; a pattern needs 2+ exact quotes "
                               "from 2 posts, checked by code (Experimental)", 15, "posts of 250+ characters"),
}
CARDS = [("channels", "Channels"), ("who", "Who it is"), ("own", "Own vs retold"), ("first", "First to report"),
         ("covered", "Covered by others"), ("news", "News yield"), ("cited", "Cited by"), ("posts", "What it posts"),
         ("rhythm", "Rhythm and age"), ("audience", "Audience"), ("reputation", "Reputation"),
         ("stance", "Stance and framing")]
LIST_COLUMNS = ("role", "per_week", "first_to_report", "news_yield", "cited_by", "solo_share")


def _utc(t: Optional[datetime]) -> Optional[datetime]:
    return t.astimezone(timezone.utc) if t else None


def _iso(t: Optional[datetime]) -> Optional[str]:
    return _utc(t).isoformat() if t else None


# ---- addresses: who a link points at (platform address shapes only, no list of sites) ------------

def link_key(url: Optional[str]) -> Optional[str]:
    """The owner an address belongs to: an account on a platform (x.com/<user>, t.me/<channel>,
    youtube.com/channel/<id>, github.com/<owner>), else its publication (the host without www)."""
    from insight_core.utils.addresses import account_key, host_of, publication_of, site_of
    if not url:
        return None
    host = host_of(url)
    if not host:
        return None
    if site_of(host) in ACCOUNT_SITES or host in ACCOUNT_SITES:
        key = account_key(url)
        first = key.split("/", 1)[1] if "/" in key else ""
        if not first or first in ("i", "intent", "search", "home", "hashtag", "share", "s", "watch", "status"):
            return None
        return key.replace("twitter.com/", "x.com/").replace("telegram.me/", "t.me/")
    return publication_of(host)


# ---- the data: one read of every table the signals count ------------------------------------------

@dataclass
class Src:
    id: str
    platform: str
    handle: str
    name: str
    kind: str
    enabled: bool
    created_at: Optional[datetime]
    voice: Optional[str] = None           # 0132 A's voice id, when voices exist
    keys: Set[str] = field(default_factory=set)
    own_account: Optional[str] = None


@dataclass
class P:
    id: str
    source: str
    at: Optional[datetime]
    title: str
    text: str
    author: Optional[str]
    repost: bool
    url_key: Optional[str]
    lang: Optional[str]
    precision: Optional[str]
    views: Optional[int] = None


@dataclass
class Data:
    now: datetime
    since: datetime
    sources: Dict[str, Src]
    voices: Dict[str, Dict[str, Any]]                       # id -> {name, kind}
    voice_links: List[Dict[str, Any]]
    posts: Dict[str, P]                                     # the window's posts
    totals: Dict[str, Tuple[int, Optional[datetime]]]       # source -> (posts ever, first stored post)
    links: Dict[str, List[Tuple[str, bool]]]                # window post -> [(target, boilerplate)]
    linked_posts: Dict[str, Set[str]]                       # target source -> window posts of others linking a post of it
    story_posts: List[Dict[str, Any]]                       # every story membership
    story_titles: Dict[str, str]
    news_posts: Set[str]
    news_since: Optional[datetime]
    news_kind: str
    news_rows: Dict[str, str]                               # post -> its News row id
    read_kinds: Dict[str, str]                              # post -> its reading's kind (every read post)
    read_sources: Dict[str, str]                            # read post -> source
    read_reposts: Set[str]
    mentions: Dict[str, List[R.Mention]]
    classics: List[Dict[str, Any]]
    perspectives: Dict[str, Counter]                        # source -> labels
    videos: Dict[str, List[int]]                            # source -> view counts (every stored video)
    stance: Dict[str, Dict[str, Any]]                       # source -> its newest answered stance
    authors: Dict[str, int]                                 # source -> distinct authors (sites)
    long_posts: Dict[str, int] = field(default_factory=dict)   # source -> own posts of 250+ characters (the window)
    post_titles: Dict[str, Tuple[str, Optional[datetime], str]] = field(default_factory=dict)   # any post -> (title, at, source)
    profiles: Dict[str, Dict[str, Any]] = field(default_factory=dict)   # 0132 C2: source -> its current profile

    def voice_of(self, source_id: str) -> str:
        s = self.sources.get(source_id)
        return f"v:{s.voice}" if s and s.voice else f"s:{source_id}"


def _exists(cur: Any, table: str, column: Optional[str] = None) -> bool:
    if column is None:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL", (f"public.{table}",))
    else:
        cur.execute("""SELECT EXISTS (SELECT 1 FROM information_schema.columns
                                       WHERE table_schema = 'public' AND table_name = %s AND column_name = %s)""",
                    (table, column))
    return bool(cur.fetchone()[0])


def voices_exist(cur: Any) -> bool:
    """0132 A's voices: the table and sources.voice_id (another slice's migration 0080); absent: per source only."""
    return _exists(cur, "voices") and _exists(cur, "sources", "voice_id")


AT = "COALESCE(p.surfaced_at, p.published_at, p.fetched_at)"


def is_repost(s: Src, title: Optional[str], author: Optional[str], reposted_by: Any, forwarded: Any = False) -> bool:
    """Not the source's own post: a Telegram forward (Part C3's "forwarded from"), a retweet ("RT by @", or a row its
    source reposted, issue 0066), or on X a post another account wrote."""
    from insight_core.db.repo_reader import repost_of
    if forwarded or (title or "").startswith("RT by @"):
        return True
    if repost_of(s.platform, s.handle, author, reposted_by) is not None:
        return True
    if s.kind == "x" and author and s.own_account:
        return author.lower().lstrip("@") != s.own_account.split("/", 1)[-1]
    return False


def sources(cur: Any) -> Dict[str, Src]:
    """Every source but saved pages, with its own platform account."""
    from insight_core.db.repo_stories import source_account
    from insight_core.utils.post_links import source_kind
    has_voices = voices_exist(cur)
    cur.execute(f"""SELECT id::text, platform, handle_or_url,
                           COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url), enabled, created_at,
                           {'voice_id::text' if has_voices else 'NULL'}
                      FROM sources WHERE platform <> ALL(%s)""", (list(NOT_SUBJECTS),))
    out: Dict[str, Src] = {}
    for sid, platform, handle, name, enabled, created, voice in cur.fetchall():
        s = Src(sid, platform or "", handle or "", name or "", source_kind(platform, handle), bool(enabled), created, voice)
        acct = source_account(platform, handle)
        if acct:
            s.own_account = acct
            if s.kind in ("x", "telegram", "youtube"):
                s.keys.add(acct)
        if s.kind == "site" and "://" in s.handle:
            k = link_key(s.handle)
            if k:
                s.keys.add(k)
        out[sid] = s
    return out


def load(cur: Any, now: Optional[datetime] = None, *, window_days: int = WINDOW_DAYS) -> Data:
    from insight_core.markx import schemas

    if now is None:
        cur.execute("SELECT now()")
        now = cur.fetchone()[0]
    since = now - timedelta(days=window_days)
    has_voices = voices_exist(cur)
    srcs = sources(cur)

    voices: Dict[str, Dict[str, Any]] = {}
    links_between: List[Dict[str, Any]] = []
    if has_voices:
        cur.execute("SELECT id::text, name, kind FROM voices")
        voices = {v: {"name": n, "kind": k} for v, n, k in cur.fetchall()}
        if _exists(cur, "voice_links"):
            cur.execute("SELECT * FROM voice_links")
            cols = [d.name for d in cur.description]
            links_between = [dict(zip(cols, [str(x) if hasattr(x, "hex") else x for x in r])) for r in cur.fetchall()]

    ids = list(srcs)
    # the window's posts
    cur.execute(f"""SELECT p.id::text, p.source_id::text, {AT}, COALESCE(p.title, ''), left(COALESCE(p.content, ''), 1500),
                           p.author, p.reposted_by, p.normalized_url, p.url, p.language_code, p.published_precision,
                           (p.metadata ? 'forwarded_from'), p.metadata->>'view_count'
                      FROM posts p
                     WHERE p.source_id = ANY(%s::uuid[]) AND {AT} >= %s""", (ids, since))
    posts: Dict[str, P] = {}
    for (pid, sid, at, title, text, author, reposted_by, nurl, url, lang, prec, forwarded, views) in cur.fetchall():
        s = srcs[sid]
        repost = is_repost(s, title, author, reposted_by, forwarded)
        posts[pid] = P(pid, sid, at, title, text, author, repost, link_key(nurl or url), (lang or "").split("-")[0] or None,
                       prec, int(views) if views and views.isdigit() else None)

    # a site's own address: the publication 50%+ of its posts live on
    by_src: Dict[str, Counter] = defaultdict(Counter)
    for p in posts.values():
        if p.url_key:
            by_src[p.source][p.url_key] += 1
    for sid, c in by_src.items():
        s = srcs[sid]
        tot = sum(c.values())
        for k, n in c.items():
            if s.kind == "site" and tot and n / tot >= 0.5 and not k.startswith(("x.com/", "t.me/", "youtube.com/")):
                s.keys.add(k)
    cur.execute("""SELECT source_id::text, count(*), min(COALESCE(published_at, fetched_at)),
                          count(DISTINCT NULLIF(btrim(COALESCE(metadata->>'author_display_name', metadata->>'author_name',
                                                               metadata->>'primary_author', metadata->>'author', '')), ''))
                     FROM posts WHERE source_id = ANY(%s::uuid[]) GROUP BY 1""", (ids,))
    totals, authors = {}, {}
    for sid, n, first, nauth in cur.fetchall():
        totals[sid] = (n, first)
        authors[sid] = nauth if srcs[sid].kind == "site" else 0
    cur.execute("""SELECT DISTINCT p.metadata->>'channel_id', p.source_id::text FROM posts p
                    WHERE p.source_id = ANY(%s::uuid[]) AND p.metadata ? 'channel_id'""", (ids,))
    for channel, sid in cur.fetchall():
        if channel:
            srcs[sid].keys.add("youtube.com/channel/" + channel.lower())
    cur.execute("""SELECT p.source_id::text, (p.metadata->>'view_count') FROM posts p
                    WHERE p.source_id = ANY(%s::uuid[]) AND p.metadata ? 'view_count'""", (ids,))
    videos: Dict[str, List[int]] = defaultdict(list)
    for sid, v in cur.fetchall():
        if v and v.isdigit():
            videos[sid].append(int(v))

    # links out of the window's posts
    cur.execute(f"""SELECT l.post_id::text, l.target_url, l.boilerplate FROM post_links l JOIN posts p ON p.id = l.post_id
                     WHERE p.source_id = ANY(%s::uuid[]) AND {AT} >= %s""", (ids, since))
    links: Dict[str, List[Tuple[str, bool]]] = defaultdict(list)
    for pid, target, bp in cur.fetchall():
        links[pid].append((target, bool(bp)))
    cur.execute(f"""SELECT DISTINCT t.source_id::text, l.post_id::text
                      FROM post_links l JOIN posts p ON p.id = l.post_id
                      JOIN posts t ON t.normalized_url = l.target_url AND t.source_id <> p.source_id
                     WHERE NOT l.boilerplate AND p.source_id = ANY(%(ids)s::uuid[]) AND {AT} >= %(since)s
                       AND t.source_id = ANY(%(ids)s::uuid[])""", {"ids": ids, "since": since})
    linked_posts: Dict[str, Set[str]] = defaultdict(set)
    for target, pid in cur.fetchall():
        linked_posts[target].add(pid)

    # stories (every stored story), with each member's source and time
    cur.execute(f"""SELECT sp.story_id::text, sp.post_id::text, p.source_id::text, sp.voice, sp.parent_id IS NULL,
                           {AT}, p.published_precision, COALESCE(p.title, '')
                      FROM story_posts sp JOIN posts p ON p.id = sp.post_id""")
    story_posts = [{"story": st, "post": pid, "source": sid, "voice": v, "root": root, "at": at, "precision": prec,
                    "title": title} for st, pid, sid, v, root, at, prec, title in cur.fetchall()]
    cur.execute("SELECT id::text, COALESCE(origin_title, '') FROM stories")
    story_titles = {k: v for k, v in cur.fetchall()}

    # News: Mark X News' newest written run when there is one, else Mark IX's
    from insight_core.markx import news as mx_news
    news_posts: Set[str] = set()
    news_rows: Dict[str, str] = {}
    news_since, news_kind = None, "markix"
    run = mx_news.last_written(cur) if _exists(cur, "mx_news") else None
    if run:
        news_kind = "markx"
        cur.execute("SELECT id::text, first_at, posts FROM mx_news WHERE run_id = %s", (run,))
        for nid, first, ps in cur.fetchall():
            news_since = first if news_since is None or (first and first < news_since) else news_since
            for q in ps or []:
                pid = str(q.get("post_id") or q.get("id") or "")
                if pid:
                    news_posts.add(pid)
                    news_rows.setdefault(pid, nid)
    else:
        cur.execute("SELECT np.post_id::text, np.news_id::text, ns.first_at FROM news_posts np "
                    "JOIN news_stories ns ON ns.id = np.news_id")
        for pid, nid, first in cur.fetchall():
            news_posts.add(pid)
            news_rows.setdefault(pid, nid)
            news_since = first if news_since is None or (first and first < news_since) else news_since

    # Mark X readings and entities (every read post of these sources)
    read_kinds: Dict[str, str] = {}
    read_sources: Dict[str, str] = {}
    read_reposts: Set[str] = set()
    mentions: Dict[str, List[R.Mention]] = defaultdict(list)
    if _exists(cur, "mx_readings"):
        cur.execute("""SELECT DISTINCT ON (r.post_id) r.post_id::text, r.kind, p.source_id::text, p.title, p.author,
                              p.reposted_by, (p.metadata ? 'forwarded_from')
                         FROM mx_readings r JOIN posts p ON p.id = r.post_id
                        WHERE p.source_id = ANY(%s::uuid[]) AND r.guide IN ('read-v2', 'read-v3')
                        ORDER BY r.post_id, r.guide""", (ids,))
        for pid, kind, sid, title, author, reposted_by, fwd in cur.fetchall():
            s = srcs[sid]
            read_kinds[pid] = kind
            read_sources[pid] = sid
            if is_repost(s, title, author, reposted_by, fwd):
                read_reposts.add(pid)
        cur.execute("""SELECT m.post_id::text, m.name, m.maker, m.role, m.type FROM mx_mentions m
                        WHERE m.guide = %s AND m.post_id = ANY(%s::uuid[])""",
                    (schemas.KINDS["entities"].guide, list(read_kinds)))
        for pid, name, maker, role, typ in cur.fetchall():
            mentions[pid].append(R.Mention(name, maker, role, typ))

    cur.execute("SELECT target_url, post_id::text, COALESCE(title, ''), voices FROM classics")
    classics = [{"url": u, "post": p, "title": t, "voices": v} for u, p, t, v in cur.fetchall()]

    perspectives: Dict[str, Counter] = defaultdict(Counter)
    if _exists(cur, "mx_perspectives"):
        cur.execute("""SELECT p.source_id::text, x.label FROM mx_perspectives x JOIN posts p ON p.id = x.post_id
                        WHERE x.valid_to IS NULL AND x.label <> 'not_this_story'""")
        for sid, label in cur.fetchall():
            perspectives[sid][label] += 1

    data = Data(now=now, since=since, sources=srcs, voices=voices, voice_links=links_between, posts=posts,
                totals=totals, links=links, linked_posts=linked_posts, story_posts=story_posts,
                story_titles=story_titles, news_posts=news_posts, news_since=news_since, news_kind=news_kind,
                news_rows=news_rows, read_kinds=read_kinds, read_sources=read_sources, read_reposts=read_reposts,
                mentions=mentions, classics=classics, perspectives=perspectives, videos=videos,
                stance=stances(cur), authors=authors)
    data.long_posts = long_post_counts(cur, ids, now)
    from insight_core.services.profiles_service import current as current_profiles
    data.profiles = current_profiles(cur, ids)   # {} before migration 0086
    want = {r["post"] for r in story_posts} | set(read_kinds) | {c["post"] for c in classics if c["post"]}
    want -= set(posts)
    titles = {pid: (p.title or p.text[:90], p.at, p.source) for pid, p in posts.items()}
    if want:
        cur.execute(f"SELECT p.id::text, COALESCE(NULLIF(p.title, ''), left(p.content, 90), ''), {AT}, p.source_id::text "
                    "FROM posts p WHERE p.id = ANY(%s::uuid[])", (list(want),))
        for pid, title, at, sid in cur.fetchall():
            titles[pid] = (title, at, sid)
    data.post_titles = titles
    return data


def long_post_counts(cur: Any, ids: Sequence[str], now: datetime) -> Dict[str, int]:
    """Own posts of 250+ characters in the window, per source (the stance card's n)."""
    cur.execute(f"""SELECT p.source_id::text, count(*) FROM posts p
                     WHERE p.source_id = ANY(%s::uuid[]) AND {AT} >= %s
                       AND length(COALESCE(p.title, '')) + length(COALESCE(p.content, '')) >= %s
                       AND NOT COALESCE(p.title, '') LIKE 'RT by @%%' AND NOT (p.metadata ? 'forwarded_from')
                     GROUP BY 1""", (list(ids), now - timedelta(days=WINDOW_DAYS), STANCE_MIN_CHARS))
    return {sid: n for sid, n in cur.fetchall()}


def stances(cur: Any) -> Dict[str, Dict[str, Any]]:
    """{source: its newest answered stance task's valid answer, input and time}."""
    if not _exists(cur, "mx_tasks"):
        return {}
    cur.execute("""SELECT DISTINCT ON (t.a) t.a::text, t.id::text, t.input, c.answer, c.created_at, c.model
                     FROM mx_tasks t JOIN mx_calls c ON c.task_id = t.id AND c.valid
                    WHERE t.kind = 'stance' AND t.status = 'answered' AND t.a IS NOT NULL
                    ORDER BY t.a, c.created_at DESC""")
    return {a: {"task": t, "input": inp, "answer": ans, "at": at, "model": model}
            for a, t, inp, ans, at, model in cur.fetchall()}


# ---- the signals ----------------------------------------------------------------------------------

@dataclass
class Row:
    kind: str           # source | voice
    id: str
    signal: str
    value: Any
    n: int
    evidence: Dict[str, Any]


def _post_ev(d: Data, pid: str, **extra: Any) -> Dict[str, Any]:
    title, at, sid = d.post_titles.get(pid, ("", None, ""))
    s = d.sources.get(sid)
    return {"id": pid, "title": (title or "")[:140], "at": _iso(at), "source": s.name if s else None, **extra}


def _voice_name(d: Data, voice: str) -> str:
    kind, _, vid = voice.partition(":")
    if kind == "v":
        return (d.voices.get(vid) or {}).get("name") or "a voice"
    if kind == "s":
        s = d.sources.get(vid)
        return s.name if s else "a source"
    return vid or voice


def _share(a: int, b: int) -> Optional[float]:
    return round(a / b, 3) if b else None


def _story_voice(d: Data, m: Dict[str, Any]) -> str:
    """A story member's voice as these signals count it: its source's voice (0132 A), or Mark IX's voice key when the
    post speaks for someone else (a Reddit author, a page's site)."""
    v = m["voice"] or ""
    if v.startswith("source:") or not v:
        return d.voice_of(m["source"])
    return v


def _member_time(m: Dict[str, Any]) -> Optional[datetime]:
    t = m["at"]
    if t is not None and m.get("precision") == "day":
        t = t.replace(hour=12, minute=0, second=0, microsecond=0)
    return t


class Copies:
    """Near-identical posts across sources in the window (5-word shingles, Jaccard >= 0.5; one shingle in
    COPY_SAMPLE indexed)."""

    URL = re.compile(r"https?://\S+")

    def __init__(self, d: Data) -> None:
        sets: Dict[str, Set[int]] = {}
        for pid, p in d.posts.items():
            words = re.findall(r"\w+", self.URL.sub(" ", f"{p.title} {p.text}".lower()))[:300]
            if len(words) < COPY_MIN_WORDS:
                continue
            sh = {h for h in (hash(" ".join(words[i:i + 5])) for i in range(len(words) - 4)) if h % COPY_SAMPLE == 0}
            if sh:
                sets[pid] = sh
        index: Dict[int, List[str]] = defaultdict(list)
        for pid, sh in sets.items():
            for h in sh:
                index[h].append(pid)
        pairs: Counter = Counter()
        for lst in index.values():
            if not 2 <= len(lst) <= COPY_MAX_POSTS:
                continue
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    x, y = lst[i], lst[j]
                    if d.posts[x].source != d.posts[y].source:
                        pairs[(x, y) if x < y else (y, x)] += 1
        self.pairs: List[Tuple[str, str, float]] = []
        for (x, y), c in pairs.items():
            if c < 2:
                continue
            j = len(sets[x] & sets[y]) / len(sets[x] | sets[y])
            if j >= COPY_JACCARD:
                self.pairs.append((x, y, round(j, 2)))
        self.eligible = set(sets)


def compute(d: Data, *, only: Optional[Iterable[str]] = None) -> List[Row]:
    """Every signal of every source (or those of `only`), and of every voice."""
    subjects: List[Tuple[str, str, List[str]]] = []
    wanted = set(only) if only is not None else None
    for sid in d.sources:
        if wanted is None or sid in wanted:
            subjects.append(("source", sid, [sid]))
    members: Dict[str, List[str]] = defaultdict(list)
    for sid, s in d.sources.items():
        if s.voice:
            members[s.voice].append(sid)
    for vid, sids in members.items():
        if wanted is None or set(sids) & wanted:
            subjects.append(("voice", vid, sorted(sids)))

    copies = Copies(d)
    by_source: Dict[str, List[P]] = defaultdict(list)
    for p in d.posts.values():
        by_source[p.source].append(p)
    stories: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for m in d.story_posts:
        stories[m["story"]].append(m)
    stories_of: Dict[str, Set[str]] = defaultdict(set)
    for st, ms in stories.items():
        for m in ms:
            stories_of[m["source"]].add(st)
    multi_posts: Set[str] = set()
    for ms in stories.values():
        if len({_story_voice(d, m) for m in ms}) >= 2:
            multi_posts |= {m["post"] for m in ms}
    key_owner: Dict[str, Set[str]] = defaultdict(set)
    for sid, s in d.sources.items():
        for k in s.keys:
            key_owner[k].add(sid)
    platformish = {sid for sid, s in d.sources.items() if s.kind in ("reddit", "hn") or d.authors.get(sid, 0) >= R.PLATFORM_AUTHORS}
    cites: Dict[str, Dict[str, Set[str]]] = defaultdict(lambda: defaultdict(set))   # target source -> voice -> posts
    for pid, ls in d.links.items():
        p = d.posts.get(pid)
        if p is None:
            continue
        hit = set()
        for target, bp in ls:
            if bp:
                continue
            for t in key_owner.get(link_key(target) or "", ()):
                if t != p.source and t not in platformish:
                    hit.add(t)
        for t in hit:
            cites[t][d.voice_of(p.source)].add(pid)
    for t, ps in d.linked_posts.items():
        for pid in ps:
            p = d.posts.get(pid)
            if p is not None:
                cites[t][d.voice_of(p.source)].add(pid)

    rows: List[Row] = []
    for kind, sid, sids in subjects:
        out = _subject(d, kind, sid, sids, by_source, stories, stories_of, multi_posts, cites, copies)
        rows.extend(Row(kind, sid, name, value, n, ev) for name, (value, n, ev) in out.items())
    return rows


def _subject(d: Data, kind: str, sid: str, sids: List[str], by_source, stories, stories_of, multi_posts, cites,
             copies: Copies) -> Dict[str, Tuple[Any, int, Dict[str, Any]]]:
    out: Dict[str, Tuple[Any, int, Dict[str, Any]]] = {}
    me = set(sids)
    my_voice = d.voice_of(sids[0]) if kind == "voice" else d.voice_of(sid)
    srcs = [d.sources[x] for x in sids]
    posts = sorted((p for x in sids for p in by_source.get(x, [])), key=lambda p: p.at or d.now, reverse=True)
    n = len(posts)
    own = [p for p in posts if not p.repost]
    main_kind = Counter({s.kind: len(by_source.get(s.id, [])) + 1 for s in srcs}).most_common(1)[0][0]
    created = min((s.created_at for s in srcs if s.created_at), default=None)

    # channels
    chans = [{"id": s.id, "name": s.name, "kind": s.kind, "enabled": s.enabled, "address": sorted(s.keys)[:3],
              "posts": d.totals.get(s.id, (0, None))[0]} for s in srcs]
    twice = []
    for s in srcs:
        for o in d.sources.values():
            if o.id != s.id and s.keys & o.keys and o.kind == s.kind and not (s.kind == "site" and d.authors.get(o.id, 0) >= R.PLATFORM_AUTHORS):
                twice.append({"source": s.id, "other": o.id, "other_name": o.name, "other_enabled": o.enabled,
                              "address": sorted(s.keys & o.keys)[0]})
    related = []
    voice_id = srcs[0].voice if srcs and srcs[0].voice else None
    for link in d.voice_links:
        ends = [str(link.get(k)) for k in link if k.endswith("voice_id") or k in ("a", "b", "voice_a", "voice_b")]
        if voice_id and voice_id in ends:
            other = next((e for e in ends if e != voice_id), None)
            related.append({"voice": other, "name": (d.voices.get(other) or {}).get("name"),
                            "kind": link.get("kind"), "evidence": link.get("evidence")})
    out["channels"] = (len(chans), len(chans), {"channels": chans, "same_channel_twice": twice[:EVIDENCE],
                                                "related": related[:EVIDENCE],
                                                "voice": {"id": voice_id, "name": (d.voices.get(voice_id) or {}).get("name")}
                                                if voice_id else None})

    # rhythm and age
    weeks = max(1.0, min(WINDOW_DAYS, (d.now - created).days if created else WINDOW_DAYS) / 7)
    out["per_week"] = (round(n / weeks, 2), n, {"posts": n, "weeks": round(weeks, 1)})
    firsts = [d.totals.get(x, (0, None))[1] for x in sids]
    first = min((f for f in firsts if f), default=None)
    flagged = bool(first and first.year < min(PLATFORM_YEARS.get(s.kind, 1991) for s in srcs))
    out["age"] = (_iso(first), sum(d.totals.get(x, (0, None))[0] for x in sids),
                  {"first_post": _iso(first), "added": _iso(created), "before_platform": flagged,
                   "new_source": bool(created and (d.now - created).days < NEW_SOURCE_DAYS)})

    # own vs retold
    reposts = [p for p in posts if p.repost]
    authors = Counter((p.author or "").lstrip("@") for p in reposts if p.author)
    out["own_share"] = (_share(len(own), n), n, {"reposts": len(reposts), "kind": main_kind,
                                                 "reposted": [{"author": a, "posts": c} for a, c in authors.most_common(5)],
                                                 "posts": [_post_ev(d, p.id) for p in reposts[:5]]})
    later = []
    for x, y, j in copies.pairs:
        px, py = d.posts[x], d.posts[y]
        for mine, other in ((px, py), (py, px)):
            if mine.source in me and other.source not in me and d.voice_of(other.source) != my_voice and not mine.repost \
                    and mine.at and other.at and mine.at > other.at:
                later.append((mine, other, j))
    eligible = sum(1 for p in own if p.id in copies.eligible)
    out["forwards"] = (len(later), eligible, {"posts": [
        _post_ev(d, a.id, original=_post_ev(d, b.id), hours_later=round((a.at - b.at).total_seconds() / 3600, 1),
                 jaccard=j) for a, b, j in sorted(later, key=lambda t: t[0].at, reverse=True)[:EVIDENCE]]})
    my_story_posts = [m for x in sids for st in stories_of.get(x, ()) for m in stories[st] if m["source"] == x]
    my_stories = {m["story"] for m in my_story_posts}
    roots = sum(1 for m in my_story_posts if m["root"])
    out["root_share"] = (_share(roots, len(my_story_posts)), len(my_stories),
                         {"roots": roots, "story_posts": len(my_story_posts),
                          "posts": [_post_ev(d, m["post"]) for m in my_story_posts if m["root"]][:5]})
    pc = Counter()
    for x in sids:
        pc.update(d.perspectives.get(x, Counter()))
    out["perspectives"] = (dict(pc), sum(pc.values()), {"labels": dict(pc)})

    # first to report (every stored story with 2+ voices)
    firsts_ev, first_n, first_hits = [], 0, 0
    aggregator = main_kind == "hn" or any(d.authors.get(x, 0) >= R.PLATFORM_AUTHORS for x in sids)
    for st in sorted(my_stories):
        best: Dict[str, Tuple[datetime, Dict[str, Any]]] = {}
        for m in stories[st]:
            v = "SELF" if m["source"] in me else _story_voice(d, m)
            if v == my_voice and m["source"] not in me:
                continue
            t = _member_time(m)
            if t and (v not in best or t < best[v][0]):
                best[v] = (t, m)
        if len(best) < 2 or "SELF" not in best:
            continue
        first_n += 1
        mine_t = best["SELF"][0]
        others = sorted(((t, v, m) for v, (t, m) in best.items() if v != "SELF"), key=lambda z: z[0])
        is_first = not any(t < mine_t - timedelta(minutes=1) for t, _v, _m in others)
        first_hits += is_first
        nt, nv, nm = others[0]
        firsts_ev.append({"story": st, "title": (d.story_titles.get(st) or best["SELF"][1]["title"] or "")[:140],
                          "first": is_first, "at": _iso(mine_t), "next": _voice_name(d, nv) if is_first else None,
                          "first_voice": None if is_first else _voice_name(d, nv),
                          "hours": round(abs((nt - mine_t).total_seconds()) / 3600, 1), "voices": len(best),
                          "post": best["SELF"][1]["post"]})
    firsts_ev.sort(key=lambda e: e["at"] or "", reverse=True)
    out["first_to_report"] = (_share(first_hits, first_n), first_n,
                              {"first": first_hits, "stories": firsts_ev[:EVIDENCE * 2],
                               "aggregator": aggregator})

    # covered by others
    solo = [p for p in posts if p.id not in multi_posts]
    out["solo_share"] = (_share(len(solo), n), n, {"solo": len(solo), "posts": [_post_ev(d, p.id) for p in solo[:5]],
                                                   "covered": [_post_ev(d, p.id) for p in posts if p.id in multi_posts][:5]})

    # News yield
    win = [p for p in posts if d.news_since and p.at and p.at >= d.news_since]
    in_news = [p for p in win if p.id in d.news_posts]
    out["news_yield"] = (_share(len(in_news), len(win)), len(win),
                         {"news": d.news_kind, "since": _iso(d.news_since), "in_news": len(in_news),
                          "rows": [_post_ev(d, p.id, row=d.news_rows.get(p.id)) for p in in_news[:EVIDENCE]],
                          "new_source": bool(created and (d.now - created).days < NEW_SOURCE_DAYS)})

    # cited by
    by_voice: Dict[str, Set[str]] = defaultdict(set)
    for x in sids:
        for v, ps in cites.get(x, {}).items():
            if v != my_voice:
                by_voice[v] |= ps
    citing = sorted(by_voice.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    keys = set().union(*(s.keys for s in srcs)) if srcs else set()
    platform = main_kind in ("reddit", "hn")
    classics = [c for c in d.classics if (c["post"] and d.post_titles.get(c["post"], ("", None, ""))[2] in me)
                or (not platform and link_key(c["url"]) in keys)]
    out["cited_by"] = (len(by_voice), sum(len(ps) for ps in by_voice.values()),
                       {"voices": [{"voice": _voice_name(d, v), "posts": len(ps), "example": _post_ev(d, sorted(ps)[0])}
                                   for v, ps in citing[:EVIDENCE]],
                        "classics": len(classics),
                        "classic_rows": [{"url": c["url"], "title": c["title"][:140], "voices": c["voices"]}
                                         for c in sorted(classics, key=lambda c: -(c["voices"] or 0))[:EVIDENCE]],
                        "bias": CITED_BIAS})

    # what it posts
    read_own = [pid for pid, x in d.read_sources.items() if x in me and pid not in d.read_reposts]
    kinds = R.kind_shares(d.read_kinds.get(pid) for pid in read_own)
    out["kinds"] = ({k: round(v, 3) for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])}, len(read_own),
                    {"posts": {k: [_post_ev(d, pid) for pid in read_own if d.read_kinds.get(pid) == k][:3]
                               for k in kinds}})
    langs = Counter(p.lang or "?" for p in posts)
    out["languages"] = ({k: _share(v, n) for k, v in langs.most_common(3)}, n, {})
    media = [p for p in posts if len(p.text.strip()) < MEDIA_ONLY_TEXT and len(p.title.strip()) < MEDIA_ONLY_TITLE]
    out["media_only"] = (_share(len(media), n), n, {"posts": [_post_ev(d, p.id) for p in media[:5]]})

    # who it is: the role rule
    rd = {pid: d.mentions.get(pid, []) for pid in read_own}
    names = R.Names.of([s.name for s in srcs] + ([(d.voices.get(voice_id) or {}).get("name")] if voice_id else []),
                       [s.own_account.split("/", 1)[-1] if s.own_account else None for s in srcs],
                       [k for s in srcs for k in s.keys if "/" not in k])
    is_off, self_share, nread, hits = R.official(rd, names)
    maker, maker_share, maker_posts = R.top_maker(rd, names)
    own_pages = None
    if main_kind == "site" and n:
        own_pages = sum(1 for p in posts if p.url_key and p.url_key in keys) / n
    link_posts = sum(1 for p in own if len(p.text) < LINK_POST_CHARS and any(
        not bp and link_key(t) not in keys for t, bp in d.links.get(p.id, ())))
    facts = R.Facts(kind=main_kind, posts=n, authors=max((d.authors.get(x, 0) for x in sids), default=0),
                    own_pages_share=own_pages, read=nread, official=is_off, self_share=self_share, maker=maker,
                    maker_share=maker_share, own_share=len(own) / n if n else 1.0,
                    link_post_share=link_posts / len(own) if own else 0.0, kinds=kinds)
    role, line = R.role(facts)
    examples = hits if role == "official" else maker_posts if role == "staff_or_beat" else (
        [p.id for p in reposts] if role == "reposter" else read_own)
    out["role"] = (role, nread, {"label": R.LABELS[role], "line": line, "needs_bio": role == "staff_or_beat",
                                 "posts": [_post_ev(d, pid) for pid in examples[:3]],
                                 "facts": {"self_share": round(self_share, 3), "maker": maker,
                                           "maker_share": round(maker_share, 3),
                                           "link_post_share": round(facts.link_post_share, 3),
                                           "own_pages_share": None if own_pages is None else round(own_pages, 3)}})

    # audience
    views = [v for x in sids for v in d.videos.get(x, [])]
    out["audience"] = (int(statistics.median(views)) if views else None, len(views),
                       {"what": "views when fetched" if views else "no audience data"})
    profs = [(x, d.profiles[x]) for x in sids if x in d.profiles]
    counted = [(x, p) for x, p in profs if p.get("followers") is not None]
    out["followers"] = (sum(int(p["followers"]) for _, p in counted) if counted else None, len(counted), {
        "what": "from its profile" if counted else ("its profile shows no count" if profs else "no audience data"),
        "channels": [{"source": x, "name": d.sources[x].name if x in d.sources else "", "followers": p.get("followers"),
                      "label": p.get("followers_label"), "url": p.get("url"), "fetched_at": p.get("fetched_at")}
                     for x, p in profs]})

    # reputation (inside your sources only)
    fv, fn, fe = out["first_to_report"]
    out["reputation"] = ({"cited_by": out["cited_by"][0], "classics": len(classics), "first_to_report": fv},
                         out["cited_by"][1], {"first_stories": fn, "note": "inside your sources only"})

    # stance and framing (per source; a voice shows its channels')
    st = None
    for x in sids:
        got = d.stance.get(x)
        if got and (st is None or got["at"] > st["at"]):
            st = dict(got, source=x)
    long_n = sum(d.long_posts.get(x, 0) for x in sids)
    if st:
        from insight_core.markx import validate
        patterns = validate.stance_grounded(st["answer"], st["input"])
        ids = _stance_post_ids(d, st)
        for pat in patterns:
            for q in pat["quotes"]:
                q["post_id"] = ids.get(q["post"])
        out["stance"] = (len(patterns), long_n, {"task": st["task"], "source": st["source"], "at": _iso(st["at"]),
                                                 "model": st.get("model"), "patterns": patterns,
                                                 "voice": (st["answer"] or {}).get("voice"),
                                                 "interest": (st["answer"] or {}).get("interest")})
    else:
        out["stance"] = (None, long_n, {"task": None, "patterns": []})
    return out


def _stance_post_ids(d: Data, st: Dict[str, Any]) -> Dict[int, Optional[str]]:
    """The stance question's numbered posts, found back among the source's posts by their text (the input holds no
    ids, so a question is the same question however it was planned)."""
    from insight_core.markx.validate import stance_posts

    def head(text: str) -> str:
        return re.sub(r"\s+", " ", text).strip().lower()[:80]
    mine = {head(f"{p.title}\n{p.text}"): pid for pid, p in d.posts.items() if p.source == st["source"]}
    mine.update({head(p.text): pid for pid, p in d.posts.items() if p.source == st["source"] and not p.title})
    return {num: mine.get(head(text)) for num, text in stance_posts(st["input"]).items()}


# ---- writing --------------------------------------------------------------------------------------

def write(cur: Any, rows: Sequence[Row], computed_at: datetime) -> int:
    """Each row over its subject's last one (the numbers are made again; nothing they count is touched)."""
    if not rows:
        return 0
    cur.executemany(
        """INSERT INTO source_stats (subject_kind, subject_id, signal, value, n, evidence, computed_at)
           VALUES (%s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
           ON CONFLICT (subject_kind, subject_id, signal)
           DO UPDATE SET value = EXCLUDED.value, n = EXCLUDED.n, evidence = EXCLUDED.evidence,
                         computed_at = EXCLUDED.computed_at""",
        [(r.kind, r.id, r.signal, json.dumps(r.value, default=str), r.n, json.dumps(r.evidence, default=str),
          computed_at) for r in rows])
    return len(rows)


def run(cur: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """One stats run in `cur`'s transaction: {subjects, rows, seconds}."""
    t0 = time.monotonic()
    d = load(cur, now)
    rows = compute(d)
    write(cur, rows, d.now)
    return {"subjects": len({(r.kind, r.id) for r in rows}), "rows": len(rows),
            "seconds": round(time.monotonic() - t0, 2), "at": _iso(d.now)}


# ---- the page's views: rows only ------------------------------------------------------------------

def _too_few(signal: str, n: int) -> bool:
    return n < SIGNALS[signal].min


def list_view(cur: Any) -> Dict[str, Any]:
    """One row per voice, and per source with no voice: the role and the list's columns (no overall score), each
    {value, n, too_few}. Sorting is the page's (any column)."""
    has_voices = voices_exist(cur)
    cur.execute(f"""SELECT id::text, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url), platform,
                           handle_or_url, enabled, {'voice_id::text' if has_voices else 'NULL'}
                      FROM sources WHERE platform <> ALL(%s)""", (list(NOT_SUBJECTS),))
    from insight_core.utils.post_links import source_kind
    srcs = cur.fetchall()
    voices: Dict[str, Dict[str, Any]] = {}
    if has_voices:
        cur.execute("SELECT id::text, name FROM voices")
        voices = {v: {"name": n, "channels": []} for v, n in cur.fetchall()}
    cur.execute("""SELECT subject_kind, subject_id::text, signal, value, n, computed_at FROM source_stats
                    WHERE signal = ANY(%s)""", (list(LIST_COLUMNS),))
    stats: Dict[Tuple[str, str], Dict[str, Any]] = defaultdict(dict)
    newest = None
    for kind, sid, signal, value, n, at in cur.fetchall():
        stats[(kind, sid)][signal] = {"value": value, "n": n, "too_few": _too_few(signal, n)}
        newest = at if newest is None or at > newest else newest
    rows = []
    for sid, name, platform, handle, enabled, voice in srcs:
        if voice and voice in voices:
            voices[voice]["channels"].append({"id": sid, "name": name, "kind": source_kind(platform, handle)})
            continue
        rows.append({"kind": "source", "id": sid, "name": name, "platform": source_kind(platform, handle),
                     "enabled": enabled, "channels": 1, "stats": stats.get(("source", sid), {})})
    for vid, v in voices.items():
        if v["channels"]:
            rows.append({"kind": "voice", "id": vid, "name": v["name"], "platform": "voice", "enabled": True,
                         "channels": len(v["channels"]), "stats": stats.get(("voice", vid), {})})
    rows.sort(key=lambda r: (r["name"] or "").lower())
    return {"rows": rows, "columns": list(LIST_COLUMNS), "computed_at": _iso(newest),
            "formulas": {k: SIGNALS[k].formula for k in LIST_COLUMNS}}


def _cards(rows: Dict[str, Dict[str, Any]], labels: Dict[int, str]) -> List[Dict[str, Any]]:
    out = []
    for card, title in CARDS:
        signals = []
        for name, sig in SIGNALS.items():
            if sig.card != card:
                continue
            r = rows.get(name)
            if r is None:
                signals.append({"signal": name, "value": None, "n": 0, "min": sig.min, "counts": sig.counts,
                                "too_few": sig.min > 0, "formula": sig.formula, "evidence": {}})
                continue
            ev = r["evidence"] or {}
            if name == "stance":
                ev = dict(ev, labels={str(k): v for k, v in labels.items()})
            signals.append({"signal": name, "value": r["value"], "n": r["n"], "min": sig.min, "counts": sig.counts,
                            "too_few": _too_few(name, r["n"]), "formula": sig.formula, "evidence": ev})
        out.append({"card": card, "title": title, "experimental": card == "stance", "signals": signals})
    return out


def _rows(cur: Any, kind: str, sid: str) -> Tuple[Dict[str, Dict[str, Any]], Optional[datetime]]:
    cur.execute("SELECT signal, value, n, evidence, computed_at FROM source_stats WHERE subject_kind = %s AND subject_id = %s",
                (kind, sid))
    out, at = {}, None
    for signal, value, n, ev, computed in cur.fetchall():
        out[signal] = {"value": value, "n": n, "evidence": ev}
        at = computed if at is None or computed > at else at
    return out, at


def stance_labels(cur: Any, task_id: Optional[str], labeller: str = "owner") -> Dict[int, str]:
    """{pattern number: the owner's newest answer (right | wrong)}; an undo takes it back."""
    if not task_id:
        return {}
    cur.execute("""SELECT DISTINCT ON (note) note, answer FROM mx_labels
                    WHERE item_kind = 'stance' AND a = %s AND labeller = %s ORDER BY note, created_at DESC""",
                (task_id, labeller))
    out = {}
    for note, answer in cur.fetchall():
        m = re.match(r"pattern (\d+)$", note or "")
        if m and answer in ("right", "wrong"):
            out[int(m.group(1))] = answer
    return out


def subject_view(cur: Any, subject_id: str) -> Dict[str, Any]:
    """A voice's or a source's page: a tab per channel (a voice: its own tab first, then each channel's), each with
    one card per signal. KeyError: no such source or voice."""
    has_voices = voices_exist(cur)
    from insight_core.utils.post_links import source_kind
    voice = None
    if has_voices:
        cur.execute("SELECT id::text, name FROM voices WHERE id = %s", (subject_id,))
        voice = cur.fetchone()
    if voice:
        cur.execute("""SELECT id::text, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url), platform,
                              handle_or_url FROM sources WHERE voice_id = %s ORDER BY 2""", (subject_id,))
        channels = cur.fetchall()
        subject = {"kind": "voice", "id": voice[0], "name": voice[1], "voice": None}
        tabs = [("voice", voice[0], voice[1], "voice")] + [("source", c[0], c[1], source_kind(c[2], c[3])) for c in channels]
    else:
        cur.execute(f"""SELECT id::text, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url), platform,
                               handle_or_url, {'voice_id::text' if has_voices else 'NULL'}
                          FROM sources WHERE id = %s""", (subject_id,))
        row = cur.fetchone()
        if row is None:
            raise KeyError(subject_id)
        vname = None
        if row[4]:
            cur.execute("SELECT name FROM voices WHERE id = %s", (row[4],))
            got = cur.fetchone()
            vname = got[0] if got else None
        subject = {"kind": "source", "id": row[0], "name": row[1], "voice": {"id": row[4], "name": vname} if row[4] else None}
        tabs = [("source", row[0], row[1], source_kind(row[2], row[3]))]
    out_tabs, newest = [], None
    for kind, tid, name, platform in tabs:
        rows, at = _rows(cur, kind, tid)
        newest = at if newest is None or (at and at > newest) else newest
        task = ((rows.get("stance") or {}).get("evidence") or {}).get("task")
        out_tabs.append({"kind": kind, "id": tid, "name": name, "platform": platform, "computed": bool(rows),
                         "cards": _cards(rows, stance_labels(cur, task))})
    return {"subject": subject, "tabs": out_tabs, "computed_at": _iso(newest)}


STANCE_ANSWERS = ("right", "wrong", "undo")


def label_stance(cur: Any, *, task_id: str, pattern: int, answer: str,
                 labeller: str = "owner") -> Dict[int, str]:
    """The owner's right / wrong on a stance pattern (mx_labels, item kind stance: a = the task, b = the source)."""
    if answer not in STANCE_ANSWERS:
        raise ValueError(f"answer: one of {', '.join(STANCE_ANSWERS)}")
    cur.execute("SELECT a::text FROM mx_tasks WHERE id = %s AND kind = 'stance'", (task_id,))
    row = cur.fetchone()
    if row is None:
        raise KeyError(task_id)
    cur.execute("INSERT INTO mx_labels (item_kind, a, b, answer, labeller, note) VALUES ('stance', %s, %s, %s, %s, %s)",
                (task_id, row[0], answer, labeller, f"pattern {int(pattern)}"))
    return stance_labels(cur, task_id, labeller)


# ---- the job --------------------------------------------------------------------------------------

NIGHT = range(2, 6)               # UTC hours a nightly run may start in
DAILY = timedelta(hours=20)       # a nightly run once a day
AT_MOST = timedelta(hours=36)     # and never further apart than this
POLL = 300.0
HARD_LIMIT = 900.0


def job_state(cur: Any) -> Dict[str, Any]:
    from insight_core.markx import repo
    return repo.get_setting(cur, JOB_KEY, {}) or {}


def due(state: Dict[str, Any], stories: Dict[str, Any], now: datetime, *, busy: Optional[str] = None) -> Optional[str]:
    """Why a stats run is due now, or None: never while Mark IX's story job is busy; after a regroup (the story job's
    full run or rebuild finished since the last stats run); nightly; at most AT_MOST apart; never run."""
    if busy:
        return None
    last = datetime.fromisoformat(state["last_at"]) if state.get("last_at") else None
    if last is None:
        return "never ran"
    full = stories.get("full_at")
    if full and not stories.get("rebuild"):
        try:
            if datetime.fromisoformat(full) > last:
                return "after a regroup"
        except ValueError:
            pass
    if now - last >= AT_MOST:
        return "overdue"
    if now - last >= DAILY and now.astimezone(timezone.utc).hour in NIGHT:
        return "nightly"
    return None


def run_job(db_url: str) -> Dict[str, Any]:
    """One stats run in its own transaction, its outcome kept in mx_settings (time, rows, peak memory)."""
    import resource
    from insight_core.db import database
    from insight_core.markx import repo
    t0 = time.monotonic()
    try:
        with database.transaction(db_url) as cur:
            out = run(cur)
        out = dict(out, ok=True)
    except Exception as exc:   # noqa: BLE001 - kept, and the next look tries again
        log.exception("Source stats: the run failed")
        out = {"ok": False, "error": str(exc)[:500]}
    out["seconds"] = round(time.monotonic() - t0, 2)
    out["peak_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    with database.transaction(db_url) as cur:
        prev = job_state(cur)
        state = dict(prev, last=out)
        if out.get("ok"):
            state["last_at"] = out["at"]
        else:
            state["failed_at"] = datetime.now(timezone.utc).isoformat()
        repo.set_setting(cur, JOB_KEY, state)
    log.info("Source stats: %s", out)
    return out


def _job_main(db_url: str) -> None:
    from insight_core.logs.core.logger_config import setup_logging
    setup_logging(debug_mode=False)
    run_job(db_url)


class Runner:
    """insight-ingestion's stats loop (run_scheduler.py): every POLL seconds, a run when one is due, in a process of
    its own (or inline: `spawn=False`). Only while Mark X is on; never raises into the scheduler."""

    def __init__(self, db_url: str, *, spawn: bool = True, on: Any = None) -> None:
        from insight_core.markx.jobs import enabled
        self.db_url, self.spawn, self.on = db_url, spawn, on or enabled
        self.stop = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def why(self) -> Optional[str]:
        from insight_core.db import database
        from insight_core.markx.jobs import mark_ix_busy
        from insight_core.services.stories_service import SETTINGS_KEY
        with database.transaction(self.db_url) as cur:
            cur.execute("SELECT now(), (SELECT value FROM system_settings WHERE key = %s)", (SETTINGS_KEY,))
            now, stories = cur.fetchone()
            failed = job_state(cur).get("failed_at")
            if failed and now - datetime.fromisoformat(failed) < timedelta(hours=1):
                return None    # a failed run is tried again after an hour
            return due(job_state(cur), stories if isinstance(stories, dict) else {}, now, busy=mark_ix_busy(cur))

    def tick(self) -> Optional[str]:
        if not self.on():
            return None
        try:
            why = self.why()
            if why is None:
                return None
            log.info("Source stats: a run (%s)", why)
            if self.spawn:
                proc = multiprocessing.get_context("spawn").Process(target=_job_main, args=(self.db_url,),
                                                                    name="source-stats", daemon=True)
                proc.start()
                proc.join(HARD_LIMIT)
                if proc.is_alive():
                    proc.kill()
                    proc.join(10)
                    log.error("Source stats: the run was killed after %.0f s", HARD_LIMIT)
            else:
                run_job(self.db_url)
            return why
        except Exception:   # noqa: BLE001
            log.exception("Source stats: the tick failed")
            return None

    def start(self, poll: float = POLL) -> bool:
        if self.thread is not None or not self.on():
            return False

        def loop() -> None:
            while not self.stop.wait(poll):
                self.tick()
        self.thread = threading.Thread(target=loop, name="source-stats", daemon=True)
        self.thread.start()
        return True
