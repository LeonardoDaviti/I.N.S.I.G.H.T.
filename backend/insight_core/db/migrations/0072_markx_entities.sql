-- 0072_markx_entities.sql (issue 0119 A, Mark X v10.1: entities in Shadow — identity, the review queue, surges)
--
-- (0071 is taken by issue 0123's story_originals on its own branch; this is the next free number at the time of
-- writing. Renumber at merge if another lands first: nothing here depends on the number.)
--
-- 1. mx_entities: one thing (an org, a person, a model family, one version or variant of it ...), 0090 C's design.
--    `parent` is the hierarchy (company -> family -> version/variant/checkpoint): a version's parent is its family, a
--    family's its maker's entity when the maker is stated. `key` is the name key it was made for (names.key);
--    family_key / version_key / variant / size / build are the fields the merge rules and the version guard read
--    (version_key: the version as a tuple, a JSON array, so "4.10" and "4.1" differ). status: provisional (made by
--    linking), confirmed (an owner's answer named it), not_entity (the owner said so; its row stays).
-- 2. mx_entity_aliases: a name key that names an entity (source: rule = its own key or a rule's merge, haiku,
--    anchor, owner). One current entity per key; an alias is never deleted.
-- 3. mx_entity_redirects: a merge (from -> to), by a rule, Haiku or the owner, with its call; undone_at undoes it
--    (the row stays). At most one current redirect per entity.
-- 4. mx_entity_queue: the review queue (0119 A1). A pair (a, b) or one entity (a collision), the system's proposal,
--    why it is queued, its confidence and evidence; the owner's answer and what applying it did. Closed items stay.
-- 5. mx_entity_pins: a mention the owner's split gave another entity (linking keeps it there). undone_at undoes it.
-- 6. mx_entity_vectors: a name's BGE-M3 vector (the embed_name kind), for the alias candidates' cosine.
-- 7. mx_entity_surges (0119 A2): an entity-day of 3 or more voices, with its posts; a recount that changes it closes
--    the row (valid_to) and opens another (keep everything).
-- 8. mx_tasks.subject_kind may name an entity ('entity', 'entity_entity': the alias and collide questions).
--
-- mx_mentions.entity_id (0068, null until now) is set by the decision run's entities stage. No key leaves the mx_*
-- tables (corrections 2). Mark X tables only; nothing is deleted. Idempotent.

CREATE TABLE IF NOT EXISTS mx_entities (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  type        text,
  name        text NOT NULL,
  key         text NOT NULL,
  level       text NOT NULL DEFAULT 'thing' CHECK (level IN ('thing', 'family', 'version', 'variant', 'checkpoint')),
  parent      uuid REFERENCES mx_entities(id),
  maker       text,
  family_key  text,
  version     text,
  version_key jsonb,
  variant     text,
  size        text,
  build       text,
  status      text NOT NULL DEFAULT 'provisional' CHECK (status IN ('provisional', 'confirmed', 'not_entity')),
  first_seen  timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now(),
  run_id      uuid REFERENCES mx_runs(id),
  CONSTRAINT mx_entities_not_its_own_parent CHECK (parent IS NULL OR parent <> id)
);
CREATE INDEX IF NOT EXISTS mx_entities_key_idx ON mx_entities (key);
CREATE INDEX IF NOT EXISTS mx_entities_parent_idx ON mx_entities (parent) WHERE parent IS NOT NULL;
CREATE INDEX IF NOT EXISTS mx_entities_family_idx ON mx_entities (family_key) WHERE family_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS mx_entity_aliases (
  key        text PRIMARY KEY,
  entity_id  uuid NOT NULL REFERENCES mx_entities(id),
  language   text,
  mixed      boolean NOT NULL DEFAULT false,      -- a word mixing scripts (Latin and Cyrillic look-alikes), flagged
  source     text NOT NULL CHECK (source IN ('rule', 'haiku', 'anchor', 'owner')),
  call_id    uuid REFERENCES mx_calls(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_entity_aliases_entity_idx ON mx_entity_aliases (entity_id);

CREATE TABLE IF NOT EXISTS mx_entity_redirects (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  from_id    uuid NOT NULL REFERENCES mx_entities(id),
  to_id      uuid NOT NULL REFERENCES mx_entities(id),
  at         timestamptz NOT NULL DEFAULT now(),
  by         text NOT NULL,                       -- 'rule:<name>', 'haiku', 'owner'
  automatic  boolean NOT NULL,
  call_id    uuid REFERENCES mx_calls(id),
  queue_id   uuid,
  run_id     uuid REFERENCES mx_runs(id),
  evidence   jsonb,
  undone_at  timestamptz,
  undone_by  text,
  CONSTRAINT mx_entity_redirects_not_to_itself CHECK (from_id <> to_id),
  CONSTRAINT mx_entity_redirects_undone_after CHECK (undone_at IS NULL OR undone_at >= at)
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_entity_redirects_current_idx ON mx_entity_redirects (from_id) WHERE undone_at IS NULL;
CREATE INDEX IF NOT EXISTS mx_entity_redirects_to_idx ON mx_entity_redirects (to_id) WHERE undone_at IS NULL;

CREATE TABLE IF NOT EXISTS mx_entity_queue (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  kind        text NOT NULL CHECK (kind IN ('alias', 'collision')),
  a           uuid NOT NULL REFERENCES mx_entities(id),
  b           uuid REFERENCES mx_entities(id),
  proposal    text NOT NULL CHECK (proposal IN ('same', 'other_version', 'different', 'split')),
  reason      text NOT NULL,                      -- why it is asked, not merged: below_bar, version, type, chain, ...
  confidence  real,
  evidence    jsonb,
  call_id     uuid REFERENCES mx_calls(id),
  run_id      uuid REFERENCES mx_runs(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  answer      text CHECK (answer IN ('same', 'other_version', 'different', 'not_entity')),
  answered_at timestamptz,
  applied     jsonb,
  closed_at   timestamptz,                        -- superseded without an answer (a newer item on the pair)
  CONSTRAINT mx_entity_queue_a_pair_is_two CHECK (kind <> 'alias' OR (b IS NOT NULL AND a <> b))
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_entity_queue_open_idx ON mx_entity_queue (kind, a, COALESCE(b, a))
  WHERE answer IS NULL AND closed_at IS NULL;
CREATE INDEX IF NOT EXISTS mx_entity_queue_b_idx ON mx_entity_queue (b) WHERE b IS NOT NULL;

CREATE TABLE IF NOT EXISTS mx_entity_pins (
  post_id    uuid NOT NULL,
  guide      text NOT NULL REFERENCES mx_guides(id),
  n          integer NOT NULL,
  entity_id  uuid NOT NULL REFERENCES mx_entities(id),
  queue_id   uuid REFERENCES mx_entity_queue(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  undone_at  timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_entity_pins_current_idx ON mx_entity_pins (post_id, guide, n) WHERE undone_at IS NULL;

CREATE TABLE IF NOT EXISTS mx_entity_vectors (
  entity_id    uuid NOT NULL REFERENCES mx_entities(id),
  model        text NOT NULL,
  model_sha256 text,
  text_hash    text NOT NULL,
  v            halfvec(1024) NOT NULL,
  PRIMARY KEY (entity_id, model)
);
CREATE INDEX IF NOT EXISTS mx_entity_vectors_v_hnsw_idx ON mx_entity_vectors USING hnsw (v halfvec_cosine_ops);

CREATE TABLE IF NOT EXISTS mx_entity_surges (
  entity_id  uuid NOT NULL REFERENCES mx_entities(id),
  day        date NOT NULL,
  voices     integer NOT NULL,
  posts      integer NOT NULL,
  rule       text NOT NULL,
  evidence   jsonb NOT NULL DEFAULT '{}'::jsonb,  -- {posts: [ids], via: [{entity, name, posts}]} (a roll-up's children)
  run_id     uuid REFERENCES mx_runs(id),
  valid_from timestamptz NOT NULL DEFAULT now(),
  valid_to   timestamptz,
  CONSTRAINT mx_entity_surges_closes_after_it_opens CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_entity_surges_current_idx ON mx_entity_surges (entity_id, day, rule) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS mx_entity_surges_day_idx ON mx_entity_surges (day) WHERE valid_to IS NULL;

CREATE INDEX IF NOT EXISTS mx_mentions_entity_idx ON mx_mentions (entity_id) WHERE entity_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS mx_mentions_unlinked_idx ON mx_mentions (post_id) WHERE entity_id IS NULL;

ALTER TABLE mx_tasks DROP CONSTRAINT IF EXISTS mx_tasks_subject_kind_check;
ALTER TABLE mx_tasks ADD CONSTRAINT mx_tasks_subject_kind_check
  CHECK (subject_kind IN ('post', 'post_story', 'post_post', 'story', 'story_story', 'day', 'entity', 'entity_entity'));
