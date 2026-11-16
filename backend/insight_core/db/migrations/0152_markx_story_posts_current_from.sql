-- 0152_markx_story_posts_current_from.sql (Stealth v10.23, issue 0165: a thing's timeline)
--
-- The stop planner (markx/stops.plan, the jobs process's plan job) reads the Mark X stories that gained a current member
-- since its last pass (mx_story_posts.valid_from >= its mark). Without an index each pass scanned the whole table:
-- measured on a scratch copy inflated to 509k rows (64k current), 9-13 ms a pass; with this partial index 0.15 ms
-- (776 kB). Mark X tables only. Idempotent.
CREATE INDEX IF NOT EXISTS mx_story_posts_current_from_idx ON mx_story_posts (valid_from) WHERE valid_to IS NULL;
