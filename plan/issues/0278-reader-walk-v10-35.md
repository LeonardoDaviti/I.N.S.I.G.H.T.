# 0278 — The reader's walk, fixed (v10.34–v10.35)

Status: built on branch v1029 (2026-11-22), not pushed. Owner review of the Inkling 2 Mini entity page plus a
read-only walk of production (News top rows, 8 entity pages, 2 families, 2 tracks).

## Built
- v10.34: a result achieved with a model is its own News row (judge-read-v1 unquoted joins re-asked; chain-v2:
  a result is not same_release); performance: the cite planner, read-ahead of a render's posts, long-reads by id.
- Entity page: one entry per release (a Mark IX story covered by a Mark X one is not listed twice; same_release
  groups are one entry), lead and date by News' rules (launch_order, story_rules.background; the release post
  leads), "(no title)" falls back to the lead's title, stories about the entity before stories that mention it.
- Timeline: releases only from the maker's own addresses (not their hosts) or a reading that says release; birth
  and first_outside about the thing, never an old Saved page, first_outside never the maker's own post.
- Versions: a build (GGUF, NVFP4) listed under its version; "5.0" = "5" and model ids folded (`same`); an org's or
  a person's page lists no versions; product SKUs (285K, 780M) are no checkpoints (repair `levels`).
- Merges: the general thing keeps over a build, then the most-mentioned name, then size, then age; repairs
  `reroot` (43 build roots + 7,284 minority spellings, type kept), `generic` (40 bare names several makers'
  names were merged into, e.g. Linux); maker_prefix guard; page maker from the cluster.
- Originals/addresses: never a chat conversation URL; a voice-platform post is its account's (own only for the
  entity or its maker); a code-host repo is own when it is the entity's repo (named as it, or under its maker).
- Joins: join/pair tasks carry their judged post (no two questions of one post in one call: 34% of v1 calls).
- Ingestion: tag/category/author listing pages are not posts (sitemap taxonomies, listing markup); track items
  show the shown title (Mastodon, Telegram).
- Page: no "Mark X entities" kicker, no accuracy note, no operator "old stories to check"; Research shows names.

## After deploy (owner)
1. Migration 0172 runs on start.
2. `python -m insight_core.scripts.hide_listing_pages --dry-run`, then without: 3,371 listing pages hidden on the
   copy (Krebs 2,594), nothing deleted. The 4 tracks holding them regroup their sections after.
3. Undo merge bc8d4950-affa-4456-9159-8a0964cf32c2 (Inkling 2 Mini into its GGUF), answer the GGUF "other version".
   Also look at the owner merge "Qwen Flash Next Coder" → "Qwen 27B" (looks wrong).
4. Entity repairs run in the decision runs: `reroot` 200 clusters a run (~37 runs), `levels`, `generic`.
5. The first decision run after deploy is full (READING_MODULES changed): 2.5–11 min on the copy.

## Measured, not shipped
- "A check at the keep bar demotes": 7/15 right on the copy (87 rows) — reverted.
- "A version needs a subject post": would drop 13,733 of 22,168 versions incl. real ones — not built. Hypothetical
  versions ("Fable 27") need the reading.
- Org-typed mentions linked by key to a product/model (Gemini the exchange on Gemini the model): 18.8k mentions;
  needs org twins for ~2k keys — design decision.

## Open
- The Mark IX story job's CPU (277 cpu-s per 30 min, ~4.5 cpu-min for 71 posts); centroid cosines N²; entity-vector
  HNSW insert cost.
- Story leads: the Apple row led by a cited article (rule:citation, first post never checked).
- Track section names read from 8 nearest posts only.
- `generic` repair wrong in ~7 of 40 (one product under an acquirer: ThinkPad, SketchUp).
