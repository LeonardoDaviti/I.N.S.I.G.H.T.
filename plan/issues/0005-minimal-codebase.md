# 0005 — Minimal codebase: keep what reading uses, retire the rest

Status: **built** 2026-10-12, not yet deployed (migration 0027 waits for the owner's go) · Drafted 2026-10-10 from the whole-codebase audit (owner request).
Renumbered from 0003 on 2026-10-11 (0003 is the source-name issue folded into the Design Studio spec as S7).

**Owner decision, 2026-10-11:** retire analysis **completely** and remove it; better analysis comes back later as new work. No exceptions (milestones and the track briefing go too). Slices 4–6 are confirmed; nothing is built until the owner says go.

## Outcome (2026-10-12)

- All 11 slices are built on `main`, one commit per slice (slices 1 and 11 in a backend and a frontend half), plus the code-review fixes. The tag `mark-ix-analysis-archive` holds the analysis code.
- Tracked lines 111,293 → 64,809 (backend 52,331 → 24,809, frontend 39,678 → 27,476, docs 18,974 → 12,236). Short of the 55–60k target: the Design Studio (~7k) and `plan/` (~12k) were kept.
- Backend image 464 MB → 427 MB (uncompressed). The preview database copy went 293 MB → 70 MB with every post kept.
- Routes 129 → 51. Changed paths for outside callers are in `BACKEND.md`, "HTTP API".
- Migration 0027 drops 30 analysis tables (the spec said 31; the migrations hold 30), 9 `posts` columns and `folders.use_global_milestone_lanes`.

## Problem Statement

INSIGHT is meant to be a lightweight, single-user reader, but the repository has grown to about 98k tracked lines. About half of it is weight the owner pays for and never uses:

- **Dead code:**
  - output writers from Mark II/III;
  - a test folder the runner can't load;
  - vendored fake copies of `fastapi`, `pydantic`, `psycopg`, `dotenv` and `uvicorn`, which cause false failures outside Docker;
  - modules nothing imports;
  - eleven npm packages nothing imports;
  - four database tables no code touches.
- **Stale docs.** Root and backend documents describe the Mark II–VI layout (connectors, engines, `insight_bridge`), and several plans are duplicated or superseded. A reader of the repo can't tell which document is true.
- **Dormant analysis.** Since Mark IX the app runs reading-only (`INSIGHT_ANALYSIS=off`). Yet these all stay loaded, built, tested and partly executed:
  - the analysis clusters: briefings, Gemini, topics, entity/event memory, evidence, stories, inbox, milestones, experts, track briefings;
  - post summary/chat/highlights and the YouTube roadmap/chat.

  In numbers: about 15.5k backend lines and 3.5k test lines, about 8.5k frontend lines and 1.2k test lines, and 31 database tables. Saving a post still computes "memory pivot" columns nothing reads. About 37 analysis routes are not gated and still serve stale tables.
- **Shallow layers:**
  - Every request passes through a 136-method bridge that mostly forwards calls and turns exceptions into `{"success": false}`. The routes then catch the same exceptions again.
  - Database connections are opened by hand in 166 places.
  - Posts can be listed four ways and marked read three ways.
  - Sources have duplicate add, delete, enable and list paths.
  - The frontend API client is 2,922 lines with 72 copy-pasted error handlers and two competing access styles.
  - Small helpers (`_iso`, `_json_default`, `strip_html`, date and duration formatting) exist in several copies.

The owner feels this as slow change, bugs that hide, a heavier image and database, and a codebase too big to steer slice by slice (retro F2, F3, F6).

## Solution

Shrink INSIGHT to what the reading product uses. It should land at about 55–60k lines, with the reading behaviour unchanged.

1. **Delete what is dead:** unused code, packages, tables, tests and stale docs.
2. **Retire the analysis version.**
   - Tag the last commit that still contains it, so nothing is lost.
   - Remove every analysis-only module, route, screen, test, table and setting from `main`, including the `INSIGHT_ANALYSIS` switch.
   - Analysis comes back later (Mark X) as new slices built on the reading core, each one earning its place with a reading test. It does not come back by restoring this code wholesale.
3. **Deepen what stays:**
   - routes call services directly, with one error handler;
   - one database connection module;
   - one way to list posts, mark them read and change a source;
   - one frontend request helper;
   - one copy of each helper.

From the owner's side, after this change:

- the feed, post pages, tracks, Sources (including Connections and the Ingestion tab) and adaptive scheduled ingestion look and behave exactly as they do today with analysis off;
- the image, the database and the repository are smaller.

## User Stories

1. As the owner, I want every screen I can reach today with analysis off to look and behave the same after the cleanup, so that the cleanup costs me nothing as a reader.
2. As the owner, I want the feed (all, by source, by track, unread counts, infinite scroll) to keep working, so that my daily reading is untouched.
3. As the owner, I want post pages (typography, media, YouTube chapters and transcript, open original, favourite, read state) to keep working, so that reading one post is untouched.
4. As the owner, I want tracks (folders) to keep showing their posts, so that grouping my sources still works.
5. As the owner, I want Sources (add, edit, enable/disable, delete, health, counts) to keep working, so that I can still curate my inputs.
6. As the owner, I want Connections (Telegram login, Substack cookie, other secrets) to keep working, so that paid and private sources keep fetching.
7. As the owner, I want the Ingestion tab (run now, scheduler, job list, run report) to keep working, so that I can still see and steer fetching.
8. As the owner, I want archive backfill and the ingestion log viewer moved into the Ingestion tab before the old ingestion page is deleted, so that I don't lose those two reading-side tools.
9. As the owner, I want scheduled ingestion with adaptive cadence and the run-level lock to behave exactly as before, so that fetching stays polite to rate limits.
10. As the owner, I want a git tag on the last commit with the analysis code, so that I can read or restore any of it when Mark X begins.
11. As the owner, I want the tag name and what it holds written down in the repo, so that I can find it in a year without searching git history.
12. As the owner, I want the analysis database tables dropped by a normal numbered migration, so that the server's database shrinks through the usual deploy path.
13. As the owner, I want a database backup step written into the deploy notes for that migration, so that dropping 35 tables is reversible.
14. As the owner, I want the four tables no code uses (clusters, cluster posts, meta posts, meta post sources) dropped, so that the schema only holds what the code reads.
15. As the owner, I want post columns that only analysis wrote (memory pivots and similar) dropped, and no longer computed on save, so that ingestion does less work per post.
16. As the owner, I want the columns reading still relies on (content hash, normalised and canonical URL, URL host, language) kept and still computed, so that deduplication keeps working.
17. As the owner, I want `google-genai` removed from the backend image once Gemini is retired, so that the image and memory use shrink further.
18. As the owner, I want unused npm packages removed, so that installs and the frontend build are smaller and faster.
19. As the owner, I want dev-only fixtures kept out of the production bundle, so that the reader downloads less.
20. As the owner, I want the Gemini entry removed from Connections, so that the UI never asks for a key nothing uses.
21. As the owner, I want the `INSIGHT_ANALYSIS` switch gone from settings, compose, `.env.example` and docs, so that there is one mode and no hidden second app.
22. As the owner, I want any leftover `INSIGHT_ANALYSIS` in my server `.env` to be ignored harmlessly, so that deploying doesn't need a config edit.
23. As the owner, I want old bookmarks to analysis routes (briefing, stories, inbox, experts, vertical briefing, the tracks list) to land on the feed, so that nothing shows a broken page.
24. As the owner, I want analysis API routes gone, not gated, so that no endpoint serves stale analysis data.
25. As the owner, I want system status to report only reading-side facts (sources, posts, ingestion, database), so that the status line stays true.
26. As the owner, I want the scheduler settings to lose the "generate daily briefing" and "generate topic briefing" options, so that the settings only offer what happens.
27. As the owner, I want stale root docs deleted (technical documentation, posts-complete changelog, frontend integration summary, testing checklist), so that every document in the root is current.
28. As the owner, I want stale backend docs deleted or rewritten (Mark II status, the unified structure, the connector guide), so that the connector guide describes source kinds as they really are.
29. As the owner, I want the two analysis feature docs (move post to outlier, topic rename) and the topics API doc removed with the code they describe, so that docs and code retire together.
30. As the owner, I want small overlapping docs merged (Docker networking into deployment, futures into local issues), so that each topic has one home.
31. As the owner, I want superseded and duplicate plans deleted, and finished analysis plans moved to an archive folder, so that `plan/` shows what is live.
32. As the owner, I want local issues 0001 (entity pages) and 0002 (track briefing) to point at the analysis tag, so that Mark X knows where the old milestones and briefing code lives.
33. As a maintainer, I want the vendored fake libraries deleted, so that tests run against the real packages and never pass or fail by accident.
34. As a maintainer, I want the unloadable old-tests folder deleted, so that the suite holds only tests that run.
35. As a maintainer, I want modules with no importers deleted (output writers, config manager, seed sources, post utilities, export scripts, connector logger), so that every module in the tree is used.
36. As a maintainer, I want dead functions in the bridge, posts repository, Gemini processor and services deleted, so that reading code is not padded with unreachable paths.
37. As a maintainer, I want routes to call services directly, so that a request goes through one layer, not two.
38. As a maintainer, I want one exception handler that turns service errors into a safe JSON error (no connection strings, no stack traces), so that error handling is consistent and written once.
39. As a maintainer, I want one module that builds the services and hands them to routes, so that wiring lives in one place and tests can swap it.
40. As a maintainer, I want one database connection module (pool, timeouts, transaction scope), so that connection behaviour can be changed in one place and the API/ingestion merge can share a pool.
41. As a maintainer, I want every repository to get connections from that module, so that no file opens a raw connection.
42. As a maintainer, I want one post-listing query with a filter (scope, source, track, date, cursor, read state), so that the feed, source and track views can't drift apart.
43. As a maintainer, I want one read-state endpoint, so that marking read has one behaviour.
44. As a maintainer, I want one way each to add, edit, enable/disable, delete and list sources, so that source changes have one path and one test.
45. As a maintainer, I want the hard-coded "Mark VI" version and the legacy job labels removed, so that the code doesn't lie about its age.
46. As a maintainer, I want one copy each of the ISO time, JSON default, JSON-safe and HTML-strip helpers, so that a fix lands everywhere at once.
47. As a maintainer, I want lazy Gemini import machinery removed with Gemini, so that importing processors doesn't pull in a 2,000-line module.
48. As a maintainer, I want the reading half of the YouTube service and of the post-detail service kept, and their analysis halves removed, so that each service has one job.
49. As a frontend maintainer, I want one request helper that handles the base URL, JSON, errors and messages, so that 72 hand-written catch blocks become one.
50. As a frontend maintainer, I want one way to reach the API (the `useApi()` hook with an injectable fake), so that every screen is testable the same way.
51. As a frontend maintainer, I want the separate track API client folded into the main client, so that there's one fetch path.
52. As a frontend maintainer, I want the API client to hold only methods some screen calls, with shared response types, so that it is about 900 lines instead of 2,922.
53. As a frontend maintainer, I want the test fake API to shrink in step with the client, so that the fake and the real client never drift.
54. As a frontend maintainer, I want the analysis pages, panels, inspector, analysis helpers, fixtures and tests deleted, so that the bundle and the test suite only cover reading.
55. As a frontend maintainer, I want the post page's analysis state, handlers and blocks removed, so that the post page is a reading page of roughly 1,000 lines.
56. As a frontend maintainer, I want the `useAnalysisEnabled` hook and the analysis feature flag removed, so that no component branches on a mode that no longer exists.
57. As a frontend maintainer, I want one date-format module and one duration formatter, so that dates and times read the same everywhere.
58. As a frontend maintainer, I want duplicated small helpers (`asArray`, editable/dialog checks, `looksLikeUrl`, source naming) collapsed, so that each lives once.
59. As a frontend maintainer, I want unused UI primitives, exports, types and CSS classes removed, so that the design system lists only what is used.
60. As a frontend maintainer, I want the scheduler clock logic to live once in the Ingestion tab, so that there's one scheduler view.
61. As an agent implementing a slice, I want each slice to end with the backend suite, the frontend tests and the frontend build green, so that I know the slice didn't break reading.
62. As an agent implementing a slice, I want each slice to be one commit (or one merge) that the owner can review alone, so that the owner steers every slice (principle 7).
63. As an agent implementing a slice, I want a before/after line count and image size in each slice's commit message, so that the owner sees the budget move (principle 4).
64. As the owner, I want nothing deployed or migrated on the server without my go, so that the retirement migration runs when I choose.

## Implementation Decisions

**The rule for what stays.** Anything reachable with analysis off stays. Anything reachable only with analysis on is retired. There are no per-feature exceptions. That includes milestones, the track briefing panel and post notes/chat, even though the owner likes milestones. Issue 0001 rebuilds milestones in Mark X from the tag.

**Order of slices.** Each slice is independently shippable, keeps reading green, and is one reviewable commit.

1. **Dead weight.**
   - Delete:
     - the vendored fake libraries and their shim tests;
     - the old-tests folder and the empty tests README;
     - the output package;
     - modules with no importers;
     - dead functions;
     - the connector logger;
     - unused npm packages;
     - unused UI primitives, exports, types and CSS.
   - Add a migration that drops the four unused cluster/meta tables.
   - No behaviour change.
2. **Docs.**
   - Delete the stale documents.
   - Rewrite the connector guide around source kinds.
   - Merge Docker networking into deployment and futures into local issues.
   - Delete the duplicate and superseded plans; move finished analysis plans into an archive folder under `plan/`.
   - Point issues 0001 and 0002 at the analysis tag.
3. **Port before cut.** Move archive backfill and the ingestion log viewer into the Ingestion tab under Sources, so the old ingestion page holds nothing reading needs.
4. **Retire analysis, backend.**
   - Create and document the tag (proposed name: `mark-ix-analysis-archive`).
   - Remove:
     - the clusters: briefings, Gemini, topics, entity/event memory, evidence, stories, inbox and analyst actions, milestones, experts;
     - their routes, bridge methods, scripts and tests;
     - the analysis halves of the YouTube and post-detail services;
     - the Gemini connection kind, the analysis-only settings and the `INSIGHT_ANALYSIS` switch;
     - the briefing options in the scheduler config;
     - the analysis entries in system status.
   - Saving a post stops computing the memory pivot fields. The enrichment step in the ingestion core collapses to nothing. If the ingestion core keeps an enrichment slot, it has one adapter, which is a hypothetical seam, so remove the slot.
   - Remove `google-genai` from the backend requirements.
5. **Retire analysis, frontend.**
   - Remove the analysis pages, panels, inspector, analysis helpers, fixtures and tests.
   - Remove the post page's analysis state and blocks.
   - Remove the feature flag and its hook.
   - Old analysis paths redirect to the feed.
6. **Retire analysis, schema.**
   - One numbered migration drops the 31 analysis tables and the analysis-only post columns.
   - The deploy notes gain a "back up the database first" step for it.
   - The migration runs on the server only on the owner's go.
7. **Deepen the backend request path.**
   - Delete the bridge.
   - Routes call services from one service registry module.
   - A single FastAPI exception handler maps service errors to a safe JSON error. It never leaks connection strings; prior art is the existing redaction in feed route tests.
   - Job tracking errors are logged, not silently swallowed.
8. **Connection seam.**
   - One database module owns a small connection pool, statement timeouts and a transaction context.
   - Every repository receives connections from it.
   - This is the precondition for the API/ingestion merge research.
9. **One reading query.**
   - The reader repository exposes one post-listing call that takes a filter (scope, source, track, date, cursor, read state).
   - The feed, posts-by-source, posts-by-date and track-posts routes collapse onto it.
   - One read-state endpoint.
   - Sources get one route each for add, edit, enable/disable, delete and list (with counts and settings).
   - Remove the hard-coded "Mark VI" version and the legacy job labels.
10. **One frontend request helper.**
    - The API client is rebuilt around a single request helper.
    - The track client folds in.
    - All screens use `useApi()`.
    - Response types are shared.
    - Dev fixtures load through dynamic import under the dev flag only.
11. **Helpers.** Collapse duplicated backend and frontend helpers into one module each (time, JSON-safe, HTML strip, dates, durations, source naming, keyboard checks).

**Interfaces that stay fixed:**
- The ingestion entry point, `run_ingestion(FetchRequest) -> RunReport`, and the source-kind interface stay as they are. They are already deep.
- The scheduler entry point stays as it is.
- HTTP paths the reading frontend calls stay stable until slices 9–10. Slices 9–10 change both sides of the HTTP interface in the same commit.

**Schema.** The retirement migration drops these, and only these:
- the 31 analysis tables:
  - topics and topic posts/connections;
  - briefings;
  - post AI cache, post highlights;
  - artifacts and artifact references, post artifacts, post relations;
  - source profiles;
  - entities and their aliases, mentions, candidates and post entities;
  - events and their entities and evidence;
  - analyst actions;
  - stories and their posts, updates and candidate links;
  - inbox batches and items;
  - experts;
  - milestone lanes and overrides;
- the analysis-only post columns, including the title and summary pivots and their versions.

Reading tables stay:
- sources, posts, source fetch state, post reader state, post interactions, post notes, folders, source folders, credentials, job runs, system settings, YouTube watch progress.

`post_notes` stays as data even though its UI is retired. It is the owner's own writing, so it is not dropped.

**Budget.** Each slice records line count (backend, frontend, docs) and backend image size before and after. The target after all slices is about 55–60k tracked lines and a backend image well below today's 464 MB.

**Budget check, 2026-10-11.** The first draft said 45–50k; that was an arithmetic slip. Main measured 102,235 lines, and the planned cuts add up to 42–47k:
- dead code about 5.5k;
- docs 5–9k;
- analysis about 28.7k (code and tests);
- pass-through layers and duplicates 3–4k.

Today's additions are inside the 102k: the blog (+1.3k) and the archive sheet (+1.3k). The Design Studio branch adds about 7k more when it merges (docs, specimens, modes), which puts the whole after-cleanup figure at about 62–67k.

## Testing Decisions

- **What a good test is here:** it exercises behaviour through a module's interface and asserts what a caller sees: HTTP status and JSON, saved rows, a `RunReport`, rendered text and route. It never asserts which internal helper was called. A deletion slice adds no tests; its proof is that the existing reading tests still pass.
- **Seams.** Three, all existing; no new seams.
  1. **The HTTP routes of the FastAPI app**, called as route functions the way the current route tests do.

     Today those tests inject a fake bridge. When the bridge goes (slice 7), they inject the service registry instead. Prefer real services against the scratch `insight_test` database, and fake only the network.

     Prior art:
     - `test_feed_routes` (route functions, error redaction);
     - `test_ingestion_routes`;
     - `test_posts_by_source_routes`;
     - `test_repo_reader` and `test_ingestion_db` (real database through the test database helpers).
  2. **The ingestion entry point**, `run_ingestion(FetchRequest) -> RunReport`, with fake source kinds.

     Prior art: `test_ingestion_runner`, `test_source_kinds`, the ingestion and kind fakes. It must stay green and unchanged through every slice. Its tests are the proof that reading-side ingestion didn't move.
  3. **The frontend app routes**, rendered with providers and the fake API.

     Prior art:
     - `App.test.tsx` (which route renders);
     - page tests such as `PostDetailPage.test` and `SourcesConfig.test`;
     - `layout.test`.

     When analysis retires, the route tests change their analysis assertions to "old path redirects to the feed". The fake API shrinks with the real client.
- **Tests that retire with their code:**
  - inbox, evidence, entity/event memory, stories, story timeline, vertical briefing (three files), topics (two files), backend fallbacks, analysis routes, analysis credentials;
  - on the frontend: DailyBriefing, briefing panels, the post page's analysis test, and the inbox/stories/experts fixtures and tests.
  - `test_settings` goes with the switch.
- **Tests that must exist after slice 9:**
  - one route-level test per listing filter (all, source, track, date, unread, cursor) against the single listing query;
  - one test for the single read-state endpoint.
- **Every slice ends with:**
  - the backend suite, run inside the image against `insight_test` with migrations applied (`MIGRATE=1`);
  - the frontend tests;
  - the frontend production build.

  All three must be green. The schema slice also runs the migration runner test.

## Out of Scope

- Merging the API and ingestion into one container (see `plan/INSIGHT_merge_api_ingestion_research.md`). This spec only builds its precondition, the connection seam.
- Docker memory/CPU limits, log rotation and Postgres tuning (they wait for measured peaks on the server).
- Postgres Alpine and frontend lazy loading (owner: lower priority).
- Any new reading feature, and any Mark X analysis feature, including entity pages (0001) and the track briefing redesign (0002).
- A Rust rewrite.
- Changing ingestion behaviour, source kinds, adaptive cadence or rate limiting.
- Running ingestion or migrations on the server (owner's go only).

## Further Notes

- **Decided (owner, 2026-10-11): retire, not pause.** Analysis is removed completely, including milestones; issue 0001 rebuilds milestones and entity pages later on the reading core. The trade-offs (what retiring gains and what it costs) are written up in the blog post `/blog/junior-to-senior`, section "Retiring analysis: the good and the bad".
- **Why retire rather than keep dormant.** Dormant code still costs:
  - build time and image size;
  - test time;
  - ungated stale routes;
  - per-post work at save time;
  - every future refactor that has to step around it.

  Retro principle 5 says a feature earns its place with a reading test. Mark X should rebuild analysis on the Mark IX reading core rather than revive code designed around the old one.
- **Sizes behind this spec** (audit, 2026-10-10):
  - dead code about 5.5k lines;
  - stale docs 5–9k;
  - analysis backend about 15.5k plus 3.5k tests;
  - analysis frontend about 8.5k plus 1.2k tests;
  - shallow layers and duplicates 3–4k;
  - 129 routes, about 61 of them analysis;
  - 166 raw connection calls;
  - 72 frontend catch blocks.
- The ingestion core and source kinds are the model for the deepening work. They already have one small interface with a lot behind it.
- Standing rule: no build, workflow or deploy starts until the owner says go.
