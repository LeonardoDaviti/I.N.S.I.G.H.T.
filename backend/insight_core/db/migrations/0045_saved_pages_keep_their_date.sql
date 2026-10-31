-- 0045_saved_pages_keep_their_date.sql (issue 0063)
--
-- A saved page is dated by the page, not by the day it was saved. New saves take the date the
-- page states (services/saved_service.py); this repairs the Saved pages stored before, from what
-- was stored when they were read. Nothing is fetched.
--
-- What was stored: the reader keeps only the article body (content_html), never the page's
-- <head>, JSON-LD or <time> elements, so the body holds no date (0 of the lab's 8). The page's
-- date was read from the whole page at save time (page_watch.page_date) and kept as
-- metadata.article_published_at. When the page stated none, that key holds the moment the page
-- was read, which always comes after the save time (published_at was the clock taken before
-- the read). So a key earlier than published_at is a date the page stated, and only those are
-- taken.
--
-- Each such post gets that date as published_at; the save time moves to surfaced_at, so the
-- post still sorts in the feed at when it was saved (issue 0022); fetched_at (when it was saved)
-- is untouched, so History and Later are unchanged. The undated pages (and the unreadable ones)
-- keep the save time. The key stays as it was.
--
-- On a copy of the lab (the server's data): 3 of 8 Saved pages. Idempotent: a repaired post's
-- published_at is its key.

UPDATE posts p
   SET surfaced_at = COALESCE(p.surfaced_at, p.published_at),
       published_at = (p.metadata ->> 'article_published_at')::timestamptz
  FROM sources s
 WHERE s.id = p.source_id
   AND s.platform = 'saved'
   AND p.metadata ->> 'article_published_at' ~ '^\d{4}-\d{2}-\d{2}T'
   AND (p.metadata ->> 'article_published_at')::timestamptz < p.published_at;

