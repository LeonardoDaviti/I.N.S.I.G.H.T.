# 0158 — What a source adds, and a weekly digest chosen by coverage

Status: **spec, after 0152, 0153 and 0157** (2026-11-10). Part A: code. Part B: its writer after 0161 E6. Fusion
stage 6 (Measures). Realises 0093 (noise per source) and 0096 (weekly what changed). Roadmap:
`plan/INSIGHT_fusion_plan.md`.

Read first: 0093 and 0096 (and their measures), 0132 B (`markx/source_stats.py`: the source analysis page, one card
per signal, **no single score**), 0118 (source track record), the daily briefing (`briefing-v1`).

## Why
- 0093's measure: from story memberships only 17 of 138 sources got a verdict, and the largest source by volume
  could not be decided. Stories are too coarse a unit. Claims are not: every read post has some.
- A source's worth to a reader is what it adds to what the reader's other sources already give — not its volume,
  and not how often it is linked (0132 B's report: a composite ranked one language's sites first because nobody
  links the other's channels).
- A weekly digest written by Haiku from the week's stories was about 93% supported (rough: private
  `plan/research/fusion/out/F5a`). That run was handed the week's biggest stories; what a digest should include was
  not tested. Choosing by size repeats a subject that had several big stories; choosing by coverage is this issue's
  proposal, measured below.

## What it does
### A. What a source adds (cards on the source analysis page; no model)
Per source and per voice, over 30 and 90 days, each with its n and "too few to tell" below a threshold:
- **First:** claims it made before any other origin on the same event, and the median lead (hours).
- **Alone:** claims no other origin made (shown with their status: an official statement alone is not a rumour
  alone).
- **Repeats:** its claims that repeat an earlier one (0157 A), as a share.
- **Adds per post:** new and updating claims per post read.
- **Origin for others:** how often other sources' claims name it as speaker or link it as source.
- Each number opens its cases. No verdict sentence and no composite: the page sorts by any card (decision 5 of
  0132).
- The same cards rank Discover's and the scout's candidates once followed for 30 days (0101, 0148).

### B. The weekly digest, chosen by coverage
- **Choosing (by code):** from the week's events, pick items one at a time; each next item is the one that adds
  the most not yet covered — subjects (entities, tracks) not yet in the digest, weighted by origins (0157 B) and
  by what is new since the reader looked (0154). Stop at the budget (10 lines, a setting). Two events about one
  subject are picked only when the second adds a subject or a number the first lacks.
- **Sections** (0096's): new subjects, surges against their own past (0159), events that moved state, numbers that
  moved (same metric and basis), follow-ups to what you read.
- **Writing:** one `digest` call from the chosen events' claims; each line cites claim ids; numbers, versions and
  dates checked against the claims by code, a failing line dropped (as the briefing is checked).
- Shown on its own page with earlier weeks kept; no email or push in this issue.

## Measure
- A: on the server copy, sources that get each card (against 0093's 17 of 138); the owner's keep / quiet choices on
  30 sources against "adds per post".
- B: the owner's preference against a plain "top stories of the week" list on 4 weeks (0096's measure); unsupported
  lines must be 0; subjects covered per 10 lines, coverage choice against top-by-size.

## What the results should be
- Most sources with 20+ read posts get numbers (not 17 of 138).
- A digest of 10 lines covers more distinct subjects than the 10 biggest stories, with no unsupported line.

## Done when
- Tests: first / alone / repeats on fixtures with origins; thresholds; the greedy choice (a second event on one
  subject needs something new); line checks; the fake-claude test.
- The two measures' tables (private rows).

## Measured (part A counts, 2026-11-20; private: `plan/research/fusion/measure/x1120/E4/`)
On a 40-story sample, 63 sources: with n >= 5, 43 get first-or-alone, 36 a repeats share, 11 adds per post, 3 a median lead. The cards get data where stories alone gave 17 of 138 a verdict; lead time needs more posts per source.
