# 0206 — Kept pages, wave 2: the requests that still rebuilt per request (v10.18)

Status: **built** (branch `v1018-kept-more` from `v1018`). Not merged, not pushed, not deployed. Migration **0139**.

## The problem

0202 listed what insight-api still built on every open (or poll) from data that changes only when a job or a write
runs: the topic tracks' pages and suggestions (the largest: +95-105 MB and ~2 s for the four pages), the unread counts
(0.4-1.4 s on every 60 s poll), the sources' anatomy (0.65-0.8 s), Discover's main source (a copy in each API process;
17-20 s on the server when stale), Discover's suggested sources (rebuilt and tested over the web from the API process),
the entity queue (every unclosed row read to page 50) and the export (a 7.5 GB peak once recorded).

## What was built

One mechanism deepened (`markx/kept_pages.py`, table `mx_kept_pages`, the jobs process's `KEPT_VIEWS`); no cache in a
process, no parallel path: each page is still built by its owner's one function.

1. **kept_pages, wave 2.**
   - `NO_RUN`: a page of no decision run (its stamp alone says whether it stands).
   - **Kept inputs** (`changes`, `compact`; migration 0139): an exact, cheap stamp for pages whose inputs many writers
     write. A trigger logs one row per writing transaction and input (`kept_input_changes`, keyed by the input and
     the transaction id: writers never wait on each other; a transaction's later writes add nothing); an input's count
     is its base plus its logged rows, so any committed write moves it whatever order transactions commit in. The jobs
     process folds the log into the base (one statement an input; the counts stay as they were, no kept page is
     lost). Inputs: `posts` (insert, delete, an update of source, album, address, dates, story-only, duration,
     length), `reads` (read, Later, starred: not a scroll's resume position), `stories` (story members, originals,
     Classics), `parts`, `folders` (folders, their sources, a source added, removed, switched, readdressed or moved in
     or out of the main digest), `sources` (any write of a source, a fetch's own included).
   - `Inputs(strict, loose)` and the row's `until`: a page is sent while its strict stamp is the same and before its
     `until`; its loose part is stored (column `loose`, migration 0139) so the jobs process builds it again when it
     moved (`has(..., loose, until_after)`).
   - `kept_or_build`: the API's side; nothing kept: built as before, and kept when its stamp did not move during the
     build (either API process then sends it).
   - `newest`: the newest kept row whatever its stamp (for a list too long to build in a request).
2. **The jobs process** (`markx/jobs.py`): `KeptView` gains `markx` (False: a reader's view, kept with Mark X off too;
   the runner's loop now always starts, and runs only those views when Mark X is off; the "markx" heartbeat only while
   it is on). New views: `tracks` (always, at most every 120 s), `unread` (always, at most every 30 s),
   `main_source` (when wanted), `discover` (when wanted). One build helper (`Jobs._keep`: snapshot, record, peak MB,
   then the inputs folded). `mx_jobs_job_check` gains them (0139).
3. **Track pages and suggestions** (`markx/tracks.py`: `page_inputs`, `kept_page`, `kept_missing`, `keep_pages`,
   `shown_page` = the page with its bylines, the routes' one path). Strict: the tracks' topic and version, folder
   name, its sources (names, switched on/off), sub-topics, labels, probes, the switched-off sources. Loose: the
   placements (`mx_track_places_state`, `mx_track_changes`), the planner's statistics and history pass. `until` =
   built + `KEPT_LAG` (15 min). The job places changed tracks first (`track_kept.refresh`) then builds.
4. **Unread counts** (`services/reader_service.py`): kept per the inputs posts, reads, stories, parts, folders;
   counted by whichever comes first (a poll, or the job "unread"); a configured window (reads the clock) is counted
   on every request as before.
5. **Anatomy** (`SourceAnatomyService.anatomy_page`): kept `KEPT_FOR` = 10 min while no source was added, removed,
   switched or readdressed (the input `folders`); its `generated_at` says when it was made. Built by the API at the
   first open in 10 min (no job: opened rarely).
6. **Discover's main source** (`services/discover_main_source.py`): the per-process `_cache` and the background tests
   are gone. The kept unit is the scan (`found`, key `found@<code>`), stamped by the newest decision run and the
   sources as the list reads them, `until` = built + 10 min (the old cache's CACHE_SECONDS). The tests and the hidden
   rows are read with every answer (a Not interested shows at once). Not kept for its stamp: the newest kept is sent
   and the job `main_source` wanted (it scans, keeps, then tests the due channels over the web); nothing kept at all
   (the first open of a code): built here as before and kept. The answer gains `built_at`. The route is a plain def.
7. **Discover's suggested sources** (`StoriesService.discover_served`, `discover_reads.keep`): no copy of the 2.1 MB
   answer in each process, no rebuild and no web reads in the API (`discover_reads.start`/`running` removed). An open
   wants the job `discover` when the answer is due (as 0172's rule) or, on the first page, when the job last started
   over `READS_EVERY` (1 h) ago; the job rebuilds when due and runs `read_first_page` there. `refreshing` = the job
   wanted or running.
8. **Entity queue** (`entity_views.queue`): paged in SQL. The open items are read as (id, a, b) only (the named test
   counts every one), the page's rows read whole by id, the answered ones `LIMIT history` in SQL. Ties now ordered by
   id (they had no order).
9. **Export**: measured, not changed (below): it already streams with bounded memory.

## Before / after

Scratch clones only (`prep_scale` → `kmore_scale`, 148k posts, 4 topic tracks with ~11.8k judged items each;
`prep_mxreal` → `kmore_mx`, one decision run of this code made on it, then 12,800 open queue items seeded with
~2 KB evidence each, the server's size). One fresh API process per route (`main:app` through ASGI, compose's malloc
settings), n calls; "peak" = the process's VmHWM minus its RSS after the start (76 MB). Harness:
`plan/research/kept-more/` (private: `routes.py`, `run.sh`, `session.sh`, `export_slow.sh`).

| route | before p50 / p95 | before peak | after, kept (the job built it) p50 / p95 | after peak | after, first open with nothing kept | answer |
|---|---|---|---|---|---|---|
| track page (2 tracks) | 0.56-0.58 / 0.72-0.76 s | +105-112 MB | 0.0042-0.0045 / 0.010-0.013 s | +9-10 MB | 0.79 s, +59 MB (then kept) | byte-identical |
| track suggestions | 0.70 / 0.89 s | +97 MB | 0.0037 / 0.0079 s | +9 MB | 0.88 s, +51 MB | byte-identical |
| unread counts | 0.43 / 0.56 s | +8 MB | 0.0015 / 0.004 s | +8 MB | 0.64 s | byte-identical |
| anatomy | 0.69 / 0.86 s | +29 MB | 0.0020 / 0.005 s | +6 MB | 0.88 s | same but `generated_at` (≤ 10 min old) |
| main source (mxreal, after a run) | 0.017 / 0.27 s (per-process cache) | +16 MB | 0.0038 / 0.0054 s | +9 MB | 0.33 s | same rows; + `built_at` |
| suggested sources | 0.034 / 0.20 s (per-process copy) | +23 MB | 0.065 / 0.22 s | +25 MB | — | same; `refreshing` true when the job is asked |
| entity queue, 12,850 open | 0.36 / 0.61 s | +116 MB | 0.14 / 0.36 s | +25 MB | — | same items and counts (ties now by id) |
| entity queue, offset 100 | 0.38 / 0.59 s | +114 MB | 0.18 / 0.44 s | +26 MB | — | byte-identical |
| export (6.4 GB copy, 1.85 GB zip) | 237 s, fast reader | +19 MB | not changed | — | — | — |

The first call of a process is ~0.15-0.2 s in every row (the pool's first connections, the code stamp): not counted.

**The jobs process** (fresh process each, scale): `tracks` 3.2 s, peak 98 MB (4 pages + suggestions, after placing the
changed tracks); `unread` 0.97 s, 58 MB; `discover` (the answer rebuilt, reads off) 2.7 s, 100 MB; `main_source`
(mxreal) 0.7 s, 65 MB. The runner's look over every kept view: 8-19 ms (tracks 3-6 ms, unread 0.5 ms).

**One API process under uvicorn** (compose's malloc settings), 8 rounds of the 12 routes of this issue 4 at once:

| | each round | RSS after 8 rounds | VmHWM | 5 s idle |
|---|---|---|---|---|
| before | 2.0-2.5 s | 190-201 MB | 201-206 MB | 154-171 MB |
| after, nothing kept at the start (round 1 builds) | — | 155 MB | 165 MB | 130 MB |
| after, kept (by the job or an earlier open) | 0.11-0.16 s (round 1: 0.31 s) | 112 MB | 123 MB | 103 MB |

**Export.** Not reproduced: the export streams (COPY, 1 MiB chunks, zip written as it goes, StreamingResponse with
uvicorn's flow control). In process with a fast reader: +19 MB for the whole 1.85 GB zip; under uvicorn with a reader
at 2 MB/s for 60 s: flat at 91 MB. The 7.5 GB of 0186/0188 was that harness's (its client held the whole body), not
the API's. Nothing changed.

## What a kept page lags, stated

- A track page and the suggestions: a worker's verdicts and the planner's statistics within `KEPT_LAG` (15 min; the
  job builds a page again ~2-2.5 min after they moved: its gap and a look); the footer's last-7-days rates and the
  suggestions' 30-day window as of the build (≤ 15 min). The owner's own changes (labels, topic, sub-topics, sources)
  are exact: the next open builds it.
- Anatomy: a report as of its `generated_at`, at most 10 minutes; a source added or removed is exact.
- Main source: a worker's readings between decision runs within 10 min (as the old per-process cache); after a new
  run or a source change, the newest list until the job makes it (a look and a scan; behind a decision run at worst).
- Discover's suggested sources: as 0172 (the last answer built, `built_at`, `refreshing`).
- Unread counts and the entity queue: exact.

## Tests

The whole suite (`JOBS=6 scripts/test-backend.sh`): 6 shards, 179 modules, 3,491 tests, OK. A first run caught the
export round trip: a restore truncated its tables before turning their triggers off, so 0139's truncate triggers added
kept-input rows the export did not hold; `db/import_export.restore` now turns the triggers off first.

New `test_kept_pages_wave_2` (11): the kept inputs (each writing transaction moves its input, a scroll or a title
does not, one transaction is one change, folding keeps every count); the unread counts (kept bytes = counted, sent
kept with the counting patched to fail, counted again after a read and a post, built by the job, a window never
kept); track pages (built by the job and sent kept with the builders patched to fail, a label shown at once, a
verdict sent within the bound and making the job build it, never sent past `until`); anatomy (kept, a source added
makes it again, past KEPT_FOR made again); the entity queue paged in SQL (the same items and counts as the whole
read); the runner with Mark X off (only the reader's views). Guards: `test_api_routes_never_block` gains
`NoPageStartsWork` (no GET route starts background work: `.start(`, `create_task`, `add_task`; the research page's next
step allowed, not this wave's) and Discover has no API-side starter; `test_api_no_whole_book` covers the new routes as
every GET (unchanged, green). Updated: `test_markx_jobs` (the runner's tests on Mark X's views; the loop starts with
Mark X off), `test_markx_kept_pages` (the views), `test_discover_main_source` (the kept list made by the job),
`test_discover_fixes_0172` (the job keeps Discover; `served_due`), `test_feed_routes`, `test_source_anatomy`.

## Not done

- Discover's suggested sources still parse the kept 2.1 MB answer on each open (p50 0.065 s, was 0.034 s with each
  process's copy): its first page could be kept as bytes once its live archive rows are stamped.
- The 17-20 s main-source scan of the server was not reproduced (this copy's announced stories yield no rows); its
  path is the same, now in the jobs process.
- The voices suggestions are still computed in an API thread (`voices_service`), and the research page advances in
  the request's background: not in 0202's list.
- No change to the frontend (`built_at` on the main source is a new field it ignores).

## The write cost of 0139's kept inputs (asked before the release)

Two clones of `prep_scale`: v1018 before this merge (26c959b, migrations to 0137) and with 0139; the same writes on
each, the database backend's own CPU read from /proc (5 rounds each, alternating), and each trigger's own time from
`EXPLAIN ANALYZE` (the direct cost; the scratch server is shared, so the whole-run numbers carry its noise).

| write | before: DB CPU (median) | with 0139 | the kept-input triggers' own time | log rows |
|---|---|---|---|---|
| ingestion-like: 50 tx x 100 single-row post inserts, then 50 x 100 single-row updates of dates, metadata, text | 9,140 ms | 9,180 ms (+0.4%) | 5,000-row insert: 0.13 ms (one statement trigger); 5,000-row update: 32 ms of ~2,500 ms (1.3%, the row trigger) | 150 (one per transaction and input) |
| 1,000 posts marked read, one statement (the app's `set_read`), and back | 20 ms | 20 ms | 0.18 ms of ~19 ms (~1%) | 1 |
| 1,000 posts marked read, one statement each, one transaction | 840 ms | 855 ms (+1.8%) | — | 1 |
| a full story job (4,962 stories) | 70.0 s / 55.9 s (two runs) | 72.8 s / 60.8 s | its 80 log rows (first run), 0 (second: nothing it rewrote was watched) | 80 / 0 |

The story job's spread is the shared server's (its second pair differs by 5 s with not one kept-input row written).
The direct cost stays under ~1.5% everywhere, below the 5% bar: nothing changed. The posts update trigger stays
row-level with its WHEN list (a statement-level one would fire on every UPDATE naming metadata or content, the
repairs' too, and stamp the unread counts stale for nothing); its rows dedupe to one per transaction.

**Discover's suggested sources, p50.** An open now reads its page's suggestions sliced in Postgres
(`DiscoverRepository.served_window`: the stored answer detoasted once, `jsonb_path_query_array`), not the whole 2.1 MB
answer: answer byte-identical; p50 0.061 → 0.054 s, the API process's peak +28 → +7 MB (before this issue: 0.033 s
with each process's copy of the answer, +47 MB in the same run). The 20 ms left are the served answer's stamp and the
job's state read with every open (both read the stored row); keeping the first page as bytes would remove them once
its live archive rows are stamped: not done.

## The real-data check with Mark X off (markx.ix_unchanged)

The check on the merged v10.18 failed `markx.ix_unchanged` 0 -> 2: with Mark X off the runner's tick kept the unread
counts (the reader's view "unread"), which wrote its mx_jobs row and its mx_kept_pages row; the check counted the
tick (a job ran) and the rows (mx_* rows written). Neither is Mark X's: since this issue the kept views' machinery
(the runner, mx_jobs, mx_kept_pages) serves the reader as well, and the reader's views run with Mark X off by design.

Decided: the invariant's definition tells them apart, from the code, not by loosening it. `jobs.readers(job)` (a
KeptView with `markx` False) and `jobs.reader_rows(cur)` (those views' mx_jobs rows and the mx_kept_pages rows of the
pages they declare: `KeptView.pages`); `markx_unchanged` counts a run with Mark X off only when it is not a reader's
view, and the mx_* rows it wrote less the reader's (both shown in its note). Any Mark X job, or any other mx_* row,
still fails it. A version before (the base) has neither and counts as before. Why not move the reader's pages out
of mx_ now: the pages and the job state are one mechanism shared with Mark X News, the entity pages and the Labels
queue; splitting the tables would be a second path. Renaming them (`kept_pages`, `jobs`) for the open-source release
is left as a no-op move of its own.
Test: `test_kept_pages_wave_2.TheRunnerWithMarkXOff.test_with_mark_x_off_a_tick_writes_the_readers_rows_only`.
