-- 0075_markx_folds.sql (issue 0127, Mark X v10.3: duplicates folded)
--
-- One change: mx_labels.item_kind may be 'fold' (the owner's answer on a member's fold: a = the Mark X story,
-- b = the post). The fold itself is not stored: it is computed from mx_readings (guide read-v3), mx_story_posts and
-- these labels. The new kind `read3` needs no change (mx_tasks.kind is not checked; its subject is a post).
--
-- The CHECK is rebuilt from the values it allows now plus 'fold', so the kinds another branch's migration added
-- (0119 B's perspective, fact) stay, whatever the order the branches merge in. Mark X tables only; idempotent.

DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_labels'::regclass AND c.conname = 'mx_labels_item_kind_check';
  IF def IS NULL OR position('''fold''' IN def) > 0 THEN
    RETURN;
  END IF;
  -- the values as Postgres shows them: ANY (ARRAY['join'::text, ...]); written back as IN (...), shown the same way
  SELECT array_agg(m[1] ORDER BY n) INTO vals
    FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
  vals := vals || ARRAY['fold'];
  ALTER TABLE mx_labels DROP CONSTRAINT mx_labels_item_kind_check;
  EXECUTE format('ALTER TABLE mx_labels ADD CONSTRAINT mx_labels_item_kind_check CHECK (item_kind IN (%s))',
                 (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
END $$;
