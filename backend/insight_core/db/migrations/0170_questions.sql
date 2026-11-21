-- 0170_questions.sql (Stealth v10.33, issue 0275: questions with citations)
--
-- A question the reader asked on the search page (markx/questions.py): its words, the `question` task asking Haiku
-- (none when nothing was found to answer from) and the posts that task shows, numbered [1]..[n] in this order (an
-- answer's cites are read back through them). Kept, never deleted. Mark X tables only. Idempotent.

CREATE TABLE IF NOT EXISTS mx_questions (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    q           text NOT NULL,
    task_id     uuid REFERENCES mx_tasks (id),
    post_ids    uuid[] NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS mx_questions_task_idx ON mx_questions (task_id);
-- A question's task names its subject: 'question' (a = the mx_questions row): the subject kinds' list gains it.
DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('question') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['question'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
