-- 0137 (issue 0184, Stealth v10.18): entity identity facts (markx/entity_facts.py owns them).
--
-- 1. mx_entity_facts: what an entity (a sense of its name) is: its kind (an entity type, or `generic` for a common
--    word), its maker (an entity, and the maker as the posts state it), a one-line `what`, up to four words that tell
--    it from another thing of the same name (`context`), and who said so (`by`: rule:mentions, rule:address, haiku,
--    owner) and the bare name key it is a sense of (`sense_key`). One current row an entity; a new fact supersedes the current one (superseded_at, superseded_by), never
--    updates it (keep everything). An owner's fact is never superseded by a rule or Haiku (the module's rule).
-- 2. mx_entity_pins gains `by` (owner, the default, or facts: a mention the facts placed in a sense), the call that
--    placed it and the entity it was linked to before (`from_entity`). An owner's undo of a facts pin is final.
-- 3. mx_mentions gains `placed`: how the facts placed a bare name's mention (rule:maker, rule:context, facts, wait);
--    NULL: not a bare name, linked as before.
-- 4. mx_entity_queue.kind may be `facts` (a sense split below the bar, for the owner).
-- Mark X tables only; nothing is deleted. Idempotent.

CREATE TABLE IF NOT EXISTS mx_entity_facts (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id     uuid NOT NULL REFERENCES mx_entities(id),
  kind          text,
  maker_id      uuid REFERENCES mx_entities(id),
  maker_name    text,
  what          text CHECK (what IS NULL OR length(what) <= 120),
  context       text[] NOT NULL DEFAULT '{}',
  generic       boolean NOT NULL DEFAULT false,
  sense_key     text,                               -- the bare name key this entity is a sense of
  by            text NOT NULL CHECK (by IN ('rule:mentions', 'rule:address', 'haiku', 'owner')),
  guide         text,
  call_id       uuid REFERENCES mx_calls(id),
  confidence    real,
  evidence      jsonb,
  run_id        uuid REFERENCES mx_runs(id),
  created_at    timestamptz NOT NULL DEFAULT now(),
  superseded_at timestamptz,
  superseded_by uuid REFERENCES mx_entity_facts(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_entity_facts_current_idx ON mx_entity_facts (entity_id) WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS mx_entity_facts_maker_idx ON mx_entity_facts (maker_id) WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS mx_entity_facts_sense_idx ON mx_entity_facts (sense_key) WHERE superseded_at IS NULL;

ALTER TABLE mx_entity_pins ADD COLUMN IF NOT EXISTS by text NOT NULL DEFAULT 'owner';
ALTER TABLE mx_entity_pins ADD COLUMN IF NOT EXISTS call_id uuid REFERENCES mx_calls(id);
ALTER TABLE mx_entity_pins ADD COLUMN IF NOT EXISTS from_entity uuid REFERENCES mx_entities(id);
ALTER TABLE mx_entity_pins DROP CONSTRAINT IF EXISTS mx_entity_pins_by_check;
ALTER TABLE mx_entity_pins ADD CONSTRAINT mx_entity_pins_by_check CHECK (by IN ('owner', 'facts'));

ALTER TABLE mx_mentions ADD COLUMN IF NOT EXISTS placed text;
ALTER TABLE mx_mentions DROP CONSTRAINT IF EXISTS mx_mentions_placed_check;
ALTER TABLE mx_mentions ADD CONSTRAINT mx_mentions_placed_check
  CHECK (placed IS NULL OR placed IN ('rule:maker', 'rule:context', 'rule:handle', 'facts', 'wait'));

ALTER TABLE mx_entity_queue DROP CONSTRAINT IF EXISTS mx_entity_queue_kind_check;
ALTER TABLE mx_entity_queue ADD CONSTRAINT mx_entity_queue_kind_check
  CHECK (kind IN ('alias', 'collision', 'rename', 'handle', 'facts'));
