# 0221: The entities stage on the server (Stealth v10.24)

Status: **built** (branch from origin/main = v10.23, 2dce4786; commits b9419843, 9fd3363a, 5e8b568e). Migration: none. Not merged, not pushed. Module tests
only (the full suite and the real-data check are the owner's session's). Scripts and logs: `plan/research/v1024-server/`
(private). The reading's code is unchanged (incremental.READING_MODULES): the first decision run after the deploy is
not forced full.

## The server (read-only GETs, 2026-11-17 07:42-07:45 UTC, one at a time)

`/api/markx/overview` (worker.jobs.decide.last, worker.last_run.counts.entities) and `/api/operations/db-statements`,
plus the snapshots in `plan/research/v1022/observe-2026-11-16/` and `v1023/observe-2026-11-17/` (main checkout):

| | v10.22 (11-16 14:39, 14:54) | v10.23 (11-17 06:56) | v10.23 (11-17 07:28) |
|---|---|---|---|
| the run / its entities stage | 118 s / 69.4 s | 184 s / 71.8 s | 155.7 s / 86.8 s (budget 45) |
| repair.seconds (steps run) | 5.5-5.9 s (all four) | 13.8 s (org_family, product_accounts; reparent, families "budget") | 17.0 s (the same two) |
| linking (`incremental`) | 1 part of 13, left 5,542 | 1 of 13, left 5,510 | 1 of 13, left 5,504 |
| full pass (`full`) | 0 chunks, started 11-11 | 1 chunk (of 74 left) | 1 chunk (of 73) |
| timing: pool / vectors / paren / facts / load | 8.1 / 8.9-10.7 / 0.1 / 2.0 / 2.6-2.8 | 13.2 / 13.3 / 5.9 / 2.2 / 4.9 | 16.0 / 13.8 / 8.0 / 2.8 / 5.4 |
| peak | 1,178-1,436 MB | 1,109 MB | 617 MB |

db-statements: the 20 top statements are the pages', the jobs' and the nearest names' (mean 11.3 s a chunk of 1,000
seeds, 113k blocks read a call: the HNSW index from disk); none of the repairs' statements is in the top 20 (each is
small: their cost is their number). The book's redirect read returns 25,019 rows a call (403,256,824 rows in 16,118
calls): **~25k current merges** on the server. Index sizes: mx_entities_pkey 13.6 MB (~340k entities),
mx_mentions_pkey 128 MB.

## The clone: S3, the server's shape

`prep_scale` migrated to v10.23 and filled as 0218's S1/S2 were (`rebuild.sh`: fill A, the seed run, fill B, the fake
worker, fill C1; 1,557,089 mentions, 332,800 names, a name vector each, 359k alias tasks, 7,252 mentions not linked
yet; S2 = S1 + a full pass half done at 36% of the ids), then **S3 = S2 + the server's merges** (`fill_s3.sql`):
24,610 redirects making 14,073 clusters of 2-3 names, and 3,000 org names of a family's name with a word in front
("Zentra Vela"), 1,500 of them merged in pairs (750): **25,360 current redirects** (the server: ~25k), 332,800 names. The clones before had **no cluster of
several names**: that is why 0218's measurements (S2: repairs 3.5 s) did not see the server's 13.8-17 s.

**The server's pace.** The planner runs with the server's settings (`SRVPLAN`: random_page_cost 4,
effective_cache_size 4 GB, work_mem 16 MB) and the entities stage's Python at **35% of a CPU** (`systemd-run
CPUQuota=35%`): with it, the base reproduces the server's run: 1 linking part of 13 (left 5,500), the repairs 21.2 s
(server 13.8-17.0), the pool 9.1 s (server 13.2-16.0), the facts 2.65 s (server 2.2-2.8), the stage 71.8 s (server
71.8-86.8). Not reproduced: the server's disk (the clone's first run on a fresh copy is cold in its own way: 18-106 s
of one statement, the run's book's snapshot or the first `load`, seen once a clone), the server's real names (the
synthetic ones meet fewer families), the HNSW reads (11.3 s a 1,000-seed chunk there, 2-7 s here).

Kept on the scratch server: the templates `v1024srv_s1` and `v1024srv_s3` (S2 = S1 + `fill_s2.sql`; S3 = S2 +
`fill_s3.sql`), ~9.7 GB each; `s1pair.sh` and `seq.sh` clone them. Drop them when done.

## Why: the causes, with the evidence

1. **The repairs, 5.5 -> 17 s: ~30k statements a run.** v10.23's run book (RunBook) answers `Book.sides`,
   `product_of` and `maker_keys` one name at a time: each cluster's org names of several words asked the database for
   their last words' aliases and families, then each family's cluster, versions and makers. On S3: **org_family
   21,566 statements, product_accounts 7,851** (v10.22: none, the whole book in memory). Each is small (they are not in
   the server's top 20); on the server ~0.5 ms each with its round trip: 13.8-17 s, past the repairs' quarter of the
   budget (11.25 s), so reparent and families were skipped every run. Not b070c44f's narrowing (it cut the walk's
   rows): the per-name reads under it.
2. **The linking did 1 part of 13 a run for days.** The budget was spent before it: the repairs first (13.8-17 s),
   then the linking had LINK_SHARE (half) of what was left, and its first part carried the run's once-a-run reads (the
   pool's indexes 13-16 s, every post's handles and addresses 2.8 s) and the first part's answered pairs. The newest
   500 mentions were linked each run; the older ~5.5k waited (`left` 5,504-5,547 since 11-16).
3. **The pool's indexes, 15 s.** `RunBook._build`: one read of every entity (332,800) and, in Python, the gram,
   squashed-key, family and maker indexes and the family values. CPU-bound: 3.2-3.5 s on this machine, 7.6-9.9 s at
   35% of a CPU, 13.2-16.0 s on the server. v10.22 did the same index work from its whole book (pool 8.1 s there) and
   read the book separately; v10.23 moved the read into `pool`. Its SQL is one hash join (0.6 s warm): the time is
   making 332,800 entities and their keys.
4. **The full pass: a chunk every other run.** v10.22.2's rule: a run whose linking spent the budget runs no chunk,
   never two runs in a row; a chunk is 1,000 seeds, ~25 s on the server (its nearest names 11 s from disk). The stage
   ran 30-40 s past its 45.

## What changed

- **The repairs ask the run's book what the product test reads, in one go** (b9419843; identity.RunBook
  `prime_names`, `prime_makers`, `prime_sides`; used by org_family, the invariants, reparent, the families and
  product_accounts' pages). **org_family 21,566 -> 13 statements, product_accounts 7,851 -> 189**, the same answers.
- **One budget, spent in the order of what matters** (identity.stage, entity_stage.entities): the run's book, then
  the linking (every part until the mentions are linked), then the full pass, then the repairs (resumed at the step
  the last run left), the shown names' sweep, the invariants, the addresses' sweep, the renames, the handle scan. A
  unit (a part, a page, a chunk, a repair step, a sweep step) starts only when the seconds it is expected to take are
  left: the last one's (a part's: its seconds, the once-a-run reads left out, plus its mentions' collisions at the
  last run's `collide_rate`); a full-pass chunk is sized to the time left at the pace the last run measured (`rate`,
  seeds a second, `PACE_MARGIN` 0.8). Nothing starts past the budget but the first unit of the most urgent work
  pending: the linking's first part, or, when nothing waits to be linked, the full pass's first page or chunk.
  LINK_SHARE, REPAIR_SHARE and v10.22.2's chunk every other run are gone.
- **A pass half done never starves what comes after it.** It lasts days on the server, and every run is "whole"
  meanwhile: it leaves (`keep`) what the repairs' next step, a shown step and the invariants took in the last run
  (`entity_stage.after_pass`; guesses for what never ran), and each of those leaves the next its own.
- **Resumable**: the repairs record `{done, next, took}` and the next run begins at `next`; the shown names' sweep
  checks before each step (`steps`, `seconds`), and waits where it is when no step fits; the addresses' sweep starts no
  chunk past the budget and waits (`after` FROM_START when it never started); the handle scan has no batch past it.
- **The counts say the pace**: `incremental.seconds`, `incremental.collide_rate`, `full.seeds`, `full.left`,
  `full.rate`, `full.seconds`, `shown.steps`, `shown.seconds`, `invariants.seconds`, `repair.took`.
- The parser is skipped for names of a type it reads no version of (`Ent.pk`: NONE at once): the pool's indexes'
  read 3.46 -> 3.16 s.

## Measured

**The repairs alone** (`rep_only.py`, S3 warm, the run's book then each step, rolled back):

| step | base 2dce4786: s / statements | head: s / statements |
|---|---|---|
| org_family | 1.97 / 21,566 | 0.97 / 13 |
| product_accounts | 1.80 / 7,851 | 1.46 / 189 (its walk's pages) |
| reparent, families, invariants | 0.26, 0.69, 0.22 / 4, 0, 0 | 0.26, 0.85, 0.32 / 4, 0, 0 |

**The stage on S3 at the server's pace** (`seq.sh`: a fresh clone of S3, 7 entities stages committed one after
another at the server's budget, 45 s, ~500 new mentions between runs, the Python at 35% of a CPU; `logs/qbase7.seq`,
`logs/qhead7.seq`; head = this branch's last commit). The first run of each is on a cold fresh copy (head's first
failed to connect to the loaded scratch server: its second is its first).

| run | base: stage s / peak MB | base: linking | base: repairs s (steps) | head: stage s / peak MB | head: linking | head: full pass seeds | head: repair steps; shown steps; invariants |
|---|---|---|---|---|---|---|---|
| 1 | 77.1 / 345 | 13 of 13 | 6.2 (4) | (no connection) | | | |
| 2 | 50.0 / 348 | **1 of 4, 1,252 left** | 6.4 (4) | **45.0** / 313 | 13 of 13 (18.2 s) | 2,566 | 1; 1; counted |
| 3 | 52.5 / 419 | 4 of 4 | 6.8 (4) | **45.2** / 276 | 4 of 4 | 2,971 | 1; 0; counted |
| 4 | 48.5 / **838** | 1 of 1 | 6.7 (4) | **44.3** / 328 | 1 of 1 | 2,000 | 0; 0; counted |
| 5 | 61.9 / 383 | 1 of 1 | 6.9 (4) | **43.5** / 305 | 1 of 1 | 1,904 | 2; 1; skipped |
| 6 | 51.5 / 381 | 1 of 1 | 7.5 (4) | **43.5** / 301 | 1 of 1 | 2,729 | 1; 2; counted |
| 7 | 52.7 / 333 | 1 of 1 | 8.7 (4) | **45.8** / 303 | 1 of 1 | 3,826 | 1; 1; skipped |

The base: 48.5-77.1 s a run (budget 45), the invariants skipped every run, the shown names' sweep one step a run past
the deadline (~21k clusters, as the server's `shown.clusters` 21,260-21,300), the full pass 1-3 chunks of 1,000 (on
this clone its repairs take 6-9 s, not the server's 14-17, so it reaches more chunks than the server does). An earlier
base sequence (`logs/qbase.seq`), its first run's repairs cold at 21.2 s, was the server's run exactly: **1 part of
13, 5,500 left, 71.8 s**. The head: **43.5-45.8 s**, the backlog linked in its first run, then every run's new
mentions in one part (10.5-11.3 s with the pool's read), the full pass **1,904-3,826 seeds a run** (the server's
v10.23: 1,000 every other run), the repairs a step or two most runs (a whole round every 2-3 runs), the shown sweep a
step most runs, the invariants 4 runs of 6. Peak 276-328 MB against the base's 333-838 (the 838: a hub's chunk, below).

**The same stage, S3 warm** (rolled back, full speed): base 51.7 s, 13 of 13, 6 chunks, repairs 6.2 s, peak 439 MB;
head 45.7 s, 13 of 13, 5 chunks (4,584 seeds), the four repairs 4.3 s, peak 348 MB.

**A hub's chunk** (`paren_peak.py`, the 2,000 seeds after 60908e0f..., which the full pass reached in run 4): their
posts are 27,976 (the first 1,000 seeds' 3,807): "X (Y)" read every text at once, the process's peak 88 -> 757 MB
(base); a page of 500 posts at a time: 88 -> 305 MB, the same pairs.

**S1, a normal incremental run, no budget** (`s1pair.sh`, the decision run as the runner's child runs it, every mx_*
table digested, base 2dce4786 against the head): **94 of 94 mx_* tables equal but mx_runs, whose run row differs by
the new count keys only** (`runcmp.py`: `repair.done`, `repair.next`, `incremental.collide_rate`; the durations
`took`, `seconds` left out). Measured at 9fd3363a and again at 5e8b568e: the entities stage 27.7 -> 20.2 s (CPU 8.7
-> 7.1 s; the machine shared), its peak 296 -> 291 MB; the repairs 4.2 -> 2.5 s.

**The run under 120 s.** The server's other stages took 68.7 s in the 07:28 run (candidates 17.4, questions and
decisions 24.6, connections 8.1, graph 6.5, news 6.2, surges 3.2, perspectives 1.9, the rest 0.8): with the entities
stage at 43.5-45.8 s, **~112-115 s**. Its peak (617 MB on the server) was the entities stage's; the stage's own peak
here 276-328 MB against the base's 333-838.

**How close the clone is.** Reproduced at 35% of a CPU: the base's repairs (21.2 s cold, 6-9 s warm; server
13.8-17.0), the pool's read (7.6-10.4 s; server 13.2-16.0: the server is slower still), every post's facts (2.6-3.1
s; server 2.2-2.8), 1 part of 13 when the repairs are slow, the shown sweep's ~21k clusters a step. Not reproduced:
the server's disk (its nearest names: 11.3 s a 1,000-seed chunk, 113k blocks read from disk a call; here 1-2 s a chunk
once warm), its real names (the synthetic ones meet a family less often: product_accounts finds 0 accounts here, 25
there), its true backlog (only `left` within LINK_LIMIT's 6,000 is known: >= 5.5k), and its CPU exactly (35% is a
guess from the pool's read; the server's is ~1.5x slower again). On the server the full pass will move fewer seeds a
run than here (its nearest names read from disk): sized to the time at its own pace, it still moves every run.

## Needs the owner

1. **The pool's indexes in the database.** The 13-16 s a run on the server is `RunBook._build`: every entity read and
   indexed in Python once a run (CPU, not SQL). The stage now keeps to its budget with it, but it is a third of the
   budget. Below it: a gram table (or the squashed keys, families and makers as columns) kept by the Writer, read per
   chunk: a migration, a backfill of ~330k names, and the gram candidates' tie order changes (a seed's 60 candidates
   by count, ties by the book's order today; production already breaks ties by the process's hash seed). Not built:
   it changes what the pool finds at the cutoff, and S1 would differ.
2. **While a full pass is half done, the sweeps get a slice, not the rest.** The pass lasts days on the server and
   every run is "whole"; it leaves the repairs' next step, a shown step and the invariants their last seconds (2-6 s),
   so each moves every run or two; the handle scan and the addresses' sweep get only what is left after them (often
   nothing until the pass is done). The order is the owner's (linking, full pass, then the sweeps); say if the handle
   scan should have a slice too.
3. **The full pass's pace on the server.** 73 chunks (~73k seeds) were left on 11-17; at ~1,000-2,000 seeds a run
   there (its nearest names from disk), 40-70 runs. If that is too slow, the next lever is the HNSW reads (shared
   buffers 1.5 GB against the 886 MB index and the 1.9 GB vector table), not the scheduler.
4. **The first run after the deploy** reads no `took`, `rate` or `collide_rate` yet: it uses guesses (a repair step
   3 s, a shown step 2 s, the invariants 1 s, 40 seeds a second, 2 ms a mention's collisions) and may run a few
   seconds past 45; from the second run on, the last run's measures. The reading's code is unchanged: no full run.
