# 0228 — An archive date taken from the article's text (0225 #2)

Status: **built on branch (v10.25 slice C)**, 2026-11-19. Migration `0156_body_dates_against_their_address.sql`.
Private rows (real names, ids, addresses): the main checkout's `plan/research/v1025/0228-dates.md`.

## What was wrong

Two posts the owner named. Their causes were found on the server (three read-only GETs, before the owner's
13:15 UTC order to stop) and on the pages as they are now and as the Web Archive kept them:

1. **A link blog's 2024 post (`/2024/Aug/30/…`) dated 2020-05-31.** It was stored on 2026-11-10 at 07:55 by the
   archive backfill (generic_rss `_sitemap_post` → `page_watch.page_date`). The code then running ranked "the one
   date written on the page" above the day in the address. That ordering was changed in v10.13.7, committed the same
   day, so today's code already dates this page 2024-08-30. Nothing repaired the rows stored before the change:
   0100 repaired future dates only.
2. **A lab's model page ("Introducing …", an address with no date) dated 2023-03-31.** This is not the same class.
   The page came in through `collect_for_source` (a page its feed missed, issue 0138 F2). The code then running read
   no date from it (two written dates; the byline reader came in v10.15). So `saved_service.first_linked` dated it by
   the first stored post linking it. That post is an essay dated 2023-03-31 whose page was edited in 2026-10
   (`metadata.modified`) to add the link. Today's code dates the page by its byline, 2026-09-22. The fallback is
   still open to an edited linker.

## What changed

- **`page_watch.page_dating(page, url) -> (date, how)`** now makes the date choice; `page_date` returns its date.
  It tries sources in order of trust: the page's markup (published_time, JSON-LD, meta date, its one `<time>`,
  scholarly tags), then the address's day, then the body (the byline, else the one written date). New: a body date
  is **held** (no date, how = `held`) when the address names a month it is not in, or when it is before the web
  began (1991-08-06). When a page is held, the callers' existing fallbacks apply: the archive and collected paths
  use the address's month (`address_hint`), and a page the watch shows now is dated now. A body date never wins over
  an address day: that was already true from v10.13.7 on, and a test now covers it.
- **`saved_service.first_linked`**: a linking post counts from `GREATEST(published_at, metadata.modified)`
  (`LINKED_SINCE`), because a page edited later shows its links only from that edit. This is a small edit outside
  ingestion/: the decision is made there and no other slice owns it.
- **Migration 0156**, following the pattern of 0099 and 0101, makes two repairs:
  - **A.** An own-site post (or a saved one) stored as a whole UTC day, whose body writes that day ("May 31, 2020",
    "Sept. 3, 2025"), and whose address names a different day (more than a day off) or a different month. It takes
    the address's day, or the 1st of the address's month, with precision `date`, and is sorted again.
  - **B.** A collected page whose date equals the old first link, where the new rule gives a later one. It takes
    the new one, never later than the moment it was collected.
  - A year alone is not used as a date. Running the migration twice changes nothing more.
- Not done, and why: a metadata date far from the address's day is **not** held. In the random sample, all 58
  addressed pages agreed with their address. Address parsing also has false days (`/2026/11/10-years-on-…` reads as
  the 10th), so holding on a disagreement would hold correct dates. "Before the source existed" is approximated by
  the web's start only. A source's first stored post is not a floor, because an archive reads backward past it.

## Measurements

- **Precision (frozen and hashed before scoring, blind Haiku labels).** The sample was 260 own-site posts of rss
  sources from the server-shaped clone (at most 6 per host, 130 hosts). 244 pages were fetched and 230 had an
  article. Five Haiku agents labelled 46 each, one label per page. Hashes are in the private notes. Both the v10.24
  choice and the new one showed 182 dates on pages with a known label, and **182 were right: 100%, Wilson lower
  bound 97.9%**. By source: markup 159/159, address 10/10, body 13/13. 3 more body dates fell on pages labelled
  unknown; I checked those by hand and they are bylines that sat beyond the 2,500 characters the labellers saw.
  45 pages got no date from either version. **No date was held**, so the new hold rule never ran on this sample.
- **Replay of the class.** I fetched the live pages of 575 address-dated own-site posts and ran the pre-v10.13.7
  order on them: 34 were dated from the body, 2 of them off their address (one per site, two sites). The v10.25
  choice on the same pages: markup 402, address 172, body 0, held 0, none 1. The class is rare: about 0.35% of
  address-dated pages. The rest of the replay (2,445 pages) was stopped when the owner's order came.
- **Counts before → after 0158.** Lab: 190 whole-day address-dated posts, 0 in class A, 0 collected pages (B):
  0 → 0. Server-shaped clone (148k posts, to 2026-11-05): 242 such posts, 0 in A, 0 in B: 0 → 0. Both sets end
  before the 2026-11-10 backfill, so the real population exists only on the server. **The server count was not
  measured.** Read-only query for the deploy: the CTEs of 0158 with `SELECT count(*)` instead of the UPDATE.
- **20 repaired rows checked by hand: not done.** No set I could reach had a repaired row, and the server is off
  limits.
- **Speed.** `page_date` over the 230 pages, 5 passes: 1.461 s (v10.24) and 1.465 s (v10.25). Peak RSS of the
  process: 125 MB and 123 MB. 0158 on the 148k-post clone: A 5.8 s, B 1.6 s. A second run updated 0 rows.
- **Tests** (module only, on a disposable `_test` database, run with the host's Python 3.12 venv, not in the
  image): `test_page_watch` (new `BodyDateTrustTests`), `test_archive_site_and_dates` (an edited linker; 0158 A and
  B), `test_page_watch_0172`, `test_saved`, `test_full_text`, `test_originals_rules`, plus the date-related modules
  listed in the slice report.
