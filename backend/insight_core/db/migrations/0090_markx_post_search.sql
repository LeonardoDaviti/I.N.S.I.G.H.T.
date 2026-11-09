-- 0090_markx_post_search.sql (issue 0139, Stealth v10.10: search that finds)
--
-- 1. mx_post_search: Mark X's English layer of a post, searched beside posts.search_vector while Mark X is on. One row a
--    post that has a read or an entities answer: `vector` is to_tsvector('english', ...) of its current reading (the
--    headline, weight A; the main action, object, actors and numbers, B) and its current entity set (mx_mentions_now:
--    the names and their entities' names, A; makers and the entities' aliases, B); `headline` is the reading's English
--    headline (the result's line when only this layer matched); `version` the rule that made it
--    (markx/search.py VERSION). Written when an answer is stored and by a resumable background fill.
-- 2. Prefix indexes on the entities' and the aliases' name keys (the search's entity cards, prefix for 3+ letters).
--
-- Mark X tables only; posts.search_vector and its rule are unchanged; nothing is deleted. Idempotent.

CREATE TABLE IF NOT EXISTS mx_post_search (
  post_id    uuid PRIMARY KEY,
  vector     tsvector NOT NULL,
  headline   text,
  version    integer NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_post_search_vector_idx ON mx_post_search USING gin (vector);

CREATE INDEX IF NOT EXISTS mx_entities_key_prefix_idx ON mx_entities (key text_pattern_ops);
CREATE INDEX IF NOT EXISTS mx_entity_aliases_key_prefix_idx ON mx_entity_aliases (key text_pattern_ops);
