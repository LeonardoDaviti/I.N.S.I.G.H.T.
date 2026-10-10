# Mark IX — Reading finish: post typography + reading-only app (§9)

Status: **approved** (2026-10-10). Built on the integration branch `mark-ix-reading-finish`.
Parent spec: `plan/INSIGHT_mark_ix_plan.md` §9. Design: `plan/INSIGHT_mark_ix_design.md`.

## Problem

The reader, post page and sources list now match the owner's ideology ("everything minimal, ideal for reading the text"). Three gaps remain:

1. **The post title wraps narrower than the body.** On `/posts/a2ef4538…`, "A new feature for my / blog, built using my voice" breaks after "my". The title uses about 55% of the reading column, so the block looks unbalanced.
2. **Article subheadings look like body text.** In the same post, "Codex voice mode" (an `<h4>` in the source) is the same size and weight as a paragraph. You can't skim the article's structure.
3. **The app still shows the analysis surfaces.** The top bar reads `feed / tracks / briefings / sources / ingestion`. Briefings, stories, the inbox and experts are still reachable. Ingestion is its own page. In the background, every saved post still goes through entity/event extraction, and the daily work still calls Gemini. §9 decided all of this goes behind `INSIGHT_ANALYSIS=off`; only the post page was done so far.

## Root causes (verified in code)

| # | Cause | Where |
|---|---|---|
| 1 | The global `h1, h2, h3, h4 { text-wrap: balance; }` rule balances the title into two equal short lines instead of filling the column. `balance` suits short UI headings, not a long article title. | `frontend/src/index.css:172`; post H1 at `frontend/src/pages/PostDetailPage.tsx:1164` |
| 2 | `MarkdownRenderer` maps only `h1`–`h3` to styled elements. `h4`–`h6` fall through to Tailwind's preflight reset, which makes them plain text. | `frontend/src/components/ui/MarkdownRenderer.tsx:95-108` |
| 3a | The nav and the ⌘K list hard-code the analysis destinations: `NAV_ITEMS` has `briefings` and `ingestion`, and `DESTINATIONS` has daily/topic/vertical briefing, stories and inbox. | `frontend/src/components/layout/navigation.ts` |
| 3b | The routes `/briefing*`, `/stories`, `/inbox` and `/experts` are always mounted, and `/tracks` renders `ExpertsPage`. | `frontend/src/App.tsx:47-58` |
| 3c | Ingestion is a separate page, `IngestionControl.tsx` (about 1,700 lines), at `/ingestion` and `/ingestion/:tab`. | `frontend/src/App.tsx:51-52` |
| 3d | Every save batch runs the `Enricher` (entity and event memory). | `backend/insight_core/ingestion/__init__.py:72` |
| 3e | Daily work runs the experts (Gemini), the daily briefing and the optional topic briefing. | `backend/insight_core/scripts/run_scheduler.py:174-230` |
| 3f | `GeminiProcessor()` is created in 5 non-test modules. | `grep -rn 'GeminiProcessor()' backend/insight_core` |

## Decisions already made (do not re-open)

- §9: hide, don't delete. One switch, **`INSIGHT_ANALYSIS`**, default **off**. No data is deleted.
- The app has three places: **feed / sources / post**. Ingestion becomes a **tab under sources**. **Tracks stay.**
- The post page already shows only content plus ↗ ☆ ⧉. The frontend flag `ANALYSIS_ENABLED` in `frontend/src/lib/features.ts` already exists.

## Requirements

### R1 — The post title uses the full column
- The post H1 fills the reading column (~42rem) and only wraps when it has to. Use `text-wrap: pretty` (no orphans, no forced balancing) on the post H1 and on article headings.
- Leave `balance` on short UI headings (page titles, section labels). Narrow the global rule to UI chrome, or override it for `.prose` and the post H1. Don't remove it everywhere.
- Long and non-Latin titles still wrap, with no horizontal scroll at 390px (break-ui worst-case fixture).

### R2 — Article headings are visibly headings
- `MarkdownRenderer` styles `h4`, `h5` and `h6` on the same scale as `h1`–`h3`:
  - `h4` ≈ 1.0em semibold, tight tracking, top margin about 1.2em;
  - `h5` and `h6` ≈ 0.95em semibold, with `h6` muted.
- All with `dir="auto"` and `text-wrap: pretty`.
- No heading level may render the same as body text.
- Monochrome only. Hierarchy comes from size, weight and spacing, never colour.

### R3 — Reading-only app when `INSIGHT_ANALYSIS=off` (§9, the rest of it)

**Frontend**
- **Top bar:** `feed / sources` (see Decision 2).
  - `briefings` and `ingestion` are not shown.
  - With the flag on, the current five words come back.
- **⌘K quick switcher:** no briefing, stories, inbox or experts entries when the flag is off. "Ingestion" points to the new sources tab.
- **Routes when off:**
  - `/briefing*`, `/stories`, `/inbox` and `/experts` redirect to `/` (replace, so no history entry).
  - `/ingestion` and `/ingestion/:tab` redirect to `/settings/sources?tab=ingestion`, carrying `:tab` across.
- **`/tracks` (list):** removed when off; redirects to `/` (Decision 2).
- **`/tracks/:id`:** the track's reading view only. No track briefing panel and no milestones rail.
- **Sources page:** gains a third tab, `ingestion` (`?tab=ingestion`), holding the run report, Run due sources, the scheduler interval/status and job history.
  - Move the useful parts of `IngestionControl` here.
  - Drop "Write a briefing" and the "Source registry" JSON↔DB buttons when off.
  - "Fetch one source" is dropped (Decision 1).
- **Reader:** no "Summary", "Topics", "Story" or expert affordances anywhere in the feed or track views when off.
- **How the flag is set:** `VITE_INSIGHT_ANALYSIS` at build time.
  - The frontend also reads a runtime value from `GET /api/config` → `{ analysis_enabled }`, so the backend and frontend can't disagree. If the build flag and runtime value differ, the runtime value wins.
  - The preview build and the docker-compose frontend build arg default to off.

**Backend**
- **`INSIGHT_ANALYSIS` env var:** default `off`. Read once into a settings object. Expose it at `GET /api/config`.
- **When off:**
  - **Enrichment:** `default_runner()` wires a no-op enricher, so saving posts never touches entity or event memory. Fetch runs get faster; the run report shows enrichment as "skipped (analysis off)".
  - **Daily work:** it still prunes job_runs, refreshes cadence and syncs sources.json. It skips experts, the daily briefing and the topic briefing, and records them as skipped in the scheduler cycle job.
  - **No Gemini client:** no `GeminiProcessor` is constructed, at startup or on any path the reading app uses. Calls to analysis endpoints (briefings, experts run, stories, inbox rebuild, memory and event rebuilds, topics generation) return **409** `{"error": "analysis_disabled"}`. Read-only GETs of stored briefings may keep working, for when the flag comes back on.
- **Data:** no migration, no deletes.

### R4 — Docs
- Update `README.md`, `QUICKSTART.md` and `FRONTEND.md` to describe the three places and the flag.
- In `plan/INSIGHT_mark_ix_plan.md` §9, add an "As built" note with the commit hashes.

## Out of scope
- Deleting analysis code or data (the analysis-version spec decides that).
- Feed search (deferred).
- Any change to how ingestion fetches.

## Test plan (pre-agreed seams)

| Seam | Tests |
|---|---|
| `index.css` / post H1 | Component test: the post H1 has the `pretty` wrap class, not `balance`. Playwright screenshots at 1400 and 390, dark and light: for the "A new feature for my blog…" post, the title's first line spans ≥ 85% of the column width. |
| `MarkdownRenderer` | Unit: `#### Codex voice mode` renders an `h4` with the heading classes. `h4`/`h5`/`h6` each have a computed font-weight ≥ 600. Snapshot of the heading scale. |
| `navigation.ts` | Unit: `NAV_ITEMS` for analysis off is `['feed','sources']`, and for on, the five words. `DESTINATIONS` contains no briefing/stories/inbox entries when off. `activeNavKey('/settings/sources?tab=ingestion') === 'sources'`. |
| Routes | Router tests: each hidden route redirects (off) or renders (on). `/ingestion/jobs` goes to `/settings/sources?tab=ingestion&sub=jobs`. |
| Sources `ingestion` tab | Component tests: run report renders, Run due sources calls the API, scheduler status shows "not running" honestly, and no briefing/registry controls when off. |
| `/api/config` + flag | Backend unit: settings default off and parse on/off/true/false. Route test: `analysis_enabled` is false by default. |
| Runner / enrichment | Runner test with flag off: the save batch runs, the enricher is a no-op, and the report says skipped. With flag on, the current behaviour is unchanged (existing tests). |
| Scheduler | `daily_work` with flag off: cadence/sync/prune run; experts and briefings don't run and are recorded as skipped. No `GeminiProcessor` is constructed (patch the constructor and assert it's never called). |
| Analysis endpoints | Route tests: each mutating analysis endpoint returns 409 `analysis_disabled` when off. |

Commands: `./run-tests.sh` (insight_test); `cd frontend && npm run typecheck && npm test && npm run build`; eslint on touched files.

## Slices (each can ship alone, in this order)

1. **S1 — Typography** (R1 and R2). Frontend only; about an hour. No dependency on the flag.
2. **S2 — Backend flag** (backend half of R3: settings, `/api/config`, no-op enricher, scheduler skip, 409s, no Gemini construction). Backend only.
3. **S3 — Frontend reading-only shell** (frontend half of R3: nav, switcher, redirects, tracks list without experts, track page without briefing/milestones, runtime flag from `/api/config`). Depends on S2's `/api/config`, or falls back to the build flag.
4. **S4 — Ingestion tab under sources** (R3 sources part). Moves the useful parts of `IngestionControl` into `?tab=ingestion`; `/ingestion` redirects. Depends on S3.
5. **S5 — Docs and as-built notes** (R4).

S1 and S2 can run in parallel (disjoint files). S3 and S4 touch `App.tsx`, `navigation.ts` and `SourcesConfig.tsx`, so run them in sequence.

## Acceptance (owner-visible)

- Opening a post: the title spans the column; "Codex voice mode" reads as a subheading.
- The top bar reads `feed / sources`. ⌘K shows no briefings, stories, inbox or experts.
- Typing `/briefing` or `/stories` in the address bar lands on the feed.
- Sources has tabs `sources / connections / ingestion`. The run report and Run due sources live there.
- A Fetch now on any source finishes without entity/event work, and its report says enrichment was skipped.
- The backend logs show no Gemini client being created during a whole scheduler cycle.
- Setting `INSIGHT_ANALYSIS=on` (backend env + build arg) brings every hidden surface back unchanged.

## Decisions (owner, 2026-10-10)

1. **"Fetch one source" is dropped** from the ingestion tab. Every source row and its detail sheet already have Fetch now.
2. **The separate `/tracks` page is dropped.** Tracks live in the reader rail and in the sources list groups (fetch, rename, main digest and delete are already in the group's ⋯ menu). With the flag off, the top bar is **`feed / sources`**. `/tracks` (the list) redirects to `/`, and `/tracks/:id` keeps working as the track's reading view. The ⌘K list gets one "Tracks…" entry per track, pointing to `/tracks/:id`.
3. **Analysis behaviour when the flag is on is not decided now.** With the flag off nothing analysis-related is visible or running. With it on, today's behaviour stays exactly as it is, and the next version decides the rest.
