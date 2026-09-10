# Adaptive Fetch Cadence — Feature Spec

Status: **proposed** (not implemented)
Requested: 2026-08-15

## Problem

`safe_ingest` treats all 223 enabled sources identically: one global
`SAFE_INGEST_SKIP_THRESHOLD_HOURS` (default 20) decides whether a source is
stale. A Telegram channel posting 30x/day and a personal blog posting twice a
year are both re-fetched on the same 20-hour cadence.

Consequences today:

- A full cycle walks every source sequentially and takes ~1 hour.
- Most of that hour is spent re-fetching feeds that have not changed.
- Slow/dead sources (DNS failures, yt-dlp timeouts) burn their full timeout on
  every cycle, forever.

## Proposal

Derive each source's fetch interval from its own observed publishing rate, then
bucket sources into cadence tiers.

### Signal

For each source, compute the mean inter-arrival time across its **latest 20
posts**:

```sql
SELECT source_id,
       EXTRACT(EPOCH FROM (max(published_at) - min(published_at)))
         / NULLIF(count(*) - 1, 0) AS mean_gap_seconds,
       count(*) AS sample_size
FROM (
    SELECT source_id, published_at,
           row_number() OVER (PARTITION BY source_id ORDER BY published_at DESC) AS rn
    FROM posts
    WHERE published_at IS NOT NULL
) ranked
WHERE rn <= 20
GROUP BY source_id
HAVING count(*) >= 3;
```

Store as `sources.mean_gap_seconds`, `sources.cadence_tier`,
`sources.cadence_computed_at`. Recompute nightly, not per cycle.

### Tiers

| Tier | Mean gap between posts | Fetch every |
|---|---|---|
| `fast` | < 12h | 24h |
| `medium` | 12h – 7d | 3–5 days |
| `slow` | > 7d | 21 days |
| `unknown` | fewer than 3 posts | 24h (probation) |

Rule of thumb: fetch interval ≈ `clamp(mean_gap * 0.5, 24h, 21d)`. The 0.5
factor means a source is polled about twice per expected post, so a burst is
caught within one interval and nothing is missed between polls given
`max_posts_per_fetch`.

### Guard rails

- **Never let backlog exceed `max_posts_per_fetch`.** If a source's tier
  implies an interval where `interval / mean_gap > max_posts_per_fetch`, cap
  the interval so the window still fits. Otherwise a 21-day sleep on a feed
  that only exposes 20 items silently drops posts.
- **Manual override wins.** Add `sources.fetch_interval_hours_override`; when
  set, skip tier logic entirely.
- **Error backoff is separate.** A source in `error` status should back off
  exponentially (1h → 2h → 4h … cap 24h) regardless of tier, and reset on
  first success. This is what would have stopped the 32 dead YouTube channels
  from costing a yt-dlp timeout every single cycle.
- **New sources start in `unknown`** and graduate once they have 3+ posts.

### Expected saving

With the current corpus, most RSS sources publish daily or slower. Rough split
is ~60 fast / ~120 medium / ~40 slow, so an average cycle would touch ~90
sources instead of 223 — combined with parallel fetching, well under 10
minutes.

## Surfacing

- `cadence_tier` and next-due time as columns in Settings → Sources.
- Operations panel: "N sources due this cycle, M deferred".
- Manual "fetch now" must ignore cadence entirely.

## Dependencies

This is worth doing **after** the ingestion concurrency fix, not before.
Parallel fetching is the larger win and is independent; adaptive cadence then
reduces the work that gets parallelised.

## Related

- `backend/insight_core/scripts/safe_ingest.py` — `should_fetch_source()` is
  the single function this replaces.
- `backend/insight_core/db/repo_sources.py` — `_platform_defaults()` holds the
  current per-platform knobs.
