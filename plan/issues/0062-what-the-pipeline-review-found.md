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
