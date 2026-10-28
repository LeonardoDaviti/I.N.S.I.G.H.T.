# 0040 — Search across every post

Status: **built, not deployed** (2026-10-28; migration 0033) for v9.4 (owner, 2026-10-28: "for 9.4 we move search into it").

## Why
On the server 41,000 of 41,128 posts are unread (0.3% read). Nobody scrolls that; you find things in it by asking. Search is the way into everything INSIGHT has already stored ("that Tailscale post on HN last month", "what did Simon write about MCP", "the Russian Telegram post about the outage").

## Decided
- **Where:**
  - a search field in the reader's toolbar, scoped to what is on screen: the Main feed, a track or a source;
  - ⌘K / Ctrl+K "Search posts…", which searches everything.
  - One results view in the reader. Opening a result opens the post as it opens anywhere else, so read state, Later and Keep work as usual.
- **What it matches:** the title, the full text and the source name. The title counts most.
  - Word forms count, in English and Russian ("watching" finds "watch", "серверы" finds "сервер").
  - "Quoted phrases" and `-word` work. Hits in another language are still found as plain words.
- **Results:**
  - Newest first by default, with "Best match" as the other order.
  - Each result shows the title, the source, the date and **the matching line** with the words marked.
  - Read or unread doesn't matter, because search covers everything.
- **Narrowing:** track, source, Later, Kept, and a date range ("last week / month / year / any"), as chips beside the field. The scope you searched from starts as the first chip.
- **Engine:** Postgres full-text search with a GIN index, in a migration. No new service and no new container.
  - Backfill the index for existing posts inside the migration, or in batches if that would lock the table for too long on 41k+ posts.
- **Speed, measured and recorded here:**
  - under 200 ms for a typical query on a database the size of the server's (fill a `_test` DB with ~50k posts);
  - also report the index size.
- **Empty states:** "No posts match 'xyz'" plus the active chips, with a one-click "Search everything" when a chip narrows the search.

## Not now
Saved searches (later, in a minor release), search inside one post, fuzzy or typo matching, and semantic or AI search (Mark X).

## Done when
- The backend route has tests: word forms in English and Russian, phrases, `-word`, each filter, ordering, the snippet, and paging.
- The frontend has tests for the toolbar field, ⌘K, the chips, the result row with the marked line, and the empty state.
- The design docs say where search lives. If it adds a rule, it gets a numbered decision in `frontend/src/design/docs/decisions.md`.
- Frontend checks pass (typecheck, test, lint and build, including the bundle budget). Any growth in the bundle is stated.
- The timing and index size are written into this issue.

## Built
- **Index:** migration 0033 adds `posts.search_vector`: the title (weight A), the source's
  name (B; an address reads as its words, `simonwillison.net` as "simonwillison net") and the
  text (D, its first 200,000 characters, since a tsvector must stay under 1 MB), with a GIN
  index `posts_search_idx`. One configuration, `russian`: Postgres' own `russian` maps ASCII
  words to the English stemmer and Cyrillic words to the Russian one, so "watching" is
  `watch`, "серверы" is `сервер`, and a word in any other language ("éléphants") is kept as
  written. A trigger fills the vector whenever a post's title, text or source is written; a
  source renamed rewrites its posts' vectors (a trigger on `sources`, only when the shown name
  changes).
- **Backfill in batches, not in the migration:** in the migration it took 2 min 20 s on 50k
  posts, longer than the backend's health check waits (5 × 30 s) before compose gives up on the
  frontend. So 0033 itself runs in 0.2 s and the backend, once started, fills the posts stored
  before it in the background, 500 a transaction (`ReaderService.fill_search_vectors`, a
  thread from the app's lifespan; `FOR UPDATE SKIP LOCKED`), logging "Search: indexed N posts".
  50k posts took 4 min; until then search misses the older posts; new posts are searchable at once.
- **Route:** `GET /api/search?q=` (`backend/insight_core/db/repo_search.py`), read with
  `websearch_to_tsquery`: words, `"quoted phrases"`, `-word`, `or`. `scope` none is every post,
  `all` the Main feed (as in the reader), `folder:` and `source:`; `filter=later|starred`;
  `days=N`. Newest first, keyset-paged on the feed's own sort key and cursor; `order=best` is
  `ts_rank` (normalised by length) over the newest 5,000 matches, paged by offset. Items are the
  feed's rows plus `snippet`, the matching line from `ts_headline` (one fragment of 12 to 28
  words from the first 20,000 characters) as `[{text, mark}]`; its words are any of the query's
  (never a `-word`), so the line still shows when the other words matched the title or the
  source; null when the text holds none of them (the row shows its excerpt).
- **Two plan traps, measured and fixed:** the query is never a prepared statement
  (`prepare=False`): after five runs psycopg prepares it, the generic plan cannot see the words
  and walks the feed's order index for a rare one (30 ms became 300 ms); and `enable_seqscan` is
  off for the search's transaction: a word in a third of the posts made the planner read the
  whole table, unpacking every vector (400 ms), where the GIN bitmap reads none.
- **UI:** `/search` is the reader's one results view (`pages/SearchPage.tsx`, its own lazy
  chunk): the reader's rail, where a link narrows the search to that scope, and a toolbar
  titled Search with the field and the chips beside it: the scope searched from (pressed, with
  ×; pressing it searches every post), Later, Kept (one at a time), Last week / month / year;
  then `Order newest / best match`. Results are the feed's rows (`PostList`, split out of
  `FeedList`), 20 a page, dated, no day headers, the matching line in place of the excerpt with
  its words in weight 600; read, Later, Keep and j/k/o/m/l/s work as in the feed; a result opens
  as a post on its own. The reader's toolbar has a search field ("Search <scope>"), which
  carries the scope and, under Show later or kept, that list. ⌘K always ends with
  "Search posts…" ("Search posts for “…”" once words are typed, every post). Empty: "No posts
  match “xyz”", the chips (`In Main feed · Last week`) and "Search everything".
- **Design docs:** `pages/reader.md` claims `/search` and its states `search` and
  `search-empty` (studio scenarios on the fixture site, which now answers `/api/search`);
  `pages/shell.md` and `system/information-architecture.md` say what ⌘K does; decision 030.
- **Bundle:** the reader's initial JS grew 4,062 bytes (468,143 → 472,205, +0.87%, within the
  1% budget): the toolbar's field, ⌘K's entry, the list split for search, and the chunks Vite
  now shares between the reader and the search page; the page itself is lazy.
- Tests: `backend/insight_core/tests/test_search.py` (word forms in English and Russian, another
  language, phrases, -word, the source's name and its rename, read or unread, stop words, each
  narrowing, both orders, the snippet, a title-only hit, paging in both orders, the batched
  backfill, 400s); `frontend/src/pages/SearchPage.test.tsx` (the toolbar field, the chips, the
  rail, the result row with its marked line, the empty states), `lib/search.test.ts`, and ⌘K in
  `components/layout/layout.test.tsx`.

## Measured (2026-10-28, a `_test` database of 50,000 posts)
The posts: 200 sources, 65% English and 35% Russian text drawn from real sentences (the
English and Russian messages of the system's translation catalogues), lengths as a reader's
feeds give them (35% 150–1,500 characters, 45% 2–12k, 15% 12–40k, 5% 40–150k; 12,134 on
average, 579 MB of text), with specific words planted at realistic rates. Postgres 15 in the
project's container on this laptop; each query run 7 times through `SearchRepository.search`
(page of 20, with the snippets), median.

| Query | Matches | Newest first | Best match |
|---|---|---|---|
| `kubectl` | 32 | 35 ms | 16 ms |
| `датацентры` | 41 | 29 ms | 12 ms |
| `нейросети` | 86 | 30 ms | 6 ms |
| `"postgres planner"` | 154 | 31 ms | 7 ms |
| `simon mcp` (source name + text) | 989 | 49 ms | 54 ms |
| `server -error` | 1,656 | 28 ms | 23 ms |
| `anthropic` | 1,760 | 26 ms | 19 ms |
| `wireguard` | 1,788 | 44 ms | 51 ms |
| `серверы` | 8,927 | 36 ms | 122 ms |
| `server` | 16,423 | 44 ms | 74 ms |
| `file` (in 68% of posts) | 34,206 | 39 ms | 107 ms |
| `file`, Main feed / one source / Later / last 30 days | | 33 / 31 / 34 / 38 ms | 120 / 28 / 17 / 35 ms |
| `"open file"` (a phrase of two common words) | 6,122 | 56 ms | 274 ms |
| `file` in a track holding half the posts | | 37 ms | 295 ms |

- A typical query is 25–70 ms newest first and under 60 ms best match. The only ones over
  200 ms are best match on a phrase of two very common words, or on a common word inside a
  track that holds half of everything: ranking then reads every matching vector.
- **Index size:** the GIN index is 97 MB; the vectors themselves 487 MB (stored in TOAST, next to
  386 MB of stored text), so `posts` went from 451 MB to about 1.1 GB.
- **Backfill:** 0.2 s of migration, then 4 min of background filling for the 50k posts (the same
  work in one transaction: 2 min 18 s plus 24 s for the index).
