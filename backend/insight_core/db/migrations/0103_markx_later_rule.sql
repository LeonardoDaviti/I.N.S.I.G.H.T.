-- 0103_markx_later_rule.sql (issue 0163, Stealth v10.13.12: later developments, the tightened rule)
--
-- 1. mx_later.rule: the trigger rule a row was found by. Every row that exists now was found by v10.13.11's loose
--    rule (1); markx/later.py writes RULE (2) explicitly. The default 1 only marks the rows already here.
--    Rows of an older rule are kept as they are (never deleted, their tasks, verdicts and labels too); they are not
--    planned for judging, not counted, and not shown unless asked for (`?all=1`).
-- 2. The unique key becomes (story, post, rule): the tightened rule's re-read of the backfill adds its own row for a
--    (story, post) an old row has, so each row keeps what its own rule found (members, entity, triggers, found_at,
--    its task and verdict) and the owner's labels stay on the rows they were given to.
-- 3. The unasked index carries the rule (plan reads the current rule's unasked rows only).
--
-- Mark X tables only. Idempotent.

ALTER TABLE mx_later ADD COLUMN IF NOT EXISTS rule smallint NOT NULL DEFAULT 1;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_later'::regclass AND conname = 'mx_later_once') THEN
    ALTER TABLE mx_later DROP CONSTRAINT mx_later_once;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_later'::regclass AND conname = 'mx_later_once_a_rule') THEN
    ALTER TABLE mx_later ADD CONSTRAINT mx_later_once_a_rule UNIQUE (story, post, rule);
  END IF;
END $$;

DROP INDEX IF EXISTS mx_later_unasked_idx;
CREATE INDEX IF NOT EXISTS mx_later_unasked_rule_idx ON mx_later (rule, post_at DESC) WHERE task_id IS NULL;
CREATE INDEX IF NOT EXISTS mx_later_story_rule_idx ON mx_later (story, rule, post_at DESC);
