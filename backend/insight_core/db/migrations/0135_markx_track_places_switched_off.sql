-- 0135_markx_track_places_switched_off.sql (Stealth v10.17.1, issue 0200: a source switched off is never suggested)
--
-- A track's placement now reads whether a passive source is switched off (tracks.placed: Haiku's in from it is
-- `off`, never in Discover nor joined). The kept placements (0133) are placed again only when a logged input
-- changed, so switching a source off or on logs every topic track: the next read places them live, the next refresh
-- keeps them. Idempotent; no row of the inputs changes.

CREATE OR REPLACE FUNCTION mx_track_changed_enabled() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO mx_track_changes (track_id) SELECT folder_id FROM mx_tracks;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS sources_track_enabled ON sources;
CREATE TRIGGER sources_track_enabled AFTER UPDATE OF enabled ON sources
    FOR EACH ROW WHEN (OLD.enabled IS DISTINCT FROM NEW.enabled) EXECUTE FUNCTION mx_track_changed_enabled();

-- The placements kept before this version knew nothing of switched-off sources: every topic track is placed again.
INSERT INTO mx_track_changes (track_id) SELECT folder_id FROM mx_tracks;
