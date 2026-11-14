-- 0139_kept_pages_wave_2.sql (Stealth v10.18, issue 0206: the requests that still rebuilt per request, kept)
--
-- 1. Kept inputs (markx/kept_pages.py `changes`): an exact, cheap stamp for a page whose inputs are written by many
--    writers (posts, read state, stories, sources). A write to an input logs one row per transaction
--    (kept_input_changes, keyed by the input and the transaction's id: inserts by different transactions never
--    wait on each other, a transaction's later writes add nothing). An input's count is its base plus its logged
--    rows: it changes with every committed writing transaction, whatever order they commit in. The jobs process
--    folds the logged rows into the base (`compact`: the rows it sees deleted and added to the base in one
--    statement), which leaves every count as it was, so no kept page is lost to it.
-- 2. mx_kept_pages gains `loose`: what a page may lag behind within its bound (its `until`), kept so the jobs
--    process can tell the page is behind and build it again (a topic track's page: the worker's verdicts).
-- 3. The jobs process's kept views of this wave have their rows in mx_jobs: tracks, unread, main_source, discover.
-- A cache: no row of posts, sources or stories changes. Idempotent.

CREATE TABLE IF NOT EXISTS kept_inputs (
  input  text PRIMARY KEY,
  base   bigint NOT NULL DEFAULT 0          -- the logged changes folded in so far
);
INSERT INTO kept_inputs (input) VALUES ('posts'), ('reads'), ('stories'), ('parts'), ('folders'), ('sources')
ON CONFLICT (input) DO NOTHING;

CREATE TABLE IF NOT EXISTS kept_input_changes (
  input  text NOT NULL,
  xid    xid8 NOT NULL DEFAULT pg_current_xact_id(),
  PRIMARY KEY (input, xid)
);

-- A write to an input (TG_ARGV[0]): its transaction's one row (row triggers too: a second row adds nothing).
CREATE OR REPLACE FUNCTION kept_input_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO kept_input_changes (input) VALUES (TG_ARGV[0]) ON CONFLICT DO NOTHING;
    RETURN NULL;
END $$;

DO $$
DECLARE
    t record;
BEGIN
    -- (table, input): every insert, delete, update and truncate of the table is a change of the input
    FOR t IN SELECT * FROM (VALUES ('post_reader_state', 'reads'), ('story_posts', 'stories'), ('post_parts', 'parts'),
                                   ('story_originals', 'stories'), ('classics', 'stories'),
                                   ('source_folders', 'folders'), ('folders', 'folders'), ('sources', 'sources')) v(tab, input)
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t.tab || '_kept_input', t.tab);
        EXECUTE format('CREATE TRIGGER %I AFTER INSERT OR UPDATE OR DELETE ON %I FOR EACH STATEMENT '
                       'EXECUTE FUNCTION kept_input_changed(%L)', t.tab || '_kept_input', t.tab, t.input);
        EXECUTE format('DROP TRIGGER IF EXISTS %I ON %I', t.tab || '_kept_input_trunc', t.tab);
        EXECUTE format('CREATE TRIGGER %I AFTER TRUNCATE ON %I FOR EACH STATEMENT '
                       'EXECUTE FUNCTION kept_input_changed(%L)', t.tab || '_kept_input_trunc', t.tab, t.input);
    END LOOP;
END $$;

-- reads: an update only of what is read, put in Later or starred (not where a reading was left: every scroll)
DROP TRIGGER IF EXISTS post_reader_state_kept_input ON post_reader_state;
CREATE TRIGGER post_reader_state_kept_input AFTER INSERT OR DELETE OR UPDATE OF read_at, later_at, starred_at
    ON post_reader_state FOR EACH STATEMENT EXECUTE FUNCTION kept_input_changed('reads');

-- posts: every insert and delete; an update only when it moves what a kept page reads of a post (its source, its
-- place in a story's fold or an album, its dates, whether it is shown only in its story, its length and duration).
DROP TRIGGER IF EXISTS posts_kept_input ON posts;
CREATE TRIGGER posts_kept_input AFTER INSERT OR DELETE ON posts
    FOR EACH STATEMENT EXECUTE FUNCTION kept_input_changed('posts');
DROP TRIGGER IF EXISTS posts_kept_input_trunc ON posts;
CREATE TRIGGER posts_kept_input_trunc AFTER TRUNCATE ON posts
    FOR EACH STATEMENT EXECUTE FUNCTION kept_input_changed('posts');
DROP TRIGGER IF EXISTS posts_kept_input_upd ON posts;
CREATE TRIGGER posts_kept_input_upd AFTER UPDATE OF source_id, album_of, normalized_url, surfaced_at, published_at,
                                                    fetched_at, metadata, content ON posts
    FOR EACH ROW WHEN (
        OLD.source_id IS DISTINCT FROM NEW.source_id
        OR OLD.album_of IS DISTINCT FROM NEW.album_of
        OR OLD.normalized_url IS DISTINCT FROM NEW.normalized_url
        OR OLD.surfaced_at IS DISTINCT FROM NEW.surfaced_at
        OR OLD.published_at IS DISTINCT FROM NEW.published_at
        OR OLD.fetched_at IS DISTINCT FROM NEW.fetched_at
        OR (OLD.metadata ? 'story_only') IS DISTINCT FROM (NEW.metadata ? 'story_only')
        OR (OLD.metadata ->> 'duration_seconds') IS DISTINCT FROM (NEW.metadata ->> 'duration_seconds')
        OR length(OLD.content) IS DISTINCT FROM length(NEW.content))
    EXECUTE FUNCTION kept_input_changed('posts');

-- folders: also a source added or removed, switched on or off, readdressed, or moved in or out of the main digest
-- (every other write of a source, a fetch's own among them, is the input 'sources' only).
DROP TRIGGER IF EXISTS sources_kept_folders ON sources;
CREATE TRIGGER sources_kept_folders AFTER INSERT OR DELETE OR UPDATE OF in_main_digest, platform, enabled, handle_or_url
    ON sources
    FOR EACH STATEMENT EXECUTE FUNCTION kept_input_changed('folders');

ALTER TABLE mx_kept_pages ADD COLUMN IF NOT EXISTS loose text;

ALTER TABLE mx_jobs DROP CONSTRAINT IF EXISTS mx_jobs_job_check;
ALTER TABLE mx_jobs ADD CONSTRAINT mx_jobs_job_check CHECK (job IN ('candidates', 'decide', 'plan', 'labels', 'news',
                                                                    'tracks', 'unread', 'main_source', 'discover'));
