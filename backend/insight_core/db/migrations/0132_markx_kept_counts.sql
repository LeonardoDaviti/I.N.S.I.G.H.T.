-- 0132_markx_kept_counts.sql (Stealth v10.17, issue 0195: the API light and fast)
--
-- /api/markx/overview and /api/markx/status counted every Mark X task by kind and status (a GROUP BY over ~1M
-- mx_tasks) and summed every call (count and tokens over mx_calls) on each request. The totals are kept instead:
--   mx_counts        the folded totals, one row a key ('task:<kind>:<status>', 'calls');
--   mx_counts_delta  an append-only log the triggers write, one row a statement and key (no row is locked: the
--                    workers that lease and answer tasks at once never wait on a counter).
-- A read is the totals plus the deltas (markx/kept_counts.py), so it always equals the GROUP BY; the fold (after
-- each ingestion run) moves the deltas into the totals in one statement. Idempotent; no row of the tasks or calls
-- changes.

CREATE TABLE IF NOT EXISTS mx_counts (
    key         text PRIMARY KEY,
    n           bigint NOT NULL DEFAULT 0,
    tokens_in   bigint NOT NULL DEFAULT 0,
    tokens_out  bigint NOT NULL DEFAULT 0,
    cost_usd    numeric NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mx_counts_delta (
    id          bigserial PRIMARY KEY,
    key         text NOT NULL,
    n           bigint NOT NULL DEFAULT 0,
    tokens_in   bigint NOT NULL DEFAULT 0,
    tokens_out  bigint NOT NULL DEFAULT 0,
    cost_usd    numeric NOT NULL DEFAULT 0
);

-- Tasks: each statement's rows counted out of their old (kind, status) and into their new one; a key whose count
-- did not move (a lease renewed, an attempt counted) writes nothing.
CREATE OR REPLACE FUNCTION mx_counts_tasks() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO mx_counts_delta (key, n)
        SELECT 'task:' || kind || ':' || status, count(*) FROM new_rows GROUP BY 1;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO mx_counts_delta (key, n)
        SELECT 'task:' || kind || ':' || status, -count(*) FROM old_rows GROUP BY 1;
    ELSE
        INSERT INTO mx_counts_delta (key, n)
        SELECT key, sum(d) FROM (SELECT 'task:' || kind || ':' || status AS key, 1 AS d FROM new_rows
                                 UNION ALL
                                 SELECT 'task:' || kind || ':' || status, -1 FROM old_rows) x
         GROUP BY key HAVING sum(d) <> 0;
    END IF;
    RETURN NULL;
END $$;

-- Calls: their number, tokens and cost.
CREATE OR REPLACE FUNCTION mx_counts_calls() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        INSERT INTO mx_counts_delta (key, n, tokens_in, tokens_out, cost_usd)
        SELECT 'calls', count(*), COALESCE(sum(tokens_in), 0), COALESCE(sum(tokens_out), 0), COALESCE(sum(cost_usd), 0)
          FROM new_rows HAVING count(*) > 0;
    ELSIF TG_OP = 'DELETE' THEN
        INSERT INTO mx_counts_delta (key, n, tokens_in, tokens_out, cost_usd)
        SELECT 'calls', -count(*), -COALESCE(sum(tokens_in), 0), -COALESCE(sum(tokens_out), 0),
               -COALESCE(sum(cost_usd), 0)
          FROM old_rows HAVING count(*) > 0;
    ELSE
        INSERT INTO mx_counts_delta (key, n, tokens_in, tokens_out, cost_usd)
        SELECT 'calls', 0, n.ti - o.ti, n.tt - o.tt, n.c - o.c
          FROM (SELECT COALESCE(sum(tokens_in), 0) ti, COALESCE(sum(tokens_out), 0) tt, COALESCE(sum(cost_usd), 0) c
                  FROM new_rows) n,
               (SELECT COALESCE(sum(tokens_in), 0) ti, COALESCE(sum(tokens_out), 0) tt, COALESCE(sum(cost_usd), 0) c
                  FROM old_rows) o
         WHERE n.ti <> o.ti OR n.tt <> o.tt OR n.c <> o.c;
    END IF;
    RETURN NULL;
END $$;

-- TRUNCATE (tests): the table is empty, and so are its totals.
CREATE OR REPLACE FUNCTION mx_counts_truncated() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    DELETE FROM mx_counts WHERE key LIKE TG_ARGV[0];
    DELETE FROM mx_counts_delta WHERE key LIKE TG_ARGV[0];
    RETURN NULL;
END $$;

-- Exactness: no task or call is written between the totals counted below and the triggers taking over.
LOCK TABLE mx_tasks, mx_calls IN SHARE ROW EXCLUSIVE MODE;

DROP TRIGGER IF EXISTS mx_tasks_counted_ins ON mx_tasks;
CREATE TRIGGER mx_tasks_counted_ins AFTER INSERT ON mx_tasks REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_counts_tasks();
DROP TRIGGER IF EXISTS mx_tasks_counted_del ON mx_tasks;
CREATE TRIGGER mx_tasks_counted_del AFTER DELETE ON mx_tasks REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_counts_tasks();
DROP TRIGGER IF EXISTS mx_tasks_counted_upd ON mx_tasks;
CREATE TRIGGER mx_tasks_counted_upd AFTER UPDATE ON mx_tasks REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_counts_tasks();
DROP TRIGGER IF EXISTS mx_tasks_counted_trunc ON mx_tasks;
CREATE TRIGGER mx_tasks_counted_trunc AFTER TRUNCATE ON mx_tasks
    FOR EACH STATEMENT EXECUTE FUNCTION mx_counts_truncated('task:%');

DROP TRIGGER IF EXISTS mx_calls_counted_ins ON mx_calls;
CREATE TRIGGER mx_calls_counted_ins AFTER INSERT ON mx_calls REFERENCING NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_counts_calls();
DROP TRIGGER IF EXISTS mx_calls_counted_del ON mx_calls;
CREATE TRIGGER mx_calls_counted_del AFTER DELETE ON mx_calls REFERENCING OLD TABLE AS old_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_counts_calls();
DROP TRIGGER IF EXISTS mx_calls_counted_upd ON mx_calls;
CREATE TRIGGER mx_calls_counted_upd AFTER UPDATE ON mx_calls REFERENCING OLD TABLE AS old_rows NEW TABLE AS new_rows
    FOR EACH STATEMENT EXECUTE FUNCTION mx_counts_calls();
DROP TRIGGER IF EXISTS mx_calls_counted_trunc ON mx_calls;
CREATE TRIGGER mx_calls_counted_trunc AFTER TRUNCATE ON mx_calls
    FOR EACH STATEMENT EXECUTE FUNCTION mx_counts_truncated('calls');

-- The totals as they are now (under the lock), every delta before them gone.
DELETE FROM mx_counts;
DELETE FROM mx_counts_delta;
INSERT INTO mx_counts (key, n)
SELECT 'task:' || kind || ':' || status, count(*) FROM mx_tasks GROUP BY 1;
INSERT INTO mx_counts (key, n, tokens_in, tokens_out, cost_usd)
SELECT 'calls', count(*), COALESCE(sum(tokens_in), 0), COALESCE(sum(tokens_out), 0), COALESCE(sum(cost_usd), 0)
  FROM mx_calls;
