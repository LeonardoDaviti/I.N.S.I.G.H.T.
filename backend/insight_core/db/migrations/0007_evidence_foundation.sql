ALTER TABLE posts
ADD COLUMN IF NOT EXISTS language_code TEXT NULL,
ADD COLUMN IF NOT EXISTS language_confidence REAL NULL,
ADD COLUMN IF NOT EXISTS normalized_url TEXT NULL,
ADD COLUMN IF NOT EXISTS canonical_url TEXT NULL,
ADD COLUMN IF NOT EXISTS url_host TEXT NULL,
ADD COLUMN IF NOT EXISTS title_hash TEXT NULL,
ADD COLUMN IF NOT EXISTS normalization_version TEXT NULL,
ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS posts_language_code_idx ON posts(language_code);
CREATE INDEX IF NOT EXISTS posts_normalized_url_idx ON posts(normalized_url);
CREATE INDEX IF NOT EXISTS posts_url_host_idx ON posts(url_host);
CREATE INDEX IF NOT EXISTS posts_title_hash_idx ON posts(title_hash);
CREATE INDEX IF NOT EXISTS posts_content_hash_idx ON posts(content_hash);
CREATE INDEX IF NOT EXISTS posts_enriched_at_idx ON posts(enriched_at DESC);

CREATE TABLE IF NOT EXISTS artifacts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  artifact_type TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  normalized_url TEXT NOT NULL UNIQUE,
  url_host TEXT NULL,
  display_title TEXT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS artifacts_type_idx ON artifacts(artifact_type);
CREATE INDEX IF NOT EXISTS artifacts_host_idx ON artifacts(url_host);

CREATE TABLE IF NOT EXISTS post_artifacts (
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  artifact_id UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  is_primary BOOLEAN NOT NULL DEFAULT FALSE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (post_id, artifact_id, relation_type)
);

CREATE INDEX IF NOT EXISTS post_artifacts_artifact_idx ON post_artifacts(artifact_id);
CREATE INDEX IF NOT EXISTS post_artifacts_primary_idx ON post_artifacts(post_id, is_primary DESC);

CREATE TABLE IF NOT EXISTS post_relations (
  from_post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  to_post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL,
  method TEXT NOT NULL,
  confidence REAL NOT NULL DEFAULT 0,
  job_run_id UUID NULL REFERENCES job_runs(id) ON DELETE SET NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (from_post_id, to_post_id, relation_type)
);

CREATE INDEX IF NOT EXISTS post_relations_to_idx ON post_relations(to_post_id);
CREATE INDEX IF NOT EXISTS post_relations_type_idx ON post_relations(relation_type);
CREATE INDEX IF NOT EXISTS post_relations_job_idx ON post_relations(job_run_id);
