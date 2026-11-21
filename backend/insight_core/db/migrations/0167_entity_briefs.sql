-- 0167_entity_briefs.sql (Stealth v10.31, issue 0261: an entity's brief, the general briefer applied to an entity)
--
-- An entity is briefed as a track whose subject is the entity (markx/entity_brief.py): its rows live where a track's
-- things do (mx_track_things, mx_track_thing_reports, mx_track_brief_asks), `track_id` the entity's root id. Its schema
-- row says whose it is and who wrote it:
--   - mx_track_schemas.subject: 'track' (a folder track, every row so far) or 'entity' (an entity's root);
--   - mx_track_schemas.by may be 'code' (the general entity schema, written by code, never proposed by Haiku).
-- Mark X tables only; nothing is deleted. Idempotent.

ALTER TABLE mx_track_schemas ADD COLUMN IF NOT EXISTS subject text NOT NULL DEFAULT 'track';

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_track_schemas'::regclass
                   AND conname = 'mx_track_schemas_subject_check') THEN
    ALTER TABLE mx_track_schemas ADD CONSTRAINT mx_track_schemas_subject_check CHECK (subject IN ('track', 'entity'));
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_track_schemas'::regclass
               AND conname = 'mx_track_schemas_by_check'
               AND position(quote_literal('code') IN pg_get_constraintdef(oid)) = 0) THEN
    ALTER TABLE mx_track_schemas DROP CONSTRAINT mx_track_schemas_by_check;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_track_schemas'::regclass
                   AND conname = 'mx_track_schemas_by_check') THEN
    ALTER TABLE mx_track_schemas ADD CONSTRAINT mx_track_schemas_by_check CHECK (by IN ('haiku', 'owner', 'code'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS mx_track_schemas_subject_idx ON mx_track_schemas (subject, track_id);
