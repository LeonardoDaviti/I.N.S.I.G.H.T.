"""Is this worth it? (issue 0173, Stealth v10.15): a candidate source judged by the worker, on the owner's tap only.

Owner decision 2026-11-12: no trial follow and no spend cap for a new source; instead the worker says, on request,
whether the reader would care about it. Asked from Discover's rows (every section, its other channels and "The main
source is missing") and from the Add source dialog once the finder found a feed or a page. The owner still decides:
Follow goes through the Add source dialog, as every add.

    got = ask(cur, address)             # the cached judgement (30 days), or a new one to read: {.., needs_read}
    await read_and_ask(db_url, got["id"])   # the test read, the measured signals and the `source_judge` question
    view(row)                           # what the page shows

**The test read** (scout_reads.Reader, 0148's, the add path's own: a source kind's account through its kind, anything
else through the feed finder, then page watching): up to ITEMS newest items, kept on the judgement row (never a post,
never in a feed, nothing followed). Nothing is written but mx_source_judgements and the question (mx_tasks).

**What INSIGHT measures** (`signals`, from code, never from the model):
  - linked: how many of your (on) sources' posts link its address, and which sources;
  - stories: your stories that started at its pages (Mark IX's origin pages, 2+ voices), and in the last 90 days;
  - its items in your stories: of the items read, how many your sources link, how many started a story;
  - rate and the newest item (the test read's health); its languages;
  - reads (0149 E8: the model fails at it): full text in the feed, else up to PAGE_CHECKS item pages read as the
    fetcher reads them (full_text.read_page): full from its pages, teasers, or a paywall the page states;
  - repeats: its items you already have (the same address, or the same title in the last REPEAT_DAYS), from which
    sources; the sources you follow on the same site;
  - rewriter marks (very high rate, many languages, never first, rarely cited): each said, the pattern when the
    rate is high and two more hold;
  - followed before: a source at this address you turned off (its posts, opens, the stories it was first in).
**The reader** (`interests`): the described tracks, the sources read most in 90 days (opens), what those reads are
about (Mark X's subjects), the folders; ordered by what is read most.

**The question**: kind `source_judge`, guide source-judge-v1, one candidate a call; the answer {verdict, reasons,
examples, fits, original} checked by the schema and validate._source_judge (each example an item the question shows).

**The cache**: an answered judgement is shown again for CACHE_DAYS (asking is free); one that could not be read, or
whose question failed, is read again on the next tap (requests, no question). "Ask again" reads again; when the items
read are the ones the last answer judged (`items_sig`), that answer stands (no question), else a new question.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import statistics
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.markx import pairing, repo, schemas, scout_reads
from insight_core.db.repo_stories import suggestable_sql

log = logging.getLogger(__name__)

KIND = "source_judge"
SUBJECT = "source_candidate"
ITEMS = 10                    # the newest items a judgement reads and shows
ITEM_CHARS = 500              # an item's text the question shows
TITLE_CHARS = 200             # an item's title the question shows (a post's title may be its whole text)
CACHE_DAYS = 30
PAGE_CHECKS = 2               # item pages read to tell full text from teasers (a teaser feed only)
REPEAT_DAYS = 60
LINK_DAYS = 90
PRIORITY = -5                 # the owner is waiting: leased before the planners' questions
CLAIM = timedelta(minutes=10)
STUCK = timedelta(minutes=30)  # a read that never finished (a restart): read again on the next ask

# Rewriter marks (0173, measured on the labelled set: plan/issues/0173-source-judge-on-request.md "Measured").
RATE_HIGH = 140.0             # items a week: 20 a day
MANY_LANGUAGES = 3            # distinct languages among the items read
RARELY_CITED = 1              # linked by at most this many of your sources
INTEREST_SOURCES, INTEREST_SUBJECTS, INTEREST_TRACK_CHARS = 12, 15, 220
SHORT_PLATFORMS = ("x", "telegram", "reddit", "hn", "bluesky", "mastodon")   # a post is complete as posted


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: Any) -> Optional[str]:
    return t.astimezone(timezone.utc).isoformat() if isinstance(t, datetime) else None


# ---- addresses ------------------------------------------------------------------------------------------

def cache_key(address: str) -> str:
    """The candidate address as the cache keys it: no scheme, no www, the host lower case, no trailing slash."""
    a = (address or "").strip()
    a = a.split("://", 1)[-1]
    host, slash, rest = a.partition("/")
    host = host.lower().removeprefix("www.")
    return (host + slash + rest).rstrip("/")


def _bare(url: str) -> str:
    return (url or "").lower().split("://", 1)[-1].removeprefix("www.")


def address_key(cur: Cursor, address: str) -> Tuple[str, str, bool]:
    """(Discover's key, its site, on a platform) of the candidate's address (scout.key_of: the platforms the data finds)."""
    from insight_core.markx import scout
    key, site, platform = scout.key_of(address, scout._platforms(cur))
    if not key:
        from insight_core.utils.addresses import host_of, site_of
        host = host_of(address).removeprefix("www.")
        key, site, platform = host, site_of(host), False
    return key.lower(), site or "", bool(platform)


# ---- the cache and the row ----------------------------------------------------------------------------------

COLS = ("id", "key", "address", "status", "resolved", "reason", "items", "items_sig", "signals", "task_id", "answer",
        "verdict", "same_as", "requests", "busy_until", "asked_at", "read_at", "answered_at")


def _rows(cur: Cursor, where: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    cur.execute(f"SELECT {', '.join(COLS)} FROM mx_source_judgements WHERE {where}", params)
    out = []
    for r in cur.fetchall():
        row = dict(zip(COLS, r))
        for k in ("id", "task_id", "same_as"):
            row[k] = str(row[k]) if row[k] is not None else None
        out.append(row)
    return out


def get(cur: Cursor, judgement_id: str) -> Optional[Dict[str, Any]]:
    got = _rows(cur, "id = %s", (judgement_id,))
    return got[0] if got else None


def latest(cur: Cursor, address: str) -> Optional[Dict[str, Any]]:
    """The newest judgement of the address; one whose question the worker gave up on (its task failed) as failed."""
    got = _rows(cur, "key = %s ORDER BY asked_at DESC, id LIMIT 1", (cache_key(address),))
    row = got[0] if got else None
    if row is not None and row["status"] == "asked" and row["task_id"]:
        cur.execute("SELECT status, last_error FROM mx_tasks WHERE id = %s", (row["task_id"],))
        task = cur.fetchone()
        if task and task[0] == "failed":
            cur.execute("""UPDATE mx_source_judgements SET status = 'failed', reason = %s WHERE id = %s""",
                        (f"the worker could not answer: {task[1] or 'invalid answers'}"[:300], row["id"]))
            row = get(cur, row["id"])
    return row


def _fresh(row: Dict[str, Any], now: datetime) -> bool:
    return row["asked_at"] >= now - timedelta(days=CACHE_DAYS)


def _stuck(row: Dict[str, Any], now: datetime) -> bool:
    return row["status"] == "reading" and row["asked_at"] < now - STUCK and (
        row["busy_until"] is None or row["busy_until"] < now)


def ask(cur: Cursor, address: str, *, again: bool = False, now: Optional[datetime] = None) -> Dict[str, Any]:
    """The owner's tap: the judgement of this address shown again while it is CACHE_DAYS fresh (or still being made),
    else a new one to read (`needs_read`). `again`: read again even when fresh (the earlier answer stands when the
    items read are the same). ValueError: no address."""
    now = now or _now()
    address = (address or "").strip()
    if not address.startswith(("http://", "https://")):
        if not address or any(c.isspace() for c in address):
            raise ValueError("An address to judge, please")
        address = "https://" + address
    key = cache_key(address)
    if not key:
        raise ValueError("An address to judge, please")
    last = latest(cur, address)
    if last is not None and last["status"] in ("reading", "asked") and not _stuck(last, now):
        return {**last, "needs_read": False}
    if last is not None and not again and _fresh(last, now) and last["status"] == "answered":
        return {**last, "needs_read": False}
    if last is not None and _stuck(last, now):
        cur.execute("UPDATE mx_source_judgements SET status = 'failed', reason = 'the read never finished' WHERE id = %s",
                    (last["id"],))
    answered = _rows(cur, "key = %s AND status = 'answered' ORDER BY asked_at DESC, id LIMIT 1", (key,))
    cur.execute("""INSERT INTO mx_source_judgements (key, address, asked_at, same_as) VALUES (%s, %s, %s, %s)
                   RETURNING id::text""", (key, address, now, answered[0]["id"] if answered else None))
    return {**get(cur, cur.fetchone()[0]), "needs_read": True}


def claim(cur: Cursor, judgement_id: str, now: datetime) -> bool:
    cur.execute("""UPDATE mx_source_judgements SET busy_until = %s WHERE id = %s AND status = 'reading'
                     AND (busy_until IS NULL OR busy_until < %s)""", (now + CLAIM, judgement_id, now))
    return cur.rowcount == 1


def items_sig(items: Sequence[Dict[str, Any]]) -> str:
    return hashlib.sha256("\n".join(sorted(i["url"] for i in items)).encode()).hexdigest()[:24]


# ---- what INSIGHT measures --------------------------------------------------------------------------------

def _addr_sql(col: str) -> str:
    return f"regexp_replace(split_part(lower({col}), '://', 2), '^www[.]', '')"


def _on_key(col: str) -> str:
    """SQL: the address in `col` is the key's (the key itself, or under it)."""
    a = _addr_sql(col)
    return (f"({a} = %(key)s OR left({a}, length(%(key)s) + 1) IN (%(key)s || '/', %(key)s || '?', %(key)s || '#'))")


def linked(cur: Cursor, key: str, site: str, now: datetime) -> Dict[str, Any]:
    """How many of your (on) sources' posts link the key's addresses: {sources, posts, recent, names}."""
    cur.execute(f"""SELECT p.source_id::text, COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url),
                           count(DISTINCT pl.post_id),
                           count(DISTINCT pl.post_id) FILTER (WHERE {pairing.ix_date('p')} > %(since)s)
                      FROM post_links pl JOIN posts p ON p.id = pl.post_id JOIN sources s ON s.id = p.source_id
                     WHERE NOT pl.boilerplate AND {suggestable_sql("s.id")} AND pl.target_site = %(site)s AND {_on_key('pl.target_url')}
                       AND NOT {_on_key('s.handle_or_url')}
                     GROUP BY 1, 2 ORDER BY 3 DESC, 2""",
                {"key": key, "site": site, "since": now - timedelta(days=LINK_DAYS)})
    rows = cur.fetchall()
    return {"sources": len(rows), "posts": sum(r[2] for r in rows), "recent": sum(r[3] for r in rows),
            "names": [r[1] for r in rows[:5]]}


def started(cur: Cursor, key: str, site: str, now: datetime) -> Dict[str, Any]:
    """Your stories (2+ voices) that started at the key's pages: {stories, recent, titles}."""
    from insight_core.utils.discover_rules import ORIGIN_MIN_VOICES
    cur.execute(f"""SELECT s.first_at, s.origin_title FROM stories s
                     WHERE s.voices >= %(min)s AND s.origin_url IS NOT NULL AND {_on_key('s.origin_url')}
                     ORDER BY s.first_at DESC""", {"key": key, "min": ORIGIN_MIN_VOICES})
    rows = cur.fetchall()
    since = now - timedelta(days=LINK_DAYS)
    return {"stories": len(rows), "recent": sum(1 for at, _ in rows if at and at > since),
            "titles": [t for _, t in rows if t][:3]}


def _normal(url: str) -> Optional[str]:
    from insight_core.utils.url_normalization import normalize_url
    try:
        return normalize_url(url)
    except Exception:  # noqa: BLE001 - an address the normaliser refuses is compared as it is
        return url


def in_stories(cur: Cursor, items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Of the items read: how many your sources' posts link ({linked}), how many started one of your stories
    ({started}), and the ids of those ({ids})."""
    urls = {i["id"]: {u for u in (i["url"], _normal(i["url"])) if u} for i in items}
    every = sorted({u for us in urls.values() for u in us})
    if not every:
        return {"linked": 0, "started": 0, "ids": []}
    cur.execute(f"""SELECT DISTINCT pl.target_url FROM post_links pl JOIN posts p ON p.id = pl.post_id
                     JOIN sources s ON s.id = p.source_id
                    WHERE pl.target_url = ANY(%s) AND NOT pl.boilerplate AND {suggestable_sql("s.id")}""", (every,))
    linked_urls = {u for (u,) in cur.fetchall()}
    from insight_core.utils.discover_rules import ORIGIN_MIN_VOICES
    cur.execute("SELECT DISTINCT origin_url FROM stories WHERE origin_url = ANY(%s) AND voices >= %s",
                (every, ORIGIN_MIN_VOICES))
    origin_urls = {u for (u,) in cur.fetchall()}
    linked_ids = [i for i, us in urls.items() if us & linked_urls]
    started_ids = [i for i, us in urls.items() if us & origin_urls]
    return {"linked": len(linked_ids), "started": len(started_ids),
            "ids": sorted(set(linked_ids) | set(started_ids), key=lambda x: int(x[1:]))}


def _title_key(title: str) -> str:
    from insight_core.markx.validate import fold
    return re.sub(r"[^\w]+", " ", fold(title)).strip()


def repeats(cur: Cursor, items: Sequence[Dict[str, Any]], key: str, site: str, now: datetime) -> Dict[str, Any]:
    """Its items you already have from a source you follow (the same address, or the same title of 20+ characters in
    the last REPEAT_DAYS): {items, from, ids}; and your sources on its site ({same_site})."""
    urls: Dict[str, str] = {}
    titles: Dict[str, str] = {}
    for i in items:
        for u in (i["url"], _normal(i["url"])):
            if u:
                urls[u] = i["id"]
        t = _title_key(i.get("title") or "")
        if len(t) >= 20:
            titles[t] = i["id"]
    hits: Dict[str, set] = {}

    def name_sql() -> str:
        return "COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url)"
    if urls:
        cur.execute(f"""SELECT DISTINCT COALESCE(p.normalized_url, p.url), {name_sql()} FROM posts p
                          JOIN sources s ON s.id = p.source_id
                         WHERE {suggestable_sql("s.id")} AND (p.normalized_url = ANY(%(u)s) OR p.url = ANY(%(u)s))
                           AND NOT {_on_key('s.handle_or_url')}""", {"u": sorted(urls), "key": key})
        for url, name in cur.fetchall():
            if url in urls:
                hits.setdefault(urls[url], set()).add(name)
    if titles:
        cur.execute(f"""SELECT p.title, {name_sql()} FROM posts p JOIN sources s ON s.id = p.source_id
                         WHERE {suggestable_sql("s.id")} AND p.title IS NOT NULL AND {pairing.ix_date('p')} > %(since)s
                           AND length(p.title) >= 20 AND NOT {_on_key('s.handle_or_url')}""",
                    {"since": now - timedelta(days=REPEAT_DAYS), "key": key})
        for title, name in cur.fetchall():
            k = _title_key(title)
            if k in titles:
                hits.setdefault(titles[k], set()).add(name)
    names = Counter(n for ns in hits.values() for n in ns)
    cur.execute(f"""SELECT {name_sql()} FROM sources s WHERE {suggestable_sql("s.id")} AND {_addr_sql('s.handle_or_url')} <> ''
                     AND (split_part({_addr_sql('s.handle_or_url')}, '/', 1) = %(site)s
                          OR split_part({_addr_sql('s.handle_or_url')}, '/', 1) LIKE '%%.' || %(site)s)
                     AND NOT {_on_key('s.handle_or_url')} ORDER BY 1 LIMIT 5""", {"site": site, "key": key})
    same_site = [r[0] for r in cur.fetchall()] if site and "/" not in key else []
    return {"items": len(hits), "from": [n for n, _ in names.most_common(5)],
            "ids": sorted(hits, key=lambda x: int(x[1:])), "same_site": same_site}


def followed_before(cur: Cursor, key: str, resolved: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A source at this address (on or turned off): {name, enabled, posts, opened, first_in}; None when none."""
    handle = (resolved or {}).get("handle_or_url") or ""
    cur.execute(f"""SELECT s.id::text, COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url), s.enabled
                      FROM sources s WHERE s.handle_or_url = %(h)s OR {_on_key('s.handle_or_url')}
                     ORDER BY (s.handle_or_url = %(h)s) DESC, s.created_at LIMIT 1""", {"h": handle, "key": key})
    row = cur.fetchone()
    if row is None:
        return None
    sid, name, enabled = row
    cur.execute("""SELECT (SELECT count(*) FROM posts WHERE source_id = %(s)s),
                          (SELECT count(DISTINCT i.post_id) FROM post_interactions i JOIN posts p ON p.id = i.post_id
                            WHERE p.source_id = %(s)s AND i.interaction_type = 'opened'),
                          (SELECT count(*) FROM stories st JOIN posts p ON p.id = st.id
                            WHERE p.source_id = %(s)s AND st.voices >= 2)""", {"s": sid})
    posts, opened, first_in = cur.fetchone()
    return {"name": name, "enabled": bool(enabled), "posts": int(posts), "opened": int(opened), "first_in": int(first_in)}


async def reads_of(http: Any, items: Sequence[Dict[str, Any]], resolved: Dict[str, Any], platform: str
                   ) -> Dict[str, Any]:
    """How its items read, by code (0149 E8): {mode, median, evidence, checked}. mode: full (in the feed), full_page
    (teasers in the feed, the article on its pages: INSIGHT reads it in full), teaser, paywalled, short (posts
    complete as posted: a platform's), video, none."""
    from insight_core.ingestion import full_text
    from insight_core.utils.addresses import host_of, site_of
    chars = [int(i.get("chars") or 0) for i in items]
    median = int(statistics.median(chars)) if chars else 0
    out: Dict[str, Any] = {"median": median, "checked": 0}
    if not items:
        return {**out, "mode": "none", "evidence": "no items"}
    if any(i.get("transcript") is not None for i in items):
        with_t = sum(1 for i in items if i.get("transcript"))
        return {**out, "mode": "video", "evidence": f"videos, {with_t} of {len(items)} with a transcript"}
    if platform in SHORT_PLATFORMS and resolved.get("via") == "kind":
        return {**out, "mode": "short", "evidence": f"posts as posted on the platform (median {median:,} characters)"}
    short = [i for i in items if int(i.get("chars") or 0) < full_text.SHORT_BODY_CHARS]
    if len(short) * 2 <= len(items):
        return {**out, "mode": "full", "evidence": f"full text in the feed (median {median:,} characters)"}
    if resolved.get("via") == "page":
        return {**out, "mode": "teaser", "evidence": f"its pages hold short texts (median {median:,} characters)"}
    outcomes: List[Tuple[str, int, int]] = []
    site = site_of(host_of(resolved.get("handle_or_url") or ""))
    for item in short[:PAGE_CHECKS] if http is not None else []:
        if not full_text.page_is_article(item["url"]):
            continue
        try:
            got = await full_text.read_page(http, item["url"], item.get("text") or "", title=item.get("title") or None,
                                            site=site or None)
        except Exception:  # noqa: BLE001 - an article page that can't be read says nothing
            outcomes.append(("error", int(item.get("chars") or 0), 0))
            continue
        page_chars = len(got.article[1]) if got.article else 0
        outcomes.append((got.outcome, int(item.get("chars") or 0), page_chars))
    out["checked"] = len(outcomes)
    if any(o == full_text.PAYWALLED for o, _, _ in outcomes):
        return {**out, "mode": "paywalled", "evidence": "its article page says it is for paying readers"}
    full = [(c, p) for o, c, p in outcomes if o == full_text.FULL]
    if full:
        c, p = full[0]
        return {**out, "mode": "full_page",
                "evidence": f"the feed gives {c:,} characters, its page about {p:,}: read in full from its pages"}
    if outcomes:
        return {**out, "mode": "teaser",
                "evidence": f"the feed gives a median {median:,} characters and its pages hold nothing longer"}
    return {**out, "mode": "teaser", "evidence": f"short items (median {median:,} characters), no page to check"}


def per_week(items: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Its items a week, from the span of the dated items read, in hours (at least one): 10 items in an hour is a
    rate the read's day-floored cadence (scout_reads.health, at most 63 a week from 10 items) can't show. None: under
    two dated items."""
    dates = sorted(d for d in (_dt(i.get("published_at")) for i in items) if d is not None)
    if len(dates) < 2:
        return None
    hours = max((dates[-1] - dates[0]).total_seconds() / 3600.0, 1.0)
    return round((len(dates) - 1) * 168.0 / hours, 1)


def cadence(rate: Optional[float]) -> str:
    """"about 30 a day (210 a week)", "4 a week", "2 a month"."""
    if rate is not None and rate >= 14:
        return f"about {round(rate / 7):g} a day ({round(rate):g} a week)"
    return scout_reads.cadence_words(rate)


def rewriter(rate: Optional[float], langs: Dict[str, int], link: Dict[str, Any], start: Dict[str, Any],
             items_in: Dict[str, Any]) -> Dict[str, Any]:
    """A rewriter's marks, each from a measurement: {marks: [...], pattern}. The pattern needs the high rate and two
    more marks."""
    marks = []
    if rate is not None and rate >= RATE_HIGH:
        marks.append("high rate")
    if len([l for l in langs if l != "und"]) >= MANY_LANGUAGES:
        marks.append("many languages")
    if not start["stories"] and not items_in["started"]:
        marks.append("never first")
    if link["sources"] <= RARELY_CITED:
        marks.append("rarely cited")
    return {"marks": marks, "pattern": "high rate" in marks and len(marks) >= 3}


def platform_of(key: str, resolved: Optional[Dict[str, Any]]) -> str:
    from insight_core.markx import scout
    p = (resolved or {}).get("platform") or ""
    if p in ("reddit", "youtube", "telegram"):
        return p
    word = scout._platform_word(key, "/" in key)
    if word in ("site", "account") and "nitter" in ((resolved or {}).get("handle_or_url") or ""):
        return "x"
    return word


async def signals(cur: Cursor, http: Any, address: str, items: Sequence[Dict[str, Any]],
                  resolved: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Everything INSIGHT measures about the candidate (the module docstring)."""
    key, site, _ = address_key(cur, address)
    h = scout_reads.health([dict(i, published_at=_dt(i.get("published_at"))) for i in items], now)
    rate = per_week(items)
    langs = Counter(str(i.get("lang") or "und") for i in items)
    link = linked(cur, key, site, now)
    start = started(cur, key, site, now)
    items_in = in_stories(cur, items)
    platform = platform_of(key, resolved)
    reads = await reads_of(http, items, resolved, platform)
    return {"key": key, "site": site, "platform": platform, "linked": link, "stories": start, "items_in": items_in,
            "rate": {"per_week": rate, "newest_days": h["newest_days"], "dated": h["dated"], "items": h["items"],
                     "cadence": cadence(rate)},
            "health": {"reads_well": h["reads_well"], "reason": h["reason"], "labels": h["labels"]},
            "languages": dict(langs.most_common()), "reads": reads,
            "repeats": repeats(cur, items, key, site, now),
            "rewriter": rewriter(rate, dict(langs), link, start, items_in),
            "followed_before": followed_before(cur, key, resolved)}


def _dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


# ---- the reader ---------------------------------------------------------------------------------------------

def interests(cur: Cursor, now: Optional[datetime] = None) -> List[str]:
    """What the reader follows and reads, compact (lines for the question): tracks first, then the sources read most
    in 90 days, what those reads are about, the folders. Each ordered by what is read most."""
    now = now or _now()
    lines: List[str] = []
    from insight_core.markx import tracks
    for t in tracks.described(cur):
        text = re.sub(r"\s+", " ", t.get("description") or "").strip()
        if len(text) > INTEREST_TRACK_CHARS:
            text = text[:INTEREST_TRACK_CHARS].rsplit(" ", 1)[0] + "…"
        lines.append(f"Track “{t['name']}”: {text}")
    since = now - timedelta(days=90)
    cur.execute(f"""SELECT COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url),
                          count(DISTINCT i.post_id)
                     FROM post_interactions i JOIN posts p ON p.id = i.post_id JOIN sources s ON s.id = p.source_id
                    WHERE i.interaction_type = 'opened' AND i.created_at > %s AND {suggestable_sql("s.id")}
                    GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %s""", (since, INTEREST_SOURCES))
    read = cur.fetchall()
    if read:
        lines.append("Reads most (posts opened in 90 days): " + "; ".join(f"{n} ({c})" for n, c in read))
    cur.execute("""SELECT count(*), count(*) FILTER (WHERE enabled) FROM sources""")
    total, on = cur.fetchone()
    cur.execute("""SELECT m.name, count(DISTINCT m.post_id) FROM mx_mentions_now m
                    WHERE m.role IN ('subject', 'actor') AND m.name IS NOT NULL
                      AND m.post_id IN (SELECT i.post_id FROM post_interactions i
                                         WHERE i.interaction_type = 'opened' AND i.created_at > %s)
                    GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT %s""", (since, INTEREST_SUBJECTS))
    subjects = cur.fetchall()
    if subjects:
        lines.append("What those reads are about: " + ", ".join(n for n, _ in subjects))
    cur.execute("""SELECT f.name, count(sf.source_id) FROM folders f JOIN source_folders sf ON sf.folder_id = f.id
                    GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 10""")
    folders = cur.fetchall()
    if folders:
        lines.append("Folders: " + "; ".join(f"{n} ({c} sources)" for n, c in folders))
    lines.append(f"Follows {on} sources ({total - on} turned off).")
    return lines


# ---- the question ---------------------------------------------------------------------------------------------

def _num(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def measured_lines(s: Dict[str, Any]) -> List[str]:
    """The MEASURED part of the question, in words."""
    link, start, items_in, rate = s["linked"], s["stories"], s["items_in"], s["rate"]
    n = rate["items"]
    out = []
    if link["sources"]:
        out.append(f"Linked by your sources: {_num(link['sources'], 'source')} ({_num(link['posts'], 'post')}, "
                   f"{link['recent']} in the last 90 days): {', '.join(link['names'])}")
    else:
        out.append("Linked by your sources: none")
    out.append(f"Stories of yours that started at its pages: {start['stories']} ({start['recent']} in the last 90 days)"
               + (": " + " | ".join(start["titles"]) if start["titles"] else ""))
    out.append(f"Its items in your stories: {items_in['linked']} of {n} linked by your sources, "
               f"{items_in['started']} started a story")
    pace = rate["cadence"] or "unknown"
    newest = f"newest item {rate['newest_days']} days old" if rate["newest_days"] is not None else "items undated"
    out.append(f"Rate: {pace}; {newest}; {rate['dated']} of {n} dated")
    out.append(f"Reads: {s['reads']['mode']}: {s['reads']['evidence']}")
    if s["health"]["reason"]:
        out.append(f"Health: can't read well: {s['health']['reason']}")
    out.append("Languages: " + ", ".join(f"{k} {v}" for k, v in s["languages"].items()))
    rep = s["repeats"]
    line = f"Repeats: {rep['items']} of {n} items you already have" + (f" (from {', '.join(rep['from'])})" if rep["from"] else "")
    if rep["same_site"]:
        line += f"; you follow on its site: {', '.join(rep['same_site'])}"
    out.append(line)
    rw = s["rewriter"]
    out.append("Rewriter marks: " + (", ".join(rw["marks"]) if rw["marks"] else "none")
               + f" (the pattern: {'yes' if rw['pattern'] else 'no'})")
    fb = s.get("followed_before")
    if fb:
        out.append(f"Followed before as {fb['name']} ({'on' if fb['enabled'] else 'turned off'}): {fb['posts']} posts, "
                   f"{fb['opened']} opened, first in {fb['first_in']} stories")
    return out


def question(address: str, resolved: Dict[str, Any], items: Sequence[Dict[str, Any]], s: Dict[str, Any],
             reader: Sequence[str]) -> str:
    via = {"feed": "its feed", "page": "page watching", "kind": "its platform"}.get(resolved.get("via") or "", "")
    title = (resolved.get("title") or "").strip()
    lines = [f"CANDIDATE: {s['key']} ({s['platform']}){' “' + title + '”' if title else ''}, read through {via}: "
             f"{resolved.get('handle_or_url') or address}", "MEASURED:"]
    lines += [f"- {m}" for m in measured_lines(s)]
    lines.append("THE READER:")
    lines += [f"- {r}" for r in reader]
    lines.append("ITEMS (newest first):")
    for i in items:
        when = (i.get("published_at") or "")[:10] or "undated"
        t = re.sub(r"\s+", " ", i.get("title") or "").strip()[:TITLE_CHARS] or "(no title)"
        text = re.sub(r"\s+", " ", i.get("text") or "").strip()[:ITEM_CHARS]
        lines.append(f"[{i['id']}] {when} · {t}")
        if text and text != t:
            lines.append(text)
    return "\n".join(lines)


def scratch_items(items: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The test read's items as the judgement keeps them: newest first, ids i1.., JSON-ready."""
    def at(i: Dict[str, Any]) -> float:
        d = i.get("published_at")
        return d.timestamp() if isinstance(d, datetime) else float("-inf")
    out = []
    for n, i in enumerate(sorted(items, key=at, reverse=True)[:ITEMS], start=1):
        out.append({"id": f"i{n}", "url": i["url"], "title": i.get("title") or "", "text": (i.get("text") or "")[:1500],
                    "chars": int(i.get("chars") or 0), "published_at": _iso(i.get("published_at")),
                    "lang": i.get("lang") or "und", "transcript": i.get("transcript")})
    return out


def _put_task(cur: Cursor, judgement_id: str, q: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """The question (one task per question): its id and its answer when it was answered before."""
    from insight_core.markx import tracks
    schemas.ensure_guides(cur)
    task_id, new = repo.add_task(cur, kind=KIND, guide=schemas.KINDS[KIND].guide, subject_kind=SUBJECT, input=q,
                                 a=judgement_id, priority=PRIORITY)
    got = None if new else tracks._answered_verdict(cur, task_id)
    return str(task_id), (got[1] if got else None)


def _answered(cur: Cursor, judgement_id: str, answer: Dict[str, Any], now: datetime) -> None:
    cur.execute("""UPDATE mx_source_judgements SET status = 'answered', answer = %s::jsonb, verdict = %s, answered_at = %s,
                          busy_until = NULL WHERE id = %s""",
                (json.dumps(answer), answer.get("verdict"), now, judgement_id))


def store_read(cur: Cursor, judgement_id: str, got: scout_reads.ReadResult, items: List[Dict[str, Any]],
               sig: Dict[str, Any], requests: int, now: datetime) -> Dict[str, Any]:
    """The test read and its signals on the judgement; the question asked, or an earlier answer kept (the same items),
    or unreadable."""
    row = get(cur, judgement_id)
    if row is None:
        raise KeyError(judgement_id)
    if not got.resolved or not items:
        reason = got.reason or ("no items" if got.resolved else "could not be read")
        cur.execute("""UPDATE mx_source_judgements SET status = 'unreadable', reason = %s, resolved = %s::jsonb,
                              requests = %s, read_at = %s, busy_until = NULL WHERE id = %s""",
                    (reason, json.dumps(got.resolved) if got.resolved else None, requests, now, judgement_id))
        return get(cur, judgement_id)
    s_items = items
    signature = items_sig(s_items)
    cur.execute("""UPDATE mx_source_judgements SET resolved = %s::jsonb, items = %s::jsonb, items_sig = %s, signals = %s::jsonb,
                          requests = %s, read_at = %s WHERE id = %s""",
                (json.dumps(got.resolved), json.dumps(s_items), signature, json.dumps(sig, default=str), requests, now,
                 judgement_id))
    if row.get("same_as"):
        before = get(cur, row["same_as"])
        if before and before["status"] == "answered" and before["items_sig"] == signature:   # nothing new: it stands
            cur.execute("""UPDATE mx_source_judgements SET status = 'answered', task_id = %s, answer = %s::jsonb,
                                  verdict = %s, answered_at = %s, busy_until = NULL WHERE id = %s""",
                        (before["task_id"], json.dumps(before["answer"]), before["verdict"], now, judgement_id))
            return get(cur, judgement_id)
    q = question(row["address"], got.resolved, s_items, sig, interests(cur, now))
    task_id, answer = _put_task(cur, judgement_id, q)
    cur.execute("UPDATE mx_source_judgements SET status = 'asked', task_id = %s, busy_until = NULL WHERE id = %s",
                (task_id, judgement_id))
    if answer is not None:
        _answered(cur, judgement_id, answer, now)
    return get(cur, judgement_id)


def reads_allowed() -> bool:
    from insight_core.services.discover_reads import enabled
    return enabled()


async def read_and_ask(db_url: str, judgement_id: str, *, reader: Optional[Any] = None, http: Any = None,
                       now: Optional[Callable[[], datetime]] = None) -> Dict[str, Any]:
    """The judgement's test read, its signals and its question (the API's background task). Claimed first; never
    raises for a site's failure; nothing written but the judgement and the question."""
    from insight_core.db import database
    clock = now or _now
    with database.transaction(db_url) as cur:
        if not claim(cur, judgement_id, clock()):
            return {"id": judgement_id, "claimed": False}
        address = get(cur, judgement_id)["address"]
    if not reads_allowed():
        got = scout_reads.ReadResult(reason="reading the web is off on this machine")
    else:
        from insight_core.markx import scout
        reader = reader or scout.default_reader()
        got = await reader.read(address, limit=ITEMS)
    try:
        items = scratch_items(got.items)
        base = http if http is not None else getattr(reader, "http", None)
        client = scout_reads.Counting(base, getattr(reader, "limiter", None)) if base is not None else None
        sig: Dict[str, Any] = {}
        if got.resolved and items:
            with database.transaction(db_url) as cur:
                sig = await signals(cur, client, address, items, got.resolved, clock())
        spent = got.requests + (client.requests if client is not None else 0)
        with database.transaction(db_url) as cur:
            row = store_read(cur, judgement_id, got, items, sig, spent, clock())
    except Exception:  # noqa: BLE001 - the judgement says it failed; the next ask reads again
        log.exception("Source judge %s: the read failed", judgement_id)
        with database.transaction(db_url) as cur:
            cur.execute("""UPDATE mx_source_judgements SET status = 'failed', reason = 'the read failed',
                                  busy_until = NULL WHERE id = %s""", (judgement_id,))
            row = get(cur, judgement_id)
    log.info("Source judge %s (%s): %s, %d items, %d requests", judgement_id, address, row["status"],
             len(row["items"] or []), row["requests"])
    return {"id": judgement_id, "claimed": True, "status": row["status"]}


def after_answer(cur: Cursor, task: Dict[str, Any], answer: Dict[str, Any]) -> int:
    """tasks.record's part for a `source_judge` answer: copied to every judgement asking it."""
    cur.execute("""UPDATE mx_source_judgements SET status = 'answered', answer = %s::jsonb, verdict = %s,
                          answered_at = now() WHERE task_id = %s AND status = 'asked'""",
                (json.dumps(answer), answer.get("verdict"), str(task["id"])))
    return cur.rowcount


# ---- what the page shows ----------------------------------------------------------------------------------------

def view(row: Optional[Dict[str, Any]], now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    now = now or _now()
    answer = row.get("answer") or {}
    items = {i["id"]: i for i in row.get("items") or []}
    examples = [{k: items[e].get(k) for k in ("id", "url", "title", "published_at")}
                for e in answer.get("examples") or [] if e in items]
    s = row.get("signals") or {}
    resolved = row.get("resolved") or {}
    return {"id": row["id"], "address": row["address"], "key": row["key"], "status": row["status"],
            "reason": row.get("reason"), "verdict": row.get("verdict"), "reasons": answer.get("reasons") or [],
            "fits": answer.get("fits"), "original": answer.get("original"), "examples": examples,
            "items": len(items), "follows_as": resolved.get("via"), "follow_address": resolved.get("handle_or_url"),
            "measured": measured_lines(s) if s else [],
            "reads": (s.get("reads") or {}).get("mode"), "cadence": (s.get("rate") or {}).get("cadence"),
            "rewriter": (s.get("rewriter") or {}).get("pattern", False),
            "same_items": bool(row.get("_reused")),
            "asked_at": _iso(row["asked_at"]), "answered_at": _iso(row.get("answered_at")),
            "fresh_until": _iso(row["asked_at"] + timedelta(days=CACHE_DAYS)),
            "fresh": row["asked_at"] >= now - timedelta(days=CACHE_DAYS)}


def page(cur: Cursor, address: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The latest judgement of an address, as the page shows it (None: never asked)."""
    row = latest(cur, address)
    if row is None:
        return None
    if row.get("same_as") and row["status"] == "answered":
        before = get(cur, row["same_as"])
        row["_reused"] = bool(before and before.get("task_id") == row.get("task_id") and before.get("items_sig")
                              == row.get("items_sig"))
    return view(row, now)


__all__ = ["after_answer", "ask", "cache_key", "interests", "measured_lines", "page", "question", "read_and_ask",
           "signals", "store_read", "view"]
