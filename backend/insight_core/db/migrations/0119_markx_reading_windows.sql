-- 0119_markx_reading_windows.sql (issue 0176, Stealth v10.16: the fresh lane and long posts' entities in windows)
--
-- 1. mx_mentions.win: the window of the post's text a mention was read from (0 = the first, the only one of a short
--    post: every row before 0176 is 0). A long post's entities are asked per window (tasks.entity_inputs); window w's
--    mentions are numbered from w * tasks.WINDOW_N, so (post_id, guide, n) stays every mention's key and identity
--    links them as before.
-- 2. mx_mentions_now is made again so it carries the new column (a view's m.* is fixed when it is made).
-- 3. mx_plan_marks.why may be 'one_window': the windows planner read a long-stored post whose shown text fits one
--    window (plan_marks: not read again until its text changes).
--
-- The fresh lane (posts fetched in the last 24 hours planned and leased first) needs no schema: it reads
-- posts.fetched_at and surfaced_at (a scan of a day's posts: about 2 ms on the 2026-11-05 copy).
--
-- Mark X tables only. Nothing is deleted. Idempotent.

ALTER TABLE mx_mentions ADD COLUMN IF NOT EXISTS win integer NOT NULL DEFAULT 0;

CREATE OR REPLACE VIEW mx_mentions_now AS
SELECT m.* FROM mx_mentions m JOIN mx_mention_sets s ON s.post_id = m.post_id AND s.guide = m.guide;

ALTER TABLE mx_plan_marks DROP CONSTRAINT IF EXISTS mx_plan_marks_why_check;
ALTER TABLE mx_plan_marks ADD CONSTRAINT mx_plan_marks_why_check CHECK (why IN ('same_input', 'not_cue', 'one_window'));
