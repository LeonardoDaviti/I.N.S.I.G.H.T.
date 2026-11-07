-- 0074_markx_perspectives.sql (issue 0119 B, Mark X v10.1.1: perspectives inside a story and the story sheet, in Shadow)
--
-- (0073 may be another branch's; nothing here depends on the number.)
--
-- 1. mx_perspectives: what one member of a Mark X story adds (0120 v3.2f): its label (original, new_facts, opinion,
--    same, not_this_story), who settled it (`by`: a code step, 'code:<rule>', or 'haiku'), Haiku's own label before the
--    final checks, its new facts (jsonb: [{fact, span, correction, about_story}]), its unconfirmed claims, its point
--    (an opinion's argument), whether it was published before the original, the copies folded into it (post ids,
--    never judged), how many facts the final checks dropped, and the call that answered it. member_hash: the story's
--    member set it was judged in. A change opens a new row and closes the old one (valid_to); nothing is deleted.
-- 2. mx_sheets: the story sheet (B4), one current row a story: jsonb (the original or source page, new facts merged with
--    their members, before the release, unconfirmed claims, opinions, related, "N more say the same"), the merge call
--    (null when there were fewer than two fact lines), the member set hash it was built for. Same rule: closed, never
--    deleted.
-- 3. mx_labels.item_kind may be 'perspective' (a = story, b = post) and 'fact' (a = story, b = post, note = the fact's
--    index and text): the owner's label buttons (B7).
--
-- Mark X tables only; no key leaves the mx_* tables (corrections 2). Idempotent.

CREATE TABLE IF NOT EXISTS mx_perspectives (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  story_id    uuid NOT NULL REFERENCES mx_stories(id),
  post_id     uuid NOT NULL,
  run_id      uuid REFERENCES mx_runs(id),
  member_hash text NOT NULL,
  label       text NOT NULL CHECK (label IN ('original', 'new_facts', 'opinion', 'same', 'not_this_story')),
  by          text NOT NULL,
  haiku_label text CHECK (haiku_label IS NULL OR haiku_label IN ('original', 'new_facts', 'opinion', 'same', 'not_this_story')),
  facts       jsonb NOT NULL DEFAULT '[]'::jsonb,
  claims      jsonb NOT NULL DEFAULT '[]'::jsonb,
  point       text,
  before      boolean NOT NULL DEFAULT false,
  copies      jsonb NOT NULL DEFAULT '[]'::jsonb,
  dropped     integer NOT NULL DEFAULT 0,
  call_id     uuid REFERENCES mx_calls(id),
  valid_from  timestamptz NOT NULL DEFAULT now(),
  valid_to    timestamptz,
  CONSTRAINT mx_perspectives_closes_after_it_opens CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_perspectives_current_idx ON mx_perspectives (story_id, post_id) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS mx_perspectives_post_idx ON mx_perspectives (post_id) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS mx_perspectives_history_idx ON mx_perspectives (story_id, post_id, valid_from);

CREATE TABLE IF NOT EXISTS mx_sheets (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  story_id    uuid NOT NULL REFERENCES mx_stories(id),
  run_id      uuid REFERENCES mx_runs(id),
  member_hash text NOT NULL,
  sheet       jsonb NOT NULL,
  call_id     uuid REFERENCES mx_calls(id),
  valid_from  timestamptz NOT NULL DEFAULT now(),
  valid_to    timestamptz,
  CONSTRAINT mx_sheets_closes_after_it_opens CHECK (valid_to IS NULL OR valid_to >= valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS mx_sheets_current_idx ON mx_sheets (story_id) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS mx_sheets_history_idx ON mx_sheets (story_id, valid_from);

ALTER TABLE mx_labels DROP CONSTRAINT IF EXISTS mx_labels_item_kind_check;
ALTER TABLE mx_labels ADD CONSTRAINT mx_labels_item_kind_check
  CHECK (item_kind IN ('join', 'check', 'merge', 'news_row', 'entity', 'connection', 'perspective', 'fact'));
