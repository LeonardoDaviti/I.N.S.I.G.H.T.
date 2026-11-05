-- 0069_markx_reopen_unnamed_mentions.sql (issue 0112 Decided 5: Mark X v10.0.1)
--
-- Reopens, once, the Mark X read tasks that failed only because read-v2 never names the mention field:
-- Haiku wrote {"event", "role"} and the server refused "answer.mentions[i]: name missing" three times.
-- The worker now sends each guide's answer schema with its body (0112 Decided 1), so the next worker
-- cycle reads them. A task is reopened when it is a failed `read` and every error recorded for it (each
-- invalid call's, and its last_error) is that one; it gets its tries back (attempts 0). Its failed calls
-- stay in mx_calls: nothing is deleted. Live on the server (2026-11-05): 39 such tasks; on the server's
-- copy run with real Haiku, 199 of 199 failed reads.
--
-- Mark X tables only. Idempotent: a reopened task is open, so a second run changes nothing.

UPDATE mx_tasks t
   SET status = 'open', attempts = 0, lease_until = NULL, leased_by = NULL
 WHERE t.kind = 'read'
   AND t.status = 'failed'
   AND COALESCE(t.last_error, '') ~ '^answer\.mentions\[[0-9]+\]: name missing$'
   AND EXISTS (SELECT 1 FROM mx_calls c WHERE c.task_id = t.id AND NOT c.valid)
   AND NOT EXISTS (SELECT 1 FROM mx_calls c
                    WHERE c.task_id = t.id
                      AND (c.valid OR COALESCE(c.error, '') !~ '^answer\.mentions\[[0-9]+\]: name missing$'));
