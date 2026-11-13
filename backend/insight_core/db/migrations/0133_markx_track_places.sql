-- 0133_markx_track_places.sql (Stealth v10.17, issue 0195: the API light and fast)
--
-- The topic tracks' sidebar counts, their source suggestions and a track's page each placed every judged post of every
-- track per request (tracks.placed: each post's newest verdict, the owner's labels, the active sources, calibration):
-- 0.5-1.9 s on the server, and the API's memory up by 100-230 MiB a request. The placements are kept:
--   mx_track_places        each judged post's place in its track (track, joined, discover, out), rank and inputs;
--   mx_track_places_state  a track's calibration as of its last placement;
--   mx_track_changes       an append-only log the triggers write: a track whose inputs changed since (its items'
--                          verdicts, the owner's track labels, its sources, a post of it deleted or moved to
--                          another source). A logged or never placed track is placed live, exactly as before.
-- The refresh (markx/track_kept.py, after each ingestion run) places the logged tracks again. Idempotent; no row of
-- the inputs changes.

CREATE TABLE IF NOT EXISTS mx_track_places (
    track_id     uuid NOT NULL,
    post_id      uuid NOT NULL,
    place        text NOT NULL,
    rank         double precision NOT NULL,
    calibrated   boolean NOT NULL,
    label        text,
    active       boolean NOT NULL,
    verdict      boolean,
    confidence   real,
    subtopic     text,
    answered_at  timestamptz,
    found_by     text[],
    PRIMARY KEY (track_id, post_id)
);

CREATE TABLE IF NOT EXISTS mx_track_places_state (
    track_id     uuid PRIMARY KEY,
    calibration  json NOT NULL,           -- json, not jsonb: its keys in tracks.calibrate's order
    placed_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mx_track_changes (
    id        bigserial PRIMARY KEY,
    track_id  uuid NOT NULL
);
CREATE INDEX IF NOT EXISTS mx_track_changes_track_idx ON mx_track_changes (track_id);

-- Each trigger logs the tracks of its statement's rows (TG_ARGV[0]: the column naming the track).
CREATE OR REPLACE FUNCTION mx_track_changed_items() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO mx_track_changes (track_id) SELECT DISTINCT track_id FROM new_rows;
    END IF;
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        INSERT INTO mx_track_changes (track_id) SELECT DISTINCT track_id FROM old_rows;
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mx_track_changed_labels() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO mx_track_changes (track_id) SELECT DISTINCT b FROM new_rows WHERE item_kind = 'track' AND b IS NOT NULL;
    END IF;
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        INSERT INTO mx_track_changes (track_id) SELECT DISTINCT b FROM old_rows WHERE item_kind = 'track' AND b IS NOT NULL;
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mx_track_changed_sources() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        INSERT INTO mx_track_changes (track_id) SELECT DISTINCT folder_id FROM new_rows;
    END IF;
    IF TG_OP IN ('DELETE', 'UPDATE') THEN
        INSERT INTO mx_track_changes (track_id) SELECT DISTINCT folder_id FROM old_rows;
    END IF;
    RETURN NULL;
END $$;

-- A deleted post leaves its tracks; a post moved to another source may change which of them hold it as active.
CREATE OR REPLACE FUNCTION mx_track_changed_posts() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        INSERT INTO mx_track_changes (track_id)
        SELECT DISTINCT i.track_id FROM mx_track_items i WHERE i.post_id IN (SELECT id FROM old_rows);
    ELSE
        INSERT INTO mx_track_changes (track_id) SELECT DISTINCT i.track_id FROM mx_track_items i WHERE i.post_id = NEW.id;
    END IF;
    RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mx_track_places_truncated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM mx_track_places_state;
    RETURN NULL;
END $$;

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['mx_track_items', 'mx_labels', 'source_folders'] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_track_ins', t);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_track_upd', t);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_track_del', t);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t || '_track_trunc', t);
    END LOOP;
END $$;

CREATE TRIGGER mx_track_items_track_ins AFTER INSERT ON mx_track_items REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_items();
CREATE TRIGGER mx_track_items_track_upd AFTER UPDATE ON mx_track_items REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_items();
CREATE TRIGGER mx_track_items_track_del AFTER DELETE ON mx_track_items REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_items();
CREATE TRIGGER mx_track_items_track_trunc AFTER TRUNCATE ON mx_track_items
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_places_truncated();

CREATE TRIGGER mx_labels_track_ins AFTER INSERT ON mx_labels REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_labels();
CREATE TRIGGER mx_labels_track_upd AFTER UPDATE ON mx_labels REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_labels();
CREATE TRIGGER mx_labels_track_del AFTER DELETE ON mx_labels REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_labels();
CREATE TRIGGER mx_labels_track_trunc AFTER TRUNCATE ON mx_labels
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_places_truncated();

CREATE TRIGGER source_folders_track_ins AFTER INSERT ON source_folders REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_sources();
CREATE TRIGGER source_folders_track_upd AFTER UPDATE ON source_folders REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_sources();
CREATE TRIGGER source_folders_track_del AFTER DELETE ON source_folders REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_sources();
CREATE TRIGGER source_folders_track_trunc AFTER TRUNCATE ON source_folders
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_places_truncated();

DROP TRIGGER IF EXISTS posts_track_del ON posts;
CREATE TRIGGER posts_track_del AFTER DELETE ON posts REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_changed_posts();
DROP TRIGGER IF EXISTS posts_track_moved ON posts;
CREATE TRIGGER posts_track_moved AFTER UPDATE OF source_id ON posts
    FOR EACH ROW WHEN (OLD.source_id IS DISTINCT FROM NEW.source_id) EXECUTE FUNCTION mx_track_changed_posts();
DROP TRIGGER IF EXISTS posts_track_trunc ON posts;
CREATE TRIGGER posts_track_trunc AFTER TRUNCATE ON posts
    FOR EACH STATEMENT EXECUTE FUNCTION mx_track_places_truncated();
