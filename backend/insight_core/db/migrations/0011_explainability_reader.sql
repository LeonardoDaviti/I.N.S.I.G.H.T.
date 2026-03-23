-- 0011_explainability_reader.sql

ALTER TABLE post_ai_cache
  ADD COLUMN IF NOT EXISTS one_sentence_takeaway TEXT NULL,
  ADD COLUMN IF NOT EXISTS highlights_updated_at TIMESTAMPTZ NULL;

CREATE TABLE IF NOT EXISTS post_highlights (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  highlight_text TEXT NOT NULL,
  highlight_kind TEXT NOT NULL DEFAULT 'evidence',
  start_char INT NULL,
  end_char INT NULL,
  language_code TEXT NULL,
  importance_score REAL NOT NULL DEFAULT 0,
  commentary TEXT NULL,
  extractor_name TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS post_highlights_post_idx ON post_highlights(post_id);
CREATE INDEX IF NOT EXISTS post_highlights_post_importance_idx ON post_highlights(post_id, importance_score DESC);

CREATE TABLE IF NOT EXISTS artifact_post_references (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_type TEXT NOT NULL,
  artifact_id UUID NOT NULL,
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  highlight_id UUID NULL REFERENCES post_highlights(id) ON DELETE SET NULL,
  reference_role TEXT NOT NULL DEFAULT 'supporting',
  display_label TEXT NULL,
  order_index INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS artifact_post_references_artifact_idx
  ON artifact_post_references(artifact_type, artifact_id, order_index);
CREATE INDEX IF NOT EXISTS artifact_post_references_post_idx
  ON artifact_post_references(post_id);
CREATE INDEX IF NOT EXISTS artifact_post_references_highlight_idx
  ON artifact_post_references(highlight_id);

CREATE TABLE IF NOT EXISTS post_interactions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  interaction_type TEXT NOT NULL,
  interaction_value JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS post_interactions_post_idx ON post_interactions(post_id);
CREATE INDEX IF NOT EXISTS post_interactions_type_idx ON post_interactions(interaction_type);
CREATE INDEX IF NOT EXISTS post_interactions_created_idx ON post_interactions(created_at DESC);
