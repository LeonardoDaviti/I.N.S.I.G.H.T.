# Development workflow

How agents and the owner get a database, run tests and run the real-data check without redoing work. Tooling
only: none of this touches the server or the product code.

## Two Postgres servers: durable and scratch

| server | container (on `insight_insight-network`) | holds |
|---|---|---|
| durable | `insight-db` (`postgres:5432`) | the owner's databases and originals: `insight`, `insight_lab`, `insight_server_1105*`, `insight_preview`. Only read by the tools below |
| scratch | `insight-scratch-db` (`insight-scratch-db:5432`) | everything copied, migrated, tested and thrown away: test runs, real-data check copies, prepared copies and their clones |

`scripts/scratch-db.sh up` starts the scratch server (the tools below start it themselves); `status` lists its
databases. It is tuned for throwaway data (fsync, synchronous_commit and full_page_writes off, 8 GB shared buffers,
checkpoints every 30 min or 16 GB of WAL): a CREATE or DROP DATABASE there never waits for the disk. A crash can
corrupt it; `scripts/scratch-db.sh recreate` and a rebuild of the prepared copies bring it back. Never put anything
there you cannot make again.

Why: on one server, every CREATE/DROP DATABASE forces a checkpoint, and with ~6 suites, the real-data check and
scratch builds writing at once, checkpoints took 10-20 minutes; drops queued behind them and every agent's tests
stalled (a 15-test module: 7 min 41 s; one suite hit a 1 h timeout).

## A scratch database in seconds: prepared copies

`scripts/prepared-db.sh` keeps one ready database per real-data snapshot, already migrated and backfilled, on the
scratch server. Clone one instead of copying a snapshot and migrating it yourself:

```bash
scripts/prepared-db.sh list                              # the prepared copies, their commit and last migration
scripts/prepared-db.sh clone lab insight_mywork_scratch  # a copy of prep_lab; prints its DSN (insight-scratch-db)
scripts/prepared-db.sh drop insight_mywork_scratch       # when done (drop only what you made)
scripts/prepared-db.sh refresh lab                       # only the NEW migrations and backfills (see below)
```

| prepared copy | from | use it for |
|---|---|---|
| `prep_lab` | `insight_lab`: 41.6k posts to 30 Oct, the lab's labelled cases | Mark IX reading, stories, News, Discover, Classics; anything the judged cases (`plan/research/lab/cases.json`) cover |
| `prep_server1105` | `insight_server_1105`: 49.4k posts to 5 Nov (the server's sources) | the server's real mix of sources and posts without Mark X answers |
| `prep_mxreal` | `insight_server_1105_mxreal`: the same with real Mark X answers (read-v2, ent-v3, vectors) | Mark X decisions, stories, News, entities on real answers |
| `prep_scale` | `prep_mxreal` inflated (`scripts/prep/scale.py`): 148k posts, ~1.06M tasks, ~0.95M calls, ~840k mentions, ~130k vectors, ~450k candidates, 4 tracks, the full story job and decision runs over a fake worker's answers | load, memory and speed at the server's size (the v10.16 slice M copy, now a committed deterministic builder) |

The DSN a clone prints is on the scratch server: `postgresql://insight:insight@insight-scratch-db:5432/<db>` from a
container on the compose network (`docker exec -it insight-scratch-db psql -U insight -d <db>` from the host).

Each prepared copy is migrated to a ref (default: this checkout's working tree) and has the standard backfills
run with that ref's code (`scripts/prep/backfills.py`): post refs, the search refill and Mark X's English layer,
the handle scan, happening keys, the round-up split, and the start's story job to the end. Its stamp says which:
`scripts/prepared-db.sh stamp <db>` (also in the table `prep.stamp` inside every clone).

- **The originals are never modified**: each is copied over to the scratch server once (`src_<original>`, by
  pg_dump, read-only) and every build starts from that copy.
- A prepared copy refuses connections, so nobody holds it open and a clone never waits. Clone it; never work in it.
- **Your branch adds a migration?** Clone, then migrate your clone (`MIGRATE=1`, or `python -m
  insight_core.db.migrate` with `DATABASE_URL` your clone): only your migrations run. Don't refresh the shared copy
  to your branch; refresh it to `main` after a merge (`refresh <set> --ref main`), which applies only what is new.
- `build <set> --rebuild` makes one from its snapshot again (`--remirror` copies the original over again); never
  needed for a new migration.

## Tests: module tests while developing, the full suite once at merge

```bash
scripts/test-backend.sh insight_core.tests.test_markx_news       # while developing: the modules you touch
JOBS=6 scripts/test-backend.sh                                    # once, before the merge: the whole suite
```

- The runs' databases are on the scratch server (`SCRATCH_DB=0`: on insight-db, as before).
- The image is tagged by the backend tree's content: an unchanged tree is not built again.
- Each run's database is a copy of a migrated template (`insight_tmpl_<hash>_test`, made once per set of
  migrations), not a database migrated from nothing; every run (every shard) still has a database of its own, so
  runs at once never share rows.
- `JOBS=n` splits the whole suite by module into n shards, each in its own container and database, the slowest
  modules dealt first (by the last run's times). The result line counts the modules and tests; a failed shard's log
  stays in `~/.cache/insight-prep/shards/<pid>/`. Within a shard the modules are imported first and run in name
  order, as `unittest discover` did (some tests mix several modules' import-time `NOW`, some read what earlier
  modules left); `DISCOVER=1` runs the old single `unittest discover`.
- A run's databases are dropped in the background when it ends, and a run first removes what ended runs left
  behind: their test containers and `insight_run_<time>_<pid>_*test` databases (on both servers) once the pid is gone
  and they are 10 minutes old and unused, or anything of theirs over `CLEAN_HOURS` (6) old (`CLEAN_ORPHANS=0` skips,
  `=dry` lists).
- Run the full suite once per slice at merge time, not after every change.
- Tests empty tables with `tests/_db.clear_tables(cur, tables, cascade=False)`, not `TRUNCATE`: a TRUNCATE makes
  new files and syncs every empty index (11-48 s for the Mark X tables on a busy disk; the DELETE 0.36 s).
- A test that waits on the wall clock fails under load: inject the clock (`now=`), poll for a condition with a
  generous deadline instead of a fixed `sleep`, and bound "it did not hang" assertions far below the hang but far
  above a busy machine's latency.

The disk is slow under sustained writes (a QLC NVMe under LUKS: 30-60% of the time every process waited on I/O while
several agents copied databases on insight-db). Every copy writes its full size: clone what you need, drop it when
done, and prefer one shared prepared copy to several private snapshots.

## The real-data check: the base side is cached

`scripts/realdata-check.sh <db>` reads `<db>` on insight-db (one pg_dump) and makes its scratch copies on the
scratch server. It keeps the base side's outputs (story job, snapshot, invariants, cases, job checks) in
`plan/research/lab/checks/base-cache/`, keyed by the base's backend tree, the copy's content (its dump restored as
SQL, hashed), the checks' code, the cases file, the image and `--now`. A second check against the same base and copy
runs only the head side. `--no-cache` runs the base again (and replaces the entry). The report says when the base
came from the cache.

## Measured (2026-11-13, v10.17; the machine shared with ~6 other agents' suites)

| what | before | after |
|---|---|---|
| a usable copy of lab / server1105 / mxreal | 8 min 47 s / 15 min 37 s / 15 min 56 s (template copy, migrations, backfills on insight-db) | 0.6 s / 0.55 s / 0.6 s (a clone of the prepared copy, scratch server; 3 suites running) |
| a server-scale copy | hours, rebuilt by hand from scripts lost in /tmp | `build scale` once, then a clone |
| one 15-test module | 29 s to 7 min 41 s (template build, drop waiting for checkpoints) | 7.4 s |
| the whole suite | 152 min 22 s (one discover on insight-db; 1 failure) | 8 min 49 s (one shard), 3 min 18 s (`JOBS=6`), scratch server |
| the real-data check | 2,019 s (v10.15), 1,675 s fresh | 919 s with the base side from the cache |

## Nothing durable in /tmp

A reboot wipes `/tmp`. Scripts you will run again go in `scripts/` (committed) or `plan/research/` (private);
databases live in the database containers; caches in `~/.cache/insight-prep/` or `plan/research/`. A scratch
builder in `/tmp` is a builder you will write twice.
