# 0160 — Track suggestions: INSIGHT proposes tracks from what your sources keep returning to, with a preview

Status: **spec, waits for 0161 E7** (2026-11-10). Fusion stage 5 (Subjects). Realises 0101 part 3. Roadmap:
`plan/INSIGHT_fusion_plan.md`.

Read first: 0145 (tracks as topics: description, excludes, the judge, sub-topics), 0147 (track recall), 0148 (the
scout), 0101 ("Discover should suggest tracks, not only sources": the owner, 2026-10-28).

**Constraints:** nothing is created without the owner's tap; keep everything (a dismissed suggestion is kept, never
shown again); no real names in committed files; realdata-check once at release.

## Why
- Today a track finds its posts and its sources; nothing finds a track. The owner must think of it and write its
  description. For the owner this is a small gap (the four tracks came from the owner's own head). **For a new
  user it is the empty page after adding sources.**
- Signals, measured (rough: private `plan/research/fusion/out/F8f`, `F3a`):
  - **what the sources keep writing about:** of 668 topics named over the archive's posts, 91% belonged to one
    post; **59 recurred cleanly** across posts. Those are the candidates;
  - **what the owner opens:** 153 opened posts. Too few; not used;
  - topics did not bridge spheres (2 real of 7 found): a suggestion stays inside one sphere.
- The risk is noise: a suggestion that names one story ("the <product> launch") or repeats an existing track
  teaches the user to ignore the list.

## What it does
### 1. A topic per post (at read time)
- The reading gains `topic`: a short phrase for the lasting subject the post belongs to (not its event): "cheap
  local inference rigs", not "<vendor> released <card>". Null when it has none.

### 2. Candidates (by code, weekly)
- Topics are grouped by their vectors (the worker's embedder, as names are embedded) and identity's name folding;
  a group is a candidate when it has posts from **3+ sources over 2+ weeks**, is not one event (its posts span
  more than one event: 0153; before events, more than one Mark X story), and is not already a track (its vector
  against each track's profile).

### 3. A suggestion (one `suggest` call per candidate, at most 10 a week)
- From 10 of the group's posts: a name, a description and excludes in 0145's form, and one line why it is a
  lasting subject.
- **The preview, by the existing machinery:** the track judge (0145) runs over the last 30 days' prefiltered posts
  exactly as for a real track, into a scratch row. The suggestion shows: "23 posts in 30 days from 9 sources", 5
  of them, and the sub-topics it would have.
- Fewer than 8 posts in 30 days: not shown.

### 4. Shown
- On the Tracks page, "Suggested" (at most 5, ranked by posts × sources); and in Discover as a line.
- **Create** (opens the track sheet filled in; the owner edits before saving), **Not this** (kept, never again),
  **Merge into <track>** (adds its description's words to that track's examples).

### 5. For a new user
- The first worker run after sources are added runs this once at lower bars (2+ sources, 1+ week), so the first
  hour ends with tracks to choose.

## Measure
E7 (0161): 15 suggestions from the owner's archive, each marked by the owner: would create, duplicate of a track, a
single story, not a subject.

## What the results should be
- At least 8 of 15 "would create" (or edited and created); at most 2 single stories; at most 2 duplicates.
- A new sphere (Starting Point's): 3+ usable suggestions after its first run.
- Below those, the feature is not built for the owner and is kept for onboarding only if the new-sphere number
  holds.

## Done when
- Tests: `topic` in the reading's schema; grouping; the three candidate rules; the preview through 0145's judge into
  scratch; never twice after "Not this"; the lower bars only on a first run; the fake-claude test.
- Frontend builds; vitest; design docs. E7's rows (private).

## Measured (E7, 2026-11-20; private: `plan/research/fusion/measure/x1120/E7/`)
3,000 of the server's last 14 days' posts; 15 suggestions; two blind checkers (no owner labels, 2026-11-14 rule), settled by reading.
- **Pass:** 11 of 15 a reader would create (bar 8), 2 single stories (bar <= 2), 0 duplicates of the four tracks (14 of 56 candidates had already been dropped as duplicates).
- **New spheres (local instance): pass.** Health 5 of 5, climate and energy 4 of 5 (bar 3 of 5).
- **Fix:** the "spans more than one event" gate leaks (3 single-story suggestions over both runs: an IPO, a leadership affair, one bill). The "2+ weeks" test must ignore a single old post.
- **Preview precision 71% (61-79)** on 100 sampled "in" posts: a suggested track's posts wait in Discover; never auto-join.
