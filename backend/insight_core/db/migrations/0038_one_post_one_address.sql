-- 0038_one_post_one_address.sql (issue 0049)
--
-- Two URLs with the same normalized_url are the same post. Until now the saver only compared
-- the exact url, so a source changing how it writes a link (Simon Willison's feed dropping
-- #atom-everything on 13 Aug) saved every post in the feed window a second time. This merges
-- the copies already stored into one row and adds the unique index that keeps them from
-- coming back (the saver resolves it, repo_posts.upsert_post).
--
-- 1. normalized_url follows the normalizer of this issue: http is written https, and a
--    fragment starting with / or ! (#/post/1, #!/post/1: a single-page site's address) is
--    kept. Both run before the merge, so two such pages are never merged as one.
-- 2. Each group sharing a normalized_url keeps one row: the one the owner touched (Later,
--    Keep, read, a position, a note, an open or any logged interaction), else the oldest
--    (first seen). Its url and id stay, so links, read state and positions stay valid.
-- 3. The others' state moves to it: read, Later and Keep if any row has them (the earliest
--    time), the furthest reading position, notes (joined, the kept row's first), the
--    interaction log, and a page watch when the kept row has none. Then the others are
--    deleted. These are every table pointing at posts (pg_constraint, 2026-10-30:
--    post_reader_state, post_notes, post_interactions, post_watch); the migration test
--    fails when a new one appears.
--
-- Nothing to do on a database without copies; a second run changes nothing.

UPDATE posts SET normalized_url = 'https://' || substr(normalized_url, 8)
WHERE normalized_url LIKE 'http://%';

UPDATE posts SET normalized_url = normalized_url || '#' || substring(url FROM '^[^#]*#([/!].*)$')
WHERE normalized_url IS NOT NULL
  AND position('#' IN normalized_url) = 0
  AND url ~ '^[^#]*#[/!]';

CREATE TEMP TABLE post_merge_0038 AS
WITH grouped AS (
  SELECT p.id,
         first_value(p.id) OVER (
           PARTITION BY p.normalized_url
           ORDER BY (
             EXISTS (SELECT 1 FROM post_reader_state r
                     WHERE r.post_id = p.id
                       AND (r.read_at IS NOT NULL OR r.later_at IS NOT NULL OR r.starred_at IS NOT NULL
                            OR r.resume_block IS NOT NULL))
             OR EXISTS (SELECT 1 FROM post_notes n WHERE n.post_id = p.id)
             OR EXISTS (SELECT 1 FROM post_interactions i WHERE i.post_id = p.id)
           ) DESC, p.fetched_at, p.created_at, p.id
         ) AS keep_id,
         count(*) OVER (PARTITION BY p.normalized_url) AS n
    FROM posts p
   WHERE p.normalized_url IS NOT NULL
)
SELECT id AS drop_id, keep_id FROM grouped WHERE n > 1 AND id <> keep_id;

-- Every row of a group, the kept one included, so the aggregates below see all of its state.
CREATE TEMP VIEW post_merge_0038_rows AS
SELECT DISTINCT keep_id, keep_id AS post_id, 0 AS kept_last FROM post_merge_0038
UNION ALL
SELECT keep_id, drop_id, 1 FROM post_merge_0038;

INSERT INTO post_reader_state (post_id, read_at, starred_at, later_at, resume_block, resume_blocks, updated_at)
SELECT m.keep_id,
       min(r.read_at),
       min(r.starred_at),
       min(r.later_at),
       (array_agg(r.resume_block ORDER BY r.resume_block DESC NULLS LAST))[1],
       (array_agg(r.resume_blocks ORDER BY r.resume_block DESC NULLS LAST))[1],
       max(r.updated_at)
  FROM post_merge_0038_rows m
  JOIN post_reader_state r ON r.post_id = m.post_id
 GROUP BY m.keep_id
ON CONFLICT (post_id) DO UPDATE SET
  read_at = EXCLUDED.read_at,
  starred_at = EXCLUDED.starred_at,
  later_at = EXCLUDED.later_at,
  resume_block = EXCLUDED.resume_block,
  resume_blocks = EXCLUDED.resume_blocks,
  updated_at = EXCLUDED.updated_at;

INSERT INTO post_notes (post_id, notes_markdown, created_at, updated_at)
SELECT m.keep_id,
       COALESCE(string_agg(n.notes_markdown, E'\n\n' ORDER BY m.kept_last, n.created_at)
                  FILTER (WHERE n.notes_markdown <> ''), ''),
       min(n.created_at),
       max(n.updated_at)
  FROM post_merge_0038_rows m
  JOIN post_notes n ON n.post_id = m.post_id
 GROUP BY m.keep_id
ON CONFLICT (post_id) DO UPDATE SET
  notes_markdown = EXCLUDED.notes_markdown,
  created_at = EXCLUDED.created_at,
  updated_at = EXCLUDED.updated_at;

UPDATE post_interactions i SET post_id = m.keep_id
  FROM post_merge_0038 m
 WHERE i.post_id = m.drop_id;

INSERT INTO post_watch (post_id, source_id, text_hash, modified, head_missed, etag, last_modified,
                        learned_at, checked_at, changed_at, next_check_at)
SELECT DISTINCT ON (m.keep_id)
       m.keep_id, w.source_id, w.text_hash, w.modified, w.head_missed, w.etag, w.last_modified,
       w.learned_at, w.checked_at, w.changed_at, w.next_check_at
  FROM post_merge_0038 m
  JOIN post_watch w ON w.post_id = m.drop_id
 ORDER BY m.keep_id, w.checked_at DESC NULLS LAST
ON CONFLICT (post_id) DO NOTHING;

-- The copies' own reader state, notes and watch go with them (ON DELETE CASCADE).
DELETE FROM posts p USING post_merge_0038 m WHERE p.id = m.drop_id;

DROP VIEW post_merge_0038_rows;
DROP TABLE post_merge_0038;

-- The unique index serves the lookups the plain one did. NULLs stay allowed (a post without
-- a parseable url has none).
DROP INDEX IF EXISTS posts_normalized_url_idx;
CREATE UNIQUE INDEX IF NOT EXISTS posts_normalized_url_unique ON posts (normalized_url);
