-- 0087_markx_ent_v42.sql (issue 0133 v4.2, Stealth v10.9: ent-v4.2 in Shadow, measured by the owner's labels)
--
-- mx_labels.item_kind may be 'mention': the owner's right / wrong on one new entity of a post (a document, a
-- `source`, a `recommended`, or one ent-v4.2's second question added): a = the post, b = the call the mention came
-- from, note = '<guide>:<n>' (the mention's key); the newest row counts (markx/ent42.py).
--
-- The second question's entities are marked in mx_mentions.rule ('q2'), a column 0082 added: no column here.
-- Mark X tables only; nothing is deleted. Idempotent. The CHECK is rebuilt from the values it allows now plus the
-- new one (0081's way), so values another branch's migration added stay.

DO $$
DECLARE
  item record;
  def  text;
  vals text[];
BEGIN
  FOR item IN SELECT * FROM (VALUES ('mx_labels', 'mx_labels_item_kind_check', 'item_kind', 'mention')) AS t(tbl, con, col, val)
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
