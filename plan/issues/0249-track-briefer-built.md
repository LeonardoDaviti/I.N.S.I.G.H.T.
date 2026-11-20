# 0249 — the general track briefer, built (v10.27; the backend of 0245)

Status: **built, switched off** (`entity_bands.json` `tracks.briefs: false`), not measured, not merged, not pushed.
Migration **0163**. Spec: 0245 ("The general design after the experiment"), 0207 (sub-topics, digest, seen state).
Prototype and prompts: `plan/research/briefer-0245/` (private). No real data was read for this build.

## The rule it follows

One briefer for every track. A track's name, description and excludes are its only track-specific input; no code,
field, constant or guide names a track, a kind or a field. Every check is about a type (text, number, money, link,
enum). The tests prove it on three invented tracks of different kinds (hardware setups, printable designs, cooking
recipes); none of those words is in the code.

## What was built (each in the module that owns it)

1. **`markx/track_things.py`** (new) owns the schema, the things, the reports and the joins.
   - **Schema** — kind `track_schema`, guide `track-schema-v1`, one question a track and description (planner
     `plan_schemas`). Haiku proposes 1-3 kinds, up to 8 typed fields each (text | number (+unit) | money | link |
     enum (+values)), 1-2 key fields, the first field the name. Code always adds `practice_or_claim` (what, result,
     evidence). Stored with the track, one row a version (`mx_track_schemas`, `by` haiku | owner, `track_version`); a
     description change (the track's version) proposes again. The owner's edit (`PUT .../schema`) is a version of its
     own. A new version re-reads every post in the track (its questions name the version).
   - **Things** — kind `track_things`, guide `track-things-v1` (planner `plan_things`), asked only for posts in the
     track (`track_subtopics.in_track`: judged in, joined, the owner's ✓), newest first, at most 60 waiting a track.
     A long post is read in windows (`tasks.text_windows`, 3,500 characters, 6 at most; the window line `tasks`
     already uses), its links listed in each; merged per post (its reports join by key). The post's own address is
     never offered: removed from the links and shown in the text as `[this post's own address]`.
   - **Checks** (`track_things.salvage`, called by `validate.salvage`, so the worker runs them too): each value is
     `{value, quote}`; the quote must be in what the question showed; number/money come typed `{number, unit,
     currency, range_to}` and their digits (and range) must be a figure of their own quote (thousands groups,
     decimal comma or point, a K/M/B-like multiplier: `figures`), the unit (when given) and the currency must be shown
     by the quote; a link is an http(s) URL inside its own quote; an enum one of its values; text at most 120
     characters. A thing whose name field did not stand is dropped. Every drop is kept on the call (`dropped`, with
     its reason); the rest of the answer stays. No free-text number parsing. Idempotent.
   - **Joins** (never by vectors): at answer time a report joins a current thing of its kind sharing a key value
     (key fields and every link field, normalised); a practice only within its own post. In the jobs process
     (`refresh`) two things of a kind whose key text is the name of the same entity (current mentions, pins,
     redirects) join (`merged_by entity`). Two practices whose quotes name a shared entity get one `track_same`
     question (guide `track-same-v1`, planner `plan_same`, 30 waiting at most), joined on `same` (`merged_by haiku`).
     A join is a status (`merged`, `merged_into`), never a delete.
2. **`markx/track_brief.py`** (new) owns the brief, the issue, the quick look and the tables.
   - **"What changed"** deepens 0207's `digest` kind: a second guide `digest-v2` (`schemas.GUIDE_VARIANTS`, the same
     `DIGEST_SCHEMA`), planned by the digest planner itself (`tasks._plan_digests` = sub-topic digests + `track_brief.plan`).
     Its input is the period's rows [1]..[n] (current things with a report from a post of the period, "new" when first
     reported in it); 2-4 points about things and practices only, never authors or sources. Check
     (`validate._digest_rows`): cites only the question's rows, each point one line, every figure a point gives is in
     the rows it cites. A week is asked again only when its rows change; the week in progress at most every 12 h.
   - **Code writes the rest**: sections per kind (schema order, practices last) with header and count, the posts of
     the period that gave no row (`also`), the counts.
   - **Weekly issue** (Monday-Sunday, UTC): a kept page per track and week (`kept_pages`, page `track_brief`, key
     `<track>:<monday>`), built by the jobs process for closed weeks (12 back) in the "tracks" job
     (`jobs.Jobs._keep_track_briefs`; `_tracks_missing` also wakes for an issue due). A closed issue rebuilt with other
     things or points says `updated` (and keeps `first_built_at`).
   - **Quick look**: things found since the track's look (`mx_track_seen`, or a given time; never looked: this week),
     the newest brief's points that cite one of them (`as_of`, `stale`), posts joined since with no row, `nothing_new`
     and `last_issue`.
   - **Tables**: a kind's current things, newest first, typed filters from the fields (`<f>.min`, `<f>.max`,
     `<money>.currency`, `<enum>=a,b`, `<text>=words`, `<link>=any`).
3. **Stored state** — migration 0163: `mx_track_schemas`, `mx_track_things` (track, kind, key, fields, schema
   version, first_at, last_at, status, merged_into, merged_by), `mx_track_thing_reports` (call, n, thing, post, task,
   schema version, window, field_values with quotes), `mx_track_brief_asks` (what a brief question showed: its week
   and its rows' thing ids, as 0207's asks); `mx_tasks.subject_kind` gains `thing_thing`. Nothing deleted.
4. **API** (`tracks_api.py`): `GET/PUT /api/markx/tracks/{id}/schema`; `GET .../brief?week=<a day>` (the kept issue),
   `?since=seen|<ISO>` (the quick look; no parameter: since the look); `GET .../things?kind=&<filters>&limit&offset`.
5. **Worker** (`scripts/markx-worker`): `track_schema`, `track_things`, `track_same` in `DEFAULT_KINDS` (after
   `digest`), per call 1, 1, 5; no effort set (not measured). `digest-v2` rides the `digest` kind.
6. **Wiring**: `schemas.KINDS` (+ schemas), `validate.CHECKS`/`GUIDE_CHECKS`, `tasks.PLANNERS`, `tasks.record`,
   `consumers.CONSUMER` (feature `tracks`), `test_markx_spend.READERS` (the planner reads its version line).

## The switch

`backend/insight_core/markx/entity_bands.json` → `"tracks": {"briefs": false}` (`track_things.on`). Off: no planner
adds a task, the jobs process neither joins nor keeps an issue, the API answers `on: false` with empty shapes. Each
part ships ON only after it passes its bar below (new-tech-on-in-production); a part under its bar stays off (a
field kind under its bar is hidden, the row stays — not built yet: needs the measure first).

## What must be measured, and how

Bars (0245): values >= 97% right with a Wilson lower bound >= 90%; recall >= 85% for the first version; joins >= 97%;
"what changed" points supported by their rows >= 97%. Never one track: **one frozen held-out set across ALL the
server's tracks**.

1. **The set.** On the one read-only server copy (never cloned; deleted after), switch on, let the worker answer the
   schema for every track, then sample posts in each track (stratified by track and by length: short, one window,
   several windows), at least 30 posts a track, newest first excluded from any guide work. Freeze the post ids and
   the schema versions before any label; a later guide change is scored on a new set mined from older posts.
2. **Labels.** Two blind Haiku labellers (they never see the model's answer) read each post with its schema and list
   the facts it states per field; a referee settles splits. I review the flagged rows first; the owner sees only my
   flags.
3. **Measures.**
   - things right (a real thing of that kind, in the post) and values right, per field type (text, number, money,
     link, enum) — a type under the bar is hidden;
   - recall: labelled facts found / labelled facts, per track and overall (round 2 was 65%: the bar is 85%);
   - drops: every dropped value with its reason, labelled right or wrong drop (round 2's 3 drops were all false);
   - joins: every key, entity and `same` join in the set, labelled one-thing or not, each mechanism separately;
   - points: each digest-v2 point against its cited rows (supported / not), and against authors-or-sources (must be 0);
   - repeatability: the same set asked twice, typed values identical (round 2: 80%);
   - cost and time: calls, dollars and seconds a post and a week; the jobs process's peak RSS for the tracks job.
4. **Decide.** Each part at or above its bar ships on (the switch, and per part if needed); under it stays off with
   its numbers here.

## Tests

`insight_core.tests.test_track_briefer_0245` (13): the kinds, guides, planners and the switch (off by default:
nothing planned or built); figures; each type checked in its own quote; one salvage for three kinds of track
(idempotent, drops with reasons); schema answers checked and the practice kind added by code; digest-v2 cites rows and
their figures (digest-v1 unchanged); weeks and filters; the flow over three tracks (schema, things, typed values, the
tables' filters, 400s); windows and the post's own address, the owner's schema version, a new description proposes
again; key joins and practices joined only within a post; entity joins and the same-claim question; the brief, the
kept issue (counts, also, points mapped to rows, `updated` after a correction, the jobs path), the quick look since the
look. Updated: `test_markx_validate`, `test_markx_storage`, `test_markx_spend`, `test_markx_api` (tables),
`scripts/tests/test_markx_worker.py` (+2). Run: the modules above (`scripts/test-backend.sh ...`) and the worker suite.

## Not done

- Not measured; no real data read; the switch stays off.
- No frontend (the rail count, the issue strip, the cards and tables): 0245's UX is the spec.
- A field type under its bar is not yet hidden per type (needs the measure to say which).
- The owner's "wrong" tap on a fact (a label) is not built.
- Questions in words (0098) are later, after the tables.

## Frontend built (v10.28)

Built behind the same switch: every view reads `on` from the API and shows nothing while it is off (the track page
is then as before). Generic: no track, kind or field is named; every rule is about a type. Not measured on real data;
no real data read.

- **Where**: `frontend/src/components/tracks/` — `TrackBrief.tsx` (the quick look, "what changed", things as tables
  or cards, the weekly issue, the tables), `TrackSchemaEditor.tsx` (in the track sheet), `briefWords.ts` (days,
  weeks, names and facts, cite numbers, filter chips, sorting; pure), `TrackTopic.tsx` (three tabs `latest / issues /
  tables` when the switch is on and the track has a schema), `TrackSheet.tsx` (+ the editor);
  `services/tracks.ts` (`briefApi` and the shapes); the rail in `components/reader/ReaderNavRail.tsx`. Page doc:
  `design/docs/pages/reader.md` ("View topic, the briefer").
- **Quick look** (latest): `since Tue · N new`, "what changed" (at most 4 points, superscript numbers linking to the
  post each cited row came from, the title on hover), new things by kind (one line each: name, 2-3 facts, link-field
  hosts, ↗ to the post's original; `see all ›` opens the kind's table), "Also in the track", then the topic as
  before. It counts from the look *before* this visit (the open records a look; never looked: Monday of this week).
  `Nothing new since Tue · the issue of 9 Nov ›` when empty. Points older than a find or a post since (`stale`)
  leave the top and follow the sub-topics, `What changed · as of Tue` (0002).
- **Issues**: Monday-Sunday, opens on the last closed week; date strip `‹ 2 Nov 9 Nov 16 Nov ›`; `so far` for the
  open week; a quiet `updated` chip; a kind as a table at `sm` (640px) and up, bordered cards below; "Also in the
  track".
- **Tables**: kind chips, filter chips from the typed fields (number/money split at a round middle, money in its most
  common currency only; enum values OR-ed; link `has <field>`; text none, 0098 later), sent to the API's filters;
  headers sort (asc, desc, newest first again).
- **Schema editor** (the sheet's "Kinds and fields"): rename in place, remove (not the name field), add with a type
  (a unit, or enum values); the practice kind shown, never sent; Save is a PUT (a new version, re-read).
- **Rail**: `3 new things` before a topic track's count, `9+` cap, silent at 0.

**Backend changes the UI needed (minimal):** `track_brief.quick_look` answers `weeks` (the issue strip, Mondays newest
first; the off shape `[]`); `track_brief.new_count` (current things found since the last look; 0 when never opened,
not opened for 30 days, or off) and `GET /api/markx/tracks/counts` adds `things` per topic track **only while the
switch is on** (the off shape is unchanged). Tested in `test_track_briefer_0245` (the quick-look test).

**Tests**: `frontend/src/components/tracks/briefer.test.tsx` (12: three invented tracks of different kinds — garden
tools, board games, bread — the words, off shows nothing, the quick look, nothing new, stale points after the posts,
the issue and its strip, the tables' chips and sorting, the schema editor, the rail). `npx tsc --noEmit`, the whole
vitest suite (1011) and the backend modules `test_track_briefer_0245` + `test_markx_track_counts` pass.

**Not done**: a row opening "its thing" (every report, each fact's post): the ↗ opens the newest post; the "wrong"
tap on a fact; hiding a field type under its bar (needs the measure); checked on a phone in a real browser.
