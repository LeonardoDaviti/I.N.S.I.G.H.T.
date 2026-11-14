"""Official channels (issue 0196, Stealth v10.18): INSIGHT follows the original postings by itself.

An event your sources reported whose actor's own post is not in the story: who is the actor, which of its own channels
are proven, and (switched on) the proven, wanted ones followed automatically, each with its item filter. Non-official
sources are never added by this module. The decision is one module's, keyed on the actor (the channel book): an
actor's channels are found once and reused by its later events.

    counts = run(db_url, now=...)          # the jobs process's pass (bounded; resumable; Postgres state only)
    rows = book(cur, actor_ids)            # every reader: {actor: [channel rows]}, one query
    page = view(cur)                       # the review view: what was found, why, from where, how; undo
    undo(cur, channel_id)                  # the owner's Undo: the source switched off, never added again
    pages = pages_wanted(cur, now, ...)    # the originals step's `cited` planner (pages 2+ voices link)

**The pipeline** (every discovery): discovered (a candidate, with where it came from) -> suggested (the review view:
why, from where, how) -> checked by the worker (one `source_judge` question on the add path's test read: worth adding,
fits the reader's tracks and sources; its item filter) -> added (official only; on, under the day's cap) or kept as
`would_add` (Shadow) or `refused` with why.

**Events** (services/discover_main_source.py's rules, deepened for one voice): the Mark X stories of the last
WITHIN_DAYS of an announced type (event_types.ANNOUNCED: never a lawsuit, a regulator's action, a leak), with one
voice or more. The actor's own post in the story: nothing to do (`held`).

**The actor**: the story's maker by identity, else the org or person the readings name as the event's (0170's rule);
else the web search's (`websearch` kind, guide websearch-official-v1: one question an actor-thing pair, kept in
mx_official_lookups and reused). A maker the search found for a makerless thing is written once, through identity's
one owner (entity_facts.set_maker, by `web`).

**Candidates**, no request first: the actor's own pages the members carry (0170's `_own_pages`) -> their channel
(`channel_of`: an X account, a Telegram channel, a site's section); the code addresses of the actor's things and of
the event's things (0138's mx_entity_addresses `code`) -> `<repo>/releases.atom`; the actor's handles (0168: the
owner's yes, its own sources' accounts) -> its X account; only when these give none, the web search's channels and its
announcement's channel. Cut by shape before any request: a site's root, one page, a platform's or code host's or model
hub's page that is no account, help, docs, CDN and file hosts, a forum thread (discover_main_source.channel_of).

**Proof** (code; all three, else no channel):
  1. owned by the actor: the channel's handle, site name or repository owner is one of the actor's names or a name of
     a thing it makes (0170's `owned_by`), or the web search's actor's name or own site; an employee's account is not
     the actor's; a repository the search names when the post links another of the same name is refused;
  2. a dated stream: the add path's test read (source_judge's: the feed finder, then page watching; an account through
     its kind) gives MIN_DATED+ dated items;
  3. announcements: a releases feed, an account, a section whose read holds the event's own page or a page your
     sources link, or whose path is an announcing one (ANNOUNCING).
Plus **not covered**: an enabled source on the channel that carries the page means the gap is a join, a section or a
backfill: `covered`, never a new source.

**Wanted**: the actor has 2+ announced events in WITHIN_DAYS, or the event 3+ voices; one channel of a kind a site;
the worker's judgement says follow and fits the reader. Else `refused` with its reasons, asked again after
REFUSED_DAYS.

**Add** (mode `on`): through the add path every add takes (scout.default_add_source: POST /api/sources' own,
the address the finder or page watching resolved at the test read), settings {added_by: official, official: {...}},
the item filter (utils/item_filter.put), then the archive back to the reading window (follow_archive). At most
ADDS_PER_DAY (config INSIGHT_OFFICIAL_ADDS_PER_DAY, default 5) a day: above it they wait as `would_add`. Undo turns
the source off (its posts kept) and the channel is never added again by the module.

**Modes** (INSIGHT_OFFICIAL): `off`; `shadow` (the default: every step but the add, recorded `would_add`); `on`.

Runs in the jobs process (markx/jobs.py, the job `official`), never in the API: at most EVENTS_PER_RUN events,
READS_PER_RUN test reads and LOOKUPS_PER_RUN web-search questions a pass; its state in Postgres (mx_official_events,
mx_official_channels, mx_official_lookups, mx_official_runs; keep everything: a new state is a new row).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

log = logging.getLogger(__name__)

MODES = ("off", "shadow", "on")
WITHIN_DAYS = 30
EVENTS_SCAN = 150                 # the newest unsettled events whose stories a pass loads (memory bound)
EVENTS_PER_RUN = 20
READS_PER_RUN = 10                # test reads (the finder / page watching / a kind's read) a pass
LOOKUPS_PER_RUN = 4               # web-search questions asked a pass
ADDS_PER_DAY = 5                  # the first weeks' cap (INSIGHT_OFFICIAL_ADDS_PER_DAY)
REFUSED_DAYS = 90                 # a refused channel is looked at again after this
WAIT_DAYS = 7                     # a lookup or a judgement not answered in this long: given up (asked again later)
MIN_DATED = 3                     # a dated stream: this many dated items read
GATE_EVENTS, GATE_VOICES = 2, 3   # wanted: the actor's announced events in WITHIN_DAYS, or the event's voices
PRIORITY = -2                     # the worker's questions: after the owner's taps (-5), before the planners (0)
LOOKUP_GUIDE = "websearch-official-v1"
LOOKUP_KIND = "websearch"
LOOKUP_SEARCHES = 4
STATES = ("candidate", "proven", "would_add", "added", "undone", "refused", "covered")
# A section's path that announces (a blog, a newsroom, releases, changelogs): its read need not hold the event's page.
ANNOUNCING = re.compile(r"(^|/)(news|newsroom|blog|blogs|press|press-releases|pressroom|announcements?|releases?|"
                        r"updates?|changelog|changes|whats-new|what-s-new|research|engineering|stories|posts|articles|"
                        r"insights|media)(/|$)", re.I)
_GITHUB_REPO = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)
_NOT_REPO = frozenset({"orgs", "topics", "sponsors", "features", "marketplace", "settings", "about", "pricing",
                       "collections", "trending", "apps", "login", "join", "explore", "enterprise", "security"})
_X_ACCOUNT = re.compile(r"^https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/?(?:[?#].*)?$", re.I)
_YOUTUBE = re.compile(r"^https?://(?:www\.)?youtube\.com/(@[A-Za-z0-9_.-]+|channel/[A-Za-z0-9_-]+)/?", re.I)
_TG = re.compile(r"^https?://t\.me/(?:s/)?([A-Za-z0-9_]{4,})/?$", re.I)


def mode() -> str:
    got = (os.getenv("INSIGHT_OFFICIAL") or "shadow").strip().lower()
    return got if got in MODES else "shadow"


def adds_per_day() -> int:
    try:
        return max(0, int(os.getenv("INSIGHT_OFFICIAL_ADDS_PER_DAY", str(ADDS_PER_DAY))))
    except ValueError:
        return ADDS_PER_DAY


# ---- channels (pure) ---------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Chan:
    key: str            # x.com/<user>, t.me/<c>, youtube.com/@<c>, <site><prefix>, github.com/<o>/<r>
    kind: str           # x | telegram | youtube | section | releases
    address: str        # what the test read (and the add) starts from
    owner: str          # the handle, the site's name, the repository's owner
    site: str = ""      # the registrable site (sections), the repository (releases)
    prefix: Optional[str] = None


def channel(url: str) -> Optional[Chan]:
    """The channel a page or an account of an actor's is published in, by shape (no request), or None: an X or Telegram
    account (a post's author), a YouTube channel, a GitHub repository's releases feed (the repository, never an org's
    page), a site's section (never its root, a help, docs or file host, a forum thread: discover_main_source.channel_of).
    """
    from insight_core.services import discover_main_source as D
    from insight_core.utils.addresses import site_of, host_of
    url = (url or "").strip()
    if not url:
        return None
    if "://" not in url:
        url = "https://" + url
    m = _GITHUB_REPO.match(url)
    if m:
        o, r = m.group(1), re.sub(r"\.git$", "", m.group(2))
        if o.lower() in _NOT_REPO or not r or r.startswith("."):
            return None
        return Chan(f"github.com/{o.lower()}/{r.lower()}", "releases", f"https://github.com/{o}/{r}/releases.atom",
                    o.lower(), f"github.com/{o.lower()}/{r.lower()}")
    m = _X_ACCOUNT.match(url)
    if m and m.group(1).lower() not in ("home", "search", "i", "explore", "intent", "share", "hashtag"):
        u = m.group(1)
        return Chan(f"x.com/{u.lower()}", "x", f"https://x.com/{u}", u.lower(), "x.com")
    m = _YOUTUBE.match(url)
    if m:
        c = m.group(1)
        return Chan(f"youtube.com/{c.lower()}", "youtube", f"https://www.youtube.com/{c}", c.lstrip("@").lower(),
                    "youtube.com")
    m = _TG.match(url)
    if m:
        c = m.group(1)
        return Chan(f"t.me/{c.lower()}", "telegram", f"https://t.me/{c}", c.lower(), "t.me")
    ch = D.channel_of(url)
    if ch is None:
        return None
    if ch.platform == "x":
        u = ch.key.split("/", 1)[1]
        return Chan(ch.key, "x", ch.url, u, "x.com")
    if ch.platform == "telegram":
        c = ch.key.split("/", 1)[1]
        return Chan(ch.key, "telegram", ch.url, c, "t.me")
    if not ch.prefix or ch.prefix == "/":
        return None                          # a site's root says who, not where
    return Chan(ch.key, "section", ch.url, (site_of(host_of(ch.url)) or "").split(".")[0], ch.site, ch.prefix)


def _forms(name: Optional[str]) -> Set[str]:
    from insight_core.markx import names as N
    sq = N.squash(N.key(name or ""))
    out = {sq} if len(sq) >= 3 else set()
    words = [w for w in re.split(r"[^0-9a-z]+", N.key(name or "")) if w]
    if len(words) > 1 and len(words[0]) >= 4:
        out.add(words[0])     # "Acme Labs" -> acme (a company's site and account carry its first word)
    return out


def owned(ch: Chan, *, mk: Any = None, actor: Optional[str] = None, names: Sequence[str] = (),
          sites: Sequence[str] = (), repos: Sequence[str] = ()) -> Optional[str]:
    """How the channel is the actor's (a short reason), or None: its owner (handle, site name, repository owner) is
    one of the actor's names or a thing it makes (0170's owned_by, through the story's Makers `mk`), or one of `names`'
    forms (the web search's actor), or its site one of `sites` (the actor's own site, as found). A code address of a
    thing (0138) is no proof of its owner: posts link third parties' plugins and forks of a thing (measured: 6 of the
    first 99 candidates), so a repository counts only when its owner holds the actor's name. `repos` is kept for the
    callers' disagreement check.)"""
    from insight_core.markx import names as N
    from insight_core.services import discover_main_source as D
    from insight_core.utils.addresses import site_of, host_of
    if mk is not None and actor and D.owned_by(mk, ch.owner, actor):
        return f"{ch.owner} is one of its names"
    forms = set()
    for n in names:
        forms |= _forms(n)
    if forms and any(f in forms for f in N.handle_forms(ch.owner)):
        return f"{ch.owner} is its name"
    # Discover's name rule (discover_rules.own_names / same_owner, 0109): a word of the owner is one of the actor's
    # names (4+ letters, its words, its words run together, a parenthesised other name), or starts or ends with it.
    from insight_core.utils.discover_rules import own_names, same_owner
    held: Set[str] = set()
    for n in names:
        for part in [n, *re.findall(r"\(([^)]*)\)", n or ""), re.sub(r"\([^)]*\)", " ", n or "")]:
            held |= own_names(part.replace("@", " "))
    if held and same_owner("owner/" + ch.owner, held):
        return f"{ch.owner} holds its name"
    if ch.kind == "section":
        own = {site_of(host_of(s if "://" in s else "https://" + s)) for s in sites if s}
        if ch.site and ch.site in own:
            return f"{ch.site} is its own site"
    return None


# ---- the rows ---------------------------------------------------------------------------------------------------

COLS = ("id", "key", "kind", "actor_id", "actor_name", "follow", "page_watch", "state", "why", "evidence", "judge_id",
        "rule", "filter_id", "source_id", "events", "created_at", "decided_at")


def _rows(cur: Any, where: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    cur.execute(f"SELECT {', '.join(COLS)} FROM mx_official_channels WHERE superseded_at IS NULL AND {where}", params)
    out = []
    for r in cur.fetchall():
        row = dict(zip(COLS, r))
        for k in ("id", "actor_id", "judge_id", "filter_id", "source_id"):
            row[k] = str(row[k]) if row[k] is not None else None
        out.append(row)
    return out


def current(cur: Any, key: str) -> Optional[Dict[str, Any]]:
    got = _rows(cur, "key = %s", (key,))
    return got[0] if got else None


def put(cur: Any, key: str, kind: str, state: str, *, why: str, before: Optional[Dict[str, Any]] = None,
        **fields: Any) -> str:
    """The channel's new current row (the old one superseded, keep everything): `before`'s fields carried over unless
    given. Returns its id."""
    assert state in STATES
    base = {k: before.get(k) for k in ("actor_id", "actor_name", "follow", "page_watch", "evidence", "judge_id",
                                       "rule", "filter_id", "source_id", "events")} if before else {}
    base.update(fields)
    events = sorted(set(base.get("events") or []))
    if before:
        cur.execute("UPDATE mx_official_channels SET superseded_at = now() WHERE id = %s AND superseded_at IS NULL",
                    (before["id"],))
    cur.execute("""INSERT INTO mx_official_channels (key, kind, actor_id, actor_name, follow, page_watch, state, why,
                                                      evidence, judge_id, rule, filter_id, source_id, events, decided_at)
                   VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, %s::jsonb, %s, %s, %s,
                           CASE WHEN %s IN ('candidate', 'proven') THEN NULL ELSE now() END)
                   RETURNING id::text""",
                (key, kind, base.get("actor_id"), base.get("actor_name"), base.get("follow"),
                 json.dumps(base.get("page_watch")) if base.get("page_watch") is not None else None, state, why[:500],
                 json.dumps(base.get("evidence") or {}, default=str), base.get("judge_id"),
                 json.dumps(base.get("rule")) if base.get("rule") is not None else None, base.get("filter_id"),
                 base.get("source_id"), events, state))
    nid = cur.fetchone()[0]
    if before:
        cur.execute("UPDATE mx_official_channels SET superseded_by = %s WHERE id = %s", (nid, before["id"]))
    return nid


def book(cur: Any, actor_ids: Iterable[str]) -> Dict[str, List[Dict[str, Any]]]:
    """Every reader: {actor: its channels' current rows}, one query by the actor ids a page holds."""
    ids = sorted({a for a in actor_ids if a})
    if not ids:
        return {}
    out: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in _rows(cur, "actor_id = ANY(%s::uuid[]) ORDER BY created_at DESC", (ids,)):
        out[r["actor_id"]].append(_shown(r))
    return dict(out)


def _shown(r: Dict[str, Any]) -> Dict[str, Any]:
    ev = r.get("evidence") or {}
    return {"id": r["id"], "key": r["key"], "kind": r["kind"], "state": r["state"], "why": r["why"],
            "actor": {"id": r["actor_id"], "name": r["actor_name"]}, "follow": r["follow"],
            "from": ev.get("from"), "owned": ev.get("owned"), "proof": ev.get("proof"), "judge": ev.get("judge"),
            "filter": r.get("rule"), "source_id": r["source_id"], "events": ev.get("events_shown") or [],
            "decided_at": r["decided_at"].isoformat() if r.get("decided_at") else None,
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None}


def view(cur: Any, *, limit: int = 200) -> Dict[str, Any]:
    """The review view: the channel book's rows by state (added and would_add first), with why, from where, how;
    the day's adds and the cap; the mode."""
    order = {"added": 0, "would_add": 1, "candidate": 2, "proven": 2, "covered": 3, "refused": 4, "undone": 5}
    rows = _rows(cur, "TRUE ORDER BY COALESCE(decided_at, created_at) DESC LIMIT %s", (limit,))
    rows.sort(key=lambda r: order.get(r["state"], 9))
    cur.execute("SELECT state, count(*) FROM mx_official_channels WHERE superseded_at IS NULL GROUP BY 1")
    counts = dict(cur.fetchall())
    cur.execute("SELECT outcome, count(*) FROM mx_official_events GROUP BY 1")
    events = dict(cur.fetchall())
    hidden = {}
    sources = [r["source_id"] for r in rows if r["source_id"]]
    if sources:
        from insight_core.utils import item_filter
        hidden = item_filter.hidden_count(cur, sources)
    shown = []
    for r in rows:
        s = _shown(r)
        s["hidden_items"] = hidden.get(r["source_id"] or "", 0)
        shown.append(s)
    return {"mode": mode(), "cap": adds_per_day(), "added_today": added_today(cur), "counts": counts,
            "events": events, "rows": shown}


def added_today(cur: Any, now: Optional[datetime] = None) -> int:
    now = now or datetime.now(timezone.utc)
    cur.execute("""SELECT count(DISTINCT key) FROM mx_official_channels WHERE state = 'added' AND decided_at > %s""",
                (now - timedelta(days=1),))
    return int(cur.fetchone()[0])


def undo(cur: Any, channel_id: str) -> Dict[str, Any]:
    """The owner's Undo: the channel's source switched off (its posts kept), the row `undone`; the module never adds
    that channel again. KeyError: no such current row."""
    got = _rows(cur, "id = %s", (channel_id,))
    if not got:
        raise KeyError(channel_id)
    row = got[0]
    if row["source_id"]:
        cur.execute("UPDATE sources SET enabled = false, updated_at = now() WHERE id = %s", (row["source_id"],))
    nid = put(cur, row["key"], row["kind"], "undone", why="undone by you: never added again", before=row)
    return {"id": nid, "state": "undone", "source_id": row["source_id"]}


# ---- events -----------------------------------------------------------------------------------------------------

def _settled(cur: Any) -> Set[str]:
    cur.execute("SELECT story_id FROM mx_official_events WHERE outcome NOT IN ('waiting')")
    return {r[0] for r in cur.fetchall()}


def _event_outcome(cur: Any, ev: Any, outcome: str, detail: Dict[str, Any]) -> None:
    cur.execute("""INSERT INTO mx_official_events (story_id, actor_id, actor_name, outcome, detail, first_at)
                   VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                   ON CONFLICT (story_id) DO UPDATE SET actor_id = EXCLUDED.actor_id, actor_name = EXCLUDED.actor_name,
                       outcome = EXCLUDED.outcome, detail = EXCLUDED.detail, decided_at = now()""",
                (ev.story, ev.actor or None, ev.actor_name or None, outcome, json.dumps(detail, default=str),
                 ev.first_at))


def pick_events(cur: Any, now: datetime, *, scan: int = EVENTS_SCAN) -> List[Any]:
    """The window's announced events of one voice or more not settled yet, newest first, at most `scan` of them read
    (their stories, actors, own pages and things' code addresses: discover_main_source.events)."""
    from insight_core.services import discover_main_source as D
    picked, checked = D.pick(cur, now, within=WITHIN_DAYS, min_voices=1)
    settled = _settled(cur)
    keep = sorted((sid for sid in picked if sid not in settled), key=lambda s: picked[s][0]["first_at"] or now,
                  reverse=True)[:scan]
    if not keep:
        return []
    evs, _ = D.events(cur, now, picked=({s: picked[s] for s in keep}, checked), bare=True)
    return evs


def _sources(cur: Any) -> Dict[str, Any]:
    from insight_core.services import discover_main_source as D
    return D._sources(cur)


def coverage(ch: Chan, pages: Sequence[str], sources: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The source already on the channel that carries the event (0170's covers): {id, name, enabled} or None. A
    releases feed is covered by a source at its address."""
    from insight_core.services import discover_main_source as D
    if ch.kind == "releases":
        return None                         # _releases_followed answers for a repository
    if ch.kind in ("x", "telegram"):
        dch = D.Channel(ch.key, "account", ch.kind, ch.address, site=ch.site)
    elif ch.kind == "youtube":
        return None
    else:
        dch = D.Channel(ch.key, "site", "site", ch.address, ch.prefix, ch.site)
    for s in sources.values():
        if D.on_channel(s, dch) and (not pages or any(D.covers(s, dch, p) is not False for p in pages)):
            return {"id": s.id, "name": s.name, "enabled": s.enabled}
    return None


def _releases_followed(cur: Any) -> Dict[str, Dict[str, Any]]:
    """{github.com/<o>/<r>: source} of the sources reading a repository's releases (or tags) feed."""
    cur.execute("""SELECT id::text, handle_or_url, enabled, COALESCE(NULLIF(btrim(settings->>'display_name'), ''),
                          handle_or_url) FROM sources WHERE handle_or_url ILIKE '%%github.com/%%'""")
    out = {}
    for sid, handle, enabled, name in cur.fetchall():
        m = _GITHUB_REPO.match(handle if "://" in handle else "https://" + handle)
        if m:
            out[f"github.com/{m.group(1).lower()}/{re.sub(r'.git$', '', m.group(2)).lower()}"] = {
                "id": sid, "name": name, "enabled": enabled}
    return out


@dataclass
class Cand:
    chan: Chan
    origin: str                       # own_page | code_address | handle | web_search | web_announcement
    owned: str
    pages: List[str] = field(default_factory=list)   # the event's own pages on it


def candidates(ev: Any, *, handles: Sequence[Tuple[str, str]] = (), lookup: Optional[Dict[str, Any]] = None
               ) -> Tuple[List[Cand], List[Dict[str, Any]]]:
    """(the event's owned candidates, the ones refused by ownership with why). Pure. In order: its own pages'
    channels, its things' code addresses, the actor's handles, then (only when those give none) the web search's."""
    out: Dict[str, Cand] = {}
    refused: List[Dict[str, Any]] = []
    code_repos = sorted({(channel(u).site if channel(u) else "") for us in ev.addresses.values() for u in us} - {""})
    actor = ev.actor or None
    for own in ev.pages:
        ch = channel(own.url)
        if ch is None:
            continue
        got = out.setdefault(ch.key, Cand(ch, "own_page", "its own page in the story (" + own.how + ")"))
        got.pages.append(own.url)
    for root, urls in ev.addresses.items():
        if actor and root != actor and root not in (ev.things or []):
            continue
        for u in urls:
            ch = channel(u)
            if ch is not None and ch.kind == "releases" and ch.key not in out:
                why = owned(ch, mk=ev.mk, actor=actor, names=[ev.actor_name] if ev.actor_name else [])
                if why:
                    out[ch.key] = Cand(ch, "code_address", why)
    for platform, handle in handles:
        if platform == "x":
            ch = channel(f"https://x.com/{handle}")
            if ch and ch.key not in out:
                out[ch.key] = Cand(ch, "handle", "its handle (confirmed by you, or its own source's account)")
    if out or not lookup:
        return list(out.values()), refused
    names = [n for n in [((lookup.get("actor") or {}).get("name")), ev.actor_name] if n]
    sites = [s for s in [((lookup.get("actor") or {}).get("site"))] if s]
    proposed = [(c.get("url") or "", "web_search", c.get("why") or "") for c in lookup.get("channels") or []]
    ann = (lookup.get("announcement") or {}).get("url")
    if ann:
        proposed.insert(0, (ann, "web_announcement", (lookup.get("announcement") or {}).get("why") or ""))
    for url, origin, said in proposed:
        ch = channel(url)
        if ch is None:
            refused.append({"url": url, "why": "not a channel's shape (a home page, one page, docs, help, a hub page)"})
            continue
        if ch.key in out:
            continue
        if ch.kind == "releases":
            same_name = [r for r in code_repos if r.rsplit("/", 1)[-1] == ch.site.rsplit("/", 1)[-1] and r != ch.site]
            if same_name:
                refused.append({"url": url, "why": f"the post links another repository ({same_name[0]})"})
                continue
        why = owned(ch, mk=ev.mk, actor=actor, names=names, sites=sites)
        if not why:
            refused.append({"url": url, "why": f"{ch.owner} is not the actor's name (an employee's or another's)"})
            continue
        got = out.setdefault(ch.key, Cand(ch, origin, why + f"; the web search: {said}"[:200]))
        if origin == "web_announcement":
            got.pages.append(url)
    return list(out.values()), refused


# ---- the web search (the `websearch` kind, guide websearch-official-v1) ------------------------------------------

def lookup_key(ev: Any) -> str:
    from insight_core.markx import names as N
    thing = ev.things[0] if ev.things else N.squash(N.key(ev.headline))[:60]
    return f"{ev.actor or '-'}:{thing}"


def lookup_input(ev: Any, book: Any) -> str:
    from insight_core.markx import schemas
    lines = [f"Event: {ev.headline}", f"Type: {ev.event_type}", "Posts:"]
    for p in ev.posts[:3]:
        lines.append(f"- {p.get('source')}: {p.get('title') or ''} ({p.get('url') or ''})")
    names = [book.label(t) for t in ev.things[:4] if book.label(t)]
    lines.append("Things named: " + (", ".join(names) if names else "(none)"))
    lines.append("Actor INSIGHT guesses: " + (ev.actor_name or "unknown"))
    lines.append(f"Searches allowed: at most {min(LOOKUP_SEARCHES, schemas.WEBSEARCH_QUERIES)}")
    return "\n".join(lines)


def lookup_answer(cur: Any, key: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """(the lookup's status: none | waiting | answered | failed, its answer)."""
    cur.execute("SELECT task_id::text, answer, asked_at FROM mx_official_lookups WHERE key = %s", (key,))
    row = cur.fetchone()
    if row is None:
        return None, None
    task_id, answer, asked = row
    if answer is not None:
        return "answered", answer
    cur.execute("SELECT status FROM mx_tasks WHERE id = %s", (task_id,))
    st = (cur.fetchone() or ("failed",))[0]
    cur.execute("SELECT answer FROM mx_calls WHERE task_id = %s AND valid ORDER BY created_at LIMIT 1", (task_id,))
    got = cur.fetchone()
    if got:
        cur.execute("UPDATE mx_official_lookups SET answer = %s::jsonb, answered_at = now() WHERE key = %s",
                    (json.dumps(got[0]), key))
        return "answered", got[0]
    if st in ("open", "leased") and asked > datetime.now(timezone.utc) - timedelta(days=WAIT_DAYS):
        return "waiting", None
    return "failed", None


def ask_lookup(cur: Any, ev: Any, book: Any) -> str:
    from insight_core.markx import repo, schemas
    schemas.ensure_guides(cur)
    key = lookup_key(ev)
    task_id, _new = repo.add_task(cur, kind=LOOKUP_KIND, guide=LOOKUP_GUIDE, subject_kind="official_event",
                                  input=lookup_input(ev, book), a=None, priority=PRIORITY)
    cur.execute("""INSERT INTO mx_official_lookups (key, actor_id, story_id, task_id) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (key) DO NOTHING""", (key, ev.actor or None, ev.story, task_id))
    return str(task_id)


# ---- the pass ---------------------------------------------------------------------------------------------------

def _gate(ev_count: int, voices: int) -> bool:
    return ev_count >= GATE_EVENTS or voices >= GATE_VOICES


def plan(cur: Any, now: datetime, counts: Counter, *, lookups: int = LOOKUPS_PER_RUN,
         events_per_run: int = EVENTS_PER_RUN) -> None:
    """Step 1 (no request): the unsettled events' candidates recorded, a web search asked where the code gives none,
    a found maker written through identity. Outcomes in mx_official_events."""
    from insight_core.markx import handles as H, identity, entity_facts
    evs = pick_events(cur, now)
    counts["events_read"] = len(evs)
    if not evs:
        return
    by_actor = Counter(ev.actor for ev in evs if ev.actor)
    cur.execute("SELECT actor_id::text, count(*) FROM mx_official_events WHERE actor_id IS NOT NULL AND first_at > %s "
                "GROUP BY 1", (now - timedelta(days=WITHIN_DAYS),))
    for a, n in cur.fetchall():
        by_actor[a] += n
    sources = _sources(cur)
    releases = _releases_followed(cur)
    book = identity.lazy_book(cur)
    asked = 0
    for ev in evs[:events_per_run]:
        if ev.member_sources & ev.actor_sources:
            _event_outcome(cur, ev, "held", {"why": "the actor's own post is in the story"})
            counts["held"] += 1
            continue
        hs: List[Tuple[str, str]] = []
        if ev.actor:
            try:
                hs = [(h["platform"], h["handle"]) for h in H.entity_handles(
                    cur, book, ev.actor, book.cluster(ev.actor),
                    [{"id": s} for s in ev.actor_sources])]
            except Exception:  # noqa: BLE001 - no handles is a candidate source less
                log.exception("Official channels: the handles of %s could not be read", ev.actor)
        key = lookup_key(ev)
        status, answer = lookup_answer(cur, key)
        cands, refused = candidates(ev, handles=hs, lookup=answer if status == "answered" else None)
        if status == "answered" and answer:
            thing = ev.things[0] if ev.things else None
            if thing and answer.get("thing_maker"):
                if entity_facts.set_maker(cur, book, thing, answer["thing_maker"],
                                          evidence={"by": "websearch-official-v1", "story": ev.story}):
                    counts["makers_written"] += 1
            if not answer.get("official"):
                _event_outcome(cur, ev, "not_official", {"why": answer.get("why_not") or "no own announcement"})
                counts["not_official"] += 1
                continue
        if not cands and status is None:
            if asked >= lookups:
                _event_outcome(cur, ev, "waiting", {"why": "a web search waits for the next pass"})
                continue
            ask_lookup(cur, ev, book)
            asked += 1
            counts["lookups_asked"] += 1
            _event_outcome(cur, ev, "waiting", {"why": "the web search is asked"})
            continue
        if not cands and status == "waiting":
            _event_outcome(cur, ev, "waiting", {"why": "the web search is not answered yet"})
            continue
        if not cands:
            _event_outcome(cur, ev, "none", {"why": "official source not found", "refused": refused[:6]})
            counts["none"] += 1
            continue
        actor_name = ev.actor_name or ((answer or {}).get("actor") or {}).get("name")
        made = []
        for c in cands:
            made.append(c.chan.key)
            before = current(cur, c.chan.key)
            shown_event = {"story": ev.story, "headline": ev.headline, "voices": ev.voices,
                           "first_at": ev.first_at.isoformat() if ev.first_at else None}
            if before is not None:
                if ev.story not in (before.get("events") or []):
                    ev_rows = sorted(set(before.get("events") or []) | {ev.story})
                    evidence = dict(before.get("evidence") or {})
                    evidence["events_shown"] = ([shown_event] + list(evidence.get("events_shown") or []))[:5]
                    cur.execute("UPDATE mx_official_channels SET events = %s, evidence = %s::jsonb WHERE id = %s",
                                (ev_rows, json.dumps(evidence, default=str), before["id"]))
                continue
            cov = (releases.get(c.chan.site) if c.chan.kind == "releases" else coverage(c.chan, c.pages, sources))
            evidence = {"from": c.origin, "owned": c.owned, "pages": c.pages[:5], "events_shown": [shown_event],
                        "actor_events": by_actor.get(ev.actor, 1) if ev.actor else 1, "voices": ev.voices,
                        "refused_proposals": refused[:4], "lookup": key if status == "answered" else None}
            common = dict(actor_id=ev.actor or None, actor_name=actor_name, follow=c.chan.address,
                          page_watch={"prefix": c.chan.prefix} if c.chan.kind == "section" else None,
                          evidence=evidence, events=[ev.story])
            if cov is not None:
                why = (f"followed already as {cov['name']}" if cov.get("enabled")
                       else f"you switched off {cov['name']}: never suggested again")
                put(cur, c.chan.key, c.chan.kind, "covered", why=why, source_id=cov["id"], **common)
                counts["covered"] += 1
            else:
                put(cur, c.chan.key, c.chan.kind, "candidate", why=f"found: {c.origin.replace('_', ' ')}", **common)
                counts["candidates"] += 1
        _event_outcome(cur, ev, "channels", {"channels": made, "refused": refused[:6]})


def _proof(row: Dict[str, Any], j: Dict[str, Any]) -> Tuple[Optional[str], Dict[str, Any]]:
    """(why it is no proven channel, or None; the proof as shown) from the judgement's test read."""
    sig = j.get("signals") or {}
    rate = sig.get("rate") or {}
    resolved = j.get("resolved") or {}
    items = j.get("items") or []
    dated = int(rate.get("dated") or sum(1 for i in items if i.get("published_at")))
    pages = {u.rstrip("/").split("://", 1)[-1].removeprefix("www.") for u in (row.get("evidence") or {}).get("pages") or []}
    holds = sum(1 for i in items if (i.get("url") or "").rstrip("/").split("://", 1)[-1].removeprefix("www.") in pages)
    linked = int((sig.get("items_in") or {}).get("linked") or 0)
    proof = {"via": resolved.get("via"), "address": resolved.get("handle_or_url"), "items": len(items),
             "dated": dated, "holds": holds, "linked": linked, "newest_days": rate.get("newest_days")}
    if j.get("status") in ("unreadable", "failed"):
        return f"no dated stream: {j.get('reason') or 'could not be read'}", proof
    if dated < MIN_DATED:
        return f"no dated stream: {dated} dated items read", proof
    if row["kind"] == "section":
        prefix = (row.get("page_watch") or {}).get("prefix") or ""
        if not (holds or ANNOUNCING.search(prefix)):   # pages your sources link (a benchmark's data pages) are no
            return "no announcements: its read holds none of the event's pages and its path announces nothing", proof
    return None, proof


def decide(cur: Any, row: Dict[str, Any], j: Dict[str, Any], now: datetime, counts: Counter, *,
           add: Optional[Callable[[Any, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None) -> str:
    """A candidate whose judgement is in: proof, wanted, then would_add / added (the cap) / refused. Returns the state."""
    no, proof = _proof(row, j)
    answer = j.get("answer") or {}
    ev = dict(row.get("evidence") or {}, proof=proof,
              judge={"verdict": answer.get("verdict"), "fits": answer.get("fits"), "original": answer.get("original"),
                     "reasons": (answer.get("reasons") or [])[:4]})
    if no:
        put(cur, row["key"], row["kind"], "refused", why=no, before=row, evidence=ev)
        counts["refused"] += 1
        return "refused"
    if not _gate(int(ev.get("actor_events") or 1), int(ev.get("voices") or 1)):
        put(cur, row["key"], row["kind"], "refused", before=row, evidence=ev,
            why=f"one event of one actor in {WITHIN_DAYS} days with under {GATE_VOICES} voices: not yet")
        counts["refused"] += 1
        return "refused"
    if answer.get("verdict") != "follow" or not answer.get("fits"):
        reasons = "; ".join((answer.get("reasons") or [])[:2])
        put(cur, row["key"], row["kind"], "refused", before=row, evidence=ev,
            why=f"the worker: {answer.get('verdict')}{'' if answer.get('fits') else ', not your topics'}: {reasons}")
        counts["refused"] += 1
        return "refused"
    site = row["key"].split("/", 1)[0]
    if row["kind"] == "section" and row.get("actor_id"):
        others = [r for r in _rows(cur, "actor_id = %s AND kind = 'section' AND state IN ('would_add', 'added')",
                                   (row["actor_id"],)) if r["key"].split("/", 1)[0] == site and r["key"] != row["key"]]
        if others:
            put(cur, row["key"], row["kind"], "refused", before=row, evidence=ev,
                why=f"one section a site: {others[0]['key']} is kept")
            counts["refused"] += 1
            return "refused"
    rule = answer.get("filter") if isinstance(answer.get("filter"), dict) and answer["filter"].get("hide") else None
    resolved = j.get("resolved") or {}
    follow = resolved.get("handle_or_url") or row["follow"]
    if mode() != "on" or added_today(cur, now) >= adds_per_day():
        why = ("Shadow: would be added" if mode() != "on"
               else f"waits: {adds_per_day()} added today (the first weeks' cap)")
        put(cur, row["key"], row["kind"], "would_add", why=why, before=row, evidence=ev, rule=rule, follow=follow)
        counts["would_add"] += 1
        return "would_add"
    try:
        got = (add or add_source)(cur, row, j)
    except Exception as exc:  # noqa: BLE001 - the channel stays would_add; the next pass tries again
        log.exception("Official channels: adding %s failed", row["key"])
        put(cur, row["key"], row["kind"], "would_add", why=f"the add failed: {str(exc)[:120]}", before=row,
            evidence=ev, rule=rule, follow=follow)
        counts["add_failed"] += 1
        return "would_add"
    put(cur, row["key"], row["kind"], "added", why="added automatically: official, proven, wanted", before=row,
        evidence=dict(ev, archive=got.get("archive")), rule=rule, follow=follow, source_id=got["source_id"],
        filter_id=got.get("filter_id"))
    counts["added"] += 1
    return "added"


def add_source(cur: Any, row: Dict[str, Any], j: Dict[str, Any]) -> Dict[str, Any]:
    """The add, through the add path every add takes (scout.default_add_source: POST /api/sources' own, at the address
    the feed finder or page watching resolved at the test read), the item filter kept, the archive queued."""
    from insight_core.markx import scout
    from insight_core.utils import item_filter
    resolved = j.get("resolved") or {}
    if not resolved.get("handle_or_url"):
        raise ValueError("the test read resolved no address")
    settings = dict(resolved.get("settings") or {})
    settings.setdefault("display_name", (row.get("actor_name") or "")[:120] or None)
    settings = {k: v for k, v in settings.items() if v is not None}
    source_id = scout.default_add_source(resolved.get("platform") or "rss", resolved["handle_or_url"], settings)
    cur.execute("""UPDATE sources SET settings = COALESCE(settings, '{}'::jsonb) || %s::jsonb WHERE id = %s""",
                (json.dumps({"added_by": "official", "official": {"key": row["key"], "actor": row.get("actor_name"),
                                                                  "actor_id": row.get("actor_id")}}), source_id))
    answer = j.get("answer") or {}
    fid = None
    rule = answer.get("filter")
    if isinstance(rule, dict) and rule.get("hide"):
        fid = item_filter.put(cur, source_id, rule, by="worker", guide="source-judge-v2", task_id=j.get("task_id"))
    archive = None
    try:
        from insight_core.services import follow_archive
        from insight_core.services.registry import services
        from insight_core.services.archive_jobs import ArchiveJobs
        archive = follow_archive.queue_on_follow(
            services(), lambda: ArchiveJobs(services().operations, services().source_fetch, trigger="official"),
            source_id)
    except Exception as exc:  # noqa: BLE001 - followed; its archive is the button's
        log.info("Official channels: the archive of %s was not queued (%s)", source_id, type(exc).__name__)
    return {"source_id": source_id, "filter_id": fid, "archive": archive}


def advance(db_url: str, now: datetime, counts: Counter, *, reads: int = READS_PER_RUN,
            reader: Optional[Any] = None, add: Optional[Callable[..., Dict[str, Any]]] = None) -> None:
    """Step 2: the candidates' judgements asked (the add path's test read, then one `source_judge` question), the
    answered ones decided. Each candidate in a short transaction of its own; the reads outside them."""
    from insight_core.db import database
    from insight_core.markx import source_judge as SJ
    with database.transaction(db_url) as cur:
        waiting = _rows(cur, "state = 'candidate' ORDER BY created_at")
        stale = _rows(cur, "state = 'refused' AND decided_at < %s ORDER BY decided_at LIMIT 20",
                      (now - timedelta(days=REFUSED_DAYS),))
    to_read: List[Tuple[Dict[str, Any], str]] = []
    for row in waiting + stale:
        with database.transaction(db_url) as cur:
            if row["state"] == "refused":
                row = dict(row, id=put(cur, row["key"], row["kind"], "candidate", why="looked at again", before=row),
                           state="candidate", judge_id=None)
            j = SJ.get(cur, row["judge_id"]) if row.get("judge_id") else None
            if j is not None and j["status"] == "asked" and j.get("task_id"):
                j = SJ.latest(cur, j["address"]) or j
            if j is None:
                if len(to_read) >= reads:
                    continue
                got = SJ.ask(cur, row["follow"], now=now)
                cur.execute("UPDATE mx_official_channels SET judge_id = %s WHERE id = %s", (got["id"], row["id"]))
                if got.get("needs_read"):
                    to_read.append((row, got["id"]))
                counts["judged_asked"] += 1
                continue
            if j["status"] in ("reading",):
                continue
            if j["status"] == "asked":
                if j["asked_at"] < now - timedelta(days=WAIT_DAYS):
                    put(cur, row["key"], row["kind"], "refused", why="the worker did not answer", before=row)
                continue
            decide(cur, row, j, now, counts, add=add)
    for row, jid in to_read:
        try:
            asyncio.run(SJ.read_and_ask(db_url, jid, reader=reader, priority=PRIORITY))
            counts["reads"] += 1
        except Exception:  # noqa: BLE001 - one channel's read; the judgement says why
            log.exception("Official channels: the test read of %s failed", row["key"])


SUGGESTIONS_PER_DAY = 10         # Discover's suggestions the worker checks a day (the pipeline's "checked" step)
SUGGESTION_SCAN = 300             # the suggestions a pass looks at for its fit prior


def to_check(suggestions: Sequence[Dict[str, Any]], read_most: Sequence[str], judged: Set[str],
             limit: int) -> List[str]:
    """Discover's suggestions to have the worker check: followable ones not judged lately, those linked by the sources
    the reader reads most first (a fit prior from what the reader opens, not link volume), then by Discover's order.
    Pure."""
    from insight_core.markx import source_judge
    from insight_core.utils.discover_rules import section
    most = {n.casefold() for n in read_most}
    pool = []
    for i, sg in enumerate(suggestions[:SUGGESTION_SCAN]):
        key = sg.get("key") or ""
        if not key or section(sg) == 1 or source_judge.cache_key(key) in judged:
            continue
        prior = sum(1 for v in sg.get("voice_names") or [] if str(v).casefold() in most)
        pool.append((-prior, i, key))
    return [k for _, _, k in sorted(pool)[:limit]]


def check_suggestions(db_url: str, now: datetime, counts: Counter, *, reader: Optional[Any] = None,
                      limit: Optional[int] = None) -> None:
    """The pipeline's "checked by the worker" step for Discover's suggestions (never an add: a suggestion is no
    official channel): up to SUGGESTIONS_PER_DAY a day, one `source_judge` read and question each; Discover then ranks
    by the answer's fit (stories_service._by_fit)."""
    from insight_core.db import database
    from insight_core.db.repo_discover import DiscoverRepository
    from insight_core.markx import source_judge as SJ
    with database.transaction(db_url) as cur:
        cur.execute("""SELECT COALESCE(sum((counts->>'suggestions_judged')::int), 0) FROM mx_official_runs
                        WHERE started_at > %s""", (now - timedelta(days=1),))
        left = (SUGGESTIONS_PER_DAY if limit is None else limit) - int(cur.fetchone()[0])
        if left <= 0:
            return
        found = DiscoverRepository.any_list(cur) or {}
        cur.execute("SELECT DISTINCT key FROM mx_source_judgements WHERE asked_at > %s", (now - timedelta(days=SJ.CACHE_DAYS),))
        judged = {r[0] for r in cur.fetchall()}
        cur.execute("""SELECT COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url)
                         FROM post_interactions i JOIN posts p ON p.id = i.post_id JOIN sources s ON s.id = p.source_id
                        WHERE i.interaction_type = 'opened' AND i.created_at > %s
                        GROUP BY 1 ORDER BY count(DISTINCT i.post_id) DESC LIMIT %s""",
                    (now - timedelta(days=90), SJ.INTEREST_SOURCES))
        most = [r[0] for r in cur.fetchall()]
        keys = to_check(found.get("suggestions") or [], most, judged, left)
        asked = []
        for key in keys:
            got = SJ.ask(cur, "https://" + key, now=now)
            if got.get("needs_read"):
                asked.append(got["id"])
    for jid in asked:
        try:
            asyncio.run(SJ.read_and_ask(db_url, jid, reader=reader, priority=PRIORITY))
        except Exception:  # noqa: BLE001 - the judgement says why
            log.exception("Official channels: a suggestion's check failed")
    counts["suggestions_judged"] += len(asked)


def run(db_url: str, *, now: Optional[datetime] = None, reader: Optional[Any] = None,
        add: Optional[Callable[..., Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The jobs process's pass: plan (events, candidates, lookups), then advance (reads, judgements, decisions).
    Off: nothing. Never raises into the caller: a failure is recorded on the run."""
    from insight_core.db import database
    import resource
    now = now or datetime.now(timezone.utc)
    m = mode()
    if m == "off":
        return {"mode": m}
    counts: Counter = Counter()
    with database.transaction(db_url) as cur:
        cur.execute("INSERT INTO mx_official_runs (mode) VALUES (%s) RETURNING id::text", (m,))
        run_id = cur.fetchone()[0]
    error = None
    try:
        with database.transaction(db_url) as cur:
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtext('insight.official'))")
            if not cur.fetchone()[0]:
                return {"mode": m, "skipped": "another pass runs"}
            plan(cur, now, counts)
        advance(db_url, now, counts, reader=reader, add=add)
        check_suggestions(db_url, now, counts, reader=reader)
    except Exception as exc:  # noqa: BLE001 - recorded; the next pass resumes from Postgres
        log.exception("Official channels: the pass failed")
        error = str(exc)[:300]
    out = {"mode": m, **dict(counts), "peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)}
    if error:
        out["error"] = error
    with database.transaction(db_url) as cur:
        cur.execute("UPDATE mx_official_runs SET finished_at = now(), counts = %s::jsonb WHERE id = %s",
                    (json.dumps(out), run_id))
    log.info("Official channels: %s", out)
    return out


# ---- the originals step's `cited` planner (pages 2+ voices link) ------------------------------------------------

CITED_DAYS = 7
CITED_VOICES = 2


def pages_wanted(cur: Any, now: datetime, *, limit: int = 40,
                 kind_of: Optional[Callable[..., str]] = None) -> List[Dict[str, Any]]:
    """For the originals step (services/originals_service.plan_cited): the pages CITED_VOICES+ voices linked in
    CITED_DAYS (a publication's feeds one voice: sources.voice_id), not stored, not asked, of no followed source (0114 and F2 own those; an added official channel's pages are its feed's),
    passing the exclusions: a front page, Discover's
    places that are no source (references, docs, apps, archives, documents), pricing, legal, help and README pages, a
    media host, a code host's or model hub's repository (0138's entity originals read those), a tweet (from a quote
    only). The most voices first."""
    from insight_core.utils import entity_originals as E
    from insight_core.utils.addresses import host_of, site_of, is_tweet
    from insight_core.utils.discover_rules import app_address, archive_address, document_address, reference_address
    from insight_core.utils.post_links import LEGAL
    from insight_core.markx import pairing
    one_voice = "count(DISTINCT COALESCE(s.voice_id::text, s.id::text))"   # a publication's feeds: one voice
    cur.execute(f"""SELECT l.target_url, {one_voice} FROM post_links l
                      JOIN posts p ON p.id = l.post_id JOIN sources s ON s.id = p.source_id
                     WHERE NOT l.boilerplate AND l.kind = 'link' AND s.platform <> 'saved' AND s.enabled
                       AND {pairing.ix_date('p')} >= %s
                     GROUP BY 1 HAVING {one_voice} >= %s""",
                (now - timedelta(days=CITED_DAYS), CITED_VOICES))
    voices = dict(cur.fetchall())
    if not voices:
        return []
    urls = sorted(voices)
    cur.execute("SELECT normalized_url FROM posts WHERE normalized_url = ANY(%s)", (urls,))
    stored = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT url FROM story_originals WHERE url = ANY(%s)", (urls,))
    asked = {r[0] for r in cur.fetchall()}
    media = re.compile(r"(^|\.)(youtube\.com|youtu\.be|vimeo\.com|twitch\.tv|spotify\.com|soundcloud\.com|"
                       r"podcasts\.apple\.com|music\.apple\.com|tiktok\.com|instagram\.com)$")
    helpish = re.compile(r"/(pricing|plans|help|support|faq|docs?|documentation|readme(\.md)?|blob|tree|login|signup|"
                         r"careers?|jobs)(/|$|\.)", re.I)
    out = []
    for url in sorted(urls, key=lambda u: (-voices[u], u)):
        if url in stored or url in asked or is_tweet(url) or E.front_page(url):
            continue
        host = host_of(url)
        site = site_of(host)
        path = urllib.parse.urlparse(url).path
        if (media.search(host) or site in E.CODE_SITES or site in E.MODEL_HUBS or helpish.search(path)
                or LEGAL.search(path.rstrip("/") + "/") or reference_address(url) or archive_address(url)
                or app_address(url) or document_address(url)):
            continue
        kind = kind_of(url) if kind_of else "page"
        if kind_of is not None and kind == "followed":
            continue
        out.append({"url": url, "voices": voices[url], "kind": kind})
        if len(out) >= limit:
            break
    return out


__all__ = ["Chan", "MODES", "add_source", "advance", "book", "candidates", "channel", "decide", "mode", "owned",
           "pages_wanted", "plan", "run", "undo", "view"]
