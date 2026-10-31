# 0062 — What the pipeline review found: same address, teasers retried, a shorter update, Discover in the database, background work you can see

Status: **spec** (2026-10-31) for v9.9 (owner, 2026-10-31: "that is already for 9.9, so spec them"). Items 3, 4 and 5 built 2026-10-31 (branch `issue-0062-ops`, not deployed); item 1 moved to 0064.

Found by running the whole update and the recurring work on a fresh copy of the server's data (41,608 posts, 489 MB), and by the owner reading the lab.

## 1. Two posts at one address are one story (moved to 0064, stories as trees, 2026-10-31)
- **The case:**
  - OpenAI News' "Introducing GPT-6.1 Terra" (published 26 Oct 00:00) and Hacker News' "GPT-6.1 Terra" (26 Oct 18:01) are the same article, at `openai.com/index/introducing-gpt-6-1-terra`.
  - Their titles differ, so 0049 rightly keeps two rows.
  - data_secrets, Simon Willison and LessWrong (twice) link that address. Every link resolves to **one** stored post, the first seen, which is HN's.
  - So HN's story has 3 sources, and OpenAI's own post, the original, sits alone with no "covered by". Three posts share an address this way on the lab copy.
- **Decided:**
  - Posts of different sources with the same normalized address join one story, with a new reason, `address`. They're the same page.
  - When one of them is from the site the address belongs to (OpenAI's post on openai.com), it's the story's origin and leads, whatever the dates.
- **Done when:** the case `openai-terra-same-address` passes. OpenAI's post leads a story with HN, data_secrets, Simon Willison and LessWrong.

## 2. Teasers are tried again
- **The case:**
  - Adding OpenAI News read 15 of its 20 articles in full. Then openai.com's bot protection answered 403, and 5 posts stayed teasers ("Introducing GPT-6.1 Terra" is 50 characters).
  - INSIGHT never retries a teaser, so it stays one.
- **Decided:**
  - A teaser whose page read failed (an HTTP error or a timeout, not "the page holds nothing longer") is read again on the source's later fetches: at most 3 tries, at least a day apart.
  - The same rule (0016's pace) and host gate apply. Record the try count with the post.
  - No new setting.
- **Done when:** tests cover a failed read retried, success ending it, the third failure being the last, and a page that holds nothing longer never retried.

## 3. An update takes INSIGHT down for seconds, not minutes
- **The case:** `./update` runs `docker compose down` **before** `docker compose build`, so INSIGHT is offline for the whole build (about 1–3 minutes on the server).
- **Decided:** build first, then restart (`build`, then `up -d`, which recreates only the changed containers). Keep `--refresh` and the version stamp as they are. Say in `DEPLOYMENT.md` that the site is down only while the containers restart.
- **Done when:** the script is changed. A dry run on this machine against a scratch compose project shows the old containers keep serving during the build.

## 4. Discover counts in the database
- **The case:** Discover's first open after each story run takes 2.6–3.3 s, and the API's memory jumps to about **800 MB**. It reads all 138k kept links into Python and counts them there.
- **Decided:**
  - Group and count in SQL: voices per site or account, articles, links. Python only shapes the top suggestions.
  - The result and its order stay exactly as now. Compare on the lab copy: same list, same order.
  - Keep the cache (0050's fix) as it is.
- **Done when:** the first open is under 0.5 s and the API's memory doesn't jump. Both are measured on a copy of the lab and recorded here.

## 5. Background work you can see
- **The case:**
  - After an update the API re-indexes search (83–153 s), reads every post's links (~47 s) and builds stories, News and Classics (~16 s). After every fetch run the story job takes ~6 s.
  - None of this is visible, so after an update the owner can't tell why "covered by" or News are empty.
- **Decided:**
  - A read-only "Background work" block in Sources → Ingestion → overview:
    - **Stories:** last run, how long it took, posts, stories, News and Classics counts, and "next run: after the next fetch run";
    - **Search index:** up to date, or "re-indexing N of M";
    - **Links:** all read, or "reading N of M".
  - From what the jobs already record (the `stories` system setting, counts of posts without a current vector or links), refreshed while work runs.
  - **No controls and no thresholds as settings** (owner, 2026-10-31: checkable, not controllable).
- **Done when:** tests cover each state (running, done, never run). Screens in light and dark, including the state right after an update.

## Done when (all)
- Backend suite and frontend checks green; bundle within the gzip budget (0061).
- Every case in `plan/research/lab/cases.json` that passed still passes.

## Built (items 3-5, 2026-10-31, branch `issue-0062-ops`, not deployed)

### 3. The update builds before restarting
- `./update` no longer runs `docker compose down`. It runs `git pull`, then `build` (the stamp exported as before and passed through `sudo --preserve-env`, `--refresh` still adds `--pull`), then `up -d --remove-orphans`, which recreates only the containers whose image changed.
- `DEPLOYMENT.md` says the build runs while the old containers serve, and the site is down only while the changed containers restart.
- **Dry run** on this machine, a scratch compose project `i0062-scratch` (its own images and ports 18621/18622; the real `insight` project and containers untouched). Three nginx services built from one Dockerfile with a 25 s step, stand-ins for `git` (no network) and `sudo` (keeps only the preserved variables, as sudo does). Both ports polled every 0.5 s while the script ran:
  - old script (`down` first): 52 of 57 samples down, from the start of the build to the restart (26 s);
  - new script: the old build answered for the whole 27 s build (55 samples), then 1 sample down at the restart, then the new build;
  - the stamp reached the images through sudo (`Mark IX v9.9-scratch scr0062 2026-10-31`); `--refresh` (dry, an echo-only docker) passes `build --pull backend ingestion frontend`.
  - The scratch project, its images and the scripts were removed after.

### 4. Discover counts in the database
- `db/repo_discover.py` (new), migration `0046_discover_addresses.sql`:
  - `discover_addresses` keeps what Discover reads of each linked address: its key, site, whether the site is a platform, and whether it reads like an article. Each is worked out once, in Python, by the same function the rules use (`story_rules.discover_address`, which `suggestions()` now calls too), so nothing of `site_of`, `account_key` or `is_article` is written twice. A `rules` fingerprint (the platform and page lists, the article pattern, a version) redoes the rows when the rules change.
  - Filled by the story job after it reads links (`StoriesService.fill_discover_addresses`, one call at the end of `recompute`, never raising), and by Discover itself when an address is missing (the query counts them; Discover fills and asks again). Rows no kept link points to are dropped when it fills.
  - One query: the candidates first, from the addresses alone (2+ article-like addresses, 40%+, not followed or hidden); then only those keys' links are read for their voices (`site:`, `reddit:<author>`, `source:`), 3+ voices kept; the top 20 articles with their voices and the words they are most often linked by. A website voice two sources share is named after the source of its first kept link, as before. Python only sorts and names.
  - The cache (0050's fix) is unchanged.
- **Measured** on a `_test` copy of `insight_lab` (41,689 posts, 138,650 kept links, 576 suggestions), in the backend image with the API's imports loaded, three runs each:

  | | first open | API memory |
  | --- | --- | --- |
  | before | 2.31-2.44 s (2.56-2.67 s after a story run) | +706 MB (peak 765 MB) |
  | after, the first open after a story run | 0.42-0.56 s (the spread is this machine's load) | +9 MB (peak 68 MB) |
  | after, once, with `discover_addresses` empty (no story run since the update) | 1.44 s | +29 MB |

  - The result is byte-identical to the old walk's JSON (same suggestions, same order, same articles, titles and names), before and after a story run on that copy.
  - The story job's fill costs 45 ms when nothing is new.
- **Tests:** `test_discover_counts.py` (7). The oracle is the old walk, kept in the test as it was, compared whole on the test database after rows that hit the edges: an account on a platform, a platform page that names no account, `@ТЕСТ` lowercased as Python does, a host with a port, `co.uk`, 40% exactly and just under, Reddit authors as voices, a site two sources share, more than 20 articles, a classic, a followed site and a hidden key. Plus Discover filling a missing address, the story job filling them, a row of older rules redone, and an unlinked row dropped.

### 5. Background work you can see
- `GET /api/operations/background` (`db/repo_background.py`, `OperationsService.background_work`), one query:
  - **stories:** the `stories` setting's last summary (when, seconds, posts grouped, stories, News, Classics), and `running` while a run holds the story job's advisory lock (`pg_locks`);
  - **search:** posts whose vector is missing or of an older `search_version`, of all posts;
  - **links:** posts whose links were never read (`links_scanned_at IS NULL`), of all posts.
  - 30-160 ms on the lab copy. No POST, no setting.
- **Sources → ingestion → overview** ends with **Background work** (`components/sources/BackgroundWork.tsx`, `lib/backgroundWork.ts`). Three rows, a glyph and words:
  - Stories: `done` with "Last run 12m ago, took 5s · next run: after the next fetch run" and "5,018 posts grouped · 86 stories · 90 in News · 175 Classics"; `building stories, News and Classics now`; `not run yet`, "Runs after the next fetch run";
  - Search index: `up to date` or `re-indexing 12,000 of 41,689`;
  - Links: `all read` or `reading 1,200 of 41,689`.
  - It refreshes every 5 seconds while anything runs, else every minute. No buttons. It lives in the Sources chunk: the feed route grew 31 bytes gzip (169,551 against 169,520).
- **Tests:**
  - backend `test_background_work.py` (7): never run, done, running while the lock is held (and not for another advisory lock), re-indexing then up to date, reading links then all read, and the route (GET only);
  - frontend `lib/backgroundWork.test.ts` (4) and `SourcesConfig.ingestion.test.tsx` (4 more): all done with nothing to press, right after an update, never run, and an error.
- **Screens** (Design Studio frames `sources/background-after-update`, `background-done`, `background-never`, at 1400 and 390, light and dark): `/tmp/i0062-shots/`.
- `design/docs/pages/sources.md` describes the block and lists the three states.

### Checks
- Backend suite: 1055 tests OK. Frontend: typecheck, 197 node + 662 vitest tests, lint and build clean, the bundle within the 0061 budget.

## Left open (items 3-5)
- **3:** `up -d` still restarts the API whenever its image changed, so an update is a few seconds down, plus the API's own start. A migration that runs long runs in that window, as before.
- **4:**
  - The first Discover open after the deploy that brings 0046, before any story run, works out every address (115k on the lab: 1.4 s once). The backend's start runs the story job, which does it first in the usual case.
  - The 0.5 s target holds on this machine with little to spare (0.42-0.56 s under other agents' load). Most of what is left is reading the 138k kept addresses once to count them; a further cut would need the counts kept between runs.
  - A Reddit author is lowercased in SQL with ICU (`und-x-icu`). The `pgvector/pgvector:pg15` image has it; a Postgres built without ICU would fail Discover.
- **5:**
  - "Running" for stories is the regroup step (the lock). The link reading before it shows in Links, not in Stories.
  - Search and Links count what is left, not whether the API's background thread is alive: a thread that died would show "re-indexing" until the next start.
