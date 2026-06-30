-- 0014_experts.sql
-- Experts: a briefing persona that runs over one folder's sources.

CREATE TABLE IF NOT EXISTS experts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  folder_id UUID NOT NULL REFERENCES folders(id) ON DELETE CASCADE,
  system_prompt TEXT NOT NULL,
  focus_instructions TEXT NULL,
  output_variant TEXT NOT NULL DEFAULT 'topics',
  lookback_days INTEGER NOT NULL DEFAULT 7,
  schedule TEXT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS experts_folder_idx ON experts(folder_id);
CREATE INDEX IF NOT EXISTS experts_enabled_idx ON experts(enabled);
