-- 0044_stories_as_trees.sql (issue 0064)
--
-- Stories as trees: each post of a story knows where it came from. Derived, computed by the story
-- job (0050) in the same pass that groups the posts.
--
-- story_posts:
--   parent_id: the post of the story it came from; NULL for the origin post, and for a post
--     whose parent is the story's outside page (stories.origin_url).
--   parent_reason: why, the most certain evidence first: address (the other posts at an address
--     hang from the post at it on its source's own site), citation (it links its parent), copy
--     (the same text or title, the earlier trustworthy time first), time (only as a tiebreaker:
--     both times trustworthy and 10+ minutes apart), none (it hangs from the origin with no
--     claim of order). NULL only for the origin post. Mark X adds meaning and attribution.
--   parent_url: the outside page it hangs from, when the story's origin is one.
--   So a post's parent is parent_id, else parent_url; with both NULL and no reason it is the origin.
--   reasons (why it joined) gains `address`: two posts at one address are one story.
-- stories: when the origin is a page outside INSIGHT that 2+ of the story's posts link (not as a
--   roundup's mentions), origin_url is its address, origin_title its most common titled link
--   words (0051's rule; NULL: show the address) and origin_linked_by how many posts link it. No
--   post is invented for it.
--
-- parent_id references story_posts and is checked at commit (the job may write a child before
-- its parent); a parent that leaves its story leaves its children hanging from the origin until
-- the next run.
--
-- The job's next run regroups every post (the `stories` setting is cleared), so every story,
-- frozen ones included, gets its tree. Idempotent.

ALTER TABLE story_posts ADD COLUMN IF NOT EXISTS parent_id uuid;
ALTER TABLE story_posts ADD COLUMN IF NOT EXISTS parent_reason text;
ALTER TABLE story_posts ADD COLUMN IF NOT EXISTS parent_url text;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'story_posts_parent_fkey') THEN
    ALTER TABLE story_posts ADD CONSTRAINT story_posts_parent_fkey FOREIGN KEY (parent_id)
      REFERENCES story_posts(post_id) ON DELETE SET NULL DEFERRABLE INITIALLY DEFERRED;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'story_posts_parent_reason_check') THEN
    ALTER TABLE story_posts ADD CONSTRAINT story_posts_parent_reason_check
      CHECK (parent_reason IS NULL OR parent_reason IN ('address', 'citation', 'copy', 'time', 'none'));
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS story_posts_parent_idx ON story_posts (parent_id) WHERE parent_id IS NOT NULL;

ALTER TABLE stories ADD COLUMN IF NOT EXISTS origin_url text;
ALTER TABLE stories ADD COLUMN IF NOT EXISTS origin_title text;
ALTER TABLE stories ADD COLUMN IF NOT EXISTS origin_linked_by integer;

-- Every story gets its tree on the job's next run: a full regroup.
DELETE FROM system_settings WHERE key = 'stories';
