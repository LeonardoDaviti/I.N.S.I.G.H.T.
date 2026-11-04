-- 0063_published_precision.sql (issue 0076: dates say what they know)
--
-- posts.published_precision: how precise the source's date is, as the ingestion read it, per item:
-- 'exact' (a time of day), 'date' (a day alone: no time in its date, or stored as 00:00:00 UTC), 'none'
-- (no date: its time is its fetch's, or a made-up backlog time). The story job's trusted time reads it
-- (story_rules.StoryPost: a date alone is that day's earliest timed post, an undated post orders nothing).
-- The posts stored before it are NULL and read as before (told by their time, 00:00:00 UTC; undated
-- when published_at is NULL): no row is rewritten, nothing moves. Raw like the title and the body: no
-- rule makes it again.

ALTER TABLE posts ADD COLUMN IF NOT EXISTS published_precision TEXT
    CHECK (published_precision IS NULL OR published_precision IN ('exact', 'date', 'none'));
