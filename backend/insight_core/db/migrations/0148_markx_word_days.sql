-- 0148_markx_word_days.sql (Stealth v10.22, issue 0216: the track finders' word counts kept by day)
--
-- The track finders' word counts (markx/finders.py `_df_words`: in how many of the last 30 days' posts each term is,
-- the post's index and Mark X's English layer together) were Postgres' ts_stat over every post of the window, on every
-- plan pass (server: 3 s and ~100k buffers a call, 60 calls in 104 minutes). The counts of a whole day of posts do not
-- change while none of its posts' terms or dates change, so they are kept a day at a time:
--
-- 1. mx_word_days: one row a day (UTC, of a post's ordinary date), every term of its posts and in how many: the
--    arrays `words` (sorted) and `ndocs`, as ts_stat counts them; `built_gen` the day's change count it was built at.
--    A cache: built by finders on use, only for the days a window needs, the older ones deleted.
-- 2. mx_word_days_dirty: a day's change count (`gen`, from mx_word_days_gen), raised by the triggers below in the
--    transaction that changes one of its posts' terms or dates (posts inserted, deleted, their search vector or date
--    changed; Mark X's English layer of one of them written or deleted). A built day whose `built_gen` is not its
--    `gen` is built again. The count is raised under the row's lock, so it only grows in commit order: a build that
--    read the count in its snapshot is never newer than its rows (its rows are read in that snapshot or a later one).
-- 3. TRUNCATE of either table empties mx_word_days (everything is built again).
--
-- Writes only these two tables; a post's own write gains one upsert of a small row. Idempotent.

CREATE TABLE IF NOT EXISTS mx_word_days (
  day       date PRIMARY KEY,
  built_gen bigint NOT NULL,
  words     text[] NOT NULL,
  ndocs     integer[] NOT NULL,
  built_at  timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS mx_word_days_dirty (
  day date PRIMARY KEY,
  gen bigint NOT NULL
);
CREATE SEQUENCE IF NOT EXISTS mx_word_days_gen;

-- The day of a post's ordinary date (pairing.ordinary_date), UTC.
CREATE OR REPLACE FUNCTION mx_word_day(surfaced timestamptz, published timestamptz, fetched timestamptz)
RETURNS date LANGUAGE sql IMMUTABLE AS $$ SELECT (COALESCE(surfaced, published, fetched) AT TIME ZONE 'UTC')::date $$;

CREATE OR REPLACE FUNCTION mx_word_days_touch(days date[]) RETURNS void LANGUAGE sql AS $$
  INSERT INTO mx_word_days_dirty (day, gen)
  SELECT d, nextval('mx_word_days_gen') FROM (SELECT DISTINCT d FROM unnest(days) d WHERE d IS NOT NULL ORDER BY d) x
  ON CONFLICT (day) DO UPDATE SET gen = nextval('mx_word_days_gen')
$$;

CREATE OR REPLACE FUNCTION mx_word_days_posts_rows() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    PERFORM mx_word_days_touch(ARRAY(SELECT mx_word_day(surfaced_at, published_at, fetched_at) FROM new_rows));
  ELSE
    PERFORM mx_word_days_touch(ARRAY(SELECT mx_word_day(surfaced_at, published_at, fetched_at) FROM old_rows));
  END IF;
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mx_word_days_posts_updated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM mx_word_days_touch(ARRAY[mx_word_day(OLD.surfaced_at, OLD.published_at, OLD.fetched_at),
                                   mx_word_day(NEW.surfaced_at, NEW.published_at, NEW.fetched_at)]);
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mx_word_days_search_rows() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    PERFORM mx_word_days_touch(ARRAY(SELECT mx_word_day(p.surfaced_at, p.published_at, p.fetched_at)
                                       FROM new_rows n JOIN posts p ON p.id = n.post_id));
  ELSE
    PERFORM mx_word_days_touch(ARRAY(SELECT mx_word_day(p.surfaced_at, p.published_at, p.fetched_at)
                                       FROM old_rows o JOIN posts p ON p.id = o.post_id));
  END IF;
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mx_word_days_search_updated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  PERFORM mx_word_days_touch(ARRAY(SELECT mx_word_day(p.surfaced_at, p.published_at, p.fetched_at)
                                     FROM posts p WHERE p.id IN (OLD.post_id, NEW.post_id)));
  RETURN NULL;
END $$;

CREATE OR REPLACE FUNCTION mx_word_days_truncated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  DELETE FROM mx_word_days;
  RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS posts_word_days_ins ON posts;
CREATE TRIGGER posts_word_days_ins AFTER INSERT ON posts REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_word_days_posts_rows();
DROP TRIGGER IF EXISTS posts_word_days_del ON posts;
CREATE TRIGGER posts_word_days_del AFTER DELETE ON posts REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_word_days_posts_rows();
-- search_vector is set by posts_search_vector_fill (a BEFORE trigger on title, content, source_id): those columns too.
DROP TRIGGER IF EXISTS posts_word_days_upd ON posts;
CREATE TRIGGER posts_word_days_upd AFTER UPDATE OF title, content, source_id, search_vector, surfaced_at, published_at, fetched_at
    ON posts FOR EACH ROW
    WHEN (OLD.surfaced_at IS DISTINCT FROM NEW.surfaced_at OR OLD.published_at IS DISTINCT FROM NEW.published_at
          OR OLD.fetched_at IS DISTINCT FROM NEW.fetched_at OR OLD.search_vector IS DISTINCT FROM NEW.search_vector)
    EXECUTE FUNCTION mx_word_days_posts_updated();
DROP TRIGGER IF EXISTS posts_word_days_trunc ON posts;
CREATE TRIGGER posts_word_days_trunc AFTER TRUNCATE ON posts FOR EACH STATEMENT EXECUTE FUNCTION mx_word_days_truncated();

DROP TRIGGER IF EXISTS mx_post_search_word_days_ins ON mx_post_search;
CREATE TRIGGER mx_post_search_word_days_ins AFTER INSERT ON mx_post_search REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_word_days_search_rows();
DROP TRIGGER IF EXISTS mx_post_search_word_days_del ON mx_post_search;
CREATE TRIGGER mx_post_search_word_days_del AFTER DELETE ON mx_post_search REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_word_days_search_rows();
DROP TRIGGER IF EXISTS mx_post_search_word_days_upd ON mx_post_search;
CREATE TRIGGER mx_post_search_word_days_upd AFTER UPDATE OF post_id, vector ON mx_post_search FOR EACH ROW
    WHEN (OLD.post_id IS DISTINCT FROM NEW.post_id OR OLD.vector IS DISTINCT FROM NEW.vector)
    EXECUTE FUNCTION mx_word_days_search_updated();
DROP TRIGGER IF EXISTS mx_post_search_word_days_trunc ON mx_post_search;
CREATE TRIGGER mx_post_search_word_days_trunc AFTER TRUNCATE ON mx_post_search
    FOR EACH STATEMENT EXECUTE FUNCTION mx_word_days_truncated();
