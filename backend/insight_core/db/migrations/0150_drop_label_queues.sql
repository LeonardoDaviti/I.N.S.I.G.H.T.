-- 0150_drop_label_queues.sql (Stealth v10.22, issue 0216 D: the Labels queue removed)
--
-- The Labels queue (0124: mx_label_queues, mx_label_queue_items; ~1.0M rows, 320 MB on the server) was a cache the
-- jobs process built from a decision run for the Labels tab (job "labels", up to 1.3 GB a build). The owner no longer
-- labels it (Haiku-first decisions, no owner-label gates) and nothing else read it: its module half, routes, tab and
-- job are removed with this. The owner's labels (mx_labels) stay, untouched.
-- mx_jobs: the "labels" row goes and the job check holds every other job (0142's list without 'labels').
-- Idempotent.

DROP TABLE IF EXISTS mx_label_queue_items;
DROP TABLE IF EXISTS mx_label_queues;

DELETE FROM mx_jobs WHERE job = 'labels';
ALTER TABLE mx_jobs DROP CONSTRAINT IF EXISTS mx_jobs_job_check;
ALTER TABLE mx_jobs ADD CONSTRAINT mx_jobs_job_check CHECK (job IN ('candidates', 'decide', 'plan', 'news', 'tracks',
                                                                    'unread', 'main_source', 'discover', 'official',
                                                                    'stories'));
