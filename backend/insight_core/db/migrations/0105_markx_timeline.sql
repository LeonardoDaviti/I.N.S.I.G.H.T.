-- 0105_markx_timeline.sql (issue 0165, Stealth v10.14: a thing's timeline: components, renames, the timeline view)
--
-- (0104 is 0164's entity identity fixes; renumber at merge if another lands first: nothing depends on the number.)
--
-- 1. mx_entity_redirects.kind: what a merge says. 'same' (one thing written two ways: every merge before 0165) or
--    'rename' (0165 B: the same thing under an earlier name; the old name's cluster redirects into the new one, its
--    names kept as "earlier names"). Undone like any other merge (undone_at; the row stays).
-- 2. mx_entity_queue.kind may be 'rename' (0165 B: two entities of one maker, one older, that shared evidence and
--    Haiku's `renamed` say may be one thing renamed: a question for the owner, never applied by itself). A rename
--    item is a pair, like an alias item (a = the older name, b = the newer).
-- 3. mx_entity_fixes.kind may be 'component' (0165 A: a thing named "<product> <name>" whose posts are about it gets
--    the product as its parent instead of its maker; the old parent kept in the row).
--
-- Mark X tables only. Idempotent. Nothing is deleted.

ALTER TABLE mx_entity_redirects ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'same';
ALTER TABLE mx_entity_redirects DROP CONSTRAINT IF EXISTS mx_entity_redirects_kind_check;
ALTER TABLE mx_entity_redirects ADD CONSTRAINT mx_entity_redirects_kind_check CHECK (kind IN ('same', 'rename'));
CREATE INDEX IF NOT EXISTS mx_entity_redirects_rename_idx ON mx_entity_redirects (to_id)
  WHERE kind = 'rename' AND undone_at IS NULL;

ALTER TABLE mx_entity_queue DROP CONSTRAINT IF EXISTS mx_entity_queue_kind_check;
ALTER TABLE mx_entity_queue ADD CONSTRAINT mx_entity_queue_kind_check CHECK (kind IN ('alias', 'collision', 'rename'));
ALTER TABLE mx_entity_queue DROP CONSTRAINT IF EXISTS mx_entity_queue_a_pair_is_two;
ALTER TABLE mx_entity_queue ADD CONSTRAINT mx_entity_queue_a_pair_is_two
  CHECK (kind NOT IN ('alias', 'rename') OR (b IS NOT NULL AND a <> b));
