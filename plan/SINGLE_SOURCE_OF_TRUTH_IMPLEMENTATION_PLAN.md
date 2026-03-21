# Single Source Of Truth Implementation Plan

## Purpose

This document is for the future engineer who will turn INSIGHT from "a system that groups posts into topics" into "a system that identifies the original event, links downstream commentary to it, and preserves the evolution of the story over time."

The feature is called **Single Source Of Truth** because most recurring news waves have this shape:

1. One primary event happens.
2. One source publishes the original artifact or closest primary report.
3. Other sources comment on it, react to it, summarize it, criticize it, or add marginal detail.

INSIGHT should stop treating those as separate, flat items when they are obviously part of one story.

This is not just deduplication.
This is the beginning of story intelligence.

For the concrete implementation shape of this idea, also read:

- `plan/STORIES_IMPLEMENTATION_PLAN.md`

## Mental Model

Do not start by asking "how do I cluster similar titles?"

Start by asking:

- What is the underlying event?
- Which post is the closest thing to primary evidence?
- Which posts are commentary, amplification, validation, opposition, or derivative reporting?
- How did the story evolve over time?

The feature should help the system answer questions like:

- "What actually happened?"
- "Who first published the core event?"
- "What are the most useful follow-up reactions?"
- "What changed in the story after the initial publication?"

## What This Feature Is

Single Source Of Truth should produce a new durable object in the backend:

- a **story**

A story is not the same as a daily topic.

Daily topics are short-lived narrative buckets for one day.
Stories are cross-source, cross-day, potentially cross-week structures that represent one underlying development.

Examples:

- `DeepSeek released DeepSeek-OCR`
- `OpenAI launched GPT-5.4 mini`
- `Karpathy published 2025 LLM Year in Review`

Then connected posts can be attached as:

- original publication
- commentary
- expert reaction
- benchmark/validation
- criticism
- derivative summary
- implementation note

## What This Feature Is Not

Do not confuse this feature with:

- entity memory
- topic clustering
- recommendation ranking
- vector-only "semantic grouping"

Entity memory tracks durable nouns over time: people, companies, products, models.
Single Source Of Truth tracks durable **events/stories** over time.

Entities will help story resolution later, but stories must be their own first-class object.

## Core Design Principles

1. Provenance first.
Every story decision must be traceable to exact posts.

2. Primary over derivative.
The system should always try to identify the best available primary source.

3. Stable identifiers.
Stories need durable IDs so weekly/monthly timelines and future alerts can refer to the same thing.

4. Human-correctable.
The user must be able to merge, split, promote, or reassign posts later.

5. Cross-time aware.
The same story may appear on Monday, continue on Wednesday, and mature on Friday.

## Data Model

Add new database tables only when the semantics are clear.
Do not shove this into `topics.metadata`.

Recommended schema:

### `stories`

- `id`
- `canonical_title`
- `canonical_summary`
- `status`
  - `active`
  - `resolved`
  - `watch`
- `story_kind`
  - `launch`
  - `paper_release`
  - `policy_change`
  - `incident`
  - `tooling_update`
  - `market_signal`
  - `other`
- `source_of_truth_post_id`
- `source_of_truth_confidence`
- `first_seen_at`
- `last_seen_at`
- `created_at`
- `updated_at`

### `story_posts`

Join table between stories and posts.

- `story_id`
- `post_id`
- `role`
  - `primary`
  - `commentary`
  - `reaction`
  - `follow_up`
  - `validation`
  - `criticism`
  - `duplicate`
- `relevance_score`
- `added_at`

### `story_events`

Chronological slices for story evolution.

- `id`
- `story_id`
- `event_date`
- `title`
- `summary`
- `post_ids` or normalized child table
- `created_at`

### Optional Later: `story_links`

For relations like:

- same underlying story
- parent/child
- contradiction
- continuation

Do not build this first.

## How It Should Interact With Existing Objects

### Posts

Posts remain the atomic evidence layer.

### Topics

Topics remain a daily organizational layer.

### Stories

Stories become the durable cross-day narrative layer.

### Briefings

Daily briefings can mention stories.
Weekly briefings should heavily rely on stories.
Monthly briefings should eventually be story-driven by default.

## Extraction Pipeline

Build this in stages.

### Stage 1: Candidate Story Detection

After ingestion and after daily topics exist:

1. Take posts from the day.
2. Group obvious duplicates/reactions into candidate story sets.
3. Identify the likely primary post in each set.

Use:

- title similarity
- URL/domain signals
- time proximity
- shared entities
- explicit references inside the text
- AI classification only after cheap heuristics

The purpose of heuristics is not perfection.
It is to reduce the AI search space.

### Stage 2: Source Of Truth Selection

For each candidate story cluster, decide:

- which post is closest to the original event?
- which are clearly derivative?

Rules of thumb:

- Official announcement beats commentary.
- Research paper link beats someone tweeting about the paper.
- Product changelog beats a newsletter summarizing the changelog.
- A reaction thread should not become the primary source when the original exists.

But be careful:

- sometimes commentary contains the best explanation
- sometimes the first source is not the best source
- sometimes no true primary exists

So the system must store confidence, not false certainty.

### Stage 3: Story Resolution Against Existing Stories

Before creating a new story:

1. Resolve whether this candidate belongs to an existing story.
2. If yes, attach new posts/events to that story.
3. If no, create a new story.

Resolution should use:

- recent story titles and summaries
- attached entities
- linked source domains
- post overlap
- AI disambiguation only when heuristics are inconclusive

### Stage 4: Timeline Construction

When new posts are attached to a story:

- create or update a `story_event` for that day
- summarize what changed that day
- keep the timeline ordered

This is what enables "topic evolution by week" to become true story evolution later.

## Suggested Service Layout

Do not bury this inside one oversized file.

Recommended backend structure:

- `backend/insight_core/services/story_service.py`
  - orchestration
- `backend/insight_core/db/repo_stories.py`
  - story persistence
- `backend/insight_core/processors/ai/story_resolver.py`
  - AI prompts for source-of-truth selection and story matching
- `backend/insight_core/services/story_briefing_service.py`
  - story-driven weekly/monthly outputs

If you prefer to extend `BriefingService`, keep story resolution logic outside it.
Briefing generation and story resolution are not the same job.

## Prompting Guidance

When using the model, do not ask:

- "Group these into topics."

Ask:

- "Which post is the most primary source?"
- "Which posts are commentary on the same underlying event?"
- "Did these posts describe the same event or only adjacent events?"
- "What changed in this story over time?"

Required prompt outputs should be structured JSON with:

- story title
- canonical summary
- source_of_truth_post_id
- confidence
- linked post IDs with roles
- timeline entries

Never accept free-form text for story resolution internals.

## UI Targets

Do not build all UI at once.

Recommended order:

1. Story badges on posts
2. Story page
3. Story timeline
4. Weekly briefing using stories
5. Manual merge/split/promote controls

The story page should eventually show:

- canonical story summary
- source of truth post
- story timeline
- related commentary
- linked entities
- contradictions / disputes

## Failure Modes To Avoid

1. Over-merging unrelated posts because titles look similar.

2. Under-merging obvious commentary because exact wording differs.

3. Treating derivative blog posts as primary when the original artifact exists.

4. Creating stories that are only "AI", "OpenAI", "agents", etc.
Those are categories, not stories.

5. Losing provenance.
If a user cannot inspect why a post belongs to a story, the system is not trustworthy.

## Phased Implementation Plan

### Phase 1

- schema for `stories`, `story_posts`, `story_events`
- basic resolver service
- manual job to build stories from one day of posts
- API endpoints to inspect created stories

### Phase 2

- automatic story resolution after daily topic generation
- story page in frontend
- source-of-truth post selection exposed in UI

### Phase 3

- weekly story briefings
- story evolution cards
- merge/split admin actions

### Phase 4

- entity-assisted story resolution
- contradiction detection
- priority/watchlist scoring

## Relationship To Entity Memory

Entity memory and single source of truth should inform each other.

Entities help stories because:

- they identify who/what the story is about
- they disambiguate similar titles
- they connect commentary back to the same subject

Stories help entities because:

- they show which entity changes actually matter
- they provide event-level context for entity updates

But do not tightly couple the first implementation.
Build stories so they work even before the full entity layer exists.

## Engineering Standard

The junior engineer implementing this should optimize for:

- correctness of story boundaries
- auditability
- deterministic storage
- human override later

Do not optimize for novelty.
Do not optimize for "smart" demos.
Optimize for a stable intelligence workflow that can support weekly and later monthly story timelines without rewriting the entire model.
