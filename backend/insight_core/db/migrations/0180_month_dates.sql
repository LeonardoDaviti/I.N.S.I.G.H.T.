-- 0180_month_dates.sql (Stealth v10.47: a page that states only its month and year)
--
-- posts.published_precision 'month': the page states its month and year alone ("February 2026", "published
-- November 2026"), so the post is dated the 1st of that month and shown as "Feb 2026", never as a day
-- (page_watch.month_date, DATED_BY_MONTH). 0088's CHECK allows it now. No row is rewritten.
ALTER TABLE posts DROP CONSTRAINT IF EXISTS posts_published_precision_check;
ALTER TABLE posts ADD CONSTRAINT posts_published_precision_check
    CHECK (published_precision IS NULL OR published_precision IN ('exact', 'date', 'none', 'seen', 'month'));
