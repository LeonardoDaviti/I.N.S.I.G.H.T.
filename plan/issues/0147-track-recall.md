# 0147 — Track recall: find a track's posts with several finders, not one description vector

Status: **spec** (2026-11-09). Stealth, beside 0145 (tracks as topics). Build when the owner's tracks have their
first ✓ labels (finders 2–5 learn from them); the example-post finder (1) needs none.

Read first: `plan/HANDOFF-v10.md` "Rules for every agent"; `plan/issues/0145-tracks-as-topics.md` and
`0145-built.md`; `markx/tracks.py` (the prefilter, the profile, the planner); `mx_mentions_now`, the reading's
`kind`/`main.numbers`, `post_links`, `mx_post_search` (0139), `mx_embeddings`.

**The owner (2026-11-09):** "is embedder enough to find related posts? where embedder fails? or we have enough
features, like entities and other things to help embedder? discuss all the options." → "yes write it."

**Constraints:** no real names in committed files (rows: `plan/research/0147-notes.md`; 0145's in
`0145-notes.md`); fix the class; never one signal alone (the owner's ensemble rule); unit tests + 3–5 real checks;
realdata-check once at release.

## Why (0145's measure, 2026-11-09, a 30-day server copy, 5,751 posts)
- The description vector is a weak signal: the median post sits at cosine 0.39–0.44 to any description. At 0.55
  the prefilter passed 22 posts of 5,751 and found **0 of 20** posts that belong to a project-ideas track; the
  adopted "closest 30%" finds 10 of 20, end to end 8 of 15.
- **Where it fails** (classes, each with private rows):
  1. **Abstract description, concrete posts:** "cool" and "worth printing" are judgements; a self-built inference
     engine running a 32B model in a 16 GB GPU sits at 0.36, below the 30% bar.
  2. **One vector, many sub-topics:** the average of a track's sub-topics is near none of them.
  3. **Long posts:** only the first 1,500 characters are embedded (`TEXT_CHARS`).
  4. **Short posts:** "22 tok/s on an RTX 3060" carries little meaning for a vector.
  5. **Passing mentions:** a big vendor's library launch sits at 0.48 (top 10%): the judge rejects it, but it spent
     a judgement.
  6. **Images:** a print shown only in a photo (not in this issue).
- **The judge is good once it sees the post:** 13 of 15 belonged posts said `in` on two tracks.

## What it does
Step 1 becomes **finders whose candidates are combined**, then the Haiku judge as today.
1. **Example posts (probes).** Once per track version, a `probes` task (guide `probes-v1`, Haiku, one call) writes
   12–20 short example posts across the track's likely sub-topics (and 4 near-misses from `excludes`); each is
   embedded (an `embed` task). A post's score is its **max** cosine to the probes (near-miss probes subtract). The
   description stays one probe.
2. **Entities from ✓ items.** Entities (subject/actor roles, `mx_mentions_now`) that occur in ≥ 2 ✓ items and in no
   more than 1% of all posts become the track's entity set; a post naming one as subject or actor is a candidate.
3. **Domains from ✓ items.** Link domains (`post_links`, not home pages, not platforms) of ≥ 2 ✓ items, and the
   domain classes a track names (code hosts, model hubs, 3D-model sites) by the description's words; a post linking
   one is a candidate.
4. **Words from ✓ items.** Terms over-represented in ✓ items against all posts (a log-odds lexicon, top 30), searched
   in the post's index and Mark X's English layer (0139); a post with 2+ is a candidate. For numeric tracks, a
   reading's `numbers` with the track's units (tok/s, GB, VRAM, $) count as a word.
5. **Source and story priors.** A source whose items were ✓ ≥ 3 times (and ≥ 20% of its judged) lowers the bar for
   its posts; a post in the same story as a ✓ item is a candidate.
6. **A small classifier (after ≥ 30 labels, ≥ 8 of each).** Logistic regression on the post vector plus the finder
   features (probe max-sim, entity/domain/word hits, source prior); retrained when 10 new labels arrive; ranks the
   union of candidates. Below the threshold only if no finder fired.
- **The union is capped** by the same budget as 0145 (`TRACK_TASKS_PER_RUN`), ordered by the classifier when it
  exists, else by the count of finders that fired, then probe max-sim. Every candidate records which finders fired
  (shown on hover: "found by: example post, entity, domain").

## Measure before adopting
On a server copy with the owner's tracks and labels (or the agent's labelled set from 0145 until the owner's exist):
- recall of each finder alone and of the union, on belonged posts, at the same number of judgements as today;
- precision after the judge must not fall;
- adopt a finder only if it adds recall; report exact rows (private).

## Done when
- Tests: probes planned once per version, embedded, max-sim with near-miss subtraction; entity/domain/word sets from
  ✓ items with their thresholds; numbers as words; source and story priors; the classifier's gate (30 labels, 8 of
  each) and retrain; the capped union and its order; "found by" on items.
- Worker: `probes` in `DEFAULT_KINDS`, `PER_CALL` `probes=1`; a fake-claude test.
- Migration if needed; frontend shows "found by"; design docs claim it.
