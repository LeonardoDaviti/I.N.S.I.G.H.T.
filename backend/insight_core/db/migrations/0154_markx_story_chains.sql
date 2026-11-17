-- 0154_markx_story_chains.sql (Stealth v10.24, issue 0219: story chains)
--
-- A story's chain (markx/graph.py `chain`) walks the story-to-story edges of rule 'chain_stops' from a story to the
-- earlier stories it follows (a -> b) and to the later ones that follow it (b -> a), "as of" any moment: so it reads
-- closed rows too, which the current-only indexes of 0068 do not cover. Two small partial indexes, one a direction,
-- over the chain rows only (decide's story connections and the post graph are other rules). Mark X tables only.
-- Idempotent.
CREATE INDEX IF NOT EXISTS mx_connections_chain_a_idx ON mx_connections (a, valid_from)
  WHERE a_kind = 'story' AND b_kind = 'story' AND rule = 'chain_stops';
CREATE INDEX IF NOT EXISTS mx_connections_chain_b_idx ON mx_connections (b, valid_from)
  WHERE a_kind = 'story' AND b_kind = 'story' AND rule = 'chain_stops';
