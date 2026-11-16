# 0215: The database's work, the rebuild's speed, the run after a stall (Stealth v10.20.1, v10.21)

Status: **v10.20.1 built** (branch `v10201` from main 85948b7a = v10.20): the decision run's catch-up limit and no
rebuild hold. No migration. **v10.21 part built** (branch `v1021-db`, v10.20.1 merged in): the rebuild ~4.5x faster,
its progress counted from the rows, each job's own peak memory, every statement planned for its values,
pg_stat_statements and its route. Migration **0146** (0145 left to the v10.21 entities branch). Not merged, not
pushed, not deployed.

## v10.20.1: a decision run always finishes

### The symptom (the server, read-only GETs, 2026-11-16, v10.20)

The decide job's record after the v10.20 deploy, every retry:

| run | candidates | load | questions and decisions | write | connections | graph | total | end |
|---|---|---|---|---|---|---|---|---|
| 09:22 | 4.1 | 0.1 | 92.0 | 0.3 | 8.7 | 16.1 | 121 s | over 120 s, stopped before back |
| 10:22 | 8.6 | 0.0 | 92.9 | 0.4 | 9.5 | 14.6 | 126 s | over 120 s, stopped before back; `skip_next` graph |

A rule-change rebuild was in progress, so each retry came an hour after the last start (0209's hold).

### Why "questions and decisions" takes 93 s: the run is a full one, every time

- A decision run is incremental only when the kept state (mx_inc_*) was left by the same code, config and guides
  (`decide.run`: `key` holds `incremental.code_stamp()`). v10.20 changed decide's modules, so the first run after the
  deploy is **full**: it reads every post and story of its window. 0204 measured that full reading at 47 s on the
  scale copy (quiet machine); the server, about 2x slower, takes 92-93 s. It is not the two days of answers.
- A run over LIMIT stops between stages and its one transaction rolls back (0112 Decided 12), **and with it the state
  the next run would start from** (0169: the state is saved in the run's transaction). So the next run is the same
  full run, over the limit again.
- `skip_next` (0188) defers one late stage after two stops in the same stage; the 93 s reading is not deferrable, so
  the runs after it (back, headlines, news, surges...) can still put it over. With backoff (10, 20, 40 min... up to
  6 h) and the rebuild's hourly hold, catching up took hours at best, and never if the skips never fit.

### The fix (markx/jobs.py owns the limit; decide.run says the kind)

- **`jobs.limit_for(kind, previous)`**, the one decision on a run's limit: CATCH_UP_LIMIT (600 s) for a **full run**
  (decide.run calls the new `on_kind` with "full" or "incremental" once it has read its state, before its reading) and
  for **the run after one that stopped over its limit** (the decide job's last record has `stopped_before`); else
  LIMIT (120 s). Recorded in the run's record (`limit`) and logged ("a full run, 600 s at most"; "the last one stopped
  over its limit; this one has 600 s").
  - Why not chunks that commit: the run is one REPEATABLE READ snapshot whose decisions, stories, News and kept state
    are written together (nothing half done); committing the reading in parts would make a run's output depend on
    where it was cut. A full run reads everything by design; it needs the time once, and the runs after it are
    incremental again.
  - 600 s is under HARD_LIMIT (900 s, the process is killed) with the entities stage's own 45 s apart.
  - The story window's step back (`story_window.room`) still measures a run against LIMIT, so a long full run never
    makes later runs bigger.
- **A rule-change rebuild holds no decision run** (`decision_hold`). 0121 held it until the rebuild's end; 0209 until
  an hour after the last start. Each rebuild batch commits whole, so the stories as stored are always one consistent
  set, and a run reads them in one snapshot; the next run decides again what later batches change. On the scale copy
  the rebuild's batches changed **0 stories** (only thread and keyed edges) for this rule change. The story job's
  lock (a batch, its seconds) still holds a run. The story job steps aside for a run that waited ten minutes, which
  can always start now (the 2026-11-14 deadlock needed a held run).

### Measured (scratch clone of prep_mxreal, base 85948b7a vs this branch, the runner's `Jobs.decide`, clock fixed)

prep_mxreal is the server's 5 Nov copy (49k posts, real answers): its full run is 37 s (16.7 s counted against the
limit, the entities stage's 20.4 s apart) and an incremental run 9-10 s. LIMIT was scaled to 12 s so that, as on the
server, a full run is over the limit and an incremental one under it.

| run | base: LIMIT 12 s | this branch: LIMIT 12 s, catch-up 60 s |
|---|---|---|
| 1 | full, stopped at 16 s before back (rolled back) | full, **finished** (40 s, limit 60) |
| 2 | full again, stopped at 14 s before back (graph skipped next) | incremental, finished in 10 s (limit 12) |
| 3 | full again, finished only with graph skipped (27 s) | incremental, finished in 9.7 s |

On the server the base's runs 2 and 3 come after a 10- and 20-minute backoff (an hour with the rebuild's hold), and
the skip helps only if the rest fits. Peak RSS of the runs: 167 MB either way.

### Tests

- test_markx_jobs: `test_a_full_run_and_the_run_after_a_stop_have_the_catch_up_limit` (the server's stage times: a
  full run finishes in 136 s of its 600; an incremental one stops at 121 s before back; the next has 600; then 120
  again), `test_the_limit_for_a_run`; the skip tests now run with `catch_up=120` (what they test is past both limits);
  `TheRebuildHold` and the runner's rebuild tests rewritten for no hold (`test_a_decision_run_goes_ahead_during_a_rule_
  change_rebuild`, `test_the_2026_11_14_deadlock_ends`).
- test_stories (the story job steps aside during its rebuild too), test_system_health (held only by the lock).
- The full suite once: `JOBS=6 scripts/test-backend.sh`: 6 shards, 185 modules, 3,602 tests, OK.
- `scripts/realdata-check.sh --base 85948b7a --head HEAD insight_lab`: **PASS**, 978 s; `story.identity` 0,
  `story.rebuild_identity` 0, `story.deploy_identity` 406 = the base's 406, `markx.ix_unchanged` 0, 0 News lead
  changes.

### On the server after the deploy

The first decision run is full (decide's code changed again): up to 600 s, then incremental runs every 15 minutes when
wanted, during the rebuild too. `/api/markx/overview` → `worker.jobs.decide.last.limit` shows 600 for that run.

## v10.21 (branch `v1021-db`)

How it was measured: scratch clones of `prep_scale` (148,152 posts, 744k post refs, 4,962 stories) migrated to main's
migrations and backfilled with main's code. Its stored rows are of older rules, so a rule change's rebuild is due:
the keys, threads and names steps were run once (80 s; `db0215_mid`, 148,152 `redo:` keys queued), and every
measurement below starts from a clone of that state. Each batch in its own transaction, as `advance` runs it; per
batch: wall seconds, statement seconds (a psycopg wrapper, by call site), Python CPU, and peak RSS (VmHWM, reset each
batch). The clock was fixed for the whole-rebuild runs (News's window). The machine was shared (load 5-35); the
4-batch figures are from the quietest runs. Scripts and logs: `plan/research/db-0215/` (private).

### 1. The rule-change rebuild: ~4.5x faster, the same rows

**Where the time went** (main's code, 4 batches under cProfile, 442 s): `NewsService.judge_names` **333 s (75%)**:
- `news_rules.name_surges` 284 s, of which 1.28 billion `dict.get` calls: with `named_by` (each name's posts by their
  stored keys) it looked up every title row against every judged name (`for p in rows: for name in only: p.id in
  named_by.get(name)`), ~100k titles x ~3k names a batch;
- `repo_news.titles_saying` 44 s: every titled post scanned with `LIKE ANY` (~10 s of statement time a batch).
- Every batch judged the names of its seeds' titles again and changed **0 surges**: a rebuild batch changes no title
  (the names step already judged every name by the new rules over the same titles).

The rest per batch: the neighbourhood's grouping (11 groupings of ~15k context posts: `page_aliases`, `_page_key`),
`load_posts` (3 statements a call, ~2.5 s), Classics and Discover's counts for the batch's links (~4 s).

**Fixed, each in its owner:**
- `news_rules.name_surges`: each judged name's posts looked up by id, in the rows' order (the same lists, so the same
  surges). Helps every story run, not only rebuilds.
- `stories_service._batch`: a rule change's batch passes no titles to News's name judgement (a post saved, changed or
  removed meanwhile is a batch of its own, which does).
- `REBUILD_BATCH` = 2,000 queued posts a rebuild batch (was STORY_BATCH's 1,000): the context a batch reads around its
  posts (~7x their number) is shared by more of them. 3,000 measured 5.3 s per 1,000 posts but 531-568 MB.
- Every pooled connection plans each statement for its own values (`plan_cache_mode=force_custom_plan`, see 5).
- Tried and not kept: `_page_key`'s cache at 2^18 (a 81% miss rate at 2^15) saved ~1 s a batch for +15-60 MB.

| scale copy, a rebuild batch | main | v10.21 |
|---|---|---|
| posts regrouped a batch | ~2,040 (1,000 queued) | ~4,000 (2,000 queued) |
| seconds a batch | 59-65 (one 96 under load) | 21-30 |
| **seconds per 1,000 posts** | **27.8** | **6.2** (8.6 at 1,000 queued) |
| statement seconds per 1,000 posts | ~9.3 | ~2.0 |
| Python CPU per 1,000 posts | ~20 | ~4.4 |
| peak RSS of a batch | 481-503 MB | 476-506 MB (384-441 at 1,000 queued) |
| a slice in the runner's child (jobs.Jobs.stories, 180 s budget) | 491 MB, ~4,300 posts | 494 MB, ~22,000 posts |

On the server (main: ~1,620 posts in a ~229 s slice, 120 s apart: 158k posts in 9-10 h), the same ratio gives about
**2 hours** for 158k posts (inferred, not measured on the server).

**The same rows:** the whole rebuild was run to the end on two clones of the same state, main's code and this
branch's, the clock fixed (main: 110 batches; v10.21: 57). Every table the job writes is the same (rows and an
order-free digest of every row): stories 4,962, story_posts 13,727, story_mentions 5,278, post_edges 15,452,
story_keys 1,716,739, news_stories 101, news_posts 376, news_surges 261, classics 3,948, discover_addresses 235,303,
post_links 533,808, the queue empty; the settings `stories`, `discover_list`, `discover_served` and `news_owners` the
same. `discover_counts` is the same as sets: in 240 of its 1,375 entries the voices come in another order (its SQL's
`array_agg(voice)` has no ORDER BY, so the order follows the plan; the served list, which sorts them, is the same).
Both runs' totals: 0 stories changed, 9,292 edges changed, 0 surges changed (this rule change moved edges only).
Under the shared machine's load (both at once, with other suites) the whole rebuild took 2,646 s of batches (v10.21) against 7,198 s (main).

### 2. The progress counter

`rebuild.done` was the posts at the rebuild's start less the `redo:` keys left. `redo_every_post` queues every post
at the names step, including those saved since the start, and a post saved meanwhile is a `post:` batch of its own,
so the server showed done -1,132 of 157,752.
Now `StoriesRepository.regrouped` counts from the rows, at the names step and after every batch: `total` = every post
now, `done` = those with no regroup waiting (no `redo:` or `post:` key of theirs queued). A post saved mid-rebuild
counts in both once its own batch ran; a removed one in neither. ~0.25 s at the start of the server-sized queue, less
as it empties. `test_a_rebuilds_progress_counts_what_is_regrouped_with_posts_saved_meanwhile` saves a post during the
keys step (the server's case: main's counter reads -1 there) and checks done = every post - waiting, never below 0,
only rising, and the rebuild ending with the late post regrouped.

### 4. The jobs' memory: the 1.4 GB was never a job's

Every job on the server recorded ~1,366-1,395 MB (`news`, `tracks`, `unread`, `official`, `stories` alike, to the
decimal). Each job runs in a process started with multiprocessing "spawn", and the record was `getrusage().ru_maxrss`.
Linux carries a process's high-water across exec: the child is first forked from insight-ingestion's scheduler, and
exec folds that fork's resident size into the child's ru_maxrss. So each job reported **the scheduler's** RSS.
Reproduced: a parent holding 1,213 MB, its spawned child's ru_maxrss 1,215 MB, its own VmHWM 16.8 MB.

`utils/peak.py` (new, the one place): `mb()` reads VmHWM (this address space's own peak, reset by exec), `reset()`
starts it again from the current RSS (`/proc/self/clear_refs`), so the kept views built one after the other in one
child each record their own (`jobs._job_main` resets before each job). Used by the kept views, the Labels queue, the
rebuild's slice, the decision run (now recorded), the official channels and the source stats.

Each job as `Runner.tick` runs it (spawned), its parent holding 1,300 MB like the server's scheduler:

| job (copy) | main records | own peak (VmHWM) | v10.21 records |
|---|---|---|---|
| unread (scale) | 1,338 MB | 59 MB | 59 MB |
| tracks (scale, 4 tracks, 47k judged items) | 1,341 MB | 95 MB | 97 MB |
| stories, a rebuild slice (scale) | 1,341 MB | 491 MB (main) / 494 MB (v10.21) | 494 MB |
| news (mxreal) | 1,337 MB | 72 MB | 72 MB |
| labels (mxreal) | 1,339 MB | 83 MB | 84 MB |
| decide (mxreal, a full run) | not recorded | 172 MB | 172 MB |

Every job is under 500 MB; nothing to cut in them. What holds ~1.4 GB is insight-ingestion's scheduler process
itself (the fetches run in it; the jobs and the story job in children). Not measured here: it needs a real day of
fetches. To read on the server: `docker exec insight-ingestion grep -E 'VmRSS|VmHWM' /proc/1/status` (or the
scheduler's pid), and whether a gc + `malloc_trim` after each tick (utils/idle_trim, 0202) gives it back.

### 5. The database's work: pg_stat_statements, its route, the top statements fixed

**On the server:** docker-compose.yml starts insight-db with `shared_preload_libraries=pg_stat_statements` (DML
only, 5,000 statements), migration 0146 creates the view (and leaves a Postgres without the extension as it is), and
`GET /api/operations/db-statements` (operations_service.top_statements) lists the top 20 by total time: the
normalized statement (values are `$n`), calls, total and mean ms, rows, blocks hit/read, temp blocks, share of all
statement time, since the last reset; `{"enabled": false, "reason"}` while the library isn't loaded. DEPLOYMENT.md,
"The database's top statements", says how it loads (the container is recreated by `./update` because its command
changed) and how to reset the counts.

**Locally, a replayed day.** A Postgres of my own with pg_stat_statements (`db0215-pgss`, pgvector:pg15), holding the
scale copy after its rebuild (148,152 posts, 251 sources with posts, settled stories). `replay.py`, 12 rounds (an
hour each of the server's day), each:
- ingestion: 60 sources fetched through `save_batch(live=True)`, each its 30 newest posts again and one new (a feed
  brings its last items at every fetch), then the source stats kept (as the runner does after a run);
- the story job after the fetch (`recompute_safely`);
- the jobs loop: 4 looks (`Runner(spawn=False).tick()`), the decision run, the candidate finder and official stubbed
  (a first decision run on the scale copy is a full 1.5 h one; official reads the web): the kept views;
- a reader's session over the API: the polls 4 times (unread counts, running, overview, markx/on, status), the feed
  twice, News, Mark X News, sources, folders, a search, the Mark X overview, 3 posts and their connected.
Counts reset before the replay; main (85948b7a) and this branch each on its own copy of the same state.

| the replayed day (12 rounds) | main | v10.21 |
|---|---|---|
| **statement time, all statements** | **347.6 s** | **209.0 s (-40%)** |
| statements run | 661,383 | 244,056 (-63%) |
| ingestion's wall time (720 fetches) | 451.6 s | 282.0 s |
| the posts upsert | 151.8 s, 22,014 calls, 6.9 ms | 17.2 s, 2,414 calls (the new and changed posts) |
| `UPDATE posts SET refs_scanned_at` | 14.8 s, 22,014 calls | gone (unchanged posts' refs not read again) |
| post_refs upserts | 2.0 s, 223,933 calls | gone with them |
| story job, jobs loop, API reads (wall) | 286.6 s, 8.2 s, 8.6 s | 289.8 s, 6.9 s, 9.5 s |

The top statements after the fixes: `repo_news.titles_saying` (40 s, 12 calls), the refs' signature passes (26 + 13
s, 12 calls each), the series pass's regex (16 s, 720 calls), post_refs' navigation flags (11 s), the story job's
links read (11 s). With a first version of the fix (the ON CONFLICT ... WHERE alone) the upsert still took 80.6 s:
an INSERT ... ON CONFLICT that updates nothing still locks the stored row (a write); the read first removed that.

**Fixed:**
- **A re-fetched post as stored is not written again** (`PostsRepository.upsert_post`, the save path every fetch
  takes): `ON CONFLICT (url) DO UPDATE SET ... WHERE` the row would change, the condition built from the same
  (column, value) pairs as the SET list (`_post_update_pairs`: one builder for the fast path, the recovery UPDATEs and
  the condition). Was: every item of every fetch rewrote its row (a new row version, its TOAST and indexes, its row
  triggers), re-parsed its parts, and read its links and refs again (`save_post_links`: a DELETE of its links, ~10
  post_refs upserts, an UPDATE of `refs_scanned_at`). Now `Saved.changed` False skips those; a post whose text, title,
  date, author, metadata, reposts... would change is written as before. `language_confidence` is cast to `real`, its
  column's type (compared as a double it always differed). `posts.updated_at` now moves only when the post changed
  (read by the post page's API only, shown nowhere). Test: `test_a_refetched_post_as_stored_is_not_written_again`
  (the same row version, links standing; the edited one written).
- **Every statement planned for its own values** (`db/database.py`: `plan_cache_mode=force_custom_plan` on every
  pooled connection). psycopg prepares a statement a connection runs 5 times; Postgres may then keep one generic plan,
  and the 74 optional filters (`%(ids)s IS NULL OR id = ANY(%(ids)s)`) cannot use an index in a plan made for any
  value. Measured on the scale copy: Discover's address fill (`repo_discover.fill_addresses`, every story batch) 47 ms
  planned for its 3,000 URLs, **4,224 ms** with the generic plan (a seq scan of post_links). Over 15 rebuild batches
  in one process, statement time -14% (123 -> 106 s); a long-lived process (the API, the scheduler) would hit it most.
  Test: every pooled connection shows `force_custom_plan`.

**Left, measured** (the next candidates, by total time in the replay after the fixes):
- `repo_news.titles_saying` (~3.3 s a story run): every titled post scanned with `lower(normalize(title, NFKC)) LIKE
  ANY(...)` for the names a fetch's new titles say. Exact by design (a name's surges read every title that says it);
  an index cannot serve it across posts and post_parts.
- `PostRefsRepository.mark_boilerplate`'s two signature passes (~2 s and ~1 s a run, after the refs of new posts are
  read): counts over every source's posts and refs.
- The series pass's regex over a source's HTML (`repo_series`, ~22 ms a source with a new post).
- The decision run's statements were not replayed here (stubbed); 0204 measured them by call site.

### 6. A deploy of one part's code no longer makes the whole decision run full

The kept decision state (mx_inc_*, 0169) was keyed by one sha256 of 16 modules' files: any change to any of them (a
deploy touching the story job, News' rules, a docstring of `decide.run`) made the next run full, a full reading of
the window (92-93 s on the server; with v10.20.1's catch-up limit it finishes, but every such deploy costs it).

Now `incremental` stamps each kept part by the code that makes it:
- `reading_stamp()` (READING_MODULES: decide, incremental, tasks, pairing, plan_marks, post_parts, post_links, voice,
  byline; `decide.run` and `decide.snapshot` cut out of decide's source by the AST: they run the stages and make
  nothing kept) is in the state's key, as the one stamp was: a change makes the next run full;
- `news_stamp()` (NEWS_MODULES: news, news_rules, story_rules, news_service, stories_service, repo_stories,
  repo_news) is kept with News' rows (`State.news["code"]`); other code makes that run's News in full (the 0177
  path, as when the source facts change), the reading incremental;
- `code_stamp()` (both) stays the Labels queue's.
The later stages keep no code-keyed state (each resumes from its own clock), so they need no stamp.

Measured on a prep_mxreal clone (the runner's `Jobs.decide`, clock fixed): two runs (full, incremental), then a
"deploy" (a comment appended to stories_service.py), two runs, then a full run with the kept state (its check):

| run after the deploy | main | v10.21 |
|---|---|---|
| kind | full | incremental, News full |
| questions and decisions | 3.5 s | 0.4 s |
| news stage | 1.0 s | 0.9 s |
| the full run's check of the state after it | same | same |

On the server's size the reading is 92-93 s full and ~1 s incremental. The v10.21 deploy itself still starts with a
full run (incremental.py is in the reading's code, and the stamps' definition changed). Tests:
`test_a_deploy_of_news_code_makes_news_full_and_the_reading_stays_incremental` (News "made" full, 0 texts read, a full
run of the snapshot writes nothing more), `test_the_readings_stamp_leaves_out_what_runs_the_stages`.

### 7. The large answers

On the server (read-only GETs): nginx already gzips every API answer (`gzip on`, application/json), and the polled
answers already carry an ETag with 304s (0195: the unread counts, Mark X News: a 304 in 45 ms). So:
- **Fields no page reads are no longer sent** (a read-only audit of the frontend's consumers and types: which fields
  each component, hook and helper reads):
  - `GET /api/sources`: `settings.archive` (the archive's checkpoint, smart plan, outcomes...: no page reads it from
    here; the source sheet asks `/api/archive/{id}/status`).
  - `GET /api/news` (`news_service.reader_view`, applied by the route; the service's answer is unchanged): each story
    post's url, source_id, published_at, platform and repost, the sources' `with`, News' `reports` and `score`, the
    rank's parts but `event` and `usable`.
  - `GET /api/markx/news` (`news.reader_view`, applied to the kept page and the route's build; `news.page` unchanged):
    each line's url, kind, role, Mark IX row index, fold rule/by/count and build joins; removed and gone posts' url,
    kind and mention details but its role; items' reports and score; surges' and Mark IX rows' ids (names and titles
    kept); the rank's coverage, score and parts the page doesn't show; the build's internals.
- **`/api/news` and `/api/sources` answer 304 when unchanged** (routers/conditional.py's list).
- Not done: storing the kept pages gzipped. nginx compresses the answer on the same host; the bytes on the wire are
  the same, and the kept rows are TOAST-compressed already.

Measured in process (main:app over ASGI, the prep_mxreal clone, median of 5 calls; gzip at nginx's level 1):

| route | raw bytes main -> v10.21 | gzip main -> v10.21 | ms main -> v10.21 |
|---|---|---|---|
| /api/markx/news | 310,067 -> 249,183 (-20%) | 67,929 -> 56,184 (-17%) | 202 -> 201 |
| /api/markx/news?all=1 | 424,738 -> 335,715 (-21%) | 90,290 -> 73,939 (-18%) | 268 -> 279 |
| /api/news | 212,239 -> 153,699 (-28%) | 57,770 -> 47,569 (-18%) | 125 -> 138 |
| /api/sources | 257,473 -> 123,878 (-52%) | 46,079 -> 24,890 (-46%) | 18 -> 13 |

(ms: the clone has no kept pages, so Mark X News is built per call; on the server it is kept: 88 ms, 45 ms as a 304.)
On the server's sizes (2.27 MB / 358 KB / 510 KB raw) the same fields are ~15-20%, ~22% and 61% of the answers.

### 8. Postgres settings for a small box

Measured, and none adopted:
- `jit=off` server-wide: every pooled connection already sets it (`db/database.py`, measured in 0188: JIT cost ~300 ms
  of a 370 ms Sources list); the server-wide setting would only reach the migrations and psql. No change to measure.
- lz4 TOAST compression for posts' text: 40,000 posts copied into a pglz and an lz4 table, the same rows, warm, twice
  in alternating order, on the real posts (prep_mxreal) and the scale copy: inserts 534-590 ms either way, sizes 243
  vs 242 MB (434 MB of text), reading every text back 455-497 ms either way. No measurable gain on this data.
- Autovacuum: after the replayed day the dead rows were few everywhere (posts 4,827 of its updates, the queues
  vacuumed 4-9 times by the defaults: story_queue, kept_input_changes, source_post_stats_changes). The replay doesn't
  exercise Mark X's worker traffic (leases and answers on mx_tasks, the kept pages rewritten every minute), where the
  server's churn is; with no measurement of it, nothing was tuned. To read on the server first:
  `SELECT relname, n_live_tup, n_dead_tup, last_autovacuum FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 15`
  (mx_tasks: 3.6 GB for 1.7M rows on the server's /api/status).
