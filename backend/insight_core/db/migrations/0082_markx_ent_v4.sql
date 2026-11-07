-- 0082_markx_ent_v4.sql (issue 0133, Stealth v10.7: ent-v4, documents and cited sources as entities)
--
-- 1. mx_mentions.rule: 'citation' for a mention the citation rule found (markx/citations.py: an in-text citation, an
--    arXiv id, a DOI, a link to a document), alone or merged with the model's mention of the same thing; null for
--    the model's alone. mx_mentions.by_name: the publisher or author an ent-v4 document names ("by"), as written.
--    mx_mentions.ref: the identifier the rule read for it ("arXiv:<id>", "doi:<doi>", "page:<address>"), so identity
--    joins the same document across posts whatever name each gives it.
-- 2. mx_mention_sets: which guide's mentions are a post's current set (one row a post): the newest valid entities
--    answer's. Written with the mentions (markx/repo.add_mentions); a new guide's answer moves the row, nothing in
--    mx_mentions is rewritten (keep everything: ent-v3's rows stay stored). Filled here from the stored ent-v3 sets.
-- 3. mx_mentions_now: the current mentions (mx_mentions joined to mx_mention_sets): what every reader reads.
-- 4. mx_connections.a_kind and b_kind may be 'entity': a document's publisher as a `published` edge between two
--    entities (rule 'mention_by'), 0131's edge storage.
--
-- Mark X tables only; nothing is deleted. Idempotent. The CHECKs are rebuilt from the values they allow now plus the
-- new one (0081's way), so values another branch's migration added stay.

ALTER TABLE mx_mentions ADD COLUMN IF NOT EXISTS rule text;
ALTER TABLE mx_mentions ADD COLUMN IF NOT EXISTS by_name text;
ALTER TABLE mx_mentions ADD COLUMN IF NOT EXISTS ref text;

CREATE TABLE IF NOT EXISTS mx_mention_sets (
  post_id    uuid PRIMARY KEY,
  guide      text NOT NULL REFERENCES mx_guides(id),
  call_id    uuid NOT NULL REFERENCES mx_calls(id),
  at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_mention_sets_guide_idx ON mx_mention_sets (guide);

INSERT INTO mx_mention_sets (post_id, guide, call_id, at)
SELECT DISTINCT ON (m.post_id) m.post_id, m.guide, m.call_id, c.created_at
  FROM mx_mentions m JOIN mx_calls c ON c.id = m.call_id
 ORDER BY m.post_id, c.created_at DESC, m.guide DESC
ON CONFLICT (post_id) DO NOTHING;

CREATE OR REPLACE VIEW mx_mentions_now AS
SELECT m.* FROM mx_mentions m JOIN mx_mention_sets s ON s.post_id = m.post_id AND s.guide = m.guide;

DO $$
DECLARE
  item record;
  def  text;
  vals text[];
BEGIN
  FOR item IN SELECT * FROM (VALUES ('mx_connections', 'mx_connections_a_kind_check', 'a_kind', 'entity'),
                                    ('mx_connections', 'mx_connections_b_kind_check', 'b_kind', 'entity')) AS t(tbl, con, col, val)
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
