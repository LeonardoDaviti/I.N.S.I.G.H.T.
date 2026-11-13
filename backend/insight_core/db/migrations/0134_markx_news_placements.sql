-- 0134_markx_news_placements.sql (Stealth v10.17, issue 0197: new News rows placed into the existing sections)
--
-- Between two full sectionings (0174: asked again only when 20% of the rows changed, at most every 30 minutes) the rows
-- added since sat under "New since" for hours. One small `news_place` question (guide news-place-v1) places them:
-- 1. mx_news_place_asks: one placement question as it was asked: its task, the News run it read, the sectioning it
--    places into (`base_call`: the mx_news_sections answer's call), the new rows' ids in key order (r1 is row_ids[0])
--    and the sections' titles in key order (s1 is titles[0]), and when. The answer's keys are read back through them.
-- 2. mx_news_placements: one row of one valid answer: the sectioning it was placed into, its section's title, or NULL
--    when the answer was "new" (no section fits: it stays under "New since" until the next full sectioning).
-- The page reads the newest sectioning plus the placements into it; a newer full sectioning supersedes them (its
-- `base_call` differs). Mark X tables only; no key to a Mark IX table; nothing is deleted. Idempotent.

CREATE TABLE IF NOT EXISTS mx_news_place_asks (
  task_id    uuid PRIMARY KEY REFERENCES mx_tasks(id),
  run_id     uuid NOT NULL REFERENCES mx_runs(id),
  base_call  uuid NOT NULL REFERENCES mx_calls(id),
  row_ids    jsonb NOT NULL,
  titles     jsonb NOT NULL,
  asked_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_news_place_asks_at_idx ON mx_news_place_asks (asked_at DESC);

CREATE TABLE IF NOT EXISTS mx_news_placements (
  task_id    uuid NOT NULL REFERENCES mx_tasks(id),
  call_id    uuid NOT NULL REFERENCES mx_calls(id),
  base_call  uuid NOT NULL REFERENCES mx_calls(id),
  row_id     uuid NOT NULL,
  title      text,
  at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (call_id, row_id)
);
CREATE INDEX IF NOT EXISTS mx_news_placements_base_idx ON mx_news_placements (base_call, at DESC);
