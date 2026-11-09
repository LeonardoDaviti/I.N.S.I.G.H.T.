-- 0089_entity_originals.sql (issue 0138, Stealth v10.10: originals from entities; Discover learns from originals)
--
-- 1. mx_entity_addresses: an entity's addresses, the links its posts carry that are that thing's own page, found by
--    rules with no request (utils/entity_originals.py): rule 'identifier' (an arXiv id or a DOI the post holds),
--    'title' (the link's read title is the entity's name), 'maker' (a page on its maker's own site naming it),
--    'site' (0138 E2: a document's work site, the front page whose site word is its name), or 'lookup' (0138 C: the
--    arXiv API or Crossref by title, behind "Look up unlinked originals"). kind: paper, code, demo, release, or work
--    (0138 E2: a work site's front page, for a document only). entity_id is the entity's root when it was written
--    (readers go through the merges); post_id the post that carried it (none for a lookup). Written by the decision
--    run's entity stage, incrementally; one row an (entity, address), never deleted. No foreign key (a log, like story_originals: the Mark X tests
--    truncate mx_entities alone).
-- 2. story_originals.kind may be 'entity' (0138 B: an entity's original collected), 'lookup' (0138 C: one title
--    lookup asked, url 'entity:<id>'), 'classic' (0138 E1: a Classic not stored, collected under the backfill
--    allowance), 'work' (0138 E2: a work site's front page or one of its own pages your posts link), 'reference'
--    (0138 F1: a page a curated long-read you opened or kept cites; from_post_id the citing post) or 'missed' (0138
--    F2: a followed source's page its feed never carried, read once as that source's post; source_id the source);
--    story_originals.entity_id names the entity (null for 0114, 0123, E1 and F's rows).
-- 3. The switches "Look up unlinked originals" (system_settings.scheduler_config.lookup_originals, off) and "Store
--    Classics" (store_classics, on) take their defaults when unwritten: no row is written here.
--
-- Idempotent. Nothing is deleted.

CREATE TABLE IF NOT EXISTS mx_entity_addresses (
  entity_id uuid NOT NULL,
  url       text NOT NULL,
  kind      text NOT NULL CHECK (kind IN ('paper', 'code', 'demo', 'release', 'work')),
  rule      text NOT NULL CHECK (rule IN ('identifier', 'title', 'maker', 'site', 'lookup')),
  post_id   uuid,
  first_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (entity_id, url)
);
CREATE INDEX IF NOT EXISTS mx_entity_addresses_url_idx ON mx_entity_addresses (url);

ALTER TABLE story_originals ADD COLUMN IF NOT EXISTS entity_id uuid;
ALTER TABLE story_originals ADD COLUMN IF NOT EXISTS from_post_id uuid;
ALTER TABLE story_originals DROP CONSTRAINT IF EXISTS story_originals_kind_check;
ALTER TABLE story_originals ADD CONSTRAINT story_originals_kind_check
  CHECK (kind IN ('fetch_linked', 'collect', 'entity', 'lookup', 'classic', 'work', 'reference', 'missed'));
CREATE INDEX IF NOT EXISTS story_originals_entity_idx ON story_originals (entity_id) WHERE entity_id IS NOT NULL;
