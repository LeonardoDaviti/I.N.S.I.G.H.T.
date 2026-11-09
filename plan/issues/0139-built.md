# 0139 Built: search that finds

Built 2026-11-09 on its own branch, test-first. Migration **0090** (`mx_post_search`, prefix indexes on the entities'
and aliases' keys). Mark X tables only; `posts.search_vector` and its rule are unchanged.

## What was built

| Part | What changed |
|---|---|
| 1. History search | `history` joins `SEARCH_FILTERS`. It searches the posts History lists (`HISTORY_CTE`: opened or a reading session), last open first, keyset-paged on `(opened_at, id)`; each row's `sort_at` and `opened_at` are its last open; `days` bounds the open; it never folds stories; best match ranks within it. `ReaderPage` passes `history` through (`lib/search.ts` accepts it), and the search page has a `History` chip between Kept and News. |
| 2. Mark X's English layer | `mx_post_search (post_id PK, vector, headline, version, updated_at)` + GIN. `markx/search.py`: `to_tsvector('english', …)` of the current reading (the newest read guide's, as the post page's panel reads it): headline A; action, object, actors, numbers B; and the current entity set (`mx_mentions_now`): each name and its entity's name A; makers and the entity's aliases B. Written by `tasks.record` for read, read3, entities and cite answers (in a savepoint: an answer never fails for its row), and by a resumable fill (`fill_batch`/`pending`, run after Mark IX's search refill at the API's start, only while Mark X is on): a post with an answer and no row, a row of an older `VERSION`, or a row older than its newest reading or entity set. A `headline` column was added to the spec's table, so the line needs no second read. |
| | Search reads it only while Mark X is on (`INSIGHT_MARKX`): each layer is a branch of its own, limited like the matches (the posts' own vector, as before; the posts whose `mx_post_search` row matches), unioned and limited again: an OR across two tables reads neither index, and a union of both whole match sets sorted every match of a common word (a common Russian word went 34 → 162 ms that way; 47 ms with the branches). The layer is read as `websearch_to_tsquery('english', q)`; best match's rank is the higher of the two (and so is a story's best-matching post's). A row only the layer matched has Mark X's headline as its line, its words marked (`snippet_from: "markx"`, shown after a quiet `Mark X ·`); a post its own words match keeps its own line. Off, the SQL is the one before. |
| 3. Entities first | `GET /api/search` answers `entities` (always present; `[]` off, on a later page, in one source, or with no match): up to 3 entities whose identity key (`names.key`) equals the query or a run of its words (of 2+ characters), or starts with the query (3+ characters), through `mx_entity_aliases` too; each read through the current redirects to its target (merged entities show it), never a `not_entity`; ordered whole query, then a run, then a prefix, then posts. Each card: name, type, maker (the entity's, else its parent's for a family/thing), posts and voices (distinct posts and sources in the current entity sets linked to it or to an entity merged into it). The search page shows them above the results as hairline rows linking `/markx/entities/:id`. |
| 4. Best match for phrases | `SearchQuery.parse` with no `order`: 2+ words (not `or`, not a `-word`) order by `best`, one by `newest`; the route's `order` default is none. The frontend has the same rule (`defaultOrder`/`searchOrder`); the order switch shows the effective order, and a chosen order goes in the URL (`order=newest` now too). |

Design docs: `pages/reader.md` claims `search-history` and `search-markx` (fixture scenarios in `design/fixtures/scenarios.ts`;
the fixture search filters History).

## Tests
- `backend/insight_core/tests/test_search_0139.py` (new): default order (2+ words best, explicit wins, `or`/`-word`), History
  (only opened posts, last open first, `opened_at = sort_at`, keyset paging, days bound the open, no folding in either
  order), the Mark X layer through the worker's POST (row written with its version; "3D library tokens" finds a
  Russian post only by its English reading, snippet from Mark X and marked; off, not read; own words keep their own
  line; an entities answer's maker matched), the fill (missing, older version, one batch then the rest, older than its
  answers), the entity cards (name, alias, run of words, prefix, 2-letter prefix refused, through a redirect, never a
  not-entity, not in one source, first page only, off).
- `test_search.py`: its helper asks `order=newest` explicitly (its marker made every query 2 words).
- Frontend: `lib/search.test.ts` (History in the URL, the order rule), `pages/SearchPage.test.tsx` (History chip from
  History's field, 2+ words best and a chosen order kept, entity cards and the Mark X line, none when off),
  `DesignStudio.test.tsx` (the reader's states).

Backend suite: 2,421 tests, OK after `test_markx_storage` learned the 30th mx_* table (its two counts were the only
failures). Frontend: `npm run build` (bundle check +0.11% feed route), `vitest` 71 files / 843 tests, `node --test` 244.

## Measures (scratch copies, dropped after)
Copies: `insight_lab` (30 Oct, no Mark X rows) and `insight_server_1105_mxreal` (5 Nov, 5,344 readings, 5,031 entity
sets, no identity run so no entities), each migrated to 0090. Base: the v10.9.1 image (main's search code).

**The fill:** 5,542 posts with an answer written in **0.6 s** (2,948 with a headline; a reading whose `main` is null
and a post with only entities get a row too, so the fill never asks again); a second pass 0 in 0.04 s. 3.8 MB with
its index.

**Latency**, 10 queries (English and Russian, 1–3 words) × 5 runs after a warm pass, through `ReaderService.search`;
another agent's check ran on the same Postgres at the time, so ±10 ms is noise. Head's multi-word queries order by
best match (the new default), base's by newest.

| copy | base | head, Mark X off | head, Mark X on |
|---|---|---|---|
| lab | p50 72 ms, p95 112 ms | p50 61 ms, p95 123 ms | p50 65 ms, p95 130 ms |
| 1105 + Mark X | p50 70 ms, p95 112 ms | p50 59 ms, p95 120 ms | p50 69 ms, p95 133 ms |

**Real checks** (rows in `plan/research/0139-notes.md`):
1. The owner's case (the post is newer than every local copy): its server Mark X answers (read by GET) and its own
   text, put through the new rule on Postgres: "3D library tokens" — own text no, Mark X layer **yes**, rank 0.191;
   "3D library", "3D tokens", "python 3d modeling" yes; the library's and its maker's names both layers. On the 1105 copy the same
   query's 102 own-text matches rank at most 0.012, so best match would put it first. **"3D library for agents" is
   still missed:** "agents" is only in the Russian title (a Russian word form) and not in Mark X's English reading, and
   "library" only in the English layer; a post matches one layer whole, never words from each.
2–4. Three (and one more) English queries for Russian posts the owner opened (1105 copy, Mark X on): silent-speech
   glasses, a GIF-generating model, space GPU cooling: **page 1, first** in everything and in History (best match;
   the third is 13th under newest). Off: none found. A fourth ("edit neural network weights"): 2nd in History, not on
   page 1 of everything (other posts hold those English words in their own text and rank higher).

realdata-check: run at merge (the owner's rule of 2026-11-09: one check per release on main). One started here was
stopped before its jobs finished and its copies were dropped.

## Open points
- **Words across layers:** a query whose words are split between the post's own text and Mark X's English (the owner's
  "3D library for agents") matches neither. Matching `own || layer` with one query would cost the indexes; meaning
  search (vectors) is the spec's next step.
- **Identity changes don't refresh rows:** a row is remade when its reading or entity set changes, or `VERSION` rises;
  an entity linked or merged later (its name and aliases in the B weight) waits for the next answer or a version bump.
  The cards themselves read identity live.
- **Ranks across layers:** the layer's text is short, so `ts_rank`'s length normalisation ranks its matches high next
  to long posts; fine for the cases above, not measured broadly.
- **Card counts** read the current entity sets' links and redirects, not the owner's pins (the entity page counts
  pins too), so a card's posts can differ from the page's by the pinned ones.
- The entity cards were tested on synthetic rows only: no local copy has identity's entities.
- The fill runs at the API's start only while Mark X is on; turning Mark X on later fills at the next start (rows of
  new answers are written as they arrive either way).

