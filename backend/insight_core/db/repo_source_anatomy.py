"""Source anatomy (issue 0054): what each source gives, counted from tables that exist. Read only;
every method takes the caller's cursor.

One query per column group, each grouped by source, each counting all time and since `since`
(the last 30 days) by a post's date as the feed sorts it (COALESCE(surfaced_at, published_at,
fetched_at)). A source with nothing in a group has no row in it; the caller reads that as zero.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Tuple

from psycopg import Cursor

from insight_core.db.repo_posts import FULL_TEXT_FLAG
from insight_core.ingestion.kinds.saved import PLATFORM as SAVED_PLATFORM

# A post's date as the feed sorts it.
POST_DATE = "COALESCE(p.surfaced_at, p.published_at, p.fetched_at)"
RECENT = f"{POST_DATE} >= %(since)s"

Counts = Dict[str, Tuple[int, ...]]


def _by_source(cur: Cursor) -> Counts:
    return {str(r[0]): tuple(int(v or 0) for v in r[1:]) for r in cur.fetchall()}


class SourceAnatomyRepository:
    @staticmethod
    def posts(cur: Cursor, since: datetime) -> Counts:
        """(posts, posts recent, read, read recent): read is opened, as History (0052) counts it
        (an `opened` or `reading_session` interaction), never a bulk mark read."""
        cur.execute(
            f"""
            SELECT p.source_id, count(*), count(*) FILTER (WHERE {RECENT}),
                   count(o.post_id), count(o.post_id) FILTER (WHERE {RECENT})
            FROM posts p
            LEFT JOIN (SELECT DISTINCT post_id FROM post_interactions
                        WHERE interaction_type IN ('opened', 'reading_session')) o ON o.post_id = p.id
            GROUP BY p.source_id
            """,
            {"since": since},
        )
        return _by_source(cur)

    @staticmethod
    def stories(cur: Cursor, since: datetime) -> Counts:
        """(stories, stories recent, first, first recent): the stories its posts are in (0050), and
        how many it leads: a story's lead is its first report, else its first share, as the feed
        ranks them (repo_reader._STORY_RANK). Recent by the source's own post."""
        cur.execute(
            f"""
            WITH leads AS (
                SELECT DISTINCT ON (sp.story_id) sp.post_id
                FROM story_posts sp JOIN posts p ON p.id = sp.post_id
                ORDER BY sp.story_id, (sp.role = 'report') DESC, COALESCE(p.published_at, p.fetched_at), p.id
            )
            SELECT p.source_id, count(DISTINCT sp.story_id), count(DISTINCT sp.story_id) FILTER (WHERE {RECENT}),
                   count(l.post_id), count(l.post_id) FILTER (WHERE {RECENT})
            FROM story_posts sp
            JOIN posts p ON p.id = sp.post_id
            LEFT JOIN leads l ON l.post_id = sp.post_id
            GROUP BY p.source_id
            """,
            {"since": since},
        )
        return _by_source(cur)

    @staticmethod
    def classics(cur: Cursor, since: datetime) -> Counts:
        """(classics, classics recent): the classics (0051) its posts link, not hidden ones; a
        source's signature links are no citation, and the Saved source is no voice (as 0051)."""
        cur.execute(
            f"""
            SELECT p.source_id, count(DISTINCT c.target_url), count(DISTINCT c.target_url) FILTER (WHERE {RECENT})
            FROM classics c
            JOIN post_links pl ON pl.target_url = c.target_url AND NOT pl.boilerplate
            JOIN posts p ON p.id = pl.post_id
            JOIN sources s ON s.id = p.source_id AND s.platform <> %(saved)s
            WHERE NOT EXISTS (SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url)
            GROUP BY p.source_id
            """,
            {"since": since, "saved": SAVED_PLATFORM},
        )
        return _by_source(cur)

    @staticmethod
    def links(cur: Cursor, since: datetime) -> Counts:
        """(links, links recent): the outside links its posts gave (0050's post links), less its
        signature and its own site (`boilerplate`)."""
        cur.execute(
            f"""
            SELECT p.source_id, count(*), count(*) FILTER (WHERE {RECENT})
            FROM post_links pl JOIN posts p ON p.id = pl.post_id
            WHERE NOT pl.boilerplate
            GROUP BY p.source_id
            """,
            {"since": since},
        )
        return _by_source(cur)

    @staticmethod
    def reading(cur: Cursor) -> Dict[str, Dict[str, Any]]:
        """How each source is read, beyond its settings: validators stored (0044), any post read
        from its article page (full text), and its watched pages (0039)."""
        cur.execute(
            f"""
            SELECT s.id,
                   EXISTS (SELECT 1 FROM source_fetch_validators v WHERE v.source_id = s.id),
                   EXISTS (SELECT 1 FROM posts p WHERE p.source_id = s.id AND p.metadata ? '{FULL_TEXT_FLAG}'),
                   (SELECT count(*) FROM post_watch w WHERE w.source_id = s.id)
            FROM sources s
            """
        )
        return {str(r[0]): {"validators": bool(r[1]), "pages_read": bool(r[2]), "watched_pages": int(r[3] or 0)}
                for r in cur.fetchall()}
