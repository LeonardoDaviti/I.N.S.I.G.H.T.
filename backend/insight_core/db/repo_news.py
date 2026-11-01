"""News and Classics storage (issue 0051): News stories and their posts, classics and the ones you
hid. Every method takes the caller's cursor and never commits.

The rules live in utils/news_rules.py; this file reads what they need, writes what they return
(only the rows that differ), and reads News and Classics back for the reader.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from psycopg import Cursor

from insight_core.db.repo_reader import _ITEM_COLUMNS, FeedScope, _item
from insight_core.utils.classic_rules import BACKGROUND_SHOWN, Citation, Classic
from insight_core.utils.news_rules import NewsStory
from insight_core.utils.post_fields import quote_only

# A post's date as the story rules read it (published, else fetched).
POST_TIME = "COALESCE(p.published_at, p.fetched_at)"


def _scope_sql(scope: FeedScope) -> Tuple[str, List[Any]]:
    """The scope as a predicate on a source `s`: in the Main feed, in a track, or that source."""
    if scope.kind == "all":
        return "s.in_main_digest", []
    if scope.kind == "folder":
        return "s.id IN (SELECT sf.source_id FROM source_folders sf WHERE sf.folder_id = %s)", [scope.id]
    return "s.id = %s", [scope.id]


class NewsRepository:
    # ---- the job: names ---------------------------------------------------------------

    @staticmethod
    def load_titles(cur: Cursor, since: Optional[datetime]) -> List[Dict[str, Any]]:
        """The titles the name rule reads: every titled post posted since `since` (every one when None)."""
        cur.execute(
            f"""
            SELECT p.id, p.source_id, {POST_TIME}, p.title FROM posts p
            WHERE p.title IS NOT NULL AND p.title <> '' AND {POST_TIME} IS NOT NULL
              AND (%(since)s::timestamptz IS NULL OR {POST_TIME} >= %(since)s)
            """,
            {"since": since},
        )
        return [{"id": str(r[0]), "source_id": str(r[1]), "t": r[2], "title": r[3]} for r in cur.fetchall()]

    @staticmethod
    def followed_since(cur: Cursor) -> Dict[str, datetime]:
        cur.execute("SELECT id, created_at FROM sources")
        return {str(r[0]): r[1] for r in cur.fetchall()}

    # ---- the job: News ----------------------------------------------------------------

    @staticmethod
    def write_news(cur: Cursor, stories: Sequence[NewsStory]) -> int:
        """Make the stored News exactly `stories` (the job's window). Returns how many rows changed."""
        changed = 0
        want = {s.id: (s.first_at, s.voices, s.reports, s.shares, s.mentions, round(s.score, 2)) for s in stories}
        want_posts = {p.id: (s.id, s.roles[p.id], p.voice, s.names.get(p.id)) for s in stories for p in s.posts}
        cur.execute("SELECT id, first_at, voices, reports, shares, mentions, score FROM news_stories")
        have = {str(r[0]): (r[1], r[2], r[3], r[4], r[5], round(float(r[6]), 2)) for r in cur.fetchall()}
        gone = [sid for sid in have if sid not in want]
        if gone:
            cur.execute("DELETE FROM news_stories WHERE id = ANY(%s::uuid[])", (gone,))
            changed += cur.rowcount
        rows = [(sid, *row) for sid, row in want.items() if have.get(sid) != row]
        if rows:
            cur.executemany(
                """
                INSERT INTO news_stories (id, first_at, voices, reports, shares, mentions, score)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET first_at = EXCLUDED.first_at, voices = EXCLUDED.voices,
                    reports = EXCLUDED.reports, shares = EXCLUDED.shares, mentions = EXCLUDED.mentions,
                    score = EXCLUDED.score, updated_at = now()
                """,
                rows,
            )
            changed += len(rows)
        cur.execute("SELECT post_id, news_id, role, voice, name FROM news_posts")
        have_posts = {str(r[0]): (str(r[1]), r[2], r[3], r[4]) for r in cur.fetchall()}
        drop = [pid for pid in have_posts if pid not in want_posts]
        if drop:
            cur.execute("DELETE FROM news_posts WHERE post_id = ANY(%s::uuid[])", (drop,))
            changed += cur.rowcount
        rows = [(pid, *row) for pid, row in want_posts.items() if have_posts.get(pid) != row]
        if rows:
            cur.executemany(
                """
                INSERT INTO news_posts (post_id, news_id, role, voice, name) VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (post_id) DO UPDATE SET news_id = EXCLUDED.news_id, role = EXCLUDED.role,
                    voice = EXCLUDED.voice, name = EXCLUDED.name
                """,
                rows,
            )
            changed += len(rows)
        return changed

    # ---- the job: Classics ------------------------------------------------------------

    @staticmethod
    def citations(cur: Cursor, *, reddit: Sequence[str], saved: Sequence[str]) -> List[Dict[str, Any]]:
        """Every kept link, with the stored post it is, if any; a Reddit post's HTML (its author).
        Not the links of the pages you saved (`saved`: the Saved source): a saved page is no voice."""
        cur.execute(
            f"""
            SELECT p.id, p.source_id, {POST_TIME}, pl.target_url, pl.link_text, t.id,
                   CASE WHEN p.source_id = ANY(%(reddit)s::uuid[]) THEN p.content_html END
            FROM post_links pl
            JOIN posts p ON p.id = pl.post_id
            LEFT JOIN LATERAL (SELECT tp.id, tp.title, tp.content FROM posts tp WHERE tp.normalized_url = pl.target_url
                               ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            WHERE NOT pl.boilerplate AND {POST_TIME} IS NOT NULL AND NOT (p.source_id = ANY(%(saved)s::uuid[]))
            ORDER BY p.id, pl.position
            """,
            {"reddit": list(reddit), "saved": list(saved)},
        )
        return [{"post_id": str(r[0]), "source_id": str(r[1]), "t": r[2], "target": r[3], "text": r[4],
                 "stored": str(r[5]) if r[5] else None, "html": r[6]} for r in cur.fetchall()]

    @staticmethod
    def stored_posts(cur: Cursor, ids: Sequence[str]) -> List[Dict[str, Any]]:
        cur.execute(f"SELECT p.id, p.source_id, {POST_TIME}, p.title, p.content FROM posts p WHERE p.id = ANY(%s::uuid[])",
                    (list(ids),))
        return [{"id": str(r[0]), "source_id": str(r[1]), "t": r[2], "title": r[3], "content": r[4]}
                for r in cur.fetchall()]

    @staticmethod
    def write_classics(cur: Cursor, found: Sequence[Classic]) -> int:
        """Make the stored classics exactly `found`. Returns how many rows changed."""
        want = {c.target: (c.post_id, c.voices, c.first_at, c.last_at, c.title, c.citers) for c in found}
        cur.execute("SELECT target_url, post_id, voices, first_at, last_at, title, citers FROM classics")
        have = {r[0]: (str(r[1]) if r[1] else None, r[2], r[3], r[4], r[5], r[6]) for r in cur.fetchall()}
        changed = 0
        gone = [t for t in have if t not in want]
        if gone:
            cur.execute("DELETE FROM classics WHERE target_url = ANY(%s)", (gone,))
            changed += cur.rowcount
        rows = [(t, row[0], row[1], row[2], row[3], row[4], json.dumps(row[5]))
                for t, row in want.items() if have.get(t) != row]
        if rows:
            cur.executemany(
                """
                INSERT INTO classics (target_url, post_id, voices, first_at, last_at, title, citers)
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (target_url) DO UPDATE SET post_id = EXCLUDED.post_id, voices = EXCLUDED.voices,
                    first_at = EXCLUDED.first_at, last_at = EXCLUDED.last_at, title = EXCLUDED.title,
                    citers = EXCLUDED.citers, updated_at = now()
                """,
                rows,
            )
            changed += len(rows)
        return changed

    # ---- reading News -----------------------------------------------------------------

    @staticmethod
    def news_posts(cur: Cursor, scope: FeedScope, since: datetime) -> List[Dict[str, Any]]:
        """Every post of the News stories begun since `since` that have a post in `scope`, as feed
        items, with its story's numbers and its role. Each story's posts first posted first."""
        scope_sql, params = _scope_sql(scope)
        cur.execute(
            f"""
            SELECT {_ITEM_COLUMNS}, ns.id, ns.first_at, ns.voices, ns.reports, ns.shares, ns.mentions, ns.score,
                   np.role, sp.post_id IS NOT NULL AND sp.parent_reason IS NULL AS origin, ({scope_sql}) AS in_scope
            FROM news_stories ns
            JOIN news_posts np ON np.news_id = ns.id
            JOIN posts p ON p.id = np.post_id
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN post_reader_state rs ON rs.post_id = p.id
            LEFT JOIN story_posts sp ON sp.post_id = p.id
            WHERE ns.first_at >= %s
              AND EXISTS (SELECT 1 FROM news_posts o JOIN posts op ON op.id = o.post_id JOIN sources s ON s.id = op.source_id
                          WHERE o.news_id = ns.id AND {scope_sql})
            ORDER BY ns.id, COALESCE(p.published_at, p.fetched_at), p.id
            """,
            [*params, since, *params],
        )
        out = []
        for row in cur.fetchall():
            item = _item(row[:-10])
            sid, first_at, voices, reports, shares, mentions, score, role, origin, in_scope = row[-10:]
            item.update({"_news": str(sid), "_first_at": first_at, "_voices": int(voices), "_reports": int(reports),
                         "_shares": int(shares), "_mentions": int(mentions), "_score": float(score), "role": role,
                         "_in_scope": bool(in_scope), "_origin": bool(origin),
                         "_quotes": quote_only(row[21])})   # issue 0072: a post that only quotes a tweet
            out.append(item)
        return out

    # ---- reading Classics -------------------------------------------------------------

    @staticmethod
    def classics(cur: Cursor, scope: FeedScope) -> List[Dict[str, Any]]:
        """The classics you did not hide that a source in `scope` cited, with the stored post each
        is now (a page you saved since counts as that post: read, in Later)."""
        scope_sql, params = _scope_sql(scope)
        cur.execute(
            f"""
            SELECT c.target_url, c.voices, c.first_at, c.last_at, c.title, c.citers,
                   t.id, t.title, left(t.content, 400), r.read_at, r.later_at
            FROM classics c
            LEFT JOIN LATERAL (SELECT tp.id, tp.title, tp.content FROM posts tp WHERE tp.normalized_url = c.target_url
                               ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            LEFT JOIN post_reader_state r ON r.post_id = t.id
            WHERE NOT EXISTS (SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url)
              AND EXISTS (SELECT 1 FROM jsonb_array_elements(c.citers) ci
                          CROSS JOIN LATERAL jsonb_array_elements_text(ci->'source_ids') x(sid)
                          JOIN sources s ON s.id = x.sid::uuid
                          WHERE {scope_sql})
            """,
            params,
        )
        out: Dict[str, Dict[str, Any]] = {}
        for url, voices, first_at, last_at, title, citers, post_id, post_title, content, read_at, later_at in cur.fetchall():
            if url in out:
                continue
            out[url] = {"url": url, "voices": int(voices), "first_at": first_at, "last_at": last_at,
                        "days": (last_at - first_at).days, "title": title, "citers": citers,
                        "post_id": str(post_id) if post_id else None, "post_title": post_title, "content": content,
                        "read_at": read_at, "later_at": later_at}
        return list(out.values())

    @staticmethod
    def hide_classic(cur: Cursor, url: str) -> None:
        cur.execute("INSERT INTO classic_hidden (target_url) VALUES (%s) ON CONFLICT DO NOTHING", (url,))

    @staticmethod
    def background(cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        """The classics a post links, at most BACKGROUND_SHOWN, most cited first."""
        cur.execute(
            """
            SELECT c.target_url, c.voices, c.title, t.id, t.title, left(t.content, 400)
            FROM post_links pl
            JOIN classics c ON c.target_url = pl.target_url
            LEFT JOIN LATERAL (SELECT tp.id, tp.title, tp.content FROM posts tp WHERE tp.normalized_url = c.target_url
                               ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            WHERE pl.post_id = %s AND NOT pl.boilerplate AND t.id IS DISTINCT FROM pl.post_id
              AND NOT EXISTS (SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url)
            ORDER BY c.voices DESC, c.last_at - c.first_at DESC, c.target_url
            LIMIT %s
            """,
            (post_id, BACKGROUND_SHOWN),
        )
        return [{"url": r[0], "voices": int(r[1]), "title": r[2], "post_id": str(r[3]) if r[3] else None,
                 "post_title": r[4], "content": r[5]} for r in cur.fetchall()]

    @staticmethod
    def classic_urls(cur: Cursor) -> List[str]:
        """The classics you did not hide (Discover counts them per site)."""
        cur.execute("SELECT c.target_url FROM classics c WHERE NOT EXISTS "
                    "(SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url)")
        return [r[0] for r in cur.fetchall()]


__all__ = ["NewsRepository"]
