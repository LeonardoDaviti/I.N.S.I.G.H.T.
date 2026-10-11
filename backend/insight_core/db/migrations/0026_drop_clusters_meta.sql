-- 0026_drop_clusters_meta.sql (issue 0005 slice 1, dead weight)
--
-- 0004 created clusters, cluster_posts, meta_posts and meta_post_sources. No code reads or
-- writes them. Children go first, so no foreign key is left pointing at a dropped table.
-- Their indexes go with them. Idempotent.

DROP TABLE IF EXISTS meta_post_sources;
DROP TABLE IF EXISTS meta_posts;
DROP TABLE IF EXISTS cluster_posts;
DROP TABLE IF EXISTS clusters;
