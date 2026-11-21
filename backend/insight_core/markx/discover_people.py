"""Discover → People and makers (issue 0276, Stealth v10.33; 0101's "authors in Discover").

Reddit is closed to INSIGHT (0262), so what practitioners write must come from following the PEOPLE and MAKERS
themselves. Discover's main list suggests the sites your sources link; this one suggests who is behind what your
tracks and News care about:

  (a) **authors**: the accounts your in-track and News posts quote, repost, @mention or link: an X / Bluesky /
      Telegram / YouTube account (a tweet's address is its author's: a quote or a retweet is a link to it), a code
      host's owner (github.com/<owner>, from a linked repository) and a model hub's org (huggingface.co/<org>);
      keyed as the scout keys them (scout.key_of), so a key here is a key there;
  (b) **makers**: the makers (entity_facts' maker) of the entities those posts name, each with the channels the
      official-channels module found for it (official.book: proven, would_add, refused), never a new search here.

**Where the posts come from** (30 days, WITHIN_DAYS): each topic track's in and ✓ posts (scout.in_posts: Haiku's in
from a switched-off source is none, the owner's ✗ is out) and the posts of the News rows first seen in the window
(news_posts). A post counts once a candidate however many ways it names it.

**Ranked** by the posts that brought the candidate (in a track or News), a track's post and a News post alike, then the
tracks it appears in, then its key; at least MIN_POSTS posts. Never one you follow (the scout's Followed: an account,
a site, a source's address), one you hid in Discover (discover_hidden), a reference/app/document address
(discover_rules.place_kind) or a platform that is no person (Reddit, Hacker News).

**Followable**: each suggestion carries the address Follow sends through the add path (the feed finder, then page
watching; POST /api/sources' own): an X account through the configured nitter bridge (feed_finder.bridge_feed), a
Telegram channel through its bridge, a YouTube channel's own feed, a code owner's page and a model hub org's page
through the finder / page watching (scrape regardless of a feed: no candidate is dropped for having none).

**Suggestions only**: nothing here adds a source. The makers' official channels are the official module's to add
(INSIGHT_OFFICIAL); a person is followed by the owner's tap.

    rows = hits(cur, now)                       # what the posts say (SQL), Hit rows
    got = rank(rows, skip=..., followed=...)    # pure: the ranked suggestions with their evidence
    page = suggestions(cur, now)                # both, plus the makers' channels: GET /api/discover/people
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

WITHIN_DAYS = 30
MIN_POSTS = 2          # a candidate brought by one post is chance
EVIDENCE = 5           # the posts shown with each suggestion
LIMIT = 60
TRACK_POSTS = 400      # a track's newest in posts read (scout.in_posts' own limit is the scout's)
# The scout's platform words (scout._platform_word) that are a person or a maker; "site" is Discover's main list,
# "reddit" is closed (0262), "hn" is a forum.
PERSON_WORDS = frozenset({"x", "telegram", "youtube", "bluesky", "code", "hub", "account"})
NOT_PERSON = frozenset({"reddit", "hn", "site"})
HOWS = ("quote", "repost", "mention", "link", "maker")


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


@dataclass
class Suggestion:
    key: str
    word: str
    name: str
    posts: Set[str] = field(default_factory=set)
    tracks: Set[str] = field(default_factory=set)
    news: Set[str] = field(default_factory=set)
    hows: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    evidence: List[Hit] = field(default_factory=list)


# ---- the address a key is followed at -------------------------------------------------------------------------

def followable(key: str, word: str) -> Dict[str, Any]:
    """{address, via, ready}: what Follow sends through the add path for this key, by shape (no request). `ready` is
    False only when the kind's bridge is not set (an X account without a nitter bridge)."""
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
    from insight_core.markx.official import _NOT_REPO
    if word == "code" and key.split("/", 1)[1] in _NOT_REPO:
        return None                              # a code host's own pages (features, topics, ...), no owner
    if place_kind(key, [url]):
        return None
    return key, word


# ---- the ranking (pure) ---------------------------------------------------------------------------------------

def rank(hits: Iterable[Hit], *, skip: Callable[[str, str], bool] = lambda k, w: False,
         min_posts: int = MIN_POSTS, limit: int = LIMIT) -> List[Suggestion]:
    """The candidates the hits name, those `skip` says are followed or hidden left out, ranked by their posts (a
    track's or News'), then the tracks they appear in, then their key; each with its newest EVIDENCE posts (one a post)."""
    by: Dict[str, Suggestion] = {}
    seen: Set[Tuple[str, str, str]] = set()
    for h in hits:
        if skip(h.key, h.word):
            continue
        s = by.get(h.key)
        if s is None:
            s = by[h.key] = Suggestion(h.key, h.word, h.name or h.key.split("/", 1)[-1])
        if (h.key, h.post_id, h.how) not in seen:
            seen.add((h.key, h.post_id, h.how))
            s.hows[h.how] += 1
        if h.where.startswith("track:"):
            s.tracks.add(h.where[6:])
        elif h.where == "news":
            s.news.add(h.post_id)
        if h.post_id not in s.posts:
            s.posts.add(h.post_id)
            s.evidence.append(h)
    out = [s for s in by.values() if len(s.posts) >= min_posts]
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
           "posts": len(s.posts), "tracks": tracks, "news": len(s.news), "how": dict(s.hows), "why": why,
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
        out["follow"] = followable(s.key, s.word)
    return out


# ---- what the posts say (SQL) ---------------------------------------------------------------------------------

def window_posts(cur: Any, now: datetime, *, days: int = WITHIN_DAYS) -> Dict[str, Set[str]]:
    """post id -> where it sits (`track:<name>`, `news`): each topic track's in and ✓ posts, the News rows' posts."""
    from insight_core.markx import scout, tracks
    since = now - timedelta(days=days)
    out: Dict[str, Set[str]] = defaultdict(set)
    for t in tracks.list_tracks(cur):
        if not t["topic"]:
            continue
        for pid in scout.in_posts(cur, t["id"], limit=TRACK_POSTS, since=since):
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
    from insight_core.markx import scout
    from insight_core.utils import byline
    places = window_posts(cur, now, days=days) if places is None else places
    ids = list(places)
    if not ids:
        return []
    platforms = scout._platforms(cur)
    from insight_core.markx import tracks
    cur.execute(f"""SELECT p.id::text, COALESCE(p.title, ''), p.url, {tracks._date('p')}, s.handle_or_url,
                           ({byline.retweet_sql('p')} OR {byline.reposted_sql('p')})
                      FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = ANY(%s::uuid[])""", (ids,))
    meta = {pid: (title, url, at, own, bool(rt)) for pid, title, url, at, own, rt in cur.fetchall()}
    out: List[Hit] = []

    def add(pid: str, url: str, how: str) -> None:
        got = person_key(url, platforms)
        if got is None or pid not in meta:
            return
        key, word = got
        title, purl, at, own, _ = meta[pid]
        if (own or "").split("://", 1)[-1].lower().removeprefix("www.").startswith(key):
            return                                   # a source naming itself
        for where in places[pid]:
            out.append(Hit(pid, where, key, word, how, purl or url, title, at, key.split("/", 1)[-1]))

    for pid, (_, url, _, _, rt) in meta.items():
        if rt and url:
            add(pid, url, "repost")                 # a retweet's address is the original tweet: its author's
    cur.execute("""SELECT l.post_id::text, l.target_url, l.kind FROM post_links l
                    WHERE l.post_id = ANY(%s::uuid[])
                      AND ((NOT l.boilerplate AND l.kind = 'link') OR l.kind = 'mention')""", (ids,))
    from insight_core.utils.addresses import is_tweet
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
        title, url, at, _, _ = meta.get(pid, ("", "", None, "", False))
        for where in places.get(pid, ()):
            out.append(Hit(pid, where, f"maker:{mid}", "maker", "maker", url or "", title, at, name or ""))
    return out


def _skip(cur: Any) -> Callable[[str, str], bool]:
    """Followed (the scout's Followed) or hidden in Discover; a maker whose official channel you already follow."""
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
    """GET /api/discover/people: {authors, makers, window_days, posts}: each ranked list with its evidence and where it
    is followed. A maker with a channel already followed (an `added` row, or a source on it) is left out."""
    from insight_core.markx import official
    now = now or datetime.now(timezone.utc)
    places = window_posts(cur, now, days=days)
    rows = hits(cur, now, days=days, places=places)
    ranked = rank(rows, skip=_skip(cur), limit=limit * 2)
    makers = [s for s in ranked if s.word == "maker"]
    book = official.book(cur, [s.key.split(":", 1)[1] for s in makers])
    authors_out = [shown(s) for s in ranked if s.word != "maker"][:limit]
    makers_out = []
    for s in makers:
        chans = book.get(s.key.split(":", 1)[1], [])
        if any(c.get("state") == "added" or c.get("source_id") for c in chans):
            continue                                 # you follow its own channel already
        makers_out.append(shown(s, chans))
    return {"window_days": days, "posts": len(places), "authors": authors_out, "makers": makers_out[:limit]}
