# 0215: The database's work, the rebuild's speed, the run after a stall (Stealth v10.20.1, v10.21)

Status: **v10.20.1 built** (branch `v10201` from main 85948b7a = v10.20): the decision run's catch-up limit and no
rebuild hold. Not merged, not pushed, not deployed. No migration. The v10.21 part (rebuild speed, progress counter,
jobs' memory, pg_stat_statements) is on `v1021-db` and written below once measured.

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
