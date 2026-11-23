-- 0173_track_field_dismissals.sql (Stealth v10.41: a track's suggested fields, FIX 6)
--
-- INSIGHT proposes fields a track's records miss (markx/track_fields.py: kind track_schema, guide track-fields-v1);
-- the owner adds one (PUT .../schema, a new version of their own) or dismisses it. A dismissed field (its kind and
-- name) is never suggested again for that track. One row a dismissal, kept. Idempotent.

CREATE TABLE IF NOT EXISTS mx_track_field_dismissals (
  track_id      uuid NOT NULL,
  kind          text NOT NULL,
  field         text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (track_id, kind, field)
);
