# 0211: Is an answered alias pair asked again? (Stealth v10.20)

Status: **A and C built** (branch `v1020-alias` from `v1020` = main, v10.19; migration **0144**). B skipped (owner's
coordinator, 2026-11-16). Not merged, not pushed, not deployed. alias4's Sonnet routing goes in v10.19.1 ("Haiku
only"): nothing here relies on alias4.

## What was built, and measured

**A.** `identity.Asked` is a read-through lookup:

- `prime(pairs)` reads the alias, alias2 and alias3/alias4 tasks of a chunk's pairs in one query, through the
  new index `mx_tasks_entity_pair_idx` on `(least(a, b), greatest(a, b))` for the pair kinds (migration 0144).
- `prime_collide(entities)` reads the collide tasks, with their input, of the entities `collisions` considers.
- A key never primed is read alone when first asked. What a key read is kept for the run.
- The whole-table read of every task's input is gone.

**C.** `third()` keeps a running union of clusters, the way `chain_guard` does:

- the chunk's automatic merges count first;
- each `third` merge counts as it is accepted;
- one that would pass MAX_CLUSTER stays queued, with its answer.

**Tests.** Two new tests in `tests/test_markx_entities.py`:

- `Merging.test_an_asked_pair_is_found_by_its_pair_and_never_asked_again`;
- `TheUnsureQueue.test_several_merges_into_one_cluster_in_one_chunk_keep_to_its_cap`. Three merges into a cluster of
  4 give 2 merged and 1 queued; the old check merged all 3.

**Answers identical (A).** One state, run under v10.19 and under A alone:

- **The state.** The replay's end state with a third of its alias tasks hidden, so 1,114 pairs are asked again. It
  carries 352k filler alias tasks, the server's count.
- **The runs.** A full pass, then synthetic answers, then an incremental pass. Each code ran from its own copy of the
  state.
- **Result: identical.** All 359,782 tasks (kind, pair, input hash, status), 952 redirects, 1,838 queue items and
  18,556 mention links.
- **With C as well**, the same tasks and links. C's difference: two `third` merges that would have made clusters past 6
  names (base made 3 such clusters in these two runs, A+C made none). 4 queue items differ accordingly.

**Memory and time.** At the server's alias count (357k tasks, inputs of 1.4 KB):

| | v10.19 | A (and A+C) |
|---|---|---|
| peak RSS, the 8-round replay (2 full passes, 6 incremental) | 1,927 MB | 156 MB (153 MB) |
| peak RSS, a full pass then an incremental pass | 1,904 MB | 128 MB (129 MB) |
| the stage's `load` step, cold cache (replay rounds 0 and 1) | 16.9 s, 32.7 s | 0.08 s, 0.06 s |
| the stage's `load` step, warm (other rounds) | 1.0-3.7 s | 0.04-0.15 s |
| a full pass / an incremental pass (warm) | 12.4 s / 2.3 s | 11.8 s / 1.2 s |

The rest of this file is the spec as written before the build.

## The suspicion

The server's `/api/markx/overview` (2026-11-16, v10.19, commit 7ae45b8a) lists **357,158 answered `alias` tasks**, and
roughly 310,000-334,000 entities (`embed_name` answered 334,066: about one name vector per entity). `alias2` has
8,670; no `alias3` or `alias4` task is listed. An alias question asks about one pair of names, so more answered pairs
than entities looked like answered pairs being asked again.

**Measured answer: they are not.** No path in v10.19 gives an already-asked pair a second `alias` task. 357,158
answered tasks are 357,158 different entity pairs, each asked once. The real costs are elsewhere:

1. **How the pairs are checked costs memory.** `identity.asked()` reads the input text of every alias task, every
   decision run. At the server's size that is about 1.8 GB of peak memory and 4.4 s a run, for nothing. This is the
   fix worth building (A below).
2. **A small duplication between groups of names.** Two member pairs of the same two clusters are sometimes asked in
   the same run: 2.4% of alias tasks in ordinary clusters.
3. **A side finding.** The unsure queue's merges (`third`) can grow a cluster past its 6-name cap (C below).

## What "answered" counts

`overview.worker.queue.alias.answered` is the number of tasks with status `answered`. It comes from
`kept_counts.queue_counts`, the triggers' running total, which equals
`SELECT kind, status, count(*) FROM mx_tasks GROUP BY 1, 2` (`kept_counts.check`). It does not count calls or items.

- A task is one `(kind, guide, input_hash)` (`repo.add_task`, unique `mx_tasks_once`).
- An alias task normally has one call. In the replay: 4,744 tasks, 4,744 calls, none with two.
- Alias tasks are never reopened. Only `collide` is, by design, up to COLLIDE_RUNS times.
- So: answered alias tasks = alias calls answered = distinct pairs asked.

## The mechanism: why a pair is asked once

**The identity of an alias question is not its input text. It is the entity-id pair.** This has been true since 0119
(0097c11e) and is still true in v10.19:

- `identity.asked(cur)` reads every alias task, of any status and any guide, into `Asked.alias`. The key is
  `pair(a, b)`, the two entity ids in sorted order.
- `stage.decide_chunk` asks only `need = [d for d in decisions if d.tier == "ask" and d.pair not in got.alias]`.
- `alias2` and the unsure queue (`alias3` or `alias4`, one between them) are keyed the same way.
- A pair is decided once a run (the `decided` set).
- Only the decision run asks, under its advisory lock (`decide.LOCK_KEY`). No other module makes alias tasks;
  `handles.py` only queues items.

### Each suspected path, checked

| path | does it give an asked pair a new alias task? | evidence |
|---|---|---|
| input text that embeds changing things (example posts, post counts, written forms, dates) | **no**: the text changes, but the gate is the pair, not the text | 77% of answered pairs would get a different text today (replay: 3,651 of 4,744). Not one was asked again. |
| order a/b vs b/a | **no** | `pair()` sorts the ids; the text is built in that order |
| a root changes after merges | **no**: pairs are entity ids, never roots, and a merge only adds a redirect | entity ids are never deleted or remade (no DELETE or TRUNCATE of `mx_entities`); 4,744 tasks = 4,744 name-key pairs |
| the backlog re-decision (0201, `backlog`, REDECIDE) | **no**: it re-decides open queue items from the answers already given | it may ask the unsure queue's question (`alias3`/`alias4`) once a pair; never `alias` |
| closed then reopened queue items | **no new task**, only a new queue row | `queue_item` refuses while an open or answered item exists. A closed item lets the pair be queued again: 1,618 items for 1,613 pairs (5 re-queued) |
| guide bumps (alias-v1 → v2) | **no**: `asked()` ignores the guide | the opposite holds: a deliberate guide change would ask no pair again (see B) |
| two pairs whose texts are identical | no new task | `Ask.answer` finds the other pair's task by hash. The second pair's answer is then never read (its pair is not in `got.alias`); there was none in the replay |
| two member pairs of the same two clusters | **yes, a different pair**: the only real duplication | below |

### How much each contributes (replay)

**The replay.**

- **Data.** A clone of `prep_mxreal`, migrated to v10.19. It has 5,031 posts with ent-v3 mentions and no name vectors.
  The newest half of the posts' mention sets were held back, then released in 7 batches.
- **Runs.** 8 entities stages: a full pass, 3 incremental passes, a full pass (the next "night"), then 3 incremental
  passes.
- **Answers.** Every alias, alias2, alias3, alias4 and collide task was answered between runs with synthetic answers,
  seeded by the pair: 35% `same` at 0.95, 10% `same` at 0.87, 40% `different`, 15% `other_version`.
- **Counting.** Each new alias task was classified against what was known when it was made: roots from the redirects
  of the runs before it.

| a new alias task was... | tasks | share |
|---|---|---|
| the first question between its two clusters | 4,262 | 89.8% |
| a second member pair of two clusters already asked in the same run | 480 | 10.1% |
| ... of which in clusters of 6 names or fewer | 112 | 2.4% |
| ... of which in clusters past 6 names (made by the bug in C) | 368 | 7.8% |
| a member pair of two clusters already answered in an earlier run | 2 | 0.04% |
| the same entity pair again | **0** | 0 |
| the same names under other entity ids | **0** | 0 |

Of the 480 same-run duplicates, the earlier answer merged the two clusters for only 29. Asking one pair per two
clusters a run, and leaving the rest for the next run, would have saved those 29. For the other 451 the clusters stayed
apart, and the other member pair is a different pair of names, so its question is legitimate.

**The server's share.**

- Re-asks of answered pairs: **0 of 357,158**.
- Same-run duplicates between ordinary clusters: about 2.4%, roughly 8,600 tasks, an upper bound. Only about 6% of
  those, roughly 500, would be saved.
- At the overview's average of about $0.0004 a call (549.45 API USD over 1,346,204 calls), all 8,600 together cost
  about $3.

**Why there are more pairs than entities.** That is the candidate pool working as built:

- On the server: 357,158 / 334,066 is about 1.07 asked pairs per name.
- In the replay, with no name vectors: 4,744 / 8,841 is 0.54.
- The server's 10 nearest names at cosine >= 0.80 (`vector_neighbours`) add the rest.

## The class

A question needs a stable identity that is not its input text, and a deliberate, narrow way to be asked again.
Identity has this part right: its identity is the pair, not the text. Two things are wrong around it:

- The identity is **checked by reading every question's text into memory** on every run (A).
- There is **no way at all to ask a pair again**. A guide change or new evidence never reaches an answered pair (B).

## The fix design (markx/identity.py: the module that owns the pair's question)

### A. The pair's question is looked up by its pair, not by reading every task (build this)

`asked()` runs `SELECT id, kind, a, b, status, input FROM mx_tasks WHERE kind IN ('alias', 'alias2', 'alias3',
'alias4', 'collide') ORDER BY created_at` at the start of every entities stage. Only the collide rows need `input`.

Measured on the clone with 357k alias tasks, each input the replay's real size (1.46 KB on average; alias3 and alias4
average 3.0-3.1 KB):

| | time | peak RSS of the process |
|---|---|---|
| `asked()` today | 5.1 s | 2,129 MB |
| the same pairs read without `input` | 0.7 s | 336 MB |

So every decision run, incremental or full, spends about **1.8 GB of peak memory and 4.4 s** to learn which pairs were
asked. That grows with every alias task, and nothing ever deletes tasks (keep everything). v10.17.2 measured the
decision run's peaks (full 0.90 GB, incremental 568 MB) on `prep_scale`, which has no alias tasks, so this cost never
showed up there.

**The design.**

- The pair is the question's identity, so the database answers "which of these pairs has a question".
- Each chunk asks it once, for the pairs the chunk pooled:
  `SELECT id, kind, least(a, b), greatest(a, b), status FROM mx_tasks WHERE kind = ANY(...) AND (least(a, b),
  greatest(a, b)) IN (unnest of the chunk's pairs)`.
- This needs an index on `(kind, least(a, b), greatest(a, b))` where `b IS NOT NULL` (new migration). Today's
  `mx_tasks_a_idx` and `mx_tasks_b_idx` are single-column.
- Collide keeps its own read, by the entities in `want`, still with `input`, since its answers are read against it.
- `Asked` becomes a per-chunk lookup with the same interface (`.alias`, `.alias2`, `.alias3`, `.collide`).
  `decide_chunk` and `collisions` keep their logic. No parallel path; the whole-table read is gone.
- Lookups stay pair-keyed and status-agnostic, as now: open, leased, answered and failed all count as asked.

### B. A deliberate way to ask again: a narrow stamp, the question's version only (spec; build only with A)

Today an answered pair is never asked again, whatever changes. That is right for cost. But it also means a new alias
guide (`alias-v1` → `alias-v2` for the first opinion) would reach no answered pair, and nothing says so.

**The rule.** A pair's question is keyed by `(kind, a, b, stamp)`. The stamp is the version of the question: its guide
id and an `ALIAS_STAMP` constant bumped on purpose. A pair is asked again only when its latest task's stamp differs
from the current one. The old answer stays, its calls stay, and the decision reads the newest answer.

**What stays out of the stamp: the evidence that changes every run.** Measured on the replay's answered pairs:

- **The text.** 77% would get a different text by the end of the replay.
- **A post-count bucket** (1 / 2-4 / 5-19 / 20+ posts on either side): it moved for 33% (1,548 of 4,744) within 7 runs.
  A stamp on that would ask a third of all pairs again every few days.
- **The made name, type and maker.** They never change (identity decides on them as made). A stamp on them would never
  move.

More evidence about an unsure pair already has its own question: the second opinion (`alias2`, other posts) and the
unsure queue (`alias3`/`alias4`, each side's facts). Re-asking `alias` would duplicate them.

**Reuse across merges and new roots is already the rule.** Answers are per entity pair, merges are redirects, and
`decide_pair` reads the pair's own answer whatever its roots are. Nothing to add. A carry-over at cluster level
(an answer between a1 and x read as the answer between a2 and x, when a1 and a2 are one cluster) is **not**
recommended. It would save at most 2.4% of tasks, and the other pair is different names, whose answer can differ (a
version or a handle inside a cluster). That is a meaning-level judgement, for Mark X's accuracy work, not a cost fix.

The one cheap part worth taking is a **deferral**: in a run, ask one member pair per two clusters and leave the rest
for the next run, by when the first answer may have merged them. The replay measured it at 29 of 4,744 tasks (0.6%).
Optional.

### C. Side finding: the unsure queue's merges pass the 6-name cap (a separate small fix, same module)

`third()` checks `cluster_size(root a) + cluster_size(root b) <= MAX_CLUSTER` for each decision separately, against
the book as it stood before the chunk's merges. Several `third` merges into one cluster in one chunk each pass the
check, and `merge()` then applies them all.

- **In the replay** (synthetic answers, so the size is exaggerated), 107 `third` redirects built clusters of 68, 13,
  11, 10 and 7 names. entity_bands.json says "never past 6 names a cluster".
- **On the server** no `alias3`/`alias4` task exists yet, so it has not happened there.
- **The fix.** `third` keeps a running cluster size, as `chain_guard` does with its `size` and `parent`. A merge that
  would pass MAX_CLUSTER stays queued (`chain`).
- **The test.** Three `third`-eligible pairs into one cluster of 4: only the first merges.

Separately: the replay's v10.19 code asked 942 `alias3` and `alias4` questions (37 and 905), while the server's overview lists
none. Check that the server's decision runs reach `third` (the band's `on`, the reasons) at the next real-data check.

## Test plan

1. **Module tests** (`tests/test_markx_entities.py`, synthetic names):
   - an answered pair is never asked again after a merge, a new post on either side, a queue close and re-queue, or
     a backlog re-decision;
   - after A, the stage's tasks and decisions are identical to before on a two-run fixture;
   - after B, bumping `ALIAS_STAMP` asks each answered pair exactly once more, and the decision reads the newest
     answer;
   - C's cap test.
2. **The replay** (the 0211 replay script, kept in `plan/research/alias-0211/`, private).
   - Run it on a `prep_mxreal` clone before and after.
   - **Bar:** the same pairs asked (4,744 tasks, 0 re-asks) and the same merges.
   - With B: a stamp bump asks every answered pair once, and runs after it ask none again.
   - With C: no cluster past 6 names.
3. **Memory, at the server's size:**
   - Inflate the clone's alias tasks to the server's count (357k, real-size inputs).
   - Measure one incremental entities stage's peak RSS and its `load` time before and after A.
   - **Bar:** at least 1.5 GB lower peak and at least 4 s less a run.
4. **The real-data check** once on main for the release (WORKFLOW.md).

## Expected saving

- **Haiku calls:** about nothing. There is no re-asking to remove. The optional deferral saves about 0.6% of alias
  tasks (roughly 2,000 of the server's 357k so far, about $1).
- **Decision run (A):** about 1.8 GB less peak memory and 4.4 s less on every run, incremental and full. This grows
  with the task count: alias tasks only accumulate.
- **Correctness (B, C):** a guide change can reach answered pairs, on purpose. Clusters keep to their documented
  6-name cap.
