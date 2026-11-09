# 0143 Built: the smart archiver

Built 2026-11-09 on its own branch, on 0140 (merged). **No migration** (settings keys and two system_settings keys).
No request in the tests: FakeHttp answers and hand-written fixtures in each platform's shape on invented hosts
(`backend/insight_core/tests/test_smart_archiver.py`). Private rows stay in `plan/research/0143-notes.md`.

## What changed

| # | Spec | What changed |
|---|---|---|
| 1 | A platform fingerprint | `ingestion/archive_ladder.py` `fingerprint`: votes from the feed (its generator, namespaces, item addresses), the home page (`<meta name=generator>`, asset paths, `link rel`) and headers; a generator or a hosting suffix weighs 3, anything else 1. `PLATFORMS` is the table: `wordpress`, `blogger`, `ghost`, `newsletter`, `bearblog`, `hugo`, `jekyll`, `medium`, `writeas`, `micro.blog`, `tumblr`, else `unknown`; each row says its feed paging, its API, its listing pages. The home page is read only when the feed gives fewer than two votes. Stored as `settings.archive.smart.platform` and `.evidence`. |
| 2 | The ladder | `Ladder.run` probes every strategy of the order (a request or two each, `PROBE_GAP_S` apart, counted): **feed pages** (RFC 5005 `rel=next` / `prev-archive`; WordPress `?paged=N`, Ghost `<feed>N/`, Write.as and Tumblr `?page=N`), **API** (WordPress REST with `x-wp-total`, found from the home page's `api.w.org` link; Blogger's JSON feed with its total; the newsletter platform's archive on any domain, run by its own kind without the owner's cookie), **sitemap** (0108's reader, now with gzip and, when robots.txt names none and `/sitemap.xml` is missing, the posts' files blog platforms write), **listing** (the platform's listing, the feed's `<link>`, `/blog/`, `/archive/`, `/posts/`, home; `rel=next` or `/page/N/`; post links by the feed items' shape: their section, depths, the folders they share or that are numbers, a list word as the last segment or a taxonomy folder never a post), **Web Archive** (CDX for the posts' section, opt-in per source `settings.archive.web_archive`, each page read live or from its capture when the live one answers 404/410). The archive (`GenericRssKind.archive_pages`) runs the strategies that found more, in order, each skipping what was seen or is stored, and stops once the seen addresses reach 95% of the estimate. Every strategy is resumable (checkpoint `mode` = the strategy, `ladder` = the rest); an old `sitemap` checkpoint resumes as before. `generic_rss` is `chronological` now, so 0130 C's date stop applies to feeds. A post found by address is read by `_sitemap_post` (0140's rules for feed and API posts via `_maybe_expand`); all are backlog. |
| 3 | Coverage | `coverage_status`: `archived` when stored ≥ 95% of the estimate (the largest of the API's total, the sitemap's count, a listing's count, a paging total) or every strategy was tried and none finds more (the plan) or the archive ran the ladder to its end (`exhausted`); else `partial`. The writer (`archive_metadata`) keeps `smart` and applies it on plan, progress, archive and live fetch: a plan that finds more makes an "archived" feed partial at once. Reasons are each other strategy's outcome (`no_sitemap`, `sitemap_no_posts`, `listing_unread`, `api_refused:403`, `blocked:429`, `paging_same`, …). The status API and the catalog carry `coverage` (`coverage_of`); a short feed archives once its ladder found more. Frontend: the archive section shows `Stored 19 of ~34`, `Built with Bear Blog; the rest is read from the listing pages.`, each reason, and the Web Archive checkbox (`PUT /api/archive/{id}/web-archive`); the catalog line reads `19 of ~34 stored`. |
| 3b | The learned ladder | `LearnedLadder` (system_settings `archive_learned`, `{platform: {strategy: posts}}`): a strategy that gave posts is counted for its platform; `ordered` puts the platform's best first. Never per site. |
| 4 | The re-run | `scripts/rerun_archives_0143.py`: at the scheduler's start (a thread, like 0140's repair), every enabled feed source whose archive says `archived` with no `last_archived_at`, or whose stored count is about its feed's (stored ≥ available − 1), is planned again through the ladder, one at a time, `PLAN_GAP_S` apart; where a strategy finds more, an archive is queued (0130's lanes, one per host). Each is marked `settings.archive.rerun_0143 {at, outcome, platform, strategy, requests}`: resumable, a later start plans nothing. The summary (system_settings `archive_rerun_0143`, logged) counts selected, queued, nothing more, errors, platforms, the requests the plans spent, and on each later start the sources gone from capped to full and the reasons of those left partial. Nothing with `INSIGHT_DISCOVER_READS=0` or `INSIGHT_ARCHIVE_RERUN=0`; `--dry-run` by hand. Telegram, X and every other kind untouched. |
| 5 | What each source discovered | `GET /api/sources/{id}/discoveries` (`routers/source_discoveries.py`, `db/repo_source_discoveries.py`, read only): the sites and accounts it linked that Discover lists (Discover's kept counts name the sources; open / followed / hidden as Discover says), the sources you added after INSIGHT first stored its link to them (inferred), the originals collected because of it (`story_originals`: its posts link the address, or its story holds one of its posts), the entities it named first (`mx_mentions_now`, the earliest mention is its post). Followed first, then voices. The source sheet's block **Discovered through this source** (`SourceDiscoveries.tsx`). |

Design: `sources.md` claims `archive-coverage` and `source-discoveries` (scenarios on the fixture site, the coverage of two feeds and one source's discoveries).

## Measure: fixtures, per platform

`FixtureMeasureTests`: each site holds 7 posts, its feed the newest 3; the archive must store all 7 and nothing else.
Requests: the plan's probes and the archive together, failing probes (404s) included.

| Fixture | Platform | Strategy | Feed | Site | Stored | Wrong | Requests |
|---|---|---|---|---|---|---|---|
| WordPress (feed ?paged=N) | wordpress | feed_pages | 3 | 7 | 7 | 0 | 33 |
| WordPress (REST API, the feed ignores ?paged) | wordpress | api | 3 | 7 | 7 | 0 | 31 |
| Blogger (JSON feed) | blogger | api | 3 | 7 | 7 | 0 | 27 |
| Ghost (/rss/N/) | ghost | feed_pages | 3 | 7 | 7 | 0 | 33 |
| Any feed (RFC 5005 rel=next) | unknown | feed_pages | 3 | 7 | 7 | 0 | 30 |
| Newsletter platform (own domain, archive API) | newsletter | api | 3 | 7 | 7 | 0 | 38 |
| Static site (gzip sitemap) | unknown | sitemap | 3 | 7 | 7 | 0 | 20 |
| Blog (no robots sitemap, post-sitemap.xml) | unknown | sitemap | 3 | 7 | 7 | 0 | 30 |
| Hugo (listing with rel=next) | hugo | listing | 3 | 7 | 7 | 0 | 26 |
| Bear Blog (one-page listing) | bearblog | listing | 3 | 7 | 7 | 0 | 25 |

70 of 70 posts, **0 wrong**. Before this version every one of these sites archived 3 (the feed), the two sitemap
fixtures aside (the gzip one and the fallback file were never read: 3 too).

## Real checks (read-only, the 2026-11-05 export `insight_server_1105`; a migrated scratch copy for the last, dropped)

1. **The re-run's selection:** 137 enabled feed sources, **102 selected** (84 "archived" whose archive never ran,
   18 stored about the feed's count). The three Bear Blog sources of the notes are among them (stored 33 / 11 / 19,
   status archived, never archived, the feed's 10).
2. **The post shape on real addresses** (the listing and Web Archive strategies read links by it): for 134 feeds,
   the shape of the newest 30 stored addresses against every older stored one: the first version refused 31%
   (a section word anywhere was "a list": `/blog/<slug>` on a site whose feed mixes two sections). Fixed by the class
   (a list word only as the last segment; taxonomy folders anywhere), then **6,867 of 7,744 match (88.7%)**; of the
   877 refused, 842 are on another host (aggregators and link blogs: right to refuse), 35 another section or depth.
3. **The fingerprint without a request** (the feed's address and stored item addresses only): 3 Bear Blog, 1 Blogger,
   1 Medium, 132 unknown: the rest needs the feed's generator and the home page, which the plan reads.
4. **The discoveries GET** on the migrated copy, the 5 feeds with the most posts: 185–446 ms; 179–931 Discover keys
   each, 8–73 followed, 2–24 inferred as followed after it linked them; no originals or entities in that export.

## Checks
- Backend: `test_smart_archiver` 40 OK; the 39 modules that touch ingestion, archives, sources, the scheduler, the
  feed finder, full text, Discover and voices: 978 tests OK (a 40th name given was no module); after the last
  cleanup `test_smart_archiver` + `test_sitemap_archive` 50 OK. The four 0108/0027 support tests stay as they were
  (a short feed the ladder never measured is still refused until the re-run plans it). Frontend: `npm run build` OK (feed route +0.05%, post
  +0.06%), `npx vitest run` 847 OK, `node --test src/lib/*.test.ts` 243 OK.
- realdata-check: run at merge (owner's rule of 2026-11-09).

## Open
- The measure after the deploy (spec 1–3): the Bear Blog sources before/after against their site's count, five capped
  sources of five platforms, the re-run's summary (capped → full, partial with reasons, requests): rows to
  `plan/research/0143-notes.md`.
- The plan costs more requests than before: up to ~10 on a site with nothing more (home, robots, sitemap and four
  fallback files, four listing addresses), once per plan; the re-run plans 102 sources once.
- The sitemap's order is lastmod, not publication: with a date to stop at, an old post edited recently can stop a
  sitemap archive early (the listing, the feed pages and the APIs go newest first).
- "Followed from a suggestion it fed" is inferred: nothing records where a follow came from. Recording it needs the
  add dialog to send its origin (a later issue). Entities named first are not resolved through merges and splits.
- The estimate from a paged listing is (posts on the first page × the last page number): approximate; it only
  decides coverage when the listing is the largest estimate.
- Platforms in the table not measured on any real site from here: Write.as and Tumblr paging, Micro.blog's archive.
