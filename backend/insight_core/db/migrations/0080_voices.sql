-- 0080_voices.sql (issue 0132 A: voices, one voice made of its channels; 0078's channels)
--
-- 1. voices: one company, person or publication. name: from its main channel, editable. kind: company | person |
--    publication (NULL: not said). entity_id: the Mark X entity it is (nullable, no foreign key: Mark X's tables are
--    its own). confirmed_at: when the owner joined its channels (a voice is only ever made by the owner: a
--    suggestion is never applied alone). removed_at: the owner removed it; its channels stay sources (0132 decision
--    1 default), the row stays (keep everything).
-- 2. sources.voice_id: one voice per source (the owner's decision 3), NULL when none. A source keeps its schedule,
--    health, backoff and on/off. ON DELETE SET NULL: removing a source never removes its voice.
-- 3. voice_links: related voices (staff <-> company), each with its evidence. One row per pair, a < b.
-- 4. voice_decisions: every decision the owner made on the voices page, with its evidence (join, not_same, related,
--    make, remove, rename, leave): "Not the same" keeps a pair from being suggested again; the rest is the history.
--
-- Stories count a confirmed voice once (story_rules.count_voices): with no confirmed voice nothing changes, and a
-- confirmed one queues only its sources' posts (the story job's source facts), never a full regroup.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS voices (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name         text NOT NULL CHECK (btrim(name) <> ''),
  kind         text CHECK (kind IN ('company', 'person', 'publication')),
  entity_id    uuid,
  created_at   timestamptz NOT NULL DEFAULT now(),
  confirmed_at timestamptz,
  removed_at   timestamptz
);

ALTER TABLE sources ADD COLUMN IF NOT EXISTS voice_id uuid REFERENCES voices(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS sources_voice_idx ON sources (voice_id) WHERE voice_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS voice_links (
  a          uuid NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
  b          uuid NOT NULL REFERENCES voices(id) ON DELETE CASCADE,
  kind       text NOT NULL DEFAULT 'related' CHECK (kind IN ('related')),
  evidence   jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (a, b),
  CHECK (a < b)
);

CREATE TABLE IF NOT EXISTS voice_decisions (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind        text NOT NULL CHECK (kind IN ('join', 'not_same', 'related', 'make', 'remove', 'rename', 'leave')),
  source_ids  uuid[] NOT NULL DEFAULT '{}',
  voice_id    uuid,
  evidence    jsonb NOT NULL DEFAULT '[]'::jsonb,
  decided_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS voice_decisions_kind_idx ON voice_decisions (kind, decided_at);
