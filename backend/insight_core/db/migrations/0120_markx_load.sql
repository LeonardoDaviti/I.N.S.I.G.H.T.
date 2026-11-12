-- 0120_markx_load.sql (Stealth v10.16, issue 0177: the server's remaining load)
--
-- /api/markx/overview (4.4 s on the server) read the whole task queue twice and every call once: the queue by kind
-- and status, the failed tasks and the token totals were sequential scans of mx_tasks (its inputs inline, ~1.5 kB a
-- row: ~2 GB at the server's 1.25M tasks) and mx_calls, and the last invalid calls walked the calls backwards until
-- ten invalid ones came. Indexes that answer each of them alone (index-only where the visibility map allows); the
-- queries and their answers are unchanged. Mark X tables only. Idempotent.

CREATE INDEX IF NOT EXISTS mx_tasks_kind_status_idx ON mx_tasks (kind, status);
CREATE INDEX IF NOT EXISTS mx_tasks_failed_idx ON mx_tasks (kind) WHERE status = 'failed';
CREATE INDEX IF NOT EXISTS mx_calls_totals_idx ON mx_calls (created_at) INCLUDE (valid, tokens_in, tokens_out, cost_usd);
CREATE INDEX IF NOT EXISTS mx_calls_invalid_idx ON mx_calls (created_at) WHERE NOT valid;
