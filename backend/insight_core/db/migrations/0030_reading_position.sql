-- 0030_reading_position.sql (Mark IX, issue 0030)
-- Continue where I stopped: where a long post was left, kept with its read state.
--
-- resume_block is the index of the top text block in view of the post body, resume_blocks
-- the body's block count (so the reader can say "40%"). A block, not a scroll offset, so
-- images loading or another width do not move it. Both NULL: not started, or finished.

ALTER TABLE post_reader_state
  ADD COLUMN IF NOT EXISTS resume_block  INTEGER NULL,
  ADD COLUMN IF NOT EXISTS resume_blocks INTEGER NULL;
