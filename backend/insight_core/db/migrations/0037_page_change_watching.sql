-- 0037_page_change_watching.sql (issue 0039)
--
-- 1. posts.surfaced_at: when a post was put in front of the owner later than its date says.
--    Set for a page first seen long after it was published (a page-based source's listing
--    shows an old page: "new to you is new") and for a watched page whose text changed
--    meaningfully (it comes back). NULL for every other post. The feed's sort key becomes
--    COALESCE(surfaced_at, published_at, fetched_at), so a feed post (surfaced_at NULL) sorts
--    exactly as before; the two feed-order indexes are rebuilt on the new key.
-- 2. post_watch: one row per watched page (a source with settings.watch_changes): the hash of
--    its article text, the date the page states it changed, its validators (ETag,
--    Last-Modified), whether that date lies past the head read first, when it was last checked
--    and changed, and when it is due again. Cascades with the post and the source.
-- Idempotent.

ALTER TABLE posts ADD COLUMN IF NOT EXISTS surfaced_at TIMESTAMPTZ NULL;

DROP INDEX IF EXISTS posts_feed_order_idx;
DROP INDEX IF EXISTS posts_source_feed_order_idx;
CREATE INDEX IF NOT EXISTS posts_feed_order_idx
  ON posts ((COALESCE(surfaced_at, published_at, fetched_at)) DESC, id DESC);
CREATE INDEX IF NOT EXISTS posts_source_feed_order_idx
  ON posts (source_id, (COALESCE(surfaced_at, published_at, fetched_at)) DESC, id DESC);

CREATE TABLE IF NOT EXISTS post_watch (
  post_id       UUID PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  source_id     UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  text_hash     TEXT NOT NULL,
  modified      TEXT NULL,
  head_missed   BOOLEAN NOT NULL DEFAULT false,
  etag          TEXT NULL,
  last_modified TEXT NULL,
  learned_at    TIMESTAMPTZ NULL,
  checked_at    TIMESTAMPTZ NULL,
  changed_at    TIMESTAMPTZ NULL,
  next_check_at TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS post_watch_due_idx ON post_watch (source_id, next_check_at);
