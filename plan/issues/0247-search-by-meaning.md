# 0247 — Search by meaning on top of words

Status: **written, skipped for development** (owner 2026-11-20: "skip the search the meaning, write issue but skip
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
