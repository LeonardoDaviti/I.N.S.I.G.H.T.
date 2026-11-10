-- 0099_archive_dates_stored_as_now.sql (Stealth v10.13.6: 0098 missed them)
--
-- The page reader dated an undated page "now" (page_watch.article_post), so an archive's old pages were stored with
-- their fetch time as their date, not undated: 0098 (undated posts only) did not reach them, and a blog's 2008 posts
-- stayed under "Today". A stored date that is the fetch time (within a second) while the address names a whole day
-- two or more days earlier is that save's clock, not the post's: the post takes its address's day (precision
-- "date") and sorts at it.
WITH parts AS (
  SELECT p.id, p.published_at, COALESCE(n[1], w[1])::int AS y,
         COALESCE(n[2]::int, array_position(ARRAY['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'],
                                            lower(substr(w[2], 1, 3)))) AS mo,
         COALESCE(n[3], w[3])::int AS d
    FROM posts p
    LEFT JOIN LATERAL regexp_match(p.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)[/-](0[1-9]|1[0-2])[/-]([0-3]\d)(?=/|$|-|\.|\?|#)') n ON true
    LEFT JOIN LATERAL regexp_match(p.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*/([0-3]?\d)(?=/|$|\?|#)', 'i') w ON true
   WHERE p.published_at IS NOT NULL AND abs(extract(epoch FROM (p.published_at - p.fetched_at))) < 1
     AND (n IS NOT NULL OR w IS NOT NULL)
), valid AS (
  SELECT id, published_at,
         CASE WHEN mo BETWEEN 1 AND 12 AND d >= 1   -- a CASE, so an invalid day (Feb 31) is never built
                   AND d <= extract(day FROM (make_date(y, mo, 1) + interval '1 month - 1 day'))
              THEN make_timestamptz(y, mo, d, 0, 0, 0, 'UTC') END AS at
    FROM parts
)
UPDATE posts p
   SET published_at = v.at, surfaced_at = NULL, published_precision = 'date'
  FROM valid v
 WHERE p.id = v.id AND v.at IS NOT NULL AND v.at < v.published_at - interval '2 days';
