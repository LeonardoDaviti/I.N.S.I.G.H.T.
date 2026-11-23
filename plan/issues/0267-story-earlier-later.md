# 0267 — Earlier and Later: a story's thread on its page and its News row (Stealth v10.32, Stalker feature 1)

Status: **built and measured** (2026-11-21, worktree of v10.31 `458e2f40`). Not merged, not pushed, not deployed.
Real rows, the frozen sample and both passes' labels are in `plan/research/0267-earlier-later/` (gitignored).

## The reader's need

A reader keeping up with a thing (a model, a product, an incident) opens a story and wants the thread: what came
before it (the leak, the preview) and what came after (the benchmarks, the maker's Q&A, the wider availability), each
with how it relates in plain words. 0219 stores those edges (chain-v1, two Haiku runs that agree, rule `chain_stops`)
and 0236 reads `same_release` for the one-release News row, but `chains.shown` was empty: readers saw none.

## What is built (on what is stored; nothing new is asked)

- **The story page** (`components/markx/MarkXChain.tsx` `StoryChain`, from `graph.chain`): the section is now
  **Earlier and later**, two lists **Earlier** and **Later**, each in date order (oldest first), each link its date,
  the linked story, the relation in words read from the page's side ("earlier in this release", "later in this
  release"), "via a linked story" beyond depth 1, and the judge's reason. Nothing when there is no shown link.
- **A News row** (`graph.row_chains`, read once for the whole page by `news.page`; `RowChain` in the opened row): the
  stories one current shown edge joins to one of the row's own stories, **outside the row** (a one-release row's own
  stories are the row, not its thread), at most 3 a side (`ROW_CHAIN_SHOWN`), the nearest in time to the row's start
  kept, one plain line each: `Earlier: <headline> · <date> · earlier in this release`, and "+N more on the story page".
  `news.SHAPE` 1 -> 2 (a kept page of the old shape is not sent).
- **The switch**: `entity_bands.json` `chains.shown = ["same_release"]` (only the relation that passed). The others
  stay stored, not shown.
- Cost: one indexed read of the chain rows per News page (35.6 ms for 500 stories on the 11-19 copy, migration 0154's
  partial indexes), the story page's two recursive reads as in 0219. The News page is kept (0198), so the row's
  thread is as of the page's run (a chain edge synced between runs appears with the next run's page).

## Measured (blind, two passes, 2026-11-21)

Sample: the 11-19 server copy's current chain edges (692: same_release 494, builds_on 81, development 72, same_event
32, follows_up 7, reaction 6), 60 same_release and 6 of each other relation, picked by md5 of the pair with a salt,
frozen and hashed before reading (`sample.sha`), shown in a random order with Haiku's relation hidden
(`pairs.txt`: the thing, both stories as the chain question showed them, the gap). Judged under 0219's final guide
and the owner's 2026-11-19 one-release rules (a release's rumour, leak, preview, launch, availability incl. an engine's
or a host's support, its benchmarks and rankings, the maker's details and Q&A, first impressions and demos).
Pass 1 on the question text alone; pass 2 read the full posts where pass 1 was unsure and re-judged.

| relation | pass 2 right / shown | point | Wilson lower | pass 1 | shown |
|---|---|---|---|---|---|
| same_release | 59 / 60 | 98.3% | 91.1% | 58/60 (96.7%, 88.6%) | **on** |
| same_event | 6 / 6 | 100% | 61.0% | 4/6 | off (too few rows) |
| follows_up | 6 / 6 | 100% | 61.0% | 2/6 | off (too few rows) |
| reaction | 5 / 6 | 83.3% | 43.6% | 3/6 | off |
| development | 3 / 6 | 50.0% | 18.8% | 3/6 | off |
| builds_on | 1 / 6 | 16.7% | 3.0% | 1/6 | off |

- same_release passes on the informed pass (point >= 97%, Wilson >= 90%); with 0236's re-score of 0219's round 2
  under the same rules (97/98) it is 156/158 = 98.7%. Pass 1's second miss was a pair whose earlier story quotes a
  partner's announcement of the model a week before the maker's launch, which the question's truncated lines hid.
- The one wrong: a many-model benchmark index story where the thing is only compared, chained to a user's impressions
  (the error 0219 and 0236 already found). The guide needs: "an index or leaderboard of many models is not the
  thing's own results unless the thing is its subject" (or the stop question's `about` to require subject, not
  compared).
- Pass 2 accepted near-synonyms for the other relations (a lift of a ban after a suspension as follows_up or
  development); pass 1 did not: their words are not settled.

## What the guide needs for the relations not shown

- **builds_on (1/6)**: the judge answers how the later story relates to the *thing*, not to the earlier *story*: a
  quantised build or a product built on the thing is chained to an unrelated earlier story about the thing (an
  incident, a bug, a visual guide). The question must ask about the two stories, and builds_on needs the earlier story
  to be the thing's release (or its weights) it builds on; otherwise `unrelated`.
- **development (3/6)**: wider availability on a third-party plan is a stage of the release (the guide's own rule),
  and a commentary essay a fortnight before an update is unrelated; the guide should give both as counter-examples.
- **reaction (5/6)**: a clarification answering press reports is a reaction to those reports, not to the maker's own
  earlier post; "reacts to *this* story" must be stated.
- **same_event, follows_up (6/6 each)**: promising but too few rows: 36 of 36 right is the least that passes; the copy
  stores 32 same_event and 7 follows_up. Re-measure on a fresh frozen set once the server has 40+ of each, with the
  words defined (follows_up: the next step of one non-release happening; same_event: one happening filed twice).

## Tests

- `test_markx_chains`: the switch as measured (`shown` = same_release); a relation not shown is on no News row; a
  News row's Earlier and Later outside itself (a row holding both stories has none; the reason, date, headline; the
  `*_more` count; off: nothing).
- `test_markx_kept_pages`: the news shape pair recorded (2, `626a1b818dcd802b`).
- Module runs: chains, release_row, folds, perspectives, kept_pages, built, decide, news_rank, news_sections,
  page_book, timeline: OK (341 tests).
- Frontend `components/markx/chain.test.tsx` (5): the story page's Earlier and Later in date order, the as-of title,
  on the page, a News row's lines, nothing without a link; `tsc --noEmit` clean; markx and newsSections tests pass.
