# 0015 — Smart archiving: continue below what I have, and no measuring phase in fetch runs

Status: **built** 2026-10-16, not yet deployed (designed with the owner, 2026-10-16).

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
  | Telegram (account) | by position | `offset_id` = oldest stored message id (exact: no overlap needed) |
  | Telegram bridge | by position | `next_page` = stored ÷ the raw page size (always at or before the oldest stored post) |
  | YouTube | by position | channel listing starts at video number stored + 1 − one page |
  | Nitter | by date | the bridge's search RSS, `until` = the day after the oldest stored tweet (`until` is exclusive); then its cursor |
  | Reddit | — | the archive is blocked by Reddit (403); unchanged |
  | Plain RSS | — | a feed holds only its latest posts; unchanged |

- **Overlap a little, never compute exactly.** Each position jump starts one page early (the Telegram account's exact id needs none), and Nitter one day early. Duplicates are already handled by the URL upsert, and the overlap also absorbs posts deleted at the source.
- **The plan says it plainly:** "You have 120 posts, back to 3 Mar 2025. The archive continues from there: about 2,180 older posts · ~18 min", or "… continues from 3 Mar 2025 · size unknown" when the source doesn't say its size (Substack).
- **An archive runs until the source ends.** The "Posts to fetch" field goes.
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
- **The jump is a checkpoint built from what's stored.** Each kind already resumes from its own checkpoint shape. Each kind gets one optional method, `start_checkpoint(stored) -> Optional[dict]`, returning that shape with `collected_posts: 0, pages_fetched: 0`, or None (Reddit, plain RSS, and any kind that can't jump). `stored` is the existing `get_source_post_stats` result, extended with the oldest post's `external_id` (the `posts.external_id` column); it already has `post_count` and `oldest_published_at`. No new query and no other new seam.
- **Per kind:**
  - **Substack:** `{mode: "substack_offset", offset: max(0, stored − ARCHIVE_PAGE_SIZE)}`.
  - **Telegram account:** `{offset_id: <oldest stored external_id>}`. `offset_id` returns older messages, so it is exact. If the external id is missing or not an integer, return None.
  - **Telegram bridge:** `{mode: "telegram_page", next_page: max(1, stored // raw_page_size)}`. `raw_page_size` is the source URL's `?limit=` value, or else the item count of the unfiltered page 1. The filtered count is smaller and would skip posts.
  - **YouTube:** `{mode: "youtube_channel", playlist_start: max(1, stored + 1 − DEFAULT_PAGE_SIZE)}`. `archive_channel_posts` and `_list_channel_entries` gain `start` (yt-dlp `--playlist-start start`; `--playlist-end` only when a target is given). `YouTubeKind.archive_pages` reads `playlist_start` from its checkpoint. It stays a single-shot listing (one long call that can't pause).
  - **Nitter:** `{mode: "nitter_cursor", search_until: "<oldest stored day + 1, YYYY-MM-DD>"}`. Its first page is `/{user}/search/rss?f=tweets&q=&until=<search_until>`. Later pages are the same URL plus the `min-id` header cursor, the same mechanism as today's pager. This was checked on the owner's bridge on 2026-10-16: RSS, 20 items, a `min-id` header, and `until` exclusive. Every page's checkpoint keeps `search_until`, so a resume stays on the search.
- **Resume vs jump.** A checkpoint carrying `completed_at` (a finished archive) is never resumable. This check goes in one place, a helper in the archive metadata module, used by both `_plan` and `resume_ready`. A resumable checkpoint wins; otherwise the start checkpoint is used. `_archive` always starts from `plan["checkpoint"]`, which is either the resume checkpoint or the start checkpoint (today it passes one only when resuming).
- **Planning measures once.** `_archive` reuses the inspection from the plan it was given, instead of calling `_plan` (and `kind.inspect`) a second time.
- **Target.** An archive runs until the source ends. The target given to kinds is "no limit". For kinds that need a number, use `available` if known, else a large sentinel. The plan's `older_posts` (`available − stored`, or None) is for the estimate only.
- **Remove the "Posts to fetch" field** and everything only it used: the field in the archive section, `desiredPosts` in the request path, `archivePresets`, `clampDesired`, `defaultDesired` and `archiveCeiling` in the archive lib, and the backend's `desired_posts` parameter if nothing else sends it. No dead code.
- **Delete the measuring phase:**
  - the inspect half of the post-run refresh (`inspection_due`, `ARCHIVE_INSPECT_INTERVAL_HOURS`, the `INSIGHT_REFRESH_ARCHIVE_METADATA` and `SAFE_INGEST_REFRESH_ARCHIVE_METADATA` env vars);
  - `DbInspectionRefresher`'s `gates`, `clock` and interval parameters;
  - the `inspected` branch in the archive metadata writer;
  - `"inspected"` in the progress phases (`"saved"` becomes 100).

  Keep the cheap write: `source_type`, `posts_fetched`, the stored count, and the last live fetch time. Rewrite the module docstring.
- **"Measured".** Catalog rows gain `last_inspected_at` (written by planning), and `ArchiveCatalogEntry` gains the field. The catalog and the sheet both say "measured 3 d ago" or "not measured yet". The sheet's current "checked …" becomes "measured …".
- **Docs:** `design/docs/pages/sources.md` (archive section), `BACKEND.md` (ingestion phases), and `DEPLOYMENT.md` and `scripts/README.md` wherever they name the removed env vars.

## Testing Decisions
- **Kind tests with `FakeHttp`** (prior art: the kind archive tests):
  - each kind's `start_checkpoint` for a stored set gives the expected shape;
  - the Telegram bridge uses the raw page size, not the filtered one;
  - the Nitter pager's first request is the search RSS with `until`, page 2 keeps `search_until` and adds the cursor, and a resume continues on the search;
  - YouTube passes the start to the listing;
  - Reddit and plain RSS return None.
- **Planning tests** (DB, scratch source):
  - with 120 stored posts the plan reports `continues_from` and `older_posts`, and its checkpoint is the start checkpoint;
  - a resumable checkpoint wins;
  - a completed checkpoint doesn't win;
  - `_archive` doesn't inspect a second time.
- **Runner tests:** a run records the cheap metadata, never calls `kind.inspect`, and has no "inspected" phase. Update the runner tests that expect the inspected phase.
- **Frontend:** the plan renders "continues from …" and "size unknown"; there's no Posts to fetch field; catalog and sheet render "measured …" or "not measured yet". Prior art: `archiveSection.test.tsx`, `SourcesConfig.ingestion.test.tsx`.

## Out of Scope
- Finding holes in the middle of a stored range. The jump assumes the newest range is complete; 0012's hourly polling of busy feeds makes holes rare.
- Reddit archives (blocked by Reddit) and archives for plain RSS feeds.
- Pacing and 429 handling (issue 0016).
