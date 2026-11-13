# 0202 — insight-api's memory down and flat (v10.17.2)

Status: **built** (branch `v10172-api-memory` from `main` at v10.17.1). Not merged, not pushed, not deployed. No
migration.

## The problem

The owner's Grafana (v10.17): insight-api ~400 MB right after a deploy, 1.2 GB by the end of the day; 4.37 GB before
v10.17 (the Labels queue and the whole-book pages, since moved out: 0182, 0186). The container runs tini, the API
supervisor (`scripts/api_supervisor.py`), uvicorn's master and two uvicorn processes (`API_WORKERS=2`,
`docker/start-backend.sh`), with `MALLOC_ARENA_MAX=2` and `MALLOC_TRIM_THRESHOLD_=131072` already set in compose.

## How it was measured

Scratch clones only (never the originals, never the server): `prep_scale` (148k posts, 1.06M tasks, 4 topic tracks
with 47k judged items: the server's size) and `prep_mxreal` (49k posts with real Mark X answers, a decision run of this
code made on the clone for its entities, News and stories). Two ways, the same route classes (polls, feed, post, News
Mark IX, News Mark X, story, entity, tracks, search, Discover, overview):

- **The real container** (`docker/start-backend.sh`, the supervisor, 2 uvicorn processes, compose's malloc settings),
  driven over HTTP; the RSS of every process read from /proc. A "day-like session": each round reads 15 pages (the
  feed, posts, News, stories, entities, a search, tracks, Discover, the overview), the three polls before each, and
  waits 1.5 s on each page as a reader does; 6 rounds.
- **In one process** (`main:app` driven through ASGI, sync routes on anyio's threadpool as under uvicorn, 4 at once):
  RSS per class, Python's traced heap, pymalloc's arenas, and what `gc.collect()` and `malloc_trim(0)` give back.

The harness is in `plan/research/apimem/` (private): `drive.py` (HTTP), `inproc.py` (in process), `cycles.py`.

## What was found, by class

**(a) The start: no heavy library.** One API process is 76-80 MB after its start. `import main` costs ~85 MB of which
the Python runtime and the standard library 29 MB, pydantic 4, fastapi/starlette/anyio 10, uvicorn 4, psycopg 8,
cryptography 6, and every INSIGHT module together ~20 MB (Mark X's decision modules, imported through labels.py, 5 MB).
No numpy, pandas, trafilatura, lxml, telethon, yt-dlp or embedding library is imported, at the start or by any route of
the session (69 modules more after a session, all INSIGHT's own or the standard library's). Lazy imports would save at
most ~5 MB a process: not done (labels.py subclasses decide's classes at import).
The container's other processes: the supervisor **56-59 MB** (it built the services to close the jobs a restart
interrupted: 23.6 MB before, 60 MB after), uvicorn's master 25 MB, two multiprocessing resource trackers 12.7 MB each.

**(b) What requests leave behind: not Python objects.** After a whole session Python's own heap had grown by ~4 MB
(the modules routes import when first used). What stayed in RSS was two other things:

1. **Freed memory glibc keeps.** A big request (a track page reads its 25k kept placements: +100 MB while it runs; the
   overview, unread counts, the Classics) frees what it built when it ends, but glibc keeps the freed pages in its heaps
   (only the top of the main heap is ever returned by itself, whatever the trim threshold), so each process stays at its
   largest request's high-water. In one process, after 4 rounds at 4 at once: 222 MB with `MALLOC_ARENA_MAX=2`, 279 MB
   with glibc's default arenas, 224 MB with 1 arena; `malloc_trim(0)` gives back ~70 MB of it.
2. **psycopg results kept by reference cycles.** A cursor sits in reference cycles (its Transformer, loaders and
   dumpers: 90-290 objects a request), and a closed cursor's Transformer still holds its last result: libpq memory,
   every row of the query. Those are freed only when the cyclic GC's next full pass runs, which with few new container
   objects can be long after. A track page's process: 220 MB, 183-223 MB once trimmed, **130 MB once collected and
   trimmed**.

Per class (in process, scale, 4 at once; RSS growth while the class runs, then what stays after collect + trim):

| class | time | grows while running | stays |
|---|---|---|---|
| polls (running, unread counts, version, status, overview, health, markx/on) | 0.4-0.7 s | +9-36 MB | ~0 |
| feed (4 filters, 4 sources, by source, folders, sources) | 0.16 s | +2-5 MB | 0 |
| post (6 posts: item, connected, Mark X panel) | 0.05 s | 0-8 MB | 0 |
| News Mark IX + Classics | 0.15 s | +5 MB | 0 |
| tracks (list, 4 track pages, suggestions) | 2.0-2.4 s | **+95-105 MB** (peak 230-290 MB) | +10-20 MB the first rounds |
| search (4 queries) | 0.1 s | 0-3 MB | 0 |
| overview (overview, catalog, anatomy, status) | 0.7 s | +5 MB | 0 |
| Mark X News, story, entity pages (mxreal) | 0.1-0.4 s | +2-19 MB | 0-3 MB |

**(c) glibc.** `MALLOC_ARENA_MAX=2` (already in compose) measurably cuts retention (222 vs 279 MB a process after the
same session; 1 arena: 224), so it stays. `malloc_trim` alone, after each class: 142 MB. **Collect, then trim**: 141
MB, and much flatter between rounds (130-147 MB right after a track page, against 183-223 MB trimmed alone).
`PYTHONMALLOC=malloc` (no pymalloc) went lower still (103 MB) but made the track pages 30% slower (3.2 s vs 2.4 s) and
their peak higher: rejected (a p95 regression).

## What was built

1. **Idle collect and trim** (`utils/idle_trim.py`, `IdleTrim`, the outermost middleware). It counts each process's
   requests in flight; when the last one ends, a thread of its own waits 1 s (`QUIET`) and, if no request started
   meanwhile and the process grew by 8 MB or more (`GROW_MB`) since its last trim, runs `gc.collect()` then
   `malloc_trim(0)`. Never during a request; a poll that leaves nothing behind never triggers it. The trim takes
   0.1-5 ms (ctypes releases the GIL while it runs).
2. **The start frozen out of the GC** (`freeze_start()`, each process's lifespan): `gc.collect(); gc.freeze()` once the
   services are built. The objects of the start live as long as the process, and a full collection no longer reads
   them: **2-9 ms instead of 40-60 ms** (the collection holds the GIL, so this bounds how long a request arriving just
   then waits). The track pages got slightly faster too (fewer long GC passes inside requests).
3. **The supervisor no longer builds the services** (`close_interrupted_jobs_in_child`): the interrupted jobs are
   closed in a spawned child the start waits for, as before uvicorn serves; the supervisor stays at ~25 MB (was 56-59)
   for the container's life.
4. `INSIGHT_API_TRIM=off` switches 1-2 off; without glibc's malloc_trim (musl) they do nothing.

Every answer is unchanged: no route, query or body changed. Checked: the session's distinct GETs sent to the old and
the new container on one clone: scale 93 paths, 92 byte-identical, the other (`/api/sources/anatomy`) differing only
in its `generated_at` clock; mxreal 100 paths, 99 byte-identical, the same one differing the same way.

## Before / after

The real container (2 API processes, compose's malloc settings), the same clone and requests for both; MB of RSS
(VmRSS of each process; "all" is every process of the container: tini, supervisor, uvicorn's master, the two
resource trackers, the two API processes).

**Server-sized copy (prep_scale)**

| when | before (main, v10.17.1) | after |
|---|---|---|
| started (the start work done) | API 77 + 77; all 258-262 | API 77-81 + 77-80; all 228-236 |
| the supervisor, for the container's life | 56-59 | 25 |
| after the day-like session (6 rounds, 864 requests, 1.5 s per page), 5 s idle | **API 177 + 181 = 358; all 463** | **API 112 + 119 = 231; all 304** |
| the same session with no pause between pages (10 rounds), 3 s idle | API 188 + 176 = 364; all 472 | API 128 + 145 = 273; all 346 |
| after a stress run (2 x 600 mixed requests at 4, 8 and 16 at once, the track pages included), idle | API 594-599; all 699-704 | API 365-385; all 438-458 |
| highest RSS of one process (VmHWM) in the stress run | 294-323 | 269-276 |

**Real Mark X answers (prep_mxreal, News, stories, entity pages)**: after the day-like session (5 rounds) all 347
before, 296 after (API 239 -> 223); this copy is small, its requests build little.

**In one process, scale, 4 at once, 4 rounds**: 222 MB before (279 with glibc's default arenas); 141 MB with the idle
collect and trim; a track page's process back to 126-147 MB right after it (220-245 while it runs).

Target (steady ≤ 400 MB for the container after a day-like session): **304 MB**, was 463. After the stress run (far
more concurrency than one reader makes) 438-458, was 699-704.

What stays after a trim is mostly pymalloc's: after 16-at-once bursts one process held 111-129 arenas of 1 MiB for 37
MB of live Python objects (69-88 MB in free pools of arenas that a few long-lived objects keep: pymalloc gives an arena
back only when all of it is free, and malloc_trim cannot reach it). Pre-importing the modules routes import later did
not change it measurably (171 vs 169-186 MB, within the noise). The lever left is making the big requests allocate
less (the track page, below), not the allocator.

## Workers: two, measured

0112 Decided 11 chose two processes so one stuck process can't freeze the reader. With every route now a plain
`def` on the threadpool (0195), measured again: 600 mixed requests (the day-like session's mix) at 4, 8 and 16 at
once, two passes, the four containers in turn on the same clone (the machine shared with other agents' suites):

| at once | 2 processes before | 2 processes after | 1 process (40 threads) | 1 process, 100 threads |
|---|---|---|---|---|
| 4: p95 / p50 / requests a second | 0.480-0.488 s / 7-8 ms / 42-44 | 0.475-0.485 s / 7-8 ms / 44 | 0.527-0.550 s / 8 ms / 37 | 0.540-0.562 s / 8 ms / 35-36 |
| 8 | 0.583-0.631 s / 9-12 ms / 54-65 | 0.523-0.573 s / 9 ms / 61-68 | 0.719-0.759 s / 18 ms / 45-48 | 0.669-0.719 s / 18-21 ms / 45-49 |
| 16 | 0.827-0.881 s / 24-27 ms / 69-76 | 0.797-0.873 s / 25-29 ms / 73-79 | 1.231-1.551 s / 116-132 ms / 45-52 | 1.238-1.386 s / 91-109 ms / 51 |
| idle after both passes (API / all) | 594-599 / 699-704 | 365-385 / 438-458 | 208 / 245 | 205 / 242 |

One process saves ~150-200 MB (one API process, uvicorn's master and its tracker) but its p95 is 10-15% worse at 4
at once, 30% at 8 and 50-75% at 16: the requests are CPU-bound Python (the GIL), so a larger threadpool does not help
(1 process with 100 threads is the same as with 40). **Kept: two processes** (`API_WORKERS=2`, unchanged), whose
p95 is the same or better than before at every load, and the memory target is met with them.

## What a request still builds that a job could keep (not built here)

Measured per request on the scale copy; each is built in insight-api on every open (or poll) from data that
changes only when a job runs. Not built here; 0198 (branch `v10171-stored-pages`, not merged) covers Mark X News and
the entity pages.

| route | what it builds per request | measured |
|---|---|---|
| `/api/markx/tracks/{id}`, `/tracks/suggestions` | groups a track's ~25k kept placements by sub-topic in Python, the profile's vector maths (0195 "left open") | the largest class: +95-105 MB while it runs, 2.0-2.4 s for 4 track pages and the suggestions; the whole stress run's peak. A job could keep each track's page after `track_kept.refresh` (as 0198 keeps News) |
| `/api/feed/unread-counts` (polled every 60 s) | all-time unread counts per source and folder | 0.4-1.4 s a poll at scale; the 304 saves only the transfer. Kept counts (triggers, as 0131's source statistics) or a job |
| `/api/sources/anatomy` | every source's anatomy | 0.65-0.8 s, 180 KB an open; changes with ingestion runs only |
| `/api/discover/main-source` | the main-source scan, cached in each API process's memory (`MainSource._cache`: one copy per process) | 17-20 s on the server when stale (0186); a job writing it would also drop the per-process copy |
| `/api/sources/suggested` (Discover) | ranks the linked sites and tests the first page's suggestions over the web from the API process (feed finder) | not timed here (it reaches out to the web); the tests belong to insight-ingestion |
| `/api/markx/entities/queue` | reads every unclosed queue row to page 50 (0195 "left open") | |
| `/api/export/everything` | the whole database as a zip, streamed by the API process | 0188: a 7.5 GB process peak on the 0186 copy; not re-measured here. A job writing the file, the API sending it, keeps it out of insight-api |
| Mark X News, an entity's page | 0198 | |

## Tests

`test_idle_trim` (the trimmer's quiet spell, overlapping requests, the growth bar and its lowest point, collect before trim, no trim
without malloc_trim, the thread, the middleware counting a request to its last byte, outermost in the app, the start
frozen), `test_api_supervisor` (the jobs closed in a child the start waits for; a child that cannot start never stops
the API; each process's start freezes), `test_api_watchdog`, `test_api_routes_never_block`, `test_conditional_get`.

The whole suite (`JOBS=6 scripts/test-backend.sh`): 6 shards, 176 modules, 3,490 tests, OK.
