# 0191 — The Mark X worker's cost (v10.17)

Status: **built** (branch `v1017-cost` from v1016 bae0ac0). Not merged, not pushed, not deployed. No migration.
The worker (`scripts/markx-worker`) changes on the owner's device; the server changes are three verdict rules
(`graph.py`, `back.py`, `identity.py`), one track rule (`tracks.py`) and one helper moved (`validate.back_numbered`).

## Why

The worker's logs of the week 7-13 Nov (`plan/research/markx-run-2026-11-07/log*.jsonl`, 84,820 calls) add up to
**$424 at list price** (Haiku 5.5: $0.10 / M input, $0.50 / M output, measured from Claude Code's own cost on a
one-line call). The owner runs it on a Claude subscription and hit the weekly limit, so calls and tokens count, not
only dollars.

| | $ | share |
|---|---|---|
| output tokens | 248.82 | 59% |
| input tokens (billed at 1.59x list on average: 1-hour cache writes at 2x) | 175.32 | 41% |
| the four biggest kinds: entities 178.43, alias 55.54, read 50.37, cite 49.55 | 333.89 | 79% |

Steady state (every kind's answers per new post over the week, priced at the week's cost per answer): **$2.97 per
1,000 new posts** (the table at the end).

## How it was measured

Every quality number comes from a labelled lab set, asked through the worker's own system prompt, prompt and call
size (`system_for`, `prompt_for`, `PER_CALL`), one `claude -p` call a batch, the answers checked by the server's
`validate.check`. Two runs at Claude Code's default give the **noise**: a change ships only when its numbers sit
inside it. Intervals are Wilson 95%.

| kind | the set (plan/research, gitignored) | items | gold |
|---|---|---|---|
| entities (ent-v4.2) | `lab/markx/proto/out/entv42_v1/set_{test,ordinary}` rendered by `tasks.entities_input` | 160 posts | the blind labellers' documents and sources (340) |
| cite (cite-v1) | the same posts the cue rule passes, `ent42.cite_input` | 98 | the same gold (299) |
| read (read-v2) | `lab/markx/kind_final.json`, rendered by `tasks.read_input` from a server copy | 199 | kind (172), events (177) |
| alias, alias2 (alias-v1) | `0130a-build/lab_inputs.json` | 198 | relation |
| relate (relate-v1) | `g2_v1/items.jsonl` test | 240 | relation (G2's) |
| back (back-v1) | `back_v2/items_test.json` | 98 | label |
| collide (collide-v1) | `entity_identity_v3/collide_test3_odd` | 117 | split or not |
| merge (judge-story-v1) | 64 merge questions of the 11-05 server copy | 64 | none (agreement only) |

The A/B's Haiku spend, everything: **$2.92 at list price** (6,701 items in 714 calls, the cache runs included).
Its scripts, inputs and answers are in `plan/research/worker-cost-0191/` (gitignored: real posts): `ab.py` (one
arm), `score.py` and `pairs.py` (agreement, gold), `gate.py`, `gate_relate.py`, `gate_back.py` (part 5),
`cache_table.py`, `logcost.py`, `refusals.py`, `final.py`, `rules_check.py`; they expect to sit in a checkout's
`scratch/` (they import its backend and worker).

## 1. Thinking effort, by kind

The worker never passed `--effort`. Claude Code's default thinks a lot on the extraction kinds: on the lab's entities
59% of the output tokens are thinking (946-1,201 output tokens an item; the week's logs say 975), on cite 88%.

| kind | arm | output / item (thinking) | first-pass valid | vs a default run | gold |
|---|---|---|---|---|---|
| entities | default (2 runs) | 946, 1,201 (557, 822) | 317/320 = 99.1% | each other: same entity set 27.4%, same subjects 63.1%, name Jaccard 0.62 | found 380/680 = 55.9% [52.1-59.6] |
| | **medium** | 760 (371) | 157/160 = 98.1% | 33.1% [28.1-38.5], subjects 61-65%, Jaccard 0.65-0.67 | 191/340 = 56.2% [50.9-61.4] |
| | low | 389 (49) | 155/160 = 96.9% | 26.4%, subjects 56-57%, Jaccard 0.57-0.60 | 175/340 = 51.5% [46.2-56.7] |
| cite | default (3 runs) | 1,483 / 1,413 / 1,676 | 292/294 = 99.3% [97.6-99.8] | each other: 41.0% [35.5-46.8] | 493/897 = 55.0% [51.7-58.2] |
| | **low (2 runs)** | 1,046 / 948 | 186/196 = 94.9% [90.9-97.2] | 43.1% [39.0-47.2] | 327/598 = 54.7% [50.7-58.6] |
| | medium | 1,625 (more than default) | 97/98 | 37.5% | 169/299 |
| read | default (3 runs) | 586 / 518 / 549 | 594/597 | each other: 83.5% [80.3-86.3] | kind 79.5%, events 90.8% |
| | low (2 runs) | 329 / 340 | 397/398 | **77.7% [75.2-80.0]: outside the noise** | kind 78.2%, events 87.9% |
| | medium | 490 | 198/199 | 80.1% [76.7-83.1] | kind 79.1%, events 89.3% |
| alias (alias2 inputs) | default (2 runs) | 132 / 124 | 396/396 | each other: 91.4% [86.7-94.6] | relation 89.9%; same at >= 0.9: 184/184 |
| | **low** | 106 (0) | 198/198 | 90.9% [87.7-93.4] | relation 89.9%; same at >= 0.9: 83/83 |
| back | default (2 runs) | 1,038 / 1,037 | 196/196 | each other: 85.7% | development precise 39/46 = 84.8% |
| | low | 633 | 98/98 | **75.5% [69.0-81.0]** | development precise 19/25 = 76.0% |
| | medium | 1,090 (no saving) | 98/98 | 79.6-89.8% | 20/25 |
| collide | default (2 runs) | 474 / 424 | 234/234 | each other: 91.5% | split-or-not right 88.9% |
| | low | 255 | 115/117 | 88.7% | 84.6% |
| relate | every arm | 94-96 (no thinking at any level) | 239-240/240 | 77-81% | the same |

**Chosen** (`EFFORT` in the worker; `--effort kind=level` overrides): **entities medium, cite low, alias low, alias2
low** (alias2 asks alias-v1 with alias2-form inputs, which is what the lab set holds). Every other kind keeps Claude
Code's default: read low falls outside the noise (medium's interval meets the noise's only at its edge, for an 11%
saving), back low loses development precision (76% vs 85%), collide low loses 4 points of gold, relate does not
think at any level. track (100 output tokens an item, no labelled set) has nothing to cut; perspective and stance
(4,600 and 2,900 output tokens an item) have no local questions to measure on and stay at the default.

cite low answers as well as the default (gold and agreement within the noise) but its first pass is valid 4.4 points
less often (5 of 98 in each run: lines missing, spans not in the post); the worker asks those again in the same
cycle (part 4), which the saving below already pays for (4.4% of cite's spend).

## 2. The prompt cache

Claude Code's JSON splits the input (`usage.cache_creation.ephemeral_1h_input_tokens`, `cache_read_input_tokens`).
On a subscription it writes **every** prompt to the 1-hour cache, billed at 2x input, and a call of distinct items
never reads it back: the lab runs show it (entities: 251,896 tokens written to the 1-hour cache, 16,998 read). The
week's input was billed at 1.59x list overall, 1.8-2.0x on most kinds.

Claude Code's switches (found in its binary and `--help`, checked on calls): `DISABLE_PROMPT_CACHING=1` (no cache:
every token at 1x), `CLAUDE_CODE_PROMPT_CACHE_TTL=5m` (the 5-minute cache: writes at 1.25x),
`CLAUDE_CODE_MESSAGES_PROMPT_CACHE_TTL=5m` (the messages only), `FORCE_PROMPT_CACHING_5M`.

| kind (per call) | mode | input tokens / item | read | written 1h | written 5m | input $ / 1k items | x list |
|---|---|---|---|---|---|---|---|
| entities (20) | default (1-hour) | 1681 | 17% | 83% | 0% | 0.2823 | 1.68 |
| entities (20) | 5-minute | 1681 | 17% | 0% | 83% | 0.1775 | 1.06 |
| entities (20) | off | 1681 | 0% | 0% | 0% | 0.1681 | 1.00 |
| read (20) | default (1-hour) | 629 | 11% | 89% | 0% | 0.1131 | 1.80 |
| read (20) | 5-minute | 629 | 11% | 0% | 89% | 0.0710 | 1.13 |
| read (20) | off | 629 | 0% | 0% | 0% | 0.0629 | 1.00 |
| back (8) | default (1-hour) | 1480 | 13% | 87% | 0% | 0.2596 | 1.75 |
| back (8) | 5-minute | 1480 | 13% | 0% | 87% | 0.1630 | 1.10 |
| back (8) | off | 1480 | 0% | 0% | 0% | 0.1480 | 1.00 |
| back (1) | default (1-hour) | 3324 | 100% | 0% | 0% | 0.0334 | 0.10 |
| back (1) | 5-minute | 3324 | 44% | 0% | 56% | 0.2491 | 0.75 |
| back (1) | off | 3324 | 0% | 0% | 0% | 0.3324 | 1.00 |

With several items a call, each mode's own item order kept it from reading another mode's messages. One call went first (the guide's
prefix warm), then eight at once. The one-a-call `default` row is not comparable: its single-item prompts were the
same as the 5-minute run's of a few minutes before, and it read them all back. On those one-item prompts the guide
is 44% of the input: written once at 1.25x and read at 0.1x it brings the input to 0.75x; with 8 or 20 items a call
it is 11-17%, and the 5-minute cache's 1.25x writes cost more than it saves (1.06-1.13x). The 1-hour default costs
1.68-1.80x wherever the items differ.

**Chosen** (`--prompt-cache`, default `off,relate=default,back=default,read3=default,websearch=default,merge=5m,
sheet=5m,stance=5m,subtopics=5m,probes=5m,scout=5m,source_judge=5m,news_sections=5m,unit_types=5m`):
- **off** for every kind of several items a call whose input was billed above 1x;
- **Claude Code's default** kept for relate, back and read3, whose input the week billed at 0.74-1.08x (their repeated
  runs ask the same prompt again and read it back), and for websearch (its turns re-send the conversation);
- **5m** for the kinds asked one item a call; under it a kind's first call of a cycle goes alone and its other calls
  wait for it (`Worker.warmed`), so they read the guide instead of each writing it. perspective (one a call, but its
  stories are long: the guide is about a fifth of its input) is off, where the two are even.

## 3. Refusals

All 3,512 refused calls of the week were the same: `API Error: Haiku 5.5 can't help with this`, details `[bio]` (the
API's biology classifier), on 69,287 items' worth of calls (each answers none of its items).

| | refused calls | |
|---|---|---|
| 7 Nov to 8 Nov 09:40 (before the halving) | 3,435 | entities 2,174, read 1,261: each a batch of 20, asked whole twice, released, leased again next cycle |
| since (the halving) | 77 | entities 48, read 10, track 11, cite 8; 15 tasks isolated (entities 9, read 3, track 3) |

Before, a refused batch was asked whole a second time before the halving began, and a task isolated by the halving
was posted as an empty answer (a failed try), then leased again in a batch of 20 the next cycle, which was refused
again: about 11 calls each time, up to three times. Now (`Worker.isolate`):
- the halving starts at the first refusal (one 20-item call less each time);
- the task it stands alone on is remembered in `refused.json` beside the spool (task and post, the newest 5,000), and
  its later leases ask it alone: 1 call, never a batch of 20 again;
- the `refused` log line says the kind, the post, the input's length and platform, and whether it was refused before.

Per offending task: about 33 calls before (three leases of ~11), about 12 now (~10, then 1 and 1).
What triggers it: the logs keep no input, and no local copy holds those tasks (the 11-05 copies predate them; the
copy of 13 Nov is a scratch build without them), so which posts trip it is unknown beyond the classifier's category.
None of the lab's 6,701 items was refused. The new log line names the platform and length of each; a count by
platform after the next run says more.

## 4. What the server refuses, checked by the worker

The week's server-invalid answers (`server-invalid` log lines):

| | to 10 Nov noon | since |
|---|---|---|
| entity span not in the post | 1,730 | 1,635 |
| entity version not in the post | 425 | 129 |
| relation value outside the allowed set (`published`) | 1,536 | 4 |
| read: main and events disagree | 200 | 75 |
| other | 108 | 142 |

The relation values stopped on 10 Nov when v10.10.1 added `published` to the schema; the allowed values are in the
system prompt already (`system_for` appends the guide's JSON schema with every enum). The spans and versions are
checks only the server ran, so each such answer was posted, refused, re-queued as a failed try and asked in a later
cycle (three and the task fails).

The worker now runs the **server's own** `validate.CHECKS[kind]` on every answer the schema passes (`rule_error`):
it imports `backend/insight_core/markx/validate.py` from its checkout (one source of truth; nothing vendored or
forked) and asks a refused answer again **in the same cycle**, with the other invalid ones. It never drops an answer:
after the retry everything is posted, as before. A check that cannot read an answer, or needs more than the standard
library, is no opinion (the server still checks). `--no-server-rules` turns it off; a worker run outside the checkout
checks the schema alone. `validate.back_numbered` moved from `back.py` so the back check is standard library too;
a test keeps validate.py importable without psycopg.

On every lab answer the A/B produced (6,675 schema-valid answers, eight kinds), the worker's verdict and
`validate.check`'s are the same on every one.

Cost: neutral per answer (the retry is the same item asked once more, now in the same cycle instead of the next);
what it saves is the failed tries (a task invalid three times fails) and the round trip.

## 5. The majority of three

relate, back and collide asked every question three times (collide: the third only when the first two disagree).
Now the second and third are asked only when the **first answer is positive or unsure**; a first answer that settles
it is the verdict (with one run; three runs already asked keep their majority, so no stored verdict changes).
Measured on the lab's stored three-run answers, each run in turn taken as the first, with the server's own verdict
code (`graph.verdict`, `back.verdict`/`relation`, `identity.split_of`/`pairrel`):

| kind | settles alone | calls saved | decisions changed | precision before -> after |
|---|---|---|---|---|
| relate (320 labelled pairs x 3 orders) | `unrelated` | 9% | **0 of 960** | 279/294 -> 279/294 |
| | (not chosen) any non-meaningful | 45% | 23 of 960 (20 right edges lost) | 279/294 -> 259/271 |
| | (not chosen) unrelated, or background at confidence >= 80 | 13% | 1 of 960 | 279/294 -> 278/293 |
| back (test 98 x 3) | `unrelated`, `related` | 37% | **0 of 294** (dev sets: 2 of 198) | 60/69 -> 60/69 |
| | (not chosen) anything but development | 51% | 1 of 294 | 60/69 -> 59/68 |
| collide (364 keys of 4 sets x 3) | every mention pair the same (no split, part or unclear) | 43% | 5 of 1,092, all toward no split | 21/33 = 64% -> 20/28 = 71% (recall 21 -> 20 of 36) |

Code: `graph.RELATE_SETTLES`/`settles`, `back.SETTLES`/`settles`, `identity.one_thing`; each kind's `after_answer`
(or the collision stage) stops reopening a task whose first answer settles it, and `verdict` reads one settling run.

## 6. Small ones

- **merge four a call (measured, not changed).** 64 server merge questions: four a call answered all 64 (valid 100%)
  and cost 18% less per item (0.352 vs 0.400-0.456 $/1k), calls / 4. But its agreement with a one-a-call run is
  89.8% [83.4-94.0] against 93.8% between two one-a-call runs, and the prototype measured merge precision 59% asked
  in batches against 89% alone (0112). Without a labelled merge set this does not ship; merge stays one a call.
- **perspective (not changed).** No perspective question is in a local copy (the kind came after 11-05); unmeasured.
- **A track's history pass on a minor edit.** A description or excludes edit that changes no word (case,
  punctuation, spacing: `tracks.material`) keeps the version, so the history pass over every older post is not
  started again and no post is judged again; any changed word is a new version as before. The logs keep no record of
  edits, so the saving is not measured; it is at most one history pass per such edit.

## The week again, after (the logs' volumes)

| kind | week $ before | after | effort | cache | majority | answers / new post | $ / 1,000 new posts before | after |
|---|---|---|---|---|---|---|---|---|
| entities | 178.43 | 123.26 | 37.90 | 17.27 | 0.00 | 1.42 | 1.248 | 0.862 |
| alias | 55.54 | 34.95 | 3.06 | 17.53 | 0.00 | 2.01 | 0.388 | 0.244 |
| read | 50.37 | 41.88 | 0.00 | 8.50 | 0.00 | 1.00 | 0.352 | 0.293 |
| cite | 49.55 | 33.07 | 9.19 | 7.29 | 0.00 | 0.29 | 0.347 | 0.231 |
| relate | 18.27 | 16.62 | 0.00 | 0.00 | 1.64 | 0.77 | 0.128 | 0.116 |
| track | 15.36 | 10.05 | 0.00 | 5.31 | 0.00 | 0.49 | 0.107 | 0.070 |
| back | 9.01 | 5.68 | 0.00 | 0.00 | 3.34 | 0.21 | 0.063 | 0.040 |
| collide | 8.54 | 4.08 | 0.00 | 1.37 | 3.08 | 0.18 | 0.060 | 0.029 |
| pair | 8.00 | 5.10 | 0.00 | 2.89 | 0.00 | 0.24 | 0.056 | 0.036 |
| read3 | 6.90 | 6.90 | 0.00 | 0.00 | 0.00 | 0.07 | 0.048 | 0.048 |
| perspective | 5.41 | 4.66 | 0.00 | 0.75 | 0.00 | 0.01 | 0.038 | 0.033 |
| connect | 5.37 | 3.27 | 0.00 | 2.10 | 0.00 | 0.12 | 0.038 | 0.023 |
| join | 4.00 | 2.50 | 0.00 | 1.50 | 0.00 | 0.10 | 0.028 | 0.017 |
| merge | 3.91 | 2.56 | 0.00 | 1.35 | 0.00 | 0.06 | 0.027 | 0.018 |
| alias2 | 1.22 | 0.77 | 0.07 | 0.38 | 0.00 | 0.04 | 0.008 | 0.005 |
| card | 0.99 | 0.84 | 0.00 | 0.16 | 0.00 | 0.01 | 0.007 | 0.006 |
| rename | 0.96 | 0.71 | 0.00 | 0.25 | 0.00 | 0.02 | 0.007 | 0.005 |
| headline | 0.88 | 0.58 | 0.00 | 0.30 | 0.00 | 0.03 | 0.006 | 0.004 |
| check | 0.50 | 0.32 | 0.00 | 0.18 | 0.00 | 0.01 | 0.004 | 0.002 |
| sheet | 0.46 | 0.35 | 0.00 | 0.11 | 0.00 | 0.00 | 0.003 | 0.002 |
| stance | 0.37 | 0.27 | 0.00 | 0.10 | 0.00 | 0.00 | 0.003 | 0.002 |
| the rest | 0.13 | 0.11 | | | | | 0.001 | 0.001 |
| **total** | **424.14** | **298.52** | 50.22 | 67.35 | 8.06 | | **2.97** | **2.09** |

How it is computed (`final.py`, from the logs' per-kind totals): a kind's output dollars times
(1 - its measured cut in output tokens an item: entities 29%, cite 35%, alias and alias2 17%), plus cite's 4.4% asked
again; its input at 1x list where the cache is off (0.75x for the 5-minute kinds, unchanged where Claude Code's
default stays); relate, back and collide times (1 - the share of calls the lab measured as saved). "Answers per new
post" is each kind's valid answers over read's (one a post) in the week. **$424 -> $299 a week (-30%); $2.97 -> $2.09
per 1,000 new posts.** The verdict checks in the worker (part 4) and the track rule (part 6) are not counted.

On a subscription the tokens count, not the price:
- **output tokens** a week: about 104 M fewer of 498 M (entities 75 M, cite 23 M, alias 6 M), the thinking cut;
- **calls** a week (of 84,820): about 4,200 fewer by the majority rule (relate 525, back 1,561, collide 2,113); a
  refused task about 21 fewer each (before the halving, 3,435 refused calls in two days);
- **input tokens** are the same count (the cache changes their price, not their number), less the majority's calls.

## Tests (only those touched)

- `scripts/tests/test_markx_worker.py` and `test_markx_worker_embed.py` (local, no database): 93 tests, OK; new class
  `TestCost0191` (effort by kind and its override, the cache by kind and its environment, the 5-minute cache's first
  call alone, cache and thinking tokens logged, the first refusal halved at once and the refused task asked alone
  next cycle, an answer the server's checks refuse asked again in the same cycle, `rule_error`, validate.py
  importable with the standard library only).
- `scripts/test-backend.sh insight_core.tests.test_markx_graph insight_core.tests.test_markx_back
  insight_core.tests.test_markx_entities.CollisionsAgree`: 49 tests, one failure that predates this branch
  (`TheBeforeList.test_oldest_first_capped_at_ten_with_the_rest_counted` expects no `byline` field; 0185's commit
  27d7ac3 added it to the before list). `test_markx_tracks test_markx_back test_markx_validate`: 86 tests, OK.

## Deploying

Pull the same commit on the device (or copy `scripts/markx-worker`) and keep it **inside the checkout**: the server
checks come from `backend/insight_core/markx/validate.py` next to it. Nothing to set; the server part needs no
migration. A worker's `start` line now says `prompt_cache` and `server_rules`, and each `call` line `effort`,
`cache_read`, `cache_write` and `thinking`.
