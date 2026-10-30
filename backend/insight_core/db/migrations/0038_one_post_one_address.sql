-- 0038_one_post_one_address.sql (issue 0049)
--
-- Two posts are the same post when their normalized_url is equal AND their titles are equal
-- under post_title_key (case, whitespace, HTML entities). Until now the saver only compared
-- the exact url, so a source changing how it writes a link (Simon Willison's feed dropping
-- #atom-everything on 13 Aug) saved every post in the feed window a second time. This merges
-- the copies already stored into one row; the saver keeps them from coming back
-- (repo_posts.upsert_post).
--
-- The address alone is not enough: on the server's data Daring Fireball links different
-- posts under one address, told apart only by a footnote fragment (#fn1-...), a text fragment
-- (#:~:text=...) or utm_campaign (WorkOS sponsor posts). Their titles differ; they stay apart.
--
-- Edited in place before deploying (2026-10-30). The first version merged on normalized_url
-- alone and made it a unique index (posts_normalized_url_unique); it ran only on
-- insight_preview and insight_lab. There 0041 defines post_title_key and drops that unique
-- index; what the first version merged stays merged. Everywhere else this file runs as
-- written here and never creates the unique index.
--
-- 0. post_title_key(title): the one title rule, used here and by the saver. 0041 repeats this
--    definition (CREATE OR REPLACE) for the databases that ran the first version; the
--    migration test checks the two are the same.
-- 1. normalized_url follows the normalizer of this issue: http is written https, and a
--    fragment starting with / or ! (#/post/1, #!/post/1: a single-page site's address) is
--    kept. Both run before the merge, so two such pages are never merged as one.
-- 2. Each group sharing a normalized_url and a post_title_key keeps one row: the one the
--    owner touched (Later, Keep, read, a position, a note, an open or any logged
--    interaction), else the oldest (first seen). Its url and id stay, so links, read state
--    and positions stay valid.
-- 3. The others' state moves to it: read, Later and Keep if any row has them (the earliest
--    time), the furthest reading position, notes (joined, the kept row's first), the
--    interaction log, and a page watch when the kept row has none. Then the others are
--    deleted. These are every table pointing at posts (pg_constraint, 2026-10-30:
--    post_reader_state, post_notes, post_interactions, post_watch); the migration test
--    fails when a new one appears.
--
-- Nothing to do on a database without copies; a second run changes nothing.

-- post_title_key: HTML entities decoded (the named ones feeds use, and every numeric one),
-- non-breaking spaces as spaces, whitespace runs as one space, trimmed, lower case; no title
-- is ''. '&' is decoded last, through a placeholder, so '&amp;lt;' gives '&lt;' as one
-- unescape does.
CREATE OR REPLACE FUNCTION post_title_key(title text) RETURNS text
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $fn$
DECLARE
  t text := replace(coalesce(title, ''), chr(1), '');
  m text[];
  code bigint;
BEGIN
  t := replace(replace(replace(replace(replace(replace(t,
         '&lt;', '<'), '&gt;', '>'), '&quot;', '"'), '&apos;', ''''), '&nbsp;', ' '), '&AMP;', '&amp;');
  t := replace(replace(replace(replace(replace(replace(replace(t,
         '&hellip;', '…'), '&mdash;', '—'), '&ndash;', '–'), '&lsquo;', '‘'), '&rsquo;', '’'),
         '&ldquo;', '“'), '&rdquo;', '”');
  LOOP
    m := regexp_match(t, '&#([xX][0-9a-fA-F]{1,6}|[0-9]{1,7});');
    EXIT WHEN m IS NULL;
    IF m[1] ~ '^[xX]' THEN
      code := ('x' || lpad(substr(m[1], 2), 8, '0'))::bit(32)::bigint;
    ELSE
      code := m[1]::bigint;
    END IF;
    t := replace(t, '&#' || m[1] || ';',
                 CASE WHEN code = 38 THEN chr(1)
                      WHEN code BETWEEN 1 AND 1114111 AND code NOT BETWEEN 55296 AND 57343 THEN chr(code::int)
                      ELSE '' END);
  END LOOP;
  t := replace(replace(t, '&amp;', chr(1)), chr(1), '&');
  RETURN lower(btrim(regexp_replace(translate(t, chr(160), ' '), '\s+', ' ', 'g')));
END
$fn$;

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
           PARTITION BY p.normalized_url, post_title_key(p.title)
           ORDER BY (
             EXISTS (SELECT 1 FROM post_reader_state r
                     WHERE r.post_id = p.id
                       AND (r.read_at IS NOT NULL OR r.later_at IS NOT NULL OR r.starred_at IS NOT NULL
                            OR r.resume_block IS NOT NULL))
             OR EXISTS (SELECT 1 FROM post_notes n WHERE n.post_id = p.id)
             OR EXISTS (SELECT 1 FROM post_interactions i WHERE i.post_id = p.id)
           ) DESC, p.fetched_at, p.created_at, p.id
         ) AS keep_id,
         count(*) OVER (PARTITION BY p.normalized_url, post_title_key(p.title)) AS n
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

-- posts_normalized_url_idx (0007) stays a plain index: the same address under another title
-- is another post, which a unique index on normalized_url cannot allow.
