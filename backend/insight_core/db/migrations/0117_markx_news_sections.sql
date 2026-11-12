-- 0117_markx_news_sections.sql (issue 0174, Stealth v10.16: Mark X News in sections, titled by Haiku)
--
-- 1. mx_news_section_asks: one `news_sections` question (guide news-sections-v1) as it was asked: its task, the News
--    run whose rows it shows, those rows' ids in the question's order (key r1 is row_ids[0], r2 row_ids[1], ...: the input
--    names rows by key, never by id), the titles it showed as last time's, and when. The answer's keys are read back
--    through `row_ids`.
-- 2. mx_news_sections: one section of one valid answer: its title, its rows (News row ids, in News' order), its place
--    on the page (`position`: 0 first, by the section's most important row) and when it was stored. The page reads the
--    newest answer's sections; nothing is replaced (keep everything: every sectioning stays as rows).
-- 3. mx_tasks.subject_kind may be 'news_run' (a = the mx_runs id of the News run the question shows).
--
-- Mark X tables only; no key to a Mark IX table; nothing is deleted. Idempotent. The CHECK is rebuilt from the values
-- it allows now plus the new one (0081's way), so values another branch's migration added stay.

CREATE TABLE IF NOT EXISTS mx_news_section_asks (
  task_id   uuid PRIMARY KEY REFERENCES mx_tasks(id),
  run_id    uuid NOT NULL REFERENCES mx_runs(id),
  row_ids   jsonb NOT NULL,
  titles    jsonb NOT NULL DEFAULT '[]'::jsonb,
  asked_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_news_section_asks_at_idx ON mx_news_section_asks (asked_at DESC);

CREATE TABLE IF NOT EXISTS mx_news_sections (
  task_id   uuid NOT NULL REFERENCES mx_tasks(id),
  call_id   uuid NOT NULL REFERENCES mx_calls(id),
  run_id    uuid NOT NULL REFERENCES mx_runs(id),
  position  integer NOT NULL,
  title     text NOT NULL,
  row_ids   uuid[] NOT NULL,
  at        timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (call_id, position)
);
CREATE INDEX IF NOT EXISTS mx_news_sections_at_idx ON mx_news_sections (at DESC);

DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('news_run') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['news_run'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
