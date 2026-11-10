-- 0101_older_pages_dated_now.sql (Stealth v10.13.9: "date or now" still leaked)
--
-- The page reader still dated an undated page "now" on paths 0099 did not cover (a collected original, a page its
-- feed missed, an archive API's post, a page whose address names a month and no day): a link blog's /2003/07/ post
-- sat under Today. v10.13.9 keeps such a page undated (sorted before its source's oldest) or dates it by its address.
-- This repairs the posts stored with their fetch time as their date (within a second) while their address names a
-- date 30 or more days earlier: a whole day takes that day, a month alone takes its 1st (posts.published_precision has
-- no "month": both are a date alone, precision "date"), a year alone is left as it is (no guess). Run twice, it
-- changes nothing more (a repaired date is no longer its fetch time).
WITH stamped AS (
  SELECT p.id, p.url, p.published_at FROM posts p
   WHERE p.published_at IS NOT NULL AND abs(extract(epoch FROM (p.published_at - p.fetched_at))) < 1
), parts AS (
  SELECT s.id, s.published_at,
         COALESCE(w[1], n[1])::int AS y,
         COALESCE(array_position(ARRAY['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'],
                                 lower(substr(w[2], 1, 3))), n[2]::int) AS mo,
         CASE WHEN w IS NOT NULL THEN w[3]::int ELSE NULLIF(n[3], '')::int END AS d
    FROM stamped s
    LEFT JOIN LATERAL regexp_match(s.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*/([0-3]?\d)(?=/|$|\?|#)', 'i') w ON true
    LEFT JOIN LATERAL regexp_match(s.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)[/-](0[1-9]|1[0-2])(?:[/-]([0-3]\d))?(?=/|$|-|\.|\?|#)') n ON true
   WHERE w IS NOT NULL OR n IS NOT NULL
), fixed AS (
  SELECT id, published_at,
         CASE WHEN mo BETWEEN 1 AND 12 AND d IS NULL THEN make_timestamptz(y, mo, 1, 0, 0, 0, 'UTC')
              WHEN mo BETWEEN 1 AND 12 AND d >= 1     -- a CASE, so an invalid day (Feb 31) is never built
                   AND d <= extract(day FROM (make_date(y, mo, 1) + interval '1 month - 1 day'))
              THEN make_timestamptz(y, mo, d, 0, 0, 0, 'UTC') END AS at
    FROM parts
)
UPDATE posts p
   SET published_at = f.at, surfaced_at = NULL, published_precision = 'date'
  FROM fixed f
 WHERE p.id = f.id AND f.at IS NOT NULL AND f.at <= f.published_at - interval '30 days';
