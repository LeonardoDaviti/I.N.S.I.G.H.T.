# I.N.S.I.G.H.T. database (Mark IX)

PostgreSQL 15. The schema is the sum of `../db/migrations/0001` to `0027`; this file says what
each table is for. The runtime database is the one `DATABASE_URL` points at.

## Migrations

- `db/migrate.py` applies every pending `.sql` file in order, in one transaction, under a
  Postgres advisory lock, so the backend and ingestion containers can both run it at start.
  Each applied file is recorded in `schema_migrations` and never runs again.
- Never edit an applied migration. Change the schema with a new numbered file, written so a
  re-run is a no-op (`IF EXISTS`, `IF NOT EXISTS`, `ON CONFLICT DO NOTHING`).
- No `VACUUM`, `CREATE INDEX CONCURRENTLY` or `ALTER TYPE ... ADD VALUE`: they cannot run
  inside the migration transaction.
- `0026` dropped the unused cluster and meta-post tables; `0027` dropped the analysis tables
  and post columns (issue 0005). The tag `mark-ix-analysis-archive` holds the analysis code.

## Tables

### sources
What to fetch.
- `platform`, `handle_or_url` (unique together), `enabled`, `settings` (jsonb: display name,
  fetch delay, priority, `max_posts_per_fetch`, archive status under `settings.archive`).
- `in_main_digest`: false keeps the source out of the "all" feed while it is still ingested.
- Cadence (0019): `mean_gap_seconds`, `cadence_sample_size`, `cadence_tier`
  (`fast|medium|slow|unknown`), `cadence_computed_at`, `fetch_interval_hours_override`.

### source_fetch_state
One row per source: the scheduler's memory. Last attempt, success, outcome
(`healthy|empty|error|unavailable`), trigger, posts fetched, last error,
`consecutive_failures`, `next_retry_at` (backoff), the last decision and `next_due_at`.
Deleted with its source.

### posts
Every fetched post, live or archived, in one format.
- `url` is unique and never changes; `(source_id, external_id)` is unique when
  `external_id` is set. Saving upserts on `url`.
- Content: `title`, `content`, `content_html`, `media_urls` (jsonb), `categories` (jsonb),
  `metadata` (jsonb: per-kind extras such as YouTube chapters, fetched Reddit comments, collision notes).
- Dates: `published_at` (may be null), `fetched_at` (first seen, never moved). The feed
  orders by `COALESCE(published_at, fetched_at)`.
- Computed on every save (`utils/post_fields.py`): `content_hash`, `normalized_url`,
  `canonical_url`, `url_host`, `language_code`, `language_confidence`. `lang` is the
  language the source declared.
- Deleting a source deletes its posts.

### post_reader_state
Read and starred state per post (`read_at`, `starred_at`). The feed and the unread counts
read it.

### post_interactions
An append-only log per post: `opened`, `reading_session` (with `duration_seconds`),
`favorited`, `unfavorited`. The post page's reader state (open count, reading time) is
built from it.

### post_notes
Markdown notes the owner wrote on a post. Kept as data; no screen shows them now.

### folders, source_folders
Tracks: named groups of sources (`kind`, `sort_order`, `exclude_from_main_digest`,
`match_keywords`). `source_folders` is the many-to-many link.

### credentials
The secrets added under Sources → Connections, one row per `(provider, key)`: Fernet
`ciphertext`, `last4`, and the last test result. The key is outside the database
(`INSIGHT_SECRET_KEY` or the `insight_secrets` volume).

### job_runs
One row per background job (`ingestion_run`, `scheduler_cycle`, `archive_source`; old rows
may be `reddit_comments_fetch`): status, trigger, message and a jsonb `payload` with progress events
and the run report. Pruned after 30 days by the daily work.

### system_settings
Key/value jsonb: `scheduler_config` (tick minutes, daily-work interval, sources.json sync)
and `scheduler_state` (last and next tick, last and next daily work).

### youtube_watch_progress
Watch position per YouTube video: progress, duration, completed, sessions.

### schema_migrations
The applied migration files.

## Invariants
- `posts.url` is globally unique and never altered.
- Deleting a source cascades to its posts, fetch state and track links; posts cascade to
  their reader state, interactions and notes. `job_runs` and `youtube_watch_progress` keep
  their rows with `source_id` set to null.
- Source fetch history lives in `source_fetch_state`; archive status in
  `sources.settings.archive`.
