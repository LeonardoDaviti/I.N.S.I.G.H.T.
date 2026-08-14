-- 0015_job_runs_retention.sql
-- job_runs.payload was written uncompacted: expert/briefing runs stored their whole
-- result graph, including every cited post with content and content_html. Rows
-- averaged ~1.3MB (max ~2.9MB) and nothing ever pruned them, so the table grew
-- without bound and every list query paid for it in RAM.
--
-- Producers now pass compact=True (see OperationsService.finish_job). This migration
-- reclaims the existing backlog and adds the index the retention sweep needs.

-- One-time cleanup: drop job history older than 30 days.
DELETE FROM job_runs
WHERE started_at < now() - interval '30 days';

-- Strip the fat keys from surviving rows. Keeps the small fields the UI reads
-- (progress, estimated_tokens, token_usage, error, posts_processed,
-- saved_briefing_id) and the events array; drops the bulk result graph.
UPDATE job_runs
SET payload = payload - 'posts' - 'topics' - 'briefing' - 'content' - 'sources'
WHERE payload IS NOT NULL
  AND (payload ?| ARRAY['posts', 'topics', 'briefing', 'content', 'sources']);

-- Retention sweeps and the list view both order by started_at DESC.
CREATE INDEX IF NOT EXISTS job_runs_started_at_idx ON job_runs (started_at DESC);

-- NOTE: no VACUUM here on purpose - migrate.py runs the batch inside a single
-- transaction and VACUUM cannot run in one. To return the freed pages to disk,
-- run this once by hand after migrating:
--   docker exec insight-db psql -U insight -d insight -c 'VACUUM (FULL, ANALYZE) job_runs;'
