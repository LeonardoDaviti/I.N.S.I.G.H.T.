-- 0052_names_and_joins.sql (issue 0070, part A)
--
-- 1. Search compares styled letters as plain ones (A3). The index and the query read text after
--    NFKC (normalize(..., NFKC)): "𝙻𝙵𝙼𝟹" is "LFM3", a no-break space a space, "ﬁ" "fi". What is
--    shown is unchanged. search_vector_version() becomes 3, so the background fill
--    (ReaderService.fill_search_vectors, 0042) refills every post's vector; until it is done an
--    older vector matches as it did. Measured on the lab: 851 of 41,619 titles and 6,174 texts change.
-- 2. Every post's links are read again (A4): a link to another publication on its site (a Substack
--    writer linking another) is kept now, where it was dropped as the post's own site. The story job
--    reads them (StoriesRepository.fill_missing_links), 500 a transaction (41,689 posts: ~45 s on
--    the lab), and marks a publisher's own other hosts boilerplate.
-- 3. One source, one title, one body, two addresses is one post (A5, extends 0049). A host move
--    (blog.ai-futures.org, blog.aifutures.org), a renamed slug or a feed's ?src=feed saved one post
--    twice. Two posts of one source are one when their titles are equal (post_title_key), they are
--    posted within a day of each other, and their bodies are the same (same_post_body: the same
--    content_hash, or one's opening is the other: a teaser and its full text, or one is empty). Not
--    at a platform's own post address (platform_post_address: a tweet, a Telegram post, a Reddit
--    thread, a YouTube video), where the same words twice are two posts. The newer address wins:
--    the row seen last stays, the others' read state, Later, Keep, position, notes, opens and page
--    watch move to it as 0038 moves them, and it keeps the longest body. The saver uses the same
--    functions (repo_posts._same_post_elsewhere). Measured on the lab: 52 pairs in 11 sources;
--    Smol's daily "not much happened today" and Xeiaso's "No way to prevent this" stay apart (their
--    bodies differ), but for two Smol issues with one identical body.
--    Before it, normalized_url drops a trailing / in a query value, as the normalizer now does
--    (The Old New Thing's ?p=112711/): those pairs then share an address, and merge here too.
-- Safe to run again (the links are read once more; the rest finds nothing left to do).

CREATE OR REPLACE FUNCTION search_vector_version() RETURNS integer
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT 3 $$;

CREATE OR REPLACE FUNCTION post_search_vector(title text, content text, source_name text)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT search_vector_with_parts(
         setweight(to_tsvector('russian', normalize(COALESCE(title, ''), NFKC)), 'A')
      -- "https://www.simonwillison.net/atom/" reads as "simonwillison net atom".
      || setweight(to_tsvector('russian', regexp_replace(normalize(COALESCE(source_name, ''), NFKC), '^https?://(www\.)?|[./:_-]+', ' ', 'g')), 'B')
      || setweight(to_tsvector('russian', normalize(left(COALESCE(content, ''), 200000), NFKC)), 'D'))
$$;

-- 0042's query, its text first made plain (NFKC) as the index is.
CREATE OR REPLACE FUNCTION search_query(q text) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT COALESCE(string_agg(
           CASE WHEN w.parts IS NULL OR (t.in_phrase AND cardinality(array_remove(w.parts, NULL)) > 1) THEN t.tok
                ELSE '(' || t.tok || ' | ' || search_parts_phrase(w.parts) || ')' END,
           '' ORDER BY t.n), '')::tsquery
  FROM (
    SELECT m.a[1] AS tok, m.n,
           COALESCE(lag(m.a[1]) OVER (ORDER BY m.n) ~ '>\s*$', FALSE)
             OR COALESCE(lead(m.a[1]) OVER (ORDER BY m.n) ~ '^\s*<', FALSE) AS in_phrase
    FROM regexp_matches(websearch_to_tsquery('russian', normalize($1, NFKC))::text, '''(?:[^'']|'''')*''|[^'']+', 'g') WITH ORDINALITY AS m(a, n)
  ) AS t
  CROSS JOIN LATERAL (
    SELECT CASE WHEN left(t.tok, 1) = ''''
                THEN search_version_parts(replace(substr(t.tok, 2, length(t.tok) - 2), '''''', '''')) END AS parts
  ) AS w
$$;

UPDATE posts SET links_scanned_at = NULL WHERE links_scanned_at IS NOT NULL;

UPDATE posts
   SET normalized_url = split_part(normalized_url, '?', 1) || '?'
                        || regexp_replace(substr(normalized_url, strpos(normalized_url, '?') + 1), '(%2F)+(?=&|#|$)', '', 'g')
 WHERE normalized_url ~ '\?[^#]*%2F(&|#|$)';

-- A platform's own post address: there an id is the post, and the same words twice are two posts.
CREATE OR REPLACE FUNCTION platform_post_address(url text) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT COALESCE(url ~ '^https://(x\.com/[^/]+/status/|t\.me/[^/]+/[0-9]|reddit\.com/r/[^/]+/comments/|youtube\.com/watch)', false)
$$;

-- A body's opening as two posts compare it: its first 2,000 characters by post_title_key (entities,
-- spaces, case), a trailing "…", "..." or "[...]" dropped.
CREATE OR REPLACE FUNCTION post_body_opening(content text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT regexp_replace(post_title_key(left(COALESCE(content, ''), 2000)), '\s*(…|\.\.\.|\[\.\.\.\]|\[…\])$', '')
$$;

-- The same body: the same hash, or one's opening opens the other (a teaser and its text; an empty one).
CREATE OR REPLACE FUNCTION same_post_body(a_hash text, a_content text, b_hash text, b_content text) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT a_hash = b_hash OR starts_with(x, y) OR starts_with(y, x)
    FROM (SELECT post_body_opening(a_content) AS x, post_body_opening(b_content) AS y) AS t
$$;

CREATE TEMP TABLE post_pairs_0052 AS
SELECT a.id AS a, b.id AS b
  FROM posts a
  JOIN posts b ON b.source_id = a.source_id AND b.id <> a.id
              AND post_title_key(b.title) = post_title_key(a.title)
 WHERE post_title_key(a.title) <> '' AND a.album_of IS NULL AND b.album_of IS NULL
   AND a.normalized_url IS NOT NULL AND b.normalized_url IS NOT NULL
   AND NOT platform_post_address(a.normalized_url) AND NOT platform_post_address(b.normalized_url)
   AND abs(extract(epoch FROM COALESCE(a.published_at, a.fetched_at) - COALESCE(b.published_at, b.fetched_at))) <= 86400
   AND same_post_body(a.content_hash, a.content, b.content_hash, b.content);

-- Each post's group (pairs joined through a shared post), kept at its newest row (the last seen).
CREATE TEMP TABLE post_merge_0052 AS
WITH RECURSIVE reach(id, other) AS (
  SELECT a, b FROM post_pairs_0052
  UNION
  SELECT r.id, p.b FROM reach r JOIN post_pairs_0052 p ON p.a = r.other
), grouped AS (
  SELECT r.id, (array_agg(p.id ORDER BY p.fetched_at DESC, p.created_at DESC, p.id DESC))[1] AS keep_id
    FROM (SELECT id, other FROM reach UNION SELECT id, id FROM reach) r
    JOIN posts p ON p.id = r.other
   GROUP BY r.id
)
SELECT id AS drop_id, keep_id FROM grouped WHERE id <> keep_id;

CREATE TEMP VIEW post_merge_0052_rows AS
SELECT DISTINCT keep_id, keep_id AS post_id, 0 AS kept_last FROM post_merge_0052
UNION ALL
SELECT keep_id, drop_id, 1 FROM post_merge_0052;

INSERT INTO post_reader_state (post_id, read_at, starred_at, later_at, resume_block, resume_blocks, updated_at)
SELECT m.keep_id, min(r.read_at), min(r.starred_at), min(r.later_at),
       (array_agg(r.resume_block ORDER BY r.resume_block DESC NULLS LAST))[1],
       (array_agg(r.resume_blocks ORDER BY r.resume_block DESC NULLS LAST))[1],
       max(r.updated_at)
  FROM post_merge_0052_rows m
  JOIN post_reader_state r ON r.post_id = m.post_id
 GROUP BY m.keep_id
ON CONFLICT (post_id) DO UPDATE SET
  read_at = EXCLUDED.read_at, starred_at = EXCLUDED.starred_at, later_at = EXCLUDED.later_at,
  resume_block = EXCLUDED.resume_block, resume_blocks = EXCLUDED.resume_blocks, updated_at = EXCLUDED.updated_at;

INSERT INTO post_notes (post_id, notes_markdown, created_at, updated_at)
SELECT m.keep_id,
       COALESCE(string_agg(n.notes_markdown, E'\n\n' ORDER BY m.kept_last, n.created_at)
                  FILTER (WHERE n.notes_markdown <> ''), ''),
       min(n.created_at), max(n.updated_at)
  FROM post_merge_0052_rows m
  JOIN post_notes n ON n.post_id = m.post_id
 GROUP BY m.keep_id
ON CONFLICT (post_id) DO UPDATE SET
  notes_markdown = EXCLUDED.notes_markdown, created_at = EXCLUDED.created_at, updated_at = EXCLUDED.updated_at;

UPDATE post_interactions i SET post_id = m.keep_id FROM post_merge_0052 m WHERE i.post_id = m.drop_id;

INSERT INTO post_watch (post_id, source_id, text_hash, modified, head_missed, etag, last_modified,
                        learned_at, checked_at, changed_at, next_check_at)
SELECT DISTINCT ON (m.keep_id)
       m.keep_id, w.source_id, w.text_hash, w.modified, w.head_missed, w.etag, w.last_modified,
       w.learned_at, w.checked_at, w.changed_at, w.next_check_at
  FROM post_merge_0052 m
  JOIN post_watch w ON w.post_id = m.drop_id
 ORDER BY m.keep_id, w.checked_at DESC NULLS LAST
ON CONFLICT (post_id) DO NOTHING;

-- The kept row keeps the longest body of its group (a teaser's newer address must not cost the text).
UPDATE posts k
   SET content = l.content, content_html = l.content_html, content_hash = l.content_hash, links_scanned_at = NULL
  FROM (SELECT DISTINCT ON (m.keep_id) m.keep_id, d.content, d.content_html, d.content_hash, length(d.content) AS chars
          FROM post_merge_0052 m JOIN posts d ON d.id = m.drop_id
         ORDER BY m.keep_id, length(d.content) DESC NULLS LAST) l
 WHERE k.id = l.keep_id AND l.chars > COALESCE(length(k.content), 0);

-- The copies' own reader state, notes and watch go with them (ON DELETE CASCADE); stories,
-- News and classics are derived (the story job regroups everything: RULES_VERSION).
DELETE FROM posts p USING post_merge_0052 m WHERE p.id = m.drop_id;

DROP VIEW post_merge_0052_rows;
DROP TABLE post_merge_0052;
DROP TABLE post_pairs_0052;
