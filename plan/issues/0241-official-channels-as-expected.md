# 0241 — Official channels that work as expected (0237 #4, v10.26 slice D)

Issue 0196's official channels, Shadow since 11-14. The server's view on 2026-11-19 (private
`plan/research/v1026/official-2026-11-19.json`) held would_add 5, candidate 5, refused 203 and covered 93. It showed
200 of those 306 rows.

## What was wrong (from the code and the 200 rows)
- **A section was proven by the event's page alone.** `_proof` passed a section when its read held the event's own
  page (`holds`), or its path matched `ANNOUNCING`. A product's page sits under its product section, so a plans page,
  a prompts page, a solutions page, API guides, a family-safety resources page or a shop's category could pass.
  - On the server, all six were candidates or "no dated stream" refusals.
  - With scraping regardless (0240), their pages would read as dated streams.
- **The path rule missed real news sections.** `ANNOUNCING` matched whole segments only. These were refused
  "no announcements" although their feeds were press releases:
  - an IR `/news-events/` section (its feed `/news-events/press-releases/rss`);
  - a central bank's `/newsevents/` (`press_all.xml`);
  - an agency's `/alerts/`;
  - `blog.<site>/p/`.
- **Candidates came only from the event's page's section.** For one company the web search gave an IR news section.
  It was refused, and the company's newsroom host was never a candidate.
- **The review view** read the newest 200 rows by decision time and then sorted them by state. The 5 would_add rows
  were older than the newest 200, so they never showed.
- **X accounts read as "gone".** Two well-known active accounts were refused "no dated stream: gone". The code has two
  causes:
  1. **The test read used a fixed bridge.** `discover_reads.kind_source` built `https://nitter.local/<user>/rss` from
     the constant `NITTER_BASE_URL`, and Telegram from `TELEGRAM_BASE_URL`.
     - The add path builds the address with `nitter_origin()`, the first host in `NITTER_HOSTS`
       (`feed_finder.bridge_feed`, `feed_finder.py:270-288`; `scout._x_bridge`).
     - So the test read went to a different host than the one the owner's source would be read from.
     - That host is in `nitter_rss.NITTER_HOSTS` and the private-address allow list, so it was fetched. A 404 from
       it became `ReadResult(reason="gone")` (`scout_reads._reason_of` → `feed_finder.REASON_BY_STATUS[404]`).
     - With `NITTER_HOSTS` empty, the read still went to `nitter.local`.
  2. **Any 404 was "gone".** Nitter answers its "User not found" 404 also when it could not load the profile (its
     sessions, a rate limit). `official._proof` turned any unreadable judgement into "no dated stream: <reason>" and
     refused it for REFUSED_DAYS (90).
  - Not checked: which cause applies on the server. Checking means reading `NITTER_HOSTS` there and asking the bridge
    for one of the accounts. The owner's order forbids that today.
- **The gate** ("one event of one actor in 30 days with under 3 voices: not yet") refused 42 of the 200 rows shown:
  21% of the rows, and 29% of the 146 refusals shown.
  - It is applied after the proof, on proven channels.
  - It decided alone for 3 of the 42: the worker said follow and fits.
  - For the other 39 the worker said skip (24) or maybe (15).
  - **Kept as is.**

## What changed
- **One rule for "the company's news section"**: `services/discover_main_source.announcing(url, *, address, items,
  via) -> int`. It returns:
  - `NEWSROOM` (2): a newsroom, news, blog, press, releases, changelog or alerts section, by its host's first label
    (`newsroom.<site>`, `blog.<site>`, never a site called `newsroom.<tld>`) or by a path segment or a word of one
    (`news-events`, `press_all`, `newsevents`);
  - `INVESTORS` (1): the same on an investor-relations host or section, so a company's newsroom comes first;
  - `NOTHING` (0).

  A section whose path says nothing can announce by the dated stream its read returned, in one of three ways:
  - the resolved address announces (a newsroom page, a press feed);
  - half its dated items or more sit in an announcing section;
  - it is a feed whose items sit under the section itself (a site's `/p/` posts).

  It lives with the section rules (`section_of`, `channel_of`).
  - **Slice B's card lead now reads it.** `discover_rules.announcing_place` is
    `announcing(...) == NEWSROOM`, so an IR host never leads a card. This is a minimal edit in B's file.
  - `official.ANNOUNCING` is gone.
  - Hosts: `stories.` counts as announcing; `research.` and `media.` do not. A media host is a file host in
    `channel_of`, and a research host's `/blog/` counts by its path.
- **Candidates from the actor's site** (`official.site_sections`, `_site_sections`). Each section candidate's site
  gives its best announcing section, and so does the web search's actor's site.
  - Where the best sections come from: the sections your posts link there (`post_links`, two links or more). It is
    one query for the pass's sites, plus one for a search's site not among them.
  - The new candidate must be owned by the actor's name or site, so a store's newsroom is never taken for a maker
    whose app page sits there.
  - Sections on that site that announce less are dropped, with "its site's news section X is tried instead". A
    plans page under which the event's page sits, or an IR section beside a newsroom, is dropped this way.
  - A quiet section with nothing beside it stays a candidate, read once. Its read must show an announcing stream.
  - `channel()` takes the root of an announcing host (`newsroom.<site>/`).
- **The proof** (`_proof`): a section passes by `announcing` only. `holds` is still shown but is no proof, and the
  proof records `announces: path | stream | null`.
- **An account the bridge could not read** (x, telegram, no items) is "not read: the bridge could not read it
  (<reason>)", never "no dated stream".
  - `proof.retry` reads it again after RETRY_DAYS (3), at most RETRIES (5) times.
  - The X and Telegram rows already refused as "no dated stream" are read again too.
- **The test read goes through the add path's bridge.** `discover_reads.kind_source` now uses
  `feed_finder.bridge_feed` (`NITTER_HOSTS`' first, the Telegram bridge's origin). With no bridge set, no kind reads
  the account. This is a minimal edit in B's file.
- **Scraping regardless (0240)**: official reads through the judgement's test read (`source_judge.read_and_ask` →
  `scout_reads.Reader.read` → `where_linked.follow`), so it gets C's step 5 with no call of its own.
  - The rows refused before the v10.26 rules are read again once: "no dated stream" rows read again
    (`SJ.ask(..., again=True)`), and "no announcements" rows decided again on their judgement's read.
  - "Before" is the mx_settings mark `official_reread_v1026`, the first pass's time.
  - It is bounded like the other reads: 20 stale rows a pass, READS_PER_RUN reads.
  - No migration.
- **The review view** (`official.view`, `GET /api/official?offset=&limit=&state=`):
  - rows in the order would_add, added, candidate, proven, covered, refused, undone, the newest first within a state;
  - a page of 100 by default (500 at most);
  - `counts` over every row, `total` for the states asked.
  - `OfficialChannels.tsx`: each group counts its rows from `counts`, and "Show N more" pages its states 50 at a time.
    The proof line says how a section announces, or that the bridge will read the account again.

## Tests
- Backend: `insight_core.tests.test_official_0241` (14 tests, new) and `test_official_0196`. Also run, all passing:
  `test_discover_main_source`, `test_scrape_regardless_0240`, `test_discover_reads`, `test_discover_cards_0239`.
- Frontend: `components/sources/officialChannels.test.tsx` (7 tests) and `tsc --noEmit`.

## Mode: stays `shadow` until measured. The measurement plan
1. **After the deploy, wait for the re-read to drain.** Let the job run until no row refused before
   `official_reread_v1026` as "no dated stream" or "no announcements" is left: about 20 rows a pass. Record the
   counts by state and by `why`.
2. **The set: rows that are new since the mark.**
   - every `would_add` row (the 5 from 11-19, plus those new since the mark);
   - every row newly proven since the mark, whatever it became next (would_add, or refused by the gate or the worker);
   - every `site_section` candidate.
   - Freeze the set by its row ids. Rows found after the freeze are a second set.
3. **The question:** for each row, is this channel the actor's own announcements stream, worth following, with the
   right item filter? Read it blind: the channel's address and ten of its items, without the module's why or the
   worker's verdict.
   - I judge each row first (memory `claude-reviews-entities-first`). The owner sees only my flags.
4. **The bar:** point ≥ 97% and Wilson lower bound ≥ 90% on the would_add rows, with at least 30 rows. If there are
   fewer than 30, run more passes before judging.
   - Also report the gate's refusals of proven channels the worker said follow to (3 of 42 on 11-19), so the gate's
     cost is visible.
5. **On pass:** `INSIGHT_OFFICIAL=on`, with the 5-a-day cap (`INSIGHT_OFFICIAL_ADDS_PER_DAY`) and Undo. After a week,
   check the Undo count.
   **On fail:** the wrong rows go in the cases file (built right / wrong / missed), and the class fix waits.
6. **X accounts:** on the server, read `NITTER_HOSTS`, then find the reason each X row gives after its re-read.
   - The bridge's own failures stay "not read" for 5 tries before a refusal.

## Owed on real data
- The measurement above.
- Which X cause applied on the server.
- How many of the 8 "no announcements" rows now pass. Read by hand from the JSON, 7 should pass by path or by the
  resolved address; the 8th (a site-wide feed) depends on its items, which the JSON does not hold.
- How many quiet-section candidates a site's news section replaces.
- The `site_sections` query's time on the server's `post_links`. `target_site` has no index; the query is one scan a
  pass for at most 20 events' sites.
