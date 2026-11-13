-- 0129_markx_job_failures.sql (Stealth v10.17, issue 0188: jobs that fail back off, then show "failing")
--
-- mx_jobs.failures: the job's failed runs in a row (0 after a run that ends well; a run skipped because another holds
-- the lock changes nothing). markx/jobs.py waits GAP x 2^failures seconds after a failed run's end (at most 6 hours)
-- before the next try, and shows the job as failing from FAILING_AFTER failures on; it keeps trying at the longest
-- wait. Mark X tables only; no row changes. Idempotent.

ALTER TABLE mx_jobs ADD COLUMN IF NOT EXISTS failures integer NOT NULL DEFAULT 0;
