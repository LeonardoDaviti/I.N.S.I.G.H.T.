-- 0096_markx_scale.sql (Stealth v10.13.4: Mark X at the scale of every post read)
--
-- The job "plan" (markx/jobs.py Jobs.plan): the planners a lease no longer runs (check, cite, track: 47-60 s each
-- on the server once every post was read), every five minutes in a process of its own, so a failing decision run
-- never stops them.
ALTER TABLE mx_jobs DROP CONSTRAINT IF EXISTS mx_jobs_job_check;
ALTER TABLE mx_jobs ADD CONSTRAINT mx_jobs_job_check CHECK (job IN ('candidates', 'decide', 'plan'));
INSERT INTO mx_jobs (job) VALUES ('plan') ON CONFLICT (job) DO NOTHING;
