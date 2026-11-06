# 0122 — Saving a page of a source you follow: fetch that source first, and save it as the source's post

Status: **built** (2026-11-06) on branch `issue-0122-fetch-source-before-saving`, not merged, not pushed. From the owner's report the same day. Mark IX (the save path, ingestion's post writer, the reader). Builds on 0031 (Save any page), 0084 B (whose page an address is) and 0114 (why a followed source's page isn't stored yet).

**The owner (2026-11-06):** "when we see a post whose source feed was not yet fetched and we don't have this post, saving should first check the post under the source and the source should be fetched, not save suggested."

**Constraints:**
- every fetch goes through the existing fetch path: the job row and its lock, the fetcher, the host gates and learned budgets (0107), the source's backoff;
- no automatic or background fetch: only the owner's click;
- keep everything: never delete a post; the reader state (read, Later, Keep, the place left) stays with the post;
- download nothing from the development machine; tests stub every request;
- no real names in committed files;
- fix the class, never a site;
- nothing merges unless `scripts/realdata-check.sh` passes.

## Why: what happens today
**The case (6 Nov, details private):**
1. News shows a story whose original is a page of a site you follow (an RSS source, medium tier, fetched every 24 hours).
2. The page isn't stored: the source's feed was last fetched before the page came out. 0114's case.
3. The story's tree offers its origin as an outside page. Its line opens Save any page (`/save`), so the owner saves it.
4. The page becomes a post of the **Saved** source. The reader says "Saved / <date>", with no source, though the owner follows the site.
5. The feed, fetched 10 minutes later, brought a post of the same day, but not this one.

**Where the reader offers to save a page INSIGHT doesn't store** (every one ends in `POST /api/saved`, `SavedService.save`):
- a story's outside origin, in a feed row's tree and on the post page (`lib/story.originHref`, to `/save`);
- Classics: Read and Later on a classic that is an outside page (`ClassicsList`);
- ⌘K "Save a page…" and the bookmarklet (`/save`).

Discover only links outside pages; it saves nothing.

**What `save` does:** a page already stored (its address or where it redirects, normalised) is "already". Otherwise the page is read and stored under the Saved source, in Later. It never asks whether the page belongs to a source you follow.

**What happens when the source's feed later brings that address** (`PostsRepository.upsert_post`):
- **the same address:** `ON CONFLICT (url)` updates the saved row with the feed's text, but never its `source_id`. One post, still Saved's: the reader keeps saying "Saved";
- **another form with the same title** (0049): the same row, still Saved's;
- **another form with another title** (a page's title against the feed's): a **second post**, under the source. Two posts for one page.

## What it does
**1. Whose page it is.** The page's address is matched to a followed (enabled) source by 0084 B's rule, `linked_rules.OwnPages` (one rule, learned from every source's stored posts):
- on a platform, a post of the account a source follows;
- elsewhere, an address of the shape of the source's stored posts on its publication.

Saved and Hacker News own nothing. A source you don't follow, or a disabled one, owns nothing.

**2. Fetch that source first.** When a followed source owns the page and it isn't stored:
- the save page says **"Fetch <source>"** instead of Save, and "<page> is a page of <source>, which you follow. Its feed is fetched first";
- the click runs that source's normal live fetch now, as Fetch now does (an `ingestion_run` job of that source, `start_job_unless_running`, with the host gates and budgets);
- **a fetch is never repeated:**
  - a fetch of that source already running is waited for;
  - a source tried in the last **15 minutes** (0114's floor) isn't fetched again;
  - a source in backoff (failures, before its retry time) isn't fetched;
  - in those cases the save goes on at once (step 4).
- Classics' Read and Later do the same (their toast says "Fetching <source>…").

**3. The fetch brought it.** The answer is the source's own post: "Found in <source>", with Read it. It goes to Later, as every save does. Nothing new is stored by the save.

**4. The fetch didn't bring it** (the feed doesn't list it, or the fetch failed): the page is saved, **as the source's post**:
- `source_id` is that source; `metadata.saved_by_owner` is the save time;
- the reader says **"<source> · saved by you"** (the post page and feed rows), not "Saved";
- dated by the date the page states (0063).
  - A page that states none is dated by the first stored post linking it, never later than the save.
  - 0113's measure: a page dated at its save time pulls its story apart (31 of 50). Dated near its first link, 48 of 50 joined.
  - It sorts at the save time (`surfaced_at`), as every save does.
- It's in Later, unread.

**5. When the feed later brings the same page: one post.** In `upsert_post`, before the insert:
- **a page saved as the source's post** (`saved_by_owner`, the same source) at the same normalised address is that post: it is updated, at the feed's address. The same address already was (`ON CONFLICT (url)`); now another form is too, whatever its title;
- **a page saved under Saved** (saved before this issue, or a page no source owned then) at the same normalised address, when the incoming source owns the page (step 1's rule): that row **moves to the source** (`source_id`), keeps `saved_by_owner`, and takes the feed's text and date;
- **one row, its id kept:** read, Later, Keep, the place left, notes and opens stay. Nothing is deleted;
- a source that doesn't own the page (a link blog whose items are the pages they link, an aggregator) never takes a saved page; it's as today;
- `saved_by_owner` is kept on every later update, as 0062's page tries and 0108's moves are.

**6. A page no followed source owns:** as today (the Saved source, its date, Later).

## Not added: automatic fetches
- Nothing fetches by itself. Only the owner's click fetches, at most once per source per 15 minutes.
- 0114, the automatic fetch when a story links a followed source's page, was measured at +1.44% requests against its 1% bar. This issue adds none of those requests: it isn't 0114, and it doesn't use 0114's budget.
- When 0114 is built, its early fetch makes this path rarer: the page is usually stored before the owner sees it.

## Done when
- Tests, every request stubbed:
  - a followed source's page: the save starts one fetch of that source; a second save while it runs, or within 15 minutes, starts none;
  - found by the fetch: "already", the source's post, in Later;
  - not found: saved as the source's post, `saved_by_owner` set, dated by the page, else its first link;
  - not followed: Saved, as today;
  - the feed brings the page later at another form and title: one post under the source, its reader state kept;
  - a page saved under Saved before: moved to the source that owns it, never to a link blog.
- The real-data check passes. No lead change comes from this issue: it changes nothing until a save or a fetch.

## Built (branch `issue-0122-fetch-source-before-saving`, 2026-11-06)
From main e162228 (v10.0.3). No migration. Nothing was fetched from this machine: the tests stub the fetch job and every page.

**Backend:**
- `db/repo_linked.page_source(cur, url)`: 0084 B's `OwnPages` for one address, over the followed (enabled) sources. `linked_not_stored` shares the same builder (`_followed`, `_own_pages`), unchanged in what it returns.
- `services/saved_service.py`:
  - `save(..., fetch=, after_fetch=)`: the owner is looked up first. Then `fetch_plan`: a running `ingestion_run` job of the source (started within the hour) is reused; tried in the last 15 minutes (`REFETCH_WITHIN`) or in backoff means no fetch.
  - Not found: saved with `source_id` the source and `metadata.saved_by_owner`. A page with no date of its own is dated by `first_linked` (the first stored post linking it, never later than the save).
  - `stored_post` also answers the post's source.
- `main.py`:
  - `GET /api/saved/source?url=` answers `{source}`;
  - `POST /api/saved` takes `after_fetch` and gives the service its fetch: `start_job_unless_running("ingestion_run", source_id=…)`, then `_run_ingestion_job` in the background, as Fetch now (`force`: cadence ignored, backoff checked first, the host gates and budgets apply in the fetch).
- `db/repo_posts.upsert_post`:
  - `_saved_copy` runs first (step 5). One indexed lookup per post. `OwnPages` is built only when a Saved row is at that address.
  - `saved_by_owner` is kept by every update (`_post_update_assignments`), as `page_update` is.
- `utils/post_fields.SAVED_KEY`; `db/repo_reader._ITEM_COLUMNS` gains `saved_by_you` (a followed source's post with `saved_by_owner`).

**Frontend:**
- `api.savePage(url, title, {onFetching})` does the two steps: on `fetching` it waits for the job (`waitForJob`; a failed fetch still goes on), then posts `after_fetch`. Every caller gets it: `/save` and Classics.
- `/save` asks `api.pageSource` for a page from a link or the bookmarklet:
  - the button reads **Fetch <source>**, with the line "A page of <source>, which you follow: its feed is fetched first…";
  - while it fetches, **Fetching <source>…**;
  - then **Found in <source>**, or **Saved as <source>'s post**.
- Classics toast "Fetching <source>…".
- The reader shows "· saved by you" after the source's name: feed rows (`saved_by_you`) and the post page (`metadata.saved_by_owner`).
- Bundle: the feed route 174,595 gzip bytes (+0.14%), the post route 314,919 (+0.09%).

**Tests:** backend 1,879 (OK, 1 skipped), including `test_save_fetch_first.py`, 13 tests:
- the rule, and a disabled source owning nothing;
- one fetch, reused while it runs;
- found by the fetch;
- not found: the source's post, dated by the page;
- undated: dated by the first link;
- 15 minutes, and backoff: no fetch;
- not followed: as today;
- the feed's other form and title: one post, the reader state kept;
- a Saved row moving to its source, and another form of it;
- a link blog never taking a saved page.

Frontend 240 node + 749 vitest, `npm run build` within the gate.

**The real-data check** (`insight_lab`, main against this branch): **PASS**.
- No case changes state.
- Every invariant is equal to main's.
- The diff is 0 for every derived thing (titles, stories, origins, News, Classics, Discover). That's expected: nothing changes until a save or a fetch.
- Two runs before it were loaded: three checks ran at once, at load 18–54.
  - The first crashed in its report: main's `markx.api_during_run`, when "not measured", put its seconds where its examples go. Fixed here, as on 0121's branch (`checks/job_checks.py`, `checks/report.py`).
  - The second was "not measured" for load alone.

**Measured** (read only, `insight_server_1105`):
- **1 Saved post on the server's copy.** No followed source owns it, so it is unchanged.
- **`page_source` costs 0.41 s a call** there: it learns every followed source's shapes. A save pays it once; a feed's post pays it only when a Saved row is at its address.
- **How well the rule ties a page to its source.** Every followed source's post of the last 30 days, asked by its own address:

  | kind | posts | its own source | none | another source |
  |---|---|---|---|---|
  | websites | 1,683 | 1,531 | 140 | 12 |
  | Telegram | 767 | 767 | 0 | 0 |
  | Reddit | 1,437 | 1,437 | 0 | 0 |
  | X | 783 | 499 | 279 | 5 |
  | YouTube | 113 | 0 | 113 | 0 |
  | Hacker News | 62 | 0 | 59 | 3 |

  - *None* is a save as today: under Saved.
  - On X, *none* is mostly other accounts' tweets stored as reposts, and *another* is a followed account's own tweet, which is right.
  - YouTube watch pages name no channel (0084 B).
  - **All 12 websites under *another source* are one site that two sources follow** (its blog's feed and a page watch of one section). 0084 B gives the section's address shape to the source with more posts there, so a save of that section's page would fetch the blog's feed, then save the page as the blog's post. That is 0084 B's tie rule, kept here (one rule).

**For the owner:**
1. **Saved as the source's post** (`source_id`), not a Saved post with a note.
   - It reads as the source everywhere (feed, News, stories, the source's own list), counts as its voice, and the feed's later copy is the same row.
   - `saved_by_owner` says you saved it. It stays after the feed brings the page.
2. **A page that states no date** is dated by the first stored post linking it, so it can't pull its story apart (0113). Saves of pages no source owns still take the save time; that's 0113's fix.
3. **Your page saved before this build** (a Saved post of a source you follow) moves to that source when its feed brings it. Not before: nothing rewrites stored rows.
4. **Not detected:** the scheduler's full run fetching the same source at that moment. Its job has no source id, so a second fetch of that source may run beside it, under the same host gate.
