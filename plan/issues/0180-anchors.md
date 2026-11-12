# 0180 — Anchors: back and later ask Pairing for follow-ups of a story or a happening (Stealth v10.16, slice J)

0166 step 3 (plan/research/v1016-architecture.md section 1). Names below are invented; the real rows are in the
private notes (plan/research/anchors-1016/notes.md).

## The problem

Back in the news (0136, back.py) and later developments (0163, later.py) each found follow-ups of Mark IX stories
only, with private gates: back's 14 d / 7 d / 72 h windows, its 0.70 centre and its type list; later's own type rule
(`specific()`), its main-subject share and its quiet rule. A happening (E6: a deal closed weeks later, a court's
ruling) had no path at all, and a Mark X story was never an anchor.

## Built

### 1. `markx/anchors.py`

- **Anchor** = {kind: `ix_story` | `mx_story` | `happening`, id, members (oldest first), happenings (the members'
  stored keys of a develops group, read from mx_happenings through `happening.stored`, the event-type seam's groups),
  subject (later's main specific subject, when it has one), pages (Pairing's page key), at / last, voices (Pairing's
  voice rule: distinct sources, a saved post none)}.
- `of(cur, kinds, near)`: Mark IX stories and Mark X stories (current members, not merged away) of 2+ voices; with
  `near`, happening anchors: posts of a develops group no story holds (a story member's key one happening with theirs
  within the same-story window holds them too), chained by `happening.same` within the group's same-story window
  (deal 30 d, legal 7 d). Id = the earliest post.
- `follow_ups(anchors, posts, keys)`: Pairing's develops gate over them. A story anchor: never a member, from the
  group's first gap after its last post. A happening anchor: its members a first gap or more before the post (a
  later post of a happening may follow up its earlier posts). One anchor per post and happening: Mark IX story, then
  Mark X story, then happening (RANK), then the latest, then the id.
- `later_find` (the later engine): **the happening first** (H; one source is enough; no quiet rule and no 14/7-day wait:
  the key replaces them), **the subject second** (later's E and L through `later.mains` / `later.match` over Mark IX
  and Mark X stories; a Mark X story that shares posts with the story doesn't house a follow-up away from it; Mark IX
  first among one subject's stories), rows of overlapping anchors joined (the first by RANK keeps the row).
- `back_find` (the back engine): back's trigger (a 72-hour burst of 2+ voices; E, L, V) over Mark IX and Mark X
  stories, pages by Pairing's page key, plus H hits (posts whose happening develops the story's, from the first gap
  after its last post, not 14/7 days). Once a story; again 30 days after its window when it keeps listening (a
  specific subject or a happening key) and is still followed.
- Both engines apply the develops row's unit rule: a roundup is never a follow-up as a whole (Pairing's rule for every
  relation; the old engines didn't).
- `shadow(cur, "back" | "later", ...)`: called from back.stage and later.stage (so inside the decision run's
  savepoint for the stage), on its own clock (`back_anchors_since`, `later_anchors_since`), in its own savepoint: an
  error is logged and returned as `{"error"}`, the old engine's rows stand and its clock doesn't move; a serialization
  failure or deadlock is raised, so the stage is deferred as before. mx_settings `anchors_shadow` (default on) turns
  it off.
- `shown(cur)` (mx_settings `anchors_shown`: `old` by default, `anchors`) decides whose rows back.page, later.of_story,
  later.of_entity, the precisions and the timeline show. The plans ask the shown engine's rows first, then the
  other's, under back's one cap (a question both engines would ask is one task: the same input).
- `compare(cur, "back" | "later")`: the old engine's rows against the anchors engine's (a match shares a follow-up
  post and an anchor member): only old, only new, both, counts by kind and trigger.
- Routes (`markx/anchors_api.py`): `GET /api/markx/anchors/compare?which=later|back`, `GET|POST
  /api/markx/anchors/shown`.

### 2. Pairing's `develops` row

- `develops_windows` (E6): deal 3–120 days, legal 3–30 days; funding, people, release and the rest never.
- `pairing.develops(pol, earlier, later, gap)`: one group of the row, 2+ shared separate parties, no money clash
  (happening.MONEY_TOLERANCE), the gap in the group's window; stage and stated day not compared.
- back's and later's gates moved into the row: `window` 72 h, `min_voices` 2, `cosine` 0.70, `first_after` 14 d,
  `last_after` 7 d, `again` 30 d, `hub_weeks` 6, `types` (back's subject types), `always_types` / `release_types` /
  `release_levels` (later's specific rule, now `pairing.specific(pol, ...)`; later.specific asks it), `main_share`
  0.5, `quiet_days` 14, `quiet_max` 2, `quiet_for_links`. back.py and later.py name them as before (back.FIRST_DAYS
  etc. read the row), so the old engine is unchanged.

### 3. back.py and later.py as callers

- back: `find` = `triggers(cur, stories(cur, now), ...)`; `stories` fills by `fill(cur, stories, page)`; `triggers`
  takes the page key, the recent posts and an anchor caller's H hits; `candidate` reads H as a primary trigger (none
  in the old engine). `write(engine=)`, the once-a-story read and page/precision filter by engine.
- later: `long_lived` = the Mark IX query + `mains(cur, by, origin)` (any story's members); `find` = the clock + `match`
  (`grown`, `rank` for the anchors engine; defaults the old behaviour); `write(engine=)`; `follow` accepts a Mark X
  story too.
- The old engine's own tests (test_markx_back, test_markx_later) pass unchanged, with the Shadow off in their base
  (`_Back.shadow = False`); test_markx_pairing passes.
- Coordination: decide.py is untouched (slice M's area). back.stage and later.stage each gained one dict entry
  (`"anchors": anchors.shadow(...)`) before their plan; if slice M changes the stage bounds there, keep that line.

### 4. Migration 0122 (`0122_markx_anchors.sql`; 0120 is not on this branch: the next free above 0121)

mx_back and mx_later gain `engine` ('old' default | 'anchors'), `anchor_kind` ('ix_story' default | 'mx_story' |
'happening') and `anchor_id` (NULL on the rows before it: read as the story). The once-a-story constraints become
`(engine, anchor_kind, story, window_at)` and `(engine, anchor_kind, story, post, rule)`. Nothing updated or deleted.

### 5. Incremental state

back and later are post-decision stages: nothing they write is in the decision run's digest, so incremental == full
holds as before (test_markx_incremental passes). pairing.py is in incremental.CODE_MODULES: the first decision run
after deploy is full.

## Measured (local copy of the 5 Nov server, scratch, entities linked, happenings backfilled)

Both engines in a simulated run every 2 days from 1 Aug to 5 Nov (no tasks asked):

| | old | anchors | both | only old | only new |
|---|---|---|---|---|---|
| back | 164 | 183 (Mark IX 162, Mark X 21) | 162 | 2 | 11 (all Mark X stories) |
| later | 37 | 54 (Mark IX 25, Mark X 28, happening 1) | 25 | 12 | 29 (Mark X 28, happening 1) |

- Only old: 7 roundups (the unit rule, by design) and 7 Later posts that a Mark X story of the same subject holds and
  that shares no post with the Mark IX story (one story per post and subject, as later.py's rule).
- Happenings: the copy has 15 deal keys and 6 legal keys among 4,900 keyed posts: 1 H row. The H path is E6's
  measurement (2+ parties 23/27 = 85%, deal 12/12), not this copy's.
- 40 only-new rows read blind (before the unit rule): development 8/40 = 20%; development or same story (E6's metric)
  15/40 = 38%; without the 4 roundup rows the rule drops, 8/36 and 14/36. **The bar (85%) is not met.** 39 of the 40
  come from the subject path over Mark X stories (later's E rule): posts naming the model or the paper, demos,
  commentary, a duplicate. 26 of 40 are from one of the anchor's own sources; requiring another source would remove
  6 of the 8 right ones, so it is no fix. 15 old-engine rows read the same way: 4 developments: the old candidates
  are as noisy, and the back judge (87% on its development verdicts) is what filters both.
- The anchors engine's stage takes 0.8 s on average (3.9 s at most) a call on the copy.

**So**: keep showing the old engine (the default). Shadow both for a week on the server and compare the judge's
verdicts on the only-new rows (`/api/markx/anchors/compare`) before switching. Mark X stories as anchors through the
subject rule add noise the judge must remove; the happening path can only be judged on the server's readings.

## Real cases (local copy)

- `company-deal-across-days`: the two posts are unread on the copy; with the server's readings replayed and a
  synthetic close (rolled back): the old engine 0 rows; anchors: one happening anchor (the two posts, 79.6 h apart),
  rows for the second post (3.3 days on: the judge tells retold from development) and for the close (82 days on,
  inside deal's 120). Test: `test_a_happening_with_no_story_is_an_anchor` (invented names).
- `renamed-tool-timeline`: not reachable: one maker post is no story anchor and release is no develops group (0165's
  rename is the fix).
- E5's unmerged stories: a Mark X story begun 3 days before its main one: not linked (an unversioned model is no
  specific subject, release no develops group); two Mark X stories sharing a post: one row per follow-up (the overlap
  rule), the Mark IX story first; anchors never merge stories (decide's merge question stays).

## Tests

- `tests/test_markx_anchors.py`: the develops row (windows per group, parties, money, the gates read from the row),
  `of` (Mark IX, Mark X, happening anchors; a merged or left Mark X story), the later engine (a deal closed weeks
  later; windows by group and parties; funding never; a happening with no story; a money clash; the subject second
  over a Mark X story; one anchor per post, Mark IX first; a grown Mark X story; a roundup never; H and E on one
  row), the back engine (an H burst from its first gap; one voice no burst; the old trigger over a Mark X story),
  Shadow (both engines' rows, the page shows the old by default, the setting route; the comparison route; an error
  leaves the old rows and its clock; a concurrent update defers the stage; off), the migration (old rows read as
  ix_story, one row an engine, the kind check).
- test_markx_back, test_markx_later, test_markx_pairing, test_markx_incremental, test_markx_timeline unchanged and
  passing; the full suite via scripts/test-backend.sh: 3,222 tests OK (2 skipped), exit 0. On the v1016 base
  test_markx_happenings_stored failed (14): its helper recorded an entities answer without the task's input, which
  0176's record now reads; the helper passes `"input": ""` now.
- No frontend change: the Back and Later panels read the same shapes (one more field, `engine`).

## Not done

- The server measurement (a week of Shadow with the judge) and the switch.
- Back's L for papers now compares by Pairing's page key in the anchors engine only; the old engine keeps `norm`.
- A repost's voice (pairing.counted_voice) is not used for an anchor's voices (distinct sources, a saved post none).
- graph.py keeps its own gates.
