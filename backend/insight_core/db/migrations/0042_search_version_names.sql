-- 0042_search_version_names.sql (issue 0056)
--
-- Search reads version names. Postgres' parser keeps a word that joins letters and a version as
-- one word: "Kimi K3.1 Pro" is `kimi`, `k3.1`, `pro`, so "kimi 3.1" never found it; "GPT-6.1" is
-- `gpt`, `-6.1` (a signed number), so "gpt 6.1" never found that.
--
-- One rule, for the index and the query, with no list of names (search_version_parts): a
-- version word is a word of letters, digits, dots and hyphens with a letter right before a digit
-- (k3.1, qwen3.8, gpt6, h100, deepseek-v4, qwen3.6-35b-a3b), or a signed number (-6.1, the "-4"
-- of Gemini-4). Its parts are its runs of letters and of numbers (a number keeps its dots), the
-- letters stemmed as any word is: k3.1 -> k, 3.1; qwen3.8-max -> qwen, 3.8, max; claude3 ->
-- claud, 3; -6.1 -> 6.1. Not split: a run like a hash or an id (a3f9c2, 26b5c67b: letters and
-- digits alternating 4 times or more inside one hyphenated piece), a word over 64 characters,
-- anything with / _ : @ (addresses, paths). A part that is a stop word ("a", "s") is left out but
-- keeps its place; a word left with fewer than two parts is not split (a100 would be just 100).
--
-- * The index (search_vector_with_parts): a version word is kept as it is, and its parts are
--   added at its place, the last part at the word's own position and each earlier part one
--   before it (from position 1 on, near the start). So every phrase that matched still matches
--   ("kimi k3.1 pro"), and the parts read as words in a row: "kimi 3.1" as a phrase matches too.
-- * The query (search_query): websearch_to_tsquery as before, then each version word W of it
--   becomes (W | part1 <-> part2 ...): "K3.1" finds K3.1 and "K 3.1"; "GPT-6.1" finds GPT-6.1,
--   GPT 6.1 and GPT6.1. W itself stays in, so a vector not refilled yet matches what it did.
--   Inside a phrase (quoted, or a hyphenated word websearch_to_tsquery reads as one) a W of two
--   or more parts stays as written: Postgres gives an OR inside a phrase the width of its longest
--   side, so ("kimi" <-> (k3.1 | k <-> 3.1) <-> "pro") would no longer find "Kimi K3.1 Pro"
--   (measured: 21 of 22 lost). A one-part W is safe there ("GPT-6.1" is 'gpt' <-> ('-6.1' |
--   '6.1')), and a phrase still finds the parts at their places ("kimi 3.1" quoted finds K3.1).
--
-- The stored vectors are not rewritten here (41k posts; 0033 measured why a migration must not).
-- posts.search_version says which rule made a post's vector: NULL is 0033's, and
-- search_vector_version() is the current one (2). The trigger writes the current version with
-- every vector; the backend's background fill (ReaderService.fill_search_vectors, from the app's
-- lifespan) refills, 500 posts a transaction, every post whose vector is missing or whose
-- version is not the current one. Until it is done an older post matches as it did before.
-- A later change to post_search_vector bumps search_vector_version() in its migration, and the
-- same fill refills every post again. Adding the column rewrites nothing (no default). Idempotent.

-- The parts of one lexeme in order, a stop word's place as NULL; NULL when it is no version
-- word (see above).
CREATE OR REPLACE FUNCTION search_version_parts(word text) RETURNS text[]
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN count(stem) >= 2 OR (count(stem) = 1 AND $1 ~ '^-') THEN array_agg(stem ORDER BY n) END
  FROM (
    SELECT m.n,
           CASE WHEN m.a[1] ~ '^[0-9]' THEN m.a[1]
                ELSE (SELECT t.lexeme FROM unnest(to_tsvector('russian', m.a[1])) AS t LIMIT 1) END AS stem
    FROM regexp_matches($1, '[0-9]+(?:\.[0-9]+)*|[[:alpha:]]+', 'g') WITH ORDINALITY AS m(a, n)
    WHERE length($1) <= 64
      AND $1 ~ '^[[:alpha:][:digit:].-]+$'
      AND (($1 ~ '[[:alpha:]][0-9]'
            AND translate($1, '.', '') !~ '[[:alpha:]][0-9]+[[:alpha:]]+[0-9]|[0-9][[:alpha:]]+[0-9]+[[:alpha:]]')
           OR $1 ~ '^-[0-9]+(\.[0-9]+)*$')
  ) parts
$$;

-- A vector with its version words' parts added at their places, with the word's weight: in a
-- row ending at the word's position, each earlier part one before it; a word too near the start
-- for that ("Qwen3.8-Max lands", position 1) starts its row at 1 instead. Past position
-- 16,383 (a tsvector's last; every later word of a long text is there) the parts stay at
-- 16,383: one before it is another word's place, and "K3.1" would match any "k" next to a
-- "3.1" in a long digest (measured: 15 of 16 posts gained by "K3.1" on the lab).
CREATE OR REPLACE FUNCTION search_vector_with_parts(v tsvector) RETURNS tsvector
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT CASE WHEN x.extra IS NULL THEN v ELSE (v::text || ' ' || x.extra)::tsvector END
  FROM (
    SELECT string_agg(format('%L:%s%s', pt.part,
                             CASE WHEN pw.pos >= 16383 THEN 16383
                                  ELSE greatest(1, pw.pos - cardinality(w.parts) + 1) + pt.n - 1 END,
                             pw.weight), ' ') AS extra
    FROM unnest(v) AS u(lexeme, positions, weights)
    CROSS JOIN LATERAL (SELECT search_version_parts(u.lexeme) AS parts) AS w
    CROSS JOIN LATERAL unnest(u.positions, u.weights) AS pw(pos, weight)
    CROSS JOIN LATERAL unnest(w.parts) WITH ORDINALITY AS pt(part, n)
    WHERE u.lexeme ~ '[[:alpha:]][0-9]|^-[0-9]' AND w.parts IS NOT NULL AND pt.part IS NOT NULL
  ) AS x
$$;

-- The parts as a phrase: 'k' <-> '3.1'; a stop word's place widens the step
-- ('qwen' <-> '3.6' <-> '35' <-> 'b' <2> '3' <-> 'b').
CREATE OR REPLACE FUNCTION search_parts_phrase(parts text[]) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT string_agg(CASE WHEN prev IS NULL THEN '' WHEN i - prev = 1 THEN ' <-> ' ELSE format(' <%s> ', i - prev) END
                    || quote_literal(part), '' ORDER BY i)
  FROM (SELECT part, i, lag(i) OVER (ORDER BY i) AS prev
        FROM unnest(parts) WITH ORDINALITY AS p(part, i) WHERE part IS NOT NULL) AS kept
$$;

-- A search's words: websearch_to_tsquery, each version word W becoming (W | its parts as a phrase).
CREATE OR REPLACE FUNCTION search_query(q text) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT COALESCE(string_agg(
           CASE WHEN w.parts IS NULL OR (t.in_phrase AND cardinality(array_remove(w.parts, NULL)) > 1) THEN t.tok
                ELSE '(' || t.tok || ' | ' || search_parts_phrase(w.parts) || ')' END,
           '' ORDER BY t.n), '')::tsquery
  FROM (
    -- The query's text as its quoted lexemes and what lies between them; a lexeme next to a
    -- phrase operator (<-> or <N>) is in a "quoted phrase".
    SELECT m.a[1] AS tok, m.n,
           COALESCE(lag(m.a[1]) OVER (ORDER BY m.n) ~ '>\s*$', FALSE)
             OR COALESCE(lead(m.a[1]) OVER (ORDER BY m.n) ~ '^\s*<', FALSE) AS in_phrase
    FROM regexp_matches(websearch_to_tsquery('russian', $1)::text, '''(?:[^'']|'''')*''|[^'']+', 'g') WITH ORDINALITY AS m(a, n)
  ) AS t
  CROSS JOIN LATERAL (
    SELECT CASE WHEN left(t.tok, 1) = ''''
                THEN search_version_parts(replace(substr(t.tok, 2, length(t.tok) - 2), '''''', '''')) END AS parts
  ) AS w
$$;

-- Which rule made a post's vector (see above). Bump it when post_search_vector changes.
CREATE OR REPLACE FUNCTION search_vector_version() RETURNS integer
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$ SELECT 2 $$;

ALTER TABLE posts ADD COLUMN IF NOT EXISTS search_version integer;

-- 0033's vector, with the version words' parts.
CREATE OR REPLACE FUNCTION post_search_vector(title text, content text, source_name text)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT search_vector_with_parts(
         setweight(to_tsvector('russian', COALESCE(title, '')), 'A')
      -- "https://www.simonwillison.net/atom/" reads as "simonwillison net atom".
      || setweight(to_tsvector('russian', regexp_replace(COALESCE(source_name, ''), '^https?://(www\.)?|[./:_-]+', ' ', 'g')), 'B')
      || setweight(to_tsvector('russian', left(COALESCE(content, ''), 200000)), 'D'))
$$;

CREATE OR REPLACE FUNCTION posts_search_vector_fill() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.search_vector := post_search_vector(NEW.title, NEW.content,
    (SELECT source_search_name(s.settings, s.handle_or_url) FROM sources s WHERE s.id = NEW.source_id));
  NEW.search_version := search_vector_version();
  RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION sources_search_name_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE posts p
     SET search_vector = post_search_vector(p.title, p.content, source_search_name(NEW.settings, NEW.handle_or_url)),
         search_version = search_vector_version()
   WHERE p.source_id = NEW.id;
  RETURN NULL;
END
$$;
