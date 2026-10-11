# Story Timeline and Narrative Trace Implementation Plan

## Purpose

This document is for the future engineer who will implement post-centric timeline navigation in INSIGHT.

The goal is to let the analyst open one post and see the wider evolution of the development it belongs to.

Important principle:
Timeline is not a separate durable object.
Timeline is a view over Story evolution.

## Why we are building this

The analyst does not only want to know what one post says.
The analyst wants to elevate above the battlefield and understand:
- what came before
- what changed later
- how this development evolved

## Why this method

We should not build timeline by naive nearest-neighbor similarity.
That will overlink on shared entities like "OpenAI" or "AI".

The right pattern is:
1. retrieve candidate related posts cheaply
2. adjudicate with story-aware logic
3. attach accepted posts as story evidence
4. render the timeline from story updates

## Relationship to Stories

Story = durable development object.
Timeline = chronological presentation of that story from the vantage point of a current post.

Timeline helps story construction by surfacing candidate related posts.
Story helps timeline quality by providing stable membership and update boundaries.

## Data model dependencies

This plan assumes Stories exist.
Use or extend:
- `stories`
- `story_posts`
- `story_updates` or `story_events`

Add one helper table if needed.

### `story_candidate_links`
Temporary or reviewable related-post candidates.

Fields:
- `id UUID PK`
- `source_post_id UUID NOT NULL REFERENCES posts(id)`
- `candidate_post_id UUID NOT NULL REFERENCES posts(id)`
- `candidate_story_id UUID NULL REFERENCES stories(id)`
- `retrieval_method TEXT NOT NULL`
- `retrieval_score REAL NOT NULL DEFAULT 0`
- `decision_status TEXT NOT NULL DEFAULT 'proposed'`
- `decision_reason TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Statuses:
- `proposed`
- `accepted`
- `rejected`
- `needs_review`

## Retrieval strategy

Use embeddings only for candidate retrieval, not final truth.

Candidate signals:
- shared canonical URL or artifact URL
- shared strong entities
- title/lede similarity
- short pivot summary similarity
- source mentions linking to the same development
- time window proximity
- existing story overlap

Recommended retrieval ladder:
1. deterministic artifact/URL match
2. strong entity overlap within time window
3. embedding retrieval over short normalized summaries or titles
4. LLM adjudication only for ambiguous cases

Do not embed full noisy multilingual posts as the only signal.
Prefer:
- title
- short normalized summary
- extracted event sentence

## Service layout

Create:
- `backend/insight_core/services/story_timeline_service.py`
- `backend/insight_core/db/repo_story_candidates.py`

Responsibilities:

### repo_story_candidates
- insert candidate links
- update candidate decisions
- fetch candidates for post/story

### story_timeline_service
- retrieve candidates for a post
- adjudicate whether candidate belongs to same story
- rebuild post timeline view
- expose past/future slices

## API shape

Suggested routes:
- `GET /api/posts/item/{post_id}/timeline`
- `POST /api/posts/item/{post_id}/timeline/refresh`
- `POST /api/story-candidates/{id}/accept`
- `POST /api/story-candidates/{id}/reject`

## UI behavior

On post detail page show:
- current story anchor
- prior relevant updates
- later relevant updates if already known
- why each linked post belongs here

Group timeline entries by date.
Do not dump all posts flat.

## Phases

### Phase 1: candidate retrieval
- generate related post candidates using rules + embeddings
- store `story_candidate_links`

### Phase 2: story-aware acceptance
- accept/reject candidates using story logic or LLM adjudication
- attach accepted posts to story if appropriate

### Phase 3: render timeline
- show chronological updates around the current post
- clearly separate past and later updates

### Phase 4: analyst correction
- allow analyst to reject or manually attach candidates

## Common mistakes

### Mistake 1
Treating every similar post as timeline-worthy.
Timeline should show development evolution, not topical cousins.

### Mistake 2
Using embeddings as final truth.
They are only retrieval aids.

### Mistake 3
Building timeline before Stories exist.
That leads to unstable IDs and bad continuity.

## First practical milestone

Open a post and see 3-5 candidate related posts from the same development, clearly labeled as earlier or later.

## Final milestone

Any significant post can be opened inside a coherent story timeline that explains the evolution of the underlying development across time.
