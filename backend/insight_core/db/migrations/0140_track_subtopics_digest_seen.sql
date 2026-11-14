-- 0140 (issue 0207, Stealth v10.18): a track's evolving sub-topics, a digest per sub-topic, "new since you looked".
--
-- 1. mx_track_subtopics gains what the clustering keeps (markx/track_subtopics.py owns it): its centroid (the mean
--    BGE-M3 vector of its members), the members' hash and the hash when it was named (a sub-topic is named again
--    only when most of its members changed), when its newest member came (`last_member_at`: quiet sub-topics fade),
--    and the name's origin (`named_by`: judge = the members' most common judge string, haiku = a naming answer,
--    owner). The id stays while it is the same sub-topic: the clustering assigns members to the existing centroids
--    first, so a rebuild keeps ids; a new group gets a new row; one left with no member is closed (valid_to).
-- 2. mx_track_subtopic_members: the current members (one row a track and post: a post is in at most one sub-topic
--    of a track); `by` cluster (the job's, until Haiku places it), haiku (a placement answer: the post is in that
--    sub-topic, or in none of them, subtopic_id NULL) or owner (a merge or split the owner made); the clustering moves
--    only the job's own.
--    Derived rows: replaced by each refresh (the items and their verdicts are kept elsewhere).
-- 3. mx_track_subtopic_asks: what a naming, digest or placement question showed (`kind` names | digest | place): the
--    sub-topics in the order of its keys (g1..gK or s1..sK) and the posts in theirs (a digest's citations [n] and a
--    placement's p1..pN map back through it).
--    mx_tracks gains `subtopics_hash`: what the last clustering read (its posts in the track, how many have a vector,
--    the owner's and Haiku's settings): a track whose inputs did not change is not clustered again.
-- 4. mx_track_seen: when the reader last looked at a track (subtopic_id NULL) or at one of its sub-topics.
-- 5. The `subtopics` kind now names the sub-topics the clustering found (subtopics-v2); a 0145 proposal question
--    (subtopics-v1) still open would be asked and its answer applied by nothing: it is closed as failed (kept).
-- Mark X tables only; nothing of the inputs is deleted. Idempotent.

ALTER TABLE mx_track_subtopics ADD COLUMN IF NOT EXISTS centroid halfvec(1024);
ALTER TABLE mx_track_subtopics ADD COLUMN IF NOT EXISTS members_hash text;
ALTER TABLE mx_track_subtopics ADD COLUMN IF NOT EXISTS named_hash text;
ALTER TABLE mx_track_subtopics ADD COLUMN IF NOT EXISTS named_members uuid[];
ALTER TABLE mx_track_subtopics ADD COLUMN IF NOT EXISTS named_by text;
ALTER TABLE mx_track_subtopics ADD COLUMN IF NOT EXISTS last_member_at timestamptz;
ALTER TABLE mx_track_subtopics DROP CONSTRAINT IF EXISTS mx_track_subtopics_named_by_check;
ALTER TABLE mx_track_subtopics ADD CONSTRAINT mx_track_subtopics_named_by_check
  CHECK (named_by IS NULL OR named_by IN ('judge', 'haiku', 'owner'));

CREATE TABLE IF NOT EXISTS mx_track_subtopic_members (
  track_id    uuid NOT NULL,
  post_id     uuid NOT NULL,
  subtopic_id uuid,                                  -- NULL: Haiku placed it in none of them (Other)
  by          text NOT NULL DEFAULT 'cluster' CHECK (by IN ('cluster', 'haiku', 'owner')),
  sim         real,
  since       timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (track_id, post_id)
);
CREATE INDEX IF NOT EXISTS mx_track_subtopic_members_sub_idx ON mx_track_subtopic_members (subtopic_id);

CREATE TABLE IF NOT EXISTS mx_track_subtopic_asks (
  task_id      uuid PRIMARY KEY,
  track_id     uuid NOT NULL,
  kind         text NOT NULL CHECK (kind IN ('names', 'digest', 'place')),
  subtopic_ids uuid[] NOT NULL,
  post_ids     uuid[] NOT NULL DEFAULT '{}',
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mx_track_subtopic_asks_track_idx ON mx_track_subtopic_asks (track_id, kind, created_at DESC);

ALTER TABLE mx_tracks ADD COLUMN IF NOT EXISTS subtopics_hash text;

CREATE TABLE IF NOT EXISTS mx_track_seen (
  track_id    uuid NOT NULL,
  subtopic_id uuid,
  seen_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_track_seen_one_idx
  ON mx_track_seen (track_id, COALESCE(subtopic_id, '00000000-0000-0000-0000-000000000000'::uuid));

UPDATE mx_tasks SET status = 'failed' WHERE kind = 'subtopics' AND guide = 'subtopics-v1' AND status IN ('open', 'leased');
