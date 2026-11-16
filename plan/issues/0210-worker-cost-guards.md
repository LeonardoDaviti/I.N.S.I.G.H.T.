# 0210 — The worker's cost: the re-ask guard, a measured gate, and questions no feature reads (Stealth v10.20)

Status: **built** on `v1020-cost` (from `v1020` = v10.19). Not merged, not pushed, not deployed. Migration **0143**
(`mx_tasks.hold`, `mx_holds`, an index by kind and creation time). The worker's default `--parallel` is 20.
Private material (scripts, the fetched rows, the replay) is in `plan/research/worker-cost-0210/` (gitignored).

## Why

The server's call log (GET `/api/markx/overview`, 2026-11-14) and the worker's own logs: one night (13 Nov, 17:28 to
23:09 UTC) answered **125,735 questions for $84.95** (Claude Code's cost on each call; entities 61,659 answers and
$72.69 of it), and used up the account's weekly limit. The next morning another 116,361 (entities 57,430). Daily
spend over the week: $36-108 at API prices (the overview), $42.7-129.8 by the worker's own cost lines. The steady
state is ~1,000 new posts a day ($2.09 per 1,000 new posts after 0191).

The week 7-14 Nov by kind (the worker's logs, every call line once; answers and $ a day, mean of 8 days):

| kind | answers/day | $/day | max day | the feature that reads it | 0210 |
|---|---|---|---|---|---|
| entities | 40,327 | 40.26 | 64,112 | entities | kept; guarded |
| alias | 44,645 | 8.13 | 124,040 | entities | kept; guarded (its re-asks: a separate issue) |
| read | 17,975 | 6.33 | 48,387 | news | kept; guarded (new posts never held) |
| cite | 5,210 | 6.23 | 24,441 | entities | kept; guarded |
| track | 15,328 | 3.08 | 28,600 | tracks | kept; guarded |
| relate | 15,263 | 2.61 | 42,012 | graph | kept; guarded |
| collide | 3,574 | 1.20 | 8,613 | entities | kept; guarded |
| back | 3,701 | 1.14 | 15,521 | Back in the news (not shipped) | **stopped** |
| pair | 5,057 | 1.13 | 27,156 | news | kept (gate measured: fails) |
| perspective | 249 | 0.97 | 582 | perspectives (Shadow) | kept (the owner: used later) |
| read3 | 1,333 | 0.90 | 5,644 | news | kept |
| connect | 2,946 | 0.86 | 6,480 | news | kept; **gated** (-78%) |
| join | 2,190 | 0.56 | 8,800 | news | kept |
| merge | 1,198 | 0.54 | 3,438 | news | kept |
| rename | 1,874 | 0.43 | 7,755 | entities (the review queue) | kept; guarded |
| alias2 | 1,084 | 0.20 | 2,641 | entities | kept |
| card, headline, sheet, unit_types, check, stance, translate, briefing, sub-topics | 1,247 | 0.48 | | news, perspectives, sources, tracks | kept |
| **total** | **163,208** | **75.1** | | | |

## 1. The re-ask guard (`markx/holds.py`; repo.add_task asks it)

A planner that adds more of a kind's tasks in a UTC day than the allowance (`mx_settings.reask_guard_per_day`,
default **2,000**, null: no guard) has the rest **born held** (`mx_tasks.hold = '<kind>:<day>'`). The decision is one
place: `repo.add_task` is the only way any task is made, so every planner (the lease's, the decision run's, the jobs'
plan, the pages') is covered, and no planner was changed.

- **New posts' tasks never count and are never held**: a task whose post (`a` or `b`) was fetched or surfaced in the
  last 24 hours and is dated in the last week (the fresh lane's rule, `tasks.fresh_sql`). The embedder's kinds
  (`embed`, `embed_name`: no model cost) are never held.
- **Per day, not per call**: the night's backfill came 500-1,000 tasks a lease call (plan_posts, plan_windows), never
  2,000 "at once"; a kind's day is what a re-read of the archive looks like.
- **A held task is asked last, automatically** (the owner, 2026-11-16: no budget, no spending cap): a lease takes
  every task that is not held first (`repo._lease` orders by held, then as before). The owner may **stop** a hold
  (none of its tasks is leased) or **release** it (leased in its turn; the rest of that kind's excess that day is not
  held). `POST /api/markx/holds {key, state: low|stopped|released}`; `POST /api/markx/settings/reask-guard {per_day}`.
- **/markx, Worker tab, "Held tasks"**: each hold as "held: 61,400 entities readings (long posts' windows among them),
  est. $72.10" with its day, its state and the buttons. The price is the kind's newest 300 answered tasks' tokens at
  Haiku's list price (every call a task took), times the held tasks.
- **No lock shared with a lease**: holding writes nothing but the task's own column (`mx_holds` holds only the owner's
  word). The count is per process: read from the database (the new `(kind, created_at)` index) at most every 30 s a
  kind and once more when the process's own count reaches the allowance; a post's freshness is read only past it.

**Measured on a scratch clone of prep_mxreal** (`planner_replay.py`: the entities planner over every post, 12 calls,
one transaction rolled back; a guide switch re-reading the archive):

| | tasks planned | held | seconds | peak RSS |
|---|---|---|---|---|
| v10.19 (base tree) | 12,054 | (none) | 4.0, 4.5 | 80.2, 89.2 MB |
| 0210 | 12,054 | **10,054** (2,000 asked in turn) | 6.1, 6.2 | 71.3, 71.1 MB |

The guard costs ~0.15 ms a task past the allowance (one key lookup of the post's freshness); peak RSS is lower.

**The week replayed** (`replay_week.py`, the worker's logs; answers and $ a day):

| | answers/day | $/day |
|---|---|---|
| before | 163,208 | 75.1 |
| after, holds asked last (the default) | 157,209 | 73.3 |
| after, every hold stopped | 21,821 | 10.9 |

With the default the guard saves nothing by itself: the held tasks are still asked, after everything else. What it
changes is that a re-read of the archive never runs ahead of new work, and that it shows on /markx with its price
before it is spent, where the owner can stop it. The second row's saving is the connect gate and back.

## 2. Confidence gates, measured blind

The bar (as identity's bands): on the cases the cheap decision settles, it agrees with Haiku's stored answer at a
point >= 97% and a Wilson 95% lower bound >= 90%; the bar is chosen on a dev half (task id hash even) and read on
the held-out half. Only gates that pass ship.

| kind | cheap decision | rows (real answers) | settles (test) | agrees (test) | Wilson low | ships |
|---|---|---|---|---|---|---|
| **connect** | `different` when the two first posts' stored vectors are below cosine 0.55 | 600 (prep_mxreal, the server's 11-05) | 237/303 = **78.2%** | 235/237 = **99.2%** (dev 236/239) | **97.0%** | **yes** |
| pair | `different` below cosine 0.50 (dev's best) | 1,275 (prep_mxreal) | 55/622 = 8.8% | 48/55 = 87.3% | 76.0% | no |
| entities, later windows | no new entity when every name-like word of the window's new text was already in the text before | 1,606 windows of 531 long posts (the server's answers, read-only GETs of the post panel) | 23/756 = 3.0% | 20/23 = 87.0% | 67.9% | no |

- **connect** (`decide.connections`, `Config.connect_settle_below = 0.55`; `pairing.post_cosines`): a pair below the
  bar is never asked (`Ask.answer(add=False)`); an answer already stored is read as before; the run's counts say how
  many were settled (`tasks_settled`). Of the 31 held-out and dev connect answers that were not `different`, 5 were
  below the bar (lost connections); the rows it settles are 98.7-99.2% right. Saving on the week's volume: **~2,300
  connect questions and ~$0.67 a day** (78% of connect's $0.86); the server's connect backlog (39,804 pairs waiting a
  run, capped 100 a run) shrinks by the same share.
- **pair** fails at every bar (agreement 66-92%): Haiku often says `mention` or `reaction` on posts the vectors call
  far apart.
- **entities' later windows** fail: Haiku names things in a window that the text before already wrote but its earlier
  answer did not list, and lowercase names; the rule settles 2-3% of windows and is 74-87% right.
- **Not measured: alias, track, rename, relate.** No local copy holds their answers (prep_mxreal predates them;
  prep_scale's are synthetic), and the server's pages do not expose the cheap signals (a track item's cosine, a
  pair's name-vector cosine) with the answers. Measuring them needs a read-only SQL on the server or a fresh copy;
  the queries are below.

## 3. Questions no feature reads (`markx/consumers.py`)

Every kind names its consumer (a feature in `FEATURES`, `CONSUMER`; a test keeps every kind named). A feature is on by
its default or the owner's word (`mx_settings.consumers`, `POST /api/markx/settings/consumers {feature, on}`; /markx
"What is asked"). While a feature is off: its kinds' planners are skipped (the lease's; the decision run's back and
perspectives stages); a task still made by any path is **born closed** (`failed`, last_error "not asked: no feature
that reads it is on (0210)", kept); its open tasks are closed the same way by every plan job. Switched on, they open
again.

- **back: off** (Back in the news, 0136: its bar failed at 68%, not shipped): 3,701 answers and $1.14 a day on the
  week, 0 now.
- **perspective, sheet, stance: on** (the owner, 2026-11-16: used later).
- **The dropped features plan nothing already**: Later developments (0203: no task kind left), the components rule and
  suffix merges (0203: off in `entity_bands.json`); nothing to stop.

## 4. Track and entities, the two volume questions

**track** (123k answers for 4 tracks; the four track pages' counters, read-only GETs): 123,376 tasks, of which
**98,820 (80%) are the history passes** (each track's description read against the archive once a version), 22,461
the recent scan and 2,004 the tracks' own sources. The recent scan passes 16-61% of each track's new posts (bars
0.47-0.61); with ~1,000 new posts a day that is ~1,400 track questions a day (~1.4 a new post, about $0.3 a day). The
history passes were one-offs (two of the four are done; the other two are still walking back); a new description
version starts one again, and the guard now holds it past 2,000 a day. Haiku said `out` on 75-99% of each track's
judged posts, so a cosine gate could settle many, but no copy holds the items' cosines with their verdicts: not
measured (query below).

**entities** (40k-64k answers a day on 10-14 Nov): the long posts' later windows (0176) over the whole archive, with
the reading window at "everything". On the 11-05 copy a post needs 0.446 later windows on average (22,021 for 49,384
posts; 7,854 posts are longer than one window, 394 of them 12 windows); every one of the 531 sampled long posts of
that copy had its windows answered on the server. It ends: the windows planner asks only posts with exactly one
entities task under the guide and marks the rest, `plan_posts` and `plan_last_posts` only posts with none, so an
unchanged post is never asked again by any planner; the worker found nothing left at 23:09 UTC on 13 Nov, and on 16
Nov (after the weekly limit reset) entities answered 12 questions. The 14 Nov morning's 57,430 came after that night's queue was empty, so they were
newly planned posts (first windows and their windows), not re-asks; which posts (an archive import or a window cap
change) the logs cannot say. Steady state: ~1,446 entities questions a day for 1,000 new posts. A guide switch or a
cap change re-reads the archive by design; it is now held past 2,000 a day and shown with its price.

## 5. The worker

`--parallel` defaults to 20 (was 3; the owner's runs passed 20-40). It already stops on a usage limit (6e4f23e).

## Not done

- No daily budget or spending cap (dropped by the owner, 2026-11-16).
- Gates for alias, track, rename and relate: not measured (no local rows). The read-only queries to run on the server
  (or a fresh copy), each joining the cheap signal to the stored answer:
  - track: `SELECT i.cos, i.verdict, i.confidence, i.origin FROM mx_track_items i WHERE i.verdict IS NOT NULL`
    (settle `out` below a cosine; per track, held out by post id hash);
  - alias: `SELECT t.a, t.b, 1 - (va.v <=> vb.v), c.answer->>'relation' FROM mx_tasks t JOIN mx_calls c ON c.task_id =
    t.id AND c.valid JOIN mx_entity_vectors va ON va.entity_id = t.a JOIN mx_entity_vectors vb ON vb.entity_id = t.b
    AND vb.model = va.model WHERE t.kind = 'alias'` (settle `different` below a name cosine).
- The alias re-ask question (357k answers for ~310k entities) is a separate issue (the owner, 2026-11-16).
- The decision run's peak RSS with the connect gate was not measured on a copy (one query of the pairs' cosines a run).

## Tests

`test_markx_holds` (8), `test_markx_consumers` (5), `test_markx_decide` (+1: a far connect pair settled, asked with the
gate off), `test_markx_pairing` (the legacy comparison runs with the gate off), `test_markx_back`, `test_markx_jobs`
(the features each test turns on), `scripts/tests/test_markx_worker.py` (89, OK), the frontend `markx.test.tsx` (17,
OK; typecheck and lint clean). The full backend suite: see the report.
