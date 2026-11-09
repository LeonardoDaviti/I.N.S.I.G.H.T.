-- 0094_markx_track_finders.sql (issue 0147, Stealth v10.13: track recall, several finders)
--
-- 1. mx_track_probes: a track's example posts (a `probes` task, guide probes-v1, once per track version): `near` the
--    near-misses (they pull a post's score down). Each is embedded (an `embed` task, subject 'track_probe', a = the
--    probe's id): `v` for the text whose sha256 is `text_hash`. A new version's probes leave the old ones (kept;
--    read by version).
-- 2. mx_track_models: the track's small classifier (logistic regression on the post's vector and the finders' features),
--    trained once 30 labels (8 of each) exist and again when 10 new ones arrive: `coef` the features' weights, the
--    bias and the features' scales. A newer model closes the old one with valid_to.
-- 3. mx_track_items.found_by: the finders that put a passive post up for judging (probe, entity, domain, word, source,
--    story, classifier); `score` its probe score (max cosine to the example posts, near-misses subtracted).
-- 4. mx_tasks.subject_kind may be 'track_probe'.
--
-- Mark X tables only; no key to a Mark IX table; nothing is deleted. Idempotent. The CHECK is rebuilt from the values
-- it allows now plus the new one (0081's way), so values another branch's migration added stay.

CREATE TABLE IF NOT EXISTS mx_track_probes (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id   uuid NOT NULL,
  version    integer NOT NULL,
  near       boolean NOT NULL DEFAULT false,
  text       text NOT NULL,
  text_hash  text NOT NULL,
  v          halfvec(1024),
  task_id    uuid,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_track_probes_track_idx ON mx_track_probes (track_id, version);
CREATE INDEX IF NOT EXISTS mx_track_probes_hash_idx ON mx_track_probes (text_hash);

CREATE TABLE IF NOT EXISTS mx_track_models (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id   uuid NOT NULL,
  version    integer NOT NULL,
  labels     integer NOT NULL,
  pos        integer NOT NULL,
  neg        integer NOT NULL,
  coef       jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  valid_to   timestamptz
);
CREATE INDEX IF NOT EXISTS mx_track_models_track_idx ON mx_track_models (track_id) WHERE valid_to IS NULL;

ALTER TABLE mx_track_items ADD COLUMN IF NOT EXISTS found_by text[];
ALTER TABLE mx_track_items ADD COLUMN IF NOT EXISTS score real;

DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('track_probe') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['track_probe'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
