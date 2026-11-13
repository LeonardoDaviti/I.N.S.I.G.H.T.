-- 0131_source_post_stats.sql (Stealth v10.17, issue 0195: the API light and fast)
--
-- Source health (GET /api/sources/health, the Ingestion tab's overview, /api/status) read six correlated subqueries
-- per source over posts on every request, and count(*) and MIN/MAX over every post. Their answers are kept here, one
-- row per source, and read:
--   source_post_stats          the source's post statistics as of its last refresh (db/repo_post_stats.py);
--   source_post_stats_changes  an append-only log: a source whose posts changed since. A source with a row here (or
--                              no stats row) is read live, exactly as before, until the refresh takes it;
--                              so a read is never stale, whoever wrote the posts (ingestion, archives, Save, repairs).
-- The refresh (repo_post_stats.refresh, after each ingestion run) takes the logged rows and recomputes those sources
-- in one statement. Opened posts are not kept: the owner's reading changes them; they are counted live, set-based.
-- No row of posts changes. Idempotent.

CREATE TABLE IF NOT EXISTS source_post_stats (
    source_id        uuid PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
    post_count       bigint NOT NULL DEFAULT 0,
    last_post_at     timestamptz,          -- max(COALESCE(surfaced_at, published_at, fetched_at))
    page_reads       jsonb NOT NULL DEFAULT '[]'::jsonb,   -- metadata.page_read of the newest page-read posts
    paid_preview     boolean,              -- the newest only_paid post was a teaser
    moved            text[],               -- metadata.moved_to of the newest posts
    latest_at        timestamptz,          -- max(COALESCE(published_at, fetched_at)) (the corpus' freshness)
    oldest_at        timestamptz,          -- min(COALESCE(published_at, fetched_at))
    latest_fetch_at  timestamptz,          -- max(fetched_at)
    refreshed_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS source_post_stats_changes (
    id         bigserial PRIMARY KEY,
    source_id  uuid NOT NULL
);
CREATE INDEX IF NOT EXISTS source_post_stats_changes_source_idx ON source_post_stats_changes (source_id);

-- Inserted and deleted posts: once per statement, each source once.
CREATE OR REPLACE FUNCTION source_post_stats_inserted() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO source_post_stats_changes (source_id) SELECT DISTINCT source_id FROM changed_rows;
    RETURN NULL;
END $$;

-- An updated post whose kept statistics may move (the WHEN of the trigger below): its old and its new source.
CREATE OR REPLACE FUNCTION source_post_stats_updated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    INSERT INTO source_post_stats_changes (source_id) VALUES (NEW.source_id);
    IF OLD.source_id IS DISTINCT FROM NEW.source_id THEN
        INSERT INTO source_post_stats_changes (source_id) VALUES (OLD.source_id);
    END IF;
    RETURN NULL;
END $$;

-- TRUNCATE posts (tests): nothing kept stands.
CREATE OR REPLACE FUNCTION source_post_stats_truncated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM source_post_stats;
    RETURN NULL;
END $$;

DROP TRIGGER IF EXISTS posts_stats_inserted ON posts;
CREATE TRIGGER posts_stats_inserted AFTER INSERT ON posts REFERENCING NEW TABLE AS changed_rows
    FOR EACH STATEMENT EXECUTE FUNCTION source_post_stats_inserted();

DROP TRIGGER IF EXISTS posts_stats_deleted ON posts;
CREATE TRIGGER posts_stats_deleted AFTER DELETE ON posts REFERENCING OLD TABLE AS changed_rows
    FOR EACH STATEMENT EXECUTE FUNCTION source_post_stats_inserted();

DROP TRIGGER IF EXISTS posts_stats_updated ON posts;
CREATE TRIGGER posts_stats_updated AFTER UPDATE OF source_id, surfaced_at, published_at, fetched_at, metadata ON posts
    FOR EACH ROW WHEN (
        OLD.source_id IS DISTINCT FROM NEW.source_id
        OR OLD.surfaced_at IS DISTINCT FROM NEW.surfaced_at
        OR OLD.published_at IS DISTINCT FROM NEW.published_at
        OR OLD.fetched_at IS DISTINCT FROM NEW.fetched_at
        OR (OLD.metadata -> 'page_read') IS DISTINCT FROM (NEW.metadata -> 'page_read')
        OR (OLD.metadata ->> 'audience') IS DISTINCT FROM (NEW.metadata ->> 'audience')
        OR (OLD.metadata ->> 'paywalled') IS DISTINCT FROM (NEW.metadata ->> 'paywalled')
        OR (OLD.metadata ->> 'moved_to') IS DISTINCT FROM (NEW.metadata ->> 'moved_to'))
    EXECUTE FUNCTION source_post_stats_updated();

DROP TRIGGER IF EXISTS posts_stats_truncated ON posts;
CREATE TRIGGER posts_stats_truncated AFTER TRUNCATE ON posts
    FOR EACH STATEMENT EXECUTE FUNCTION source_post_stats_truncated();

-- Every source kept now (repo_post_stats.COLUMNS as of 0131), so no read after the deploy counts posts per source.
INSERT INTO source_post_stats (source_id, post_count, last_post_at, page_reads, paid_preview, moved, latest_at,
                               oldest_at, latest_fetch_at)
SELECT s.id,
       (SELECT count(*) FROM posts p WHERE p.source_id = s.id),
       (SELECT max(COALESCE(p.surfaced_at, p.published_at, p.fetched_at)) FROM posts p WHERE p.source_id = s.id),
       (SELECT COALESCE(jsonb_agg(r.page_read ORDER BY r.fetched_at DESC), '[]'::jsonb)
          FROM (SELECT p.metadata -> 'page_read' AS page_read, p.fetched_at FROM posts p
                 WHERE p.source_id = s.id AND p.metadata ? 'page_read'
                 ORDER BY p.fetched_at DESC LIMIT 8) r),
       (SELECT (p.metadata ->> 'paywalled')::boolean FROM posts p
         WHERE p.source_id = s.id AND p.metadata ->> 'audience' = 'only_paid'
         ORDER BY p.fetched_at DESC LIMIT 1),
       (SELECT array_agg(r.moved) FROM (SELECT p.metadata ->> 'moved_to' AS moved FROM posts p
         WHERE p.source_id = s.id
         ORDER BY COALESCE(p.surfaced_at, p.published_at, p.fetched_at) DESC, p.id DESC LIMIT 10) r),
       (SELECT max(COALESCE(p.published_at, p.fetched_at)) FROM posts p WHERE p.source_id = s.id),
       (SELECT min(COALESCE(p.published_at, p.fetched_at)) FROM posts p WHERE p.source_id = s.id),
       (SELECT max(p.fetched_at) FROM posts p WHERE p.source_id = s.id)
  FROM sources s
ON CONFLICT (source_id) DO NOTHING;

-- The corpus' last-24-hours count (/api/status) by index, not a scan of every post.
CREATE INDEX IF NOT EXISTS posts_fetched_at_idx ON posts (fetched_at);
