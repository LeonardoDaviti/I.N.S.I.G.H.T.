-- 0031_read_later.sql (issue 0022)
-- Read later: "I want this, not now". later_at is when the post was put in Later; NULL
-- when it is not there. Nothing clears it on a clock: finishing the post (its end
-- reached, or an explicit mark read) or the owner's own toggle does. The star
-- (starred_at) is Keep, unchanged. The partial index serves the Later list and its
-- count, like the starred one.

ALTER TABLE post_reader_state ADD COLUMN IF NOT EXISTS later_at TIMESTAMPTZ NULL;
CREATE INDEX IF NOT EXISTS post_reader_state_later_idx
  ON post_reader_state (later_at) WHERE later_at IS NOT NULL;
