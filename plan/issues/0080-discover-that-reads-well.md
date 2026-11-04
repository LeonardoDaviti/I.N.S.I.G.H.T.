# 0080 — Discover that reads well: tested suggestions, real names and titles, owners not platforms

Status: **spec, decided** (owner, 2026-11-04: "80 everything recommended"), written 2026-11-04 from a read of the server's Discover (owner: "does very bad discovering"). Planned for v9.17, after 0076 and 0077. It starts after 0072 A merges, because that branch holds `stories_service`'s Discover code. Builds on 0050, 0060, 0065 and 0067.

**Constraints:** no real source names in this file or fixtures; measure on a copy of the lab and on a fresh server copy; nothing merges unless `scripts/realdata-check.sh` passes.

## The case (the server, 2026-11-04; the data is kept privately in `plan/research/discover-prod/`)

| What | Count |
|---|---|
| suggestions | 1,122: 632 sites, 478 X accounts, the rest platform accounts |
| that start none of your stories and hold no classic | 1,019 |
| names of the sources linking them that are a feed address (`https://…/feeds/main`) | 1,411, in 609 suggestions |
| article lines shown as a bare address | 3,908 of 10,682 |
| article titles rebuilt from the address's words ("Ai jobs white collar unemployment …") | 3,982 |
| whole platforms suggested as one site, including **#1 and #2** (a model hub, a preprint server), a blog platform, a Mastodon server, a creators' platform | 5 |
| help, docs and support sites (`help.…`, `support.…`, `docs.…`) | 7 |
| a site you already follow suggested again, because some of its pages are outside your feed | 2 |

**Tested from this machine** (the top 60 sites, and the first article of the top 80 suggestions):
- 10 sites refuse plain readers (HTTP 401 or 403), including 6 of the top 40: a wire service, two business papers, a paywalled tech newsletter, a news site, and the help site of a source you follow;
- 2 refuse with HTTP 400 or 406, and 1 article answers 402 (a paywall);
- 18 home pages announce no feed.

Discover tests nothing, so it can't tell "follow this" from "you'll only ever get headlines".

## Why it reads this badly (causes, not symptoms)
1. **Discover counts, it doesn't check.**
   - A suggestion is "3+ of your sources link it" (0050).
   - Whether it can be followed, what it is (a publication, a platform, a help centre) and whether it is readable were never asked: "fetches nothing" was a rule.
2. **Every fallback leaks onto the page.**
   - A source with no name shows its address (`SourceFacts.voice_name` returns `sources.name`, which the importer filled with the feed address).
   - An article with no stored post and no link words gets its address's slug in title case (`origin_title`), or the bare address.
   - Each fallback was a sensible last resort, but nothing counts how often the last resort is what's shown: here it is 74%.
3. **The unit is the host.**
   - That's right for a publication. It's wrong for a platform, whose host holds pages from many owners: there the owner is the source (0060 did it for X, GitHub and YouTube from a fixed list of platforms, `DISCOVER_PLATFORMS`).
4. **No size limit.** Every candidate is listed. 0067 cleaned what shouldn't be there, but nothing limits what's shown first.
5. **It was never reviewed on production data.**
   - 0067 was judged on the lab (30 Oct).
   - The reader review covers stories, News and the feed more than Discover.
   - 0075's invariants check Discover's titles against the feed's, not whether a name or title is an address.

## Decided (owner, 2026-11-04: every recommendation, including the first page of about 30 and the follow test's requests)
1. **One name for a source, everywhere.**
   - A source's display name is its own name, else its feed's or site's title, else its host (`example.com`), and never an address.
   - It's one function, used by the feed, stories, News, Classics, Discover and source health (the class of 0072 D1's titles).
   - Measure how many sources it renames.
2. **One title for a linked page.** In order:
   1. the stored post's title;
   2. the link's own words, when they are a title (not "here" or "link");
   3. the page's title, read once and stored for the top suggestions' articles only (see 4);
   4. otherwise, the line shows the site and section (`example.com · blog`) and no title.

   A bare address and a title rebuilt from the address's words are never shown.
3. **Owners, not platforms, from the data:**
   - a host is a platform when the pages your sources link there have **many different first path segments, each linked by different voices**;
   - its suggestions are those owners (`hub.example/org`, `forge.example/team`, `social.example/@user`);
   - measure the threshold on the lab, and check it on hosts nobody named;
   - `DISCOVER_PLATFORMS` stays only as long as the measured rule needs it.
4. **Test what's shown, then label it:**
   - for the suggestions on the first page, run the feed finder (the same path every source add takes: the feed finder, then page watching) once, and store the answer with a date;
   - labels:
     - **Feed found**;
     - **Page watching**;
     - **Headlines only** (a paywall, or no feed and a walled page);
     - **Blocks readers** (401 or 403 on every way of reading the finder knows);
   - "Blocks readers" and "Headlines only" sink below every followable suggestion and say so;
   - this changes Discover's "fetches nothing" rule: a few small requests, only for what's shown, never repeated within 30 days.
5. **References aren't sources.**
   - Help, docs, support, status and government pages are linked as references: their pages aren't dated articles.
   - Decide by what the links are (pages with no date, or stable URLs linked again and again), not by a list of subdomains; measure it.
   - They go to a quiet "References your sources use" line, never into the suggestions.
6. **A site you follow is never suggested.** Pages of it outside your feeds go to "missing from a source you follow" (0065's archives).
7. **Fewer, ranked, each with its reason:**
   - the first page holds about 30;
   - rank by:
     - the stories it started;
     - its classics;
     - how recently your sources linked it;
     - how much you open what they link there;
     - whether it's followable;
   - the rest behind "More";
   - X accounts stay (owner, 0067: "sorted by impact, priority and sourced by") and are ranked by the same signals, not apart;
   - an X account's lines show its stored tweet's text, never a status address.

8. **A source's health says what failed, and waits as long as the error deserves** (moved to [0088](0088-v9.16-backoff-health-and-rail-order.md), 2026-11-04; moved here from 0081, owner 2026-11-04; the case: a feed service answering 502 put a source into a 6-day wait):
   - a 5xx is the other server's trouble, so retry within hours, never days;
   - the health text names the site, not "the server": "example.org is failing (HTTP 502): its own server didn't answer, usually temporary."
   - Files: the fetch backoff and the health text (ingestion and source health), not Discover's. This is its own slice.

9. **From the v9.15 reader review (2026-11-04):**
   - Discover sends 1.96 MB per open and draws all 1,070 suggestions at once: the first page's answer carries only that page;
   - Reddit authors inflate "linked by N of your sources": count followed sources there, as 0067's wording says;
   - the Saved source counts as a source on 5 suggestions: it never does.

10. **An archive row follows its archive** (owner 2026-11-04: "When I started archive from discover, why do I still see it in Discover?"). A row of "a source you follow whose own pages start stories it doesn't hold" stays until the archive has stored those pages and the story job has run, and it said nothing about the archive:
    - the row carries the source's archive as it is stored: running, paused or finished, and how many of the row's pages it has stored since;
    - while running: "Archive running · N of M found so far"; finished with pages still missing: "Archive finished · N of these pages aren't in its archive" (0084 B can fetch them later);
    - a source whose archive is running or finished gets no fresh "Archive…" button.

## Invariants added to 0075's check (each on every suggestion of the copy)
- No source name, voice name or article title is an address.
- No article title is its address's slug in title case.
- No suggestion is a host you follow.
- The first page holds at most 30, and each says why it is there.
- Every first-page suggestion has a follow test no older than 30 days.

## Measured before adopting
- The renamed sources (1).
- The titles by where they came from (2): the share of "no title" must be reported, not hidden.
- The platforms found (3), checked by hand on 20, and on hosts nobody named.
- The labels (4) on the first 60.
- Discover's answer time with the stored tests.

## Measured (2026-11-04, a copy of the lab and the server's saved answer; details private in `plan/research/0080-measure/`)
What the numbers change in the decisions above. Where they differ, **this section wins**.
1. **Names:**
   - 88 of 247 lab sources are named by their feed address (importer, no display name); 62 sources on the server.
   - No feed or site title is stored, so the fallback is the host.
   - The screen already makes address names readable (`frontend/src/lib/sourceLabel.ts`), so the addresses show in API answers, not on Discover's screen. The fix belongs in the backend's one name, built in 18 places today.
   - **Changed:**
     - the host fallback keeps the owner when the address is a multi-owner host (`newsletter.example/author`, `~user`, an author feed);
     - it drops feed-only subdomains (`feed.`);
     - two sources that would share a host keep their sections (`example.com/news` and `example.com/research`).
2. **Titles:**
   - 37% of article lines show a bare address and 37% a title rebuilt from the address.
   - Without reading page titles, 75% of all lines (87% of site lines) would show no title, so **reading the page title once, for the first page's articles, is required, not optional.**
   - An X line has its stored tweet only ~15% of the time, so otherwise it reads "a post by @account", never a status address.
3. **Platforms:**
   - **The rule:** a host is a platform when it has 50+ owner segments (or 15+ with none above 20% of the pages), and 2+ owners are each linked by 2+ voices. Numbers, dates, ids and language codes aren't owners; a 70%+ prefix (`/r/`) moves to the next segment.
   - **Results:** it finds 10 of 1,313 hosts, including two nobody named. It is debatable on a contributor-network magazine and a store.
   - **Added:**
     - the owner may sit at the third segment (a blog platform's company blogs);
     - a link from a source to its own page on a platform doesn't count (a creators' platform suggested from its own creators);
     - a host whose addresses hold paper ids and no owner (a preprint server) is a **paper source**, not a site: its papers stay in Classics and stories, and it is never a suggestion.
   - `DISCOVER_PLATFORMS` stays for video and Telegram, whose addresses the rule can't read.
4. **References:**
   - The data argues against "decide by what the links are": undated, re-linked pages are mostly ordinary blogs (44 hits, 0 references), and help and docs pages are linked in bursts like news.
   - **Changed:** references are found by the address's shape, i.e. a `help.`, `support.`, `docs.` or `developer.` host, or a `/docs`, `/help` or `/support` path. That is a shape rule, not a site list. It finds all 10 seen.
   - **Changed:** government sites are not references (they publish dated press releases); they stay suggestions.
5. **Followed sites suggested again:** 5 on the server and 6 on the lab, all coming in through where stories start.
   - When no section qualifies, the code suggests the whole followed host. Instead, it goes to "missing from a source you follow".
   - **Bug:** an aggregator's most common post host counts as a site you follow (`SourceFacts.followed()`: a link aggregator's posts make a large tech company's site "followed"). That hides the site from link-based suggestions and labels its section "of a site you follow".
   - Fix: a source that isn't the publisher of its posts' addresses (`NOT_PUBLISHERS`, aggregators and Saved) follows no site by them.
6. **Ranking:**
   - **Proposed:** score = 3·ln(1+origins) + 2·ln(1+classics) + 1.5·ln(1+opened) + ln(1+voices) + a recency bonus, after platforms, references and followed sites are removed.
   - The first 30 hold 7–8 X accounts.
   - Origins and classics carry it; recency is nearly flat and opens are sparse.
   - 7 of the server's first-page sites refuse plain readers, so the follow test's labels decide their place (they sink).

## Built: Discover (2026-11-04, branch `issue-0080-discover`)

From main b26874d, with main merged in twice (0083, 0075's scratch names). It is not merged or deployed and adds no migration. Nothing was fetched or downloaded. The code ran mounted on the local `insight-backend:lab-b26874d` image, and the frontend used the main checkout's `node_modules`. Every test of the follow test and the page titles uses recorded answers. Decision 1 ("one name for a source") and item 8 (health) are **not** in this slice. They touch News and ingestion, which other branches hold.

- **Platforms (Measured 3):** `discover_rules.find_platforms`, the measured rule:
  - 50+ owners, or 15+ with none holding over 20% of the pages, and 2+ owners each linked by 2+ voices.
  - The owner moves down past one segment that 70% of the pages share. A language segment is skipped (`/ru/companies/<owner>`). It never steps down twice: on the lab copy that turned a government site's `/government/publications/<doc>` into 16 "owners", so it was fixed.
  - It is computed in SQL with every count (`DiscoverRepository.platforms`). A row of `discover_addresses` is written by the platforms it was keyed by (`address_stamp`), so a host that becomes a platform refills.
  - On the lab it finds exactly the measured five hosts beyond the listed ones: a model hub, two social servers, a contributors' magazine and a store. Their owners are the suggestions.
  - A source's link to its own page (one of its names, `SourceFacts.selves`, in the first three segments) is no voice.
  - A host whose shown pages hold paper ids (a preprint's yymm.nnnnn, a DOI) is a paper source. It is never a suggestion, and its papers stay in stories and Classics.
  - `DISCOVER_PLATFORMS` stays for video and Telegram.
- **References (Measured 4):** a `help.`/`support.`/`docs.`/`developer.` host, or a `/docs`, `/help` or `/support` path on 60% of the shown pages (`place_kind`). These go to `references` and show on the page as a quiet line. Government sites stay suggestions.
- **Followed sites (Measured 5, decision 6):**
  - `SourceFacts.followed()` no longer counts a NOT_PUBLISHERS source's most-linked site. On the lab, the large company site that the aggregator made "followed" is suggested again, at #22.
  - In `origins()`, a followed site's pages outside the places your sources hold are never a suggestion. They are added to the stories the site's source misses (its archive row).
- **Titles (decision 2, Measured 2):**
  - A line is titled by the stored post's title, else link words that read as a title (`origin_title(..., slug=False)`), else the page's own title read once (below).
  - Otherwise the screen shows "site · section" (`untitledLine`), never the address and never a slug made into a title.
  - An X line uses only the tweet's own words, else "a post by @account".
- **The reads (decisions 2 and 4):** `services/discover_reads.py`.
  - Opening the first page starts one background read of what that page lacks. Each suggestion gets a follow test through `where_linked.follow` (the feed finder, then page watching), labelled feed / page / headlines / blocked (401 or 403 on every request). Each untitled article that isn't a tweet gets its page title read (`page_watch.page_title`).
  - Each answer is stored with its date in system_settings `discover_reads`, failures too, and is never re-read within 30 days.
  - Each host has one follow test at a time, and title reads are spaced by `HostLimiter`. `INSIGHT_DISCOVER_READS=0` turns the reads off.
  - Suggestions labelled Headlines only or Blocks readers sink below the rest.
- **Ranking and size (decision 7, Measured 6, item 9):**
  - The score is `discover_rules.score`. A roundup-only voice weighs half in its "sources" term, as 0067 has it.
  - `discover(offset, limit, q)` and `GET /api/sources/suggested?offset&limit&q` carry one page (30), and the page shows "More (N)".
  - "Linked by N of your sources" counts each voice once and a Reddit source once (its authors count only toward the 3-voice bar). Saved is never a voice.
- **An archive row follows its archive (decision 10):** `DiscoverRepository.archive_states` reads the newest archive job (running or paused), the archive checkpoint's `completed_at` (finished), and how many of the row's pages the source has stored since. The page shows "Archive running · N of M found so far" or "Archive finished · N of these pages aren't in its archive". It offers no fresh Archive… button then.
- **0075's check:** `discover.title_address`, `discover.name_address` (decision 1, so it stays high), `discover.title_slug`, `discover.followed_host`, `discover.first_page`, `discover.untested`. The snapshot keeps each suggestion's first three titles.

**On real data** (`scripts/realdata-check.sh insight_lab`, rebased on main c21bed8: **PASS**; private report `plan/research/lab/checks/issue-0080-discover-2026-11-04.md`):
- **Cases:** 69 pass, 14 fail.
  - Two turn to pass: the followed site's section (its expectation changed by decision 6: no suggestion, and the research source's archive row holds it, 22 stories), and "a Reddit user among your sources".
  - None turns from pass to fail.
- **Discover's invariants, main → this branch:**

  | Invariant | main | this branch | Note |
  |---|---|---|---|
  | slug-made titles | 3,663 | 15 | The 15 left are link words or stored titles that spell the slug |
  | an address as a title | 3 | 3 | Stored tweet titles; unchanged |
  | a suggestion on a followed host | 2 | 0 | |
  | the first page over 30 or without a reason | 1,040 | 0 | |
  | untested on the first page | 1,070 | 30 | Nothing is fetched on this machine |
  | an address as a name | 1,163 | 1,141 | Decision 1, not built |

  Everything else is equal. Stories, News and Classics don't change.
- **Discover:** 1,082 suggestions against 1,070.
  - 33 are new: model-hub owners and three contributors on the magazine, a big company's site (no longer "followed" through an aggregator), its research site and its podcasts.
  - 21 are gone: the model hub and the preprint server as whole hosts, the followed site's section, the followed lab's whole host and a followed lab's models page, 8 help and docs sites, a Mastodon server, the magazine as one host, two paper publishers, and two X accounts whose own site sources linked them.
- **The first 30, by hand:**
  - Each reads as a source to follow: a wire service, an AI lab's site and its accounts, an interpretability journal, model-hub owners (a fine-tuner, a lab, a chip maker, a search company, a model maker), business papers, a tech newsletter, research sites and investigative outlets.
  - 7 are X accounts.
  - Of their first three lines, 42 of 90 have no title yet (they read "site · section" on screen). The server's first open reads their page titles.
  - Two titles are wrong but read as titles: a citation ("<Author> et al. 2024") and a byline. Telling those from titles is Mark X.
- **Wrong or missed, by hand (further down):**
  - A hub's chat page is listed as an owner (#614): a kind of page the rule can't tell from an owner.
  - The creators' platform is still at #78. Its creators' names there differ from their channel names, so the self-link test misses them.
- **Tests:**
  - `./run-tests.sh`: 1,409 OK. One earlier full run had a single search-ranking failure that passed alone and in two later full runs.
  - Frontend: node 221 and vitest 701 pass; typecheck and the build pass.
  - The feed route is 172,839 B gzip against main's 172,801 (0.99% of the 1% budget, against 0.97%). The post route is 312,901 B against 312,843. Discover's chunk (SourcesConfig) is 132.5 kB raw against 130.3 kB.
- **Left open:**
  - Decision 1 (one name for a source) and item 8 (health): other branches.
  - Measuring the follow test's labels on the first 60, and the answer time with stored tests: both need the server, since nothing is fetched here.

## Built: Discover's speed (2026-11-05, branch `issue-0080-discover-speed`)

**The case:** after 0080 merged, the lab's Discover took 29.5 s on its first open after start and 32.0 s on the second, then 9 ms. v9.12 measured 239 ms cold.

**The first start after 0080 rebuilds every story.**
- 0080 changes the rules, so the incremental job rebuilds in about 74 bounded steps: every post's keys, the X threads and the names, then every post queued in batches.
- On a copy of the lab it took 1,433-1,722 s (24-29 min) at load 12-21. Plan for about half an hour on the lab. Each step is its own transaction, and the old rows are served until a batch replaces them.

**Cause:**
- Every rebuild step wrote a new `stories.computed_at`.
- Discover's kept counts are stamped with that value (`DiscoverRepository.stamp`). Its in-process list is keyed by the whole `stories` setting (`discover_inputs`).
- The keys, threads and names steps carry no addresses to count, so nothing re-kept the counts. Every open during the rebuild counted every kept link again: the counts SQL, the platform query, the mirrors and the titles, 7 s at load 3 and 12-51 s at load 12.
- The lab's two slow opens were two such full counts; 9 ms came once the rebuild was over.
- The counting itself costs what it did, give or take: the self-link test adds 0.1 s.

**Fix:**
- `_settle` keeps `discover_at`, when what Discover counts last changed. It moves only on a batch, a full run, links read, or a step that changed boilerplate links.
- A setting from before it keeps its last run's time as `discover_at`, so counts kept by the old code stay valid across the deploy.
- The stamp and `discover_inputs` read `discover_at`.
- A story run's incremental count keeps the kept platforms; the platform query (2.3 s) runs only on a full count.

**Measured** (copies of the lab, Discover opened by a fresh service, as after a start):

| | main | this branch |
|---|---|---|
| a settled copy | 0.41 / 0.35 s | 0.44 / 0.33 s |
| after each of 4 rebuild steps (load 3) | 7.23, 7.21, 7.35, 7.30 s | 0.39, 0.38, 0.36, 0.39 s (8 steps: at most 0.74 s) |
| a cached open, same process | 0 s | 0 s |

During a whole rebuild run in its own process, the branch opened Discover 48 times, every 30 s. **None counted again.**
- The median was 1.14 s and 30 of 48 took under 1.2 s.
- The slow ones, up to 27 s, were single small reads stalled while the job saturated the database at load 15-21 (`discover_inputs`' three subqueries took 21 s once). Every other page's reads wait the same way then.
- After the rebuild, an open took 0.55 s.

**What Discover does during the rebuild now:** it serves the counts kept before the deploy, and the list it shows changes only as the rebuild's batches replace stories. The last step ("all") counts once in the job, not in an open.

**Checks:**
- `./run-tests.sh`: 1,410 OK, including a test that a step with nothing to count keeps the stamp, the inputs and the list, and that a batch moves them.
- `scripts/realdata-check.sh insight_lab` (scratch `insight_lab_8001a/b`): **PASS**, with no case and no invariant changed.

## Not in this issue
- Reading walled or JavaScript-only sites (0081).
- Mark X's "same voice" (0078 channels).
