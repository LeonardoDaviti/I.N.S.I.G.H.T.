# 0107 — An archive that waits out a host's limit and carries on, instead of pausing for you

Status: **spec** 2026-11-05, from an archive run on the server (owner's report). Measured on one run only; the fix learns the numbers per host instead of assuming them.

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
