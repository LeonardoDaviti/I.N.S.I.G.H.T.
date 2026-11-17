# 0223 — Relations in the one reading (Stealth v10.24, slice "relations in the one reading")

Status: **built, measured, OFF.** ent-v5.1 (ent-v5 + `relations`) is in the code as a guide variant, not asked: new
reading tasks still ask **ent-v5** (`schemas.READING_ASKED`). No migration. Module tests only. Private notes, the frozen
set, every run, label and script: `plan/research/0223-relations/` (gitignored: real posts).

Reads: 0212 (ent-v5, one reading), 0220 (graph section 4: relations as entity edges, `stated`; based_on and released
on, released only when `graph.corroborated`).

## The problem

ent-v5 is the production reading and asks no relations, so no new `based_on` / `released` edge comes from new posts.
The owner wants one reading per post (no separate job), so relations would have to be in ent-v5's answer.

## Built

- **Guide `ent-v5.1`** (`markx/guides/ent-v5.1.md`): ent-v5 word for word, plus a section "4. relations" and
  `"relations": []` in the output's example. Only five lines of ent-v5 change (the title, "three sections" -> four, the
  entities bullet, the window line, the output example; a test holds this). It asks only the relations graph can
  switch on (`entity_bands.json relations`: released, based_on, acquired, part_of, partnered_with;
  `schemas.READING_RELATIONS`, a test holds them equal).
- **Schema** `READING_V51_SCHEMA`: ent-v5's, plus an optional `relations` [{a, rel, b}] (left out = none stated).
  Checked entry by entry (`validate.SALVAGE["reading"]["relations"]`): a bad relation is dropped and kept under
  `dropped`, never sinks the reading.
- **Versions of the reading's guide** (`schemas.READING_GUIDES`, `READING_ASKED`): the asked one is the kind's guide,
  the other a `GUIDE_VARIANTS` entry (its open tasks still answered and checked by its own schema, as track-v1).
  Every guide stores its rows under `ent-v5` (`reading5.GUIDE`): one reading a post, whichever text asked it; the
  call says which. `reading5.TASK_GUIDES` is used where a post's reading task is looked up (`reading5.plan`,
  `old_kinds_sql`, `ent42.plan`'s cite planner and `ent42.after_cite`): a post read under either guide is never
  asked again.
- **graph.py section 4: no new path.** It already reads `c.answer->'relations'` of the call of any guide in
  `schemas.mention_guides()` (ent-v5 included), each side one of that call's own mentions. Test: an ent-v5.1 answer
  recorded through `tasks.record` -> entity stage -> `graph.stage` opens exactly the based_on and the corroborated
  released edge (a switched-off relation, an uncorroborated release, a side not among the entities: none).
- Switching it on later is one line (`READING_ASKED = "ent-v5.1"`) plus the decision run's one full run (the kinds'
  guides are part of its key).

## Measured (Haiku only, as the worker asks it: its system prompt, prompt, `split_calls` 20 a call, effort low, no
## prompt cache, its parser, the server's `validate.check`)

**The set** (`pick_frozen.py`, frozen and hashed before the first call: `frozen.sha`): the 11-05 server copy
(prep_mxreal, migrated), posts in none of 0212's or 0220's samples (every UUID in those files excluded). R = 500
random posts (714 windows, 1.43 a post: the server's mix); E = 900 posts whose text says what a relation would
(released, fine-tune, based on, fork, acquired ...), for enough stated relations. Windows by `reading5.inputs`.

**Runs:** ent-v5 three times on R (r1-r3); ent-v5.1 twice on R (b, c; the same batches as r1-r3) and once on R+E (a).

### Quality 1: precision of the relations, as graph reads them (run a, 1,400 posts)

Items: each (post, a, rel, b) graph would write (relation on, both sides among the answer's own entities, not one
thing, `released` corroborated). Two blind labellers (subagents) with 0220's guide chose the relation themselves for
each pair, mixed with 26 decoy pairs; a referee on the 1 split. Bar: point >= 97%, Wilson lower >= 90%.

| relation | right | bar | |
|---|---|---|---|
| based_on | **25/32 = 78.1% [61.2-89.0]** (E 22/26, R 3/6) | 97 / 90 | **fails** |
| released (corroborated) | 99/100 = 99.0% [94.6-99.8] (R 26/26, E 73/74) | 97 / 90 | passes |

Decoys: both labellers saw a relation in 5 of 26 (the model left those out: recall is not measured).
based_on's 7 misses: a quantiser org as the derived thing ("Unsloth based_on <model>"), a training method typed
`other` based_on its base model (2), a network card based_on its chip, a project by the same author called a fork
(Disque / Redis), a product's variant based_on the product, one library based_on another it only uses. A type rule
(a model/software/product side only) would remove 3 of the 7 and one right item: 24/28 = 85.7%, still under the bar
(and in sample). 0220's ent-v3 based_on was 95/95: asked inside ent-v5's long reading, Haiku states it loosely.

### Quality 2: ent-v5's own fields, with and without the relations part (R, the same batches)

Agreement between runs on the fields the code reads (posts both answers valid; names: Jaccard of the name keys over
all windows; roles: on the names both list). Bar: ent-v5.1 x ent-v5 >= ent-v5's own run-to-run agreement.

| field | ent-v5 x ent-v5 (3 pairs: the bar) | ent-v5.1 x ent-v5 (6 pairs) | ent-v5.1 x ent-v5.1 | difference [95% bootstrap] |
|---|---|---|---|---|
| kind | 86.6% | 84.3% | 86.7% | -2.3 [-4.6, -0.1] |
| events | 91.6% | 90.4% | 91.7% | -1.2 [-3.2, +0.6] |
| event type | 85.1% | 82.3% | 87.2% | -2.8 [-5.3, -0.5] |
| origin | 93.0% | 91.1% | 92.7% | -1.9 [-3.8, -0.2] |
| entity names | 74.7% | **68.9%** | 69.5% | **-5.8 [-8.0, -3.8]** |
| entity roles | 83.3% | 81.6% | 85.3% | -1.7 [-3.6, +0.2] |

(n = 399 posts; 394 for names, 286 for roles.) **Fails**: ent-v5.1 is as consistent with itself as ent-v5, but its
answers differ from ent-v5's more than ent-v5's differ among themselves, on every field, and entities most: it lists
**9% fewer entities a window** (3.09-3.10 against 3.33-3.44) and **thinks 19% less** (523 against 642 tokens a window).
0212 measured the same lever: a wording change that cut Haiku's thinking cut the reading's accuracy (d3b).

### Cost (R, the same 714 windows; Claude Code's own price; Haiku 5.5 $0.10/M in, $0.50/M out)

| guide | in / window | out / window (thinking) | $ / window | $ / day at 1,000 posts (1.43 windows a post) |
|---|---|---|---|---|
| ent-v5 (3 runs) | 1,830 | 932 (642) | 0.000649 | 0.93 |
| ent-v5.1 (2 runs) | 1,853 (+1.3%) | 807 (523) (-13%) | 0.000589 (-9%) | 0.84 |

Relations themselves cost little (0.08 a window on random posts); ent-v5.1 is cheaper only because Haiku thinks less,
which is the regression above. The guide's system prompt is 0.9k characters longer.

**Verdict: OFF** (both bars fail: based_on precision, and the regression on every existing field). The guide stays
ent-v5; ent-v5.1 is built, tested and not asked. Haiku spent: $4.12 (seven runs and the smoke).

## For the owner

- **released does not need the relation.** With 0220's corroboration a `released` edge is written only when the thing's
  own entity names a as its maker, so the reading's `maker` field already carries it; a `released` edge could come
  from ent-v5's answer as it is (the thing's entity with a maker, the post's event about it, e.g. its action
  `released`), with no new output and no change to the reading. That is a rule to measure on its own frozen set.
- **based_on** needs more than one more line in the long reading: 0220's 95/95 came from ent-v3, a guide about
  entities only. Asking it in ent-v5 costs entities recall and the reading's agreement. Options: the `predecessor`
  role ent-v5 already gives (a model "fine-tuned from" its base is a predecessor) read as a based_on candidate and
  checked by a small Haiku question of its own on the few posts that have one; each needs its own frozen set.
- Until then no new based_on or released edge comes from new posts (0220's edges from the old answers stay).
