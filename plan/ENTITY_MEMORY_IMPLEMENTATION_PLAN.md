# Entity Memory Implementation Plan

## Purpose

This document is for the future engineer who will add entity memory to INSIGHT.

The goal is not to build a huge abstract knowledge graph first. The goal is to extend the current system so it can remember the important actors, artifacts, and claims that appear across posts over time, with explicit provenance back to the original sources.

INSIGHT already does three things well:

- it ingests heterogeneous source posts into one shared `posts` table
- it groups daily posts into `topics`
- it stores rendered briefings in `briefings`

Entity memory should sit on top of that, not replace it.

## How To Think About The System

### What the system already is

At the moment INSIGHT is a DB-backed information intake and briefing engine.

Important layers:

- `sources`
  - source registry
  - source settings
  - archive/live ingestion metadata
- `posts`
  - normalized storage for all fetched source items
  - this is the main evidence table
- `topics`
  - daily clustering/story grouping
  - useful for daily and later weekly synthesis
- `briefings`
  - cached rendered outputs for daily, topic, and now weekly briefings
- `job_runs`
  - operational telemetry for manual/automatic work

Important services:

- `backend/insight_core/services/source_fetch_service.py`
  - source acquisition and archive orchestration
- `backend/insight_core/services/posts_service.py`
  - post retrieval and metadata/category updates
- `backend/insight_core/services/topics_service.py`
  - topic storage and topic-post links
- `backend/insight_core/services/briefing_service.py`
  - cached daily/topic/weekly synthesis
- `backend/insight_core/services/post_detail_service.py`
  - single-post analysis, tags, notes, post chat
- `backend/insight_core/processors/ai/gemini_processor.py`
  - LLM-facing extraction/synthesis entry point

### What entity memory should be

Entity memory is the durable layer across days.

Topics answer:

- what was grouped together on one day

Entities answer:

- who keeps appearing
- what product/model/project keeps changing
- what claims have evidence behind them
- what changed this week versus last week

Do not confuse daily story clustering with durable identity.

Examples:

- `OpenAI` is an entity
- `GPT-5.4 mini` is an entity
- `RLVR adoption in local models` is probably a topic or later a theme, not a canonical entity
- `OpenAI released GPT-5.4 mini` is a claim/event with evidence

## Design Principles

### 1. Provenance first

Every extracted entity or claim must point back to one or more posts. Do not create free-floating intelligence.

### 2. Conservative resolution

If alias resolution is ambiguous, keep two candidate entities rather than merging aggressively.

### 3. Incremental processing

Do not reprocess the entire database whenever possible. Run extraction on new or changed posts after ingestion.

### 4. Start thin

Do not start with embeddings, graph algorithms, or complex ontology work.

Start with:

- canonical entities
- aliases
- post-to-entity mention links
- claim records with evidence links

### 5. The user product decides the schema

The first user-facing value is not “graph browsing.” It is:

- better weekly briefings
- entity-centric timelines
- source disagreement detection
- durable watchlists

## Phase 1: Durable Entity Extraction

### Objective

Extract durable entities from posts and persist them with provenance.

### New tables

Create a new migration in `backend/insight_core/db/migrations/`.

Recommended tables:

#### `entities`

Fields:

- `id UUID PK`
- `entity_type TEXT NOT NULL`
- `canonical_name TEXT NOT NULL`
- `normalized_name TEXT NOT NULL`
- `description TEXT NULL`
- `status TEXT NOT NULL DEFAULT 'active'`
- `first_seen_at TIMESTAMPTZ`
- `last_seen_at TIMESTAMPTZ`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

Add indexes:

- `(entity_type, normalized_name)`
- `last_seen_at`

#### `entity_aliases`

Fields:

- `id UUID PK`
- `entity_id UUID FK -> entities`
- `alias TEXT NOT NULL`
- `normalized_alias TEXT NOT NULL`
- `alias_type TEXT NOT NULL`
- `source_hint TEXT NULL`
- `created_at TIMESTAMPTZ`

Add unique constraint:

- `(entity_id, normalized_alias)`

#### `post_entities`

Fields:

- `post_id UUID FK -> posts`
- `entity_id UUID FK -> entities`
- `mention_text TEXT NOT NULL`
- `confidence REAL NOT NULL`
- `role TEXT NULL`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ`

Primary key can be:

- `(post_id, entity_id, mention_text)`

This is the core provenance table.

### New repository/service layer

Create:

- `backend/insight_core/db/repo_entities.py`
- `backend/insight_core/services/entities_service.py`

The pattern should follow the existing repo/service split used for posts, topics, and briefings.

Repository responsibilities:

- CRUD for `entities`
- alias lookup
- insert/update post-entity links
- lookup by canonical/normalized alias

Service responsibilities:

- resolve or create canonical entities
- merge aliases into known entities conservatively
- persist extracted mentions
- expose entity timelines later

### Extraction logic

Do not put extraction orchestration inside the API route directly.

Create a dedicated orchestration method in the service layer, for example:

- `EntitiesService.extract_entities_for_post(post_id: str, refresh: bool = False)`
- `EntitiesService.extract_entities_for_posts(post_ids: list[str])`

Use `GeminiProcessor` for the first version, but make the interface extraction-specific.

Add a new method in:

- `backend/insight_core/processors/ai/gemini_processor.py`

Expected extraction output shape:

```json
{
  "entities": [
    {
      "name": "OpenAI",
      "type": "organization",
      "aliases": ["openai"],
      "mention_text": "OpenAI",
      "confidence": 0.98,
      "role": "actor"
    }
  ]
}
```

### First entity types

Do not start with ten types.

Start with four:

- `person`
- `organization`
- `product_model`
- `project`

If the extractor is unsure, let it emit `project` rather than inventing more classes.

### Alias resolution

Use deterministic hints before AI heuristics.

Examples:

- Nitter handle strongly hints a person/org alias
- YouTube channel title can seed aliases
- RSS host and feed title can seed org/project names
- Reddit subreddit names are weak hints and should not auto-merge with confidence

Conservative rule:

- exact normalized match within same type can merge
- exact alias match with strong source hint can merge
- fuzzy merges should not happen automatically in phase 1

## Phase 2: Claims And Evidence

### Objective

Move beyond “entity mentioned in a post” to “what was asserted about that entity.”

### New tables

#### `claims`

Fields:

- `id UUID PK`
- `claim_type TEXT NOT NULL`
- `subject_entity_id UUID NULL`
- `object_entity_id UUID NULL`
- `claim_text TEXT NOT NULL`
- `normalized_claim TEXT NULL`
- `confidence REAL NOT NULL`
- `status TEXT NOT NULL DEFAULT 'observed'`
- `occurred_at TIMESTAMPTZ NULL`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

#### `claim_evidence`

Fields:

- `claim_id UUID FK -> claims`
- `post_id UUID FK -> posts`
- `stance TEXT NOT NULL`
- `evidence_snippet TEXT NULL`
- `confidence REAL NOT NULL`
- `created_at TIMESTAMPTZ`

Possible `stance` values:

- `supports`
- `contradicts`
- `mentions`

### Why this matters

Without claims, the system knows only that `OpenAI` appeared often.
With claims, the system can know:

- multiple sources reported the same launch
- one source contradicted another
- a story evolved over several days

This is where weekly briefings become materially stronger.

### Where to integrate

Do not attach claim generation to every frontend click.

Trigger extraction after ingestion, in the backend workflow, once posts are persisted.

Good integration points:

- the end of safe ingestion/full ingestion for newly inserted or updated posts
- manual backfill command for existing posts

Avoid:

- recomputing claims every time `/api/daily` or `/api/weekly` is requested

## Phase 3: Timeline And Weekly Entity Briefings

### Objective

Use entities and claims to generate week-scale memory, not just daily summaries.

### Product outputs enabled by this phase

- entity profile page
- “what changed this week about X”
- contradiction detection
- cross-source comparison
- weekly entity watchlists

### Weekly briefing evolution

Current weekly briefing can aggregate daily briefings.

Later weekly variants should be:

- `weekly_briefing/default`
  - current synthesis from daily briefings
- `weekly_briefing/entities`
  - synthesis from entities, claims, and claim evidence
- `weekly_briefing/topics`
  - weekly topic evolution timeline

Do not block the current weekly variant waiting for entity memory.

## Execution Plan For The Junior Developer

### Step 1

Read these files first:

- `backend/insight_core/services/source_fetch_service.py`
- `backend/insight_core/services/posts_service.py`
- `backend/insight_core/services/topics_service.py`
- `backend/insight_core/services/briefing_service.py`
- `backend/insight_core/services/post_detail_service.py`
- `backend/insight_core/processors/ai/gemini_processor.py`

Your job is to understand where evidence enters the system and where derived intelligence is already stored.

### Step 2

Add the migration for:

- `entities`
- `entity_aliases`
- `post_entities`

Keep the schema boring and explicit.

### Step 3

Implement `repo_entities.py` first.

Do not start with a service. Make sure you can:

- insert entity
- find by normalized alias
- add alias
- link entity to post
- fetch entities for a post

### Step 4

Implement `entities_service.py`.

This is where canonicalization belongs. Keep the repo dumb and the service smart.

### Step 5

Add one extraction entry point to `GeminiProcessor`.

Do not mix entity extraction prompts with daily briefing prompts. Keep them separate and typed.

### Step 6

Add a script or service hook that processes only new posts.

Recommended flow:

1. ingestion stores posts
2. gather inserted/updated post ids
3. run entity extraction for that batch
4. persist entities and post-entity links
5. record a job in `job_runs`

### Step 7

Add read APIs only after persistence works.

Suggested first API shapes:

- `GET /api/entities`
- `GET /api/entities/{id}`
- `GET /api/posts/item/{post_id}/entities`

Frontend can wait. The data model should be correct first.

## Common Mistakes To Avoid

### Mistake 1: building an ontology instead of a product

Do not spend days inventing entity subclasses that nobody uses.

### Mistake 2: over-merging aliases

Entity merge mistakes are expensive. Duplicates are cheaper than false merges.

### Mistake 3: dropping provenance

If you cannot show which post produced the entity or claim, the memory layer will become untrustworthy.

### Mistake 4: recomputing from scratch

Incremental extraction matters. This system is built around ongoing ingestion.

### Mistake 5: burying logic in route handlers

Keep repositories for SQL, services for domain logic, routes for transport only.

## How This Should Connect To Weekly Briefings

Short term:

- weekly briefing uses stored daily briefings

Later:

- entity memory provides recurring actors
- claims provide week-over-week changes
- claim evidence provides trustworthy citations

That means weekly intelligence can evolve from:

- “here is what the week looked like”

to:

- “here is what changed about OpenAI, Anthropic, local LLM tooling, and model release cadence, with evidence”

## Final Guidance

If you are implementing this feature, optimize for durable memory and trustworthy evidence, not clever graph demos.

INSIGHT already knows how to collect and summarize information.
Entity memory is the layer that should make it remember what mattered across time.
