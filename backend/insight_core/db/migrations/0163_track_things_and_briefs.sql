-- 0163_track_things_and_briefs.sql (Stealth v10.27, issue 0245: the general track briefer; built: 0249)
--
-- A track's things: the kinds of thing its description is about (a schema per track, versioned), the things its posts
-- describe (one row a thing, however many posts report it), each post's report of a thing (its values, each with the
-- quote it came from), and what a brief question showed. markx/track_things.py and markx/track_brief.py own them.
-- Behind entity_bands.json `tracks.briefs` (default off): while off nothing writes these tables.
--
-- 1. mx_track_schemas: a track's kinds and fields, one row a version (keep everything: an older version stays).
--    `by` haiku (a track_schema answer, task_id) or owner (an edit through the API); `track_version` is the track's
--    description version it was made for: a description change proposes again (a new version).
-- 2. mx_track_things: one thing of one kind in one track: its key (the normalised key field it was first found by), its
--    merged fields ({field: {value, post}}: the newest report's value of each field), the post dates of its first and
--    last reports, and its status: current, or merged into another thing (`merged_into`, `merged_by` key | entity |
--    haiku): a join is a status, never a delete.
-- 3. mx_track_thing_reports: one thing as one answer (a window of a post) gave it: the call, the post, the schema
--    version and window, its values (field_values: each {value, quote}; numbers typed {number, unit, currency, range_to}). One row
--    a call and entry (`n`, its place in the answer).
-- 4. mx_track_brief_asks: what a brief question (kind `digest`, guide digest-v2) showed: the track, the week (its
--    Monday), the things in the order of its rows ([1]..[n] map back through `thing_ids`).
-- 5. mx_tasks.subject_kind may be 'thing_thing' (track_same: a and b are two practices of a track).
--
-- Mark X tables only; no key to a Mark IX table; nothing is deleted. Idempotent. The CHECK is rebuilt from the values
-- it allows now plus the new one (0081's way), so values another branch's migration added stay.

CREATE TABLE IF NOT EXISTS mx_track_schemas (
  track_id      uuid NOT NULL,
  version       integer NOT NULL,
  schema        jsonb NOT NULL,
  by            text NOT NULL CHECK (by IN ('haiku', 'owner')),
  track_version integer NOT NULL,
  task_id       uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (track_id, version)
);

CREATE TABLE IF NOT EXISTS mx_track_things (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id       uuid NOT NULL,
  kind           text NOT NULL,
  key            text NOT NULL,
  fields         jsonb NOT NULL DEFAULT '{}'::jsonb,
  schema_version integer NOT NULL,
  first_at       timestamptz,
  last_at        timestamptz,
  status         text NOT NULL DEFAULT 'current' CHECK (status IN ('current', 'merged')),
  merged_into    uuid,
  merged_by      text CHECK (merged_by IS NULL OR merged_by IN ('key', 'entity', 'haiku')),
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_track_things_track_idx ON mx_track_things (track_id, status, kind);

CREATE TABLE IF NOT EXISTS mx_track_thing_reports (
  call_id        uuid NOT NULL,
  n              integer NOT NULL,
  thing_id       uuid NOT NULL,
  post_id        uuid NOT NULL,
  task_id        uuid NOT NULL,
  schema_version integer NOT NULL,
  win            integer NOT NULL DEFAULT 0,
  field_values   jsonb NOT NULL,
  created_at     timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (call_id, n)
);
CREATE INDEX IF NOT EXISTS mx_track_thing_reports_thing_idx ON mx_track_thing_reports (thing_id);
CREATE INDEX IF NOT EXISTS mx_track_thing_reports_post_idx ON mx_track_thing_reports (post_id);

CREATE TABLE IF NOT EXISTS mx_track_brief_asks (
  task_id    uuid PRIMARY KEY,
  track_id   uuid NOT NULL,
  week       date NOT NULL,
  thing_ids  uuid[] NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_track_brief_asks_track_idx ON mx_track_brief_asks (track_id, week, created_at DESC);

DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('thing_thing') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['thing_thing'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
