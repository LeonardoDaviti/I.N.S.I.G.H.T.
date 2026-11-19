-- v10.25 (issue 0229): mx_entity_addresses (0089, 0097) takes the kind 'cited': a page an entity's posts cite, found by
-- rule 'identifier' or 'title' with no evidence that it IS the entity (a paper a report's posts link, a third party's
-- page titled with a model's name). Never an original or an address; the entity page lists it apart. Rows an older
-- rule wrote as 'paper', 'code', 'demo' or 'release' become 'cited' when the entity stage's sweep reads their post
-- again (entity_addresses.stage); no row is rewritten here.
ALTER TABLE mx_entity_addresses DROP CONSTRAINT IF EXISTS mx_entity_addresses_kind_check;
ALTER TABLE mx_entity_addresses ADD CONSTRAINT mx_entity_addresses_kind_check
  CHECK (kind IN ('paper', 'code', 'demo', 'release', 'work', 'package', 'cited')) NOT VALID;
