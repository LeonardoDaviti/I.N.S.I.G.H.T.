-- 0020_reader_state.sql (Mark IX, B7)
-- Read state: a per-post projection of the reader's read/starred state.
--
-- post_interactions stays the audit log, but a feed query cannot aggregate it per row
-- cheaply, so the reader reads this projection instead. The two feed-order indexes match
-- the keyset the feed pages on: (COALESCE(published_at, fetched_at), id) descending,
-- globally (scope all/folder) and per source (scope source, by-source groups).

CREATE TABLE IF NOT EXISTS post_reader_state (
  post_id    UUID PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  read_at    TIMESTAMPTZ NULL,
  starred_at TIMESTAMPTZ NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS post_reader_state_starred_idx
  ON post_reader_state (starred_at) WHERE starred_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS posts_feed_order_idx
  ON posts ((COALESCE(published_at, fetched_at)) DESC, id DESC);
CREATE INDEX IF NOT EXISTS posts_source_feed_order_idx
  ON posts (source_id, (COALESCE(published_at, fetched_at)) DESC, id DESC);

-- Backfill from the interaction log: read_at = first open, starred_at = the latest
-- favorite toggle when it was a favorite. Idempotent (ON CONFLICT DO NOTHING).
INSERT INTO post_reader_state (post_id, read_at, starred_at)
SELECT i.post_id,
       MIN(i.created_at) FILTER (WHERE i.interaction_type = 'opened'),
       (SELECT CASE WHEN i2.interaction_type = 'favorited' THEN i2.created_at END
          FROM post_interactions i2
         WHERE i2.post_id = i.post_id AND i2.interaction_type IN ('favorited', 'unfavorited')
         ORDER BY i2.created_at DESC LIMIT 1)
FROM post_interactions i
GROUP BY i.post_id
ON CONFLICT (post_id) DO NOTHING;
