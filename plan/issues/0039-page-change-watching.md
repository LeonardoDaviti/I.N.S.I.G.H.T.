# 0039 — Watching pages for changes (Gwern first)

Status: **built, not deployed** (2026-10-28; migration 0037). Planned for v9.5 (owner, 2026-10-28: "super useful for Gwern").

## The case: Gwern
- Gwern rewrites essays constantly. A page is re-read only while it is on `/doc/newest/index`, and the save then overwrites its text silently, with no mark. Older essays are never re-checked. The reader stores each page's `dcterms.modified` (`adapters/gwern_adapter.py`).
- gwern.net sends **no ETag and no Last-Modified** (its `cache-control` even says `immutable`, 900 days), so conditional requests alone can't see its edits.
- gwern.net's sitemap: 22,308 addresses, 685 essay-like, **0 with `<lastmod>`** (2026-10-28). The server has 75 Gwern posts (the archive was never run there).

## Design (proposed)
- **A per-source switch**, "Watch for changes", in the source sheet; off by default.
- **How often:** a single page follows the source's cadence (usually daily); a whole site checks a **rotating slice** (e.g. 50 pages a day, about two weeks for Gwern's 685; recently changed pages more often).
- **Cheap checks:** conditional requests (ETag / If-Modified-Since, 304 = no body); the page's own modified date when it has one (Gwern); then a hash of the **article text only** (the shared reader), so ads and timestamps don't count; ignore tiny changes.
- **What the owner sees:** the post comes back as "Updated 3 Nov: +2 sections, 1,400 words", with the new text; an "Updates" list per source. No full version history (post versions are skipped): the latest text plus a short summary of what changed.
- **Read only the head first** (from the Gwern study, 2026-10-28): `get_start` reads the first few KB of a page, which is enough for a modified date (`dcterms.modified`, `article:modified_time`, JSON-LD `dateModified`). Download the full page only when that date moved. Then use the article-text hash for pages without a date. This is the general path for sites that send no ETag.
- **New to you is new:** a page first seen today, but first published long ago (Gwern's "Lean Software Scaling Laws": published 2025-09, updated 2026-06, on today's newest list), must not land in the past where the Main feed never shows it. Decide the rule (e.g. order by when INSIGHT first saw it, showing the published date) for every page-based source, not just Gwern.
- **Show the page's own state** where the page states it: "Updated 23 Jun 2026", and for Gwern, the status and confidence (stored by 0043).
- **Builds on 0044:** the conditional GET and stored validators come first; this issue adds the head-first date check and the text hash on top. Migration **0037**.
- Size: M. Resource cost: one conditional request per watched page per check; storage, one text hash per page.

## Built
- **Which sources.** A kind says what it can do: `BaseKind.watches` (its stored pages can be
  re-read: it implements `page_post(source, url, html)`, the post a page's HTML is, read the
  way its fetch reads it) and `BaseKind.page_based` (its posts are pages from the site's own
  lists). `page_watch` and the Gwern adapter watch; every site adapter (`BaseSourceAdapter`) is
  page-based. The owner's switch is `settings.watch_changes` (a boolean, off by default,
  validated by `SourcesService`); `page_changes.watching(source, kind)` needs both. The health row
  carries `watchable` and `watch_changes`. **Feed posts read through full text are not watched**:
  their edits are mostly news corrections, a feed re-delivers its own edited items (the upsert
  already takes them), and a feed source holds thousands of posts the owner never opens; a kind
  that wants it implements `page_post` and sets `watches`.
- **When (the rotating slice).** During the source's own fetch, inside the same host gate slot,
  after `fetch_latest` (so host politeness, the learned pace and the scheduler are unchanged; a
  fetch that answered 304 still checks): `PageWatchStore.due` gives at most `WATCH_SLICE` = 50
  pages, the longest overdue first, then pages never checked, newest first; they are checked the
  kind's page delay apart (1 s Gwern, 2 s page watch). When a page is due again
  (`repo_page_watch`): half the time since it last changed (else since published, else first
  seen), at least 1 day, at most 14 days. A page that changed is due the next day; one untouched
  for a month or more every two weeks, so Gwern's 465 candidates cost about 33 checks a day once
  the first sweep (about 10 days at 50 a fetch) is done. A host limiting us (429, timeout) ends
  the slice; the rest wait. "Fetch now" checks without validators.
- **The cheap checks, in order** (`ingestion/page_changes.py`, `check_page`):
  1. a conditional GET with the page's stored ETag / Last-Modified (0044's `AddressMemory`, same
     7-day age limit): a 304 is unchanged;
  2. when the page stated a modified date last time, only its first `HEAD_BYTES` = 48,000 bytes
     (`max_bytes`): the same date is unchanged. `parsing.page_modified` reads, in order,
     `dcterms.modified`, `article:modified_time`, `og:updated_time`, `last-modified` meta, JSON-LD
     `dateModified`, as ISO so two reads compare equal. A date found only past the head
     (`head_missed`, Wikipedia's JSON-LD at 370 KB) skips the head read next time;
  3. otherwise the whole page, read by the kind's `page_post`, and `text_changes.text_hash` of its
     article text (the shared reader's output, whitespace runs as one space), compared with the
     stored one. A different hash, or a moved date with the same text, sends the page to the saver
     as a post, its stored address kept and its date left out (the stored date stays). A 404/410,
     or a page that is no longer an article, is "gone": its text stays and it is checked again
     later.
- **Tiny changes.** `text_changes.change_summary(old, new)` diffs the article html's blocks
  (paragraphs; sentences for plain text), then word by word inside a replaced block, so a fixed
  typo counts 1 word, not the paragraph twice; sections are the headings added or removed. A
  change is **meaningful at 50 changed words (added + removed) or one section added or removed**
  (`MIN_CHANGED_WORDS`): about three sentences. Below that the new text is kept silently, as the
  saver always did. Measured: a BBC page whose text changes on every request (1 word) is tiny.
- **The saver** (`repo_posts.save_batch`, `repo_page_watch.PageWatchRepository.saved`): a
  `PostDraft` carries `watch` and `surface`. A watched draft reads the stored text first, is
  upserted as before, then (in its own savepoint, so a failure costs neither the post nor the
  batch) keeps the hash in `post_watch` and, on a meaningful change: `posts.surfaced_at = now()`,
  `metadata.page_update = {at, words, words_added, words_removed, sections_added,
  sections_removed}` (a later fetch keeps it), and `read_at` cleared. No version is kept.
  `SaveBatchResult.resurfaced_ids` counts them; the job line reads "Gwern: 2 new of 80 · 50 pages
  checked for changes, 3 updated · …". A changed page whose save failed is not recorded as
  checked, so it is read again next time.
- **Read state: an updated post becomes unread again only if you had read it.** An unread one is
  already unread and only moves to the top. This cannot flood: it touches only the posts you read
  (0.3% of them) and only on a meaningful change, and those are the posts whose changes you care
  about; without it the update would never reach the default Unread view. Later and Kept are
  untouched.
- **New to you is new.** `posts.surfaced_at` (migration 0037) is when a post reached you later
  than its date. Besides an update, it is set when a page-based source's live fetch (after its
  first successful fetch, so adding a source never puts its history on top) inserts a page whose
  published date is more than 2 days before it was first seen (`surfaced_at = fetched_at`).
  Page watch marks posts found only in the sitemap as backlog (`repo_posts.BACKLOG_KEY`): its
  daily fetch reads the site's history `limit` at a time, and those must not fill the top of the
  feed. Archives never set it. The feed's sort key is now `COALESCE(surfaced_at, published_at,
  fetched_at)` (both feed-order indexes rebuilt on it in 0037), so every feed post (surfaced_at
  NULL) sorts exactly as before.
  - Trade-off: search's "newest" uses the same key, so a resurfaced or late-found page ranks by
    when it reached you there too. One key keeps one index and one cursor; the alternative (search
    by published date) needs a second pair of indexes for a handful of posts. The day view
    (`?date=`) also files such a post under the day it reached you.
- **What the owner sees.**
  - Sheet: a "Watch for changes" switch under Show in Main feed, only on a watchable source,
    saved at once.
  - Feed row: the time column is when the post reached you; the meta line adds `updated +2
    sections, +1,400 words` (full line `Updated Nov 3: …` in its tooltip), or, for a page new to
    you, `published Sep 14 ’25`.
  - Reader: a source that watches adds Show `/ updated` (`filter=updated`: posts with a
    `page_update`, latest change first), empty state "No updated pages yet".
  - Post header: ` / updated Jun 23` after the date when the page states another day, and under
    the title one `text-3` line: `Updated Nov 3: +2 sections, +1,400 words · finished · highly
    likely` (the status and confidence where the page states them, 0043's metadata; nothing
    otherwise). Design decision 032.
- **Stored:** `post_watch (post_id, source_id, text_hash, modified, head_missed, etag,
  last_modified, learned_at, checked_at, changed_at, next_check_at)`, one row per watched page,
  cascading with the post and the source; `posts.surfaced_at`. Page watch now keeps
  `metadata.modified`. Migration 0037 rebuilds the two feed-order indexes (seconds on 50k posts).
- **Tests:** `backend/insight_core/tests/test_page_change_watching.py` (30): the hash and the
  summary (a typo is tiny, a section is not, plain text by sentence); every place a page states
  its date; the checks (304, the same head date reading only 48 KB, a moved date then the whole
  page, the same text with a new date, no date, a date past the head remembered, gone and failed,
  a limiting host ending the slice, pages spaced); which kinds watch and their readers; the runner
  (a slice checked and the changes saved as watched drafts, the switch off, a kind that cannot
  watch, a failed save checked again, new to you only after the first fetch and never for a feed,
  the job line); the setting and the health row; against the scratch DB, the saver (a new post's
  row due in 14 days, a tiny change silent, a meaningful one surfaced, unread, summarised, its date
  kept and due tomorrow, kept across a re-fetch; new to you vs a recent post, a backlog page, a
  feed post), the due order, the next check, the sort key and the Updated filter. Backend suite:
  842 OK. Frontend: `pageUpdate.test.ts` (3), the feed row, the post header and the sheet's switch
  (3 vitest); 165 node + 600 vitest OK. Reader initial JS: 473,830 bytes (+1,625, 0.34% against
  472,205).

### Live check (2026-10-28, read-only from this machine, about 1.2 s between requests, nothing stored)
Each page read in full, then checked as a watch would (stored hash, date and validators from the
full read). Bytes are the body as read (no Accept-Encoding is sent).

| Page | Full | Date stated | Validators | Check | Read | Saved |
|---|---|---|---|---|---|---|
| gwern.net/lean-scaling | 70,036 | dcterms.modified at ~33 KB | none | unchanged (head) | 48,000 | 31% |
| gwern.net/scaling-hypothesis | 290,410 | ~34 KB | none | unchanged (head) | 48,000 | 83% |
| gwern.net/spaced-repetition | 370,503 | ~33 KB | none | unchanged (head) | 48,000 | 87% |
| gwern.net/complement | 204,894 | ~34 KB | none | unchanged (head) | 48,000 | 77% |
| gwern.net/backstop | 352,688 | ~34 KB | none | unchanged (head) | 48,000 | 86% |
| gwern.net/search | 215,602 | ~33 KB | none | unchanged (head) | 48,000 | 78% |
| gwern.net/blog/2026/llm-timetravel | 56,976 | ~33 KB | none | unchanged (head) | 48,000 | 16% |
| gwern.net/fiction/walking | 64,380 | ~33 KB | none | unchanged (head) | 48,000 | 25% |
| **Gwern, 8 pages** | **1,625,489** | | | | **384,000** | **76%** |
| en.wikipedia.org/wiki/Neural_scaling_law | 442,709 | JSON-LD at ~370 KB (past the head) | Last-Modified | 304 | 0 | 100% |
| arstechnica.com (article:modified_time) | 151,882 | ~1 KB | none | unchanged (head) | 48,000 | 68% |
| techcrunch.com | 236,325 | ~2 KB | none | unchanged (head) | 48,000 | 80% |
| blog.cloudflare.com/php-ctf | 290,468 | ~12 KB | Last-Modified | 304 | 0 | 100% |
| theverge.com | 509,906 | ~3 KB | ETag (changes per request) | unchanged (head) | 48,000 | 91% |
| danluu.com/ambitious (no date) | 46,529 | none | ETag, Last-Modified | 304 | 0 | 100% |
| bbc.co.uk/news/videos/… (no date) | 370,354 | none | none | whole page; hash differed | 370,354 | 0% |
| jvns.ca/blog/2026/09/27/… (no date) | 17,439 | none | ETag | (two full reads: same text) | | |
| paulgraham.com/greatwork.html (no date) | 79,767 | none | none | gone: the reader finds no article (a table layout) | 79,767 | 0% |
| **Others, 8 pages checked** | **2,127,940** | | | | **594,121** | **72%** |

- gwern.net's head ends near 35 KB and its `dcterms.modified` sits at 33-34 KB on every page, so
  48 KB was chosen over the first try's 64 KB (Gwern saved 69% at 64 KB, 76% at 48 KB). A short
  page (llm-timetravel, 57 KB) saves little; the long essays, where it matters, 77-87%.
- Pages that state no date: one with validators answers 304 (danluu); one without is read whole
  every check. The BBC page's article text differed between two reads 1.2 s apart by one word
  (twice; the address with its feed's `&amp;` query): the hash changes, `change_summary` says
  `{words_added: 1, words_removed: 1}`, not meaningful, so nothing comes back. That is the case
  the threshold is for.

### Left open (for the owner)
- The threshold (50 words or a section) and the schedule (50 a fetch, 1-14 days) are guesses
  sized for Gwern; worth a look after a month of real updates.
- Feed posts read through full text are not watched (above).
- An archive run that re-reads a stored page overwrites its text silently, as before (archives
  are not watched).
- Paul Graham's essays cannot be read as articles at all (0 words), watched or not: a reader
  issue, not this one.
