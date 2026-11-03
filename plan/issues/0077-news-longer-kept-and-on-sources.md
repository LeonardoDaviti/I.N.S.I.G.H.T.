# 0077 — News: a longer view, every row kept, and News and Classics on a source's page

Status: **spec** for v9.16, decided by the owner 2026-11-04. It ships next to 0076 and merges on its own (the merge rule, 0075).

**Constraints:** download nothing; no real channel names in committed files; measure on a copy of the lab; nothing merges unless `scripts/realdata-check.sh` passes.

## Why (the owner, 2026-11-04)
- "Only 3 days covering for news is too low… I want to go deep."
  - News shows the stories whose first post is in the last 7 days (`news_rules.NEWS_DAYS`).
  - A story is News only once 2+ voices cover it, so the newest days fill late, and the view feels shorter than 7 days. The server had 22 rows, from 28 Oct to 2 Nov.
- "Nothing should be deleted, we need to keep everything."
  - `NewsRepository.write_news` makes `news_stories` exactly the job's window: a windowed run deletes every News row it didn't recompute.
  - On the lab, stories go back to 2025, but News only covers 4–29 Oct.
  - The rows can be derived again from the posts (nothing the owner wrote is lost), but the history disappears from the product.
- "When I read a source I want to check news."
  - The reader hides News and Classics on one source (`ReaderPage`: `oneSource` forces the stream; 0051 made them views of the Main feed and tracks only).
  - The API already answers `GET /api/news?scope=source:<id>`.

## Decided
1. **Every News row is kept.**
   - A run writes and updates rows inside its own window, and deletes only rows inside that window that it no longer finds.
   - Rows before the window stay as they are.
   - A full run may still remove a row whose story no longer exists, but only as a counted, reported change, never silently. (A post is never deleted by any of this.)
2. **Longer view (A):**
   - News shows 30 days (`NEWS_DAYS = 30`) in the parts "Last 48 hours", "This week", and then one part per earlier week ("Week of 12 Oct").
   - Each part is sorted by score, as today.
   - It is paged by the existing cursor.
3. **News and Classics on a source's page:**
   - One source offers Stream / News / Classics.
   - Its News lists the stories with a post from that source.
   - Each row says the source's part:
     - **Started it**: its post is the story's origin;
     - **Covered**: it reported the story;
     - **Shared**: a share or repost;
     - **Mentioned**: a roundup that lists the story.
   - Its Classics lists the classics the source cites.
   - The API adds that part to each row of a source-scoped answer (`news.scope_role`, `classic.scope_role`), computed from what the job already stores (`news_posts.role`, the origin flag).
4. **A source with nothing** shows a quiet empty line ("No News from this source yet: News needs 2+ sources on one story"), not an error.

## Slices (each owns its files; none shares one)
- **F, the reader (frontend only):**
  - files: `pages/ReaderPage.tsx`, `components/reader/NewsList.tsx`, `components/reader/ClassicsList.tsx`, `lib/news.ts`, `lib/classics.ts`, and their tests;
  - it does not touch `services/api.ts` (held by 0072 A);
  - it reads `scope_role` when present, and the week parts from `news.first_at`.
- **K, keep and widen (backend):**
  - files: `db/repo_news.py`, `services/news_service.py`, `utils/news_rules.py`, `tests/test_news.py`;
  - **starts only after 0072 A merges** (those are its files);
  - delete only inside the window, `NEWS_DAYS = 30` with the week parts, and `scope_role`.

## Measured before adopting
- The News view's answer time and size at 30 days on the lab (Main feed, a track, one large source), against 7 days.
- The rows a windowed run keeps against a full run, row by row: after K, a full run and a run of windowed runs must give the same `news_stories`.
- Optional, not decided: News for every date (one full fill) is measured on the lab copy for time and memory before it's offered.

## Not in this issue
- New News rules; Mark X's events.
- Classics' own window.

## Built
### F, the reader (branch `issue-0077-reader`, 2026-11-04)
- **Parts by week** (`lib/news.ts` `newsPart`, `inNewsParts`):
  - "Last 48 hours" is still the API's `part === 'recent'`;
  - "This week" is a story begun since Monday (local time);
  - each earlier week is "Week of 12 Oct" (its Monday; another year adds the year).
  - The reader groups the rows by part, newest part first, and keeps the API's order (score) inside each part, so it works before and after K whatever order K sends across parts.
- **One source's page** (`ReaderPage`): `?view=news` and `?view=classics` now open the source's News and Classics (`GET /api/news?scope=source:<id>`, the classics equivalent); `?view=by_source` stays its stream.
  - Moving to a source from the rail while in News or Classics keeps that view (the rail already carried `view`).
- **The source's part**: a News row's line starts with "Started it", "Covered", "Shared" or "Mentioned" when the row carries `news.scope_role`; a classic's line does the same from `classic.scope_role`. Typed optional in `lib/news.ts` (`ScopedNews`) and `lib/classics.ts` (`ScopedClassic`), not in `services/api.ts` (0072 A holds it). Absent or unknown: nothing shown.
- **Empty**: a source with no News says "No News from this source yet" / "News needs 2+ sources on one story."; with no Classics, "No Classics from this source yet". No action, no error.
- **Not done in F, needs a file outside F's list**: the toolbar's View choice. `FeedToolbar.tsx` hides View on one source (`oneSource ? null : …`), so the page has no Stream / News / Classics choice on screen yet; it needs View on one source with By source left out.
- **Checks**: node tests 216 pass, vitest 694 pass (49 files), `tsc` clean, eslint clean on the touched files. Bundle: the feed route 0.93% over the baseline (main 0.92%), the post route 0.63% (main 0.62%).
- **Left for K**: `scope_role` on source-scoped rows; `NEWS_DAYS = 30` (until then the earliest week parts stay empty); paging past the first page (NewsList still loads one page); the main News empty line still says "No news this week".
