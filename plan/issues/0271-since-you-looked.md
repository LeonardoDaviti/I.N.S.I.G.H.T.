# 0271 — Since you looked: one look for the reader, over News, the changed rows and the tracks

Status: **built** (Stealth v10.32, in a worktree off main 458e2f40), not merged, not deployed. Migration **0170**.
Folds in 0154 (seen state, never written), 0094 (since you last looked: the News and track part; stories and
entities are not in it yet) and the keeping-up half of 0096 (what changed). Real rows: `plan/research/since-0271/`
(gitignored: run.txt, result.json, judged.md, simulate.py).

## The problem

The reader keeps up daily, and each place had its own idea of new: News has per-post read state (0238, "Mark all News
read"), each track a look (0207 `mx_track_seen`) with its quick look and rail count (0245), entity pages none. Nothing
said what *changed* since the reader last looked: a row that gained a confirming source, a release row that gained
its benchmarks.

## The choice: one look, kept in mx_track_seen (deepened), not in the read state

- **The look is a seen state, not a read state.** Read state is per post and says "I read this"; opening a list of
  what came does not read its posts, and marking them read would empty News's Unread view behind the reader's back.
  So the look is separate from post_reader_state and touches nothing in it.
- **mx_track_seen already owns the reader's looks** (a track, a sub-topic). It now also keeps the reader's one look
  at everything (track and sub-topic NULL, migration 0170: track_id nullable, the unique index over both). No new
  table, no settings key, one owner: `track_subtopics.seen / look / reader_look / look_all`.
- **One idea of new.** A track's look is the later of its own and the reader's (`seen`): what "Since you looked"
  showed of a track is not new again on the track page, in its quick look or in the rail's count.

## What was built

- `track_subtopics` (owns the looks): `reader_look`, `look_all` ({before, now}); `seen` merges the reader's look.
- `news_service.since_rows` (pure): over News's rows in News's order — `new`: rows begun after the look; `changed`:
  rows begun before it that a **voice** joined after it (a post dated after the look from a source none of the row's
  earlier posts came from), with the voices that joined and their posts, the most voices joined first. A later post
  of a voice already in the row is no change. `NewsService.since(at)` reads it (never writes): never looked, the
  last 24 h; each topic track since its look (the later of its own and the reader's) through
  `track_brief.since_lines`, which reads the track's quick look (no second path): its count, the joined posts with no
  row, and the top 3 lines (first reported after the look first, then most independent sources). `NewsService.look`.
- Routes: `GET /api/news/since[?at=ISO]` (read only), `POST /api/news/since/look`.
- Reader: News's Show gets a third choice, **Since you looked** (`?news=since`), next to All and Unread. Three plain
  lists: New in News (n), Changed (n) (each "+ the voices that joined: the first new post"), then one block per
  track with new things (its name links its topic page, a count, its top lines). Opening it moves the look to now,
  once the list is shown (`components/reader/SinceLooked.tsx`).

## Measured on production (GET only, 2026-11-21 ~12:30 UTC; News: 615 rows, Mark X, ranked)

The view's function run on production's News (`since_rows` on GET /api/news?limit=1000), the tracks from
GET /api/markx/tracks/{id}/brief?since=<look> (what `since_lines` reads):

| look | new rows | changed rows | tracks (new things, joined posts with no row) |
|---|---|---|---|
| 12 h back | 1 | 10 | Agentic 6, 3D 1, Cool Projects 199 (+1), Local 1, Security 66 (+145) |
| 3 days back | 75 | 40 | Agentic 233 (+1), 3D 7 (+1), Cool Projects 763 (+1), Local 240 (+1), Security 408 (+263) |

Judged as a reader keeping up on AI and security (rows in judged.md):
- **3 days, top 20 (10 new + 10 changed): 16 wanted, 4 marginal, 0 not wanted.** The changed list is where the value
  is: a leak row that 18 voices joined, an IPO row 14 joined, a world-model release that gained its availability, a
  harness-adapter release that gained its benchmarks; 9 of 10 wanted.
- **12 h, all 16 shown: 8 wanted, 2 marginal, 4 not wanted** (2 off-topic tracks not judged). The one new row was
  not wanted (a conference post). Of 10 changes, 3 were an all-posts aggregator's translated republish joining as a
  new voice, 1 more a translation echo.
- Cost: the view reads News's whole window (what GET /api/news already reads: 0.90 s on production) and one quick
  look per track (0.04-0.16 s each, 5 tracks): about 1.5 s, nothing kept, no added memory beyond News's own answer.

## What is wrong, and where it is fixed (not in this slice)

1. **A translated republish counts as a new voice** (12 h: 3 of 10 changes; 3 d: also in the lists). The class: a
   source that republishes other outlets' stories in another language is a voice by News's voice rule. Owner:
   News's voice rule / Mark X's same-story join (a republish is a repost, not a report) — measure there, not a
   filter here.
2. **Two rows for one release or one story** (3 d: a release and its index score; an IPO and its returns). Owner:
   one release, one row (Mark X News join).
3. **Track counts now are inflated by re-reads.** 12 h: Cool Projects 199 new things, 7 first reported after the
   look; Security 145 joined posts with no row, 0 dated after it. The quick look counts things found since the look
   from posts of the week in progress (v10.29), and joined posts by their join time; v10.31's re-checks (0169) and
   re-reads re-joined and re-found older posts. The view orders its lines first-reported-after-the-look first, so
   its top lines are mostly fresh; the counts stay the quick look's (one idea of new). Owner: `track_brief.quick_look`
   and the join time of a re-checked post (a post re-joined after a reset is not new) — measure once the backlog is
   read, then decide.

## Not done

- Stories and entity pages (0094's story/entity part): an entity page's "new since you looked" needs the entity's
  events per time (0095); left to that work.
- Nothing on the reader rail: the view is one more Show choice of News (plain, no badge).

## Tests

- `insight_core.tests.test_since_0271` (new): new and changed rows (a voice joined, the same voice again is no
  change, benchmarks joined first), ISO times and the shown limit, the routes (read only GET, 400s, the POST), the
  one look row on the database.
- `test_track_briefer_0245`: `since_lines` from the quick look; the reader's look moves the track's look and the
  rail's count.
- Frontend: `SinceLooked.test.tsx` (the three lists, the look moved once, nothing new), `ReaderPage.news.test.tsx`
  (Show: All, Unread, Since you looked).
