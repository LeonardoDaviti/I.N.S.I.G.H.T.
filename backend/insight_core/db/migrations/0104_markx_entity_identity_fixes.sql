-- 0104_markx_entity_identity_fixes.sql (issue 0164, Stealth v10.13.13: entity identity fixes, in Shadow)
--
-- (0103 is main's later-developments rule; renumber at merge if another lands first: nothing depends on the number.)
--
-- 1. mx_entities.shown_name / shown_type: the name and type an entity is shown under, chosen by evidence each run
--    (markx/entity_repair.py `shown`: the alias the most sources write, never a handle or an account naming itself
--    when a plain form exists, a person's full name; the type most of its mentions give). Derived: `name` and `type`
--    (what it was made as) are kept and still decide identity. NULL: shown as `name` / `type`. shown_by: 'evidence'
--    (the run's), or 'owner' (a rename, which a run never overwrites).
-- 2. mx_entity_fixes: every derived field a repair changed (0164: a version whose family was an org gets a family
--    entity: field 'parent'), with the old and new value, why, and its run. Undoable (undone_at); never deleted.
--    Merges a repair undoes are not here: their redirect keeps the record (undone_by 'repair', evidence.undone).
--
-- Mark X tables only. Idempotent.

ALTER TABLE mx_entities ADD COLUMN IF NOT EXISTS shown_name text;
ALTER TABLE mx_entities ADD COLUMN IF NOT EXISTS shown_type text;
ALTER TABLE mx_entities ADD COLUMN IF NOT EXISTS shown_by text;

CREATE TABLE IF NOT EXISTS mx_entity_fixes (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind       text NOT NULL,                       -- 'org_family' (a version's family was an org)
  entity_id  uuid NOT NULL REFERENCES mx_entities(id),
  field      text NOT NULL,                       -- 'parent'
  old        jsonb,
  new        jsonb,
  evidence   jsonb,
  run_id     uuid REFERENCES mx_runs(id),
  at         timestamptz NOT NULL DEFAULT now(),
  undone_at  timestamptz
);
CREATE INDEX IF NOT EXISTS mx_entity_fixes_entity_idx ON mx_entity_fixes (entity_id);
