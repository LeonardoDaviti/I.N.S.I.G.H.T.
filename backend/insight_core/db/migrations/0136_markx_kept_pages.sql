-- 0136_markx_kept_pages.sql (Stealth v10.17.2, issue 0198: pages that only change when a job runs are kept)
--
-- mx_kept_pages: a page's answer as the API sends it (the JSON's bytes), with the stamp of the inputs it was built
-- from (markx/kept_pages.py). The API sends the kept bytes while the page's stamp, read again at the request, is the
-- same; else it builds the page as before. One row a page, key and decision run:
--   - Mark X News (page 'news', key 'differences' or 'all'): built by the jobs process after each decision run and
--     again when what the page reads between runs changed (news.keep_pages); the newest KEEP_RUNS runs' rows stay.
--   - an entity's page (page 'entity', key its id and the page's parameters): built by the API at the first open (as
--     before) and kept; at most ENTITY_PAGES rows, the newest built.
-- A cache: rows are pruned and rebuilt (the posts, stories and News rows it is built from are kept as ever).
-- Mark X tables only; no key to another table. Idempotent.

CREATE TABLE IF NOT EXISTS mx_kept_pages (
  page      text NOT NULL,
  key       text NOT NULL,
  run_id    uuid NOT NULL,
  stamp     text NOT NULL,
  body      bytea NOT NULL,
  bytes     integer NOT NULL,
  seconds   real,
  until     timestamptz,                 -- sent only before this (a page that reads the clock: its next edge)
  built_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (page, key, run_id)
);
CREATE INDEX IF NOT EXISTS mx_kept_pages_built_idx ON mx_kept_pages (page, built_at DESC);

-- The jobs process's job "news" (markx/jobs.py: Mark X News' views kept after each run) has its row in mx_jobs.
ALTER TABLE mx_jobs DROP CONSTRAINT IF EXISTS mx_jobs_job_check;
ALTER TABLE mx_jobs ADD CONSTRAINT mx_jobs_job_check CHECK (job IN ('candidates', 'decide', 'plan', 'labels', 'news'));
