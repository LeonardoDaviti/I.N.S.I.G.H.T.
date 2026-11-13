"""News and Classics storage (issue 0051): News stories and their posts, classics and the ones you
hid. Every method takes the caller's cursor and never commits.

The rules live in utils/news_rules.py; this file reads what they need, writes what they return
(only the rows that differ), and reads News and Classics back for the reader.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from psycopg import Cursor

from insight_core.db.repo_reader import _ITEM_COLUMNS, FeedScope, _item, voiced
from insight_core.db.repo_stories import KEY_CHARS
from insight_core.utils.addresses import paper_id
from insight_core.utils.story_rules import page_key
from insight_core.utils.classic_rules import BACKGROUND_SHOWN, Citation, Classic
from insight_core.utils.news_rules import NewsStory, Surge
from insight_core.db.repo_post_parts import shown_title
from insight_core.utils.post_fields import MOVED_KEY
from insight_core.utils.url_normalization import normalize_url
from insight_core.markx import pairing

LIKE_SPECIAL = re.compile(r"[\\%_]")   # what LIKE reads as more than a letter
OWNERS_KEY = "news_owners"   # system_settings: the voices News counts by owner (issue 0111, SourceFacts.owners)
# A post's date as the story rules read it (published, else fetched).
POST_TIME = pairing.ix_date("p")


def _scope_sql(scope: FeedScope) -> Tuple[str, List[Any]]:
    """The scope as a predicate on a source `s`: in the Main feed, in a track, or that source."""
    if scope.kind == "all":
        return "s.in_main_digest", []
    if scope.kind == "folder":
        return "s.id IN (SELECT sf.source_id FROM source_folders sf WHERE sf.folder_id = %s)", [scope.id]
    if scope.kind == "voice":   # every channel of one voice (issue 0132 A)
        return "s.voice_id = %s", [scope.id]
    return "s.id = %s", [scope.id]


class NewsRepository:
    # ---- the job: names ---------------------------------------------------------------

    @staticmethod
    def load_titles(cur: Cursor, since: Optional[datetime]) -> List[Dict[str, Any]]:
        """The titles the name rule reads: every titled post posted since `since` (every one when None), each
        as every page shows it, or its opening when its stored title said more (post_parts, issue 0076)."""
        cur.execute(
            f"""
            SELECT p.id, p.source_id, {POST_TIME}, t.title FROM posts p LEFT JOIN post_parts pp ON pp.post_id = p.id CROSS JOIN LATERAL (SELECT COALESCE(pp.opening, pp.title, p.title) AS title) t
            WHERE t.title IS NOT NULL AND t.title <> '' AND {POST_TIME} IS NOT NULL
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
    def write_owners(cur: Cursor, owners: Dict[str, str]) -> int:
        """Keep the owners the job counted News voices by (issue 0111), so reading News names them alike.
        Returns 1 when they changed."""
        from insight_core.db.repo_operations import SystemSettingsRepository
        if NewsRepository.owners(cur) == owners:
            return 0
        SystemSettingsRepository.upsert(cur, OWNERS_KEY, owners)
        return 1

    @staticmethod
    def owners(cur: Cursor) -> Dict[str, str]:
        """The owners the last story run counted News voices by: a voice -> its owner's voice."""
        from insight_core.db.repo_operations import SystemSettingsRepository
        row = SystemSettingsRepository.get(cur, OWNERS_KEY)
        return dict(row[0] or {}) if row else {}

    @staticmethod
    def write_news(cur: Cursor, stories: Sequence[NewsStory], *, since: datetime,
                   post_ids: Optional[Sequence[str]] = None) -> Tuple[int, int]:
        """Write `stories`, the News of the window begun at `since`, for `post_ids` (every post when
        None): the News stories holding them before and now, and their rows. Nothing before the window
        is deleted (issue 0077): inside it a row the run no longer finds goes; a row begun before it
        stays as it is, unless no post of it is left (they all moved to rows of the window). Returns
        (rows changed, News rows removed)."""
        changed = removed = 0
        want = {s.id: (s.first_at, s.voices, s.reports, s.shares, s.mentions, round(s.score, 2)) for s in stories}
        want_posts = {p.id: (s.id, s.roles[p.id], p.voice, s.names.get(p.id), position)
                      for s in stories for position, p in enumerate(s.posts)}
        scope = None if post_ids is None else list(post_ids)
        cur.execute(
            """
            SELECT id, first_at, voices, reports, shares, mentions, score FROM news_stories
            WHERE %(ids)s::uuid[] IS NULL OR id = ANY(%(want)s::uuid[])
               OR id IN (SELECT news_id FROM news_posts WHERE post_id = ANY(%(ids)s::uuid[]))
            """,
            {"ids": scope, "want": list(want)},
        )
        have = {str(r[0]): (r[1], r[2], r[3], r[4], r[5], round(float(r[6]), 2)) for r in cur.fetchall()}
        gone = [sid for sid, row in have.items() if sid not in want and row[0] >= since]
        if gone:
            cur.execute("DELETE FROM news_stories WHERE id = ANY(%s::uuid[])", (gone,))
            removed += cur.rowcount
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
        # The run's posts: those it places, and those of the rows it made or of its window; a post of a
        # row begun before the window, placed nowhere now, stays in that row.
        cur.execute("SELECT np.post_id, np.news_id, np.role, np.voice, np.name, np.position, "
                    "ns.first_at >= %(since)s OR np.news_id = ANY(%(want)s::uuid[]) "
                    "FROM news_posts np JOIN news_stories ns ON ns.id = np.news_id "
                    "WHERE %(ids)s::uuid[] IS NULL OR np.post_id = ANY(%(ids)s::uuid[])",
                    {"ids": scope, "since": since, "want": list(want)})
        have_posts = {str(r[0]): (str(r[1]), r[2], r[3], r[4], r[5]) for r in cur.fetchall()
                      if r[6] or str(r[0]) in want_posts}
        drop = [pid for pid in have_posts if pid not in want_posts]
        if drop:
            cur.execute("DELETE FROM news_posts WHERE post_id = ANY(%s::uuid[])", (drop,))
            changed += cur.rowcount
        rows = [(pid, *row) for pid, row in want_posts.items() if have_posts.get(pid) != row]
        if rows:
            cur.executemany(
                """
                INSERT INTO news_posts (post_id, news_id, role, voice, name, position) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (post_id) DO UPDATE SET news_id = EXCLUDED.news_id, role = EXCLUDED.role,
                    voice = EXCLUDED.voice, name = EXCLUDED.name, position = EXCLUDED.position
                """,
                rows,
            )
            changed += len(rows)
        kept = [sid for sid in have if sid not in want and sid not in gone]
        if kept:   # a row before the window with no post left: its story is no more
            cur.execute("DELETE FROM news_stories ns WHERE ns.id = ANY(%s::uuid[]) "
                        "AND NOT EXISTS (SELECT 1 FROM news_posts np WHERE np.news_id = ns.id)", (kept,))
            removed += cur.rowcount
        return changed + removed, removed

    @staticmethod
    def stored_surges(cur: Cursor) -> List[Surge]:
        """Every name's surges as the job keeps them (news_rules.name_surges, issue 0072 A)."""
        cur.execute("SELECT name, at, posts, usual FROM news_surges")
        return [Surge(name, at, [str(p) for p in posts], usual) for name, at, posts, usual in cur.fetchall()]

    @staticmethod
    def write_surges(cur: Cursor, found: Sequence[Surge], names: Optional[Set[str]] = None) -> int:
        """The surges of `names` (every name when None) become exactly `found`. Returns rows changed."""
        want = {(s.name, s.at): (s.posts, s.usual) for s in found}
        cur.execute("SELECT name, at, posts, usual FROM news_surges WHERE %(names)s::text[] IS NULL OR name = ANY(%(names)s)",
                    {"names": None if names is None else sorted(names)})
        have = {(r[0], r[1]): ([str(p) for p in r[2]], r[3]) for r in cur.fetchall()}
        gone = [key for key in have if key not in want]
        if gone:
            cur.executemany("DELETE FROM news_surges WHERE name = %s AND at = %s", gone)
        rows = [(name, at, posts, usual) for (name, at), (posts, usual) in want.items() if have.get((name, at)) != (posts, usual)]
        if rows:
            cur.executemany("INSERT INTO news_surges (name, at, posts, usual) VALUES (%s, %s, %s::uuid[], %s) "
                            "ON CONFLICT (name, at) DO UPDATE SET posts = EXCLUDED.posts, usual = EXCLUDED.usual", rows)
        return len(gone) + len(rows)

    @staticmethod
    def titles_saying(cur: Cursor, words: Sequence[str]) -> List[Dict[str, Any]]:
        """The titled posts whose title may say one of these: a name's words, lowercase, joined by "%"
        (in this order, anything between). Its plain letters (NFKC), lowercase, hold them, or it has an
        entity (decoded only in Python). More than say them, never fewer."""
        cur.execute(
            f"""
            SELECT p.id, p.source_id, {POST_TIME}, t.title FROM posts p LEFT JOIN post_parts pp ON pp.post_id = p.id CROSS JOIN LATERAL (SELECT COALESCE(pp.opening, pp.title, p.title) AS title) t
            WHERE t.title IS NOT NULL AND t.title <> '' AND {POST_TIME} IS NOT NULL
              AND (lower(normalize(t.title, NFKC)) LIKE ANY(%(like)s) OR t.title LIKE '%%&%%;%%')
            """,
            {"like": ["%" + "%".join(LIKE_SPECIAL.sub(r"\\\g<0>", part) for part in w.split("%")) + "%" for w in words]},
        )
        return [{"id": str(r[0]), "source_id": str(r[1]), "t": r[2], "title": r[3]} for r in cur.fetchall()]

    @staticmethod
    def titles_of(cur: Cursor, ids: Sequence[str]) -> List[Dict[str, Any]]:
        cur.execute(f"SELECT p.id, p.source_id, {POST_TIME}, t.title FROM posts p LEFT JOIN post_parts pp ON pp.post_id = p.id CROSS JOIN LATERAL (SELECT COALESCE(pp.opening, pp.title, p.title) AS title) t WHERE p.id = ANY(%s::uuid[]) "
                    f"AND t.title IS NOT NULL AND t.title <> '' AND {POST_TIME} IS NOT NULL", (list(ids),))
        return [{"id": str(r[0]), "source_id": str(r[1]), "t": r[2], "title": r[3]} for r in cur.fetchall()]

    @staticmethod
    def window_posts(cur: Cursor, since: datetime, until: Optional[datetime] = None,
                     ids: Optional[Sequence[str]] = None) -> List[str]:
        """The posts News reads (issue 0072 A): those of the stories begun since `since`, and those in no
        story posted since; with `until`, only those of the stories begun, or posted, before it; with
        `ids`, only these."""
        cur.execute(
            f"""
            SELECT sp.post_id FROM story_posts sp JOIN stories st ON st.id = sp.story_id
            WHERE st.first_at >= %(since)s AND (%(until)s::timestamptz IS NULL OR st.first_at < %(until)s)
              AND (%(ids)s::uuid[] IS NULL OR sp.post_id = ANY(%(ids)s::uuid[]))
            UNION ALL
            SELECT p.id FROM posts p WHERE {POST_TIME} >= %(since)s AND (%(until)s::timestamptz IS NULL OR {POST_TIME} < %(until)s)
              AND (%(ids)s::uuid[] IS NULL OR p.id = ANY(%(ids)s::uuid[]))
              AND NOT EXISTS (SELECT 1 FROM story_posts sp WHERE sp.post_id = p.id)
            """,
            {"since": since, "until": until, "ids": None if ids is None else list(ids)},
        )
        return [str(r[0]) for r in cur.fetchall()]

    @staticmethod
    def named(cur: Cursor, phrases: Sequence[str], at_least: int) -> Set[str]:
        """The phrases that are a name in `at_least` titles (story_keys' "n:" keys)."""
        cur.execute("SELECT substr(key, 3) FROM story_keys WHERE key = ANY(%s) GROUP BY key HAVING count(*) >= %s",
                    (["n:" + p for p in phrases], at_least))
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def surging(cur: Cursor, phrases: Sequence[str]) -> Set[str]:
        """The phrases that are a name with surges kept."""
        cur.execute("SELECT DISTINCT name FROM news_surges WHERE name = ANY(%s)", (list(phrases),))
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def naming(cur: Cursor, names: Sequence[str]) -> Dict[str, Set[str]]:
        """Each of these names -> the posts whose title names it (story_keys' "n:" keys)."""
        cur.execute("SELECT substr(key, 3), post_id FROM story_keys WHERE key = ANY(%s)", (["n:" + n for n in names],))
        out: Dict[str, Set[str]] = {}
        for name, pid in cur.fetchall():
            out.setdefault(name, set()).add(str(pid))
        return out

    @staticmethod
    def news_mates(cur: Cursor, post_ids: Sequence[str]) -> Set[str]:
        """The posts of the News stories these posts are in."""
        cur.execute("SELECT o.post_id FROM news_posts np JOIN news_posts o ON o.news_id = np.news_id "
                    "WHERE np.post_id = ANY(%s::uuid[])", (list(post_ids),))
        return {str(r[0]) for r in cur.fetchall()}

    @staticmethod
    def stories_of(cur: Cursor, post_ids: Sequence[str], since: datetime) -> Dict[str, Dict[str, Any]]:
        """The stories begun since `since` holding these posts: id -> {posts: their ids, mentions: the
        roundups that mention it}."""
        cur.execute(
            """
            SELECT st.id, array_agg(DISTINCT o.post_id),
                   COALESCE((SELECT array_agg(m.post_id) FROM story_mentions m WHERE m.story_id = st.id), '{}')
            FROM story_posts sp JOIN stories st ON st.id = sp.story_id JOIN story_posts o ON o.story_id = st.id
            WHERE sp.post_id = ANY(%s::uuid[]) AND st.first_at >= %s GROUP BY st.id
            """,
            (list(post_ids), since),
        )
        return {str(r[0]): {"posts": [str(p) for p in r[1]], "mentions": {str(p) for p in r[2]}} for r in cur.fetchall()}

    # ---- the job: Classics ------------------------------------------------------------

    @staticmethod
    def citations(cur: Cursor, *, reddit: Sequence[str], saved: Sequence[str],
                  targets: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """Every kept link (to `targets`, when given), with the stored post it is, if any; a Reddit
        post's author (post_parts: its footer's). Not the links of the pages you saved (`saved`: the Saved source): a
        saved page is no voice."""
        cur.execute(
            f"""
            SELECT p.id, p.source_id, {POST_TIME}, pl.target_url, pl.link_text, t.id,
                   CASE WHEN p.source_id = ANY(%(reddit)s::uuid[]) THEN (SELECT pp.author FROM post_parts pp WHERE pp.post_id = p.id) END
            FROM post_links pl
            JOIN posts p ON p.id = pl.post_id
            LEFT JOIN LATERAL (SELECT tp.id, tp.title, tp.content FROM posts tp WHERE tp.normalized_url = pl.target_url
                               ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            WHERE NOT pl.boilerplate AND {POST_TIME} IS NOT NULL AND NOT (p.source_id = ANY(%(saved)s::uuid[]))
              AND (%(targets)s::text[] IS NULL OR pl.target_url = ANY(%(targets)s))
            ORDER BY p.id, pl.position
            """,
            {"reddit": list(reddit), "saved": list(saved), "targets": None if targets is None else list(targets)},
        )
        return [{"post_id": str(r[0]), "source_id": str(r[1]), "t": r[2], "target": r[3], "text": r[4],
                 "stored": str(r[5]) if r[5] else None, "author": r[6]} for r in cur.fetchall()]

    @staticmethod
    def stored_posts(cur: Cursor, ids: Sequence[str]) -> List[Dict[str, Any]]:
        cur.execute(f"SELECT p.id, p.source_id, {POST_TIME}, {shown_title()} FROM posts p WHERE p.id = ANY(%s::uuid[])",
                    (list(ids),))
        return [{"id": str(r[0]), "source_id": str(r[1]), "t": r[2], "title": r[3]} for r in cur.fetchall()]

    @staticmethod
    def write_classics(cur: Cursor, found: Sequence[Classic], targets: Optional[Sequence[str]] = None) -> int:
        """Make the stored classics (of `targets`, when given) exactly `found`. Returns how many rows changed."""
        want = {c.target: (c.post_id, c.voices, c.first_at, c.last_at, c.title, c.citers) for c in found}
        cur.execute("SELECT target_url, post_id, voices, first_at, last_at, title, citers FROM classics "
                    "WHERE %(targets)s::text[] IS NULL OR target_url = ANY(%(targets)s)",
                    {"targets": None if targets is None else list(targets)})
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
    def news_posts(cur: Cursor, scope: FeedScope, since: datetime, news_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Every post of the News stories begun since `since` that have a post in `scope`, as feed
        items, with its story's numbers and its role. Each story's posts first posted first. On one
        source (issue 0077) also the stories a roundup of it mentions (0050's story_mentions).
        `news_id`: that story's only (a post page's row, issue 0083)."""
        scope_sql, params = _scope_sql(scope)
        one = "AND ns.id = %s" if news_id else ""
        mentioned, mention_params = "", []
        if scope.kind in ("source", "voice"):
            mentioned = f"""
              OR EXISTS (SELECT 1 FROM news_posts o JOIN story_posts osp ON osp.post_id = o.post_id
                         JOIN story_mentions m ON m.story_id = osp.story_id
                         JOIN posts mp ON mp.id = m.post_id JOIN sources s ON s.id = mp.source_id
                         WHERE o.news_id = ns.id AND {scope_sql})"""
            mention_params = params
        cur.execute(
            f"""
            SELECT {_ITEM_COLUMNS}, ns.id, ns.first_at, ns.voices, ns.reports, ns.shares, ns.mentions, ns.score,
                   np.role, sp.post_id IS NOT NULL AND sp.parent_reason IS NULL AS origin, ({scope_sql}) AS in_scope,
                   np.voice, p.content_hash, pp.subject,
                   EXISTS (SELECT 1 FROM story_mentions m WHERE m.post_id = p.id) AS roundup,
                   sp.parent_url IS NOT NULL AND sp.parent_reason IN ('citation', 'quote')
                     AND sp.parent_url = (SELECT st.origin_url FROM stories st WHERE st.id = sp.story_id) AS shares_origin,
                   sp.story_id, (SELECT st.voices FROM stories st WHERE st.id = sp.story_id), np.name
            FROM news_stories ns
            JOIN news_posts np ON np.news_id = ns.id
            JOIN posts p ON p.id = np.post_id
            JOIN sources s ON s.id = p.source_id
            LEFT JOIN post_reader_state rs ON rs.post_id = p.id
            LEFT JOIN post_parts pp ON pp.post_id = p.id
            LEFT JOIN story_posts sp ON sp.post_id = p.id
            WHERE ns.first_at >= %s {one}
              AND (EXISTS (SELECT 1 FROM news_posts o JOIN posts op ON op.id = o.post_id JOIN sources s ON s.id = op.source_id
                           WHERE o.news_id = ns.id AND {scope_sql}){mentioned})
            ORDER BY ns.id, np.position NULLS LAST, {pairing.ix_date('p')}, p.id
            """,
            [*params, since, *([news_id] if news_id else []), *params, *mention_params],
        )
        out = []
        for row in cur.fetchall():
            item = _item(row[:-18])
            (sid, first_at, voices, reports, shares, mentions, score, role, origin, in_scope, voice, content_hash, subject,
             roundup, shares_origin, story_id, story_voices_, name) = row[-18:]
            item.update({"_news": str(sid), "_first_at": first_at, "_voices": int(voices), "_reports": int(reports),
                         "_shares": int(shares), "_mentions": int(mentions), "_score": float(score), "role": role,
                         "_in_scope": bool(in_scope), "_origin": bool(origin),
                         "_quotes": row[21],   # issue 0072: a post that only quotes a tweet (post_parts)
                         "_voiced": voiced(row, voice, content_hash), "_subject": subject,
                         "_roundup": bool(roundup),   # issue 0083: without an origin, a roundup gives way
                         "_shares_origin": bool(shares_origin),   # issue 0103: it links its story's outside origin
                         # issue 0111: its 0050 story, that story's voices and the name that joined it to the row
                         "_story": str(story_id) if story_id else None, "_story_voices": int(story_voices_ or 0),
                         "_name": name})
            out.append(item)
        return out

    @staticmethod
    def lines(posts: Sequence[Dict[str, Any]], lead_id: str) -> List[Dict[str, Any]]:
        """A News story's lines under its row, as News and search's News filter show them (issue 0072 D1):
        its posts (news_posts' items) but the lead, each its feed row's title. A post that only quotes a
        post of the story is no line (issue 0072): it was read there."""
        addresses = {normalize_url(p["url"]) for p in posts} - {None}
        return [{
            "id": p["id"], "title": p["title"], "url": p["url"], "source_id": p["source_id"],
            "source_display_name": p["source_display_name"], "platform": p["platform"],
            "sort_at": p["sort_at"], "published_at": p["published_at"], "read_at": p["read_at"],
            "role": p["role"], "repost": p["repost"],   # issue 0070: its line names the author
            "reposted_by": (p["repost"] or {}).get("by") or None,   # issue 0068
        } for p in posts if p["id"] != lead_id and p["_quotes"] not in addresses]

    # ---- reading Classics -------------------------------------------------------------

    @staticmethod
    def classics(cur: Cursor, scope: FeedScope) -> List[Dict[str, Any]]:
        """The classics you did not hide that a source in `scope` cited, with the stored post each
        is now (a page you saved since counts as that post: read, in Later). On one source (issue
        0077) also those that are a post of its own (`own`)."""
        scope_sql, params = _scope_sql(scope)
        own_sql, own_params = "FALSE", []
        if scope.kind == "source":
            own_sql = "EXISTS (SELECT 1 FROM posts op WHERE op.normalized_url = c.target_url AND op.source_id = %s)"
            own_params = [scope.id]
        elif scope.kind == "voice":   # a voice's own posts that are classics, any channel's (issue 0132 A)
            own_sql = ("EXISTS (SELECT 1 FROM posts op JOIN sources os ON os.id = op.source_id "
                       "WHERE op.normalized_url = c.target_url AND os.voice_id = %s)")
            own_params = [scope.id]
        cur.execute(
            f"""
            SELECT c.target_url, c.voices, c.first_at, c.last_at, c.title, c.citers,
                   t.id, t.title, r.read_at, r.later_at, {own_sql}
            FROM classics c
            LEFT JOIN LATERAL (SELECT tp.id, {shown_title("tp")} AS title FROM posts tp WHERE tp.normalized_url = c.target_url
                               ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            LEFT JOIN post_reader_state r ON r.post_id = t.id
            WHERE NOT EXISTS (SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url)
              AND (EXISTS (SELECT 1 FROM jsonb_array_elements(c.citers) ci
                           CROSS JOIN LATERAL jsonb_array_elements_text(ci->'source_ids') x(sid)
                           JOIN sources s ON s.id = x.sid::uuid
                           WHERE {scope_sql}) OR {own_sql})
            """,
            [*own_params, *params, *own_params],
        )
        out: Dict[str, Dict[str, Any]] = {}
        for (url, voices, first_at, last_at, title, citers, post_id, post_title, read_at, later_at, own) in cur.fetchall():
            if url in out:
                continue
            out[url] = {"url": url, "voices": int(voices), "first_at": first_at, "last_at": last_at,
                        "days": (last_at - first_at).days, "title": title, "citers": citers,
                        "post_id": str(post_id) if post_id else None, "post_title": post_title,
                        "read_at": read_at, "later_at": later_at, "own": bool(own)}
        return list(out.values())

    @staticmethod
    def source_name(cur: Cursor, source_id: str) -> Optional[str]:
        """A source's name as its voices are named (SourceFacts.name): its display name, else its address."""
        cur.execute("SELECT COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url) FROM sources WHERE id = %s",
                    (source_id,))
        row = cur.fetchone()
        return row[0] if row else None

    @staticmethod
    def hide_classic(cur: Cursor, url: str) -> None:
        cur.execute("INSERT INTO classic_hidden (target_url) VALUES (%s) ON CONFLICT DO NOTHING", (url,))

    @staticmethod
    def background(cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        """The classics a post links, at most BACKGROUND_SHOWN, most cited first."""
        cur.execute(
            f"""
            SELECT c.target_url, c.voices, c.title, t.id, t.title
            FROM post_links pl
            JOIN classics c ON c.target_url = pl.target_url
            LEFT JOIN LATERAL (SELECT tp.id, {shown_title("tp")} AS title FROM posts tp WHERE tp.normalized_url = c.target_url
                               ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            WHERE pl.post_id = %s AND NOT pl.boilerplate AND t.id IS DISTINCT FROM pl.post_id
              AND NOT EXISTS (SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url)
            ORDER BY c.voices DESC, c.last_at - c.first_at DESC, c.target_url
            LIMIT %s
            """,
            (post_id, BACKGROUND_SHOWN),
        )
        return [{"url": r[0], "voices": int(r[1]), "title": r[2], "post_id": str(r[3]) if r[3] else None,
                 "post_title": r[4]} for r in cur.fetchall()]

    @staticmethod
    def untitled_classics(cur: Cursor) -> List[str]:
        """The classics you did not hide that no stored post is at and the stored data leaves untitled (issue
        0106: their page's own title is read once)."""
        cur.execute("SELECT c.target_url FROM classics c WHERE c.title IS NULL "
                    "AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.normalized_url = c.target_url) "
                    "AND NOT EXISTS (SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url) ORDER BY 1")
        return [r[0] for r in cur.fetchall()]

    @staticmethod
    def unlinked_classics(cur: Cursor) -> List[str]:
        """The classics at an address no kept link points to and no stored post is at (issue 0109 B1): their
        links were read again into another address (a tracker's query dropped), so no batch's links name
        them; a full run has none of them."""
        cur.execute("SELECT c.target_url FROM classics c "
                    "WHERE NOT EXISTS (SELECT 1 FROM post_links pl WHERE pl.target_url = c.target_url AND NOT pl.boilerplate) "
                    "AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.normalized_url = c.target_url) ORDER BY 1")
        return [r[0] for r in cur.fetchall()]

    @staticmethod
    def paper_paths(cur: Cursor, urls: Sequence[str]) -> List[str]:
        """`urls` and every other kept link target of the papers among them (issue 0106: a paper's paths
        are one classic), found by the page key every post linking one of its paths holds (story_keys)."""
        wanted = {page_key(url) for url in urls if paper_id(url)}
        if not wanted:
            return list(urls)
        cur.execute("SELECT DISTINCT pl.target_url FROM story_keys k JOIN post_links pl ON pl.post_id = k.post_id "
                    "WHERE k.key = ANY(%s) AND NOT pl.boilerplate", (sorted(key[:KEY_CHARS] for key in wanted),))
        found = {url for (url,) in cur.fetchall() if paper_id(url) and page_key(url) in wanted}
        return sorted(set(urls) | found)

    @staticmethod
    def moved_pages(cur: Cursor, urls: Optional[Sequence[str]] = None) -> Dict[str, Tuple[str, Optional[str]]]:
        """The stored pages (at `urls`, when given) that moved (issue 0108, metadata.moved_to): address ->
        (where it moved, the post stored there, if any)."""
        cur.execute(
            f"""
            SELECT p.normalized_url, p.metadata ->> '{MOVED_KEY}',
                   (SELECT q.id FROM posts q WHERE q.normalized_url = p.metadata ->> '{MOVED_KEY}'
                    ORDER BY q.fetched_at, q.created_at, q.id LIMIT 1)
            FROM posts p
            WHERE p.metadata ? '{MOVED_KEY}' AND p.normalized_url IS NOT NULL
              AND (%(urls)s::text[] IS NULL OR p.normalized_url = ANY(%(urls)s))
            """,
            {"urls": None if urls is None else list(urls)},
        )
        return {r[0]: (r[1], str(r[2]) if r[2] else None) for r in cur.fetchall() if r[1] and r[1] != r[0]}

    @staticmethod
    def moved_paths(cur: Cursor, urls: Sequence[str]) -> List[str]:
        """`urls`, where the pages among them moved, and the pages that moved to them (issue 0108: one
        classic), so an incremental batch rewrites both."""
        if not urls:
            return list(urls)
        cur.execute(
            f"""
            SELECT p.normalized_url, p.metadata ->> '{MOVED_KEY}' FROM posts p
            WHERE p.metadata ? '{MOVED_KEY}' AND (p.normalized_url = ANY(%(urls)s) OR p.metadata ->> '{MOVED_KEY}' = ANY(%(urls)s))
            """,
            {"urls": list(urls)},
        )
        return sorted(set(urls) | {url for row in cur.fetchall() for url in row if url})

    @staticmethod
    def classic_urls(cur: Cursor) -> List[str]:
        """The classics you did not hide (Discover counts them per site)."""
        cur.execute("SELECT c.target_url FROM classics c WHERE NOT EXISTS "
                    "(SELECT 1 FROM classic_hidden h WHERE h.target_url = c.target_url)")
        return [r[0] for r in cur.fetchall()]


__all__ = ["NewsRepository"]
