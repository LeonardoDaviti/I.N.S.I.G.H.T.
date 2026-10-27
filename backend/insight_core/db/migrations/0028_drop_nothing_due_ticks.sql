-- 0028_drop_nothing_due_ticks.sql (issue 0021)
--
-- A scheduler tick with nothing due made no request, and the scheduler now deletes its
-- job instead of listing it (scripts/run_scheduler.py). This removes the ones stored
-- before, so the job list and the Last run region show runs that fetched. The scheduler
-- state still records every tick. Idempotent.

DELETE FROM job_runs
WHERE job_type = 'ingestion_run'
  AND trigger = 'scheduler'
  AND payload->>'status' = 'nothing_due';
