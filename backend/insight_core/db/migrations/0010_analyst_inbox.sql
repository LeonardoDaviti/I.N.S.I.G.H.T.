-- 0010_analyst_inbox.sql

CREATE TABLE IF NOT EXISTS inbox_batches (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  scope_type TEXT NOT NULL DEFAULT 'daily_queue',
  scope_value TEXT NULL,
  generated_for_date DATE NULL,
  status TEXT NOT NULL DEFAULT 'ready',
  item_count INTEGER NOT NULL DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS inbox_batches_scope_idx
  ON inbox_batches(scope_type, generated_for_date DESC, created_at DESC);
CREATE INDEX IF NOT EXISTS inbox_batches_status_idx
  ON inbox_batches(status);
CREATE INDEX IF NOT EXISTS inbox_batches_created_idx
  ON inbox_batches(created_at DESC);

CREATE TABLE IF NOT EXISTS inbox_items (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  batch_id UUID NOT NULL REFERENCES inbox_batches(id) ON DELETE CASCADE,
  target_type TEXT NOT NULL,
  target_id UUID NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  priority_score REAL NOT NULL DEFAULT 0,
  novelty_score REAL NOT NULL DEFAULT 0,
  evidence_score REAL NOT NULL DEFAULT 0,
  duplication_penalty REAL NOT NULL DEFAULT 0,
  source_priority_score REAL NOT NULL DEFAULT 0,
  reason_summary TEXT NULL,
  reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  surfaced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  acted_at TIMESTAMPTZ NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (batch_id, target_type, target_id)
);

CREATE INDEX IF NOT EXISTS inbox_items_batch_idx ON inbox_items(batch_id);
CREATE INDEX IF NOT EXISTS inbox_items_status_idx ON inbox_items(status);
CREATE INDEX IF NOT EXISTS inbox_items_target_idx ON inbox_items(target_type, target_id);
CREATE INDEX IF NOT EXISTS inbox_items_priority_idx ON inbox_items(priority_score DESC);
CREATE INDEX IF NOT EXISTS inbox_items_acted_idx ON inbox_items(acted_at DESC);

ALTER TABLE analyst_actions
  ADD COLUMN IF NOT EXISTS inbox_item_id UUID NULL REFERENCES inbox_items(id) ON DELETE SET NULL;

ALTER TABLE analyst_actions
  ADD COLUMN IF NOT EXISTS actor_id TEXT NULL;

CREATE INDEX IF NOT EXISTS analyst_actions_action_idx ON analyst_actions(action_type);
CREATE INDEX IF NOT EXISTS analyst_actions_inbox_item_idx ON analyst_actions(inbox_item_id);

