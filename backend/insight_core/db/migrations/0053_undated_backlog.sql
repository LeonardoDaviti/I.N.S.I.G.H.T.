-- 0053_undated_backlog.sql (issue 0070, B1)
--
-- Undated posts don't flood the feed. A post its feed gave no date sorts at the moment it was
-- fetched (COALESCE(surfaced_at, published_at, fetched_at)), so a new source whose feed has no dates
-- put its whole backlog at the top (Google Developers Blog's 20 rows led the Main feed on the lab).
-- A source's first fetch is its backlog: its undated posts sort below the source's dated posts, at
-- the start of the UTC day of the second before its oldest dated post, or before that fetch, which
-- reads as a date alone. The saver does this for each first fetch (repo_posts.UNDATED_BACKLOG_SQL),
-- a microsecond apart in the feed's order; a later fetch's undated post is new and sorts at its fetch.
--
-- The stored ones: a source's undated posts saved at its first fetch moment (its earliest
-- fetched_at) and not surfaced. Their feed order was not stored; they keep the order the feed shows
-- them in today (id, newest first). On the lab (2026-11-01): 59 posts, Google Developers Blog 20
-- (30 Oct), chadnauseam.com 20 (23 Mar), GitHub Trending 14 (27 Oct), paul graham 5 (31 Mar 2001,
-- the day before his oldest dated essay). Idempotent: a placed post has surfaced_at.

WITH firsts AS (
  SELECT source_id, min(fetched_at) AS fetched_at, min(published_at) AS oldest FROM posts GROUP BY source_id
), placed AS (
  SELECT p.id,
         date_trunc('day', LEAST(p.fetched_at, f.oldest) - interval '1 second', 'UTC')
         + (count(*) OVER (PARTITION BY p.source_id)
            - row_number() OVER (PARTITION BY p.source_id ORDER BY p.id DESC) + 1) * interval '1 microsecond' AS at
  FROM posts p JOIN firsts f ON f.source_id = p.source_id AND p.fetched_at = f.fetched_at
  WHERE p.published_at IS NULL AND p.surfaced_at IS NULL
)
UPDATE posts p SET surfaced_at = placed.at FROM placed WHERE p.id = placed.id;
