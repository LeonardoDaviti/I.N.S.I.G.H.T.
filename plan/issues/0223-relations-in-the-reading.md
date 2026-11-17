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

## 0224 — relations from ent-v5's own fields (Stealth v10.24, slice "links from the reading's fields")

Status: **built; `released` ON, `based_on` off.** No new Haiku output, the guide unchanged (ent-v5.md hashed equal to
0223's: 924b2c83…). No migration. Module tests only. Private notes, both frozen sets, runs, labels and scripts:
`plan/research/0224-derived/` (gitignored).

### Built (graph.py section 4, the one path)

- `graph.derived(mentions, on)` (pure): one post's ent-v5 mentions (every window) -> `[(a, relation, b)]`:
  - **released**: the reading's **subject** (a model, product or software) whose own `maker` is the name or span of an
    org or person the same reading lists as **subject or actor** -> that maker `released` it.
  - **based_on**: the subject (model, product, software) `based_on` each `predecessor` of those types.
- `stated()` (what `sync_relations` writes) now returns the answers' own `relations` (ent-v3 / ent-v4.2, as before)
  plus `derived` over the posts' current ent-v5 mentions (pins read, roots through redirects): the same edges (rule
  `stated`), the same evidence, closing and backfill; an edge an old answer and a new reading both say has both posts.
- Scope: `_relation_scope` adds the ent-v5 posts whose call is new since the last run and has a candidate mention
  (`_derived_sql`: a subject with a maker / a predecessor, only for the derived relations on); the backfill reads them
  once when a derived relation is switched on (its state's `on` carries `derived:<rel>`; off -> nothing re-read).
- Switch: `entity_bands.json relations.derived` {released: true, based_on: false} (each also needs `relations.on`).
- Tests (`test_markx_timeline`): `DerivedRelations` (2, pure: the roles, types, makers by span, the thing itself, a
  maker in passing), `DerivedLinks` (2, DB: off writes nothing; on, the backfill writes released then based_on with
  their posts; a new answer read by the next run). `test_markx_timeline`, `_graph`, `_reading5`: 70 OK.

### Measured (Haiku ent-v5 as the worker asks it, 0223's `run.py`; 0220's label guide verbatim; two blind labellers
### as subagents, decoys mixed in, a referee on splits; bar: point >= 97%, Wilson lower >= 90%)

**Sets.** Not 0223's R/E: those posts had ent-v5 answers only on R (dev here: the rule was designed on them) and
had been read for relations already. New sets from the 11-05 server copy (prep_mxreal clone migrated to 0156), every
UUID of 0212's, 0220's, 0223's (and, for set 2, set 1's) files excluded; the set, its picker, the item script, the
label guide and graph.py hashed before the first call (`frozen.sha`, `frozen2.sha`).
- **Held out 1** (`frozen.sha` 13:09): H = 400 random posts, B = 800 posts with base/derivative cue words (fine-tune,
  quantised, based on, fork, distilled, LoRA, successor, replaces, на базе ...). 2,655 windows, 2,588 valid; $2.11.
- **Held out 2** (`frozen2.sha` 13:43, after set 1 had narrowed the rule): H2 = 300 random posts, C = 700 posts with
  release cue words. 1,945 windows, 1,881 valid; $1.50.

| rule | set | right | Wilson 95% | bar | |
|---|---|---|---|---|---|
| released, first form: any model/product/software with its maker anywhere in the reading (org/person) | held out 1 (all H + B to 200) | 138/200 = 69.0% (H 75/110, B 63/90) | 62.3-75.0 | 97 / 90 | fails |
| released, as built: the subject's maker, listed as subject or actor | held out 1, in sample (the slice the narrowing came from) | 40/41 = 97.6% | | | dev |
| **released, as built** | **held out 2 (every item)** | **175/180 = 97.2%** (random H2 36/36; C 139/144) | **93.7-98.8** | 97 / 90 | **passes: ON** |
| based_on: the subject based on each predecessor | held out 1 (every item) | **20/33 = 60.6%** (H 1/2, B 19/31) | 43.7-75.3 | 97 / 90 | **fails: off** |

Decoys: held out 1 43/46 seen as no relation by both, held out 2 32/36 (the labellers were not just agreeing).
Referee: 7 splits on set 1 (all released), 2 on set 2 (1 right, 1 wrong).

**What failed** (the labellers' guide counts a relation only when the post states it or clearly reports it as fact):
- released, first form (62 wrong): a thing merely named or used (a lab's coding agent used by the author, an old OS
  version in passing, a compared model) whose maker the post never ties to it, though the maker is named elsewhere
  in the post; the maker named in another window than the thing; a retailer as a tea's maker; an owner as a site's
  maker. Nearly all are true in the world, not stated in the post: the bar is the post's word, as 0220's.
- released, as built (5 wrong of 180): the same class, rarer (a lab's model named the subject with the lab the actor
  but never said to make it; a phone maker and its phone; a model fine-tuned by its own maker's researchers; a pilot
  of a lab's assistant built by its customer; a video tool's maker not named in the window shown).
- based_on (13 wrong of 33): a predecessor is mostly what the subject replaces, migrates from or is compared with
  (one recommender model and its earlier one; a realtime voice model and its previous version; a database migration;
  an embedding model and an older one); about half pair the subject of one item of a long post or digest with the
  predecessor of another (the subject in window 1, the predecessor in window 3).

**How often** (valid posts): a `predecessor` (any type) in **0.5-0.7% of random posts** (H 2/387, H2 2/285; 0223's R
runs 1-5 of ~480), 3.1% of base-cue posts (24/773), 1.6% of release-cue posts (11/671). Released as built: 36 edges'
worth of items in 285 random posts (12.6 a hundred); the first form gave 110 in 387 (28 a hundred): the narrowing
keeps about 45% of the pairs, the main event's.

### based_on: a small Haiku check (proposed, not built)

ent-v5's `predecessor` is a candidate, not a relation. A question of its own on each (subject, predecessor) pair of
one post, both named in the same window: the window's text, A and B, "is A made from B (fine-tune, quantisation,
distillation, fork, derivative, a version built from it), or does A only replace / follow / compare with B?",
answers {derived, replaces, compared, other}; `based_on` only on `derived`. Volume at the server's ~1,000 new posts a
day: ~0.6% have a predecessor (~6 posts, ~8 pairs a day at set 1's 1.4 pairs a post; fewer once a pair must share a
window): **one call a day** at 20 pairs a call (three for a majority), ~2k input tokens a pair: **< $0.01 a day**.
Measuring it needs ~40+ pairs: a base-cue set of ~1,500 posts read by ent-v5 (~$2.5) plus the check, the same bar.

### Resources (the 11-05 copy, migrated, one full decision run first; then held out 1's 2,588 ent-v5 answers written
### as the worker's are, `reading_guide` on: 1,074 posts' sets current; checks/resources.py, each run its own process)

| decision run (incremental) | derived off | released on |
|---|---|---|
| 1 (answers new; the entities stage links them after graph) | 115.2 MB, 28.3 s, graph 12.0 s | 114.0 MB, 28.1 s, graph 12.0 s (the switch's backfill: 1,171 posts read, nothing linked yet) |
| 2 | 142.3 MB, 36.2 s, graph 12.7 s | 145.1 MB, 37.1 s, graph 13.2 s (42 edges opened) |
| 3 | | 110.5 MB, 21.5 s, graph 14.0 s (97 more opened as linking and merges settle) |

The rule alone on every candidate post of the copy (311 posts, 137 edges): **0.077 s, peak +0.4 MB** (55.3 -> 55.7);
the answers' own relations on the same posts 0.013 s. Run-to-run noise (±8 s, ±30 MB) is larger than the rule. No
table is read whole into Python: the scope is the calls new since the last run, the backfill 500 posts a chunk under
the stage's deadline.

### For the owner

- **released from new posts is on**: the subject's maker, named as the subject or actor of the same reading (97.2% on
  held out 2, all 36 random-post items right). It asks nothing of Haiku. Edges on the copy with held out 1's 1,074 posts read: 432 released after three
  runs on, 303 with it off (0220's, from ent-v3 answers).
- **based_on from new posts stays off** (60.6%); the Haiku check above is the way, measured on its own set first.
- **A gap this shares with 0220's path (not changed here):** the decision run's graph stage runs before the entities
  stage, so a new answer's mentions are linked in the run after graph; graph reads them in the next run only because
  its scope looks back one hour (`MARGIN`) before the last run. A backlog over the linking cap (6,000 mentions a run)
  or runs more than an hour apart would leave such a post's edges until a backfill. Scoping on a set's linking time
  would close it (no such column today).
- Seen while measuring (0220's code): `_relation_scope` re-reads the evidence posts of every edge whose side was ever
  merged (860 posts each incremental run on the copy, `r.at` not bounded by `since`); cheap here (graph 12 s in all),
  unmeasured at the server's size.
