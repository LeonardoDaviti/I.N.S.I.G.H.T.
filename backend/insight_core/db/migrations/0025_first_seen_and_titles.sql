-- 0025_first_seen_and_titles.sql (Mark IX, reader repairs after the first server deploy)
--
-- 1. fetched_at is when a post was first seen. Every upsert used to set it to now(), so a
--    post without a date (chadnauseam.com's feed has none) took the time of the latest
--    re-fetch, jumped to the top of the reader as new and came back unread. Ingest no
--    longer moves it; this puts the undated rows back to when they were first saved.
-- 2. Titles that are only the URL's slug ("levers-in-the-brain") become words, as ingest
--    now does (parsing.readable_title). Release tags ("2024-11-05") are not slugs.
-- 3. The Telegram RSS bridge prefixes media posts' titles ("[Photo] ...", "[Media] ...").
--    The tag hid that the title is the start of the text, so the reader showed it twice.
--    Ingest now strips it (parsing.strip_telegram_media_tag); a title that is only the tag
--    is kept. Idempotent.

UPDATE posts
   SET fetched_at = created_at
 WHERE published_at IS NULL
   AND fetched_at > created_at;

UPDATE posts
   SET title = upper(left(replace(title, '-', ' '), 1)) || substr(replace(title, '-', ' '), 2),
       updated_at = now()
 WHERE title ~ '^[a-z0-9]+(-[a-z0-9]+)+$'
   -- two or more words with letters: release tags such as 2024-11-05 stay as they are
   AND (SELECT count(*) FROM regexp_split_to_table(title, '-') AS w WHERE w ~ '[a-z]') >= 2
   AND lower(regexp_replace(url, '^.*/([^/?#]+)/?([?#].*)?$', '\1')) = title;

UPDATE posts
   SET title = regexp_replace(title, '^\[[A-Z][A-Za-z ]{1,20}\]\s+', ''),
       updated_at = now()
 WHERE url LIKE 'https://t.me/%'
   AND title ~ '^\[[A-Z][A-Za-z ]{1,20}\]\s+\S';
