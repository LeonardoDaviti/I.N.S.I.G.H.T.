# 0145 Built: tracks as topics

Built 2026-11-09 on its own branch (Stealth v10.11), on main at ed55066. **Migration 0093** (`mx_tracks`,
`mx_track_items`, `mx_track_subtopics`; `mx_tasks.subject_kind` may be `track` and `post_track`; `mx_labels.item_kind`
may be `track`). Mark X tables only, no key to a Mark IX table; the owner's "make it active" writes the folder's source
list as Sources does. Private rows (titles, sources, every verdict and label) stay in `plan/research/0145-notes.md`.

realdata-check: run at merge.

## What changed

| # | Spec | What changed |
|---|---|---|
| 1 | A track is a topic | `markx/tracks.py`: a folder with an `mx_tracks` row and a description is a topic (`set_topic`; new words or excludes are a new `version`, the old verdicts kept); without one it stays a folder and nothing reads it. Its active sources are the folder's (read when needed, so a source made active turns its items into track items). `PUT /api/markx/tracks/{id}`. The **track sheet** (`components/tracks/TrackSheet.tsx`): name, what belongs, what doesn't, the active sources, the examples so far, the sub-topics. |
| 2 | Who is judged, when | `tracks.plan` (`tasks.PLANNERS["track"]`, at lease time): active sources' posts of the reading window, newest first; passive posts of the last 7 days the prefilter passes; the **history pass** once a version, every older post, newest first, 2,000 a page, at most 10 pages a call, resumable (a keyset cursor on `mx_tracks`), its tasks at priority 1000 + age so new posts lease first. One `mx_track_items` row per track, post and version; a repost sharing a question shares its verdict. |
| 3.1 | The prefilter | The profile: the description's BGE-M3 vector (an `embed` task, subject `track`, leased first, stored by `embed.store`) + the ✓ mean − 0.5 × the ✗ mean, scaled to 1. The bar after 5 ✓: the highest that keeps 98% of the ✓ passing, each ✓ scored **leave-one-out**. **Before 5 ✓: the cosine that passes 30% of the last 30 days' posts, at most 0.55** (see the measure: 0.55 alone passed 0.09–6% of a month and 0–27% of the posts that belonged). Each plan logs scanned / passed / planned per phase (`mx_tracks.stats`, and the log). |
| 3.2 | The `track` task | Guide `track-v1` (`markx/guides/track-v1.md`), schema `{in, confidence 0–1, subtopic, why}`, `validate._track` (`why` one line, ≤ 300 characters). The question: the track's header (name, what belongs, what doesn't, the locked sub-topics, the 4 newest ✓ and 2 newest ✗, titles cut at 140) and the post (markx text v1, 1,200 characters, 3 links). Refusals halve as the worker does; an empty answer is a failed try. |
| 3.3 | Labels as examples | `POST /api/markx/tracks/{id}/labels {post, answer: in \| out \| undo}` (`mx_labels`, kind `track`, the newest counts); they shape the profile, the bar and the guide's few-shot. |
| 4 | Where a judged post goes | Read when the page is built (`tracks.placed`): an owner ✗ is out (kept, counted); an owner ✓ or an active `in` is in the track; a passive `in` is in Discover, ranked by the Wilson lower bound of the owner's labels on passive `in`s at or above its confidence band (by confidence until 10 labels); **auto-join**: the lowest band (with labels of its own) whose passive `in`s at or above it have 20+ labels, 90%+ ✓ and a lower bound of 0.85+ makes those at or above it "joined by INSIGHT"; when that stops holding they are back in Discover. `out` verdicts are kept, never shown. |
| 5 | Sub-topics | `subtopics` task (guide `subtopics-v1`, one track a call): planned at 15+ items, then weekly when new items came. Each proposed sub-topic collects the judge's subtopic strings its items had (majority); an item goes to the sub-topic holding its string or named like it, else "Other". `POST /api/markx/tracks/{id}/subtopics` rename / merge / split (strings to a new one) / lock / unlock / add; an owner edit locks; a new proposal closes the unlocked ones (`valid_to`) and keeps the locked, whose names the judge is given. |
| 6 | The track finds its sources | A passive source with 3+ items judged `in` (not ✗ by the owner) in 30 days: on the track page ("Example Blog: 3 of your Prints in 30 days — make it active?", one tap: `POST /api/markx/tracks/{id}/sources/{source}`) and as Discover's first block (`TrackSourceLines.tsx`, Mark X on only). |
| 7 | Cost guard | At most `INSIGHT_TRACK_TASKS_PER_RUN` (default 300) track tasks open across tracks; each phase shares what is left among the tracks; the history pass comes last. The page's footer: cost so far, cost a day and items a day (7 days), questions asked, posts judged out. |

The reader: a track offers **View … / topic** while Mark X is on (`?view=topic`, `TrackTopic.tsx`, its own chunk): the
words, the precision and the auto-join bar, the sources it found, sections by sub-topic (newest first), Discover, the
footer; ✓ / ✗ on every row. Design: `reader.md` (View topic, the track sheet), `sources.md` (Discover's block).
Worker: `track` and `subtopics` in `DEFAULT_KINDS`, `PER_CALL` `track=10,subtopics=1`. API routes: `markx/tracks_api.py`.

## Tests

- `test_markx_tracks` (25): a folder stays a folder; describing and versions; the kinds, schemas and validation
  (an empty answer refused); the profile, leave-one-out, the 98% bar, the 30% default capped at 0.55; active posts
  judged without the prefilter; the prefilter's pass and its logged counts; the history pass (cap, resume, done, its
  priority); the per-run cap and its env; the description embedded by the worker (leased first, stored, not asked again,
  asked again for new words); routing (active → track, passive → Discover, out kept, ✓ / ✗ / undo); a repost's shared
  verdict; calibrated ranking; auto-join at 22+ right labels and back off when it drops; labels as examples; source
  suggestions at 3+ in 30 days and "make it active"; the footer; sub-topics proposed at 15+, renamed, merged, split,
  locked, the judge given the locked names, a new proposal keeping them; none under 15.
- `test_markx_storage`, `test_markx_validate` updated for the three tables and two kinds.
- `markx/incremental.py` `memo_for`: the last finished run is told apart by `finished_at` too. Runs started in one
  transaction (the tests') share `started_at`, and `ctid` alone stopped telling them apart once a run's row grew (the
  two new kinds in its config): `test_markx_incremental` failed on the branch before this, passes after.
- Worker: `scripts/tests/test_markx_worker.py` `TestTracks` (fake-claude): default kinds, 10 a call, one sub-topic
  question a call.
- Frontend: `components/tracks/tracks.test.tsx` (8), `pages/ReaderPage.topic.test.tsx` (3). `npm run build` passes
  (feed route +0.25% gzip, the topic view its own chunk); `npx vitest run`: 76 files, 870 tests pass.

## Measure (4 real checks)

On `insight_server_1105_mxreal` (the server export of 2026-11-05 with 20,742 BGE-M3 vectors) as a scratch copy
migrated to 0093, dropped after. Three tracks described as the owner's (project ideas; things worth 3D printing; cheap
local AI setups), no active sources (everything passive), no examples. The descriptions embedded once by the local
llama-server (the build the copy's vectors are). 30 days = 5,751 posts, all embedded.

**1. The prefilter over 30 days** (pass rate; recall on keyword-search posts the agent read and labelled should-be-in:
20 of 40 for projects, 2 of 21 for prints, 22 of 40 for setups):

| Track | 0.55 (the spec's default) | Adopted: top 30%, ≤ 0.55 | Prefilter recall at 0.55 | at the adopted bar |
|---|---|---|---|---|
| Project ideas | 22 / 5,751 (0.4%) | bar 0.427, 1,729 (30%) | 0 / 20 | 10 / 20 |
| 3D printing | 5 / 5,751 (0.1%) | bar 0.417, 1,727 (30%) | 0 / 2 | 2 / 2 |
| Local setups | 346 / 5,751 (6.0%) | bar 0.478, 1,727 (30%) | 6 / 22 | 15 / 22 |

The description alone is a weak signal (the median post is at 0.39–0.44 to it, a post that belongs often at 0.36–0.45),
so the fixed 0.55 let almost nothing through; 30% is a share, not a number fitted to these tracks. Recall at 40% would
be 12 / 20 and 16 / 22; the ✓ examples then set the bar (98% of them pass).

**2. The judge** (Haiku, `track-v1`, 10 a call, 137 judgements, $0.0263 as Claude Code reported it: ~$0.00019 a post).
A sample of each track's month, 18 from the top 10% by cosine and 17 from 10–40%, plus up to 15 of the keyword
should-be-in posts; every verdict labelled by the agent from the post's text:

| Track | `in` in the sample | Precision of `in` | Judge recall on should-be-in | Missed in the sample |
|---|---|---|---|---|
| Project ideas | 11 / 35 | 7 / 11 (64%): 4/5 top 10%, 3/6 in 10–40% | 13 / 15 | 1 (a thin post on the author's own engine) |
| 3D printing | 0 / 35 | — (no post of the month's sample belongs) | 1 / 2 | 0 |
| Local setups | 14 / 35 | 11 / 14 (79%) | 13 / 15 | 0 |

Wrong `in`s: an essay with tools in passing, a workflow tip, a newsletter roundup, a paper with code (projects); a local
dubbing app, a data-centre engine, a model evaluation (setups). Missed: a joke repo and a benchmark write-up (projects),
two laptop launch posts (setups), a title-only post (prints, the guide's "too thin" rule). End to end at the adopted bar
(prefilter and judge) on the judged should-be-in posts: 8 / 15 projects, 1 / 2 prints, 8 / 15 setups.

**3. The history pass**, per track at the adopted bar: 6,731 (projects), 5,948 (prints), 5,057 (setups) tasks of the
20,742 posts with a vector, about $1.29, $1.14 and $0.97 at the measured cost; 28,642 older posts have no vector and are
not read by it until they are embedded (the embedder runs on request). At 300 open a run, about 20 runs a track.

**4. One planner call on the copy** (as a lease makes it): 300 tasks planned across the three tracks (100, 101, 99),
the cap held; recent posts at priority 0–1, the history pass at 1,000+; scanned 1,323 recent posts per track, 407–456
passed; the history pass resumed past the recent posts already asked.

## Open

- After deploy (spec measure 3): the owner's first labels; precision per track after 20.
- The prefilter's 30% default is an adopted change from the spec's 0.55 (measured above); the owner may prefer another
  share (`DEFAULT_PASS_SHARE`).
- Auto-join's two bars together: with 1.96 for the Wilson bound, 20 labels can never reach 0.85 (20 of 20 gives 0.839);
  the first band that can join needs 22 of 22, or about 60 labels at 95%. As specified; say if 90% raw on 20 should do.
- Discover's rank uses the labels at or above each band (cumulative), so a band without labels of its own borrows the
  precision of those above; ties go by confidence.
- 28,642 posts have no vector on the copy: the history pass skips them (counted as `unembedded`) until they are embedded.
- The worker in the main checkout must be updated at merge (`DEFAULT_KINDS`, `PER_CALL`), not while it runs.
