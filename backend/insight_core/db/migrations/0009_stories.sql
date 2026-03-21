-- 0009_stories.sql

CREATE TABLE IF NOT EXISTS stories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_title TEXT NOT NULL,
  canonical_summary TEXT NULL,
  story_kind TEXT NOT NULL DEFAULT 'other',
  status TEXT NOT NULL DEFAULT 'active',
  anchor_post_id UUID NULL REFERENCES posts(id) ON DELETE SET NULL,
  anchor_confidence REAL NOT NULL DEFAULT 0,
  first_seen_at TIMESTAMPTZ NULL,
  last_seen_at TIMESTAMPTZ NULL,
  created_by_method TEXT NOT NULL DEFAULT 'auto',
  resolution_version TEXT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS stories_status_last_seen_idx ON stories(status, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS stories_story_kind_idx ON stories(story_kind);
CREATE INDEX IF NOT EXISTS stories_anchor_post_idx ON stories(anchor_post_id);
CREATE INDEX IF NOT EXISTS stories_first_seen_idx ON stories(first_seen_at DESC);
CREATE INDEX IF NOT EXISTS stories_last_seen_idx ON stories(last_seen_at DESC);

CREATE TABLE IF NOT EXISTS story_posts (
  story_id UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  relevance_score REAL NOT NULL DEFAULT 0,
  anchor_score REAL NOT NULL DEFAULT 0,
  is_anchor_candidate BOOLEAN NOT NULL DEFAULT FALSE,
  evidence_weight REAL NOT NULL DEFAULT 0,
  added_by_method TEXT NOT NULL DEFAULT 'auto',
  added_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (story_id, post_id)
);

CREATE INDEX IF NOT EXISTS story_posts_story_idx ON story_posts(story_id);
CREATE INDEX IF NOT EXISTS story_posts_post_idx ON story_posts(post_id);
CREATE INDEX IF NOT EXISTS story_posts_role_idx ON story_posts(role);

CREATE TABLE IF NOT EXISTS story_updates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  story_id UUID NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  update_date DATE NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL,
  importance_score REAL NOT NULL DEFAULT 0,
  created_by_method TEXT NOT NULL DEFAULT 'auto',
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS story_updates_story_date_idx ON story_updates(story_id, update_date);
CREATE INDEX IF NOT EXISTS story_updates_date_importance_idx ON story_updates(update_date, importance_score DESC);

CREATE TABLE IF NOT EXISTS story_update_posts (
  story_update_id UUID NOT NULL REFERENCES story_updates(id) ON DELETE CASCADE,
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  role TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (story_update_id, post_id)
);

CREATE INDEX IF NOT EXISTS story_update_posts_update_idx ON story_update_posts(story_update_id);
CREATE INDEX IF NOT EXISTS story_update_posts_post_idx ON story_update_posts(post_id);
