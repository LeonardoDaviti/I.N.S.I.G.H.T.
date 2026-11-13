"""A post's references (issue 0125, migration 0076): storage, the backfill, the signature pass and the Connected read.

- **Written** where post_links is (StoriesRepository.save_post_links: ingestion's post writer for new and updated
  posts; fill_missing_links: the story job's link reading), and by the one-off backfill (`fill_missing`, 500 posts a
  transaction, `FOR UPDATE SKIP LOCKED`, resumable: posts.refs_scanned_at). Only the rows that differ are written; a
  link gone from the text is closed (valid_to), never deleted.
- **The signature pass** (`mark_boilerplate`, called by StoriesRepository.mark_boilerplate): a link in
  SIGNATURE_SHARE of its source's posts and SIGNATURE_MIN_POSTS at least is boilerplate, never a row.
- **Connected** (`connected`): Earlier, the stored posts a post links, in the text's order; Later, the stored posts
  that link it, oldest first (the newest kept by the cap); Outside, its kept links (post_links, not boilerplate)
  no post is at. Resolved by address at read time, as the post page's internal links are (0057): the post with that
  exact url, else the first seen at its normalized address, never the post itself.

Every method takes the caller's cursor and never commits.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence
from urllib.parse import urljoin

from psycopg import Cursor

from insight_core.db.repo_post_parts import shown_title
from insight_core.db.repo_series import SeriesRepository
from insight_core.utils.addresses import host_of
from insight_core.utils.post_refs import PostRef, refs_of, shown_reason
from insight_core.utils.story_rules import SIGNATURE_MIN_POSTS, SIGNATURE_SHARE
from insight_core.utils.url_normalization import normalize_url
from insight_core.markx import pairing

REFS_BATCH = 500
# The caps of the Connected groups (0125 decision 2, the default): each group says how many more it has.
EARLIER_SHOWN, LATER_SHOWN, OUTSIDE_SHOWN = 10, 10, 5
GROUPS = ("earlier", "later", "outside")
POST_DATE = pairing.ix_date("p")


class PostRefsRepository:
    # ---- writing ------------------------------------------------------------------------

    @staticmethod
    def write(cur: Cursor, post_id: str, refs: Sequence[PostRef]) -> None:
        """One post's open refs become exactly `refs`: the others are closed, a closed one linked again opens."""
        cur.execute("UPDATE post_refs SET valid_to = now() WHERE post_id = %s AND valid_to IS NULL "
                    "AND NOT (target_address = ANY(%s))", (post_id, [r.address for r in refs]))
        if refs:
            cur.executemany(
                """
                INSERT INTO post_refs (post_id, target_address, href, position, reason, reason_kind)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (post_id, md5(target_address)) DO UPDATE
                    SET href = EXCLUDED.href, position = EXCLUDED.position, reason = EXCLUDED.reason,
                        reason_kind = EXCLUDED.reason_kind, valid_to = NULL
                    WHERE (post_refs.href, post_refs.position, post_refs.reason, post_refs.reason_kind, post_refs.valid_to)
                          IS DISTINCT FROM (EXCLUDED.href, EXCLUDED.position, EXCLUDED.reason, EXCLUDED.reason_kind, NULL)
                """,
                [(post_id, r.address, r.href, r.position, r.reason, r.reason_kind) for r in refs],
            )

    @classmethod
    def read_post(cls, cur: Cursor, post_id: str, url: Optional[str], content_html: Optional[str],
                  content: Optional[str]) -> None:
        """Write one post's refs from its stored text, and say it was read."""
        cls.write(cur, post_id, refs_of(content_html, content, url))
        cur.execute("UPDATE posts SET refs_scanned_at = now() WHERE id = %s", (post_id,))

    @classmethod
    def fill_missing(cls, cur: Cursor, limit: int = REFS_BATCH) -> int:
        """The backfill: the refs of up to `limit` posts never read (stored before 0125). Returns how many posts."""
        cur.execute(
            """
            SELECT id, url, content_html, content FROM posts
            WHERE refs_scanned_at IS NULL
            ORDER BY id
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (limit,),
        )
        rows = cur.fetchall()
        for post_id, url, content_html, content in rows:
            cls.write(cur, str(post_id), refs_of(content_html, content, url))
        if rows:
            cur.execute("UPDATE posts SET refs_scanned_at = now() WHERE id = ANY(%s::uuid[])", ([r[0] for r in rows],))
        return len(rows)

    @staticmethod
    def missing(cur: Cursor) -> bool:
        """Whether a post's refs still wait to be read, locked rows too."""
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE refs_scanned_at IS NULL)")
        return cur.fetchone()[0]

    # ---- the signature pass -----------------------------------------------------------------

    @staticmethod
    def mark_boilerplate(cur: Cursor, source_ids: Optional[Sequence[str]] = None) -> int:
        """Mark every open ref that is its source's signature (in SIGNATURE_SHARE of its posts, SIGNATURE_MIN_POSTS at
        least), and unmark the others; with `source_ids`, only those sources' refs. Returns the rows changed. A link to
        the source's own site is no signature here: it is the Earlier row to its own post (post_links marks those)."""
        cur.execute(
            """
            WITH n AS (SELECT source_id, count(*) AS posts FROM posts
                       WHERE %(only)s::uuid[] IS NULL OR source_id = ANY(%(only)s::uuid[]) GROUP BY source_id),
            c AS (SELECT p.source_id, r.target_address, count(*) AS posts
                  FROM post_refs r JOIN posts p ON p.id = r.post_id
                  WHERE r.valid_to IS NULL AND (%(only)s::uuid[] IS NULL OR p.source_id = ANY(%(only)s::uuid[]))
                  GROUP BY 1, 2),
            want AS (SELECT r.post_id, r.target_address, c.posts >= %(min_posts)s AND c.posts >= %(share)s * n.posts AS boilerplate
                     FROM post_refs r
                     JOIN posts p ON p.id = r.post_id
                     JOIN n ON n.source_id = p.source_id
                     JOIN c ON c.source_id = p.source_id AND c.target_address = r.target_address
                     WHERE r.valid_to IS NULL)
            UPDATE post_refs r SET boilerplate = want.boilerplate
            FROM want
            WHERE r.post_id = want.post_id AND md5(r.target_address) = md5(want.target_address)
              AND r.boilerplate IS DISTINCT FROM want.boilerplate
            """,
            {"min_posts": SIGNATURE_MIN_POSTS, "share": SIGNATURE_SHARE,
             "only": None if source_ids is None else list(source_ids)},
        )
        return cur.rowcount

    # ---- Connected ----------------------------------------------------------------------

    @classmethod
    def connected(cls, cur: Cursor, post_id: str, *, full: bool = False) -> Optional[Dict[str, Any]]:
        """{earlier, later, outside, more: {group: rows not shown}} of one post, None for no such post. Each row:
        {post_id, url, source, source_id, date, title, same_source, reason, reason_kind}; an Outside row has no
        post_id, source or date, its `host` and its link words as `title`. With `full`, no caps."""
        cur.execute("SELECT source_id::text, url, normalized_url FROM posts WHERE id = %s", (post_id,))
        row = cur.fetchone()
        if row is None:
            return None
        source_id, url, normalized = row
        groups = {"earlier": cls._earlier(cur, post_id, url, source_id),
                  "later": cls._later(cur, post_id, url, normalized, source_id),
                  "outside": cls._outside(cur, post_id)}
        # 0134: series navigation (post_refs.navigation, same source) shows under the Series line, not as Earlier/Later
        navigation: List[Dict[str, Any]] = []
        for g in ("earlier", "later"):
            kept = []
            for r in groups[g]:
                if r.pop("navigation"):
                    navigation.append(dict(r, group=g))
                else:
                    kept.append(r)
            groups[g] = kept
        # issue 0185: each stored row's byline (who wrote it, via whom), one query
        from insight_core.utils.byline import bylines
        stored = [r for rows in (groups["earlier"], groups["later"], navigation) for r in rows if r.get("post_id")]
        bys = bylines(cur, [r["post_id"] for r in stored])
        for r in stored:
            r["byline"] = bys.get(r["post_id"])
        caps = {"earlier": EARLIER_SHOWN, "later": LATER_SHOWN, "outside": OUTSIDE_SHOWN}
        out: Dict[str, Any] = {"more": {}}
        for group, rows in groups.items():
            shown = rows if full else (rows[-caps[group]:] if group == "later" else rows[:caps[group]])
            out[group] = shown
            out["more"][group] = len(rows) - len(shown)
        out["navigation"] = sorted(navigation, key=lambda r: (r["date"] or "", r["post_id"]))   # 0134
        out["series"] = SeriesRepository.line(cur, post_id)   # 0134
        out["references"] = cls._references(cur, post_id)    # 0137 B8: the reference list, shown folded
        return out

    @staticmethod
    def _references(cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        """The links of its references or bibliography section (post_links kind 'reference', issue 0137 B8), in the
        text's order: {url (as written), address, host, title (the link's words)}. Every one: the list is folded."""
        cur.execute("""SELECT target_url, COALESCE(shared_url, target_url), link_text FROM post_links
                       WHERE post_id = %s AND kind = 'reference' ORDER BY position""", (post_id,))
        return [{"url": href, "address": address, "host": host_of(address), "title": words}
                for address, href, words in cur.fetchall()]

    @staticmethod
    def _stored_row(target_id: Any, target_url: str, target_source: str, name: str, at: Any, title: Optional[str],
                    first_line: Optional[str], source_id: str, reason: Optional[str], kind: Optional[str],
                    navigation: bool = False) -> Dict[str, Any]:
        shown = " ".join((title or "").split()) or None
        line, how = shown_reason(reason, kind, shown)
        return {"post_id": str(target_id), "url": target_url, "source": name, "source_id": target_source,
                "date": at.isoformat() if at else None, "title": shown or (first_line or "").strip()[:200] or None,
                "same_source": target_source == source_id, "reason": line, "reason_kind": how,
                "navigation": bool(navigation) and target_source == source_id}

    _SOURCE_NAME = "COALESCE(NULLIF(btrim(s.settings->>'display_name'), ''), s.handle_or_url)"
    _FIRST_LINE = "substring(btrim(COALESCE(p.content, '')) FROM '^[^\\n]{0,200}')"

    @classmethod
    def _earlier(cls, cur: Cursor, post_id: str, url: Optional[str], source_id: str) -> List[Dict[str, Any]]:
        """The stored posts this post links, in the text's order, each once."""
        cur.execute("SELECT target_address, href, reason, reason_kind, navigation FROM post_refs "
                    "WHERE post_id = %s AND valid_to IS NULL AND NOT boilerplate ORDER BY position", (post_id,))
        refs = cur.fetchall()
        if not refs:
            return []
        absolute = []
        for _, href, _, _, _ in refs:
            try:
                absolute.append(urljoin(url or "", href))
            except ValueError:
                absolute.append(href)
        cur.execute(
            f"""
            SELECT k.n, p.id, p.url, p.source_id::text, {cls._SOURCE_NAME}, {POST_DATE}, {shown_title()}, {cls._FIRST_LINE}
            FROM unnest(%s::text[], %s::text[]) WITH ORDINALITY AS k(url, address, n)
            JOIN LATERAL (SELECT tp.id FROM posts tp
                          WHERE (tp.url = k.url OR tp.normalized_url = k.address) AND tp.id <> %s::uuid
                          ORDER BY tp.url = k.url DESC, tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            JOIN posts p ON p.id = t.id JOIN sources s ON s.id = p.source_id
            ORDER BY k.n
            """,
            (absolute, [r[0] for r in refs], post_id),
        )
        out, seen = [], set()
        for n, target, target_url, target_source, name, at, title, first in cur.fetchall():
            if target in seen:   # two addresses of one post: one row
                continue
            seen.add(target)
            _, _, reason, kind, nav = refs[n - 1]
            out.append(cls._stored_row(target, target_url, target_source, name, at, title, first, source_id, reason, kind,
                                       nav))
        return out

    @classmethod
    def _later(cls, cur: Cursor, post_id: str, url: Optional[str], normalized: Optional[str],
               source_id: str) -> List[Dict[str, Any]]:
        """The stored posts that link this one, by its normalized address or its url normalized, oldest first."""
        addresses = sorted({a for a in (normalized, normalize_url(url) if url else None) if a})
        if not addresses:
            return []
        cur.execute(
            f"""
            SELECT DISTINCT ON ({POST_DATE}, p.id) p.id, p.url, p.source_id::text, {cls._SOURCE_NAME}, {POST_DATE},
                   {shown_title()}, {cls._FIRST_LINE}, r.reason, r.reason_kind, r.navigation
            FROM post_refs r JOIN posts p ON p.id = r.post_id JOIN sources s ON s.id = p.source_id
            WHERE r.target_address = ANY(%s) AND r.valid_to IS NULL AND NOT r.boilerplate AND r.post_id <> %s::uuid
            ORDER BY {POST_DATE}, p.id, r.position
            """,
            (addresses, post_id),
        )
        return [cls._stored_row(target, target_url, target_source, name, at, title, first, source_id, reason, kind, nav)
                for target, target_url, target_source, name, at, title, first, reason, kind, nav in cur.fetchall()]

    @staticmethod
    def _outside(cur: Cursor, post_id: str) -> List[Dict[str, Any]]:
        """Its kept links (post_links, not boilerplate) that no post is at, in the text's order."""
        cur.execute(
            """
            SELECT pl.target_url, COALESCE(pl.shared_url, pl.target_url), pl.link_text, r.reason, r.reason_kind
            FROM post_links pl
            LEFT JOIN post_refs r ON r.post_id = pl.post_id AND md5(r.target_address) = md5(pl.target_url)
                                 AND r.target_address = pl.target_url AND r.valid_to IS NULL
            WHERE pl.post_id = %s AND NOT pl.boilerplate AND NOT COALESCE(r.boilerplate, false)
              AND NOT EXISTS (SELECT 1 FROM posts tp WHERE tp.normalized_url = pl.target_url OR tp.url = pl.target_url)
            ORDER BY pl.position
            """,
            (post_id,),
        )
        out = []
        for address, href, words, reason, kind in cur.fetchall():
            line, how = shown_reason(reason, kind, outside=True)
            out.append({"post_id": None, "url": href, "address": address, "host": host_of(address), "source": None,
                        "date": None, "title": words, "same_source": False, "reason": line, "reason_kind": how})
        return out
