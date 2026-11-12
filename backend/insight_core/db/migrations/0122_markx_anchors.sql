-- 0122_markx_anchors.sql (issue 0180, Stealth v10.16 slice J: anchors, 0166 step 3)
--
-- Back in the news (mx_back) and later developments (mx_later) attach a follow-up to an anchor: a Mark IX story, a
-- Mark X story or a happening (markx/anchors.py). Two engines write rows side by side while Shadow compares them:
--   engine       'old' (back.py / later.py's own triggers over Mark IX stories, as before) or 'anchors' (the anchors
--                engine: Pairing's `develops` relation, the anchor's happening first, its subject second);
--   anchor_kind  'ix_story' | 'mx_story' | 'happening';
--   anchor_id    the anchor's id (a Mark IX story, a Mark X story, or a happening's earliest post). NULL on the rows
--                written before this migration: they are read as anchor_kind 'ix_story', anchor_id = story.
-- Old rows are kept as they are (nothing is updated or deleted). The once-a-story constraints take the engine and the
-- anchor kind, so the two engines never collide on a row. Mark X tables only. Idempotent.

ALTER TABLE mx_back ADD COLUMN IF NOT EXISTS engine text NOT NULL DEFAULT 'old';
ALTER TABLE mx_back ADD COLUMN IF NOT EXISTS anchor_kind text NOT NULL DEFAULT 'ix_story';
ALTER TABLE mx_back ADD COLUMN IF NOT EXISTS anchor_id uuid;
ALTER TABLE mx_later ADD COLUMN IF NOT EXISTS engine text NOT NULL DEFAULT 'old';
ALTER TABLE mx_later ADD COLUMN IF NOT EXISTS anchor_kind text NOT NULL DEFAULT 'ix_story';
ALTER TABLE mx_later ADD COLUMN IF NOT EXISTS anchor_id uuid;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_back'::regclass AND conname = 'mx_back_engine_check') THEN
    ALTER TABLE mx_back ADD CONSTRAINT mx_back_engine_check CHECK (engine IN ('old', 'anchors'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_back'::regclass AND conname = 'mx_back_anchor_kind_check') THEN
    ALTER TABLE mx_back ADD CONSTRAINT mx_back_anchor_kind_check CHECK (anchor_kind IN ('ix_story', 'mx_story', 'happening'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_later'::regclass AND conname = 'mx_later_engine_check') THEN
    ALTER TABLE mx_later ADD CONSTRAINT mx_later_engine_check CHECK (engine IN ('old', 'anchors'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_later'::regclass AND conname = 'mx_later_anchor_kind_check') THEN
    ALTER TABLE mx_later ADD CONSTRAINT mx_later_anchor_kind_check CHECK (anchor_kind IN ('ix_story', 'mx_story', 'happening'));
  END IF;

  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_back'::regclass AND conname = 'mx_back_once') THEN
    ALTER TABLE mx_back DROP CONSTRAINT mx_back_once;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_back'::regclass AND conname = 'mx_back_once_an_engine') THEN
    ALTER TABLE mx_back ADD CONSTRAINT mx_back_once_an_engine UNIQUE (engine, anchor_kind, story, window_at);
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_later'::regclass AND conname = 'mx_later_once_a_rule') THEN
    ALTER TABLE mx_later DROP CONSTRAINT mx_later_once_a_rule;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'mx_later'::regclass AND conname = 'mx_later_once_an_engine') THEN
    ALTER TABLE mx_later ADD CONSTRAINT mx_later_once_an_engine UNIQUE (engine, anchor_kind, story, post, rule);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS mx_back_engine_story_idx ON mx_back (engine, anchor_kind, story);
CREATE INDEX IF NOT EXISTS mx_later_engine_post_idx ON mx_later (engine, post);
