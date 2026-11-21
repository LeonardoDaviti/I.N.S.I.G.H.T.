-- 0170_reader_look.sql (Stealth v10.32, issue 0271: since you looked)
--
-- mx_track_seen becomes the reader's looks: at a track (subtopic_id NULL), at one of its sub-topics, and the reader's
-- one look at everything (track_id NULL and subtopic_id NULL), set by opening "Since you looked". A track's look is
-- the later of its own and the reader's (track_subtopics.seen). One row more at most; nothing is moved or deleted.
-- Idempotent.

ALTER TABLE mx_track_seen ALTER COLUMN track_id DROP NOT NULL;
DROP INDEX IF EXISTS mx_track_seen_one_idx;
CREATE UNIQUE INDEX IF NOT EXISTS mx_track_seen_one_idx
  ON mx_track_seen (COALESCE(track_id, '00000000-0000-0000-0000-000000000000'::uuid),
                    COALESCE(subtopic_id, '00000000-0000-0000-0000-000000000000'::uuid));
