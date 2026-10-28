-- 0032_source_doctor.sql (issue 0036)
--
-- The source doctor's memory, per source: when it last looked for a broken source's
-- replacement (it looks at most once a day) and what it found:
--   {"replacement": {"kind": "feed"|"page_watch", "url", "title", "found", "prefix"} | null,
--    "dismissed": false}
-- A fetch that works clears both (the failure streak is over); so does a switch.
-- Numbered 0032: unmerged branches hold 0030 and 0031. Idempotent.

ALTER TABLE source_fetch_state
    ADD COLUMN IF NOT EXISTS doctor_checked_at timestamptz,
    ADD COLUMN IF NOT EXISTS doctor_finding jsonb;
