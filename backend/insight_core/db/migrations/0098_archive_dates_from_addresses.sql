-- 0098_archive_dates_from_addresses.sql (Stealth v10.13.5: an archive's old pages showed as today's)
--
-- An archive read through a sitemap (issue 0108) stores a site's older pages; a page whose markup states no date
-- was stored undated, and an undated post of a source fetched before sorted at its fetch time: thousands of a
-- blog's 2008 posts showed under "Today", unread. v10.13.5 dates such a page by its address (/2008/Jul/7/,
-- /2008/07/07/) and sorts an undated older post before its source's oldest. This repairs the posts stored before:
-- an undated post whose address names a whole (valid) day takes that day (precision "date"), and sorts at it.
WITH parts AS (
  SELECT p.id, COALESCE(n[1], w[1])::int AS y,
         COALESCE(n[2]::int, array_position(ARRAY['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'],
                                            lower(substr(w[2], 1, 3)))) AS mo,
         COALESCE(n[3], w[3])::int AS d
    FROM posts p
    LEFT JOIN LATERAL regexp_match(p.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)[/-](0[1-9]|1[0-2])[/-]([0-3]\d)(?=/|$|-|\.|\?|#)') n ON true
    LEFT JOIN LATERAL regexp_match(p.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*/([0-3]?\d)(?=/|$|\?|#)', 'i') w ON true
   WHERE p.published_at IS NULL AND (n IS NOT NULL OR w IS NOT NULL)
), valid AS (
  SELECT id, CASE WHEN mo BETWEEN 1 AND 12 AND d >= 1   -- a CASE, so an invalid day (Feb 31) is never built
                   AND d <= extract(day FROM (make_date(y, mo, 1) + interval '1 month - 1 day'))
                  THEN make_timestamptz(y, mo, d, 0, 0, 0, 'UTC') END AS at
    FROM parts
)
UPDATE posts p
   SET published_at = v.at, surfaced_at = NULL, published_precision = 'date'
  FROM valid v
 WHERE p.id = v.id AND v.at IS NOT NULL AND v.at <= now();
