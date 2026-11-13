# 0195 — The API light and fast (v10.17)

Status: **built** (branch `v1017-api-perf` from `v1016` bae0ac0). Not merged, not pushed, not deployed. Migrations
**0131** (source post statistics), **0132** (Mark X totals), **0133** (track placements).

Owner priority: a functional, lightweight, fast service. Rules kept: one mechanism per class, in the module that owns
the data; nothing added to what insight-api holds between requests; every answer identical to before except the
pages asked for (C3); every claim below measured before and after.

## The problem (a read-only audit of the server, v10.16, 2026-11-13)

| route | server (one GET each) | why |
|---|---|---|
| `/api/operations/overview` (polled by the top bar on every page, 15 s / 5 s) | 1.34 s, 35 KB | source health: six correlated subqueries per source over posts, count(*) and MIN/MAX over every post; and an `async def` route running it on the event loop |
| `/api/sources/health` | 0.70 s, 430 KB | the same health rows |
| `/api/feed/unread-counts` (polled every 60 s / 10 s) | 0.30 s, 40 KB | all-time unread counts, sent whole each poll |
| `/api/news` | 0.43 s, 899 KB | 311 rows, no paging |
| `/api/classics` | 0.54 s, 1.6 MB | 3,018 rows |
| `/api/sources` | 0.19 s, 906 KB | 48% the archive checkpoint's resume lists (candidate URLs, the ladder) |
| `/api/archive/catalog` | 0.24 s, 668 KB | 66% the same lists; each source's settings read one by one |
| `/api/markx/overview` | 5.69 s, 68 KB | a GROUP BY over ~1M tasks and sums over every call, per request |
| `/api/markx/entities/queue` | 15.09 s, 28.9 MB | 12,572 open items, each built with its examples and join plan |
| `/api/markx/tracks/suggestions` | 2.00 s | every topic track placed in full per request |
| `/api/markx/tracks/{id}` | 2.05 s, 159 KB | the track placed twice (its own items, then the suggestions) |
| `/api/markx/tracks/counts` | 0.65 s | every topic track placed per request |

48 of main.py's `async def` routes and 7 Mark X routes awaited nothing and called sync services: each ran its
database work on the event loop, so one slow request stalled every other request of that API process.

## What was built, by class

**C1. No route blocks the loop; the polled overview reads kept statistics.**
- Every async route that awaits nothing is a plain `def` (FastAPI runs it in the threadpool); the async ones that also
  call a sync service await it through `asyncio.to_thread`. Guard: `tests/test_api_routes_never_block.py` reads every
  route of main.py and the routers and fails on an async route that awaits nothing or calls `services().x.y()` (or a
  module function that does) on the loop. `debug_spin` (0117's watchdog measure) busy-loops on purpose and is allowed.
- `db/repo_post_stats.py` + migration 0131: each source's post statistics (count, newest post, newest page reads,
  paid preview, moved-to, the corpus' newest/oldest/latest fetch) kept in `source_post_stats`. Triggers on posts log a
  source whose posts changed (insert, delete, an update of a column the statistics read) in an append-only log; a
  logged or never kept source is read live by the very same expressions (`stats_sql`), so no read is ever stale,
  whoever wrote the posts. The ingestion runner keeps them again after each run (`DbFetchStateStore.keep_derived`).
  Opened posts are counted from the opened posts up (set-based), not per source over every post. The migration keeps
  every source at once. Readers: source health (so the overview, `/api/sources/health`, a source's row, anatomy),
  `/api/status`, `/api/sources`' post counts.
- `GET /api/operations/running`: the recent jobs only (the list the overview carries), for the top bar, the feed's
  "fetching" sign and a source's sheet. The full overview is fetched only on the Ingestion tab.

**C3. Bounded answers.** One paging rule (`utils/paging.py`: an offset cursor, as search's best order; the first page
is the whole list's top rows):
- `/api/news` `limit` 50, `/api/classics` `limit` 100, `cursor`, `next_cursor` (Classics reads the page's titles
  only). The real-data check's snapshot reads the whole lists (`news_on`, `classics_on` unpaged), unchanged.
- `/api/markx/entities/queue` `limit` 50 + `offset`, `next_offset`; `counts.open` still counts every open item; only
  the page's items and examples are built. An entity page's questions are the open items naming it (`queue_about`),
  not the whole queue built and filtered.
- An entity page lists `stories_limit` 50 story blocks and `loose_limit` 100 loose posts, with `stories_total` and
  `loose_total`; the blocks not listed are only headed (their timeline events and the label sample read every story).
- The list views (`/api/sources`, `/api/archive/catalog`) leave out the archive checkpoint's resume lists (`urls`,
  `ladder`; the frontend reads the checkpoint's counts only; a source's own settings and its archive status keep the
  whole checkpoint), as 0105 left out the history. The catalog reads the list's settings in one query.
- Not paged: `/api/sources` (the reader's directory needs every source) and `/api/sources/health` (each source's sheet
  finds its row in it); both are now fast, and health is a conditional GET (C8).

**C4. No per-request aggregate over a whole table.**
- `markx/kept_counts.py` + migration 0132: the tasks by kind and status and the calls' totals kept. Statement-level
  triggers on mx_tasks and mx_calls append each statement's net change to `mx_counts_delta` (no counter row is locked,
  so the parallel workers never wait on one); a read is the folded totals plus the deltas, so it always equals the
  GROUP BY; `fold` (after each ingestion run) moves the deltas in one statement. The migration takes the totals under
  a lock on both tables. `repo.queue_counts` (overview, `/api/markx/status`) and `news.worker`'s call totals read it.
  Chosen over a snapshot per decision run: a snapshot is wrong between runs; this is exact at every read.
- `markx/track_kept.py` + migration 0133: each topic track's placement (`tracks.placed` itself, the planner untouched)
  kept in `mx_track_places`, its calibration in `mx_track_places_state` (json, its key order kept). Triggers log a
  track whose inputs changed (its items' verdicts, the owner's track labels, its sources, a post of it deleted or
  moved); a logged or never placed track is placed live. Readers: the sidebar counts, the suggestions, and a track's
  page (its listed items get their title, address, source and why read for those only). The refresh runs after each
  ingestion run; the Mark X jobs process may also call `track_kept.refresh(cur)` after the track planner or after
  answers land, to keep tracks fresh while a worker runs (not done here: jobs.py belongs to other slices).

**C8. Light polling.** The polled answers (running jobs, unread counts, the overview, source health) are conditional
GETs (`routers/conditional.py`, a pure ASGI middleware on those four paths): a weak ETag of the body and
`Cache-Control: no-cache`; the browser revalidates by itself and an unchanged answer is a 304 with no body. The data
panel polls only while the browser tab is visible; React Query never polls a background tab. The bundle gate budgets
the Mark X routes (`markx`, `markxEntity`, `markxStory`); a route with no baseline yet is recorded, not checked.

## Measured (scratch copy, before / after, the same data)

The workflow slice's prepared copy of the server (`prep_mxreal`: 49k posts, 256 sources), migrated, with mx_tasks
and mx_calls inflated to the server's scale (1.04M tasks, 482k calls) and four synthetic topic tracks of 25k judged
posts each (the copy has no track items). The API in one process on it; seconds the median of three GETs; RSS of the
API process after each route (VmRSS; peak VmHWM in brackets where it moved).

| route | before | after |
|---|---|---|
| `/api/operations/overview` | 0.231 s | 0.06-0.11 s |
| `/api/operations/running` (new; the top bar) | (the overview, 0.231 s) | 0.007 s, 304 when unchanged |
| `/api/sources/health` | 0.210 s | 0.070 s |
| `/api/status` | 0.217 s | 0.069 s |
| `/api/feed/unread-counts` | 0.118 s, 27.6 KB each poll | 0.12 s; 0 bytes (304) when unchanged |
| `/api/news` | 0.082 s, 267 KB (99 rows) | 0.078 s, 178 KB (50 rows) |
| `/api/classics` | 0.044 s, 270 KB (518) | 0.032 s, 71 KB (100) |
| `/api/archive/catalog` | 0.075 s | 0.021 s |
| `/api/markx/overview` (1M tasks) | 0.172 s | 0.068 s |
| `/api/markx/tracks/suggestions` | 1.33 s, RSS +236 MiB | 0.29 s, +11 MiB |
| `/api/markx/tracks/{id}` | 0.96 s, +97 MiB | 0.63 s, +42 MiB |
| `/api/markx/tracks/counts` | 0.68 s | 0.13 s |

The copy's archives carry no large checkpoints and its Mark X has no entity queue, so `/api/sources`, the catalog's
bytes and the entity queue are the server's: from the payloads above, `/api/sources` 906 KB -> 468 KB and the catalog
668 KB -> 230 KB (the URL lists removed from the saved answers), the entity queue 28.9 MB of 12,572 open items -> 50 open items a page.
Kept placements: the four tracks placed by the refresh in ~12 s (in insight-ingestion, after a run); the source
statistics kept in ~1 s.

Identity: every changed GET answered the same JSON before and after on the copy (`news`, `classics` across all their
pages, `sources` and the catalog without the checkpoint lists, health, overview, status, unread counts, the Mark X
overview, the track pages, suggestions and counts with kept and with live placements at one instant); clock-derived
fields (`decision_detail`, `silent.days`) aside.

## Tests

`test_api_routes_never_block`, `test_source_post_stats`, `test_conditional_get`, `test_markx_kept_counts`,
`test_markx_tracks.KeptPlaces`, and the queue / entity page / story window / source settings additions; the modules
they touch (repo_fetch_state, source_health, ingestion_routes, operations_service, moved_pages, news, search,
realdata_checks, markx_api, api_no_whole_book, ingestion_runner, markx_entities, markx_tracks, track_counts,
track_feed, timeline, handles, entity_guards) pass. Frontend: the touched vitest files, tsc, the bundle check.

## Left open

- The entity queue still reads every unclosed row and primes the book with them to tell which are shown (named now);
  only the page is built. If the server's 14.7 s was mostly the rows themselves, a kept "shown" flag would be next.
- The track page reads its 25k kept placements to group them by sub-topic in Python (0.25 s of its 0.63 s) and the
  profile's vector maths (0.18 s); both could move to SQL / kept values.
- Unread counts are computed per poll (0.12-0.3 s); the 304 saves the transfer, not the query.
- The confidence-band filter of the entity queue counts the loaded items only (the frontend loads 50 more at a time).
