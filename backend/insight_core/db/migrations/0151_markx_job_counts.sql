-- 0151_markx_job_counts.sql (Stealth v10.22, issue 0216: process monitoring)
--
-- mx_jobs keeps, besides each job's last run (`last`), what GET /metrics needs to show a job over time without a
-- store of its own:
--   runs_ok, runs_failed  every run that ended well, and every failed run (markx/jobs.py: the runs `failures` counts),
--                         since this migration (Prometheus reads them as counters);
--   ok_at                 the end of the last run that ended well (a job failing, or never running, ages from it);
--   recent                the last jobs.RECENT runs, newest first: [{at, ok, seconds, peak_mb, cpu_s}] (a few hundred
--                         bytes a job).
-- Written by the same UPDATE that records a run's end (jobs.Jobs._finish, Runner._reap); nothing else changes.
-- Mark X tables only. Idempotent.

ALTER TABLE mx_jobs ADD COLUMN IF NOT EXISTS runs_ok bigint NOT NULL DEFAULT 0;
ALTER TABLE mx_jobs ADD COLUMN IF NOT EXISTS runs_failed bigint NOT NULL DEFAULT 0;
ALTER TABLE mx_jobs ADD COLUMN IF NOT EXISTS ok_at timestamptz;
ALTER TABLE mx_jobs ADD COLUMN IF NOT EXISTS recent jsonb NOT NULL DEFAULT '[]'::jsonb;

-- a job whose last run ended well: its end is its last success
UPDATE mx_jobs SET ok_at = finished_at
 WHERE ok_at IS NULL AND finished_at IS NOT NULL AND (last ->> 'ok') = 'true';
