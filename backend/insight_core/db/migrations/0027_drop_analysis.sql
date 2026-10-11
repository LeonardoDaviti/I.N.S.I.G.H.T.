-- 0027_drop_analysis.sql (issue 0005 slice 6, retire analysis: schema)
--
-- Analysis was retired from the code in slice 4; the tag mark-ix-analysis-archive holds it.
-- This drops the 30 tables only analysis read or wrote, and the posts columns only analysis
-- used, and the milestones switch on folders. Back up the database before this runs
-- (DEPLOYMENT.md, "Retiring analysis").
--
-- Kept: sources, posts, source_fetch_state, post_reader_state, post_interactions,
-- post_notes (the owner's own writing), folders, source_folders, credentials, job_runs,
-- system_settings, youtube_watch_progress, schema_migrations; and on posts the content
-- hash, normalized and canonical URL, URL host and language.
--
-- Children go first, so no foreign key is left pointing at a dropped table. Their indexes
-- go with them. Every statement is IF EXISTS, so re-running is a no-op.

-- Inbox and analyst actions (0008, 0010). analyst_actions points at inbox_items.
DROP TABLE IF EXISTS analyst_actions;
DROP TABLE IF EXISTS inbox_items;
DROP TABLE IF EXISTS inbox_batches;

-- Stories (0009, 0012).
DROP TABLE IF EXISTS story_candidate_links;
DROP TABLE IF EXISTS story_update_posts;
DROP TABLE IF EXISTS story_updates;
DROP TABLE IF EXISTS story_posts;
DROP TABLE IF EXISTS stories;

-- Entity and event memory, source profiles (0008).
DROP TABLE IF EXISTS event_evidence;
DROP TABLE IF EXISTS event_entities;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS post_entities;
DROP TABLE IF EXISTS mention_entity_candidates;
DROP TABLE IF EXISTS entity_aliases;
DROP TABLE IF EXISTS entity_mentions;
DROP TABLE IF EXISTS entities;
DROP TABLE IF EXISTS source_profiles;

-- Evidence and explainability (0007, 0011). artifact_post_references points at
-- post_highlights.
DROP TABLE IF EXISTS artifact_post_references;
DROP TABLE IF EXISTS post_highlights;
DROP TABLE IF EXISTS post_artifacts;
DROP TABLE IF EXISTS post_relations;
DROP TABLE IF EXISTS artifacts;

-- Post summaries (0006, 0011).
DROP TABLE IF EXISTS post_ai_cache;

-- Topics (0003).
DROP TABLE IF EXISTS topic_connections;
DROP TABLE IF EXISTS topic_posts;
DROP TABLE IF EXISTS topics;

-- Briefings (0005), experts (0014), milestones (0017).
DROP TABLE IF EXISTS briefings;
DROP TABLE IF EXISTS experts;
DROP TABLE IF EXISTS milestone_overrides;
DROP TABLE IF EXISTS milestone_lanes;

-- posts: the memory pivots (0008) and the evidence bookkeeping only analysis read (0007).
-- Their indexes (posts_title_hash_idx, posts_enriched_at_idx) go with the columns.
ALTER TABLE posts
  DROP COLUMN IF EXISTS title_original,
  DROP COLUMN IF EXISTS body_original,
  DROP COLUMN IF EXISTS title_pivot,
  DROP COLUMN IF EXISTS summary_pivot,
  DROP COLUMN IF EXISTS title_pivot_version,
  DROP COLUMN IF EXISTS summary_pivot_version,
  DROP COLUMN IF EXISTS title_hash,
  DROP COLUMN IF EXISTS normalization_version,
  DROP COLUMN IF EXISTS enriched_at;

-- folders: the milestones switch (0018). Nothing reads it.
ALTER TABLE folders DROP COLUMN IF EXISTS use_global_milestone_lanes;
