-- 0055_search_version_title_key.sql (issue 0071, B1 and C3)
--
-- 1. Which rule made a post's search vector is no longer a number bumped by hand (0042: 2, 0052: 3):
--    search_vector_version() is a fingerprint of what post_search_vector (and source_search_name, as the
--    trigger calls it) makes of a fixed sample of made-up titles, texts and source names, as the Python
--    stamps are (utils/stamps.py). A migration that changes the vectors' rule changes the version by
--    itself, and the background fill (ReaderService.fill_search_vectors) refills every older vector; a
--    migration that rewrites the functions without changing what they make keeps it.
--    The sample's lines each exercise a part of the rule: styled letters (NFKC), version names and
--    their parts (0042), a source's address read as words, Russian stemming, an empty post.
--    IMMUTABLE: the planner works it out once per statement, so the trigger pays nothing per row.
--    The first start after this migration refills every vector once (the vectors themselves are the same).

CREATE OR REPLACE FUNCTION search_vector_version() RETURNS integer
LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT ('x' || left(md5(string_agg(post_search_vector(title, content, source_search_name(settings, handle))::text,
                                     '|' ORDER BY n)), 7))::bit(28)::integer
  FROM (VALUES
    (1, 'Introducing 𝙻𝙵𝙼𝟹: a new generation', 'Our model, version GPT-5.1 and Qwen3.6-27B, ships today.',
        '{}'::jsonb, 'https://www.sample.example/atom/'),
    (2, 'Новая модель вышла', 'Исследователи опубликовали веса модели и отчёт.',
        '{"display_name": "Sample Channel"}'::jsonb, 'https://tg.bridge.example/rss/sample_channel'),
    (3, E'Model\u00a0K3.1 Pro', 'Model K3.1 Pro reads long documents; FLUX.3 Image and v2.0-beta too.',
        '{"display_name": ""}'::jsonb, 'https://nitter.local/writer_x/rss'),
    (4, NULL, NULL, NULL::jsonb, NULL)
  ) AS sample(n, title, content, settings, handle)
$$;

-- 2. One title comparison (C3): post_title_key, by which the saver tells one post at two addresses
--    (0038, 0041, 0052), takes the steps of the Python rule (utils/titles.py: title_key, which the
--    story job, names in titles and the reader compare by): after 0041's entities, styled letters as
--    plain (NFKC) and curly quotes straight, then lower case and single spaces as before. Only what
--    the saver compares from now on changes; no stored row is rewritten.
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
  RETURN btrim(regexp_replace(translate(lower(normalize(t, NFKC)), '‘’“”', '''''""'), '\s+', ' ', 'g'));
END
$fn$;
