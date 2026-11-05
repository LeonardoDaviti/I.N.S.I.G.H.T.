-- 0069_markx_v10_0_1.sql (issue 0112, Mark X v10.0.1: the queue v10.0 left, repaired once)
--
-- 1. (Decided 5) Reopens the Mark X read tasks that failed only because read-v2 never names the mention
--    field: Haiku wrote {"event", "role"} and the server refused "answer.mentions[i]: name missing" three
--    times. The worker now sends each guide's answer schema with its body (0112 Decided 1), so the next
--    worker cycle reads them. A task is reopened when it is a failed `read` and every error recorded for it
--    (each invalid call's, and its last_error) is that one; it gets its tries back (attempts 0). Its failed
--    calls stay in mx_calls. Live on the server (2026-11-05): 39 such tasks; on the server's copy run with
--    real Haiku, 199 of 199 failed reads.
-- 2. (0112 C) Closes the check tasks still waiting (open or leased) whose input shows their story with no
--    member (bug 2): v10.0.1 never builds that input, so no decision would read their answer; asking them
--    would only spend Haiku calls. They become `failed` with the reason in last_error; their rows stay.
--    The same test as tasks.shows_empty_story and the real-data check's markx.check_empty_story. On the lab
--    (2026-11-05): 10 of its 125 waiting checks. Answered ones stay as they are (Decided 6: not read again).
--
-- 3. (Decided 9) mx_settings: the owner's Mark X settings, set from the /markx page (Mark X writes only mx_*
--    tables, so not system_settings). Key `reading_window_days`: the read, entities and embed planners' window,
--    an int or null for every post; no row means 30 days. Nothing is seeded: the owner sets it on the page.
--
-- Mark X tables only; nothing is deleted. Idempotent: a reopened read is open and a closed check failed, so a
-- second run changes nothing.

UPDATE mx_tasks t
   SET status = 'open', attempts = 0, lease_until = NULL, leased_by = NULL
 WHERE t.kind = 'read'
   AND t.status = 'failed'
   AND COALESCE(t.last_error, '') ~ '^answer\.mentions\[[0-9]+\]: name missing$'
   AND EXISTS (SELECT 1 FROM mx_calls c WHERE c.task_id = t.id AND NOT c.valid)
   AND NOT EXISTS (SELECT 1 FROM mx_calls c
                    WHERE c.task_id = t.id
                      AND (c.valid OR COALESCE(c.error, '') !~ '^answer\.mentions\[[0-9]+\]: name missing$'));

UPDATE mx_tasks
   SET status = 'failed', lease_until = NULL, leased_by = NULL,
       last_error = 'v10.0.1 (issue 0112): shows its story with no member (an empty story); never asked'
 WHERE kind = 'check'
   AND status IN ('open', 'leased')
   AND strpos(split_part(input, E'\n\nPOST\n', 1) || E'\n', E'\nMembers (earliest first):\n') = 0;

CREATE TABLE IF NOT EXISTS mx_settings (
  key        text PRIMARY KEY,
  value      jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);
