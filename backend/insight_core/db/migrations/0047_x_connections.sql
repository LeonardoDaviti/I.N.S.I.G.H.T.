-- 0047_x_connections.sql (issue 0066)
--
-- X: one address per tweet, reposts named, and the links a tweet makes to other tweets.
--
-- posts:
--   author: a tweet's account, as its address writes it (the user of /<user>/status/<id>); NULL
--     for any other post. Attribution, ready for Mark X's entities.
--   reposted_by: the accounts of your sources that reposted it, the author not counted; NULL for
--     none. The saver adds each feed's "RT by @user" (repo_posts), so a tweet two of your
--     sources repost, stored once, keeps both.
-- Every post at a tweet's address, whatever the host (x.com, twitter.com, your Nitter, a mirror),
--   is re-addressed: normalized_url and canonical_url become x.com/<user, lower case>/status/<id>,
--   url_host x.com (url_normalization.TWEET_PATH). Its url, id, read state and everything
--   pointing at it stay. On the lab copy no two posts then share an address and a title, so no
--   post merges (0049's rule); the saver keeps it so.
-- reposted_by is filled from the title ("RT by @user: ", Nitter's) and from the post's own source
--   when that is an X account other than the author (a tweet a second feed brought again keeps
--   only the last title).
-- Links to tweets are now kept (post_links.extract_links), so every post linking one is read
--   again by the story job (links_scanned_at cleared).
-- story_posts.parent_reason gains repost, thread and quote.
-- The job's next run regroups every post (the `stories` setting is cleared).
--
-- Idempotent.

ALTER TABLE posts ADD COLUMN IF NOT EXISTS author text;
ALTER TABLE posts ADD COLUMN IF NOT EXISTS reposted_by text[];

WITH t AS (
  SELECT p.id, m[1] AS author, 'https://x.com/' || lower(m[1]) || '/status/' || m[2] AS address,
         substring(p.title FROM '^RT by @(\w+): ') AS rt,
         CASE WHEN s.handle_or_url ~* '(nitter|//(www\.)?(x|twitter)\.com/)'   -- post_links.source_kind's x
              THEN substring(s.handle_or_url FROM '^[A-Za-z]+://[^/]+/([A-Za-z0-9_]+)/rss') END AS owner
  FROM (SELECT id, source_id, title,
               regexp_match(url, '^[A-Za-z][A-Za-z0-9+.-]*://[^/?#]+/([A-Za-z0-9_]+)/status/([0-9]{15,})(?:[/?#]|$)') AS m
        FROM posts) p
  JOIN sources s ON s.id = p.source_id
  WHERE p.m IS NOT NULL
)
UPDATE posts p
SET normalized_url = t.address, canonical_url = t.address, url_host = 'x.com', author = t.author,
    reposted_by = NULLIF(ARRAY(SELECT DISTINCT a FROM unnest(COALESCE(p.reposted_by, '{}') || ARRAY[t.rt, t.owner]) a
                               WHERE a IS NOT NULL AND lower(a) <> lower(t.author) ORDER BY 1), '{}')
FROM t
WHERE p.id = t.id;

UPDATE posts SET links_scanned_at = NULL
WHERE links_scanned_at IS NOT NULL AND content_html ~ '/status/[0-9]{15,}';

ALTER TABLE story_posts DROP CONSTRAINT IF EXISTS story_posts_parent_reason_check;
ALTER TABLE story_posts ADD CONSTRAINT story_posts_parent_reason_check
  CHECK (parent_reason IS NULL OR parent_reason IN ('address', 'repost', 'thread', 'quote', 'citation', 'copy', 'time', 'none'));

DELETE FROM system_settings WHERE key = 'stories';
