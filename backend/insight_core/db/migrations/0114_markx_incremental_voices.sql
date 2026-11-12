-- 0114_markx_incremental_voices.sql (Stealth v10.15: a followed author's repost counts as that author's voice)
--
-- mx_inc_posts (0113) keeps each world post as the rules read it; the rules now read the voice a post counts as
-- (tasks.Post.voice: a repost's or forward's original author when a source follows that author, else its own
-- source), so it is kept beside the source. Rows written before have none and are read again
-- (incremental.STATE_VERSION also makes the first run after this full). A cache: Mark X tables only. Idempotent.

ALTER TABLE mx_inc_posts ADD COLUMN IF NOT EXISTS voice text;
