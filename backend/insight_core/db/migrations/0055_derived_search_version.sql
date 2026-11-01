-- 0055_derived_search_version.sql (issue 0071, B1)
--
-- Which rule made a post's search vector is no longer a number bumped by hand (0042: 2, 0052: 3):
-- search_vector_version() is a fingerprint of what post_search_vector (and source_search_name, as the
-- trigger calls it) makes of a fixed sample of made-up titles, texts and source names, as the Python
-- stamps are (utils/stamps.py). A migration that changes the vectors' rule changes the version by
-- itself, and the background fill (ReaderService.fill_search_vectors) refills every older vector; a
-- migration that rewrites the functions without changing what they make keeps it.
-- The sample's lines each exercise a part of the rule: styled letters (NFKC), version names and
-- their parts (0042), a source's address read as words, Russian stemming, an empty post.
-- IMMUTABLE: the planner works it out once per statement, so the trigger pays nothing per row.
-- The first start after this migration refills every vector once (the vectors themselves are the same).

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
