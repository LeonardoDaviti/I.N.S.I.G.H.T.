"""Discover's counts in the database: the sites and accounts your sources keep linking, grouped and counted in
one query so the API never holds every kept link in memory (0062).

It is discover_rules.suggestions (the pure reference) in SQL over every kept link (`post_links`, plus
@mentions: `read_sql`). Per-address facts (key, site, platform, article-like) are worked out once in Python
into `discover_addresses` (`fill_addresses`); a key with enough article-like addresses is a candidate, and a
candidate with 3+ voices is kept. Python orders the kept keys, names the voices and titles the articles. The
counts are kept between story runs (system_settings `discover_counts`) while their `stamp` holds; hidden and
followed keys are left out when read, so hiding or following needs no recount. Addresses compare byte for
byte (COLLATE "C"), as Python's strings do; the one lowercasing in SQL uses ICU, Python's case mapping.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from itertools import groupby
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
                                               host_platform)
from insight_core.utils.url_normalization import TWEET_SHAPE

LOCK_KEY = "insight.discover_addresses"
# An address's path segments, lower case (ICU), as discover_rules.path_segments reads them.
_SEGMENTS = ("array_remove(string_to_array(lower(regexp_replace(regexp_replace({url}, '^[a-z]+://[^/]*/?', ''), "
             "'[?#].*$', '') COLLATE \"und-x-icu\"), '/'), '')")
KEPT_KEY = "discover_counts"   # Discover's counts between story runs (system_settings)
TAGGED_KEY = "discover_tagged"   # the round-up tagged posts the kept counts were made with (`retagged`)
LIST_KEY = "discover_list"     # Discover's last list, by what it was made from
SERVED_KEY = "discover_served"   # the answer Discover's page serves, built in the background
# When Discover's inputs last changed (StoriesService._settle), else the last story run.
DISCOVER_AT = "COALESCE(value->>'discover_at', value->>'computed_at')"
READS_KEY = "discover_reads"   # the follow tests and page titles Discover read
VIDEO_LIKE = "https://youtube.com/watch?v=%"   # a video's one address (url_normalization writes every form so)
WORK_MEM = "48MB"
PLATFORM_ROWS = 2000   # the platform rule's grouped rows fetched at a time (`platforms`)



def read_sql(alias: str = "") -> str:
    """SQL: a post_links row Discover reads: a kept link, or an @mention (stored as boilerplate so no story, News
    or Mark X rule reads it)."""
    a = alias + "." if alias else ""
    return f"(NOT {a}boilerplate OR {a}kind = 'mention')"


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
mention_url AS MATERIALIZED (     -- 0235: the addresses posts @mention (an account's own; stored as boilerplate)
    SELECT DISTINCT target_url COLLATE "C" AS url FROM post_links WHERE kind = 'mention'
),
kept_url AS MATERIALIZED (        -- each address a kept link (or a mention) points to, and what Discover reads of it
    SELECT u.url, d.key COLLATE "C" AS key, d.site, d.platform, d.article, d.url IS NULL AS unknown,
           u.url IN (SELECT url FROM mention_url) AS mentioned
    FROM (SELECT target_url COLLATE "C" AS url FROM post_links WHERE """ + "{read}" + """ AND %(keys)s::text[] IS NULL
          UNION SELECT a.url COLLATE "C" FROM discover_addresses a      -- the keys asked: their linked addresses
                WHERE a.key = ANY(%(keys)s) AND a.rules = %(rules)s
                  AND EXISTS (SELECT 1 FROM post_links pl WHERE pl.target_url = a.url AND """ + "{read_pl}" + """)
          UNION SELECT url FROM reposted WHERE NOT unknown) u
    LEFT JOIN discover_addresses d ON d.url = u.url AND d.rules = %(rules)s
),
unknown AS (SELECT (SELECT count(*) FROM kept_url WHERE unknown) + (SELECT count(*) FROM reposted WHERE unknown) AS n),
unfollowed AS MATERIALIZED (      -- those with a key, not a tweet mirror's other pages (issue 0067; one you
    SELECT url, key, article, mentioned FROM kept_url   -- follow or hid is left out when read: discover_open)
    WHERE key IS NOT NULL AND (platform OR NOT key = ANY(%(mirrors)s))
),
candidate AS MATERIALIZED (       -- keys with 2+ article-like addresses, 40%%+ of their addresses, or (0235) @mentioned
    SELECT key, count(*) FILTER (WHERE article) AS articles, count(*) AS links,
           COALESCE(array_agg(url) FILTER (WHERE url IN (SELECT target_url FROM classics)), '{}') AS classics
    FROM unfollowed GROUP BY key
    HAVING (count(*) FILTER (WHERE article) >= %(min_articles)s
            AND count(*) FILTER (WHERE article) >= %(share)s::float8 * count(*))
        OR bool_or(mentioned)     -- an account named by posts needs no article, only its voices (0235)
),
linked AS MATERIALIZED (          -- the kept links to those keys' addresses, but Saved's and a source's
    SELECT u.key, u.url, u.article, pl.post_id, p.source_id,   -- links to its own pages (issue 0080)
           COALESCE(s.kind, 'site') AS kind, COALESCE(s.own_site, '') AS own_site
    FROM unfollowed u JOIN post_links pl ON pl.target_url = u.url AND """ + "{read_pl}" + """
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

_COUNTS = _COUNTS.replace("{read_pl}", read_sql("pl")).replace("{read}", read_sql())

# The hosts where tweets are found by shape: X and its mirrors, found, never listed. Read once per post after
# its links are read; the hosts and the newest post read are kept with Discover's counts.
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

# The platform rule's links (discover_rules.platform_rows in SQL): every kept link but Saved's, a tweet's and a
# self-link, on a host that isn't a listed platform, by voice, grouped by host and first OWNER_DEPTH segments.
_PLATFORMS = """
WITH src AS (
    SELECT * FROM unnest(%(ids)s::uuid[], %(kinds)s::text[], %(sites)s::text[], %(selves)s::text[]) AS s(id, kind, own_site, selves)
),
link AS MATERIALIZED (            -- each kept link once a voice (v10.22: before any address is parsed)
    SELECT DISTINCT pl.target_url AS url, s.selves,
           """ + voice_keys.source_key_sql("s.kind", "s.own_site", "p.source_id") + """ AS voice
    FROM post_links pl JOIN posts p ON p.id = pl.post_id JOIN src s ON s.id = p.source_id
    WHERE NOT pl.boilerplate AND s.kind <> 'saved'
      AND NOT (strpos(pl.target_url, '/status/') > 0 AND pl.target_url ~ %(tweet)s)   -- the shape needs it (v10.22)
),
parsed AS MATERIALIZED (          -- each address parsed once (v10.22: was once a link and voice), not a listed platform's
    SELECT url, host, segs[1:%(depth)s] AS head, cardinality(segs) > %(depth)s AS deeper FROM (
        SELECT url, regexp_replace(lower(split_part(regexp_replace(url, '^[a-z]+://', ''), '/', 1)), '^www[.]', '') AS host,
               """ + _SEGMENTS.format(url="url") + """ AS segs
        FROM (SELECT DISTINCT url FROM link) u
    ) x
    WHERE NOT (host = ANY(%(listed)s) OR host LIKE ANY(%(under)s))   -- v10.22: a pattern each (was a subquery an address)
),
grouped AS MATERIALIZED (
SELECT a.host COLLATE "C" AS host, (a.head || CASE WHEN a.deeper THEN ARRAY['*'] ELSE '{}'::text[] END) COLLATE "C" AS segs,
       count(DISTINCT l.url) AS urls, array_agg(DISTINCT l.voice) AS voices   -- grouped byte for byte: the same groups, a cheaper sort
FROM link l JOIN parsed a USING (url)
WHERE NOT (l.selves <> '' AND EXISTS (SELECT 1 FROM unnest(a.head) g WHERE ltrim(g, '@~') = ANY(string_to_array(l.selves, ' '))))
GROUP BY 1, 2
)
SELECT host, segs, urls, voices FROM grouped   -- v10.22.2: only the hosts with find_platforms' voices (a NULL voice one)
WHERE host IN (SELECT host FROM grouped, unnest(voices) v GROUP BY host
                HAVING count(DISTINCT v) + bool_or(v IS NULL)::int >= %(min_voices)s)
"""

# Each suggestion's activity: its last link, how many linking posts you opened or read, and how many linking
# sources first did since %(since)s and before (discover_rules.growth).
_ACTIVITY = f"""
SELECT key, max(last_at), sum(opened)::int, count(*) FILTER (WHERE first_at > %(since)s),
       count(*) FILTER (WHERE first_at <= %(since)s)
FROM (SELECT d.key, p.source_id, max({pairing.ix_date('p')}) AS last_at, min({pairing.ix_date('p')}) AS first_at,
             count(DISTINCT p.id) FILTER (WHERE rs.read_at IS NOT NULL OR EXISTS (
                 SELECT 1 FROM post_interactions i WHERE i.post_id = p.id
                    AND i.interaction_type IN ('opened', 'reading_session', 'opened_source'))) AS opened
      FROM discover_addresses d JOIN post_links pl ON pl.target_url = d.url AND {read_sql("pl")}
      JOIN posts p ON p.id = pl.post_id LEFT JOIN post_reader_state rs ON rs.post_id = p.id
      WHERE d.rules = %(rules)s AND d.key = ANY(%(keys)s) AND {suggestable_sql("p.source_id")}
      GROUP BY d.key, p.source_id) per_source
GROUP BY key
"""

# The code repositories your sources link (github.com/<owner>/<repo>/...), each with its voices, sources, last
# link and most linked pages. Not Saved's, not a switched-off source's, not a source's self-link.
_REPOS = f"""
WITH src AS (
    SELECT * FROM unnest(%(ids)s::uuid[], %(kinds)s::text[], %(sites)s::text[], %(selves)s::text[]) AS s(id, kind, own_site, selves)
),
link AS MATERIALIZED (
    SELECT lower(m[1] || '/' || regexp_replace(m[2], '[.]git$', '')) COLLATE "C" AS repo, lower(m[1]) AS owner,
           pl.target_url AS url, p.source_id, COALESCE(s.selves, '') AS selves,
           {voice_keys.source_key_sql("COALESCE(s.kind, 'site')", "COALESCE(s.own_site, '')", "p.source_id")} AS voice,
           {pairing.ix_date('p')} AS at
    FROM post_links pl JOIN posts p ON p.id = pl.post_id LEFT JOIN src s ON s.id = p.source_id,
         regexp_match(pl.target_url, '^https://github[.]com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)') m
    WHERE {read_sql("pl")} AND pl.target_url LIKE 'https://github.com/%%/%%' AND s.kind IS DISTINCT FROM 'saved'
      AND {suggestable_sql("p.source_id")}
),
kept AS MATERIALIZED (
    SELECT * FROM link WHERE NOT (selves <> '' AND owner = ANY(string_to_array(selves, ' ')))
),
-- 0248: each repository's most linked pages in one grouped pass (was a subquery per repository over every kept link:
-- 4.4 s of Discover's 20 s build on the server's copy)
page AS (
    SELECT repo, url, row_number() OVER (PARTITION BY repo ORDER BY count(DISTINCT voice) DESC, url) AS n
    FROM kept GROUP BY repo, url
),
top AS (
    SELECT repo, json_agg(url ORDER BY n) AS urls FROM page WHERE n <= %(shown)s GROUP BY repo
),
repos AS (
    SELECT repo, array_agg(DISTINCT voice) AS voices, array_agg(DISTINCT source_id::text) AS sources, max(at) AS last_at
    FROM kept GROUP BY repo HAVING count(DISTINCT voice) >= %(min_voices)s
)
SELECT r.repo, r.voices, r.sources, r.last_at, t.urls FROM repos r LEFT JOIN top t ON t.repo = r.repo
"""

# A website voice is named after the source of its first kept link in post order; asked only for sites more
# than one website source shares.
_SITE_NAMERS = """
SELECT DISTINCT ON (voice) voice, source_id FROM (
    SELECT """ + voice_keys.site_key_sql("s.own_site") + """ AS voice, p.source_id, min(p.id::text COLLATE "C") AS first
    FROM posts p JOIN unnest(%(ids)s::uuid[], %(sites)s::text[]) AS s(id, own_site) ON s.id = p.source_id
    WHERE EXISTS (SELECT 1 FROM post_links pl WHERE pl.post_id = p.id AND NOT pl.boilerplate)
    GROUP BY 1, 2
) per_source ORDER BY voice, first
"""

# Each story's root: its outside page, else its one post with no parent and no reason.
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
        """Work out the addresses kept links (and `post_sources`' posts: a repost is at its original's address)
        point to that discover_addresses lacks or holds by older rules, and drop unpointed rows. Returns how many
        it added. One writer at a time (a transaction lock). With `urls`, only those addresses."""
        rules = address_stamp(platforms)
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        if urls is None:   # a story run's addresses are counted only while the rules hold
            cur.execute("DELETE FROM discover_addresses WHERE rules <> %s", (rules,))
        only = None if urls is None else sorted(set(urls))
        cur.execute("SELECT url FROM (SELECT target_url AS url FROM post_links WHERE " + read_sql() + " "
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
        channels = DiscoverRepository.video_channels(cur)   # a video read is its channel's
        with cur.copy("COPY discover_addresses (url, key, site, platform, article, rules) FROM STDIN") as copy:
            for url in found:
                key, site, platform = discover_address(url, platforms, channels)
                copy.write_row((url, key, site, platform, url in channels or discover_article(url), rules))
        DiscoverRepository._drop_unlinked(cur, only)
        return len(found)

    @staticmethod
    def _drop_unlinked(cur: Cursor, urls: Optional[Sequence[str]]) -> None:
        """Drop the addresses (of `urls`, when given) no kept link and no post points to. Asked as two indexed
        lookups: COALESCE(normalized_url, url) has no index."""
        cur.execute("DELETE FROM discover_addresses d WHERE (%(only)s::text[] IS NULL OR d.url = ANY(%(only)s)) "
                    "AND NOT EXISTS (SELECT 1 FROM post_links pl WHERE pl.target_url = d.url AND " + read_sql("pl") + ") "
                    "AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.normalized_url = d.url) "
                    "AND NOT EXISTS (SELECT 1 FROM posts p WHERE p.url = d.url AND p.normalized_url IS NULL)",
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
        """The kept suggestions, unordered (followed and hidden too), and how many linked addresses
        discover_addresses lacks (when any, fill_addresses and ask again). A suggestion: key, voices [(voice,
        naming source)], roundups, article_count, link_count, classics, its `shown` top articles [(url, voices)]
        and sources [(source, only in roundups)].
        `kinds`/`own_sites`: each source's kind and publication; `accounts`: each source's platform account (its
        posts at another account's address are reposts); `mirrors`: tweet hosts; `keys`: only these keys;
        `selves`: each source's own names (no voice under one, nor Saved's); `platforms`: find_platforms'."""
        selves = selves or {}
        ids = sorted(kinds)
        # its hash tables and sorts fit in memory with this (4 MB spilled to disk); this transaction only
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
        """The hosts the data finds platforms (discover_rules.find_platforms), each with the path its owners sit
        under, from every kept link grouped in SQL. The groups are streamed a host at a time (discover_rules.
        host_platform; 0283: holding all ~280k at once was ~270 MB of the Discover job's peak on the server's copy).
        Streamed rather than through a named cursor: Postgres plans a cursor without parallel workers (+2.5 s there)."""
        from insight_core.utils.url_normalization import TWEET_SHAPE as shape
        ids = sorted(kinds)
        cur.execute("SET LOCAL work_mem = '%s'" % WORK_MEM)
        rows = cur.stream(_PLATFORMS + " ORDER BY host",
                          {"ids": ids, "kinds": [kinds[i] for i in ids], "sites": [own_sites.get(i, "") for i in ids],
                           "selves": [" ".join(sorted(selves.get(i, ()))) for i in ids], "tweet": shape,
                           "depth": OWNER_DEPTH, "listed": sorted(DISCOVER_PLATFORMS),
                           "under": ["%." + host for host in sorted(DISCOVER_PLATFORMS)],
                           "min_voices": DISCOVER_MIN_VOICES}, size=PLATFORM_ROWS)
        out: Dict[str, Tuple[str, ...]] = {}
        for host, group in groupby(rows, key=lambda row: row[0]):
            prefix = host_platform((tuple(segs), n, voices) for _, segs, n, voices in group)
            if prefix is not None:
                out[host] = prefix
        return out

    @staticmethod
    def activity(cur: Cursor, keys: Iterable[str], platforms: Platforms = {}, *, since: Optional[datetime] = None
                 ) -> Dict[str, Tuple[Optional[datetime], int, int, int]]:
        """Each key's last link, the linking posts you opened or read, and the linking sources that first did after
        `since` and before (none counted without `since`)."""
        cur.execute(_ACTIVITY, {"rules": address_stamp(platforms), "keys": sorted(keys),
                                "since": since or datetime.max.replace(tzinfo=timezone.utc)})
        return {key: (last, int(opened or 0), int(new) if since else 0, int(old) if since else 0)
                for key, last, opened, new, old in cur.fetchall()}

    @staticmethod
    def read_sources(cur: Cursor, since: datetime) -> Set[str]:
        """The sources you read since `since`: a post of theirs opened, read in a session or marked read."""
        cur.execute("""SELECT DISTINCT p.source_id::text FROM post_interactions i JOIN posts p ON p.id = i.post_id
                        WHERE i.interaction_type IN ('opened', 'reading_session', 'opened_source') AND i.created_at > %(since)s
                       UNION
                       SELECT DISTINCT p.source_id::text FROM post_reader_state rs JOIN posts p ON p.id = rs.post_id
                        WHERE rs.read_at > %(since)s""", {"since": since})
        return {r[0] for r in cur.fetchall()}

    @staticmethod
    def repos(cur: Cursor, *, kinds: Dict[str, str], own_sites: Dict[str, str], selves: Dict[str, Iterable[str]],
              min_voices: int, shown: int) -> List[Dict[str, Any]]:
        """The code repositories `min_voices`+ of your voices link (_REPOS), unordered: [{repo, voices, sources,
        last_at, urls}]. Which are a repository's releases is markx/official.channel's."""
        ids = sorted(kinds)
        cur.execute(_REPOS, {"ids": ids, "kinds": [kinds[i] for i in ids], "sites": [own_sites.get(i, "") for i in ids],
                             "selves": [" ".join(sorted(selves.get(i, ()))) for i in ids], "min_voices": min_voices,
                             "shown": shown})
        return [{"repo": repo, "voices": list(voices), "sources": [s for s in sources if s], "last_at": last_at,
                 "urls": list(urls or [])} for repo, voices, sources, last_at, urls in cur.fetchall()]

    @staticmethod
    def mirrors(cur: Cursor, kept: Optional[Dict[str, Any]]) -> Tuple[List[str], Optional[str]]:
        """The hosts where tweets are found by shape (TWEET_HREF), and the newest post read: `kept`'s, plus those
        found in posts read since."""
        hosts = set(kept["mirrors"]) if kept else set()
        cur.execute(_MIRRORS, {"tweet": TWEET_HREF, "since": kept["scanned_to"] if kept else None})
        found, scanned_to = cur.fetchone()
        return sorted(hosts | set(found)), scanned_to.isoformat() if scanned_to else None

    @staticmethod
    def gifted(cur: Cursor, urls: Sequence[str]) -> set:
        """Of these addresses, the ones a post links by an access or gift token (post_links.shared_url)."""
        if not urls:
            return set()
        from insight_core.utils.originals_rules import tokened
        cur.execute("SELECT DISTINCT target_url, shared_url FROM post_links WHERE target_url = ANY(%s) AND shared_url IS NOT NULL",
                    (list(urls),))
        return {url for url, shared in cur.fetchall() if tokened(shared)}

    @staticmethod
    def kept(cur: Cursor, *, found: bool = True) -> Optional[Dict[str, Any]]:
        """Discover's last counts: {stamp, found, mirrors, scanned_to, ...}, or None. Without `found`, all but the
        found rows (a few KB of ~11 MB; 0283: they cost the recount, which never reads them, ~50 MB); `kept_found`
        reads them when wanted."""
        if found:
            row = SystemSettingsRepository.get(cur, KEPT_KEY)
            return row[0] if row else None
        cur.execute("SELECT value - 'found' FROM system_settings WHERE key = %s", (KEPT_KEY,))
        row = cur.fetchone()
        return row[0] if row else None

    @staticmethod
    def kept_found(cur: Cursor) -> List[Dict[str, Any]]:
        """The found rows of Discover's last counts (`kept`'s), [] when none are kept."""
        cur.execute("SELECT value->'found' FROM system_settings WHERE key = %s", (KEPT_KEY,))
        row = cur.fetchone()
        return (row[0] if row else None) or []

    @staticmethod
    def keep(cur: Cursor, kept: Dict[str, Any]) -> None:
        SystemSettingsRepository.upsert(cur, KEPT_KEY, kept)

    @staticmethod
    def kept_list(cur: Cursor, made_from: str) -> Optional[Dict[str, Any]]:
        """Discover's last list when it was made from `made_from` (its inputs and code), else None."""
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
        """(made_from, built_at) of the answer Discover serves, without the answer, or None."""
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
        """(the served answer with only suggestions offset..offset+limit, how many it holds), sliced in Postgres so
        an open reads its page, not the whole answer. None before the first build."""
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
    def served_outline(cur: Cursor) -> Optional[Dict[str, Any]]:
        """The built served answer as Discover's reads choose from it, projected in Postgres (0283: the whole answer,
        ~10 MB of JSON and ~75 MB of objects on the server's copy, was read for this on every run): {built_at,
        suggestions: [{at (its place in the answer), key and what discover_rules.order and to_read rank by: score,
        fit, follow_test's label, last_days, voices (truthy or not), reader_fit}], apart: {kind: {rows: [{key}]}},
        archives (whole: a few rows)}. None before the first build. `served_rows` reads chosen rows whole."""
        cur.execute("""WITH v AS MATERIALIZED (SELECT value->'answer' AS a FROM system_settings
                                                WHERE key = %s AND value->'answer' ? 'built_at')
                       SELECT a->>'built_at',
                              (SELECT COALESCE(jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                                          'at', n - 1, 'key', s->'key', 'score', s->'score', 'fit', s->'fit',
                                          'follow_test', CASE WHEN jsonb_typeof(s->'follow_test') = 'object'
                                                              THEN jsonb_build_object('label', s->'follow_test'->'label') END,
                                          'last_days', s->'last_days', 'reader_fit', s->'reader_fit',
                                          'voices', CASE WHEN jsonb_typeof(s->'voices') IN ('array', 'object')
                                                         THEN to_jsonb(s->'voices' NOT IN ('[]'::jsonb, '{}'::jsonb))
                                                         ELSE s->'voices' END)) ORDER BY n), '[]'::jsonb)
                                 FROM jsonb_array_elements(COALESCE(a->'suggestions', '[]'::jsonb)) WITH ORDINALITY e(s, n)),
                              (SELECT COALESCE(jsonb_object_agg(kind, jsonb_build_object('rows', (
                                          SELECT COALESCE(jsonb_agg(jsonb_build_object('key', r->'key')), '[]'::jsonb)
                                            FROM jsonb_array_elements(COALESCE(got->'rows', '[]'::jsonb)) r))), '{}'::jsonb)
                                 FROM jsonb_each(CASE WHEN jsonb_typeof(a->'apart') = 'object' THEN a->'apart'
                                                      ELSE '{}'::jsonb END) k(kind, got)),
                              COALESCE(a->'archives', '[]'::jsonb)
                         FROM v""", (SERVED_KEY,))
        row = cur.fetchone()
        if not row:
            return None
        return {"built_at": row[0], "suggestions": row[1], "apart": row[2], "archives": row[3]}

    @staticmethod
    def served_rows(cur: Cursor, built_at: str, at: Sequence[int]) -> Optional[Dict[int, Dict[str, Any]]]:
        """The served answer's suggestions at these places (`served_outline`'s `at`), whole; None when the answer
        served is no longer the one built at `built_at`."""
        if not at:
            return {}
        cur.execute("""WITH v AS MATERIALIZED (SELECT value->'answer' AS a FROM system_settings
                                                WHERE key = %s AND value->'answer'->>'built_at' = %s)
                       SELECT i, a->'suggestions'->i FROM v, unnest(%s::int[]) i""",
                    (SERVED_KEY, built_at, sorted(set(at))))
        got = {int(i): s for i, s in cur.fetchall() if isinstance(s, dict)}
        return got if len(got) == len(set(at)) else None

    @staticmethod
    def keep_served(cur: Cursor, made_from: str, built_at: str, answer: Dict[str, Any]) -> None:
        SystemSettingsRepository.upsert(cur, SERVED_KEY, {"made_from": made_from, "built_at": built_at, "answer": answer})

    @staticmethod
    def archive_states(cur: Cursor, missing: Dict[str, Sequence[str]]) -> Dict[str, Dict[str, Any]]:
        """Each source's archive as stored, for the sources missing these pages: {state: running | paused |
        finished | None, found (pages stored since), pages_fetched, stored_urls, newest, prefix, host}. Running:
        its newest archive job runs or waits; paused: that job paused; finished: its checkpoint is completed."""
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
            # a waiting archive still runs: it continues by itself
            state = ("running" if status in ("running", "waiting") else "paused" if paused is True
                     else "finished" if sid in done else None)
            out[sid] = {"state": state, "found": len(stored[sid]),
                        **({"pages_fetched": pages} if isinstance(pages, int) else {}),
                        "stored_urls": sorted(stored[sid]), "newest": newest.get(sid), "prefix": prefixes.get(sid),
                        "host": hosts.get(sid)}   # the host a page watch reads
        return out

    @staticmethod
    def reads(cur: Cursor) -> Dict[str, Any]:
        """What Discover read of the web (services/discover_reads.py): {follow: {key: {label, at}}, titles:
        {address: {title, at}}}."""
        row = SystemSettingsRepository.get(cur, READS_KEY)
        return (row[0] if row else None) or {}

    @staticmethod
    def read_titles(cur: Cursor, urls: Sequence[str]) -> Dict[str, str]:
        """The page titles read of these addresses, except one 2+ pages of its host share (its site's name:
        page_titles.shared_titles)."""
        from insight_core.services import page_titles
        reads = DiscoverRepository.reads(cur).get("titles", {})
        shared = page_titles.shared_titles(reads)
        return {url: title for url in urls if (title := page_titles.read(reads, url, shared))}

    @staticmethod
    def keep_reads(cur: Cursor, reads: Dict[str, Any]) -> None:
        SystemSettingsRepository.upsert(cur, READS_KEY, reads)

    @staticmethod
    def video_channels(cur: Cursor, reads: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        """Each video address whose channel Discover read (services/discover_reads.read_video), and that channel's
        key (youtube.com/@<handle>)."""
        videos = (DiscoverRepository.reads(cur) if reads is None else reads).get("videos") or {}
        return {url: v["channel"] for url, v in videos.items() if isinstance(v, dict) and v.get("channel")}

    @staticmethod
    def linked_videos(cur: Cursor) -> List[Tuple[str, int]]:
        """The video addresses kept links point to, each with how many sources link it, most first: the order
        their channels are read in."""
        cur.execute("SELECT pl.target_url, " + voice_keys.count_sql("p.source_id") + " FROM post_links pl JOIN posts p ON p.id = pl.post_id "
                    "WHERE " + read_sql("pl") + " AND pl.target_url LIKE %s AND " + suggestable_sql("p.source_id") + " "
                    "GROUP BY 1 ORDER BY 2 DESC, 1", (VIDEO_LIKE,))
        return [(url, int(n)) for url, n in cur.fetchall()]

    @staticmethod
    def map_videos(cur: Cursor, channels: Dict[str, str]) -> List[str]:
        """Key these videos' addresses by their channels in discover_addresses, whatever rules wrote them. Returns
        the addresses moved."""
        moved = []
        for url, key in sorted(channels.items()):
            cur.execute("UPDATE discover_addresses SET key = %s, site = 'youtube.com', platform = true, article = true "
                        "WHERE url = %s AND key IS DISTINCT FROM %s", (key, url, key))
            if cur.rowcount:
                moved.append(url)
        return moved

    @staticmethod
    def base(cur: Cursor) -> str:
        """What the counts are counted by, a story run aside: the rules (while they hold, a story run counts again
        only the keys its posts link). Round-up tags are apart (`retagged`)."""
        what = [_COUNTS, _COUNT_RULES, ADDRESS_RULES]
        return hashlib.sha1(json.dumps(what).encode()).hexdigest()[:16]

    @staticmethod
    def tags(cur: Cursor) -> str:
        """The round-up tags the counts read (units.tags_stamp), kept with them."""
        return units.tags_stamp(cur)

    @staticmethod
    def retagged(cur: Cursor, kept: Optional[Dict[str, Any]], tags: str) -> Optional[Set[str]]:
        """The posts whose round-up tag moved since the kept counts were made: none when `tags` is the kept stamp,
        else those tagged then or now but not both (TAGGED_KEY); None when not known. Only the keys these posts
        link can move (`keys_linked_by`), so a tag change needs no full count."""
        if not kept or "tags" not in kept:
            return None
        if kept["tags"] == tags:
            return set()
        row = SystemSettingsRepository.get(cur, TAGGED_KEY)
        was = row[0] if row else None
        if not was or was.get("stamp") != kept["tags"]:
            return None
        return set(was["posts"]) ^ set(units.tagged(cur))

    @staticmethod
    def keep_tagged(cur: Cursor, tags: str) -> None:
        """The tagged posts the kept counts were made with (`retagged` reads them), written when they moved."""
        cur.execute("SELECT value->>'stamp' FROM system_settings WHERE key = %s", (TAGGED_KEY,))
        row = cur.fetchone()
        if not row or row[0] != tags:
            SystemSettingsRepository.upsert(cur, TAGGED_KEY, {"stamp": tags, "posts": units.tagged(cur)})

    @staticmethod
    def keys_linked_by(cur: Cursor, post_ids: Iterable[str], platforms: Platforms = {}) -> Set[str]:
        """The Discover keys these posts link or are at (a platform account's repost counts as a link): every key a
        post's round-up tag counts in."""
        ids = sorted(post_ids)
        if not ids:
            return set()
        cur.execute("""SELECT target_url FROM post_links WHERE post_id = ANY(%(ids)s::uuid[]) AND """ + read_sql() + """
                       UNION SELECT COALESCE(normalized_url, url) FROM posts WHERE id = ANY(%(ids)s::uuid[])""",
                    {"ids": ids})
        return DiscoverRepository.keys_of(cur, [r[0] for r in cur.fetchall() if r[0]], platforms)

    @staticmethod
    def stamp(cur: Cursor, facts: Any) -> str:
        """What the counts are counted from: the rules (the counting query as written and the addresses'), the
        last story run and `facts` of the sources with posts. Same stamp, same counts."""
        cur.execute(f"SELECT {DISCOVER_AT} FROM system_settings WHERE key = 'stories'")
        row = cur.fetchone()
        what = json.dumps([DiscoverRepository.base(cur), row[0] if row else None, facts])
        return hashlib.sha1(what.encode()).hexdigest()[:16]

    @staticmethod
    def story_origins(cur: Cursor, *, kinds: Dict[str, str], own_sites: Dict[str, str]) -> List[Origin]:
        """Where each story of ORIGIN_MIN_VOICES+ voices starts: its outside page, else its origin post's address,
        with its voices (named as Discover names them) and its title (origin_title, else post_title)."""
        cur.execute(_ORIGINS, {"min_voices": ORIGIN_MIN_VOICES})
        # only voices of sources not switched off count: a story left under the bar starts nothing Discover
        # suggests; a story with none keeps the story job's count
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
        """Each site's hosts your kept links point to, and the posts linking it: {site: (hosts, posts)}."""
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
        """Each website voice and the source it is named after: its only website source, else the one whose kept
        links come first in post order."""
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


SUPPLIERS_KEY = "originals_suppliers"   # kept by OriginalsService.keep_suppliers (ingestion)


def light_facts(cur: Cursor) -> Any:
    """The sources' facts from the sources table alone (names, own sites, followed sites), no posts read: cheap
    enough for every Discover open (the full SourceFacts reads posts)."""
    from insight_core.db.repo_stories import SourceFacts, switched_off
    cur.execute("SELECT id, platform, handle_or_url, COALESCE(NULLIF(btrim(settings->>'display_name'), ''), handle_or_url) "
                "FROM sources")
    rows = cur.fetchall()
    return SourceFacts.of(rows, [], off=switched_off(cur))


def entity_pages(cur: Cursor, db_url: str, now: datetime, *, hidden: Set[str], names: Any,
                 skip: Set[str]) -> List[Dict[str, Any]]:
    """Discover -> Pages: Mark X entities' originals not stored whose entity meets Collect originals' trigger
    (2+ voices in 7 days, or a News lead): {url, title, site, hide_key, video, tweet, first_linked_at, voices,
    readable, stories, entity: {id, name}, voice_names}. `names`: source id -> name; `skip`: addresses already
    a row."""
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
    """As OriginalsService.keep_suppliers kept them: {current: {key: {n, urls, since}}, suggested: {key: at}}."""
    row = SystemSettingsRepository.get(cur, SUPPLIERS_KEY)
    return (row[0] if row else None) or {}


def longread_citations(cur: Cursor) -> Dict[str, Dict[str, int]]:
    """As OriginalsService.keep_cited kept it: {key: {n: citations, posts: long-reads}}."""
    row = SystemSettingsRepository.get(cur, "longread_citations")
    return (row[0] if row else None) or {}


def supplied_first(cur: Cursor, suggested: Dict[str, str], *, facts: Any) -> List[Dict[str, Any]]:
    """Each source you followed at a site Discover suggested, after it was suggested, and how many originals it
    brought before any other source of yours (shown, not used to rank): [{key, source_id, name, followed_at,
    originals_first}]."""
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
    """The source a voice is named after: a website the source of its first kept link (`site_namers`), a source
    voice its own; a Reddit author none."""
    source_id = voice_keys.source_of(voice)
    return source_id if source_id is not None else site_namers.get(voice)


__all__ = ["DiscoverRepository", "ADDRESS_RULES", "read_sql"]
