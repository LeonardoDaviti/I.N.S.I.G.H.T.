-- 0113_markx_incremental_state.sql (Stealth v10.15, issue 0169: the decision run's incremental state in Postgres)
--
-- Each decision run is a process of its own (0112 Decided 10), so 0116's in-process memo never survived to the next
-- run and every run was full. A run now leaves what the next one needs here (markx/incremental.py), in its own
-- transaction: a failed run leaves the last finished run's state.
--
--   mx_inc_state   one row ('decide'): the run that left it, its key (code, config, guides), Mark IX's table stamps,
--                  the last run's News inputs and rows and its memberships (incremental.encode: typed json).
--   mx_inc_posts   each world post as the rules read it (source, kind, time, words), kept by its text stamp
--                  (plan_marks.STAMP): its text is read again only when the stamp changed.
--   mx_inc_inputs  a question's input hash by what it shows (its kind and its posts' stamps, readings, cards).
--   mx_inc_copies  a story's near-copies by its members' stamps.
--   mx_inc_tasks   each judge task's (status, valid calls) as the last run saw it: the dirty set is what changed.
--
-- A cache of what a run read, not derived rows: every value is a function of the rows its key names, a full run
-- (nightly, or after a code change) writes it whole again, and a run keeps only what it used. Mark X tables only.
-- Idempotent.

CREATE TABLE IF NOT EXISTS mx_inc_state (
  name      text PRIMARY KEY,
  run_id    uuid,
  key       text NOT NULL,
  stamps    jsonb NOT NULL,
  news      jsonb,
  want      jsonb,
  saved_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mx_inc_posts (
  post_id    uuid PRIMARY KEY,
  stamp      text NOT NULL,
  source_id  text NOT NULL,
  kind       text NOT NULL,
  at         timestamptz,
  words      integer NOT NULL
);

CREATE TABLE IF NOT EXISTS mx_inc_inputs (
  key         text PRIMARY KEY,
  kind        text NOT NULL,
  input_hash  text NOT NULL
);

CREATE TABLE IF NOT EXISTS mx_inc_copies (
  key     text PRIMARY KEY,
  copies  text[] NOT NULL
);

CREATE TABLE IF NOT EXISTS mx_inc_tasks (
  task_id  uuid PRIMARY KEY,
  status   text NOT NULL,
  n        integer NOT NULL
);
