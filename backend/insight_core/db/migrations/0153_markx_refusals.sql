-- 0153_markx_refusals.sql (Stealth v10.23, issue 0217): the judge's refused verdicts between two Mark X stories.
-- A merge or connect question answered "different" keeps two stories apart: News's grouping reads it as a cannot-link
-- (utils/grouping.py), never as a connection (mx_connections holds only what connects; its many readers never see
-- these). Each row keeps the members the question showed (`shown`: {"a": [...], "b": [...]}), so a refusal about
-- members a story no longer holds is dropped as stale. Current rows: valid_to IS NULL; a refusal no longer found by
-- a run is closed, never deleted (keep everything).
CREATE TABLE IF NOT EXISTS mx_refusals (
  a          uuid NOT NULL,                 -- a story (mx_stories.id), the earlier
  b          uuid NOT NULL,                 -- the other story
  relation   text NOT NULL DEFAULT 'different',
  p          real,
  call_id    uuid REFERENCES mx_calls(id),
  question   text,                          -- the question's id (merge:..., connect:...)
  shown      jsonb,
  reason     text,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to   timestamptz,
  run_id     uuid REFERENCES mx_runs(id),
  CONSTRAINT mx_refusals_closes_after_it_opens CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_refusals_current_idx ON mx_refusals (a, b, relation) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS mx_refusals_b_idx ON mx_refusals (b) WHERE valid_to IS NULL;
