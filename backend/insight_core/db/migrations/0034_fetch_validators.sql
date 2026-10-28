-- 0034_fetch_validators.sql (issue 0044)
--
-- Conditional fetching: what each address a source's fetch reads (its feed; a page-watch
-- listing page and its sitemap files) last said identifies its answer, sent back next time so
-- an unchanged address answers 304 with no body. One row per (source, address): a page-watch
-- source reads several. etag / last_modified are the headers verbatim; learned_at is when a
-- full answer gave them (a 304 keeps it), so validators older than a week are not sent.
-- A fetch's rows are replaced only after its posts are saved. Numbered 0034: unmerged
-- branches hold 0035-0037. Idempotent.

CREATE TABLE IF NOT EXISTS source_fetch_validators (
  source_id     UUID NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  url           TEXT NOT NULL,
  etag          TEXT NULL,
  last_modified TEXT NULL,
  learned_at    TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (source_id, url)
);
