# 0145 — Tracks as topics: a track in your own words, judged post by post from active and passive sources, organised into sub-topics, self-improving

Status: **spec** (2026-11-09). Stealth (Mark X: vectors and the worker). Not news-only (the owner: "not only focus
on news"). Builds on the folders/tracks feature (a track today is a folder of sources), 0086 (the worker, tasks,
guides), the BGE-M3 vectors (`mx_embeddings`), 0101 / 0138 (Discover), the source-adding rule.

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; the folders code (`/api/folders`, its repo and service,
the reader's track view); `markx/tasks.py`, `markx/schemas.py`, `markx/validate.py`, `scripts/markx-worker` (how a
task kind and its guide are added: `translate` is the newest small example); `mx_embeddings`.

**The owner (2026-11-09):** "I want to create Tracks, which are self-created topics … custom agents running over
threads … 1. Cool Projects (instead of GitHub Trending only, anything that covers cool project ideology) 2. Cool 3D
Projects — best ideas what to print and why, organized into sub-topics (as I scroll Instagram I face too many such
projects … that's how I discovered <a modular wall-storage system>) 3. Local Setups (as cheap as performant as
possible). Active sources are always monitored for posts that relate to the track; passive sources are random
sources whose posts are checked on read or in some other work; if a post corresponds to a track it goes into the
track's Discover section, labelled for that track. Automating track addition."

**Decided (the owner, 2026-11-09):**
1. A passive match joins the track **by itself only when the track's measured precision is ≥ 90%**; until then it
   waits in the track's Discover. Discover ranks suggestions **by precision** (the judge's confidence calibrated on
   the owner's labels).
2. Sub-topics: **INSIGHT proposes** them; the owner renames, merges, splits.
3. Active sources' posts are **judged too** (not every post goes in).
4. Stealth, now.

**Constraints:** no real names in committed files; fix the class; keep everything (a track's rejected posts are kept
with their verdict); never touch the live DB or the server except GETs; unit tests + 3–5 real checks; realdata-check
runs once at release (not by the agent).

## What it does
### 1. A track is a topic
- A track gets: **`description`** (what belongs, the owner's words), optional **`excludes`** (what doesn't), and
  **examples** (posts the owner marks ✓ or ✗ for it). Its **active sources** are today's folder sources. A track
  with no description stays a plain folder (today's behaviour, unchanged).
- Create / edit on the track page (a sheet: name, description, excludes, active sources, examples so far).

### 2. Who is judged, when
- **Active sources:** every new post, at the next worker run (planned like `read`, newest first).
- **Passive (every other source):** every post the prefilter passes, at any worker run, newest first; and **once
  over all history** when a track is created or its description changes (resumable, its own page size).
- A post may belong to several tracks.

### 3. The judge, cheapest first (the Mark X ladder)
1. **Prefilter (no model call):** cosine of the post's BGE-M3 vector against the track's **profile** — the embedded
   description (embedded by the worker's embedder as a task, `embed` kind) and the mean of its ✓ examples, minus the
   ✗ examples' pull. A post passes above a per-track threshold set so that ≥ 98% of the owner's ✓ examples pass
   (default 0.55 until 5 ✓ exist). Logged: passed / total per run.
2. **`track` task** (guide `track-v1`, Haiku, 10 posts a call): per post `{in: bool, confidence: 0–1, subtopic:
   string|null, why: one line}`; `why` says what it is and why it's worth it in the track's terms (for a 3D track:
   what to print and why). Validated like other kinds; refusals halve as the worker does today.
3. **The owner's labels:** ✓ / ✗ on any track item or Discover suggestion; they become examples (profile and the
   guide's few-shot: the 4 newest ✓ and 2 ✗, short), so the track sharpens itself.

### 4. Where a judged post goes
- **Active source, `in`:** into the track.
- **Passive source, `in`:** into the track's **Discover** section, ranked by calibrated precision (the share of
  the owner's labels that were ✓ at that confidence band, Wilson lower bound; until 10 labels, by confidence).
- **Auto-join:** when the track's measured precision on passive `in`s (labels, ≥ 20) is ≥ 90% (Wilson lower bound
  ≥ 0.85), passive `in`s at or above the band that achieves it join the track by themselves, marked "joined by
  INSIGHT" with ✓ / ✗; below it they stay in Discover. The page shows the precision and the bar.
- **`out`:** kept with its verdict (never shown; counted).

### 5. Sub-topics (INSIGHT proposes)
- After 15+ items, and weekly, a `subtopics` task (guide `subtopics-v1`, one call per track) proposes 3–8
  sub-topics from the items' `subtopic` strings and headlines, each with a one-line definition; items are assigned
  by their judge `subtopic`, re-mapped to the proposal. The owner renames, merges, splits, or locks a sub-topic; a
  locked set is kept and the judge is given it.
- The track page reads as sections by sub-topic (newest first within), with a "Discover" section at the end.

### 6. The track finds its own sources
- A passive source with **3+ accepted items in 30 days** for a track is suggested on the track page: "<source>:
  N of your <track> in 30 days — make it active?" (one tap; no new source is added without the feed finder).
- Discover (the main one) gets a line on such sources.

### 7. Cost guard
- Per run, at most `TRACK_TASKS_PER_RUN` (default 300) track tasks across tracks; the history pass shares it.
- Measured cost and items per track per day on the track page's footer.

## Measure (3–5 real checks)
1. On a local server copy, with three tracks described as the owner's (project ideas; 3D printing ideas; cheap local
   AI setups): the prefilter's pass rate over 30 days of posts; 40 judged posts per track labelled by the agent
   from their text (private rows): precision of `in`, and recall on posts found by keyword search that should be in.
2. The history pass's planned task count and cost per track.
3. After deploy: the owner's first labels; precision per track after 20.

## Done when
- Tests: a track without a description stays a folder; the profile and threshold; prefilter pass; the `track`
  schema, validation, refusals; routing (active → track, passive → Discover); calibrated ranking; auto-join only at
  ≥ 90% with ≥ 20 labels (and back off when it drops); sub-topic proposal, rename/merge/lock; source suggestions at
  3+ in 30 days; the per-run cap; labels as examples.
- Worker: `track` and `subtopics` in `DEFAULT_KINDS` and `PER_CALL` (`track=10,subtopics=1`); guides in the guide
  store; a fake-claude test.
- Migration; frontend builds; vitest passes; design docs claim the track sheet, sections, Discover, labels.
