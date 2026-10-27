# 0021 — Ingestion jobs that say what they delivered

Status: **built** 2026-10-27, not yet deployed. UX.

## Problem Statement
An hourly scheduler tick shows up as a job: "Ingestion run · success · All sources · <1s", heading "Nothing was due", "Skipped: 213 not due yet, 9 in backoff", six stats all 0, the whole raw report JSON, then the events "Ingestion decided" and "0 due, 222 deferred, 0 failed; 0 new posts". What did this run deliver to me? How do I know ingestion actually gathered posts? If nothing was fetched, why does it run and show up at all?

## Background
The scheduler wakes every hour (`ingest_tick_minutes`) and fetches only the sources whose own cadence is due. A tick with nothing due is a cheap check that makes no request.

## Solution
- **A job answers "what did it deliver" first.** The headline is the outcome in words: "34 new posts from 5 sources", "Nothing new: 12 sources checked", "Nothing was due", "3 sources failed" (or "34 new posts from 5 sources, 3 sources failed"). Under it, the sources that delivered, each with its count and a link to read it; then the failed sources, one line each with the reason. The job list rows use the same words.
- **No zero stats, no raw JSON.** The only other line is "2 posts could not be saved" when that happened.
- **A tick with nothing due leaves no job.** The scheduler deletes its job instead of finishing it; the scheduler state still records the tick, so the Scheduler line (next tick, "not running" when stale) is unchanged. Migration 0028 deletes the ones stored before. A manual "Run due sources" with nothing due is still listed: someone asked for it.
- **Events are the per-source lines** (from 0007) and slow-downs. "Ingestion decided", "Ingestion saved" and the final line repeating the summary are gone, also from jobs stored before.

## Implementation Decisions
- **One wording, twice.** `RunReport.summary_line()` (backend: the job message, the log line) and `summarizeRunReport` (frontend, `lib/runReport.ts`) say the same. The report gains `sources_with_new`, because `inserted_by_source` is capped at 20; an old report falls back to its list's length.
- **Why delete, not hide.** The overview loads the 50 newest jobs; hourly ticks would push every real run out of the list and make "Last run" read "Nothing was due". Nothing reads those rows: `recentFailedRun` only cares about failed runs, the daily-work gate reads `scheduler_cycle`, scheduler liveness reads the scheduler state.
- **The frontend `RunReport` type keeps only what is shown**; the counts grid, the "Raw report" disclosure, the decision labels and the stage labels are deleted. `asRunReport` ignores the rest of an old payload (`enrichment`, `decisions`, `summary`).
- **`JobProgressSink`** writes events only for the `source` and `slowed` phases; `jobEvents` (`lib/jobRuns.ts`) filters the old noise from stored jobs.

## Testing Decisions
- Backend: `summary_line` for each outcome, `sources_with_new` from the runner, no events for `decided`/`saved`, a nothing-due tick discards its job and still saves the scheduler state, `discard_job` against Postgres.
- Frontend: `summarizeRunReport` and `asRunReport` (old payloads), `jobSummary` and `jobEvents`; `RunReportSummary` (delivered links, failures, no zero counts or JSON); the jobs view with a job stored before this issue.

## Out of Scope
- The version line at the bottom of the Ingestion tab (issue 0020).
