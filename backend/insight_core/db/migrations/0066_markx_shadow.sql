-- 0066_markx_shadow.sql (issue 0086 A: Mark X Shadow's storage)
--
-- Fourteen new tables, mx_*, and nothing else: no existing table, column, index or trigger changes.
-- Mark X writes only these; markx/repo.py holds their inserts and reads.
--
-- Keyed by posts and content, never by a Mark IX story (build plan, corrections 2): a Mark IX story's
-- row is deleted and rewritten when the story changes shape, so no mx_* table has a foreign key out of
-- mx_* (not to stories, story_posts, nor posts: a Mark IX delete never cascades into Mark X or waits
-- on it). A task's input is content only, and input_hash is the sha256 of that text, so the same
-- question is asked once whatever the ids around it say.
--
-- Keep everything: a membership or connection that changes is closed (valid_to), never deleted; a
-- changed guide is a new guide id (an edit is refused below). Model output is JSONB; what INSIGHT
-- joins, filters or counts are typed columns. The embeddings are halfvec(1024) (BGE-M3) under an
-- HNSW cosine index (0086 open question 4: now).
--
-- Idempotent.

CREATE EXTENSION IF NOT EXISTS vector;   -- 0003 made it; pgvector 0.8.3 has halfvec and HNSW

-- One prompt, as sent. sha256 is the body's (UTF-8), checked here.
CREATE TABLE IF NOT EXISTS mx_guides (
  id         text PRIMARY KEY,
  kind       text NOT NULL,
  sha256     text NOT NULL,
  body       text NOT NULL,
  schema     jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT mx_guides_sha256_is_the_body CHECK (sha256 = encode(sha256(convert_to(body, 'UTF8')), 'hex'))
);

CREATE OR REPLACE FUNCTION mx_guides_unchanged() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.kind IS DISTINCT FROM OLD.kind OR NEW.body IS DISTINCT FROM OLD.body
     OR NEW.sha256 IS DISTINCT FROM OLD.sha256 OR NEW.schema IS DISTINCT FROM OLD.schema THEN
    RAISE EXCEPTION 'mx_guides: guide % is never edited; a changed guide is a new id', OLD.id;
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS mx_guides_unchanged ON mx_guides;
CREATE TRIGGER mx_guides_unchanged BEFORE UPDATE ON mx_guides FOR EACH ROW EXECUTE FUNCTION mx_guides_unchanged();

-- One question. a, b: its subjects (posts or Mark X stories, by kind), for reading back only.
CREATE TABLE IF NOT EXISTS mx_tasks (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind         text NOT NULL,
  guide        text NOT NULL REFERENCES mx_guides(id),
  subject_kind text NOT NULL CHECK (subject_kind IN ('post', 'post_story', 'post_post', 'story', 'story_story', 'day')),
  a            uuid,
  b            uuid,
  day          date,
  input        text NOT NULL,
  input_hash   text NOT NULL,
  priority     integer NOT NULL DEFAULT 0,
  status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'leased', 'answered', 'failed')),
  lease_until  timestamptz,
  leased_by    text,
  attempts     integer NOT NULL DEFAULT 0,
  last_error   text,
  created_at   timestamptz NOT NULL DEFAULT now(),
  answered_at  timestamptz,
  CONSTRAINT mx_tasks_once UNIQUE (kind, guide, input_hash),
  CONSTRAINT mx_tasks_input_hash_is_the_input CHECK (input_hash = encode(sha256(convert_to(input, 'UTF8')), 'hex')),
  CONSTRAINT mx_tasks_a_lease_has_an_end CHECK (status <> 'leased' OR lease_until IS NOT NULL)
);
-- The worker's lease: open (or expired) tasks of its kinds, by priority then age.
CREATE INDEX IF NOT EXISTS mx_tasks_queue_idx ON mx_tasks (kind, priority, created_at) WHERE status IN ('open', 'leased');
CREATE INDEX IF NOT EXISTS mx_tasks_lease_idx ON mx_tasks (lease_until) WHERE status = 'leased';
CREATE INDEX IF NOT EXISTS mx_tasks_a_idx ON mx_tasks (a) WHERE a IS NOT NULL;
CREATE INDEX IF NOT EXISTS mx_tasks_b_idx ON mx_tasks (b) WHERE b IS NOT NULL;

-- One answer from one model, valid or not (the audit trail and 0087's training set).
CREATE TABLE IF NOT EXISTS mx_calls (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id    uuid NOT NULL REFERENCES mx_tasks(id),
  executor   text NOT NULL CHECK (executor IN ('claude-code', 'api', 'api-batch')),
  model      text NOT NULL,
  valid      boolean NOT NULL,
  error      text,
  tokens_in  integer,
  tokens_out integer,
  ms         integer,
  cost_usd   numeric,
  created_at timestamptz NOT NULL DEFAULT now(),
  answer     jsonb
);
CREATE INDEX IF NOT EXISTS mx_calls_task_idx ON mx_calls (task_id);
CREATE INDEX IF NOT EXISTS mx_calls_created_idx ON mx_calls (created_at);

-- A post's reading (F0.2).
CREATE TABLE IF NOT EXISTS mx_readings (
  post_id  uuid NOT NULL,
  guide    text NOT NULL REFERENCES mx_guides(id),
  call_id  uuid NOT NULL REFERENCES mx_calls(id),
  kind     text,
  events   text,
  lang     text,
  headline text,
  reading  jsonb NOT NULL,
  PRIMARY KEY (post_id, guide)
);

-- One entity named in one post (F7, 0090 A). entity_id stays null until 0090 C's identity.
CREATE TABLE IF NOT EXISTS mx_mentions (
  post_id   uuid NOT NULL,
  guide     text NOT NULL REFERENCES mx_guides(id),
  n         integer NOT NULL,
  call_id   uuid NOT NULL REFERENCES mx_calls(id),
  span      text NOT NULL,
  name      text NOT NULL,
  name_key  text NOT NULL,
  type      text,
  role      text,
  maker     text,
  family    text,
  version   text,
  variant   text,
  size      text,
  build     text,
  entity_id uuid,
  PRIMARY KEY (post_id, guide, n)
);
CREATE INDEX IF NOT EXISTS mx_mentions_name_key_idx ON mx_mentions (name_key);
CREATE INDEX IF NOT EXISTS mx_mentions_family_version_idx ON mx_mentions (family, version);

-- A post's vector: text_hash is the hash of the text embedded (markx text v1), so a text change is seen.
CREATE TABLE IF NOT EXISTS mx_embeddings (
  post_id   uuid NOT NULL,
  model     text NOT NULL,
  text_hash text NOT NULL,
  v         halfvec(1024) NOT NULL,
  PRIMARY KEY (post_id, model)
);
CREATE INDEX IF NOT EXISTS mx_embeddings_v_hnsw_idx ON mx_embeddings USING hnsw (v halfvec_cosine_ops);

-- A pair worth a question, once per source.
CREATE TABLE IF NOT EXISTS mx_candidates (
  kind       text NOT NULL,
  a          uuid NOT NULL,
  b          uuid NOT NULL,
  source     text NOT NULL CHECK (source IN ('embedding', 'link', 'entity', 'burst')),
  score      real,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (kind, a, b, source)
);
CREATE INDEX IF NOT EXISTS mx_candidates_b_idx ON mx_candidates (b);

-- One decision run.
CREATE TABLE IF NOT EXISTS mx_runs (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  code_version text,
  config       jsonb NOT NULL DEFAULT '{}'::jsonb,
  counts       jsonb
);
CREATE INDEX IF NOT EXISTS mx_runs_started_idx ON mx_runs (started_at);

-- A Mark X story.
CREATE TABLE IF NOT EXISTS mx_stories (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  first_at      timestamptz,
  created_run   uuid REFERENCES mx_runs(id),
  merged_into   uuid REFERENCES mx_stories(id),
  headline      text,
  headline_call uuid REFERENCES mx_calls(id),
  card_call     uuid REFERENCES mx_calls(id)
);
CREATE INDEX IF NOT EXISTS mx_stories_first_at_idx ON mx_stories (first_at);

-- A post in a Mark X story (0074's edge model: a post may be current in several). valid_to null = current.
CREATE TABLE IF NOT EXISTS mx_story_posts (
  story_id   uuid NOT NULL REFERENCES mx_stories(id),
  post_id    uuid NOT NULL,
  role       text NOT NULL CHECK (role IN ('member', 'mention', 'digest_item')),
  reason     text NOT NULL,
  p          real,
  call_id    uuid REFERENCES mx_calls(id),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to   timestamptz,
  run_id     uuid REFERENCES mx_runs(id),
  CONSTRAINT mx_story_posts_closes_after_it_opens CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_story_posts_current_idx ON mx_story_posts (story_id, post_id) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS mx_story_posts_post_idx ON mx_story_posts (post_id) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS mx_story_posts_history_idx ON mx_story_posts (story_id, post_id, valid_from);

-- A typed connection between posts or stories; each names a call or a rule.
CREATE TABLE IF NOT EXISTS mx_connections (
  a_kind     text NOT NULL CHECK (a_kind IN ('post', 'story')),
  a          uuid NOT NULL,
  b_kind     text NOT NULL CHECK (b_kind IN ('post', 'story')),
  b          uuid NOT NULL,
  relation   text NOT NULL,
  p          real,
  call_id    uuid REFERENCES mx_calls(id),
  rule       text,
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to   timestamptz,
  run_id     uuid REFERENCES mx_runs(id),
  evidence   jsonb,
  CONSTRAINT mx_connections_names_a_call_or_rule CHECK (call_id IS NOT NULL OR rule IS NOT NULL),
  CONSTRAINT mx_connections_closes_after_it_opens CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_connections_current_idx ON mx_connections (a_kind, a, b_kind, b, relation) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS mx_connections_b_idx ON mx_connections (b_kind, b) WHERE valid_to IS NULL;

-- A Mark X News row, in the shape of Mark IX's news_stories (id: its first post) with its news_posts rows
-- in `posts` ([{post_id, role, voice, name, position}]), per run, tagged against Mark IX's News.
CREATE TABLE IF NOT EXISTS mx_news (
  run_id     uuid NOT NULL REFERENCES mx_runs(id),
  id         uuid NOT NULL,
  first_at   timestamptz NOT NULL,
  voices     integer NOT NULL,
  reports    integer NOT NULL,
  shares     integer NOT NULL,
  mentions   integer NOT NULL,
  score      numeric NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  tag        text CHECK (tag IN ('NEW', 'CHANGED', 'MERGED', 'SPLIT', 'SAME')),
  posts      jsonb NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY (run_id, id)
);
CREATE INDEX IF NOT EXISTS mx_news_first_at_idx ON mx_news (run_id, first_at);

-- A day's briefing; lines: [{text, keys: [story keys]}].
CREATE TABLE IF NOT EXISTS mx_briefings (
  day        date NOT NULL,
  call_id    uuid NOT NULL REFERENCES mx_calls(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  lines      jsonb NOT NULL,
  PRIMARY KEY (day, call_id)
);

-- Your answer to one item (E1, part F).
CREATE TABLE IF NOT EXISTS mx_labels (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  item_kind  text NOT NULL CHECK (item_kind IN ('join', 'check', 'merge', 'news_row', 'entity', 'connection')),
  a          uuid,
  b          uuid,
  answer     text NOT NULL,
  labeller   text NOT NULL DEFAULT 'owner',
  split      text CHECK (split IN ('dev', 'test')),
  note       text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_labels_item_idx ON mx_labels (item_kind, a, b);
