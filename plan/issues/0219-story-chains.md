# 0219 — Story chains: typed links between events across time (Stealth v10.24, slice "chains")

Status: **built and measured** (2026-11-17, worktree branch of v10.23 `2dce4786`). Not merged, not pushed, not
deployed. Names here are invented; the real rows, every answer and every label are in `plan/research/0219-chains/`.
Migration **0154** (`0154_markx_story_chains.sql`; renumber at merge if another slice takes 0154).

## 1. The problem, as a class

Edges join posts (0131), stops say "story S is about thing T" (0165, on, 97% precise), but two stories about the same
thing at different times are separate and nothing says how they relate: a model's preview, its launch, its weights
and its benchmarks are four rows and four stories. Experiment G (0091) found plain similarity gives 19% meaningful
candidates, "follows up" only 50% right (a next version reads as a follow-up), and name/family matches alone 3%. A
strong candidate source exists since v10.23: two stories that are both stops of the same exact thing.

## 2. The model

- **Candidates (rule `chain_stops`)**: each thing's stops (its stored stop-v1 answers saying about, under any name of its
  cluster; stories merged away or with no current member left out), ordered by their first member's date; each stop is
  paired with the `CHAIN_PREV` = 3 stops before it whose first post is at most `CHAIN_DAYS` = 30 days earlier. A pair
  two things propose (a family and its version) goes to the thing with the fewer stops (the narrower one). Only the
  stops answered since the last pass are paired again (mx_settings `chains_planned`).
- **The question** (kind `chain`, guide `chain-v1`, subject `story_story`, a = the later story, b = the earlier): the
  THING (name, type, maker), the EARLIER and the LATER story as the stop question shows a story (headline, dates,
  post count, the earliest 6 posts with how each treats the thing), and the days between them. Answer
  `{reason, relation, confidence?}`; `reason` must not be empty (validate); `next_version` is not a relation: a
  successor stays identity's rule (0131).
- **Relations**: `same_release` (one release of one exact thing at any stage: rumour, teaser, preview, launch, weights,
  availability incl. an engine's or host's support, its benchmarks and rankings, the maker's details, first
  impressions and demos), `same_event` (one non-release happening filed twice), `follows_up` (the next step of the same
  non-release happening), `development` (a new happening that changes what the earlier reported), `reaction` (a named
  party's response), `builds_on` (another party's own model or study from it: quantised weights, fine-tunes, studies),
  `unrelated` (no edge).
- **Asked**: Haiku only (the worker's model), effort low, 10 a call, **two runs**; an edge only when both agree
  (`CHAIN_RUNS` = 2; the task is opened again after its first answer, as relate's). Planned by the jobs process's plan
  job (`tasks.BACKGROUND_PLANNED`, after `stop`), never a decision run or a lease, at most 300 new questions a pass,
  the newest later story first. Consumer feature: `graph`.
- **Stored**: `mx_connections` rows `a_kind = b_kind = 'story'`, rule `chain_stops`, `call_id` the first agreeing call,
  `p` 1.0, evidence `{reason, thing, runs}`. Every relation is stored; an edge whose verdict changed, or whose pair is
  no longer two stops of one thing (a stop answer that now says not about, a story merged away or emptied), is closed
  (`valid_to`), never deleted. A sync reads again only the pairs answered since the last one (`chains_synced`); every
  current edge is checked against the pairs proposed. decide's story connections never read or close them (rule
  filter in `persist_connections`), built's leak links never read them, the post panel leaves them to the story page.
- **The chain** (`graph.chain(cur, story, as_of=None)`): one recursive query a side over the chain rows valid at
  `as_of` (now by default): `before` (what led to it: a -> b, then on), `after` (what followed: b -> a), depth 3, 12 a
  side (`*_more` the rest), each link `{story, via, relation, reason, depth, headline, first_at}`, nearest first then
  by date, only the relations shown. Migration 0154: two partial indexes `(a, valid_from)` and `(b, valid_from)` over
  the chain rows (closed rows too; the rule written as a literal so the planner proves them).
- **API**: `GET /api/markx/stories/{id}` adds `chain` (`?as_of=` an ISO date: only the edges valid then); empty while
  the switch is off.
- **Frontend**: the story page's **Chain** section (`components/markx/MarkXChain.tsx`): "Led to it" and "Followed",
  each link its date, the linked story, the relation in words read from the page's side ("earlier in this release",
  "later in this release", "builds on this"...), "via a linked story" beyond depth 1, the judge's reason; nothing when
  there is no link.
- **Switch** (`entity_bands.json` → `chains`): `on` (the plan job asks and syncs, the page shows), `shown` (the
  relations a reader sees).

## 3. Measured (read-only GETs of the server, 2026-11-17; Haiku as the worker asks it; blind labellers as subagents)

Bar for every word shown to the reader: point >= 97% and Wilson lower bound >= 90% (precision of the edges shown).

### Dev (guide writing)
- Sets: 102 pairs of 46 things from 0165's entity pages (stops = 0165's stop-v1 answers saying about, pairs at most 30
  days apart, at most one per gap band a thing) + the release case's 10 pairs.
- Draft 1, labellers on the first label guide (agree 106/112): one run `same_release` 27/30 (90%); other relations
  under 50%; run to run 85%.
- Draft 2-3 (impressions, demos and the maker's details are part of a release; another party's builds and studies are
  `builds_on`; an index of many models is not the thing's own results), two new labellers on the revised label guide
  (agree 111/112): one run `same_release` 40/43 = 93.0% [81.4-97.6]; **both runs agree: 35/36 = 97.2% [85.8-99.5]**.
  Hence two runs.

### Held-out round 1 (frozen and hashed before reading: `held.sha`)
- 279 pairs: every candidate pair (production's `chain_pairs`) of the stops of 36 products of the server's 30-day entity
  list that the dev never used (stop-v1 asked by Haiku as the worker would: 233 questions, 173 stops); 19 things have
  pairs (one broad product gives 106). Three blind labellers (agree 272-275 of 279).

| relation (both runs agree) | right / shown | point | Wilson | bar |
|---|---|---|---|---|
| same_release | 53 / 55 | 96.4% | 87.7% | **fail** (point and lower bound) |
| builds_on | 15 / 24 | 62.5% | 42.7% | fail |
| development | 2 / 5 | 40% | 11.8% | fail |
| same_event | 1 / 3 | 33% | 6.1% | fail |

- Both `same_release` errors were an inference engine's day-0 support for a model, which the label guide called
  `builds_on` and Haiku (both runs, both guides) called availability. 0165's second case files an engine's day-0
  support inside the model's weights story, and 0217's owner rule makes availability on platforms part of the one
  row, so the definition changed (an engine's or host's support around the release is availability; another party's
  own model or study stays `builds_on`). That is a change after a held-out read: round 1 stays a fail on record and
  the change is measured on a fresh frozen set.

### Held-out round 2 (frozen and hashed before reading: `held2.sha`, guide sha256 `be24941d...`)
- 307 pairs: every candidate pair of the stops of 89 fresh products (named as subjects in the server's News rows'
  first posts, or versions listed on the pages already read; never in dev or round 1: 167 stop questions, 139 stops, 58
  pairs over 24 things) and 249 pairs never seen before of the dev things' stops (production's `chain_pairs`, the
  pairs of dev, round 1 and the case dropped, at most 10 a thing by a hash of the pair). Haiku twice with the final
  guide; three new blind labellers on the final label guide (agree 294-300 of 307).

| relation (both runs agree) | right / shown | point | Wilson | bar |
|---|---|---|---|---|
| same_release | 92 / 98 | 93.9% | 87.3% | **fail** |
| builds_on | 6 / 9 | 66.7% | 35.4% | fail |
| development | 3 / 12 | 25.0% | 8.9% | fail |
| same_event | 4 / 8 | 50.0% | 21.5% | fail |
| follows_up | 3 / 4 | 75.0% | 30.1% | fail |
| reaction | 1 / 1 | | 20.7% | fail |

- One run alone: same_release 99/114 (86.8%) and 101/109 (92.7%); two runs agree on 264 of 307. Recall of the
  labellers' same_release pairs (both runs): 92 of 130 (71%).
- The six wrong (exact rows in `plan/research/0219-chains/`): a many-model index story joined to a user's
  impressions; one happening (a maker's quiet safeguards) filed twice, which the labellers call `same_event`; a
  third-party comparison three days after a quantised build trended (labellers 2-1); a product's explainer a week
  after its open-sourcing; the maker's AMA 17 and 28 days after two release stories (labellers 2-1 both).
- Explored on the sets already read (no claim): a gap cap does not lift it over the bar (round 2: 3 days 63/66 =
  95.5%, 7 days 78/82, 14 days 88/92); counting `same_event` with `same_release` as "one news item" gives 104/110 =
  94.5% [88.6]. Round 1 under the same caps reaches 97.9-98.1% but is under the old guide. Haiku's own noise (two runs
  disagree on 14% of pairs) is the size of the gap, as with 0165's stop words.

### The owner's release case (0217, "Orbit-Max": a preview, then the launch day's launch, router, benchmark and arena
threads, five stories)
- The five are stops of the model by their share (the server has not asked their stop questions yet); `chain_pairs`
  proposes 9 of the 10 pairs (the preview and the arena ranking are 4 stops apart).
- Haiku, both runs, final guide: **same_release on 9 of 9 proposed pairs** (and on the 10th); the labellers: 10 of 10
  `same_release`. The five stories are one connected component of `same_release` edges: the preview reaches the
  launch-day rows directly and the arena row through any launch-day row.
- So `same_release` edges find the release case, and a News row change can read "one release" as a component of
  `same_release` edges among its stories (not built here). On held-out pairs they are 94-96% precise, so that change
  would need its own guard (or the next measured step below) before it joins rows by them.

### Resources (scratch clone of prep_mxreal, migrated to 0154, a 549-day story window, one real decision round, then
30,000 synthetic stories with 39,895 stop answers over 3,000 things to reach and pass the server's size)
| what | value |
|---|---|
| the plan job's chain pass (300 questions, the production limit), 40k stop answers, 32k stories | 1.28 s, peak RSS 88.6 MB (43.5 MB at start: +45 MB) |
| one pass with no limit (17,595 questions at once) | 6.3 s, 143.6 MB |
| the first sync after 17,895 pairs were answered (5,838 edges opened) | 20.6 s, 101 MB (once; later syncs read only the pairs answered since) |
| the chain query, 1,500 stories with edges, 29,551 chain rows (5,877 current, 4 closed versions of each) | now: p50 13.3 ms, p95 22.5 ms, max 33.9 ms; as of a random day: p50 6.4 ms, p95 13.0 ms, max 23.3 ms (index scans on 0154's indexes) |
| the planner's reads | SQL only: the stop answers as (story, thing, about, at) rows, the candidate pairs' task ids, the calls of the pairs answered since the last sync; nothing read whole into Python |

- **On the server**: the stop planner had asked 2,400 stop questions of the last 30 days' stories by 07:30 on 11-17
  (300 a pass, the backlog still running). With 74% of them stops (0165: 596/800; round 1: 173/233) and 0.4-1.6
  pairs a stop (round 2's small things; round 1's big ones), the first month gives about 700-3,500 pairs, then about
  60-120 new pairs a day: 120-240 answers a day (two runs), **12-24 Haiku calls a day** at 10 a call, about $0.0015 a
  call measured (**~$0.02-0.04 a day**; the first backlog ~$1 once).
- **Edges a month**: both runs agree on a link for 31% (round 1) to 41% (round 2) of the pairs, same_release 20-32%:
  about 600-1,400 edges a month, 400-1,100 of them same_release, all stored, none shown. The whole archive gets no
  chains: stops are asked only for stories with members in the last 30 days (0165), so chains run from the deploy's
  30-day backlog onwards. (The 11-05 clone's own real stories after one decision round gave 133 stories with members
  in its window, 257 stop questions and 139 pairs: too few to say more.)
- Haiku spent measuring: $0.47 (15 runs).

## 4. What is on

| | state |
|---|---|
| the chain questions (kind `chain`, plan job, two runs) | **on** (`chains.on`): every pair of stops asked, every verdict stored as an edge |
| the edges shown on the story page | **off**: `chains.shown` is empty: no relation passed its bar |
| same_release | stored, not shown (93.9% [87.3] held out) |
| same_event, follows_up, development, reaction, builds_on | stored, not shown (25-75%) |
| the post panel, decide's connections, built's leak links | never read a chain edge |

Switch on a relation by listing it in `entity_bands.json` → `chains.shown` once it passes on a fresh frozen set.

## 5. Open questions for the owner

1. **Ask and store while nothing is shown?** Chains cost about $0.02-0.04 a day and are the input of 0217's
   one-release row (`same_release` components). The 0210 rule asks a question only for a feature that reads it; here
   the reader is the next slice (News). Keep `chains.on` (default here) or switch it off until the News slice?
2. **Is an inference engine's day-0 support part of the release?** Changed to yes after round 1 (0165's case files it
   in the weights story; 0217 counts availability on platforms in the row). Labellers followed the guide; please
   confirm, it decides many pairs.
3. **How far does a release reach?** The maker's AMA a month later, first impressions two weeks later: labellers split
   2-1. A cap of 7-14 days for `same_release` is the owner's call (0217's narrow arm used 14 for stages, 3 for lines).
4. **One news item = same_release or same_event?** For the News row both mean "the same news"; merging them is 94.5%
   on round 2, still under the bar.
5. **Next measured step** (not built): a third Haiku run only where the two disagree, or the stop's own word (0165,
   off) as an input, measured on fresh days (2026-11-17..23, once the server's stop answers exist), with the same bar.

## 6. Tests

- `test_markx_chains` (15): the candidate rule (window, three back, the narrower thing, only fresh stories), the
  verdict (both runs, unknown on a split), the question's shape, the kind (guide sha256 frozen before round 2, schema,
  validate, planner, consumer, the switch as measured); on 0165's second case: asked once later-against-earlier and
  only after both stops say about, nothing when off; agreeing runs make an edge read both ways; differing or unrelated
  runs make none; a relation not shown is stored; a pair no longer proposed closes its edge and `as_of` still reads it;
  several links without a loop; decide never closes a chain edge and built never reads one; the worker's path (asked
  twice through lease and answer) and the story page's `chain` field (`as_of`, off).
- `test_markx_jobs`, `test_markx_validate`: the kind in the planners and the kinds set. Worker tests: `chain` after
  `relate`, 10 a call, effort low, its answers pass the server's rules.
- Frontend `components/markx/chain.test.tsx` (3): the Chain section's lines and words, nothing without a link, on the
  story page; `npm run build` (bundle check passed: markxStory -1.14% against its budget).
- Module runs: chains, timeline, validate, jobs, graph, built, api, consumers, decide, holds, perspectives (345 tests),
  the worker's 106: OK. The full suite and the real-data check are the coordinator's.
