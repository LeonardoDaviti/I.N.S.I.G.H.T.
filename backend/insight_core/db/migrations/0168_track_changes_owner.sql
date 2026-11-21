-- 0168_track_changes_owner.sql (Stealth v10.31, issue 0264: a track's kept placement read while the worker changes it)
--
-- 0133's change log made a track read live (tracks.placed, every judged item) from any change of its inputs until the
-- next refresh. Since v10.29 the blind check (0166) updates track items for thousands of backlog posts: one track was
-- placed live on every sidebar count and page (65,000 items; 0.8 s and 2-5 s, the DB's CPU doubled). A change row now
-- says whose it is:
--   owner true   the owner's own inputs (a track label, the folder's sources, a source switched on or off): read
--                live until placed again, as before (a read is never wrong for the owner's own action);
--   owner false  the worker's and the ingestion's (a track item's verdict or check, a post deleted or moved to another
--                source): the readers read the last kept placement; markx/track_kept.refresh places it again at most
--                every REFRESH_GAP.
-- The rows logged before this migration are the owner's (read live until the next refresh). Idempotent.

ALTER TABLE mx_track_changes ADD COLUMN IF NOT EXISTS owner boolean NOT NULL DEFAULT true;
CREATE INDEX IF NOT EXISTS mx_track_changes_owner_idx ON mx_track_changes (track_id) WHERE owner;

CREATE OR REPLACE FUNCTION mx_track_changed_items() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO mx_track_changes (track_id, owner) SELECT DISTINCT track_id, false FROM new_rows;
    END IF;
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        INSERT INTO mx_track_changes (track_id, owner) SELECT DISTINCT track_id, false FROM old_rows;
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mx_track_changed_posts() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO mx_track_changes (track_id, owner)
        SELECT DISTINCT i.track_id, false FROM mx_track_items i WHERE i.post_id IN (SELECT id FROM old_rows);
    ELSE
        INSERT INTO mx_track_changes (track_id, owner)
        SELECT DISTINCT i.track_id, false FROM mx_track_items i WHERE i.post_id = NEW.id;
    END IF;
    RETURN NULL;
END $$;
