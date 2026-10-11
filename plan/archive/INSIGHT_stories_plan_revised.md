# INSIGHT Stories Implementation Plan (Revised)

## Audience

This document is written for a junior software engineer who will implement the Stories layer in INSIGHT while working directly with OpenAI Codex.

The goal is to make the work easy to execute in small, safe steps.

This is not a research essay. It is a build plan.

---

## Why We Are Building Stories

Right now INSIGHT can:

- ingest posts from many sources
- group posts into daily topics
- render briefings from those daily groupings

That is useful, but it still leaves the analyst doing too much mental work.

The analyst still has to answer these questions manually:

- what actually happened?
- which post is the best anchor for the development?
- which posts are just commentary, reaction, or reposts?
- is this the same development as yesterday, or a new one?
- what changed over time?

Stories solve that problem.

A story is the durable object for one real-world development across time.

Examples:

- `OpenAI` is an entity
- `GPT-5.4 mini` is an entity
- `OpenAI released GPT-5.4 mini` is a story
- `people are debating the release` is commentary attached to that story

### Product motivation

We are building Stories because the product should help the human spend less time re-reading the same development through many derivative posts.

The main user value is:

- one durable object per development
- one best current anchor post
- supporting evidence grouped by role
- a timeline of what changed
- a better weekly briefing built from durable developments, not only daily clusters

If this feature works, the user should move from reading a stream of posts to working on a set of stable developments.

---

## Why We Are Choosing This Method

We are **not** choosing a pure embedding-clustering approach.

We are **not** trying to ask one model to cluster the entire corpus into perfect stories.

We are **not** hiding story state inside `topics.metadata`.

We are choosing an evidence-first and correction-friendly approach because:

1. **News is noisy and duplicated**.
   Different sites repost the same release, press statement, paper, or rumor.

2. **A story must survive across days**.
   Daily topics are temporary; stories must be durable.

3. **There is not always one true source-of-truth post**.
   In intelligence workflows, there is often a **best current anchor** plus corroboration and commentary. The system must allow uncertainty.

4. **Humans must be able to correct the system later**.
   A bad merge or a bad anchor choice must be fixable.

5. **Cheap signals should narrow the problem before AI**.
   URLs, artifact links, time windows, title overlap, entity overlap, and source type should do most of the narrowing. LLM calls should resolve ambiguity, not replace the entire pipeline.

### Important terminology change

In the previous plan, the field was called `source_of_truth_post_id`.

For implementation, prefer the term:

- `anchor_post_id`

Why:

- it is more honest
- it handles uncertainty better
- it still gives the user one preferred entry point into the story
- it leaves room for later multi-anchor stories

In the UI, you can still display:

- “Primary Source”
- “Best Available Source”
- “Anchor Post”

But in the data model, `anchor_post_id` is the safer concept.

---

## Where We Are Going

This feature is not just about grouping posts.

It is the bridge from:

- daily intake and summaries

to:

- durable analyst objects
- evidence-first investigation
- story timelines
- better weekly and monthly briefings
- later user actions such as merge, split, promote anchor, and remove irrelevant commentary

Long-term, the product direction should look like this:

1. **Posts** are evidence
2. **Entities** tell us who/what is involved
3. **Stories** tell us what happened
4. **Story updates** tell us what changed over time
5. **Analyst actions** make the system compound instead of reset every day

Stories should become one of the core product objects, not an afterthought.

---

## Foundations Required Before Deeper Story Logic

Do not start by writing the full Stories pipeline immediately.

The story layer will be weak if the evidence layer is missing basic normalization.

### Foundation requirements

Before or alongside story work, make sure `posts` has enough normalized data for cheap narrowing:

- `canonical_url` or equivalent normalized final URL
- `language_code`
- `published_at`
- `title`
- `content_hash` or normalized text hash
- `source_id`
- optional short pivot summary for multilingual matching later

### Strongly recommended foundation tables

#### `post_relations`

Use this to represent relationships such as:

- `near_duplicate`
- `same_story_candidate`
- `translation_of`
- `syndicated_from`
- `quotes`
- `references`

This does **not** replace Stories.
It reduces noise before story resolution.

#### `post_artifacts`

If a post links to a strong primary artifact, store it.
Examples:

- release notes URL
- changelog URL
- GitHub release URL
- paper URL / DOI
- company blog post URL
- official announcement thread URL

Why this matters:

Many stories are easier to resolve by shared artifact than by shared text.

If five posts all discuss the same release note or the same paper, that is a much stronger signal than title similarity.

### Dependency on entities

Stories can start before the entity system is perfect.

But if entity mentions already exist, use them as a narrowing signal.
Entity overlap is helpful; entity perfection is not required.

---

## Core Design Principles

### 1. Provenance is mandatory

Every story must be backed by concrete posts.

No free-floating story summaries.

### 2. Anchor selection is not fake certainty

The system should choose one best current anchor, but store confidence and reasons.

### 3. Stories are event-level, not entity-level

Do not create one giant story for “OpenAI” or “AI industry.”
A story must describe one specific development.

### 4. Incremental processing only

Process new and recently changed posts.
Do not rebuild all stories on every request.

### 5. Conservative merge policy

Duplicate stories are cheaper than incorrect merges.

### 6. Human correction must be possible

The system must later support:

- merge stories
- split stories
- promote a different anchor post
- remove bad attachments
- mark a story as irrelevant

### 7. Start operational, not theoretical

Do not build a huge story ontology first.
Start with enough structure to drive the product.

---

## Recommended Data Model

Create a dedicated migration in:

- `backend/insight_core/db/migrations/`

Do not hide story state inside topic metadata.

### `stories`

Durable object for one real-world development.

Suggested fields:

- `id UUID PK`
- `canonical_title TEXT NOT NULL`
- `canonical_summary TEXT NULL`
- `story_kind TEXT NOT NULL DEFAULT 'other'`
- `status TEXT NOT NULL DEFAULT 'active'`
- `anchor_post_id UUID NULL REFERENCES posts(id)`
- `anchor_confidence REAL NOT NULL DEFAULT 0`
- `first_seen_at TIMESTAMPTZ NULL`
- `last_seen_at TIMESTAMPTZ NULL`
- `created_by_method TEXT NOT NULL DEFAULT 'auto'`
- `resolution_version TEXT NULL`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Recommended indexes:

- `(status, last_seen_at)`
- `story_kind`
- `anchor_post_id`
- `first_seen_at`
- `last_seen_at`

#### Notes

- `created_by_method` lets you distinguish automatic creation from manual corrections later.
- `resolution_version` helps when you improve prompts or heuristics and need to backfill.

### `story_posts`

Join table between stories and posts.

Suggested fields:

- `story_id UUID NOT NULL REFERENCES stories(id)`
- `post_id UUID NOT NULL REFERENCES posts(id)`
- `role TEXT NOT NULL`
- `relevance_score REAL NOT NULL DEFAULT 0`
- `anchor_score REAL NOT NULL DEFAULT 0`
- `is_anchor_candidate BOOLEAN NOT NULL DEFAULT FALSE`
- `evidence_weight REAL NOT NULL DEFAULT 0`
- `added_by_method TEXT NOT NULL DEFAULT 'auto'`
- `added_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `metadata JSONB NOT NULL DEFAULT '{}'`

Primary key:

- `(story_id, post_id)`

Recommended roles for phase 1:

- `anchor`
- `corroboration`
- `commentary`
- `reaction`
- `follow_up`
- `contradiction`
- `duplicate`
- `context`

#### Why this schema

Do not store only one anchor and nothing else.
The story needs a ranked evidence set around the anchor.

### `story_updates`

This is the timeline table.

Use `story_updates` instead of `story_events` because the meaning is clearer for junior engineers.

Suggested fields:

- `id UUID PK`
- `story_id UUID NOT NULL REFERENCES stories(id)`
- `update_date DATE NOT NULL`
- `title TEXT NOT NULL`
- `summary TEXT NOT NULL`
- `importance_score REAL NOT NULL DEFAULT 0`
- `created_by_method TEXT NOT NULL DEFAULT 'auto'`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Recommended indexes:

- `(story_id, update_date)`
- `(update_date, importance_score)`

#### Why `story_updates` is better than `story_events`

Because in implementation, what you are really storing is:

- what changed for this story on a date

That is easier to reason about than the more abstract word “event.”

### `story_update_posts`

Join table between updates and evidence posts.

Suggested fields:

- `story_update_id UUID NOT NULL REFERENCES story_updates(id)`
- `post_id UUID NOT NULL REFERENCES posts(id)`
- `role TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Primary key:

- `(story_update_id, post_id)`

### Later, not in phase 1

#### `story_links`

Possible link types:

- `continuation_of`
- `same_as`
- `supersedes`
- `contradicts`

Do not implement this first.

#### `story_actions`

This will later store manual changes such as:

- promoted anchor
- merged story
- split story
- removed post

This is valuable, but it should not block the first milestone.

---

## Recommended Code Layout

Follow the repo/service split already used in INSIGHT.

Create:

- `backend/insight_core/db/repo_stories.py`
- `backend/insight_core/services/stories_service.py`

Optionally later:

- `backend/insight_core/services/story_briefing_service.py`

### Repository responsibilities

Keep the repository boring.

It should handle:

- create/read/update stories
- attach posts to stories
- update anchor fields
- create/read/update story updates
- fetch recent candidate stories for resolution
- fetch story detail payloads for APIs

### Service responsibilities

Keep the service smart.

It should handle:

- candidate generation from new posts
- narrowing by cheap heuristics
- anchor ranking
- role classification
- matching against existing stories
- deciding whether to create a new story or update an existing one
- generating a daily story update when something materially changed

### Processor responsibilities

Extend `backend/insight_core/processors/ai/gemini_processor.py`, but keep orchestration outside the processor.

Good processor tasks:

- rank anchor candidates when heuristics are inconclusive
- classify post role inside a candidate story
- judge whether a candidate belongs to an existing story
- summarize what changed for a story on a date

Bad processor task:

- “Here are 4,000 posts, invent the stories.”

---

## Story Pipeline

The story pipeline should run after ingestion, not during page render.

Recommended high-level flow:

1. ingestion stores new/updated posts
2. normalize URLs / hashes / language / artifact links
3. detect story candidates from the new batch
4. rank anchor candidates inside each candidate cluster
5. compare each candidate cluster to recent stories
6. attach to existing story or create new story
7. generate or update one `story_update` for that date if something materially changed
8. record a `job_runs` entry with counts and sample IDs

This keeps story logic incremental and debuggable.

---

## Development Roadmap

Build this in narrow milestones.

### Milestone 0 — Foundations and observability

#### Objective

Make story work possible and measurable.

#### Why now

Without normalized URLs, hashes, and job logging, story quality will be poor and hard to debug.

#### Work

- ensure `posts` has the required normalized fields
- add `post_relations` if it does not exist yet
- add `post_artifacts` if feasible
- add `job_runs` types for story processing

#### Deliverable

The system can show, for a set of posts, which ones are near-duplicates or share strong artifacts.

#### Stop condition

Do not move on until you can inspect and debug the evidence layer.

---

### Milestone 1 — Persistent story storage

#### Objective

Add durable story tables and repository methods.

#### Work

1. add migrations for:
   - `stories`
   - `story_posts`
   - `story_updates`
   - `story_update_posts`
2. implement `repo_stories.py`
3. add unit tests for basic CRUD and joins

#### Deliverable

You can create a story, attach posts, assign an anchor, create story updates, and fetch a story with attached evidence.

#### Important note for Codex

Use Codex for one small task at a time:

- first migration
- then repository
- then tests

Do not ask Codex to implement the full feature in one prompt.

---

### Milestone 2 — Candidate detection with cheap heuristics

#### Objective

Find small clusters of posts that likely describe the same development.

#### Why this method

This reduces token cost and avoids sending every post pair to the model.

#### Required heuristics

Start with these:

- shared canonical URL
- shared artifact URL
- strong title overlap
- near-duplicate relation
- close publication window
- shared key entities if available
- explicit linking or quoting of the same primary post

#### Deliverable

For a batch of new posts, the service can produce candidate clusters plus a shortlist of anchor candidates.

#### Success metric

The output should be noisy but useful. It only needs to narrow the search space.

---

### Milestone 3 — Anchor selection and role classification

#### Objective

Choose the best current anchor and classify the other posts around it.

#### Why this matters

This is the first moment where the product becomes helpful to the analyst.

#### Deterministic rules first

Prefer these before asking Gemini:

- official domain > commentary domain
- linked primary artifact > post discussing an artifact without linking it
- original thread > repost
- changelog / paper / release notes / official announcement > social reaction
- fuller factual post > vague reaction

#### When to call Gemini

Only when two or more candidates remain plausible.

#### Deliverable

For one candidate cluster, the system can:

- choose an anchor post
- assign roles to the rest
- store confidence and reason metadata

#### Success metric

When a human opens the story, the chosen anchor should feel believable.

---

### Milestone 4 — Resolution against existing stories

#### Objective

Prevent the system from creating duplicate stories every day.

#### Why this is the hardest step

A junior implementation will often cluster today correctly and still fail to maintain stable story IDs across time.

#### Resolution signals

Compare candidate clusters to recent stories using:

- existing anchor post URL
- shared artifact URLs
- entity overlap
- title/summary similarity
- attached post overlap
- temporal continuity

#### Merge policy

Be conservative.

If confidence is low:

- create a new story
- mark it as possible duplicate later

#### Deliverable

The same story should persist across multiple days when new evidence arrives.

#### Success metric

On a one-week test set, obvious repeated developments should mostly reuse the same story ID.

---

### Milestone 5 — Story updates timeline

#### Objective

Track what changed for a story on each date.

#### Why this matters

Without updates, stories become static buckets of posts.

#### Rule

Do not create a new update for every attached post.
Only create a `story_update` when the day contains a material change.

Examples of material change:

- new official announcement
- new benchmark/result/paper
- contradiction from another trusted source
- user-visible release/patch/decision
- follow-up confirmation or rollback

#### Deliverable

A story detail view can show:

- anchor
- supporting posts by role
- one update per date when something actually changed

#### Success metric

The timeline reads like a development history, not a spam log.

---

### Milestone 6 — Story-aware weekly briefing

#### Objective

Upgrade weekly output from “merged daily summaries” to “durable development intelligence.”

#### Why this matters

This is where users directly feel the value of Stories.

#### Output priorities

Weekly story briefings should emphasize:

- new stories
- materially updated stories
- contradictory or disputed stories
- stories with strong anchor evidence
- stories involving watchlist entities later

#### Deliverable

A weekly view can render story cards with:

- canonical title
- anchor post
- short summary
- update timeline
- supporting evidence counts by role

#### Final milestone

INSIGHT can ingest a week of posts and produce a story-aware weekly view where a user can answer:

- what happened?
- what was the best anchor?
- what changed during the week?
- which posts were commentary vs corroboration?

That is the point where Stories become a real product layer, not just a schema.

---

## API Roadmap

Keep APIs read-first.

### Phase 1 APIs

- `GET /api/stories`
- `GET /api/stories/{story_id}`
- `GET /api/stories/{story_id}/timeline`
- `GET /api/posts/item/{post_id}/story`
- `POST /api/stories/rebuild-for-date`
- `POST /api/stories/{story_id}/refresh`

### Later correction APIs

- `POST /api/stories/{story_id}/promote-anchor`
- `POST /api/stories/{story_id}/merge`
- `POST /api/stories/{story_id}/split`
- `POST /api/stories/{story_id}/remove-post`

Do not build all correction APIs before the read path works.

---

## UI Order

Do not start with a giant stories dashboard.

### 1. Post detail page

Add:

- connected story
- role inside story
- anchor badge if applicable

### 2. Weekly briefing page

Add:

- story cards
- anchor post callout
- timeline preview

### 3. Story detail page

Show:

- canonical title
- canonical summary
- anchor post
- supporting posts grouped by role
- timeline of updates
- connected entities later

This order makes debugging much easier.

---

## How Stories Interact With Entities

Entities answer:

- who or what is involved

Stories answer:

- what happened

Recommended path:

1. extract entity mentions from posts
2. use entity overlap only as one story-resolution signal
3. later attach aggregated entities to stories if needed

Do not wait for perfect entity memory before starting Stories.
But do not confuse entity recurrence with event identity.

---

## How Stories Interact With Topics

Topics remain useful.

Topics are the daily working layer.
Stories are the durable layer.

Recommended relationship:

- one topic can contribute posts to multiple stories
- one story can receive posts from multiple topics across multiple days

Do not force a 1:1 mapping.

---

## Prompting Guidance For GeminiProcessor

Keep prompts narrow and typed.

Good tasks:

- choose the best anchor among 3 candidates
- classify the role of 6 posts relative to an anchor
- decide whether a new candidate cluster belongs to an existing story
- summarize what changed for a story on a date

Bad tasks:

- “cluster this entire corpus into stories”
- “figure out everything from scratch”

### Example output shapes

#### Anchor ranking

```json
{
  "anchor_post_id": "uuid",
  "confidence": 0.87,
  "reason": "Official announcement with direct release notes link"
}
```

#### Role classification

```json
{
  "posts": [
    {
      "post_id": "uuid",
      "role": "commentary",
      "confidence": 0.81,
      "reason": "Discusses the release but is not the original announcement"
    }
  ]
}
```

#### Story update summary

```json
{
  "update_date": "2026-03-21",
  "title": "Vendor published follow-up patch notes",
  "summary": "The story materially changed because the vendor clarified the issue scope and released a patch.",
  "importance_score": 0.78
}
```

---

## Job Runs / Observability

Story work will fail silently if not instrumented.

Recommended `job_runs` types:

- `story_candidate_detection`
- `story_anchor_selection`
- `story_resolution`
- `story_update_generation`
- `weekly_story_briefing`

Recommended metadata:

- `batch_post_count`
- `candidate_cluster_count`
- `new_story_count`
- `updated_story_count`
- `anchor_promoted_count`
- `possible_duplicate_count`
- `estimated_tokens`
- `sample_story_ids`
- `resolution_version`

---

## Evaluation Plan

Do not trust vibes. Measure story quality.

### Evaluation set 1 — Anchor accuracy

Create a manually reviewed set of candidate clusters.
Measure:

- was the selected anchor acceptable?
- was a better anchor present?

### Evaluation set 2 — Story persistence

Use a 7-day window.
Measure:

- duplicate story rate
- false merge rate
- % of recurring developments that keep the same story ID

### Evaluation set 3 — Timeline usefulness

For each story, ask:

- does the timeline show only material changes?
- is it readable by a human?

### Evaluation set 4 — Weekly product value

Compare:

- weekly briefing from daily topics only
- weekly briefing from stories
- hybrid weekly briefing

Judge on:

- clarity
- novelty
- trust
- actionability

---

## Common Mistakes To Avoid

### Mistake 1 — treating every day as new

If you only cluster the current batch, you will create duplicate stories constantly.

### Mistake 2 — letting commentary outrank the anchor

This usually happens when social posts are more verbose than official sources.

### Mistake 3 — building story logic inside routes

Keep routes thin. Put logic in services.

### Mistake 4 — hiding uncertainty

Store confidence and reasons. A false certainty is worse than an honest provisional assignment.

### Mistake 5 — using embeddings as the entire solution

Embeddings can help retrieve candidates, but they should not become the only truth layer for story identity.

### Mistake 6 — making the timeline too noisy

A timeline of every attached post is not a timeline. It is spam.

### Mistake 7 — asking Codex to do too much at once

Codex performs much better when asked for one tightly scoped implementation step.

---

## How To Work With OpenAI Codex On This Feature

When using Codex, split work into small prompts.

Good sequence:

1. “Add migration for `stories`, `story_posts`, `story_updates`, `story_update_posts`.”
2. “Add repository methods with tests.”
3. “Add service skeleton and typed method stubs.”
4. “Implement heuristic candidate detection only.”
5. “Implement anchor ranking rules only.”
6. “Add GeminiProcessor method for tie-breaking only.”
7. “Expose read APIs.”

Bad sequence:

- “Implement the entire Stories feature end-to-end.”

### Rule for the junior engineer

After every Codex-generated step:

- run tests
- inspect migrations manually
- inspect SQL indexes manually
- verify service boundaries manually
- read any prompt text manually before shipping

Codex should accelerate implementation, not replace judgment.

---

## Final Milestone

The Stories feature is complete enough for version 1 when all of the following are true:

1. New posts are incrementally resolved into durable stories.
2. Each story has a believable best current anchor post.
3. Supporting posts are attached with useful roles.
4. Story IDs remain stable across multiple days for recurring developments.
5. Story timelines show only material changes.
6. Weekly briefings can render story cards with anchor evidence and timeline summaries.
7. A human can open a story and quickly answer:
   - what happened?
   - what is the best anchor?
   - what changed?
   - what evidence supports or comments on it?

If those conditions are not true, the feature is not done yet.

---

## Final Advice To The Junior Engineer

Do not try to impress with novelty.

The best Stories implementation is the one that is:

- stable
- evidence-backed
- easy to debug
- easy to correct
- useful in the weekly product

INSIGHT does not need a magic clustering demo.
It needs a durable development object that helps a human stay on top of reality.
