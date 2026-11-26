"""Reader interactions (opens, reading sessions, originals opened, favourites), the rows the reader saw, the reader
state built from them and the reader's own reading summary (GET /api/reading/summary).

A reading session's interaction_value: duration_seconds (the time the post was current and its tab visible); since
the reading-usage change also active_seconds (visible, focused, with input or a scroll in the last minute) and depth
(0-1, the farthest the article body was read to). Older rows have duration_seconds alone: readers take both.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from psycopg import Cursor
from insight_core.utils.json_safe import json_default


# What says "the reader opened this post": its page opened, read a while, or its original opened from it.
OPENED_TYPES = ("opened", "reading_session", "opened_source")
# Where a row can be seen (post_seen.surface, 0187).
SEEN_SURFACES = ("news", "track", "feed")
SEEN_BATCH = 500          # the most items one POST /api/reading/seen takes
SUMMARY_POSTS = 2000      # the most opened posts the summary lists one by one (its totals count every one)
_NUMBER = "jsonb_typeof(i.interaction_value->'{k}') = 'number'"


def _seconds(value: Any) -> Optional[int]:
    return None if value is None else int(round(float(value)))


class PostInteractionsRepository:
    """SQL access for post_interactions and the per-post reader state."""

    def record_post_interaction(
        self,
        cur: Cursor,
        post_id: str,
        interaction_type: str,
        interaction_value: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        query = """
            INSERT INTO post_interactions (
                post_id,
                interaction_type,
                interaction_value
            )
            VALUES (%s, %s, %s::jsonb)
            RETURNING id, created_at
        """
        cur.execute(query, (post_id, interaction_type, json.dumps(interaction_value or {}, default=json_default)))
        row = cur.fetchone()
        return {
            "id": str(row[0]),
            "post_id": post_id,
            "interaction_type": interaction_type,
            "interaction_value": interaction_value or {},
            "created_at": row[1],
        }

    def get_post_reader_state(self, cur: Cursor, post_id: str) -> Dict[str, Any]:
        """Interaction-log aggregates plus the read-state projection (read_at, starred_at, later_at, resume_block).
        `is_favorited` comes from post_reader_state.starred_at; the interaction log stays the audit trail.
        """
        query = """
            SELECT
                COUNT(*) FILTER (WHERE i.interaction_type = 'opened') AS open_count,
                MIN(i.created_at) FILTER (WHERE i.interaction_type = 'opened') AS first_opened_at,
                MAX(i.created_at) FILTER (WHERE i.interaction_type = 'opened') AS last_opened_at,
                COALESCE(SUM(
                    CASE
                        WHEN i.interaction_type = 'reading_session'
                        THEN COALESCE((i.interaction_value->>'duration_seconds')::numeric, 0)
                        ELSE 0
                    END
                ), 0) AS total_read_seconds,
                (SELECT rs.read_at FROM post_reader_state rs WHERE rs.post_id = %s) AS read_at,
                (SELECT rs.starred_at FROM post_reader_state rs WHERE rs.post_id = %s) AS starred_at,
                (SELECT rs.resume_block FROM post_reader_state rs WHERE rs.post_id = %s) AS resume_block,
                (SELECT rs.resume_blocks FROM post_reader_state rs WHERE rs.post_id = %s) AS resume_blocks,
                (SELECT rs.later_at FROM post_reader_state rs WHERE rs.post_id = %s) AS later_at
            FROM post_interactions i
            WHERE i.post_id = %s
        """
        cur.execute(query, (post_id, post_id, post_id, post_id, post_id, post_id))
        row = cur.fetchone()
        if not row:
            return {
                "post_id": post_id,
                "is_favorited": False,
                "open_count": 0,
                "first_opened_at": None,
                "last_opened_at": None,
                "total_read_seconds": 0,
                "read_at": None,
                "starred_at": None,
                "resume_block": None,
                "resume_blocks": None,
                "later_at": None,
            }
        return {
            "post_id": post_id,
            "is_favorited": row[5] is not None,
            "open_count": int(row[0] or 0),
            "first_opened_at": row[1],
            "last_opened_at": row[2],
            "total_read_seconds": int(row[3] or 0),
            "read_at": row[4],
            "starred_at": row[5],
            "resume_block": row[6],
            "resume_blocks": row[7],
            "later_at": row[8],
        }

    # ---- seen, not opened ----

    def record_seen(self, cur: Cursor, items: Iterable[Tuple[str, str]]) -> int:
        """Count each (post, surface) seen once more on today's (UTC) row; a post no longer stored is skipped. The
        number of rows written."""
        pairs = [(str(p), s) for p, s in items]
        if not pairs:
            return 0
        cur.execute(
            """INSERT INTO post_seen AS ps (day, post_id, surface, first_at, last_at, count)
               SELECT (now() AT TIME ZONE 'UTC')::date, x.post, x.surface, now(), now(), count(*)
                 FROM unnest(%s::uuid[], %s::text[]) AS x (post, surface)
                 JOIN posts p ON p.id = x.post
                GROUP BY x.post, x.surface
               ON CONFLICT (day, post_id, surface) DO UPDATE
                  SET last_at = EXCLUDED.last_at, count = ps.count + EXCLUDED.count""",
            ([p for p, _ in pairs], [s for _, s in pairs]),
        )
        return cur.rowcount

    # ---- the reader's own reading ----

    def reading_summary(self, cur: Cursor, days: Optional[int], *, now: Optional[datetime] = None) -> Dict[str, Any]:
        """What the reader opened over the last `days` (None: all time), every query bounded by that window:
        `days` the opened posts by UTC day (first open, title, source, active and open seconds, depth, original
        opened); totals by source, track and story; and per source and track the posts seen in a list against those
        of them opened."""
        now = now or datetime.now(timezone.utc)
        since = None if days is None else now - timedelta(days=days)
        since_day = None if since is None else since.astimezone(timezone.utc).date()
        cur.execute(
            f"""SELECT (i.created_at AT TIME ZONE 'UTC')::date AS day, i.post_id, min(i.created_at),
                       sum((i.interaction_value->>'active_seconds')::numeric)
                           FILTER (WHERE i.interaction_type = 'reading_session' AND {_NUMBER.format(k='active_seconds')}),
                       sum((i.interaction_value->>'duration_seconds')::numeric)
                           FILTER (WHERE i.interaction_type = 'reading_session' AND {_NUMBER.format(k='duration_seconds')}),
                       max((i.interaction_value->>'depth')::numeric)
                           FILTER (WHERE i.interaction_type = 'reading_session' AND {_NUMBER.format(k='depth')}),
                       bool_or(i.interaction_type = 'opened_source')
                  FROM post_interactions i
                 WHERE i.interaction_type = ANY(%(types)s) AND (%(since)s::timestamptz IS NULL OR i.created_at >= %(since)s)
                 GROUP BY 1, 2
                 ORDER BY 3 DESC""",
            {"types": list(OPENED_TYPES), "since": since},
        )
        acts = cur.fetchall()
        post_ids = sorted({str(r[1]) for r in acts})
        posts: Dict[str, Dict[str, Any]] = {}
        tracks: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        stories: Dict[str, List[Tuple[str, Optional[str]]]] = defaultdict(list)
        if post_ids:
            cur.execute(
                """SELECT p.id::text, COALESCE(pp.title, p.title), p.source_id::text,
                          COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url)
                     FROM posts p JOIN sources s ON s.id = p.source_id
                     LEFT JOIN post_parts pp ON pp.post_id = p.id
                    WHERE p.id = ANY(%s::uuid[])""", (post_ids,))
            posts = {pid: {"title": t, "source_id": sid, "source": name} for pid, t, sid, name in cur.fetchall()}
            tracks = self._tracks_of(cur, post_ids)
            cur.execute(
                """SELECT sp.post_id::text, st.id::text, st.headline
                     FROM mx_story_posts sp JOIN mx_stories st ON st.id = sp.story_id
                    WHERE sp.valid_to IS NULL AND sp.post_id = ANY(%s::uuid[]) AND st.merged_into IS NULL""",
                (post_ids,))
            for pid, sid, headline in cur.fetchall():
                stories[pid].append((sid, headline))

        rows: List[Dict[str, Any]] = []
        by_source: Dict[str, Dict[str, Any]] = {}
        by_track: Dict[str, Dict[str, Any]] = {}
        by_story: Dict[str, Dict[str, Any]] = {}

        def add(table: Dict[str, Dict[str, Any]], key: str, name: Optional[str], pid: str, active: Optional[int],
                source_opened: bool) -> None:
            got = table.setdefault(key, {"id": key, "name": name, "posts": set(), "active_seconds": 0,
                                         "originals_opened": set()})
            got["posts"].add(pid)
            got["active_seconds"] += active or 0
            if source_opened:
                got["originals_opened"].add(pid)

        for day, post_id, first_at, active, duration, depth, source_opened in acts:
            pid = str(post_id)
            post = posts.get(pid)
            if post is None:
                continue
            active_s, duration_s = _seconds(active), _seconds(duration)
            if len(rows) < SUMMARY_POSTS:
                rows.append({"day": day.isoformat(), "post_id": pid, "at": first_at, "title": post["title"],
                             "source_id": post["source_id"], "source": post["source"], "active_seconds": active_s,
                             "open_seconds": duration_s, "depth": None if depth is None else round(float(depth), 3),
                             "source_opened": bool(source_opened),
                             "tracks": [{"id": t, "name": n} for t, n in tracks.get(pid, [])]})
            add(by_source, post["source_id"], post["source"], pid, active_s, bool(source_opened))
            for tid, name in tracks.get(pid, []):
                add(by_track, tid, name, pid, active_s, bool(source_opened))
            for sid, headline in stories.get(pid, []):
                add(by_story, sid, headline, pid, active_s, bool(source_opened))

        def totals(table: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
            out = [{"id": v["id"], "name": v["name"], "posts": len(v["posts"]), "active_seconds": v["active_seconds"],
                    "originals_opened": len(v["originals_opened"])} for v in table.values()]
            return sorted(out, key=lambda r: (-r["posts"], -r["active_seconds"], r["name"] or ""))

        seen_sources, seen_tracks = self._seen_against_opened(cur, since, since_day)
        return {
            "days": days,
            "since": since,
            "posts": rows,
            "posts_total": len(acts),
            "by_source": totals(by_source),
            "by_track": totals(by_track),
            "by_story": totals(by_story),
            "seen_by_source": seen_sources,
            "seen_by_track": seen_tracks,
        }

    @staticmethod
    def _tracks_of(cur: Cursor, post_ids: Sequence[str]) -> Dict[str, List[Tuple[str, str]]]:
        """{post: [(track id, track name)]} for the tracks each post is in (markx.track_feed.IN_TRACK)."""
        from insight_core.markx.track_feed import IN_TRACK
        cur.execute(
            """SELECT tp.post_id::text, f.id::text, f.name
                 FROM mx_track_places tp JOIN mx_tracks t ON t.folder_id = tp.track_id
                 JOIN folders f ON f.id = t.folder_id
                WHERE tp.post_id = ANY(%s::uuid[]) AND tp.place = ANY(%s)
                ORDER BY f.name""", (list(post_ids), list(IN_TRACK)))
        out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
        for pid, tid, name in cur.fetchall():
            out[pid].append((tid, name))
        return out

    def _seen_against_opened(self, cur: Cursor, since: Optional[datetime], since_day: Any
                             ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Per source and per track: the posts seen in a list since `since_day` and how many of them were opened
        since `since` (sorted most seen first)."""
        cur.execute(
            """SELECT s.post_id::text, p.source_id::text,
                      COALESCE(NULLIF(btrim(src.settings->>'display_name'), ''), src.handle_or_url),
                      EXISTS (SELECT 1 FROM post_interactions i
                               WHERE i.post_id = s.post_id AND i.interaction_type = ANY(%(types)s)
                                 AND (%(since)s::timestamptz IS NULL OR i.created_at >= %(since)s))
                 FROM (SELECT DISTINCT post_id FROM post_seen
                        WHERE %(day)s::date IS NULL OR day >= %(day)s) s
                 JOIN posts p ON p.id = s.post_id JOIN sources src ON src.id = p.source_id""",
            {"types": list(OPENED_TYPES), "since": since, "day": since_day})
        seen = cur.fetchall()
        tracks = self._tracks_of(cur, [r[0] for r in seen]) if seen else {}
        by_source: Dict[str, Dict[str, Any]] = {}
        by_track: Dict[str, Dict[str, Any]] = {}
        for pid, sid, name, opened in seen:
            for table, key, label in [(by_source, sid, name)] + [(by_track, t, n) for t, n in tracks.get(pid, [])]:
                got = table.setdefault(key, {"id": key, "name": label, "seen": 0, "opened": 0})
                got["seen"] += 1
                got["opened"] += int(bool(opened))

        def order(table: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
            return sorted(table.values(), key=lambda r: (-r["seen"], -r["opened"], r["name"] or ""))

        return order(by_source), order(by_track)
