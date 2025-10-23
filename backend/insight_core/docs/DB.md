# I.N.S.I.G.H.T. Database (Mark VI)



### How to update migrated table

1. drop table

2. drop migration schema from schema_migrations

3. update migration of table in file

4. run migrate.py


## Tables

### sources
- Columns: id (uuid), platform (text), handle_or_url (text), enabled (bool), settings (jsonb), created_at, updated_at
- Constraints: UNIQUE(platform, handle_or_url)
- Why: Registry of what to fetch + per-source fetch state in `settings`
- Notes: examples of settings for RSS/Telegram cursors

### posts
- Columns: id, source_id (fk), url (unique), external_id (nullable), published_at, fetched_at, title, text, content_html, lang, content_hash, keywords (jsonb), created_at, updated_at
- Constraints/Indexes: UNIQUE(url); partial unique (source_id, external_id) when external_id is not null; indexes on published_at, source_id, keywords (GIN)
- Why: immutable archive of fetched content; dedupe on url; integrity via FK

### topics
- Columns: id, title, summary (nullable), created_at
- Join: topic_posts(topic_id, post_id), FKs with ON DELETE CASCADE, indexes

### clusters
- Columns: id, day (date), method (text), signature (text nullable), created_at
- Join: cluster_posts(cluster_id, post_id); indexes
- Why: near-duplicate grouping per day; supports meta-posts

### meta_posts
- Columns: id, cluster_id (fk), title, summary (nullable), created_at
- Join: meta_post_sources(meta_post_id, post_id); indexes
- Why: synthesized narrative for a cluster; cite sources explicitly

## Invariants
- posts.url is globally unique and never altered.
- A post may appear in multiple clusters (design choice).
- Deleting a source cascades to its posts; deleting a cluster cascades to joins.
- Source fetch cursors live in `sources.settings` (jsonb) by platform.

## Write patterns
- Upsert sources via (platform, handle_or_url).
- Insert posts with ON CONFLICT (url) DO UPDATE (refresh title/text/fetched_at).
- Compute content_hash over normalized text/html for dedupe/cluster seeds.

## Read patterns
- Daily briefing = posts where published_at in [day, day+1), ordered; plus topics/clusters/meta_posts when available.

## Future migrations
- embeddings table.
- audit tables (optional).
- platform-level `enabled` (optional).