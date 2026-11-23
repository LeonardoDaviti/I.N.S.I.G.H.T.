-- 0177_data_repairs.sql (Stealth v10.43: data repairs run themselves after a deploy)
--
-- data_repairs: one row a registered one-time repair (services/data_repairs.py). The jobs process runs each repair
-- once per its version after a start and records what it changed; the Operations page shows it and asks for a run
-- again or a preview (`requested`), which the jobs process picks up. The API never runs a repair.
--   version       the repair's version last run for real without an error (a failed run is tried again next start)
--   last_run      {at, version, dry_run: false, counts, sample, seconds, error?}
--   last_preview  the same, of the last dry run
--   requested     'run' | 'preview' (the page's ask), requested_at when; cleared when the jobs process takes it
--   running       'run' | 'preview' while the jobs process runs it, since running_since
-- Nothing is deleted. Idempotent.

CREATE TABLE IF NOT EXISTS data_repairs (
    name           text PRIMARY KEY,
    version        text,
    last_run       jsonb,
    last_preview   jsonb,
    requested      text CHECK (requested IN ('run', 'preview')),
    requested_at   timestamptz,
    running        text CHECK (running IN ('run', 'preview')),
    running_since  timestamptz,
    updated_at     timestamptz NOT NULL DEFAULT now()
);
