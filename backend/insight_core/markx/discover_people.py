"""Discover → People and makers: who is behind what your tracks and News care about, as suggestions to follow.

  (a) **authors**: the accounts your in-track and News posts quote, repost, @mention or link (X, Bluesky, Telegram,
      YouTube, a code host's owner, a model hub's org), keyed as the scout keys them (scout.key_of);
  (b) **makers**: the makers (entity_facts) of the entities those posts name, with the channels markx/official.py
      found for them (never a new search here).

The posts: each topic track's posts in the last WITHIN_DAYS (track_feed.track_posts) and the News rows' first seen in
the window. Ranked by posts, then tracks, then key; kept with 2+ posts from MIN_SOURCES of your sources. Never one you
follow, hid in Discover, a reference/app/document address, or a platform that is no person. An account is a person's
only by the owner's yes in mx_entity_handles (handles.py's rule); a person's accounts fold into `person:<id>`, and a
person you follow under any account is left out. Each suggestion carries the address Follow sends through the add path.
Nothing here adds a source.

    rows = hits(cur, now)                       # what the posts say (SQL), Hit rows
    got = rank(rows, skip=..., people=...)      # pure: the ranked suggestions with their evidence
    page = suggestions(cur, now)                # both, plus the makers' channels: GET /api/discover/people
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

WITHIN_DAYS = 30
MIN_POSTS = 3          # (kept for callers; the floor is MIN_SOURCES only) ...
MIN_SOURCES = 2        # ... or 2+ posts from 2+ of your sources
EVIDENCE = 5           # the posts shown with each suggestion
LIMIT = 60
TRACK_POSTS = 400      # a track's newest posts of the window read
# The scout's platform words (scout._platform_word) that are a person or a maker; "site" is Discover's main list,
# "reddit" is closed, "hn" is a forum.
PERSON_WORDS = frozenset({"x", "telegram", "youtube", "bluesky", "code", "hub", "account"})
NOT_PERSON = frozenset({"reddit", "hn", "site"})
CODE_HOST = "git" + "hub.com/"


@dataclass(frozen=True)
class Hit:
    """One post naming one candidate: where the post sits (`track:<name>` or `news`), and how it names it."""
    post_id: str
    where: str
    key: str
    word: str            # the scout's platform word (x, code, hub, ...) or "maker"
    how: str             # quote | repost | mention | link | maker
    url: str = ""
    title: str = ""
    at: Optional[datetime] = None
    name: str = ""       # a maker's name; an account's handle otherwise
    source_id: str = ""  # the post's source


@dataclass
class Suggestion:
    key: str
    word: str
    name: str
    posts: Set[str] = field(default_factory=set)
    sources: Set[str] = field(default_factory=set)
    accounts: Set[str] = field(default_factory=set)   # the keys folded into it (one person's accounts)
    tracks: Set[str] = field(default_factory=set)
    news: Set[str] = field(default_factory=set)
    hows: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    evidence: List[Hit] = field(default_factory=list)


# ---- the address a key is followed at -------------------------------------------------------------------------

def followable(key: str, word: str) -> Dict[str, Any]:
    """{address, via, feed, ready}: what Follow sends through the add path for this key, by shape (no request). `ready`
    is False only when the kind's bridge is not set (an X account without a nitter bridge)."""
    from insight_core.ingestion.feed_finder import bridge_feed
    address = key if key.startswith(("http://", "https://")) else "https://" + key
    if word in ("x", "telegram"):
        got = bridge_feed(address)
        bridge = got[1] if got else None
        return {"address": address, "via": f"{word} bridge", "feed": bridge, "ready": bool(bridge)}
    if word == "youtube":
        return {"address": address, "via": "feed finder (the channel's feed)", "feed": None, "ready": True}
    if word == "code":
        return {"address": address, "via": "feed finder (the owner's activity feed), else page watching",
                "feed": address.rstrip("/") + ".atom", "ready": True}
    return {"address": address, "via": "feed finder, else page watching", "feed": None, "ready": True}


def person_key(url: str, platforms: Optional[Dict[str, Tuple[str, ...]]] = None) -> Optional[Tuple[str, str]]:
    """(key, word) when the address is a person's or maker's account (scout.key_of's key), else None."""
    from insight_core.markx.scout import _platform_word, key_of
    from insight_core.utils.discover_rules import paper_address, place_kind
    if not url or paper_address(url):
        return None
    key, _, platform = key_of(url, platforms)
    if not key or "/" not in key.strip("/"):
        return None                              # a site's root, or a platform's own home: no account
    word = _platform_word(key, platform)
    if word in NOT_PERSON or word not in PERSON_WORDS:
        return None
    if "?" in key or (word in ("code", "hub") and key.count("/") != 1):
        return None                              # an owner, never a search feed or a deeper page
    if word == "youtube" and not key.split("/", 1)[1].startswith(("@", "channel/", "c/", "user/")):
        return None                              # a playlist or a video page: no channel (measured: youtube.com/playlist)
    if word == "account" and not key.split("/", 1)[1].startswith("@"):
        return None                              # a site's section the platform rules key (measured: a news site's /tech)
    from insight_core.markx.official import _NOT_REPO
    if word == "code" and key.split("/", 1)[1] in _NOT_REPO:
        return None                              # a code host's own pages (features, topics, ...), no owner
    if place_kind(key, [url]):
        return None
    return key, word


# ---- people: one person's accounts, and whether you follow them (the handles module's links only) ---------------

HANDLE_PLATFORMS = (("x.com/", "x"), (CODE_HOST, "github"), ("huggingface.co/", "hf"), ("t.me/", "telegram"),
                    ("bsky.app/profile/", "bluesky"))


def handle_of(key: str) -> Optional[Tuple[str, str]]:
    """A candidate key as the handles module keys an account ((platform, handle)), or None."""
    for prefix, platform in HANDLE_PLATFORMS:
        if key.startswith(prefix):
            h = key[len(prefix):].split("/", 1)[0].lstrip("@").casefold()
            return (platform, h) if h else None
    return None


@dataclass
class People:
    """(platform, handle) -> (person id, name), from the owner's yes in mx_entity_handles; `followed`: the persons you
    follow under any account or site."""
    handles: Dict[Tuple[str, str], Tuple[str, str]] = field(default_factory=dict)
    followed: Set[str] = field(default_factory=set)

    def of(self, key: str) -> Optional[Tuple[str, str]]:
        h = handle_of(key)
        return self.handles.get(h) if h else None


def people(cur: Any) -> People:
    """The handles the owner said are a person's (newest answer yes), and the persons followed: a yes handle that is
    a followed source's account (handles.account_of), a source the owner said is theirs (mx_entity_sources yes), or a
    live confirmed voice of theirs (voices.entity_id)."""
    from insight_core.markx.handles import account_of
    cur.execute("""SELECT DISTINCT ON (h.entity_id, h.platform, h.handle) h.entity_id::text, h.platform, h.handle,
                          h.answer, COALESCE(e.shown_name, e.name)
                     FROM mx_entity_handles h JOIN mx_entities e ON e.id = h.entity_id
                    WHERE e.status <> 'not_entity'
                    ORDER BY h.entity_id, h.platform, h.handle, h.created_at DESC, h.id DESC""")
    out = People()
    for eid, platform, handle, answer, name in cur.fetchall():
        if answer == "yes":
            out.handles[(platform, handle.casefold())] = (eid, name or handle)
    cur.execute("SELECT platform, handle_or_url FROM sources WHERE enabled")
    for platform, handle in cur.fetchall():
        acc = account_of(platform, handle)
        if acc and acc in out.handles:
            out.followed.add(out.handles[acc][0])
    cur.execute("""SELECT DISTINCT ON (a.entity_id, a.source_id) a.entity_id::text, a.answer
                     FROM mx_entity_sources a JOIN sources s ON s.id = a.source_id AND s.enabled
                    ORDER BY a.entity_id, a.source_id, a.created_at DESC, a.id DESC""")
    out.followed |= {eid for eid, answer in cur.fetchall() if answer == "yes"}
    cur.execute("""SELECT DISTINCT v.entity_id::text FROM voices v JOIN sources s ON s.voice_id = v.id AND s.enabled
                    WHERE v.entity_id IS NOT NULL AND v.confirmed_at IS NOT NULL AND v.removed_at IS NULL""")
    out.followed |= {eid for (eid,) in cur.fetchall()}
    return out


# ---- the ranking (pure) ---------------------------------------------------------------------------------------

def rank(hits: Iterable[Hit], *, skip: Callable[[str, str], bool] = lambda k, w: False,
         people: Optional[People] = None, min_posts: int = MIN_POSTS, min_sources: int = MIN_SOURCES,
         limit: int = LIMIT) -> List[Suggestion]:
    """The candidates the hits name, those `skip` says are followed or hidden left out, ranked by their posts (a
    track's or News'), then the tracks they appear in, then their key; each with its newest EVIDENCE posts (one a post).
    Kept: min_posts posts, or 2+ posts from min_sources sources. `people`: a person's accounts are one suggestion
    (`person:<id>`), and a person you follow under any account or source is left out."""
    by: Dict[str, Suggestion] = {}
    seen: Set[Tuple[str, str, str]] = set()
    for h in hits:
        if skip(h.key, h.word):
            continue
        key, name = h.key, h.name
        person = people.of(h.key) if people is not None and h.word != "maker" else None
        if person is not None:
            if person[0] in people.followed:
                continue                             # you follow this person under another account or site
            key, name = f"person:{person[0]}", person[1]
        s = by.get(key)
        if s is None:
            s = by[key] = Suggestion(key, h.word, name or key.split("/", 1)[-1])
        s.accounts.add(h.key)
        if h.source_id:
            s.sources.add(h.source_id)
        if (key, h.post_id, h.how) not in seen:
            seen.add((key, h.post_id, h.how))
            s.hows[h.how] += 1
        if h.where.startswith("track:"):
            s.tracks.add(h.where[6:])
        elif h.where == "news":
            s.news.add(h.post_id)
        if h.post_id not in s.posts:
            s.posts.add(h.post_id)
            s.evidence.append(h)
    out = [s for s in by.values()
           if len(s.posts) >= 2 and len(s.sources) >= min_sources]   # 2+ of your sources only (0276)
    for s in out:
        s.evidence.sort(key=lambda h: h.at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        s.evidence = s.evidence[:EVIDENCE]
    out.sort(key=lambda s: (-len(s.posts), -len(s.tracks), s.key))
    return out[:limit]


def shown(s: Suggestion, channels: Sequence[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """A suggestion as the page shows it: who, why (N posts in which tracks and News), how they were named, the
    posts that brought it, and where it is followed (an author's address; a maker's official channels)."""
    tracks = sorted(s.tracks)
    why = f"{len(s.posts)} of your posts in 30 days" + (f" in {', '.join(tracks)}" if tracks else "") + \
          (f"{' and' if tracks else ' in'} News ({len(s.news)})" if s.news else "")
    out = {"key": s.key, "kind": "maker" if s.word == "maker" else "author", "platform": s.word, "name": s.name,
           "posts": len(s.posts), "sources": len(s.sources), "accounts": sorted(s.accounts) if s.word != "maker" else [],
           "tracks": tracks, "news": len(s.news), "how": dict(s.hows), "why": why,
           "evidence": [{"post_id": h.post_id, "title": h.title, "url": h.url, "where": h.where, "how": h.how,
                         "at": h.at.isoformat() if h.at else None} for h in s.evidence]}
    if s.word == "maker":
        out["channels"] = [{"key": c.get("key"), "kind": c.get("kind"), "state": c.get("state"),
                            "address": (c.get("follow") or {}).get("address") if isinstance(c.get("follow"), dict)
                            else c.get("follow"), "source_id": c.get("source_id")} for c in channels]
        out["follow"] = None if not channels else {"via": "official channels (INSIGHT_OFFICIAL)",
                                                   "ready": any(c.get("state") in ("proven", "would_add", "added")
                                                                for c in channels)}
    else:
        account = s.key if not s.key.startswith("person:") else sorted(s.accounts)[0]
        got = person_key("https://" + account)
        out["follow"] = followable(account, got[1] if got else s.word)
    return out


# ---- what the posts say (SQL) ---------------------------------------------------------------------------------

def window_posts(cur: Any, now: datetime, *, days: int = WITHIN_DAYS) -> Dict[str, Set[str]]:
    """post id -> where it sits (`track:<name>`, `news`): each topic track's posts placed in it or joined (its newest
    TRACK_POSTS of the window), and the posts of the News rows first seen in the window."""
    from insight_core.markx import track_feed, tracks
    since = now - timedelta(days=days)
    out: Dict[str, Set[str]] = defaultdict(set)
    for t in tracks.list_tracks(cur):
        if not t["topic"]:
            continue
        ids = track_feed.track_posts(cur, t["id"]) or []
        if not ids:
            continue
        cur.execute(f"""SELECT p.id::text FROM posts p WHERE p.id = ANY(%s::uuid[]) AND {tracks._date('p')} >= %s
                         ORDER BY {tracks._date('p')} DESC LIMIT %s""", (ids, since, TRACK_POSTS))
        for (pid,) in cur.fetchall():
            out[pid].add(f"track:{t['name']}")
    cur.execute("""SELECT np.post_id::text FROM news_posts np JOIN news_stories n ON n.id = np.news_id
                    WHERE n.first_at >= %s""", (since,))
    for (pid,) in cur.fetchall():
        out[pid].add("news")
    return dict(out)


def hits(cur: Any, now: datetime, *, days: int = WITHIN_DAYS,
         places: Optional[Dict[str, Set[str]]] = None) -> List[Hit]:
    """Every (post, candidate) the window's posts give: their links and @mentions to an account (a quote is a link to
    the quoted tweet), a repost's original author, and the makers of the entities they name."""
    from insight_core.markx import scout, tracks
    from insight_core.utils import byline
    from insight_core.utils.addresses import is_tweet
    places = window_posts(cur, now, days=days) if places is None else places
    ids = list(places)
    if not ids:
        return []
    platforms = scout._platforms(cur)
    cur.execute(f"""SELECT p.id::text, COALESCE(p.title, ''), p.url, {tracks._date('p')}, s.handle_or_url,
                           ({byline.retweet_sql('p')} OR {byline.reposted_sql('p')}), p.source_id::text
                      FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ANY(%s::uuid[])""", (ids,))
    meta = {pid: (title, url, at, own, bool(rt), sid) for pid, title, url, at, own, rt, sid in cur.fetchall()}
    out: List[Hit] = []

    def add(pid: str, url: str, how: str) -> None:
        got = person_key(url, platforms)
        if got is None or pid not in meta:
            return
        key, word = got
        title, purl, at, own, _, sid = meta[pid]
        if (own or "").split("://", 1)[-1].lower().removeprefix("www.").startswith(key):
            return                                   # a source naming itself
        for where in places[pid]:
            out.append(Hit(pid, where, key, word, how, purl or url, title, at, key.split("/", 1)[-1], sid))

    for pid, (_, url, _, _, rt, _) in meta.items():
        if rt and url:
            add(pid, url, "repost")                 # a retweet's address is the original tweet: its author's
    cur.execute("""SELECT l.post_id::text, l.target_url, l.kind FROM post_links l
                    WHERE l.post_id = ANY(%s::uuid[])
                      AND ((NOT l.boilerplate AND l.kind = 'link') OR l.kind = 'mention')""", (ids,))
    for pid, url, kind in cur.fetchall():
        add(pid, url, "mention" if kind == "mention" else ("quote" if is_tweet(url) else "link"))
    out.extend(maker_hits(cur, places, meta))
    return out


def maker_hits(cur: Any, places: Dict[str, Set[str]], meta: Dict[str, Tuple]) -> List[Hit]:
    """The makers of the entities the posts name (the current facts' maker, entity_facts' one owner), a post a maker."""
    cur.execute("""SELECT DISTINCT m.post_id::text, f.maker_id::text, COALESCE(me.shown_name, me.name)
                     FROM mx_mentions_now m
                     JOIN mx_entity_facts f ON f.entity_id = m.entity_id AND f.superseded_at IS NULL
                     JOIN mx_entities me ON me.id = f.maker_id
                    WHERE m.post_id = ANY(%s::uuid[]) AND f.maker_id IS NOT NULL AND me.status <> 'not_entity'""",
                (list(places),))
    out = []
    for pid, mid, name in cur.fetchall():
        title, url, at, _, _, sid = meta.get(pid, ("", "", None, "", False, ""))
        for where in places.get(pid, ()):
            out.append(Hit(pid, where, f"maker:{mid}", "maker", "maker", url or "", title, at, name or "", sid))
    return out


def _skip(cur: Any) -> Callable[[str, str], bool]:
    """Followed (the scout's Followed) or hidden in Discover."""
    from insight_core.db.repo_stories import StoriesRepository
    from insight_core.markx import scout
    followed = scout._followed(cur)
    hidden = StoriesRepository.hidden(cur)

    def skip(key: str, word: str) -> bool:
        if word == "maker":
            return False
        site = key.split("/", 1)[0]
        return key in hidden or scout.is_followed(key, site, True, followed)
    return skip


def suggestions(cur: Any, now: Optional[datetime] = None, *, limit: int = LIMIT, days: int = WITHIN_DAYS
                ) -> Dict[str, Any]:
    """{window_days, posts, authors, makers, built_at}: each ranked list with its evidence and where it is followed.
    A maker with a channel already followed (an `added` row, or a source on it) is left out."""
    from insight_core.markx import official
    now = now or datetime.now(timezone.utc)
    places = window_posts(cur, now, days=days)
    rows = hits(cur, now, days=days, places=places)
    ranked = rank(rows, skip=_skip(cur), people=people(cur), limit=limit * 2)
    makers = [s for s in ranked if s.word == "maker"]
    book = official.book(cur, [s.key.split(":", 1)[1] for s in makers])
    authors_out = [shown(s) for s in ranked if s.word != "maker"][:limit]
    makers_out = []
    for s in makers:
        chans = book.get(s.key.split(":", 1)[1], [])
        if any(c.get("state") == "added" or c.get("source_id") for c in chans):
            continue                                 # you follow its own channel already
        makers_out.append(shown(s, chans))
    return {"window_days": days, "posts": len(places), "authors": authors_out, "makers": makers_out[:limit],
            "built_at": now.isoformat()}


# ---- kept: built in the jobs process's "discover" view, served from system_settings --------------------------------
# A build takes about a second (0276), so it is never made on the request.

KEY = "discover_people"
KEEP_FOR = timedelta(hours=1)      # a kept list this old is built again at the next "discover" job


def due(cur: Any, now: Optional[datetime] = None) -> bool:
    """Whether the kept list is missing or KEEP_FOR old."""
    from insight_core.db.repo_operations import SystemSettingsRepository
    row = SystemSettingsRepository.get(cur, KEY)
    now = now or datetime.now(timezone.utc)
    return row is None or row[1] is None or now - row[1] >= KEEP_FOR


def keep(cur: Any, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Build the list (LIMIT a kind) and keep it: {built, authors, makers, seconds}. The jobs process's, never the API's."""
    import json
    import time
    from insight_core.db.repo_operations import SystemSettingsRepository
    t = time.monotonic()
    got = suggestions(cur, now)
    SystemSettingsRepository.upsert(cur, KEY, json.loads(json.dumps(got, default=str)))
    return {"built": True, "authors": len(got["authors"]), "makers": len(got["makers"]),
            "seconds": round(time.monotonic() - t, 2)}


def served(cur: Any, *, limit: int = 30, now: Optional[datetime] = None) -> Dict[str, Any]:
    """GET /api/discover/people: the kept list (its first `limit` of each kind) with `built_at` and `refreshing`; when
    it is missing or due, the "discover" job is wanted (markx/jobs.py) and the older list (or an empty one) is served."""
    from insight_core.db.repo_operations import SystemSettingsRepository
    from insight_core.markx import jobs
    row = SystemSettingsRepository.get(cur, KEY)
    value = (row[0] if row else None) or {}
    refreshing = False
    if due(cur, now):
        jobs.want(cur, "discover")
        refreshing = True
    return {"window_days": value.get("window_days", WITHIN_DAYS), "posts": value.get("posts", 0),
            "authors": (value.get("authors") or [])[:limit], "makers": (value.get("makers") or [])[:limit],
            "built_at": value.get("built_at"), "refreshing": refreshing}
