# Stories Implementation Plan

## Purpose

This document is for the future engineer who will implement the **Stories** layer in INSIGHT.

The goal is to turn INSIGHT from:

- a system that stores posts
- groups them into daily topics
- renders briefings

into:

- a system that identifies the underlying development
- selects the best available primary source
- attaches commentary and reactions to it
- preserves the evolution of that development across time

This is the concrete product form of the broader **Single Source Of Truth** idea.

If you remember only one sentence from this document, remember this:

**A story is the durable object for one real-world development, while posts are evidence and topics are temporary groupings.**

## How To Think About INSIGHT

Before you write code, understand the current layers:

- `sources`
  - the registry of feeds/channels/accounts/subreddits
- `posts`
  - the normalized evidence table
- `topics`
  - daily AI-generated groupings
- `briefings`
  - cached daily/topic/weekly outputs
- `job_runs`
  - operational history

The mistake a junior engineer is likely to make is this:

- trying to force stories into `topics`
- trying to force stories into `entities`
- trying to skip provenance and only cluster with embeddings

Do not do that.

The correct mental model is:

- `post` = one piece of evidence
- `topic` = one short-lived narrative cluster for a date range
- `entity` = a durable noun across time
- `story` = one durable development/event across time

Examples:

- `OpenAI` is an entity
- `GPT-5.4 mini` is an entity
- `OpenAI released GPT-5.4 mini` is a story
- `People are debating the release` is commentary attached to that story

## Product Outcome

When this feature is done well, the user should be able to ask:

- What actually happened?
- Which post is the best primary source?
- Which other posts are only commentary?
- What changed in this story across the week?
- Which entities are involved?

That means the UI and data model should support:

- one canonical story title
- one preferred source-of-truth post
- related posts by role
- timeline of updates
- later: user correction and story merging/splitting

## Design Principles

### 1. Provenance is mandatory

Every story claim must point back to exact posts.

Do not produce free-floating summaries without evidence links.

### 2. Prefer primary evidence over commentary

If an official source, paper, changelog, release note, or original thread exists, it should usually outrank commentary.

But do not hardcode this blindly.

Sometimes:

- the first post is incomplete
- the primary source is unavailable
- the best explanatory post is derivative

That is why the system needs confidence, not fake certainty.

### 3. Stories must survive across days

Daily topics expire conceptually.

Stories do not.

That is why stories need stable IDs and explicit `first_seen_at` / `last_seen_at`.

### 4. Human correction matters

Eventually the user will need to:

- promote another post as source of truth
- split one story into two
- merge duplicate stories
- remove irrelevant commentary from a story

Do not design a schema that makes correction impossible later.

### 5. Cheap heuristics should narrow the problem before AI

Do not start with “send every post pair to the model.”

Use:

- URL and domain signals
- time proximity
- title similarity
- entity overlap
- explicit link references
- source type hints

Then use AI to resolve ambiguous cases.

## Recommended Data Model

Create a dedicated migration in:

- `backend/insight_core/db/migrations/`

Do not hide story state inside `topics.metadata`.

### `stories`

Core durable object.

Suggested fields:

- `id UUID PK`
- `canonical_title TEXT NOT NULL`
- `canonical_summary TEXT NULL`
- `story_kind TEXT NOT NULL DEFAULT 'other'`
- `status TEXT NOT NULL DEFAULT 'active'`
- `source_of_truth_post_id UUID NULL REFERENCES posts(id)`
- `source_of_truth_confidence REAL NOT NULL DEFAULT 0`
- `first_seen_at TIMESTAMPTZ NULL`
- `last_seen_at TIMESTAMPTZ NULL`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Recommended indexes:

- `status`
- `story_kind`
- `first_seen_at`
- `last_seen_at`

### `story_posts`

Join table between stories and posts.

Suggested fields:

- `story_id UUID REFERENCES stories(id)`
- `post_id UUID REFERENCES posts(id)`
- `role TEXT NOT NULL`
- `relevance_score REAL NOT NULL DEFAULT 0`
- `is_primary_candidate BOOLEAN NOT NULL DEFAULT FALSE`
- `evidence_weight REAL NOT NULL DEFAULT 0`
- `added_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `metadata JSONB NOT NULL DEFAULT '{}'`

Primary key:

- `(story_id, post_id)`

Recommended roles:

- `primary`
- `commentary`
- `reaction`
- `follow_up`
- `validation`
- `criticism`
- `duplicate`
- `context`

### `story_events`

This table stores timeline slices.

Suggested fields:

- `id UUID PK`
- `story_id UUID REFERENCES stories(id)`
- `event_date DATE NOT NULL`
- `title TEXT NOT NULL`
- `summary TEXT NOT NULL`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Recommended index:

- `(story_id, event_date)`

### `story_event_posts`

Do not stuff large `post_ids` arrays directly into one row if you want future flexibility.

Suggested fields:

- `story_event_id UUID REFERENCES story_events(id)`
- `post_id UUID REFERENCES posts(id)`
- `role TEXT NULL`

Primary key:

- `(story_event_id, post_id)`

### Optional Later: `story_links`

Use this only after the core works.

This is for:

- `continuation_of`
- `contradicts`
- `same_as`
- `supersedes`

Do not build this in phase 1.

## Recommended Code Layout

Follow the existing repo/service pattern already used in INSIGHT.

Create:

- `backend/insight_core/db/repo_stories.py`
- `backend/insight_core/services/stories_service.py`

Later, optionally:

- `backend/insight_core/services/story_briefing_service.py`

Keep responsibilities clear.

### Repository responsibilities

- create/update/read stories
- attach posts to stories
- read story timelines
- fetch recent candidate stories for resolution
- manage source-of-truth assignment

### Service responsibilities

- detect story candidates
- resolve candidates against existing stories
- classify post roles
- build/update story timelines
- expose story-centric API payloads

### Processor responsibilities

Extend:

- `backend/insight_core/processors/ai/gemini_processor.py`

Do not bury orchestration logic inside the processor.

The processor should only:

- classify
- extract
- summarize
- rank candidates when heuristics are inconclusive

## Phase Plan

Implement this in phases. Do not jump to the final vision immediately.

### Phase 1: Story Candidate Detection

Objective:

- identify groups of posts that likely refer to the same underlying development

Input:

- new posts after ingestion
- optionally recent posts from the last `N` days

Use cheap heuristics first:

- exact or near-exact shared URLs
- same linked paper/release/changelog URL
- same product/model names from entity extraction
- temporal closeness
- significant title overlap
- “X released Y” vs “comment about Y” patterns

Output shape:

- candidate clusters
- primary-source candidates

The output here does not need to be perfect.
It only needs to reduce the search space.

### Phase 2: Source-Of-Truth Selection

For each candidate cluster, determine:

- which post is the best primary anchor
- which posts are derivative
- what role each attached post should have

Use deterministic preference rules first:

- official domain > commentary domain
- paper/changelog/release notes > discussion about the paper/changelog/release notes
- original thread > repost
- direct artifact link > vague reaction

Then use the model only when the result remains ambiguous.

Store:

- chosen source-of-truth post
- confidence
- reason metadata if available

### Phase 3: Story Resolution Against Existing Stories

Before creating a new story:

1. compare against recent stories
2. look for shared entities
3. compare primary artifact URLs
4. compare titles/summaries
5. compare attached post overlap

If the candidate matches an existing story:

- attach posts to that story
- update `last_seen_at`
- maybe add a new story event for the day

If not:

- create a new story

This is where many junior implementations go wrong by creating duplicate stories every day.

Your job is not “cluster today.”
Your job is “maintain one durable story object across time.”

### Phase 4: Story Timeline Construction

Every time a story receives new posts, decide whether that day produced a meaningful update.

Create or update one `story_event` for that day with:

- short title
- summary of what changed
- attached evidence posts

This will become the basis for:

- weekly story briefings
- monthly story briefings
- “what changed since last time” UI

### Phase 5: Story-Aware Weekly Briefings

Once stories exist, weekly briefings should stop being only:

- merged daily topic summaries

and become:

- a story evolution layer

The output should prioritize:

- new stories
- materially updated stories
- stories with contradictions
- stories with strong commentary from trusted entities

## API Shape

Do not build everything at once.

Start with read-oriented APIs that support debugging and UI validation.

Suggested first routes:

- `GET /api/stories`
- `GET /api/stories/{story_id}`
- `GET /api/stories/{story_id}/timeline`
- `POST /api/stories/rebuild-for-date`
- `POST /api/stories/{story_id}/refresh`

Later:

- `POST /api/stories/{story_id}/promote-primary`
- `POST /api/stories/{story_id}/merge`
- `POST /api/stories/{story_id}/split`

## UI Order

Do not start with a giant story dashboard.

Start with the minimal surfaces that prove the model works.

### 1. Post detail page

Add:

- connected story
- post role inside story
- source-of-truth badge if applicable

### 2. Weekly briefing page

Add:

- story cards instead of only topic cards
- evolution timeline
- primary source callout

### 3. Story detail page

This page should show:

- canonical title
- canonical summary
- primary source post
- timeline events
- supporting posts grouped by role
- connected entities later

## How Stories Interact With Entities

Entities and stories are complementary.

Entities answer:

- who or what is involved

Stories answer:

- what happened

A strong implementation path is:

1. extract entities from posts
2. use entity overlap to help candidate story resolution
3. attach entities to stories later via aggregated post evidence

Do not wait for the entity system to be perfect before building stories.

Stories can start from posts plus heuristics.

## How Stories Interact With Topics

Topics are still useful.

Topics are the daily working layer.

Stories are the durable truth layer.

Recommended relationship:

- a topic may contribute posts to one or more stories
- a story may receive posts from multiple daily topics across multiple days

Do not force a 1:1 relationship.

## Prompting Guidance

When adding story-related prompts to `GeminiProcessor`, do not ask vague questions like:

- “group these into stories”

Instead ask constrained questions like:

- which post is the best primary source
- which posts are commentary vs validation vs reaction
- whether this candidate belongs to an existing story
- what changed on this date for this story

Good prompts reduce ambiguity.
Bad prompts create unstable IDs and unstable clustering.

## Operational Guidance

Story generation should be visible in `job_runs`.

Recommended job types:

- `story_candidate_detection`
- `story_resolution`
- `story_timeline_update`
- `weekly_story_briefing`

Store useful payload metadata:

- candidate_count
- new_story_count
- updated_story_count
- promoted_primary_count
- estimated_tokens
- sample_story_ids

This matters because story logic will fail silently if you do not instrument it.

## Common Failure Modes

### Failure 1: Everything becomes a new story

Cause:

- weak resolution against existing stories

Fix:

- compare against recent story anchors before creating new records

### Failure 2: Commentary becomes the source of truth

Cause:

- over-reliance on social posts or reactions

Fix:

- add source ranking heuristics and artifact-link preference

### Failure 3: One story becomes too broad

Cause:

- “AI” or “OpenAI” level grouping instead of event grouping

Fix:

- force event-level resolution, not entity-level grouping

### Failure 4: Timeline is noisy

Cause:

- every attached post becomes an event

Fix:

- only create story events when something materially changes

### Failure 5: No path for correction

Cause:

- immutable automatic assignment

Fix:

- design admin/user correction routes from the start, even if UI comes later

## First Practical Milestone

The first milestone should be intentionally narrow.

Target:

- ingest one day of posts
- detect candidate stories
- create stories
- select a primary source
- attach related posts by role
- render a simple story-aware weekly view

If that works, then the system has crossed the threshold from:

- “grouped posts”

to:

- “structured information intelligence”

## Final Advice To The Junior Engineer

Do not try to impress with complexity.

The correct implementation is the one that produces:

- stable story IDs
- clear provenance
- believable primary-source selection
- useful story timelines

If users cannot answer “what actually happened?” from the story object, the feature is not done.
