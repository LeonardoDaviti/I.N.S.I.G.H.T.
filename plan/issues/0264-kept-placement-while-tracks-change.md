# 0264 — A track's kept placement read while the worker changes it

Status: **built** (Stealth v10.31), not deployed. Migration 0168.

## Why (production, 2026-11-21)

Since v10.29 the blind check (tracks.plan_checks, kind `track`, guide track-check-v1, answered via
tracks._fill_check) updates `mx_track_items` for thousands of backlog posts. Each update fired 0133's triggers into
`mx_track_changes`, and `track_kept.calibration()` answered None while any change row of the track existed: the
track was placed live (tracks.placed: every judged item, newest version) on every request until the next refresh.
One track has 65,000 items. The sidebar's counts (GET /api/markx/tracks/counts, every page) took 0.8 s, track pages
2-5 s; the DB's CPU went from 11% to 26% mean, DB->clients traffic from 1.4 to 3.9 MB/s.

## What changed (markx/track_kept.py owns it; no new cache, no second path)

- `mx_track_changes.owner` (0168): the triggers say whose change it is.
  - The owner's own (track labels, the folder's sources, a source switched on/off): `owner` true. The track is
    placed live until placed again, as before: a ✓/✗ shows at once; a read is never wrong for the owner's action.
  - The worker's and the ingestion's (a verdict or check answered on a track item, a post deleted or moved):
    `owner` false. Readers read the last kept placement.
  - Rows logged before 0168 count as the owner's (read live until the next refresh).
- `track_kept.calibration` reads kept unless an owner change is pending (a partial index on owner rows).
- `track_kept.refresh(cur, gap=REFRESH_GAP)`: places again a never-placed track and an owner-changed track at
  once; a worker-changed track only when its placement is REFRESH_GAP (**5 minutes**) old. Its change rows stay
  until then.
- `track_kept.due(cur)`: whether a refresh would place something now; the jobs process's "tracks" view
  (jobs._tracks_missing) looks at it, so the refresh follows an owner's label within the view's 120 s pace and a
  worker's changes within REFRESH_GAP plus that pace. The refresh still also runs after each background plan
  (every 5 min) and after each ingestion run (ports.keep_derived).
- `track_kept.counts`: Discover counted in SQL (a number sent, not every Discover row).
- tracks.page_inputs' loose part counts only the owner's changes for a kept track (the worker's move the page once
  placed again, through placed_at); a never-kept track's every change, as before.

Staleness: for the worker's changes, a reader sees the placement at most about REFRESH_GAP + 2 minutes old.

## Measured (local test DB, one track, synthetic posts; no server access)

20,000 judged items (each with 2 older versions: 60,000 item rows), kept, then 200 check answers (200 worker change
rows). Same data, `calibration` as before vs now; 5 calls each, warm:

| Read | before | after |
|---|---|---|
| sidebar counts (track_counts.topic_counts) | 75.7 ms, 20,004 rows to the client, 1 live placement | 9.1 ms, 4 rows, 0 |
| track page build (tracks.shown_page) | 390 ms, 40,171 rows, 2 live placements | 389 ms, 40,211 rows, 0 |
| the live placement's SQL alone | 51 ms, 80,000 rows scanned, 1,750 blocks | (not run) |
| kept counts' SQL | | 1.4 ms (in-track) + 6.8 ms (Discover count) |

At 5,000 items (one version): counts 17.0 -> 7.5 ms; page 84 -> 92 ms.

The page build is not faster: it groups all kept items into sections in Python either way. The API sends kept page
bytes (0206) and builds only when the owner's inputs changed or KEPT_LAG ended; what goes away is the live
placement's scan of every item version in the DB (on the server, 65,000 items x versions, on each build and each
counts request).

## Left

- Deploy, then check on the server: /tracks/counts time, DB CPU, DB->clients traffic, `mx_track_changes` rows
  (owner false accumulating between refreshes, then taken).
- An owner label on the 65k track still places it live on every read until the refresh (within ~2 minutes), as
  before v10.29. If that is too slow, the label could place its track synchronously (not done).
- The page build over every kept item (~0.4 s at 20k locally) is the jobs process's; not touched.
