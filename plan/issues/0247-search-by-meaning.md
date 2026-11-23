# 0247 — Search by meaning on top of words

Status: **built (Stealth v10.32), switch `search.meaning` on; needs INSIGHT_EMBEDDER_URL on the server.** Written 2026-11-20 and skipped; the owner brought it back 2026-11-21.
for development, because we don't need it for now"). Do not build until the owner brings it back.

## The miss that shows the class

Searching the server for "AMD Unsloth" (2026-11-19) did not find a post that was there: a repost of "We collaborated
with @AMD to bring local model inference to XDNA 2 NPUs …" (in the Local Setups track since 11-19). Search
(`repo_search.search`, Postgres full text plus Mark X's English layer `mx_post_search`) needs every word: the post says
"@AMD" and does not say "Unsloth" (its author is the Unsloth account), so the AND of words fails.

## What exists to build it from

- Every post has an embedding (`mx_embeddings`, 162,263 rows, BGE-M3 from the local embedder the worker runs).
- Entities have vectors (`mx_entity_vectors`) and search already shows entity cards (`mx_search.entity_cards`).

## The idea

- Hybrid: the word ranking as today, plus the nearest posts by embedding to the query's embedding, merged by
  reciprocal rank; a post found only by meaning is marked so.
- The query's embedding needs the embedder at search time (the worker's local embedder): either the API calls it, or
  search by meaning only works when it is up (state which).
- Also: an entity named in the query (AMD, Unsloth) widens the search to posts naming that entity, by identity, not text.

## Bar

Recall on a frozen set of known-item queries (the owner's real misses plus sampled ones) and precision of the first 10,
judged blind: point >= 97% / Wilson >= 90% for the first 10's precision; recall reported.

## Built (Stealth v10.32, 2026-11-21)

- **Where the query's vector comes from (design (a)):** the API asks the worker's embedder (the same `llama-server
  --embedding --pooling cls`, BGE-M3) at `INSIGHT_EMBEDDER_URL`, 2 s timeout, one query a search
  (`markx/search.query_vector`). No URL, the embedder down or slow, or the switch off: no vector, and search is the word
  search exactly as before. Nothing is embedded or kept in the API: the nearest posts are an exact scan of
  `mx_embeddings` in Postgres (the posts' HNSW index was dropped in 0149; ~190 ms on the busy copy, 159k vectors).
  Server deploy: run the device's llama-server on its tailnet address (not 127.0.0.1) and set INSIGHT_EMBEDDER_URL.
- **Nearest posts** (`markx/search.nearest_posts`): 30 nearest, cosine >= 0.55, and 200+ characters of text: a short
  text's vector is near every query (placeholder and one-line posts at 0.56-0.57 for an aviation query).
- **Hybrid ranking** (`db/repo_search.SearchRepository.search`, best order only): the nearest posts are one more branch
  of the matches (same scope, filter, dates, story rule); the word ranking (as before: rank, then newest) and the
  meaning ranking merge by reciprocal rank (k = 60), under the existing tiers (exact title, entity first, titled). With no
  meaning posts the order is the word order unchanged. A post only meaning found has `matched: "meaning"`,
  `snippet_from: "meaning"` and its first line; the reader marks it "By meaning ·" (FeedItem).
- **Switch:** entity_bands.json `search.meaning` (on), read by `markx/search.meaning_on`.

## Measure (frozen set, 2026-11-21, 11-19 server copy, read only)

32 known-item queries: real titles from the copy, each rephrased by meaning (mostly not the title's words), the
target the post (plan/research/0247-search-meaning/set.json; results beside it). Best order, first 10, Mark X on.

| | words (before) | hybrid (after) |
|---|---|---|
| recall@10 (the target in the first 10, or in a shown story) | 8/32 (25%) | 28/32 (88%, Wilson lower ~72%) |
| first-10 precision (Claude, on topic for the query) | 79/218 (36%) | 160/270 (59%) |
| search latency on the busy copy, 8 queries, median | 1,924 ms | 2,381 ms |
| peak RSS of the process | 49 MB | 51 MB |

Better on both axes, but the bar above (97% precision) is met by neither. The 4 recall misses and every first 10, with
the judgments, are in plan/research/0247-search-meaning (real rows stay there).

**Today's three production misses** (not in the 11-19 copy; cosines from the embedder on the target texts):
- "looped transformer" -> the HN post of Thinking Machines' "Inkling 2 Mini" (it says "a looped transformer"): it matches
  by words but ranks below 10 posts naming it in their titles; its cosine is 0.531, under the floor and the top 30
  (~0.57+): meaning does not rescue it. Open: the word rank (a title-only rank against a 6,000-char page).
- "AMD Unsloth" -> the repost "We collaborated with @AMD …": cosine 0.455, far from the 30 Unsloth/AMD posts nearer:
  meaning does not rescue it. It needs the issue's third idea (the author or the entity, Unsloth, widening by identity),
  not built.
- "Inkling 2 Mini" padding: not an OR. The words are ANDed; the shattered.io comparisons hold all three because the
  index's English stemmer reads "Inkling" as `inkl`, the stem of German "inkl." / Swedish "inklusive" on those
  pages, plus "Mini-PC" and a "2". Their cosines are 0.41 and 0.28, so with the switch on the merged ranking puts every
  nearer Inkling post above them; they are not removed. A word-level fix (a name that the stemmer cuts, read whole)
  is not built.
