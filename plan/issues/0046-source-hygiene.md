# 0046 — Source hygiene: which sources went quiet, which you never read

Status: **built, not deployed** (2026-10-28; migration 0035). Planned for v9.5 (owner, 2026-10-28).

## Why
Sources pile up. Some stop publishing, and some you never open. Neither shows today unless the source is broken (the doctor, 0036, covers broken).

## Decided
- **Two marks, computed from data INSIGHT already has:**
  - **Quiet:** fetches work, but nothing new has arrived for 30 days **and** for more than 3× the source's own usual gap between posts. A monthly newsletter isn't quiet at day 31. Shown as "Quiet: last post 4 Mar".
  - **Never opened:** at least 20 posts over at least 30 days since it was added, and none opened, saved to Later or kept. Shown as "Never opened: 214 posts".
  - Broken sources keep the doctor's notes and get neither mark.
- **Where:**
  - the Sources list shows the mark in its note column, where the doctor's notes already live;
  - a **"Tidy up"** view (a filter of the Sources list, not a new page) lists the marked sources, each with **Remove** and **Keep**.
  - **Keep** dismisses the mark for that source; it comes back only if it's still true 90 days later.
- **Never automatic:** nothing is removed or muted without the owner's click. Removing works exactly like removing a source today (sources.json included).
- **Backend:** the marks come with the health/list data the Sources page already loads, computed in SQL. Migration **0035** only if the dismissal needs storage.

## Done when
- Backend tests cover: quiet against the source's own cadence; never-opened counting opens, Later and Keep; broken sources excluded; dismissal and its 90-day return.
- Frontend tests cover the notes, the Tidy up filter, Remove and Keep.
- A dry run on a copy of the preview data (`insight_preview`, read only): how many sources get each mark, with a few examples, recorded here.

## Built
- **One rule**, `tidy_marks` in `backend/insight_core/services/operations_service.py`, applied by
  `health_row`, so the marks come with `GET /api/sources/health` (and every fresh row a route
  returns). Each row gains `quiet`, `never_opened`, `opened_posts` and `tidy_kept_at`.
- **The counts are SQL**, in `FetchStateRepository.load_schedule_view`: `opened_posts` counts the
  source's posts that are opened (`OPENED_POST_SQL`: a `post_interactions` row `opened` or
  `reading_session`, or a `post_reader_state` with `later_at`, `starred_at` or `resume_block`).
  `read_at` alone does not count: "mark read up to here" sets it on posts never looked at. The
  rule itself runs in Python because "broken" is the health status, which only `decide_fetch`
  knows.
- **Quiet:** the source is on, not failing (`error`/`backoff`), not unavailable, has fetched
  once (`last_success_at`), and its newest post (`max(COALESCE(published_at, fetched_at))`; with
  no posts, the day it was added) is at least 30 days old **and** more than 3 times its mean gap
  (`sources.mean_gap_seconds`, the cadence's latest 20 posts). No known gap (under 3 distinct
  dates): 30 days alone.
- **Never opened:** 20 posts or more stored, added 30 days ago or more, and `opened_posts = 0`.
  "Over at least 30 days since it was added" is read as the source's age, not the posts' spread:
  an archive can bring 200 posts in a day, and that is still too soon to judge.
- **Neither mark** for a failing source (the doctor's note stays), a disabled one (the owner
  already acted), or the Saved source.
- **Keep:** `POST /api/sources/{id}/tidy/keep` writes `sources.tidy_kept_at` (migration
  `0035_source_tidy.sql`; one timestamp for both marks) and returns the fresh row; 404 for no such
  source. Within 90 days of it neither mark shows; after, a mark shows again only if still true.
  The column is on `sources`, not `source_fetch_state`: Keep is the owner's choice, not fetch
  memory, and a success does not clear it.
- **Remove** is the existing delete: the same confirm dialog ("Delete "Unread News"?" / Delete
  source) and `DELETE /api/sources/{id}`, which rewrites sources.json.
- **UI:** the note column reads "Quiet: last post Mar 4" (or "Quiet: no posts yet") or
  "Never opened: 214 posts" (both true: quiet shows, both in the tooltip). **Tidy up** is a
  secondary status chip (`?status=tidy`), shown while it has sources, after Scheduled; in that
  view a marked row shows **Keep** and **Remove…** after its note. Keep drops the row from the
  view at once (the cache is patched, then refetched). Empty: "Nothing to tidy up: no source went
  quiet or goes unopened." Decision 031; `design/docs/pages/sources.md`.
- **Limits:** "nothing new has arrived" reads the newest post's date, so a feed that re-dates old
  posts looks alive. YouTube/Telegram sources that are unavailable on a server (no yt-dlp, no
  session) are never quiet, since their fetches do not run there. The sheet does not show the
  marks: only the list and Tidy up do.
- Tests: `backend/insight_core/tests/test_source_tidy.py` (quiet against the source's own
  cadence, no posts, fetches that work; never opened at 20 posts / 30 days; broken, disabled and
  saved excluded; Keep and the 90-day return, over a fake view and end to end on a `_test` DB;
  the route), `test_repo_fetch_state.py` (`opened_posts` counts open, reading session, Later,
  Keep, part-read, not `read_at` alone; `keep_source`);
  `frontend/src/components/sources/sourceList.test.tsx` (notes, the filter, the URL),
  `frontend/src/pages/SourcesConfig.test.tsx` (notes in the list, the chip, Keep, Remove).

## Dry run on insight_preview (2026-10-28, read only)
The rule as one SELECT (`default_transaction_read_only=on`; `tidy_kept_at` taken as NULL, the
preview has no migration 0035). The preview is a copy whose newest posts are from mid-October
and in which few posts were ever opened (453 opens, no Later or Keep), so "never opened" is high.

82 enabled sources (12 Telegram ones are disabled: excluded); 10 enabled sources are failing:
excluded (the r/… feeds, r/LocalLLaMA, tg.i-c-a.su).

| Mark | Sources | Examples |
|---|---|---|
| Quiet | 14 (8 feeds, 6 YouTube) | modelcontextprotocol/docs commits (last post 8 Apr 2025, gap 0.6 d); karpathy.bearblog.dev (30 Apr, gap 45 d: 181 d > 134 d); DigiLens News (7 Oct 2025, gap 48 d); Vuzix Corporation on YouTube (13 Aug 2025, gap 100 d); The Verge AR/VR and anthropics/skills releases (fetched, never a post, added Aug/Jul) |
| Never opened | 32 | rss.arxiv.org cs.LG (1,025 posts) and cs.CL (985); arXiv physics.optics (510); UploadVR (183); Marques Brownlee (29) |
| Both | 3 | anthropics/courses commits, modelcontextprotocol/docs commits, Solos Glasses Blog (20 posts each) |

Not quiet, as meant: oneusefulthing.org (last post 1 Oct, gap 20 d: 27 d is under 30), Vuzix
Blog (14 Jul, gap 85 d: 106 d is under 3 × 85), RayNeo on YouTube (7 Sep, gap 40 d). The six
YouTube quiet ones are quiet only where yt-dlp runs; elsewhere they are unavailable and unmarked.
