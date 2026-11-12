-- 0107_markx_research.sql (issue 0162, Stealth v10.14: research from a link, a name, an entity, a pasted post or a
-- question: the maker, its channels, its papers and who discusses it)
--
-- 1. mx_research_runs: one research run, only ever started by the owner's tap. `seed_kind` and `seed` what it started
--    from; `entity_id` the entity it resolved to; `scout_run_id` the scout run (0148, trigger 'research') that holds its
--    channels' candidates and test reads; `track_id` the track "Watch this" made; `previous_id` the run it re-ran (its
--    findings already seen are not new). `steps` when each step finished; `page_requests`, `paper_calls`,
--    `search_calls`, `identity_asked` what it spent (the cost guard); `busy_until` the claim of whoever advances it.
-- 2. mx_research_findings: what each step found, one row a (run, section, key): held (in INSIGHT), same_post (the same
--    announcement), entity (names that may be one thing), account (a page of the identity graph: read, its declared
--    links, same identity or not and why), paper, discussion, unread (what could not be read and why). `new`: not seen
--    by an earlier run of the same seed.
-- 3. mx_research_pairs: a same-identity question the plain rules left unclear, asked as an `identity` task (guide
--    identity-v1; subject 'research_pair', a = the pair), its answer copied here.
-- 4. mx_scout_runs.research_id; mx_source_provenance.kind may be 'research'; mx_tasks.subject_kind may be
--    'research_pair'.
--
-- Mark X tables only; no key to a Mark IX table; nothing is deleted. Idempotent. The CHECKs are rebuilt from the values
-- they allow now plus the new one (0081's way), so values another branch's migration added stay.

CREATE TABLE IF NOT EXISTS mx_research_runs (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  seed_kind      text NOT NULL CHECK (seed_kind IN ('post', 'link', 'entity', 'name', 'question')),
  seed           text NOT NULL,
  entity_id      uuid,
  scout_run_id   uuid REFERENCES mx_scout_runs(id),
  track_id       uuid,
  previous_id    uuid REFERENCES mx_research_runs(id),
  status         text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'waiting', 'done', 'failed')),
  steps          jsonb NOT NULL DEFAULT '{}'::jsonb,
  page_requests  integer NOT NULL DEFAULT 0,
  paper_calls    integer NOT NULL DEFAULT 0,
  search_calls   integer NOT NULL DEFAULT 0,
  identity_asked integer NOT NULL DEFAULT 0,
  stats          jsonb NOT NULL DEFAULT '{}'::jsonb,
  busy_until     timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  finished_at    timestamptz
);
CREATE INDEX IF NOT EXISTS mx_research_runs_seed_idx ON mx_research_runs (seed_kind, seed, created_at DESC);
CREATE INDEX IF NOT EXISTS mx_research_runs_entity_idx ON mx_research_runs (entity_id) WHERE entity_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS mx_research_findings (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id     uuid NOT NULL REFERENCES mx_research_runs(id),
  section    text NOT NULL CHECK (section IN ('held', 'same_post', 'entity', 'account', 'paper', 'discussion', 'unread')),
  key        text NOT NULL,
  data       jsonb NOT NULL DEFAULT '{}'::jsonb,
  new        boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mx_research_findings_once UNIQUE (run_id, section, key)
);

CREATE TABLE IF NOT EXISTS mx_research_pairs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id      uuid NOT NULL REFERENCES mx_research_runs(id),
  a           text NOT NULL,
  b           text NOT NULL,
  how         text,
  task_id     uuid,
  same        text CHECK (same IN ('yes', 'no', 'unsure')),
  confidence  real,
  why         text,
  created_at  timestamptz NOT NULL DEFAULT now(),
  answered_at timestamptz,
  CONSTRAINT mx_research_pairs_once UNIQUE (run_id, a, b)
);
CREATE INDEX IF NOT EXISTS mx_research_pairs_task_idx ON mx_research_pairs (task_id) WHERE task_id IS NOT NULL;

ALTER TABLE mx_scout_runs ADD COLUMN IF NOT EXISTS research_id uuid;

ALTER TABLE mx_source_provenance DROP CONSTRAINT IF EXISTS mx_source_provenance_kind_check;
ALTER TABLE mx_source_provenance ADD CONSTRAINT mx_source_provenance_kind_check CHECK (kind IN ('scout', 'research'));

DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('research_pair') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['research_pair'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
