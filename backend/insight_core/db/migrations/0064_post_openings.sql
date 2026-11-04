-- 0064_post_openings.sql (issue 0076: nothing the stored title said is lost)
--
-- post_parts.opening: the text's start as long as the post's stored title, when that title is the
-- text's start and says more than the title shown (a bridge's title is the post's first ~85 characters,
-- two lines glued: "Стрим про инференсВ среду в 18:00 …"). The story job joins copies of one post by it
-- as by a title (story_rules.StoryPost.title_keys). A new parser stamp: the next start parses every
-- post again, writing the rows that changed.

ALTER TABLE post_parts ADD COLUMN IF NOT EXISTS opening TEXT;
