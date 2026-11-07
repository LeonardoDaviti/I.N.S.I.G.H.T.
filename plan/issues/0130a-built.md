# 0130 A — Built (v10.5: the entity queue, measured)

Slice A of `0130-v10.5-stealth.md`. Branch `worktree-agent-a3967d4bd7bf763f9` (off main `df54d6f`). Not pushed, not
merged. Real names, the exact rows and the measuring scripts are in the private `plan/research/0130a-build/`
(`NOTES.md`, `rows.md`). No migration (the second opinion is a task kind; `mx_tasks.kind` is not checked, and the
marks live in the queue item's evidence).

## What was built
- **A1, the bands as config:** `markx/entity_bands.json` holds the measured table (opinion × guard × band, right/n, on
  or off) and the bar (point ≥ 0.97, Wilson ≥ 0.90; automatic merges ≥ 97%). `identity.py` reads it (`bands`,
  `band_of`, `first_auto`, `second_asked`); changing a row changes what merges, no code. The queue's items carry their
  band; the Entities tab shows it on each item and filters the queue by band, so the owner can label every band.
- **A2, the second opinion:** new task kind `alias2` (guide alias-v1, the same schema): a held-back Haiku `same` at
  ≥ 0.85 whose every reason has its second row on is asked again with two other example posts per name
  (`examples(other=True)`). Two `same` ≥ 0.85: an automatic merge `by = 'second'` (a redirect like any other, undoable
  from the history; an undo is never merged again), and the pair's open queue item is closed with why (kept, never
  deleted). A disagreement stays queued, its evidence marked (`second`, `disagree`), shown as "second opinion
  disagrees". Collisions keep their rule. Cap: 2,000 new second questions a run. Stage counts: `entities.second`
  {asked, cleared, marked}.
- **A3, the version guard narrowed** (`soft_reason`): a one-sided version, variant, size or build is held (`version`)
  only when the family (either side's family field, or the bare name itself) has several of it among the entities;
  an edition year on one side only (`version_year`) or a field the family has one of (`version_one_side`) goes to the
  second opinion. Both sides stating different versions stays apart, never asked (unchanged).
- Every reason a `same` is held for is kept (`reasons`); the first is the one shown.

## Measured (A4)
On 277 labelled pairs Haiku called the same: the lab's experiment 2 (dev 70, test 92, test2 65; two blind labellers and
a referee) and the owner's queue answers (50). Real Haiku through `scripts/markx-worker` against my own API on a scratch
copy: **$0.35** (734 second asks with alias-v1, 734 with a candidate alias-v2).

**The first opinion alone, right/n** (nothing new passes the bar, so nothing new is automatic on one opinion):

| guard | ≥ 0.90 | 0.85–0.90 | 0.80–0.85 | < 0.80 |
|---|---|---|---|---|
| none (automatic since 0119) | 86/87 | 46/49 | 24/25 | 25/31 |
| maker only guessed | 18/18 | – | – | – |
| fields without the parser | 7/7 | – | – | – |
| handle with an extra word | 4/4 | – | – | – |
| chain | 7/7 | 4/4 | – | – |
| type | 4/6 | – | – | – |
| version, held (family has several) | 7/9 | – | 4/5 | 5/9 |
| edition year on one side | 4/4 | 1/1 | 2/3 | 2/2 |
| a version the family has one of | 3/3 | 0/2 | 0/1 | – |

**Two opinions, both `same` ≥ 0.85, right/n:**

| guard | alias-v1 + two other posts (adopted) | alias-v2 (not adopted) | on |
|---|---|---|---|
| below the bar | 35/35 | 42/43 | yes |
| maker only guessed | 18/18 | 18/18 | yes |
| fields without the parser | 7/7 | 7/7 | yes |
| handle with an extra word | 4/4 | 4/4 | yes |
| edition year on one side | 4/4 | 4/4 | yes |
| a version the family has one of | 3/3 | 3/3 | yes |
| **adopted guards together** | **71/71 (Wilson 0.95)**; held out of alias-v2's writing 64/64 | 78/79 | |
| type | 2/2 | 2/2 | no (too few; one opinion is 4/6) |
| version, held | 5/5 | 6/6 | no (held by A3) |
| "X (Y)" | 0/0 | 0/0 | no (not measured) |
| chain | 11/11 | 11/11 | no (the chain guard runs after) |

- **Automatic merges after the change, on the labels: 157/158 = 99.4%** (held out: 119/119); bar ≥ 97%: met. The one
  wrong is the existing ≥ 0.90 first-opinion merge; the second opinion says `different` on it.
- The second opinion caught 5 labelled pairs the first called the same at ≥ 0.85 that are not (a model and its paper,
  a book and a dated edition, a brand and its site, a model and its app, a plugin and its org).
- Missed: 65 labelled `same` stay queued (most below 0.85 on the first answer).
- alias-v2 clears more (136 against 115 of the open queue) but made one wrong merge; alias-v1 with other posts is
  adopted. alias-v2 stays private, measured.
- At a 0.80 bar alias-v1 is 96/98 (held out 78/80 = 97.5%): not adopted, the spec's 0.85 kept.

**The owner's open queue** (504 at the read-only GET: 457 pairs, 47 collisions):
- the narrowed guard sends 48 of the 124 version items to the second opinion (21 year, 27 one-side), 76 stay held;
- the second opinion would clear **115** automatically and mark 48 as disagreeing; 294 pairs and the 47 collisions stay;
- a hand read of the 115 (one reader, not blind) finds about 4 doubtful, so expect about 96–97% there, not 100%.

These are estimated on the 11-05 export with the second question asked on the queue's shown posts. The live figure
comes from the next worker run.

**Speed:** the full pass on the 120-day copy is 27.8 s (the stage's own budget, 0128), its check `same`.

## Tests
- `test_markx_entities`:
  - the narrowed guard (year, one-sided, a family with several versions held);
  - the bands read from config, a band turned on in config merging;
  - `decide_pair`'s second opinion (asked, agreeing, disagreeing, below its bar, off for "X (Y)" and type);
  - two DB flows: agree → a 'second' redirect, the queue item closed, undo never merged again; disagree → queued and
    marked.
- `test_markx_validate`: the kinds include `alias2`.
- All 13 Mark X backend modules: 322 tests OK.
- Frontend: Mark X tests (29) and `npm run build` pass. A new test covers the band chips, the band filter and the
  "second opinion disagrees" mark.

## For the owner
- **The worker:** `alias2` must be in the worker's kinds. Either pass `--kinds …,alias,alias2,collide,…`, or change
  `DEFAULT_KINDS` in `scripts/markx-worker` to add `alias2` after `alias` (not changed here: the live worker runs from
  the main checkout).
- **Answer by band:** none of your 56 answers is below 0.90; the queue's band filter lets you label each band. The
  one-opinion rows turn on in `entity_bands.json` once a band meets the bar.
- **Open decision 1:** two example posts per name was the default and is what was measured.
- **An option:** ask the second opinion of the ≥ 0.90 band too, before its automatic merge. On the labels it would have
  stopped the one wrong merge there. Not built: it changes merges that already meet the bar.
