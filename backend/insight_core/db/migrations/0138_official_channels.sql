-- 0138 (issue 0196, Stealth v10.18): Official channels (markx/official.py owns them) and the per-source item filter
-- (utils/item_filter.py owns it).
--
-- 1. mx_official_channels: an actor's channel as the module decided it: candidate, proven, would_add, added, undone,
--    refused, covered (state), with why, the evidence (where the candidate came from, ownership, the finder's or the
--    first read's answer, holds), the judgement (0173) and the filter it carries, the source it became, the events
--    (Mark X stories) it serves. One current row a channel key; a new state is a new row (the old one superseded,
--    keep everything).
-- 2. mx_official_lookups: one web-search question an actor-thing pair (kind websearch, guide websearch-official-v1),
--    its answer kept and reused.
-- 3. mx_official_runs: each pass of the job: its counts (keep everything; the log of what the job did).
-- 4. source_filters: a source's item filter (a rule the worker proposed when the channel was added, or the owner's);
--    the current row is the one not superseded. posts.filtered_by: the filter row that hid the post (stored as any
--    post, never deleted; the feeds, unread counts and Mark X's planners skip it).
-- 5. story_originals.kind may be `cited` (a page 2+ voices link, saved by the originals step).
-- No foreign keys: the rows name sources, entities, tasks and judgements by id only (a test or a repair that empties
-- those tables is never blocked by these; a reader joins). Idempotent.

CREATE TABLE IF NOT EXISTS source_filters (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id     uuid NOT NULL,
  rule          jsonb NOT NULL,
  by            text NOT NULL CHECK (by IN ('worker', 'owner')),
  guide         text,
  task_id       uuid,
  created_at    timestamptz NOT NULL DEFAULT now(),
  superseded_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS source_filters_current_idx ON source_filters (source_id) WHERE superseded_at IS NULL;

ALTER TABLE posts ADD COLUMN IF NOT EXISTS filtered_by uuid;
CREATE INDEX IF NOT EXISTS posts_filtered_idx ON posts (source_id) WHERE filtered_by IS NOT NULL;

CREATE TABLE IF NOT EXISTS mx_official_channels (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  key           text NOT NULL,                     -- x.com/<user>, t.me/<channel>, <site><prefix>, github.com/<o>/<r>
  kind          text NOT NULL CHECK (kind IN ('x', 'telegram', 'youtube', 'section', 'releases')),
  actor_id      uuid,
  actor_name    text,
  follow        text,                              -- what the add follows (the finder's feed, or the watched page)
  page_watch    jsonb,                             -- {prefix} when page watching follows it
  state         text NOT NULL CHECK (state IN ('candidate', 'proven', 'would_add', 'added', 'undone', 'refused',
                                                 'covered')),
  why           text,
  evidence      jsonb NOT NULL DEFAULT '{}',
  judge_id      uuid,
  rule          jsonb,                             -- the item filter the judgement proposed (applied when added)
  filter_id     uuid,
  source_id     uuid,
  events        text[] NOT NULL DEFAULT '{}',      -- the Mark X stories it serves
  created_at    timestamptz NOT NULL DEFAULT now(),
  decided_at    timestamptz,
  superseded_at timestamptz,
  superseded_by uuid
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_official_channels_current_idx ON mx_official_channels (key) WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS mx_official_channels_actor_idx ON mx_official_channels (actor_id) WHERE superseded_at IS NULL;
CREATE INDEX IF NOT EXISTS mx_official_channels_added_idx ON mx_official_channels (decided_at) WHERE state = 'added';

CREATE TABLE IF NOT EXISTS mx_official_lookups (
  key         text PRIMARY KEY,                    -- the actor-thing pair asked about
  actor_id    uuid,
  story_id    text,
  task_id     uuid,
  answer      jsonb,
  asked_at    timestamptz NOT NULL DEFAULT now(),
  answered_at timestamptz
);

CREATE TABLE IF NOT EXISTS mx_official_runs (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mode        text NOT NULL,
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  counts      jsonb NOT NULL DEFAULT '{}'
);

ALTER TABLE story_originals DROP CONSTRAINT IF EXISTS story_originals_kind_check;
ALTER TABLE story_originals ADD CONSTRAINT story_originals_kind_check
  CHECK (kind IN ('fetch_linked', 'collect', 'entity', 'lookup', 'classic', 'work', 'reference', 'missed', 'cited'));

-- 6. An entity's maker found by the official channels' web search (markx/entity_facts.set_maker, by `web`): written
--    only where no maker is known (the owner's and the mentions' makers always win).
ALTER TABLE mx_entity_facts DROP CONSTRAINT IF EXISTS mx_entity_facts_by_check;
ALTER TABLE mx_entity_facts ADD CONSTRAINT mx_entity_facts_by_check
  CHECK (by IN ('rule:mentions', 'rule:address', 'haiku', 'owner', 'web'));

-- 7. mx_official_events: each event (a Mark X story) the job looked at, and what it found: held (the actor's own post
--    is in the story), covered, channels, waiting (a lookup or a judgement is pending: looked at again), none (no
--    provable channel: the story says "official source not found"), not_official (no official source: a lawsuit, a
--    leak), no_actor.
CREATE TABLE IF NOT EXISTS mx_official_events (
  story_id    text PRIMARY KEY,
  actor_id    uuid,
  actor_name  text,
  outcome     text NOT NULL,
  detail      jsonb NOT NULL DEFAULT '{}',
  first_at    timestamptz,
  decided_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_official_events_actor_idx ON mx_official_events (actor_id, first_at);

-- 8. mx_tasks.subject_kind may be `official_event` (the web search of an event's actor and channels).
DO $$
DECLARE
  def  text;
  vals text[];
BEGIN
  SELECT pg_get_constraintdef(c.oid) INTO def
    FROM pg_constraint c
   WHERE c.conrelid = 'mx_tasks'::regclass AND c.conname = 'mx_tasks_subject_kind_check';
  IF def IS NOT NULL AND position(quote_literal('official_event') IN def) = 0 THEN
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY['official_event'];
    ALTER TABLE mx_tasks DROP CONSTRAINT mx_tasks_subject_kind_check;
    EXECUTE format('ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check CHECK (subject_kind IN (%s))',
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END IF;
END $$;
