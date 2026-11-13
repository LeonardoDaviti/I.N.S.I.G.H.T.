-- 0130_posts_ix_date.sql (Stealth v10.17, issue 0190: one owner per decision, the dates)
--
-- Every post date is one of Pairing's four meanings (markx/pairing.py, "the dates"). Three are indexable:
--   - ordinary_date, COALESCE(surfaced_at, published_at, fetched_at): already indexed since 0037
--     (posts_feed_order_idx, posts_source_feed_order_idx); the feed, the planners, the lease and
--     pairing.post_date_within's own-date bound read them;
--   - ix_date, COALESCE(published_at, fetched_at), Mark IX's time: Mark IX News's windows (repo_news), Mark X News's
--     window posts, Discover's and the statistics' reads scanned every post. This index is on that exact expression
--     (pairing.IX_DATE with no alias);
--   - published_date only orders a story's few lines: no window reads it, no index.
-- post_date (a round-up's issue time, looked up in the round-ups' table) is no index's: its windows go through
-- pairing.post_date_within, which bounds the own date first.
-- No row changes. Idempotent. ANALYZE gives the new expression its statistics at once (without them the planner
-- kept the sequential scan on the scratch copy until the next autovacuum).

CREATE INDEX IF NOT EXISTS posts_ix_date_idx ON posts ((COALESCE(published_at, fetched_at)) DESC, id DESC);
ANALYZE posts;
