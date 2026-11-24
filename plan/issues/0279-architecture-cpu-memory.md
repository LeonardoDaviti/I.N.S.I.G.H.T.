# 0279 — Architecture for CPU and memory: where production spends, the seams that stop the seven patterns

Status: **measured, guards and one deepening built** (Stealth v10.44, branch `architecture` from v1029), not pushed.
Method: the codebase-design vocabulary (module, interface, seam, depth, leverage, locality); every claim below is a
production measurement (GET only: the app's routes, Prometheus/cAdvisor) or a measurement on the test database,
named where it is used. The core metric is CPU seconds per hour and peak MB of the jobs process (insight-ingestion),
the API (insight-api) and the database (insight-db).

## 0. What production spends (2026-11-23)

### Containers (cAdvisor, CPU seconds an hour; 2 h steps over 48 h)

| | worker answering (21/14–22/08, 23/06, 23/12–) | worker idle (22/10–23/04) |
|---|---|---|
| insight-api | 160–500 | **22** |
| insight-ingestion (jobs) | 735–2,040 | 372–545 |
| insight-db | 1,090–1,490 | 399–514 |
| DB → API (network) | 1.2–3.3 MB/s | **0** |
| DB → jobs | 3.5–6.1 MB/s | 1.5–2.4 MB/s |

**The worker's answers drive ~95% of the API's CPU, ~2/3 of the database's and about half of the jobs'.** The
question for every module is therefore its cost per answer, not its cost per hour of clock.

Peak working set over 7 days: insight-ingestion **2,851 MB** (the brief's 1.5 GB is exceeded), insight-api
1,639 MB, insight-db 6,442 MB. Right after the v10.43 deploy (14:18–14:27, the data repairs running): API 1,052,
DB 3,331, jobs 4,132 CPU s/h.

### The jobs' last runs (production, 13:50–14:01, v10.41; `/api/markx/overview`)

| job | wall s | CPU s | peak MB | where |
|---|---|---|---|---|
| decide (incremental) | 124.3 | 61.5 | 757 | entities 47.9 s, questions and decisions 27.5, candidates 12.3, graph 10.6, connections 9.9, news 8.8 |
| stories (Mark IX) | 209.6 | 133.4 | 613 | a rule change's rebuild in progress: 15,702 of 168,258 posts regrouped |
| main_source | 61.1 | 39.0 | 330 | |
| entities (kept) | 50.8 | 34.8 | 405 | 20 hot entity pages 46.0 s (slowest 9.0 s), list 4.0 s |
| plan | 59.6 | 15.5 | 232 | |
| tracks (kept) | 11.5 | 14.4 | 225 | 5 track pages 0.85–4.1 s each |
| news (kept) | 18.0 | 13.5 | 204 | two views 8.9 + 8.0 s |
| discover | 29.7 | 11.6 | 665 | |

### The database's statements

pg_stat_statements since the server's start (11-16) mixes seven versions: its all-time top 20 covered only **48 s
of the 601 s** the database executed between 14:02 and 14:23 (two reads of the endpoint, differenced). v10.43's
`?since=start` (deployed 14:18) shows the present. Measured live from it and from two differenced reads:

| statement (owning module) | rate | cost |
|---|---|---|
| track_things `_member_reports` (the v10.43 repair `repair_track_rows`, one-off) | 9,349 calls/h, 99 ms | 923 s/h for ~20 min |
| track_things `_match` (per thing of a things answer, in POST /api/markx/answers) | 2,071 calls/h, 204 ms | 422 s/h |
| track_things `roots` (twice per thing of an answer, and per repaired row) | 32,974 calls/h, 4.8 ms | 157 s/h |
| tasks.load_posts (+ its post_links read) | 5,370 calls/h (14:02–14:23), **22,305 calls/h** (14:27–14:38) | 30–80 s/h; its links read returned 2.37 M rows in 21 min |
| plan_marks / tasks.plan_posts (post-age scan) | 10–50 calls/h, 1.5 s | 42–75 s/h |
| track footer (tracks.footer: a track's all-time cost) | 14 calls/h, 0.9 s | 13 s/h |
| track_tools "everywhere" count | 14 calls/h, 155 ms (620 ms all-time mean) | 2–29 s/h |
| unchanged.table_stamps (a full scan per table: post_links 191 ms, posts 48 ms, post_parts 39 ms, mx_readings 39 ms) | ~37 a table an hour | ~20 s/h, ×3 with parallel workers |

API routes (v10.43 `api_routes`, first 10 minutes after the deploy, two API processes): **POST /api/markx/answers
144 calls, mean 1.65 s and 2.60 s, max 20.9 s**; GET /api/markx/entities/{id} 12 calls, mean 2.4–4.6 s (built in
the request); GET /api/markx/work 184 calls, mean 110–124 ms, max 5.1–6.4 s. Settled (14:38–14:48, one API
process, worker answering): answers 2,935 calls/h at 93 ms mean (274 s/h), /work 445/h at 87 ms, GET /tracks/{id}
55/h at 1.26 s; the database 1,366 statement-s/h, of which track_things' `_match` 2,369 calls/h (152 s/h) and
`roots` 19,048 calls/h (72 s/h), both from the things answers: **~16% of the database's statement time**;
load_posts 12,075 calls/h (47 s/h) with its links read 12,197/h. CPU over the API process's life: DB 1,912, jobs
2,511, API 479 s/h.

### The entity pages, read twice 10 minutes apart (GET ?all=true, 12 most-listed entities)

At 14:11 3 of 12 were kept (0.2–0.4 s) and 9 built in the request (4.3–8.1 s). At 14:22, with no decision run in
between, 6 of 12 were built in the request again (4.6–8.1 s). All 12 bodies differed (the timeline, stories_total;
3 also stories): new mentions arrived. The jobs' entities job built all 20 hot pages at 14:10 (46 s) and again at
14:19 (74.5 s) for the **same** decision run (8feab7c9, finished 14:09:58), which `_hot_due` should have prevented:
a page stays due when its row of the run is gone or expiring; not explained from GET only (C4 shows the rows' rate).

## A. The module map: who owns the cost

Each module: its interface (what callers know), its measured cost, the patterns (1 recompute all, 2 heavy work at
request time, 3 N+1, 4 all history where a window matters, 5 invalidation too broad, 6 a lock over slow work,
7 whole datasets in memory).

| # | module | interface | measured cost | patterns |
|---|---|---|---|---|
| A1 | **decide** (decide.py, incremental.py, entity_stage.py, identity.py) | `decide.run(cur, now)` from jobs.Jobs.decide, one REPEATABLE READ snapshot | ~354 CPU s/h; a run 61.5 CPU s, 757 MB (1,252 MB on the 11-19 copy) | 1 (the entities stage's budgeted full pass takes its 45 s budget every run while unfinished: 47.9 of 124 s); 3 (C1 measured: reading5.pick, news_sections.title_rows, repo.task_for read once a story; a write per new row); 7 |
| A2 | **kept entity pages** (entity_views + kept_pages) | `kept_entity_page` (API), `keep_pages` (jobs), stamp = run + mentions + owner marks + samples | ~283 CPU s/h jobs; 4.3–8.1 s a request-time build | 1 (a 2 MB page with 920 events and 1,053 citing lines rebuilt whole for one mention; 260 kB shown); 2 (built in the request on a miss); 5 (the stamp has the mentions' count and newest set: it moves with every worker answer for a big entity) |
| A3 | **tracks** (tracks.page/keep_pages, track_kept, track_tools, track_brief, track_things) | `tracks.keep_pages` (jobs), `track_things.after_answer` (API, per answer) | ~213 CPU s/h jobs; answers 1.6–2.6 s mean in the API | 2 (apply_things in the answer request); 3 (`roots` twice a thing); 4 (`_match` reads every report of the kind per thing; the footer sums a track's all-time cost per build; the tool panel counts each tool over all history) |
| A4 | **planners** (tasks.PLANNERS, jobs.plan_background, api.work) | `tasks.PLANNERS[kind](cur, days=)`; the lease plans the fresh lane and read/entities/reading when < limit wait | ~103 CPU s/h jobs; the lease 110–124 ms mean, max 6.4 s, API 22 → 160–500 CPU s/h with the worker | 2 (the lease still plans); 4 (plan_posts' window scan 1.5 s); 3 (a statement or two per new task: measured trivial, 20k tasks/day) |
| A5 | **News kept view** (news.keep_pages, news.page) | `news.kept_page` (API), `keep_pages` (jobs) | ~98 CPU s/h; two views 17 s a build | 5 (built again on every input change between runs) |
| A6 | **Mark IX stories** (services/stories_service, db/repo_stories.load_posts) | `regroup` / rebuild slices in the jobs process | ~93 CPU s/h; 133 CPU s, 613 MB a slice; 2,354 MB peak on the copy | 1 (a rule change regroups all 168k posts, ~1 day); 7 (every post with its links in memory; 2.37 M link rows in 21 min) |
| A7 | **embeddings and pairing** (embed.py, pairing.py) | `embed.store`, `pairing.centroid_cosines` | lock waits 5.3 s mean (747 calls, 3,937 s since 11-16); centroids 3.6 s mean (1,071 calls); entity vectors insert 4.7–7.1 s | 4 (centroid N²); 6 (BUILD_LOCK held over the build) |
| A8 | **source_stats** | `load` → `compute` → `write` in a child process, nightly | 1.6 GB peak before its child process | 7 |
| A9 | **post loading** (tasks.load_posts, incremental.LazyTexts) | `load_posts(cur, ids)`: every Mark X reader of a post's text | 5,370–22,305 calls/h, ~44 posts a call | 3 |
| A10 | **change stamps** — six mechanisms: unchanged.py (table stamps, mx_table_changes), incremental.State (mx_inc_*), kept_pages stamps (+ kept_input_changes), plan_marks/mx_post_stamps, track_kept.due (REFRESH_GAP), kept_counts (deltas) | each consumer names its inputs its own way | unchanged's full-table scans ~20 s/h (×3 parallel); every kept view's breadth of invalidation (A2, A5) | 5, 1 |

## B. Deepening opportunities, ranked by measured saving ÷ effort

| rank | deepening (the seam) | measured basis | expected saving | effort |
|---|---|---|---|---|
| **B1** | **An answer does O(its own rows) in the request.** `tasks.record`'s per-kind hooks read what one answer needs once (the answer's view of its track, its post), never a track or entity whole; anything wider is marked dirty for the jobs. **First step built (D1): track_things' per-answer view `_Seen`.** | settled: `_match` 2,369 calls/h (152 s/h) + `roots` 19,048/h (72 s/h) = 224 of 1,366 DB statement-s/h; after the deploy answers 1.65 / 2.60 s mean, max 20.9 s | most of the 224 s/h (one plain read a kind an answer, one roots read; 3.7× faster answer on a 20k-report track, D1) | S (D1 done), M for the other kinds once C4 names them |
| **B2** | **A planner registry that is background-only by construction.** The lease only leases; `tasks.PLANNERS` runs in the jobs process (the fresh lane on a 30–60 s cadence there). C2's AST guard lists the lease as the one exception today. | API 22 CPU s/h idle vs 160–500 answering; DB → API 0 vs 1.2–3.3 MB/s; /work max 5.1–6.4 s | most of the API's worker-time CPU and its DB reads (≈ 0.1–0.4 core), moved to one jobs pass per minute instead of one per lease | M; **owner decision**: a new post's first read waits up to the jobs' next look (≤ 60 s) |
| **B3** | **One post loader.** `tasks.load_posts` the only reader of a post's text, with a per-transaction memo and a batch seam (`want(ids)` then `get`), so an N+1 cannot be written; incremental's prefetch reads ahead a page of each missing render (0277 item 3). First its caller tally in each job report (visibility). | 5,370 → 22,305 calls/h, ~44 posts a call, 30–80 s/h DB plus the links read (2.37 M rows/21 min) and the jobs' decode | ~half the calls (0277's estimate: renders that miss load their unchanged members one by one) | M |
| **B4** | **One derived-view module** (kept_pages deepened): build / keep / invalidate, background-only builds, stamps made of change-log counters (not volatile counts), a per-view report of rebuilds that produced the same bytes. | entity pages ~283 CPU s/h jobs, 4.3–8.1 s request builds, two hot builds for one run (46 s + 74.5 s); News 17 s a build | the request-time builds (API) and the second hot build a run; then rebuilds that change nothing | L; **owner decision**: send the kept page and rebuild behind it (a page may lag new mentions by one jobs look) instead of "never stale" |
| **B5** | **One change-tracking primitive**: mx_table_changes generalized (every input table logs its writing statements by kind), each consumer keeps a cursor (dirty set since its last pass); unchanged, kept_pages, track_kept and incremental read it. | six mechanisms (A10); full-table stamps 191 ms (post_links) ×~37/h, ×3 CPU with parallel workers | ~20–60 DB CPU s/h now; the breadth of invalidation of A2/A5 later | M–L |
| **B6** | **Windowed by default.** Mark IX regroups by window (a rule change replays a window, older posts lazily); the track footer reads kept totals (kept_counts' deltas); the tool panel reads a kept per-entity post count. | regroup ~1 day, 133 CPU s a slice, 2.35 GB peak; footer 0.32 s (synthetic 53k items) – 0.9 s; "everywhere" 155–620 ms with a sort spill | the regroup's day of jobs CPU after each rule change; ~15–40 DB s/h | M each |
| **B7** | **The entity page reads what it shows**: timeline, citing and works read their shown part plus counts (the `_short` cut moved into the build). | 2.0 MB built for 260 kB answered; builds 3–9 s | most of each build's DB time and Python | M |
| **B8** | **BUILD_LOCK over the decision only**, not the vectors' build. | 747 lock waits since 11-16, 5.3 s mean | the waits (not CPU) | S–M |

Not proposed (measured too small): batching a planner's task INSERTs (20k tasks a day ≈ 1,700 statements an hour);
the post-age scan's form (0277 built it; 1.5 s × 10–50 calls/h is the anti-join itself).

## C. Guards (built)

1. **Query-count budgets** (`tests/_query_budget.py`, `tests/test_query_budgets.py`): each key path runs over one
   world at two sizes and fails when code's statement count grows with the world, named by module:function.
   - News page build, entity page build (`EV._full`): 58 and 43 statements, flat from 3 to 6 stories.
   - Decision run (3 → 6 Mark IX stories): 313 → 374. Growth allowed only for writes of new rows (add_task with
     its guide read, add_story, open_membership, significance asks, handle refs) and four **known N+1 reads, listed
     to be removed**:
     `reading5.pick` (+3), `news_sections.title_rows` (+6), `repo.task_for` (+6), `incremental._last_run` (+1).
     Anything new, or these growing more, fails.
   - The post planners (read, entities, reading, cite, check): nothing grows but a new task's writes (≤ 3 a task).
   - A things answer (POST /api/markx/answers, 1 thing then 4): before D1 22 → 42 statements (`roots` +7,
     `_match` +3); after 24 → 35, only the things' own writes and reads grow.
   - The guard sees an N+1 (a test that writes one).
2. **Background only** (`tests/test_background_only.py`): every call of `tasks.PLANNERS` / `FRESH_PLANNERS` and of a
   kept-view build (`news` / `entity_views` / `tracks` `keep_pages`, `track_kept.refresh`) is in the jobs process
   (read from the source); the lease (`markx/api.py:work`) is the one listed exception until B2; every GET route
   over a seeded world plans nothing.
3. **Per-job budgets in the real-data check** (`checks/resources.py`): `plan`, `news`, `entities`, `tracks` measured
   in their own process beside decide/stories/discover, each with a peak-MB and CPU-s budget at about twice its last
   production run (plan 30 s / 400 MB, news 30 s / 400 MB, entities 70 s / 600 MB, tracks 30 s / 400 MB).
4. **Post-deploy comparison** (`scripts/compare-statements.py`, GET only): `save` reads
   `/api/operations/db-statements?since=start` with `api_routes` and each container's CPU over the same window from
   Prometheus; `compare before.json after.json` prints both per hour: all statements, CPU per container, each top
   statement and route. Run one save an hour after a deploy with the worker answering, and one before the next.

## D. Built: track_things reads its track once an answer (D1, deepening B1's first module)

`track_things.apply_things` (called by `tasks.record` inside POST /api/markx/answers) matched each thing of an
answer by reading every report of the thing's kind with a correlated count per row (`_match`, 204 ms on production),
recomputing every report's name, links and the kind's rare words in Python, and reading the track's roots twice
(`_match`, `remerge` → `reports`). Now one `_Seen` view per answer, inside the module (no interface change): the
roots once; each kind's reports once (a plain read, and one GROUP BY for those posts' thing counts instead of the
correlated subquery), each report's name and links computed once, the names' word counts kept for `rare_words`
(only the new name's words are asked: `same_identity` tests `shared & rare`, `shared` ⊆ the new name's words); all
kept equal to the database as the answer adds things and reports (all of one post). `remerge` / `reports` take the
held roots. Same joins: a test keeps the pre-0279 read as the reference and compares `_match` over 36 cases (3
posts × 12 values, links and none); the track tests (0245 briefer, rows, linked docs, search fields, numbers, entity
brief) pass unchanged.

| measured (test DB; the synthetic track ANALYZEd as autovacuum keeps production's) | before | after |
|---|---|---|
| statements, an answer of 1 thing / of 4 (C1) | 22 / 42 | 24 / 35 |
| track-wide reads, an answer of k things | 3k (roots twice, `_match` once a thing) | 1 + 2 a kind named |
| an answer of 4 things on a track of 2,000 reports | 0.354 s, 33 statements | **0.098 s**, 25 statements |
| ... of 20,000 reports | 4.098 s, 33 statements | **1.092 s**, 25 statements |

On production the reads it replaces were 224 DB statement-s/h settled (`_match` 152 + `roots` 72, §0); C4's
next save shows what is left (the route's time is not split by answer kind yet). Memory: the view holds, per kind the answer
names, the objects the old `_match` built for every thing (the kind's rows, each row's name and links), built once
and kept until the answer ends instead of rebuilt per thing: the peak is the old one's (plus a second link set for
the rows of a post that gave one thing, and of the answer's own post), held for one answer.

## E. v10.48: the jobs container's memory, split and cut (branch v1048-memory)

Production (2026-11-24): insight-ingestion 1–2.2 GiB (max 2.84); Discover's job 809 MB / 106 CPU s / 502 s.

1. **The split, readable (kept).** The scheduler's beat (every 30 s, a few /proc reads) carries `doing`: what its
   process runs now (`fetch (tick)`, `archives` with how many, `lane`, `markx <job>` and `source_stats` with the
   child's pid and its own rss/hwm/cpu). GET /api/operations/scheduler gains `process: {age_s, rss_mb, peak_mb,
   cpu_s, doing}`; /api/status' `checks.processes.scheduler` carries the same. The lane's mx_jobs record gains
   `rss_mb: [before, after, after the trim]` (GET /api/markx/status).
2. **Discover's job (kept).** Measured on the read-only server copy (11-19, 162k posts, 1.77 M mentions), the job as
   production runs it (build, the first page's work, the reads — web stubbed, 25 follow tests, 69 titles, 25 videos
   — then the rebuild), writes no-ops, the clock fixed, each run a fresh spawned process:

   | | peak MB | CPU s | wall s |
   |---|---|---|---|
   | main | 682 (653, 610 on earlier runs) | 20.7 | 36 |
   | v10.48 | **331** (340) | 21.1 | 37 |

   Where it went: Discover's "worlds" (rabbit_hole.discover_rows) asked which of ~100k roots a current reading names
   by reading every mention row of them (1.77 M rows: +255 MB peak, +120 MB held); `entity_views._names_now` now
   reads each named entity once (DISTINCT, pinned mentions excluded and counted for their pin as before): the
   worlds' peak 423 → 187 MB, CPU 5.7 → 5.1 s. The job's second build stacked on the first: the cached list
   (~145 MB) was held into the rebuild, and the served answer the first page's work reads lived through it;
   `refresh` now keeps no copy (the list is in the database; the jobs' next build always has new inputs), collects
   and trims before it builds, and `read_first_page` reads the served answer in a function of its own. The answer is
   byte-identical (the whole JSON, clock fixed). No cap on the re-tests: the memory was the builds, not the tests.
3. **The lane stays in the scheduler's process (measured, not moved).** On a test database at production's volumes
   (393 sources, 7 days × 660 posts of 5.8 kB, 6 links each; 1,000 tasks planned a pass, a 1,175-post burst once),
   20 passes in one process: a pass 0.12–0.3 CPU s (1.0 the first), grows the process 35–80 MB, and after the trim
   it holds 20–100 MB over its post-import size, reused by the next pass (83–165 MB, no growth over 20 passes, 87
   at the end). A spawned process a pass: 1.9–2.8 CPU s (its imports) and a 140 MB child each pass. At LANE_EVERY
   30 s that is ~240 CPU s/h against ~20–40 to save a bounded 20–100 MB; a long-lived lane process would pay its own
   ~60–100 MB of imports to save the same. Kept as it is; the trim moved into `Jobs.lane` so its record shows it.

## Owner decisions

1. **B2**: may the lease stop planning (a new post's first questions wait for the jobs' next look, ≤ 60 s)?
2. **B4**: may an entity page (and News) be sent as kept while the jobs rebuild it behind (lagging new mentions by
   one look, ~1–2 min), instead of being built in the request (4–8 s)?
3. **A1**: the entities stage spends its 45 s budget every run while a full pass is unfinished: keep, or run the full
   pass only at night?

## Next measurement (after this deploys)

`scripts/compare-statements.py save` one hour after the deploy with the worker answering: the answers route's
mean and the `_match`/`roots` rates against the table above; then B3's caller tally before changing the loader.

## Tests

- New: `test_query_budgets` (7: News page, entity page, decision run, post planners, a things answer, the guard
  sees an N+1, `_match` over the answer's view against the pre-0279 read), `test_background_only` (3).
- Module runs: the track tests (0245 briefer, rows v10.41, linked docs 0257, search fields v10.41, numbers 0272,
  entity brief 0261), `test_realdata_checks`, `test_background_only`, `test_query_budgets`: 98 OK.
- Full suite (6 shards, 4,240 tests), three runs: each failed one test, a different one each time, two outside this
  change's modules and paths (`test_markx_reading_windows` FreshLaneApi.test_an_entities_task_carries_its_post;
  `test_markx_pairing` DecisionRun round 2), each passing alone and repeated (pairing 3/3), neither in a shard with
  the new tests; the third, the decision-run budget here, counted the guide read of a new task (`get_setting`, read
  or not by what the process read before): allowed as a task write, then 3/3 OK.
