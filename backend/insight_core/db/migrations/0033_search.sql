-- 0033_search.sql (issue 0040)
--
-- Search across every post: one tsvector per post, `posts.search_vector`, over a GIN index.
-- It holds the title (weight A, it counts most), the source's name (B) and the text (D).
-- The `russian` configuration stems ASCII words as English ("watching" -> watch) and
-- Cyrillic words as Russian ("серверы" -> сервер); any other word is kept as it is written.
-- The text is cut at 200,000 characters: a tsvector must stay under 1 MB.
--
-- A trigger fills it when a post is written (its title, text or source changes), and a
-- source renamed rewrites its posts' vectors. The posts already stored are not filled here:
-- on 50k posts that took 2 min 20 s, and the backend's health check gives up before the
-- migration ends. The backend fills them after it starts, 500 posts a transaction
-- (ReaderService.fill_search_vectors). Idempotent.

CREATE OR REPLACE FUNCTION post_search_vector(title text, content text, source_name text)
RETURNS tsvector LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT setweight(to_tsvector('russian', COALESCE(title, '')), 'A')
      -- "https://www.simonwillison.net/atom/" reads as "simonwillison net atom".
      || setweight(to_tsvector('russian', regexp_replace(COALESCE(source_name, ''), '^https?://(www\.)?|[./:_-]+', ' ', 'g')), 'B')
      || setweight(to_tsvector('russian', left(COALESCE(content, ''), 200000)), 'D')
$$;

-- The name a source is shown by (the reader's COALESCE(display_name, handle_or_url)).
CREATE OR REPLACE FUNCTION source_search_name(settings jsonb, handle_or_url text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
  SELECT COALESCE(settings->>'display_name', handle_or_url)
$$;

ALTER TABLE posts ADD COLUMN IF NOT EXISTS search_vector tsvector;

CREATE OR REPLACE FUNCTION posts_search_vector_fill() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.search_vector := post_search_vector(NEW.title, NEW.content,
    (SELECT source_search_name(s.settings, s.handle_or_url) FROM sources s WHERE s.id = NEW.source_id));
  RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS posts_search_vector_fill ON posts;
CREATE TRIGGER posts_search_vector_fill
  BEFORE INSERT OR UPDATE OF title, content, source_id ON posts
  FOR EACH ROW EXECUTE FUNCTION posts_search_vector_fill();

CREATE OR REPLACE FUNCTION sources_search_name_changed() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE posts p
     SET search_vector = post_search_vector(p.title, p.content, source_search_name(NEW.settings, NEW.handle_or_url))
   WHERE p.source_id = NEW.id;
  RETURN NULL;
END
$$;

DROP TRIGGER IF EXISTS sources_search_name_changed ON sources;
CREATE TRIGGER sources_search_name_changed
  AFTER UPDATE OF settings, handle_or_url ON sources
  FOR EACH ROW
  WHEN (source_search_name(OLD.settings, OLD.handle_or_url) IS DISTINCT FROM source_search_name(NEW.settings, NEW.handle_or_url))
  EXECUTE FUNCTION sources_search_name_changed();

CREATE INDEX IF NOT EXISTS posts_search_idx ON posts USING GIN (search_vector);
