-- 0102_markx_later.sql (issue 0163, Stealth v10.13.11: later developments, in Shadow)
--
-- 1. mx_later: a later post of a long-lived Mark IX story (a story whose subject is a paper, a document, a model,
--    software or a dataset; markx/later.py's trigger, no model): the story (its id, its root post's), the new post,
--    the members the story had when found (the judge's question shows the earliest 4), the subject entity it was
--    found for, the triggers (E: the post's own subject is the story's subject, the same version or a later one of
--    its family; L: it links one of the story's own pages or an address of its subject), the post's and the story's
--    last post's dates, the `back` task asking it and, once answered three times, its verdict and the runs. One row a
--    (story, post); kept, never deleted.
-- 2. mx_later_stops: the owner's "Stop following this story" and "Follow again", one row each time (the latest row of
--    a story says whether it is stopped). Kept, never deleted.
-- 3. mx_labels.item_kind may be 'later' (the owner's label on a row: a = the mx_later row; answer development,
--    retold, related, unrelated or undo).
--
-- Mark X tables only; no key to a Mark IX table, nor to mx_tasks (the test suites truncate mx_tasks alone). Idempotent.

CREATE TABLE IF NOT EXISTS mx_later (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  story      uuid NOT NULL,
  post       uuid NOT NULL,
  members    uuid[] NOT NULL,
  entity     uuid,
  trig       text[] NOT NULL,
  post_at    timestamptz NOT NULL,
  last_at    timestamptz NOT NULL,
  task_id    uuid,
  verdict    text,
  runs       text[],
  judged_at  timestamptz,
  run_id     uuid,
  found_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mx_later_once UNIQUE (story, post)
);
CREATE INDEX IF NOT EXISTS mx_later_story_idx ON mx_later (story, post_at DESC);
CREATE INDEX IF NOT EXISTS mx_later_entity_idx ON mx_later (entity) WHERE entity IS NOT NULL;
CREATE INDEX IF NOT EXISTS mx_later_unasked_idx ON mx_later (post_at DESC) WHERE task_id IS NULL;
CREATE INDEX IF NOT EXISTS mx_later_unjudged_idx ON mx_later (task_id) WHERE task_id IS NOT NULL AND verdict IS NULL;

CREATE TABLE IF NOT EXISTS mx_later_stops (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  story      uuid NOT NULL,
  stopped    boolean NOT NULL,
  note       text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_later_stops_story_idx ON mx_later_stops (story, created_at DESC);

DO $$
DECLARE
  item record;
  def  text;
  vals text[];
BEGIN
  FOR item IN SELECT * FROM (VALUES ('mx_labels', 'mx_labels_item_kind_check', 'item_kind', 'later')) AS t(tbl, con, col, val)
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
