# 0054 — Source anatomy: how each source is read, and what it gives

Status: **built, not deployed** (2026-10-30; design decision 037) for v9.6 (owner, 2026-10-30: "do we have a page … for the sources? I want to display how sources are built and what they build. So add them near the ingestion page.").

## The case
- **No page answers "how is this source read, and what does it give me?" for all sources at once.**
  - Sources → Ingestion shows the scheduler, the last run, the archive, jobs and logs.
  - A source's sheet shows its settings and health, one source at a time.
- **0050 and 0051 add new things a source gives:** stories it covered, stories it reported first, classics it cited, sites it points Discover to. These live nowhere per source.
- **On the server's data the gaps are real:**
  - 99 sources have no name of their own;
  - a quarter of Telegram and X sources never appear in a story;
  - HN takes articles from sites the owner follows (0017).
  - The owner can't see any of that today.

## Decided
- **Where:** a new view in Sources → Ingestion, `?sub=sources`, next to overview, archive, jobs and logs. One row per source. A click opens the source's existing sheet; no new editor.
- **How it's read** (from what INSIGHT already stores; nothing new is fetched):
  - **kind:** feed, page watching, site reader (Gwern), Telegram, X, Reddit, YouTube, Saved;
  - **address**, shown with the shared source-name helper;
  - **full text:** on, off, or the feed carries it;
  - **change watching:** on or off (0039);
  - **conditional fetching:** validators stored or not (0044);
  - **schedule:** its cadence and when it's due;
  - **last fetch:** when, and its last error if any.
- **What it gives** (over the last 30 days, with all-time on hover):
  - posts, and how many you read;
  - stories it's in, and how many it **reported first** (0050's lead);
  - classics it cited (0051);
  - outside links it gave (0050's post links).
- **Sorting:** by any column, as the sources list does (0011). The default order is the most posts.
- **Minimal:**
  - one query per column group, from tables that exist;
  - no new tables, unless a count is too slow (measure on the lab first);
  - no charts, no new settings.

## Done when
- **Backend:** one endpoint for the view, with tests on a `_test` DB covering each column. It answers in under 500 ms on the lab copy of the server's data (41k posts, 240 sources); measured, and recorded here.
- **Frontend:** tests for the view, its sorting, and opening a source's sheet. Screens in light and dark, wide and narrow.
- **Checks:** backend suite and frontend checks green; bundle within the 1% budget (lazy-load the view if needed).

## Built
- **Backend:** `GET /api/sources/anatomy` (`services/source_anatomy_service.py`, `db/repo_source_anatomy.py`), read only, nothing fetched, no new table or migration.
  - **How it's read:** the kind the runner resolves, in words (`feed`: generic RSS and Substack; `page_watch`; `site_reader`: any site adapter, Gwern and LessWrong among them; `telegram`, `x`, `reddit`, `youtube`, `saved`). A Reddit `.rss` address is read as a feed, so it says Feed.
  - **Full text:** `off` for a feed with `fetch_full_content: false`; `on` for a feed that read some post's article page (`full_content_fetched`), and for the kinds whose posts are pages (page watching, site reader, Saved); `feed` otherwise (the feed or platform carries the whole post).
  - **Change watching:** the health row's own `watch_changes`, `null` for a kind that cannot watch, with the count of watched pages. **Conditional fetching:** validators stored or not for a kind that fetches conditionally, else `null`.
  - **Schedule and last fetch:** the source health row's own fields (`health_row`, the same decision the runner makes), so this view and the Sources list never disagree.
  - **What it gives,** last 30 days and all time, by a post's feed date (`COALESCE(surfaced_at, published_at, fetched_at)`), one query per group: posts and **read** (opened: an `opened` or `reading_session` interaction, as History counts it, never a bulk mark read); stories its posts are in and how many it **leads** (0050's lead: the first report, else the first share); **classics** it links (not hidden ones, not through a signature link, not from Saved); **outside links** (0050's post links, less signatures and its own site).
  - The schedule view and the counts run in one read-only transaction with **JIT off**: on the lab copy, compiling the schedule view's plan cost about 300 ms of 350 ms.
- **Frontend:** `?tab=ingestion&sub=sources`, a lazy chunk (`components/sources/SourceAnatomy.tsx`, 8.1 KB; words and order in `lib/sourceAnatomy.ts`). One table: the name (sticky; a source without its own name is named by `sourceLabel` from its address, in a quieter tone), How it's read (Kind, Full text, Watch, If changed, Every, Last fetch with its error), What it gave · 30 days (Posts, Read, Stories, First, Classics, Links; all time on hover). Every header sorts (the sources list's direction rules and arrows), the most posts first. A row, or its name, opens the existing sheet: `?source=` now opens it over this view too, and the sheet's changes refresh it. A phone scrolls the table sideways under the sticky name.
- **Speed** (the lab copy of the server's data: 240 sources, 41,562 posts, 141,863 post links, 572 stories, 181 classics):
  - `EXPLAIN ANALYZE` on `insight_lab`, read only, JIT off: posts and read 42 ms, stories 10 ms, links 61 ms, classics 6 ms, how it's read 1 ms, the schedule view 35 ms.
  - The whole endpoint on a `_test` copy of `insight_lab` (own API container): **about 155 ms over HTTP** (205 ms the first call); the service alone 141 ms median of 6. Before JIT was turned off it was 486 ms.
- **Tests:**
  - Backend `test_source_anatomy.py` (12): every kind and full-text rule over the real kind registry; an empty source counts zero; on a `_test` database every column (posts and read in and out of the window, a favorite is no read; stories and who leads, a report beating an earlier share; classics once, the hidden one not, a signature link not; links without signatures; full text on, off and in feed; watching and watched pages; validators; the last error; the default order); the route. **Suite: 978 tests, OK.**
  - Frontend `lib/sourceAnatomy.test.ts` (5: every column's order, the default, reversing, names from addresses, the cells) and `pages/SourcesConfig.anatomy.test.tsx` (6: the view next to the overview, the cells and the hover, sorting and reversing, a row opening the sheet and Back closing it on the view, a click anywhere on the row, the error state). Typecheck, lint, **181 node + 637 vitest tests**, build OK.
  - The reader's initial JS: **479,685 bytes**, +0.97% on the 475,065 baseline (+102 on 479,583: the API method, the view's name and its query key). The limit is 479,815: 130 bytes are left in the budget.
- **Screens** (the dev server against an own API container on a `_test` copy of the lab, light and dark, wide and narrow; not committed): `~/.cache/insight-checks/0054-shots/` (`0054-anatomy-wide-*`, `-narrow-*`, `-narrow-scrolled-*`, `-sorted-first-*`, `-sheet-*`).

## Left open
- **Done after the merge (2026-10-30): JIT is off for every pooled connection** (`db/database.py`). Measured on the lab with JIT off for the whole database: `/api/sources/health` 368 → 75 ms, search 47 → 34 ms, every other endpoint the same or faster.
- **Discover takes 2.6 s on the server's data:** it reads every kept link (138k) in Python per request. Not fixed here.
- **"Read" is opened,** not `read_at`: a bulk mark read is no reading (as 0052 decided). The spec named the read state; say if `read_at` is meant.
- **The 30 days go by a post's feed date,** so an archive backfill of old posts counts in all time, not in the window.
- **Full text `in feed` for a feed with full text on** means no post needed its page so far; a feed whose page reads all failed reads the same (its reading notice on the sheet says so).
- On the lab copy 101 sources have no name of their own (the spec's 99 was counted earlier).
- No search or filter on the view: sorting was what the spec asked for.
