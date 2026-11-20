# 0251 — The incremental decision run under its memory budget (v10.28)

Status: **built** on a branch from v1027, not merged, not pushed. No migration. Module tests only.

## Why

The v10.26 real-data check (B2) failed the incremental decision run: 910.6 MB, 115.3 s, CPU 72.8 s against its budget
(600 MB, 90 s); v10.24's was 695.6 MB, 91.7 s. 0248 measured both codes on one state peaking in the entities stage,
~330 MB above what the run held before it, and left the cut as "its own work".

## How it was measured

One copy of the server's data (the check's scratch state after the v10.26 check; 162k posts, 443k entities, 1.98M
mentions, 358k of them not linked yet: every incremental run links its LINK_LIMIT of 6,000 and has real work). A
harness (scratch, not committed) runs `decide.run` as the jobs process does (ENTITY_BUDGET 45 s, LIMIT), in a
REPEATABLE READ transaction **rolled back at its end**, so every run, base and head, starts from the same state:

- per stage: wall, CPU, the RSS at its start, its own peak (VmHWM reset at each stage, `utils/peak`), after
  `gc` + `malloc_trim` (as `Jobs.decide` does between stages); the entities stage split into its steps
  (`run_book`, `identity.stage`, repairs, shown, invariants, addresses, renames, handles);
- an RSS sampler thread (20 ms) keeps the Python stack at each stage's high-water;
- tracemalloc snapshots (one run) at the entities stage's start, before the collisions and after `identity.stage`;
  `sys._debugmallocstats` at the entities stage;
- the reading's and News' code stamps fixed for both codes (the kept state stays warm: the run is incremental), and
  the story window held where it is (a stable state run after run).

A base run was committed first (full), then each measured run is the incremental one after it.

## What held the memory (base, incremental)

| where | what | MB |
|---|---|---|
| entities stage, the collisions' new questions | up to COLLIDE_CAP (1,000) entities' every first mention and the **whole texts** of their samples (~8,000 posts, `tasks.load_posts`) at once | +200-330 transient: the run's peak |
| entities stage, a split's posts (`match_pick`) | every post of the entity read whole (text, links, linked page) to compare its date and title | transient, per answered collision |
| the reading's kept state, to the run's end | the judge tasks' index (`refresh`: 127k tasks, (kind, hash) -> (id, status, n), and id -> key, and what the last run saw), the kept and this run's inputs (123k each), the near-copies: held beside the entity book for the few rows `save` writes | ~140 of the ~170 MB of objects at the entities stage's start |
| connections (and the first pass) | `pairing.story_pairs` read every pair of stories at the bar (393k rows at the connect bar) and kept the window's (58k) in Python | +170 transient |
| News | every window post's links joined into one string a post, held at once (`post_digests`) | part of News' +100-130 |

## What changed (each in the module that owns it)

- `identity.collisions`: the new questions COLLIDE_PAGE (50) entities at a time, each page's mentions and texts let go
  before the next: the same questions in the same order.
- `identity.match_pick` reads `tasks.heads` (new: each post's date and title as `load_posts`' Post shows them, the same
  posts) instead of whole posts.
- `incremental.release` keeps only what `save` writes of the inputs, near-copies and tasks (`State.pending`, from
  `_pending`, the one computation `save` uses) and lets the index and the input dicts go; a question asked after it
  (the briefing) finds its task by query (`task_of`), a task it adds goes to `pending` (`task_added`); `Ask` reads and
  writes the index only through these.
- `pairing.centroid_cosines(at=, within=)`: the window in the database; `story_pairs` passes its firsts and window
  (Policy.story_within still decides, on the rows the database kept).
- `news.post_digests`: the links streamed (a named cursor, 2,000 rows a page), each post digested as it comes.

## Before and after (the same state, incremental)

RESULTS

## Identity

IDENTITY

## Tests

TESTS

## Risks and what is left

RISKS
