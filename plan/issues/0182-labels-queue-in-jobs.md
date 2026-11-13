# 0182 — The Labels queue built in the jobs process (v10.16 slice P)

Status: **built** (branch `v1016-labels` from `v1016`). Not merged, not pushed, not deployed. Migration **0124**.

## The problem

0177 item 6: the Labels tab's queue (`labels.population`, called by `GET /api/markx/labels`, `/labels/precision`,
`/labels/items/{id}` and `POST /labels`) is a whole decision reading (decide.load and think) plus every answered
connect and entities task with its answer. It ran inside insight-api on the first open after each decision run: on a
server-sized copy a 2.4 GB peak of Python allocations, RSS ~3.4 GB after (glibc keeps the arenas). The owner's Grafana
shows insight-api at several GB, and insight-ingestion peaking at ~7.7 GB during decision runs: the build must not add
to either long-lived process, nor run beside a decision run.

## What was built

1. **The job "labels"** (markx/jobs.py). The runner builds the newest decision run's queue right after each decision
   run, in the same tick, once the run's process has ended: in a **process of its own** (`_in_own_process`, spawned;
   its memory goes back to the OS when it exits; never in the scheduler or the API) and one REPEATABLE READ
   transaction of its own (`decide.snapshot`). Never beside a decision run: the runner runs one job at a time. The
   run is committed before the build starts, so a failed build never touches a run; it is recorded in mx_jobs
   (`labels`: ok false, the error) and tried again GAP (5 min) after its start. `due()` also returns "labels" on any
   pass that finds the newest run's queue not kept for this code (the first start after a deploy), after a due
   decision run and before the candidate finder. mx_jobs.last of "labels": run, items, queued, seconds, peak_mb.
2. **Kept as rows** (migration 0124). `mx_label_queues`: one header a queue, unique by (decision run, code stamp):
   the cut, the offered order, the pools in order, each (pool, split)'s size, each feature's bar, the reading's
   `now`, the build's seconds and the process's peak MB. `mx_label_queue_items`: the whole population (queued or
   not), one row an item, in population order. `labels.stamp()` is the sha256 of decide's version and
   incremental.code_stamp (the decision reading's modules), labels.py, schemas.py (the guides) and the settings: a
   queue of another stamp is never read, so a deploy that changes the reading builds it again. The table is analysed
   after each build (the pages read items by key).
3. **The API reads only what is kept** (`labels.kept`): the header, then the items a page needs (`Kept.ensure`: the
   queued ones for the queue view, one for an item or an answer, the labelled ones for precision), by primary key.
   `score` takes the (pool, split) sizes and the bars from the header (`Queue.sizes`, `Queue.bar_of`: the same
   numbers a built queue counts). The in-process cache (`labels._cache`, `fresh`) is gone. One build path is left:
   `labels.queue` (population, then build), called only by `labels.keep` in the jobs process (and the tests); the API
   calls only `labels.kept`, and its tests patch every builder to fail if a route reaches one.
4. **Being built.** No kept queue of this stamp for the newest run: `GET /labels` and `/labels/precision` answer
   `building: true`, with the last kept queue of this stamp meanwhile (the tab shows one line), or with none (total
   0, no features: the tab says "The queue is being built" and asks again every 30 s); the item routes and the
   answer answer 503 then. Nothing is ever built in the API.
5. **The build's own peak, cut.** Its peak was the answered tasks' answers, not the reading: `population` loaded
   every answered entities task's whole answer (138k on the inflated copy below: a 532 MB Python peak, more than the
   decision reading's 80 MB). It now reads in SQL only what it uses (the verdict's relation, confidence and reason;
   whether `entities` names anything, by Python's truth of the value, every JSON type), a page of 5,000 rows at a
   time; lets the decision reading go before those reads; and keeps of a judged task only its id and posts (not its
   ~1.5 kB input). The same items in the same order.
6. **Size.** ~200-250 bytes an item row with its index (127,585 items: 25 MB). The items of the newest `KEEP_ITEMS`
   = 3 queues are kept (~100 MB at server scale); older queues keep their headers (items_kept false). mx_labels is
   untouched: keep everything.

## How it was proved

Scratch copies (never the originals; never the server), migrated to 0124, a decision run of this code first, one
pinned `now` for old and new:
- the copy of the server snapshot with real Mark X answers (49k posts; 6,841 items, 96 queued), then the same copy
  with every answered entities task copied 24 times (138k answered; 127,585 items) to reach a server's count;
- the copy of the lab database: it has no answered task, so its queue is empty (identical, and proves nothing more).

Synthetic labels by two labellers on ~60% of the queued items and some others. **Identity:** the old code (v1016's
image) and the new answered the three GET routes byte-identically (the queue view, each labeller's precision, every
queued item's view); in-process, the kept queue against one built in the same snapshot: every item's fields, order,
pools and their order, cut, sizes, bars, every view and precision for three labellers identical; the old and the
new `population` on the inflated copy: all 127,585 items with every field (rank included), the order, pools and cut
identical.

**Re-proved 2026-11-13** (after the memory rewrite of `population` was finished and checked): v1016's labels.py
against this branch's, one REPEATABLE READ transaction, `now` pinned 10 minutes after the newest run, rolled back. On
the inflated copy: `population` 127,608 items, every field (rank included) and the order identical; the kept queue
(`keep` then `kept`) against v1016's `queue`: run, offered order (98), cut, pools in order, every kept item's fields
and its `seq` order identical; `queue_view` and `precision` for both labellers and 253 item views (every queued and
every labelled item, per labeller) byte-identical as JSON. On the lab copy: empty both ways.

**Tests.** test_markx_labels: the kept queue reads as the built one on a seeded world (before and after labels); the
answers read in SQL as Python read them (every JSON type of `entities`, verdicts with fields missing or a string
confidence); being built until kept, the last kept one meanwhile, another stamp never read; pruning keeps headers;
the routes with every builder (`population`, `build`, `queue`, `keep`, `decide.load`, `decide.think`) patched to
fail the test; "being built" through the routes (200 building, 503 on an item and an answer). test_markx_jobs: `due`
with a missing queue and after a failed build; built right after the run in the same tick; a failed build leaves the
run committed and ok and is retried after GAP; the first start after a deploy builds the missing queue.

## Numbers

| | before | after |
|---|---|---|
| insight-api RSS opening the tab, real answers (import 79 MiB) | 208 MiB (116 after malloc_trim) | 82 MiB |
| the same, inflated copy | 656 MiB, high-water 760 (569 after trim) | 82 MiB; re-measured 2026-11-13: 76 MiB (import 73), the three GET routes |
| first GET /api/markx/labels, inflated | 8.0 s | 0.09 s (re-measured: 0.15 s) |
| the build's process peak, inflated (no tracemalloc) | 732 MiB, 17.0 s | 223 MiB, 4.5 s (re-measured: 733 -> 221 MiB, 6.3 -> 3.3 s) |
| the build's Python peak, inflated (tracemalloc) | 532 MiB | 85 MiB (re-measured: 533 -> 86 MiB) |
| the labels job (child process), inflated: seconds, peak | none | 12.2 s (5.1 the reading, the rest storing 127k rows), 235 MiB; re-measured through the runner's spawned child: 4.4 s, 218 MiB |
| the labels job, real answers | none | 1.5 s, 185 MiB |

Re-measured 2026-11-13 on the inflated copy (127,608 items at the pinned `now`; 127,565 at the job's own `now`), each
number a fresh process; the server's insight-ingestion peaks at ~6.6 GB in decision runs, and the labels job runs
after the run's process has ended, never beside it, so its ~220 MiB is never added to that peak.

## Left

- The server-sized copy of 0177 (148k posts, 2.4 GB peak) was dropped; it was not rebuilt. Here the reading itself
  (decide.load and think) was 80 MB; on the server it is larger (0177: a full run's questions stage ~2.9 GiB), and
  it is what is left of the build's peak: in the child process, once a run, and given back when it exits. Cutting it
  means changing decide.load (shared with the decision run), not done here.
- A queue's `now` is the build's (right after the run), where the API's was the first open's; the two differ only by
  what was answered between the run and the open, which the next run's queue holds.
