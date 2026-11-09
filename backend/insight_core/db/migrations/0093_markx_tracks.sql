-- 0093_markx_tracks.sql (issue 0145, Stealth v10.11: tracks as topics)
--
-- 1. mx_tracks: a track's topic, keyed by its folder (no key to `folders`: Mark X never keys to a Mark IX table). A
--    folder with no row here, or a row whose description is null, stays a plain folder. `version` goes up when the
--    description or the excludes change (the history pass starts again for it, from `history_at`/`history_id`, a
--    keyset cursor, newest first; `history_done_at` when it reached the oldest post). `v` is the description's BGE-M3
--    vector (an `embed` task, subject 'track'), for the text whose sha256 is `v_hash`. `stats` keeps the planner's
--    last counts (scanned, passed, planned per origin). Kept, never deleted.
-- 2. mx_track_items: one row per track, post and version: the `track` task asking it, the origin it was planned under
--    (active: its source was in the folder; passive: the prefilter passed it, cosine `cos`), and the judge's verdict
--    once answered (in, confidence, subtopic, why). A rejected post keeps its row and verdict. Where it shows (the
--    track, Discover, joined by INSIGHT) is read from the labels and the precision when the page is built.
-- 3. mx_track_subtopics: the sub-topics INSIGHT proposed (a `subtopics` task) or the owner made; `keys` are the
--    judge's subtopic strings (folded) it collects. A replaced or merged one is closed with valid_to.
-- 4. mx_tasks.subject_kind may be 'track' (a description's vector, a sub-topic proposal: a = the folder) and
--    'post_track' (a track question: a = the post, b = the folder); mx_labels.item_kind may be 'track' (the owner's
--    in / out on a post for a track: a = the post, b = the folder).
--
-- Mark X tables only; no key to a Mark IX table; nothing is deleted. Idempotent. The CHECKs are rebuilt from the
-- values they allow now plus the new ones (0081's way), so values another branch's migration added stay.

CREATE TABLE IF NOT EXISTS mx_tracks (
  folder_id       uuid PRIMARY KEY,
  description     text,
  excludes        text,
  version         integer NOT NULL DEFAULT 1,
  version_at      timestamptz NOT NULL DEFAULT now(),
  v               halfvec(1024),
  v_hash          text,
  history_at      timestamptz,
  history_id      uuid,
  history_done_at timestamptz,
  stats           jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at      timestamptz NOT NULL DEFAULT now(),
  updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mx_track_items (
  track_id    uuid NOT NULL,
  post_id     uuid NOT NULL,
  version     integer NOT NULL,
  task_id     uuid NOT NULL,
  origin      text NOT NULL CHECK (origin IN ('active', 'passive')),
  cos         real,
  verdict     boolean,
  confidence  real,
  subtopic    text,
  why         text,
  call_id     uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  answered_at timestamptz,
  PRIMARY KEY (track_id, post_id, version)
);
CREATE INDEX IF NOT EXISTS mx_track_items_task_idx ON mx_track_items (task_id);
CREATE INDEX IF NOT EXISTS mx_track_items_post_idx ON mx_track_items (post_id);

CREATE TABLE IF NOT EXISTS mx_track_subtopics (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  track_id    uuid NOT NULL,
  name        text NOT NULL,
  definition  text,
  keys        text[] NOT NULL DEFAULT '{}',
  locked      boolean NOT NULL DEFAULT false,
  made_by     text NOT NULL DEFAULT 'insight' CHECK (made_by IN ('insight', 'owner')),
  task_id     uuid,
  merged_into uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  valid_to    timestamptz
);
CREATE INDEX IF NOT EXISTS mx_track_subtopics_track_idx ON mx_track_subtopics (track_id) WHERE valid_to IS NULL;

DO $$
DECLARE
  item record;
  def  text;
  vals text[];
BEGIN
  FOR item IN SELECT * FROM (VALUES ('mx_tasks', 'mx_tasks_subject_kind_check', 'subject_kind', 'track'),
                                    ('mx_tasks', 'mx_tasks_subject_kind_check', 'subject_kind', 'post_track'),
                                    ('mx_labels', 'mx_labels_item_kind_check', 'item_kind', 'track')) AS t(tbl, con, col, val)
  LOOP
    SELECT pg_get_constraintdef(c.oid) INTO def
      FROM pg_constraint c
     WHERE c.conrelid = item.tbl::regclass AND c.conname = item.con;
    IF def IS NULL OR position(quote_literal(item.val) IN def) > 0 THEN
      CONTINUE;
    END IF;
    SELECT array_agg(m[1] ORDER BY n) INTO vals
      FROM regexp_matches(def, '''([^'']+)''', 'g') WITH ORDINALITY AS t(m, n);
    vals := vals || ARRAY[item.val];
    EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', item.tbl, item.con);
    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK (%I IN (%s))', item.tbl, item.con, item.col,
                   (SELECT string_agg(quote_literal(v), ', ' ORDER BY n) FROM unnest(vals) WITH ORDINALITY AS u(v, n)));
  END LOOP;
END $$;
