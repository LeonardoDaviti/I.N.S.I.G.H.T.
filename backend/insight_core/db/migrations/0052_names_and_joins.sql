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
-- Safe to run again (the links are read once more).

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
