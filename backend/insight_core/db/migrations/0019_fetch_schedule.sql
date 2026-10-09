-- 0019_fetch_schedule.sql (Mark IX B1)
-- Adaptive fetch cadence: cadence columns on sources, and the per-source fetch state in
-- its own table instead of settings.ops / settings.ingest_backoff JSONB.
-- Idempotent; runs inside migrate.py's single transaction (under its advisory xact lock).

ALTER TABLE sources
  ADD COLUMN IF NOT EXISTS mean_gap_seconds DOUBLE PRECISION NULL,
  ADD COLUMN IF NOT EXISTS cadence_sample_size INT NULL,
  ADD COLUMN IF NOT EXISTS cadence_tier TEXT NOT NULL DEFAULT 'unknown'
      CHECK (cadence_tier IN ('fast','medium','slow','unknown')),
  ADD COLUMN IF NOT EXISTS cadence_computed_at TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS fetch_interval_hours_override DOUBLE PRECISION NULL
      CHECK (fetch_interval_hours_override IS NULL OR fetch_interval_hours_override > 0);

CREATE TABLE IF NOT EXISTS source_fetch_state (
  source_id            UUID PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
  last_attempt_at      TIMESTAMPTZ NULL,
  last_success_at      TIMESTAMPTZ NULL,   -- healthy OR empty: the fetch worked
  last_outcome         TEXT NULL CHECK (last_outcome IN ('healthy','empty','error','unavailable')),
  last_trigger         TEXT NULL,
  last_fetched_posts   INT NULL,
  last_error           TEXT NULL,
  last_error_at        TIMESTAMPTZ NULL,
  consecutive_failures INT NOT NULL DEFAULT 0,
  next_retry_at        TIMESTAMPTZ NULL,
  last_decision_kind   TEXT NULL,
  last_decision_at     TIMESTAMPTZ NULL,
  next_due_at          TIMESTAMPTZ NULL,   -- denormalised from the last decision, for sorting in the UI
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS source_fetch_state_next_due_idx ON source_fetch_state (next_due_at);

-- Safe casts: the JSONB was written by Python and can be malformed ("not-a-date"). A raw
-- ::timestamptz would abort migrate.py, and both start scripts run it under
-- `set -euo pipefail`, so both containers would crash-loop. pg_temp functions vanish
-- with the session.
CREATE OR REPLACE FUNCTION pg_temp.try_ts(v text) RETURNS timestamptz LANGUAGE plpgsql AS $$
BEGIN RETURN NULLIF(v,'')::timestamptz; EXCEPTION WHEN others THEN RETURN NULL; END $$;
CREATE OR REPLACE FUNCTION pg_temp.try_int(v text) RETURNS int LANGUAGE plpgsql AS $$
BEGIN RETURN NULLIF(v,'')::int; EXCEPTION WHEN others THEN RETURN NULL; END $$;

-- Backfill from Mark VIII JSONB (settings.ops + settings.ingest_backoff), else from posts.
INSERT INTO source_fetch_state (source_id, last_attempt_at, last_success_at, last_outcome, last_trigger,
                                last_fetched_posts, last_error, last_error_at, consecutive_failures, next_retry_at)
SELECT s.id,
       pg_temp.try_ts(s.settings #>> '{ops,last_checked_at}'),
       -- Mark VIII only advanced ops.last_success_at on 'healthy'; Mark IX counts 'empty' as a
       -- success too, so an empty last check is the newer success.
       COALESCE(GREATEST(pg_temp.try_ts(s.settings #>> '{ops,last_success_at}'),
                         CASE WHEN s.settings #>> '{ops,last_status}' = 'empty'
                              THEN pg_temp.try_ts(s.settings #>> '{ops,last_checked_at}') END),
                (SELECT MAX(p.fetched_at) FROM posts p WHERE p.source_id = s.id)),
       -- Normalised here, not in a later UPDATE: the CHECK constraint is enforced during the
       -- INSERT, so an out-of-set value ('running', 'unknown', ...) must never reach it.
       CASE WHEN s.settings #>> '{ops,last_status}' IN ('healthy','empty','error','unavailable')
            THEN s.settings #>> '{ops,last_status}' END,
       NULLIF(s.settings #>> '{ops,last_trigger}',''),
       pg_temp.try_int(s.settings #>> '{ops,last_fetched_posts}'),
       CASE WHEN s.settings #>> '{ops,last_status}' = 'error' THEN s.settings #>> '{ops,last_message}' END,
       pg_temp.try_ts(s.settings #>> '{ops,last_error_at}'),
       GREATEST(COALESCE(pg_temp.try_int(s.settings #>> '{ingest_backoff,consecutive_failures}'), 0), 0),
       pg_temp.try_ts(s.settings #>> '{ingest_backoff,next_retry_at}')
FROM sources s
ON CONFLICT (source_id) DO NOTHING;

UPDATE sources SET settings = settings - 'ingest_backoff' - 'ops'
WHERE settings ? 'ingest_backoff' OR settings ? 'ops';

-- First cadence refresh, so the health UI is not blank until the first ingest.
-- A literal copy of FetchStateRepository.refresh_cadence (window 20, 3 distinct
-- timestamps, tier boundaries 12h / 7d); keep the two in step.
WITH ranked AS (
    SELECT source_id, published_at,
           row_number() OVER (PARTITION BY source_id ORDER BY published_at DESC) AS rn
    FROM posts
    WHERE published_at IS NOT NULL
), agg AS (
    SELECT source_id,
           count(DISTINCT published_at)::int AS samples,
           EXTRACT(EPOCH FROM (max(published_at) - min(published_at)))
               / NULLIF(count(*) - 1, 0) AS gap
    FROM ranked
    WHERE rn <= 20
    GROUP BY source_id
), target AS (
    SELECT s2.id,
           COALESCE(a.samples, 0) AS samples,
           CASE WHEN COALESCE(a.samples, 0) >= 3 THEN a.gap END AS gap
    FROM sources s2
    LEFT JOIN agg a ON a.source_id = s2.id
)
UPDATE sources s SET
    cadence_sample_size = t.samples,
    mean_gap_seconds = t.gap,
    cadence_tier = CASE
        WHEN t.gap IS NULL THEN 'unknown'
        WHEN t.gap < 43200 THEN 'fast'
        WHEN t.gap <= 604800 THEN 'medium'
        ELSE 'slow'
    END,
    cadence_computed_at = now()
FROM target t
WHERE s.id = t.id;
