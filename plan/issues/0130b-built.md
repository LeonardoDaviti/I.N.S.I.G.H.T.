# 0130 — Built (B, C, E1)

Branch `worktree-agent-aed7dd4d61d4e8dfe` off main df54d6f. Commits: a5eb4c6 (B and C, backend), bab7f5e (E1 and the
scheduler's part of C), af2051f (B and C, frontend), and this file. No migration (0077 unused: the queue is a job
status, `queued`, in `job_runs`, whose `status` has no constraint). Real sources and rows are in
`plan/research/0130-notes.md` (private); every fixture here is on an invented host.

**Nothing was fetched from the lab.** Every failure below is fixed from what the server's run logs and the read-only
server copy (`insight_server_1105`) show, and tested on fixtures. Each fix is **unverified against the real sites
until the owner's server runs the archives again** (0130's "Done when": a measured run on the server).

## B. Archives that work again

### B1. The newsletter platform's archive API (8 of 8 failed: HTTP 400 on `offset=0`)
- **Changed** (`ingestion/kinds/substack.py`): the first archive page is asked with **no `offset`**
  (`/api/v1/archive?sort=new&limit=12`); later pages keep `offset=N` (N ≥ 1). When the API refuses a page anyway
  (any answer but a list; never a 429/timeout, which waits as before, nor an expired session) the archive goes on
  from the **publication's sitemap** (page watch's reader: robots.txt's Sitemap lines, else `/sitemap.xml`, an index
  followed up to 60 files): its `/p/<slug>` addresses on the publication's host, newest lastmod first, each read
  from `/api/v1/posts/<slug>` as before; the stored ones are not read again (the registry now hands the kind
  `stored_urls`). Checkpoint mode `substack_sitemap` (`next_index`, `skipped`, `refused`), resumable. A refusal on
  a later page switches too. A refusal with no sitemap is the archive's error (never a silent 0). The plan
  (`inspect`) measures the sitemap when the API refuses (`raw.archive_api`, `raw.sitemap_posts`).
- **Not done:** no other paging (a cursor) is guessed: the code knew none, and nothing was probed.
- **Tests** (`test_archive_repairs.NewsletterArchiveTests`, 7): no offset on page 1; a 400 read from the sitemap,
  stored post unread, another host and a non-post page left out; a later page refused; a resumed sitemap
  checkpoint never asks the API; refused + no sitemap raises (archive and plan); the plan's sitemap count; a 429 is
  no refusal. `test_substack_kind` and `test_credentials` now expect page 1 without `offset`.
- **Unverified:** whether the platform's API accepts `offset` ≥ 1, or the first page without one. If it refuses both,
  the sitemap carries the archive; if a publication's sitemap lists few posts, the archive is that short.

### B2. The weekly newsletter's site reader (`deeplearning_batch_site`: 38 pages, 0 posts)
- **The server copy:** no stored page of the new layout. The source's newest stored issue is of 17 July 2026 (237
  posts, the last live fetch recorded on 21 July); nothing since, so the reader has silently found nothing for
  about four months. The copy stores post bodies, not pages, so the layout could not be learned.
- **Changed** (`adapters/deeplearning_batch_adapter.py`, `adapters/base_adapter.py`): an issue page without the old
  Next.js payload is read **as any article page** (page watch's `article_post`: body, title, the page's own date,
  else the sitemap's), the issue number kept as its id so the stored issue is updated, not doubled
  (`metadata.read_as: "page"`). The issue list falls back to **the site's own sitemap** (`/the-batch/issue-N/`) when
  the CMS sitemap can't be read or lists no issue. `LISTS_ONLY_POSTS`: every listed entry is an issue, so an archive
  that reads ≥ 3 and finds no post **fails saying "The site's layout changed: N listed pages read and no post found
  on any; its reader needs an update"** (`layout_changed` in the result); a live fetch that reads 3 issue pages and
  no post fails the same way (the health row shows it) instead of a healthy 0.
- **Tests** (`WeeklyNewsletterReaderTests`, 3; `ZeroNewTests` layout test): the fallback read, the site sitemap, the
  live fetch's error, the archive's failure.
- **Unverified:** whether the new issue pages read as articles by the generic reader (a page built only by
  JavaScript would not: then the archive says the layout changed, and the reader needs a stored page to be fixed).

### B3. A feed that moved (a lab's `/blog/index.xml` answers 404)
- **The server copy:** the source was healthy on 5 Nov (7 posts); the 404 is new since, so no live fetch had woken
  the doctor yet.
- **Changed** (`services/source_fetch_service.py`): a plan or an archive of a doctor kind (generic RSS, page watch)
  whose feed answers 404/410, or no feed, **runs the source doctor** (0036: the feed finder on the address, its
  section and home page, then page watching), as a live fetch's failure does, with its own rules (once a day, a
  same-site feed of the source's own items is switched to, anything else stored as the finding). The archive's
  error says what it found: "The feed moved: INSIGHT now follows <address>; run the archive again", or "INSIGHT
  found a feed / a page to follow at <address>: switch to it on the source's sheet, then run the archive again", or
  that it found nothing. The finding shows on the source sheet as every doctor finding does (ReplacementNotice:
  Switch / Dismiss), per the source-adding rule. `archive_service()` builds the doctor as the runner does.
- **Tests** (`MovedFeedTests`, 3): switched and said; a page offered on the sheet; a 503 doesn't wake it.
- **Unverified:** where that feed moved; the doctor reads it on the server.

### B4. "Success, 0 new" while the site lists more (a research org: 102 re-read, 153 unreached; two lab news pages: 10, 3)
- **The server copy:** the two news pages are page-watched. One read 281 candidates and got 273 posts, 271 stored:
  its "10 not archived" are 8 candidates that are no post and 2 stored under another address. Its `available_posts`
  is the candidate count (an estimate that counts non-posts), so the backlog never reaches 0. The research org is
  not in the 5 Nov copy (added later); its "102 updated" is page watch's archive re-reading every stored page.
- **Changed:** kinds count why a listed page added nothing in the checkpoint's `skipped` (`stored`, `no_post`,
  `unreadable`; base `index_pages`, page watch, generic RSS's sitemap, the newsletter's sitemap). **Page watch's
  archive no longer reads stored pages again** (page watching, 0039, re-checks them) and **reads the site's whole
  sitemap** (60 files, not a live fetch's 5) for the rest, its plan too. The result's message says why: "Archive
  completed with 0 posts; nothing new: 102 pages already stored (not read again) · 2 posts already stored under
  another address · 8 pages no post (no article, or no date) · 2 pages could not be read", or "the source's listing
  ends here"; `result.unreached` and `settings.archive.unreached` keep the counts; the sheet shows the line.
- **Not done:** the backlog figure still counts non-post candidates (changing what `available_posts` means is a
  measurement for the three sources, on the server).
- **Tests** (`ZeroNewTests`, 4).
- **Unverified:** whether the research org's sitemap holds the 153 (the 60-file read is the change that could reach
  them).

### B5. Resume interrupted archives
- **Changed:** `POST /api/archive/resume-interrupted` queues every source whose newest archive job a restart
  interrupted (not a linked fetch), to resume from its checkpoint with its horizon and pacing. The catalog answers
  `interrupted` and `queued`; **Sources → Ingestion → Archive** shows "Resume N interrupted archives" (one tap) and
  marks each queued / interrupted source.
- **Tests:** `ArchiveQueueTests.test_resume_interrupted…`, the frontend's `archiveQueue.test.tsx`.

## C. Archives back to a date, one Telegram and one X archive at a time
- `ArchiveRequest.until` (a date). A kind whose pages go newest first (`chronological`: telegram_mtproto,
  telegram_rss, nitter_rss, substack) stops after the first page whose oldest post is before the date: that page is
  saved, no page after it; the result says "Archive reached 1 Nov 2025 with N posts (its oldest page goes to …)",
  `until_reached`; **its checkpoint is kept** (no `completed_at`), so a later archive goes on from there. Stored posts
  already past the date: "The archive already reaches …", no page read. Any other kind ignores `until` (the API
  drops it; the sheet doesn't offer it). A continuation after a host's wait keeps the horizon.
- The sheet's archive section offers **"Back to"** (default 2025-11-01, the owner's open decision 2's default) on
  those kinds; the button says "Run archive back to 2025-11-01"; blank archives the whole history.
- **The queue:** a job can be `queued` (payload `queued_at`, `lane`). Lanes: `telegram` (both Telegram kinds),
  `nitter`, else `host:<key>`. One archive per lane runs (a waiting one holds its lane), at most 3 from the queue at
  once. The ingestion process starts queued jobs whose lane is free on every archive poll (30 s); at its start the
  queued jobs it was running are queued again (they resume). The API's Run on a Telegram or Nitter source whose
  lane is busy **queues instead of starting** (202, status `queued`; the sheet says "Queued"); other kinds start as
  before. `POST /api/archive/{id}/queue` queues explicitly. All checks and writes run under advisory locks (the
  source's, the one start_job_unless_running takes; the lane's; the queue's).
- **Tests:** `BackToADateTests` (3), `ArchiveQueueTests` (6), `LaneTests`, the frontend (back to, queued, blank).
- **Unverified:** a real Telegram archive stopping within one page of the date ("Done when"), on the server.

## E1. Posts with no normalised address
- `scripts/repair_normalized_urls.py`: every post with an http(s) address and no `normalized_url` gets it by the
  save path's rule (`normalize_url`; an empty `canonical_url` and `url_host` too: all three are empty on these
  rows), only where empty; a batch a transaction, `FOR UPDATE SKIP LOCKED`, resumable; `--dry-run`. **The
  ingestion process runs it at its start** (the deploy's first start; logged "Addresses: N of M posts … filled";
  a later start finds 0 and logs nothing), in a thread so the first tick doesn't wait.
- Invariant `post.address_unnormalized` (`checks/invariants.py`): an http(s) address with no `normalized_url`.
- **Timed once** on a scratch copy of `insight_server_1105` (`insight_server_1105_check_553007_a`, dropped after):
  **1,146 posts filled in 0.31 s** (1.2 s with the container's start), 0 unreadable; a second run: 0. The story
  queue grew by exactly 1,146 (55,176 → 56,322: the update trigger regroups each, as for any address change).
  Same-source duplicate addresses: 4 before and 4 after (the repair made none).
- **Tests:** `NormalizedAddressRepairTests` (2): filled by the rule, a filled one unchanged, a non-address left, the
  invariant passes after, a second run changes nothing, a dry run writes nothing.

## Files
Backend: `ingestion/kinds/{base,substack,page_watch,generic_rss,telegram_mtproto,telegram_rss,nitter_rss,__init__}.py`,
`adapters/{base_adapter,deeplearning_batch_adapter}.py`, `ingestion/archive_metadata.py`,
`services/source_fetch_service.py`, `services/archive_jobs.py`, archive routes in `main.py`,
`scripts/repair_normalized_urls.py`, `checks/invariants.py` (one invariant). Outside the list, small and archive-only:
`db/repo_operations.py` (the archive job summary carries `unreached`, `until`, `until_reached`, `layout_changed`,
`queued_at`), `scripts/run_scheduler.py` (the queue's start/requeue and the repair at start),
`frontend/src/hooks/useOperations.ts` (a queued job is polled as a waiting one). Frontend: `ArchiveSection.tsx`,
`IngestionArchive.tsx`, `api.ts` (one block at the end, `// 0130 B`). Not touched: `markx/`, `components/markx/`,
`plan/issues/README.md`, `VERSION`, `scripts/markx-worker`, migrations.

## Tests run
- Backend (`TEST_IMAGE=insight-backend:v105b ./run-tests.sh`, 32 modules: the archive, kinds, adapters, doctor,
  feed finder, page watch, sitemap, routes, operations, scheduler, safe start, deploy finishes, migrate runner,
  real-data checks' unit tests, and the two new): 822 OK.
- Frontend: `vitest` on `components/sources` and the two Sources pages, 178 OK (4 new); `eslint` on the touched files;
  `npm run build` OK (bundle check within its bar).
- Not run: the whole suite, `scripts/realdata-check.sh` (the owner's rule for this slice).

## For the owner
- **Run the failed archives again on the server** (the newsletter platform's 8, the weekly newsletter, the moved
  feed, the three "0 new"): that run is B's measurement. Each now either works or says why in its job's message.
- **The new invariant** counts 1,146 on any copy before the deploy's first start (0 after): the real-data check's
  baseline (main) has no such invariant, so read its first count with that in mind.
- **Open decision 2 (C):** the default horizon is 1 Nov 2025, as the spec's default.
- The page-watch archive no longer re-reads stored pages: an archive is no longer how a changed page is refreshed
  (page watching is).
