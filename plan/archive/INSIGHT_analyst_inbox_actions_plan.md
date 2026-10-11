# Analyst Inbox + Actions Implementation Plan

## Purpose

This document is for the future engineer who will implement the **Analyst Inbox + Actions** layer in INSIGHT while working directly with **OpenAI Codex**.

The goal is to give the user a **human-controlled daily work surface** where the system proposes what matters and the analyst decides what to keep, reject, save, escalate, or ignore.

INSIGHT should not become an opaque autonomous feed.
It should become a **second brain with an explicit control loop**.

If you remember only one sentence from this document, remember this:

**The inbox is where the system proposes, the human decides, and those decisions become durable product memory.**

## Why We Are Building This

Without an analyst inbox, later features will increase intake volume but not reduce effort.

Examples:

- stories can exist, but the user still has to hunt through many items manually
- monitors can surface more matches, but they may only create more noise
- source discovery can expand coverage, but the user may lose control
- notes and memory can grow, but no deliberate triage loop exists

This feature exists because INSIGHT must remain **human-controllable** unless the system becomes extraordinarily reliable.
At the current stage, the correct model is:

- the system ranks and explains
- the analyst confirms or corrects
- the product learns from explicit decisions, not hidden behavioral drift

This is the leverage feature that turns processing into workflow.

## Why We Choose This Method

We are deliberately not building an infinite scrolling feed driven by silent personalization.

We are choosing an **inbox + explicit actions** model because it is:

1. more trustworthy
2. more controllable
3. easier to debug
4. closer to real analyst workflows
5. a better training surface for later automation

Why this method is correct:

- it reduces cognitive load by turning streams into bounded queues
- it records why something was surfaced
- it captures analyst decisions in a durable, auditable way
- it supports later monitor tuning and source controls without hidden algorithm drift
- it fits the “second brain” goal better than another social-style feed

## Where This Feature Fits In The Roadmap

This feature should come **after Evidence Foundation** and ideally **after Stories**, because the inbox becomes much better when it can surface durable developments instead of only raw posts.

However, the inbox should be designed so it can start thin:

- first on top of posts and obvious story candidates
- later on top of stories, entity/event updates, contradictions, and monitor hits

This feature is the missing control surface before large-scale Monitors / Watchlists / Discovery.

## How To Think About INSIGHT

Before writing code, understand the current and near-future layers:

- `posts`
  - raw evidence
- `topics`
  - daily grouping
- `entities` / `events`
  - durable memory about actors and developments
- `stories`
  - durable development objects across time
- `briefings`
  - rendered synthesis

The mistake a junior engineer is likely to make is this:

- building the inbox as a feed of copied summaries
- hiding ranking logic in the frontend
- letting user reactions silently retrain ranking
- making actions mutate state without an audit trail
- assuming the inbox is just a nicer list of posts

Do not do that.

The correct mental model is:

- `inbox item` = a proposal for analyst attention
- `target object` = the thing the analyst may act on, such as a post, story, event, contradiction, or monitor hit
- `action` = an explicit recorded human decision
- `inbox batch` = a generated queue for a time window and scope
- `analyst inbox` = the control surface where ranking, explanation, and correction meet

## Product Outcome

When this feature is done well, the analyst should be able to answer:

- Why am I seeing this?
- Is this genuinely new or just duplicated noise?
- What action can I take right now?
- What did I already decide about similar items?
- Which source or story should be promoted, ignored, or watched?
- Can the system remember my explicit decisions without becoming opaque?

That means the product should support:

- a ranked queue of candidate items
- explanation of ranking factors
- a small set of high-value actions
- persistent action logging
- item status transitions
- filters and scopes
- later: direct handoff to notes, watchlists, and story correction

## Design Principles

### 1. Human decision is primary

The system proposes.
The user decides.

Do not let the product silently override human control because of inferred preference.

### 2. Every surfaced item needs an explanation

The analyst should be able to see why an item was surfaced.

Examples:

- intersects a watched entity
- high novelty
- strong evidence update in a story
- contradiction detected
- trusted source
- low duplication penalty

Do not show a mysterious score with no explanation.

### 3. Actions must be durable and auditable

Every meaningful action must be stored as a first-class record.

Examples:

- accepted
- rejected as noise
- saved
- snoozed
- promoted anchor
- blocked source
- lowered source priority
- created monitor from this item

Do not hide these actions inside transient UI state.

### 4. Inbox items should point to durable objects, not duplicate them

The inbox is not the data model.
It is a control surface over the data model.

An inbox item should reference a post, story, event, or other object.
Do not create detached copies of summaries that drift from the source object.

### 5. Ranking should be explicit and mostly deterministic at first

Start with a weighted, explainable ranking formula.

Do not start with black-box personalization.

### 6. Keep the action set small in phase 1

A small set of useful actions is better than a giant menu nobody trusts.

### 7. Avoid addictive feed mechanics

This is not a social feed.
It is a work queue.

Bound the queue, support status transitions, and preserve analyst calm.

## Recommended Data Model

Create a dedicated migration in:

- `backend/insight_core/db/migrations/`

Do not hide inbox state in `briefings.metadata` or ad hoc UI storage.

### `inbox_batches`

Represents a generated queue for a time window and scope.

Suggested fields:

- `id UUID PK`
- `scope_type TEXT NOT NULL`
- `scope_value TEXT NULL`
- `generated_for_date DATE NULL`
- `status TEXT NOT NULL DEFAULT 'ready'`
- `item_count INTEGER NOT NULL DEFAULT 0`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Examples of `scope_type`:

- `global`
- `source_bundle`
- `watchlist`
- `story_review`
- `daily_queue`

Start simple.
A single-user product can begin with `global` or `daily_queue`.

### `inbox_items`

Represents one surfaced proposal for analyst attention.

Suggested fields:

- `id UUID PK`
- `batch_id UUID REFERENCES inbox_batches(id)`
- `target_type TEXT NOT NULL`
- `target_id UUID NOT NULL`
- `status TEXT NOT NULL DEFAULT 'pending'`
- `priority_score REAL NOT NULL DEFAULT 0`
- `novelty_score REAL NOT NULL DEFAULT 0`
- `evidence_score REAL NOT NULL DEFAULT 0`
- `duplication_penalty REAL NOT NULL DEFAULT 0`
- `source_priority_score REAL NOT NULL DEFAULT 0`
- `reason_summary TEXT NULL`
- `reasons JSONB NOT NULL DEFAULT '[]'`
- `surfaced_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `acted_at TIMESTAMPTZ NULL`
- `metadata JSONB NOT NULL DEFAULT '{}'`

Recommended indexes:

- `batch_id`
- `status`
- `target_type`
- `priority_score DESC`

Examples of `target_type`:

- `post`
- `story`
- `event`
- `story_update`
- `contradiction`
- `monitor_hit`

For phase 1, start with:

- `post`
- `story`

### `analyst_actions`

Durable audit log of human decisions.

Suggested fields:

- `id UUID PK`
- `inbox_item_id UUID NULL REFERENCES inbox_items(id)`
- `target_type TEXT NOT NULL`
- `target_id UUID NOT NULL`
- `action_type TEXT NOT NULL`
- `actor_id TEXT NULL`
- `payload JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Recommended indexes:

- `target_type, target_id`
- `action_type`
- `created_at`

Suggested `action_type` values for phase 1:

- `accept`
- `reject_noise`
- `save`
- `snooze`
- `block_source`
- `lower_source_priority`
- `promote_anchor`
- `attach_to_story`
- `dismiss_duplicate`

Do not implement every action on day one.
The audit table should support them even if the UI exposes only a subset first.

### Optional Later: `analyst_saved_items`

Do not block the inbox on this table.

Later you may want a separate table or notebook/collection layer for:

- saved insights
- pinned stories
- linked notes
- personal research threads

For phase 1, a `save` action in `analyst_actions` is enough.

## Recommended Code Layout

Follow the existing repo/service split already used in INSIGHT.

Create:

- `backend/insight_core/db/repo_inbox.py`
- `backend/insight_core/services/inbox_service.py`
- `backend/insight_core/services/analyst_actions_service.py`

Optionally add a small ranking policy module:

- `backend/insight_core/services/inbox_ranking.py`

Do not bury ranking rules in the frontend.

### Repository responsibilities

- create/read inbox batches
- create/read/update inbox items
- insert analyst actions
- fetch queue views and filters
- update item status after actions
- retrieve prior actions for a target

### Service responsibilities

- generate inbox candidates
- score and rank candidates
- build explanation payloads
- persist batches and items
- apply actions and trigger side effects safely
- prevent duplicate inbox items for the same target within a batch

### Processor responsibilities

Avoid LLM dependence in phase 1.

The inbox should use existing structured outputs where possible:

- story updates
- evidence signals
- source settings
- novelty signals
- contradiction flags later
- monitor hits later

If you later use a model, use it for a narrow explanation or disambiguation task, not for core ranking.

## What Should Surface In The Inbox

The inbox should not surface everything.
It should surface **proposals worthy of analyst attention**.

Good initial candidate types:

- newly created stories
- materially updated stories
- posts with strong novelty but no story yet
- posts from highly important sources
- ambiguous duplicates needing review later
- source-of-truth promotion candidates

Later candidate types:

- contradiction candidates
- watchlist hits
- new source discovery suggestions
- entity spikes
- source drift or trust warnings

## Recommended Ranking Method

Start with a small explainable formula.

Example ingredients:

- novelty score
- evidence quality score
- story materiality score
- source priority score
- contradiction score later
- duplication penalty
- already-seen penalty
- recency factor

Examples of features that can contribute positively:

- first appearance of a story
- strong anchor artifact
- official source or highly valued source
- large material change inside a story timeline
- direct intersection with a watch target later

Examples of features that should penalize:

- near duplicate of already surfaced item
- weak derivative commentary
- already acted upon similar item recently
- low evidence confidence

Store the components in structured form.
Do not store only the final score.

## How Actions Should Work

An action should do two things:

1. create an immutable audit record
2. trigger controlled side effects when appropriate

Examples:

### `accept`

Meaning:

- this item deserved analyst attention

Possible side effects:

- mark inbox item as accepted
- raise confidence that this story/source combination matters
- optionally create or update a saved record later

### `reject_noise`

Meaning:

- this item should not have been surfaced in this form

Possible side effects:

- mark inbox item as rejected
- suppress similar duplicates in the same batch
- record useful review data for later ranking adjustments

### `save`

Meaning:

- preserve this as part of the user's working memory

Possible side effects:

- mark item saved
- later add to notebook/collection layer

### `snooze`

Meaning:

- defer without losing it

Possible side effects:

- change item status
- resurface later if still relevant

### `block_source` / `lower_source_priority`

Meaning:

- update explicit source control, not hidden personalization

Possible side effects:

- adjust source settings
- affect future batch generation transparently

### `promote_anchor`

Meaning:

- human overrides story anchor/source selection

Possible side effects:

- update story anchor state
- log the correction visibly

Do not let side effects happen invisibly.
They should be explicit and inspectable.

## Phase Plan

Implement this in phases.
Do not start with a giant workspace.

### Phase 1: Core Inbox Over Existing Objects

Objective:

- generate one bounded analyst queue over posts and stories

Start with candidates from:

- new stories if stories exist
- materially updated stories if stories exist
- otherwise recent posts passing a novelty threshold

Store:

- batch
- ranked items
- explanation payloads
- item status

Expose a minimal read API.

### Phase 2: Actions and Audit Trail

Objective:

- let the analyst make real decisions

Add a minimal action set:

- accept
- reject_noise
- save
- snooze
- block_source

Persist all actions in `analyst_actions`.

Update item status from actions.
Do not leave actions as frontend-only events.

### Phase 3: Ranking Explanations and Filters

Objective:

- make the queue trustworthy and navigable

Add:

- explicit reason summaries
- score component display
- filters by status, target type, source, date
- “why am I seeing this?” support

### Phase 4: Story and Source Corrections

Objective:

- connect inbox actions to durable product corrections

Add higher-value actions:

- promote anchor
- attach post to story
- dismiss duplicate
- lower source priority
- later: merge story, split story

These actions should update the durable objects and log the decision.

### Phase 5: Handoff To Monitors and Second-Brain Layers

Objective:

- turn analyst actions into leverage

Later actions can create or update:

- watchlists
- source bundles
- saved collections
- linked notes
- research threads

Do not block the core inbox on these features.

## Suggested APIs

Start read-first and action-focused.

Suggested first routes:

- `GET /api/inbox`
- `GET /api/inbox/batches`
- `GET /api/inbox/items/{item_id}`
- `POST /api/inbox/rebuild`
- `POST /api/inbox/items/{item_id}/actions`
- `GET /api/inbox/actions`

Later:

- `POST /api/inbox/items/{item_id}/promote-anchor`
- `POST /api/inbox/items/{item_id}/block-source`
- `POST /api/inbox/items/{item_id}/create-watchlist`

Do not build all routes at once.
The minimum loop is: generate queue -> inspect item -> take action -> persist action.

## UI Order

Do not start with a giant intelligence dashboard.

### 1. Inbox page

Show:

- bounded ranked queue
- item type
- short explanation
- status
- priority
- quick actions

### 2. Item detail drawer or page

Show:

- linked post/story
- evidence summary
- why this surfaced
- prior actions on this target
- quick correction actions

### 3. Action history view

Show:

- what was accepted, rejected, saved, snoozed
- when
- on which target

This is important for trust.

## How This Connects To Other Features

### Connection to Evidence Foundation

- inbox ranking needs duplicate penalties
- source controls need normalized evidence
- explanations are better when evidence relations are reliable

### Connection to Stories

- the best inbox object is often a story or story update, not a raw post
- promote-anchor actions depend on story state
- story-aware inboxes reduce overload more effectively

### Connection to Entities and Events

- entity/event signals can later improve ranking and explanation
- watch intersections become more meaningful
- novelty can be computed at the entity/event layer later

### Connection to Monitors / Watchlists

- monitor hits should eventually surface through the inbox
- actions on monitor hits should update explicit user controls, not hidden ranking
- the inbox is the control loop that prevents monitors from becoming another firehose

### Connection to Second-Brain / Notes

- accepted and saved items should later flow into collections and notes
- the inbox is intake; the notebook is retention and reflection

## Execution Plan For The Junior Engineer

You are working with OpenAI Codex.
Do not ask Codex to build the whole inbox in one shot.

### Step 1

Inspect the current codebase first.

Read these areas before changing code:

- current story/entity/event service files if they exist
- current post detail service and any note/tag/chat flows
- existing route patterns for read/write endpoints
- any repo modules for job runs, posts, or future story state
- existing source settings logic if present

Your first job is to understand which durable objects the inbox can point to today.

### Step 2

Add the migration first.

Create explicit tables for:

- `inbox_batches`
- `inbox_items`
- `analyst_actions`

Do not store the queue only in cache or memory.

### Step 3

Implement `repo_inbox.py`.

Make sure you can:

- create a batch
- insert ranked items
- fetch queue views
- update item status
- insert analyst action
- fetch prior actions for a target

### Step 4

Implement ranking as a small explicit policy.

Do not hide weights across the codebase.
Keep one place where the phase 1 ranking formula is defined.

### Step 5

Implement `inbox_service.py`.

This service should orchestrate:

- candidate collection
- scoring
- explanation generation
- batch/item persistence
- rebuild operations

### Step 6

Implement `analyst_actions_service.py`.

This service should:

- validate the action
- write the audit record
- update item status
- apply controlled side effects
- keep the behavior transparent

### Step 7

Add tests before UI work.

You need tests for:

- score ordering in simple cases
- duplicate suppression within one batch
- action logging
- item status transitions
- source block / source priority side effects if implemented

### Step 8

Add minimal read and action APIs.

Only after the persistence and action logic is correct should you add UI.

## Codex Prompting Guidance

Do not tell Codex:

- “build analyst inbox”

Tell Codex something like this instead:

1. inspect the current durable objects and service boundaries
2. propose the smallest viable inbox data model
3. add the migration for `inbox_batches`, `inbox_items`, and `analyst_actions`
4. implement `repo_inbox.py`
5. add tests for item persistence and action logging
6. stop and summarize changes

Then continue with a second prompt for the service layer and a third for the API routes.

Small bounded prompts are safer and easier to review.

## Common Failure Modes

### Failure 1: The inbox becomes another feed

Cause:

- surfacing too many items with no bounded queue or status model

Fix:

- keep batches bounded and track item states

### Failure 2: Ranking becomes opaque

Cause:

- storing a final score without explanation

Fix:

- persist reason summaries and score components

### Failure 3: Actions are not durable

Cause:

- relying on frontend state or ephemeral events

Fix:

- use `analyst_actions` as the audit source of truth

### Failure 4: Hidden personalization drift

Cause:

- silently changing ranking based on clicks without explicit user controls

Fix:

- limit phase 1 changes to explicit actions and transparent source settings

### Failure 5: Too many actions too early

Cause:

- trying to implement every possible correction in phase 1

Fix:

- start with a small action set and expand later

### Failure 6: Inbox items duplicate underlying objects

Cause:

- copying summaries and data into the inbox instead of referencing the target object

Fix:

- keep inbox items as pointers plus explanation state

## First Practical Milestone

The first milestone should be intentionally narrow.

Target:

- generate one daily inbox batch
- surface a bounded set of post/story items
- attach explanations for why each item surfaced
- allow the user to accept, reject, save, snooze, or block source
- persist every action
- display item status correctly after action

If that works, INSIGHT has crossed the threshold from:

- “information system with summaries”

to:

- “human-controlled intelligence workflow”

## Final Milestone

This feature is complete enough for the next layer when:

- the user can process the day from one inbox instead of scanning raw sources
- every surfaced item has a visible reason
- actions are durable and auditable
- source-control actions affect future queue generation transparently
- the inbox can later accept monitor hits, story updates, and second-brain saves without redesign

At that point, Monitors / Watchlists / Discovery can be added without turning INSIGHT into a louder firehose.

## Final Advice To The Junior Engineer

Do not optimize for clever ranking.

Optimize for calm, trust, and control.

If the analyst cannot answer “why did this surface, what can I do with it, and will the system remember my decision correctly?” the inbox is not done.
