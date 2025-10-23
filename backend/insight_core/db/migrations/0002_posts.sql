-- 0002_posts.sql

-- 1) Create posts table
CREATE TABLE IF NOT EXISTS posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  external_id TEXT,
  published_at TIMESTAMPTZ,
  fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  title TEXT,
  content TEXT,
  content_html TEXT,
  lang TEXT,
  content_hash TEXT,
  media_urls JSONB NOT NULL DEFAULT '[]'::jsonb,
  categories JSONB NOT NULL DEFAULT '[]'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (url)
);

-- 2) Partial unique index on (source_id, external_id) when external_id is present
CREATE UNIQUE INDEX posts_source_external_unique ON posts(source_id, external_id) WHERE external_id IS NOT NULL;

-- 3) Helpful indexes
CREATE INDEX posts_published_idx ON posts(published_at);
CREATE INDEX posts_source_idx ON posts(source_id);
CREATE INDEX posts_categories_gin ON posts USING GIN (categories);