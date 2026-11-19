# 0240 — Scrape regardless of a feed (0237 #3, v10.26 slice C)

Owner rule 2026-11-19: "I don't care if something has feed, we should scrape it regardless."

## What was wrong
The add path's test read (`where_linked.follow`, then `scout_reads.Reader`) is what all four callers use: Discover's
follow test, the daily judge (through Discover's label), the scout, and official channels (through the judgement).
Read on invented fixtures before the change, a site with no feed was "none found" in three common shapes:
- **A list page given as itself** (`corp.example/newsroom`, no feed): never previewed. For a page deeper than the home
  page, `own_section` offers only its section page when the address has two or more segments, and the pages the finder
  read under it. A one-segment section was never watched itself.
- **A home page built in JavaScript** with a dated `/news`: the finder reads only the blog and news pages the home page
  links. With no links there was nothing to preview.
- **A feed whose items are undated or titles only:** read as is. Health said "undated" or "titles only", and official
  said "no dated stream: 0 dated items read", even when every article page states its date.

The server's official rows (private `plan/research/v1026/official-2026-11-19.json`, 200 rows): 74 refused as "no dated
stream". By kind and reason:

| Kind | Reason | Rows |
|---|---|---|
| section | none found | 34 |
| section | gone | 8 |
| section | 1 dated | 2 |
| section | blocked | 1 |
| section | could not be read | 1 |
| releases | empty feed | 23 |
| releases | 1–2 dated | 3 |
| x | gone | 2 |

39 of the 46 sections are one-segment addresses: the first shape above.

## What changed
- **`where_linked.follow` step 5** (the one path; the Add source dialog gets it too):
  - When to try it: nothing is offered (no feed, or no feed holding the linked articles, and no page). Skipped when the
    site rate-limits us.
  - What it tries: `page_watch.list_offers`, which previews these pages one after another:
    - the linked articles' section (for a home page, or the page's own section);
    - the page itself, its parent and its first segment;
    - its sitemap's sections named news, newsroom, press or blog;
    - for a home page only, `/news`, `/newsroom`, `/press` and `/blog`.
  - What it offers: the first list page whose preview is a dated stream (`dated_list`: 2 or more posts dated, and at
    least half). Beside a feed, the list counts only if it holds linked articles.
  - A page under a section or an account (`hub.example/<org>`) keeps to it, as v10.13.5 rules: it is never offered the
    site's root lists.
  - Bound: one sitemap read, shared with the previews, then at most `LIST_TRIES` = 6 previews within `LIST_BUDGET_S` = 20 s.
  - On the JS-only fixture that fails, the step adds 6 requests: robots, sitemap and 4 lists.
- **Article dates:** each item is dated by its own page through `post_from` / `page_dating`. The order is the page's
  markup, then its address, then its body (byline or one written date). Body text never comes first.
- **News sitemaps:** a `<news:publication_date>` dates an entry before its `lastmod`, which is often a redeploy date.
- **`scout_reads.Reader._from_pages`:** a feed read as undated or titles only is read from its items' own pages, at most
  `DATE_PAGES` = 10, newest first.
  - Each page gives its date (`page_dating`) and its article text.
  - The read records `resolved.from_pages` = how many items a page dated or filled.
  - If the feed still reads badly, the page offered beside it is read instead, when that reads better.
  - Result: a titles-only feed dated by its article pages is a dated stream, both for health and for official's
    `MIN_DATED`.
- **When everything fails**, the reason is now `NOTHING` ("no feed, and no page that lists dated articles: …") instead
  of the finder's bare "none found".
- **The four callers:**
  - **Discover.** The follow test takes the same `follow`, so a site that scrapes is labelled `page`. `section()` then
    returns 0, so it is no longer "unfollowable". `discover_rules.order` needs no change; it orders by that label.
    *Minimal edit in B's `services/discover_reads.py`:* `FOLLOW_TEST` 4 → 5, and `due()` re-tests only the tests
    rule 4 left unfollowable. Rule 4's followable tests stand, since 0240 only adds ways in.
  - **Judge.** `source_judge.to_judge` still skips the unfollowable section, which now means scraping failed too.
    Only its docstring changed.
  - **Scout.** It reads through the Reader, so it gets the change. Only its docstring changed.
  - **Official.** It reads through the judgement's test read, so it gets the change. `official.py` is not edited.
    **For D's integrator:** refused rows are looked at again only after `REFUSED_DAYS` = 90, and an answered
    judgement is cached 30 days. To re-read today's "no dated stream" rows once, change one query and one call in
    `official.advance`:
    - the `stale` query adds `OR (why LIKE 'no dated stream%%' AND decided_at < <v10.26 deploy time>)`;
    - for those rows, call `SJ.ask(cur, row["follow"], now=now, again=True)`.

## Tests (invented HTML, no network)
`insight_core.tests.test_scrape_regardless_0240`, 16 tests:
- a newsroom with no feed (JS home page plus a dated `/news`), checked through `follow`, the Reader, official's
  `_proof`, the Discover label and `to_judge`;
- a list page given as itself;
- an article address finding its own section's list;
- an account page that keeps to its section;
- an undated press list whose pages carry JSON-LD dates;
- a titles-only undated feed dated from its pages (official's refusal before, a dated stream after);
- the `DATE_PAGES` bound;
- a JS newsroom dated by its news sitemap's publication dates;
- a JS-only site that truly fails (`NOTHING`, labelled `headlines`, not judged, 17 requests);
- undated lists that are not offered;
- a rate-limiting site that is not tried further;
- `list_pages` order, `dated_list`, and the `due()` rule.

`test_feed_finder.test_a_section_address_is_followed_as_it_is` now expects the section itself to be offered, and still
never the `/news` it links.

Module runs (scratch Postgres via `scripts/test-backend.sh`): test_scrape_regardless_0240, test_where_linked,
test_page_watch, test_page_watch_0172, test_feed_finder, test_discover_reads, test_discover_reads_well,
test_markx_scout, test_markx_source_judge, test_official_0196, test_discover_fixes_0172, test_discover_main_source,
test_markx_tracks, test_new_spheres_0137, test_new_spheres_0135, test_markx_research, test_archive_site_and_dates.
All OK (490 tests). Full suite not run (the integrator's).

## Owed on real data (not measured: no real data allowed in v10.26)
1. **Official refusals turned into dated streams.**
   - Take the 74 rows of `official-2026-11-19.json` refused "no dated stream". The 46 sections are the ones in scope;
     the 23 empty releases feeds are repositories with no releases, and the 2 X rows are D's.
   - Run the new test read on each row's `follow` address (`scout_reads.Reader` on a machine allowed to fetch).
   - Count the rows whose read now gives `MIN_DATED` or more dated items.
   - Then read the items blind: is each item a real announcement, is its date the article's own (open the page), and
     is it the actor's channel?
   - Report the share per reason (none found / gone / 1–2 dated) and Wilson's lower bound. This is the input to #4's bar.
2. **Discover's unfollowable section.**
   - Count the stored follow tests with `test = 4` and an unfollowable label: that is how many re-tests the first
     `read_first_page` after deploy runs. Each costs up to about 20 s more; check that the jobs pass stays in bounds.
   - Measure the share that become `page`, and read 30 of them blind: is the offered list the site's announcements?
3. **Request and time cost per failed read on real sites**: median and p95 requests and seconds of step 5. The
   fixture adds 6 requests; real sitemaps can be index files of up to 5 files.
4. **Dates from body text.** `page_dating` falls back to a byline or one written date. Measure how many items step 5
   and `_from_pages` date by `DATED_BY_BODY`, and check them against the page.

## Risks
- A guessed `/press` that redirects to the home page previews the home page's own links. The page is offered only if
  they read as a dated stream, which is the site's own news.
- The Add source dialog now shows the section itself as "a page to follow" for a feedless section address.
- Discover's re-test of rule-4 unfollowable rows is not capped per run.
