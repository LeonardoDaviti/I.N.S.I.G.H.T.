# INSIGHT: Revised Entity, Event, and Evidence Memory Plan

## Why this revision exists

The original entity-memory plan is directionally correct, but entity memory alone is not enough to produce a trustworthy news-intelligence system.

A real analyst workflow needs five things at the same time:

1. **durable identity** — who/what keeps appearing
2. **durable events/claims** — what changed
3. **provenance** — where each assertion came from
4. **uncertainty handling** — avoid over-merging and fake certainty
5. **analyst control** — save time without hiding logic in black-box ranking

This plan keeps the existing INSIGHT architecture and extends it in a way that supports better weekly briefings, watchlists, comparison views, and contradiction detection.

---

## What INSIGHT already is

INSIGHT already has the right base shape:

- `sources` = source registry and ingestion settings
- `posts` = normalized evidence table
- `topics` = daily grouping
- `briefings` = cached rendered outputs
- `job_runs` = operational telemetry

This should remain the foundation.

The memory layer should sit **above** posts and topics, not replace them.

---

## Strategic correction

Do **not** think of the next feature as only "entity memory."

The actual next layer should be:

**evidence -> mentions -> entities -> events -> claims -> analyst outputs**

That is the order in which trust and product value compound.

---

## Design principles

### 1. Provenance first
Every durable record must point back to one or more posts.

### 2. Uncertainty is a first-class concept
Ambiguous mentions must be stored as unresolved or multi-candidate, not forced into a bad merge.

### 3. Duplicates are cheaper than false merges
False entity merges and fake corroboration are more damaging than duplicated records.

### 4. Start event-first before open-ended claims
Typed events are easier to normalize, deduplicate, compare, and summarize than arbitrary claim text.

### 5. Cross-lingual normalization is required
Store original text, but also create a normalized pivot representation for cross-language comparison.

### 6. Human actions must be logged
If an analyst confirms a merge, dismisses a story, or pins an item, that action becomes part of the system memory.

### 7. Incremental processing only
Extract on new or changed posts. Backfill only when needed.

---

## Phase 0: Foundations that should exist before entity memory

### Why this phase matters
If you do not solve these foundations first, every later metric will be polluted.

### 0.1 Language and normalization fields on `posts`
Ensure `posts` can support:

- `language_code`
- `title_original`
- `body_original`
- `title_pivot` (optional translated/normalized title)
- `summary_pivot` (optional short normalized summary)
- `canonical_url`
- `content_hash`
- `published_at`

The system should always preserve original text, but cross-language comparison should use a pivot representation.

### 0.2 Deduplication and syndication control
Add a thin dedupe layer before counting evidence.

Recommended table:

#### `post_relations`
Fields:
- `post_id UUID FK -> posts`
- `related_post_id UUID FK -> posts`
- `relation_type TEXT NOT NULL`
- `confidence REAL NOT NULL`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ`

Possible `relation_type` values:
- `near_duplicate`
- `syndicated_from`
- `same_story`
- `translation_of`

This matters because 10 rewrites of the same AP/Reuters story are not 10 independent confirmations.

### 0.3 Source profile layer
Recommended table:

#### `source_profiles`
Fields:
- `source_id UUID PK/FK -> sources`
- `language_code TEXT NULL`
- `publisher_type TEXT NULL`
- `country_code TEXT NULL`
- `is_primary_reporter BOOLEAN NOT NULL DEFAULT false`
- `reliability_notes TEXT NULL`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

This enables ranking, weighting, and better evidence interpretation later.

---

## Phase 1: Raw mention extraction (before canonical entity resolution)

### Why this should come first
The original plan links posts directly to canonical entities. That is too early.

You first need a durable record of **what the model extracted from the post**, even if resolution is ambiguous.

### New tables

#### `entity_mentions`
Fields:
- `id UUID PK`
- `post_id UUID FK -> posts`
- `mention_text TEXT NOT NULL`
- `normalized_mention TEXT NOT NULL`
- `language_code TEXT NULL`
- `entity_type_predicted TEXT NOT NULL`
- `role TEXT NULL`
- `char_start INT NULL`
- `char_end INT NULL`
- `extractor_confidence REAL NOT NULL`
- `extractor_name TEXT NOT NULL`
- `extractor_version TEXT NOT NULL`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ`

This becomes the durable raw extraction record.

#### `entities`
Fields:
- `id UUID PK`
- `entity_type TEXT NOT NULL`
- `canonical_name TEXT NOT NULL`
- `canonical_name_pivot TEXT NULL`
- `normalized_name TEXT NOT NULL`
- `description TEXT NULL`
- `status TEXT NOT NULL DEFAULT 'active'`
- `review_state TEXT NOT NULL DEFAULT 'provisional'`
- `first_seen_at TIMESTAMPTZ`
- `last_seen_at TIMESTAMPTZ`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

Indexes:
- `(entity_type, normalized_name)`
- `last_seen_at`
- `review_state`

#### `entity_aliases`
Fields:
- `id UUID PK`
- `entity_id UUID FK -> entities`
- `alias TEXT NOT NULL`
- `normalized_alias TEXT NOT NULL`
- `language_code TEXT NULL`
- `script TEXT NULL`
- `alias_type TEXT NOT NULL`
- `transliteration TEXT NULL`
- `source_hint TEXT NULL`
- `created_at TIMESTAMPTZ`

Unique constraint:
- `(entity_id, normalized_alias)`

#### `mention_entity_candidates`
Fields:
- `mention_id UUID FK -> entity_mentions`
- `entity_id UUID FK -> entities`
- `candidate_method TEXT NOT NULL`
- `score REAL NOT NULL`
- `selected BOOLEAN NOT NULL DEFAULT false`
- `resolver_version TEXT NOT NULL`
- `created_at TIMESTAMPTZ`

This table is the missing uncertainty layer.

### Resolution policy
Entity resolution should happen in stages:

1. exact normalized alias match within entity type
2. transliteration match
3. source-hint-based match
4. optional embedding retrieval for candidate generation
5. LLM adjudication only on shortlisted candidates
6. unresolved state if confidence is low

### Important rule
Do not auto-merge fuzzy matches in phase 1.

---

## Phase 2: Canonical entity links

Once mention extraction exists, create resolved links.

#### `post_entities`
Fields:
- `post_id UUID FK -> posts`
- `entity_id UUID FK -> entities`
- `mention_id UUID FK -> entity_mentions`
- `resolution_status TEXT NOT NULL`
- `confidence REAL NOT NULL`
- `role TEXT NULL`
- `metadata JSONB NOT NULL DEFAULT '{}'`
- `created_at TIMESTAMPTZ`

Suggested statuses:
- `resolved`
- `provisional`
- `needs_review`

Primary key:
- `(post_id, entity_id, mention_id)`

This table should represent resolved usage, while `entity_mentions` remains the raw evidence record.

---

## Phase 3: Events before generic claims

### Why events should precede claims
Generic claims are too open-ended at the beginning.

For news intelligence, typed events are much easier to:

- deduplicate
- compare across sources
- render in timelines
- summarize in weekly briefings
- attach stances to

### Start with a small event ontology
Only use a handful of event types that match the domain you track most.

Suggested initial event types:
- `release_launch`
- `funding`
- `partnership`
- `acquisition`
- `leadership_change`
- `policy_regulation`
- `security_incident`

### New tables

#### `events`
Fields:
- `id UUID PK`
- `event_type TEXT NOT NULL`
- `title TEXT NOT NULL`
- `normalized_event_key TEXT NULL`
- `status TEXT NOT NULL DEFAULT 'observed'`
- `confidence REAL NOT NULL`
- `occurred_at TIMESTAMPTZ NULL`
- `first_seen_at TIMESTAMPTZ`
- `last_seen_at TIMESTAMPTZ`
- `created_at TIMESTAMPTZ`
- `updated_at TIMESTAMPTZ`

#### `event_entities`
Fields:
- `event_id UUID FK -> events`
- `entity_id UUID FK -> entities`
- `role TEXT NOT NULL`
- `created_at TIMESTAMPTZ`

Examples of roles:
- `actor`
- `target`
- `issuer`
- `acquirer`
- `acquired`
- `announcer`

#### `event_evidence`
Fields:
- `event_id UUID FK -> events`
- `post_id UUID FK -> posts`
- `stance TEXT NOT NULL`
- `evidence_snippet TEXT NULL`
- `confidence REAL NOT NULL`
- `extractor_version TEXT NOT NULL`
- `created_at TIMESTAMPTZ`

Possible stance values:
- `supports`
- `contradicts`
- `mentions`
- `unclear`

---

## Phase 4: Claims and relations (only after events work)

After events stabilize, add claims for assertions that do not fit cleanly into event templates.

Recommended examples:
- benchmark claims
- intent/strategy claims
- capability claims
- allegation/dispute claims

Keep the original `claims` / `claim_evidence` idea, but only after event memory is providing value.

---

## Phase 5: Analyst actions and reviewability

Palantir-like value does not come only from storing objects. It comes from making analyst decisions durable and auditable.

Recommended table:

#### `analyst_actions`
Fields:
- `id UUID PK`
- `action_type TEXT NOT NULL`
- `target_type TEXT NOT NULL`
- `target_id UUID NOT NULL`
- `payload JSONB NOT NULL DEFAULT '{}'`
- `created_by TEXT NULL`
- `created_at TIMESTAMPTZ`

Examples:
- `confirm_entity_merge`
- `reject_entity_merge`
- `pin_event`
- `dismiss_post`
- `add_to_watchlist`
- `mark_source_priority`

This creates a memory of human judgment, not just machine output.

---

## How multilingual handling should work

### Do not rely on one global multilingual embedder as your main truth engine
For mixed-language news, full-post embeddings are often too coarse for event clustering and too brittle for canonical entity assignment.

### Better approach
For each post:

1. keep original-language title/body
2. detect language
3. optionally create a short pivot title/summary for cross-language matching
4. extract mentions in original language
5. store transliterations and pivot aliases where useful
6. use hybrid candidate retrieval:
   - exact alias
   - transliteration
   - source hints
   - embedding shortlist
   - LLM adjudication

This makes multilingual support a normalization problem, not an all-or-nothing model bet.

---

## Where embeddings are useful

Embeddings should be optional support infrastructure, not the core logic.

### Good uses
- shortlist candidate entities for a mention
- semantic search over posts or evidence
- retrieve historical analogs
- near-duplicate or same-story support
- related-entity suggestions

### Bad uses in early versions
- final canonical entity assignment
- contradiction detection
- free-form claim normalization
- raw full-post multilingual clustering without time/entity constraints

---

## Updated service architecture

### Do not keep all extraction logic inside one generic processor
Refactor toward typed extractor interfaces.

Suggested services/modules:

- `entities_service.py`
  - extraction orchestration
  - entity creation / resolution
  - mention persistence
- `events_service.py`
  - event extraction
  - event resolution
  - evidence linking
- `resolution_service.py`
  - candidate generation
  - deterministic matching
  - optional embedding lookup
  - adjudication hooks

Suggested AI methods:
- `extract_entity_mentions(post)`
- `resolve_entity_mention(mention, candidates)`
- `extract_events(post)`
- `judge_event_evidence(event, post)`
- `create_pivot_summary(post)`

Every result should include model/prompt/schema version metadata.

---

## Product outputs this plan enables

### Earlier than a graph UI
This plan supports higher-value outputs first:

- entity profile page
- event timeline page
- “what changed this week about X”
- source disagreement view
- watchlists
- analyst review queue
- better weekly briefings

### Later
- graph browsing
- relation explorer
- deeper cross-entity analytics

Do not build graph browsing first.

---

## Revised execution order

### Step 1
Add phase-0 fields and dedupe relations.

### Step 2
Implement `entity_mentions` and mention extraction first.

### Step 3
Implement conservative entity resolution and `mention_entity_candidates`.

### Step 4
Only then write `post_entities`.

### Step 5
Add typed event extraction and `event_evidence`.

### Step 6
Add entity/event APIs and watchlist outputs.

### Step 7
Only after that, add generic claims.

---

## What not to do

- do not build a huge ontology first
- do not treat embeddings as truth
- do not merge aggressively across languages
- do not count syndicated rewrites as independent evidence
- do not skip extractor versioning
- do not hide uncertainty
- do not start with graph browsing

---

## Final recommendation

The next milestone should not be called only “entity memory.”

It should be treated as:

**Evidence, Entity, and Event Memory**

That is the layer that can turn INSIGHT from a summarization system into an analyst-controlled intelligence system.
