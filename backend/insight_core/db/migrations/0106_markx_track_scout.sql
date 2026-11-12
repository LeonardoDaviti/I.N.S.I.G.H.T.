-- 0106_markx_track_scout.sql (issue 0148, Stealth v10.14: a track finds sources in a sphere INSIGHT doesn't read yet)
--
-- (0105 is another branch's; renumber at merge if another lands first: nothing depends on the number.)
--
-- 1. mx_scout_runs: one scout of one track (trigger 'tap': the owner's "Find sources for this track"; 'weekly': a
--    track with fewer than 5 items in or ✓ in 7 days, at most once a week). `scout_task_id` its one `scout` question
--    (guide scout-v1); `requests`, `reads` and `judgements` what it spent (the cost guard); `busy_until` the claim of
--    whoever advances it (the API's background task after a tap, or insight-ingestion's hook), so two never read at once.
-- 2. mx_scout_candidates: a source the scout may suggest, from one of three finders ('match': the track's matches'
--    links and quoted accounts; 'shape': a platform class's address built from the track's words, a search feed among
--    them; 'haiku': the scout question's answer). `key` is Discover's address key (one row a run and key). After its
--    test read: `resolved` how the add path would follow it ({platform, handle_or_url, settings, via: kind | feed |
--    page}), `reason` why it can't be read (or can't be read well), `health` what the read found. The owner's answer
--    (`answer`: active | passive | not) and the source it became (`source_id`).
-- 3. mx_scout_items: the scratch area. Up to 20 newest items of a candidate as its test read found them: never a post,
--    never in a feed, nothing followed. `task_id` the track judge's question on it (a `track` task of subject
--    'scout_item'), its verdict copied here when answered.
-- 4. mx_source_provenance: where a followed source came from (the scout run and candidate, the track), so its later
--    precision is shown. Never deleted.
-- 5. mx_tasks.subject_kind may be 'scout_item'.
--
-- Mark X tables only; no key to a Mark IX table; nothing is deleted. Idempotent. The CHECK is rebuilt from the values
-- it allows now plus the new one (0081's way), so values another branch's migration added stay.

CREATE TABLE IF NOT EXISTS mx_scout_runs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id      uuid,
  version       integer,
  trigger       text NOT NULL CHECK (trigger IN ('tap', 'weekly', 'research')),
  status        text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'waiting', 'done', 'failed')),
  scout_task_id uuid,
  busy_until    timestamptz,
  requests      integer NOT NULL DEFAULT 0,
  reads         integer NOT NULL DEFAULT 0,
  judgements    integer NOT NULL DEFAULT 0,
  stats         jsonb NOT NULL DEFAULT '{}'::jsonb,
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz
);
CREATE INDEX IF NOT EXISTS mx_scout_runs_track_idx ON mx_scout_runs (track_id, started_at DESC);
CREATE INDEX IF NOT EXISTS mx_scout_runs_task_idx ON mx_scout_runs (scout_task_id) WHERE scout_task_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS mx_scout_candidates (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id      uuid NOT NULL REFERENCES mx_scout_runs(id),
  finder      text NOT NULL,
  platform    text NOT NULL,
  address     text NOT NULL,
  key         text NOT NULL,
  name        text,
  why         text,
  evidence    jsonb NOT NULL DEFAULT '{}'::jsonb,
  rank        integer NOT NULL DEFAULT 0,
  state       text NOT NULL DEFAULT 'new' CHECK (state IN ('new', 'read', 'unreadable', 'skipped')),
  resolved    jsonb,
  reason      text,
  health      jsonb,
  requests    integer NOT NULL DEFAULT 0,
  read_at     timestamptz,
  answer      text CHECK (answer IN ('active', 'passive', 'not')),
  answered_at timestamptz,
  source_id   uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mx_scout_candidates_once UNIQUE (run_id, key)
);
CREATE INDEX IF NOT EXISTS mx_scout_candidates_key_idx ON mx_scout_candidates (key);

CREATE TABLE IF NOT EXISTS mx_scout_items (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  candidate_id uuid NOT NULL REFERENCES mx_scout_candidates(id),
  url          text NOT NULL,
  title        text,
  text         text,
  published_at timestamptz,
  lang         text,
  chars        integer NOT NULL DEFAULT 0,
  transcript   boolean,
  task_id      uuid,
  verdict      boolean,
  confidence   real,
  why          text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mx_scout_items_once UNIQUE (candidate_id, url)
);
CREATE INDEX IF NOT EXISTS mx_scout_items_task_idx ON mx_scout_items (task_id) WHERE task_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS mx_source_provenance (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id    uuid NOT NULL,
  kind         text NOT NULL CHECK (kind IN ('scout')),
  run_id       uuid,
  candidate_id uuid,
  track_id     uuid,
  as_active    boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_source_provenance_source_idx ON mx_source_provenance (source_id);
CREATE INDEX IF NOT EXISTS mx_source_provenance_track_idx ON mx_source_provenance (track_id);

DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('scout_item') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['scout_item'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
