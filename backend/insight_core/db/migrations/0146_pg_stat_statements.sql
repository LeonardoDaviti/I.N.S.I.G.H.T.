-- 0146_pg_stat_statements.sql (Stealth v10.21, issue 0215: the database's top statements)
--
-- pg_stat_statements: Postgres's own count of each normalized statement (constants as $1, $2...): calls, time, rows,
-- blocks. docker-compose.yml loads its library at the server's start (shared_preload_libraries); this creates its
-- view in INSIGHT's database. GET /api/operations/db-statements reads the top statements by total time
-- (operations_service.top_statements); it says "not enabled" while the library isn't loaded (a server not restarted
-- with compose's command yet, or a Postgres of your own without it).
--
-- A Postgres without the extension's files (not the pgvector image) is left as it is: the route says why.
-- Idempotent. (0145 is left to the v10.21 entities branch.)

DO $$
BEGIN
  CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
EXCEPTION WHEN OTHERS THEN
  RAISE NOTICE 'pg_stat_statements not created: %', SQLERRM;
END $$;
