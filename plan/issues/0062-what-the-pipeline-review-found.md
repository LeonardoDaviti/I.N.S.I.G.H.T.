# 0062 — What the pipeline review found: same address, teasers retried, a shorter update, Discover in the database, background work you can see

Status: **spec** (2026-10-31) for v9.9 (owner, 2026-10-31: "that is already for 9.9, so spec them").

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
- **Built** (2026-10-31, branch `issue-0062-0063-reading-fixes`, not deployed):
  - **What counts as a failed read:** an `HttpError` from the article page: an HTTP status, a timeout, a dropped connection. "The page holds nothing longer" or "not the same article" (`read_article` returning None) is no failure and is never counted. Neither is a page the reader cannot parse.
  - **The count** is `metadata.page_tries` = `{count, last_at, failed}` (`repo_posts.PAGE_TRIES_KEY`). A new teaser's failed read writes count 1. The saver keeps the key when the feed sends the post again without it (`_post_update_assignments`, like the page-watch update key); without that, every re-fetch wiped the count.
  - **The retry** (`GenericRssKind._read_again`, `PostsRepository.teasers_to_read_again`):
    - every fetch of a generic RSS source asks for its stored teasers with `failed` true, `count < 3`, `last_at` at least a day ago, oldest try first, up to 20 (`full_text.MAX_PAGE_TRIES`, `RETRY_APART`, `RETRY_SLICE`);
    - an unchanged feed (304) asks too, so a quiet feed's teasers are still retried, and so does a post that has left the feed;
    - they're read after the feed's own pages, inside the same host slot and `PAGE_DELAY_S` apart, so the runner's pace and host gate apply as to the first read;
    - each comes back as a post the saver writes in place (the stored url, title, media, categories and metadata; `date` None, so the stored date stays). Full text sets `full_content_fetched` and ends it; nothing longer sets `failed` false and ends it; another failure counts again;
    - a limiting answer (429 or a timeout) counts that try and ends the slice: the rest wait for the next fetch, a day apart still holding;
    - a source with `fetch_full_content: false` is never retried. No new setting.
  - **Tests:** `tests/test_teaser_retries.py` (11): a failed read counted (403 and timeout), a page with nothing longer never counted, a retry that works (count 2, done), the third failure counted and then never due, nothing longer ending it, a 304 feed still retrying, a limiting host ending the slice, the delay between pages, full text off, and on the database: only failed reads under 3 tries a day old are due, and a feed re-fetch keeps the count while the retry writes the full text in place. Backend suite: 1060 tests green.
- **Left open:**
  - **The 5 OpenAI teasers already stored** (`openai-teasers-retried`) carry no count: they were stored before 0062, and nothing recorded whether their read failed or found nothing. No rule can tell them from a teaser whose page really is short, so they're not retried by this. `python -m insight_core.scripts.repair_full_text --source <OpenAI News id>` reads them once (it reads every teaser never read from its page). From now on, a failed read is retried by itself.
  - A 404 or 410 is retried like any HTTP error, as decided: at most two wasted reads, a day apart.
  - The fetch's `fetched` count includes the retried posts, so a 304 fetch with retries says "unchanged" with posts.

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
