-- 0116_markx_source_judge.sql (issue 0173, Stealth v10.15: "Is this worth it?", a candidate source judged on the owner's tap)
--
-- (0114 is v1015-voices'; renumber at merge if another lands first: nothing depends on the number.)
--
-- 1. mx_source_judgements: one judgement of one candidate source (an address Discover suggests, or the Add source
--    dialog found), asked by the owner's tap only. `key` is Discover's address key (scout.key_of), the cache's key: a
--    judgement is shown again for 30 days, and asking again re-asks only when the test read finds new items
--    (`items_sig`, the read items' addresses). `items` the up to 10 newest items its test read found (the scratch
--    area: never a post, never in a feed, nothing followed), each with its id in the question ("i1".."i10");
--    `signals` what INSIGHT measured (links, stories, rate, how it reads, repeats); `task_id` the `source_judge`
--    question (guide source-judge-v1), its answer copied here (`answer`, `verdict`). `busy_until` the claim of the
--    background read.
-- 2. mx_tasks.subject_kind may be 'source_candidate' (a = the judgement that first asked).
--
-- Mark X tables only; no key to a Mark IX table; nothing is deleted (a judgement asked again is a new row). Idempotent.
-- The CHECK is rebuilt from the values it allows now plus the new one (0081's way), so values another branch's
-- migration added stay.

CREATE TABLE IF NOT EXISTS mx_source_judgements (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key         text NOT NULL,
  address     text NOT NULL,
  status      text NOT NULL DEFAULT 'reading' CHECK (status IN ('reading', 'asked', 'answered', 'unreadable', 'failed')),
  resolved    jsonb,
  reason      text,
  items       jsonb NOT NULL DEFAULT '[]'::jsonb,
  items_sig   text,
  signals     jsonb NOT NULL DEFAULT '{}'::jsonb,
  task_id     uuid,
  answer      jsonb,
  verdict     text CHECK (verdict IN ('follow', 'maybe', 'skip')),
  same_as     uuid,
  requests    integer NOT NULL DEFAULT 0,
  busy_until  timestamptz,
  asked_at    timestamptz NOT NULL DEFAULT now(),
  read_at     timestamptz,
  answered_at timestamptz
);
CREATE INDEX IF NOT EXISTS mx_source_judgements_key_idx ON mx_source_judgements (key, asked_at DESC);
CREATE INDEX IF NOT EXISTS mx_source_judgements_task_idx ON mx_source_judgements (task_id) WHERE task_id IS NOT NULL;

DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('source_candidate') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['source_candidate'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
