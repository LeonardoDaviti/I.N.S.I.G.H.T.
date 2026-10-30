-- 0043_known_news_is_not_new.sql (issue 0058)
--
-- Known news is not new. The saver no longer surfaces a page first seen long after its date when
-- a post from another source linked its address before it was first seen (repo_posts
-- LINKED_BEFORE_SQL). This clears surfaced_at on the posts stored before that met the same
-- condition, so they sort at their published date again.
--
-- Only posts surfaced as new to you are cleared, never an update. 0039 tells them apart:
-- "new to you" sets surfaced_at = fetched_at (when the post was first seen, never moved) and
-- writes nothing else; an update (repo_page_watch) sets surfaced_at = now() at the check and
-- always writes metadata.page_update. So a post with no page_update whose surfaced_at is still
-- its fetched_at was surfaced as new to you and nothing since.
--
-- On a copy of the lab (the server's data): 1 post. Idempotent.

UPDATE posts p SET surfaced_at = NULL
 WHERE p.surfaced_at IS NOT NULL
   AND p.surfaced_at = p.fetched_at
   AND NOT COALESCE(p.metadata ? 'page_update', false)
   AND EXISTS (SELECT 1 FROM post_links l JOIN posts q ON q.id = l.post_id
                WHERE l.target_url = p.normalized_url AND q.source_id <> p.source_id
                  AND q.fetched_at < p.fetched_at);
