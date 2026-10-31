"""Discover's counts in the database (issue 0062): the sites and accounts your sources keep linking,
grouped and counted in one query, so the API never holds the 138k kept links in memory (it did:
2.6-3.3 s and ~800 MB on the server's data).

It is story_rules.suggestions (the reference, kept as a pure function) in SQL, over every kept link
(`post_links`, not boilerplate):
- an address's key, site and platform (story_rules.discover_address) and whether it reads like an
  article (post_links.is_article) depend on the address alone: `discover_addresses` keeps them,
  each worked out once in Python (fill_addresses), by the story job after it reads links, or by
  Discover itself for an address it finds missing;
- a key is a candidate with 2+ article-like addresses that are 40%+ of its addresses, unless you
  follow it or hid it (story_rules.discover_open): this needs the addresses only;
- only the candidates' links are then read for their voices (StoryPost.voice: `site:<own site>`
  for a website, `reddit:<author>` for a Reddit post whose feed names its author, else
  `source:<source id>`), and a candidate with 3+ voices is kept.
The query returns only the kept keys: their counts, voices, top articles with the voices linking
each and the words they are most often linked by. Python orders them and names the voices.

Issue 0065: a post on a platform is an article of its account (story_rules.discover_article: a
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
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from psycopg import Cursor

from insight_core.utils.post_links import ACCOUNT_NAMESPACES, ARTICLE, REDDIT_AUTHOR
from insight_core.utils.story_rules import (DISCOVER_ARTICLE_SHARE, DISCOVER_MIN_ARTICLES, DISCOVER_MIN_VOICES,
                                            DISCOVER_PLATFORMS, NOT_ACCOUNT, ORIGIN_MIN_VOICES, PLATFORM_POST, TWEET,
                                            Origin, discover_address, discover_article)

# Which rules wrote a discover_addresses row. Bump ADDRESS_RULES_VERSION when discover_address,
# site_of, account_key or discover_article change in a way the constants below don't show.
ADDRESS_RULES_VERSION = 2
ADDRESS_RULES = hashlib.sha1(repr((ADDRESS_RULES_VERSION, sorted(DISCOVER_PLATFORMS), sorted(NOT_ACCOUNT),
                                   sorted(ACCOUNT_NAMESPACES), ARTICLE.pattern, TWEET.pattern,
                                   PLATFORM_POST.pattern)).encode()).hexdigest()[:12]
LOCK_KEY = "insight.discover_addresses"
WORK_MEM = "48MB"

_COUNTS = """
WITH src AS (
    SELECT * FROM unnest(%(ids)s::uuid[], %(kinds)s::text[], %(sites)s::text[], %(accounts)s::text[])
        AS s(id, kind, own_site, account)
),
reposted AS MATERIALIZED (        -- a post of a platform account at another account's address (a repost):
    SELECT p.id AS post_id, p.url COLLATE "C" AS url, d.key COLLATE "C" AS key, d.article,   -- a link to it (0065)
           d.url IS NULL AS unknown
    FROM (SELECT id, source_id, COALESCE(normalized_url, url) AS url FROM posts) p
    JOIN src s ON s.id = p.source_id AND s.account <> ''
    LEFT JOIN discover_addresses d ON d.url = p.url AND d.rules = %(rules)s
    WHERE d.url IS NULL OR (d.platform AND d.key <> s.account)
),
kept_url AS MATERIALIZED (        -- each address a kept link points to, and what Discover reads of it
    SELECT u.url, d.key COLLATE "C" AS key, d.site, d.platform, d.article, d.url IS NULL AS unknown
    FROM (SELECT target_url COLLATE "C" AS url FROM post_links WHERE NOT boilerplate
          UNION SELECT url FROM reposted WHERE NOT unknown) u
    LEFT JOIN discover_addresses d ON d.url = u.url AND d.rules = %(rules)s
),
unknown AS (SELECT (SELECT count(*) FROM kept_url WHERE unknown) + (SELECT count(*) FROM reposted WHERE unknown) AS n),
unfollowed AS MATERIALIZED (      -- those whose key you neither follow nor hid (discover_open)
    SELECT url, key, article FROM kept_url
    WHERE key IS NOT NULL AND CASE
        WHEN platform THEN NOT (key = ANY(%(followed_accounts)s) OR key = ANY(%(hidden)s))
        ELSE NOT (site = ANY(%(followed)s) OR key = ANY(%(hidden)s) OR site = ANY(%(hidden)s)) END
),
candidate AS MATERIALIZED (       -- keys with 2+ article-like addresses, 40%%+ of their addresses
    SELECT key, count(*) FILTER (WHERE article) AS articles, count(*) AS links,
           count(*) FILTER (WHERE url = ANY(%(classics)s)) AS classics
    FROM unfollowed GROUP BY key
    HAVING count(*) FILTER (WHERE article) >= %(min_articles)s
       AND count(*) FILTER (WHERE article) >= %(share)s::float8 * count(*)
),
linked AS MATERIALIZED (          -- the kept links to those keys' addresses
    SELECT u.key, u.url, u.article, pl.post_id, pl.position, pl.link_text AS text, p.source_id,
           COALESCE(s.kind, 'site') AS kind, COALESCE(s.own_site, '') AS own_site
    FROM unfollowed u JOIN post_links pl ON pl.target_url = u.url AND NOT pl.boilerplate
    JOIN posts p ON p.id = pl.post_id LEFT JOIN src s ON s.id = p.source_id
    WHERE u.key IN (SELECT key FROM candidate)
    UNION ALL                     -- and the reposts of them
    SELECT r.key, r.url, r.article, r.post_id, 0, NULL, p.source_id, COALESCE(s.kind, 'site'), COALESCE(s.own_site, '')
    FROM reposted r JOIN posts p ON p.id = r.post_id LEFT JOIN src s ON s.id = p.source_id
    WHERE NOT r.unknown AND r.key IN (SELECT key FROM candidate)
),
author AS MATERIALIZED (          -- a Reddit post's author, as its feed writes it, lowercase as Python's
    SELECT p.id, lower(substring(p.content_html FROM %(author_re)s) COLLATE "und-x-icu") AS author
    FROM posts p WHERE p.id IN (SELECT post_id FROM linked WHERE kind = 'reddit')
      AND strpos(p.content_html, %(author_mark)s) > 0
),
link AS MATERIALIZED (            -- with their voices (StoryPost.voice)
    SELECT l.key, l.url, l.article, l.post_id, l.position, l.text,
           (CASE WHEN l.kind = 'site' THEN 'site:' || l.own_site
                 WHEN l.kind = 'reddit' AND a.author IS NOT NULL THEN 'reddit:' || a.author
                 ELSE 'source:' || l.source_id::text END) COLLATE "C" AS voice
    FROM linked l LEFT JOIN author a ON a.id = l.post_id
),
heard AS MATERIALIZED (           -- who linked what: each address and voice once
    SELECT DISTINCT key, url, voice, article FROM link
),
counted AS MATERIALIZED (         -- and 3+ voices
    SELECT c.key, v.voices, c.articles, c.links, c.classics
    FROM candidate c
    JOIN (SELECT key, array_agg(voice) AS voices FROM (SELECT DISTINCT key, voice FROM heard) kv
          GROUP BY key HAVING count(*) >= %(min_voices)s) v USING (key)
),
shown AS MATERIALIZED (           -- each kept key's top articles: most voices first, then by address
    SELECT key, url, voices, r FROM (
        SELECT key, url, voices, row_number() OVER (PARTITION BY key ORDER BY cardinality(voices) DESC, url) AS r
        FROM (SELECT key, url, array_agg(voice) AS voices FROM heard
              WHERE article AND key IN (SELECT key FROM counted) GROUP BY key, url) per_url
    ) ranked WHERE r <= %(shown)s
),
title AS MATERIALIZED (           -- an article's words most often linked by; on a tie, the first read
    SELECT DISTINCT ON (url) url, text
    FROM (SELECT url, text, post_id, position, count(*) OVER (PARTITION BY url, text) AS n FROM link
          WHERE text <> '' AND url IN (SELECT url FROM shown)) t
    ORDER BY url, n DESC, post_id, position
),
listed AS (
    SELECT s.key, json_agg(json_build_array(s.url, s.voices, t.text) ORDER BY s.r) AS articles
    FROM shown s LEFT JOIN title t USING (url) GROUP BY s.key
)
SELECT c.key, c.articles, c.links, c.classics, c.voices, COALESCE(l.articles, '[]'::json), (SELECT n FROM unknown)
FROM counted c LEFT JOIN listed l USING (key)
UNION ALL   -- the unknown count also when nothing is kept
SELECT NULL, NULL, NULL, NULL, NULL, NULL, (SELECT n FROM unknown)
"""

# A website voice is named after the source of its first kept link in post order; asked only for
# the sites more than one website source shares (the others have one source).
_SITE_NAMERS = """
SELECT DISTINCT ON (voice) voice, source_id FROM (
    SELECT 'site:' || s.own_site AS voice, p.source_id, min(p.id::text COLLATE "C") AS first
    FROM posts p JOIN unnest(%(ids)s::uuid[], %(sites)s::text[]) AS s(id, own_site) ON s.id = p.source_id
    WHERE EXISTS (SELECT 1 FROM post_links pl WHERE pl.post_id = p.id AND NOT pl.boilerplate)
    GROUP BY 1, 2
) per_source ORDER BY voice, first
"""

# Each story's root (0064): its outside page, else its one post with no parent and no reason.
_ORIGINS = """
SELECT s.id, COALESCE(s.origin_url, p.normalized_url, p.url), COALESCE(s.origin_title, p.title), p.source_id,
       s.first_at,
       (SELECT array_agg(DISTINCT sp.voice) FROM story_posts sp WHERE sp.story_id = s.id)
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
    def fill_addresses(cur: Cursor, post_sources: Iterable[str] = ()) -> int:
        """Work out the addresses kept links point to, and the posts of `post_sources` are at (the
        platform accounts' sources: a repost is at its original's address), that discover_addresses
        lacks (or holds by older rules), and drop the rows no kept link and no post points to.
        Returns how many it added. One writer at a time (a transaction lock): a second open waits,
        then finds nothing to add."""
        cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (LOCK_KEY,))
        cur.execute("DELETE FROM discover_addresses WHERE rules <> %s", (ADDRESS_RULES,))
        cur.execute("SELECT url FROM (SELECT target_url AS url FROM post_links WHERE NOT boilerplate "
                    "UNION SELECT COALESCE(normalized_url, url) FROM posts WHERE source_id = ANY(%s::uuid[])) a "
                    "WHERE url IS NOT NULL AND NOT EXISTS (SELECT 1 FROM discover_addresses d WHERE d.url = a.url)",
                    (sorted(post_sources),))
        urls = [r[0] for r in cur.fetchall()]
        if not urls:
            return 0
        with cur.copy("COPY discover_addresses (url, key, site, platform, article, rules) FROM STDIN") as copy:
            for url in urls:
                key, site, platform = discover_address(url)
                copy.write_row((url, key, site, platform, discover_article(url), ADDRESS_RULES))
        cur.execute("DELETE FROM discover_addresses d WHERE NOT EXISTS "
                    "(SELECT 1 FROM post_links pl WHERE pl.target_url = d.url AND NOT pl.boilerplate) "
                    "AND NOT EXISTS (SELECT 1 FROM posts p WHERE COALESCE(p.normalized_url, p.url) = d.url)")
        return len(urls)

    @staticmethod
    def counts(cur: Cursor, *, kinds: Dict[str, str], own_sites: Dict[str, str], accounts: Dict[str, str],
               followed: Iterable[str], followed_accounts: Iterable[str], hidden: Iterable[str],
               classic_urls: Iterable[str], shown: int) -> Tuple[List[Dict[str, Any]], int]:
        """The kept suggestions, unordered, and how many linked addresses discover_addresses lacks
        (when any, fill_addresses and ask again: those links were not counted). A suggestion: key,
        voices [(voice, the source naming it; None for a Reddit author)], article_count,
        link_count, classics and its `shown` top articles [(url, voices, title)].
        `kinds` and `own_sites`: each source's kind (source_kind) and own site (SourceFacts.own_site);
        `accounts`: the platform account of each source that follows one (SourceFacts.platform_accounts),
        whose posts at another account's address are reposts, counted as links to that address."""
        ids = sorted(kinds)
        # Its hash tables and sorts (~100k addresses) fit in memory with this; the default 4 MB
        # spilled them to disk. For this transaction only.
        cur.execute("SET LOCAL work_mem = '%s'" % WORK_MEM)
        cur.execute(_COUNTS, {
            "ids": ids, "kinds": [kinds[i] for i in ids], "sites": [own_sites.get(i, "") for i in ids],
            "accounts": [accounts.get(i, "") for i in ids],
            "author_re": REDDIT_AUTHOR.pattern, "author_mark": "submitted by",
            "rules": ADDRESS_RULES, "followed": sorted(followed), "followed_accounts": sorted(followed_accounts),
            "hidden": sorted(hidden), "classics": sorted(classic_urls),
            "min_voices": DISCOVER_MIN_VOICES, "min_articles": DISCOVER_MIN_ARTICLES, "share": DISCOVER_ARTICLE_SHARE,
            "shown": shown,
        })
        rows = cur.fetchall()
        unknown = int(rows[0][-1])   # on every row, and on the one row with no key
        found = [{
            "key": key, "article_count": int(articles), "link_count": int(links), "classics": int(classics),
            "voices": list(voices),
            "articles": [(url, list(url_voices), text) for url, url_voices, text in shown_articles],
        } for key, articles, links, classics, voices, shown_articles, _ in rows if key is not None]
        site_voices = {v for s in found for v in s["voices"] if v.startswith("site:")}
        namers = DiscoverRepository._site_namers(cur, kinds, own_sites, site_voices)
        for s in found:
            s["voices"] = [(voice, voice_source(voice, namers)) for voice in s["voices"]]
        return found, unknown

    @staticmethod
    def story_origins(cur: Cursor, *, kinds: Dict[str, str], own_sites: Dict[str, str]) -> List[Origin]:
        """Where each story of ORIGIN_MIN_VOICES+ voices starts (issue 0065): its outside page, else
        its origin post's address (a story whose tree is not drawn yet has none), with its voices,
        each named as Discover names it."""
        cur.execute(_ORIGINS, {"min_voices": ORIGIN_MIN_VOICES})
        rows = cur.fetchall()
        namers = DiscoverRepository._site_namers(
            cur, kinds, own_sites, {v for *_, voices in rows for v in voices if v.startswith("site:")})
        return [Origin(str(story_id), url, title, str(source_id) if source_id else None, first_at,
                       {v: voice_source(v, namers) or "" for v in voices})
                for story_id, url, title, source_id, first_at, voices in rows]

    @staticmethod
    def first_posts(cur: Cursor, source_ids: Iterable[str]) -> Dict[str, datetime]:
        """Each source's first post (published, else fetched): how far back it holds."""
        cur.execute("SELECT source_id, min(COALESCE(published_at, fetched_at)) FROM posts "
                    "WHERE source_id = ANY(%s::uuid[]) GROUP BY 1", (sorted(source_ids),))
        return {str(source_id): first for source_id, first in cur.fetchall() if first}

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
            if kind == "site" and "site:" + own_sites.get(source_id, "") in voices:
                by_site["site:" + own_sites.get(source_id, "")].append(source_id)
        namers = {voice: ids[0] for voice, ids in by_site.items() if len(ids) == 1}
        shared = sorted(i for ids in by_site.values() if len(ids) > 1 for i in ids)
        if shared:
            cur.execute(_SITE_NAMERS, {"ids": shared, "sites": [own_sites.get(i, "") for i in shared]})
            namers.update({voice: str(source_id) for voice, source_id in cur.fetchall()})
        return namers


def voice_source(voice: str, site_namers: Dict[str, str]) -> Optional[str]:
    """The source a voice is named after (SourceFacts.voice_name): a website the source of its
    first kept link (`site_namers`), a source voice its own; a Reddit author none."""
    if voice.startswith("source:"):
        return voice.split(":", 1)[1]
    return site_namers.get(voice)


__all__ = ["DiscoverRepository", "ADDRESS_RULES"]
