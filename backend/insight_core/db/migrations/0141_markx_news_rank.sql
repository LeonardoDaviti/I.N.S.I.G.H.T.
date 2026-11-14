-- 0141_markx_news_rank.sql (Stealth v10.19, issue 0208: News ranked for the reader)
--
-- 1. mx_news_significance_asks: one significance question as it was asked about a News row: its task (kind
--    `significance`, guide significance-v1), the row (`row_id`: its first post, the id mx_news gives it), the row's
--    posts when asked (`members`: a row is asked again only when they change) and when. The answer is the task's
--    valid call (mx_calls); the newest answered ask of a row is its significance.
-- 2. mx_news_rank: each News row's place as the jobs process last ranked it (markx/news_rank.keep): its significance,
--    its fit with the reader, its coverage, the score they make, whether it is in the "Notable for you" lane, what
--    decided them (`why`), the written run it was ranked over and when. One row a News row (a cache of a derived
--    order: replaced when ranked again, never read as history; the inputs it is made of are all kept).
-- Mark X tables only; no key to a Mark IX table. Idempotent.

CREATE TABLE IF NOT EXISTS mx_news_significance_asks (
  task_id   uuid PRIMARY KEY REFERENCES mx_tasks(id),
  row_id    uuid NOT NULL,
  members   uuid[] NOT NULL,
  asked_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_news_significance_asks_row_idx ON mx_news_significance_asks (row_id, asked_at DESC);

CREATE TABLE IF NOT EXISTS mx_news_rank (
  row_id        uuid PRIMARY KEY,
  run_id        uuid NOT NULL REFERENCES mx_runs(id),
  significance  real,
  fit           real NOT NULL DEFAULT 0,
  coverage      real NOT NULL DEFAULT 0,
  score         real NOT NULL,
  notable       boolean NOT NULL DEFAULT false,
  why           jsonb NOT NULL DEFAULT '{}'::jsonb,
  ranked_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_news_rank_run_idx ON mx_news_rank (run_id);
