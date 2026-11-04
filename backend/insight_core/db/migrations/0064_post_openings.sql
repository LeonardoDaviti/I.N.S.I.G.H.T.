-- 0064_post_openings.sql (issue 0076: nothing the stored title said is lost)
--
-- post_parts.opening: what the post's stored title says when it says more than the title shown, without
-- Nitter's "RT by"/"R to" and the bridge's cut (a bridge's title is the post's first ~85 characters,
-- two lines glued: "Стрим про инференсВ среду в 18:00 …"; Nitter's the whole tweet), spaced as the text
-- is when it is the text's start. The story job joins copies of one post by it as by a title
-- (story_rules.StoryPost.title_keys). A new parser stamp: the next start parses every post again,
-- writing the rows that changed.

ALTER TABLE post_parts ADD COLUMN IF NOT EXISTS opening TEXT;
