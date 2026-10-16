# 0016 — A pace that learns: survive 429s and timeouts instead of failing

Status: **ready-for-agent** (designed with the owner, 2026-10-16).

## Problem Statement
- **One 429 fails a source, and the next ones fail the same way.** In the full run on the preview, the first subreddit got HTTP 429 "Too Many Requests", and the other 8 were still asked at the same 8-second gap. All 9 failed. A Telegram bridge timeout failed its source too.
- **Nothing retries, and nothing slows down.** The site's "Retry-After" hint is ignored. The per-site gaps are fixed numbers in the code.
- **Archives are long runs against the same sites**, so they need this most. A blocked page today ends the archive.

## Solution
- **Every site has a learned pace.**
  - It starts at today's gap for that site (`HOST_FLOORS`, or 0).
  - **On a 429 or a timeout:** wait what the site asks for (Retry-After, else 60 s; at most 120 s), retry once, and **double the site's gap** (at most 120 s).
  - **After 20 successes in a row:** the gap shrinks by a quarter, never below its starting value.
- **The pace is remembered for the life of the process.** The scheduler is long-running, so the pace carries from one hourly run to the next; a restart starts fresh. No database, no settings screen.
- **A second failure after the retry fails the source as today** (backoff applies). An archive instead **pauses with its checkpoint saved**: "paused: reddit.com is limiting us; resume later". Its progress is never lost.
- **Every slow-down is visible** in the job's events: "reddit.com: too many requests, slowing to 16 s".

## User Stories
1. As the owner, I want a 429 retried after the wait the site asks for, so that one limit doesn't fail a source.
2. As the owner, I want INSIGHT to slow down for a site that limits us, so that the next sources don't hit the same wall.
3. As the owner, I want the pace to speed back up after a run of successes, so that a short limit doesn't slow us forever.
4. As the owner, I want a timeout retried once, so that a slow bridge doesn't fail a source on one hiccup.
5. As the owner, I want waits capped at 2 minutes, so that a run never hangs on one site.
6. As the owner, I want an archive to pause with its checkpoint instead of failing, so that I can resume it later.
7. As the owner, I want slow-downs shown in the job's events, so that I can see INSIGHT protecting itself.
8. As the owner, I want no settings to tune, so that it just works.
9. As the owner, I want sites that never limit us to keep today's speed, so that nothing gets slower for no reason.

## Implementation Decisions
- **One place: the per-host limiter** (the `HostLimiter` behind every fetch's gate slot). It gains the learned gap per host, starting at the host's floor. Two methods: `limited(host, retry_after_s)`, which doubles the gap (capped) and returns the wait, and `succeeded(host)`, which counts successes and shrinks the gap after 20. The existing spacing reads the learned gap instead of the floor. No new module.
- **Detection: one function.** HTTP errors arrive as `ValueError("HTTP 429 …")` from `KindHttp`. `KindHttp` attaches the status and Retry-After to the error (an exception subclass carrying `status` and `retry_after`), so detection doesn't parse message text. Timeouts are recognised by type (`asyncio.TimeoutError`, `TimeoutError`, and the read-timeout error `KindHttp` raises).
- **Retry: one wrapper around a request**, in `KindHttp` (every kind's requests go through it), with access to the limiter for its host. On a 429 or timeout it calls `limited`, sleeps (through `KindHttp.sleep`, so tests don't wait), and retries once. On success it calls `succeeded`. A second failure raises as today.
- **Events.** A slow-down logs a warning and, inside a run or archive, adds a job event through the existing progress sink: "<host>: too many requests, slowing to N s" or "<host>: timed out, slowing to N s".
- **Archives.** When a page still fails after the retry with a 429 or timeout, the archive ends as **paused**, not failed. Its checkpoint from the last good page is already recorded per page; the result says `paused: true` with the reason, and the Archive screen offers Resume (which exists).
- **Limits** (constants in the limiter): wait ≤ 120 s, gap ≤ 120 s, 20 successes to shrink, shrink by 25 %.
- **Docs:** `BACKEND.md` (pacing), `design/docs/pages/sources.md` (the paused archive line).

## Testing Decisions
- **Limiter unit tests** (fake clock and sleep, prior art: the gates tests):
  - `limited` doubles up to the cap;
  - Retry-After is honoured and capped;
  - 20 successes shrink the gap by 25 %, never below the floor;
  - spacing uses the learned gap.
- **`KindHttp` tests** with a fake transport:
  - a 429 with `Retry-After: 7` waits 7 s, then succeeds on the retry;
  - two 429s raise;
  - a timeout is retried once.
- **Runner test:** after one source's 429, the next source on the same host is spaced by the doubled gap, and the job events include the slow-down line.
- **Archive test:** a page failing twice with 429 ends the archive as paused with the last good checkpoint, and Resume starts there.

## Out of Scope
- Editable per-site gaps or any pacing UI (over-engineering for a number nobody tunes).
- Remembering the pace across restarts.
- Reddit OAuth (0012's comments half).
