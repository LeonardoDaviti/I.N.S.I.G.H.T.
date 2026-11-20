-- 0161_drop_redundant_indexes.sql (Stealth v10.26, issue 0244: data and CPU)
--
-- Three indexes no statement needs, each a plain DROP (milliseconds, a short exclusive lock on its table; the file runs
-- in a transaction like the archive restore's). Every insert and every non-HOT update stops writing them (WAL too).
--
-- 1. mx_calls_created_idx (0068) is mx_calls (created_at). mx_calls_totals_idx (0120) is mx_calls (created_at)
--    INCLUDE (valid, tokens_in, tokens_out, cost_usd): the same key in the same order, so every scan the first can do
--    (a range, an order by created_at, max(created_at)) the second does too, index-only for the totals. The server's
--    1.56M calls: ~35-45 MB of index.
-- 2. mx_mentions_family_version_idx (0068) is mx_mentions (family, version). No statement filters, joins or orders
--    mx_mentions by family (the code's queries, the views and the SQL functions read: family is only selected, by
--    identity.py, surges.py). The server's 1.98M mentions: an estimated 40-60 MB, and every mention insert writes it.
-- 3. job_runs_started_at_idx (0015) duplicates job_runs_started_idx (0006): both job_runs (started_at DESC).
--
-- Idempotent. Nothing a reader sees changes: no row is touched.

DROP INDEX IF EXISTS mx_calls_created_idx;
DROP INDEX IF EXISTS mx_mentions_family_version_idx;
DROP INDEX IF EXISTS job_runs_started_at_idx;
