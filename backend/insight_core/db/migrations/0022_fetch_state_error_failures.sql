-- 0022_fetch_state_error_failures.sql (Mark IX, repair of the 0019 backfill)
--
-- 0019 took consecutive_failures from settings.ingest_backoff alone, so a Mark VIII source
-- whose ops.last_status was 'error' but had no (or a malformed) backoff counter came out
-- as last_outcome='error' with 0 failures. Health then read it as due/deferred and the
-- summary undercounted errors. 0019 is fixed for fresh installs; this repairs databases
-- that already ran it. Only rows whose error is newer than their last success are touched.
-- next_retry_at stays NULL, so the next tick retries the source. Idempotent.

UPDATE source_fetch_state
   SET consecutive_failures = 1, updated_at = now()
 WHERE last_outcome = 'error'
   AND consecutive_failures = 0
   AND (last_success_at IS NULL OR last_error_at IS NULL OR last_error_at >= last_success_at);
