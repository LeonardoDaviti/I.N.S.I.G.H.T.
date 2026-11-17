-- 0156_markx_opinion_inputs_and_flags.sql (Stealth v10.24, issue 0222).
--
-- 1. mx_opinion_inputs: what a pair question about two entities (alias, alias2, alias3, alias4) showed of each side
--    when it was asked: each side's name, type, maker and version fields and the example posts it quoted
--    (`basis`: {"sides": [{"id", "head", "posts"}, ...]}). Keyed by the question's input (kind, sha256 of the input:
--    mx_tasks.input_hash), as a task is. markx/identity.py reads it before an answer decides anything: an opinion holds
--    only while both sides still are what it was asked on (an example post no longer the side's, after a relink or a
--    new reading of the post, voids it: the item is closed and the pair asked again). `derived`: read back from an
--    older question's input text (asked before this table), not recorded at ask time.
-- 2. mx_entity_queue.flagged_*: an item Claude's review flagged for the owner (the owner sees only these by default;
--    the rest is decided by its measured band or stays apart/held and is asked again). flagged_at NULL: not flagged.
-- Mark X tables only; nothing is deleted. Idempotent.

CREATE TABLE IF NOT EXISTS mx_opinion_inputs (
  kind        text NOT NULL,
  input_hash  text NOT NULL,
  a           uuid,
  b           uuid,
  basis       jsonb NOT NULL,
  derived     boolean NOT NULL DEFAULT false,
  created_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, input_hash)
);

ALTER TABLE mx_entity_queue ADD COLUMN IF NOT EXISTS flagged_at timestamptz;
ALTER TABLE mx_entity_queue ADD COLUMN IF NOT EXISTS flagged_by text;
ALTER TABLE mx_entity_queue ADD COLUMN IF NOT EXISTS flag_note text;
CREATE INDEX IF NOT EXISTS mx_entity_queue_flagged_idx ON mx_entity_queue (flagged_at DESC)
  WHERE flagged_at IS NOT NULL AND answer IS NULL AND closed_at IS NULL;
