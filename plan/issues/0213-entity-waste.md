# 0213 — Entity answers paid for and refused: bad entries dropped, the rest stored (v10.20)

Status: **built** (branch `v1020-entity-waste` from v1020). Not merged, not pushed, not deployed. No migration.
Private: `plan/research/entity-waste/` (scripts, the clone's calls, the blind labels).

## Why
The worker's logs since 0191's settings (14 Nov 01:45 – 16 Nov, `plan/research/markx-run-2026-11-07/log*.jsonl`):
of 71,061 entities answers asked a first time, **60,530 were stored (85.2%)**, 4,146 refused (5.8%), 6,385 missing
(9.0%). The refused and the missing were asked again in the same cycle (10,535 answers, $12.74 of the $79.91 spent
on entities); what failed again went back to the queue.

Why answers were refused (5,608, the retries included):

| reason | answers | |
|---|---|---|
| a relation `published` | 2,311 (41%) | **the lease's stale schema**: `mx_guides` keeps the schema a guide was first loaded with (a guide is never edited), so ent-v4.2's `published` relation, added to the code's set in v10.10.1, never reached the worker; the worker refused, asked again and posted, and the server (which checks with the code's schema) took it |
| one span not in the post | 2,651 (47%) | one bad entry refused the whole answer |
| one version not in the post | 273 | the same |
| more than 20 entities | 261 | the same |
| `recommended` on a non-document | 74 | the same |

The **missing** ones are not this fix: 4,529 were in calls that failed whole (the API unreachable, the weekly limit,
refusals) and 4,731 were left out of answered calls (the model's output lacked their line). Its own issue.

## What it does
- **`validate.salvage(kind, answer, input, guide)`** (the module that owns validation; `validate.check` runs it first):
  for `entities` and `cite`, each entry of the entity list (and of `relations`) is checked alone, by its schema and the
  server's per-entry rule (`_entity_error` / `_cite_error`, which `_entities` / `_cite` now also use: one rule).
  A bad entry is dropped; past the schema's cap (20 entities, 30 cites) the rest is dropped in order (the guide puts
  subjects, actors and versions first). **Every dropped entry is kept in the stored answer** under `"dropped"`
  (`{list, item, why}`): keep everything; nothing reads it.
- **Still asked again** (`validate.salvage_refused`): an answer whose every entity was dropped (an empty set from a
  non-empty answer is a wrong reading), and an entities answer whose every subject was dropped (ent-v4.2's rule: a post
  whose subject is a named thing never ends without it). The error says which entries and why.
- **The worker** (`scripts/markx-worker`) runs the server's own `salvage` and `salvage_refused` (imported from the
  checkout's validate.py, as 0191's rule checks are; standard library only), posts the salvaged answer, and logs
  `dropped` per call. Without the checkout (or `--no-server-rules`) it behaves as before.
- **The lease sends the schema the server checks with** (`schemas.schema_for(kind, guide)`, falling back to the stored
  one): the stale-schema refusals stop.

## What the consumers assume (checked)
- `repo.add_mentions`: a post's mentions under a guide are written once per window, and the newest valid answer's set
  becomes the post's current one (`mx_mention_sets`). A salvaged answer is therefore final for its window, and it
  replaces an older guide's set as a full answer did. The subject rule keeps a set from losing its subject that way;
  the other dropped entries are not asked for again (the cost below).
- `ent42.main_mentions / after_cite / merge_cite` read the answers' `entities` lists: the salvaged ones. The own-title
  drop and the q2 merge are unchanged.
- 0176 windows: each window's answer is salvaged alone; the shared-text rule reads the kept entities.
- `labels` (the entities label item's "extracted") reads the stored answer's `entities`: the kept ones.
- Nothing reads `relations` or `dropped`; no reader counts an answer's entities against its mentions.

## Measured
**Previously refused answers through the new check** (`measure.py`): 58 refused ent-v4.2 / cite / ent-v3 answers (the
0191 lab A/B runs, the ent-v5 sample's old run, and the 25 refused calls of the 11-05 server copy cloned from
`prep_mxreal`): **47 stored (81%)**, 11 still asked again (10 lost every subject, 1 every entity); 68 entries dropped
(spans 39, versions 19, `recommended` on a non-document 7, a role outside the set 3). Every one of the 1,818 answers
valid before stays valid and unchanged.

| set | answers | stored before | stored after |
|---|---|---|---|
| lab entities (ent-v4.2, 7 runs of 160 posts + 126 windows) | 1,225 | 1,203 (98.2%) | 1,222 (99.8%) |
| lab cite (6 runs of 98 posts) | 586 | 575 (98.1%) | 586 (100%) |
| server copy (ent-v3: its 25 refused calls, 40 valid ones) | 65 | 40 | 57 (the copy's whole: 5,541 / 5,566 → 5,558) |

**Precision of what is now kept** (blind: two labellers, ent-v4.2's and cite-v1's rules, sides hidden, 60 entities kept
from previously refused answers mixed with 60 from valid answers of the same runs):

| | right | right with its role |
|---|---|---|
| kept from refused answers | **55/60 = 92% [82–96]** | 50/60 = 83% [72–91] |
| from valid answers | 44/60 = 73% [61–83] | 42/60 = 70% [57–80] |

Not lower (the valid side holds more cited documents, the hardest entries). One "wrong" on the kept side is the
labeller's own slip (a span differing only in case, which the server's folded match takes).

**The cost of not asking again:** on the lab posts asked seven times, 14 of the 26 entries dropped from salvaged
answers were named validly by another run: a re-ask would have found about 0.8 more entities per salvaged answer, for
the price of a whole answer.

**On the week's logs** (applying the measured rates to the refused answers by reason): the 2,311 stale-schema
refusals go to 0; of the 3,259 single-entry refusals about 81% are stored. First-pass stored entities answers
**85.2% → about 90.4%** (+3,700 of 71,061), first-pass refused **5.8% → about 0.7%**; the in-cycle re-asks for
refused answers (about $5.0 of the $12.74) fall to about $0.6, about 5–6% of the entities spend. The 9% missing stay.

## Tests (only those touched; then the whole suite once)
- `insight_core.tests.test_markx_validate` (new `Salvage`: one bad entity among good ones, each kind of bad entry, the
  every-subject rule, idempotent, other kinds and shapes untouched; the 20 cap; a bad relation),
  `test_markx_ent_v42` (cite: the 30 cap, one bad entry), `test_markx_api` (the round trip of a salvaged answer: 20
  stored, the 21st kept under `dropped`, 20 mentions; the refused messages; the lease sends the code's schema),
  `test_markx_reading_windows`, `test_markx_entities`: 196 tests OK.
- `scripts/tests/test_markx_worker` (a partially bad cite answer posted once with its `dropped`, the worker's salvage
  is the server's): 91 tests OK.
- The whole backend suite (`JOBS=6 scripts/test-backend.sh`): 185 modules, 3,589 tests, OK.

## Deploying
Server and worker together (the worker imports the checkout's validate.py). No migration, nothing to set.
