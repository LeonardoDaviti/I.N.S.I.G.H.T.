# 0227: The decision run: the graph after the entities stage, a bounded reading (Stealth v10.25, slice B)

Status: **built, not measured after** (0225 items #15 and #9; #31 measured before only). No migration. Module tests only.
The scratch Postgres was wiped at 13:15 UTC on 2026-11-19 during the measurements (every clone gone), and the owner then
ordered no real-data testing and no request to the server: the "after" numbers below are **not measured**. Scripts and
logs: `plan/research/v1025-b/` (private, main checkout).

**On the deploy:** `incremental.py` and `decide.py` outside `run` changed (incremental.READING_MODULES), so the first
decision run after it is full (its catch-up limit, 600 s), as after any change of the reading. That run is the one #9
is about.

## What was measured (before), and how

One clone of `v1024srv_s1` (the server's shape: 1.56M mentions, 332,800 names; 0154 and 0155 applied by hand), one
decision run as the runner's child runs it (`stage_mem.py` of 0218/0221: `Jobs.decide`, per-stage seconds, CPU and
peak RSS by VmHWM reset per stage, the clock at 18:15, ENTITY_BUDGET 45 s, the graph's own 20 s budget), its snapshot
rolled back (`ROLLBACK=1`, new: one clone serves every run). The template keeps **no decision state** (`why_full:
{"state": "none"}`), so the run was **full**: the first full run after a deploy (#9's case). The machine was loaded
(load average ~52 on 32 cores, eight slices cloning): wall seconds are inflated, CPU seconds are the process's.

| stage (base 965adad3, full run) | wall s | CPU s | peak MB |
|---|---|---|---|
| candidates | 45.6 | 7.8 | 155 |
| load | 0.1 | 0.0 | 81 |
| questions and decisions | 37.2 | 21.2 | **787** |
| - inc.refresh / decide.load / decide.think | 0.2 / 27.2 / 9.5 | 0.0 / 14.5 / 6.3 | 79 / 321 / **787** |
| write | 0.7 | 0.5 | 790 |
| connections | 1.1 | 0.5 | 799 |
| graph | 76.0 | 10.4 | 819 |
| back, headlines, news | 0.2, 0.3, 2.0 | 0.2, 0.3, 1.1 | 816 |
| entities (identity.stage 39.8) | 43.9 | 12.7 | 545 |
| surges | 0.0 | 0.0 | 314 |
| perspectives_plan (inc.save 77.8) | 78.1 | 1.9 | 451 |
| **the run** | **285.5** | **56.9** | **819** |

A second full run with tracemalloc got its `decide.load` snapshot (128 MB traced: the rules' posts 34 MB, the stamps
15 MB, the fresh_posts rows) and was killed by the wipe before `decide.think`'s. The incremental runs (#31) were next:
**not measured** (they need a committed state on the clone first).

## #9: what holds the memory in "questions and decisions" on a full run

`decide.think` takes the stage from 321 MB to 787 MB (server: ~1.1 GB). By the code (the snapshot that would have shown
it was lost): **every text and reading the reading renders is kept until the reading ends** (`State.texts`,
`State.readings`, cleared by `incremental.release` after News). On an incremental run almost every render is kept by its
key and reads nothing; on a full run none is, so `World.copies` reads every member of every story and the renders read
every post a question shows, and all of them stay: in effect every post of the window, its text (with its links and a
link post's page) and its reading. The read-ahead made it so: each render's miss also read 500 posts read again
(`State.stale`) in id order, unrelated to the order of use, so nothing could be let go.

**Built** (incremental.py, decide.py; the one reading path, no second one):
- The reading holds at most `TEXT_KEEP` (3 pages, 6,000) texts and as many readings, the least recently used let go
  (`_hold`; one render's or prefetch's posts are never let go). A text used again is read again from the run's one
  snapshot (REPEATABLE READ): the same text, so the same input and decision.
- The read-ahead follows the order of use: `incremental.prefetch` reads, in one query, the texts (and readings) of the
  posts read again among those the next questions show (`Questions.shows`, a page of TEXT_PAGE posts at a time, in
  `_ask_all`'s order), and `World.copies` the next stories' members the same way. When the posts read again fit in a
  page (an incremental run), all of them at once, as the first render did before. The random `STALE_PAGE` read-ahead
  is gone. `LazyTexts.items()` reads a page at a time.
- Expected: the stage's peak ~ load's 321 MB + 6,000 texts and readings, against every post's. **Not measured.**
  The risk to measure first: a post shown again after it was let go is read again (more statements on a full run; the
  full run's limit is 600 s; the joins and merges follow the candidates' order, not the stories').

Tests (`test_markx_incremental`): with TEXT_KEEP 2, a full run then an incremental run never hold more than
max(TEXT_KEEP, one request) texts or readings, and write the same rows and tasks as with every text kept; the existing
"a page of 1 and of 1000 write the same rows" and the full-equals-incremental checks pass.

## #15: the edges of a new post one run late

**Why.** `graph.stage` ran before `entity_stage.entities` in `decide.run`: a new answer's mentions were linked after
the graph read them, so their relations and same-subject candidates came one run later, and only because the graph's
scopes (answers since its last run, less MARGIN, 1 h) still reached them. A post linked later than that (the linking
backlog: 1 part of 13 a run on the server for days; runs more than an hour apart) was never read again: its edges
waited for a backfill (which runs once per version).

**Built** (decide.run's order, graph.stage's hand-off):
- The graph stage runs after the entities stage (before the surges). Nothing between them reads the graph's edges
  (back, headlines, news, entities: checked), and the stage still counts in LIMIT; the entities stage keeps its own
  budget.
- The entities stage's `posts_linked` (the posts whose mentions it linked or relinked; it computed them already) is
  handed to `graph.stage(linked=...)`: they join the relations' and the same-subject candidates' scopes whatever their
  answers' age. The 1 h look-back stays as it was for what it covers (a transaction that committed after the last
  snapshot).
- A graph stage that does not run (a concurrent update defers it, or it is skipped after two runs over the limit in it)
  keeps the run's linked posts for the next one (`graph.defer`, mx_settings `graph_pending`); the next stage reads
  them with its own and clears the setting.
- One line in `entity_stage.py` (slice A's file): `posts_linked` is left in the stage's counts (`out.get` for
  `out.pop`); `decide.run` pops it before the counts are stored.

**Cost.** The graph's `sync_relations` and `discover` also read the posts the run linked (at most the linking cap's
posts, 6,000 mentions a run). **Not measured.**

Tests: `test_markx_graph` (a post linked after its answer aged is missed by the answer's time and found through
`linked`; a deferred stage's posts are kept, read once by the next, then cleared); `test_markx_jobs` (the stage order).

## #31: the incremental run against its 120 s

**Not measured** on the clone (see above); no change made for it beyond #15's order. The server's numbers from the
brief (v10.24, 2026-11-19, no new request): 132 s in all, entities 71.6 s, graph 6.3 s, questions 24.6 s. With the
entities stage held to its 45 s budget (slice A), the same run is ~105 s, under 120 s, before anything here. Where the
questions stage's 24.6 s go on an incremental run is still to be measured (on the full run above, `decide.load` was
27.2 s wall, 14.5 s CPU: the current pairs' table and the window's stream, the posts' stamps), with `SQL=1` per call
site, once real-data runs are allowed again.

## Next, when real data is allowed

On a clone of the server's shape: (1) the full run before and after (peak of "questions and decisions", its wall and
CPU, texts_loaded); (2) one committed full run, then incremental runs base and head with `BASE_STAMP` set to the base's
reading stamp, per stage with `SQL=1`; (3) the graph stage's seconds with the hand-off, and the mx_* digest of base
and head on S1 (the order changes when edges land, not which).
