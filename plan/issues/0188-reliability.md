# 0188 — Reliability: jobs that back off, timeouts, health that tells the truth, backups, migrations, growth, limits

Status: **built** (branch `v1017-reliability` from the integration branch v1016). Not merged, not pushed, not
deployed. Migration **0129** (mx_jobs.failures; Mark X tables only, no row changes).

A read-only audit of v1016 found eight classes of operational failure. Each is fixed with one mechanism, in the
module that owns it; nothing is deleted (keep everything): sizes are reported, never pruned.

## 1. Jobs retried forever → a backoff, "failing", and a stage skipped once

**Was.** Every failed Mark X run set `wanted_at` again; `due()` had no failure count: a TooLong run came back every
GAP (300 s), a run killed at HARD_LIMIT or by the OOM killer at the next 30 s look: the identical run, over and over
(0183's 5-minute RAM spikes on the server fit this).

**Now** (markx/jobs.py, one decision: `held`, asked by `due` for every job).
- `mx_jobs.failures`: failed runs in a row. `_finish` adds one for `ok: false` (not for a run skipped for another's
  lock), clears it on `ok: true`; `_reap` (a dead run) and `_dead` (killed, crashed) add one too.
- The next try waits `GAP x 2^failures` after the failed run's end (10, 20, 40, 80 min ...), at most 6 h, and keeps
  trying at that pace. `failing` from 3 in a row (`FAILING_AFTER`); `view()` gives `failures`, `failing`, `retry_at`.
- TooLong records `over_in` (the stage that ran past the limit). Two TooLong runs in a row over the same deferrable
  stage (`SKIPPABLE`: graph, back, later, entities, surges, perspectives_plan) → `skip_next`; the next run passes
  `skip` to `decide.run`, whose `guarded` defers that stage (the same path as a stage that met a concurrent update:
  `counts.deferred`, a warning in the log, `skipped_stages` on the job). The run after tries the stage again. A core
  stage (load, questions and decisions, write, connections, headlines, news) is never skipped; the backoff alone.
- The labels job's own "GAP after a failed build" is replaced by the same backoff.
- /markx: "It runs again after <time>", "without its <stage> stage once", "Failing: N runs in a row".

## 2. Database timeouts → by role, set where connections are made

**Audit correction.** A 5-minute `statement_timeout` already existed on every pooled connection (db/database.py);
missing were an idle-in-transaction limit, a request-sized limit, and anything ending a killed client's statement.

**Now** (db/database.py; `INSIGHT_DB_ROLE`, set by run_scheduler.py → "jobs" and api_supervisor.py → "api";
spawned job processes inherit it):
- jobs: `statement_timeout` 840 s (under HARD_LIMIT 900 s), `idle_in_transaction_session_timeout` 960 s.
- api: process default 5 min (background tasks: archives, fetches, research), idle-in-transaction 2 min, and a
  request's own statements 30 s: `RequestTimeouts` (pure ASGI, added innermost in main.py) sets a context variable
  until the response's last body is sent, so background tasks Starlette runs after it have the default. The pool sets
  the timeout on checkout only when it differs from the connection's (one round trip on a switch). Opt-out:
  `with long_statements():` (deleting a source: the cascade can take minutes). `INSIGHT_DB_REQUEST_TIMEOUT_MS=0`
  turns the request limit off.
- every connection: `client_connection_check_interval` 10 s: a statement whose client died (killed at HARD_LIMIT or
  by the kernel) ends within seconds and frees its locks. Tested: a spawned "job" holding an advisory lock in a
  `pg_sleep(120)` is SIGKILLed; the lock is gone within the check interval.

## 3. Health that tells the truth

- `/api/status` `healthy` was a literal `True`. Now `OperationsService.system_health`: reasons (ingestion's last
  success older than interval + 2 ticks; the scheduler's next tick 2 ticks overdue; a stale heartbeat; Mark X job
  failing; no decision run finished in 2 x EVERY), warnings (failing sources, workers silent > 3 days), checks.
  `health`, `table_sizes` added to the response.
- Heartbeats (utils/heartbeat.py, standard library only): the scheduler's event loop beats every 30 s from a task of
  its own; Mark X's loop after each look (limit 2000 s: a decision run and the labels build after it, HARD_LIMIT
  each). Files in the logs volume (`/app/logs/runtime/heartbeat-*`); Mark X's is cleared at the scheduler's start.
- insight-ingestion's healthcheck: `python -I insight_core/utils/heartbeat.py` (was a /proc grep a hung loop passes).
- Workers: `news.workers_view` marks `stale` (silent > 3 days); shown on the /markx page.

## 4. Update with backup and rollback (owner: no deploy friction; backups were declined before)

- `./update` tags each build `insight-*:<version>` and `:<commit>` beside `:latest` (cheap; `INSIGHT_IMAGES_KEEP`=3).
  `./update --rollback <tag>` retags and `up -d --no-build`, refuses if the images are missing; `--images` lists.
- The pre-migration `pg_dump -Fc` into ./backups is **opt-in** (`INSIGHT_BACKUP_ON_UPDATE=1`, default off); when on,
  a failed dump stops the update with the old version serving.
- `scripts/backup`: the database (`-Fc`, checked), the `insight_secrets` volume and `.env` (mode 600/700, a warning:
  they hold secrets), last `INSIGHT_BACKUPS_KEEP`; `--restore <dir>`. contrib/systemd/insight-backup.{service,timer}.
- DEPLOYMENT.md: the manual dump to /tmp → ./backups with -Fc; restore; rollback.

## 5. Migrations

db/migrate.py: one transaction per migration (with its schema_migrations row), runners serialized by a session
advisory lock for the whole run; `SET LOCAL lock_timeout` per migration (`INSIGHT_MIGRATION_LOCK_TIMEOUT`, 10 s) with
retries (`INSIGHT_MIGRATION_LOCK_RETRIES`, 5); a file marked `-- no transaction` runs statement by statement in
autocommit (`CREATE INDEX CONCURRENTLY`). Big data rewrites belong in resumable jobs. `--pending` prints the tables
each pending migration touches with row estimates. Left: the archive restore (db/import_export.py) still applies
migrations in one transaction; it would fail on a future `-- no transaction` file.

## 6. Growth

- compose: json-file `max-size` (`INSIGHT_DOCKER_LOG_SIZE`, 20m) and `max-file` 5 on every service.
- logs/ files: `SharedRotatingFileHandler` (logger_config.py): WatchedFileHandler (each write to the file now at the
  path; O_APPEND) + rotation under an flock after re-reading the size. Chosen over stdout-only because the Ingestion
  tab's log view and the API watchdog read these files; RotatingFileHandler shared by the uvicorn processes, the
  supervisor, the scheduler and every job child rotated per process and lost or misplaced lines. Tested with three
  processes: 900 lines, none lost or torn, every file near its limit.
- The worker's log.jsonl rotates at 10 MB, 4 kept, under an flock.
- `/api/status.table_sizes`: the 15 biggest tables (pg_total_relation_size, row estimate). mx_calls is kept.

## 7. Resource limits

`mem_limit` from `.env`, above measured peaks so no normal run is ended (a limit that kills healthy runs is worse than
none): ingestion 12g (server spikes 7.0-7.75 GiB, 0183), API 10g (3.2 GB at most before 0186; an export's 7.5 GB in
0186's harness), db 6g, frontend 256m; a frontend healthcheck (wget). The kernel then ends the biggest process of
the container over its limit (a job's child: a failed run, backed off), never Postgres. Minimum host (DEPLOYMENT.md):
16 GB RAM and 4 cores for a server-sized corpus.

## 8. Workers survive reboots; no working state in /tmp

contrib/systemd: markx-worker.service + .timer (Persistent=true, shipped disabled: the owner runs the worker by hand),
llama-server.service (Restart=on-failure); user units and `loginctl enable-linger` in DEPLOYMENT.md. The export's
progress files moved from /tmp to the logs volume (`INSIGHT_LOG_DIR/runtime/export-progress`; 0112 still names
/tmp/insight-runtime). The worker's state was already in ~/.local/state.

## Tests run (only the modules touched; the shared Postgres is busy)

test_markx_jobs (all), test_markx_decide.Snapshot, test_database, test_system_health, test_logger_config,
test_api_supervisor, test_migrate_runner (fork), scripts/tests test_markx_worker*, frontend markx.test.tsx.
Not run: the real-data check (one run on main per release).

## On deploy

Nothing required. Migration 0129 adds a column. Optional in `.env`: the memory limits, `INSIGHT_BACKUP_ON_UPDATE=1`,
`INSIGHT_DB_REQUEST_TIMEOUT_MS`. Rollback works from the second update with this code. After the deploy: read
`/api/status`'s `health.reasons` and `table_sizes`, and `docker ps` for insight-ingestion and insight-frontend healthy.
