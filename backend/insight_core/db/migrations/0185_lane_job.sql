-- 0185_lane_job.sql (Stealth v10.47, 0279 B2: planners never at lease time)
--
-- The jobs' lane (markx/jobs.py Jobs.lane: the planners a worker's lease ran, now run beside the jobs every
-- LANE_EVERY seconds) has its mx_jobs row: 0179's list + 'lane'. No row is rewritten.
ALTER TABLE mx_jobs DROP CONSTRAINT IF EXISTS mx_jobs_job_check;
ALTER TABLE mx_jobs ADD CONSTRAINT mx_jobs_job_check CHECK (job IN ('candidates', 'decide', 'plan', 'news', 'tracks',
                                                                    'unread', 'main_source', 'discover', 'official',
                                                                    'stories', 'entities', 'discussions', 'lane'));
