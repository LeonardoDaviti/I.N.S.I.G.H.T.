# 0244 — v10.26: data and CPU, ranked, the safe fixes built

Status: built on the v10.26 branch (not merged, not pushed). Migration 0161. Measured on synthetic data in a scratch
test database (`insight_a298_synth_test`, made from the migrated test template, dropped after); nothing measured on
real data (the real-data copy was busy with another check). What real data must still measure is at the end.

## Where the numbers come from
- **S16**: the server's `/api/status` table sizes, 2026-11-16 (0216's table: bytes on disk, rows estimated).
- **M19**: the server export of 2026-11-19 (`manifest.json` row counts; the zip's file list: each table's CSV bytes,
  a measure of its data without indexes, TOAST compression or bloat). The server's DB is 17 GB on disk.
- **0226 / 0231 / 0215 / 0216 / 0243**: those issues' measurements (server or server-shaped clones).
- **SYN**: this issue's synthetic database (shape below).

## The ranking: bytes
| # | what | bytes | source | lever |
|---|---|---|---|---|
| 1 | `mx_tasks` (1.90M rows; 12 indexes) | 3,823 MB; CSV 4.25 GB | S16, M19 | ~90% is answered tasks' `input`. `tasks.spend` (0233, migration 0159) is built but not on the server (it is at 0155): est. 2.0-2.6 GB back after the owner's one `VACUUM FULL mx_tasks` (DEPLOYMENT.md). Biggest single item; nothing more to build. |
| 2 | `posts` (162k) | 3,769 MB; CSV 4.34 GB (~27 kB a post: text, HTML, tsvector) | S16, M19 | the reader's data: kept. |
| 3 | `mx_entity_vectors` (359k) | 1,936 MB at 329k | S16, M19 | ~2.1 kB vector in TOAST + ~2.7 kB of HNSW a row (0216). The index serves `identity.vector_neighbours` (kept, 0216). A partial index over live entities changes which neighbours are found: measure first (below). |
| 4 | `mx_calls` (1.56M) | 946 MB at 1.33M; CSV 1.04 GB | S16, M19 | the stored answers (referenced by ~20 tables: kept). **0161 drops `mx_calls_created_idx`** (a duplicate). |
| 5 | `mx_embeddings` (162k) | 909 MB at 148k, ~0.5 GB after 0149's HNSW drop | S16, 0216 | read by the windows' cosines: kept. |
| 6 | `story_keys` (2.27M) | 565 MB; CSV 214 MB | S16, M19 | 2.6x its data: the rule-change rebuilds rewrote it (bloat suspected, not measured). |
| 7 | `post_refs` (1.39M) | CSV 506 MB | M19 | a btree on (post, md5) and a hash index on the address: both read (graph, refs). |
| 8 | `mx_units` (638k) | CSV 387 MB, plus a GIN on `links` | M19 | GIN read by units.py. |
| 9 | `mx_mentions` (1.98M; 7 indexes) | CSV 375 MB | M19 | **0161 drops `mx_mentions_family_version_idx`** (no reader). |
| 10 | `system_settings` (a few dozen keys) | CSV 29.6 MB | M19 | whole JSON values (Discover's list, reads, tagged posts...) rewritten on each upsert: WAL and TOAST churn. Which keys and how often: measure first. |

## The ranking: CPU
| # | what | seconds | source |
|---|---|---|---|
| 1 | the decision run's graph stage | 41-514 s a run (514.0 s at 12:28 on 11-19; the next run's 430.6 s failed the 120 s limit) | 0226, 0237 #30 |
| 2 | the entities stage | 119 s (server, 11-19); the pool's indexes 12.2 s CPU every run (#10) | 0226 |
| 3 | the story job, a regrouping slice | 235 s, 580 MB (server); a wanted run 39.7 s, CPU 30.5 s (clone) | 0231 |
| 4 | the full decision run's reading | 92-93 s (server, a deploy's first run) | 0215 |
| 5 | hourly ingestion after the fetch | 132-388 s a run | 0216 |
| 6 | Discover's build | 12.3 s, CPU 5.1 s (clone); ~20 s at server size | 0231, 0243 |
| 7 | the real-data check's invariants | 2,255 s -> 111 s (fixed) | 0243 |

## 1. The graph stage's relation scope: mention rows x stated edges (CPU #1)
**Cause.** `graph._relation_scope`'s first query (0220, measured as #16 by 0226's counts but never at size) kept a
post when `EXISTS (SELECT 1 FROM mx_connections x WHERE ... AND x.evidence->'posts' ? m.post_id::text)`. Inside an
OR the EXISTS cannot become a join: EXPLAIN shows a SubPlan, a sequential scan of mx_connections (no index answers
`?` on evidence) for **every mention row** of the calls since the last stage less MARGIN (1 h). Its cost is mention
rows x connections: 16-18 ms a mention row on SYN, so a normal run (~660 rows) pays ~11 s and a run after a burst of
answers (a backlog, ent-v5 reading again) pays minutes.
**Changed (markx/graph.py, the module that owns the scope).** The current stated edges' evidence posts are read once
as a hashed `IN (SELECT jsonb_array_elements_text(evidence->'posts') ...)`: one scan of the edges, then a hash probe a
mention row. The same posts: `?` on the posts array is true exactly when the post's id is one of its string elements
(evidence posts are always an array of ids, `_evidence`; the stage's merged-posts query already reads them so).
**SYN, before -> after** (each the same set of posts; the before at 300 posts once, it takes minutes):

| window since | mention rows | before | after |
|---|---|---|---|
| 10 posts | 125 | 3.1 s | 0.38 s |
| 53 posts (a 75-minute window at ~1,000 posts a day) | 663 | 10.7 s | 0.28 s |
| 300 posts | 3,750 | 66.9 s | 0.40 s |
| 1,000 / 5,000 / 20,000 posts | 12.5k / 62.5k / 250k | (linear, ~18 ms a row: ~3.7 / 18 / 74 min) | 0.39 / 0.41 / 0.66 s |

**Server estimate.** ~185k connections there (M19) against SYN's 160k: about the same per row. The 430-514 s stages
of 11-19 fit ~25k mention rows since (~2,000 posts answered within the window, e.g. read again by ent-v5) in this one query; after: under a
second. To confirm with the stage's own `graph.timing.relations` and `relations.scope.since_seconds` (0226) once
v10.25+ runs on the server.
**Tests.** `test_markx_timeline.ThingLinks.test_the_scope_finds_a_read_again_post_by_the_edges_it_is_evidence_of`
(new; it and `test_stated_relations_become_edges_with_their_posts` fail with the evidence branch removed), the rest of
test_markx_timeline and test_markx_graph.

## 2. Migration 0161: three indexes nothing needs (bytes #4, #9; WAL)
- `mx_calls_created_idx` = mx_calls (created_at); `mx_calls_totals_idx` = (created_at) INCLUDE (...): the same key, so
  every scan of the first the second does (SYN's planner already picks the totals index for `created_at >=`).
- `mx_mentions_family_version_idx` = mx_mentions (family, version): no statement in the code, the views or the SQL
  functions filters, joins or orders mx_mentions by `family` (it is only selected: identity.py, surges.py).
- `job_runs_started_at_idx` duplicates `job_runs_started_idx` (both started_at DESC). A small table (logs, pruned).

SYN, the same rows inserted into a copy of each table with and without the index:

| | with | without |
|---|---|---|
| 500k mentions inserted: WAL | 271 MB | 221 MB (-18%) |
| 162k calls inserted: WAL | 82 MB | 69 MB (-16%) |
| `mx_calls_created_idx`, 162k calls | 6.4 MB | - |
| `mx_mentions_family_version_idx`, 2.0M mentions (20% with a family) | 15 MB | - |

**Server estimate.** `mx_calls_created_idx` ~60 MB at 1.56M calls (SYN's 40 B a call); the mentions index 15-60 MB
(how many mentions have a family is not known here). Every mention and call insert writes 16-18% less WAL. Plain DROPs
(milliseconds, a short exclusive lock), in a transaction like every migration.
**Tests.** test_migrate_runner, test_markx_storage, test_db_statements, test_markx_kept_counts, test_export,
test_markx_entities, test_markx_api, test_markx_jobs.

## SYN's shape
162k posts 85 s apart (160 days), one ent-v5 entities task, call and mention set a post (3% of answers stating a
relation), 2.0M mentions (12-13 a post, 360k entities, 8% models, 20% with a family), 160k connections (40k current
stated entity edges citing 1-3 posts, 120k author-link edges), 1.39M post refs (8-11 a post), 27k redirects. Row
counts of M19; the split of mx_connections by rule is a guess (the export's CSVs were not read).

## Not built, and why
- **mx_tasks beyond spend**: `input_hash` is 64 hex characters in the heap and in `mx_tasks_once` (~1.9M x 65 B
  twice, ~250 MB). As bytea it would be half; every hash reader and the ON CONFLICT arbiter change. Worth it only
  after spend and the VACUUM FULL, measured.
- **Superseded calls** (`answer` of a call whose task was answered again): readers take the first valid call in some
  places and the latest in others, so "superseded" is not one thing; an owner question (keep everything).
- **system_settings**: an upsert that skips an unchanged value would stop `updated_at` moving, which some readers use
  (Discover's reads stamp). Which keys cost what must be measured first.
- **The graph stage's other steps**: `stale_links` (0.34 s on SYN), `dirty_posts`' post_refs scan (0.07 s),
  `next_version_edges` (every version entity each run; not shaped in SYN). Measure with `graph.timing` first.

## To measure on real data (the integrator, after the current check; read-only statements)
On the server-shaped copy, `psql -X`:
```sql
-- A. bytes by table and index, and the indexes never scanned (stats on the copy start at the restore: run the
--    index part on the server's GET /api/operations/db-statements `indexes` instead, which keeps the server's scans)
SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) total, pg_size_pretty(pg_relation_size(oid)) heap
  FROM pg_class WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace ORDER BY pg_total_relation_size(oid) DESC LIMIT 25;
SELECT indexrelid::regclass, pg_size_pretty(pg_relation_size(indexrelid)) FROM pg_stat_user_indexes
 ORDER BY pg_relation_size(indexrelid) DESC LIMIT 40;
-- B. mx_tasks' inputs by kind (what spend gives back) and what stays
SELECT kind, count(*), pg_size_pretty(sum(pg_column_size(input))) FROM mx_tasks GROUP BY kind ORDER BY sum(pg_column_size(input)) DESC;
-- C. story_keys' bloat (pgstattuple: CREATE EXTENSION needs the owner's say on the copy; else compare with a count)
SELECT pg_size_pretty(pg_relation_size('story_keys')), count(*), pg_size_pretty(count(*) * 80) AS packed_estimate FROM story_keys;
-- D. system_settings: the big keys
SELECT key, pg_size_pretty(pg_column_size(value)::bigint), octet_length(value::text), updated_at
  FROM system_settings ORDER BY pg_column_size(value) DESC LIMIT 15;
-- E. the entity vectors of entities no longer live (the share a partial HNSW would drop)
SELECT count(*) FILTER (WHERE r.from_id IS NOT NULL OR e.status = 'not_entity'), count(*)
  FROM mx_entity_vectors v JOIN mx_entities e ON e.id = v.entity_id
  LEFT JOIN mx_entity_redirects r ON r.from_id = v.entity_id AND r.undone_at IS NULL;
-- F. the mentions index 0161 drops, and its share with a family
SELECT pg_size_pretty(pg_relation_size('mx_mentions_family_version_idx')), count(*) FILTER (WHERE family IS NOT NULL), count(*) FROM mx_mentions;
-- G. mx_connections by rule (the relation scope's edges)
SELECT rule, a_kind, valid_to IS NULL AS current, count(*) FROM mx_connections GROUP BY 1, 2, 3 ORDER BY 4 DESC;
```
And the relation scope itself, base and head, read-only (`graph._relation_scope(cur, since)` for since = the
copy's newest call less 1 h, 24 h and 7 days, in a transaction rolled back): seconds and the same set of posts.
`scripts/realdata-check.sh` covers the rest (the migration, the decision run with the graph stage, the invariants).

## Risks
- A future query by `mx_mentions.family` has no index (add it with its reader).
- The relation scope now reads every current stated edge's posts once a run (one scan of mx_connections, ~0.3 s on
  SYN): flat, but paid even when no mention row is new.
