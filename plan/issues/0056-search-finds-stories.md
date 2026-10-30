# 0056 — Search finds stories: version names, folded results, News and Classics

Status: **built, not deployed** (2026-10-31; migration 0042) for v9.8 (owner, 2026-10-31: "can I search for stories? … I searched kimi 3.1 … please add that search as well. so we should be able to search in news and in classics as well").

## The case (measured on the lab, the server's data)
- **"kimi 3.1" doesn't find Kimi K3.1 Pro.** Search reads text with Postgres' `russian` configuration. It indexes "K3.1" as one word, `k3.1`, so the query's `3.1` never matches it. "kimi k3.1" would.
  - **The class:** names that join letters and a version (K3.1, GPT-6.1, Qwen3.8, M5, Gemini-4). That is most model, chip and product names your sources write about.
- **Results are posts, not stories.** A story covered by 8 posts shows as up to 8 results, with no "covered by".
- **News and Classics have no search.**

## Decided
- **Version names match by their parts.** A word that joins letters and a version is also indexed as its parts, `k3.1` → `k3.1`, `k`, `3.1`; `qwen3.8` → `qwen`, `3.8`. A query is read the same way, so "kimi 3.1", "kimi k3.1" and "K3.1" all find it.
  - Done in the search vector function and the query: one rule for both, no list of names.
  - The stored vectors are refilled by the existing background fill (0040's), not in the migration.
  - **Measure precision on the lab before adopting:** run 20 real queries before and after (model names, people, topics, Russian words), record what changed, and make sure nothing that matched stops matching.
- **Results fold into stories,** as the Main feed does: a story shows once, at its best-matching post, with its "covered by" line.
- **Two more scopes in search:** "News" (stories whose posts match, any date) and "Classics" (classics whose title or address matches). Beside the existing scopes; no new page.
- **Out of scope:** meaning-based search (Mark X), and search inside comments.

## Done when
- **Backend tests:** version splitting on the index and query sides; folding; the two scopes; paging.
- **Lab cases:** `search-kimi-31` passes (`plan/research/lab/cases.json`); the before/after table of 20 queries is recorded here.
- **Frontend:** tests and screens for folded results and the new scopes.
- **Checks:** bundle within budget (lazy-load if needed).

## Built
- **One rule, in SQL, for the index and the query** (migration `0042_search_version_names.sql`, no list of names):
  - `search_version_parts(lexeme)`: a version word is a word of letters, digits, dots and hyphens with a letter right before a digit (`k3.1`, `qwen3.8-max`, `gpt6`, `h100`, `deepseek-v4`), or a signed number (`-6.1`, the parser's reading of "GPT-6.1" and "Gemini-4"). Its parts are its runs of letters and numbers (a number keeps its dots), letters stemmed like any word: `k3.1` → `k`, `3.1`; `claude3` → `claud`, `3`; `-6.1` → `6.1`.
  - Not split: hashes and ids (letters and digits alternating 4+ times in one hyphenated piece: `26b5c67b`, `a3f9c2e7`), words over 64 characters, anything with `/ _ : @` (addresses, paths). A stop-word part (`a`, `s`) is left out but keeps its place. A word left with fewer than two parts is not split (`a100` would be just `100`).
  - **Index** (`search_vector_with_parts`, called by `post_search_vector`): the word stays, and its parts are added in a row ending at its position (`'kimi':1 'k':1 'k3.1':2 '3.1':2`). A word near the start begins its row at 1. Past position 16,383, where a tsvector puts every later word of a long text, the parts stay at 16,383: one before it is another word's place, and "K3.1" matched 15 long AINews digests that way before this rule.
  - **Query** (`search_query`, used everywhere `websearch_to_tsquery` was): each version word W becomes `(W | part <-> part …)`: "K3.1" also finds "K 3.1", "qwen3.8" finds "Qwen3.8-Max", and "GPT-6.1" finds GPT-6.1, GPT 6.1 and GPT6.1.
    - Inside a phrase (quoted, or a hyphenated word websearch reads as one), a multi-part W stays as written. Postgres gives an OR inside a phrase the width of its longer side, so `"kimi k3.1 pro"` lost 21 of its 22 matches until this rule.
    - A one-part W (`-6.1` → `('-6.1' | '6.1')`) is safe inside a phrase.
    - W itself always stays in, so a vector not refilled yet matches what it did.
- **The refill** (no rewrite in the migration):
  - `posts.search_version` (a new nullable column, so nothing is rewritten) says which rule made a vector: NULL is 0033's, `search_vector_version()` (2) is the current one. The trigger and a source's rename write it with each vector.
  - The background fill (`ReaderService.fill_search_vectors`, `SearchRepository.fill_missing_vectors`, the thread in `main.py`'s lifespan) refills every post whose vector is missing **or** older, 500 a transaction, `FOR UPDATE SKIP LOCKED`, logging "Search: indexed N posts stored before search or indexed by an older rule".
  - **A future change to `post_search_vector` bumps `search_vector_version()` in its migration, and the same fill refills everything.**
  - Lab copy: 41,609 posts refilled in 83–153 s (three runs). The vectors stayed at 125 MB (no measurable growth).
- **Folding** (`repo_search.py`):
  - Unless the search is of one source, Later or Kept (as the feed: those show every post), a story (0050) shows once. It shows at its best-matching post among the results: the highest `ts_rank` among its posts that match, in the scope and the dates; on a tie, the feed's lead rule (a report before a share, then the first posted).
  - The row carries `story` exactly as the Main feed's lead does, so the row shows `▸ covered by N · …` and opens the others. Newest first, the story sits at that post's date; keyset paging is unchanged (the fold is a per-row predicate).
- **News** (`filter=news`): the News stories (0051's tables, **any date**) with a post in the scope (none: every story; `all`: the Main feed; a track; a source), whichever of their posts matched. Each story shows once at its best-matching post, with `story` (its News posts, the first report's source first) and `news` {part, first_at, reports, shares, mentions, score}, as GET /api/news shapes them.
- **Classics** (`filter=classics`): the classics you did not hide whose title (the stored post's, else the link words) or address matches. The address is read as words, except a dot before a digit, so a version survives: `huggingface.co/Qwen/Qwen3.6-35B-A3B` is found by "qwen 3.6".
  - The answer is `{classics, next_cursor}`, shaped as GET /api/classics, paged by offset in both orders.
  - Newest is the most recently cited; `days` bounds the last citation; a scope keeps the classics a source of it cited.
- **API:** `GET /api/search` takes `filter=all|later|starred|news|classics` (one at a time, as the chips are); nothing else changed.
- **UI** (`SearchPage.tsx`, lazy):
  - The chips are `Later · Kept · News · Classics` (one at a time), then the dates.
  - A folded row is the feed's row with its covered-by line (no new component).
  - News rows are the same rows; empty: "No News stories match “xyz”".
  - Classics renders the Classics view's own list (`ClassicsList` with a `search` prop: title reads, Later, Hide; up to 100), lazy; empty: "No classics match “xyz”" with "Search everything".
  - The intro line says "kimi 3.1" finds Kimi K3.1. Design docs: `pages/reader.md` (the search page, the story rule) and decision 030 (amended, not a new number).
- **Tests:**
  - Backend `test_search.py`, 39 tests (16 new):
    - version names on both sides: `kimi 3.1` / `kimi k3.1` / `K3.1` / `"kimi 3.1"` / `"k3.1 pro"` / `"kimi k3.1 pro"`; GPT-6.1 hyphenated, spaced and joined, each way; a suffix and a stop-word part; hashes not split;
    - the SQL rule's exact parts, queries and vector;
    - an older vector refilled by the fill and matching what it did meanwhile;
    - folding at the best match, a tie (report, then first posted), only matching posts in the scope and dates competing, one source / Later / Kept unfolded, folded paging without overlap in both orders;
    - News of any date with scope and days; Classics by title, address, stored post, scope, days, hidden; a classic's address keeping its version; Classics paging; what folds.
  - **Full suite: 998 tests, OK.**
  - Frontend: `SearchPage.test.tsx` (4 new: the folded row and its covered-by list, the News and Classics chips, Classics results, Classics empty) and `lib/search.test.ts` (News and Classics in the URL). Typecheck, lint, **182 node + 641 vitest tests**, build OK.
- **Bundle:** the reader's initial JS is **479,704 bytes** (+19 on 479,685; limit 479,815): only `parseSearch` knowing the two new filters. The search page chunk is 5,142 bytes and `ClassicsList` 4,624, both lazy.
- **Screens** (the dev server against my own API on the lab copy, light and dark, 1400 and 390; not committed): `~/.cache/insight-checks/0056-shots/`.
  - `0056-folded-best-*`: "kimi 3.1", best match, the Kimi story opened.
  - `0056-folded-newest-*`.
  - `0056-news-*`.
  - `0056-classics-*`: "language models".
  - `0056-classics-version-*`: "qwen 3.6" finds the Hugging Face address.
  - `0056-classics-empty-*`.

### The lab case
`search-kimi-31` **passes** (`cases.json` updated). On the lab copy "kimi 3.1" now finds Simon Willison's "Introducing Kimi K3.1 Pro". The post is folded into its 8-post story (7 voices), which shows at r/LocalLLaMA's "Kimi K3.1 Pro Tech Blog", its best match, with Simon Willison in its covered-by line: row 3 under best match, row 24 newest first. That is 214 rows for 220 matching posts.

### 20 real queries, before and after (lab copy of the server, 2026-10-31)
`insight_lab` copied by pg_dump into a `_test` database.
- **Before:** the stored 0033 vectors and `websearch_to_tsquery`.
- **After:** 0042 applied, the 41,609 vectors refilled by the background fill, and `search_query`.
- **Nothing that matched before stopped matching (lost: 0 in every row).**

To judge the gains, each version query has a pattern for the thing it names (for example `kimi[ -]?k?[ -]?3\.1` and `qwen[ -]?3\.8`), run over title and text:
- "gained naming it": how many of the new matches name it;
- recall: of every post naming it, how many match, before and after.

Rows are the results after folding (every post, newest first). Times are the median of 5 runs through `SearchRepository.search`, a page of 20.

| # | Query | Read as | Before | After | Lost | Gained (naming it) | Recall before → after | Rows folded | Newest / best ms |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `kimi 3.1` | `'kimi' & '3.1'` | 166 | 220 | 0 | 54 (33) | 13% → **100%** | 214 | 35 / 19 |
| 2 | `kimi k3.1` | `'kimi' & ('k3.1' \| 'k' <-> '3.1')` | 35 | 36 | 0 | 1 (1) | 94% → 97% | 31 | 28 / 22 |
| 3 | `K3.1` | `'k3.1' \| 'k' <-> '3.1'` | 36 | 37 | 0 | 1 (1) | 95% → 97% | 31 | 27 / 22 |
| 4 | `qwen 3.8` | `'qwen' & '3.8'` | 245 | 507 | 0 | 262 (253) | 43% → **94%** | 488 | 36 / 20 |
| 5 | `qwen3.8` | `'qwen3.8' \| 'qwen' <-> '3.8'` | 132 | 466 | 0 | 334 (332) | 27% → **94%** | 447 | 38 / 22 |
| 6 | `gpt 6.1` | `'gpt' & '6.1'` | 69 | 160 | 0 | 91 (89) | 28% → **99%** | 157 | 40 / 14 |
| 7 | `GPT-6.1` | `'gpt' <-> ('-6.1' \| '6.1')` | 107 | 125 | 0 | 18 (17) | 86% → 99% | 122 | 41 / 19 |
| 8 | `gemini 4` | `'gemini' & '4'` | 942 | 1,103 | 0 | 161 (1) | 97% → 98% | 1,086 | 41 / 32 |
| 9 | `opus 5.5` | `'opus' & '5.5'` | 455 | 626 | 0 | 171 (3) | 99% → 100% | 612 | 52 / 22 |
| 10 | `deepseek v4` | `'deepseek' & ('v4' \| 'v' <-> '4')` | 671 | 680 | 0 | 9 (4) | 86% → 87% | 667 | 53 / 35 |
| 11 | `rtx 5090` | `'rtx' & '5090'` | 239 | 244 | 0 | 5 (4) | 96% → 98% | 243 | 23 / 20 |
| 12 | `h100` | `'h100' \| 'h' <-> '100'` | 310 | 351 | 0 | 41 (39) | 84% → 95% | 341 | 79 / 51 |
| 13 | `llama 3.1` | `'llama' & '3.1'` | 222 | 302 | 0 | 80 (73) | 64% → **97%** | 300 | 64 / 40 |
| 14 | `"claude opus"` | `'claud' <-> 'opus'` | 863 | 864 | 0 | 1 (0) | 97% → 97% | 851 | 79 / 38 |
| 15 | `"kimi k3.1 pro"` | `'kimi' <-> 'k3.1' <-> 'pro'` | 22 | 22 | 0 | 0 | | 18 | 17 / 17 |
| 16 | `simon willison` | `'simon' & 'willison'` | 697 | 697 | 0 | 0 | | 692 | 25 / 18 |
| 17 | `karpathy` | `'karpathi'` | 779 | 779 | 0 | 0 | | 769 | 46 / 18 |
| 18 | `dario amodei` | `'dario' & 'amodei'` | 255 | 255 | 0 | 0 | | 252 | 74 / 29 |
| 19 | `tailscale` | `'tailscal'` | 62 | 62 | 0 | 0 | | 62 | 56 / 29 |
| 20 | `нейросети` | `'нейросет'` | 665 | 665 | 0 | 0 | | 652 | 28 / 17 |
| 21 | `серверы` | `'сервер'` | 426 | 426 | 0 | 0 | | 397 | 22 / 20 |
| 22 | `smart glasses -meta` | `'smart' & 'glass' & !'meta'` | 65 | 66 | 0 | 1 (0) | 31% → 31% | 66 | 65 / 42 |

What it says:
- **The names are found.** A model named with a version was found in 13–43% of the posts that name it when the query was spelled differently from the text. Now it is 94–100%: rows 1, 4, 5, 6 and 13.
- **People, topics and Russian words are unchanged** (rows 15–21: the same posts). Folding takes 0–29 rows off each.
- **The cost is in "word number" queries,** which were already loose: a plain query is every word anywhere in the post.
  - "opus 5.5" before matched 455 posts, of which 286 name Opus 5.5 (63%). Now it also matches posts that name Opus and, elsewhere, GPT-5.5 (163 of its 171 gains come from a `-5.5`): 289 of 626 (46%).
  - "gemini 4" (12% before, 11% after) gains posts with Gemini and DeepSeek-V4 or GPT-4.
  - "kimi 3.1" gains 21 posts with Kimi and Gemini-3.1 or Llama-3.1, beside the 33 that name it.
  - Best match orders the posts that name the thing first (the Kimi story is row 3).
  - Adopted: the recall gains are large and nothing was lost, but this is the trade (see Left open).
- **Speed:** every query is 13–79 ms with folding, newest or best, the Main feed or News (News 10–54 ms). Folding costs a lookup per matching row that is in a story.
- The two other gains:
  - row 14, "Claude (opus5.5)": right, though the pattern misses it;
  - row 22, a digest with "smart4" and, elsewhere, "glasses": noise of the same kind.

## Left open
- **"word number" precision** (above): an unquoted "opus 5.5" matches Opus anywhere and a 5.5 anywhere, now including GPT-5.5. A fix would rank or require nearness: read "opus 5.5" as a phrase first, or order by cover density (`ts_rank_cd`). That changes what matches or how it is ordered, so it is not done here; measured, not decided.
- **The matching line doesn't mark a version's number:** "kimi 3.1" marks "Kimi" but not the "3.1" inside "K3.1" (ts_headline reads the text afresh, without the parts). A row whose only hit is a part shows its excerpt.
- **A version split by the parser itself is not rejoined:** "kimi-k3.1-pro" in a file name reads as `kimi-k3`, `1`, `pro`, so "kimi 3.1" doesn't find that spelling (Simon's post is found by its own "K3.1").
- **`-word` excludes parts too:** `-4` now also leaves out posts with "Gemini-4" or "v4". That is arguably right, but it is a post that matched before and doesn't now. None of the 20 queries had one.
- **The quoted phrase "K 3.1"** (written with a space) does not find "K3.1": inside a phrase a multi-part word stays as written (Postgres' OR width). Unquoted it does.
- **Hashes and ids by rule:** a model name with 4+ letter–digit alternations in one piece (`8xa100m40`) is treated as an id and not split.
- **Classics are one page of up to 100** in the UI (the API pages by offset); there are 173 classics on the lab.
- **The phone's covered-by list** is 0050's: names and titles truncate hard at 390 px (`0056-folded-best-390-*`).
