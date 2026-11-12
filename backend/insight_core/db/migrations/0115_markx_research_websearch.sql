-- 0115_markx_research_websearch.sql (issue 0171, Stealth v10.15: research's web search done by the Mark X worker)
--
-- Research's web search (0162 step 4) is asked of the worker (Claude Code on the owner's device, its web search tool
-- only) as a `websearch` task (guide websearch-v1) when no SearXNG or Brave search is configured. One task a run:
--
-- 1. mx_research_runs.web_task_id: the `websearch` task the run waits on (several runs asking the same question share
--    one task, as the identity pairs do).
-- 2. mx_tasks.subject_kind may be 'research_run' (a = the run that first asked).
--
-- Mark X tables only; nothing is deleted. Idempotent. The CHECK is rebuilt from the values it allows now plus the new
-- one (0081's way), so values another branch's migration added stay.

ALTER TABLE mx_research_runs ADD COLUMN IF NOT EXISTS web_task_id uuid;
CREATE INDEX IF NOT EXISTS mx_research_runs_web_task_idx ON mx_research_runs (web_task_id) WHERE web_task_id IS NOT NULL;

DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('research_run') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['research_run'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
