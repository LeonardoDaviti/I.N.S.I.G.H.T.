# Vertical Briefing / Scoped Briefing Implementation Plan

## Purpose

This document is for the future engineer who will implement **Vertical Briefing** in INSIGHT.

The goal is to extend INSIGHT from:

- horizontal briefings built from a time slice of posts
- daily topics built within one date window
- weekly syntheses built by combining daily outputs

into:

- source-centric recurring-theme briefings
- monitor-centric briefings
- entity-centric briefings later
- a more general **scoped briefing** system where the user can choose the axis of synthesis

If you remember only one sentence from this document, remember this:

**Horizontal briefing answers “what happened in this time window?”, while vertical briefing answers “what keeps happening within this chosen scope across time?”**

---

## Why We Are Building This

The current product is good at answering:

- what was important today
- what changed this week
- what stories emerged across sources in a date range

But many real analyst workflows are not date-first.

Sometimes the user wants:

- everything Andrej Karpathy has been developing across several posts
- recurring threads from one research lab or one blog
- a thematic digest for one watchlist
- a focused brief on one source bundle or monitor

Your example is exactly right:

- one source: `Andrej Karpathy`
- several posts across time
- repeated discussion of `autoresearch`
- desire to merge these into one coherent tracked thread

That is not a normal daily topic.
It is also not exactly a story in the event sense.
It is a **source-scoped recurring theme**.

This is why vertical briefing should start phase 2.
It opens the path toward INSIGHT as a second brain, not just a daily news summarizer.

---

## Why We Choose This Method

We should **reuse the current briefing architecture pattern**, but **not reuse the current prompting strategy unchanged**.

We choose this method because:

1. the repo already has a strong derived-output path
   - posts are loaded from the database
   - briefings are generated in service layer
   - outputs are cached in `briefings`
   - structured variants are stored in payloads

2. vertical briefing is a **read-model feature** first
   - it does not need a giant new durable ontology on day one
   - it can begin as a new briefing subject type and variant

3. the product needs flexible axes of synthesis
   - source
   - watchlist
   - monitor
   - entity later
   - story set later

4. the user wants controllable information compression
   - same scope
   - longer time span
   - recurring threads made visible

---

## What The Current System Already Does

Based on the current implementation, the existing briefing system has four important behaviors.

### 1. Daily horizontal briefing

`BriefingService.generate_daily_briefing()` loads posts for one date from the database and sends them to `GeminiProcessor.daily_briefing()`, then stores the markdown output in `briefings` as a `daily_briefing` variant. 

### 2. Daily horizontal briefing with topics

`BriefingService.generate_daily_briefing_with_topics()` loads all posts for one date, calls `GeminiProcessor.topic_briefing_with_numeric_ids()`, normalizes the returned topic `post_ids`, stores the topics through `TopicsService.save_topic_with_posts()`, and caches the rendered markdown plus structured topic payload. 

### 3. Weekly horizontal briefing

`BriefingService.generate_weekly_briefing()` combines already-generated daily briefings for a week and asks `GeminiProcessor.weekly_briefing()` to synthesize them into a weekly memo. 

### 4. Weekly cross-day topic synthesis

`BriefingService.generate_weekly_topic_briefing()` reuses daily topic briefings for each day of the week, builds a list of `daily_topic_briefings`, and asks `GeminiProcessor.weekly_topic_briefing()` to merge same-story developments across days into timeline-bearing weekly topics. The processor prompt already asks for a `weekly_briefing` plus structured `topics` with `timeline` entries and `post_ids`. 

These four behaviors matter because they show that INSIGHT already has:

- post retrieval
- prompt-based grouping
- structured JSON normalization
- timeline-style weekly synthesis
- briefing caching by subject and variant

That is a very good starting point.

---

## What Vertical Briefing Should Be

Vertical briefing should not be hardcoded as “brief a source.”

The general concept should be:

- **horizontal briefing** = time-first synthesis
- **vertical briefing** = scope-first synthesis

### Phase 1 scope types

Start with one scope type only:

- `source`

### Future scope types

Later extend to:

- `monitor`
- `watchlist`
- `entity`
- `story_collection`
- `saved_collection`

### What source vertical briefing answers

For a single source over a date range, it should answer:

- what recurring threads keep appearing?
- what changed in each thread over time?
- what is this source currently focused on?
- what are the persistent themes vs one-off posts?

This is closer to a **theme / thread briefing** than a daily topic clustering pass.

---

## Important Conceptual Distinction

A junior engineer is likely to make this mistake:

- take all posts from one source for 30 days
- run the existing daily topic prompt unchanged
- treat the result as vertical briefing

Do not do that.

Why this is wrong:

- daily topic clustering is optimized for one date window
- story/event grouping across a day is not the same as theme recurrence across weeks
- repeated source themes can span multiple distinct events
- one source often returns to the same concept using new posts and new framings

For example:

- “Autoresearch” may be one recurring project thread
- “agentic engineering” may be a broader recurring theme
- “education / teaching” may be another recurring source theme

These are not all one story, and they are not all one entity.

Vertical briefing therefore needs **threads/tracks**, not ordinary daily topics.

---

## Can The Same Strategy Be Applied?

### What can be reused

Yes, the **service orchestration strategy** can be reused.

Reuse:

- load posts from the DB
- call a dedicated processor method
- normalize structured JSON output
- save final markdown to `briefings`
- keep structured tracks in payload
- use variants and cache keys

### What should not be reused unchanged

No, the **prompting and clustering strategy** should not be reused unchanged.

Do not blindly reuse the current daily topic prompt because it tells the model to:

- “create as many topics as needed”
- group related posts inside one date window
- prefer the original source event over commentary

That is good for daily cross-source grouping.
It is not enough for source-scoped recurring-theme synthesis across time.

### What is closer to the right model

The current **weekly topic briefing** is much closer to the right conceptual shape.

Why:

- it already merges related developments across days
- it already emits timelines
- it already distinguishes core events from commentary

Vertical briefing should borrow more from **weekly topic briefing** than from **daily topic briefing**.

---

## Product Outcome

When this feature is done well, the user should be able to ask:

- What has Karpathy been focused on over the last 30 days?
- Which recurring thread matters most in this source?
- Show me the evolution of one source-specific theme over time.
- Summarize one source without flattening everything into a generic recap.
- Later: do the same for one monitor or watchlist.

That means the product should support:

- choosing a scope
- choosing a date range
- producing recurring tracks
- attaching evidence posts to each track
- showing timeline entries for each track
- caching the briefing and its structured payload

---

## Design Principles

### 1. Scope first, then synthesize

Do not start with “all posts today.”
Start with:

- one source
- one monitor
- one watchlist

Then synthesize across time.

### 2. Recurring tracks, not one-off topic buckets

The core output object is a **track**.
A track is a recurring thread within the chosen scope.

### 3. Keep provenance

Every track and timeline entry must point to exact post IDs.

### 4. Start as a derived view, not a new ontology

Do not create a giant new permanent graph table for vertical tracks in phase 1.
Use the existing briefing storage path first.

### 5. Reuse memory, do not duplicate it

Stories and entities should strengthen vertical briefing later.
Do not rebuild them inside this feature.

### 6. Human-readable, operator-useful output only

This is not a demo clustering feature.
The briefing must save analyst time.

---

## Recommended Output Model

Start by extending `briefings` with a new `subject_type` usage rather than creating many new persistent tables.

Use:

- `subject_type = 'vertical_briefing'`
- `variant = 'source'` for phase 1

Construct a `subject_key` like:

- `source:{source_id}:{start_date}:{end_date}`

The markdown goes into `content`.
Structured tracks go into `payload`.

### Suggested payload shape

```json
{
  "scope_type": "source",
  "scope_id": "source-uuid",
  "start_date": "2026-03-01",
  "end_date": "2026-03-31",
  "tracks": [
    {
      "id": "track-1",
      "title": "Autoresearch",
      "summary": "Recurring source thread summary",
      "track_kind": "project_thread",
      "post_ids": ["post-1", "post-2"],
      "timeline": [
        {
          "date": "2026-03-07",
          "summary": "What changed on this date",
          "post_ids": ["post-1"]
        }
      ]
    }
  ],
  "estimated_tokens": 1234
}
```

### Recommended `track_kind` values

Start with a small set:

- `project_thread`
- `recurring_theme`
- `one_off_update`

Do not invent a huge taxonomy.

---

## Why This Schema Choice

We choose this because:

- vertical briefing is still a briefing product first
- the current system already stores structured briefing payloads
- we should validate product value before introducing persistent `vertical_tracks` tables

Later, if track pages become important, you can promote tracks into first-class durable objects.

Not in phase 1.

---

## Recommended Code Layout

Do not create a completely separate subsystem.

Extend:

- `backend/insight_core/services/briefing_service.py`
- `backend/insight_core/services/posts_service.py`
- `backend/insight_core/processors/ai/gemini_processor.py`

Potential additions:

- `backend/insight_core/services/vertical_briefing_service.py` later, if the briefing service grows too large

### Posts service responsibilities

Add retrieval methods such as:

- `get_posts_by_source_and_range(source_id, start_date, end_date)`
- later `get_posts_by_monitor_and_range(...)`

### Briefing service responsibilities

Add methods such as:

- `generate_source_vertical_briefing(source_id, start_date, end_date, refresh=False)`
- later `generate_scoped_vertical_briefing(scope_type, scope_id, start_date, end_date, refresh=False)`

### Processor responsibilities

Add a dedicated method such as:

- `source_vertical_briefing(posts, scope_label, start_date, end_date)`

Do not reuse the daily topic method name.
Do not overload the weekly topic method with hidden source-specific assumptions.

---

## Processor Output Shape

Expected output shape:

```json
{
  "vertical_briefing": "markdown summary",
  "tracks": [
    {
      "title": "Autoresearch",
      "summary": "2-5 sentence summary",
      "track_kind": "project_thread",
      "post_ids": ["post-uuid-1", "post-uuid-2"],
      "timeline": [
        {
          "date": "YYYY-MM-DD",
          "summary": "what changed on this date",
          "post_ids": ["post-uuid-1"]
        }
      ]
    }
  ]
}
```

---

## Prompting Guidance

This is the most important design correction.

Do not ask:

- “group these posts into topics”

Ask instead:

- identify recurring tracks within this source across time
- separate recurring themes from one-off updates
- merge posts into one track only when they clearly belong to the same recurring thread
- emit timeline entries showing what changed and when

The prompt should strongly constrain the model to produce:

- fewer, stronger tracks
- concrete titles
- explicit post IDs
- timeline entries
- a useful source-level memo

### Example prompt intent

- You are preparing a vertical briefing for one source over a date range.
- Find recurring themes, project threads, or one-off updates.
- Group posts into tracks that persist across time.
- Do not over-merge unrelated posts just because the same source wrote them.
- Preserve post IDs and timeline evidence.

This is a different instruction set from daily topic clustering.

---

## Phase Plan

### Phase 1: Source-Scoped Vertical Briefing

Objective:

- add one new briefing mode for one source across a date range

Input:

- `source_id`
- `start_date`
- `end_date`

Output:

- markdown briefing
- structured `tracks` with timelines and `post_ids`

No new UI beyond a simple source detail action is needed at first.

### Phase 2: Track Quality Improvements

Objective:

- reduce noisy or over-broad tracks

Add:

- use story links when available
- use entity overlap as a helper
- use evidence foundation dedupe so reposts do not distort track prominence

### Phase 3: Generic Scoped Briefing

Objective:

- generalize beyond source

Add support for:

- `monitor`
- `watchlist`
- `entity`

At this point, vertical briefing becomes **scoped briefing**.

### Phase 4: Source Comparison and Multi-Vertical Views

Objective:

- compare two or more sources or scopes

Examples:

- Karpathy vs Simon Willison on coding agents
- one watchlist vs another
- official sources vs commentary sources

Do not build this in phase 1.

### Phase 5: Notebook / Second-Brain Integration

Objective:

- let the user save tracks, annotate them, and reuse them later

This is where the zettelkasten / second-brain direction becomes real.

---

## API Shape

Start thin.

Suggested first routes:

- `GET /api/briefings/vertical/source/{source_id}?start=YYYY-MM-DD&end=YYYY-MM-DD`
- `POST /api/briefings/vertical/source/{source_id}/refresh`

Later:

- `GET /api/briefings/vertical/{scope_type}/{scope_id}`
- `POST /api/briefings/vertical/{scope_type}/{scope_id}/refresh`

Do not start with a giant generic abstraction if only source scope is shipping first.

---

## UI Order

### 1. Source detail page

Add:

- “Generate Vertical Briefing” action
- date range selector
- recurring tracks list
- timeline entries per track

### 2. Saved briefings view

Show:

- recent source vertical briefings
- cached status
- date ranges

### 3. Later: generic scoped briefing page

Only after source mode is validated.

---

## How This Connects To Stories

Stories answer:

- what happened

Vertical briefing answers:

- what this source keeps focusing on across time

One source may cover:

- one story repeatedly
- several related stories under one recurring theme
- a durable concept that is not one event-story

Therefore:

- stories help vertical briefing
- stories do not replace vertical briefing

This distinction matters.

---

## How This Connects To Monitors And Watchlists

Monitors answer:

- what should we keep watching

Vertical briefing answers:

- what does this scoped stream look like over time

A future monitor vertical briefing is very natural:

- monitor = coding agents
- date range = last 14 days
- output = recurring tracks + notable shifts

This is why vertical briefing is a good phase-2 feature after monitors.

---

## Operational Guidance

Vertical briefing should be generated on demand first.

Do not schedule automatic generation for every source.

Why:

- expensive
- many scopes will never be used
- source/date combinations explode quickly

Recommended phase-1 flow:

1. user requests source vertical briefing
2. system checks cached briefing in `briefings`
3. if cache miss or refresh requested, load posts for the scope and range
4. run processor
5. normalize tracks
6. save markdown + payload
7. return result

Recommended `job_runs` types:

- `vertical_briefing_source`
- later `vertical_briefing_scope`

Store metadata such as:

- source_id
- start_date
- end_date
- post_count
- track_count
- estimated_tokens

---

## Common Failure Modes

### Failure 1: Everything becomes one giant source bucket

Cause:

- grouping by source only

Fix:

- require recurring tracks inside the source
- keep track titles concrete

### Failure 2: Every post becomes its own track

Cause:

- no recurrence threshold or weak prompting

Fix:

- instruct the model to favor recurring themes and project threads
- allow one-off updates only when they materially matter

### Failure 3: Tracks collapse into generic themes like “AI”

Cause:

- titles too broad
- poor normalization

Fix:

- concrete titles only
- emphasize project/thread-level naming

### Failure 4: Vertical briefing duplicates story pages

Cause:

- using story logic only

Fix:

- allow recurring themes broader than single stories
- but still use story memory as supporting structure

### Failure 5: Overbuilding a permanent ontology too early

Cause:

- trying to make vertical tracks into permanent canonical objects before validating value

Fix:

- keep it as structured briefing payload first

---

## First Practical Milestone

Target:

- choose one source
- choose a 14- or 30-day date range
- load posts from that source
- generate one vertical briefing with 2-6 recurring tracks
- attach exact post IDs and timeline entries
- render it on the source detail page

If that works, the product has crossed the threshold from:

- “source archive”

to:

- “source intelligence view”

---

## Final Milestone

The final milestone for this feature is:

- vertical briefing works first for sources, then for other scopes
- recurring tracks are evidence-backed and useful
- timelines show what changed within each track
- outputs are cached and explainable
- the system moves closer to a second-brain workflow rather than a one-shot summarizer

When the feature is done well, the user should be able to say:

- “Show me what this source has really been about lately.”
- “Merge the repeated autoresearch posts into one coherent track.”
- “Keep one-off noise separate from recurring focus.”
- “Later, do the same for this watchlist or monitor.”

That is the standard.

---

## Development Roadmap For The Junior Engineer Using Codex

Do not ask Codex to “build vertical briefing.”

Use bounded tasks.

### Step 1

Inspect first:

- `backend/insight_core/services/briefing_service.py`
- `backend/insight_core/services/posts_service.py`
- `backend/insight_core/services/topics_service.py`
- `backend/insight_core/processors/ai/gemini_processor.py`

Understand the existing daily/weekly/default/topics flow before changing anything.

### Step 2

Add the missing posts retrieval method for source + date range.

### Step 3

Add one processor method specifically for source vertical briefing.

### Step 4

Add one briefing service method for source vertical briefing.

### Step 5

Store the result in `briefings` using a new subject type or clearly separated varianting scheme.

### Step 6

Add one read API and one refresh API.

### Step 7

Add a minimal source-detail UI entry point.

Only after that should you generalize to monitor / watchlist / entity scopes.

---

## Final Advice To The Junior Engineer

Reuse the current service and caching pattern.

Do not reuse the daily topic prompt unchanged.

Build a source-scoped recurring-track briefing first.

If the user cannot look at one vertical briefing and quickly answer:

- what this source keeps focusing on
- what changed within those threads
- which posts prove it

then the feature is not done.
