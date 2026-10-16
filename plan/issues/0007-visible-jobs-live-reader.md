# 0007 — See the jobs that run, and a reader that updates by itself

Status: **built** 2026-10-16, not yet deployed (owner observations on the server, 2026-10-16). UX.

## Problem Statement
- **I can't tell whether anything is running.** I added a source and it said "due" with a "Fetch now" button. I didn't know whether I had to press it. In fact the scheduler fetched it at the next hourly tick (the 11:28 run fetched 41 due sources and found 125 new posts), and nothing told me.
- **Running jobs are only visible deep in Sources → Ingestion.** From the reader or a post, there is no sign that a fetch is going on.
- **The reader never updates by itself.** While I read, new posts arrive in the database, but the "N new posts" pill only appears after I switch windows or start a fetch from this tab. I want to see posts come in while they are being fetched.

## Solution
- **"Due" says when.** Wherever a source is due, it reads "due · next check in 37 min" (the scheduler's next tick). "Fetch now" stays as an optional shortcut, worded as optional.
- **A new source is fetched straight away.** Adding a source starts a fetch of it right then, and the toast says "Added — fetching now". Nobody has to know about the scheduler.
- **One quiet activity indicator in the top bar**, on every page. While any ingestion run or archive job is running, it shows "fetching · 3 of 41" (or just "fetching" when the count isn't known). Clicking it opens Sources → Ingestion → Jobs on that job. When nothing runs, it shows nothing.
- **A running ingestion run reports progress**: sources done out of sources due, and new posts so far. Each source's posts are saved as soon as its fetch finishes, so they reach the reader during the run, not at its end.
- **The reader updates itself while it is open.** While a job runs, the unread counts are checked every 10 seconds; otherwise every 60 seconds. New posts show as the existing "N new posts" pill. The list itself never reorders under you; the pill puts them in on click, as today.

## User Stories
1. As the reader, I want "due" to say when the next automatic check is, so that I know I don't have to act.
2. As the reader, I want "Fetch now" to read as optional, so that I don't think a due source is waiting for me.
3. As the reader, I want a source I add to be fetched immediately, so that I can read it right away.
4. As the reader, I want the add-source toast to say it is fetching, so that I know something is happening.
5. As the reader, I want a sign in the top bar while anything is fetching, so that I know from any page that work is running.
6. As the reader, I want that sign to show progress (sources done out of due), so that I can tell how long it will take.
7. As the reader, I want to click the sign to see the job, so that I can follow or inspect it.
8. As the reader, I want the sign gone when nothing runs, so that a quiet app looks quiet.
9. As the reader, I want a scheduler run to show up too, not only runs I started, so that automatic fetches are visible.
10. As the reader, I want a failed run to leave a quiet "last fetch failed" note on the sign for an hour, so that I notice failures without hunting.
11. As the reader, I want the "N new posts" pill to appear while I'm reading, without switching windows, so that I see posts arriving.
12. As the reader, I want counts checked more often while a fetch runs, so that new posts appear soon after they are saved.
13. As the reader, I want the list not to jump while I read, so that I don't lose my place.
14. As the reader, I want the rail's unread counts to update too, so that I see which source got new posts.
15. As the reader on a phone, I want the sign to stay small, so that it doesn't crowd the top bar.
16. As the reader with reduced motion, I want the sign not to animate, so that it is calm.
17. As the reader, I want polling to stop while the tab is hidden, so that an idle tab costs nothing.
18. As the owner of the server, I want no new long-lived connections (no websockets), so that the stack stays as simple as it is.

## Implementation Decisions
- **No SSE or websockets.** Everything is polling on existing endpoints. This keeps the minimal-codebase rule: no new transport and no new seam.
- **Each source's posts are saved as soon as its fetch finishes.** Today the runner fetches every due source at once and saves everything in one batch at the end. The runner changes so that each source's fetch is followed by its own save, as the fetches complete, and the per-source results are merged into the run's one save result. Cross-source duplicates are already handled by the URL upsert. Outcomes are still recorded after each source's save, with the same rule: a source whose posts all failed to save is failing.
- **Progress.** `progress` stays the bar's percentage. The job payload gains `sources: {done, total}` and `new_posts`, both updated after each source's save.
- **One source of "what is running".** The top-bar indicator and the Ingestion tab both use the existing `useOperationsOverview` (it already polls every 15 s). No second interval. While a run is active it polls every 5 s, the same hook with a shorter interval.
- **Which jobs count.** Only job types `ingestion_run` and `archive_source`; `scheduler_cycle` doesn't count.
- **Where the indicator links.** `/settings/sources?tab=ingestion&sub=jobs&job=<id>`, built with `sourcesIngestionHref`. Fix `useIngestionRun`'s navigation to the old `/ingestion/missions?job=` path at the same time.
- **Failure note.** The sign shows `last fetch failed` while the newest `ingestion_run` failed and finished under 60 min ago.
- **Add source, then fetch.** The add-source endpoint keeps its contract. After a successful add, `handleAddSource` calls the existing `runFetch({kind: 'source', id, name})` from `useIngestionRun`, and only when the new source is enabled (fetch-now would force a fetch even for a source added disabled). Its toast is the toast, with the start text "Added — fetching now".
- **"Due" wording.** Uses `GET /api/operations/scheduler` → `scheduler.state.next_tick_at` (via `useSchedulerConfig`): "due · next check in 37 min". When `next_tick_at` is missing or in the past, it reads "due · scheduler not running".
- **Reader polling.** The unread-counts query gets a `refetchInterval`: 10 s while the overview shows a running job, 60 s otherwise. React Query already stops interval polling in a hidden tab, so no code is needed for that. The feed query stays frozen (`staleTime: Infinity`); only the counts poll, and the pill does the rest.
- **Top bar.** A small text indicator in the existing top bar, in the slash-nav language, with no new layout. Hidden when idle.
- **Design rules.** Amend principle P7 and decision 007: "Reading views never start a fetch; the top bar may show that one is running, linking to Sources." Update `shell.md` for the indicator.

## Testing Decisions
- Test what a user sees: rendered text, routes, calls made to the API client. Never which internal helper ran.
- **Backend:** a runner test with two sources where the first source's posts are in the database before the second fetch finishes (gate the second fake fetch), and the payload's `sources.done` grows to `total`. A test that a source whose save fails is still recorded as failing. Prior art: the existing runner tests.
- **Frontend:** component tests with the existing fake API client.
  - The indicator renders "fetching · 3 of 41" for a running job and nothing when idle, and its link goes to the jobs view (in `layout.test.tsx`).
  - Adding an enabled source calls `runFetch`; adding a disabled source doesn't.
  - "Due" renders the next-check time, and "scheduler not running" when there is none.
  - With fake timers, the unread counts are refetched and the pill appears.
  - Prior art: `SourcesConfig.ingestion.test.tsx`, `ReaderPage.test.tsx`, `layout.test.tsx`.

## Out of Scope
- Streaming each post into the list as it is saved (the pill is the boundary, so reading never jumps).
- Changing scheduler cadence or the tick length.
- Notifications outside the app.

## Further Notes
- Evidence (server, 2026-10-16 11:51 UTC): scheduler ticks hourly at :28; 11:28 run "41 due, 181 deferred, 0 failed; 125 new posts"; unread counts have `staleTime: 30s` and no interval.
