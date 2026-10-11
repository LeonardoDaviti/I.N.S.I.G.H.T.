# Explainable Briefings and Reader Workflow Implementation Plan

## Purpose

This document is for the future engineer who will implement the explainability and reader-workflow layer in INSIGHT.

The goal is to make the system inspectable and revisitable.
A briefing should not feel like a black box paragraph.
A post should not disappear after it has been used once.

When this feature is done, the analyst should be able to answer:
- which exact parts of which posts were used by AI
- why those parts were selected
- where the referenced post lives
- what the one-line takeaway is
- whether the post was already read or favorited

## Why we are building this

INSIGHT already stores posts and generates summaries/briefings.
But there is still a trust gap between:
- raw evidence
- derived output
- analyst memory

This feature closes that gap by introducing explicit evidence traces and reader state.

## Why this method

We are not trying to expose internal chain-of-thought.
We are building explicit, user-visible evidence traces:
- highlight spans
- importance notes
- source references
- interaction history

This is safer, more stable, and more useful than trying to reveal hidden reasoning.

## Product outcomes

### On a briefing card or line item
Show:
- one-sentence distillation
- referenced post links
- optional "why this matters" note

### On a post page
Show:
- extracted highlights actually used in summaries/briefings/story updates
- where each highlight was used
- why it was selected
- read state / first opened / last opened / total reading time
- favorite toggle

## Data model

Create a migration with these tables.

### `post_highlights`
Stores extracted important snippets from a post.

Fields:
- `id UUID PK`
- `post_id UUID NOT NULL REFERENCES posts(id)`
- `highlight_text TEXT NOT NULL`
- `highlight_kind TEXT NOT NULL DEFAULT 'evidence'`
- `start_char INT NULL`
- `end_char INT NULL`
- `language_code TEXT NULL`
- `importance_score REAL NOT NULL DEFAULT 0`
- `commentary TEXT NULL`
- `extractor_name TEXT NOT NULL`
- `extractor_version TEXT NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Indexes:
- `(post_id)`
- `(post_id, importance_score DESC)`

### `artifact_post_references`
Links derived outputs back to posts and optionally to highlights.

Fields:
- `id UUID PK`
- `artifact_type TEXT NOT NULL`
- `artifact_id UUID NOT NULL`
- `post_id UUID NOT NULL REFERENCES posts(id)`
- `highlight_id UUID NULL REFERENCES post_highlights(id)`
- `reference_role TEXT NOT NULL DEFAULT 'supporting'`
- `display_label TEXT NULL`
- `order_index INT NOT NULL DEFAULT 0`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Suggested artifact types:
- `daily_briefing`
- `topic_briefing`
- `weekly_briefing`
- `post_summary`
- `story_update`
- `vertical_briefing`

### `post_interactions`
Local analyst interaction state.

Fields:
- `id UUID PK`
- `post_id UUID NOT NULL REFERENCES posts(id)`
- `interaction_type TEXT NOT NULL`
- `interaction_value JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Interaction types:
- `opened`
- `favorited`
- `unfavorited`
- `reading_session`

### Optional cached view / materialized table later
`post_reader_state`
- `post_id`
- `is_favorited`
- `open_count`
- `first_opened_at`
- `last_opened_at`
- `total_read_seconds`

Do not build this until query patterns justify it.

## Service layout

Create:
- `backend/insight_core/db/repo_highlights.py`
- `backend/insight_core/services/highlights_service.py`
- `backend/insight_core/services/post_interactions_service.py`

Responsibilities:

### repo_highlights
- insert highlights
- fetch highlights for post
- fetch references for artifact
- fetch artifacts using a highlight/post

### highlights_service
- generate highlights for a post
- attach references while generating summaries/briefings
- return user-facing explainability payloads

### post_interactions_service
- record open event
- start/end reading session or accumulate dwell time
- toggle favorite
- compute current post reader state

## Processor changes

Extend the AI processor with a separate task:
- `extract_post_highlights(post)`

Expected output:

```json
{
  "highlights": [
    {
      "text": "OpenAI released GPT-4 with multimodal capabilities.",
      "kind": "claim",
      "importance_score": 0.96,
      "commentary": "This is the core development referenced by later commentary.",
      "start_char": 120,
      "end_char": 172
    }
  ],
  "one_sentence_takeaway": "The post announces a concrete model release that anchors the surrounding discussion."
}
```

Do not mix this with briefing prompts.

## Integration points

### During post analysis
If a post receives a cached AI summary, it is a good time to also generate highlights.

### During briefing generation
Whenever the briefing references a post, persist `artifact_post_references`.
If the briefing can cite a specific highlight, attach `highlight_id`.
If not, attach the post only.

### During UI reads
- record `opened`
- optionally record reading session start/end

## Phases

### Phase 1: clickable sources and artifact references
- persist briefing/post references
- render clickable post links in briefings

### Phase 2: highlights and one-sentence takeaway
- generate `post_highlights`
- show them on post detail
- show a one-sentence takeaway on post detail and briefing cards

### Phase 3: why-this-matters notes
- show analyst-facing rationale for each highlight
- keep these short and factual

### Phase 4: favorites and reading history
- add favorite toggle
- add reading history and dwell estimates
- expose basic analytics on the post page

## Common mistakes

### Mistake 1
Trying to expose hidden model reasoning.
Do not do this.
Show explicit evidence traces instead.

### Mistake 2
Storing only briefing-level references, not per-post references.
That makes the feature too vague.

### Mistake 3
Treating dwell time as exact truth.
It is only an estimate.

### Mistake 4
Generating too many highlights.
Show 3 to 7 meaningful snippets, not 30 sentences.

## First practical milestone

A daily briefing line item shows clickable post sources.
Clicking opens the post page, where the analyst can see the top 3 highlights and a one-sentence takeaway.

## Final milestone

Every major INSIGHT output is explainable via explicit post references and reusable highlights, while the analyst can keep track of what was read, saved, and revisited.
