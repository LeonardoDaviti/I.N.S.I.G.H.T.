-- 0158_kept_pages_code_and_opens.sql (Stealth v10.25, issue 0232: pages kept across a deploy, opened pages built first)
--
-- mx_kept_pages.code: the code stamp a row was built with (kept_pages.code_stamp), apart from its input stamp. Before,
-- the code was hashed into the stamp, so every deploy made every kept page cold (Qwen's page 7.5 s, News 6.9 s after
-- the v10.24 deploy). A page whose module says it may (News, the entity list and queue, an entity's page) is sent
-- from a row of the previous code while its inputs are the same, until the jobs process builds it again; every other
-- page still needs a row of the current code. A row without a code (built before this) is never the current code's.
--
-- mx_page_opens: how often a kept page's key was opened (one row a page and key, a count and the newest open): the jobs
-- process builds the most opened entity pages after each decision run and after a deploy (entity_views.keep_pages).
-- An operational count, nothing is derived from it.
--
-- mx_jobs' job check: the jobs process's job "entities" (the entity list, the queue's first page, the most opened
-- entity pages: 0216 item 5 and 0232).
-- Idempotent.

ALTER TABLE mx_kept_pages ADD COLUMN IF NOT EXISTS code text;

CREATE TABLE IF NOT EXISTS mx_page_opens (
  page      text NOT NULL,
  key       text NOT NULL,
  opens     bigint NOT NULL DEFAULT 0,
  first_at  timestamptz NOT NULL DEFAULT now(),
  last_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (page, key)
);
CREATE INDEX IF NOT EXISTS mx_page_opens_last_idx ON mx_page_opens (page, last_at DESC);

ALTER TABLE mx_jobs DROP CONSTRAINT IF EXISTS mx_jobs_job_check;
ALTER TABLE mx_jobs ADD CONSTRAINT mx_jobs_job_check CHECK (job IN ('candidates', 'decide', 'plan', 'news', 'tracks',
                                                                    'unread', 'main_source', 'discover', 'official',
                                                                    'stories', 'entities'));
