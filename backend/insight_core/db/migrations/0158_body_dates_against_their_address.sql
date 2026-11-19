-- 0158_body_dates_against_their_address.sql (Stealth v10.25, issue 0228: a date from the article's text)
--
-- Two ways an older page took a date that was not its publication's (issue 0225 #2):
--   A. Before v10.13.7 the page reader ranked the one date written in a page's body above the day its address names:
--      a 2024 post (/2024/Aug/30/...) quoting "May 31, 2020" from a tutorial was stored as 2020-05-31. v10.25
--      (page_watch.page_dating) never lets a body date win over its address: the address's day, or, when the address
--      names a month alone, a body date outside that month is held (the page's month is its sort hint).
--      Repaired here: an own-site post stored as a whole day (00:00 UTC) that its body writes ("May 31, 2020",
--      "Sept. 3, 2025") while its address names another day (more than a day off) or another month takes its
--      address's day, or its month's 1st, as 0099 and 0101 date such pages (precision "date", sorted again).
--   B. A page its feed missed was dated by the first stored post linking it (saved_service.first_linked), even a
--      linking page edited later to add the link: a 2023 essay edited in 2026 dated a 2026 page 2023. v10.25 counts
--      such a linker from the change its page says it had (metadata.modified). Repaired here: a collected page whose
--      date is the old first link, and the new rule gives a later one, takes the new one (never after it was
--      collected).
-- A year alone is no date (no guess); an invalid day (Feb 31) is never built. Run twice, it changes nothing more: a
-- repaired date agrees with its address (A) or is the new first link (B).
WITH whole_days AS (
  SELECT p.id, p.url, p.published_at, p.content
    FROM posts p JOIN sources s ON s.id = p.source_id
   WHERE p.published_at IS NOT NULL
     AND p.published_at = date_trunc('day', p.published_at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
     AND (s.platform = 'saved'
          OR p.url_host = regexp_replace(lower(substring(s.handle_or_url FROM '^https?://([^/:?#]+)')), '^www\.', ''))
), parts AS (
  SELECT h.id, h.published_at, h.content,
         COALESCE(w[1], n[1])::int AS y,
         COALESCE(array_position(ARRAY['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'],
                                 lower(substr(w[2], 1, 3))), n[2]::int) AS mo,
         CASE WHEN w IS NOT NULL THEN w[3]::int ELSE NULLIF(n[3], '')::int END AS d
    FROM whole_days h
    LEFT JOIN LATERAL regexp_match(h.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)/(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*/([0-3]?\d)(?=/|$|\?|#)', 'i') w ON true
    LEFT JOIN LATERAL regexp_match(h.url, '^https?://[^/]+(?:/[^?#]*)?/((?:19|20)\d\d)[/-](0[1-9]|1[0-2])(?:[/-]([0-3]\d))?(?=/|$|-|\.|\?|#)') n ON true
   WHERE w IS NOT NULL OR n IS NOT NULL
), addressed AS (
  SELECT id, published_at, content, d IS NULL AS month_alone,
         CASE WHEN mo BETWEEN 1 AND 12 AND d IS NULL THEN make_timestamptz(y, mo, 1, 0, 0, 0, 'UTC')
              WHEN mo BETWEEN 1 AND 12 AND d >= 1
                   AND d <= extract(day FROM (make_date(y, mo, 1) + interval '1 month - 1 day'))
              THEN make_timestamptz(y, mo, d, 0, 0, 0, 'UTC') END AS at
    FROM parts
), body_dated AS (
  SELECT id, at FROM addressed
   WHERE at IS NOT NULL AND at <= now()
     AND CASE WHEN month_alone THEN date_trunc('month', published_at AT TIME ZONE 'UTC') <> at AT TIME ZONE 'UTC'
              ELSE abs(extract(epoch FROM (published_at - at))) > 86400 END
     -- its body writes the stored day, as page_watch.TEXT_DATE_RE reads one
     AND content ~ ('\m' || substr(to_char(published_at AT TIME ZONE 'UTC', 'FMMonth'), 1, 3) || '[a-z]*\.? '
                    || to_char(published_at AT TIME ZONE 'UTC', 'FMDD') || ', '
                    || to_char(published_at AT TIME ZONE 'UTC', 'YYYY') || '\M')
)
UPDATE posts p
   SET published_at = b.at, surfaced_at = NULL, published_precision = 'date'
  FROM body_dated b
 WHERE p.id = b.id;

WITH collected AS (
  SELECT p.id, p.published_at, p.normalized_url,
         LEAST(p.fetched_at, CASE WHEN p.metadata->>'missed_by_feed' ~ '^\d{4}-\d\d-\d\dT'
                                  THEN (p.metadata->>'missed_by_feed')::timestamptz END,
               CASE WHEN p.metadata->>'collected_original' ~ '^\d{4}-\d\d-\d\dT'
                    THEN (p.metadata->>'collected_original')::timestamptz END) AS saved_at
    FROM posts p
   WHERE p.published_at IS NOT NULL AND p.normalized_url IS NOT NULL
     AND (p.metadata ? 'missed_by_feed' OR p.metadata ? 'collected_original')
), linked AS (
  SELECT c.id, c.published_at, c.saved_at, min(l.published_at) AS old_first,
         -- saved_service.LINKED_SINCE
         min(GREATEST(l.published_at, CASE WHEN l.metadata->>'modified' ~ '^\d{4}-\d\d-\d\dT'
                                           THEN (l.metadata->>'modified')::timestamptz END)) AS new_first
    FROM collected c
    JOIN post_links pl ON pl.target_url = c.normalized_url
    JOIN posts l ON l.id = pl.post_id AND l.id <> c.id
   GROUP BY c.id, c.published_at, c.saved_at
), redated AS (
  SELECT id, LEAST(new_first, saved_at) AS at FROM linked
   WHERE published_at = old_first AND LEAST(new_first, saved_at) > old_first
)
UPDATE posts p
   SET published_at = r.at, surfaced_at = NULL,
       published_precision = CASE WHEN r.at = date_trunc('day', r.at AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'
                                  THEN 'date' ELSE 'exact' END
  FROM redated r
 WHERE p.id = r.id;
