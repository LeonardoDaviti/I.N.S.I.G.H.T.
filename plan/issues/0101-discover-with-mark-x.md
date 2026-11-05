# 0101 — Discover with Mark X: coverage gaps by entity, sources found by attribution, and tracks

Status: **future** (2026-11-04). Mark X, after 0080 (merged on main 2026-11-04) and 0090.

## Why (the sources review, 2026-11-04)
- **Discover suggests only what your sources link.** After 0080 it is tested, ranked and clean, but:
  - an account that breaks news and is quoted without a link is invisible;
  - a forwarded Telegram channel is invisible, because the bridge strips forwards (0 of 14,280 posts carry one).
- **It has no view by entity.** Your stories are about a few labs and model families, yet several of those have no source of their own among yours. Today that shows only as hosts that many sources link.
- **It suggests no tracks.** The owner asked for them on 2026-10-28: "Discover should suggest tracks, not only sources".

## What
1. **Coverage gaps:**
   - "Your stories are about <entity> (N stories this month), but you follow none of its own channels."
   - The suggestion is the entity's own site or account, from 0090's makers and the hosts its posts come from.
   - Ranked by how much of your News the entity is in.
2. **Attribution:**
   - names of sources inside posts become candidates ("according to <outlet>", "via @account", "<channel> writes"), counted like links;
   - Haiku's reading marks attributions, and code resolves them to an address or account.
3. **Tracks:**
   - clusters of entities and stories over your sources: "9 of your sources cover AR glasses: make them a track?";
   - and for the hosted product, predefined tracks.
4. **Originality first:** among candidates you could follow, the ones that break news rank above the ones that repeat it (0093's numbers, once followed).

## Measure before adopting
- The first 30 coverage-gap and attribution suggestions, labelled by you: worth following or not.
- Compare with 0080's first 30.
