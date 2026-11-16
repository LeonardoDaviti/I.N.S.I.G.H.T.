-- 0144_markx_entity_pair_tasks.sql (Stealth v10.20, issue 0211: an alias pair's questions looked up by the pair)
--
-- identity.Asked reads the questions already asked of the pairs a chunk decides (alias, alias2, alias3, alias4: a
-- pair of entities, either way round) instead of every such task and its input each decision run (5.1 s and 1.8 GB
-- of peak memory at the server's 357k alias tasks). This index is that lookup. Mark X tables only. Idempotent.

CREATE INDEX IF NOT EXISTS mx_tasks_entity_pair_idx ON mx_tasks ((least(a, b)), (greatest(a, b)))
  WHERE kind IN ('alias', 'alias2', 'alias3', 'alias4') AND b IS NOT NULL;
