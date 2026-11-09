# 0138 — Built (Stealth v10.10): originals from entities, Discover learns from originals, long-reads stored

Built 2026-11-09 on its own branch from main a45c7e9 (main merged in for sections E and F), parts A–F and the
orphan-entity fix. **Migration 0089** (`0089_entity_originals.sql`). Nothing here fetches from the development
machine: every request in the tests is a FakeHttp answer; the real checks below are GETs to the server and reads of a
scratch copy of the server's export.

**realdata-check: run at merge** (the owner's rule of 2026-11-09: agents no longer run it).

## What a deploy changes
- The decision run's entity stage writes `mx_entity_addresses` (Mark X table only) after identity's linking.
- Collect originals (on by default since 0126) now also collects **an entity's original** (B) under 0123's credit.
- **Store Classics** (new switch, **on** by default) starts the backfill: work sites (E2), long-reads' references
  (F1), followed sources' missed pages (F2) and the unstored Classics (E1), **at most 100 pages a day, 12 a run, one
  page at a time, 2 s apart**, apart from 0123's 1% credit. Switch it off in the Scheduler dialog to keep the old
  behaviour.
- **Look up unlinked originals** (C) is **off** until the owner switches it on.

## A. An entity's addresses (no request) — `utils/entity_originals.py`, `markx/entity_addresses.py`
- For an entity of `SPECIFIC_TYPES`, the links its posts carry (`post_links`, kept, not boilerplate, not a reference
  list) that are its own page, in this order (`RULE_ORDER`):
  1. `identifier`: the mention's ref (0133), an arXiv id or DOI its span or name holds, else — the post's only document
     — the one paper the post links (ent-v4.2 runs no citation rule, so this is how the owner's case is found). The
     page is the post's own link to the paper's page (never its PDF), else the canonical abstract / DOI page. The same
     post's single code repository and single demo are kept as the paper's links (kinds `code`, `demo`).
  2. `title`: the link's read title (Discover's read, else a stored post's title, else the link's words) is the name
     or an alias by the name key — whole, without a leading `[id]`, or one part of `Title | Site`.
  3. `maker`: a model / product / software whose maker's name is the site's own word; the page's title holds the name
     word for word **and the name is half the title's words or more**.
  - Never a front page or profile (`is_home`) — except a **document's work site** (E2: rule `site`, the site word is
    the name run together, or `title`), kind `work`.
  - Never a "release" that is a docs/help page, a store's or catalog's listing (`CATALOG_LABELS`) or a raw file
    (`not_a_release`).
- `mx_entity_addresses (entity_id, url, kind, rule, post_id, first_at)`, one row per (entity, address), never deleted,
  written under the entity's root; readers go through the merges (`current`, `of_root`) and keep a row only while its
  post still names that root in its current set. Incremental: the posts whose current set came since the last run;
  the full pass: every post. In its own savepoint: a failure is logged in the run's counts, never the run's.
- One address a kind (`pick`); the **original** is the paper, else the release page, else the work site.

## B. Collect an entity's original — `services/originals_service.py`
- Trigger (`triggered`): the entity is the `subject` (current set) of posts from 2+ voices in 7 days, or of one
  voice's post that leads a News row (the row's first report by position); `source` / `recommended` never count.
  Saved posts are no voice.
- Its original, not stored, not asked before (as 0123's or 0138's), is planned after 0123's News originals, by
  voices then newest, and read through 0123's path (classification, the host gate, the save path's `collect`).
  Recorded once in `story_originals` kind `entity` with `entity_id`. A paper page is an article here (tested).
- B5: the credit's cap rises from 3 to 6 while an entity original has waited on it over 72 hours (`credit_cap`); the
  run's summary reports `entity_wait_hours` so the wait can be measured on the server before relying on it.
- The entity page shows **Original** first: the stored post (`· collected original`) or the page (`not collected
  yet`), how it was found, then its code / demo / other pages.

## C. Look up unlinked originals (switch, default off)
- A document entity of 2+ voices with no address: the arXiv API's title search (`max_results=3`), else Crossref
  (`rows=3`); a match when the title is the name by the name key **and** an author of `by` is among the authors
  (whole name or surname). One credit per request; recorded once (`story_originals` kind `lookup`, url
  `entity:<id>`, `found` / `not_found`). A match is stored as an address (rule `lookup`) and collected by the next run.
  No `by`: not asked (nothing to check a match with).

## D. Discover learns from originals
- **D1** Pages lists entity originals (not stored, trigger met) after the stories' roots: "The original of <thing>,
  which N of your sources wrote about (names)", Save / Follow site / Hide as today; collected ones leave by
  themselves. Read on each open (`stories_service._from_originals`), never kept with the list, from the sources table
  alone (`repo_discover.light_facts`: the cold-open tests count SourceFacts builds).
- **D2** Each run keeps (`system_settings.originals_suppliers`) the sites that were the address of 3+ originals in 30
  days (0123's and 0138's asks, walled / no-article aside, and an entity's title-named release page beside a paper
  original: the summariser), not followed, not hidden, never a paper host. Discover adds them as suggestions (or adds
  the line to one already listed): "The original of N things your sources talked about"; Follow… is the feed finder.
- **D3** The first time each site was suggested is kept; Discover's `supplied` lists the sources you followed there
  since, with the originals each brought before any other source linked them (shown under the list, not ranked by).

## E. Long-reads that aren't feeds
- **E1 Store Classics** (`store_classics`, default on): every Classic not stored, not hidden, not asked, biggest voices
  first, through the same classification and save path (`story_originals` kind `classic`, the post's
  `metadata.collected_as = classic`: its post page says `· classic, collected`). A repository is read as its page
  (whose article is its README), a model card as its page.
- **E2 Work sites**: a `work` address linked by 2+ voices, never one whose site word names a product, software, model,
  org or person entity (E5), collected with its own pages your posts link (same host, at most 20, most linked first),
  kind `work`. When the work is also the document's original, B collects the front page and E2 its pages.
- **E3 The rabbit hole** on the entity page (org / person / document with 2+ works or 10+ posts): its sites
  (Followed ✓ / Stored ✓ / Follow / Watch page — both open Add source, the feed finder then page watching), its works
  (Stored ✓ / Collect: the save path), its people; **Go down the rabbit hole** collects every work not stored, then
  opens Add source on the first site not followed (every follow stays the owner's tap there).
- **E4** Discover's "Worlds to explore": "<entity>: N sites, M not followed, K works not stored".
- **E5** never products' / apps' sites, walled pages, or a whole site (only linked pages, max 20).

## F. A long-read's references, a followed source's missed pages
- **F1** A curated long-read (own text 8,000+ characters, Mark X's reading `commentary` or `roundup`, 8+ cited
  outside pages) you opened or kept (History's opens, Kept): its cited pages (another site's, not a front page or a
  platform profile, not an archive, app or docs page; a one-segment news slug is an article) collected once, at most
  30 a post, kind `reference` with `from_post_id`. A followed source's cited page is read as F2 reads one.
- **F2** A followed source's own page (0084 B) that another source's post linked in the last 30 days and the feed
  never carried: read once and stored **as that source's post** (`collect_for_source`, `metadata.missed_by_feed`),
  kind `missed` with `source_id`. A post with 3+ links counts its first only (Mark IX's roundup rule); a tweet is
  never read. The ingestion tab's sources table says `in feed · partial` (the count on hover).
- **F3** `longread_citations` (kept each run): the sites the long-reads you opened cite; Discover adds "Cited N times by
  long-reads you read", and a site cited 3+ times by 2+ long-reads is suggested below the voices bar.

## Also: entities only an older guide named (the coordinator's addition)
- `GET /api/markx/entities/{id}` answers `current: false` and `older` (the posts an earlier guide named it in: id,
  title, source, guide, the span, and `now`, what the post's current reading names as its subjects) when no current
  reading names it. The page says "Not named in any post's current reading. An earlier guide (ent-v3) named it in N
  posts:" with those posts and what each names now.
- `entity_views.named_now`: such an entity is in no queue item, no version list and no `published` edge's other end
  (a publisher named by a current `by` counts as named); the list already counted from `mx_mentions_now`; Discover's
  rows read the current set only.

## Tests
- Backend `tests/test_entity_originals.py` (41): the rules (A's three rules and their order, merges read the
  target, `is_home` never, a document's front page is its work and a model's never, the not-a-release shapes, the
  maker's half-the-title rule; B's trigger: 2 voices, 1 voice News lead, `source` / `recommended` excluded, after
  0123's, recorded once, a paper page collectable; C's match (title key + author), its parse, off by default; D1's
  rows (hidden, gone once collected), D2's 3+ threshold with paper hosts excluded; E1's switch and the day's
  allowance, E2 one at a time 2 s apart and never a product-named front page; F1 curated or not, F2 read as the
  source's post, F3 kept citations; the orphan page and its absence from queue and edges).
  Updated: `test_markx_api.MX_TABLES`, `test_markx_storage` (the table count).
- Frontend: `entityOriginal.test.tsx` (4: Original first, not collected yet, older guide, the rabbit hole's one tap),
  `discoverPages.test.tsx` (+1), `schedulerDialog.test.tsx` (+1). `npm run build`, `npx vitest run` (all pass) and
  the design docs (`pages/sources.md`, `pages/shell.md`) claim the new UI; no new route.
- The whole backend suite: see the run noted in the branch's report.

## The real checks (4; private rows in `plan/research/0138-notes.md` and /tmp, never committed)
1. **The owner's case** (GET of the post and its Mark X panel): the post's 8 links through A: the arXiv abstract page
   is the original (rule `identifier`: the post's one document, one paper linked), its repository and demo kept as
   `code` and `demo`. Under B (2 voices, subject) it is collected as the entity's Original.
2. **A on the server's export** (scratch copy of `insight_server_1105_mxreal`, identity linked there first: 18,556
   mentions, 8,820 entities in 35 s; the address stage 6.2 s for 3,586 posts): of 180 specific entities that 2+
   voices made a subject, **43 have an address (239 per 1,000)**, 36 an original. First sample of 20: **13 right** —
   5 of the 7 wrong were the maker rule (a docs page, a research post naming the product in passing, a browser add-on,
   a comparison page) and 1 a third party's raw docs file. The class fixes (`not_a_release`, the maker's
   half-the-title rule) → second sample of 20: **18 right** (wrong: a reseller's page titled by the model's name, a
   product account's tweet). B on that week: 11 originals planned (1 followed, 2 no article). E2: the 6 work
   addresses are all work sites (a forecast scenario and its sequel, a report, an essay, two documents); no product
   front page among them.
3. **F1 on the owner's long-read** (GET; 20,134 characters, `commentary`, opened): curated; of its 27 links **24 would
   be collected** (18 article pages incl. a paper and a repository, 6 pages of followed sources read as their posts),
   3 not: two product front pages (right) and one article on the post's own multi-author site (open point 3).
   Before the one-segment fix, 7 news slugs were wrongly taken for profiles.
4. **F2 on the export**: 182 missed pages wanted at first — half one meetups list's event pages and old archive
   essays linked by roundups; with Mark IX's roundup rule and no tweets, **18 in 30 days**, all
   real pages of followed sources (a few blogs and newsrooms, a forum, an essayist).
- Not measured here: the credit's wait for B (needs the schedule's replay on the server: `entity_wait_hours` in the
  run's summary); E1's reads (751 unstored Classics on the server: about 8 days at 100 a day).

## Open points
1. **The credit's cap (B5)** rises to 6 automatically after 72 hours of waiting; measure `entity_wait_hours` in the
   first week's logs and lower it back if the wait is short.
2. **Go down the rabbit hole** follows nothing by itself: it collects the works and opens Add source on the first
   unfollowed site; the rest of the sites stay one tap each. A server-side follow queue (feed finder per site) was not
   built.
3. **F1's own-site rule** drops a cited article on the long-read's own site even when the site is a platform of many
   authors (1 of 27 in the case); `SourceFacts.shared_sites` could tell such sites.
4. **"Its source is one you read most of"** (F1's third trigger) is not built: opened or kept only.
5. A title match on the thing's name can still take a third party's page (a reseller) or a product account's tweet for
   a release page (2 of 20).
6. E1/E2/F use one allowance (100 a day): the backlog of Classics comes last, after works, references and missed
   pages.
