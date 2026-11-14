"""Discover's counts in the database (issue 0062): the sites and accounts your sources keep linking,
grouped and counted in one query, so the API never holds the 138k kept links in memory (it did:
2.6-3.3 s and ~800 MB on the server's data).

It is discover_rules.suggestions (the reference, kept as a pure function) in SQL, over every kept link
(`post_links`, not boilerplate):
- an address's key, site and platform (discover_rules.discover_address) and whether it reads like an
  article (post_links.is_article) depend on the address alone: `discover_addresses` keeps them,
  each worked out once in Python (fill_addresses), by the story job after it reads links, or by
  Discover itself for an address it finds missing;
- a key is a candidate with 2+ article-like addresses that are 40%+ of its addresses, unless you
  follow it or hid it (discover_rules.discover_open): this needs the addresses only;
- only the candidates' links are then read for their voices (StoryPost.voice: `site:<publication>`
  for a website, `reddit:<author>` for a Reddit post whose feed names its author, else
  `source:<source id>`), and a candidate with 3+ voices is kept.
The query returns only the kept keys: their counts, voices, top articles with the voices linking
each. Python orders them, names the voices and titles the articles (issue 0070: as a story's
outside origin is titled, tree_rules.origin_title; a stored post by its own title).

Issue 0065: a post on a platform is an article of its account (discover_rules.discover_article: a
tweet in any form, a Telegram post), and a post of a platform account's source at another
account's address (a repost) counts as that source's link to it, so discover_addresses also keeps
the addresses of those sources' posts. Where each story starts (story_origins) and the places
your sources hold (posts_on) are read for StoriesService.discover to rank by.
Addresses and keys compare byte for byte (COLLATE "C"), as Python's strings do; the one thing
lowercased in SQL, a Reddit author, is lowercased by ICU ("und-x-icu", in the postgres image),
which is Python's full case mapping.

Measured on a copy of the lab (41.7k posts, 138.6k kept links, 2026-10-31): the first open after
a story run went from 2.3-2.7 s and a 706 MB jump in the API's memory to 0.42-0.56 s and 9 MB,
with the same list in the same order.

Issue 0067: each voice also says whether it links a key only in roundups (v10.17, 0190: the posts markx/units.py
tags a round-up, the one predicate; 3+ anchors before), which Discover's order weighs half; the other pages
of a host where tweets are found (a mirror, `mirrors`) are no key; and the counts are kept between story runs
(system_settings `discover_counts`): the story job counts them after it fills the addresses, and
an open reads them while their stamp (the rules, the last story run, the sources with posts) holds.
Hidden and followed keys are left out when read, so hiding or following needs no recount.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from psycopg import Cursor

from insight_core.db.repo_operations import SystemSettingsRepository
from insight_core.db.repo_post_parts import shown_title
from insight_core.db.repo_stories import suggestable_sql
from insight_core.markx import pairing, units
from insight_core.utils import voice as voice_keys
from insight_core.utils.addresses import host_of
from insight_core.utils.discover_rules import (ADDRESS_RULES, DISCOVER_ARTICLE_SHARE, DISCOVER_MIN_ARTICLES,
                                               DISCOVER_MIN_VOICES, DISCOVER_PLATFORMS, ORIGIN_MIN_VOICES, OWNER_DEPTH,
                                               Origin, Platforms, address_stamp, discover_address, discover_article,
                                               find_platforms)
from insight_core.utils.url_normalization import TWEET_SHAPE

LOCK_KEY = "insight.discover_addresses"
# An address's path segments, lower case (ICU: Python's case mapping), as discover_rules.path_segments reads them.
_SEGMENTS = ("array_remove(string_to_array(lower(regexp_replace(regexp_replace({url}, '^[a-z]+://[^/]*/?', ''), "
             "'[?#].*$', '') COLLATE \"und-x-icu\"), '/'), '')")
KEPT_KEY = "discover_counts"   # Discover's counts between story runs (system_settings, issue 0067)
LIST_KEY = "discover_list"     # Discover's last list, by what it was made from (system_settings, issue 0080 cold open)
SERVED_KEY = "discover_served"   # the answer Discover's page serves, built in the background (issue 0172 c1)
# When Discover's inputs last changed (issue 0080 speed: StoriesService._settle), else the last story run.
DISCOVER_AT = "COALESCE(value->>'discover_at', value->>'computed_at')"
READS_KEY = "discover_reads"   # the follow tests and page titles Discover read (system_settings, issue 0080)
WORK_MEM = "48MB"

_COUNTS = """
WITH src AS (
    SELECT * FROM unnest(%(ids)s::uuid[], %(kinds)s::text[], %(sites)s::text[], %(accounts)s::text[], %(selves)s::text[])
        AS s(id, kind, own_site, account, selves)
),
reposted AS MATERIALIZED (        -- a post of a platform account at another account's address (a repost):
    SELECT p.id AS post_id, p.url COLLATE "C" AS url, d.key COLLATE "C" AS key, d.article,   -- a link to it (0065)
           d.url IS NULL AS unknown
    FROM (SELECT id, source_id, COALESCE(normalized_url, url) AS url FROM posts) p
    JOIN src s ON s.id = p.source_id AND s.account <> ''
    LEFT JOIN discover_addresses d ON d.url = p.url AND d.rules = %(rules)s
    WHERE (d.url IS NULL OR (d.platform AND d.key <> s.account))
      AND (%(keys)s::text[] IS NULL OR d.key = ANY(%(keys)s))   -- the keys asked (issue 0072: a story run's)
),
kept_url AS MATERIALIZED (        -- each address a kept link points to, and what Discover reads of it
    SELECT u.url, d.key COLLATE "C" AS key, d.site, d.platform, d.article, d.url IS NULL AS unknown
    FROM (SELECT target_url COLLATE "C" AS url FROM post_links WHERE NOT boilerplate AND %(keys)s::text[] IS NULL
          UNION SELECT a.url COLLATE "C" FROM discover_addresses a      -- the keys asked: their linked addresses
                WHERE a.key = ANY(%(keys)s) AND a.rules = %(rules)s
                  AND EXISTS (SELECT 1 FROM post_links pl WHERE pl.target_url = a.url AND NOT pl.boilerplate)
          UNION SELECT url FROM reposted WHERE NOT unknown) u
    LEFT JOIN discover_addresses d ON d.url = u.url AND d.rules = %(rules)s
),
unknown AS (SELECT (SELECT count(*) FROM kept_url WHERE unknown) + (SELECT count(*) FROM reposted WHERE unknown) AS n),
unfollowed AS MATERIALIZED (      -- those with a key, not a tweet mirror's other pages (issue 0067; one you
    SELECT url, key, article FROM kept_url   -- follow or hid is left out when read: discover_open)
    WHERE key IS NOT NULL AND (platform OR NOT key = ANY(%(mirrors)s))
),
candidate AS MATERIALIZED (       -- keys with 2+ article-like addresses, 40%%+ of their addresses
    SELECT key, count(*) FILTER (WHERE article) AS articles, count(*) AS links,
           COALESCE(array_agg(url) FILTER (WHERE url IN (SELECT target_url FROM classics)), '{}') AS classics
    FROM unfollowed GROUP BY key
    HAVING count(*) FILTER (WHERE article) >= %(min_articles)s
       AND count(*) FILTER (WHERE article) >= %(share)s::float8 * count(*)
),
linked AS MATERIALIZED (          -- the kept links to those keys' addresses, but Saved's and a source's
    SELECT u.key, u.url, u.article, pl.post_id, p.source_id,   -- links to its own pages (issue 0080)
           COALESCE(s.kind, 'site') AS kind, COALESCE(s.own_site, '') AS own_site
    FROM unfollowed u JOIN post_links pl ON pl.target_url = u.url AND NOT pl.boilerplate
    JOIN posts p ON p.id = pl.post_id LEFT JOIN src s ON s.id = p.source_id
    WHERE u.key IN (SELECT key FROM candidate) AND s.kind IS DISTINCT FROM 'saved'
      AND """ + suggestable_sql("p.source_id") + """   -- a source switched off links nothing (issue 0200)
      AND NOT (COALESCE(s.selves, '') <> '' AND EXISTS (
          SELECT 1 FROM unnest((""" + _SEGMENTS.format(url="u.url") + """)[1:%(depth)s]) g
          WHERE ltrim(g, '@~') = ANY(string_to_array(s.selves, ' '))))
    UNION ALL                     -- and the reposts of them
    SELECT r.key, r.url, r.article, r.post_id, p.source_id, COALESCE(s.kind, 'site'), COALESCE(s.own_site, '')
    FROM reposted r JOIN posts p ON p.id = r.post_id LEFT JOIN src s ON s.id = p.source_id
    WHERE NOT r.unknown AND r.key IN (SELECT key FROM candidate) AND """ + suggestable_sql("p.source_id") + """
),
roundup AS MATERIALIZED (         -- the linking posts that are round-ups (markx/units.py owns the predicate,
    SELECT DISTINCT l.post_id FROM linked l   -- GLOSSARY "Round-up"; v10.17, 0190: 3+ anchors before)
    WHERE """ + units.roundup_sql("l.post_id") + """
),
author AS MATERIALIZED (          -- a Reddit post's author, as its feed writes it (post_parts, issue 0076)
    SELECT pp.post_id AS id, pp.author FROM post_parts pp
    WHERE pp.post_id IN (SELECT post_id FROM linked WHERE kind = 'reddit') AND pp.author IS NOT NULL
),
link AS MATERIALIZED (            -- with their voices (StoryPost.voice), and whether a roundup linked it
    SELECT l.key, l.url, l.article, l.post_id, l.source_id,
           """ + voice_keys.key_sql("l.kind", "l.own_site", "a.author", "l.source_id") + """ COLLATE "C" AS voice,
           l.post_id IN (SELECT post_id FROM roundup) AS roundup
    FROM linked l LEFT JOIN author a ON a.id = l.post_id
),
heard AS MATERIALIZED (           -- who linked what: each address and voice once
    SELECT DISTINCT key, url, voice, article FROM link
),
counted AS MATERIALIZED (         -- and 3+ voices, with those that link the key only in roundups, and
    SELECT c.key, v.voices, v.roundups, c.articles, c.links, c.classics, ks.sources   -- the sources linking it
    FROM candidate c
    JOIN (SELECT key, array_agg(voice) AS voices, COALESCE(array_agg(voice) FILTER (WHERE only_roundups), '{}') AS roundups
          FROM (SELECT key, voice, bool_and(roundup) AS only_roundups FROM link GROUP BY key, voice) kv
          GROUP BY key HAVING count(*) >= %(min_voices)s) v USING (key)
    JOIN (SELECT key, json_agg(json_build_array(source_id::text, only_roundups) ORDER BY source_id) AS sources
          FROM (SELECT key, source_id, bool_and(roundup) AS only_roundups FROM link GROUP BY key, source_id) ksrc
          GROUP BY key) ks USING (key)
),
shown AS MATERIALIZED (           -- each kept key's top articles: most voices first, then by address
    SELECT key, url, voices, r FROM (
        SELECT key, url, voices, row_number() OVER (PARTITION BY key ORDER BY cardinality(voices) DESC, url) AS r
        FROM (SELECT key, url, array_agg(voice) AS voices FROM heard
              WHERE article AND key IN (SELECT key FROM counted) GROUP BY key, url) per_url
    ) ranked WHERE r <= %(shown)s
),
listed AS (
    SELECT key, json_agg(json_build_array(url, voices) ORDER BY r) AS articles FROM shown GROUP BY key
)
SELECT c.key, c.articles, c.links, c.classics, c.voices, c.roundups, COALESCE(l.articles, '[]'::json), c.sources,
       (SELECT n FROM unknown)
FROM counted c LEFT JOIN listed l USING (key)
UNION ALL   -- the unknown count also when nothing is kept
SELECT NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, (SELECT n FROM unknown)
"""

# The hosts where tweets are found by shape (0066's TWEET_PATH in a link of a post's HTML): X and its
# mirrors (nitter.net, xcancel.com, ...), found, never listed. Read once per post, after its links are
# read (links_scanned_at): the kept hosts and the newest post read are kept with Discover's counts.
TWEET_HREF = r"https?://([A-Za-z0-9.-]+)" + TWEET_SHAPE
_MIRRORS = """
SELECT COALESCE(array_agg(DISTINCT lower(m[1])), '{}'), (SELECT max(links_scanned_at) FROM posts)
FROM posts p, regexp_matches(p.content_html, %(tweet)s, 'g') m
WHERE strpos(p.content_html, '/status/') > 0 AND (%(since)s::timestamptz IS NULL OR p.links_scanned_at > %(since)s)
"""
# A home page, as post_links.is_home reads one: a host and at most one segment, no query or fragment.
HOME = r"^([^/]*://)?[^/]*(/[^/?#]*)?$"

# The counting query's fixed parameters: with its text, the rules its stamp says (DiscoverRepository.stamp).
_COUNT_RULES = {"home": HOME, "depth": OWNER_DEPTH,
                "min_voices": DISCOVER_MIN_VOICES,
                "min_articles": DISCOVER_MIN_ARTICLES, "share": DISCOVER_ARTICLE_SHARE}

# The platform rule's links (issue 0080, discover_rules.platform_rows in SQL): every kept link but Saved's,
# a tweet's and a self-link, on a host that isn't a listed platform, by voice (a website's publication,
# else its source), grouped by host and first OWNER_DEPTH segments ("*": deeper ones follow).
_PLATFORMS = """
WITH src AS (
    SELECT * FROM unnest(%(ids)s::uuid[], %(kinds)s::text[], %(sites)s::text[], %(selves)s::text[]) AS s(id, kind, own_site, selves)
),
link AS (
    SELECT DISTINCT pl.target_url AS url, s.selves,
           """ + voice_keys.source_key_sql("s.kind", "s.own_site", "p.source_id") + """ AS voice
    FROM post_links pl JOIN posts p ON p.id = pl.post_id JOIN src s ON s.id = p.source_id
    WHERE NOT pl.boilerplate AND s.kind <> 'saved' AND pl.target_url !~ %(tweet)s
),
parsed AS (
    SELECT url, voice, selves, regexp_replace(lower(split_part(regexp_replace(url, '^[a-z]+://', ''), '/', 1)), '^www[.]', '') AS host,
           """ + _SEGMENTS.format(url="url") + """ AS segs
    FROM link
)
SELECT host, segs[1:%(depth)s] || CASE WHEN cardinality(segs) > %(depth)s THEN ARRAY['*'] ELSE '{}'::text[] END,
       count(DISTINCT url), array_agg(DISTINCT voice)
FROM parsed
WHERE NOT (host = ANY(%(listed)s) OR EXISTS (SELECT 1 FROM unnest(%(listed)s::text[]) l WHERE host LIKE '%%.' || l))
  AND NOT (selves <> '' AND EXISTS (SELECT 1 FROM unnest(segs[1:%(depth)s]) g WHERE ltrim(g, '@~') = ANY(string_to_array(selves, ' '))))
GROUP BY 1, 2
"""

# Each suggestion's activity (issue 0080: Discover's order): when your sources last linked it, and how many
# of the posts linking it you opened or read.
_ACTIVITY = f"""
SELECT d.key, max({pairing.ix_date('p')}),
       count(DISTINCT p.id) FILTER (WHERE rs.read_at IS NOT NULL OR EXISTS (
           SELECT 1 FROM post_interactions i WHERE i.post_id = p.id AND i.interaction_type IN ('opened', 'reading_session')))
FROM discover_addresses d JOIN post_links pl ON pl.target_url = d.url AND NOT pl.boilerplate
JOIN posts p ON p.id = pl.post_id LEFT JOIN post_reader_state rs ON rs.post_id = p.id
WHERE d.rules = %(rules)s AND d.key = ANY(%(keys)s) AND {suggestable_sql("p.source_id")}
GROUP BY d.key
"""

# A website voice is named after the source of its first kept link in post order; asked only for
# the sites more than one website source shares (the others have one source).
_SITE_NAMERS = """
SELECT DISTINCT ON (voice) voice, source_id FROM (
    SELECT """ + voice_keys.site_key_sql("s.own_site") + """ AS voice, p.source_id, min(p.id::text COLLATE "C") AS first
    FROM posts p JOIN unnest(%(ids)s::uuid[], %(sites)s::text[]) AS s(id, own_site) ON s.id = p.source_id
    WHERE EXISTS (SELECT 1 FROM post_links pl WHERE pl.post_id = p.id AND NOT pl.boilerplate)
    GROUP BY 1, 2
) per_source ORDER BY voice, first
"""

# Each story's root (0064): its outside page, else its one post with no parent and no reason.
_ORIGINS = f"""
SELECT s.id, COALESCE(s.origin_url, p.normalized_url, p.url), s.origin_title, {shown_title()}, p.source_id,
       s.first_at, EXISTS (SELECT 1 FROM posts held WHERE s.origin_url IS NOT NULL AND held.normalized_url = s.origin_url),
       (SELECT array_agg(DISTINCT sp.voice) FROM story_posts sp JOIN posts vp ON vp.id = sp.post_id
        WHERE sp.story_id = s.id AND {suggestable_sql("vp.source_id")}),
       (SELECT array_agg(DISTINCT rp.source_id::text) FROM story_posts sp JOIN posts rp ON rp.id = sp.post_id
        WHERE sp.story_id = s.id AND sp.voice LIKE '{voice_keys.POSTER_LIKE}' AND {suggestable_sql("rp.source_id")}),
       EXISTS (SELECT 1 FROM story_posts sp JOIN posts op ON op.id = sp.post_id
               WHERE sp.story_id = s.id AND NOT {suggestable_sql("op.source_id")})
FROM stories s
LEFT JOIN LATERAL (
    SELECT min(sp.post_id::text)::uuid AS post_id FROM story_posts sp
    WHERE sp.story_id = s.id AND sp.parent_id IS NULL AND sp.parent_reason IS NULL AND sp.parent_url IS NULL
    HAVING count(*) = 1
) root ON s.origin_url IS NULL
LEFT JOIN posts p ON p.id = root.post_id
WHERE s.voices >= %(min_voices)s AND COALESCE(s.origin_url, p.normalized_url, p.url) IS NOT NULL
"""


class DiscoverRepository:
    @staticmethod
    def fill_addresses(cur: Cursor, post_sources: Iterable[str] = (), urls: Optional[Sequence[str]] = None,
                       platforms: Platforms = {}) -> int:
        """Work out the addresses kept links point to, and the posts of `post_sources` are at (the
        platform accounts' sources: a repost is at its original's address), that discover_addresses
        lacks (or holds by older rules), and drop the rows no kept link and no post points to.
        Returns how many it added. One writer at a time (a transaction lock): a second open waits,
        then finds nothing to add. With `urls`, only those addresses (a story run's, issue 0072); by the
        platforms the data finds (`platforms`, issue 0080: their rows' rules say which)."""
        rules = address_stamp(platforms)
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        if urls is None:   # a story run's addresses are counted only while the rules hold (StoriesService._counted)
            cur.execute("DELETE FROM discover_addresses WHERE rules <> %s", (rules,))
        only = None if urls is None else sorted(set(urls))
        cur.execute("SELECT url FROM (SELECT target_url AS url FROM post_links WHERE NOT boilerplate "
                    "AND (%(only)s::text[] IS NULL OR target_url = ANY(%(only)s)) "
                    "UNION SELECT COALESCE(normalized_url, url) FROM posts WHERE source_id = ANY(%(sources)s::uuid[]) "
                    "AND (%(only)s::text[] IS NULL OR COALESCE(normalized_url, url) = ANY(%(only)s))) a "
                    "WHERE url IS NOT NULL AND NOT EXISTS (SELECT 1 FROM discover_addresses d WHERE d.url = a.url "
                    "AND d.rules = %(rules)s)",
                    {"only": only, "sources": sorted(post_sources), "rules": rules})
        found = [r[0] for r in cur.fetchall()]
        if not found:
            if only is not None:
                DiscoverRepository._drop_unlinked(cur, only)
            return 0
        cur.execute("DELETE FROM discover_addresses WHERE url = ANY(%s)", (found,))   # an older rules' row
        with cur.copy("COPY discover_addresses (url, key, site, platform, article, rules) FROM STDIN") as copy:
            for url in found:
                key, site, platform = discover_address(url, platforms)
                copy.write_row((url, key, site, platform, discover_article(url), rules))
        DiscoverRepository._drop_unlinked(cur, only)
        return len(found)

    @staticmethod
    def _drop_unlinked(cur: Cursor, urls: Optional[Sequence[str]]) -> None:
        """Drop the addresses (of `urls`, when given) no kept link and no post points to."""
        cur.execute("DELETE FROM discover_addresses d WHERE (%(only)s::text[] IS NULL OR d.url = ANY(%(only)s)) "
                    "AND NOT EXISTS (SELECT 1 FROM post_links pl WHERE pl.target_url = d.url AND NOT pl.boilerplate) "
                    "AND NOT EXISTS (SELECT 1 FROM posts p WHERE COALESCE(p.normalized_url, p.url) = d.url)",
                    {"only": None if urls is None else list(urls)})

    @staticmethod
    def keys_of(cur: Cursor, urls: Sequence[str], platforms: Platforms = {}) -> Set[str]:
        """The Discover keys of these addresses."""
        cur.execute("SELECT DISTINCT key FROM discover_addresses WHERE url = ANY(%s) AND rules = %s AND key IS NOT NULL",
                    (list(urls), address_stamp(platforms)))
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def counts(cur: Cursor, *, kinds: Dict[str, str], own_sites: Dict[str, str], accounts: Dict[str, str],
               mirrors: Iterable[str], shown: int, keys: Optional[Iterable[str]] = None,
               selves: Optional[Dict[str, Iterable[str]]] = None,
               platforms: Platforms = {}) -> Tuple[List[Dict[str, Any]], int]:
        """The kept suggestions, unordered, those you follow or hid too, and how many linked addresses
        discover_addresses lacks (when any, fill_addresses and ask again: those links were not
        counted). A suggestion: key, voices [(voice, the source naming it; None for a Reddit author)],
        roundups (the voices linking it only in roundups, issue 0067), article_count, link_count,
        classics (its addresses that are classics, hidden or not) and its `shown` top articles
        [(url, voices)].
        `kinds` and `own_sites`: each source's kind (source_kind) and publication, its website voice
        (SourceFacts.publication, issue 0069);
        `accounts`: the platform account of each source that follows one (SourceFacts.platform_accounts),
        whose posts at another account's address are reposts, counted as links to that address;
        `mirrors`: the hosts where tweets are found (DiscoverRepository.mirrors);
        `keys`: only these keys (a story run counts again the keys its posts link, issue 0072);
        `selves`: each source's own names (SourceFacts.selves): its links under one are no voice, nor are
        Saved's (issue 0080); `platforms`: the data's (find_platforms), which the addresses were keyed by.
        Each suggestion also has its sources [(source, whether it links it only in roundups)]."""
        selves = selves or {}
        ids = sorted(kinds)
        # Its hash tables and sorts (~100k addresses) fit in memory with this; the default 4 MB
        # spilled them to disk. For this transaction only.
        cur.execute("SET LOCAL work_mem = '%s'" % WORK_MEM)
        cur.execute(_COUNTS, {
            "ids": ids, "kinds": [kinds[i] for i in ids], "sites": [own_sites.get(i, "") for i in ids],
            "accounts": [accounts.get(i, "") for i in ids], "selves": [" ".join(sorted(selves.get(i, ()))) for i in ids],
            "mirrors": sorted(mirrors), "shown": shown, "keys": None if keys is None else sorted(keys), **_COUNT_RULES,
            "rules": address_stamp(platforms),
        })
        rows = cur.fetchall()
        unknown = int(rows[0][-1])   # on every row, and on the one row with no key
        found = [{
            "key": key, "article_count": int(articles), "link_count": int(links), "classics": list(classics),
            "voices": list(voices), "roundups": list(roundups),
            "articles": [(url, list(url_voices)) for url, url_voices in shown_articles],
            "sources": [(source_id, bool(only)) for source_id, only in sources],
        } for key, articles, links, classics, voices, roundups, shown_articles, sources, _ in rows if key is not None]
        DiscoverRepository.name_voices(cur, found, kinds, own_sites)
        return found, unknown

    @staticmethod
    def name_voices(cur: Cursor, found: List[Dict[str, Any]], kinds: Dict[str, str], own_sites: Dict[str, str]) -> None:
        """Each suggestion's voices as (voice, the source naming it; voice_source)."""
        voices = [[v[0] if isinstance(v, (list, tuple)) else v for v in s["voices"]] for s in found]
        namers = DiscoverRepository._site_namers(cur, kinds, own_sites, {v for vs in voices for v in vs if voice_keys.is_site(v)})
        for s, vs in zip(found, voices):
            s["voices"] = [(voice, voice_source(voice, namers)) for voice in vs]

    @staticmethod
    def platforms(cur: Cursor, *, kinds: Dict[str, str], own_sites: Dict[str, str],
                  selves: Dict[str, Iterable[str]]) -> Dict[str, Tuple[str, ...]]:
        """The hosts the data finds platforms (discover_rules.find_platforms, issue 0080), each with the
        path its owners sit under, from every kept link grouped in SQL (platform_rows')."""
        from insight_core.utils.url_normalization import TWEET_SHAPE as shape
        ids = sorted(kinds)
        cur.execute("SET LOCAL work_mem = '%s'" % WORK_MEM)
        cur.execute(_PLATFORMS, {"ids": ids, "kinds": [kinds[i] for i in ids], "sites": [own_sites.get(i, "") for i in ids],
                                 "selves": [" ".join(sorted(selves.get(i, ()))) for i in ids], "tweet": shape,
                                 "depth": OWNER_DEPTH, "listed": sorted(DISCOVER_PLATFORMS)})
        return find_platforms((host, tuple(segs), n, voices) for host, segs, n, voices in cur.fetchall())

    @staticmethod
    def activity(cur: Cursor, keys: Iterable[str], platforms: Platforms = {}) -> Dict[str, Tuple[Optional[datetime], int]]:
        """Each key's last link (its post's time) and the posts linking it you opened or read (issue 0080)."""
        cur.execute(_ACTIVITY, {"rules": address_stamp(platforms), "keys": sorted(keys)})
        return {key: (last, int(opened)) for key, last, opened in cur.fetchall()}

    @staticmethod
    def mirrors(cur: Cursor, kept: Optional[Dict[str, Any]]) -> Tuple[List[str], Optional[str]]:
        """The hosts where tweets are found by shape (TWEET_HREF), and the newest post read: those
        `kept` with the last counts, plus the ones found in the posts read since (all, the first time)."""
        hosts = set(kept["mirrors"]) if kept else set()
        cur.execute(_MIRRORS, {"tweet": TWEET_HREF, "since": kept["scanned_to"] if kept else None})
        found, scanned_to = cur.fetchone()
        return sorted(hosts | set(found)), scanned_to.isoformat() if scanned_to else None

    @staticmethod
    def gifted(cur: Cursor, urls: Sequence[str]) -> set:
        """Of these addresses, the ones a post links by an access or gift token (issue 0126: post_links.shared_url)."""
        if not urls:
            return set()
        from insight_core.utils.originals_rules import tokened
        cur.execute("SELECT DISTINCT target_url, shared_url FROM post_links WHERE target_url = ANY(%s) AND shared_url IS NOT NULL",
                    (list(urls),))
        return {url for url, shared in cur.fetchall() if tokened(shared)}

    @staticmethod
    def kept(cur: Cursor) -> Optional[Dict[str, Any]]:
        """Discover's last counts (issue 0067): {stamp, found, mirrors, scanned_to}, or None."""
        row = SystemSettingsRepository.get(cur, KEPT_KEY)
        return row[0] if row else None

    @staticmethod
    def keep(cur: Cursor, kept: Dict[str, Any]) -> None:
        SystemSettingsRepository.upsert(cur, KEPT_KEY, kept)

    @staticmethod
    def kept_list(cur: Cursor, made_from: str) -> Optional[Dict[str, Any]]:
        """Discover's last list (issue 0080 cold open) when it was made from `made_from` (its inputs and
        code), else None."""
        cur.execute("SELECT value->'list' FROM system_settings WHERE key = %s AND value->>'made_from' = %s",
                    (LIST_KEY, made_from))
        row = cur.fetchone()
        return row[0] if row else None

    @staticmethod
    def keep_list(cur: Cursor, made_from: str, found: Dict[str, Any]) -> None:
        SystemSettingsRepository.upsert(cur, LIST_KEY, {"made_from": made_from, "list": found})

    @staticmethod
    def any_list(cur: Cursor) -> Optional[Dict[str, Any]]:
        """The list kept last (LIST_KEY), whatever it was made from: what Discover serves before its first build."""
        cur.execute("SELECT value->'list' FROM system_settings WHERE key = %s", (LIST_KEY,))
        row = cur.fetchone()
        return row[0] if row and isinstance(row[0], dict) and "suggestions" in row[0] else None

    @staticmethod
    def served_stamp(cur: Cursor) -> Optional[Tuple[str, str]]:
        """(made_from, built_at) of the answer Discover serves (issue 0172 c1), without the answer, or None."""
        cur.execute("SELECT value->>'made_from', value->>'built_at' FROM system_settings WHERE key = %s", (SERVED_KEY,))
        row = cur.fetchone()
        return (row[0], row[1]) if row and row[1] else None

    @staticmethod
    def served(cur: Cursor) -> Optional[Dict[str, Any]]:
        """The answer Discover serves: {made_from, built_at, answer}, or None before the first build."""
        row = SystemSettingsRepository.get(cur, SERVED_KEY)
        return row[0] if row and isinstance(row[0], dict) and row[0].get("answer") else None

    @staticmethod
    def served_window(cur: Cursor, offset: int, limit: int) -> Optional[Tuple[Dict[str, Any], int]]:
        """Issue 0206: (the answer served with only its suggestions offset..offset+limit, how many suggestions it
        holds), sliced in Postgres: an open reads its page, not the whole 2 MB answer. None before the first build."""
        if limit <= 0:
            return None
        window = f"$[{int(offset)} to {int(offset) + int(limit) - 1}]"   # lax: the elements in range, [] past the end
        # the stored value read (detoasted) once, not once an operator
        cur.execute("""WITH v AS MATERIALIZED (SELECT value->'answer' AS a FROM system_settings
                                                WHERE key = %(k)s AND value ? 'answer')
                       SELECT a - 'suggestions'::text
                              || jsonb_build_object('suggestions', COALESCE(
                                     jsonb_path_query_array(a->'suggestions', %(w)s::jsonpath), '[]')),
                              jsonb_array_length(COALESCE(a->'suggestions', '[]'::jsonb))
                         FROM v""", {"w": window, "k": SERVED_KEY})
        row = cur.fetchone()
        return (row[0], int(row[1])) if row and isinstance(row[0], dict) else None

    @staticmethod
    def keep_served(cur: Cursor, made_from: str, built_at: str, answer: Dict[str, Any]) -> None:
        SystemSettingsRepository.upsert(cur, SERVED_KEY, {"made_from": made_from, "built_at": built_at, "answer": answer})

    @staticmethod
    def archive_states(cur: Cursor, missing: Dict[str, Sequence[str]]) -> Dict[str, Dict[str, Any]]:
        """Each source's archive as it is stored (issue 0080: an archive row follows it), for the sources
        missing these pages: {state: running | paused | finished | None, found: how many of the pages it
        has stored since, pages_fetched: the running or last archive's, when it says}. Running: its newest
        archive job runs or waits out a host's limit; paused: that job paused (its checkpoint kept); finished: the archive's checkpoint
        is done (settings.archive.checkpoint.completed_at). Issue 0109: also the pages it stores (stored_urls), its
        newest post (newest) and the page-watch prefix it watches (prefix), for the row to say what it lacks."""
        ids = sorted(missing)
        cur.execute("""SELECT DISTINCT ON (source_id) source_id::text, status, payload->'paused', payload->'pages_fetched'
                       FROM job_runs WHERE job_type = 'archive_source' AND source_id = ANY(%s::uuid[])
                       ORDER BY source_id, started_at DESC""", (ids,))
        jobs = {sid: (status, paused, pages) for sid, status, paused, pages in cur.fetchall()}
        cur.execute("SELECT id::text, settings->'archive'->'checkpoint'->>'completed_at', settings->'page_watch'->>'prefix', "
                    "handle_or_url FROM sources WHERE id = ANY(%s::uuid[])", (ids,))
        rows = cur.fetchall()
        done = {sid for sid, completed, _, _ in rows if completed}
        prefixes = {sid: prefix for sid, _, prefix, _ in rows if prefix}
        hosts = {sid: host_of(handle).removeprefix("www.") for sid, _, prefix, handle in rows if prefix and handle}
        cur.execute("SELECT DISTINCT source_id::text, normalized_url FROM posts p, unnest(%s::uuid[], %s::text[]) AS m(sid, url) "
                    "WHERE p.source_id = m.sid AND p.normalized_url = m.url",
                    ([sid for sid in ids for _ in missing[sid]], [url for sid in ids for url in missing[sid]]))
        stored: Dict[str, List[str]] = defaultdict(list)
        for sid, url in cur.fetchall():
            stored[sid].append(url)
        cur.execute(f"SELECT source_id::text, max({pairing.ix_date('')}) FROM posts WHERE source_id = ANY(%s::uuid[]) "
                    "GROUP BY 1", (ids,))
        newest = dict(cur.fetchall())
        out = {}
        for sid in ids:
            status, paused, pages = jobs.get(sid, (None, None, None))
            # A waiting archive (issue 0107) still runs: it continues by itself.
            state = ("running" if status in ("running", "waiting") else "paused" if paused is True
                     else "finished" if sid in done else None)
            out[sid] = {"state": state, "found": len(stored[sid]),
                        **({"pages_fetched": pages} if isinstance(pages, int) else {}),
                        "stored_urls": sorted(stored[sid]), "newest": newest.get(sid), "prefix": prefixes.get(sid),
                        "host": hosts.get(sid)}   # the host a page watch reads (issue 0111)
        return out

    @staticmethod
    def reads(cur: Cursor) -> Dict[str, Any]:
        """What Discover read of the web for its first page (issue 0080, services/discover_reads.py):
        {follow: {key: {label, at}}, titles: {address: {title, at}}}."""
        row = SystemSettingsRepository.get(cur, READS_KEY)
        return (row[0] if row else None) or {}

    @staticmethod
    def read_titles(cur: Cursor, urls: Sequence[str]) -> Dict[str, str]:
        """The page titles read of these addresses (issue 0106: Classics show them), those that had one, and not
        one 2+ pages of its host share (issue 0109 W7: its site's name; page_titles.shared_titles)."""
        from insight_core.services import page_titles
        reads = DiscoverRepository.reads(cur).get("titles", {})
        shared = page_titles.shared_titles(reads)
        return {url: title for url in urls if (title := page_titles.read(reads, url, shared))}

    @staticmethod
    def keep_reads(cur: Cursor, reads: Dict[str, Any]) -> None:
        SystemSettingsRepository.upsert(cur, READS_KEY, reads)

    @staticmethod
    def base(cur: Cursor) -> str:
        """What the counts are counted by, a story run aside: the rules (issue 0072: while they hold, a story
        run counts again only the keys its posts link; a source whose facts change has its posts queued, so
        the keys they link are among those) and the round-up tags (units.tags_stamp, 0190: a post tagged since
        moves the voices that link only in round-ups, whatever keys a run's posts link)."""
        what = [_COUNTS, _COUNT_RULES, ADDRESS_RULES, units.tags_stamp(cur)]
        return hashlib.sha1(json.dumps(what).encode()).hexdigest()[:16]

    @staticmethod
    def stamp(cur: Cursor, facts: Any) -> str:
        """What the counts are counted from: the rules (the counting query as written, issue 0071, and
        the addresses'), the last story run (links are read and classics refreshed before it) and
        `facts`, the facts of the sources with posts (a source with none links nothing). Same stamp,
        same counts."""
        cur.execute(f"SELECT {DISCOVER_AT} FROM system_settings WHERE key = 'stories'")
        row = cur.fetchone()
        what = json.dumps([DiscoverRepository.base(cur), row[0] if row else None, facts])
        return hashlib.sha1(what.encode()).hexdigest()[:16]

    @staticmethod
    def story_origins(cur: Cursor, *, kinds: Dict[str, str], own_sites: Dict[str, str]) -> List[Origin]:
        """Where each story of ORIGIN_MIN_VOICES+ voices starts (issue 0065): its outside page, else
        its origin post's address (a story whose tree is not drawn yet has none), with its voices,
        each named as Discover names it, and its title: the outside page's (origin_title), else the
        post's as every place shows it (post_title, issue 0072 D1)."""
        cur.execute(_ORIGINS, {"min_voices": ORIGIN_MIN_VOICES})
        # Its voices are those of sources not switched off (issue 0200): a story with a post of one, which the others
        # leave under the bar, starts nothing Discover suggests, nor a page or an archive row (its place in the
        # stories is unchanged). A story with none keeps the story job's count.
        rows = [r[:-1] for r in cur.fetchall() if not r[-1] or len(r[7] or ()) >= ORIGIN_MIN_VOICES]
        namers = DiscoverRepository._site_namers(
            cur, kinds, own_sites, {v for *_, voices, _ in rows for v in voices if voice_keys.is_site(v)})
        return [Origin(str(story_id), url, title if source_id else origin_title,
                       str(source_id) if source_id else None, first_at, {v: voice_source(v, namers) or "" for v in voices},
                       reddit_sources=tuple(reddit or ()), at_post=bool(held))
                for story_id, url, origin_title, title, source_id, first_at, held, voices, reddit in rows]

    @staticmethod
    def stored_titles(cur: Cursor, urls: Sequence[str]) -> Dict[str, str]:
        """The title every place shows (post_title) of the first post stored at each address."""
        cur.execute(f"SELECT DISTINCT ON (p.normalized_url) p.normalized_url, {shown_title()} FROM posts p "
                    "WHERE p.normalized_url = ANY(%s) ORDER BY p.normalized_url, p.fetched_at, p.created_at, p.id", (list(urls),))
        return dict(cur.fetchall())

    @staticmethod
    def first_posts(cur: Cursor, source_ids: Iterable[str]) -> Dict[str, datetime]:
        """Each source's first post (published, else fetched): how far back it holds."""
        cur.execute(f"SELECT source_id, min({pairing.ix_date('')}) FROM posts "
                    "WHERE source_id = ANY(%s::uuid[]) GROUP BY 1", (sorted(source_ids),))
        return {str(source_id): first for source_id, first in cur.fetchall() if first}

    @staticmethod
    def site_hosts(cur: Cursor, sites: Iterable[str]) -> Dict[str, Tuple[int, int]]:
        """Each site's hosts your sources' kept links point to, and the posts linking it (issue 0109: a domain
        of many owners, discover_rules.federation): {site: (hosts, posts)}."""
        sites = sorted(set(sites))
        if not sites:
            return {}
        cur.execute("""SELECT target_site, count(DISTINCT regexp_replace(lower(substring(target_url FROM '://([^/:?#]+)')), '^www[.]', '')),
                              count(DISTINCT post_id)
                       FROM post_links WHERE NOT boilerplate AND target_site = ANY(%s) GROUP BY 1""", (sites,))
        return {site: (int(hosts), int(posts)) for site, hosts, posts in cur.fetchall()}

    @staticmethod
    def posts_on(cur: Cursor, hosts: Iterable[str]) -> List[Tuple[str, str]]:
        """(source, address) of every post on these hosts: the places your sources hold there."""
        cur.execute("SELECT source_id, COALESCE(normalized_url, url) FROM posts WHERE url_host = ANY(%s)", (sorted(hosts),))
        return [(str(source_id), url) for source_id, url in cur.fetchall() if url]

    @staticmethod
    def _site_namers(cur: Cursor, kinds: Dict[str, str], own_sites: Dict[str, str],
                     voices: Set[str]) -> Dict[str, str]:
        """Each website voice and the source it is named after: its only website source, or of
        the sources sharing the site the one whose kept links come first in post order."""
        by_site: Dict[str, List[str]] = defaultdict(list)
        for source_id, kind in kinds.items():
            if kind == "site" and voice_keys.site_key(own_sites.get(source_id, "")) in voices:
                by_site[voice_keys.site_key(own_sites.get(source_id, ""))].append(source_id)
        namers = {voice: ids[0] for voice, ids in by_site.items() if len(ids) == 1}
        shared = sorted(i for ids in by_site.values() if len(ids) > 1 for i in ids)
        if shared:
            cur.execute(_SITE_NAMERS, {"ids": shared, "sites": [own_sites.get(i, "") for i in shared]})
            namers.update({voice: str(source_id) for voice, source_id in cur.fetchall()})
        return namers


SUPPLIERS_KEY = "originals_suppliers"   # 0138 D2: kept by OriginalsService.keep_suppliers (ingestion)


def light_facts(cur: Cursor) -> Any:
    """0138: the sources' facts from the sources table alone (names, own sites, followed sites), with none of their
    posts read: what Discover's per-open rows need, cheap enough for every open (the full SourceFacts reads posts)."""
    from insight_core.db.repo_stories import SourceFacts, switched_off
    cur.execute("SELECT id, platform, handle_or_url, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url) "
                "FROM sources")
    rows = cur.fetchall()
    return SourceFacts.of(rows, [], off=switched_off(cur))


def entity_pages(cur: Cursor, db_url: str, now: datetime, *, hidden: Set[str], names: Any,
                 skip: Set[str]) -> List[Dict[str, Any]]:
    """Discover → Pages, 0138 D1: the Mark X entities' originals not stored whose entity meets Collect originals'
    trigger (2+ voices in 7 days, or a News lead), beside the stories' roots: {url, title, site, hide_key, video,
    tweet, first_linked_at, voices, readable, stories: [], entity: {id, name}, voice_names}. `names`: a source id's
    name; `skip`: the addresses already a row. Collected ones are stored, so they leave by themselves."""
    from insight_core.services.originals_service import OriginalsService, site_reads
    from insight_core.utils.addresses import is_tweet, site_of
    from insight_core.utils.discover_rules import follow_url, page_key_of
    from insight_core.utils.originals_rules import SiteReads, strip_access_tokens, tokened
    wanted, _ = OriginalsService(db_url).plan_entities(cur, now, listing=True)
    walls = site_reads(cur)
    out = []
    for w in wanted:
        url = strip_access_tokens(w["url"])
        if url in skip or page_key_of(url) in hidden:
            continue
        skip.add(url)
        site = site_of(host_of(url))
        out.append({"url": url, "title": None, "site": site, "hide_key": page_key_of(url), "video": False,
                    "tweet": is_tweet(url), "follow_url": follow_url(url), "first_linked_at": w["first_at"].isoformat(), "voices": w["voices"],
                    "readable": not (tokened(w["url"]) or walls.get(site, SiteReads()).walled), "stories": [],
                    "entity": {"id": w["entity_id"], "name": w["name"]},
                    "voice_names": sorted({names(s) for s in w["sources"] if names(s)})[:6]})
    if out:
        titled = DiscoverRepository.read_titles(cur, [r["url"] for r in out])
        for r in out:
            r["title"] = titled.get(r["url"])
    return out


def suppliers(cur: Cursor) -> Dict[str, Any]:
    """0138 D2-D3 as OriginalsService.keep_suppliers kept them: {current: {key: {n, urls, since}}, suggested: {key:
    first suggested at}}."""
    row = SystemSettingsRepository.get(cur, SUPPLIERS_KEY)
    return (row[0] if row else None) or {}


def longread_citations(cur: Cursor) -> Dict[str, Dict[str, int]]:
    """0138 F3 as OriginalsService.keep_cited kept it: {key: {n: citations, posts: long-reads}}."""
    row = SystemSettingsRepository.get(cur, "longread_citations")
    return (row[0] if row else None) or {}


def supplied_first(cur: Cursor, suggested: Dict[str, str], *, facts: Any) -> List[Dict[str, Any]]:
    """0138 D3 (shown, not used to rank yet): each source you followed at a site D2 suggested, after it was suggested,
    and how many originals it brought before any other source of yours: its posts since you followed it at an
    address that is an original (an entity's address, a story's root, an original asked for) whose first linking
    post of another source, if any, came later. [{key, source_id, name, followed_at, originals_first}]."""
    from insight_core.utils.addresses import site_of
    if not suggested:
        return []
    cur.execute(f"SELECT id::text, created_at FROM sources WHERE {suggestable_sql('id')}")
    created = dict(cur.fetchall())
    out = []
    for key, since in sorted(suggested.items()):
        at = datetime.fromisoformat(since)
        site = key.split("/", 1)[0]
        ids = [sid for sid, s in facts.site.items() if s and (s == key or s == site or site_of(s) == site_of(site))
               and sid in created and created[sid] >= at]
        for sid in ids:
            cur.execute(f"""
                SELECT count(*) FROM posts p
                 WHERE p.source_id = %(s)s AND {pairing.ix_date('p')} >= %(at)s
                   AND (EXISTS (SELECT 1 FROM mx_entity_addresses a WHERE a.url = p.normalized_url)
                        OR EXISTS (SELECT 1 FROM stories st WHERE st.origin_url = p.normalized_url)
                        OR EXISTS (SELECT 1 FROM story_originals o WHERE o.url = p.normalized_url))
                   AND NOT EXISTS (SELECT 1 FROM post_links l JOIN posts q ON q.id = l.post_id
                                    WHERE l.target_url = p.normalized_url AND q.source_id <> p.source_id
                                      AND {pairing.ix_date('q')} < {pairing.ix_date('p')})""",
                        {"s": sid, "at": created[sid]})
            out.append({"key": key, "source_id": sid, "name": facts.name.get(sid, ""),
                        "followed_at": created[sid].isoformat(), "originals_first": cur.fetchone()[0]})
    return out


def voice_source(voice: str, site_namers: Dict[str, str]) -> Optional[str]:
    """The source a voice is named after (SourceFacts.voice_name): a website the source of its
    first kept link (`site_namers`), a source voice its own; a Reddit author none."""
    source_id = voice_keys.source_of(voice)
    return source_id if source_id is not None else site_namers.get(voice)


__all__ = ["DiscoverRepository", "ADDRESS_RULES"]
