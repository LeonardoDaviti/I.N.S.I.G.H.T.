-- 0051_telegram_albums.sql (issue 0069, B4)
--
-- A Telegram album is one post. The bridge sends each picture of an album as its own item, with
-- no text and a placeholder title ("[Photo]"). posts.album_of names the post such a piece belongs
-- to; the feed, its counts and search leave the piece out, the post page shows its pictures in
-- that post's body, and reading that post reads it (repo_reader). Nothing is deleted.
--
-- The rule (fold_telegram_albums), measured on the lab copy (2026-10-31): a Telegram post (its
-- address on t.me) with no text and some media, posted at most 2 minutes after its channel's
-- previous post, is a piece of the run it continues; the run's first post holds it. Of the 2,353
-- text-less "[Photo]/[Video]/[Media]" rows, 2,188 come within 2 minutes (1,652 within 10 s), and
-- 2,055 of those are the very next message; between 2 and 10 minutes there are 31.
-- The saver calls it for a channel after each batch (repo_posts.save_batch). Idempotent.

ALTER TABLE posts ADD COLUMN IF NOT EXISTS album_of uuid REFERENCES posts(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS posts_album_of_idx ON posts (album_of) WHERE album_of IS NOT NULL;

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
    SELECT id, source_id, n,
           textless AND published_at - lag(published_at) OVER (PARTITION BY source_id ORDER BY n)
                        <= interval '2 minutes' AS piece
    FROM ordered
  ), runs AS (
    SELECT id, source_id, n, piece,
           count(*) FILTER (WHERE NOT piece OR piece IS NULL) OVER (PARTITION BY source_id ORDER BY n) AS run
    FROM pieces
  ), held AS (
    SELECT id, CASE WHEN piece THEN first_value(id) OVER (PARTITION BY source_id, run ORDER BY n) END AS album_of
    FROM runs
  ), changed AS (
    UPDATE posts p SET album_of = held.album_of
    FROM held
    WHERE p.id = held.id AND p.album_of IS DISTINCT FROM held.album_of
    RETURNING 1
  )
  SELECT count(*)::integer FROM changed
$fn$;

SELECT fold_telegram_albums(NULL);
