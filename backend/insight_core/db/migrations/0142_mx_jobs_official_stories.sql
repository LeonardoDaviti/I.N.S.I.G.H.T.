-- 0142_mx_jobs_official_stories.sql (Stealth v10.19.1, issue 0209: decision runs held)
--
-- mx_jobs' job check names every job of markx/jobs.JOBS:
--   - official (0196, v10.18): its runs could never record their start, so every pass crashed at its first write
--     (exit code 1, nothing recorded, tried again at the next look): official channels never ran on the server;
--   - stories (0209): a rule change's rebuild, its slices run from the jobs loop.
-- A test (test_markx_jobs) inserts every name in JOBS, so a job added without its row fails there, not on a server.
-- Idempotent.

ALTER TABLE mx_jobs DROP CONSTRAINT IF EXISTS mx_jobs_job_check;
ALTER TABLE mx_jobs ADD CONSTRAINT mx_jobs_job_check CHECK (job IN ('candidates', 'decide', 'plan', 'labels', 'news',
                                                                    'tracks', 'unread', 'main_source', 'discover',
                                                                    'official', 'stories'));
