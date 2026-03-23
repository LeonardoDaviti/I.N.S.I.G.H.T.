# Source Adapters and Custom Archivators Implementation Plan

## Purpose

This document is for the future engineer who will implement custom acquisition logic for sources that do not provide sufficient feed support.

The goal is to improve coverage and quality of evidence intake for hard-to-archive sources.

## Why we are building this

Many high-value sources are not clean RSS publishers.
Some have weak feeds, incomplete feeds, missing comments, or unstable markup.
If INSIGHT depends only on standard feeds, it will miss valuable material.

## Why this method

Do not build random one-off scrapers.
Build a consistent source-adapter framework with:
- fetch policy
- parser/extractor
- canonicalization
- dedupe hooks
- archival metadata
- polite rate limits

## What we know now

- LessWrong does have a richer RSS feed than it first appears, including frontpage/curated views, author filtering, comment feeds, and shortform feeds, though only some options are officially supported.
- Gwern explicitly says Gwern.net does not provide an on-site RSS feed and instead points readers to monthly Substack RSS plus other alternatives.
- Hacker News has an official Firebase API for stories, comments, users, and list endpoints, while `hnrss.org` provides convenient custom RSS feeds for front page, searches, threads, users, favorites, and more.

This means:
- LessWrong may need adapter support, but not necessarily full scraping first
- Gwern is a clear custom-adapter candidate
- Hacker News should prefer official API ingestion for archival depth, with feed-style utilities only as optional helpers

## Product outcomes

The analyst should be able to add a hard source and know:
- how INSIGHT ingests it
- whether it is partial or deep archive quality
- whether comments are captured
- how often it refreshes
- whether custom parsing is in effect

## Data model

### `source_adapters`

Fields:
- `id UUID PK`
- `source_id UUID NOT NULL REFERENCES sources(id)`
- `adapter_type TEXT NOT NULL`
- `status TEXT NOT NULL DEFAULT 'active'`
- `config JSONB NOT NULL DEFAULT '{}'`
- `last_success_at TIMESTAMPTZ NULL`
- `last_error_at TIMESTAMPTZ NULL`
- `last_error_message TEXT NULL`
- `created_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`

### `source_fetch_artifacts`
Optional but useful for debugging.

Fields:
- `id UUID PK`
- `source_id UUID NOT NULL REFERENCES sources(id)`
- `adapter_id UUID NULL REFERENCES source_adapters(id)`
- `artifact_kind TEXT NOT NULL`
- `artifact_url TEXT NOT NULL`
- `artifact_hash TEXT NULL`
- `fetched_at TIMESTAMPTZ NOT NULL DEFAULT now()`
- `metadata JSONB NOT NULL DEFAULT '{}'`

## Adapter interface

Create a small adapter contract.

Example methods:
- `discover_items()`
- `fetch_item(item_ref)`
- `extract_posts(raw_item)`
- `normalize_post(extracted)`
- `discover_archive_range()` optional

Supported adapter types at first:
- `rss_plus`
- `html_scrape`
- `api_pull`
- `site_map`

## Code layout

Create:
- `backend/insight_core/adapters/base_adapter.py`
- `backend/insight_core/adapters/rss_plus_adapter.py`
- `backend/insight_core/adapters/html_scrape_adapter.py`
- `backend/insight_core/adapters/hackernews_adapter.py`
- `backend/insight_core/adapters/lesswrong_adapter.py`
- `backend/insight_core/adapters/gwern_adapter.py`

Do not put custom scraping logic directly in route handlers or in one giant fetch service file.

## Recommended source-specific strategy

### LessWrong
Start with feed-based adapter support.
Use feed parameters where stable.
Only escalate to heavier extraction if feed coverage proves insufficient.

### Gwern
Start with targeted scraping of index/navigation pages or other stable entrypoints.
Treat this as an adapter with careful canonicalization and strong caching.

### Hacker News
Use official Firebase API for archive depth and comments.
Optionally support `hnrss.org` style feeds only for convenience or special filtered monitors, not as the main archival substrate.

## Operational guidance

Politeness rules:
- conditional fetches when possible
- per-domain rate limiting
- backoff on repeated errors
- strong dedupe by canonical URL and content hash
- explicit source health status

## Phases

### Phase 1: adapter framework
- create base contract
- attach adapter metadata to sources
- support one adapter execution path in ingestion jobs

### Phase 2: first adapters
- LessWrong feed adapter
- Hacker News API adapter
- one custom scrape adapter, likely Gwern

### Phase 3: archive depth and comments
- add deeper historical crawl support where feasible
- add comment ingestion hooks for sources that support it

### Phase 4: monitoring and discovery integration
- allow monitors/watchlists to target adapter-backed sources
- surface source health and freshness in UI

## Common mistakes

### Mistake 1
Building one script per site with no shared contract.

### Mistake 2
Scraping when a reliable official API exists.

### Mistake 3
Treating partial-feed coverage as full archive coverage.

### Mistake 4
Ignoring canonicalization and duplicating the same source items.

## First practical milestone

INSIGHT can ingest one weak-feed source and one non-feed source through the shared adapter framework, with job visibility and dedupe intact.

## Final milestone

INSIGHT supports a growing library of hard-source adapters without turning ingestion into a brittle collection of one-off scripts.
