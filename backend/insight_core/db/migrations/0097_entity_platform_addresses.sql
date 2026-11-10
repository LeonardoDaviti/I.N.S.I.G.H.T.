-- 0097_entity_platform_addresses.sql (Stealth v10.13.5: an entity's platform page is its address)
--
-- mx_entity_addresses (0089) takes the rule 'repo' (utils/entity_originals.by_repo: a code host's, a model hub's or a
-- package index's page of one thing whose <thing> segment is the entity's name), the kind 'package' (a package
-- index's page), and `owner`: the platform's <owner> segment of such a page (npm's @scope; none on the other package
-- indexes), a maker candidate the entity page shows, never asserted as its maker.
--
-- Idempotent. Nothing is deleted.

ALTER TABLE mx_entity_addresses ADD COLUMN IF NOT EXISTS owner text;
ALTER TABLE mx_entity_addresses DROP CONSTRAINT IF EXISTS mx_entity_addresses_kind_check;
ALTER TABLE mx_entity_addresses ADD CONSTRAINT mx_entity_addresses_kind_check
  CHECK (kind IN ('paper', 'code', 'demo', 'release', 'work', 'package'));
ALTER TABLE mx_entity_addresses DROP CONSTRAINT IF EXISTS mx_entity_addresses_rule_check;
ALTER TABLE mx_entity_addresses ADD CONSTRAINT mx_entity_addresses_rule_check
  CHECK (rule IN ('identifier', 'title', 'maker', 'site', 'lookup', 'repo'));
