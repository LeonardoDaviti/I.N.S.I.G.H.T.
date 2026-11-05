-- 0070_markx_jobs.sql (issue 0112 Decided 10-12, Mark X v10.0.2: Mark X's jobs leave the API)
--
-- 1. mx_jobs: one row per Mark X job ('candidates', 'decide'). The API never runs a job: it only marks that work
--    arrived (wanted_at, set once until a run takes it), and insight-ingestion's scheduler runs the job within
--    30 s (markx/jobs.py). The row also shows a run while it runs (started_at, stage, stage_at; /api/markx/status
--    and the /markx page) and how the last one ended (finished_at, last). Written only in short transactions of
--    their own, never inside a run's transaction, so a request marking work never waits for a run.
-- 2. mx_candidate_posts: the posts whose vectors arrived, for the candidate finder (they lived in one process's
--    memory before). noted_at is the last time a vector arrived for it, found_at the start of the last run that
--    found its candidates; a post waits while found_at is null or older than noted_at. One row per post, never
--    deleted.
-- 3. mx_workers: each Mark X worker's last request (a dict in one API process's memory before; with two API
--    processes each saw half of them).
--
-- Mark X tables only; nothing is deleted. Idempotent.

CREATE TABLE IF NOT EXISTS mx_jobs (
  job         text PRIMARY KEY CHECK (job IN ('candidates', 'decide')),
  wanted_at   timestamptz,
  started_at  timestamptz,
  stage       text,
  stage_at    timestamptz,
  finished_at timestamptz,
  last        jsonb
);
INSERT INTO mx_jobs (job) VALUES ('candidates'), ('decide') ON CONFLICT (job) DO NOTHING;

CREATE TABLE IF NOT EXISTS mx_candidate_posts (
  post_id  uuid PRIMARY KEY,
  noted_at timestamptz NOT NULL DEFAULT now(),
  found_at timestamptz
);
CREATE INDEX IF NOT EXISTS mx_candidate_posts_waiting_idx ON mx_candidate_posts (noted_at)
  WHERE found_at IS NULL OR found_at < noted_at;

CREATE TABLE IF NOT EXISTS mx_workers (
  worker       text PRIMARY KEY,
  last_contact timestamptz NOT NULL DEFAULT now()
);
