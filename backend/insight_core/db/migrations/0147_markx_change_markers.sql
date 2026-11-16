-- 0147_markx_change_markers.sql (Stealth v10.22, issue 0216: the planners' fingerprints and the passes' stamps)
--
-- 1. mx_post_stamps: a post's text version (markx/plan_marks.py STAMP). A post's text stamp was its row's version plus
--    four subqueries a post (its parts' row version, its source's shown name, every kept link's row version, the page
--    a link post is read with), computed for every post of the window on every planner run (on the server: 12% of the
--    database's time, ~120M buffer reads in 104 min, for 242 rows). Now the stamp is this table's `n` (a sequence),
--    moved by triggers on every write of the post's row and of those dependents: post_parts and post_links (statement
--    triggers), the source's shown name and kind fields, and story_originals' `linked` rows a post's page points to.
--    A narrow table, so the planners find the posts whose mark no longer holds by a join of two narrow tables, not a
--    read of every post (plan_marks.unread). Every post gets a row (backfilled); the stamps kept before (mx_plan_marks,
--    mx_inc_posts) differ once, and the posts are read again once, as after any change of the stamp's definition.
-- 2. mx_table_changes: what markx/unchanged.py stamps mx_tasks by (a pass's declared `mx_tasks[kind,...]`). It summed
--    every row version of those kinds (a full scan of mx_tasks: ~600 ms a call on the server). Now each statement that
--    writes mx_tasks appends one row per kind it touched (n from a sequence); a kind's stamp is the count and sum of
--    its rows (a late commit adds a row, so the stamp moves whatever its n). unchanged.py prunes it.
-- 3. mx_tasks (kind, guide, a): the planners' "has the post a task of this kind and guide" from the index alone, per
--    post (it fetched every task row of the post from the 3.8 GB table to check two columns) or for every post at once
--    (plan_marks.unread: the kind's posts in order, against the posts' ids). (a) stays: with it replaced by (a, kind,
--    guide), a query reading tasks by `a` alone took the new index and its rows in another order, and one decision run
--    of the mxreal copy asked one rename question more (an order-dependent step; measured: base code, index swapped).
--
-- One transaction, like every file the archive restore replays (import_export.restore runs each in a transaction: a
-- CONCURRENTLY build can't run there). The index is built in it: mx_tasks' writes wait for the build (seconds on the
-- server's 1.7M tasks, during ./update's restart). Every statement is safe to run again.

CREATE SEQUENCE IF NOT EXISTS mx_post_stamps_seq;
CREATE TABLE IF NOT EXISTS mx_post_stamps (
  post_id uuid PRIMARY KEY,
  n       bigint NOT NULL
);

CREATE OR REPLACE FUNCTION mx_post_stamps_bump(ids uuid[]) RETURNS void LANGUAGE sql AS $$
  INSERT INTO mx_post_stamps (post_id, n)
  SELECT x.id, nextval('mx_post_stamps_seq')
    FROM (SELECT DISTINCT id FROM unnest(ids) AS u(id) WHERE id IS NOT NULL ORDER BY id) x
   WHERE EXISTS (SELECT 1 FROM posts p WHERE p.id = x.id)       -- a post deleted in this statement keeps no row
  ON CONFLICT (post_id) DO UPDATE SET n = EXCLUDED.n
$$;

-- post_parts and post_links: every insert, update and delete, once a statement (in post order: no deadlock between two
-- statements bumping the same posts).
CREATE OR REPLACE FUNCTION mx_post_stamps_rows() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    PERFORM mx_post_stamps_bump(ARRAY(SELECT post_id FROM new_rows));
  ELSIF TG_OP = 'UPDATE' THEN
    PERFORM mx_post_stamps_bump(ARRAY(SELECT post_id FROM new_rows UNION SELECT post_id FROM old_rows));
  ELSE
    PERFORM mx_post_stamps_bump(ARRAY(SELECT post_id FROM old_rows));
  END IF;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS post_parts_stamp_ins ON post_parts;
CREATE TRIGGER post_parts_stamp_ins AFTER INSERT ON post_parts REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_post_stamps_rows();
DROP TRIGGER IF EXISTS post_parts_stamp_upd ON post_parts;
CREATE TRIGGER post_parts_stamp_upd AFTER UPDATE ON post_parts REFERENCING NEW TABLE AS new_rows OLD TABLE AS old_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_post_stamps_rows();
DROP TRIGGER IF EXISTS post_parts_stamp_del ON post_parts;
CREATE TRIGGER post_parts_stamp_del AFTER DELETE ON post_parts REFERENCING OLD TABLE AS old_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_post_stamps_rows();

DROP TRIGGER IF EXISTS post_links_stamp_ins ON post_links;
CREATE TRIGGER post_links_stamp_ins AFTER INSERT ON post_links REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_post_stamps_rows();
DROP TRIGGER IF EXISTS post_links_stamp_upd ON post_links;
CREATE TRIGGER post_links_stamp_upd AFTER UPDATE ON post_links REFERENCING NEW TABLE AS new_rows OLD TABLE AS old_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_post_stamps_rows();
DROP TRIGGER IF EXISTS post_links_stamp_del ON post_links;
CREATE TRIGGER post_links_stamp_del AFTER DELETE ON post_links REFERENCING OLD TABLE AS old_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_post_stamps_rows();

-- A source's shown name and kind (what a render names it by): its posts.
CREATE OR REPLACE FUNCTION mx_post_stamps_source() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM mx_post_stamps_bump(ARRAY(SELECT id FROM posts WHERE source_id = NEW.id));
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS sources_stamp_upd ON sources;
CREATE TRIGGER sources_stamp_upd AFTER UPDATE ON sources FOR EACH ROW
  WHEN (OLD.platform IS DISTINCT FROM NEW.platform OR OLD.handle_or_url IS DISTINCT FROM NEW.handle_or_url
        OR OLD.settings->>'display_name' IS DISTINCT FROM NEW.settings->>'display_name'
        OR OLD.settings->>'name' IS DISTINCT FROM NEW.settings->>'name')
  EXECUTE FUNCTION mx_post_stamps_source();

-- The page a link post is read with (plan_marks.LINKED_PAGE): a `linked` original written for its address.
CREATE INDEX IF NOT EXISTS post_parts_page_target_idx ON post_parts (link_target) WHERE link_kind = 'page';
CREATE OR REPLACE FUNCTION mx_post_stamps_linked() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  urls text[];
BEGIN
  IF TG_OP IN ('INSERT', 'UPDATE') AND NEW.kind = 'linked' THEN
    urls := array_append(urls, NEW.url);
  END IF;
  IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.kind = 'linked' THEN
    urls := array_append(urls, OLD.url);
  END IF;
  IF urls IS NOT NULL THEN
    PERFORM mx_post_stamps_bump(ARRAY(SELECT post_id FROM post_parts
                                       WHERE link_kind = 'page' AND link_target = ANY(urls)));
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS story_originals_stamp ON story_originals;
CREATE TRIGGER story_originals_stamp AFTER INSERT OR UPDATE OR DELETE ON story_originals FOR EACH ROW
  EXECUTE FUNCTION mx_post_stamps_linked();

-- The post's own row: every insert and update (its row version was the stamp's first part), and a deleted post's row
-- goes with it.
CREATE OR REPLACE FUNCTION mx_post_stamps_post() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO mx_post_stamps (post_id, n) VALUES (NEW.id, nextval('mx_post_stamps_seq'))
  ON CONFLICT (post_id) DO UPDATE SET n = EXCLUDED.n;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS posts_stamp ON posts;
CREATE TRIGGER posts_stamp AFTER INSERT OR UPDATE ON posts FOR EACH ROW EXECUTE FUNCTION mx_post_stamps_post();
CREATE OR REPLACE FUNCTION mx_post_stamps_gone() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM mx_post_stamps WHERE post_id IN (SELECT id FROM old_rows);
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS posts_stamp_del ON posts;
CREATE TRIGGER posts_stamp_del AFTER DELETE ON posts REFERENCING OLD TABLE AS old_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_post_stamps_gone();

-- Every post stored before: a row (after the triggers, so a post saved meanwhile is not missed).
INSERT INTO mx_post_stamps (post_id, n) SELECT id, nextval('mx_post_stamps_seq') FROM posts ON CONFLICT (post_id) DO NOTHING;
ANALYZE mx_post_stamps;

-- 2. The kinds of mx_tasks a statement wrote (markx/unchanged.py).
CREATE SEQUENCE IF NOT EXISTS mx_table_changes_seq;
CREATE TABLE IF NOT EXISTS mx_table_changes (
  tbl  text NOT NULL,
  kind text NOT NULL,                       -- '*': every kind (a TRUNCATE)
  n    bigint NOT NULL DEFAULT nextval('mx_table_changes_seq'),
  at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_table_changes_idx ON mx_table_changes (tbl, kind, n);
CREATE INDEX IF NOT EXISTS mx_table_changes_at_idx ON mx_table_changes (at);

CREATE OR REPLACE FUNCTION mx_tasks_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'TRUNCATE' THEN
    INSERT INTO mx_table_changes (tbl, kind) VALUES ('mx_tasks', '*');
  ELSIF TG_OP = 'INSERT' THEN
    INSERT INTO mx_table_changes (tbl, kind) SELECT DISTINCT 'mx_tasks', kind FROM new_rows;
  ELSIF TG_OP = 'UPDATE' THEN
    INSERT INTO mx_table_changes (tbl, kind)
    SELECT 'mx_tasks', kind FROM (SELECT kind FROM new_rows UNION SELECT kind FROM old_rows) k;
  ELSE
    INSERT INTO mx_table_changes (tbl, kind) SELECT DISTINCT 'mx_tasks', kind FROM old_rows;
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS mx_tasks_changes_ins ON mx_tasks;
CREATE TRIGGER mx_tasks_changes_ins AFTER INSERT ON mx_tasks REFERENCING NEW TABLE AS new_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_tasks_changed();
DROP TRIGGER IF EXISTS mx_tasks_changes_upd ON mx_tasks;
CREATE TRIGGER mx_tasks_changes_upd AFTER UPDATE ON mx_tasks REFERENCING NEW TABLE AS new_rows OLD TABLE AS old_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_tasks_changed();
DROP TRIGGER IF EXISTS mx_tasks_changes_del ON mx_tasks;
CREATE TRIGGER mx_tasks_changes_del AFTER DELETE ON mx_tasks REFERENCING OLD TABLE AS old_rows
  FOR EACH STATEMENT EXECUTE FUNCTION mx_tasks_changed();
DROP TRIGGER IF EXISTS mx_tasks_changes_trunc ON mx_tasks;
CREATE TRIGGER mx_tasks_changes_trunc AFTER TRUNCATE ON mx_tasks
  FOR EACH STATEMENT EXECUTE FUNCTION mx_tasks_changed();

-- 3. The planners' probe from the index alone.
CREATE INDEX IF NOT EXISTS mx_tasks_kind_guide_a_idx ON mx_tasks (kind, guide, a) WHERE a IS NOT NULL;
