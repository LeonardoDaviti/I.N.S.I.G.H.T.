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
