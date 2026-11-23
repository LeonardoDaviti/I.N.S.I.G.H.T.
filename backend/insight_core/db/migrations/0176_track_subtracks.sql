-- 0176_track_subtracks.sql (Stealth v10.42: sub-tracks and a reader's stack)
--
-- mx_tracks gains:
--   parent_id  a sub-track's parent track (its folder). A sub-track's posts are its parent's posts in the track: a
--              judged sub-track asks the track judge of each (its own description, excludes and stack); a `rest`
--              sub-track takes the parent's posts that none of its judged siblings holds, with no question.
--   stack      the things (mx_entities ids) the reader uses. A sub-track with a stack asks only the posts whose
--              mentions name one of them (or a thing under one: a version, a product of a maker); any track shows
--              its stack to the judge.
--   rest       this sub-track takes the rest of its parent's posts.
--   sort       'newest' (default), or 'news': as News ranks its posts' rows, without the reader's fit (newest after).
-- Mark X tables only; nothing is deleted. Idempotent.

ALTER TABLE mx_tracks ADD COLUMN IF NOT EXISTS parent_id uuid;
ALTER TABLE mx_tracks ADD COLUMN IF NOT EXISTS stack uuid[] NOT NULL DEFAULT '{}';
ALTER TABLE mx_tracks ADD COLUMN IF NOT EXISTS rest boolean NOT NULL DEFAULT false;
ALTER TABLE mx_tracks ADD COLUMN IF NOT EXISTS sort text NOT NULL DEFAULT 'newest';
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'mx_tracks_sort_check') THEN
    ALTER TABLE mx_tracks ADD CONSTRAINT mx_tracks_sort_check CHECK (sort IN ('newest', 'news'));
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS mx_tracks_parent_idx ON mx_tracks (parent_id) WHERE parent_id IS NOT NULL;
