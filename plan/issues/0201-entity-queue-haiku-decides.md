# 0201 — The entity review queue: Haiku decides, the backlog is decided again (Stealth v10.18, part A)

Real rows are in the private notes (`plan/research/identity-1018/`); no name from them is written here.

## The problem

Production showed "To review: 14,297". The owner read 20 items from the top of the queue: the queue's top was a name
rule's proposal (two names equal once squashed, or one is the other with its maker in front) whose two entities had
different types. `identity._decide_pair` queued such a pair as `type` with the rule's constant 0.97 **without asking
Haiku, or without using Haiku's answer when it had one**, and the page showed that constant as "Haiku's confidence".
The owner's reading: the rule was right about 30% of the time (6 same, 12 different, 2 unclear).

The owner's decisions (2026-11-14): Haiku decides; automatic above a measured bar (identity's bands: point >= 97%,
Wilson lower bound >= 90%); only unsure or disagreeing pairs stay queued; the owner must not review thousands.

## The open queue, read (2026-11-14, light GETs)

13,368 distinct open items (pages shifted while read): alias 11,413, collision 1,887 (0184's, part B), rename 69.
The alias items by why they wait:

| | items |
|---|---|
| Haiku `same` below its bar (`below_bar`), no second opinion | 5,277 (first answer < 0.85) |
| `below_bar` and others with two agreeing opinions >= 0.85, held by the chain guard | 544 |
| the version guards (`version`, `version_year`, `version_one_side`) | ~2,170 |
| `chain` | 805 |
| a name rule's pair of two types, Haiku never asked (the owner's case) | 281 (+23 with an answer) |
| the two ends already one cluster (merged since), still open | 1,253 |

## What changed

- **A rule's pair of two types is Haiku's** (`_decide_pair`): asked when unasked (`alias-v1`, the existing question);
  `different` >= 0.8 keeps it apart by itself (`rule_apart`, config `rule_type`); `same` is held for its types as any
  `same` is, so the second opinion (`alias2`) is asked; `part`, `other_version`, `cant_tell` or a lower confidence
  stays queued (`haiku_unsure`). A queued item's confidence is Haiku's, never the rule's constant.
- **The second opinion for a type mismatch is on** (`entity_bands.json`, measured below).
- **The backlog is decided again** (`identity.backlog`): each run takes up to 2,000 open alias items not decided by
  this rule set (`evidence.redecided`), pools them with the run's first chunk and decides them as any pair: merged,
  kept apart or already one cluster closes the item (kept, `closed_by` says why); still queued, the item says what
  was decided now (`refresh_queued`; the earlier reason and confidence kept in `evidence.before`). Every 15-minute run
  takes the next 2,000: about 7 runs for the whole backlog. New questions: ~280 `alias` and ~100 `alias2` (about
  0.07 $ at the measured 0.19 $ a 1,000 answers).
- **The page says who proposes** (`opinion` in the API's queue item; `MarkXEntities`): "Haiku says different, 93%" or
  "a name rule suggests same (…) · Haiku not asked yet"; the band filter counts only Haiku's `same`.

## Measured (blind)

Frozen sets from the server's open queue (seed 1018): every rule-proposed type item (304); 80 of the 544 agreeing
pairs; 100 + 150 weak first answers; 60 version-held; 60 type-held Haiku pairs. Haiku asked through the worker's own
`claude -p` call (alias-v1): first opinions on the 281 never asked, second opinions (two other posts a side) and a
"rich" ask (four posts a side, wider windows) where noted. Labels: one blind labeller on all 604 items (no answer, no
rule, no reason shown), an independent second labeller on every item where the label and the class's decision
disagree plus 45 random agreed ones (agreement 43/45 on the random ones, 67/75 on the disputed), the 10 where the two
disagreed adjudicated.

| Decision class | n | right | precision | Wilson 95% | automatic? |
|---|---|---|---|---|---|
| a rule's pair, Haiku `different` >= 0.8: apart | 160 | 160 | 100% | 97.7-100% | **yes** (`rule_type`) |
| a rule's pair, Haiku `part` >= 0.8: apart | 16 | 10 | 62.5% | 38.6-81.5% | no: queued (a company and its same-name product) |
| a rule's pair, two `same` >= 0.85 | 48 | 47 | 97.9% | 89.1-99.6% | pooled below |
| a Haiku pair held for type, two `same` >= 0.85 | 39 | 39 | 100% | 91.0-100% | pooled below |
| **held for type, two `same` >= 0.85 (both, + 2/2 before)** | 89 | 88 | 98.9% | 93.9-99.8% | **yes** (second row `type`) |
| a rule's pair, two `same`, one < 0.85 | 31 | 26 | 83.9% | 67.4-92.9% | no |
| chain-held, two agreeing `same` >= 0.85 | 79 | 74 | 93.7% | 86.0-97.3% | no: the chain guard holds (unchanged) |
| weak first (< 0.85), second `same` >= 0.85 | 26 | 22 | 84.6% | 66.5-93.9% | no |
| weak first, second `same` < 0.85 | 43 | 33 | 76.7% | 62.3-86.8% | no |
| version-held, second `same` | 39 | 37 | 94.9% | 83.1-98.6% | no |

So of the backlog, the run closes the 1,253 already-one items, keeps apart about 57% of the rule items once asked,
and merges the type-held pairs two opinions agree on; the rest stays queued because Haiku is unsure (a weak first
`same`: 77-85% right even with a second opinion) or a guard holds (chain, versions: 94-95% with two opinions). Those
need a better question, not a lower bar. A three-opinion class (a weak first `same`, then the second opinion and a
four-post ask both `same` >= 0.85) was 18/18 on the first 100 and 26/27 on a held-out 150 (the one a disclosure
post and a later technical report): 44/45, 97.8%, Wilson 88.4-99.6%, just under the bound; it fires on ~18% of the
weak items. Not switched on; ~15 more labelled rows decide it.

Haiku cost of the whole measurement (both parts): 0.37 $ (the worker's own `claude -p` call).

Not measured: the rule items' share that merge (their `same` answers wait for the second opinion), and the run's time
on the server's book (2,000 pairs pooled with the first chunk; a run's 15-minute budget).

## Round 2 (2026-11-14): a better question for the unsure queue

**The question: `alias3`, guide `alias-v2`.** For each side it shows the known identity facts (0184: what it is, its
kind and maker, when there are any), the accounts whose posts name it (their handles), and four example posts with
wider windows (300/500 characters around the name). Haiku first says what each side is, then compares the two things
rather than the two strings. It is asked only for a Haiku `same` still queued after both opinions and the chain guard,
for a reason listed in the config (`entity_bands.json` `third`); `identity.third` decides on its answer.

**Measured, blind, held out.** None of these items was used before. The labels are a blind labeller's, who saw the
same four posts a side as Haiku.

| Set | Class | n | right | precision | Wilson 95% | automatic? |
|---|---|---|---|---|---|---|
| chain-held `same` (40 + 48) | alias-v2 `same` >= 0.8: merge | 77 | 76 | 98.7% | 93.0-99.8% | **yes** (decides 77 of 88) |
| chain-held | alias-v2 `same` >= 0.9 | 61 | 61 | 100% | 94.1-100% | (contained above) |
| weak first `same` (40) | alias-v2 `same` >= 0.85 | 15 | 12 | 80% | 54.8-93.0% | no |
| weak first | alias-v2 `same` >= 0.9 | 6 | 5 | 83% | | no |
| either | alias-v2 apart | 1 | 1 | | | not measurable (said once in 168) |

The richer question does not settle the weak `same` pairs. The blind labels call 27 of 40 of them the same thing,
but Haiku stays below 0.85 on most of them even with four posts a side: it is under-confident there, not wrong. So
below_bar is not listed in `third`. Settling them needs another judge (a stronger model) measured the same way.

**The three-opinion class** (a weak first `same`, then the second opinion and a four-post ask both `same` >= 0.85),
with about 15 more items labelled: 13 more fired in 100 held-out items, 11 of them right (the other two: two
different online talks; one edition of a conference series). In total 55/58, 94.8%, Wilson low 85.9%: **fails**.
It stays off.

**Effect on the backlog.** Of about 1,350 chain-held items, about 87% merge once asked (one `alias3` call each). With
the round-1 closures, about 2,700 of the ~11,400 open alias items close. What remains is the ~7,500 weak `same` (Haiku
unsure), the ~1,900 version-held items and the chain items alias-v2 is unsure on.

**Cost.** alias-v2 measured at 0.023-0.027 $ for 40-48 items, i.e. about 0.55 $ per 1,000 items: about 0.75 $ for the
chain backlog. Every Haiku call in rounds 1 and 2 together: 0.49 $.

A merge by `third` passes the chain guard's two-groups rule but never the six-names-a-cluster cap. The labels judged
the two names, not every name in the two groups being joined.

## Round 3 (2026-11-14): a stronger judge for the weak `same`; what version-held items are

**Sonnet on the weak class.** The same alias-v2 question is now asked as its own kind, `alias4`, through the worker's
usual path. The model is a per-kind setting: `entity_bands.json` `models` gives `{"alias4": "sonnet"}`, the server
names it on each leased task, and the worker asks with it instead of its `--model` (`identity.model_for`; no fork).
`third.kinds` sends `below_bar` items to `alias4`. Only a weak first `same` with no second opinion qualifies: a
`same` still waiting for its second opinion, or one whose second opinion disagrees, stays the owner's.

Measured blind on 120 held-out weak items (two fresh sets of 60, labelled with the same four posts a side):

| Class | n | right | precision | Wilson 95% | automatic? |
|---|---|---|---|---|---|
| Sonnet `same` >= 0.8: merge (both sets) | 68 | 67 | 98.5% | 92.1-99.7% | **yes** (fires on 68 of 120) |
| the second set alone | 34 | 34 | 100% | 89.8-100% | |
| Sonnet `same` >= 0.9 | 38 | 38 | 100% | 90.8-100% | |
| Sonnet not-`same` (any confidence): apart | 32 | 31 | 96.9% | 84.3-99.4% | no |
| Sonnet not-`same` >= 0.8: apart | 13 | 13 | 100% | 77.2-100% | no |

The one wrong merge: Sonnet `same` at 0.88 on a pair the label calls another version. The one wrong apart: Sonnet
`other_version` at 0.65 on a pair the label calls the same.

**Effect and cost.** About 57% of the ~7,500 weak items merge: about 4,250. Sonnet cost 0.54 $ per 60 items, so
about 9 $ per 1,000 and **about 67 $ to ask the whole weak backlog once**. Haiku costs about 0.55 $ per 1,000 on the
same question, but scores 12/15. The 43% Sonnet doesn't settle stay queued (its apart is off): about 3,200 items.

**Version-held (~1,900 items), 40-row sample, blind:**

| What they are | Rows |
|---|---|
| the same thing, the version written two ways ("P40 24GB" / "P40", "2nd generation" / "second generation", "TPU v7x" / "Ironwood", "macOS 15" / "Sequoia", "Mac OS X Tiger" / "10.4") | 19 |
| the same thing, one name leaves out a version the posts show is the same (a year on an election, "Ironwood" / "TPU v7 Ironwood") | 11 |
| a family against one of its versions ("Nemotron 3.5" / "Nemotron 3.5 Bolt", "Transformers.js" / "v4", a survey / its 2026 edition) | 5 |
| really another version | 2 |
| part (a model card, a system around a product) | 2 |
| different | 1 |

30 of 40 are the same thing. But the "written two ways" rows are mostly the same thing under another name (a code
name against a number, a generation word against a digit, an added size or variant), not a spelling a normaliser can
read. The deterministic sub-classes are too small and mixed to reach the bar:
- the same version on both sides with one side adding only a size or a build: 2 rows;
- an added variant: 3 same against 1 family-vs-version ("Bolt" is its own model);
- a year on one side: 4 same against 3 family-vs-edition.

So **no normaliser was built**. A judge does better: Haiku's alias-v2 on these 40 says `same` >= 0.85 on 25, 24 of
them right (96%, Wilson low 80.5%), close to the bar but short. Sonnet, measured the same way, is the next step.
