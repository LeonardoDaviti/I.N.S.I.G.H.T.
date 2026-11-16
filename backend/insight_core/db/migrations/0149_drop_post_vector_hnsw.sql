-- 0149_drop_post_vector_hnsw.sql (Stealth v10.22, issue 0216 F: the unused HNSW index on the posts' vectors)
--
-- mx_embeddings_v_hnsw_idx (0068) served only markx/repo.nearest, which only a test called (removed with it). A post's
-- neighbours are exact cosines over its window by primary key (pairing._cosines, embed.current_candidates), the track
-- scoring and the centroids read every window vector, and no statement of the server's pg_stat_statements orders
-- mx_embeddings by distance (GET /api/operations/db-statements, 2026-11-16; its `indexes` show the scans from v10.22 on).
-- Every embed answer's insert stopped maintaining an HNSW graph; ~2.7 kB a row of index (0.4 GB on the server).
-- The entity vectors' index (mx_entity_vectors_v_hnsw_idx, 0072) stays: identity.vector_neighbours orders by it.
--
-- A plain DROP INDEX (milliseconds, a short exclusive lock on mx_embeddings, taken within the migration's lock
-- timeout) so the file runs in a transaction like the archive restore's. Idempotent.

DROP INDEX IF EXISTS mx_embeddings_v_hnsw_idx;
