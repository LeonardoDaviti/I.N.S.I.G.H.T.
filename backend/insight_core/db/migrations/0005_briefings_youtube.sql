ALTER TABLE posts
ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS posts_metadata_gin
ON posts
USING GIN (metadata);

CREATE TABLE IF NOT EXISTS briefings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  subject_type TEXT NOT NULL,
  subject_key TEXT NOT NULL,
  variant TEXT NOT NULL DEFAULT 'default',
  render_format TEXT NOT NULL DEFAULT 'markdown',
  title TEXT,
  content TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(subject_type, subject_key, variant)
);

CREATE INDEX IF NOT EXISTS briefings_subject_idx
ON briefings(subject_type, subject_key);

CREATE TABLE IF NOT EXISTS youtube_watch_progress (
  video_id TEXT PRIMARY KEY,
  source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
  video_url TEXT NOT NULL,
  title TEXT,
  duration_seconds INTEGER,
  progress_seconds INTEGER NOT NULL DEFAULT 0,
  progress_percent NUMERIC(5,2),
  notes_markdown TEXT,
  watch_sessions INTEGER NOT NULL DEFAULT 0,
  completed BOOLEAN NOT NULL DEFAULT FALSE,
  last_watched_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS youtube_watch_progress_source_idx
ON youtube_watch_progress(source_id);
