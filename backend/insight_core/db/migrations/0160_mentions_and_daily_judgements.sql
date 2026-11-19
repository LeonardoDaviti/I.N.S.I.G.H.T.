-- 0160_mentions_and_daily_judgements.sql (issue 0235, backlog #32)
--
-- 1. An @mention is a link (utils/post_links.mentions): post_links.kind 'mention', an X or Bluesky post's @handle as
--    the account's address (x.com/<handle>, bsky.app/profile/<handle>). Stored as boilerplate, as a reference is, so
--    no story, News, Classics or Mark X rule reads it; Discover (repo_discover.read_sql) and the scout's match finder
--    read kind = 'mention'. The index serves Discover's `mention_url` (the addresses mentioned).
--    No existing row changes here. The posts stored before gain their mentions by a resumable step run by hand
--    (scripts/backfill_mentions.py, StoriesRepository.fill_mentions), never by this migration.
ALTER TABLE post_links DROP CONSTRAINT IF EXISTS post_links_kind_check;
ALTER TABLE post_links ADD CONSTRAINT post_links_kind_check CHECK (kind IN ('link', 'reference', 'mention')) NOT VALID;
ALTER TABLE post_links VALIDATE CONSTRAINT post_links_kind_check;   -- a scan under a light lock, not ADD's
CREATE INDEX IF NOT EXISTS post_links_mention_idx ON post_links (target_url) WHERE kind = 'mention';

-- 2. Who asked a source judgement (markx/source_judge.ask `by`): 'daily' for the daily planner (source_judge.daily,
--    JUDGE_DAILY a day, counted by this column); NULL for the owner's tap and the official channels' checks.
ALTER TABLE mx_source_judgements ADD COLUMN IF NOT EXISTS asked_by text;
CREATE INDEX IF NOT EXISTS mx_source_judgements_daily_idx ON mx_source_judgements (asked_at) WHERE asked_by = 'daily';
