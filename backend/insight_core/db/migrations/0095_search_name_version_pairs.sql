-- 0095_search_name_version_pairs.sql (Stealth v10.13.1: search, a name and its version)
--
-- A name word followed by a version number in a query ("fable 5.2", "gpt 6.1", "qwen 3.8", "opus 5.5", "gpt 4o")
-- asks for that name's version: the two must stand together in the text, the version one or two words after the
-- name ("Fable 5.2", "Claude Fable 5.2", "Qwen3.8" read as its parts, "Fable версии 5.2"). Before, the query was
-- 'fabl' & '5.2', so a post about another model's 5.2 that also named Fable anywhere matched and ranked high.
--
-- search_pair_versions(tsquery): each `name & version` of a query, where the name is a word of letters only and the
-- version a number with dots or with one or two letters after its digits (5.2, 3.8, 4o, 70b; a plain integer is no
-- version: "fable 5" is read as before), becomes ('name' <-> 'version' | 'name' <2> 'version'). Not a pair: a word
-- excluded (-word), either side of `or`, a pair already in a "quoted phrase" (in order already), a version word
-- (k3.1, qwen3.8: it holds its name itself). "fable" alone and "5.2" alone are read as before.
--
-- search_query (the posts' index, Mark X's layer under the index's rule, Classics) pairs before it reads version
-- words by their parts (0042, 0052; that step is search_version_words now); Mark X's English layer is read as
-- search_query_english(q), websearch_to_tsquery('english', q) paired. search_query_words(q) is the query as
-- 0052 read it, unpaired: the words a result's line marks, each where it stands. No vector changes, so nothing is
-- refilled. Two Mark X indexes: the entities' and aliases' keys reversed (the entity a name and its version names, by
-- its key's last words). Idempotent.

-- Whether a query's lexeme is a version number (see above).
CREATE OR REPLACE FUNCTION search_version_number(lexeme text) RETURNS boolean
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT $1 ~ '^[0-9]+((\.[0-9]+)+[[:alpha:]]{0,2}|[[:alpha:]]{1,2})$'
$$;

CREATE OR REPLACE FUNCTION search_pair_versions(q tsquery) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT COALESCE(string_agg(
           CASE WHEN p.pair THEN format('( %s <-> %s | %s <2> %s )', p.name, p.tok, p.name, p.tok)
                WHEN p.joins OR p.names THEN ''      -- written with its version
                ELSE p.tok END,
           '' ORDER BY p.n), '')::tsquery
  FROM (
    SELECT t.*, lag(t.tok, 2) OVER w AS name,
           COALESCE(lead(t.pair, 1) OVER w, FALSE) AS joins,
           COALESCE(lead(t.pair, 2) OVER w, FALSE) AS names
    FROM (
      -- The query's text as its quoted lexemes and what lies between them (0042's reading). Token n closes a pair
      -- when it is a version number, the text before it is exactly ' & ', the lexeme before that is a word of
      -- letters, which no '!' or phrase operator precedes, and no phrase operator follows the version.
      SELECT s.tok, s.n,
             left(s.tok, 1) = '''' AND search_version_number(substr(s.tok, 2, length(s.tok) - 2))
             AND s.s1 = ' & '
             AND left(s.nm, 1) = '''' AND substr(s.nm, 2, length(s.nm) - 2) ~ '^[[:alpha:]]+$'
             AND (s.s0 IS NULL OR s.s0 IN (' & ', ' | ') OR s.s0 ~ '\(\s*$')
             AND (s.s2 IS NULL OR s.s2 !~ '^\s*<') AS pair
      FROM (
        SELECT m.a[1] AS tok, m.n,
               lag(m.a[1], 1) OVER o AS s1, lag(m.a[1], 2) OVER o AS nm, lag(m.a[1], 3) OVER o AS s0,
               lead(m.a[1], 1) OVER o AS s2
        FROM regexp_matches($1::text, '''(?:[^'']|'''')*''|[^'']+', 'g') WITH ORDINALITY AS m(a, n)
        WINDOW o AS (ORDER BY m.n)
      ) AS s
    ) AS t
    WINDOW w AS (ORDER BY t.n)
  ) AS p
$$;

-- A query's lexemes with each version word W read as (W | its parts as a phrase): 0052's search_query, on a tsquery.
CREATE OR REPLACE FUNCTION search_version_words(q tsquery) RETURNS tsquery
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT COALESCE(string_agg(
           CASE WHEN w.parts IS NULL OR (t.in_phrase AND cardinality(array_remove(w.parts, NULL)) > 1) THEN t.tok
                ELSE '(' || t.tok || ' | ' || search_parts_phrase(w.parts) || ')' END,
           '' ORDER BY t.n), '')::tsquery
  FROM (
    SELECT m.a[1] AS tok, m.n,
           COALESCE(lag(m.a[1]) OVER (ORDER BY m.n) ~ '>\s*$', FALSE)
             OR COALESCE(lead(m.a[1]) OVER (ORDER BY m.n) ~ '^\s*<', FALSE) AS in_phrase
    FROM regexp_matches($1::text, '''(?:[^'']|'''')*''|[^'']+', 'g') WITH ORDINALITY AS m(a, n)
  ) AS t
  CROSS JOIN LATERAL (
    SELECT CASE WHEN left(t.tok, 1) = ''''
                THEN search_version_parts(replace(substr(t.tok, 2, length(t.tok) - 2), '''''', '''')) END AS parts
  ) AS w
$$;

-- The three readings of a query below are PL/pgSQL: a search names them 20-odd times, each read once as its plan is
-- made; a PL/pgSQL function keeps its statements' plans for the connection, where a SQL function nesting two more
-- plans them all again each time (measured: 1.1 ms a reading, +10-20 ms a search; this way 0.6 ms, as 0052's).

-- The query's words unpaired, as 0052's search_query read them: what a result's line marks, each word where it stands.
CREATE OR REPLACE FUNCTION search_query_words(q text) RETURNS tsquery
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
BEGIN
  RETURN search_version_words(websearch_to_tsquery('russian', normalize(q, NFKC)));
END
$$;

-- A search's words (0052's), its name-version pairs read first.
CREATE OR REPLACE FUNCTION search_query(q text) RETURNS tsquery
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
BEGIN
  RETURN search_version_words(search_pair_versions(websearch_to_tsquery('russian', normalize(q, NFKC))));
END
$$;

-- Mark X's English layer's reading of a query (issue 0139's websearch_to_tsquery('english', q)), its pairs read first.
CREATE OR REPLACE FUNCTION search_query_english(q text) RETURNS tsquery
LANGUAGE plpgsql IMMUTABLE PARALLEL SAFE AS $$
BEGIN
  RETURN search_pair_versions(websearch_to_tsquery('english', q));
END
$$;

-- A name and its version names the entities whose key or alias ends with it as words ("claude fable 5.2" for "fable
-- 5.2"; markx/search.py): read as a prefix of the reversed key, so no search reads every entity.
CREATE INDEX IF NOT EXISTS mx_entities_key_reversed_idx ON mx_entities (reverse(key) text_pattern_ops);
CREATE INDEX IF NOT EXISTS mx_entity_aliases_key_reversed_idx ON mx_entity_aliases (reverse(key) text_pattern_ops);
