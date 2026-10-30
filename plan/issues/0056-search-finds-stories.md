# 0056 — Search finds stories: version names, folded results, News and Classics

Status: **spec** (2026-10-31) for v9.8 (owner, 2026-10-31: "can I search for stories? … I searched kimi 3.1 … please add that search as well. so we should be able to search in news and in classics as well").

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
