# 0015 — Smart archiving: continue below what I have, and no measuring phase in fetch runs

Status: **ready-for-agent** (designed with the owner, 2026-10-16).

## Problem Statement
- **An archive downloads what I already have first.** It always starts at the source's newest page and walks back. If I have 400 posts and ask for 500, it downloads my 400 again before anything new arrives, and those 400 count toward the 500. On slow, rate-limited sites (Nitter, Reddit, the Telegram bridge) that is minutes of wasted requests, and every wasted request moves us closer to a 429.
- **I have to choose a number.** I always want "everything older than what I have".
- **Fetch runs carry a second phase nobody needs.** After saving, a run re-measures each source's size once a week (a second download of the source; for YouTube, a listing of the whole channel). In the full run on the preview that was 3.5 minutes after the last post was saved. The measurement only feeds the Archive screen's "at the source" number, and planning an archive measures the source fresh anyway.

## Solution
- **An archive continues below the oldest post I have**, jumping straight there when the source allows it, and fetches **everything older** by default.
- **How each kind jumps:**

  | Kind | Jump | From |
  |---|---|---|
  | Substack | by position | `offset` = stored posts − one page |
  | Telegram (account) | by position | `offset_id` = oldest stored message id |
  | Telegram bridge | by position | `next_page` = stored ÷ page size, one page early |
  | YouTube | by position | channel listing starts at video number stored + 1 − one page |
  | Nitter | by date | the bridge's search, `until` = the oldest stored tweet's day; then its cursor |
  | Reddit | — | the archive is blocked by Reddit (403); unchanged |
  | Plain RSS | — | a feed holds only its latest posts; unchanged |

- **Overlap a little, never compute exactly.** Each jump starts one page (Nitter: one day) early. Duplicates are already handled by the URL upsert.
- **The plan says it plainly:** "You have 120 posts, back to 3 Mar 2025. The archive continues from there: about 2,180 older posts · 110 pages · ~18 min."
- **Fetch runs no longer measure sources.** The weekly measurement is deleted. Archive planning measures (as today), and the Archive screen shows each source's last measured size with its date, or "not measured yet". The cheap per-run record (stored post count, last fetch time) stays.

## User Stories
1. As the owner, I want an archive to start below the oldest post I have, so that no request is spent on posts I already have.
2. As the owner, I want "everything older" as the default, so that I don't have to pick a number.
3. As the owner, I want the plan to say where the archive continues from and how much is left, so that I know what will happen.
4. As the owner, I want Nitter archives to jump by date, so that 500 stored tweets cost no extra pages.
5. As the owner, I want sources that can't jump to still work as today, so that nothing breaks.
6. As the owner, I want a stopped archive to resume from its checkpoint, as today, so that nothing is fetched twice.
7. As the owner, I want the archive's numbers to say how many posts were new, so that I see what it added.
8. As the owner, I want fewer requests per archive, so that rate-limited sites don't block us (with 0016's pacing).
9. As the reader, I want fetch runs to end when the last source is saved, so that "81 of 81" means done.
10. As the owner, I want the Archive screen to show when a size was measured, so that I know how fresh the number is.
11. As the owner, I want planning an archive to measure the source fresh, as today, so that the plan is right.

## Implementation Decisions
- **The jump is a checkpoint built from what's stored.** Each kind already resumes from its own checkpoint shape (Substack `offset`, Telegram `offset_id`, Telegram bridge `next_page`, Nitter `cursor`). Each kind gets one optional method, `start_checkpoint(stored: StoredRange) -> Optional[dict]`. `StoredRange` holds the stored count, the oldest stored post's date and its external id. The method returns its usual checkpoint shape positioned one page early, or None (Reddit, plain RSS: no change). No other new seam.
- **Planning** (the existing `_plan`):
  - When there's no resumable checkpoint, the start checkpoint is `kind.start_checkpoint(stored range)`.
  - The default target is "everything older": `available − stored` when `available` is known, otherwise unbounded until the source ends.
  - The plan returns `continues_from` (oldest stored date) and `older_posts`.
  - A resumable checkpoint still wins (resume as today).
- **Stored range:** one query in the posts repository: count, oldest `COALESCE(published_at, fetched_at)`, and that post's external id (from metadata) for the source.
- **Nitter by date:** the Nitter kind's start checkpoint is `{mode: "nitter_cursor", search_until: "<YYYY-MM-DD>"}`. Its pager fetches `/{user}/search?f=tweets&q=&until=<date>` for the first page, then follows the page's own cursor. This was checked on the owner's bridge on 2026-10-16: 20 tweets from the `until` day back, plus a cursor.
- **YouTube by position:** the channel listing accepts a start index (yt-dlp's playlist start). The archive passes `stored + 1 − page` as the start.
- **Counting:** the archive result already reports `posts_inserted`, and the plan, job message and progress show that number as "new". Because the archive starts below what's stored, fetched ≈ new. Kinds keep counting fetched posts toward their target.
- **Deleting the measuring phase:** remove `inspection_due`, `ARCHIVE_INSPECT_INTERVAL_HOURS` and its environment variables, and the inspect call from the run's post-save refresh. Keep the cheap write: `source_type`, `posts_fetched`, the stored count, and the last live fetch time. The run's "inspected" phase and its progress event go. Each catalog row carries its `last_inspected_at` (already written by planning), shown as "measured 3 d ago" or "not measured yet".
- **Docs:** `design/docs/pages/sources.md` (archive section), `BACKEND.md` (the ingestion phases), `scripts/README.md` if it names the interval, and `DEPLOYMENT.md`, removing the env vars.

## Testing Decisions
- **Kind tests with `FakeHttp`** (prior art: the kind archive tests):
  - each jumping kind's `start_checkpoint` for a stored range gives the expected shape, one page early;
  - the Nitter pager's first request is the `until` search, and it then follows the cursor;
  - Reddit and plain RSS return None.
- **Planning tests** (DB, scratch source):
  - with 120 stored posts the plan reports `continues_from` and `older_posts`, and its checkpoint is the kind's start checkpoint;
  - a resumable checkpoint wins;
  - no target means everything older.
- **Runner test:** a run records the cheap metadata and never calls `kind.inspect`, and its phases have no "inspected".
- **Frontend:** the archive plan renders "continues from" and "older posts"; a catalog row renders "measured …" or "not measured yet". Prior art: `archiveSection.test.tsx`, `SourcesConfig.ingestion.test.tsx`.

## Out of Scope
- Finding holes in the middle of a stored range. The jump assumes the newest range is complete; 0012's hourly polling of busy feeds makes holes rare.
- Reddit archives (blocked by Reddit) and archives for plain RSS feeds.
- Pacing and 429 handling (issue 0016).
