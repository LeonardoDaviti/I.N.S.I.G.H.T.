# Research: merge the API and ingestion into one process?

Status: research only, nothing changed. Date: 2026-10-10.

## Question

Should the API (`backend/main.py` under uvicorn, `backend/docker/start-backend.sh`) and the ingestion scheduler (`backend/insight_core/scripts/run_scheduler.py`, `backend/docker/start-ingestion.sh`) run as one process in one container? Today they are two containers built from the same image. Each one is a separate Python runtime using about 80–120 MB RSS at idle.

The owner has two constraints. The system should be lightweight, and a misbehaving fetch must not slow down reading.

## Short answer

**Merge, with conditions, and keep the separate container as a switch.**

The isolation that two containers seem to provide is mostly not there. The API process already runs the same `run_ingestion` code on its own event loop for every manual trigger: Run cycle, fetch-now, and folder/track fetch. The hourly tick is the only ingestion work that lives elsewhere. Moving it into the API:

- saves one interpreter (about 80–116 MB);
- gives scheduled and manual fetches one shared set of `FetchGates`, which fixes known limitation §A.6;
- adds no new kind of risk to reading. It does add more of an existing risk: an hourly run on the reader's loop instead of an occasional manual one.

Do it only after measuring reader latency during a forced manual Run cycle today, and only with the guards listed in the recommendation below.

## What the code does today

**Scheduler process**
- `run_scheduler.py:278-289` is an `asyncio` loop. It wakes every 1 s and calls `tick()` when `next_tick_at` has passed.
- `tick()` runs `run_ingestion(all, SCHEDULER)` at `:121`, then the daily work: prune, cadence refresh, `sources.json` sync (`:196`, synchronous), experts, and briefings.
- SIGTERM only sets a flag (`:269-270`). A tick that is in progress keeps running until Docker's SIGKILL.

**The API already runs ingestion in-process**
- `_accept_ingestion_run` (`main.py:298-325`) creates the job, then calls `background_tasks.add_task(...)` (`:320`), which in turn calls `api_bridge.run_ingestion_job` → `run_ingestion(...)` (`insight_api_bridge.py:1027-1031`).
- The callers are fetch-now (`main.py:1663`), Run cycle (`main.py:2164`) and folder ingest (`main.py:1234`).
- These run on the same event loop that serves `/api/feed`.

**Readers run on the loop**
- Every route is `async def`: 130 of them, with no sync `def` routes.
- Most call synchronous psycopg directly on the loop, for example `get_feed` (`main.py:566-568`) and unread counts (`:578`).
- Only a few heavy routes use `asyncio.to_thread`, such as milestones (`main.py:1319`, `:1351`).
- So reader latency already depends on the loop being free.

**How ingestion does its I/O**
- HTTP uses blocking `urllib` with a timeout, inside `asyncio.to_thread` (`ingestion/http.py:57,71,102,128`).
- DB saves and state writes go through `to_thread` (`runner.py:236`, `_safely`).
- yt-dlp is a `subprocess.Popen` with `communicate(timeout=90)` running inside a worker thread (`youtube_service.py:539-547`, `kinds/youtube.py:50`). It runs in its own process group so a timeout kills grandchildren too.
- Feed parsing (`parsing.parse_feed_posts`, ElementTree) runs **on the event loop** (`kinds/generic_rss.py:45`, `reddit.py:69`, `substack.py:222`, `telegram_rss.py:133`, `nitter_rss.py:143`).
- Telethon is native asyncio, so MTProto runs on the loop.
- Fetches fan out with `asyncio.gather` (`runner.py:215`).

**Gates and locks**
- `FetchGates.shared()` is one instance per event loop (`gates.py:194`). Its global budget of 8 is sized against the default thread pool (`gates.py:182-186`).
- Each process has its own gates. The plan records this as a known limitation (`plan/INSIGHT_mark_ix_plan.md` §A.6, lines 308-312): "A forced track fetch in the API can overlap a scheduler tick on the same host."
- Full runs take a session advisory lock, `pg_try_advisory_lock`, on a dedicated connection (`ports.py:222-257`, `runner.py:147`). Folder and source runs do not take it.
- Daily work (briefings, experts) is **not** under any lock.
- Telegram sessions take their own advisory lock (`kinds/telegram_session.py:21`). The loser reports "in use by another run".

**Containers**
- Both services use `insight-backend:latest` (`docker-compose.yml`).
- Neither has a `mem_limit`.
- Both set `MALLOC_ARENA_MAX=2` and `MALLOC_TRIM_THRESHOLD_`.
- The compose comment says each process pays about 116 MB of imports and recommends `API_WORKERS=1`.
- `start-backend.sh` explains why there is no `--limit-max-requests`.
- The ingestion healthcheck only checks that `run_scheduler` exists in `/proc`. It cannot see a hung tick.
- Both containers run `migrate.py` and the JSON→DB sync on start. The migration is serialised by an xact advisory lock.

**Other facts**
- `INSIGHT_ANALYSIS` appears only in `plan/` documents, not in the code yet. Daily work still calls the briefing and expert services.
- There is no reaper for stale "running" jobs (none in `operations_service.py`). A killed run leaves its `job_runs` row stuck as running, in either design.

## Evidence (primary sources)

| Claim | Source |
|---|---|
| Lifespan code runs once before the app accepts requests and once at shutdown | https://fastapi.tiangolo.com/advanced/events/ |
| Starlette runs the lifespan teardown "once all connections have been closed, and any in-process background tasks have completed", and recommends anyio task groups for managing tasks | https://github.com/Kludex/starlette/blob/main/docs/lifespan.md |
| FastAPI `BackgroundTasks` run in the same process. For heavy work that doesn't need shared memory, FastAPI suggests a separate tool | https://fastapi.tiangolo.com/tutorial/background-tasks/ (Caveat) |
| `--workers N > 1` runs `Multiprocess`, which spawns separate worker processes. Each one calls `server.run()`, and therefore its own lifespan | https://github.com/encode/uvicorn/blob/master/uvicorn/main.py (lines ~614-632), https://github.com/encode/uvicorn/blob/master/uvicorn/server.py (`startup` → `lifespan.startup`, line ~116) |
| On shutdown uvicorn stops accepting connections, waits for in-flight connections and background tasks (indefinitely unless `--timeout-graceful-shutdown` is set; the default is `None`), and only then sends lifespan shutdown | https://github.com/encode/uvicorn/blob/master/uvicorn/server.py (`shutdown`, lines ~280-323), https://github.com/encode/uvicorn/blob/master/uvicorn/config.py, https://uvicorn.dev/settings/ |
| One event loop runs every task. A 1 s CPU call delays all other tasks and I/O by 1 s. The fix is an executor (thread or process). Debug mode logs callbacks slower than 100 ms | https://docs.python.org/3/library/asyncio-dev.html |
| Because of the GIL, `asyncio.to_thread` only makes I/O-bound work non-blocking | https://docs.python.org/3/library/asyncio-task.html#asyncio.to_thread |
| Keep a reference to `create_task` results, because the loop holds only weak references | https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task |
| The default `ThreadPoolExecutor` size is `min(32, os.cpu_count() + 4)` | https://docs.python.org/3/library/concurrent.futures.html |
| The GIL lets only one thread execute Python bytecode at a time | https://docs.python.org/3/glossary.html#term-global-interpreter-lock |
| Under an OOM the kernel kills processes. Without `-m`/`mem_limit`, a container can exhaust host memory. Containers are made more likely to be killed than the daemon | https://docs.docker.com/engine/containers/resource_constraints/ |
| Restart policies act on container exit (`on-failure`: non-zero exit). `unless-stopped` stays down after a manual stop. A policy only applies after 10 s of successful start | https://docs.docker.com/engine/containers/start-containers-automatically/ |
| Compose `stop_grace_period` defaults to 10 s before SIGKILL | https://docs.docker.com/reference/compose-file/services/#stop_grace_period |
| A session-level advisory lock is held until it is released or the session ends. `pg_try_advisory_lock` returns false immediately instead of waiting | https://www.postgresql.org/docs/15/explicit-locking.html#ADVISORY-LOCKS, https://www.postgresql.org/docs/15/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS |
| Telethon is asyncio-native and runs inside an existing loop. Without `cryptg` it falls back to libssl, then to pure-Python `pyaes`. `cryptg` is not in `requirements.txt` | https://docs.telethon.dev/en/stable/concepts/asyncio.html, https://docs.telethon.dev/en/stable/basic/installation.html, https://github.com/LonamiWebs/Telethon/blob/v1/telethon/crypto/aes.py |

APScheduler is not needed. The scheduler is already a 1 s `asyncio.sleep` loop around a testable `tick()`.

## Trade-offs

| Aspect | Two containers (today) | One process (merged) |
|---|---|---|
| Idle RAM | Two interpreters, about 2 × 80–116 MB | Saves one interpreter (about 80–116 MB). Ingestion modules are already imported by the API through `insight_api_bridge.py` |
| Peak RAM | A run's peak stays in the ingestion process | A run's peak lands in the API process. glibc may keep some of the high-water mark (partly mitigated by the `MALLOC_*` settings). yt-dlp is a child process either way |
| OOM kill | Usually only the bigger process dies. With no `mem_limit`, the host kernel picks the victim | A spike kills reading too. Set `mem_limit` so the cgroup, not the host, decides |
| Crash (unhandled exception) | Scheduler container restarts on its own | `tick()` already catches everything. A dead lifespan task must be logged and surfaced, not silently gone |
| Hung fetch | Blocked worker thread, bounded by the urllib and yt-dlp timeouts | Same, but it takes a slot from the **shared** default thread pool that reader `to_thread` routes use (8 threads on a 4-core box) |
| Event-loop blocking | Scheduled parsing and Telethon block only the scheduler's loop | Hourly parsing and Telethon (pure-Python AES if libssl is missing) compete with `/api/feed` on one loop. **Manual runs already do this today** |
| GIL | Separate processes, no contention | Threaded save and parse work competes with the loop thread for the GIL |
| Host politeness | Two `FetchGates`: an API fetch and a tick can hit the same host together (§A.6) | One `FetchGates`: fixed for free |
| Deploy coupling | Same image: `compose up --build` recreates both anyway | Same, plus restarting the API for a config change interrupts a tick |
| Shutdown | SIGTERM is ignored mid-tick, then SIGKILL after 10 s | Lifespan teardown runs after connections and BackgroundTasks drain, then must cancel the tick. The job row needs finishing on cancel |
| `API_WORKERS > 1` | Not applicable | N schedulers. The run lock dedupes full runs, but **daily work and briefings would run N times** |
| Health and observability | Ingestion health is only "process exists" | One `/health`, which can report the scheduler heartbeat (`next_tick_at`) and loop lag |
| Startup | Two `migrate.py` and JSON syncs racing (locked) | One |
| Change size | None | Small: about 40 lines in `main.py` lifespan, plus compose and an env switch |

## Recommendation

**Merge with conditions.** Run `tick()` as a lifespan task in the API process, behind a switch that keeps the current container as a fallback.

### Gate before any code

1. Measure reader latency while a forced manual Run cycle runs (`POST /api/ingestion/run {"force": true}`) in today's API.
   - Use a probe that times `/api/feed` every 200 ms, or `PYTHONASYNCIODEBUG=1` to log callbacks slower than 100 ms.
   - This is exactly the load the merge would add, once an hour.
2. If p95 is fine, merge. If it is not, the manual path already has the bug, and conditions 3 and 4 below fix it for both paths.

### Minimal safe design

1. **Switch.** `INSIGHT_SCHEDULER=embedded|off`, default `embedded`.
   - `run_scheduler.py` stays as it is, so `ingestion` can come back as a compose profile with the API set to `off`.
2. **Lifespan task.**
   - In `lifespan`, `asyncio.create_task(scheduler_loop())` and keep the reference.
   - Do the `ensure_database()` work already done at start.
   - On teardown, cancel the task and await it.
   - In `tick()`, an `except CancelledError` finishes the open `ingestion_run` job as failed ("interrupted by shutdown"), then re-raises.
   - Set `stop_grace_period: 30s`.
3. **Single-scheduler guard.**
   - The task first takes `pg_try_advisory_lock(hashtext('insight.scheduler'))` on a dedicated connection held for the process lifetime.
   - If it gets the lock, it schedules. If not, it logs and idles, retrying every few minutes.
   - This covers `API_WORKERS > 1` and a stray old `ingestion` container. It reuses the `PgAdvisoryRunLock` pattern from `ports.py:222`.
4. **Keep fetch work off the reader's path.**
   - Move `parse_feed_posts` behind `asyncio.to_thread`. It is a one-line seam in each kind, or one wrapper in `parsing`.
   - Give ingestion its own small `ThreadPoolExecutor`, sized to `INSIGHT_FETCH_MAX_CONCURRENCY` + 2, so a hung or slow fetch never takes a default-pool thread from a reader route. Alternatively, enlarge the default executor with `loop.set_default_executor` at startup.
   - Add `cryptg` (or confirm libssl is found) for Telethon.
5. **Make the scheduler's sync DB calls run on threads.** `ops.start_job`, `finish_job`, `set_scheduler_state` and `sync_json_to_db` are fine in their own process, but would stall the API loop for milliseconds.
6. **Memory ceiling.** Set `mem_limit` on the merged container, roughly 2× the observed peak, so an OOM is contained by the cgroup and `unless-stopped` restarts it.
7. **Health.**
   - `/health` returns a `scheduler` field: `embedded`/`off`/`standby`, `next_tick_at`, and `stale: true` when `now > next_tick_at + 2×tick`.
   - Keep the HTTP probe as liveness.
   - Docker does not restart on unhealthy, so a stale scheduler needs to show in the UI's operations panel.

What this does not fix: an OOM or SIGKILL mid-run still leaves a "running" job row. That is true today too. A small reaper on startup could finish stale `running` rows as failed.

## Open questions for the owner

1. How many CPU cores and how much RAM does the home server have? This sets the default thread-pool size (cores + 4) and a sensible `mem_limit`.
2. Is reading during an hourly tick acceptable at the latency measured in the gate above? Is a manual Run cycle today ever noticeably slow for reading?
3. Once `INSIGHT_ANALYSIS=off` exists, should daily work (briefings and experts, the Gemini calls) also be off? If not, those LLM calls would run inside the API process. This is an argument for keeping `INSIGHT_SCHEDULER=off` plus the separate container whenever analysis is on.
4. Is "a code redeploy interrupts the current tick" acceptable? A tick is cadence-gated and idempotent, so the next tick picks up the due sources.
5. Should the switch default be `embedded`, with the `ingestion` service moved to a compose profile, or should both stay available with no default change until the latency gate passes?
