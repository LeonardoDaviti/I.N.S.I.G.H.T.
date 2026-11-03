"""Stories storage (issue 0050): post links, stories, their posts and mentions, Discover's hidden
suggestions. Every method takes the caller's cursor and never commits.

The rules live in utils/post_links.py, story_rules.py, tree_rules.py and discover_rules.py; this
file only reads what they need and writes what they return, touching only the rows that differ.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, urlparse

from psycopg import Cursor

from insight_core.utils.addresses import PLATFORM_SITES, account_key, host_of, publication_of, site_of, x_account
from insight_core.utils.post_links import PLATFORM_KINDS, PostLink, extract_links, is_article, source_kind
from insight_core.utils.discover_rules import DISCOVER_PLATFORMS
from insight_core.utils.story_rules import (HOME_SITE_SHARE, NOT_PUBLISHERS, SIGNATURE_MIN_POSTS, SIGNATURE_SHARE, Edge, Story,
                                            source_site)
from insight_core.utils.tree_rules import _PAGE
from insight_core.utils.url_normalization import normalize_url

LINKS_BATCH = 500
KEY_CHARS = 500   # a key is kept to its first 500 characters (an index's row limit): two longer ones may share a row, never miss one


def source_account(platform: Optional[str], handle: Optional[str]) -> Optional[str]:
    """The platform account a source follows, as Discover keys it (addresses.account_key): a
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
            return x_account(nitter_rss._username(handle))
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
    """What the rules need of every source: its kind, its own site, its publication and its name."""

    def __init__(self, cur: Cursor) -> None:
        cur.execute("SELECT id, platform, handle_or_url, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url) FROM sources")
        rows = cur.fetchall()
        cur.execute("SELECT source_id, url_host, count(*) FROM posts WHERE url_host IS NOT NULL GROUP BY 1, 2")
        self._read(rows, cur.fetchall())

    @classmethod
    def of(cls, rows: Iterable[Tuple[Any, ...]], hosts: Iterable[Tuple[Any, str, int]]) -> "SourceFacts":
        """The facts of these sources ((id, platform, handle, name)) and their posts' hosts ((source, host,
        posts)), as read from the database: the rules' stamp reads its sample so (utils/stamps.py)."""
        facts = cls.__new__(cls)
        facts._read(list(rows), list(hosts))
        return facts

    def _read(self, rows: List[Tuple[Any, ...]], host_rows: List[Tuple[Any, str, int]]) -> None:
        self.kind = {str(r[0]): source_kind(r[1], r[2]) for r in rows}
        self.name = {str(r[0]): r[3] for r in rows}
        self.account = {str(r[0]): source_account(r[1], r[2]) for r in rows}
        # The source following each account (issue 0068: who reposted a tweet), the first by id.
        self.of_account = {a: i for i, a in sorted(self.account.items(), reverse=True) if a}
        # The Saved source's pages come from any site: it has no site of its own.
        self.handle_site = {str(r[0]): site_of(host_of(r[2] if "://" in (r[2] or "") else "")) for r in rows
                            if self.kind[str(r[0])] != "saved"}
        self.handle_host = {str(r[0]): publication_of(host_of(r[2] if "://" in (r[2] or "") else "")) for r in rows
                            if self.kind[str(r[0])] != "saved"}
        hosts: Dict[str, List[Tuple[str, int]]] = defaultdict(list)
        for source_id, host, n in host_rows:
            if self.kind.get(str(source_id)) != "saved":
                hosts[str(source_id)].append((host, int(n)))
        self.site = {source_id: source_site(pairs) for source_id, pairs in hosts.items()}
        self.host = {source_id: source_site(pairs, of=publication_of) for source_id, pairs in hosts.items()}
        # A site of publications (issue 0070): one your website sources publish on at 2+ hosts
        # (Substack's writers, github.io's). Elsewhere a site's other hosts are its publisher's own
        # (tools.simonwillison.net, forms.technologyreview.com: measured on the lab).
        hosts_of: Dict[str, Set[str]] = defaultdict(set)
        for source_id, site in self.site.items():
            if self.kind.get(source_id) == "site":
                hosts_of[site].add(self.host[source_id])
        self.shared_sites = {site for site, pubs in hosts_of.items() if len(pubs) >= 2}
        # How much of a source is on its own site (issue 0064): an aggregator's most common site
        # is only where it links most (Hacker News: 8% github.com on the server's data).
        self._site_share = {
            source_id: sum(n for host, n in pairs if site_of(host) == self.site[source_id]) / sum(n for _, n in pairs)
            for source_id, pairs in hosts.items() if sum(n for _, n in pairs)
        }

    def own_site(self, source_id: str) -> str:
        return self.site.get(source_id) or self.handle_site.get(source_id) or ""

    def publication(self, source_id: str) -> str:
        """The host a source publishes at (issue 0069), as own_site finds its site: a website's voice.
        Its site (own_site) still says where it is, for Discover's places and a site's sections."""
        return self.host.get(source_id) or self.handle_host.get(source_id) or ""

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

    def platform_accounts(self) -> Dict[str, str]:
        """Each source that follows an account on a platform (Discover's), and that account."""
        return {source_id: a for source_id, a in self.account.items()
                if a and site_of(a.split("/", 1)[0]) in DISCOVER_PLATFORMS}

    def voice_name(self, voice: str, source_id: str) -> str:
        """A voice as you know it: u/<author> on Reddit, else its source's name."""
        return "u/" + voice.split(":", 1)[1] if voice.startswith("reddit:") else self.name.get(source_id, "")

    def of_kind(self, *kinds: str) -> List[str]:
        return [source_id for source_id, kind in self.kind.items() if kind in kinds]

    def html_sources(self) -> List[str]:
        return [source_id for source_id, kind in self.kind.items() if kind in PLATFORM_KINDS]


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
    def missing_links(cur: Cursor) -> bool:
        """Whether a post's links still wait to be read (fill_missing_links), locked rows too."""
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE links_scanned_at IS NULL)")
        return cur.fetchone()[0]

    @staticmethod
    def mark_boilerplate(cur: Cursor, sources: SourceFacts, source_ids: Optional[Sequence[str]] = None) -> List[str]:
        """Mark every link that is its source's signature (in SIGNATURE_SHARE of its posts and
        SIGNATURE_MIN_POSTS at least) or points at its source's own site. Returns rows changed. On a
        site of publications (SourceFacts.shared_sites, issue 0070) its own is its publication: a
        Substack writer linking another cites them. Returns the posts whose links changed. A platform is no source's own site: what is kept
        of its links there (another tweet, issue 0066) is told by `extract_links`. With `source_ids`, only
        those sources' links (a source's signature counts its own posts only)."""
        own = [(source_id, *((sources.host[source_id], True) if site in sources.shared_sites else (site, False)))
               for source_id, site in sources.site.items()
               if site not in PLATFORM_SITES.get(sources.kind.get(source_id, ""), ())]
        cur.execute(
            """
            WITH n AS (SELECT source_id, count(*) AS posts FROM posts
                       WHERE %(only)s::uuid[] IS NULL OR source_id = ANY(%(only)s::uuid[]) GROUP BY source_id),
            c AS (SELECT p.source_id, pl.target_url, count(*) AS posts
                  FROM post_links pl JOIN posts p ON p.id = pl.post_id
                  WHERE %(only)s::uuid[] IS NULL OR p.source_id = ANY(%(only)s::uuid[]) GROUP BY 1, 2),
            own AS (SELECT * FROM unnest(%(ids)s::uuid[], %(own)s::text[], %(by_host)s::bool[]) AS o(source_id, own, by_host)),
            want AS (
                SELECT pl.post_id, pl.target_url,
                       (c.posts >= %(min_posts)s AND c.posts >= %(share)s * n.posts)
                       OR CASE WHEN own.by_host THEN substring(pl.target_url FROM '^[a-z]+://([^/?#:]+)') = own.own
                               ELSE pl.target_site = own.own END AS boilerplate
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
            RETURNING pl.post_id
            """,
            {"ids": [o[0] for o in own], "own": [o[1] for o in own], "by_host": [o[2] for o in own],
             "min_posts": SIGNATURE_MIN_POSTS, "share": SIGNATURE_SHARE, "only": None if source_ids is None else list(source_ids)},
        )
        return sorted({str(r[0]) for r in cur.fetchall()})

    # ---- the story job ----------------------------------------------------------------

    @staticmethod
    def load_posts(cur: Cursor, sources: SourceFacts, ids: Optional[Iterable[str]] = None, *,
                   linking: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
        """The posts the job groups: every post, or those of `ids`; with `linking`, only those with a
        kept link to one of these addresses (Discover's articles, issue 0070). Each with its kept links,
        in order, and the stored post each link is, if any."""
        cur.execute(
            """
            SELECT p.id, p.source_id, COALESCE(p.published_at, p.fetched_at), p.title, p.content_hash,
                   length(p.content), p.normalized_url,
                   CASE WHEN p.source_id = ANY(%(html)s::uuid[]) THEN p.content_html END,
                   COALESCE(p.metadata ? 'page_update', false), p.author, p.reposted_by, p.created_at
            FROM posts p
            WHERE COALESCE(p.published_at, p.fetched_at) IS NOT NULL
              AND (%(ids)s::uuid[] IS NULL OR p.id = ANY(%(ids)s::uuid[]))
              AND (%(linking)s::text[] IS NULL OR p.id IN (SELECT post_id FROM post_links
                                                         WHERE NOT boilerplate AND target_url = ANY(%(linking)s)))
            """,
            {"html": sources.html_sources(), "ids": None if ids is None else list(ids),
             "linking": None if linking is None else list(linking)},
        )
        posts = [
            {"id": str(r[0]), "source_id": str(r[1]), "t": r[2], "title": r[3], "content_hash": r[4],
             "text_chars": r[5] or 0, "url": r[6], "html": r[7], "updated": r[8], "author": r[9],
             "reposted_by": r[10] or [], "stored_at": r[11], "links": [], "link_texts": {}}
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
    def write_stories(cur: Cursor, stories: Sequence[Story], *, post_ids: Optional[Sequence[str]] = None,
                      mentions: Iterable[Tuple[str, str]] = ()) -> int:
        """Make the stored stories of `post_ids` (every post when None) match `stories`, theirs: the
        stories holding them before and now, their story rows and the mentions of those stories and by
        those posts (`mentions`: (story, post) of stories not given, by those posts). The caller gives whole
        stories (the incremental job's neighbourhood holds each
        story a post of it was in). Writes only what differs; returns how many rows changed."""
        changed = 0
        want_posts: Dict[str, Tuple[Any, ...]] = {}
        want_mentions: Set[Tuple[str, str]] = set()
        for story in stories:
            for position, post in enumerate(story.posts):
                # Its tree (issue 0064): the parent post, else the outside page origin, and why.
                parent_id, parent_url, reason = story.parents.get(post.id, (None, None, None))
                want_posts[post.id] = (story.id, story.roles[post.id], story.reasons[post.id], post.voice,
                                       parent_id, reason, parent_url, position)
            want_mentions |= {(story.id, pid) for pid in story.mentions}
        want_mentions |= set(mentions)
        want = {story.id: (story.first_at, story.voices, story.origin_url, story.origin_title,
                           story.origin_linked_by if story.origin_url else None) for story in stories}
        scope = None if post_ids is None else list(post_ids)

        cur.execute(
            """
            SELECT id, first_at, voices, origin_url, origin_title, origin_linked_by FROM stories
            WHERE %(ids)s::uuid[] IS NULL OR id = ANY(%(want)s::uuid[])
               OR id IN (SELECT story_id FROM story_posts WHERE post_id = ANY(%(ids)s::uuid[]))
            """,
            {"ids": scope, "want": list(want)},
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
            SELECT post_id, story_id, role, reasons, voice, parent_id, parent_reason, parent_url, position
            FROM story_posts WHERE %(ids)s::uuid[] IS NULL OR post_id = ANY(%(ids)s::uuid[])
            """,
            {"ids": scope},
        )
        have_posts = {str(r[0]): (str(r[1]), r[2], list(r[3]), r[4], str(r[5]) if r[5] else None, r[6], r[7], r[8])
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
                INSERT INTO story_posts (post_id, story_id, role, reasons, voice, parent_id, parent_reason, parent_url, position)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (post_id) DO UPDATE
                    SET story_id = EXCLUDED.story_id, role = EXCLUDED.role, reasons = EXCLUDED.reasons, voice = EXCLUDED.voice,
                        parent_id = EXCLUDED.parent_id, parent_reason = EXCLUDED.parent_reason, parent_url = EXCLUDED.parent_url,
                        position = EXCLUDED.position
                """,
                rows,
            )
            changed += len(rows)

        cur.execute(
            """
            SELECT story_id, post_id FROM story_mentions
            WHERE %(ids)s::uuid[] IS NULL OR post_id = ANY(%(ids)s::uuid[]) OR story_id = ANY(%(stories)s::uuid[])
            """,
            {"ids": scope, "stories": sorted(set(have) | set(want))},
        )
        have_mentions = {(str(r[0]), str(r[1])) for r in cur.fetchall()}
        for story_id, post_id in have_mentions - want_mentions:
            cur.execute("DELETE FROM story_mentions WHERE story_id = %s AND post_id = %s", (story_id, post_id))
            changed += cur.rowcount
        new = sorted(want_mentions - have_mentions)
        if new:
            cur.executemany("INSERT INTO story_mentions (story_id, post_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", new)
            changed += len(new)
        return changed

    # ---- stored connections (issue 0072 A) -----------------------------------------------

    @staticmethod
    def write_edges(cur: Cursor, edges: Iterable[Edge], *, made_by: str, post_ids: Optional[Sequence[str]] = None,
                    threads: bool = False, mentioned: Sequence[str] = ()) -> int:
        """Make the stored edges from `post_ids` (every post when None) exactly `edges`: the thread
        edges with `threads`, every other kind without (a thread's are kept by its timeline,
        StoriesService), and the mentions of the nodes `mentioned` (posts, and _PAGE + an address:
        a roundup mentions a story it is not in). Returns how many rows changed."""
        want: Dict[Tuple[str, str, str], Tuple[Any, ...]] = {}
        for e in edges:
            if (e.kind == "thread") == threads:
                want[(e.src, e.kind, e.dst)] = (json.dumps({"key": e.via}) if e.via else None, made_by)
        cur.execute(
            """
            SELECT src_post, kind, COALESCE(dst_post::text, %(page)s || dst_url), evidence::text, made_by FROM post_edges
            WHERE (kind = 'thread') = %(threads)s AND dst_story IS NULL
              AND (%(ids)s::uuid[] IS NULL OR src_post IN (SELECT unnest(%(ids)s::uuid[]))
                   OR kind = 'mention' AND (dst_post IN (SELECT unnest(%(posts)s::uuid[])) OR dst_url = ANY(%(pages)s)))
            """,
            {"page": _PAGE, "threads": threads, "ids": None if post_ids is None else list(post_ids),
             "posts": [n for n in mentioned if not n.startswith(_PAGE)],
             "pages": [n[len(_PAGE):] for n in mentioned if n.startswith(_PAGE)]},
        )
        have = {(str(r[0]), r[1], r[2]): (json.dumps(json.loads(r[3])) if r[3] else None, r[4]) for r in cur.fetchall()}
        gone = [key for key in have if key not in want]
        changed = 0
        if gone:
            cur.executemany("DELETE FROM post_edges WHERE src_post = %s AND kind = %s AND dst_story IS NULL "
                            "AND COALESCE(dst_post::text, %s || dst_url) = %s",
                            [(src, kind, _PAGE, dst) for src, kind, dst in gone])
            changed += len(gone)
        rows = [(src, None if dst.startswith(_PAGE) else dst, dst[len(_PAGE):] if dst.startswith(_PAGE) else None,
                 kind, evidence, made_by)
                for (src, kind, dst), (evidence, made_by) in want.items() if have.get((src, kind, dst)) != (evidence, made_by)]
        if rows:
            cur.executemany(
                """
                INSERT INTO post_edges (src_post, dst_post, dst_url, kind, evidence, made_by) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (src_post, kind, COALESCE(dst_post::text, dst_story::text, dst_url))
                DO UPDATE SET evidence = EXCLUDED.evidence, made_by = EXCLUDED.made_by
                """,
                rows,
            )
            changed += len(rows)
        return changed

    @staticmethod
    def replies(cur: Cursor, post_ids: Sequence[str]) -> Dict[str, str]:
        """The stored thread edges of these posts: each reply -> the post it continues."""
        cur.execute("SELECT src_post, dst_post FROM post_edges WHERE kind = 'thread' "
                    "AND src_post IN (SELECT unnest(%s::uuid[]))", (list(post_ids),))
        return {str(src): str(dst) for src, dst in cur.fetchall()}

    @staticmethod
    def edges_of(cur: Cursor, post_ids: Sequence[str], kinds: Sequence[str]) -> List[Edge]:
        """The stored edges of these kinds from or to these posts."""
        cur.execute(
            f"""
            SELECT src_post::text, COALESCE(dst_post::text, %(page)s || dst_url), kind, evidence->>'key' FROM post_edges
            WHERE kind = ANY(%(kinds)s) AND dst_story IS NULL
              AND (src_post IN (SELECT unnest(%(ids)s::uuid[])) OR dst_post IN (SELECT unnest(%(ids)s::uuid[])))
            """,
            {"page": _PAGE, "kinds": list(kinds), "ids": list(post_ids)},
        )
        return [Edge(*row) for row in cur.fetchall()]

    @staticmethod
    def mentioned_by(cur: Cursor, post_ids: Sequence[str]) -> Set[str]:
        """The posts of the stories these posts mention (story_mentions)."""
        cur.execute("SELECT sp.post_id::text FROM story_mentions m JOIN story_posts sp ON sp.story_id = m.story_id "
                    "WHERE m.post_id IN (SELECT unnest(%s::uuid[]))", (list(post_ids),))
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def stories_holding(cur: Cursor, nodes: Sequence[str]) -> Dict[str, str]:
        """The stored story each node is in: a post's, and a page's (the story its link edges join)."""
        posts = [n for n in nodes if not n.startswith(_PAGE)]
        pages = [n[len(_PAGE):] for n in nodes if n.startswith(_PAGE)]
        cur.execute(
            """
            SELECT post_id::text, story_id::text FROM story_posts WHERE post_id IN (SELECT unnest(%(posts)s::uuid[]))
            UNION
            SELECT DISTINCT %(page)s || e.dst_url, sp.story_id::text FROM post_edges e JOIN story_posts sp ON sp.post_id = e.src_post
            WHERE e.kind = 'link' AND e.dst_url = ANY(%(pages)s)
            """,
            {"posts": posts, "pages": pages, "page": _PAGE},
        )
        return dict(cur.fetchall())

    @staticmethod
    def pages_linked(cur: Cursor, post_ids: Sequence[str]) -> Set[str]:
        """The outside pages these posts are joined through (their stored link edges)."""
        cur.execute("SELECT DISTINCT dst_url FROM post_edges WHERE kind = 'link' AND src_post IN (SELECT unnest(%s::uuid[]))",
                    (list(post_ids),))
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def linking(cur: Cursor, urls: Sequence[str]) -> Set[str]:
        """The posts with a stored link edge to these outside pages (a story joined through them)."""
        cur.execute("SELECT DISTINCT src_post::text FROM post_edges WHERE kind = 'link' AND dst_url = ANY(%s)", (list(urls),))
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def write_keys(cur: Cursor, keys: Dict[str, Set[str]]) -> int:
        """These posts' keys become exactly `keys` (story_rules.keys, and News' names). Returns rows changed."""
        cur.execute("SELECT post_id::text, key FROM story_keys WHERE post_id = ANY(%s::uuid[])", (list(keys),))
        have = {(pid, key) for pid, key in cur.fetchall()}
        want = {(pid, key[:KEY_CHARS]) for pid, ks in keys.items() for key in ks}
        gone, new = sorted(have - want), sorted(want - have)
        if gone:
            cur.executemany("DELETE FROM story_keys WHERE post_id = %s AND key = %s", gone)
        if new:
            with cur.copy("COPY story_keys (post_id, key) FROM STDIN") as copy:
                for row in new:
                    copy.write_row(row)
        return len(gone) + len(new)

    @staticmethod
    def stored_keys(cur: Cursor, post_ids: Sequence[str]) -> Dict[str, Set[str]]:
        cur.execute("SELECT post_id::text, key FROM story_keys WHERE post_id = ANY(%s::uuid[])", (list(post_ids),))
        out: Dict[str, Set[str]] = defaultdict(set)
        for pid, key in cur.fetchall():
            out[pid].add(key)
        return out

    @staticmethod
    def holders(cur: Cursor, keys: Iterable[str]) -> Set[str]:
        """The posts holding any of these keys: by story_keys, and for an address ("u:") every post
        linking it too (a link to a home page is a key only once a post is stored there)."""
        keys = sorted({key[:KEY_CHARS] for key in keys})
        cur.execute(
            """
            SELECT post_id::text FROM story_keys WHERE key = ANY(%(keys)s)
            UNION SELECT post_id::text FROM post_links WHERE NOT boilerplate AND target_url = ANY(%(urls)s)
            """,
            {"keys": keys, "urls": [key[2:] for key in keys if key.startswith("u:")]},
        )
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def at_addresses(cur: Cursor, urls: Sequence[str]) -> Set[str]:
        """The posts stored at these addresses."""
        cur.execute("SELECT id::text FROM posts WHERE normalized_url = ANY(%s)", (list(urls),))
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def count_posts(cur: Cursor) -> int:
        cur.execute("SELECT count(*) FROM posts")
        return int(cur.fetchone()[0])

    @staticmethod
    def counts(cur: Cursor) -> Dict[str, int]:
        """How many stories, News stories and classics are stored (a run's summary)."""
        cur.execute("SELECT (SELECT count(*) FROM stories), (SELECT count(*) FROM news_stories), (SELECT count(*) FROM classics)")
        stories, news, classics = cur.fetchone()
        return {"stories": int(stories), "news": int(news), "classics": int(classics)}

    @staticmethod
    def story_mates(cur: Cursor, post_ids: Iterable[str]) -> Set[str]:
        """These posts and every post of the stories they are in."""
        ids = sorted(set(post_ids))
        cur.execute("SELECT o.post_id::text FROM story_posts sp JOIN story_posts o ON o.story_id = sp.story_id "
                    "WHERE sp.post_id = ANY(%s::uuid[])", (ids,))
        return set(ids) | {r[0] for r in cur.fetchall()}

    # ---- the queue (issue 0072 A: migration 0059's triggers write it) ---------------------

    @staticmethod
    def take_queue(cur: Cursor, limit: int, *, redo: bool = False) -> List[Tuple[str, Any]]:
        """Up to `limit` queued changes, removed from the queue: (key, what it was). With `redo`, a
        rule change's posts (redo:<id>) once no saved or changed post is waiting."""
        cur.execute(
            """
            DELETE FROM story_queue WHERE key IN (
                SELECT key FROM story_queue WHERE (key LIKE 'redo:%%') = %s ORDER BY queued_at, key LIMIT %s
                FOR UPDATE SKIP LOCKED)
            RETURNING key, was
            """,
            (redo, limit),
        )
        return cur.fetchall()

    @staticmethod
    def queued(cur: Cursor) -> Dict[str, int]:
        cur.execute("SELECT count(*) FILTER (WHERE key LIKE 'redo:%%'), count(*) FILTER (WHERE key NOT LIKE 'redo:%%') "
                    "FROM story_queue")
        redo, changed = cur.fetchone()
        return {"redo": int(redo), "changed": int(changed)}

    @staticmethod
    def take_keys(cur: Cursor, keys: Sequence[str]) -> None:
        """These queued changes are being regrouped: off the queue."""
        cur.execute("DELETE FROM story_queue WHERE key = ANY(%s)", (list(keys),))

    @staticmethod
    def queue_posts(cur: Cursor, source_ids: Sequence[str], accounts: Sequence[str]) -> None:
        """Queue the posts of these sources, and the X posts by or reposted by these accounts
        (addresses.x_account: x.com/<name>)."""
        names = [a.split("/", 1)[1] for a in accounts if a.startswith("x.com/")]
        cur.execute(
            """
            INSERT INTO story_queue (key)
            SELECT 'post:' || id FROM posts
            WHERE source_id = ANY(%(sources)s::uuid[])
               OR lower(author) = ANY(%(names)s)
               OR EXISTS (SELECT 1 FROM unnest(reposted_by) r WHERE lower(r) = ANY(%(names)s))
            ON CONFLICT DO NOTHING
            """,
            {"sources": list(source_ids), "names": names},
        )

    @staticmethod
    def done(cur: Cursor, post_ids: Iterable[str]) -> None:
        """A rule change's posts regrouped: off the queue."""
        cur.execute("DELETE FROM story_queue WHERE key = ANY(%s)", (["redo:" + pid for pid in post_ids],))

    @staticmethod
    def redo_every_post(cur: Cursor) -> int:
        """Queue every post for a rule change (redo:<id>), the changes already queued staying."""
        cur.execute("DELETE FROM story_queue WHERE key LIKE 'redo:%%'")
        cur.execute("INSERT INTO story_queue (key) SELECT 'redo:' || id FROM posts ON CONFLICT DO NOTHING")
        return cur.rowcount

    @staticmethod
    def clear_queue(cur: Cursor) -> None:
        cur.execute("DELETE FROM story_queue")

    @staticmethod
    def timeline(cur: Cursor, source_id: str, start: datetime, end: datetime) -> List[str]:
        """The posts of a source posted between `start` and `end`."""
        cur.execute("SELECT id::text FROM posts WHERE source_id = %s "
                    "AND COALESCE(published_at, fetched_at) BETWEEN %s AND %s", (source_id, start, end))
        return [r[0] for r in cur.fetchall()]

    @staticmethod
    def post_ids(cur: Cursor, after: Optional[str], limit: int) -> List[str]:
        """Every post's id in order, `limit` at a time after `after`."""
        cur.execute("SELECT id::text FROM posts WHERE %s::uuid IS NULL OR id > %s::uuid ORDER BY id LIMIT %s",
                    (after, after, limit))
        return [r[0] for r in cur.fetchall()]

    # ---- Discover (its counts: repo_discover.py) -----------------------------------------

    @staticmethod
    def linked_articles(cur: Cursor, host: str) -> List[str]:
        """The article-like addresses on a host (www. aside) your sources' kept links point to,
        once each, in address order: what a site's findings are ranked by (issue 0060)."""
        host = publication_of(host)
        if not host:
            return []
        cur.execute("SELECT DISTINCT target_url FROM post_links WHERE target_site = %s AND NOT boilerplate",
                    (site_of(host),))
        return sorted(url for (url,) in cur.fetchall() if publication_of(host_of(url)) == host and is_article(url))

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
