# 0139 — Search that finds: History searched, Mark X's English layer searched, entities first, best match for phrases

Status: **spec** (2026-11-09). Mark IX search (0040, 0042, 0056) with a Mark X layer (Stealth: read only while Mark X
is on). Meaning search (vectors) and asking Mark X are **not** here: they are being discussed with the owner.

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; 0040, 0042, 0052 (History), 0056 (search and stories).

**The owner (2026-11-09):** "I can't search in my History, why? I remember I found from post 3D library which makes
agent to spend 3x less tokens on 3D objects, and now I can't find it… I found it going through history by myself."

**Constraints:** no real names in committed files (the case's rows: `plan/research/0139-notes.md`); fix the class;
keep everything; never touch the live DB; nothing merges unless `scripts/realdata-check.sh` passes; 3–5 real checks.

## Why (measured on the server by GET, 2026-11-09)
The post: a Russian Telegram post (7 Nov) about a Python 3D-modelling library for language models, "2–6× fewer
tokens". It is the 44th row of the owner's History. Four gaps hid it:
1. **History's search box searches every post.** `ReaderPage.tsx` maps the `history` filter to `all`;
   `SEARCH_FILTERS` has no `history`.
2. **Words in one language.** `search_query` is `websearch_to_tsquery('russian', q)` over the post's own text: the
   English "3D library tokens" can't meet "библиотеку", "токенов". Its name ("sand3d", its maker) finds it at once.
3. **Newest first.** "3D library" listed certificate hex dumps and hardware reviews holding "3D" and "library".
4. **Mark X's English isn't searched.** Mark X already read the post: an English headline ("… released …, a Python
   3D-modeling library built for language models"), numbers ("2-6x fewer tokens"), entities (the library as
   `software`/`subject`, its maker as `org`/`actor`).

## What it does
### 1. History search
- `history` joins `SEARCH_FILTERS`: it searches the posts History lists (`HISTORY_SQL`, 0052), newest **opened**
  first (History's own order), keyset-paged on its sort key; stories don't fold (as Later and Kept).
- `ReaderPage` passes `history` through; `lib/search.ts` accepts it; the search page's filter chips show History.

### 2. Mark X's English layer in the index
- A side table **`mx_post_search (post_id PK, vector tsvector, version, updated_at)`** with a GIN index: from the
  post's **current** read answer (headline, main action/object/actors, numbers) and its current entity set
  (`mx_mentions_now`: names, aliases of their entities, makers), as `to_tsvector('english', …)` — weight A for the
  headline and entity names, B for the rest.
- Written when a read or entities answer is stored (the worker's POST), and by a resumable background fill (like
  0033's) for posts that have answers and no row or an older `version`.
- **Search reads it only while Mark X is on:** a post matches when its own vector **or** its Mark X vector matches
  the query (the latter by `websearch_to_tsquery('english', q)`); rank is the max of the two. The snippet stays the
  post's own text when it matches, else the Mark X headline marked "Mark X" (so the owner sees why it matched).
- Mark IX's `posts.search_vector` and its rule are unchanged.

### 3. Entities first
- A search (first page, not one source) whose words match an entity's name or alias (identity's name key, prefix
  for 3+ letters) shows up to 3 **entity cards** above the posts: name, type, maker, posts and voices, linking to
  `/markx/entities/:id`. Only while Mark X is on; redirected entities show their target.
- `GET /api/search` returns `entities: [...]` (empty when Mark X is off or no match).

### 4. Best match for phrases
- With no explicit `order`, a query of **2+ words** orders by `best`; one word stays `newest`. The order switch on
  the search page still overrides it, and the URL keeps the choice.

## Measure (3–5 real checks, after deploy or on the lab copy)
1. The owner's case: "3D library tokens" in History and in everything finds the post on the first page.
2. 3 more English queries for non-English posts the owner opened (private rows): found on page 1 or not.
3. The fill's time over every post with answers; search latency p50/p95 before and after on 10 queries.

## Done when
- Tests: History filter (only opened posts, its order, paging); the Mark X layer matched in English for a Russian
  post, off when Mark X is off; the snippet's "Mark X" fallback; entity cards (alias, redirect, off); 2+ words →
  best, explicit order wins; the fill resumable and versioned.
- A migration; `realdata-check.sh` passes; frontend builds and vitest passes; design docs claim the new UI states.
