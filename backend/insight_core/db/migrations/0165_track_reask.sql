-- 0165_track_reask.sql (Stealth v10.28, issue 0252: track judging gaps)
--
-- When the `track` kind's guide changes (track-v1 -> track-v2), the answers made under the old guide for a track's
-- last tracks.REASK_DAYS are asked once more under the new one (tracks.plan's re-ask phase, newest first, at most
-- tracks.REASK_PER_DAY a track a day). The item row then names the new task; the tasks it was asked under before stay
-- listed in `asked_before` (their answers are kept in mx_calls: nothing is deleted), and `reasked_at` says when (the
-- per-day cap counts it). Mark X tables only. Idempotent.

ALTER TABLE mx_track_items ADD COLUMN IF NOT EXISTS asked_before uuid[];
ALTER TABLE mx_track_items ADD COLUMN IF NOT EXISTS reasked_at timestamptz;
CREATE INDEX IF NOT EXISTS mx_track_items_reasked_idx ON mx_track_items (track_id, reasked_at)
  WHERE reasked_at IS NOT NULL;
