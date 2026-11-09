-- 0092_markx_story_window.sql (issue 0144, Stealth v10.10: stories for all history, and the person page)
--
-- 1. mx_entity_sources: the owner's answer to "These sources are <name>: yes / no" on an entity's page (0144 B1), for
--    a source whose handle, profile or site names the entity by identity's key. One row an answer, never deleted:
--    the newest row of an (entity, source) counts. entity_id is the entity's root when answered (readers go through
--    the merges). A source whose confirmed voice (voices.entity_id) is the entity needs no answer.
-- 2. mx_story_samples: the old stories offered for labelling on an entity's page (0144 C): 10 a page visited, 30 a
--    day at most. One row a story (offered once); first_at is the story's first post's time when offered.
-- 3. mx_story_sample_labels: the owner's right / wrong / missed on an offered story, one row an answer, the newest
--    counts. Precision of the stories older than 30 days decides whether the story window stays at "everything".
-- The story window itself (`story_window_days`, its backfill's progress `story_backfill`) lives in mx_settings: no
-- row is written here (no row: 30 days, as before).
--
-- No foreign key (Mark X's tables are its own; the tests truncate mx_entities and mx_stories alone).
-- Idempotent. Nothing is deleted.

CREATE TABLE IF NOT EXISTS mx_entity_sources (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id  uuid NOT NULL,
  source_id  uuid NOT NULL,
  answer     text NOT NULL CHECK (answer IN ('yes', 'no')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS mx_entity_sources_entity_idx ON mx_entity_sources (entity_id, source_id, created_at DESC);

CREATE TABLE IF NOT EXISTS mx_story_samples (
  story_id   uuid PRIMARY KEY,
  entity_id  uuid,
  first_at   timestamptz,
  offered_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_story_samples_offered_idx ON mx_story_samples (offered_at);

CREATE TABLE IF NOT EXISTS mx_story_sample_labels (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  story_id   uuid NOT NULL,
  answer     text NOT NULL CHECK (answer IN ('right', 'wrong', 'missed')),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS mx_story_sample_labels_story_idx ON mx_story_sample_labels (story_id, created_at DESC);
