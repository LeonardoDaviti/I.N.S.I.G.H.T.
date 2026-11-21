# 0159 — Surges against a subject's own past: how surprising today is, not how loud

Status: **closed, not adopted (2026-11-22)**: measured 2026-11-20 on the lab's labelled windows (below): the own-past
rule loses recall and precision against today's 3-voice rule. One variant left untested: today's rule OR a quiet
subject's 2-voice day (about 85% precise by the counts, under the 88% bar).
Roadmap: `plan/INSIGHT_fusion_plan.md`.

Read first: 0090 E, 0119 A2 (`markx/surges.py`: a day of 3 or more voices is a surge; "the 3x baseline waits for a
month of data"); the lab's surge sets (private: `plan/research/lab/markx/proto/out/surges_v2`, `surges_v3`).

## Why
- Today's rule is one bar for every subject: 3 voices in a day. Measured on the lab: **88–91% precise, recall
  46%**.
- One bar is wrong at both ends. A subject that 5 sources mention every day "surges" every day and tells nothing. A
  subject nobody mentioned for a month, named by 2 sources today, is news and is missed.
- The month of data the baseline waited for exists now.

## What it does
### 1. A surge is a day that the subject's own past makes unlikely
- Per subject (an entity at the version level, with today's roll-up and roles unchanged) and day: voices today,
  against its **own rate over the 28 days before** (a floor for subjects with no past, so a new name needs 2
  voices, never 1).
- **Surprise** = how unlikely today's count is at that rate (a Poisson tail; plain arithmetic, no library).
  A surge: surprise past a bar **and** at least 2 voices.
- The bar is chosen on the lab's first labelled window and tested on the second, never on both.
- Stored beside today's rule in `mx_entity_surges` (a `rule` column: `three_voices`, `own_past`), both computed,
  both kept. Shadow until measured; then the owner chooses which the entity list reads.

### 2. Shown with its reason
- "4 sources today; usually 0–1" instead of a bare mark. A subject that is always loud shows no surge and, on its
  page, its usual level.

### 3. The same measure elsewhere (after it passes on entities)
- Tracks (items in per day), events (posts per day after the first three days: "back in the news" has its own
  judge, 0136; this is its cheaper trigger), 0158 B's digest section.

## Measure (no model calls)
- On the lab's two labelled windows: precision and recall of `own_past` against `three_voices`, per window; the
  surges each rule finds that the other does not, 20 of each read by the agent (exact rows, private).

## What the results should be
- Recall up from 46% with precision not below 88%. First step of the measure: read the lab's missed surges and
  count how many were 2-voice days of quiet subjects (the case this rule can recover; not counted yet).
- Fewer daily surges of the always-loud subjects; counted.
- If recall does not rise at that precision, the rule is not adopted and the spec says so.

## Done when
- Tests: the rate over 28 days; the floor; the tail computed exactly on small counts; both rules stored; incremental
  days as today; nothing deleted.
- The measure's table and rows.

## Measured (2026-11-20; private: `plan/research/fusion/measure/x1120/S0159/`)
**Not adopted.** Reproduced today's rule exactly on the lab's two labelled windows (85% / 44% on v2, 91% / 45% on v3). Bar chosen on v2 (0.003, floor 0.02 voices a day), tested on v3: own-past rule 80% precise (69-88), recall 23% (18-29), against 91% / 45%. No setting reaches 46% recall at 88% precision. It silences loud subjects even on real big days (45 -> 1 surges a window), and recovers 27-32 real 2-voice days of quiet subjects. A union (today's rule OR a quiet subject's 2-voice day) is the only variant left; by the counts it would be about 85% precise, still under the bar.
