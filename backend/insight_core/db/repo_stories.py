"""Stories storage: post links, stories, their posts and mentions, edges, the story queue, Discover's hidden
suggestions. Every method takes the caller's cursor and never commits. The rules live in utils/post_links.py,
story_rules.py, tree_rules.py and discover_rules.py; this file reads what they need and writes what they
return, touching only the rows that differ.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.parse import parse_qs, urlparse

from psycopg import Cursor

from insight_core.utils.addresses import PLATFORM_SITES, account_key, host_of, publication_of, site_of, x_account
from insight_core.db.repo_post_parts import PostPartsRepository
from insight_core.db.repo_post_refs import PostRefsRepository
from insight_core.utils.post_fields import MOVED_KEY
from insight_core.utils.post_links import PLATFORM_KINDS, PostLink, extract_links, is_article, source_kind
from insight_core.utils.post_refs import refs_of
from insight_core.utils.discover_rules import DISCOVER_PLATFORMS, NOT_SELF, SELF_MIN, channel_owners, owner_pairs
from insight_core.utils.story_rules import (HOME_SITE_SHARE, NOT_PUBLISHERS, SIGNATURE_MIN_POSTS, SIGNATURE_SHARE,
                                            Edge, Story, source_site, text_chars_sql)
from insight_core.markx.pairing import ix_date
from insight_core.markx.units import roundup_sql   # the round-up tag: units owns it
from insight_core.utils import voice as voice_keys
from insight_core.utils.tree_rules import _PAGE
from insight_core.utils.url_normalization import normalize_url

LINKS_BATCH = 500
KEY_CHARS = 500   # keys are cut to an index row's limit: two longer ones may share a row, never miss one


def source_account(platform: Optional[str], handle: Optional[str]) -> Optional[str]:
    """The platform account a source follows, as Discover keys it (addresses.account_key): t.me/<channel>,
    x.com/<user>, reddit.com/r/<sub>, youtube.com/channel/<id>, else the account its path is under."""
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


# Switched off (0200): a source the owner switched off (sources.enabled false) never feeds a suggestion (any
# list proposing something to follow, read or join), and its address is never proposed. Its stored posts keep
# their places and voices in News, stories and Classics: membership is not a suggestion. The one rule, in SQL
# (`suggestable_sql`) and Python (`switched_off`, SourceFacts.suggestable); every list asks it.
_SUGGESTABLE = "enabled"   # of a sources row: the owner has not switched it off


def suggestable_sql(source_id: str) -> str:
    """The rule as a SQL condition on a source id column (`p.source_id`): true when its posts may feed a suggestion."""
    return f"({source_id} IN (SELECT id FROM sources WHERE {_SUGGESTABLE}))"


def switched_off(cur: Cursor) -> Set[str]:
    """The ids of the sources whose posts feed no suggestion (suggestable_sql's complement)."""
    cur.execute(f"SELECT id::text FROM sources WHERE NOT ({_SUGGESTABLE})")
    return {r[0] for r in cur.fetchall()}


class SourceFacts:
    """What the rules need of every source: its kind, its own site, its publication and its name."""

    def __init__(self, cur: Cursor) -> None:
        cur.execute("SELECT id, platform, handle_or_url, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url) FROM sources")
        rows = cur.fetchall()
        self.off: Set[str] = switched_off(cur)
        cur.execute("SELECT source_id, url_host, count(*) FROM posts WHERE url_host IS NOT NULL GROUP BY 1, 2")
        self._read(rows, cur.fetchall())
        from insight_core.db.repo_voices import counted
        self.voice_of: Dict[str, str] = counted(cur)   # the owner's confirmed voices
        self._own(self._linked(cur))

    @classmethod
    def of(cls, rows: Iterable[Tuple[Any, ...]], hosts: Iterable[Tuple[Any, str, int]],
           links: Iterable[Tuple[str, str]] = (), voices: Optional[Dict[str, str]] = None,
           off: Iterable[str] = ()) -> "SourceFacts":
        """The facts of these sources ((id, platform, handle, name)), their posts' hosts ((source, host, posts))
        and `links` ((linking, linked), as _linked reads them): the rules' stamp builds its sample so
        (utils/stamps.py). `voices`: source -> confirmed voice. `off`: the sources switched off."""
        facts = cls.__new__(cls)
        facts.off = {str(i) for i in off}
        facts._read(list(rows), list(hosts))
        facts.voice_of = dict(voices or {})
        facts._own(links)
        return facts

    def _channels(self) -> List[Tuple[str, str, str, Optional[str], str]]:
        """The followed sources that are someone's channel: not an aggregator, Saved or a subreddit."""
        return [(i, kind, self.name.get(i, ""), self.account.get(i), self.publication(i))
                for i, kind in sorted(self.kind.items()) if kind not in (*NOT_PUBLISHERS, "reddit")]

    def _linked(self, cur: Cursor) -> List[Tuple[str, str]]:
        """(a, b): of the pairs that may be one owner (owner_pairs), a's posts link b's posts or b's own place (its
        address, any case, or a page under it), decided in SQL over those pairs (0283: not every link in Python)."""
        self._pairs = owner_pairs(self._channels(), shared_sites=self.shared_sites)
        asks = [(a, b) for (x, y), why in self._pairs.items() if why == "name" for a, b in ((x, y), (y, x))]
        if not asks:
            return []
        places = {i: "https://" + (self.publication(i) if kind == "site" else (self.account.get(i) or "")).lower()
                  for i, kind, *_ in self._channels()}
        found = self._linking(cur, asks, places)
        return [(a, b) for a, b in asks if (a, b) in found]

    @staticmethod
    def _linking(cur: Cursor, asks: Sequence[Tuple[str, str]], places: Dict[str, str]) -> Set[Tuple[str, str]]:
        """The asked (a, b) where one of a's links (not boilerplate) is a page of b's posts, or is b's place or under
        it in Python's lower(). An ASCII link is lowered once in SQL, under the C collation (A-Z only, as Python's
        lower() does to ASCII, in any database locale); the few links with other characters come back and are
        lowered here (Postgres' lower() would make a dotted capital I an "i", Python's an "i" and a dot)."""
        cur.execute("""
            WITH q AS (SELECT * FROM unnest(%s::uuid[], %s::uuid[], %s::text[]) AS q(a, b, place)),
                 la AS MATERIALIZED (
                     SELECT p.source_id AS a, pl.target_url AS t,
                            CASE WHEN octet_length(pl.target_url) = char_length(pl.target_url)
                                 THEN lower(pl.target_url COLLATE "C") END AS low
                       FROM posts p JOIN post_links pl ON pl.post_id = p.id AND NOT pl.boilerplate
                      WHERE p.source_id IN (SELECT a FROM q))
            (SELECT q.a::text, q.b::text, NULL::text FROM q JOIN la ON la.a = q.a
              WHERE la.low = q.place OR starts_with(la.low, q.place || '/')
             UNION
             SELECT q.a::text, q.b::text, NULL FROM q JOIN la ON la.a = q.a
               JOIN posts o ON o.source_id = q.b AND o.normalized_url = la.t)
            UNION ALL
            SELECT la.a::text, NULL, la.t FROM la WHERE la.low IS NULL""",
                    ([a for a, _ in asks], [b for _, b in asks], [places[b] for _, b in asks]))
        found: Set[Tuple[str, str]] = set()
        wide: Dict[str, List[str]] = defaultdict(list)   # linking source -> its links with other characters, lowered
        for a, b, t in cur.fetchall():
            if t is None:
                found.add((a, b))
            else:
                wide[a].append(t.lower())
        for a, b in asks:
            place = places[b]
            if (a, b) not in found and any(low == place or low.startswith(place + "/") for low in wide.get(a, ())):
                found.add((a, b))
        return found

    def _own(self, linked: Iterable[Tuple[str, str]]) -> None:
        """Who owns each channel (News counts a voice by owner): `owner` (source -> its owner's first source, for
        an owner of 2+ channels) and `owners` (voice -> its owner's voice, when another); a Reddit poster named
        as a followed account's handle is that account's owner too."""
        if not hasattr(self, "_pairs"):
            self._pairs = owner_pairs(self._channels(), shared_sites=self.shared_sites)
        self.owner = channel_owners(self._channels(), self._pairs, linked)

        def voice(i: str) -> str:
            return voice_keys.source_key(i, self.kind.get(i), self.publication(i))
        self.owners: Dict[str, str] = {voice(i): voice(o) for i, o in self.owner.items() if voice(i) != voice(o)}
        # a confirmed voice of 2+ channels is one voice everywhere: stories and News count it once
        voice_of = getattr(self, "voice_of", {})
        for i, v in sorted(voice_of.items()):
            if self.kind.get(i) not in (*NOT_PUBLISHERS, "reddit"):
                self.owners[voice(i)] = voice_keys.confirmed_key(v)
        for i, kind in sorted(self.kind.items()):
            account = self.account.get(i) or ""
            if kind in ("x", "telegram", "youtube") and "/" in account:
                self.owners.setdefault(voice_keys.poster_key(account.rsplit("/", 1)[1].lstrip("@").lower()),
                                       voice_keys.confirmed_key(voice_of[i]) if i in voice_of else voice(self.owner.get(i, i)))

    def owner_voice(self, voice: str) -> Optional[str]:
        """A voice's owner's voice, when another (a Reddit poster by its name in any case)."""
        return voice_keys.owner_of(self.owners, voice)

    def _read(self, rows: List[Tuple[Any, ...]], host_rows: List[Tuple[Any, str, int]]) -> None:
        self.kind = {str(r[0]): source_kind(r[1], r[2]) for r in rows}
        self.name = {str(r[0]): r[3] for r in rows}
        self.account = {str(r[0]): source_account(r[1], r[2]) for r in rows}
        # the source following each account (who reposted a tweet), the first by id
        self.of_account = {a: i for i, a in sorted(self.account.items(), reverse=True) if a}
        # the Saved source's pages come from any site: it has no site of its own
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
        # A site of publications: one your website sources publish on at 2+ hosts (Substack, github.io).
        # Elsewhere a site's other hosts are its publisher's own.
        hosts_of: Dict[str, Set[str]] = defaultdict(set)
        for source_id, site in self.site.items():
            if self.kind.get(source_id) == "site":
                hosts_of[site].add(self.host[source_id])
        self.shared_sites = {site for site, pubs in hosts_of.items() if len(pubs) >= 2}
        # how much of a source is on its own site: an aggregator's most common site is only where it links most
        self._site_share = {
            source_id: sum(n for host, n in pairs if site_of(host) == self.site[source_id]) / sum(n for _, n in pairs)
            for source_id, pairs in hosts.items() if sum(n for _, n in pairs)
        }

    def suggestable(self, source_id: Optional[str]) -> bool:
        """Whether a source's posts may feed a suggestion (not switched off). A post of no source is judged by the
        source that carried it, so None is suggestable."""
        return source_id is None or str(source_id) not in self.off

    def own_site(self, source_id: str) -> str:
        return self.site.get(source_id) or self.handle_site.get(source_id) or ""

    def publication(self, source_id: str) -> str:
        """The host a source publishes at: a website's voice. Its site (own_site) still says where it is."""
        return self.host.get(source_id) or self.handle_host.get(source_id) or ""

    def home_site(self, source_id: str) -> str:
        """The site a source publishes on, "" when none can be told: its own site, if its address is on it or half
        its posts are; never Hacker News' or Saved's."""
        site = self.own_site(source_id)
        if not site or self.kind.get(source_id) in NOT_PUBLISHERS:
            return ""
        if site == self.handle_site.get(source_id) or self._site_share.get(source_id, 0) >= HOME_SITE_SHARE:
            return site
        return ""

    def followed(self, publications_on: Iterable[str] = ()) -> Set[str]:
        """The sites you follow: each source's own site and its address's. A source that isn't its posts' publisher
        (NOT_PUBLISHERS) follows no site by them. On a site of publications (`publications_on`) a source follows
        its publication, not the platform."""
        on = set(publications_on)

        def unit(site: str, host: str) -> str:
            return host if site in on and host else site
        own = (unit(s, self.host.get(i, "")) for i, s in self.site.items() if self.kind.get(i) not in NOT_PUBLISHERS)
        handles = (unit(s, self.handle_host.get(i, "")) for i, s in self.handle_site.items())
        return {s for s in (*own, *handles) if s}

    def selves(self, source_id: str) -> Set[str]:
        """A source's own names on a platform: its account's (t.me/<name>, x.com/<name>) and its publication's
        first word (<name>.substack.com). Its links to pages under one are self-links."""
        names = set()
        account = self.account.get(source_id) or ""
        if "/" in account:
            names.add(account.rsplit("/", 1)[1].lstrip("@~"))
        if self.kind.get(source_id) == "site":
            labels = self.publication(source_id).split(".")[:-1]
            names.add(next((label for label in labels if label not in NOT_SELF), ""))
        return {n for n in names if len(n) >= SELF_MIN and n not in NOT_SELF}

    def followed_accounts(self) -> Set[str]:
        """The platform accounts you follow (source_account): on a platform, only these are followed."""
        return {a for a in self.account.values() if a}

    def platform_accounts(self) -> Dict[str, str]:
        """Each source that follows an account on a platform (Discover's), and that account."""
        return {source_id: a for source_id, a in self.account.items()
                if a and site_of(a.split("/", 1)[0]) in DISCOVER_PLATFORMS}

    def voice_name(self, voice: str, source_id: str) -> str:
        """A voice as you know it: u/<author> on Reddit, else its source's name."""
        return "u/" + voice_keys.poster(voice) if voice_keys.is_poster(voice) else self.name.get(source_id, "")

    def of_kind(self, *kinds: str) -> List[str]:
        return [source_id for source_id, kind in self.kind.items() if kind in kinds]

    def html_sources(self) -> List[str]:
        return [source_id for source_id, kind in self.kind.items() if kind in PLATFORM_KINDS]


class StoriesRepository:
    @staticmethod
    def write_links(cur: Cursor, post_id: str, links: Sequence[PostLink]) -> None:
        """One post's links become exactly `links` (rows that did not change are not written)."""
        cur.execute("DELETE FROM post_links WHERE post_id = %s AND NOT (target_url = ANY(%s))",
                    (post_id, [link.url for link in links]))
        if links:
            cur.executemany(
                """
                INSERT INTO post_links (post_id, target_url, target_site, position, link_text, shared_url, kind, boilerplate)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (post_id, target_url) DO UPDATE
                    SET target_site = EXCLUDED.target_site, position = EXCLUDED.position, link_text = EXCLUDED.link_text,
                        shared_url = EXCLUDED.shared_url, kind = EXCLUDED.kind,
                        -- A reference is boilerplate (issue 0137 B8), so is a mention (0235); a link the signature
                        -- pass marks.
                        boilerplate = CASE WHEN EXCLUDED.kind IN ('reference', 'mention') THEN true
                                           WHEN post_links.kind IN ('reference', 'mention') THEN false
                                           ELSE post_links.boilerplate END
                    WHERE (post_links.target_site, post_links.position, post_links.link_text, post_links.shared_url,
                           post_links.kind)
                          IS DISTINCT FROM (EXCLUDED.target_site, EXCLUDED.position, EXCLUDED.link_text, EXCLUDED.shared_url,
                                            EXCLUDED.kind)
                """,
                [(post_id, link.url, link.site, link.position, link.text, link.shared, link.kind,
                  link.kind in ("reference", "mention"))
                 for link in links],
            )

    def save_post_links(self, cur: Cursor, post_id: str) -> None:
        """Read a stored post's links from its stored HTML (what the saver kept, not the draft)."""
        cur.execute(
            """
            SELECT p.url, p.content_html, s.platform, s.handle_or_url, p.content
            FROM posts p JOIN sources s ON s.id = p.source_id WHERE p.id = %s
            """,
            (post_id,),
        )
        row = cur.fetchone()
        if row is None:
            return
        url, content_html, platform, handle, content = row
        self.write_links(cur, post_id, extract_links(content_html, url, source_kind(platform, handle), content))
        PostRefsRepository.read_post(cur, post_id, url, content_html, content)   # every link, Connected's
        cur.execute("UPDATE posts SET links_scanned_at = now() WHERE id = %s AND links_scanned_at IS NULL", (post_id,))

    def fill_missing_links(self, cur: Cursor, limit: int = LINKS_BATCH) -> int:
        """Read the links of up to `limit` posts never read (or whose text a repair rewrote). Returns how many."""
        cur.execute(
            """
            SELECT p.id, p.url, p.content_html, s.platform, s.handle_or_url, p.content
            FROM posts p JOIN sources s ON s.id = p.source_id
            WHERE p.links_scanned_at IS NULL
            ORDER BY p.id
            LIMIT %s
            FOR UPDATE OF p SKIP LOCKED
            """,
            (limit,),
        )
        rows = cur.fetchall()
        for post_id, url, content_html, platform, handle, content in rows:
            self.write_links(cur, str(post_id), extract_links(content_html, url, source_kind(platform, handle), content))
            PostRefsRepository.write(cur, str(post_id), refs_of(content_html, content, url))
        if rows:
            cur.execute("UPDATE posts SET links_scanned_at = now(), refs_scanned_at = now() WHERE id = ANY(%s::uuid[])",
                        ([r[0] for r in rows],))
        return len(rows)

    MENTIONS_KEY = "mentions_backfill"   # {"after": the last post read, "done"} (system_settings)

    def fill_mentions(self, cur: Cursor, limit: int = LINKS_BATCH) -> int:
        """The mentions backfill, resumable: the next `limit` X and Bluesky posts (by id) whose text holds an @,
        their links read again as extract_links reads them now. Its place is kept in MENTIONS_KEY. Returns how
        many posts were read (0: done)."""
        cur.execute("SELECT value FROM system_settings WHERE key = %s", (self.MENTIONS_KEY,))
        row = cur.fetchone()
        state = row[0] if row and isinstance(row[0], dict) else {}
        if state.get("done"):
            return 0
        cur.execute("SELECT id::text, platform, handle_or_url FROM sources")
        ids = [i for i, platform, handle in cur.fetchall()
               if source_kind(platform, handle) == "x" or (platform or "").lower() == "bluesky"]
        cur.execute(
            """
            SELECT p.id, p.url, p.content_html, s.platform, s.handle_or_url, p.content
            FROM posts p JOIN sources s ON s.id = p.source_id
            WHERE p.source_id = ANY(%s::uuid[]) AND (%s::uuid IS NULL OR p.id > %s::uuid)
              AND strpos(COALESCE(p.content_html, p.content, ''), '@') > 0
            ORDER BY p.id
            LIMIT %s
            """,
            (ids, state.get("after"), state.get("after"), limit),
        )
        rows = cur.fetchall()
        for post_id, url, content_html, platform, handle, content in rows:
            self.write_links(cur, str(post_id), extract_links(content_html, url, source_kind(platform, handle), content))
        done = len(rows) < limit
        cur.execute("""INSERT INTO system_settings (key, value) VALUES (%s, %s::jsonb)
                       ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
                    (self.MENTIONS_KEY, json.dumps({"after": str(rows[-1][0]) if rows else state.get("after"),
                                                    "done": done})))
        return len(rows)

    @staticmethod
    def mentions_left(cur: Cursor) -> bool:
        """Whether the mentions backfill has posts left (fill_mentions)."""
        cur.execute("SELECT value FROM system_settings WHERE key = %s", (StoriesRepository.MENTIONS_KEY,))
        row = cur.fetchone()
        return not (row and isinstance(row[0], dict) and row[0].get("done"))

    @staticmethod
    def missing_links(cur: Cursor) -> bool:
        """Whether a post's links still wait to be read (fill_missing_links), locked rows too."""
        cur.execute("SELECT EXISTS (SELECT 1 FROM posts WHERE links_scanned_at IS NULL)")
        return cur.fetchone()[0]

    @staticmethod
    def mark_boilerplate(cur: Cursor, sources: SourceFacts, source_ids: Optional[Sequence[str]] = None) -> List[str]:
        """Mark every link that is its source's signature (in SIGNATURE_SHARE of its posts, SIGNATURE_MIN_POSTS at
        least) or points at its own site; on a site of publications its own is its publication; a platform is no
        source's own site. With `source_ids`, only those sources'. Their post_refs are marked by the same rule.
        Returns the posts whose links changed."""
        own = [(source_id, *((sources.host[source_id], True) if site in sources.shared_sites else (site, False)))
               for source_id, site in sources.site.items()
               if site not in PLATFORM_SITES.get(sources.kind.get(source_id, ""), ())]
        cur.execute(
            """
            WITH n AS (SELECT source_id, count(*) AS posts FROM posts
                       WHERE %(only)s::uuid[] IS NULL OR source_id = ANY(%(only)s::uuid[]) GROUP BY source_id),
            c AS (SELECT p.source_id, pl.target_url, count(*) AS posts
                  FROM post_links pl JOIN posts p ON p.id = pl.post_id
                  WHERE (%(only)s::uuid[] IS NULL OR p.source_id = ANY(%(only)s::uuid[])) AND pl.kind = 'link' GROUP BY 1, 2),
            own AS (SELECT * FROM unnest(%(ids)s::uuid[], %(own)s::text[], %(by_host)s::bool[]) AS o(source_id, own, by_host)),
            want AS (
                SELECT pl.post_id, pl.target_url,
                       -- A reference is never an ordinary link (issue 0137 B8), nor a mention (0235): always boilerplate.
                       pl.kind IN ('reference', 'mention') OR (c.posts >= %(min_posts)s AND c.posts >= %(share)s * n.posts)
                       OR CASE WHEN own.by_host THEN substring(pl.target_url FROM '^[a-z]+://([^/?#:]+)') = own.own
                               ELSE pl.target_site = own.own END AS boilerplate
                FROM post_links pl
                JOIN posts p ON p.id = pl.post_id
                JOIN n ON n.source_id = p.source_id
                LEFT JOIN c ON c.source_id = p.source_id AND c.target_url = pl.target_url
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
        changed = sorted({str(r[0]) for r in cur.fetchall()})
        # Connected's refs by the same rule; no story reads them, so they are not in `changed`
        PostRefsRepository.mark_boilerplate(cur, source_ids)
        return changed

    @staticmethod
    def load_posts(cur: Cursor, sources: SourceFacts, ids: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
        """The posts the job groups: every post, or `ids`, each with its kept links in order and the stored post each
        link is. Its parts (post_parts; parsed first when missing): title, reply target, quoted tweet, quoted
        pages' words, Reddit poster; HTML-derived ones only on `html_sources`. `roundup`: units.roundup_sql."""
        PostPartsRepository.write_missing(cur, ids)
        cur.execute(
            f"""
            SELECT p.id, p.source_id, {ix_date("p")}, p.title, p.content_hash,
                   {text_chars_sql("p.content")}, p.normalized_url, p.source_id = ANY(%(html)s::uuid[]),
                   COALESCE(p.metadata ? 'page_update', false), p.author, p.reposted_by, p.created_at,
                   pp.title, pp.reply_to, pp.quoted, pp.quoted_words, pp.author, pp.words, pp.opening,
                   CASE WHEN p.published_at IS NULL THEN 'none' ELSE p.published_precision END,
                   p.metadata ->> %(moved)s, {roundup_sql("p.id")}
            FROM posts p LEFT JOIN post_parts pp ON pp.post_id = p.id
            WHERE {ix_date("p")} IS NOT NULL
              AND (%(ids)s::uuid[] IS NULL OR p.id = ANY(%(ids)s::uuid[]))
            """,
            {"html": sources.html_sources(), "ids": None if ids is None else list(ids), "moved": MOVED_KEY},
        )
        posts = [
            {"id": str(r[0]), "source_id": str(r[1]), "t": r[2], "title": r[3], "content_hash": r[4],
             "text_chars": r[5] or 0, "url": r[6], "updated": r[8], "author": r[9],
             "reposted_by": r[10] or [], "stored_at": r[11], "links": [], "link_texts": {},
             "shown_title": r[12], "reply_to": r[13], "quoted": r[14], "quoted_words": (r[15] or {}) if r[7] else {},
             "poster": r[16] if r[7] else None, "words": (r[17] or 0) if r[7] else 0, "opening": r[18],
             "precision": r[19], "moved_to": r[20], "roundup": r[21]}
            for r in cur.fetchall()
        ]
        by_id = {p["id"]: p for p in posts}
        cur.execute("""SELECT post_id, target_url, link_text FROM post_links
                        WHERE NOT boilerplate AND post_id = ANY(%s::uuid[]) ORDER BY post_id, position""", (list(by_id),))
        links = cur.fetchall()
        # the stored post each link is: the first stored at its address, looked up once an address
        cur.execute("""SELECT DISTINCT ON (normalized_url) normalized_url, id FROM posts WHERE normalized_url = ANY(%s)
                        ORDER BY normalized_url, fetched_at, created_at, id""", (sorted({t for _, t, _ in links}),))
        stored_at = {url: str(pid) for url, pid in cur.fetchall()}
        for post_id, target, text in links:
            by_id[str(post_id)]["links"].append((target, stored_at.get(target)))
            if text:
                by_id[str(post_id)]["link_texts"][target] = text
        return posts

    @staticmethod
    def linking_posts(cur: Cursor, urls: Sequence[str]) -> List[str]:
        """The posts with a kept link to one of these addresses, by id (their evidence is read in batches)."""
        cur.execute("SELECT DISTINCT post_id::text FROM post_links WHERE NOT boilerplate AND target_url = ANY(%s) "
                    "ORDER BY 1", (list(urls),))
        return [r[0] for r in cur.fetchall()]

    @staticmethod
    def write_stories(cur: Cursor, stories: Sequence[Story], *, post_ids: Optional[Sequence[str]] = None,
                      mentions: Iterable[Tuple[str, str]] = ()) -> int:
        """Make the stored stories of `post_ids` (every post when None) match `stories`: their story rows and the
        mentions of those stories and by those posts (`mentions`: (story, post) of stories not given). The
        caller gives whole stories. Writes only what differs; returns how many rows changed."""
        changed = 0
        want_posts: Dict[str, Tuple[Any, ...]] = {}
        want_mentions: Set[Tuple[str, str]] = set()
        for story in stories:
            for position, post in enumerate(story.posts):
                # its tree: the parent post, else the outside page origin, and why
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

    @staticmethod
    def write_edges(cur: Cursor, edges: Iterable[Edge], *, made_by: str, post_ids: Optional[Sequence[str]] = None,
                    threads: bool = False, mentioned: Sequence[str] = ()) -> int:
        """Make the stored edges from `post_ids` (every post when None) exactly `edges`: thread edges with `threads`,
        every other kind without, and the mentions of the `mentioned` nodes (posts, and _PAGE + an address).
        Returns how many rows changed."""
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
    def stories_holding(cur: Cursor, nodes: Sequence[str], *, besides: Sequence[str] = ()) -> Dict[str, str]:
        """The stored story each node is in (a post's, a page's through its link edges), read from posts not in
        `besides` (a batch's scope, rewritten now)."""
        posts = [n for n in nodes if not n.startswith(_PAGE)]
        pages = [n[len(_PAGE):] for n in nodes if n.startswith(_PAGE)]
        cur.execute(
            """
            SELECT post_id::text, story_id::text FROM story_posts WHERE post_id IN (SELECT unnest(%(posts)s::uuid[]))
              AND post_id NOT IN (SELECT unnest(%(besides)s::uuid[]))
            UNION
            SELECT DISTINCT %(page)s || e.dst_url, sp.story_id::text FROM post_edges e JOIN story_posts sp ON sp.post_id = e.src_post
            WHERE e.kind = 'link' AND e.dst_url = ANY(%(pages)s) AND e.src_post NOT IN (SELECT unnest(%(besides)s::uuid[]))
            """,
            {"posts": posts, "pages": pages, "page": _PAGE, "besides": list(besides)},
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
    def keys_moved(cur: Cursor, keys: Dict[str, Set[str]]) -> Dict[str, Tuple[Set[str], Set[str]]]:
        """Of these posts, those whose stored keys are not `keys`: {post: (stored, `keys`)}, cut to KEY_CHARS.
        Nothing is written."""
        cur.execute("SELECT post_id::text, key FROM story_keys WHERE post_id = ANY(%s::uuid[])", (list(keys),))
        have: Dict[str, Set[str]] = defaultdict(set)
        for pid, key in cur.fetchall():
            have[pid].add(key)
        want = {pid: {key[:KEY_CHARS] for key in ks} for pid, ks in keys.items()}
        return {pid: (have.get(pid, set()), ks) for pid, ks in want.items() if have.get(pid, set()) != ks}

    @staticmethod
    def relabel_edges(cur: Cursor, made_by: str) -> int:
        """Stamp every connection with the rules `made_by` (the grouping's stamp). Returns rows changed."""
        cur.execute("UPDATE post_edges SET made_by = %s WHERE made_by <> %s", (made_by, made_by))
        return cur.rowcount

    @staticmethod
    def stored_keys(cur: Cursor, post_ids: Sequence[str]) -> Dict[str, Set[str]]:
        cur.execute("SELECT post_id::text, key FROM story_keys WHERE post_id = ANY(%s::uuid[])", (list(post_ids),))
        out: Dict[str, Set[str]] = defaultdict(set)
        for pid, key in cur.fetchall():
            out[pid].add(key)
        return out

    @staticmethod
    def holders(cur: Cursor, keys: Iterable[str]) -> Set[str]:
        """The posts holding any of these keys: by story_keys, and for an address ("u:") every post linking it too
        (a link to a home page is a key only once a post is stored there)."""
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

    @staticmethod
    def take_queue(cur: Cursor, limit: int, *, redo: bool = False) -> List[Tuple[str, Any]]:
        """Up to `limit` queued changes, removed from the queue: (key, what it was), first queued first. With
        `redo`, a rule change's posts (redo:<id>) once nothing else waits, newest first."""
        order = "queued_at DESC, key" if redo else "queued_at, key"
        cur.execute(
            f"""
            DELETE FROM story_queue WHERE key IN (
                SELECT key FROM story_queue WHERE (key LIKE 'redo:%%') = %s ORDER BY {order} LIMIT %s
                FOR UPDATE SKIP LOCKED)
            RETURNING key, was
            """,
            (redo, limit),
        )
        return cur.fetchall()

    @staticmethod
    def regrouped(cur: Cursor) -> Dict[str, int]:
        """A rule change's progress, counted from the rows: every post (`total`) and those with no regroup waiting
        in the queue (`done`)."""
        cur.execute("""SELECT (SELECT count(*) FROM posts),
                              (SELECT count(DISTINCT p.id) FROM story_queue q JOIN posts p ON p.id = substr(q.key, 6)::uuid
                                WHERE q.key LIKE 'redo:%%' OR q.key LIKE 'post:%%')""")
        total, waiting = cur.fetchone()
        return {"done": int(total) - int(waiting), "total": int(total)}

    @staticmethod
    def take_keys(cur: Cursor, keys: Sequence[str]) -> None:
        """These queued changes are being regrouped: off the queue."""
        cur.execute("DELETE FROM story_queue WHERE key = ANY(%s)", (list(keys),))

    @staticmethod
    def queue_posts(cur: Cursor, source_ids: Sequence[str], accounts: Sequence[str]) -> None:
        """Queue the posts of these sources, and the X posts by or reposted by these accounts (x.com/<name>)."""
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
        """Queue every post for a rule change (redo:<id>), each at its date so `take_queue` takes the newest first;
        changes already queued stay."""
        cur.execute("DELETE FROM story_queue WHERE key LIKE 'redo:%%'")
        cur.execute(f"INSERT INTO story_queue (key, queued_at) SELECT 'redo:' || id, {ix_date('posts')} FROM posts "
                    "ON CONFLICT DO NOTHING")
        return cur.rowcount

    @staticmethod
    def newest_first(cur: Cursor) -> int:
        """Requeue the rule change's posts still queued at their dates, so the newest are regrouped first. Returns
        how many."""
        cur.execute(f"UPDATE story_queue q SET queued_at = {ix_date('p')} FROM posts p "
                    "WHERE q.key LIKE 'redo:%%' AND q.key = 'redo:' || p.id")
        return cur.rowcount

    @staticmethod
    def drop_redo(cur: Cursor) -> int:
        """Unqueue a rule change's posts (the rows they hold are already by the rules now). Returns how many."""
        cur.execute("DELETE FROM story_queue WHERE key LIKE 'redo:%%'")
        return cur.rowcount

    @staticmethod
    def queue_regroup(cur: Cursor, post_ids: Sequence[str]) -> None:
        """Queue these posts to regroup as a saved post is (post:<id>)."""
        cur.execute("INSERT INTO story_queue (key) SELECT 'post:' || unnest(%s::uuid[])::text ON CONFLICT DO NOTHING",
                    (list(post_ids),))

    @staticmethod
    def clear_queue(cur: Cursor) -> None:
        cur.execute("DELETE FROM story_queue")

    @staticmethod
    def timeline(cur: Cursor, source_id: str, start: datetime, end: datetime) -> List[str]:
        """The posts of a source posted between `start` and `end`."""
        cur.execute(f"SELECT id::text FROM posts WHERE source_id = %s "
                    f"AND {ix_date('')} BETWEEN %s AND %s", (source_id, start, end))
        return [r[0] for r in cur.fetchall()]

    @staticmethod
    def post_ids(cur: Cursor, after: Optional[str], limit: int) -> List[str]:
        """Every post's id in order, `limit` at a time after `after`."""
        cur.execute("SELECT id::text FROM posts WHERE %s::uuid IS NULL OR id > %s::uuid ORDER BY id LIMIT %s",
                    (after, after, limit))
        return [r[0] for r in cur.fetchall()]

    @staticmethod
    def linked_articles(cur: Cursor, host: str) -> List[str]:
        """The article-like addresses on a host (www. aside) your kept links point to, once each, in address order."""
        host = publication_of(host)
        if not host:
            return []
        cur.execute("SELECT DISTINCT target_url FROM post_links WHERE target_site = %s AND NOT boilerplate",
                    (site_of(host),))
        return sorted(url for (url,) in cur.fetchall() if publication_of(host_of(url)) == host and is_article(url))

    @staticmethod
    def discover_inputs(cur: Cursor) -> str:
        """What Discover is computed from, in one string: the story run's discover_at, the sources by what Discover
        reads of them (never their updated_at, which every fetch moves), the hidden suggestions and what
        Discover read of the web. Same string, same list."""
        cur.execute(
            """
            SELECT concat_ws('|', (SELECT COALESCE(value->>'discover_at', value->>'computed_at') FROM system_settings
                                   WHERE key = 'stories'),
                             (SELECT count(*) || ':' || md5(COALESCE(string_agg(
                                         concat_ws(' ', id::text, platform, handle_or_url,
                                                   NULLIF(btrim(settings->>'display_name'), ''), enabled::text,
                                                   voice_id::text), E'\\n' ORDER BY id), ''))
                              FROM sources),
                             (SELECT count(*) || ':' || COALESCE(max(COALESCE(confirmed_at, created_at))::text, '')
                                     || ':' || count(removed_at) FROM voices),
                             (SELECT count(*) || ':' || COALESCE(max(hidden_at)::text, '') FROM discover_hidden),
                             (SELECT updated_at::text FROM system_settings WHERE key = 'discover_reads'))
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
