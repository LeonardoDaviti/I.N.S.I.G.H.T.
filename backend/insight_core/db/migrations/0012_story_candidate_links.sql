-- 0012_story_candidate_links.sql

CREATE TABLE IF NOT EXISTS story_candidate_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  candidate_post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  candidate_story_id UUID NULL REFERENCES stories(id) ON DELETE SET NULL,
  retrieval_method TEXT NOT NULL,
  retrieval_score REAL NOT NULL DEFAULT 0,
  decision_status TEXT NOT NULL DEFAULT 'proposed',
  decision_reason TEXT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (source_post_id, candidate_post_id)
);

CREATE INDEX IF NOT EXISTS story_candidate_links_source_idx
  ON story_candidate_links(source_post_id, decision_status, retrieval_score DESC, updated_at DESC);
CREATE INDEX IF NOT EXISTS story_candidate_links_candidate_idx
  ON story_candidate_links(candidate_post_id);
CREATE INDEX IF NOT EXISTS story_candidate_links_story_idx
  ON story_candidate_links(candidate_story_id);
