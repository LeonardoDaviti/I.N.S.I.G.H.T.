-- 0008_entity_event_memory.sql

-- Phase 0: explicit originals + pivot fields on posts.
ALTER TABLE posts
  ADD COLUMN IF NOT EXISTS title_original TEXT,
  ADD COLUMN IF NOT EXISTS body_original TEXT,
  ADD COLUMN IF NOT EXISTS title_pivot TEXT,
  ADD COLUMN IF NOT EXISTS summary_pivot TEXT,
  ADD COLUMN IF NOT EXISTS title_pivot_version TEXT,
  ADD COLUMN IF NOT EXISTS summary_pivot_version TEXT;

CREATE TABLE IF NOT EXISTS source_profiles (
  source_id UUID PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  language_code TEXT NULL,
  publisher_type TEXT NULL,
  country_code TEXT NULL,
  is_primary_reporter BOOLEAN NOT NULL DEFAULT FALSE,
  reliability_notes TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS source_profiles_language_idx ON source_profiles(language_code);
CREATE INDEX IF NOT EXISTS source_profiles_publisher_idx ON source_profiles(publisher_type);

CREATE TABLE IF NOT EXISTS entity_mentions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  mention_text TEXT NOT NULL,
  normalized_mention TEXT NOT NULL,
  language_code TEXT NULL,
  entity_type_predicted TEXT NOT NULL,
  role TEXT NULL,
  char_start INT NULL,
  char_end INT NULL,
  extractor_confidence REAL NOT NULL,
  extractor_name TEXT NOT NULL,
  extractor_version TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (post_id, mention_text, normalized_mention, entity_type_predicted, role, char_start, char_end)
);

CREATE INDEX IF NOT EXISTS entity_mentions_post_idx ON entity_mentions(post_id);
CREATE INDEX IF NOT EXISTS entity_mentions_normalized_idx ON entity_mentions(entity_type_predicted, normalized_mention);

CREATE TABLE IF NOT EXISTS entities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_type TEXT NOT NULL,
  canonical_name TEXT NOT NULL,
  canonical_name_pivot TEXT NULL,
  normalized_name TEXT NOT NULL,
  description TEXT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  review_state TEXT NOT NULL DEFAULT 'provisional',
  first_seen_at TIMESTAMPTZ,
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS entities_type_normalized_idx ON entities(entity_type, normalized_name);
CREATE INDEX IF NOT EXISTS entities_last_seen_idx ON entities(last_seen_at DESC);
CREATE INDEX IF NOT EXISTS entities_review_state_idx ON entities(review_state);

CREATE TABLE IF NOT EXISTS entity_aliases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  normalized_alias TEXT NOT NULL,
  language_code TEXT NULL,
  script TEXT NULL,
  alias_type TEXT NOT NULL,
  transliteration TEXT NULL,
  source_hint TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (entity_id, normalized_alias)
);

CREATE INDEX IF NOT EXISTS entity_aliases_normalized_idx ON entity_aliases(normalized_alias);
CREATE INDEX IF NOT EXISTS entity_aliases_entity_idx ON entity_aliases(entity_id);

CREATE TABLE IF NOT EXISTS mention_entity_candidates (
  mention_id UUID NOT NULL REFERENCES entity_mentions(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  candidate_method TEXT NOT NULL,
  score REAL NOT NULL,
  selected BOOLEAN NOT NULL DEFAULT FALSE,
  resolver_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (mention_id, entity_id, candidate_method)
);

CREATE INDEX IF NOT EXISTS mention_entity_candidates_mention_idx ON mention_entity_candidates(mention_id);
CREATE INDEX IF NOT EXISTS mention_entity_candidates_entity_idx ON mention_entity_candidates(entity_id);
CREATE INDEX IF NOT EXISTS mention_entity_candidates_selected_idx ON mention_entity_candidates(selected);

CREATE TABLE IF NOT EXISTS post_entities (
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  mention_id UUID NOT NULL REFERENCES entity_mentions(id) ON DELETE CASCADE,
  resolution_status TEXT NOT NULL,
  confidence REAL NOT NULL,
  role TEXT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (post_id, entity_id, mention_id)
);

CREATE INDEX IF NOT EXISTS post_entities_post_idx ON post_entities(post_id);
CREATE INDEX IF NOT EXISTS post_entities_entity_idx ON post_entities(entity_id);
CREATE INDEX IF NOT EXISTS post_entities_mention_idx ON post_entities(mention_id);

CREATE TABLE IF NOT EXISTS events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type TEXT NOT NULL,
  title TEXT NOT NULL,
  normalized_event_key TEXT NULL,
  status TEXT NOT NULL DEFAULT 'observed',
  confidence REAL NOT NULL,
  occurred_at TIMESTAMPTZ NULL,
  first_seen_at TIMESTAMPTZ,
  last_seen_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS events_normalized_key_unique_idx
  ON events(normalized_event_key)
  WHERE normalized_event_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS events_type_idx ON events(event_type);
CREATE INDEX IF NOT EXISTS events_last_seen_idx ON events(last_seen_at DESC);

CREATE TABLE IF NOT EXISTS event_entities (
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (event_id, entity_id, role)
);

CREATE INDEX IF NOT EXISTS event_entities_entity_idx ON event_entities(entity_id);

CREATE TABLE IF NOT EXISTS event_evidence (
  event_id UUID NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  post_id UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  stance TEXT NOT NULL,
  evidence_snippet TEXT NULL,
  confidence REAL NOT NULL,
  extractor_version TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (event_id, post_id)
);

CREATE INDEX IF NOT EXISTS event_evidence_post_idx ON event_evidence(post_id);
CREATE INDEX IF NOT EXISTS event_evidence_stance_idx ON event_evidence(stance);

CREATE TABLE IF NOT EXISTS analyst_actions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  action_type TEXT NOT NULL,
  target_type TEXT NOT NULL,
  target_id UUID NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_by TEXT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS analyst_actions_target_idx ON analyst_actions(target_type, target_id);
CREATE INDEX IF NOT EXISTS analyst_actions_created_idx ON analyst_actions(created_at DESC);
