"""Series (issue 0134, migration 0083): the pass that finds a source's series and columns (utils/series.py) and marks
its series navigation in post_refs, and the post page's Series line.

- **The pass** (`run`, the story job's, after the refs are read): the sources with a post stored, changed or whose refs
  were read again since the last pass (an hour of overlap); every source the first time and after a VERSION bump (the
  backfill). Each source's groups are made again from all its posts; a group that changed is a new row and the old one
  is closed (valid_to), never deleted; one that did not is left.
- **Navigation** (`post_refs.navigation`): a same-source link whose two ends are in one group, or whose link words are
  navigation. Set on the source's open refs whose flag differs, with `navigation_at`.
- **The line** (`line`): the post's series, its stored parts in order, prev and next; for a column, the issue and the
  previous and next ones.

Every method takes the caller's cursor and never commits.
"""
from __future__ import annotations

import json
import logging
import time
from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import urljoin

from psycopg import Cursor

from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_post_parts import shown_title
from insight_core.utils import series as rule
from insight_core.utils.post_links import source_kind
from insight_core.utils.url_normalization import normalize_url
from insight_core.markx import pairing

log = logging.getLogger(__name__)

SETTINGS_KEY = "series"
LOCK_KEY = "insight.series"
MARGIN = timedelta(hours=1)
HEAD = 600                       # the text's start the rule reads for a post with no title (the lab's)
PARTS_SHOWN = 50                 # a series' parts on the line
POST_DATE = pairing.ix_date("p")


class SeriesRepository:
    # ---- the pass -----------------------------------------------------------------------

    @staticmethod
    def lock(cur: Cursor) -> bool:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        return cur.fetchone()[0]

    @staticmethod
    def dirty_sources(cur: Cursor, since: Optional[datetime]) -> List[str]:
        """The sources to read again: with a post stored, changed or whose refs were read since `since`; all with None."""
        if since is None:
            cur.execute("SELECT DISTINCT source_id::text FROM posts ORDER BY 1")
        else:
            cur.execute("""SELECT DISTINCT source_id::text FROM posts
                            WHERE updated_at >= %(t)s OR created_at >= %(t)s OR refs_scanned_at >= %(t)s ORDER BY 1""",
                        {"t": since})
        return [r[0] for r in cur.fetchall()]

    @classmethod
    def run(cls, cur: Cursor, now: datetime, *, sources: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """The incremental pass on the caller's transaction (or, with `sources`, those sources only, the state left).
        Its counts."""
        t0 = time.monotonic()
        state = (SystemSettingsRepository.get(cur, SETTINGS_KEY) or ({}, None))[0] or {}
        fresh = state.get("version") != rule.VERSION
        whole = sources is None
        if whole:
            since = None
            if not fresh and state.get("since"):
                since = datetime.fromisoformat(state["since"]) - MARGIN
            sources = cls.dirty_sources(cur, since)
        counts: Counter = Counter()
        for source_id in sources:
            counts.update(cls.compute_source(cur, source_id, now))
        counts["sources"] = len(sources)
        counts["seconds"] = round(time.monotonic() - t0, 3)
        if whole:
            SystemSettingsRepository.upsert(cur, SETTINGS_KEY, {"version": rule.VERSION, "since": now.isoformat(),
                                                                **{k: counts[k] for k in ("sources", "seconds")}})
        if counts["opened"] or counts["closed"] or counts["navigation_changed"] or (fresh and whole):
            log.info("Series pass: %d sources, %d groups opened, %d closed, %d navigation flags changed in %.1f s",
                     counts["sources"], counts["opened"], counts["closed"], counts["navigation_changed"], counts["seconds"])
        return dict(counts)

    @classmethod
    def compute_source(cls, cur: Cursor, source_id: str, now: datetime) -> Counter:
        """One source's groups and navigation flags made again from all its posts."""
        cur.execute("SELECT platform, handle_or_url FROM sources WHERE id = %s", (source_id,))
        row = cur.fetchone()
        if row is None:
            return Counter()
        kind = source_kind(*row)
        cur.execute(f"""SELECT p.id::text, {POST_DATE}, p.title, left(p.content, {HEAD * 2}), p.url, p.normalized_url
                          FROM posts p WHERE p.source_id = %s
                         ORDER BY p.fetched_at, p.created_at, p.id""", (source_id,))
        rows = cur.fetchall()
        posts = [rule.Post(pid, at, title, " ".join((head or "").split())[:HEAD], kind)
                 for pid, at, title, head, _u, _n in rows if at is not None]
        by_url: Dict[str, str] = {}
        by_address: Dict[str, str] = {}
        for pid, _at, _t, _h, url, normalized in rows:   # the first seen first, as Connected resolves
            if url:
                by_url.setdefault(url, pid)
            if normalized:
                by_address.setdefault(normalized, pid)

        def resolve(post: str, absolute: str, address: str) -> Optional[str]:
            got = by_url.get(absolute)
            if got and got != post:
                return got
            got = by_address.get(address)
            return got if got and got != post else None

        # the links whose words may be navigation (NAV_PREFILTER, a superset), read from their text
        cur.execute("""SELECT id::text, url, content_html, content FROM posts
                        WHERE source_id = %s AND content_html ~* %s""", (source_id, rule.NAV_PREFILTER))
        words: Dict[Tuple[str, str], str] = {}
        nav: List[rule.NavLink] = []
        for pid, url, content_html, content in cur.fetchall():
            for address, absolute, w in rule.navigation_links(content_html, content, url):
                words[(pid, address)] = w
                nav.append(rule.NavLink(pid, address, w, resolve(pid, absolute, address)))
        groups = rule.build(posts, nav)
        counts = cls.write_groups(cur, source_id, groups, now)
        # navigation: the open refs of the groups' posts and of the navigation links
        members = sorted({m for g in groups for m in g.members} | {p for p, _a in words})
        links: List[Tuple[str, str, Optional[str], Optional[str]]] = []
        if members:
            cur.execute("""SELECT r.post_id::text, p.url, r.target_address, r.href FROM post_refs r
                             JOIN posts p ON p.id = r.post_id
                            WHERE r.post_id = ANY(%s::uuid[]) AND r.valid_to IS NULL""", (members,))
            for pid, url, address, href in cur.fetchall():
                try:
                    absolute = urljoin(url or "", href)
                except ValueError:
                    absolute = href
                links.append((pid, address, resolve(pid, absolute, address), words.get((pid, address))))
        want = rule.navigation(groups, links)
        counts["navigation_changed"] = cls.mark_navigation(cur, source_id, want, now)
        counts["groups"] = len(groups)
        return counts

    @staticmethod
    def mark_navigation(cur: Cursor, source_id: str, want: Set[Tuple[str, str]], now: datetime) -> int:
        """The source's open refs: navigation exactly for `want` ((post, address)). How many flags changed."""
        cur.execute(
            """WITH w AS (SELECT * FROM unnest(%(posts)s::uuid[], %(addresses)s::text[]) AS w(post_id, address))
               UPDATE post_refs r
                  SET navigation = EXISTS (SELECT 1 FROM w WHERE w.post_id = r.post_id AND w.address = r.target_address),
                      navigation_at = %(now)s
                 FROM posts p
                WHERE p.id = r.post_id AND p.source_id = %(source)s AND r.valid_to IS NULL
                  AND r.navigation IS DISTINCT FROM
                      EXISTS (SELECT 1 FROM w WHERE w.post_id = r.post_id AND w.address = r.target_address)""",
            {"posts": [p for p, _a in sorted(want)], "addresses": [a for _p, a in sorted(want)], "now": now,
             "source": source_id})
        return cur.rowcount

    @staticmethod
    def write_groups(cur: Cursor, source_id: str, groups: Sequence[rule.Group], now: datetime) -> Counter:
        """The source's open series become exactly `groups`: one unchanged is left, the others closed, the new opened."""
        cur.execute("""SELECT s.id::text, s.kind, s.stem,
                              array_agg(sp.post_id::text ORDER BY sp.position), array_agg(sp.number ORDER BY sp.position)
                         FROM series s JOIN series_posts sp ON sp.series_id = s.id
                        WHERE s.source_id = %s AND s.valid_to IS NULL GROUP BY s.id""", (source_id,))
        have = {(kind, stem, tuple(zip(members, numbers))): sid for sid, kind, stem, members, numbers in cur.fetchall()}
        want = {g.key(): g for g in groups}
        gone = [sid for key, sid in have.items() if key not in want]
        if gone:
            cur.execute("UPDATE series SET valid_to = GREATEST(computed_at, %s) WHERE id = ANY(%s::uuid[])", (now, gone))
        opened = 0
        for key, g in want.items():
            if key in have:
                continue
            cur.execute("""INSERT INTO series (source_id, kind, stem, name, total, first_at, last_at, evidence, computed_at)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s) RETURNING id""",
                        (source_id, g.kind, g.stem, g.name, g.total, g.first_at, g.last_at, json.dumps(g.evidence), now))
            sid = cur.fetchone()[0]
            cur.executemany("INSERT INTO series_posts (series_id, post_id, number, position) VALUES (%s, %s, %s, %s)",
                            [(sid, m, g.numbers.get(m), k + 1) for k, m in enumerate(g.members)])
            opened += 1
        return Counter(opened=opened, closed=len(gone))

    # ---- the post page's line -----------------------------------------------------------------

    @staticmethod
    def line(cur: Cursor, post_id: str) -> Optional[Dict[str, Any]]:
        """The post's open series (the earliest begun when several): {id, kind, name, number, position, count, total,
        parts: [{post_id, title, number, date, current}], prev, next}, or None. A column's parts are its previous and
        next issues only."""
        cur.execute("""SELECT s.id::text, s.kind, s.name, s.total, sp.position, sp.number FROM series_posts sp
                         JOIN series s ON s.id = sp.series_id
                        WHERE sp.post_id = %s AND s.valid_to IS NULL ORDER BY s.first_at, s.id LIMIT 1""", (post_id,))
        row = cur.fetchone()
        if row is None:
            return None
        sid, kind, name, total, position, number = row
        cur.execute(f"""SELECT sp.post_id::text, sp.number, sp.position, {shown_title()}, {POST_DATE}
                          FROM series_posts sp JOIN posts p ON p.id = sp.post_id
                         WHERE sp.series_id = %s ORDER BY sp.position""", (sid,))
        parts = [{"post_id": pid, "number": n, "position": pos, "title": " ".join((t or "").split())[:200] or None,
                  "date": at.isoformat() if at else None, "current": pid == post_id}
                 for pid, n, pos, t, at in cur.fetchall()]
        here = next(k for k, p in enumerate(parts) if p["current"])
        prev = parts[here - 1] if here > 0 else None
        nxt = parts[here + 1] if here + 1 < len(parts) else None
        numbers = [int(''.join(c for c in p["number"] if c.isdigit())) for p in parts
                   if p["number"] and any(c.isdigit() for c in p["number"])]
        out_of = max([len(parts)] + numbers + ([total] if total else []))
        shown = [p for p in (prev, parts[here], nxt) if p] if kind == rule.COLUMN else parts[max(0, here - PARTS_SHOWN // 2):][:PARTS_SHOWN]
        return {"id": sid, "kind": kind, "name": name, "number": number, "position": position, "count": len(parts),
                "total": out_of, "parts": shown, "prev": prev, "next": nxt}
