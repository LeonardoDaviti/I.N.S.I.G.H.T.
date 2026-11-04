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
- **One source's page** (`ReaderPage`, `FeedToolbar`, the latter approved for F by the coordinator): View is Stream / News / Classics (By source left out, no Posts choice), opening the source's News and Classics (`GET /api/news?scope=source:<id>`, the classics equivalent); `?view=by_source` stays its stream.
  - Moving to a source from the rail while in News or Classics keeps that view (the rail already carried `view`).
- **The source's part**: a News row's line starts with "Started it", "Covered", "Shared" or "Mentioned" when the row carries `news.scope_role`; a classic's line does the same from `classic.scope_role`. Typed optional in `lib/news.ts` (`ScopedNews`) and `lib/classics.ts` (`ScopedClassic`), not in `services/api.ts` (0072 A holds it). Absent or unknown: nothing shown.
- **Empty**: a source with no News says "No News from this source yet" / "News needs 2+ sources on one story."; with no Classics, "No Classics from this source yet". No action, no error. The Main feed's and a track's empty News now says "No News yet" (true at 30 days, not only a week).
- **Checks**: node tests 216 pass, vitest 695 pass (49 files), `tsc` clean, eslint clean on the touched files. Bundle: the feed route 172,774 B gzip, 0.95% over the baseline (main 0.92%); the post route 312,769 B, 0.64% (main 0.62%).
- **Left for K**: `scope_role` on source-scoped rows; `NEWS_DAYS = 30` (until then the earliest week parts stay empty); paging past the first page (NewsList still loads one page).
- **Design docs**: `src/design/docs/pages/reader.md` updated at the merge (week parts, one source, the empty lines).

### K, keep and widen (branch `issue-0077-news-kept`, 2026-11-04)
On main e03c5cf (0072 A merged); not merged, not deployed. No migration, no new stamp: the first start rebuilds nothing. Nothing fetched or downloaded: the code ran mounted on the local `insight-backend` image built from the branch. Measured on scratch `pg_dump`s of `insight_lab` (41,637 posts), clock its last fetch (2026-10-30 21:32). The machine was shared: load 9–13 all along.
- **Every News row is kept** (`NewsRepository.write_news(…, since=)`):
  - a run (full or incremental) writes and updates the rows of its window (the stories begun in the last `NEWS_KEEP`, 30 days); it deletes a row of that window it no longer finds;
  - a row begun before the window stays as it is (its numbers and its posts); a post of it the run places nowhere stays in it; a post the run places in a row of its window moves there;
  - a row before the window left with no post (all moved to rows of the window) is removed: the one way a full run removes a row outside its window. Every removal is counted: `news_removed` in the job's result (full and incremental), never silent. A post is never deleted by any of this.
  - The incremental job no longer reads every stored row begun before the window (`news_before`, gone): with rows kept, it had nothing to delete, and it would have regrouped all of News's history every run. The window's edge (`window_posts` between the last run's start and this one's) still brings in what crossed it.
  - **What a full run keeps, so both agree:** exactly what the runs before it left before the window, minus the rows with no post left; inside the window it rebuilds as before. So a full run after a sequence of incremental runs writes nothing (the identity check, below). A full run on an empty `news_stories` still makes only the window: history before it is what the runs kept (a fill of every date is the spec's optional item, not built).
- **30 days:** `NEWS_DAYS = 30`. The API's parts stay `recent` (the last 48 hours) and `earlier`, sorted by part, then score; the reader makes the week parts from `first_at` (F). `GET /api/news` still answers one page (`next_cursor: null`).
- **The source's part** (`scope=source:<id>` only, `news.scope_role`, `classic.scope_role`):
  - News: `origin` when one of its posts is the row's origin (the first post flagged origin, the one the lead is taken from), else the strongest role of its posts (`report`, then `share`, from `news_posts.role`); `mention` when it has no post in the row and a roundup of it lists one of the row's 0050 stories (`story_mentions`). One source's News now also lists those rows (the spec's "Mentioned"); the Main feed's and a track's lists are unchanged.
  - Classics: `origin` when the classic's page is a post of the source (`normalized_url`), else `report`. One source's Classics now also lists its own pages that are classics (its own voice is never a citer, so they were missing).
  - Order `SCOPE_ROLES` in `news_rules.py`.
- **Measured: the answer at 30 days against 7** (`news_on` in process, 5 rounds alternating, median; the JSON as sent; the lab has no track, so a scratch one of the 10 sources with most News rows after the largest):

  | scope | days | rows | bytes | gzip | time (median, min–max) |
  |---|---|---|---|---|---|
  | Main feed | 7 | 27 | 80,404 | 17,105 | 155 ms (143–157) |
  | Main feed | 30 | 100 | 289,796 | 58,866 | 494 ms (430–502) |
  | the track | 7 | 23 | 68,733 | 14,686 | 113 ms (75–148) |
  | the track | 30 | 75 | 230,096 | 45,556 | 397 ms (360–403) |
  | the largest source | 7 | 9 | 47,934 | 8,847 | 94 ms (61–97) |
  | the largest source | 30 | 30 | 140,939 | 23,691 | 234 ms (226–237) |

  Size and time grow with the rows (3.6×), about 2.9 KB a row. **Paging is not needed yet:** the whole 30 days is one answer of 290 KB (59 KB gzipped) in half a second on a loaded machine, and NewsList shows all of it; the frontend was not touched. It would be worth a cursor at a few times today's sources.
- **The parts on the lab:** every source's News (247 sources, 2.4 s): 315 rows, origin 45, report 188, share 45, mention 37. Classics on every source: report 644, origin 20. Hand checks, 3 of each at random: the 3 origins are the release's own blog post leading its row; the 3 shares are reposts (`RT by …`) or a link post; the 3 mentions are a source's roundup listing the story, with no post of it in the row. All right.
- **Kept rows, a sequence of runs against a full run, row by row** (`scripts/story_identity.check` with the clock moving, so News's window passes rows; then every derived table against a full run over the same posts):

  | held back | fetches | clock | main: `news_stories` after | K: after (before the window) | removed, counted (each run) | K against a full run |
  |---|---|---|---|---|---|---|
  | 300 | 10 | +72 h each (30 days) | 0 | 101 (101) | 12 (the first full run: the lab's rows by older code, inside the window), then 1, 1 | identical, every table |
  | 3,000 | 10 | +48 h each (20 days) | 42 | 94 (52) | 6, then 1, 3 | identical, every table |

  Main's runs empty News as the window passes; K's keep the rows, and the 42 rows in the last window are the same as main's. Main's check is identical too (it deletes the same in both).
- **Tests** (`test_news.py`, `test_incremental_stories.py`): 30 days and `recent`; a row past its window kept as it was, its posts in it, a second run writing nothing; a row in the window no longer found removed and counted; a row before the window with no post left removed and counted; one source's part in News (origin, report, share, mention) and in Classics (origin, report), none on the Main feed; the incremental job keeps a row past its window, a post joining that old story later doesn't rewrite it, and a full run after each changes nothing (was: "a story leaves News when its window passes").
- **Suites:** backend 1,342 tests OK (`./run-tests.sh`, own image tag). Frontend not touched.
- **The real-data check (0075, `scripts/realdata-check.sh insight_lab`): PASS** with one `--allow`. No judged case changes state (62 pass, 14 fail as on main, 17 not checked); `story.identity` 0 of 720,741 rows, `story.rebuild_identity` 0; the diff: **News 73 new rows** (the view 27 → 100: 30 days, not 7), nothing else (titles, text, roundups, stories, origins, Classics, Discover: 0). On the lab copy every stored row is inside the 30 days at its clock, so the stored rows don't grow there; they grow as the window passes (the table above).
  - **Allowed:** `label.news_voices` 1 → 7 (of 100 rows; main reads 27). At 7 days the branch counts the same 1 as main; all 7 hold a Reddit source, whose authors are voices while the source is named once (0069), a label rule this slice doesn't touch. The first run, without the `--allow`, failed on it alone.

## Left open (K)
- **History before the first K run is gone** (lab and server): the rows earlier runs deleted come back only by a fill of every date (the spec's optional item: not measured, not built).
- **A kept row's numbers are as they were when it left the window:** a post that later joins its story, or a removed source, doesn't change it; a post the window's rows take moves out of it (the row can then count more voices than it lists). Rows are read only within 30 days today, so none of this shows yet.
- **A row in the window whose story now begins before it** (an earlier post joined) is removed, counted: the spec's "inside its window, no longer found". 1–3 per sequence above.
- **`label.news_voices`** (Reddit authors as voices, their source named once) shows on 7 of 100 rows at 30 days.
- **Paging:** not built; one answer of 290 KB (59 KB gzipped) at 30 days.
