-- 0128_markx_page_reads.sql (Stealth v10.17, issue 0186: no whole-book read per API request)
--
-- A page's book (identity.lazy_book) answers by index what it read whole before:
--   - which clusters some entity names as its maker (perspectives.Makers): the distinct stated makers;
--   - whether a current mention's `by` (a document's publisher) names an entity (entity_views.named_now on the
--     entity page): the publishers' names, not every current mention.
-- Mark X tables only; no row changes. Idempotent. (Apart from 0127, which v10.16.1 ships on its own.)

CREATE INDEX IF NOT EXISTS mx_entities_maker_idx ON mx_entities (maker) WHERE maker IS NOT NULL;
CREATE INDEX IF NOT EXISTS mx_mentions_by_name_idx ON mx_mentions (by_name) WHERE by_name IS NOT NULL;
