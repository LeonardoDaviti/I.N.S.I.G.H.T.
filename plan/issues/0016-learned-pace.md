# 0016 — A pace that learns: survive 429s and timeouts instead of failing

Status: **ready-for-agent** (designed with the owner, 2026-10-16).

## Problem Statement
- **One 429 fails a source, and the next ones fail the same way.** In the full run on the preview, the first subreddit got HTTP 429 "Too Many Requests", and the other 8 were still asked at the same 8-second gap. All 9 failed. A Telegram bridge timeout failed its source too.
- **Nothing retries, and nothing slows down.** The site's "Retry-After" hint is ignored. The per-site gaps are fixed numbers in the code.
- **Archives are long runs against the same sites**, so they need this most. A blocked page today ends the archive.

## Solution
- **Every site has a learned pace.**
  - It starts at today's gap for that site (`HOST_FLOORS`, or 0).
  - **On a 429 or a timeout:** wait what the site asks for (Retry-After, else 60 s; at most 120 s), retry once, and **double the site's gap** (at least 5 s, at most 120 s).
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
- **The learned gap lives in the per-host limiter** (`HostLimiter`), keyed by the same host keys as today (`reddit.com`, `platform:reddit`, the Substack and Telegram keys). It gains:
  - `limited(host, retry_after_s) -> wait_s`: new gap = `min(120, max(2 × gap, 5))`; wait = `min(120, retry_after_s or 60)`; resets the success count.
  - `succeeded(host)`: after 20 in a row, gap = `max(floor, gap × 0.75)`, and resets the count.

  The existing spacing reads the learned gap instead of the floor. `slot()` is unchanged, and nothing takes it re-entrantly.
- **Archives share the limiter.** Today archives don't go through `FetchGates` at all. The archive path takes the same `FetchGates.slot` per page that a fetch takes, so a run and an archive on the same host are spaced together. Use the process's one gates instance (the services registry already holds shared services; reuse it, no new singleton).
- **`KindHttp` only classifies errors.** `class HttpError(ValueError)` carries `status`, `retry_after` (integer seconds from the header, else None) and `timed_out`. A non-2xx response raises it with the status. Connect and read timeouts both raise it with `timed_out=True`; today a read timeout escapes as a raw `TimeoutError`. Because it subclasses `ValueError`, existing callers are unaffected. The Telegram bridge's JSON "too many requests" body maps to `HttpError(status=429)` in the bridge kind.
- **Retries happen where the host is known:**
  - **Runner `_fetch`**, inside its slot: on `HttpError` with 429 or `timed_out`, call `limited(host_key)`, emit a `slowed` progress event, sleep through the gates' sleep, and run `fetch_latest` once more. On success call `succeeded(host_key)`. A second failure fails the source as today.
  - **Archive loop:** on the same errors, wait, then restart `kind.archive_pages` once from the last recorded checkpoint. A second failure ends the archive as paused.
- **Paused archive.** The job finishes as `success` with `paused: true` and `paused_reason`, and no `completed_at` on the checkpoint, so Resume continues from it. If the first page fails, there is no checkpoint, and the next archive recomputes its start (0015). The archive sheet shows a warning notice, "Paused: reddit.com is limiting us", with Resume.
- **Event line.** A new progress phase `slowed`, whose message is built in `JobProgressSink`: "<host>: too many requests, slowing to N s", or "<host>: timed out, slowing to N s".
- **Limits** (constants in the limiter): wait ≤ 120 s, gap between 5 s and 120 s after a limit, 20 successes to shrink, ×0.75 per shrink.
- **Docs:** `BACKEND.md` (pacing) and `design/docs/pages/sources.md` (the paused archive).

## Testing Decisions
- **Limiter unit tests** (fake clock and sleep; prior art: the gates tests):
  - `limited` doubles, with the 5 s minimum and 120 s cap;
  - Retry-After is honoured and capped, with 60 s when absent;
  - 20 successes shrink by ×0.75, never below the floor;
  - spacing uses the learned gap.
- **`KindHttp` classification:** stub `_get_text_sync`. A 429 with `Retry-After: 7` raises `HttpError(429, retry_after=7)`; a read timeout and a connect timeout raise `timed_out=True`.
- **Runner tests:**
  - a 429 then a success fetches the source;
  - after one source's 429, the next source on the same host is spaced by the doubled gap;
  - the job events include the slow-down line;
  - two 429s fail the source.
- **Archive tests:**
  - a page failing once is retried from the last checkpoint;
  - failing twice ends as paused, with the checkpoint, and Resume starts there;
  - an archive takes the shared gate slot.

## Out of Scope
- Editable per-site gaps or any pacing UI (over-engineering for a number nobody tunes).
- Remembering the pace across restarts.
- Reddit OAuth (0012's comments half).
- The Telegram account (MTProto), which has its own flood-wait rule, and yt-dlp, which has its own retries.
