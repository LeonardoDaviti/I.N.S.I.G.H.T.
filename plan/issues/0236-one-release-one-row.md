# 0236 — One release, one News row (Stealth v10.25, slice K; backlog #34)

Status: **built; the join is OFF** (`entity_bands.json` → `chains.one_row: false`), the leak-lead title fix is ON.
No real data was read (owner order for this slice: no server requests, no clones, no prepared databases). The
re-score reads only 0219's stored labels and answers (`plan/research/0219-chains/`, private). No migration.

## 1. The case

A model release showed as two Mark X News rows, both tagged SPLIT. Row A had a Haiku headline ("<maker> launches
<model>"). Row B was named by its lead post's title, a rumour account's "…Leaks: Coming Today…". B also held the maker's
"rolling out now", a router's availability post and a third party's benchmarks. Both rows had the same thing, the same
type (model_release), and were hours apart. The owner's rule (2026-11-19, memory `one-release-one-row`): everything
about one release of one exact thing (leak, teaser, preview, launch, availability, benchmarks, breakdowns) is one row,
even across days, oldest first, named by the launch and never by a leak. same_event + same_release is one row. A
maker's Q&A weeks later is still open; it is counted out here.

## 2. 0219's chains re-scored under the owner's rules (no new labels, no new Haiku answers, the guide unchanged)

The disputed items are the both-runs `same_release` edges where the labellers' majority said something else (2 in round
1, 6 in round 2). Each one is relabelled by the rule below. The real rows are in
`plan/research/0219-chains/rescore_0236.py` and `.log`.

| set | item (invented gist) | gap | rule applied | in the row? |
|---|---|---|---|---|
| 1 | an engine's day-0 support -> the maker's "live on <host>" plus an event | 15 d | availability on a platform, even across days | yes |
| 1 | early user tests -> an engine's day-0 support | 1 d | an engine's day-0 support is availability; tests are first impressions | yes |
| 2 | a many-model coding index -> a user's first impressions | 0 d | rule C: the index story's main subject is the index, not the release (runaway guard) | **no** |
| 2 | one safeguards happening filed twice (labelled same_event) | 0 d | same_event + same_release is the same row | yes |
| 2 | a quantised build trending -> third-party benchmarks | 3 d | third-party benchmarks are in the row; the build on a hub is availability | yes |
| 2 | an open-sourcing -> an explainer and a hands-on review | 7 d | breakdowns are in the row | yes |
| 2 | the launch -> the maker's AMA | 28 d | a maker's Q&A weeks later: open, counted out | **no** |
| 2 | the weights release -> the same AMA | 17 d | the same | **no** |

| held-out set | right / shown | point | Wilson lower | bar (97% and 90%) |
|---|---|---|---|---|
| round 1 (old guide) | 55 / 55 | 100% | 93.5% | pass |
| round 2 (final guide) | 95 / 98 | **96.9%** | 91.4% | **fail by one item** (96/98 is needed) |

- If the owner rules that the maker's Q&A is in the row, round 2 is 97/98 = 99.0% [94.4]: a pass.
- Explored only, not claimed (a cap chosen after reading the set): with a 14-day cap, round 2 is 91/92 = 98.9% [94.1].
  The owner's "even across days" argues against a cap.
- The re-score is of sets already read and labelled before these rules existed. The rules come from the owner, not
  from the errors, but it is still not a fresh frozen set.

## 3. What changed

**The one-release row** (`markx/graph.py`, `markx/news.py`; off):
- `graph.release_groups(cur, stories)` makes the groups that current `same_release` chain edges (rule `chain_stops`)
  form among the given stories. It returns `[]` while `chains.one_row` is off, without a query.
- `graph.release_components` (pure) gives each story only the edges of its own release thing. That thing is the one
  most of its edges are about, with the lowest id breaking ties. So a group is about one thing, and a story that is a
  stop of a family and of a version never chains them.
- The runaway guard holds: an edge exists only between two stories that stop-v1 says are about the thing. A story that
  only mentions the thing has no edge.
- `news.rows_of` treats a group as one story for News's code. Its posts are in date order (the leaks first), it is
  keyed by the lowest story id, and every post still names its own story. The judge's story pairs are mapped onto the
  groups, so the large-story guard reads them too.
- `news._changed_rows` (incremental) seeds from the groups that came or went since the last run, and its closure
  follows the groups now and before. `write` reads the groups once a run and keeps them in the News state.
- `news.headlines`: a row with 2+ stories in one group is named by its launch (`launch_order`). That is the headline
  of the story holding the maker's own post (`built.build`: original `how == "maker"`), else of the newest story of a
  news type. A leak story is never used. Without such a headline, the row falls back to the usual path.

**The leak-lead title** (`news.headlines`; on): a row with no headline answered yet used its lead post's title. Now,
when the lead post's read-v3 type is `leak_rumour` and the row holds the maker's own post, the row takes that post's
title instead (`from: "maker title"`). The frontend type is widened to match.

## 4. Why the run made two rows (backlog #34's "check why")

The SPLIT tag (`news.tag`) means that Mark IX's one News row holds posts that are in two Mark X rows. Mark X did not
split a story. It kept two stories apart and then refused to join their rows. The likely chain, read in the code (not
checked on the real rows: no real data in this slice):
1. **Joins pull the launch posts into the leak story.** A join is asked against the story's earliest three reports
   (`decide.py:251-252` `side`, `:308` `side=tuple(side(key)[:3])`, members sorted by time at `:222`), and
   `development` counts as "about" (`:61`, `:416`). So the maker's "rolling out now" joins the teaser story as a
   development. The posts that embed closer to the launch story's posts join that story instead (`:303`, the
   candidate's anchor story). That is how the maker's posts land on both sides.
2. **The merge never fires.** Two stories merge only on `same_event` at p >= 0.85, confirmed by a second answer
   (`decide.py:472`, `settle` `:571-597`). The merge question also shows each story's earliest three reports
   (`:298`, `:325`, pass 2 `:359`). For the leak story those are the teasers, so the judge sees "rumours" against "the
   launch", which judge-story-v1 calls a development, not the same event.
3. **News will not join two large stories without a judged connection.** `utils/news_rules.py:409-414` joins two
   stories of 5+ posts (`LARGE_POSTS`) by a surging name only when the judge connected them (development / follows_up
   / same_event at the merge bar: `built.py:40`, `:208-215`). That read excludes the chain edges (`:213`, rule
   `chain_stops`). Mark IX has no judge and joins by name alone, so it kept one row, and that is why both rows are
   tagged SPLIT.

Not fixed here: changing what the merge or join question shows (the earliest three reports) changes a guide's inputs,
which needs Haiku and a held-out set. The one-release row (section 3) answers the case once it passes its bar.

## 5. Tests

- New `tests/test_markx_release_row.py` (9), built from invented rows:
  - groups are about one thing, and a story of two things never chains them;
  - `release_keys`;
  - `launch_order` (the maker's story first, else the newest news-type story, never a leak);
  - **a leak story and a launch story of one version become one row, in date order, named by the launch** (off: two
    rows, named by the leak story as before);
  - a story that only mentions the thing stays out;
  - an edge that is not same_release, or a closed edge, joins nothing;
  - the leak-lead title, and a lead that is not a leak keeps its own title;
  - an edge that opens joins the rows in an incremental run, the same rows as a full run.
- `test_markx_chains`: `chain_config` now includes `one_row: False`.
- Module runs, on the scratch Postgres: release_row, decide, chains, built, news_sections, news_rank, incremental,
  news, grouping. 259 tests, OK. The full suite and the real-data check are the integrator's.

## 6. Not measured

- Seconds and peak RSS on real data: not measured (owner order: no real data). While off, the cost is no query.
- The leak-lead title cost is one `types_of` read for the untitled rows, plus `built.build` for those led by a leak.
- How often the maker title applies on the server: unknown.
