# 0007 — See the jobs that run, and a reader that updates by itself

Status: **ready-for-agent** (owner observations on the server, 2026-10-16). UX.

## Problem Statement
- **I can't tell whether anything is running.** I added a source and it said "due" with a "Fetch now" button. I didn't know whether I had to press it. In fact the scheduler fetched it at the next hourly tick (the 11:28 run fetched 41 due sources and found 125 new posts), and nothing told me.
- **Running jobs are only visible deep in Sources → Ingestion.** From the reader or a post, there is no sign that a fetch is going on.
- **The reader never updates by itself.** While I read, new posts arrive in the database, but the "N new posts" pill only appears after I switch windows or start a fetch from this tab. I want to see posts come in while they are being fetched.

## Solution
- **"Due" says when.** Wherever a source is due, it reads "due · next check in 37 min" (the scheduler's next tick). "Fetch now" stays as an optional shortcut, worded as optional.
- **A new source is fetched straight away.** Adding a source starts a fetch of it right then, and the toast says "Added — fetching now". Nobody has to know about the scheduler.
- **One quiet activity indicator in the top bar**, on every page. While any ingestion run or archive job is running, it shows "fetching · 3 of 41" (or just "fetching" when the count isn't known). Clicking it opens Sources → Ingestion → Jobs on that job. When nothing runs, it shows nothing.
- **A running ingestion run reports progress**: sources done out of sources due, and new posts so far.
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
10. As the reader, I want a failed run to leave a quiet "last fetch failed" note on the sign for a while, so that I notice failures without hunting.
11. As the reader, I want the "N new posts" pill to appear while I'm reading, without switching windows, so that I see posts arriving.
12. As the reader, I want counts checked more often while a fetch runs, so that new posts appear soon after they are saved.
13. As the reader, I want the list not to jump while I read, so that I don't lose my place.
14. As the reader, I want the rail's unread counts to update too, so that I see which source got new posts.
15. As the reader on a phone, I want the sign to stay small, so that it doesn't crowd the top bar.
16. As the reader with reduced motion, I want the sign not to animate, so that it is calm.
17. As the reader, I want polling to stop while the tab is hidden, so that an idle tab costs nothing.
18. As the owner of the server, I want no new long-lived connections (no websockets), so that the stack stays as simple as it is.

## Implementation Decisions
- **No SSE or websockets.** Everything is polling on existing endpoints, with React Query intervals. This keeps the minimal-codebase rule: no new transport, no new seam.
- **Operations overview is the single source of "what is running".** The existing operations overview endpoint gains (if missing) the running jobs with `progress` `{done, total, new_posts}`; the top-bar indicator and the Ingestion tab read the same query. One hook, used by both.
- **Ingestion run progress.** The runner already writes a job row; it updates that job's progress after each source (sources done, sources due, new posts). No new table.
- **Add source → fetch.** The add-source endpoint keeps its contract; the frontend calls the existing fetch-now endpoint for the new source right after a successful add (the same call the sheet's "Fetch now" makes). Decision: frontend-driven, so the backend contract does not change.
- **"Due" wording** uses the scheduler status's next tick time, already returned by the scheduler status endpoint.
- **Reader polling.** The unread-counts query gets a `refetchInterval`: 10 s while the operations overview reports a running job, 60 s otherwise, paused when the document is hidden. The feed query stays frozen (`staleTime: Infinity`); only counts poll, and the pill does the rest.
- **Top bar.** A small text indicator in the existing top bar, in the slash-nav language, no new layout. Hidden when idle.

## Testing Decisions
- Test behaviour a user sees: rendered text, routes, calls made to the API client. Never which internal helper ran.
- **Backend:** a runner test that a multi-source run's job shows growing `progress` and ends at `done == total`; an operations overview route test that a running job carries `progress`. Prior art: the existing runner and operations route tests.
- **Frontend:** component tests with the existing fake API client: the indicator renders "fetching · 3 of 41" for a running job and nothing when idle; clicking goes to the jobs view; adding a source calls fetch-now and shows the toast; "due" renders the relative next-check time; with a fake timer, unread counts are refetched and the pill appears. Prior art: `SourcesConfig.ingestion.test.tsx`, `ReaderPage.test.tsx`.

## Out of Scope
- Streaming each post into the list as it is saved (the pill is the boundary, so reading never jumps).
- Changing scheduler cadence or the tick length.
- Notifications outside the app.

## Further Notes
- Evidence (server, 2026-10-16 11:51 UTC): scheduler ticks hourly at :28; 11:28 run "41 due, 181 deferred, 0 failed; 125 new posts"; unread counts have `staleTime: 30s` and no interval.
