-- 0039_post_links_and_stories.sql (issue 0050)
--
-- One story, many sources. Three derived tables, all recomputable from the posts:
--
-- post_links: the outside links inside each post (utils/post_links.py), filled when a post is
--   saved; the posts stored before are filled in the background by the story job, 500 posts a
--   transaction (posts.links_scanned_at IS NULL: not read yet). target_url is normalized as
--   posts.normalized_url is (0049), so a link to a stored post joins it on that column.
--   position 0 is the post's first outside link; link_text is the link's own words (the title of
--   a page that isn't stored). boilerplate: the link is its source's signature (in 25% of its
--   posts, 4 or more) or points at its source's own site; the story job sets it, and nothing
--   reads a boilerplate link.
-- stories: a group of posts from 2+ sources, keyed by its first post (a recount never reshuffles
--   it). voices: how many independent voices it has (0051 ranks by them).
-- story_posts: each post's story, its role (report: its own writing; share: a copy or a link
--   post), why it joined (text, title, link, citation; Mark X adds reasons) and its voice.
-- story_mentions: a roundup (3+ anchors) joins only the story of its first link and mentions the
--   others; 0051 counts mentions, nothing joins by them.
-- discover_hidden: Discover's suggestions you hid ("Not interested") and the sites of sources
--   you removed, never suggested again.
--
-- Idempotent.

ALTER TABLE posts ADD COLUMN IF NOT EXISTS links_scanned_at timestamptz;
CREATE INDEX IF NOT EXISTS posts_links_unscanned_idx ON posts (id) WHERE links_scanned_at IS NULL;

CREATE TABLE IF NOT EXISTS post_links (
  post_id     uuid NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  target_url  text NOT NULL,
  target_site text NOT NULL,
  position    integer NOT NULL,
  link_text   text,
  boilerplate boolean NOT NULL DEFAULT false,
  PRIMARY KEY (post_id, target_url)
);
CREATE INDEX IF NOT EXISTS post_links_target_idx ON post_links (target_url);

CREATE TABLE IF NOT EXISTS stories (
  id         uuid PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  first_at   timestamptz NOT NULL,
  voices     integer NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS stories_first_at_idx ON stories (first_at);

CREATE TABLE IF NOT EXISTS story_posts (
  post_id  uuid PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  story_id uuid NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  role     text NOT NULL CHECK (role IN ('report', 'share')),
  reasons  text[] NOT NULL DEFAULT '{}',
  voice    text NOT NULL
);
CREATE INDEX IF NOT EXISTS story_posts_story_idx ON story_posts (story_id);

CREATE TABLE IF NOT EXISTS story_mentions (
  story_id uuid NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  post_id  uuid NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  PRIMARY KEY (story_id, post_id)
);
CREATE INDEX IF NOT EXISTS story_mentions_post_idx ON story_mentions (post_id);

CREATE TABLE IF NOT EXISTS discover_hidden (
  key       text PRIMARY KEY,
  reason    text NOT NULL CHECK (reason IN ('not_interested', 'removed')),
  hidden_at timestamptz NOT NULL DEFAULT now()
);
