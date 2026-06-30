# Folders & Experts Implementation Plan

## Purpose

This document is for the engineer who will implement **Folders** and **Experts** in
INSIGHT, together with the supporting work that makes them observable and safe
(**Langfuse tracing** and a set of **processor fixes**), plus two downstream
experts (**Changelogs**) and a **feed discovery** helper.

If you remember only one sentence from this document, remember this:

**INSIGHT today has deep vertical enrichment but no horizontal organization — Folders
add the grouping layer, and Experts add scoped, opinionated synthesis on top of it.**

> Scope note: **automatic folder suggestion / auto-clustering ("Suggest folders") is
> intentionally OUT of scope for this plan.** Folders here are created and populated
> manually. The auto-clustering design is deferred to a separate document.

---

## Why We Are Building This

The current product answers date-first questions well:

- what was important today (daily briefing)
- what changed this week (weekly briefing)
- what stories emerged across sources in a date range (topics)
- what keeps happening within one source (vertical briefing)

But everything renders into one flat, undifferentiated stream. Two primitives are missing:

1. **Folders** — a grouping layer over sources, so the main surface is not chaotic.
2. **Experts** — a briefing agent with its own system prompt, its own source scope,
   and its own focus instructions, so synthesis is opinionated per domain instead of
   one generic "everything" briefing.

These compose: **an Expert runs over a Folder.** A folder like *Scientific Papers (AI)*
feeds both a scoped topic briefing and the *Scientific Papers* expert persona.

Target experts (examples the product owner wants):

- Scientific Papers (AI)
- Biology Papers (wants this to stay rigorous / "very based")
- Economy & World Events
- Global AI News
- Changelogs (special: input = an app + the user's current version)

---

## Locked Product Decisions

These were decided with the product owner and are not open questions:

| Decision | Choice | Consequence |
|---|---|---|
| Folder ↔ Expert relationship | **Experts run over Folders** | One grouping hierarchy. An expert points at exactly one folder for its source scope. |
| Auto-foldering | **Out of scope (manual only)** | Folders are created and populated by hand in this plan. |
| Expert execution | **Scheduled per expert** | Each expert carries its own cadence; the scheduler drives expert briefings unattended. |
| Folder briefing == expert briefing | **Same operation** | An expert *is* the thing that generates its folder's **daily topic briefing**, scoped to that folder's sources only, with the expert's persona + focus injected. There is no separate "folder briefing" mechanism. |

### Core logic (one sentence)

**Sources live in folders → an expert is attached to a folder → the expert generates a
daily topic briefing over that folder's sources only.** The existing topic pipeline is
reused; the only changes are (a) scope the post query to the folder's sources, and (b)
inject the expert's `system_prompt` / `focus_instructions` into the prompt.

A source can belong to **multiple folders** (many-to-many). This is required so a source
relevant to two experts (e.g. an AI-research Telegram channel relevant to both
*Scientific Papers* and *Global AI News*) can feed both without duplication.

---

## What Already Exists (reuse, do not rebuild)

- **Generic briefing store** — `BriefingsStoreService` keys everything by
  `subject_type` / `subject_key` / `variant`. Folder and expert briefings are new
  subject types, **not** a new storage system.
- **Per-source profile** — `BriefingService._build_vertical_source_profile()`
  (`briefing_service.py:1488`) already computes dominant entities/stories/categories/
  track-hints per source. Reuse it for folder descriptions and expert context.
- **Model fallback engine** — `GeminiProcessor._generate_text_sync()`
  (`gemini_processor.py:976`) handles model routing, retries, backoff, and fallback.
  Every new feature routes through it; do not write a second LLM client.
- **Scheduler** — `scripts/run_scheduler.py` already drives ingestion and global
  briefings. Expert briefings become additional scheduled jobs keyed by `expert_id`.
- **Reddit comment summarization** — `GeminiProcessor.summarize_reddit_comments()`
  (`gemini_processor.py:611`) — reused by the Changelogs expert for "community opinion".
- **Layered architecture** — repo → service → bridge → API (see `BACKEND.md`). Every
  new feature follows this; folders/experts each get a repo, a service, bridge methods,
  and routes in `main.py`.

---

## Pre-Work: Bugs To Fix First

These are existing defects in the LLM path. Fix the first two **before** building
Experts, because scheduled unattended experts will expose them hard.

### B1 — Shared `GeminiProcessor` is not concurrency-safe (HIGH)

`BriefingService` (`briefing_service.py:47`) and `PostDetailService`
(`post_detail_service.py:24`) each hold one long-lived `self.processor`. Every call does
`setup → connect → generate → disconnect`, and `disconnect()` nulls `self._client`
(`gemini_processor.py:188`). Two overlapping requests race: one nulls the client mid-flight
for the other. `self.model_name`, `self._client`, and `self._disabled_models` are shared
mutable state on a singleton.

**Fix:** make the client request-scoped (construct/use/discard per call), or guard the
critical section with a lock. Prefer request-scoped — the `google.genai` client is cheap.

### B2 — `_disabled_models` never resets (HIGH)

When a model hits a 429 + quota text (`gemini_processor.py:1033`) it is added to
`self._disabled_models` for the **process lifetime**. After the daily quota resets you
silently keep running on fallbacks until restart.

**Fix:** give disabled entries a TTL (e.g. reset after N minutes), or clear the set per
request. Pairs naturally with the B1 request-scoping fix.

### B3 — Synchronous Gemini calls block the event loop (MEDIUM)

Single-post methods (`analyze_single_post`, `extract_post_highlights`, `ask_single_post`,
`summarize_reddit_comments`) call `_generate_text_sync` directly and are invoked inline
from `async def` endpoints when `asyncMode` is false (e.g. `main.py:756`, `main.py:783`).
With retries/backoff this blocks the loop up to ~120s.

**Fix:** route the synchronous single-post path through `asyncio.to_thread` the way the
briefing methods already do (`gemini_processor.py:950`), or always use the async-job path.

### Lower-severity (note, fix opportunistically)

- **B4** — `NavigationPanel.tsx` is unused mock data (fake sources/counts/intel types,
  imported nowhere). Delete it; the Folders UI replaces its intent.
- **B5** — Model-name drift: `.env.example:51` = `gemini-3-flash-preview` vs
  `DEFAULT_MODEL` = `gemini-3.0-flash` (`gemini_processor.py:17`), reconciled only by the
  alias map (`gemini_processor.py:132`). Collapse to one source of truth.
- **B6** — `except Exception: pass` around every `disconnect()` (e.g.
  `briefing_service.py:215`) hides real errors.
- **B7** — No auth on any endpoint. Acceptable for localhost; decide before exposing the
  new config-write surfaces (folders/experts are world-writable otherwise).

---

## Pre-Work: The Enrichment Pipeline Is Not Wired Into Ingestion (HIGH)

**Symptom reported by the owner:** "stories and other features other than briefings are
not working."

**Root cause:** the automated cycle never builds evidence, story candidates, stories, or
the inbox. `scripts/run_scheduler.py::run_cycle()` runs exactly four stages:

1. sync sources config
2. `safe_ingest` → which runs **only** entity memory + event memory enrichment
   (`source_fetch_service.py:1257-1264`)
3. daily briefing
4. optional topic briefing

Everything else is manual-only:

| Feature | Only populated by | Result today |
|---|---|---|
| **Evidence foundation** | `EvidenceFoundationService` is instantiated only in the bridge (`insight_api_bridge.py:41`) and fired only by `/api/evidence/rebuild-for-{post,date}` | Evidence stays empty unless manually rebuilt |
| **Story candidates** | `story_timeline_service._refresh_candidates`, on-demand when one post's timeline is refreshed (`/api/posts/item/{id}/timeline/refresh`) | No bulk candidate generation ever happens |
| **Stories** | created only when a candidate is manually accepted (`stories_service` via `accept_candidate`, `story_timeline_service.py:66`) | `stories` table empty → `/api/stories` returns `[]` → Stories page looks dead |
| **Inbox** | `inbox_service.rebuild_inbox` via `/api/inbox/rebuild`; reads `list_story_candidates` (empty) + `list_post_candidates` | At best post-only, only after manual rebuild |

The chain **evidence → story candidates → accept → story → inbox** has no automated entry
point. This also degrades vertical/folder briefings: `_build_vertical_briefing_context`
(`briefing_service.py:1204`) reads evidence + story + entity links to cluster posts, so with
evidence/stories empty it silently falls back to the weak deterministic path — which is why
briefings feel "too divided."

### Fix

Add the missing stages to `run_cycle()` (and to `safe_ingest`) after posts persist, scoped
to the ingested date — following the same pattern entity/event memory already use:

1. `evidence_service.rebuild_for_date(today)` (or build per-post inside the fetch flow)
2. bulk story-candidate generation for the new posts (a batch version of
   `_refresh_candidates`, not one-post-at-a-time)
3. `inbox_service.rebuild_inbox(today)`

### Open question (resolve before wiring)

Should **story creation stay manual** (analyst accepts candidates) or should
high-confidence candidates **auto-promote** to stories? Today nothing promotes, so even
once candidates are generated, the `stories` table stays empty until manual acceptance.
A confidence threshold for auto-promotion would make Stories populate without manual work.

---

## Cross-Cutting: Langfuse Tracing

Do this early so everything built afterward is observable, and so B1/B2 are diagnosable.

**Integration point:** wrap `GeminiProcessor._generate_text_sync()`
(`gemini_processor.py:976`) — the single chokepoint every LLM call flows through. One span
captures: prompt, the model **actually** used after fallback, token estimate, latency, and
which fallback fired.

**Trace metadata:** thread `briefing_type`, `folder_id`, `expert_id`, `post_id` through so
you can later answer "which expert burns the most tokens / falls back most." Pass these as
optional context (e.g. a contextvar or an explicit `trace_meta` arg on the generate path).

**Config:** `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` via env. If
unset, tracing is a no-op — mirror the existing optional `GEMINI_API_KEY` pattern. Add the
three vars to `.env.example`.

**Acceptance:** generating any briefing produces a Langfuse trace showing the resolved
model, token estimate, and latency; disabling the env vars disables tracing with no errors.

---

## Phase 1 — Folders (manual grouping layer)

### Data model

```sql
CREATE TABLE folders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,                       -- optional, human-written
    system_prompt_default TEXT,            -- optional default persona seed for experts
    sort_order INT DEFAULT 999,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE source_folders (
    source_id UUID REFERENCES sources(id) ON DELETE CASCADE,
    folder_id UUID REFERENCES folders(id) ON DELETE CASCADE,
    PRIMARY KEY (source_id, folder_id)
);
```

Migration goes through the existing `db/migrate.py` mechanism.

### Layers (follow `BACKEND.md`)

- `db/repo_folders.py` — CRUD for folders; add/remove sources; list sources in a folder;
  list folders for a source; folder-with-counts (mirror
  `repo_sources.get_sources_with_post_counts`).
- `services/folders_service.py` — connection/transaction management over the repo.
- Bridge methods in `insight_api_bridge.py` — consistent `{success, data, ...}` envelopes.
- Routes in `main.py`:
  - `GET /api/folders` (with source + post counts)
  - `POST /api/folders`, `PUT /api/folders/{id}`, `DELETE /api/folders/{id}`
  - `POST /api/folders/{id}/sources` / `DELETE /api/folders/{id}/sources/{source_id}`

### Folder briefing

Reuse the existing topic pipeline, scoped to the folder's source set instead of all posts:

- Add a posts query: "posts for these source_ids in date range" (extend
  `PostsService` / `repo_posts.py`; the per-source range query already exists —
  generalize to a set of sources).
- New briefing entry point on `BriefingService`, e.g.
  `generate_folder_topic_briefing(folder_id, date_or_range)`, storing under
  `subject_type="folder_briefing"`, `subject_key=folder_id`, `variant="topics"`.
- Cache/refresh semantics identical to the existing daily-topic path.

### Frontend

- Sources sidebar / main surface grouped by folder (this is what replaces the mock
  `NavigationPanel`). Sources are real, counts are real (from folder-with-counts).
- Folder management UI in `SourcesConfig.tsx`: create folder, drag/assign sources,
  edit description.
- A "Generate folder briefing" action per folder.

### Open product question (resolve during build)

The global "everything" daily/topic briefing now overlaps folder briefings. Decide whether
the global briefing stays as a top-level pseudo-folder or is retired, to avoid generating
the same synthesis twice.

### Acceptance

- Can create folders, assign a source to multiple folders, and see real grouped counts.
- Can generate a topic briefing scoped to one folder; it appears in that folder's history.

---

## Phase 2 — Expert Framework

### The one genuinely new backend primitive

Today each briefing type has its prompt **hardcoded** inside `GeminiProcessor`
(`daily_briefing` at `gemini_processor.py:196`, `topic_briefing_with_numeric_ids` at
`:232`, etc.). Experts need the persona prompt injected at call time.

Add a **parameterized prompt path**:

```
GeminiProcessor.expert_briefing(
    posts,
    system_prompt: str,        # the expert persona
    focus_instructions: str,   # user's custom "focus more on X"
    output_contract: str,      # markdown vs topic-JSON shape, reuse existing contracts
) -> dict | str
```

It reuses `_format_posts`, `_generate_text` (`asyncio.to_thread`), fallback, and the JSON
extraction helpers. It must **not** introduce a second client or a second fallback engine.

### Data model

```sql
CREATE TABLE experts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    folder_id UUID REFERENCES folders(id) ON DELETE CASCADE,  -- experts run over folders
    system_prompt TEXT NOT NULL,
    focus_instructions TEXT,
    output_variant TEXT DEFAULT 'topics',   -- 'topics' | 'markdown'
    schedule TEXT,                          -- per-expert cadence (e.g. 'daily@08:00')
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### Layers

- `db/repo_experts.py`, `services/experts_service.py`, bridge methods, routes:
  - `GET /api/experts`, `POST /api/experts`, `PUT /api/experts/{id}`,
    `DELETE /api/experts/{id}`
  - `POST /api/experts/{id}/run` (on-demand generate)
- `BriefingService.generate_expert_briefing(expert_id, date_or_range)`:
  1. load expert → resolve folder → resolve folder's sources → fetch posts in range,
  2. call `processor.expert_briefing(posts, system_prompt, focus_instructions, ...)`,
  3. store under `subject_type="expert_briefing"`, `subject_key=expert_id`,
  4. save artifact references the same way other briefings do
     (`_save_artifact_references`).

### Scheduling (locked: per-expert)

- Extend `run_scheduler.py` to read enabled experts and enqueue a briefing job per expert
  on its own `schedule`. Reuse the operations/jobs machinery already used by ingestion.
- Each run is an unattended call to `generate_expert_briefing`; output lands in the
  expert's dated history automatically.
- Tag Langfuse traces with `expert_id` so per-expert cost/latency/fallback is visible.

### Frontend

- **Experts** entry in the Actions area — add a `FeatureCard` in `Index.tsx`
  (`featureCards`, ~`Index.tsx:24`) linking to `/experts`.
- Experts page: list experts; create/edit (pick folder, write system prompt + focus,
  set schedule); "Generate now"; view per-expert briefing history.

### Cost note

Token cost scales with `expert_count × schedule_frequency`. Four scheduled daily experts
≈ 4× current daily spend before Changelogs. Per-expert schedules are the throttle; Langfuse
makes the spend visible.

### Acceptance

- Can create an expert over a folder with a custom persona + focus.
- On-demand run produces an opinionated briefing distinct from the generic daily.
- A scheduled expert produces a briefing unattended, visible in its history and in Langfuse.

---

## Phase 3 — Changelogs Expert

A specialized expert whose **input is `(app, user's current version)`**, not source posts.
The product owner's requirement: *"I specify my version, and it tells me what updates
happened since, and whether the update is worth doing."*

### New parts

```sql
CREATE TABLE tracked_apps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    current_version TEXT,                   -- the user's installed version
    release_feed_url TEXT,                  -- GitHub Releases / RSS / release-notes page
    discussion_query TEXT,                  -- optional Reddit/HN search seed
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);
```

### Flow

1. Ingest release notes via the existing RSS connector (GitHub Releases expose an Atom
   feed; many apps have release RSS). Store as posts or as a dedicated changelog payload.
2. Diff `current_version → latest`: collect releases newer than the user's version.
3. Expert prompt summarizes **what changed**, **breaking changes / risk**, and a
   **verdict: worth updating?**
4. Pull **community opinion** by reusing `summarize_reddit_comments`
   (`gemini_processor.py:611`) over a Reddit/HN search for the release.
5. Store under `subject_type="expert_briefing"`, `variant="changelog"`,
   `subject_key=app_id`.

### Sequencing

Build **after** Phase 2 — it is "Expert framework + version-diff input + release ingest".
Reuses the parameterized prompt path and Reddit summarization.

### Acceptance

- Register an app + your version → receive a summary of changes since your version with a
  worth-it verdict and a community-opinion section.

---

## Phase 4 — Feed Discovery (manual-assign)

Given a topic or a seed URL, **propose** new sources to add. Kept simple and manual since
auto-clustering is out of scope:

1. Resolve candidate feeds (known-feed lookup / search / autodiscovery from a site URL).
2. Validate each candidate parses with the existing RSS connector.
3. Present validated candidates as **suggestions**; the user accepts and **manually picks
   the folder** to file them into (no auto-classification).

Depends only on Folders (Phase 1) and the RSS connector. No dependency on auto-clustering.

### Acceptance

- Enter a seed URL/topic → get a list of valid feeds → accept one → it is added as a source
  and assigned to a folder the user chooses.

---

## Recommended Build Order

1. **Wire the enrichment pipeline into the cycle** (evidence + story candidates + inbox in
   `run_cycle`/`safe_ingest`). Without this, Stories/Inbox stay empty and folder/expert
   briefings degrade to the weak fallback. Highest priority — it unblocks everything.
2. **Langfuse wrapper + B1/B2 processor fixes** (same file; do together).
3. **Phase 1 — Folders** (manual): removes the chaos immediately.
4. **Phase 2 — Expert framework** (parameterized prompt + experts table + per-expert
   schedule + Experts page): the headline win. Folder briefing == expert briefing.
5. **Phase 3 — Changelogs expert**.
6. **Phase 4 — Feed discovery**.

First shippable unit = **Folders + Expert framework** (Phases 1–2). That is what removes
the chaos and delivers the expert briefings.

---

## Explicitly Out Of Scope (this document)

- **Automatic folder suggestion / "Suggest folders" clustering.** Deferred to a separate
  plan. Folders here are manual only.
- Auto-classification of discovered feeds into folders (feed discovery is manual-assign).
- Hierarchical / nested folders (single level for now).
- Auth / multi-user (note B7; decide separately before exposing config-write endpoints).
