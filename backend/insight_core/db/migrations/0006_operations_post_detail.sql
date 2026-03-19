CREATE TABLE IF NOT EXISTS system_settings (
  key TEXT PRIMARY KEY,
  value JSONB NOT NULL DEFAULT '{}'::jsonb,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_runs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  trigger TEXT NOT NULL DEFAULT 'manual',
  source_id UUID REFERENCES sources(id) ON DELETE SET NULL,
  message TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS job_runs_started_idx ON job_runs(started_at DESC);
CREATE INDEX IF NOT EXISTS job_runs_status_idx ON job_runs(status);
CREATE INDEX IF NOT EXISTS job_runs_source_idx ON job_runs(source_id);

CREATE TABLE IF NOT EXISTS post_notes (
  post_id UUID PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  notes_markdown TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS post_ai_cache (
  post_id UUID PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  summary_markdown TEXT,
  summary_model TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
