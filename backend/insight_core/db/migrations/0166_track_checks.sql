-- 0166_track_checks.sql (Stealth v10.29, issue 0256: posts from any source join a track by a blind check)
--
-- A post from a source outside the track that the judge put `in` is asked once more, blind, under the `track` kind's
-- second guide track-check-v1 (tracks.plan's check phase). The item row names that task and keeps its answer: in,
-- confidence, why, when. tracks.placed joins the post into the track when the check says in at
-- tracks.CHECK_JOIN or more (measured: 0256). An update of the row marks the track changed (0133's triggers), so the
-- kept placement follows. Mark X tables only; nothing deleted. Idempotent.

ALTER TABLE mx_track_items ADD COLUMN IF NOT EXISTS check_task_id uuid;
ALTER TABLE mx_track_items ADD COLUMN IF NOT EXISTS check_in boolean;
ALTER TABLE mx_track_items ADD COLUMN IF NOT EXISTS check_confidence real;
ALTER TABLE mx_track_items ADD COLUMN IF NOT EXISTS check_why text;
ALTER TABLE mx_track_items ADD COLUMN IF NOT EXISTS checked_at timestamptz;
CREATE INDEX IF NOT EXISTS mx_track_items_check_task_idx ON mx_track_items (check_task_id) WHERE check_task_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS mx_track_items_unchecked_idx ON mx_track_items (track_id, answered_at DESC)
  WHERE verdict AND check_task_id IS NULL;

-- The check's tasks name their subject (tracks.CHECK_SUBJECT): the subject kinds' list gains it.
DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('post_track_check') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['post_track_check'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
