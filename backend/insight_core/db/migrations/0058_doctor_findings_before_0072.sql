-- 0058_doctor_findings_before_0072.sql (issue 0072, D3)
--
-- What the source doctor and the fetcher stored before 0072 C1, said as C1 says it now.
--
-- An error whose answer was a web page (a proxy's "502 Bad Gateway" page) stored that page as its
-- text. It becomes its status line, as C1's fetcher writes it: "HTTP 502 while fetching <url>:
-- Bad Gateway", the reason taken from the page's <title>, else its <h1>, without the code.
--
-- An offer stored before C1 was never checked against the source's items (no `shared`): it is
-- removed. On a source failing with a server error (HTTP 5xx, a timeout) it becomes C1's server-error
-- finding, with its status; on any other the finding and when it looked go, so the doctor looks
-- again at the next failure.
-- Runs once; a second run finds nothing to change.

UPDATE source_fetch_state
   SET last_error = regexp_replace(last_error, ':\s*<.*$', '')
                    || COALESCE(': ' || NULLIF(btrim(regexp_replace(
                           COALESCE(substring(last_error from '(?i)<title>([^<]*)</title>'),
                                    substring(last_error from '(?i)<h1>([^<]*)</h1>')), '^\s*\d{3}\s*', '')), ''), ''),
       updated_at = now()
 WHERE last_error ~ '^HTTP \d{3} while [^<]*:\s*<';

UPDATE source_fetch_state
   SET doctor_finding = CASE WHEN last_error ~ '^(HTTP 5\d\d |Timed out)'
                             THEN jsonb_build_object('replacement', NULL, 'dismissed', false, 'server_error', true,
                                                     'note', 'server error, not moved',
                                                     'status', substring(last_error from '^HTTP (5\d\d) ')::int) END,
       doctor_checked_at = CASE WHEN last_error ~ '^(HTTP 5\d\d |Timed out)' THEN doctor_checked_at END,
       updated_at = now()
 WHERE jsonb_typeof(doctor_finding->'replacement') = 'object' AND NOT (doctor_finding->'replacement' ? 'shared');
