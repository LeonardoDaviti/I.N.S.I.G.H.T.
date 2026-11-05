# 0107 — An archive that waits out a host's limit and carries on, instead of pausing for you

Status: **built, not merged** (2026-11-05, branch `issue-0107-archive-waits`); spec 2026-11-05, from an archive run on the server (owner's report). Measured on one run only; the fix learns the numbers per host instead of assuming them.

**Constraints:** download nothing; no fetches from the development machine (tests use fakes); no real channel names in committed files; nothing merges unless `scripts/realdata-check.sh` passes.

## What happened (the server, 2026-11-05)
- An archive of an X account through the self-hosted Nitter planned about 9,600 older posts.
- **The pace:** one page every ~11 s, plus a 30 s cool-down every 10 pages (`NITTER_PROFILE`: 10 s, batches of 10, 30 s). That's 40 pages (800 posts) in 8 min 40 s.
- **Then the limit:** the 41st page got a 429. The archive waited 60 s, doubled the host's gap to 20 s, asked again, got another 429, and **paused** ("resume later"). Total: 9 min 40 s, 800 of ~9,600 posts.
- **A paused archive stays paused until you press Resume.** Nothing in the scheduler resumes it.

## Why
- **A self-hosted Nitter answers 429 when the X sessions it uses are out of requests.** That budget refills over a time window (minutes). Waiting 60 s and asking once more, while the window hasn't refilled, can't succeed. The second 429 is the same limit, not a new one.
- **The pace is fixed, not learned per host.** 0016's learned gap only doubles after a 429 and shrinks after 20 successes. It never learns "N requests per window", so every archive spends the budget as fast as the floor allows, then hits the wall.
- **The archive and the hourly fetches share the host.** An archive that spends the whole budget leaves the hourly fetches of every followed X account to hit the same 429.

## Decided
1. **A limited archive waits for the window, then continues by itself.**
   - On the second limit in a row: it doesn't end. It records `waiting_until` (first 5 min, then doubling up to 60 min) and shows "Waiting for <host>'s limit: continues at HH:MM".
   - The scheduler resumes it from its checkpoint at that time.
   - After 6 waits with no page gained, it pauses as today, saying why.
   - Pause and Resume by hand keep working.
2. **Learn each host's budget from what happened** (kept in `system_settings`, per host):
   - the pages fetched from the last recovery to the next 429 (the window's budget), and the time from the 429 to the first success (the window's length);
   - after two limits have been measured, an archive paces to **80% of the measured budget per window**, so it stays under the limit instead of hitting it.
   - Shown in health: "<host>: about N requests per M min, learned from K limits".
3. **Archives leave room for the hourly fetches:** an archive on a host that live sources use keeps 20% of the learned budget free, and it yields when a live fetch of that host is due.
4. **The class, not one site:** this applies to every host the archive limits on (Nitter, the Telegram bridge, Reddit). No host is named in the rule.

## Not in INSIGHT (the owner's side)
- **More X sessions in Nitter's sessions file multiply the budget.** Nitter rotates through its sessions; each has its own limit. That's Nitter's configuration, outside INSIGHT.

## Done when
- Tests with a fake host that allows N requests per window:
  - an archive of 3N pages finishes by itself, waiting the window out;
  - after two measured limits, it never gets a 429 again;
  - live fetches due meanwhile go through.
- On the server after deploy: the next large X archive finishes without a Resume press, and its events show the learned budget. The owner reads it; nothing is fetched from this machine.
- The real-data check passes (no derived change).

## Built (branch `issue-0107-archive-waits`, 2026-11-05)
From main 50371cc; not merged, not pushed. No migration (the budgets live in `system_settings`, the waiting state in `job_runs` and `settings.archive`). Nothing fetched or downloaded: the tests use a fake host under a fake clock; the numbers below are read-only queries of the lab and a replay of the server's run against fake hosts.

- **1. A limited archive waits for the window, then continues by itself.**
  - The first 429 of a leg is today's (Retry-After or 60 s, the host's gap doubled, one retry). The second in a row ends the leg **waiting**: the job's status becomes `waiting` (not finished) with `waiting_until`, `waiting_host`, `waits` and the counts so far; `settings.archive.waiting` = {host, until, reason}; the checkpoint stays resumable. Waits: 5 min, then 10, 20, 40, 60, 60 while no page comes; a page resets them to 5.
  - **The scheduler continues it** (`run_scheduler.py`, every 30 s; `services/archive_jobs.py`): it claims a due job atomically (waiting -> running, trigger `scheduler`, so only one process continues it and an API restart does not call it interrupted) and continues on the same job, from the checkpoint, with the plan the job carries (no new measurement: that would be one more request to a host that was limiting us). The counts carry across legs. Its pages then share one host limiter with that process's hourly fetches. A scheduler restart sets the archives it was continuing waiting again, due at once (a deploy needs no Resume).
  - **After 6 waits with no page gained** it pauses as before: "Paused: <host> is still limiting us after 6 waits; resume later".
  - **By hand:** Resume on a waiting archive continues the same job at once ("Continue now" in its notice); a new archive without resume replaces the waiting job. A second archive is refused while one runs in either process (the API now also reads the job's status).
  - A timeout counts the same way ("Waiting for <host> to answer"); it teaches no budget.
- **2. Each host's budget is learned** (`ingestion/host_budgets.py`, `system_settings` key `host_budget:<host>`, one per host so the two processes never overwrite each other):
  - a measure is the requests that went through from a recovery (the first success after a limit, or an archive's start) to the next 429, over the time **from that recovery to the next one**. Not "from the 429 to the first success" as the spec put it: that is the window minus the time spent using it (on the server's run, 429 at 8 min 40 s: with a 15 min window it would measure about 6 min), and pacing to it would hit the limit again;
  - only archives take measures (they ask continuously); a live fetch in the same process counts against the stretch being measured; requests from the other process are not counted, so a measure can only come out lower than the host allows;
  - after **2 measured limits** an archive paces to 80% of the slowest fresh measure: one page every window / (0.8 x requests), as the slot's minimum interval (max with the host gap and the kind's pause, never the sum). Measures older than 7 days are forgotten (a bridge given more sessions allows more).
  - Events: `learned` ("nitter.local: about 40 requests per 15 min, learned from 1 limit", and from the second "...; pacing to 80%: one page every 36 s"), `pacing` at the start of a later leg.
  - **Health:** `GET /api/sources/health` and the overview's `source_health` carry `host_limits` [{host, requests, window_s, limits, archive_gap_s, line}]; the ingestion overview shows **Site limits**: "<host>: about N requests per M min, learned from K limits · archives page every X s, 80% of it" (or "· archives pace to it once 2 limits are measured").
- **3. Room for the hourly fetches:** the 20% the archive leaves is that room (the same 20% as Decided 2; nothing more is subtracted). And at most once a minute an archive asks whether a run has decided to fetch a source of its host and not tried it yet (`ports.DbLiveFetchDue`, `source_fetch_state`'s decision newer than its last attempt, under 2 h old); if so it steps back in 30 s steps, at most 15 min ("Making room for <host>'s live fetches"). A continuation due during a scheduler tick starts after the tick.
  - Measured on the lab (read-only): 12 enabled X sources on the Nitter host and 35 on the Telegram bridge; of the 360 stored runs, 22 fetched X sources, **at most 7 in one run, 1.9 on average** (one request each); the bridge at most 17, 3.1 on average. So at 40 requests per window, 20% (8) covers the largest X run seen; the yield covers the bridge's larger runs.
- **4. The class:** nothing names a host. The waits, the budgets and the yield key on the kind's host key, so they apply to the Nitter host, the Telegram bridge, Reddit and any host that answers 429.
- **Frontend:** the archive notice "Waiting for <host>'s limit: continues at HH:MM" (the reader's time) with the result so far and **Continue now**; the same line under the source's row in the archive catalog, as the job's line in the job history (glyph `scheduled`, word `waiting`) and for its `waiting` events; the sheet follows a waiting job (polled every 30 s) and sees the scheduler take it up. The line lives in its own module (`lib/archiveWaiting.ts`) so the main chunk takes only it: feed route **173,290** gzip bytes vs main's 172,915 (+375, gate passes).

**What the server's events will show** (the server's run replayed against fake hosts with the real pace, `NITTER_PROFILE` and `HOST_FLOORS`, 480 pages; the window is the owner's to measure, so three are tried):

| assumed limit | finishes in | legs | 429s | learned (2nd) | then |
|---|---|---|---|---|---|
| 40 per 15 min | 4.4 h | 3 | 5, the last at 57 min | about 99 requests per 47 min | a page every 36 s, no 429 |
| 40 per 30 min | 10.7 h | 6 | 10, the last at 134 min | about 40 requests per 46 min | a page every 87 s, no 429 |
| 80 per 60 min | 10.2 h | 8 | 14, the last at 263 min | about 80 requests per 96 min | a page every 90 s, no 429 |

The first case's job reads: "nitter.local: too many requests, slowing to 20 s" (8 min) · "Waiting for nitter.local's limit: continues at HH:MM" · "Continuing after nitter.local's limit" · "nitter.local: about 40 requests per 15 min, learned from 1 limit" · ... · "nitter.local: about 99 requests per 47 min, learned from 2 limits; pacing to 80%: one page every 36 s" · "Archive completed with 9600 posts". **Every case finishes without a Resume and has no 429 once paced.** The learned pace is safe but slower than the host allows (36 s against an ideal 28 s; 87 against 56; 90 against 56): the window measured is an upper bound, longer than the true one by up to the last wait (the 5, 10, 20, 40 min ladder overshoots the refill), and 0016's doubled gap can keep a stretch from spending the whole window (the 99 per 47 min). Open for the owner: once one window is measured, the wait could aim at its expected refill instead of the ladder, which would measure it within 5 min.

**Follow-up built** (2026-11-05, branch `issue-0109-b`, commit "0107 follow-up"): once one window of a host is measured, the wait aims at its refill instead of the ladder (the ladder stays for an unmeasured host).
- **A limit is measured from the start of the window it hit**, not the stretch's: that window began with the request its budget's count back (the host allowed that many in it), so a stretch slower than the host allows, across several windows, still measures one window (the 99 per 47 min above was such a stretch: 40 per 15 min, three times over).
- **The wait aims at that window's refill** (`HostBudgets.refill_wait`): each measure brackets the window between its latest refusal and its recovery; the wait goes 5 min past the latest refusal known, at most to the narrowest recovery measured, at least 60 s. A refusal at or past the window measured falls back to the 5, 10, 20, 40 min ladder (the host allows less now). The `waiting` event says "…, when its window refills" and carries `refill: true`.
- **The learned budget** is the fewest requests measured over the narrowest window of those measures when their brackets agree (every refusal before every recovery), else the slowest measure as before. Records gain `window_started`, `refused_at` and each measure's `refused_s`; older records read as before.
- **The replay** (the same simulation, 480 pages, the real pace and floors):

| assumed limit | ideal pace (80%) | before: learned, pace, finished | after: learned, pace, finished |
|---|---|---|---|
| 40 per 15 min | 28 s | 99 per 47 min, 36 s, 4.4 h | 40 per 15 min, **28 s**, 3.7 h |
| 40 per 30 min | 56 s | 40 per 46 min, 87 s, 10.7 h | 40 per 31 min, **59 s**, 7.9 h |
| 80 per 60 min | 56 s | 80 per 96 min, 90 s, 10.2 h | 80 per 61 min, **58 s**, 8.2 h |

  No 429 once paced, in every case (the last refusals at 57, 128 and 245 min, before the pace). Tests: `test_host_budgets` (5 new: no refill for an unmeasured host; a stretch over several windows measured from the window it hit and its wait at that window's refill; a wide bracket probed 5 min past its latest refusal, then 5 more; a refusal past the window falls back to the ladder; brackets that disagree keep the slowest); `test_source_fetch_service` (the ladder before the first measure, the refill after it; the 3N archive now waits 5, 10, 9, 4 min; the 6N archive learns 10 per 17 min, a page every 128 s, against 19 min and 140 s).


**Tests** (written first, with a fake host that allows N requests per window, under a fake clock): `test_host_budgets` (11: two limits before pacing, recovery-to-recovery windows, the same limit twice, live requests counted, nothing learned from live fetches alone, two processes measuring one host, no measure from an empty stretch, old measures forgotten, the slowest wins, health's list); `test_source_fetch_service` (an archive of 3N pages finishes by itself with waits 5, 10, 5, 10 min and its counts carried; after two measured limits it never gets a 429 again; live fetches due meanwhile go through in a window the archive is pacing in; six waits with no page gained pause it saying why; the 0016 pause test now waits); `test_archive_jobs` (7: a limited job waits; the scheduler continues it at its time on the same job; a job claimed once; Resume by hand continues it; a failed continuation fails the job; the job_runs side: due, claimed once, a restart requeues the one it was continuing); `test_ingestion_runner` (a live fetch spends the budget being measured); `test_source_health` (the overview's health has `host_limits`). Frontend: `archiveWaiting.test.ts`, `jobRuns.test.ts` (2), `archiveSection.test.tsx` (the waiting notice and Continue now), `SourcesConfig.ingestion.test.tsx` (the waiting line in the history, the events and the catalog row; Site limits). Backend **1,483 OK** (`./run-tests.sh`, own image tag), frontend **232 + 708**, `npm run build` passes the bundle gate.

**The real-data check** (`scripts/realdata-check.sh --base main --head issue-0107-archive-waits insight_lab`, on 707e06c; the later commit only touches the archive loop's count and the overview's health): **PASS**, no `--allow`. Report: `plan/research/lab/checks/issue-0107-archive-waits-2026-11-05.md` (private). Cases 75 pass, no case changes state; every invariant equal (`story.identity` 0 of 743,865); the diff is empty in every part (titles, text starts, link titles, roundups, membership, origins, News, Classics, Discover): nothing derived reads this code.
