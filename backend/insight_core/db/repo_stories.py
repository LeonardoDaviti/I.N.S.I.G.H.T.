"""Stories storage (issue 0050): post links, stories, their posts and mentions, Discover's hidden
suggestions. Every method takes the caller's cursor and never commits.

The rules live in utils/post_links.py and utils/story_rules.py; this file only reads what they
need and writes what they return, touching only the rows that differ.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, urlparse

from psycopg import Cursor

from insight_core.utils.post_links import (PostLink, account_key, extract_links, host_of, is_article,
                                          site_of, source_kind)
from insight_core.utils.story_rules import (HOME_SITE_SHARE, NOT_PUBLISHERS, SIGNATURE_MIN_POSTS, SIGNATURE_SHARE,
                                           Story, source_site)
from insight_core.utils.url_normalization import normalize_url

LINKS_BATCH = 500
# The kinds whose post HTML the rules read beyond its links: a Reddit author, a link post's words.
HTML_KINDS = ("reddit", "hn")


def source_account(platform: Optional[str], handle: Optional[str]) -> Optional[str]:
    """The platform account a source follows, as Discover keys it (post_links.account_key): a
    Telegram channel read through a bridge is t.me/<channel>, a Nitter feed x.com/<user>, a
    subreddit reddit.com/r/<sub>, a YouTube channel youtube.com/channel/<id>, any other address
    the account its path is under (github.com/<owner>). The kinds' own parsers read the address."""
    from insight_core.ingestion.kinds import nitter_rss, reddit, telegram_rss

    handle = (handle or "").strip()
    kind = source_kind(platform, handle)
    try:
        if kind == "telegram":
            channel = telegram_rss._username(handle) if "://" in handle else handle
            return "t.me/" + channel.lstrip("@").lower()
        if kind == "x" and "nitter" in handle:
            return "x.com/" + nitter_rss._username(handle).lower()
        if kind == "reddit":
            return "reddit.com/r/" + reddit.subreddit_name(handle).lower()
    except ValueError:
        return None
    if kind == "youtube":
        channel = (parse_qs(urlparse(handle).query).get("channel_id") or [handle if "://" not in handle else ""])[0]
        if channel:
            return "youtube.com/" + (channel.lower() if channel.startswith("@") else "channel/" + channel.lower())
    url = normalize_url(handle) if "://" in handle else None
    return account_key(url) if url else None


class SourceFacts:
    """What the rules need of every source: its kind, its own site and its name."""

    def __init__(self, cur: Cursor) -> None:
        cur.execute("SELECT id, platform, handle_or_url, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url) FROM sources")
        rows = cur.fetchall()
        self.kind = {str(r[0]): source_kind(r[1], r[2]) for r in rows}
        self.name = {str(r[0]): r[3] for r in rows}
        self.account = {str(r[0]): source_account(r[1], r[2]) for r in rows}
        # The Saved source's pages come from any site: it has no site of its own.
        self.handle_site = {str(r[0]): site_of(host_of(r[2] if "://" in (r[2] or "") else "")) for r in rows
                            if self.kind[str(r[0])] != "saved"}
        cur.execute("SELECT source_id, url_host, count(*) FROM posts WHERE url_host IS NOT NULL GROUP BY 1, 2")
        hosts: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for source_id, host, n in cur.fetchall():
            if self.kind.get(str(source_id)) != "saved":
                hosts[str(source_id)].append((host, int(n)))
        self.site = {source_id: source_site(pairs) for source_id, pairs in hosts.items()}
        # How much of a source is on its own site (issue 0064): an aggregator's most common site
        # is only where it links most (Hacker News: 8% github.com on the server's data).
        self._site_share = {
            source_id: sum(n for host, n in pairs if site_of(host) == self.site[source_id]) / sum(n for _, n in pairs)
            for source_id, pairs in hosts.items() if sum(n for _, n in pairs)
        }

    def own_site(self, source_id: str) -> str:
        return self.site.get(source_id) or self.handle_site.get(source_id) or ""

    def home_site(self, source_id: str) -> str:
        """The site a source publishes on (issue 0064), "" when none can be told: its own site, if
        its address is on it or half its posts are; never Hacker News' or Saved's."""
        site = self.own_site(source_id)
        if not site or self.kind.get(source_id) in NOT_PUBLISHERS:
            return ""
        if site == self.handle_site.get(source_id) or self._site_share.get(source_id, 0) >= HOME_SITE_SHARE:
            return site
        return ""

    def followed(self) -> Set[str]:
        """The sites you follow: each source's own site, and the site of its address."""
        return {s for s in (*self.site.values(), *self.handle_site.values()) if s}

    def followed_accounts(self) -> Set[str]:
        """The platform accounts you follow (source_account): on a platform, only these are followed."""
        return {a for a in self.account.values() if a}

    def voice_name(self, voice: str, source_id: str) -> str:
        """A voice as you know it: u/<author> on Reddit, else its source's name."""
        return "u/" + voice.split(":", 1)[1] if voice.startswith("reddit:") else self.name.get(source_id, "")

    def of_kind(self, *kinds: str) -> List[str]:
        return [source_id for source_id, kind in self.kind.items() if kind in kinds]

    def html_sources(self) -> List[str]:
        return [source_id for source_id, kind in self.kind.items() if kind in HTML_KINDS]


class StoriesRepository:
    # ---- post links -------------------------------------------------------------------

    @staticmethod
    def write_links(cur: Cursor, post_id: str, links: Sequence[PostLink]) -> None:
        """One post's links become exactly `links` (rows that did not change are not written)."""
        cur.execute("DELETE FROM post_links WHERE post_id = %s AND NOT (target_url = ANY(%s))",
                    (post_id, [link.url for link in links]))
        if links:
            cur.executemany(
                """
                INSERT INTO post_links (post_id, target_url, target_site, position, link_text)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (post_id, target_url) DO UPDATE
                    SET target_site = EXCLUDED.target_site, position = EXCLUDED.position, link_text = EXCLUDED.link_text
                    WHERE (post_links.target_site, post_links.position, post_links.link_text)
                          IS DISTINCT FROM (EXCLUDED.target_site, EXCLUDED.position, EXCLUDED.link_text)
                """,
                [(post_id, link.url, link.site, link.position, link.text) for link in links],
            )

    def save_post_links(self, cur: Cursor, post_id: str) -> None:
        """Read a stored post's links from its stored HTML (what the saver kept, not the draft)."""
        cur.execute(
            """
            SELECT p.url, p.content_html, s.platform, s.handle_or_url
            FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = %s
            """,
            (post_id,),
        )
        row = cur.fetchone()
        if row is None:
            return
        url, content_html, platform, handle = row
        self.write_links(cur, post_id, extract_links(content_html, url, source_kind(platform, handle)))
        cur.execute("UPDATE posts SET links_scanned_at = now() WHERE id = %s AND links_scanned_at IS NULL", (post_id,))

    def fill_missing_links(self, cur: Cursor, limit: int = LINKS_BATCH) -> int:
        """Read the links of up to `limit` posts never read (stored before 0050, or whose text a
        repair rewrote). Returns how many posts were read."""
        cur.execute(
            """
            SELECT p.id, p.url, p.content_html, s.platform, s.handle_or_url
            FROM posts p JOIN sources s ON s.id = p.source_id
            WHERE p.links_scanned_at IS NULL
            ORDER BY p.id
            LIMIT %s
            FOR UPDATE OF p SKIP LOCKED
            """,
            (limit,),
        )
        rows = cur.fetchall()
        for post_id, url, content_html, platform, handle in rows:
            self.write_links(cur, str(post_id), extract_links(content_html, url, source_kind(platform, handle)))
        if rows:
            cur.execute("UPDATE posts SET links_scanned_at = now() WHERE id = ANY(%s::uuid[])", ([r[0] for r in rows],))
        return len(rows)

    @staticmethod
    def mark_boilerplate(cur: Cursor, sources: SourceFacts) -> int:
        """Mark every link that is its source's signature (in SIGNATURE_SHARE of its posts and
        SIGNATURE_MIN_POSTS at least) or points at its source's own site. Returns rows changed."""
        own = list(sources.site.items())
        cur.execute(
            """
            WITH n AS (SELECT source_id, count(*) AS posts FROM posts GROUP BY source_id),
            c AS (SELECT p.source_id, pl.target_url, count(*) AS posts
                  FROM post_links pl JOIN posts p ON p.id = pl.post_id GROUP BY 1, 2),
            own AS (SELECT * FROM unnest(%s::uuid[], %s::text[]) AS o(source_id, site)),
            want AS (
                SELECT pl.post_id, pl.target_url,
                       (c.posts >= %s AND c.posts >= %s * n.posts) OR pl.target_site = own.site AS boilerplate
                FROM post_links pl
                JOIN posts p ON p.id = pl.post_id
                JOIN n ON n.source_id = p.source_id
                JOIN c ON c.source_id = p.source_id AND c.target_url = pl.target_url
                LEFT JOIN own ON own.source_id = p.source_id
            )
            UPDATE post_links pl SET boilerplate = COALESCE(want.boilerplate, false)
            FROM want
            WHERE pl.post_id = want.post_id AND pl.target_url = want.target_url
              AND pl.boilerplate IS DISTINCT FROM COALESCE(want.boilerplate, false)
            """,
            ([s for s, _ in own], [site for _, site in own], SIGNATURE_MIN_POSTS, SIGNATURE_SHARE),
        )
        return cur.rowcount

    # ---- the story job ----------------------------------------------------------------

    @staticmethod
    def load_posts(cur: Cursor, sources: SourceFacts, cutoff: Optional[datetime]) -> List[Dict[str, Any]]:
        """The posts the job recomputes: posted since `cutoff` (every post when None), less those in
        a story that began before it (frozen). Each with its kept links, in order, and the stored
        post each link is, if any."""
        cur.execute(
            """
            SELECT p.id, p.source_id, COALESCE(p.published_at, p.fetched_at), p.title, p.content_hash,
                   length(p.content), p.normalized_url,
                   CASE WHEN p.source_id = ANY(%(html)s::uuid[]) THEN p.content_html END,
                   COALESCE(p.metadata ? 'page_update', false)
            FROM posts p
            WHERE COALESCE(p.published_at, p.fetched_at) IS NOT NULL
              AND (%(cutoff)s::timestamptz IS NULL OR COALESCE(p.published_at, p.fetched_at) >= %(cutoff)s)
              AND NOT EXISTS (SELECT 1 FROM story_posts sp JOIN stories st ON st.id = sp.story_id
                              WHERE sp.post_id = p.id AND st.first_at < %(cutoff)s)
            """,
            {"html": sources.html_sources(), "cutoff": cutoff},
        )
        posts = [
            {"id": str(r[0]), "source_id": str(r[1]), "t": r[2], "title": r[3], "content_hash": r[4],
             "text_chars": r[5] or 0, "url": r[6], "html": r[7], "updated": r[8], "links": [], "link_texts": {}}
            for r in cur.fetchall()
        ]
        by_id = {p["id"]: p for p in posts}
        cur.execute(
            """
            SELECT pl.post_id, pl.target_url, t.id, pl.link_text
            FROM post_links pl LEFT JOIN LATERAL (SELECT tp.id, tp.title, tp.content FROM posts tp WHERE tp.normalized_url = pl.target_url
                               ORDER BY tp.fetched_at, tp.created_at, tp.id LIMIT 1) t ON TRUE
            WHERE NOT pl.boilerplate AND pl.post_id = ANY(%s::uuid[])
            ORDER BY pl.post_id, pl.position
            """,
            (list(by_id),),
        )
        for post_id, target, stored, text in cur.fetchall():
            by_id[str(post_id)]["links"].append((target, str(stored) if stored else None))
            if text:
                by_id[str(post_id)]["link_texts"][target] = text
        return posts

    @staticmethod
    def write_stories(cur: Cursor, stories: Sequence[Story], *, post_ids: Sequence[str],
                      cutoff: Optional[datetime]) -> int:
        """Make the stored stories match `stories`, the stories of `post_ids` (every post posted
        since `cutoff`, less the frozen): stories begun since `cutoff`, those posts' story rows and
        the mentions they make. Writes only what differs; returns how many rows changed."""
        changed = 0
        want_posts: Dict[str, Tuple[Any, ...]] = {}
        want_mentions: Set[Tuple[str, str]] = set()
        for story in stories:
            for post in story.posts:
                # Its tree (issue 0064): the parent post, else the outside page origin, and why.
                parent_id, parent_url, reason = story.parents.get(post.id, (None, None, None))
                want_posts[post.id] = (story.id, story.roles[post.id], story.reasons[post.id], post.voice,
                                       parent_id, reason, parent_url)
            want_mentions |= {(story.id, pid) for pid in story.mentions}
        want = {story.id: (story.first_at, story.voices, story.origin_url, story.origin_title,
                           story.origin_linked_by if story.origin_url else None) for story in stories}

        cur.execute(
            """
            SELECT id, first_at, voices, origin_url, origin_title, origin_linked_by FROM stories
            WHERE %s::timestamptz IS NULL OR first_at >= %s
            """,
            (cutoff, cutoff),
        )
        have = {str(r[0]): tuple(r[1:]) for r in cur.fetchall()}
        gone = [sid for sid in have if sid not in want]
        if gone:
            cur.execute("DELETE FROM stories WHERE id = ANY(%s::uuid[])", (gone,))
            changed += cur.rowcount
        rows = [(sid, *row) for sid, row in want.items() if have.get(sid) != row]
        if rows:
            cur.executemany(
                """
                INSERT INTO stories (id, first_at, voices, origin_url, origin_title, origin_linked_by)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET first_at = EXCLUDED.first_at, voices = EXCLUDED.voices,
                    origin_url = EXCLUDED.origin_url, origin_title = EXCLUDED.origin_title,
                    origin_linked_by = EXCLUDED.origin_linked_by, updated_at = now()
                """,
                rows,
            )
            changed += len(rows)

        cur.execute(
            """
            SELECT post_id, story_id, role, reasons, voice, parent_id, parent_reason, parent_url
            FROM story_posts WHERE post_id = ANY(%s::uuid[])
            """,
            (list(post_ids),),
        )
        have_posts = {str(r[0]): (str(r[1]), r[2], list(r[3]), r[4], str(r[5]) if r[5] else None, r[6], r[7])
                      for r in cur.fetchall()}
        drop = [pid for pid in have_posts if pid not in want_posts]
        if drop:
            cur.execute("DELETE FROM story_posts WHERE post_id = ANY(%s::uuid[])", (drop,))
            changed += cur.rowcount
        rows = [(pid, *row) for pid, row in want_posts.items() if have_posts.get(pid) != row]
        if rows:
            # parent_id references story_posts, checked at commit: a parent may be written after its child.
            cur.executemany(
                """
                INSERT INTO story_posts (post_id, story_id, role, reasons, voice, parent_id, parent_reason, parent_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (post_id) DO UPDATE
                    SET story_id = EXCLUDED.story_id, role = EXCLUDED.role, reasons = EXCLUDED.reasons, voice = EXCLUDED.voice,
                        parent_id = EXCLUDED.parent_id, parent_reason = EXCLUDED.parent_reason, parent_url = EXCLUDED.parent_url
                """,
                rows,
            )
            changed += len(rows)

        cur.execute(
            """
            SELECT m.story_id, m.post_id FROM story_mentions m JOIN stories st ON st.id = m.story_id
            WHERE m.post_id = ANY(%s::uuid[]) AND (%s::timestamptz IS NULL OR st.first_at >= %s)
            """,
            (list(post_ids), cutoff, cutoff),
        )
        have_mentions = {(str(r[0]), str(r[1])) for r in cur.fetchall()}
        for story_id, post_id in have_mentions - want_mentions:
            cur.execute("DELETE FROM story_mentions WHERE story_id = %s AND post_id = %s", (story_id, post_id))
            changed += cur.rowcount
        new = sorted(want_mentions - have_mentions)
        if new:
            cur.executemany("INSERT INTO story_mentions (story_id, post_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", new)
            changed += len(new)

        # A frozen story whose posts went with a removed source is no story any more.
        cur.execute(
            """
            DELETE FROM stories st WHERE (SELECT count(DISTINCT p.source_id) FROM story_posts sp
                                          JOIN posts p ON p.id = sp.post_id WHERE sp.story_id = st.id) < 2
            """
        )
        return changed + cur.rowcount

    # ---- Discover (its counts: repo_discover.py) -----------------------------------------

    @staticmethod
    def linked_articles(cur: Cursor, host: str) -> List[str]:
        """The article-like addresses on a host (www. aside) your sources' kept links point to,
        once each, in address order: what a site's findings are ranked by (issue 0060)."""
        host = (host or "").lower().removeprefix("www.")
        if not host:
            return []
        cur.execute("SELECT DISTINCT target_url FROM post_links WHERE target_site = %s AND NOT boilerplate",
                    (site_of(host),))
        return sorted(url for (url,) in cur.fetchall() if host_of(url).removeprefix("www.") == host and is_article(url))

    @staticmethod
    def discover_inputs(cur: Cursor) -> str:
        """What Discover is computed from, in one string: the last story run (links are read before
        it), the sources (added, removed, renamed) and the hidden suggestions. Same string, same list."""
        cur.execute(
            """
            SELECT concat_ws('|', (SELECT value::text FROM system_settings WHERE key = 'stories'),
                             (SELECT count(*) || ':' || COALESCE(max(updated_at)::text, '') FROM sources),
                             (SELECT count(*) || ':' || COALESCE(max(hidden_at)::text, '') FROM discover_hidden))
            """
        )
        return cur.fetchone()[0]

    @staticmethod
    def hidden(cur: Cursor) -> Set[str]:
        cur.execute("SELECT key FROM discover_hidden")
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def hide(cur: Cursor, keys: Iterable[str], reason: str) -> None:
        cur.executemany(
            "INSERT INTO discover_hidden (key, reason) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
            [(key, reason) for key in keys if key],
        )

    def hide_removed_source(self, cur: Cursor, source_id: str) -> None:
        """A source about to be removed is never suggested again: a website by its site, and any
        source by the platform account it follows (a channel, a subreddit, a GitHub owner)."""
        cur.execute("SELECT platform, handle_or_url FROM sources WHERE id = %s", (source_id,))
        row = cur.fetchone()
        if row is None:
            return
        keys = {source_account(row[0], row[1])}
        if source_kind(row[0], row[1]) == "site":
            cur.execute("SELECT url_host, count(*) FROM posts WHERE source_id = %s AND url_host IS NOT NULL GROUP BY 1",
                        (source_id,))
            keys.add(source_site(cur.fetchall()) or site_of(host_of(row[1] if "://" in (row[1] or "") else "")))
        self.hide(cur, keys, "removed")
