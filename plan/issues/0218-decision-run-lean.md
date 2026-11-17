# 0218: The decision run, lean (Stealth v10.23)

Status: **built**, review follow-up built (branch `v1023-light` from `v1023` fb373c40). No migration. Not merged, not pushed. Module tests
only (the full suite and the real-data check are the owner's session's). Scripts and logs:
`plan/research/v1023-light/` (private). **On the deploy:** the reading's code changed (decide.load, incremental.release:
the reading's stamp), so the first decision run after it is full (0215: its catch-up limit, 600 s), as after any change
of the reading.

## Review follow-up (2026-11-17): the server's state's regression, the shown names, the graph stage

The review held the merge: on S2 the branch linked 1 part of 13 and did 3 full-pass chunks against 4 (the backlog
could stall again). Five commits on the same branch (2f601e60, ee4bc6fc, d515347d, 646cdcf9, b070c44f), measured on
templates S1 and S2 built again from prep_scale the same way (the old ones were dropped; the base measured again on
them: `rbase_*`).

**Why the linking lost its parts.** Inside the stage's 45 s, before any part: the repairs (6.2-14.9 s: the product
accounts' walk read every name of two words, ~222k rows, for the ~37k typed an org) and the pool's indexes' one read
of every entity (7.7 s). The base spent load_book (4.9 s) and its repairs (1.6 s) there.

**Built.**
- *The indexes' read outside the budget* (646cdcf9): still once a run, shared by every part and chunk; its seconds
  (`RunBook.reading`) are left out of identity.stage's clock and of the later steps' deadline. And cheaper: only the
  columns the indexes and family values read, a fields key once for each set of fields and maker, a maker's key once
  a maker: 7.7 -> 5.7 s. (Not a stored structure: the indexes' list order, the whole book's order when read, decides
  the gram candidates' ties, so a table would not give the same rows.)
- *The repairs' walk narrowed* (b070c44f): a book read by need reads the names some mention types an org (or, none
  counted, typed an org), one semi-join on the run's snapshot; the caller's test still decides. 5.0 -> 2.1 s.
- *The shown names' sweep resumes* (2f601e60, ee4bc6fc). Why it restarted: a run with a full pass half done is
  "whole", and a whole run whose last sweep was done starts a new one; the sweep did every single name (330k on the
  clone, which has no cluster of several names) at its start whatever the deadline, and resumed only the clusters of
  several names. Now one sweep in id order, a step at a time (2,000 clusters of several names or 20,000 of one,
  whichever first), stopping past the deadline after a step, the next run resuming after it (the same {done, after}).
- *The graph stage's subjects read by need* (d515347d). The dominant structure: `Subjects` held every post's subject
  mentions (on S2: 484k rows, 129k posts, 128 MB of Python objects, 161 MB while read; RSS 489 MB after it in a fresh
  process). Now next_version reads the versions, then only their posts; discover the scope's subjects, then their
  roots' posts by date; the relate backfill a chunk at a time.

**S1 (a normal incremental run): all 94 mx_* tables equal to the base** (rbase_s1 against wip2_s1, the branch's
last commit).

| S1 | base fb373c40 | v1023-light b070c44f |
|---|---|---|
| the run's peak | 695 MB | **298 MB** |
| questions and decisions: peak / after trim | 501 / 354 MB | 281 / 237 MB |
| graph stage: peak / CPU | 631 MB / 12.0 s | **292 MB** / 10.2 s |
| entities stage: wall / CPU / peak | 23.5 s / 16.8 s / 695 MB | 22.3 s / 10.9 s / 298 MB |
| the run's CPU | 45.8 s | 36.5 s |
| rows | - | **94 of 94 equal** |

| S2 (the server's state, entities 45 s, the graph's own budget) | base fb373c40 | v1023-light b070c44f (read outside the budget) | the same, read inside (measured variant) |
|---|---|---|---|
| linking parts | 13 of 13 | **13 of 13** | 13 of 13 |
| full-pass chunks | 4 | **5** | 4 |
| entities stage: wall / CPU | 52.4 s / 31.3 s | 57.4 s / 28.3 s | 49.7 s / 24.2 s |
| before identity.stage (in the budget) | load_book 4.9 + repairs 1.6 s | repairs 3.5 s (the read, ~5.5 s, outside) | repairs 3.5 s + the read |
| shown | 3.2 s | 1.7 s (one step) | 2.2 s |
| entities stage peak | 733 MB | 410 MB | 363 MB |
| graph stage peak | 634 MB | 293 MB | 294 MB |
| the run's peak / CPU | 733 MB / 61.8 s | **410 MB** / 54.8 s | 363 MB / 50.5 s |

**Wall time against the base.** With the read outside the budget, the stage's deadline moves by the read's seconds by
construction, so on S2 its wall is the base's plus ~5 s (57.4 s against 52.4 s), for one more chunk (5 against 4) and
13 of 13 parts. The variant with the read inside the budget (one line: `RunBook.reading` not counted) meets every
number, 13 parts, 4 chunks, 49.7 s, because the read and the repairs now cost less than the base's load_book and
repairs did; it was measured, not committed (the review asked for the read outside the budget). Wall seconds on this
machine vary (the candidate finder, unchanged, took 30-96 s across these runs); CPU seconds less.

## Summary

Measured on a server-sized clone (fresh clone per run, one decision run as the runner's child does it). **S1**, a
normal incremental run: every mx_* table compared with the base after every commit, **all 94 equal**. **S2**, the
server's state (a full pass half done) at the server's budgets: time and memory only.

| S1 (a normal incremental run) | base fb373c40 | v1023-light |
|---|---|---|
| questions and decisions: peak / RSS after the trim | 500 / 354 MB | 285 / 237 MB |
| RSS when the entity stages start | 350 MB | 219 MB |
| entities stage: peak / above its start / CPU (wall) | 694 MB / +344 MB / 16.8 s (99.4 s, a loaded machine; 24 s quiet) | **322 MB / +103 MB** / 14.0 s (25.2 s) |
| RSS after the trim: graph, news, entities, surges | 362, 350, 398, 398 | 267, 219, 220, 220 |
| the run's peak | 694 MB (entities) | 541 MB (the graph stage: its backfill unbounded in this harness) |

| S2 (the server's state, entities 45 s, the graph's own budget) | base | v1023-light |
|---|---|---|
| the run's peak | 744 MB (entities) | 542 MB (graph) |
| entities stage: peak / identity.stage peak | 744 / 744 MB | **348 / 345 MB** |
| graph stage peak | 634 MB | 542 MB |
| entities stage: wall / CPU | 51.8 s / 30.5 s | 69.5 s / 31.7 s (see "Reading S2") |
| the work it did in its 45 s | 13 of 13 linking parts, 4 full-pass chunks | 1 of 13 parts, 3 chunks |

Per slice (S1 unless said; each commit's rows equal to the base's):

| slice | before | after |
|---|---|---|
| 1. the entity book read by need (RunBook) | load_book +250 MB; entities stage peak 694 MB | no whole book; peak 316-322 MB (S2: 744 -> 348) |
| 2. the candidate pairs in the database | decide.load peak 500 MB (+416) | 284 MB (+202); its DB time 29.7 -> 3.5 s (S2) |
| 3. the nearest names (120 seeds, warm) | 324 ms, 227k buffers | 260 ms, 217k (the same rows); "X (Y)" reads the texts of posts with a pair only |
| 4. what each stage lets go | after the trim: Q&D 354 ... entities 398 | 237 ... 219 (flat after Q&D) |
| 5. the story job before the decision run | a due decision run went first | a wanted story run first (tests) |
| 6. budgets in the real-data check | none | each job's peak MB and seconds, base and head; fails over budget or 20% worse |

**Against the targets.** The entities stage's memory: +99-103 MB above its start on S1 (target ~150), its peak 348 MB on
the server's state against 744. Its time: 25-29 s (CPU 14-16 s) on S1, within its 45 s; on the server's state its budget
decides, and the run's book costs time there (the pool's indexes built from one read of every row inside the budget:
1 linking part of 13 against 13, 3 chunks against 4; the shown names' sweep over every entity, 18 s past the deadline
against 3 s): CPU 31.7 s against 30.5 s, wall 69.5 s against 51.8 s, see "Reading S2". The post-trim baseline is flat
after questions and decisions (219-267 MB). The run's peak is now the graph stage's (539-542 MB); questions and
decisions 285 MB, entities 322-348 MB. **Not reached**: a run under 500 MB at the clone's size (the graph stage) and
under 90 s (the clone's candidate finder alone took 29-129 s on the shared machine, the server's 12 s; the graph stage
28-127 s for the same code).

## The server (read-only GETs, v10.22.2)

A normal incremental decision run, `/api/markx/overview` jobs.decide.last (2026-11-16 21:18 UTC): 140.7 s, peak 915 MB,
`rss_mb` [stage, MB at its end, MB after gc + trim]:

| stage | seconds | MB at end | MB after trim |
|---|---|---|---|
| candidates | 12.1 | 141 | 75 |
| load | 0.3 | 104 | 87 |
| questions and decisions | 22.5 | 401 | 360 |
| write | 0.4 | 373 | 360 |
| connections | 8.5 | 475 | 421 |
| graph | 7.4 | 506 | 430 |
| news | 5.5 | 500 | 402 |
| entities | 78.3 | 772 | 523 |
| surges | 3.2 | 566 | 522 |
| perspectives_plan | 2.4 | 463 | |

Its entities stage: the full pass begun 2026-11-11 is still half done (`full`: 1 chunk this run, 111 to go), so every
run is "whole"; the linking linked 1 part of 13 (5,519 mentions left). `timing`: paren 18.5 s, vectors 16.5 s, pool
9.9 s, load 4.5 s, write 3.5 s, decide 3.4 s.

## The clone

`prep_scale` migrated to v1023 (0151) and filled as 0216's `v1022-decide` did (fill A: name-like names, 4-7 more
mentions a post: 1,557,089 mentions, 325,496 names; one real first full decision run, 767 s; fill B: the pair
questions answered, 359k alias tasks of real-sized inputs, a name vector for every entity with HNSW: 329,800), then:

- **S1, a normal incremental run**: 300 judge answers since (the fake worker), ~450 alias answers since, 3,000 queue
  items not re-decided yet, the newest 600 posts' mentions not linked (7,252); no full pass half done. Deterministic
  (`ENTITY_BUDGET=none`, the graph's backfill unbounded, `det.sql` ids): **every mx_* table (94) and system_settings
  compared, base against head** (0204's digest).
- **S2, the server's state**: S1 plus a full pass half done (phase pool, `after` at 36% of the ids): what every run on
  the server is now. Timed at the server's budget (45 s); not compared (what a run does depends on its clock).

Each measurement: a fresh clone of the template (FILE_COPY, ~2 s), one decision run as the runner's child does it
(`stage_mem.py`: `Jobs.decide`, its candidate finder then `decide.run`, the clock fixed at 18:15), per-stage seconds and
peak RSS (VmHWM, reset per stage), the digest, the clone dropped. Base: fb373c40 (v1023).

## Slice 5: the story job before the decision run (markx/jobs.py, `due`)

**The class.** A fetch that saves posts wants the story job (`want_stories`) and, through the candidate finder, the
decision run. `due` asked the decision run first: a run due at the same look (its hour, or wanted 60 s ago) went
first and decided the new posts on the stories as they were; the next run decided them again in their stories.

**Built.** A story run that is *wanted* goes before the decision run (after the background planners, which never
starve). A rebuild's slice alone still follows the decision run (0215: a rebuild holds no run). A wanted run that
yielded or stepped aside rests STORIES_GAP first (`stories_due`), a running or failing one is not due: the decision
run is never held by it (and the story job steps aside for a run that waited 10 minutes, as before).

Tests (`test_markx_jobs.Due`): a wanted story run goes before a due decision run (with or without a rebuild), the
decision run follows once it started, the plan still first; a story job resting after a yield or a step-aside, running,
or waiting out its backoff never holds the decision run; a rebuild's slice alone follows it.

## Slice 6: resource budgets in the real-data check (checks/resources.py, side.sh, report.py)

**Built.** Each side measures its jobs as the jobs process runs them, each in a fresh `spawn`ed process (the job's own
peak: utils/peak, VmHWM; wall and CPU seconds): the decision run twice (the copy's first, full: `decide_full`; then the
next, incremental: `decide`), Mark IX's story job (wanted; its originals and scouts left out: a check reads no web)
and Discover (its web reads off). The decision runs' clock is the copy's. `resources.json` on each side, before the
job checks (their own decision runs). The report's section **B2** compares them: the check **fails** when the head is
over a budget (decision run 600 MB and 90 s incremental, story job 300 MB, Discover 300 MB) or more than 20% above
the base's peak MB or CPU seconds (a difference under 50 MB or 5 s never fails). The values are `BUDGETS`, `WORSE_BY`,
`FLOOR_MB`, `FLOOR_S` in the module, overridable per run (`RESOURCE_BUDGETS` JSON). A base from before the check has
no resources.json: budgets only. Documented in WORKFLOW.md.

Tests (`test_realdata_checks`): the verdicts (12% worse ok, 25% worse fails, over a budget fails, seconds over 90
fails, CPU doubled under the floor ok, over it fails, no base: budgets only, RESOURCE_BUDGETS overrides); a job
measured in its own spawned process on the test database records its own peak, seconds and the run's kind; a job a
version lacks is "not measured".

## Slice 1: the entity book read by need (markx/identity.py RunBook; entity_repair, entity_addresses, handles, rename)

**The class.** The entities stage read the whole book every run (`load_book`: every entity, alias, redirect, pin and
mention count; 330k entities on the server, 198 MB of objects, +250 MB RSS on the clone) and walked it whole for the
pool's indexes and the repairs, though a run touches the seeds of its new mentions, their pool and the clusters they
reach. The pages already read a book by need (`lazy_book`, 0186).

**Built** (one module owns it: `identity.RunBook`, a LazyBook; the whole `Book` stays the second adapter, for the
pages' tests and the scripts):
- each entity and alias read when first asked, many at once where the stage knows them ahead (`prime`: the seeds, the
  pairs' ends, the candidates of a seed's grams, the keys of a run's mentions, a cluster's members); the merges, pins
  and the owner's "never" read whole (they are few);
- the mention counts (`types`, `subject`, `mentioned`), the version parents and the versions under a parent as they
  stood when the book was read: snapshots in temporary tables of the run's transaction (`pg_temp.mx_run_types`,
  `mx_run_versions`, ON COMMIT DROP), read by need, as load_book's were (the run's own linking adds to `mentioned`);
- the whole book's order (as read, then as made: the first family of a key wins) from each entity's place when read
  (`pg_temp.mx_run_order`), the entities the run makes after, in the order made (`Book.added`, the Writer's one call);
- the pool's indexes (`Book.index`, INDEXES: by gram, by squashed key, by family, by maker prefix) built from one read
  of every row, none kept; a key of one id holds the id alone (`_Compact`); grown with what the run makes live, in the
  whole book's order (`_grow`); the family values (`family_values`) from the same read; which entities a mention
  names (`mentioned`) asked of the snapshot for the pairs a chunk pools, in one read (`Pool` checks its pairs when
  they are read); a seed's string candidates read as their keys only (`keys_of`), for the chunk;
- the walks over the whole book (`Book.walk`, `Book.ids`; the repairs' product accounts, versions and families, the
  rename makers, the shown names' sweep) read row by row, narrowed by the caller's SQL; an entity the run holds is
  the one given (its changes are the run's); `names_of` and `named_by` (the addresses' names, the handle pairs'
  forms) by query.

**The same rows.** S1, base fb373c40 against this slice (and each slice after it): **all 94 mx_* tables and
system_settings equal**. A test (`test_markx_entities.TheRunsBook`) runs the stage on one fixture with the whole book
and with the run's book: the same counts and rows; the quiet names never read; the run's book cannot be walked.

## Slice 2: the candidate pairs (markx/embed.py `current_pairs`, decide.load)

**What was asked, checked against the code.** "Only pairs touching changed posts" cannot give the same decisions: the
rules run over the whole world every run (incremental.py: the plan, glue, merges and the second pass are global;
only the reading is incremental), and `plan_pass1` reads every window pair to find each question (a pair's join or
merge depends on both posts' stories now, which change with any other pair). What a run held was the problem, not
what it read: `decide.load` read all ~452k `post_post` rows (each row's tuple, two id strings, its source and score),
their cosines now by row, then a dict of every pair: **+416 MB in decide.load** on the clone (84 -> 500 MB).

**Built.** `embed.current_pairs` gives the rows "as the posts' current vectors have them" (the cosine now, a vector set
aside, one vector for two texts, the answered pairs kept) in a temporary table of the run's transaction;
`current_candidates` (its per-row reader, the tests') reads the same table, so the rule has one implementation. The
decision run reads the pairs' posts from it (`SELECT DISTINCT`), loads its world, then reads the pairs as a stream
ordered by pair (`_window`): each pair once, its cosine rounded as before, kept only when both posts are in the world
and the first is in the window, on the world's own id strings. The same order (strength, then ids). **Measured (S1):**
decide.load's peak 500 -> 286 MB, "questions and decisions" after the trim 326 -> 237 MB (with slice 4 before it); its
database time: the temporary table 3.5 s (the cosines were computed by the same SQL before); 94 of 94 tables equal.

**The judge tasks and kept inputs by need: not built.** On the server a run reads 106,924 kept inputs and renders 931,
reads ~63k answers (`answers_read`): the reading asks nearly every kept question every run (the rules
run over the whole world). Read by need, the same entries are read, one query each instead of one in all; the working
set does not shrink. The clone holds 1,902 judge tasks, so its reading cannot show this part of the server's memory;
its measured lever (a compact state: hashes as bytes, answers as their few fields) is left for a clone with the
server's judge tasks.

## Slice 3: the nearest-names query (identity.vector_neighbours) and "X (Y)"

**EXPLAIN on the clone** (120 seeds of a chunk, `EXPLAIN (ANALYZE, BUFFERS)`, `plan/research/v1023-light/
explain_vec.sql`): the plan **already uses the HNSW index**, one `Index Scan using mx_entity_vectors_v_hnsw_idx` per
seed (`Order By: v <=> s.v`, the seed itself the one row filtered). Each seed's walk touches **~1,800 buffers** (the
graph's 1024-dim halfvec tuples, ~2 KB each): 546 ms cold, 324 ms warm for 120 seeds. On the server
(pg_stat_statements, 2026-11-16) the statement ran 5 times, 8.3 s each, **426,389 blocks read** (3.3 GB) for 5,810
rows: the index does not stay in the server's cache, so a full pass's chunk of ~1,000 seeds is ~16.5 s of disk reads.
No plan keeps the results and reads much less: a lower `ef_search` or another index changes which names are found.

**Built.** The distance is the scan's own (`o.v <=> s.v AS d` in the lateral), not computed again from each
neighbour's vector read back: -10k buffers (the neighbours' heap and TOAST pages) and -20% warm time for 120 seeds;
**the same 20,000 rows and cosines** for 2,000 seeds (`same_vec.sql`).

**"X (Y)"** (identity.paren_by_post, 18.5 s of the server's run): a full pass's chunk read the text of every post
naming one of its 1,000 seeds and tried every pair of each post's mentions against the whole text. Now only the posts
with a pair the rule could name (two entities of one type, not a place or person) have their text read, and a pair is
looked for only when its Y is the whole of a "(...)" in the text (a span folds to words and spaces, never a bracket,
so the rule's match implies it). The same pairs. Measured on S2: 8.3 s -> 7.5 s for 13 parts and 4 chunks (the base
with the SQL hook, against 7c36a14f); the clone's synthetic posts nearly all hold a nameable pair (4-7 more mentions
of six types each), so the texts read barely fall there; the server's real posts (18.5 s for one part and one chunk)
were not measured.

**The DB time of the reading's pairs** (slice 2's table, S2 with the SQL hook): the base computed the 452k cosines
with the rows sent back as two arrays of ids (`embed.py:470`, 29.7 s that run); the table computes them in one join
from mx_candidates (3.5 s).

## Slice 4: what each stage lets go (decide.run)

**Built.** The candidate pairs (`world.candidates`, the first pass's input only) let go once `think` has read them;
before the entity stages, what the run's end reads of the reading (its memberships `want`, the closure, the counts) is
taken and the reading itself let go (the world's Mark IX stories, the outcome, the connections): they were held to the
run's end, under the entity book. `run` is outside the reading's stamp (NOT_KEPT). The kept state (memo) stays, its
save the run's last write, but after News (`incremental.release`) without what only the reading's renders read: the
answers (~63k a run on the server; read again on use), each post's text and reading stamps, its reading's kind and
events, the world's posts' rules (the save reads only which posts they were). The pairs' temporary table is dropped
once read. In the graph stage every post's subjects are made objects a page at a time (`Subjects`: ~400k rows were
made tuples at once), in the order read.

| S1 | base | slice 4 alone (63949912) | with the later releases (ebd23f2f, f4745587) |
|---|---|---|---|
| questions and decisions: peak / RSS after the trim | 500 / 354 | 502 / 326 | 286 / 238 (with slice 2) |
| RSS when the entity stages start | 350 | 325 | 218 |
| entities stage peak | 694 | 676 | 317 (with slice 1) |
| RSS after the trim: graph, entities, surges | 362, 398, 398 | 338, 374, 374 | 264, 220, 220 |
| graph stage peak (backfill unbounded) | 631 | 599 | 541 |
| rows | - | **94 of 94 equal** | **94 of 94 equal** |

## What is left (measured, not built)

- **The pool's indexes are still whole.** The run's book reads its entities by need, but the pool (blocking by grams,
  squashed key, family, maker prefix) still indexes every live entity in the process, built from one read of every
  row each run: tracemalloc at identity.stage's end (S2) holds ~100 MB of Python objects, ~70 MB of them the index
  (the 330k ids 26 MB, the gram lists 26 MB, the squashed keys 11 MB, the keys' dicts 7 MB) and ~22 MB the entities
  the run read; the rest of the stage is let go at its end (49 MB traced after it, as before it). Below that the index
  has to live in the database: a gram table kept by the Writer (a migration and a backfill), or pg_trgm with the
  rule's Jaccard as the recheck, read per chunk. Its liveness (an entity a mention names, as when the book was read)
  is the snapshot RunBook already keeps. (Review follow-up: the read is outside the budget and costs 5.7 s, not 7.7.)
- **The judge tasks' state is the server's largest share of "questions and decisions"** (106,924 kept inputs, ~63k
  answers a run) and the clone holds 1,902 judge tasks: a compact state (hashes as bytes, answers as their fields) is
  to be measured on a clone with the server's judge tasks. The answers are let go after News (`incremental.release`).
  On the clone the stage's end holds 153 MB of Python objects (tracemalloc), the world's 130k posts': their kept rows
  27 MB, their readings' kinds and events 35 MB, stamps 25 MB, texts 13 MB; 49 MB once released after News.
- **The graph stage** was the run's peak (539-541 MB): built in the review follow-up (its subjects read by need: 292 MB).
- **A full pass half done keeps every run "whole"** (0216): with its steps cheaper (the "X (Y)" texts, the nearest
  names' second read), more chunks fit the 45 s; the server's pace after the deploy says whether the pass needs a job
  of its own.

## Measured on S1 (a normal incremental run, server-sized clone; every row compared)

Each line is the branch at one commit (cumulative), against base fb373c40, on a fresh clone of S1. Peak and RSS in MB
(VmHWM of the stage; RSS at its end, after the jobs' gc and trim). The graph stage's backfill is unbounded in this harness (to be
deterministic): its 560-630 MB peak is the harness's, not the server's (its backfill has 20 s a run; S2 below). Wall
seconds vary with the shared machine (other agents' suites); CPU seconds less.

| run | wall / CPU | peak | questions and decisions (s, peak -> end) | decide.load peak | graph (s, peak) | after news (RSS) | entities (s, peak -> end) | identity.stage (s, peak) | rows |
|---|---|---|---|---|---|---|---|---|---|
| base fb373c40 | 198.6 s / 45.8 s | 694 | 35.0 s, 500 -> 354 | 500 | 27.8 s, 631 | 350 | 99.4 s (CPU 16.8), 694 -> 398 | 90.9 s, 670 | - |
| + slices 4, "X (Y)", 1 (RunBook) | 189.7 s / 48.2 s | 594 | 17.1 s, 502 -> 325 | 502 | 27.7 s, 594 | 325 | 109.0 s (CPU 19.5), 585 -> 386 | 21.1 s, 585 | **94 of 94 equal** |
| + repairs' walks paged and narrowed, slice 3 | 179.5 s / 45.0 s | 591 | 85.1 s, 504 -> 326 | 504 | 30.3 s, 591 | 326 | 29.2 s (CPU 16.4), 515 -> 370 | 20.6 s, 515 | **94 of 94 equal** |
| + slice 2 (pairs in the database) | 157.4 s / 44.7 s | 564 | 12.3 s, 287 -> 237 | 286 | 79.2 s, 564 | 238 | 30.7 s (CPU 17.5), 443 -> 290 | 21.6 s, 443 | **94 of 94 equal** |
| + the index's one-id keys | 148.4 s / 44.1 s | 565 | 12.0 s, 286 -> 238 | 284 | 58.4 s, 565 | 241 | 29.7 s (CPU 16.8), 424 -> 292 | 21.3 s, 424 | **94 of 94 equal** |
| + a seed's candidates not held | 157.1 s / 43.2 s | 567 | 11.9 s, 285 -> 237 | 284 | 59.7 s, 567 | 240 | 28.6 s (CPU 16.3), 421 -> 288 | 20.2 s, 421 | **94 of 94 equal** |
| + the releases after News, liveness from the snapshot, the graph's subjects paged, the shown names' chunks read ahead | 176.2 s / 45.3 s | 541 | 79.8 s, 286 -> 238 | 284 | 29.8 s, 541 | 218 | 30.3 s (CPU 16.7), 317 -> 220 | 20.6 s, 317 | **94 of 94 equal** |
| + a seed's candidates read as keys, the shown sweep's pages let go (head8) | 228.6 s / 44.0 s | 541 | 12.0 s, 284 -> 237 | 283 | 29.0 s, 541 | 217 | 29.0 s (CPU 15.8), 316 -> 219 | 20.8 s, 316 | **94 of 94 equal** |
| + the anchors' keys in one go, a sweep's unfound names let go (head9, the branch's last) | 191.5 s / 40.7 s | 541 | 11.8 s, 285 -> 237 | 284 | 27.2 s, 541 | 219 | 25.2 s (CPU 14.0), 322 -> 220 | 17.2 s, 322 | **94 of 94 equal** |

(The first head's 109 s entities stage: the repairs' first walks, unnarrowed (84.5 s of correlated subqueries); the
next commit narrowed them. The second head's 85 s "questions and decisions": 4.2 s of CPU, the machine's waits.)

## Measured on S2 (the server's state: a full pass half done; the server's budgets: entities 45 s, the graph's own)

What a run does here depends on its clock (the budget decides how many linking parts and chunks fit), so the rows are
not compared; the work done is (parts, chunks). CPU seconds hold better than wall seconds on the shared machine (the
same code's graph stage took 28.6 s and 127.1 s in two runs).

| run | wall / CPU | peak | Q&D (peak -> end) | graph (s, peak) | entities (s, CPU, peak -> end) | identity.stage | shown | linking parts | full chunks | paren / vectors / pool / facts (s) |
|---|---|---|---|---|---|---|---|---|---|---|
| base_s2 | 199.0 / 61.0 s | 744 | 502 -> 354 | 30.4 s, 634 | 51.8 s, 30.5 s, 744 -> 408 | 40.7 s, 744 | 3.3 s, 742 | ? of ? | 4 | ? / ? / ? / ? |
| basesql_s2 | 161.4 / 60.7 s | 733 | 503 -> 355 | 35.6 s, 639 | 52.5 s, 31.3 s, 733 -> 414 | 41.5 s, 733 | 3.1 s, 729 | 13 of 13 | 4 | 8.31 / 9.4 / 6.15 / 1.9 |
| c7_s2 | 224.0 / 60.2 s | 702 | 501 -> 326 | 28.6 s, 593 | 51.6 s, 30.1 s, 702 -> 385 | 40.1 s, 702 | 3.1 s, 702 | 13 of 13 | 4 | 7.5 / 9.57 / 5.89 / 1.87 |
| head5_s2 | 250.3 / 61.0 s | 604 | 288 -> 237 | 127.1 s, 566 | 62.4 s, 33.5 s, 604 -> 333 | 39.5 s, 480 | 15.0 s, 604 | 5 of 13 | 3 | 6.59 / 7.2 / 8.36 / 4.25 |
| head6_s2 | 237.5 / 61.5 s | 541 | 285 -> 237 | 28.5 s, 541 | 61.9 s, 33.3 s, 490 -> 247 | 39.3 s, 361 | 14.7 s, 490 | 1 of 13 | 3 | 6.13 / 7.11 / 8.32 / 4.86 |
| head8_s2 | 231.5 / 63.5 s | 539 | 285 -> 237 | 95.5 s, 539 | 67.1 s, 35.6 s, 392 -> 241 | 40.3 s, 359 | 18.1 s, 392 | 1 of 13 | 3 | 6.3 / 7.35 / 9.03 / 4.76 |
| head9_s2 | 199.1 / 58.8 s | 542 | 282 -> 238 | 82.4 s, 542 | 69.5 s, 31.7 s, 348 -> 228 | 35.0 s, 345 | 18.1 s, 348 | 1 of 13 | 3 | 6.36 / 7.16 / 7.77 / 2.03 |

(base_s2, basesql_s2: fb373c40, the second with the SQL timing hook; c7_s2: 7c36a14f, slices 4 and "X (Y)" without the run's book; head5: the run's book, slices 2 and
3, the index's one-id keys; head6: the releases after News, the graph's subjects paged, liveness from the snapshot;
head8: a seed's candidates read as keys, the shown sweep's pages let go and read ahead; head9: the anchors' keys read
in one go, the names asked and not found let go with a sweep's page.)

**Reading S2.** The stage keeps to its budget either way: the linking gets half of what is left (LINK_SHARE), the full
pass's chunks the rest, then one step past it. With the run's book its first step costs more: the pool's indexes are
built from one read of every row (~8 s; the whole book was read before, and its index built from memory), and what a
part asks of the book is read from the database (the alias questions' renders, the chunk's pairs, the anchors'
keys: read in one go where the stage knows them; the anchors' read went from 4.8 s to 2.0 s so). So on this clone it links 1 of 13 parts in its share against 13 of
13 (the base with "X (Y)"), and does 3 chunks against 4; its memory is what it saves (identity.stage 345 MB against
744). Past the deadline, on a whole run whose last shown-names sweep was done, the sweep starts again over every
entity (the clone's S2: 330k): the whole book held them all (3.1 s); the run's book reads them a page at a time and
lets each page go, and the names it asked and did not find (18.1 s, +3 MB; +136 MB before). On the server that sweep comes once
per cycle of the shown names (its record says where it is); the singles could resume by `after` as the clusters do (a
change of what a run writes: not built).

**Slice 6's step at the server's size** (`checks.resources --jobs decide,stories,discover` on a clone of S1, this branch, the machine
shared): the decision run peaked at 162 MB in its own process but did not finish: 167 s against its 120 s limit, CPU
8.1 s (the candidate finder's queries on the loaded machine; it now says so, `not_finished`, and fails the check); the
story job 379 MB (a rule change's rebuild slice is due on this copy; over the 300 MB budget); Discover 83 MB.
