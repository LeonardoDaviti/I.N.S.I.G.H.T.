-- 0174_track_thing_splits.sql (Stealth v10.41: one row a thing)
--
-- A track's thing joined reports that were not one thing (before v10.41 a shared link or hardware string sufficed, and
-- joins followed through it). track_things.repair splits such a row, never deleting: a member thing merged into it is
-- current again, and reports joined to it directly move to a new thing. Both keep where they came from:
--   mx_track_things.split_from        the root the thing was split off (or unmerged) from;
--   mx_track_thing_reports.moved_from the thing the report was first joined to.
-- Mark X tables only. Idempotent.

ALTER TABLE mx_track_things ADD COLUMN IF NOT EXISTS split_from uuid;
ALTER TABLE mx_track_thing_reports ADD COLUMN IF NOT EXISTS moved_from uuid;
