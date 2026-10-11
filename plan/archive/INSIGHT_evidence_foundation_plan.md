# Evidence Foundation Implementation Plan

## Purpose

This document is for the future engineer who will implement the **Evidence Foundation** layer in INSIGHT while working directly with **OpenAI Codex**.

The goal is to strengthen the evidence substrate **before** building deeper memory, stories, analyst workflows, and monitors.

INSIGHT already has a good product direction:

- collect heterogeneous posts
- normalize them into one `posts` table
- group them into daily topics
- render briefings

But the current system will become unreliable if the raw evidence layer is still noisy, duplicated, weakly normalized, or operationally opaque.

If you remember only one sentence from this document, remember this:

**Evidence Foundation makes every later layer more trustworthy by making posts comparable, inspectable, and linkable before AI tries to reason over them.**

## Why We Are Building This

Entity memory, stories, contradiction detection, and watchlists all depend on the same hidden assumptions:

- the system knows when two posts are the same or nearly the same
- the system can identify the language of the post
- the system can extract the primary artifact being discussed
- the system can preserve exact provenance for every later inference
- the system can reprocess batches incrementally and explain what happened

Without this, later features will look smarter than they are.

Examples of failure without this layer:

- one Reuters/AP story copied across many feeds looks like many independent confirmations
- one Russian translation and one English original are treated as unrelated evidence
- one GitHub release and ten commentary posts are not linked to the same artifact
- one story is created from noisy duplicates instead of a clean evidence set
- debugging becomes impossible because enrichment happened invisibly and inconsistently

This feature exists to prevent those failures.

## Why We Choose This Method

We are deliberately choosing a **boring, inspectable, deterministic-first** method.

That means:

- normalize URLs before using AI
- detect language before cross-language reasoning
- compute hashes/fingerprints before clustering
- extract artifacts with rules before asking a model
- store explicit relation tables instead of hidden arrays in metadata
- process incrementally rather than reprocessing the full corpus

Why this method is correct:

1. It is cheaper than using LLMs on every post pair.
2. It is easier to debug.
3. It preserves human trust.
4. It gives later layers a clean substrate.
5. It allows the product to stay human-controllable instead of silently autonomous.

## Where This Feature Fits In The Roadmap

This feature is the base layer for:

- Entity + Event Memory
- Stories
- Analyst Inbox + Actions
- Monitors / Watchlists / Discovery
- later: source disagreement, corroboration quality, and second-brain notes

Do not skip this layer because it looks unglamorous.
This is the layer that prevents fake intelligence.

## How To Think About INSIGHT

Before writing code, understand the current product layers:

- `sources`
  - feed/channel/account registry
  - ingestion metadata
- `posts`
  - normalized storage for fetched evidence
- `topics`
  - daily grouping layer
- `briefings`
  - rendered cached output
- `job_runs`
  - operational visibility

The mistake a junior engineer is likely to make is this:

- treating evidence cleanup as a frontend problem
- hiding normalization inside random service methods
- using embeddings or LLMs before deterministic normalization exists
- collapsing duplicates too aggressively and losing provenance

Do not do that.

The correct mental model is:

- `post` = immutable evidence record
- `artifact` = the primary object a post refers to, such as a paper, release note, repo, announcement, thread, issue, or video
- `post_relation` = an explicit relation between posts, such as duplicate, near-duplicate, translation, or syndication
- `evidence foundation` = the layer that makes later intelligence possible

## Product Outcome

When this feature is done well, the system should be able to answer:

- Are these posts actually the same evidence?
- Is this post original, syndicated, translated, or derivative?
- Which artifact is this post really about?
- What language is this evidence in?
- What enrichment job produced these results?
- Can I trust corroboration counts on top of this data?

That means the system should support:

- stable URL normalization
- language detection
- content fingerprinting
- artifact extraction
- bounded duplicate and relation detection
- incremental reprocessing
- visible job telemetry

## Design Principles

### 1. Raw evidence is immutable

Do not overwrite the original fetched fields.

If you enrich a post, add new derived fields or related tables.
Preserve raw title, raw text, raw URL, raw timestamps, and raw source metadata.

### 2. Deterministic enrichment comes before AI enrichment

Use rules and utilities first:

- URL normalization
- language detection
- hash/fingerprint generation
- artifact URL extraction
- explicit link parsing

Only use models later when deterministic methods cannot decide an ambiguous case.

### 3. Provenance must survive every enrichment step

Every derived relation must point back to:

- the exact post(s)
- the method that produced it
- the enrichment job run
- the confidence or reason when relevant

### 4. Conservative linking beats aggressive collapsing

If two posts might be the same, link them.
Do not silently merge them into one row.

Duplicate and relation mistakes at the evidence layer will poison every later layer.

### 5. Incremental processing matters

The system is not a one-time dataset.
It is a continuously updated evidence stream.

Process only new or changed posts whenever possible.

### 6. Bounded candidate generation matters

Do not compare every post against every other post.

Narrow the search space using:

- same normalized URL
- same extracted artifact
- same source domain
- recent time window
- matching hashes or close title fingerprints
- same source item ids where available

### 7. Everything important must be debuggable

If a human cannot inspect why a post was marked duplicate, translation, or syndicated, the system will lose trust.

## Recommended Data Model

Create a dedicated migration in:

- `backend/insight_core/db/migrations/`

Do not hide this state inside arbitrary JSON when it deserves a first-class table.

### Additions to `posts`

Add these fields if they do not already exist:

- `language_code TEXT NULL`
- `language_confidence REAL NULL`
- `normalized_url TEXT NULL`
- `canonical_url TEXT NULL`
- `url_host TEXT NULL`
- `title_hash TEXT NULL`
- `content_hash TEXT NULL`
- `normalization_version TEXT NULL`
- `enriched_at TIMESTAMPTZ NULL`

Notes:

- `normalized_url` = machine-normalized form used for comparisons
- `canonical_url` = preferred final URL after cleaning if you distinguish the two
- `title_hash` and `content_hash` should be deterministic and cheap
- `normalization_version` lets you safely backfill or refresh later

### `artifacts`

Durable referenced objects extracted from posts.

Suggested fields:

- `id UUID PK`
- `artifact_type TEXT NOT NULL`
- `canonical_url TEXT NOT NULL`
- `normalized_url TEXT NOT NULL`
- `url_host TEXT NULL`
- `display_title TEXT NULL`
- `status TEXT NOT NULL DEFAULT 'active'`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Recommended indexes:

- unique on `normalized_url`
- `artifact_type`
- `url_host`

Start with a small set of `artifact_type` values:

- `paper`
- `release_note`
- `repo`
- `issue`
- `official_post`
- `video`
- `article`
- `other`

### `post_artifacts`

Join table between posts and artifacts.

Suggested fields:

- `post_id UUID REFERENCES posts(id)`
- `artifact_id UUID REFERENCES artifacts(id)`
- `relation_type TEXT NOT NULL`
- `confidence REAL NOT NULL DEFAULT 0`
- `is_primary BOOLEAN NOT NULL DEFAULT FALSE`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Primary key:

- `(post_id, artifact_id, relation_type)`

Suggested `relation_type` values:

- `discusses`
- `links_to`
- `quotes`
- `mirrors`
- `announces`

### `post_relations`

Explicit relation edges between posts.

Suggested fields:

- `from_post_id UUID REFERENCES posts(id)`
- `to_post_id UUID REFERENCES posts(id)`
- `relation_type TEXT NOT NULL`
- `method TEXT NOT NULL`
- `confidence REAL NOT NULL DEFAULT 0`
- `job_run_id UUID NULL REFERENCES job_runs(id)`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`

Primary key suggestion:

- `(from_post_id, to_post_id, relation_type)`

Suggested `relation_type` values for phase 1:

- `exact_duplicate`
- `near_duplicate`
- `translation_of`
- `syndicated_from`
- `references_same_artifact`

Notes:

- keep direction when the relation is directional
- if the relation is symmetric, still store one canonical ordering consistently or store both explicitly and document the rule
- do not infer too many relation types at once

### Optional Later: `source_profiles`

Do not block phase 1 on this table.

Later you may want a durable place for:

- source type
- official vs commentary hints
- source trust settings
- source language defaults
- rate limit and crawl behavior

For now, keep source-specific logic minimal and explicit.

## Recommended Code Layout

Follow the existing repo/service split already used in INSIGHT.

Create:

- `backend/insight_core/db/repo_evidence.py`
- `backend/insight_core/services/evidence_foundation_service.py`

Add lightweight utilities as needed:

- `backend/insight_core/utils/url_normalization.py`
- `backend/insight_core/utils/language_detection.py`
- `backend/insight_core/utils/content_fingerprints.py`
- `backend/insight_core/utils/artifact_extraction.py`

Do not bury enrichment logic in route handlers or unrelated services.

### Repository responsibilities

- update post enrichment fields
- upsert artifacts
- link posts to artifacts
- insert/update post relations
- fetch candidate posts for bounded relation checks
- retrieve evidence debug views

### Service responsibilities

- orchestrate enrichment for one post or a batch
- compute normalized fields
- detect language
- extract artifacts
- detect bounded post relations
- record job metadata
- expose rebuild operations later

### Processor responsibilities

The evidence foundation should avoid LLM dependency in phase 1.

Do not put this feature inside `GeminiProcessor` unless you later add a very narrow ambiguity resolver.
The foundation should remain mostly deterministic.

## Phase Plan

Implement this in phases.
Do not jump to relation detection before the normalization substrate is correct.

### Phase 1: Post Enrichment Basics

Objective:

- give every new post the minimum fields required for reliable comparison

Implement:

- URL normalization
- canonical/normalized host extraction
- language detection
- title/content hashes
- enrichment versioning
- `enriched_at`

Run this after ingestion for newly inserted or updated posts.

This phase should be cheap, deterministic, and easy to backfill.

### Phase 2: Artifact Extraction

Objective:

- identify what concrete artifact a post is actually talking about

Extract from posts:

- linked papers
- GitHub repos/releases/issues
- release notes
- official announcement pages
- original threads/videos where clearly identifiable

Rules first:

- parse explicit URLs
- normalize them
- classify host/domain patterns
- choose one primary artifact when confidence is high
- allow multiple artifacts when needed

Do not ask a model to guess the artifact if the post contains no explicit clue.

### Phase 3: Post Relation Detection

Objective:

- create explicit edges between posts that are operationally related

Use bounded candidate generation first:

- same normalized URL
- same artifact
- same host + similar title
- recent time window + strong title hash similarity
- same source item IDs if available

Start with conservative relation types:

- exact duplicate
- near duplicate
- translation of
- syndicated from
- references same artifact

Do not turn this into general story clustering.
That is a later layer.

### Phase 4: Rebuild and Telemetry

Objective:

- make enrichment observable and safe to rerun

Add:

- `job_runs` payload metadata for enrichment jobs
- rebuild for one post
- rebuild for one date range
- refresh for one source or source family later

Recommended job types:

- `evidence_enrichment`
- `artifact_extraction`
- `post_relation_detection`

Store useful metadata such as:

- post_count
- enriched_count
- artifact_count
- relation_count
- error_count
- normalization_version
- sample_post_ids

### Phase 5: Read APIs and Debug Surfaces

Objective:

- let the human verify that the evidence layer is behaving correctly

Suggested first routes:

- `GET /api/posts/item/{post_id}/evidence`
- `GET /api/posts/item/{post_id}/relations`
- `POST /api/evidence/rebuild-for-post`
- `POST /api/evidence/rebuild-for-date`

Do not start with a giant dashboard.
Start with post-level inspection.

## Recommended Processing Flow

The normal flow should become:

1. ingestion stores raw posts
2. gather inserted/updated post ids
3. enrich those posts with normalized URL, language, and hashes
4. extract artifacts for those posts
5. fetch bounded candidate posts for relation checks
6. persist post relations
7. record `job_runs`
8. expose evidence state to later entity/story pipelines

This flow should be incremental.
Do not recompute the entire database on every run.

## How This Connects To Later Features

### Connection to Entity + Event Memory

- better language and artifact data improve entity resolution
- duplicate control reduces fake corroboration
- artifacts help ground event extraction

### Connection to Stories

- stories need clean post relations
- shared artifacts strongly help story anchoring
- syndication control prevents one development from looking larger than it is

### Connection to Analyst Inbox + Actions

- the inbox should not surface six copies of the same post
- analyst actions should refer to evidence the system can explain
- source blocking or source trust actions become more reliable with normalized evidence

### Connection to Monitors / Watchlists

- feed discovery works better when normalized URLs and domains are clean
- monitor hits need dedupe before ranking
- artifact extraction enables better watch targets

## Execution Plan For The Junior Engineer

You are working with OpenAI Codex.
Do not ask Codex to build the whole feature in one pass.

### Step 1

Inspect the current codebase first.

Read these areas before changing code:

- `backend/insight_core/services/source_fetch_service.py`
- `backend/insight_core/services/posts_service.py`
- the current posts and sources migrations
- the current repo modules that read/write posts
- any existing `job_runs` service or repo
- any utilities already handling URLs, hashing, or parsing

Your first job is to understand how evidence enters the system.

### Step 2

Add the migration first.

Do not start with service code.
Make the schema explicit for:

- post enrichment fields
- `artifacts`
- `post_artifacts`
- `post_relations`

### Step 3

Implement `repo_evidence.py`.

Make sure you can:

- update enriched post fields
- upsert artifact by normalized URL
- link post to artifact
- insert or upsert post relation
- fetch bounded candidate posts for comparison
- fetch debug views for one post

### Step 4

Implement the utilities.

Write small, testable helpers for:

- URL normalization
- language detection
- title/content fingerprinting
- artifact extraction from raw text and URLs

Do not mix these helpers into one giant class.

### Step 5

Implement `evidence_foundation_service.py`.

This service should orchestrate:

- enrich one post
- enrich a batch of posts
- extract artifacts
- detect relations
- record the result into `job_runs`

### Step 6

Add a hook after ingestion.

Recommended flow:

1. ingestion stores raw posts
2. collect inserted/updated post ids
3. run evidence enrichment for that batch
4. persist results
5. record a job run

### Step 7

Add tests before adding UI work.

You need tests for:

- URL normalization
- language detection fallback behavior
- artifact extraction from representative post examples
- duplicate relation detection for obvious cases
- non-collapse behavior for ambiguous cases

### Step 8

Add minimal read APIs only after persistence is correct.

## Codex Prompting Guidance

Do not tell Codex:

- “implement evidence foundation”

Tell Codex something like this instead:

1. inspect the current ingestion and post persistence flow
2. summarize how posts are stored today
3. add a migration for the evidence foundation tables/fields
4. implement `repo_evidence.py`
5. add unit tests for URL normalization and artifact extraction
6. stop and summarize what changed

Then continue in another prompt for service orchestration.

Small bounded prompts are safer than one giant prompt.

## Common Failure Modes

### Failure 1: Overwriting raw post data

Cause:

- treating enriched data as a replacement for raw data

Fix:

- preserve raw values and store derived fields separately

### Failure 2: Using AI before deterministic normalization exists

Cause:

- asking a model to decide duplicates or artifact identity too early

Fix:

- build the cheap deterministic layer first

### Failure 3: O(N²) comparison explosions

Cause:

- comparing every new post against the full corpus

Fix:

- fetch bounded candidate sets only

### Failure 4: Silent provenance loss

Cause:

- storing relation outputs without method, version, or job link

Fix:

- include method, confidence, and `job_run_id`

### Failure 5: Over-collapsing duplicates

Cause:

- merging rows instead of linking rows

Fix:

- use relation edges, not destructive merges

### Failure 6: Artifact extraction becoming too clever too early

Cause:

- trying to classify every possible object type

Fix:

- start with a small artifact taxonomy and expand later

## First Practical Milestone

The first milestone should be narrow and testable.

Target:

- ingest one day of posts
- enrich them with normalized URL, language, and hashes
- extract primary artifacts where clear
- detect exact duplicates and obvious near-duplicates conservatively
- expose one post-level debug API showing evidence fields and relations

If that works, INSIGHT has crossed the threshold from:

- “raw collected posts”

to:

- “trusted normalized evidence”

## Final Milestone

This feature is complete enough for the next layer when:

- new posts are automatically enriched after ingestion
- duplicates and basic relations are persisted with provenance
- artifacts are extracted and linked
- every enrichment run is visible in `job_runs`
- a human can inspect one post and understand why the system considers it original, duplicate, translated, syndicated, or artifact-linked

At that point, Entity + Event Memory and Stories can be built on top of something trustworthy.

## Final Advice To The Junior Engineer

Do not try to impress with sophistication.

The correct implementation is the one that makes later intelligence more believable.

If the system cannot answer “what exactly is this evidence and how is it related to the rest?” the foundation is not done.
