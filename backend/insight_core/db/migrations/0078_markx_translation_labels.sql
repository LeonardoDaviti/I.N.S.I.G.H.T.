-- 0078_markx_translation_labels.sql (issue 0130 D, Stealth v10.5: translation)
--
-- One change: mx_labels.item_kind may be 'translation' (the owner's ✓ / ✗ on a post's translation: a = the translate
-- task, b = the post; answer right | wrong | undo). The translation itself is the task's valid call (mx_calls.answer);
-- nothing else is stored. The kind `translate` needs no change (mx_tasks.kind is not checked; its subject is a post).
--
-- The CHECK is rebuilt from the values it allows now plus 'translation', so the kinds another branch's migration added
-- stay, whatever the order the branches merge in (0075's way). Mark X tables only; idempotent.

DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_labels'::regclass AND c.conname = 'mx_labels_item_kind_check';
  IF def IS NULL OR position('''translation''' IN def) > 0 THEN
    RETURN;
  END IF;
  -- the values as Postgres shows them: ANY (ARRAY['join'::text, ...]); written back as IN (...), shown the same way
  SELECT array_agg(m[1] ORDER BY n) INTO vals
    FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
  vals := vals || ARRAY['translation'];
  ALTER TABLE mx_labels DROP CONSTRAINT mx_labels_item_kind_check;
  EXECUTE format('ALTER TABLE mx_labels ADD CONSTRAINT mx_labels_item_kind_check CHECK (item_kind IN (%s))',
                 (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
END $$;
