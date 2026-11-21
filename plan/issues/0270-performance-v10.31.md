# 0270 — Performance of v10.31: where production's time goes, and the first fixes

Status: **built in part** (Stealth v10.31.1), not deployed. No migration. Items 2, 4, 6-10 are measured and open.

## Measured on production (GET only, 2026-11-21, v10.31, from this machine; each URL timed twice, cold then warm)

| GET | cold s | warm s | bytes |
|---|---|---|---|
| /api/markx/entities/<Anthropic> (1,517 posts) | 13.06 | 11.41 | 2.5 MB |
| /api/markx/entities (the list) | 5.08 | 0.07 | 490 kB |
| /api/search?q=openai | 1.94 | 0.38 | 41 kB |
| /api/markx/overview | 1.24 | 0.38 | 92 kB |
| /api/news?scope=all (Mark IX News) | 0.88 | 0.73 | 110 kB |
| /api/markx/stories/<a 77 kB story> | 0.84 | 0.68 | 77 kB |
| /api/markx/stories/<a 17 kB story> | 0.35 | 0.36 | 17 kB |
| /api/classics?scope=all | 0.29 | 0.20 | 101 kB |
| /api/markx/tracks/counts (every page) | 0.28 | 0.26 | 551 B |
| /api/markx/tracks/<id> (all 5 tracks) | 0.03-0.07 | 0.03-0.07 | 124-586 kB |
| /api/markx/news?all=0 | 0.11 | 0.09 | 2.1 MB |
| /api/feed?limit=50, /feed/unread-counts, /sources, /folders, /posts/item/... | < 0.1 | | |

The track page itself is now fast (kept bytes, 0264); the 2.6-5 s seen earlier were live placements while change
rows were pending. A second agent timed the track's reading view, GET /api/feed?scope=folder:<track>: 1.3-1.4 s on
every track (item 11).

The owner's pg_stat_statements (production, v10.31) ranked the statements by blocks read; their numbers below are
from that, not from my GETs.

## Built (v10.31.1)

### 1. graph._relation_scope: every current mention joined to mx_calls, a run (112 calls, 15,753 s, 4.65B blocks)

Cause: the query starts from `mx_mentions_now` (all of mx_mentions joined to mx_mention_sets) and joins mx_calls by
`call_id`. mx_mentions has no index on call_id, so every run scans every mention, then tests each mention row
against its call's `answer->'relations'` (the call's answer is detoasted once a mention, not once a call) and the
hashed set of every stated edge's evidence posts. It grows with all mentions ever, not with the calls since.

Fix (markx/graph.py, the module that owns the scope): read from the calls since (their created_at index), their
tasks (primary key; a mention's post is its call's task's `a`: repo.add_mentions, ent42.after_cite, reading5),
and those posts' current mentions (the (post_id, guide, n) key), with the call's answer read once in a
materialized CTE; the stated edges' evidence posts are joined only to the posts since that state nothing. No index.

Measured locally (synthetic: 200k posts read, 200k calls with 12-entity answers, 1.6M mentions, 30k+ stated edges;
`since` windows as below; same rows checked by EXCEPT both ways):

| window | rows | before | after | same rows |
|---|---|---|---|---|
| 3 hours (a run: last run less MARGIN) | 126 | 136 ms, ~31k blocks (seq scan of mx_mentions) | 41 ms, ~6k blocks (index probes) | yes |
| 2 days | 1,673 | 223 ms | 132 ms | yes |
| 20 days | 13,673 | 345 ms | 612 ms | yes |

Locally it does not reproduce 140 s: production's plan differs (more mentions, larger answers, or a non-hashed
subplan). The new form scales with the calls since, not with all mentions, which removes the cause whatever the
plan was. **Confirm on the server** after deploy (pg_stat_statements below; the statement now begins
`WITH c AS MATERIALIZED (SELECT c.id, t.a AS post_id`).

Not changed, same shape, not in the owner's top list: graph._subject_scope, graph.py:738/818/1004 (backfill),
candidates.py:80, identity.py:2185 (`mx_mentions_now m JOIN mx_calls c ON c.id = m.call_id ... c.created_at >= `).
If they show up after this deploy, the same route (calls since -> tasks -> mentions) applies.

### 3. track_kept.refresh rewrote every kept row (2,086 calls, 85.6M rows of INSERT INTO mx_track_places)

Cause: each placement did `DELETE` every row of the track and `INSERT` them all again (~41k a refresh), while a
refresh changes a few: WAL, dead tuples, index churn and autovacuum on every refresh.

Fix (markx/track_kept.py, `write_places`; the refresh's gating, i.e. when a track is placed, is unchanged, owned by
the 0264 staleness work): one statement, one snapshot: the rows the placement makes, `DELETE` of the kept rows it no
longer makes, `INSERT ... ON CONFLICT DO UPDATE` of only the rows that are new or differ (found by a read: an
`ON CONFLICT ... DO UPDATE WHERE` alone still locks, and so writes, every unchanged row — measured, 5.9 MB WAL).

Measured locally (synthetic: one track of 41,000 judged items, its next placement moving the rank of 1%):

| | rows written | WAL | time |
|---|---|---|---|
| before (delete all + insert all) | 41,000 deleted + 41,000 inserted | 8.4 MB | 130 ms |
| after | 393 | 2.9 MB (full-page images of the 393 rows' pages) | 110 ms |

The time is the read of each item's newest verdict (the lateral join), unchanged. Test:
test_markx_tracks.KeptPlaces.test_placing_again_writes_only_the_rows_that_differ (no write when unchanged: same
ctid; a changed row written, a dropped post deleted; kept rows = live placement; the feed reads the kept set).

### 5. track_tools.rows returned every entity a track's posts name (6,229 calls, 63M rows; 4,326 s counting)

Cause: the tools panel (each track page build) and the tool finder asked for every entity the track's 13k-65k posts
name with the array of its posts, then Python dropped the non-tools and the one-post names; the "everywhere"
count (`count(DISTINCT post_id) ... WHERE entity_id = ANY(...)`) counted every one of them.

Fix (markx/track_tools.py): the tool kinds (the current fact's kind when entity facts are on, else the entity's
type; a generic fact is no tool) and the post minimum (`min_posts`: the panel's MIN_VOICES, the finder's
FINDER_MIN_VOICES; a tool's voices are never more than its posts) are the query's own conditions.

Measured locally (synthetic: 60k entities over the 1.6M mentions, half of them tool kinds — production has fewer
tools, so the cut there is larger; 27k track posts):

| | rows | post ids returned | first query | everywhere count |
|---|---|---|---|---|
| before | 51,611 | 218,031 | 1.35 s | 3.06 s |
| after | 18,784 | 104,644 | 1.70 s | 1.55 s |

The candidates the panel keeps: 18,784 = 18,784 (the same set).

### 11. The track's reading views placed the track live every request (GET /api/feed?scope=folder:<track>, 1.3-1.4 s)

Cause: track_feed.track_posts called tracks.placed (every judged item, 52k on one track) on each request.

Fix: `track_kept.posts_in(cur, track, places)` (the kept placement's posts in these places, None when not kept) —
track_kept.counts reads it too — and track_feed reads it, placing live only when the track is not kept. Not
re-measured locally; to confirm on the server after deploy (time the GET).

## Open (measured, not built)

2. `SELECT p.id, GREATEST(0, floor(extract(epoch FROM (COALESCE($now, now()) - <ordinary date>)) / 86400))::int ...`
   (1,361 calls ~3 s, 1.86B blocks; variants 2,934 and 725 calls): the planners' post scan — tasks.plan_posts
   (tasks.py:665), tasks.py:1240, embed.py:266, reading5.py:139, folds.py:187, ent42.py:294. With the owner's
   all-time reading window (`days` NULL) each call reads the whole posts heap (`unread`'s `posts q` subquery and
   the outer `posts p`), ~1.4M blocks a call. Needs its server plan before a fix: run on the server
   `EXPLAIN (ANALYZE, BUFFERS)` of one (the statement text from pg_stat_statements with its parameters filled).
   Likely fix: drive it from the index (posts_feed_order_idx is the ordinary date, id) and the tasks' (a, kind,
   guide) index with a keyset cursor kept per planner, so a call reads only posts newer than the last scan plus
   the changed ones.
4. Mentions with roundups (9,875 calls, 6,344 s): `SELECT m.post_id::text, m.guide, m.n, m.entity_id::text, m.role,
   COALESCE(((SELECT jsonb_object_agg(r_.post_id, r_.issue_at) FROM mx_roundups r_ ...`.
6. Track waiting/invalid counts (3,902 calls, 1,532 s): `WITH t AS (SELECT DISTINCT task_id FROM mx_track_items
   WHERE track_id = $1 UNION ...`.
7. Post + source lookups (321,878 calls, 28M rows): an N+1 (`SELECT p.id, s.platform, s.handle_or_url, ...`).
8. Nearest posts (17,293 calls, 30M rows): `mx_embeddings e, (SELECT v ...)` ordered by distance with no ANN limit.
9. mx_connections reads (921 calls, 1,096 s).
10. Per-source counts (123 calls, 441 s).
12. The entity page: GET /api/markx/entities/<Anthropic> 11-13 s, 2.5 MB (not in the statement list by blocks;
    profile next).

## The server's real top statements (the owner runs this)

```
docker exec insight-db psql -U insight -d insight -c "SELECT calls, round(total_exec_time/1000) AS total_s, round(mean_exec_time) AS mean_ms, rows, shared_blks_hit + shared_blks_read AS blocks, shared_blks_read AS from_disk, temp_blks_written AS temp, left(regexp_replace(query, '\s+', ' ', 'g'), 180) AS query FROM pg_stat_statements ORDER BY shared_blks_hit + shared_blks_read DESC LIMIT 25"
```

What to look for: after deploying v10.31.1, run `SELECT pg_stat_statements_reset();` once, wait a day, run the
query. `WITH c AS MATERIALIZED (SELECT c.id, t.a AS post_id` (item 1) should be far below a second and a few
thousand blocks a call; `WITH y AS MATERIALIZED` into mx_track_places (item 3) should write a few rows a call
(`rows`), not ~41k; the track_tools query (`array_agg(DISTINCT m.post_id::text)`) fewer rows a call. Order by
`total_exec_time` too (`ORDER BY total_exec_time DESC`) — a statement cheap per call but called 300k times (item 7)
ranks there, not by blocks. `rows / calls` large means rows sent to Python to count or group.

## Memory

No cache, no new structure kept in a process. Items 5 and 11 return fewer rows to Python (item 11 no longer builds a
live placement of every judged item a request); item 3 sends the same arrays as before. Peak RSS was not measured
here (the synthetic runs were SQL in the database); measure the api and jobs processes' RSS on the server after
deploy (Grafana) against the 0.9-1.6 GiB peaks of 2026-11-21.
