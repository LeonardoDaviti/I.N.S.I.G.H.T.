-- 0112_markx_handles.sql (issue 0168, Stealth v10.15: a person's handles and reposts credited to their author)
--
-- (0111 is another v10.15 slice's; renumber at merge if another lands first: nothing depends on the number.)
--
-- 1. mx_handle_scans: which posts the handle rule (markx/handles.py) has read, under which rule (`stamp`) and text
--    (`content_hash`), and the digest its rows carry. A post read again (a new rule, new text) gets a new digest; the
--    rows of the old one stay, unread (nothing is deleted).
-- 2. mx_handle_refs: a post's handle references by the deterministic rule over its full text, kept links and author
--    fields: platform (x, github, telegram, bluesky, hf), the handle casefolded and as written, the form (repost,
--    quote, embed, status, said, at, profile, reply) and its role (by, source, mention, reply), a status link's id,
--    the post's source and the line's key (a line 3+ posts of one source repeat is boilerplate, found at read time).
-- 3. mx_handle_pairs: "Display Name (@handle)" pairs in a post's text (the name, its squashed key), from which a
--    handle is proposed for the entity of that name (2+ agreeing posts; the owner confirms once).
-- 4. mx_entity_handles: the owner's answers: this entity has (yes) or has not (no) this handle on this platform, the
--    display name and the time range its pairs gave (an old, renamed account). The newest answer counts.
-- 5. mx_entity_queue.kind may be 'handle' (one entity, the handle in its evidence); a second open item for the same
--    entity and another handle is allowed (the open index reads the handle).
--
-- Mark X tables only (no key to a Mark IX table). Idempotent.

CREATE TABLE IF NOT EXISTS mx_handle_scans (
  post_id      uuid PRIMARY KEY,
  stamp        text NOT NULL,
  content_hash text,
  digest       text NOT NULL,
  refs         integer NOT NULL DEFAULT 0,
  pairs        integer NOT NULL DEFAULT 0,
  at           timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_handle_scans_stamp_idx ON mx_handle_scans (stamp);

CREATE TABLE IF NOT EXISTS mx_handle_refs (
  post_id    uuid NOT NULL,
  digest     text NOT NULL,
  platform   text NOT NULL CHECK (platform IN ('x', 'github', 'telegram', 'bluesky', 'hf')),
  handle     text NOT NULL,
  shown      text NOT NULL,
  form       text NOT NULL CHECK (form IN ('repost', 'quote', 'embed', 'status', 'said', 'at', 'profile', 'reply')),
  role       text NOT NULL CHECK (role IN ('by', 'source', 'mention', 'reply')),
  status     text,
  source_id  uuid,
  line_key   text,
  snippet    text,
  at         timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (post_id, digest, platform, handle, form)
);
CREATE INDEX IF NOT EXISTS mx_handle_refs_handle_idx ON mx_handle_refs (platform, handle);
CREATE INDEX IF NOT EXISTS mx_handle_refs_line_idx ON mx_handle_refs (source_id, line_key) WHERE line_key IS NOT NULL;

CREATE TABLE IF NOT EXISTS mx_handle_pairs (
  post_id    uuid NOT NULL,
  digest     text NOT NULL,
  platform   text NOT NULL CHECK (platform IN ('x', 'github', 'telegram', 'bluesky', 'hf')),
  handle     text NOT NULL,
  name       text NOT NULL,
  name_sq    text NOT NULL,
  at         timestamptz,
  PRIMARY KEY (post_id, digest, platform, handle, name_sq)
);
CREATE INDEX IF NOT EXISTS mx_handle_pairs_handle_idx ON mx_handle_pairs (platform, handle);

CREATE TABLE IF NOT EXISTS mx_entity_handles (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  entity_id    uuid NOT NULL REFERENCES mx_entities(id),
  platform     text NOT NULL CHECK (platform IN ('x', 'github', 'telegram', 'bluesky', 'hf')),
  handle       text NOT NULL,
  answer       text NOT NULL CHECK (answer IN ('yes', 'no')),
  display_name text,
  first_seen   timestamptz,
  last_seen    timestamptz,
  queue_id     uuid REFERENCES mx_entity_queue(id),
  evidence     jsonb,
  created_at   timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS mx_entity_handles_entity_idx ON mx_entity_handles (entity_id, platform, handle, created_at DESC);
CREATE INDEX IF NOT EXISTS mx_entity_handles_handle_idx ON mx_entity_handles (platform, handle);

ALTER TABLE mx_entity_queue DROP CONSTRAINT IF EXISTS mx_entity_queue_kind_check;
ALTER TABLE mx_entity_queue ADD CONSTRAINT mx_entity_queue_kind_check
  CHECK (kind IN ('alias', 'collision', 'rename', 'handle'));
DROP INDEX IF EXISTS mx_entity_queue_open_idx;
CREATE UNIQUE INDEX IF NOT EXISTS mx_entity_queue_open_idx
  ON mx_entity_queue (kind, a, COALESCE(b, a), COALESCE(evidence->>'platform', ''), COALESCE(evidence->>'handle', ''))
  WHERE answer IS NULL AND closed_at IS NULL;
