-- 0083_series.sql (issue 0134, Stealth v10.8: Series, "Part 3 of 4" on a post, a recurring column told apart)
--
-- 1. series: a source's multi-part work (kind 'series') or recurring numbered column (kind 'column'), found by
--    utils/series.py's rule (no model) over the source's stored posts. stem: the normalized title stem the parts
--    share; name: the stem as a title writes it, for the line; total: the largest "of N" a part says. evidence: the
--    rule's edges counted (E1 numbered titles, E2 navigation links, E3 a shared start, part_one). Keep everything: a
--    group that changes is a new row, the old one closed (valid_to), never deleted.
-- 2. series_posts: its stored parts, oldest first (position), each with its number as written ("3", "32a"; NULL for
--    an unnumbered part).
-- 3. post_refs.navigation: the link is series navigation (both ends in one series, or its link words are navigation:
--    previous part, начало, ...). Connected shows such a row under the Series line, not as Earlier or Later; Stalker's
--    author-link edge over it is next_in_series (markx/graph.py). navigation_at: when the flag last changed (the
--    graph reads the changed refs again).
--
-- Written by the story job's series pass (db/repo_series.py: the sources with new or changed posts; every source the
-- first time, the backfill). Idempotent.

CREATE TABLE IF NOT EXISTS series (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id   uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  kind        text NOT NULL CHECK (kind IN ('series', 'column')),
  stem        text NOT NULL,
  name        text NOT NULL,
  total       integer,
  first_at    timestamptz NOT NULL,
  last_at     timestamptz NOT NULL,
  evidence    jsonb NOT NULL DEFAULT '{}'::jsonb,
  computed_at timestamptz NOT NULL DEFAULT now(),
  valid_to    timestamptz,
  CONSTRAINT series_closes_after_it_opens CHECK (valid_to IS NULL OR valid_to >= computed_at)
);
CREATE INDEX IF NOT EXISTS series_source_open_idx ON series (source_id) WHERE valid_to IS NULL;

CREATE TABLE IF NOT EXISTS series_posts (
  series_id uuid NOT NULL REFERENCES series(id) ON DELETE CASCADE,
  post_id   uuid NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  number    text,
  position  integer NOT NULL,
  PRIMARY KEY (series_id, post_id)
);
CREATE INDEX IF NOT EXISTS series_posts_post_idx ON series_posts (post_id);

ALTER TABLE post_refs ADD COLUMN IF NOT EXISTS navigation boolean NOT NULL DEFAULT false;
ALTER TABLE post_refs ADD COLUMN IF NOT EXISTS navigation_at timestamptz;
