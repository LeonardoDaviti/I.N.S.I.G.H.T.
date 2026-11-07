-- 0081_source_stats.sql (issue 0132 B, Stealth v10.6: the source analysis page)
--
-- 1. source_stats: every card's signal for a source or a voice, as the stats job (markx/source_stats.py, in
--    insight-ingestion's runner, nightly and after a regroup) computed it: its value (a number, a text or an object),
--    how many it counted (n: posts, read posts, stories, labels, videos), its evidence (posts, stories, voices, the
--    rule's line) and when. The page reads these rows and never computes. One row per subject and signal: a new run
--    writes over the last one (the numbers are made again from the rows they count; nothing they count is touched).
--    A voice's rows (subject_kind 'voice') exist only once the voices table does (0132 A).
-- 2. mx_tasks.subject_kind may be 'source' (the stance question: a = the source).
-- 3. mx_labels.item_kind may be 'stance' (the owner's right / wrong on a stance pattern: a = the stance task,
--    b = the source, note = "pattern <n>").
--
-- Both CHECKs are rebuilt from the values they allow now plus the new one, so the values another branch's migration
-- added stay, whatever the order the branches merge in (0078's way). Idempotent.

CREATE TABLE IF NOT EXISTS source_stats (
  subject_kind text NOT NULL CHECK (subject_kind IN ('source', 'voice')),
  subject_id   uuid NOT NULL,
  signal       text NOT NULL,
  value        jsonb,
  n            integer NOT NULL DEFAULT 0,
  evidence     jsonb NOT NULL DEFAULT '{}'::jsonb,
  computed_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (subject_kind, subject_id, signal)
);
CREATE INDEX IF NOT EXISTS source_stats_signal_idx ON source_stats (signal, subject_kind);

DO $$
DECLARE
  item record;
  def  text;
  vals text[];
BEGIN
  FOR item IN SELECT * FROM (VALUES ('mx_tasks', 'mx_tasks_subject_kind_check', 'subject_kind', 'source'),
                                    ('mx_labels', 'mx_labels_item_kind_check', 'item_kind', 'stance')) AS t(tbl, con, col, val)
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
