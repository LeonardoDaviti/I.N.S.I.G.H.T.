# 0198 — Pages that only change when a job runs: built by the job, served stored (v10.17.2)

Status: **built** (branch `v10171-stored-pages` from main 1890456 = v10.17, main d57aa11 = v10.17.1 merged in). Not merged, not pushed, not deployed.
Migration **0136** (main took 0135 for 0200).

## The problem (production, after deploying v10.17)

Time to first byte, gzip, measured from outside: `GET /api/markx/news` 4.5 s (1.66 MB raw, 336 KB gzip; `?all=1`
~5.7 s, 2.1 MB), re-measured here 4.82 s (338 KB gzip); `GET /api/markx/entities/{id}` for a big entity 5.6 s
(1.2 MB). 0186 already cut what each request reads (no whole-book read); what is left is the rows' own work, done
again on every load although the News page changes only when a decision run, a sectioning or placement, a label or a
headline answer changes what it reads, and an entity's page mostly with a run.

## What was built

One mechanism (`markx/kept_pages.py`, table `mx_kept_pages`), two owners deepened (news.py, entity_views.py); the
page code itself is untouched (one path: `news.page`, `entity_views.entity_page`).

1. **A kept page** is the route's own answer, as bytes (`kept_pages.encode`: FastAPI's jsonable_encoder and
   JSONResponse, so byte for byte what the route answered), with the **stamp of its inputs**: a sha256 of the code
   (every backend source file, read once a process: a deploy rebuilds every page) and of a few indexed reads the owning
   module names. A request reads the stamp again (milliseconds) and sends the kept bytes only when it is the same;
   otherwise it builds the page exactly as before. Nothing is held in a process between requests; the bytes are in
   Postgres (TOAST-compressed), read by primary key.
2. **Mark X News** (`news.page_inputs`, `kept_page`, `keep_pages`). Built by the jobs process, never by the API:
   - **One after-run step, a policy per view** (`jobs.KEPT_VIEWS`, `Runner._after_run`, was `_labels_after`). Each
     kept view is a `KeptView(job, missing(cur, now), when="always"|"wanted", between_runs=seconds|None)`:
     `KEPT_VIEWS = (KeptView("news", news.kept_missing, between_runs=60), KeptView("labels", labels.missing,
     when="wanted"))`. Right after each decision run, `kept_due(states, missing, now, gap, after_run=True)` lists the
     views to build and they are built one after the other in one process of their own (News, then the Labels queue),
     each with its own mx_jobs row (`news`: run, views built, bytes, build seconds, peak MB). `due()` takes
     `kept_missing` (was `labels_missing`) and asks the same `kept_due`: the first start after a deploy builds what is
     missing. "wanted" (0199, merged from v10.17.1): a view is built only when its job was wanted since its last build:
     the one mark `labels.ask` writes when a Labels page opens unkept (`jobs.want`: mx_jobs wanted_at, cleared when a
     build starts); `labels.missing` is "not kept for this code" again, the wanted check is the policy's alone.
   - **Both views** (`differences`, `all`), each `news.page` in the job's REPEATABLE READ snapshot (the stamp and the
     page read one snapshot), one row a view a run (`KEEP_RUNS` = 3 runs kept; a cache, pruned).
   - **Between runs** the stamp changes when a label (a News flag, a fold, an entity answer: any label), a sectioning
     or placement, a sections question waiting, a headline answer, Mark IX's News of the window, a merge, pin, an
     entity's sources/handles or fix lands. The runner sees it at its next look (every 30 s) and builds the views again,
     at most every `REBUILD_GAP` = 60 s; meanwhile the API builds the page as before (exact, today's speed). With
     decision runs at most every RUN_GAP = 15 min (0199), these between-run rebuilds are what keeps News current in
     between: at most 15 a run interval, each only when an input changed; a new run's views are built at once
     (`after_run`), whatever the gap.
   - **Rebuild, not overlay** (asked): an overlay of the flags, sections or headlines would parse the 1.7 MB kept page
     in the API and encode it again on every request (tens of MB of transient objects, against "no added memory"), and
     each overlay would be a second copy of how the page applies that input (a parallel path). A rebuild keeps
     `news.page` the one path; the window between a change and its rebuild (one look + one build) is served exact.
   - **The clock.** The page reads `now` only for its window (`NEWS_DAYS`) and its "last 48 hours first" order. The
     stamp counts the newest written run's rows inside each bound: the rows of a run are fixed and both bounds only move
     forward, so equal counts are the same rows in the same order; Mark IX's window is hashed (ids, voices, starts, its
     posts' rows), so its bound is exact too.
   - **The route** sends the kept bytes (`Response(media_type="application/json")`) or builds; it is a conditional GET
     (`routers/conditional.POLLED` gains `/api/markx/news`: weak ETag, 304 when unchanged).
3. **Entity pages** (`entity_views.page_inputs`, `kept_entity_page`). Built by the API at the first open, as before,
   then kept (key: the asked id and the page's parameters; `ENTITY_PAGES` = 300 newest built kept; one row an entity,
   the older run's replaced). The stamp: the newest run (stories, memberships, connections, surges, the book and the
   queue as the entities stage left them), the cluster's current mentions (count, newest set change), the offered old
   stories and their labels, Mark IX's story job's last pass, and the owner's changes (labels, merges and their
   undoing, pins, sources, handles, fixes). Its clock is the row's `until`: the next UTC day (surges by day, the day's
   offers) or the moment an old story becomes old enough to be offered, whichever is first. A page built while one of
   its inputs changed (the stamp read after the build differs, its own offers aside) is answered, not kept.
4. Migration **0136**: `mx_kept_pages` (page, key, run_id, stamp, body bytea, bytes, seconds, until, built_at; primary
   key (page, key, run_id)) and the job `news` in `mx_jobs_job_check`.

## What a kept page does not see until the next decision run

Stated, not hidden. A worker's answers other than headlines and the sections/placement questions (fold, check,
reading, entities answers) are read by the News page live today; with this change the News page shows them from the
decision run that each of them asks for (`api.post_answers` wants a run: SETTLE 60 s, at most one every RUN_GAP
15 min since 0199; one runs at least hourly): up to ~16 minutes later while a worker streams. Likewise an entity page shows new posts by its sources or citing its handles, and a
worker's answers on other entities (a version or a component newly named), from the next run. A post's title or a
source's name edited between runs shows from the next run. Each of these was chosen over a stamp that changes with
every worker answer (`mx_calls`): while a worker streams, that stamp would change every few seconds and nothing would
ever be sent kept. Adding a kind is one more read in `news.page_inputs` (its answered count), if the owner wants one
live.

## Proof

A scratch clone of `prep_mxreal` (real Mark X answers, 49k posts; never an original), migrated, one decision run of
this code at a pinned `now` (61 s, 228 MB peak): 7 runs with News, 126 rows, 8,843 entities.

- **News, in-process**: both views kept by `keep_pages` equal `kept_pages.encode(news.page(...))` byte for byte
  (`differences` 58 KB, `all` 430 KB at the pinned `now`); after `keep_pages` nothing is missing.
- **News, through the app** (ASGI, middleware included, the real clock): `GET /api/markx/news` and `?all=1` sent
  kept, then the kept rows deleted and the page built by the route: identical bytes (38 KB and 332 KB).
- **Entity pages**: 30 entities (the 15 most named and 15 by hash): the first open (built and kept), the second
  (kept) and a fresh `entity_page` build: all byte-identical, all 30 kept; through the app, the 3 most named: first
  and kept opens identical.
- **Invalidation** (tests below): a new run, a News flag, a sectioning, a placement, a headline answer, Mark IX's
  News, a merge (News); a new run, a label, a merge, a new mention, the clock edge (entity).
- **The server-scale copy** (`prep_scale`) has no decision rows; its first decision run is a full one. It was started
  (the copy refreshed to main, migrated) and stopped by the coordinator after 2 h 12 min at 35 GB RSS (the owner's
  machine): the slice v10.17.2 run-memory is fixing the full run's memory. Nothing of it was kept; the clone is
  dropped. The server-scale numbers below are estimates from the sizes measured here, 0186's scale copy and production.

## Numbers

Measured on the mxreal clone (this machine, shared with other agents' suites):

| | built (today's path) | kept |
|---|---|---|
| `GET /api/markx/news` through the app | 0.094 s | 0.0049 s |
| `GET /api/markx/news?all=1` through the app | 0.356 s | 0.0042 s |
| `GET /api/markx/entities/{id}`, the 3 most named (163 / 127 / 60 KB) | 0.44 / 0.19 / 0.15 s (first open) | 0.0044 / 0.0050 / 0.0035 s |
| 30 entity pages, in-process | median 0.083 s, max 0.16 s | median 0.0017 s, max 0.005 s |
| the News stamp (`page_inputs`) | | 1.6-2.3 ms |
| a kept News body of the server's sizes (1.72 MB / 2.15 MB, 457 KB / 572 KB TOASTed), `kept_page` | | 11.3 / 11.2 ms |
| the job "news" in a fresh process (both views) | | 1.2 s wall, 0.52 + 0.57 s builds, peak 72 MB |
| the runner's look (`Runner._missing`: both views' stamps and the Labels queue's) | | 22 ms |

**Production** (read-only, one GET): `GET /api/markx/news` 4.82 s to first byte (338 KB gzip), as the 4.5 s measured
after the v10.17 deploy.

**Estimate for the server** (its CPU ~2-3x slower; its tables larger: ~100k News rows over its runs, now read by
`last_written`'s index; a 30-day Mark IX window of ~1-2k posts, hashed; its labels, merges and pins counted):
- News, kept: the stamp ~5-20 ms + the body ~25-35 ms + the ETag's sha1 of 1.7 MB ~5 ms: **~40-80 ms to first byte**
  (was 4.5 s; `?all=1` was 5.7 s), and a 304 with no body when unchanged. Built (a changed input not yet rebuilt,
  the first start): as today.
- Entity page, kept (a second open within a run): the stamp (its cluster's mentions: up to ~25k rows for the most
  named) ~10-40 ms + the 1.2 MB body ~20-30 ms: **~50-100 ms** (was 5.6 s). The first open after each decision run:
  as today plus the stamp twice and one insert (~30-60 ms). Runs at most every 15 min (0199), so a page opened
  again within a run interval is sent kept.
- The job, per decision run: both views built once, ~4.5 + 5.7 s ≈ **10 s of CPU in the jobs process** (in its own
  process, after the run's process ended; never beside a run), peak about the page's own (0186: 74 MiB for the call
  on the scale copy) plus the process's imports (~70 MB here): **~150-250 MB**, below the Labels build's when both
  are built in one process (the peak is the larger, not the sum). Between runs, a rebuild only when an input changed,
  at most once a minute. Against it: every News load on the server is ~5 s of insight-api's CPU today.
- The runner's look every 30 s: ~22 ms here, ~50-100 ms on the server, in insight-ingestion's scheduler thread.
- Storage: News 3 runs x 2 views x ~1 MB TOASTed ≈ 3 MB; entity pages ≤ 300 rows, ~10-300 KB each TOASTed:
  ≤ ~30 MB.

## Tests

`test_markx_kept_pages` (15): both News views kept equal the built page byte for byte; the route sends the kept view
(the builder patched to fail), with an ETag, and builds when none is kept (the first start); a new run, a News flag, a
sectioning, a placement, a headline answer, Mark IX's News and a merge each make the kept view unsent until it is
built again, then equal again; the clock changes it only when a row crosses its 48 hours; another code's view is never
sent; only the newest KEEP_RUNS runs' views stay; the runner keeps the missing views at the first start, a label makes
them due again after REBUILD_GAP; `due` and `_kept_may`; an entity page built at the first open then sent kept (the
builder patched to fail), equal to a fresh build, the route's JSON as before and 404 as before; a new run, a label, a
merge, a new mention each build it again; its `until` and the ENTITY_PAGES bound; a page built while an input changed
is answered, not kept; the policies (News always, Labels when wanted) through `kept_due` and `due`. Updated:
test_markx_jobs and test_markx_labels (`kept_missing`; 0199's "nobody asked" is the policy's, read from the mark), test_conditional_get (the app's paths from its
OpenAPI: an included router's routes), test_markx_storage and test_markx_api (the new table).

The whole suite after the merge of main (v10.17.1): `JOBS=6 scripts/test-backend.sh`: 6 shards, 176 modules, 3,493
tests, OK.
