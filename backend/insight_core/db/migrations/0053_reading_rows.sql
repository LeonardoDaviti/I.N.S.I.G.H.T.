-- 0053_reading_rows.sql (issue 0070, B1 and B6)
--
-- 1. Undated posts don't flood the feed (B1). A post its feed gave no date sorts at the moment it
-- was fetched (COALESCE(surfaced_at, published_at, fetched_at)), so a new source whose feed has no
-- dates put its whole backlog at the top (Google Developers Blog's 20 rows led the Main feed on the
-- lab). A source's first fetch is its backlog: its undated posts sort below the source's dated
-- posts, at the start of the UTC day of the second before its oldest dated post, or before that
-- fetch, which reads as a date alone. The saver does this for each first fetch
-- (repo_posts.UNDATED_BACKLOG_SQL), a microsecond apart in the feed's order; a later fetch's undated
-- post is new and sorts at its fetch.
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

-- 2. An album whose caption came last is one post too (B6, 0069 B4's Left open). 0051 folds the
-- text-less pictures after a post into it; when the pictures come first (their run's head has no
-- text) and the channel's next post, within 2 minutes of the last of them, has the text, that post
-- holds them all. On the lab: 17 albums, 30 pictures (12 of the albums 0 seconds before their caption).

CREATE OR REPLACE FUNCTION fold_telegram_albums(only_source uuid) RETURNS integer
LANGUAGE sql AS $fn$
  WITH ordered AS (
    SELECT id, source_id, published_at,
           row_number() OVER (PARTITION BY source_id ORDER BY published_at, length(url), url) AS n,
           btrim(coalesce(content, '')) = '' AND media_urls <> '[]'::jsonb AS textless
    FROM posts
    WHERE url LIKE 'https://t.me/%' AND published_at IS NOT NULL
      AND (only_source IS NULL OR source_id = only_source)
  ), pieces AS (
    SELECT id, source_id, n, textless, published_at,
           textless AND published_at - lag(published_at) OVER (PARTITION BY source_id ORDER BY n)
                        <= interval '2 minutes' AS piece
    FROM ordered
  ), runs AS (
    SELECT id, source_id, n, piece, textless, published_at,
           count(*) FILTER (WHERE NOT piece OR piece IS NULL) OVER (PARTITION BY source_id ORDER BY n) AS run
    FROM pieces
  ), captions AS (
    SELECT r.source_id, r.run, next.id AS caption
    FROM (SELECT source_id, run, max(n) AS last_n, max(published_at) AS last_at, bool_and(textless) AS textless
          FROM runs GROUP BY source_id, run) r
    JOIN ordered next ON next.source_id = r.source_id AND next.n = r.last_n + 1
    WHERE r.textless AND NOT next.textless AND next.published_at - r.last_at <= interval '2 minutes'
  ), held AS (
    SELECT runs.id, COALESCE(captions.caption,
           CASE WHEN piece THEN first_value(runs.id) OVER (PARTITION BY runs.source_id, runs.run ORDER BY n) END) AS album_of
    FROM runs LEFT JOIN captions ON captions.source_id = runs.source_id AND captions.run = runs.run
  ), changed AS (
    UPDATE posts p SET album_of = held.album_of
    FROM held
    WHERE p.id = held.id AND p.album_of IS DISTINCT FROM held.album_of
    RETURNING 1
  )
  SELECT count(*)::integer FROM changed
$fn$;

SELECT fold_telegram_albums(NULL);
