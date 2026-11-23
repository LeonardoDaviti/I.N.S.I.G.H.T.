-- 0172_listing_filter.sql (Stealth v10.35: listing pages hidden, never deleted)
--
-- A source's item filter (source_filters, 0138) may carry {"listing": true}: it hides the source's stored listing
-- pages (a tag, category, topic or author archive read as an article; utils/item_filter, page_watch.stored_listing).
-- INSIGHT sets that flag itself, so a row may be `by` 'insight' besides the worker's and the owner's. Idempotent.

ALTER TABLE source_filters DROP CONSTRAINT IF EXISTS source_filters_by_check;
ALTER TABLE source_filters ADD CONSTRAINT source_filters_by_check CHECK (by IN ('worker', 'owner', 'insight'));
