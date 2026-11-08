-- 0085_markx_back.sql (issue 0136, Stealth v10.8: back in the news, in Shadow)
--
-- 1. mx_back: an old Mark IX story's candidate return (markx/back.py's trigger, no model): the story (its id, which
--    is its root post's), the members it had when asked, its first and last post, the 72-hour window's start, the
--    triggers that fired in it (E: its subject entity; L: one of its pages; V: similarity, only without E or L), the
--    new posts as the question numbers them (at most 6) with each one's triggers, and the `back` task asking it.
--    One row per story and window (a story fires once, as the lab's did: its earliest burst). Kept, never deleted.
-- 2. mx_labels.item_kind may be 'back' (the owner's label on a row: a = the mx_back row; answer development,
--    retold, related, unrelated or undo).
--
-- Mark X tables only; no key to a Mark IX table. Idempotent. The CHECK is rebuilt from the values it allows now plus
-- the new one (0081's way), so values another branch's migration added stay.

CREATE TABLE IF NOT EXISTS mx_back (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  story      uuid NOT NULL,
  members    uuid[] NOT NULL,
  first_at   timestamptz NOT NULL,
  last_at    timestamptz NOT NULL,
  window_at  timestamptz NOT NULL,
  trig       text[] NOT NULL,
  posts      uuid[] NOT NULL,
  post_trig  jsonb NOT NULL DEFAULT '{}'::jsonb,
  task_id    uuid REFERENCES mx_tasks(id),
  run_id     uuid,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mx_back_once UNIQUE (story, window_at)
);
CREATE INDEX IF NOT EXISTS mx_back_window_idx ON mx_back (window_at);
CREATE INDEX IF NOT EXISTS mx_back_task_idx ON mx_back (task_id) WHERE task_id IS NOT NULL;

DO $$
DECLARE
  item record;
  def  text;
  vals text[];
BEGIN
  FOR item IN SELECT * FROM (VALUES ('mx_labels', 'mx_labels_item_kind_check', 'item_kind', 'back')) AS t(tbl, con, col, val)
  LOOP
    SELECT pg_get_constraintdef(c.oid) INTO def
      FROM pg_constraint c
     WHERE c.conrelid = item.tbl::regclass AND c.conname = item.con;
    IF def IS NULL OR position(quote_literal(item.val) IN def) > 0 THEN
      CONTINUE;
    END IF;
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY[item.val];
    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', item.tbl, item.con);
    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK (%I IN (%s))', item.tbl, item.con, item.col,
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END LOOP;
END $$;
