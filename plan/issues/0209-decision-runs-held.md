# 0209: No decision run for 45 hours after the v10.18 deploy (Stealth v10.19.1)

Status: **built** (branch `v10191` from main 7ae45b8, v10.19). Not merged, not pushed, not deployed. One migration
(0142). Real rows stay in the private notes; no name from them is written here.

## The symptom (the server, read-only GETs, 2026-11-16)

- `/api/status` health: "the last Mark X decision run finished 45.8 hours ago". Ingestion succeeds every hour.
- `/api/markx/overview` → `worker.jobs.decide`: `started_at` 2026-11-14 09:56:27, `finished_at` 09:53:44, `stage`
  null, `wanted_at` 09:56:28, `failures` 0. `candidates` last ran 10:18. `plan`, `news`, `tracks` and `unread` keep
  running. `main_source`, `discover` and `official` have never run.
- `/api/operations/background` → the story job's last run: `computed_at` 2026-11-14 10:00:44, 180.74 s (it yielded
  at its budget), `rebuild` {done 0, total 157,752}. Links never read: 152 posts. **No story run since.**

## The mechanism: two jobs waiting on each other

The v10.18 deploy changed the rules stamp (0205: the stamp sees 0203's News rule), so a rule change's rebuild of
every post was due. Then:

1. A restart (the deploy's) ended the decision run that had started at 09:56:27. This is inferred from the row:
   no stage, no end recorded, and `wanted_at` one second later. Only `Runner.recover` writes that: it cleared the
   stage and set `wanted_at`, but recorded no end. So the row shows a start after its last end, for ever.
2. The API start's story job began the rebuild (keys first) and yielded after 180 s (10:00:44), with the rebuild in
   progress.
3. From then on, `jobs.mark_ix_busy` said "a rule change's rebuild is in progress", so `due()` never picked the
   decision run.
4. The story job runs only after a fetch that saved posts (hourly). From 10:06:28 (wanted + DECISION_WAIT_S) every
   run found the decision run "waiting" ten minutes and stepped aside (`{"skipped": "a decision run's turn"}`). It
   skipped before reading links, which is why 152 posts wait for theirs.

So the rebuild waited for the decision run, and the decision run waited for the rebuild. Neither could ever move.

**Reproduced** with main's code on a lab clone (a scratch script, not committed). The server's stories setting
and decide row were set as above, then three story-job runs were made:

| round | story job | mark_ix_busy | due() |
|---|---|---|---|
| 0, 1, 2 | `{"skipped": "a decision run's turn"}` | a rule change's rebuild is in progress | None |

**The leading hypothesis was refuted:** the rebuild's steps are not too big. They were measured on the scale clone
(148,152 posts) with main's code and the jobs role's timeouts (840 s statements, 960 s idle in a transaction):

| phase | steps | seconds a step | peak RSS of the step |
|---|---|---|---|
| the first (the boilerplate by the new rules) | 1 | 8.4 | 66 MB |
| keys (2,000 posts a step) | 75 | 0.3-0.7 | ≤ 133 MB |
| threads (one X source a step) | 16 | 0.2-1.0 | ≤ 173 MB |
| names (every name's surges + 0205's News over the window) | 1 | 17.8 (30-day window, 3.9k posts); 19.4 (90 days, 12.8k posts) | 351 MB; 360 MB |
| stories (1,000 queued posts a batch) | ~148 | 50-80 (mean 61) | 460-492 MB |
| the end (News over the window again, Discover over everything) | 1 | 4.1 (30 days); 3.9 (90 days) | 118 MB; 138 MB |

0205's News-over-the-window work runs in two steps only (names, end), never per batch. Tripling the window (3.9k
to 12.8k posts) adds 1.6 s and 9 MB to the names step. No step comes near a time slice, a statement timeout or the
memory limit. The 3-4 GB spikes in insight-ingestion are not the story job, which has not run since
10:00:44. A kept-views process records 1.4 GB peak (`news`, `tracks`, `unread` in one process). The official job's
crash loop (below) spawned a process at every idle look.

**Why official never ran:** mx_jobs' check constraint (0139) lists every job but `official`. `Jobs.official`'s first
write (`_begin`) raised a CheckViolation, so the child process exited with code 1. `_dead` records only a run with a
stage, so nothing was written. With no row, the job was due again at the next idle look: a spawned crash every
30 s. `main_source` and `discover` run only when a Discover open asks for them ("wanted"). Both rows show
`wanted_at` null, so nobody asked: that is expected.

## The fix (in the modules that own each decision)

- **markx/jobs.py `decision_hold`** is the one decision. A rule change's rebuild (due or in progress) holds a
  decision run at most REBUILD_HOLD (1 h) after the last decision run started. The story job's lock still holds it
  for a batch's seconds. Past the hold, the run goes ahead on the stories as stored, logged as "goes ahead on the
  stories as stored" and kept in its record (`last.mark_ix`).
  - Why not wait for the rebuild's end: on the server's posts the rebuild is hours of work, and days when only
    fetches drove it.
  - Why the stories as stored are safe to read: every rebuild batch commits whole, so they are always one
    consistent set. A decision run reads every story, so the next run decides again what later batches change.
  - So during a rebuild, decision runs come hourly instead of every 15 minutes.
  - Asked by the runner (`due`'s `busy`), by the story job (`decision_waits`) and by health.
- **stories_service `_decision_waiting`** asks `jobs.decision_waits`. It steps aside only for a run that Mark X is on
  for, that is wanted, not running, not backing off, has waited DECISION_WAIT_S, and that the rebuild doesn't hold.
  Stepping aside for a run the rebuild holds was the deadlock.
- **The rebuild always advances.** The jobs loop runs its slices (the job `stories`: `recompute_safely`, ≤ 180 s and
  one step, then the 90 s rest), STORIES_GAP (120 s) after the last slice ended, whenever a rebuild is due or in
  progress, with Mark X on or off.
  - Before, only a fetch that saved posts ran it: about 3 minutes an hour.
  - It is recorded with the rebuild's progress and its peak memory.
  - It counts as the reader's job, not Mark X's (`markx.ix_unchanged`).
- **A run that never finished is reaped.** `stale()` also lists a run with no stage whose start is after its last end
  and older than HARD_LIMIT + STALE_MARGIN. The runner records its end (`finished_at`, `last.error` "started at … and
  never finished") and wants it again. This is not a failure: a restart ended it, not its work. `recover()` now
  records the end itself, merged into the last record, so `candidates.mentions_since` survives.
- **No job starves.** A candidates run or an official pass due for STARVE_AFTER (15 min) goes before the kept views.
  The unread counts can be due at every look.
- **Official runs.** Migration 0142 adds `official` and `stories` to mx_jobs' check. A test inserts every name in
  `jobs.JOBS`, so a job added without its row fails in the suite. A single job whose process crashed before it
  recorded its start is now recorded as failed (backoff), not spawned again at every look.
- **Health names the hold.** The old-run reason gets "; held: …" (for example "a rule change's rebuild is in progress
  (1,200 of 157,752 posts regrouped); it holds a decision run until 60 min after the last one started"). It also
  gets `checks.markx.decision_held` and `checks.markx.mark_ix_rebuild`. A rebuild going on for over 2 hours is a
  warning with its phase and progress.

## Measured after (the scale clone, the head's code, the runner's loop)

The server's state was set on a fresh scale clone: the rebuild due, and the decide row unended since 45 h. Then the
jobs runner's loop ran as insight-ingestion runs it. The decision run and the candidate finder were stubs: a first
decision run on a scale clone is a full one, 1.5 h and 30 GB. Kept views and official were off. Results:

| at (s) | job | seconds | peak RSS | rebuild done / 148,152 | what it shows |
|---|---|---|---|---|---|
| 0 | (the first look) | | | due | the unended decide row reaped: "started at … and never finished", recorded as ended, no failure |
| 1 | decide | 1 | 52 MB | due | goes ahead on the stories as stored (the hold long over) |
| 230 | stories | 229 | 498 MB | 4,274 | the first slice: start, keys, threads, names and the first batches |
| 559-3255 | stories (9 slices) | 194-274 | 480-508 MB | 8,338 → 55,252 | a slice every ~330 s, held decisions named |
| 3580 | stories | 206 | 501 MB | 61,277 | |
| 3601 | decide | 1 | 495 MB | 61,277 | one hour after the last start: goes ahead during the rebuild, logged |
| 3902 | stories | 201 | 503 MB | 67,124 | the slices go on after it |

So 61,277 posts in the first hour, about 17 posts a second of wall time. The whole copy takes about 2.4 h and
the server's 157,752 posts about 2.6 h. The run was stopped at 67,124: the rate was steady and the last step was
measured on its own above. Before this change, fetches gave the same rebuild about 3 minutes an hour (about two days
of wall time), and the deadlock stopped even that.

Peak RSS before and after: main's rebuild steps measured alone peaked at 460-492 MB. The head's slice process peaks
at 480-508 MB. The steps did not change; the slice's process also holds the job's start (catch-up, links, refs,
series) and the Discover keep after it.

## Tests (module tests, then the full suite once)

- test_markx_jobs:
  - `TheRebuildHold`: the hold, the slice after the decision run, no starving behind the kept views.
  - `TheRunner`:
    - `test_the_2026_11_14_deadlock_ends`: the server's state; the story job doesn't step aside while the hold
      lasts, then does, and the run goes ahead with its record.
    - `test_the_rebuild_slices_run_here_with_mark_x_off_too`.
    - `test_a_run_a_restart_ended_is_wanted_again`: now with its end recorded, not a failure.
    - `test_every_job_has_its_row`.
  - `ADeadRun`:
    - a crash before the first write is recorded;
    - a run with no stage and no end is stale;
    - the runner records the end of a run that never finished.
- test_stories `test_a_run_steps_aside_for_a_decision_run_that_waited_ten_minutes`: never for a held run, then after
  the hold, never with Mark X off.
- test_system_health `test_names_why_mark_ix_holds_the_decision_run`.
- Test fixes: runner tests that read "nothing due" now switch official off. Before, its tick crashed at the check
  constraint and returned None.

Results:

- The full suite: 6 shards, 183 modules, 3,576 tests, OK. The first run had one failure, the stories test above
  (written for the old stepping aside), since fixed.
- `scripts/realdata-check.sh --base 7ae45b8 --head HEAD insight_lab`: **PASS**, 777 s. `markx.ix_unchanged` is 0,
  and 0 News lead changes. The report is in the private checks folder.

## On the server after the deploy

Nothing is done by hand. Migration 0142 runs at the API's start.

1. **The API's start story job steps aside.** The decision run has been wanted for two days and the hold is long
   over, so the job returns "a decision run's turn". The start then asks for a decision run.
2. **insight-ingestion's first look reaps the old run.** `stale()` finds decide's run of 2026-11-14 09:56, which
   started after its last end with no stage. It records the end as "never finished", not as a failure, and the run
   is wanted again.
3. **The decision run starts within a minute or two** (after the plan job, if that is due). The rebuild no longer
   holds it, so it runs on the stories as stored, logged as "goes ahead on the stories as stored".
   - It is a full run: decide's code stamp has changed since its last run (v10.18's and this change to
     stories_service), as after every deploy that touches those modules.
   - The Labels and News views follow it as usual.
4. **The rebuild resumes.** The stored rebuild is at done 0: its first 180 s ended before any batch was counted. So
   nearly the whole rebuild runs: what is left of the keys, threads and names (about two minutes at most), then
   every batch. If the stored rebuild was made by other rules than this code's, it starts again from its keys, which
   costs the same two minutes.
   - The slices come from the jobs loop: about 210 s of work, the 90 s rest, then the next look. Fetch-driven runs
     add to them.
   - A decision run goes ahead every hour on the stories as stored, then the slices go on.
   - On this machine: about 17.5 posts a second of wall time once the batches run, with no other load. That is
     about **2.5 hours for 158k posts**. Allow 3-4 hours if the server's cores are slower or busier: under this
     machine's full test suite the batches took 70-100 s instead of 50-58 s.
   - Memory: at most about 0.5 GB in the slice's process.
   - The end step (News over the window, Discover over everything): about 4 s.
   - After the rebuild, decision runs go back to every 15 minutes when wanted, and the source stats run follows
     ("after a regroup").
5. **Health shows the rebuild.** While it runs, /api/status warns "Mark IX's rule-change rebuild began … ago: n of
   157,752 posts regrouped (… phase)". `/api/operations/background` shows done of total. The decision-run reason
   clears after the first run finishes.
6. **Official channels run for the first time on this server.** Their default mode is shadow (INSIGHT_OFFICIAL
   unset), every 30 minutes, with their own budgets. This was meant to start with v10.18, but the check constraint
   stopped it. `INSIGHT_OFFICIAL=off` in `.env` keeps them off.
7. The 152 posts whose links were never read are read at the first story run that does not step aside.

## Also in v10.19.1

The owner's decision of 2026-11-16: only Haiku. alias4's Sonnet routing is removed, and `identity.model_for` refuses
any model that is not a Haiku. See [0201](0201-entity-queue-haiku-decides.md), last section.
