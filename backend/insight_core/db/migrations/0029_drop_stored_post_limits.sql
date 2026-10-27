-- 0029_drop_stored_post_limits.sql (issue 0029)
--
-- The posts a fetch may bring is the kind's own (the platform default and the cadence
-- rules); the API stopped accepting max_posts_per_fetch and the UI stopped showing it. A
-- value stored before still overrode the default, unseen: this removes it. priority stays,
-- the runner still orders by it. Idempotent.

UPDATE sources
SET settings = settings - 'max_posts_per_fetch'
WHERE settings ? 'max_posts_per_fetch';
