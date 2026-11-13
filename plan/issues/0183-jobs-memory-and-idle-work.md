# 0183 — The Mark X jobs' memory and idle work (v10.16 slice Q)

Status: **built** (branch `v1016-memory` from the integration branch v1016, 4e9da6a). Not merged, not pushed, not
deployed. No migration (the kept stamps are rows of mx_inc_state, 0113).

## The problem (the owner's Grafana, server on v10.15.1, ~156k posts, ~250k entities)

- Evening, workers uploading: insight-ingestion's RAM spikes to 7.0-7.75 GiB every ~5 minutes (mean 4.77 GiB).
- Overnight, 12 h with **no worker and no upload**: still a spike every ~5 minutes (max 6.58 GiB, mean 3.08 GiB);
  CPU at 100% hourly (the ingestion run) and smaller spikes every few minutes.

With nothing uploaded the 5-minute work is the plan job (jobs.PLAN_EVERY): the background planners check, cite and
track (tasks.BACKGROUND_PLANNED), each reading all it reads every time, to plan nothing. The decision run also runs at
least hourly (jobs.EVERY).

**Where the jobs run.** Every job already runs in a child process (`multiprocessing` "spawn": one job, then the
process exits), so what a pass reads goes back to the OS when it ends: the spikes are a child's own peak, not a leak
or glibc arenas of a long-lived process. Nothing was changed there (no MALLOC_ARENA_MAX / malloc_trim needed).

## How it was measured

A server-sized scratch copy built for this slice (/tmp was wiped by a reboot; slice M's builder was gone): 148k posts
(the server copy cloned one and two years back), Mark IX's stories (18.5k story posts), 1.12M tasks and calls
(a read-v2 reading and an ent-v4.2 entities answer for every post, 889k mentions, padding kinds), 130k vectors
(HNSW), 4 topic tracks with 48k judged items and 100 owner labels each, reading window and story window
"everything" with the backfill at the oldest post (the widest check), the planners brought to their steady state, then
four decision runs over a fake worker's answers (95k entities, 6.5k Mark X stories). Each measurement in a fresh
process, as the runner's child: seconds and peak RSS (VmHWM, reset per planner / per stage), and a digest of every
mx_* row the pass wrote (ids, times and durations masked), in a transaction rolled back unless it says otherwise.
PYTHONHASHSEED fixed, parallel scans off.

The machine was shared with other agents' test runs (load 10-17): **seconds swing 2-4x between identical runs**;
peak memory and the digests are stable. The seconds below are the quietest of each.

## Results

### The plan job (every 5 minutes)

| pass | before | after | equivalence |
|---|---|---|---|
| idle, whole job (check, cite; track at its open-task cap) | 21-23 s, peak 336-339 MB | **0.9 s, peak 43 MB** (check and cite skipped) | a full run of each planner at that state adds 0 tasks and writes nothing: digests equal to the database as it stands |
| idle, the first pass after a change (the no-op that keeps the stamp) | 21 s, 339 MB | 19 s, **107 MB** | same digests |
| check alone (a full pass) | 9.0 s, 338 MB | 8.9 s, **105 MB** | same tasks |
| cite alone (a full pass) | 4.5-8 s | 4.8-6 s (+~0.5 s: two stamps) | same tasks and marks |
| busy (300 new posts, their entities answers, two new stories, 40 edits) | check +1, cite +48 | the same, peak 105 MB (was 338) | mx_tasks, mx_plan_marks, track rows identical |
| track, room left (300 tasks planned) | 6.8-7.9 s, 72 MB alone | unchanged (always runs: see below) | |

On this copy the plan job's peak was 339 MB; the server's spike is about 3.5 GB over its mean. The share the plan job
has of it can't be read from here (see "Not done").

### The decision run (hourly, and SETTLE after work)

| run | before | after | equivalence |
|---|---|---|---|
| full run (forced, entities budget 0 so both stop at the same chunk) | peak 1,627 MB in entities, 945 MB in surges | **1,408 MB** in entities, **664 MB** in surges | every mx_* table identical; mx_runs differs by the before run's own `check` reading (its kept key matched; the after code's key differs, so no check reading) and mx_inc_state by its key (code stamp) |
| incremental, nothing new (entities: the resumable full pass under its 45 s budget) | 90 s; peak 1,207 MB in entities, 607 in surges | 117-144 s (under load); peak 1,031-1,204 MB in entities (the resumable pass's chunk differs run to run), **486-501 MB** in surges | (the full runs above) |

Stage seconds, incremental idle before (quietest): load 0.3, questions and decisions 6.8, write 0.3, connections 3.4,
graph 3.1, back 14.0, headlines 2.4, news 2.2, entities 52.0 (budget 45), surges 0.2, perspectives 1.9.

## What was built

1. **One rule for a pass that would change nothing** (`markx/unchanged.py`, `run(cur, name, tables, key, work)`): a
   pass declares the tables it reads and writes and a key (its code, its settings as it computes them). Its inputs'
   stamp is the key and each table's stamp (rows, newest row version, a sum of the row versions' hashes: one aggregate
   a table in Postgres, nothing held in Python). The stamp is taken before and after the pass in its own transaction;
   when they are equal the pass wrote nothing it reads and nothing it reads changed meanwhile, so it was a no-op on
   those inputs, and the stamp is kept (mx_inc_state, row `unchanged:<name>`). The next pass whose stamp equals it is
   that same no-op on the same inputs: skipped. Any change (a post, an answer, a task, a setting, a deploy, the
   window's next day) runs it in full, as before. A key of None: the pass depends on the clock itself and always runs.
   The table stamp is the one the decision run's incremental state already used (`incremental.table_stamps`, moved
   here: one stamp for every pass).
2. **The planners' declarations** (`tasks.BACKGROUND_INPUTS`, `tasks.background_inputs`): check (posts, parts, links,
   sources, story_posts, readings, tasks, settings, guides; key: the story window's days as the run computes them,
   check_threads, the code) and cite (posts, parts, links, sources, tasks, plan marks, settings, guides; key: the
   reading window, the entities guide, the code). Why the clock is not in their key: within a day it only narrows their
   windows (now - days): a post that leaves a window adds no question, and an age is only a new task's priority; the
   window's length in days is in the key, so its next day runs them. **track** has no declaration: its bar is the share
   of the last 30 days' posts a probe passes, and its windows move with the clock, so a later pass may plan what an
   earlier one did not; it always runs (it is cheap when its open tasks are at the cap, as overnight with no worker:
   0.0 s).
3. **jobs.py, the gate only** (`Jobs.plan_background`, 9 lines): each kind's pass is
   `unchanged.run(cur, "plan:" + kind, *tasks.background_inputs(cur, kind, self.clock()), lambda: tasks.PLANNERS[kind](cur))`;
   a skipped kind is recorded as `{"unchanged": true, "seconds": s}` in mx_jobs.last. Nothing else in jobs.py changed.
4. **check reads its stories a chunk at a time** (`tasks.check_questions`, CHECK_CHUNK = 500 stories): the posts and,
   of their readings, only the kind (`tasks.reading_kinds`); was every story's texts and whole readings at once. The
   wide window's sort keeps (time, id, input), not the posts. The same questions in the same order (a test compares
   chunks of 1, 2 and all).
5. **The decision run lets go of what it no longer reads**: the entities stage's book before the next book is read
   (`decide.run`: both were held to the run's end), and the texts and readings the stages up to News read
   (`incremental.release`, before the entities stage: a full run held every text beside the book). A text used after
   is read again from the run's one snapshot.
6. **identity.Pooled** with slots (no per-pair dict; a full pass pools every pair of a family).

**Deeper, deleted.** markx/unchanged.py is the one place that decides "nothing changed" for any pass (planners now,
any other pass by declaring its tables and key); `incremental.table_stamps` was deleted from incremental.py (it uses
unchanged's). Deleted: check_questions' whole-world load and its use of whole readings.

## Proved

- `test_markx_unchanged`: the rule (a no-op keeps, the next is skipped, a change to a named table or the key runs
  again, a pass that writes what it reads keeps nothing, a key of None always runs); cite and check through the
  plan job's declarations: busy, no-op, skipped, and **the planner run anyway where it was skipped adds nothing and
  writes nothing**; an edit, a new story and the window's next day run them again; chunked check = whole check.
- On the copy: the skipped state's full planners (before and after code) add 0 and leave mx_tasks and mx_plan_marks
  as they are; busy passes identical before and after; full decision runs identical table by table.
- Test fixture: `_Api` clears mx_inc_state (two tests' empty tables have equal stamps).

## Not done

- **The hourly decision run is not gated.** Its outputs move with the clock by design: News' window and the surges'
  days, the nightly full pass and the resumable entities pass, the briefing hour, back's and later's clocks; and every
  run writes its own row and state. A run on unchanged tables is not a no-op, so `unchanged` would never keep it.
  Skipping it would change what the owner sees; it stays hourly. What it holds was cut instead (5, 6).
- **The server's 3.5 GB spike is not reproduced here.** The plan job peaked at 339 MB on this copy (now 43-107 MB),
  the decision run at 1.2-1.6 GB with 95k entities (server: 250k). One reading fits a ~5-minute cadence of a
  decision-run-sized peak: a run stopped over LIMIT (TooLong) is wanted again and runs again after GAP (5 minutes),
  each time reading its world, and is stopped again. The server's mx_jobs row for `decide` (last.ok, stopped_before)
  and its log lines "nothing written, it runs again" would say; not looked at (no server access from here).
- The synthetic entity names make one huge family (identity's pool held 762k pairs; the server's 120-day pass pooled
  ~29k), so the entities stage's peak here is larger than its real share.
- Seconds on this machine were too noisy for small differences; the stamp itself costs ~0.3-0.5 s a pass.
