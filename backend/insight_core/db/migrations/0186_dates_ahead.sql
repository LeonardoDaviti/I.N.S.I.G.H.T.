-- 0186_dates_ahead.sql (Stealth v10.49.4: a stated date ahead of now is no publication date)
--
-- A post whose source stated a date more than a day ahead (Brave's research papers dated by their venue's issue,
-- "Jul 1, 2027") is dated when first seen, precision 'seen'; the date it stated is kept in metadata `stated_date`
-- (repo_posts.not_ahead does the same for every new or refreshed post). Only such rows are rewritten.
UPDATE posts
   SET metadata = metadata || jsonb_build_object('stated_date', to_char(published_at AT TIME ZONE 'UTC',
                                                                        'YYYY-MM-DD"T"HH24:MI:SS"+00:00"')),
       published_at = fetched_at,
       published_precision = 'seen'
 WHERE published_at > now() + interval '1 day';
