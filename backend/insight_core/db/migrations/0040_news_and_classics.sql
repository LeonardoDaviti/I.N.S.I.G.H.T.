-- 0040_news_and_classics.sql (issue 0051)
--
-- News and Classics, both derived by the story job (services/news_service.py) and recomputable;
-- only classic_hidden is yours.
--
-- news_stories: what several independent sources cover now. A News story is 0050's stories plus
--   the posts that share a surging name in their titles (utils/news_rules.py), for News only: a
--   name never folds rows in the Main feed. Keyed by its first post. score = reports + 1/2 shares
--   + 1/2 roundup mentions, each voice once, in its strongest role. The table holds the stories of
--   the job's window (the last 30 days; every post on a full run); News shows the last 7 days.
-- news_posts: each post's News story, its role there, its voice and the surging name that joined
--   it (null when it joined through 0050's story).
-- classics: a page linked by 2+ of your voices with links 30+ days apart (a stored post, or an
--   outside page), recomputed over every kept post link. citers: [{voice, name, source_id, at}],
--   each voice once at its first citation, in time order.
-- classic_hidden: Hide on a classic ("I know it" and "not for me"); a hidden classic never comes
--   back.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS news_stories (
  id         uuid PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  first_at   timestamptz NOT NULL,
  voices     integer NOT NULL,
  reports    integer NOT NULL,
  shares     integer NOT NULL,
  mentions   integer NOT NULL,
  score      numeric NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS news_stories_first_at_idx ON news_stories (first_at);

CREATE TABLE IF NOT EXISTS news_posts (
  post_id uuid PRIMARY KEY REFERENCES posts(id) ON DELETE CASCADE,
  news_id uuid NOT NULL REFERENCES news_stories(id) ON DELETE CASCADE,
  role    text NOT NULL CHECK (role IN ('report', 'share')),
  voice   text NOT NULL,
  name    text
);
CREATE INDEX IF NOT EXISTS news_posts_news_idx ON news_posts (news_id);

CREATE TABLE IF NOT EXISTS classics (
  target_url text PRIMARY KEY,
  post_id    uuid REFERENCES posts(id) ON DELETE SET NULL,
  voices     integer NOT NULL,
  first_at   timestamptz NOT NULL,
  last_at    timestamptz NOT NULL,
  title      text,
  citers     jsonb NOT NULL DEFAULT '[]'::jsonb,
  updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS classic_hidden (
  target_url text PRIMARY KEY,
  hidden_at  timestamptz NOT NULL DEFAULT now()
);
