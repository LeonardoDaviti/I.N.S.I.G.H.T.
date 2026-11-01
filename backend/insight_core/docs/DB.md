# I.N.S.I.G.H.T. database (Mark IX)

PostgreSQL 15. The schema is the sum of `../db/migrations/0001` to `0053`; this file says what
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
- There is no `0048`, `0049` or `0050`: no commit on any branch created a file with those
  numbers (`git log --all`). The runner doesn't care: a version is its file name.
- `0036`, `0038`, `0043`, `0045`, `0047`, `0051`, `0052` and `0053` rewrite or delete stored rows
  once (each header says what, and what it measured); `./update` lists the pending ones first.

### SQL functions, and the migration that defines each now

| Function | What it is | Defined last in |
|---|---|---|
| `post_search_vector`, `search_query` | the search index's text and the query, NFKC first | `0052` |
| `search_vector_version()` | the search rule's version (3); `posts.search_version` older: refilled | `0052` |
| `search_version_parts`, `search_vector_with_parts`, `search_parts_phrase` | version words (`k3.1`) as parts | `0042` |
| `posts_search_vector_fill`, `sources_search_name_changed` | the triggers that keep `search_vector` | `0042` |
| `source_search_name` | a source's name as search reads it | `0033` |
| `post_title_key` | two titles the same: case, whitespace, HTML entities | `0041` (as `0038`) |
| `platform_post_address`, `post_body_opening`, `same_post_body` | one post at two addresses (0052, A5) | `0052` |
| `fold_telegram_albums` | a Telegram album's pictures fold into one post | `0053` |

## Tables

### sources
What to fetch.
- `platform`, `handle_or_url` (unique together), `enabled`, `settings` (jsonb: display name,
  fetch delay, priority, `max_posts_per_fetch`, archive status under `settings.archive`).
- `in_main_digest`: false keeps the source out of the "all" feed while it is still ingested.
- `tidy_kept_at` (0035): when Keep was pressed on a source marked quiet or never opened; its
  marks hide for 90 days from then.
- Cadence (0019): `mean_gap_seconds`, `cadence_sample_size`, `cadence_tier`
  (`fast|medium|slow|unknown`), `cadence_computed_at`, `fetch_interval_hours_override`.

### source_fetch_state
One row per source: the scheduler's memory. Last attempt, success, outcome
(`healthy|empty|error|unavailable`), trigger, posts fetched, last error,
`consecutive_failures`, `next_retry_at` (backoff), the last decision and `next_due_at`.
The source doctor's memory (0032): `doctor_checked_at` and `doctor_finding`
(`{replacement: {kind, url, title, found, prefix} | null, dismissed}`). Deleted with its source.

### source_fetch_validators
Conditional fetching (0034): per (source, address it reads), the `etag` and `last_modified` its
last full answer gave and `learned_at`, sent back so an unchanged address answers 304. Older than
a week: not sent.

### posts
Every fetched post, live or archived, in one format.
- `url` is unique and never changes; `(source_id, external_id)` is unique when
  `external_id` is set. Saving upserts on `url`.
- Content: `title`, `content`, `content_html`, `media_urls` (jsonb), `categories` (jsonb),
  `metadata` (jsonb: per-kind extras such as YouTube chapters, fetched Reddit comments, collision notes).
- Dates: `published_at` (may be null), `fetched_at` (first seen, never moved), `surfaced_at`
  (0037: put in front of you later than its date says, a page new to you or a watched page that
  changed; also an undated first fetch's place, 0053). The feed orders by
  `COALESCE(surfaced_at, published_at, fetched_at)`.
- Computed on every save (`utils/post_fields.py`): `content_hash`, `normalized_url`,
  `canonical_url`, `url_host`, `language_code`, `language_confidence`. `lang` is the
  language the source declared.
- Search (0033, 0042, 0052): `search_vector` (tsvector, kept by a trigger) and `search_version`,
  the rule that made it (NULL: 0033's). The API's start refills older versions in the background.
- Links: `links_scanned_at`, when its outside links were read into `post_links` (NULL: not yet;
  the story job reads them, 500 a transaction).
- X (0047): `author`, a tweet's account; `reposted_by`, the accounts of your sources that
  reposted it. A tweet's `normalized_url` is `x.com/<user>/status/<id>` whatever host brought it.
- `album_of` (0051, 0053): the post a Telegram album's text-less picture belongs to; the feed,
  its counts and search leave the piece out.
- Two rows are one post when they share `normalized_url` and `post_title_key(title)` (0038,
  0041), or for one source, the same title within a day and the same body (0052). The saver
  keeps it so (`repo_posts.upsert_post`).
- Deleting a source deletes its posts.

### post_watch
A watched page (0037, a source with `settings.watch_changes`): the hash of its article text, the
date the page states it changed, its validators, and when it was last checked, changed and is
due again. Cascades with the post and the source.

### post_reader_state
Read and starred state per post (`read_at`, `starred_at`). The feed and the unread counts
read it. `later_at` (0031): in Later since then. `resume_block`, `resume_blocks` (0030): where a
long post was left, as the top text block in view and the body's block count.

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
Key/value jsonb: `scheduler_config` (tick minutes, daily-work interval), `scheduler_state`
(last and next tick, last and next daily work), and `sources_json_imported` (when a start first
imported sources.json into this database, issue 0071: later starts don't import again).

### youtube_watch_progress
Watch position per YouTube video: progress, duration, completed, sessions.

## Derived tables: stories, trees, News, Classics, Discover

Written by the story job (`services/stories_service.py`) and recomputable from the posts, except
the two `*_hidden` tables, which are yours. The job writes only rows that differ.

### post_links
The outside links inside each post (0039, `utils/post_links.py`): `target_url` (normalized as
`posts.normalized_url`, so a link to a stored post joins it), `target_site`, `position` (0: its
first outside link), `link_text` (the link's own words), `boilerplate` (its source's signature
or its own site: nothing reads it).

### stories, story_posts, story_mentions
- `stories` (0039, 0044): a group of posts from 2+ sources, keyed by its first post: `first_at`,
  `voices` (independent voices), and when the origin is an outside page 2+ of its posts link,
  `origin_url`, `origin_title`, `origin_linked_by`.
- `story_posts`: each post's story (one per post), its `role` (report, share), `reasons` (why it
  joined: address, text, title, link, citation, ...), `voice`, and its tree (0044, 0047):
  `parent_id` (the post it came from), `parent_reason` (address, citation, copy, repost, thread,
  quote, time, none) and `parent_url` (an outside page it hangs from).
- `story_mentions`: a roundup mentions the stories of its other links; nothing joins by them.

### news_stories, news_posts
News (0040): `news_stories` (`first_at`, `voices`, `reports`, `shares`, `mentions`, `score`) and
each post's News story in `news_posts` (`role`, `voice`, and `name`, the surging name that joined
it, NULL when it joined through its story). The job keeps its window's stories.

### classics, classic_hidden
Classics (0040): a page 2+ of your voices linked 30+ days apart (`target_url`, `post_id` when it
is stored, `voices`, `first_at`, `last_at`, `title`, `citers` jsonb). `classic_hidden`: the ones
you hid; they never come back.

### discover_addresses, discover_hidden
- `discover_addresses` (0046): what Discover reads of each linked address, worked out once:
  `key` (a site, or a platform's account), `site`, `platform`, `article`, and `rules`, the
  version of the rules that wrote it (a row of older rules is worked out again).
- `discover_hidden` (0039): suggestions you hid ("Not interested") and the sites of sources
  you removed, never suggested again.

### system_settings keys the job and the API keep
`stories` (the last run: `rules`, `full_at`, `seconds`, `computed_at`), `discover_counts`
(Discover's counts between runs, 0067) and `stored_bodies` (the version of the stored-body repair that ran, `posts_service.py`).

### schema_migrations
The applied migration files.

## Invariants
- `posts.url` is globally unique and never altered.
- Deleting a source cascades to its posts, fetch state and track links; posts cascade to
  their reader state, interactions and notes. `job_runs` and `youtube_watch_progress` keep
  their rows with `source_id` set to null.
- Source fetch history lives in `source_fetch_state`; archive status in
  `sources.settings.archive`.
