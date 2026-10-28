-- 0036_gwern_noise_cleanup.sql (issue 0048)
--
-- The Gwern reader stopped storing topic directories (/doc/**) and newsletter issues
-- (/newsletter/...) in issue 0043; this removes the ones stored before it. A post goes when
-- its source's address is on gwern.net (www. ignored) and its own URL's path starts with
-- /doc/ or /newsletter/.
--
-- Never deleted: a post in Later or kept (starred), a post with a note (the owner's own
-- writing), and pages saved by hand (0031: they belong to the Saved source, whose address
-- is not gwern.net). Read state, positions and the interaction log go with the post
-- (ON DELETE CASCADE), and so does its search vector, a column of the row. Nothing to do
-- without a Gwern source; a second run finds nothing.

DELETE FROM posts p
USING sources s
WHERE s.id = p.source_id
  AND substring(lower(s.handle_or_url) FROM '^(?:[a-z][a-z0-9+.-]*://)?(?:www\.)?([^/:?#]+)') = 'gwern.net'
  AND substring(p.url FROM '^[A-Za-z][A-Za-z0-9+.-]*://[^/?#]+(/[^?#]*)') ~ '^/(doc|newsletter)/'
  AND NOT EXISTS (
    SELECT 1 FROM post_reader_state r
    WHERE r.post_id = p.id AND (r.later_at IS NOT NULL OR r.starred_at IS NOT NULL)
  )
  AND NOT EXISTS (SELECT 1 FROM post_notes n WHERE n.post_id = p.id);
