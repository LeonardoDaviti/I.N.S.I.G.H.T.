# 0262 — Reddit through the reader's browser (browser intake)

Status: **chosen direction** (owner 2026-11-21: "so browser intake is our future? mark that"). Not built yet.

## Why (what was tried, 2026-11-21)

Reddit is closing automated reading (TechCrunch, 2026-09-30): RSS ends 2026-11-13, apps must register by
2027-01-12, the public API shuts down 2027-03. From the server (and this machine), every gate answers 403:

| Path | Result |
|---|---|
| OAuth API, the owner's app (0242) | 403 "Blocked" (unapproved app) |
| Registering the app | did not work (owner) |
| Public `.rss` / `.json`, combined `/r/a+b/new.json` | 403 / 404 / 429 ("blocked by network security") |
| The owner's private feed `.json?feed=…` from the server | 403 |
| Redlib bridge on the server | 403 on every request |
| PullPush / Arctic Shift | third-party archives: unreliable, lagging; history backfill only |

v10.28 made it worse: every Reddit address went to OAuth; the RSS path that worked until 2026-11-17 was dropped
(r/LocalLLaMA's last post 2026-11-17, 3,324 stored).

## The design (browser intake)

A small browser extension (Firefox incl. Android, Chrome), the "Save to INSIGHT" bookmarklet's idea made automatic:
1. The reader pastes INSIGHT's address and an intake token (Connections; it can only post Reddit JSON).
2. Every ~20 min while the browser runs: asks INSIGHT for the followed subreddits (the Reddit sources), reads
   `/r/<a>+<b>+…/new.json?limit=100&raw_json=1` with the reader's own session, pages with `after=` while all are new
   (Reddit keeps ~1,000 per listing: one browser session a day catches the day up).
3. Posts the JSON as-is to `POST /api/reddit/intake`; INSIGHT reads it with the Reddit kind's existing parser (each
   post into its subreddit's source, deduplicated by address as always).
4. Comments only where they matter: INSIGHT lists the threads it wants (posts in a track or a News row, a cap a
   round); the extension reads `/comments/<id>.json?sort=top&limit=50&depth=3` and posts them.
No password stored; data goes only from the reader's browser to their own INSIGHT. Each open-source user runs it
for their own account. Risk stated to the owner: background reads from a logged-in session are not zero-risk under
Reddit's terms (as for any RSS-reader extension).

Also: restore the Reddit kind's address routing so a future working path (registration approved, a feed) is not
blocked by 0242's OAuth-only rule.

## Listed, not chosen: a headless logged-in browser on the server

Technically possible: a headless browser (e.g. Playwright/Chromium) on the server, logged in to the owner's Reddit
account, opening the subreddit pages on a schedule and handing their JSON/HTML to INSIGHT. Not built, by my
decision: its purpose would be to get automated server traffic past Reddit's network-security block, which Reddit
put up against exactly this; it is fragile (Reddit hunts it), risks the owner's account, and cannot ship in
open-source INSIGHT. Kept here so the option is on record.
