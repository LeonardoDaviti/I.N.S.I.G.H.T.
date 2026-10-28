# 0036 — Source doctor: a broken source finds its replacement

Status: **built** (2026-10-28, not deployed; migration 0032). Decided by the owner (2026-10-28: "our checker of sources should check if that old source is working, if not it should automatically run our feed finder or follow page and find all the posts"; "everything your pick").

## The case
`https://arena.ai/blog/rss/` stopped working; the source failed every fetch. Pasting `https://arena.ai/blog` offered "Follow this page instead": 76 articles.

## Decided
- **When:** after repeated failures (e.g. 3 in a row), or at once on a clear signal: HTTP 404/410, or the address no longer parses as a feed.
- **Look:** the feed finder (0026) on the source's address, its section (`/blog/` for `/blog/rss/`) and its home page; no feed → page watch preview (0028) of the section. Same rule as every source add.
- **Act:**
  - **Automatic switch** only when it is safe: a new **feed on the same site** while the old address is gone (404/410). The source keeps its id, name, tracks, read state and posts; only `handle_or_url` (and the kind) change; the job's events say "Arena: feed moved, now following arena.ai/blog/feed.xml".
  - **Otherwise suggest:** another site, page watching instead of a feed, or a flaky (not gone) feed → the Sources list and sheet show "Broken: INSIGHT found a replacement" with **Switch** and a preview ("Follow arena.ai/blog: 76 articles").
  - **Nothing found:** "Broken: no replacement found", plainly, not only "HTTP 404" in backoff.
- Posts match by URL, so a switch never duplicates what is stored; an archive after a switch brings the older ones.
- Rate: the doctor runs at most once a day per source.

## Built
- **One module**, `backend/insight_core/ingestion/source_doctor.py`, one entry point
  (`SourceDoctor.after_failure`), which the runner calls after every failed fetch with the
  exception and the fresh fetch state, outside the save lock. It never raises.
- **When:** `generic_rss` and `page_watch` sources of platform rss only (YouTube, Reddit,
  Telegram, Substack, site adapters and any other direct kind are never looked at); 3 failures in
  a row, or at once on HTTP 404/410 (`HttpError.status`) or an answer that does not parse as a
  feed (`ParseError`). At most once a day (`source_fetch_state.doctor_checked_at`), and not again
  in a streak whose finding was dismissed; a fetch that works clears the finding.
- **First, the old address** (v9.3, from the dry run): it is read again (`reads_again`: a feed
  that parses, by the finder's own proof; a followed page whose preview still lists articles).
  When it reads, the error was temporary: the finding is `{replacement: null, working_again: true,
  note: "temporary error, working again"}`, nothing is suggested, the health row shows no finding,
  and nothing else is looked at (devblogs.microsoft.com/oldnewthing's SSL error on the server).
- **Look:** `find_feeds` on the address (it reads the first-segment section and the home page
  itself) and on a deeper section (`/a/b/rss` -> `/a/b/`); the address itself is never its own
  replacement. A feed on the source's site must stay within its section (`within_section`: the
  address less its last segment, `/oldnewthing/` for `/oldnewthing/feed`; v9.3, from the dry
  run), so the home page's `devblogs.microsoft.com/landing` (every Microsoft blog) is never taken
  for one blog; a source at the site's root (`joanwestenberg.com/rss`) takes any feed of the
  site (`www.joanwestenberg.com/feed`). No feed: `page_watch.preview` of the section, which must
  read at least one article; for a feed source at the root that is the address itself, so a site
  whose address answers a page (incompleteideas.net) is suggested as a page to follow.
- **Act:** a feed on the same site (`www.` ignored) while the old address answered 404/410 is
  switched to: `handle_or_url` changes, `settings.page_watch` is removed, failures and backoff
  clear, the job gets the line "Arena: feed moved, now following arena.ai/blog/feed.xml" (and the
  log). A switch that fails (the address is already a source) becomes a suggestion. Anything else
  is stored in `source_fetch_state.doctor_finding` (`{replacement: {kind, url, title, found,
  prefix} | null, dismissed}`); the health row carries `doctor_looked_at` and `replacement`.
- **Routes:** `POST /api/sources/{id}/switch {url, page_watch?}` and
  `POST /api/sources/{id}/replacement/dismiss` (the fresh row; 404 without a finding).
- **sources.json:** every switch (doctor or route) goes through
  `SourceConfigSyncService.switch_source`: the DB change in one transaction, then sources.json is
  rewritten; when the file cannot be written the switch is undone, since a file naming the old
  address would make the next sync re-add it and mirror-delete the switched source with its posts.
- **Kind cache:** `KindRegistry` now keys on platform, address and whether `settings.page_watch`
  is set, so an address the feed finder once resolved as a feed resolves as page_watch after a
  Switch to follow it.
- **UI:** the Sources list note reads "Broken: replacement found" / "Broken: no replacement found"
  (note column widened to 10.5rem); the sheet shows "This source stopped working." with "INSIGHT
  found a replacement: <title> (<address>)" or "Follow <page>: N articles", Switch and Dismiss,
  or "INSIGHT looked for a replacement 2h ago and found none."
- **Limits:** the same-site test compares host names less `www.`, not the public-suffix list
  (`blog.arena.ai` and `arena.ai` are different sites, so that is a suggestion). An answer that
  is well-formed XML but not a feed (XHTML) reads as an empty fetch, not a failure, so the doctor
  never sees it. Nothing is re-fetched after a switch.
- Tests: `backend/insight_core/tests/test_source_doctor.py` (with the dry run's three cases:
  oldnewthing working again, and never the whole site's feed; joanwestenberg.com switched;
  incompleteideas.net followed as a page);
  `frontend/src/components/sources/replacementNotice.test.tsx`, `sourceList.test.tsx`.

## Dry run on the server's 7 failing sources (2026-10-28, before release)
| Source | Error | Doctor |
|---|---|---|
| joanwestenberg.com/rss | 404 | auto-switch → www.joanwestenberg.com/feed (same site, gone) |
| incompleteideas.net (Rich Sutton) | not a feed | suggest: follow the page (12 articles) |
| tedunangst.com/flak/rss | DNS | no replacement |
| dfarq.homeip.net/feed/ | garbled | no replacement |
| rachelbythebay.com/w/atom.xml | 404 | no replacement |
| devblogs.microsoft.com/oldnewthing/feed | SSL (temporary on the server) | **wrong:** suggested devblogs.microsoft.com/landing (all Microsoft blogs) |
| r/MachineLearning | 429 | skipped (Reddit kind) |

**Fix before release (v9.3):**
1. Check the old address first: if it reads as a feed now, record "temporary error, working again" and look no further.
2. A replacement must stay within the source's section (`/oldnewthing/…`); a home-page feed is offered only when the source was the whole site.
3. Tests from these three real cases.

**Fixed in v9.3** (release-9.3, test-first): 1 and 2 as written (see Built: "First, the old
address" and the section rule in "Look"), and 3 in `test_source_doctor.py`'s
`DryRunCaseTests`. incompleteideas.net's address is the site's root, which the doctor had
skipped as its own page; a feed source at the root is now followed as that page.
