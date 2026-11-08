-- 0086_source_profiles.sql (issue 0132 C2: channel profiles)
--
-- One row per profile fetch of a source (services/profiles_service.py, monthly, through the normal fetch path):
-- the name it shows, its bio, its website field, the accounts and addresses it links, its subscriber or follower
-- count. Nothing is ever deleted (keep everything): a new answer closes the last one (valid_to) and adds a row, so a
-- source's profile has its history. A failed fetch is a row too (status failed, closed at once: never current), so
-- the next ask waits its retry.
--
-- kind: nitter | youtube | telegram_bridge | telegram_mtproto | site (ingestion/profiles.py's parsers).
-- links: [address], the website field first. followers_label: followers | subscribers.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS source_profiles (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id       uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  kind            text NOT NULL,
  url             text,
  status          text NOT NULL CHECK (status IN ('ok', 'failed')),
  name            text,
  bio             text,
  website         text,
  links           jsonb NOT NULL DEFAULT '[]'::jsonb,
  followers       bigint,
  followers_label text,
  error           text,
  fetched_at      timestamptz NOT NULL DEFAULT now(),
  valid_to        timestamptz
);
CREATE INDEX IF NOT EXISTS source_profiles_source_idx ON source_profiles (source_id, fetched_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS source_profiles_current_idx ON source_profiles (source_id)
  WHERE valid_to IS NULL AND status = 'ok';
