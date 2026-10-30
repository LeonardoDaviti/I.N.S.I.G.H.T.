-- 0041_same_post_same_title.sql (issue 0049, after the server-data rehearsal)
--
-- The same address is not enough: the same post also has the same title. 0038 was edited in
-- place to merge only posts sharing a normalized_url AND a post_title_key, and no longer makes
-- normalized_url unique. This file brings the databases that ran the first 0038
-- (insight_preview, insight_lab) to the same schema; on every other database it changes
-- nothing (0038 already defined the function; the unique index was never made).
--
-- 1. post_title_key, the same definition as 0038's (the migration test checks it), so the
--    saver's lookup can use it everywhere.
-- 2. posts_normalized_url_unique becomes the plain posts_normalized_url_idx again: two posts
--    at one address with different titles are two posts (Daring Fireball's footnote, text
--    fragment and utm_campaign links). The saver finds the stored post by address and title
--    under an advisory lock instead (repo_posts.upsert_post).
--
-- Rows the first 0038 merged stay merged: their copies are gone. On insight_preview those
-- were 17 same-title pairs; nothing there needs undoing.

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

DROP INDEX IF EXISTS posts_normalized_url_unique;
CREATE INDEX IF NOT EXISTS posts_normalized_url_idx ON posts (normalized_url);
