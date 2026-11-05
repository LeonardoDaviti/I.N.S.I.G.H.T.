# 0084 — Substack: the cookie only where you pay; and a source's own older posts that its posts link

Status: **spec** (2026-11-04), from the owner's bug report: "it fetched kaitchup, but it does not fetch other substack feeds, because I have no subscription on them … also … some post might mention an older post that we don't have … can we parse it and store?" Part A is a bug fix (v9.16). Part B is a small feature (v9.16 or v9.17). **B built** 2026-11-05 on `issue-0084-b-linked-posts`, not merged (Built (B), below).

**Constraints:** download nothing beyond the feeds a fetch already reads; no real names in committed files or fixtures; nothing merges unless `scripts/realdata-check.sh` passes; the cookie is never logged or put in an error message.

## A. The cookie only where you pay (bug)
**Today** (the server, 2026-11-04):
- 4 of 12 Substack sources are in error, "Substack session expired — update it in Sources → Connections", although the cookie is fine.
- **The cause** is in `ingestion/kinds/substack.py`, `_to_post`: with a cookie set, any `only_paid` post that comes back truncated raises "expired". On a publication you don't pay for, a truncated paid post is normal, and it stops the whole source.

**Decided:**
1. **Which publications you pay for:**
   - asked once per fetch run of Substack's subscriptions API (`SUBSCRIPTIONS_URL`), kept in memory for the run;
   - it holds each publication you're subscribed to, with its paid or free state, read defensively (fields missing means "not paid").
2. **A publication you pay for:** as today. A truncated paid post means the session expired, so the source is unavailable until the cookie is updated.
3. **Any other publication** (free, or paid with no subscription):
   - the cookie isn't sent;
   - a paid post is stored as its public teaser, with `metadata.paywalled = true`, as without a cookie;
   - never an error.
4. **If the subscriptions API answers 401 or 403,** the session expired: every paid publication is unavailable, and free ones are read without the cookie.
5. **The connection test** (`check_session`) says which publications it reads in full: "Signed in · full text on 1 publication you pay for".
6. **A source's health** for a paywalled publication says "Paid posts: preview only (no subscription)", not an error.
7. **The repair:** on the first fetch after this, the 4 sources in error recover on their own; nothing to do by hand.

**Tests:** fixtures for paid-subscribed, free-subscribed, not subscribed, and an expired session (401 on the subscriptions API).

### Built (A)
Branch `issue-0084-substack-cookie` (2026-11-04), on main 20d18d5. Not merged, not deployed. No migration.
- **`ingestion/kinds/substack.py`**: each source is read in one of four ways, decided once per fetch from the subscriptions answer:
  - *you pay for it*: as before (cookie sent; a truncated `only_paid` post, or a 401/403, is "expired");
  - *you don't* (free, not subscribed, or no cookie at all): no cookie on the archive or post requests, a paid post is stored as its teaser with `metadata.paywalled = true`, never an error;
  - *the subscriptions API answered 401/403*: no cookie; a publication with a truncated `only_paid` post is unavailable ("expired"), free ones are read (Decided 4, "paid publication" read as one that has paid posts: with a rejected cookie we can't know which ones you paid for);
  - *the answer can't be read* (another error, an unexpected shape, an empty list, or no entry recognised as paid): the cookie is sent everywhere as before, but a teaser is stored, never an error. This keeps full text on the publication you pay for if Substack's shape isn't the one assumed, and never puts a source in error. Its cost: in that case an expired cookie is not detected.
- **Asked once per run**: the answer is kept in memory on the kind for `SUBSCRIPTIONS_TTL_S` (600 s), keyed by a hash of the cookie (a new cookie asks again). An unreadable answer is not kept. The cookie is never logged or put in a message.
- **The shape assumed** (not verified, no request made from this machine; `paid_publication_hosts`): a JSON object whose `subscriptions` is a list. An entry is paid when `membership_state` (or `type`, `subscription_type`, `plan`) is one of `subscribed`, `paid`, `founding`, `comp`, `gift`, or when a flag `paid` / `is_paid` / `isPaid` / `is_paid_subscriber` / `is_founding` is `true`. Anything missing means not paid (`free_signup` is not paid). The entry's publication is embedded (`publication: {subdomain, custom_domain, base_url}`) or found by `publication_id` in a top-level `publications` list (`id`, `subdomain`, `custom_domain`). Hosts are matched without `www.`: `<subdomain>.substack.com` and the custom domain. **To check on the server:** the connection test's count. If it says "no publication you pay for found" while you pay for one, the shape is not the one assumed: fetches still work (the unreadable case), but expiry isn't detected.
- **The connection test** (`check_session`): "Signed in · full text on N publication(s) you pay for". With a source you pay for, it also reads its newest paid post ("· “title” reads in full"; a teaser is "expired"). "Signed in · no publication you pay for found" when none is recognised. A 401/403 is "expired"; a failed request is "Could not check the Substack session: …".
- **Source health** (Decided 6): the schedule view (`repo_fetch_state.load_schedule_view`) gains `paid_preview`, the `metadata.paywalled` of the source's newest `only_paid` post. `operations_service` adds the kind's `reading_notice(source)` to the row's `reading_notice`, which source settings already show: "Paid posts: preview only (no subscription)" when a cookie is set and that post is a teaser. Without a cookie the existing notice ("Add your Substack session…") stays.
- **The repair** (Decided 7): nothing stored changes. On the next fetch the 4 sources read without the cookie and succeed, which clears their error.
- **Tests**: backend 1357 pass (`./run-tests.sh`). New: paid-subscribed (full, cookie sent; a teaser means expired), free-subscribed and not subscribed (no cookie, teaser, no error), a custom domain you pay for, 401 on the subscriptions API (the paid publication expired, a free one read without the cookie), an unreadable answer (cookie sent, teaser, no error), one subscriptions request per run, the parser's defensive reads, the check's messages, the health note, and `paid_preview` against the database. Fixtures use `example.substack.com`; the real name the two test files used is gone.
- **The real-data check** (`insight_lab`, clock 2026-10-30 21:31): **PASS**. Cases: none changes state. Invariants: all equal to main's. Diff: 0 in every part (titles, text starts, link titles, roundups, story membership, origins, News, Classics, Discover).

## B. A source's own older posts that its posts link
**Today:**
- A post that links an older post of the same publication, one we don't store, gets nothing. Neither the archive nor Discover fetches it.
- Discover's "missing from a source you follow" (0065) lists only pages that **start stories**.

Measured on the lab (posts linking `<publication>/p/…` of a followed Substack):

| | linked | not stored |
|---|---|---|
| all 7 Substack publications | 79 | 43 |
| the largest | 20 | 17 |

**The archive** reaches far back for Substack: the archive API pages back to the first post (one publication: about 540 posts, back to 2023). So most of these come in by running that source's archive. The rest are pages the archive doesn't list, or sources whose archive can't page.

**Decided:**
1. **"Linked, not stored"** is counted per followed source from what is stored: its own pages (its site, or its publication's path) that any stored post links, and that no stored post is.
2. **Fill them with the source's own reader, one page each:**
   - Substack's `read_post`, the full-text repair path every kind with `read_post` has;
   - the site reader for websites.

   Each is stored as a post of that source, with its real date.
   - Paced like the archive: one request per page delay.
   - Never more than the linked list.
   - Never for a page behind a paywall the source can't read (stored as its teaser, as A says).
3. **Where it shows:** the source's Archive section gets "Linked by your posts, not stored: 17 · Fetch them". A source whose archive can page offers the archive first ("Run the archive: it holds them").
4. **Done when:** on a lab copy, the linked-not-stored count of every Substack source after a fill is 0, except pages that answer 404 or 410 (listed); the real-data check passes (expect new posts and their stories, nothing else).

### Built (B)
Branch `issue-0084-b-linked-posts` (2026-11-05), from main 9c5514c. Not merged, not pushed, not deployed. No migration. Nothing was fetched from this machine: the tests use fakes, the numbers below are read-only queries of `insight_server_1105` (the server's copy) and `insight_lab`.

**Found while measuring: a source's links to its own older posts were never kept.** `post_links` leaves out every link of a post to its own publication (`post_links.extract_links`, issue 0070). So the owner's case, a writer linking their own older post, was in no table. The spec's lab table (79 linked, 43 not stored) counted only other sources' links, which is all `post_links` has (the same query gives 79 and 46 on today's lab). This build reads a post's own links from its stored HTML.

1. **"Linked, not stored" is one function** (`db/repo_linked.linked_not_stored(cur, source_ids=None, since=None)`, rules in `utils/linked_rules.py`). It returns, per followed (enabled) source, its pages that stored posts link and that no stored post is. Each page comes with how many posts link it and when it was first and last linked, the most linked first.
   - **The links:** every kept link (`post_links`, a source's signature left out), and each post's links to its own publication (`own_links`: the same hrefs, made absolute and normalized, read from the HTML of the posts on the sources' hosts). A link found in a quarter of a source's posts (4 or more) is its signature (story_rules' `SIGNATURE_SHARE` and `SIGNATURE_MIN_POSTS`), such as a subscribe page or a series index.
   - **Whose page it is** (`OwnPages`). The rule is learned from every source's stored posts, as 0065's places are, and names no site:
     - **On a platform**, the page belongs to the account a source follows (0065's `discover_address`). It must have a post's shape: a tweet, a Telegram `/<channel>/<number>`, or a Reddit thread. `youtube.com/watch` names no channel, so it is nobody's page.
     - **Elsewhere**, the page has the shape of the source's posts on the same publication, counting only posts on the site the source publishes on (its address's, and 0064's `home_site`). A link blog's posts stored at the pages it links are not its pages.
       - A shape is the path's segments, each a number or a word, plus the query's keys. The first segment stays as written when 2+ posts share it: `/p/<slug>`, `/news/<slug>`, `/blog?id=`.
       - A shape of words only (`/<slug>`) holds only when half the source's posts there have it (`GENERIC_SHARE`). On the server's copy, root-level blogs have 85–100% of their posts that way, while a site organised in sections has 0–2% stray pages at its root. With such a shape, a docs, pricing or product page (`post_links.REFERENCE`) is not a post.
       - A page named for a kind of page (`NOT_POST`: about, archive, tag, author, page, subscribe, form…) is never a post.
       - A query the source's posts don't have (a referral's `?r=…`) is not part of the page.
       - When two sources hold one shape, the page goes to the one with more posts there. Hacker News and Saved own nothing.
   - **Not stored** means: no post is at that address (`normalized_url`), none moved there (`metadata.moved_to`, 0108), and none names it as its canonical address.
   - **For 0114:** `since=` keeps only links of posts published since then. That gives 0114's wanted links: the same set, limited to recent links. On the server's copy, the 72 hours before its newest post hold **175** such pages.
   - **Cost:** about 11 s for every source on the server's copy (49k posts, 176k links), 1–2.5 s for one source (the Archive section's request).
2. **Fetch them: an archive job of the source.**
   - **The readers.** Each kind says whether it can read one page (`reads_posts`):
     - Substack: its `read_post`, the API's post. A paid post of a publication you don't pay for is its teaser with `metadata.paywalled`, as part A says, and only one request is made.
     - Every website kind (generic RSS, page watch, the site adapters): `page_watch.read_page_post`. It keeps the page's article with the date the page states (0070). A page with no date of its own is not stored, because stored with the time it was read it would sort as new.
     - Platform kinds (X through Nitter, Telegram, Reddit, YouTube) read no single page. Their linked pages are counted only.
   - **The job** (`SourceFetchService.plan_linked` / `fetch_linked`, `ArchiveJobs.run(linked=True)`; `GET` and `POST /api/archive/{id}/linked`):
     - The list is the plan's checkpoint, so it reads **never more than the list**.
     - The archive loop reads the list one page at a time, under the same host gate slot and pace as an archive's pages, with 0107's learned budgets. A host that limits twice in a row waits for its window, and the scheduler continues the job on the same list and the same job row (a continuation never recounts).
     - A page that fails (404, 410, another error) or holds no post goes into `missing`, with its status, and is never asked again.
     - An expired Substack session stops the job (`KindUnavailable`).
     - Each page is saved through the normal save batch as a post of the source, marked backlog (an older page, never "new to you"), so the story job joins it.
     - The job is an `archive_source` job, so only one archive or fetch runs per source at a time. It writes nothing into `settings.archive`: a paused archive keeps its checkpoint.
     - Its result says, for example, "Fetched 15 of 17 linked pages; 2 not stored (listed)".
3. **The Archive section** (`ArchiveSection.tsx`, `lib/archive.describeLinked`) shows "Linked by your posts, not stored: N · **Fetch them** · ~1m, one page at a time". It loads by its own request, so the status isn't slowed.
   - When the source's archive pages back and hasn't run, the line says "Run the archive: it holds them. Or fetch only these: …", with Fetch them beside it. Decision 3 says "first". I kept the fetch beside the archive because no Substack source on the server has run its archive, and a whole archive costs every older post plus its listings, while this costs N requests.
   - Pages nothing reads one by one: "Its pages can't be fetched one by one", with the count only.
   - A feed with nothing older to archive still shows the line and fetches.
   - The section follows the job like an archive: progress ("Read linked page 5 of 17"), the waiting notice, and **Continue now**, which continues the same list.
   - Feed route 174,399 gzip bytes (0.93% over its baseline, within the gate; +57 bytes over this branch's backend-only state).

**Measured** (read-only, the code of this branch):

| | server's copy | lab |
|---|---|---|
| followed sources with linked, not stored pages | 158 | 137 |
| pages | 7,964 | 7,281 |
| …that one fetch can read (118 / 101 sources) | 5,933 | 5,684 |
| …of a subreddit, X accounts and Telegram channels (counted only) | 957 + 646 + 428 | 945 + 263 + 389 |
| Substack-kind sources (7) | 97 | 91 |
| Substack publications on their own domains, read as feeds (7 / 6 sources) | 223 | 106 |

- **Per Substack source on the server's copy:** 29, 24, 18, 9, 8, 6, 3.
  - Expected requests: one API call each, plus the subscriptions call once per run, 2 s apart (the Substack host's floor). That is 97 requests, about 5 minutes in all.
  - **What the archive would cover instead:** Substack's archive pages back to the first post, so it would reach these pages too, unless one isn't listed there. Its cost is every older post (one request each) plus one listing request per 12. A post's date isn't known before reading it. Only 12 of the 97 were first linked before the source's oldest stored post, the pages the archive certainly covers. The rest may be gaps between stored posts, which the archive, starting below the stored posts (0015), never reads.
- **All readable sources on the server's copy:** 5,933 requests, about 155 minutes at the hosts' floors. 189 of them are certainly in an archive's range. The largest lists are a forum's posts (2,190, about 73 min; its pages are read by the site reader, not its API) and a newsletter's issues (550).
- **Built right, wrong, missed** (a seeded sample of 60 pages from the server's copy; the cases are private, in `plan/research/0084-build/`):
  - **Right:** 57 of 60. Substack `/p/` posts linked by the writer and by others, dated blog posts, a section's posts, a followed account's tweets and channel posts.
  - **Wrong, fixed:** a file name linked under a Telegram channel had counted as a post of the channel (now a post's shape is required). A site's `/form/…` pages that its feed listed had counted (`form` is now in `NOT_POST`).
  - **Wrong, left:** a link with a space in its address (it will answer 404 and be listed). A forum's event pages, which its feed stores as posts, so they are its shape. 6 of the subreddit's 957 are a comment's address on a thread that is stored (`/comments/<id>/comment/<id>`); the subreddit is only counted.
  - **Missed:** a publication reachable at two hosts with posts stored at only one of them (a Substack subdomain and its own domain). Links in posts that have no HTML.
  - **Fix where:** a page's other addresses are 0106's aliases, a 9.x follow-up. Telling an event from a post is meaning, so Mark X.

**Tests**, written first:
- `test_linked_pages` (20): own links; signatures; the shapes (a Substack, a dated blog, a root blog, two sections, a shared shape, a query, a referral, a link blog, a stray root page, a docs page, platforms, a repost, an aggregator and Saved); on the database: self links and others' links, moved and canonical pages stored, a signature, a disabled source, `since`, a quoted tweet.
- `test_linked_fetch` (11): the readers (a dated page, no date, a 404, which kinds read; a Substack teaser in one request); the job (each page once through the host gate, 404 and no-post listed, the waits, the archive untouched; a host limiting twice waits and the continuation reads the same list; nothing to do; a kind that can't read; an expired session); the job is an archive job.
- `test_ingestion_routes` (2 more): the routes.
- Frontend: `archive.test.ts` (3), `archiveSection.test.tsx` (6), and the design fixtures answer the new request.
- Backend **1,772 OK** (`./run-tests.sh`, own image tag), frontend **240 node + 734 vitest**, `npm run build` within the gate.

**Done when 4, on a lab copy** (`insight_lab` restored into a scratch database, dropped after): a fill with no network. One post was saved through the source's save batch at each listed address, as `read_post` returns it, for the 7 Substack sources. The count went from **91 to 0**, and every other source's count stayed the same (7,190). On the server, after the real fill, what's left is the listed 404s and 410s.

**The real-data check** (`scripts/realdata-check.sh --base main --head issue-0084-b-linked-posts`; reports private in `plan/research/0084-build/checks/`, as the main checkout's `plan/research` was refused to this worktree):
- `insight_lab`: **PASS**, no `--allow`. Cases: 80 pass, and none changes state against main. Every invariant is equal (`story.identity` 0 of 742,613). The diff is **0** in every part (titles, text starts, link titles, roundups, membership, origins, News, Classics, Discover).
- `insight_server_1105`: **verdict FAIL, from the cases file only**. 14 cases marked pass on the lab fail on the server's copy, on main as on this branch ("Against main: no case changes state"), because their posts and stories are the lab's. 3 marked fail pass on both: `openai-teasers-retried`, `origin-title-slug-only`, `discover-owner-already-followed`. Every invariant is equal to main's and the diff is **0** in every part. Nothing derived reads this code: no post is fetched until a press.

**What the owner will see on the server after the deploy** (nothing is fetched until a press):
- Each source's Archive section in its sheet shows the line. For the Substack sources it says "Run the archive: it holds them. Or fetch only these", with Fetch them beside it.
- Fetch them on the source with 29 pages: a job of about 1.5 min (29 API calls, 2 s apart), "Fetched 29 of 29 linked pages". Teasers come in where you don't pay. Any page that answers 404 or 410 is listed in the result.
- The next story job joins the new posts. The line then says the count left, which should be 0 except the listed ones (Done when 4, checked there).
- On a website the reads are pages at the host's floor. A forum's 2,190 pages take about 73 min, so that one is the owner's choice.

## Not in this issue
- Fetching any linked page of a site you don't follow (that's Discover).
- A paid subscription's login flow (the cookie stays pasted in Connections).
