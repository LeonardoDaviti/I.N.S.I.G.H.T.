-- 0035_source_tidy.sql (issue 0046)
--
-- Source hygiene: the owner's Keep on a source marked quiet or never opened. tidy_kept_at
-- is when Keep was pressed; the marks stay hidden for 90 days from then and come back only
-- if still true. NULL: never kept. Removing a source removes the row, so nothing to clean.
-- Numbered 0035: 0034, 0036 and 0037 are held by other branches. Idempotent.

ALTER TABLE sources ADD COLUMN IF NOT EXISTS tidy_kept_at timestamptz;
