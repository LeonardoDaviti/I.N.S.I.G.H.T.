-- 0100_future_page_dates.sql (Stealth v10.13.7: a sponsor's date made a 2025 post sit above today)
--
-- A page that states no date of its own was dated by the one date written on it, even a future one (an event, a
-- sponsor's banner): a 2025 post was stored as 17 Nov 2026 and stayed at the top of the feed. v10.13.7 never takes a
-- date more than a day ahead and ranks the address's day above a written date. This repairs the posts stored with a
-- date more than a day after they were fetched: their address's whole day when it names one, else undated (they
-- then sort at their fetch).
WITH future AS (
  SELECT p.id, p.url FROM posts p WHERE p.published_at > p.fetched_at + interval '1 day'
), parts AS (
  SELECT f.id, COALESCE(n[1], w[1])::int AS y,
         COALESCE(n[2]::int, array_position(ARRAY['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'],
                                            lower(substr(w[2], 1, 3)))) AS mo,
         COALESCE(n[3], w[3])::int AS d
    FROM future f
    LEFT JOIN LATERAL regexp_match(f.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)[/-](0[1-9]|1[0-2])[/-]([0-3]\d)(?=/|$|-|\.|\?|#)') n ON true
    LEFT JOIN LATERAL regexp_match(f.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*/([0-3]?\d)(?=/|$|\?|#)', 'i') w ON true
), fixed AS (
  SELECT id, CASE WHEN y IS NOT NULL AND mo BETWEEN 1 AND 12 AND d >= 1
                       AND d <= extract(day FROM (make_date(y, mo, 1) + interval '1 month - 1 day'))
                  THEN make_timestamptz(y, mo, d, 0, 0, 0, 'UTC') END AS at
    FROM parts
)
UPDATE posts p
   SET published_at = CASE WHEN f.at IS NOT NULL AND f.at <= now() THEN f.at END,
       published_precision = CASE WHEN f.at IS NOT NULL AND f.at <= now() THEN 'date' ELSE 'none' END,
       surfaced_at = NULL
  FROM fixed f
 WHERE p.id = f.id;
