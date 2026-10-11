# INSIGHT Feature Consolidation Plan

## Why this document exists

The owner dumped several ideas that look separate on the surface but are not independent in implementation.
If we build them one by one without consolidation, we will duplicate schema, duplicate prompts, and create UI surfaces that do not compose well.

This document groups the ideas into coherent product features and recommends build order.

## Original idea groups

1. Briefing explainability
   - show which post parts were actually used by AI
   - clickable source links from briefings back to posts
   - one-sentence distillation
   - comments on why a highlight mattered
2. Timeline
   - find related past and future posts for a current post
   - show evolution of one development over time
3. Custom archivators
   - scrape sources with poor or missing feeds
4. Posts workflow
   - favorites
   - reading history / reading time / opened posts

## Consolidated product features

### A. Explainable Briefings and Reader Workflow

Combine:
- briefing/source traceability
- highlight spans
- why-this-matters comments
- clickable post references from briefings
- one-sentence distillations
- favorites
- reading history

Why these belong together:
- all are reader-facing surfaces around understanding, trusting, and revisiting information
- all depend on post detail UI and derived-artifact provenance
- all can share one common model: `post interaction + derived evidence trace`

### B. Story Timeline and Narrative Trace

Combine:
- similar-post discovery for one post
- past/future timeline
- post-centric view into a story

Why these belong together:
- timeline is not a separate ontology object; it is a view over story evolution
- similar-post retrieval is the candidate-generation step for story resolution and timeline expansion
- the system should not build a "timeline feature" disconnected from Stories

### C. Source Adapters and Custom Archivators

Combine:
- custom scrapers for weak/no-RSS sources
- source-specific archive logic
- artifact extraction quality improvements for hard sources

Why these belong together:
- this is acquisition infrastructure, not a UI feature
- every custom source will need the same lifecycle: discovery, fetch policy, parser, dedupe, archival metadata, monitoring

## What should NOT be combined

### Do not combine Story Timeline with Explainable Briefings
They touch similar pages, but the dependencies are different.
One is about provenance of already-generated outputs.
The other is about durable cross-time resolution.

### Do not combine Custom Archivators with Favorites/History
One is ingestion infrastructure; the other is analyst interaction state.
They should ship separately.

## Recommended order

1. Explainable Briefings and Reader Workflow
2. Story Timeline and Narrative Trace
3. Source Adapters and Custom Archivators

Reasoning:
- feature A adds immediate trust and usability to the existing product
- feature B compounds strongly once Stories land
- feature C is strategically important, but should be implemented with the monitor/discovery architecture in mind rather than as isolated scripts

## Design rule across all three

Human control remains primary.
The system may propose:
- highlights
- related posts
- timeline links
- source interpretations

But the analyst must be able to:
- inspect evidence
- override links
- ignore weak candidates
- favorite / annotate / revisit

## Final milestone for this batch

By the end of this feature batch, INSIGHT should let the analyst:
- open a briefing and see exactly which post snippets drove it
- click directly into the referenced post
- see a compact one-line distillation and why it matters
- open any post and jump into its evolving story timeline
- collect hard-to-find sources through custom adapters where RSS is weak or missing
- keep a personal memory of what was read and saved
